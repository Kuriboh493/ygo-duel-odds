"""Learn deck archetypes for the extension from published Goat and Edison decklists.

Usage:
  python3 tools/train_decks.py                 # fetch what isn't cached, train, write extension/learned.js
  python3 tools/train_decks.py --refresh       # fetch the deck lists again (deck details stay cached)

Two sources, weighted differently:
  - Topping decks from Format Library: tournament results labeled with their deck type. These carry the
    most weight, more for higher placements and recent events, and set how common each archetype is.
  - Decks published on YGOPRODeck: unlabeled, weight 1. They fill in copy counts and casual archetypes.

The model is a semi-supervised latent class mixture. Each archetype gives every card a distribution
over 0 to 3 copies, which is the same shape the panel samples decks from. Every common Format Library
deck type is one archetype, fit only from the decks labeled with it. Unlabeled decks are shared out by
EM among those archetypes and a few free ones. The number of free archetypes is picked by held-out
likelihood. Free archetypes are named from the titles of the decks in them.

Fetching is slow on purpose (about one request a second), resumable, and cached under tools/.cache.
"""
import json, math, os, random, re, sys, time, urllib.parse, urllib.request
from collections import Counter
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", ".cache")
OUT = os.path.join(ROOT, "extension", "learned.js")
UA = {"User-Agent": "ygo-duel-odds deck trainer (personal project)"}

FORMATS = {
    # cutoff: latest TCG release date allowed in the card pool, used to drop invalid YGOPRODeck decks.
    "goat": {"ygopd": "goat format decks", "fl": "Goat", "cutoff": "2005-09-30", "banlist": "ban_goat"},
    "edison": {"ygopd": "edison format decks", "fl": "Edison", "cutoff": "2010-07-31", "banlist": None},
}
LIMITS = {"Forbidden": 0, "Limited": 1, "Semi-Limited": 2}
TOP_WEIGHT = 4.0       # one topping deck counts this many published decks when fitting copy counts
TOP_PRIOR = 0.8        # share of each archetype's starting weight that comes from topping decks
HALF_LIFE = 2.0        # years; older events count for less, since the meta moves
MIN_TYPE = 8           # a deck type needs this many topping decks to be its own archetype
FREE_RANGE = (0, 1, 2, 3, 4, 6, 8)
SMOOTH = 3.0           # Dirichlet pseudo-count, spread like the format-wide copy counts
MIN_DECKS = 3          # cards in fewer decks than this are left to the panel's "tech card" allowance

def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()

def load(name, default=None):
    path = os.path.join(CACHE, name)
    if not os.path.exists(path): return default
    with open(path, encoding="utf-8") as f: return json.load(f)

