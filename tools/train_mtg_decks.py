"""Learn deck archetypes for mtga/mtg-decks.js from tournament decklists on MTGTop8.

Usage:
  python3 tools/train_mtg_decks.py                  # up to 200 recent decks per format, 1 request a second
  python3 tools/train_mtg_decks.py --decks 300

Run tools/build_mtg_cards.py first: decks are checked against the Arena card pool. Needs no extra packages.
Everything downloaded is cached in tools/.cache/mtg, so it can be stopped and rerun. Metagames move quickly,
so rerun this every few weeks. Most of these decks come from Magic Online and paper events, not the Arena ladder.
A format with too few decks from the last six months gets no archetypes, because an old metagame would mislead.
"""
import argparse, datetime, json, os, re, time, urllib.error, urllib.request
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", ".cache", "mtg")
SITE = "https://www.mtgtop8.com/"
UA = {"User-Agent": "mtga-odds-trainer/0.1"}
FORMATS = {"standard": "ST", "explorer": "EXP", "historic": "HI", "alchemy": "ALCH"}
BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes", "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp", "Snow-Covered Mountain", "Snow-Covered Forest"}
MIN_DECKS = 3       # fewer decks than this go into the "Other decks" pool
SMOOTH = 1.0        # pull of an archetype's copy counts toward the format's, in decks
MAX_UNKNOWN = 0.1   # a deck with more non-Arena cards than this isn't an Arena deck
MAX_AGE_DAYS = 183  # events older than this describe a different metagame
MIN_DECKS_FORMAT = 30
SHOWN = 0.015       # a card an archetype runs less often than this is left to the unlisted-card allowance
last = 0.0


def fetch(url, cache_as=None):
    global last
    path = os.path.join(CACHE, cache_as) if cache_as else None
    if path and os.path.exists(path):
        return open(path, encoding="utf-8", errors="replace").read()
    time.sleep(max(0, 1.1 - (time.time() - last)))
    last = time.time()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        raw = r.read()
    # Some of the site's pages are Latin-1, which matters for names like "Dáin's Company".
    try: body = raw.decode("utf-8")
    except UnicodeDecodeError: body = raw.decode("latin-1")
    if path:
        with open(path, "w", encoding="utf-8") as f: f.write(body)
    return body


def load_pool():
    src = open(os.path.join(ROOT, "mtga", "mtg-cards.js"), encoding="utf-8").read()
    data = json.loads(src[src.index("window.MTG_CARD_DATA = ") + 23:].rstrip().rstrip(";"))
    pool = {}
    for line in data.split("\n"):
        name = line.split("\t")[0]
        pool[name.lower()] = name
        if " // " in name: pool[name.split(" // ")[0].lower()] = name
    return pool


def parse_date(text):
    return datetime.datetime.strptime(text, "%d/%m/%y").date()


def recent_events(code):
    """Events from the last six months, newest first, as (event id, date). The lists themselves are never cached."""
    cutoff = datetime.date.today() - datetime.timedelta(days=MAX_AGE_DAYS)
    seen = {}
    for page in range(1, 40):
        html = fetch(f"{SITE}format?f={code}&cp={page}")
        rows = re.findall(r"event\?e=(\d+)&f=" + code + r">.*?class=S12>(\d\d/\d\d/\d\d)<", html, re.S)
        fresh = [r for r in rows if r[0] not in seen and parse_date(r[1]) >= cutoff]
        if not fresh: break
        seen.update(fresh)
    return list(seen.items())


def deck_links(code, event):
    """Deck id -> archetype name, for every deck on an event's page."""
    html = fetch(f"{SITE}event?e={event}&f={code}", f"event-{event}.html")
    return {d: name.strip() for d, name in re.findall(r"\?e=" + event + r"&d=(\d+)&f=" + code + r">([^<]+)</a>", html) if name.strip()}


def parse_deck(text, pool):
    main, unknown, total = {}, 0, 0
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("sideboard"): break
        m = re.match(r"(\d+)\s+(.+)", line)
        if not m: continue
        n, name = int(m.group(1)), m.group(2).strip()
        total += n
        card = pool.get(name.lower()) or pool.get(name.lower().split(" / ")[0])
        if not card:
            unknown += n
            continue
        main[card] = main.get(card, 0) + n
    return main, total, unknown


