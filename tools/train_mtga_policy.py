"""Train the MTG Arena play-ranking model from logs or recorded decisions.

Usage:
  python3 tools/train_mtga_policy.py Player.log ~/.mtga-odds/decisions.jsonl [-o policy.json] [--epochs 12]

Takes Player.log files and the .jsonl files `mtga_odds.py --record` writes. Trains a linear softmax ranker with AdaGrad and
L2, like tools/train_policy.py. It holds out 20% of games, reports how often it picks the play the player made, then refits on
everything. Needs no extra packages. It learns to copy, so accuracy isn't win rate.
"""
import argparse, json, math, os, random, sys, time
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mtga"))
from decisions import Recorder, load_details
from policy import FEATURES_VERSION, featurize, rank
from tracker import load_cards


def read_all(paths):
    cards, details = load_cards(), load_details()
    out = []
    for p in paths:
        if p.endswith(".jsonl"):
            with open(p, encoding="utf-8") as f: out += [json.loads(l) for l in f if l.strip()]
            continue
        t = Recorder(cards, details=details, on_decision=out.append)
        with open(p, errors="replace") as f:
            for line in f: t.feed(line.rstrip("\r\n"))
    return out


def fit(data, epochs, lr=0.15, l2=1e-5, seed=7):
    feats = [([featurize(r, c) for c in r["cands"]], next(i for i, c in enumerate(r["cands"]) if c["key"] == r["chosen"])) for r in data]
    w, g = defaultdict(float), defaultdict(float)
    rng = random.Random(seed)
    for _ in range(epochs):
        rng.shuffle(feats)
        for cands, y in feats:
            s = [sum(w[x] for x in c) for c in cands]
            top = max(s)
            ps = [math.exp(v - top) for v in s]
            z = sum(ps)
            for i, c in enumerate(cands):
                grad = ps[i] / z - (1 if i == y else 0)
                if abs(grad) < 1e-4: continue
                for x in c:
                    d = grad + l2 * w[x]
                    g[x] += d * d
                    w[x] -= lr * d / math.sqrt(g[x] + 1e-8)
    return w


def score(data, model):
    """Top-1 accuracy of the model, of random choice and of always taking the commonest kind of play."""
    top = rnd = 0
    for r in data:
        top += rank(model, r)[0][1]["key"] == r["chosen"]
        rnd += 1 / len(r["cands"])
    return top / max(1, len(data)), rnd / max(1, len(data))


def report(label, data, model, common):
    if not data:
        print(f"  {label}: no decisions")
        return
    acc, rnd = score(data, model)
    base = sum(next(c["play"] for c in r["cands"] if c["key"] == r["chosen"]) == common.get(r["kind"]) for r in data) / len(data)
    print(f"  {label}: {len(data)} decisions, model {acc:.1%}, random {rnd:.1%}, always the commonest kind of play {base:.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("-o", "--out", default="policy.json")
    ap.add_argument("--epochs", type=int, default=12)
    args = ap.parse_args()
    data = read_all(args.paths)
    games = sorted({r["game"] for r in data})
    print(f"{len(data)} decisions from {len(games)} games ({sum(1 for r in data if r.get('brawl'))} in Brawl)")
    if len(games) < 5: sys.exit("That's too few games to train on.")
    random.Random(11).shuffle(games)
    held = set(games[:max(1, len(games) // 5)])
    train = [r for r in data if r["game"] not in held]
    test = [r for r in data if r["game"] in held]
    model = {"weights": fit(train, args.epochs)}
    common = {}
    for kind in ("priority", "attack"):
        n = Counter(next(c["play"] for c in r["cands"] if c["key"] == r["chosen"]) for r in train if r["kind"] == kind)
        if n: common[kind] = n.most_common(1)[0][0]
    print("Games it never saw:")
    report("everything", test, model, common)
    for kind in ("priority", "attack"): report(kind, [r for r in test if r["kind"] == kind], model, common)
    # Decisions with a real choice: a nonland play was on offer as well as passing.
    report("choosing among several plays", [r for r in test if r["kind"] == "priority" and len(r["cands"]) >= 3], model, common)
    # Brawl logs are rare, so each Brawl game gets held out in turn while training on all the others.
    brawl_games = sorted({r["game"] for r in data if r.get("brawl")})
    brawl = []
    for b in brawl_games:
        m = {"weights": fit([r for r in data if r["game"] != b], max(4, args.epochs // 3))}
        brawl += [(rank(m, r)[0][1]["key"] == r["chosen"], 1 / len(r["cands"])) for r in data if r["game"] == b]
    if brawl: print(f"  Brawl, each game held out: {len(brawl)} decisions from {len(brawl_games)} games, model {sum(x for x, _ in brawl) / len(brawl):.1%}, random {sum(x for _, x in brawl) / len(brawl):.1%}")
    final = fit(data, args.epochs)
    weights = {k: round(v, 3) for k, v in final.items() if abs(v) >= 0.02}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"kind": "mtga-odds-policy", "featuresVersion": FEATURES_VERSION, "trained": time.strftime("%Y-%m-%d %H:%M"), "decisions": len(data), "games": len(games), "brawlDecisions": sum(1 for r in data if r.get("brawl")), "weights": weights}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Wrote {args.out}: {len(weights)} weights, {os.path.getsize(args.out) // 1024} KB")


if __name__ == "__main__":
    main()