def store(name, data):
    os.makedirs(CACHE, exist_ok=True)
    tmp = os.path.join(CACHE, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f: json.dump(data, f)
    os.replace(tmp, os.path.join(CACHE, name))

# ---------- Fetching ----------
def fetch_cards():
    cards = load("cardinfo_misc.json")
    if cards is None:
        print("Fetching the card database...")
        cards = json.loads(get("https://db.ygoprodeck.com/api/v7/cardinfo.php?misc=yes"))["data"]
        store("cardinfo_misc.json", cards)
    return cards

def fetch_ygopd(fmt, refresh):
    name = f"decks_{fmt}.json"
    decks = None if refresh else load(name)
    if decks is not None: return decks
    decks, offset = [], 0
    while True:
        url = "https://ygoprodeck.com/api/decks/getDecks.php?" + urllib.parse.urlencode({"format": FORMATS[fmt]["ygopd"], "limit": 20, "offset": offset})
        try: page = json.loads(get(url))
        except (ValueError, OSError): page = []
        if not isinstance(page, list) or not page: break
        decks += page; offset += len(page)
        print(f"  YGOPRODeck {fmt}: {len(decks)} decks", end="\r", flush=True)
        time.sleep(1)
    print()
    store(name, decks)
    return decks

def fetch_fl(fmt, refresh):
    """Format Library topping decks. The list is cheap; each deck's cards need one request, cached as they come."""
    lname, dname = f"fl_list_{fmt}.json", f"fl_decks_{fmt}.json"
    lst = None if refresh else load(lname)
    if lst is None:
        lst, page = [], 1
        while True:
            q = urllib.parse.urlencode({"page": page, "limit": 100, "sort": "publishDate:desc", "filter": f"format:eq:{FORMATS[fmt]['fl']},origin:eq:event"})
            try: rows = json.loads(get("https://formatlibrary.com/api/decks?" + q))
            except (ValueError, OSError): rows = []
            if not isinstance(rows, list) or not rows: break
            lst += rows; page += 1
            print(f"  Format Library {fmt}: {len(lst)} topping decks listed", end="\r", flush=True)
            time.sleep(1)
        print()
        store(lname, lst)
    got = load(dname, {})
    todo = [r["id"] for r in lst if str(r["id"]) not in got]
    if todo: print(f"  Format Library {fmt}: fetching {len(todo)} decklists (about {len(todo)//60 + 1} min). Safe to stop and rerun.")
    for n, i in enumerate(todo, 1):
        try:
            d = json.loads(get(f"https://formatlibrary.com/api/decks/{i}"))
            got[str(i)] = {"main": [c.get("artworkId") or "" for c in d.get("main") or []],
                           "names": [c.get("name") or "" for c in d.get("main") or []]}
        except (ValueError, OSError) as e:
            print(f"\n  deck {i} failed ({e}); it will be retried next run")
        if n % 25 == 0 or n == len(todo):
            store(dname, got); print(f"  {n}/{len(todo)}", end="\r", flush=True)
        time.sleep(1)
    if todo: print()
    return lst, got

# ---------- Cleaning ----------
def card_index(cards):
    by_id, by_name, info = {}, {}, {}
    for c in cards:
        if "Monster" in c["type"] and any(x in c["type"] for x in ("Fusion", "Synchro", "XYZ", "Link")): continue
        misc = (c.get("misc_info") or [{}])[0]
        info[c["name"]] = {"date": misc.get("tcg_date") or misc.get("ocg_date"), "ban": c.get("banlist_info") or {}}
        for img in c.get("card_images", []): by_id[int(img["id"])] = c["name"]
        by_id[int(c["id"])] = c["name"]
        by_name[re.sub(r"[^a-z0-9]", "", c["name"].lower())] = c["name"]
    return by_id, by_name, info

def years_ago(iso):
    try: t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError): return 5.0
    return max(0.0, (datetime.now(timezone.utc) - t).days / 365.25)

