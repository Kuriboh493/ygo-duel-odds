"""Train the auto-play model from decisions recorded by the extension.

Usage:
  python3 tools/train_policy.py ygo-training-data.json [more.json ...] [-o policy.json] [--epochs 30]

Record decisions first: in the panel's Auto tab, turn on "Record my plays for training", play some duels,
then press "Download training data". Load the policy.json this writes with "Load a trained model".

The model is a linear softmax ranker. At each decision point you had some candidate plays (everything on
your cards' menus, the deck menu, phases and End turn). Each candidate gets features (see featurize below),
the model scores each one as the sum of its feature weights, and training raises the score of the play you
actually made relative to the others. It's trained with AdaGrad and L2 regularization, and scored on duels
it never saw, against two baselines: picking at random, and picking the most common kind of play.

No extra packages are needed.
"""
import argparse, json, math, random, sys, time
from collections import Counter, defaultdict

FEATURES_VERSION = 4

# ---------- Features: a line-for-line copy of extension/features.js ----------
def f_num(x):
    if x is None or x == "" or isinstance(x, bool):
        return None if x is None or x == "" else int(x)
    try:
        n = float(x)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return int(n) if n.is_integer() else n

def f_bucket(x, edges):
    if x is None:
        return "na"
    b = 0
    for i, e in enumerate(edges):
        if x >= e:
            b = i
    return str(edges[b])

def f_battle(card, target):
    if not target:
        return "none"
    if target.get("pos") == "FD":
        return "unknown"
    a = f_num((card or {}).get("atk"))
    d = f_num(target.get("def") if target.get("pos") == "DEF" else target.get("atk"))
    if a is None or d is None:
        return "unknown"
    return "win" if a > d else "tie" if a == d else "lose"

def f_level(card):
    l = f_num((card or {}).get("level"))
    if l is None or l == 0:
        return "na"
    return "low" if l <= 4 else "mid" if l <= 6 else "high"

def featurize(rec, cand):
    p = "p:" + cand["play"]
    c = cand.get("card") or {}
    me = rec.get("me") or {}
    opp = rec.get("opp") or {}
    ph = rec.get("phase") or "none"
    ost = min(len(opp.get("st") or []), 3)
    out = [
        p,
        p + "|z:" + (c.get("zone") or "none"),
        p + "|ct:" + (c.get("ctype") or "none"),
        p + "|ph:" + ph,
        p + "|my:" + ("1" if rec.get("myTurn") else "0"),
        p + "|ns:" + str(min(f_num(rec.get("summonsThisTurn")) or 0, 2)),
        p + "|k:" + f_bucket(f_num(rec.get("playsThisTurn")) or 0, [0, 1, 3, 6, 10]),
        p + "|h:" + f_bucket(len(me.get("hand") or []), [0, 1, 3, 5, 7]),
        p + "|mm:" + str(min(len(me.get("mon") or []), 3)),
        p + "|om:" + str(min(len(opp.get("mon") or []), 3)),
        p + "|ost:" + str(ost),
        p + "|oh:" + f_bucket(f_num(opp.get("hand")) or 0, [0, 1, 3, 5]),
        p + "|olp:" + f_bucket(f_num(opp.get("lp")), [0, 1000, 2000, 4000, 8000]),
        p + "|mlp:" + f_bucket(f_num(me.get("lp")), [0, 1000, 2000, 4000, 8000]),
        p + "|lv:" + f_level(c),
    ]
    last = rec.get("lastPlay") or "none"
    out.append(p + "|last:" + last)
    if rec.get("lastCard"):
        out.append(p + "|last:" + last + "|ln:" + rec["lastCard"])
    out.append(p + "|dr:" + str(min(f_num(rec.get("drawsThisTurn")) or 0, 5)))
    out.append(p + "|dc:" + str(min(f_num(rec.get("discardsThisTurn")) or 0, 3)))
    for h in rec.get("turnHistory") or []:
        out.append(p + "|did:" + h)
    myst = len([x for x in (me.get("st") or []) if x and x.get("pos") == "FD"])
    ostn = len(opp.get("st") or [])
    out.append(p + "|stc:" + ("more" if ostn > myst else "same" if ostn == myst else "fewer"))
    if c.get("ctype") == "Monster":
        ups = [v for v in (f_num(x.get("atk")) for x in (opp.get("mon") or []) if x and x.get("pos") != "FD") if v is not None]
        a = f_num(c.get("atk"))
        out.append(p + "|vs:" + ("na" if a is None else "empty" if not ups else "win" if a > max(ups) else "lose"))
    ofd = min(len([x for x in (opp.get("mon") or []) if x and x.get("pos") == "FD"]), 2)
    gyld = ("L" if (f_num(me.get("gyLight")) or 0) > 0 else "-") + ("D" if (f_num(me.get("gyDark")) or 0) > 0 else "-")
    out.append(p + "|ofd:" + str(ofd))
    if c.get("name"):
        n = p + "|n:" + c["name"]
        out.append(n)
        out.append(n + "|ph:" + ph)
        out.append(n + "|om:" + str(min(len(opp.get("mon") or []), 3)))
        out.append(n + "|ofd:" + str(ofd))
        out.append(n + "|ost:" + str(ost))
        out.append(n + "|oh:" + f_bucket(f_num(opp.get("hand")) or 0, [0, 1, 3, 5]))
        out.append(n + "|gy:" + gyld)
    t = cand.get("target")
    if t:
        b = f_battle(c, t)
        out.append(p + "|bt:" + b)
        out.append(p + "|bt:" + b + "|ost:" + str(ost))
        if t.get("name"):
            out.append(p + "|tn:" + t["name"])
    return out