def collect(fmt, code, want, pool):
    decks, dropped, dates = [], 0, []
    for event, date in recent_events(code):
        try: links = deck_links(code, event)
        except urllib.error.URLError as e:
            print(f"  skipped event {event}: {e}")
            continue
        got = 0
        for d, label in links.items():
            if len(decks) >= want: break
            try: text = fetch(f"{SITE}mtgo?d={d}", f"deck-{d}.txt")
            except urllib.error.URLError as e:
                print(f"  skipped deck {d}: {e}")
                continue
            main, total, unknown = parse_deck(text, pool)
            if total < 60 or unknown > MAX_UNKNOWN * total:
                dropped += 1
                continue
            decks.append((label, main))
            got += 1
        if got: dates.append(date)
        print(f"  {fmt}: {len(decks)}/{want} decks", flush=True)
        if len(decks) >= want: break
    return decks, dropped, dates


def copies_table(decks, marginal=None):
    """Card -> chance of running 0, 1, 2, 3 or 4 copies, among these decks."""
    counts, n = defaultdict(lambda: [0] * 5), len(decks)
    for main in decks:
        for card, k in main.items():
            if card not in BASICS: counts[card][min(4, k)] += 1
    out = {}
    for card, c in counts.items():
        c = list(c)
        c[0] = n - sum(c[1:])
        if marginal and card in marginal: p = [(c[j] + SMOOTH * marginal[card][j]) / (n + SMOOTH) for j in range(5)]
        else: p = [(c[j] + (SMOOTH if j == 0 else 0)) / (n + SMOOTH) for j in range(5)]
        out[card] = [round(x, 4) for x in p]
    return out


def component(name, decks, weight, marginal):
    copies = copies_table(decks, marginal)
    basics = defaultdict(float)
    for main in decks:
        for card, k in main.items():
            if card in BASICS: basics[card] += k / len(decks)
    avg = Counter()
    for main in decks:
        for card, k in main.items():
            if card not in BASICS: avg[card] += k
    lands = sum(basics.values())
    return {
        "name": name, "decks": len(decks), "weight": round(weight, 4),
        "signature": [c for c, _ in avg.most_common(4)],
        "copies": {c: p for c, p in copies.items() if 1 - p[0] >= SHOWN},
        "basics": {c: round(v, 2) for c, v in basics.items()},
    }


def learn(decks):
    mains = [m for _, m in decks]
    marginal = copies_table(mains)
    groups = defaultdict(list)
    for name, main in decks: groups[name].append(main)
    comps, other = [], []
    for name, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(members) >= MIN_DECKS: comps.append(component(name, members, len(members) / len(mains), marginal))
        else: other.extend(members)
    if other: comps.append(component("Other decks", other, len(other) / len(mains), marginal))
    return {"decks": len(mains), "components": comps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--decks", type=int, default=200)
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    pool = load_pool()
    out = {}
    for fmt, code in FORMATS.items():
        print(fmt, flush=True)
        decks, dropped, dates = collect(fmt, code, args.decks, pool)
        if len(decks) < MIN_DECKS_FORMAT:
            print(f"  only {len(decks)} usable recent decks, so {fmt} gets no archetypes")
            continue
        out[fmt] = learn(decks)
        out[fmt]["newest"], out[fmt]["oldest"] = dates[0], dates[-1]
        print(f"  {len(decks)} decks ({dropped} dropped), {len(out[fmt]['components'])} archetypes, {dates[-1]} to {dates[0]}")
    dst = os.path.join(ROOT, "mtga", "mtg-decks.js")
    with open(dst, "w", encoding="utf-8") as f:
        f.write("// Generated by tools/train_mtg_decks.py from tournament decklists on MTGTop8. Do not edit by hand.\n")
        f.write("window.MTG_DECKS = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("Wrote", dst)


if __name__ == "__main__":
    main()