def clean(fmt, ygopd, fl_list, fl_decks, by_id, by_name, info):
    cfg, decks, seen, why = FORMATS[fmt], [], set(), Counter()
    def admit(names, check_era, dedupe=True):
        if not names or None in names: why["unknown or Extra Deck card"] += 1; return None
        if not 40 <= len(names) <= 60: why["not 40-60 cards"] += 1; return None
        counts = Counter(names)
        if max(counts.values()) > 3: why["more than 3 copies"] += 1; return None
        if check_era and any((info[n]["date"] or "0") > cfg["cutoff"] for n in counts): why["card from after the format"] += 1; return None
        if check_era and cfg["banlist"] and any(counts[n] > LIMITS.get(info[n]["ban"].get(cfg["banlist"]), 3) for n in counts): why["breaks the banlist"] += 1; return None
        key = tuple(sorted(counts.items()))
        if dedupe and key in seen: why["duplicate"] += 1; return None
        seen.add(key)
        return dict(counts)
    # Topping decks go first. The same list topping again is a separate result and is kept;
    # only published copies of lists already seen are dropped. Topping decks were legal at their event,
    # so only the shape checks apply.
    for r in fl_list:
        d = fl_decks.get(str(r["id"]))
        if not d: why["topping deck not fetched yet"] += 1; continue
        names = []
        for pid, nm in zip(d["main"], d["names"]):
            n = by_id.get(int(pid)) if str(pid).isdigit() else None
            names.append(n or by_name.get(re.sub(r"[^a-z0-9]", "", nm.lower())))
        counts = admit(names, False, dedupe=False)
        if counts is None: continue
        place = r.get("placement") or 99
        boost = 1.5 if place == 1 else 1.25 if place <= 4 else 1.1 if place <= 8 else 1.0
        w = TOP_WEIGHT * boost * 0.5 ** (years_ago(r.get("publishDate")) / HALF_LIFE)
        decks.append({"counts": counts, "title": "", "type": re.sub(r"\s+", " ", (r.get("deckTypeName") or "").strip()), "w": w, "top": True})
    for d in ygopd:
        try: ids = [int(x) for x in json.loads(d.get("main_deck") or "[]")]
        except (ValueError, TypeError): why["unreadable"] += 1; continue
        counts = admit([by_id.get(i) for i in ids], True)
        if counts is None: continue
        decks.append({"counts": counts, "title": d.get("deck_name") or "", "type": None, "w": 1.0, "top": False})
    return decks, why

# ---------- Semi-supervised latent class model ----------
# Deck likelihood under archetype k is a product over the vocabulary of p_k(card, copies), computed as
# the sum of log p_k(v, 0) over every card plus a correction for the few cards the deck actually runs.
class Model:
    def __init__(self, V, decks):
        self.V = V; vi = {v: i for i, v in enumerate(V)}
        self.X = [[(vi[n], min(3, c)) for n, c in d["counts"].items() if n in vi] for d in decks]
        self.W = [d["w"] for d in decks]
        tot = sum(self.W); marg = [[0.0] * 4 for _ in V]
        for x, w in zip(self.X, self.W):
            for v, j in x: marg[v][j] += w
        for v in range(len(V)):
            marg[v][0] = tot - sum(marg[v][1:])
            marg[v] = [(m + 0.25) / (tot + 1) for m in marg[v]]
        self.marg = marg

    def mstep(self, R, K):
        V, X, W = self.V, self.X, self.W
        Nk = [sum(R[i][k] * W[i] for i in range(len(X))) for k in range(K)]
        P = []
        for k in range(K):
            cnt = [[0.0] * 4 for _ in V]
            for i, x in enumerate(X):
                r = R[i][k] * W[i]
                if r:
                    for v, j in x: cnt[v][j] += r
            z = Nk[k] + SMOOTH
            P.append([[(((Nk[k] - sum(c[1:])) if j == 0 else c[j]) + SMOOTH * self.marg[v][j]) / z for j in range(4)] for v, c in enumerate(cnt)])
        pi = [(n + 0.5) / (sum(Nk) + 0.5 * K) for n in Nk]
        return P, pi

    @staticmethod
    def scores(P, pi, X):
        L = [[math.log(max(p[0], 1e-12)) for p in pk] for pk in P]; base = [sum(l) for l in L]
        lp = [math.log(p) for p in pi]
        return [[lp[k] + base[k] + sum(math.log(P[k][v][j]) - L[k][v] for v, j in x) for k in range(len(P))] for x in X]

    def fit(self, labels, nlab, nfree, seed, iters):
        """labels[i] is the archetype of a labeled deck, or None. Archetypes from nlab on are free."""
        rnd, X, K = random.Random(seed), self.X, nlab + nfree
        unl = [i for i, l in enumerate(labels) if l is None]
        sets = [dict(x) for x in X]
        dist = lambda a, b: sum(abs(sets[a].get(v, 0) - sets[b].get(v, 0)) for v in sets[a].keys() | sets[b].keys())
        seeds = []
        if nfree and unl:
            seeds = [rnd.choice(unl)]
            sample = rnd.sample(unl, min(len(unl), 600))
            while len(seeds) < nfree:
                d2 = [min(dist(i, s) for s in seeds) ** 2 for i in sample]
                r, acc = rnd.random() * sum(d2), 0
                for i, v in zip(sample, d2):
                    acc += v
                    if acc >= r: seeds.append(i); break
        R = []
        for i, l in enumerate(labels):
            row = [0.0] * K
            if l is not None: row[l] = 1.0
            elif nfree: row[nlab + min(range(nfree), key=lambda f: dist(i, seeds[f]))] = 1.0
            else: row = [1.0 / K] * K
            R.append(row)
        ll = 0.0
        for it in range(iters):
            P, pi = self.mstep(R, K)
            ll = 0.0
            for i, s in zip(unl, self.scores(P, pi, [X[i] for i in unl])):
                m = max(s); e = [math.exp(a - m) for a in s]; z = sum(e)
                R[i] = [a / z for a in e]; ll += self.W[i] * (m + math.log(z))
        P, pi = self.mstep(R, K)
        return {"P": P, "pi": pi, "R": R, "ll": ll}