# ---------- Data ----------
def load(paths):
    recs = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        rows = d["records"] if isinstance(d, dict) else d
        for r in rows:
            if isinstance(r, dict) and r.get("cands") and isinstance(r.get("chosen"), int) and 0 <= r["chosen"] < len(r["cands"]):
                recs.append(r)
    return recs

def split_by_duel(recs, share, seed):
    duels = sorted({r.get("duel") or "?" for r in recs})
    random.Random(seed).shuffle(duels)
    k = max(1, int(len(duels) * share)) if len(duels) > 1 else 0
    held = set(duels[:k])
    return [r for r in recs if (r.get("duel") or "?") not in held], [r for r in recs if (r.get("duel") or "?") in held]

# ---------- Model ----------
def scores(w, feats):
    return [sum(w.get(f, 0.0) for f in fs) for fs in feats]

def softmax(xs):
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    z = sum(e)
    return [v / z for v in e]

def evaluate(w, data):
    if not data:
        return {"n": 0}
    top1 = top3 = 0
    ll = 0.0
    for feats, y in data:
        s = scores(w, feats)
        order = sorted(range(len(s)), key=lambda i: -s[i])
        top1 += order[0] == y
        top3 += y in order[:3]
        ll += math.log(max(softmax(s)[y], 1e-12))
    n = len(data)
    return {"n": n, "top1": top1 / n, "top3": top3 / n, "loglik": ll / n}

def train(data, dev, epochs, lr, l2, seed):
    w = defaultdict(float)
    g2 = defaultdict(float)
    rnd = random.Random(seed)
    best, best_w, since = None, None, 0
    order = list(range(len(data)))
    for ep in range(1, epochs + 1):
        rnd.shuffle(order)
        for i in order:
            feats, y = data[i]
            p = softmax(scores(w, feats))
            grad = defaultdict(float)
            for j, fs in enumerate(feats):
                g = p[j] - (1.0 if j == y else 0.0)
                if g:
                    for f in fs:
                        grad[f] += g
            for f, g in grad.items():
                g += l2 * w[f]
                g2[f] += g * g
                w[f] -= lr * g / (math.sqrt(g2[f]) + 1e-8)
        m = evaluate(w, dev) if dev else evaluate(w, data)
        print(f"  epoch {ep:3d}: {'held-out' if dev else 'training'} top-1 {m['top1']:.3f}, log-likelihood {m['loglik']:.3f}")
        if best is None or m["loglik"] > best + 1e-4:
            best, best_w, since = m["loglik"], dict(w), 0
        else:
            since += 1
            if since >= 4:
                print("  stopping early: no improvement for 4 epochs")
                break
    return best_w

def baselines(train_data, test_recs):
    # Most common kind of play: how often the chosen play type wins among the types offered.
    chosen_types = Counter()
    for r in train_data:
        chosen_types[r["cands"][r["chosen"]]["play"]] += 1
    rand = sum(1 / len(r["cands"]) for r in test_recs) / max(1, len(test_recs))
    hits = 0
    for r in test_recs:
        best = max(range(len(r["cands"])), key=lambda i: chosen_types[r["cands"][i]["play"]])
        hits += best == r["chosen"]
    return rand, hits / max(1, len(test_recs))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", nargs="+", help="training data files downloaded from the panel")
    ap.add_argument("-o", "--out", default="policy.json")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--lr", type=float, default=0.1)
    ap.add_argument("--l2", type=float, default=1e-4)
    ap.add_argument("--holdout", type=float, default=0.2, help="share of duels kept back for testing")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()

    recs = load(a.data)
    if not recs:
        sys.exit("No usable decisions in those files. Record some plays first.")
    duels = len({r.get("duel") for r in recs})
    print(f"{len(recs)} decisions from {duels} duels, {sum(len(r['cands']) for r in recs) / len(recs):.1f} plays to choose from on average")
    tr, te = split_by_duel(recs, a.holdout, a.seed)
    if not te:
        print("Only one duel recorded, so there's nothing to test on. Record more duels for a real score.")
    enc = lambda rs: [([featurize(r, c) for c in r["cands"]], r["chosen"]) for r in rs]
    tr_d, te_d = enc(tr), enc(te)
    print(f"Training on {len(tr)} decisions, testing on {len(te)} from duels it never sees.")
    w = train(tr_d, te_d, a.epochs, a.lr, a.l2, a.seed)
    m = evaluate(w, te_d) if te_d else evaluate(w, tr_d)
    if te:
        rand, common = baselines(tr, te)
        print(f"\nOn held-out duels: picks your play {m['top1']:.1%} of the time, and has it in its top 3 {m['top3']:.1%} of the time.")
        print(f"For comparison: picking at random gets {rand:.1%}, and picking the most common kind of play gets {common:.1%}.")
    # Refit on everything, for as many epochs as worked, before exporting.
    print("\nRefitting on all decisions for the final model...")
    w = train(enc(recs), [], a.epochs, a.lr, a.l2, a.seed)
    weights = {f: round(v, 4) for f, v in w.items() if abs(v) >= 1e-3}
    model = {"kind": "ygo-duel-odds-policy", "featuresVersion": FEATURES_VERSION, "trained": time.strftime("%Y-%m-%d %H:%M"),
             "decisions": len(recs), "duels": duels, "heldOut": m if te else None, "weights": weights}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(model, f, separators=(",", ":"))
    top = sorted(weights.items(), key=lambda kv: -abs(kv[1]))[:12]
    print("\nStrongest learned preferences:")
    for f, v in top:
        print(f"  {v:+.2f}  {f}")
    print(f"\nWrote {a.out} ({len(weights)} weights). Load it in the panel's Auto tab with \"Load a trained model\".")

if __name__ == "__main__":
    main()