def heldout(model, X):
    total = 0.0
    for s in Model.scores(model["P"], model["pi"], X):
        m = max(s); total += m + math.log(sum(math.exp(a - m) for a in s))
    return total / max(1, len(X))

STOP = {"goat", "goats", "format", "edison", "deck", "decks", "the", "a", "of", "and", "my", "v", "vs", "with", "build", "list", "new", "test", "version", "ver", "ygo", "yugioh", "2005", "2010", "tcg", "best", "update", "updated", "budget", "casual", "fun"}
def title_name(decks, R, k):
    uni, bi = Counter(), Counter()
    for d, r in zip(decks, R):
        if r[k] < 0.05 or not d["title"]: continue
        toks = [t for t in re.findall(r"[a-z]+", d["title"].lower()) if t not in STOP and len(t) > 1]
        for t in set(toks): uni[t] += r[k]
        for b in set(zip(toks, toks[1:])): bi[b] += r[k]
    mass = sum(r[k] for r in R) or 1
    # A two-word title ("Blue Eyes") beats its own words when it's nearly as common as the top word.
    if bi and (bi.most_common(1)[0][1] / mass >= 0.12 or (uni and bi.most_common(1)[0][1] >= 0.6 * uni.most_common(1)[0][1])):
        return " ".join(bi.most_common(1)[0][0]).title()
    return uni.most_common(1)[0][0].title() if uni else "Other"

def train(fmt, refresh):
    by_id, by_name, info = card_index(fetch_cards())
    ygopd = fetch_ygopd(fmt, refresh)
    fl_list, fl_decks = fetch_fl(fmt, refresh)
    decks, why = clean(fmt, ygopd, fl_list, fl_decks, by_id, by_name, info)
    ntop = sum(d["top"] for d in decks)
    print(f"{fmt}: kept {ntop} topping and {len(decks) - ntop} published decks. Dropped: " + ", ".join(f"{v} {k}" for k, v in why.most_common()))

    tcount = Counter(d["type"] for d in decks if d["top"])
    types = [t for t, n in tcount.most_common() if n >= MIN_TYPE and t]
    ti = {t: i for i, t in enumerate(types)}
    labels = [ti.get(d["type"]) if d["top"] else None for d in decks]
    df = Counter(n for d in decks for n in d["counts"])
    V = sorted(n for n, c in df.items() if c >= MIN_DECKS)

    # Pick the number of free archetypes on held-out decks, scored without their labels.
    rnd = random.Random(7); idx = list(range(len(decks))); rnd.shuffle(idx)
    test = set(idx[:len(idx) // 5])
    trm = Model(V, [d for i, d in enumerate(decks) if i not in test])
    trl = [l for i, l in enumerate(labels) if i not in test]
    full = Model(V, decks)
    teX = [x for i, x in enumerate(full.X) if i in test]
    scores = {}
    for nf in FREE_RANGE:
        if len(types) + nf == 0: continue
        scores[nf] = heldout(trm.fit(trl, len(types), nf, 1, 25), teX)
        print(f"  {len(types)} deck types + {nf} free archetypes: held-out log-likelihood per deck {scores[nf]:9.2f}")
    # The most free archetypes that predict unseen decks about as well as the best count.
    best = max(scores.values())
    nfree = max(nf for nf, h in scores.items() if h >= best - 1.0)

    fit = max((full.fit(labels, len(types), nfree, s, 50) for s in (1, 2)), key=lambda m: m["ll"])
    K = len(types) + nfree
    names = types + [title_name(decks, fit["R"], k) for k in range(len(types), K)]
    names = [n if k < len(types) or n not in types else f"{n} (casual)" for k, n in enumerate(names)]
    # How common each archetype is, weighted by the decks in it, so topping lists dominate.
    share = [sum(r[k] * d["w"] for r, d in zip(fit["R"], decks)) for k in range(K)]
    topshare = [sum(r[k] * d["w"] for r, d in zip(fit["R"], decks) if d["top"]) for k in range(K)]
    pubshare = [a - b for a, b in zip(share, topshare)]
    TS, PS = sum(topshare), sum(pubshare)
    # The starting weight leans on what tops events, with the published decks as a smaller part.
    a = TOP_PRIOR if TS and PS else (1.0 if TS else 0.0)
    share = [a * (t / TS if TS else 0) + (1 - a) * (p / PS if PS else 0) for t, p in zip(topshare, pubshare)]
    S, TS = sum(share), TS or 1
    P = fit["P"]
    avg = [sum(sum(P[q][v][j] * j for j in range(4)) for q in range(K)) / K for v in range(len(V))]
    comps = []
    sigs = []
    for k in range(K):
        mean = [sum(P[k][v][j] * j for j in range(4)) for v in range(len(V))]
        sigs.append([V[v] for v in sorted(range(len(V)), key=lambda v: -(mean[v] - avg[v]))[:4]])
    # Free archetypes that end up with the same title are told apart by their signature card.
    taken = Counter(names)
    names = [n if taken[n] == 1 or k < len(types) else f"{n} ({sigs[k][0]})" for k, n in enumerate(names)]
    for k in sorted(range(K), key=lambda k: -share[k]):
        if share[k] / S < 0.003: continue
        sig = sigs[k]
        copies = {V[v]: [round(p, 4) for p in P[k][v]] for v in range(len(V)) if P[k][v][0] < 0.995}
        comps.append({"name": names[k], "weight": round(share[k] / S, 4), "topShare": round(topshare[k] / TS, 4),
                      "decks": round(sum(r[k] for r in fit["R"]), 1), "from": "topping" if k < len(types) else "published",
                      "signature": sig, "copies": copies})
    marg = {V[v]: [round(p, 4) for p in full.marg[v]] for v in range(len(V))}
    print(f"  {K} archetypes: " + ", ".join(f"{c['name']} {c['weight']*100:.0f}%" for c in comps))
    return {"decks": len(decks), "topping": ntop, "components": comps, "marginal": marg}

def main():
    refresh = "--refresh" in sys.argv
    out = {"trained": time.strftime("%Y-%m-%d"), "source": "Format Library topping decks and YGOPRODeck published decks"}
    for fmt in FORMATS: out[fmt] = train(fmt, refresh)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("// Generated by tools/train_decks.py from Format Library topping decks and YGOPRODeck published decks. Do not edit by hand.\n")
        f.write("// Per format: archetypes with their share of play and a 0-3 copy distribution per card.\n")
        f.write("window.LEARNED = " + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"Wrote {OUT} ({os.path.getsize(OUT)//1024} KB)")

if __name__ == "__main__":
    main()
