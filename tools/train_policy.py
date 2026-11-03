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

Decisions from tools/sim_goat.py's look-ahead teacher also carry the value the teacher measured for each play
(cvals). With --soft-temp above 0 they're trained as soft targets (plays the teacher saw as equally good share
the credit) and --adv-scale weights decisions by how clearly the best play won. Both are off by default: with
the teacher's few noisy rollouts, soft targets taught the model to prefer safe plays like ending the turn, and
models trained on them won fewer games than ones trained on the teacher's pick alone. The "near-best" score
reported on teacher data is how often the model's pick is one the teacher rated within 0.01 of its best.

No extra packages are needed.
"""
import argparse, json, math, random, sys, time
from array import array
from collections import Counter, defaultdict

FEATURES_VERSION = 5

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
    my_atk = sum((f_num(x.get("atk")) or 0) for x in (me.get("mon") or []) if x and x.get("pos") == "ATK")
    olp = f_num(opp.get("lp"))
    lethal = 1 if olp is not None and not (opp.get("mon") or []) and my_atk >= olp else 0
    out.append(p + "|lth:" + str(lethal))
    out.append(p + "|t1:" + ("1" if (f_num(rec.get("turn")) or 0) <= 1 else "0"))
    out.append(p + "|mst:" + str(min(myst, 3)))
    if c.get("pos"):
        out.append(p + "|pos:" + c["pos"])
    if c.get("name"):
        n = p + "|n:" + c["name"]
        out.append(n)
        out.append(n + "|ph:" + ph)
        out.append(n + "|om:" + str(min(len(opp.get("mon") or []), 3)))
        out.append(n + "|ofd:" + str(ofd))
        out.append(n + "|ost:" + str(ost))
        out.append(n + "|oh:" + f_bucket(f_num(opp.get("hand")) or 0, [0, 1, 3, 5]))
        out.append(n + "|gy:" + gyld)
        out.append(n + "|lth:" + str(lethal))
        out.append(n + "|mlp:" + f_bucket(f_num(me.get("lp")), [0, 1000, 2000, 4000, 8000]))
        if c.get("pos"):
            out.append(n + "|pos:" + c["pos"])
    t = cand.get("target")
    if t:
        b = f_battle(c, t)
        out.append(p + "|bt:" + b)
        out.append(p + "|bt:" + b + "|ost:" + str(ost))
        if t.get("name"):
            out.append(p + "|tn:" + t["name"])
    return out

# ---------- Data ----------
def records(path):
    """Streams the decision records from a training file one at a time, so a file larger than memory still loads."""
    dec, buf, pos = json.JSONDecoder(), "", 0
    with open(path, encoding="utf-8") as f:
        def more():
            nonlocal buf, pos
            chunk = f.read(1 << 24)
            buf, pos = buf[pos:] + chunk, 0
            return bool(chunk)
        more()
        start = buf.find('"records"')
        if start < 0:  # a bare list of records
            start = buf.find("[")
        else:
            start = buf.find("[", start)
        if start < 0: return
        pos = start + 1
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,": pos += 1
            if pos >= len(buf):
                if not more(): return
                continue
            if buf[pos] == "]": return
            try:
                r, end = dec.raw_decode(buf, pos)
            except json.JSONDecodeError:
                if not more(): return
                continue
            pos = end
            yield r

def load(paths, vocab, temp=0.0, adv_scale=0.0):
    """Reads every usable decision and encodes it straight away, keeping only what training needs."""
    out = []
    for path in paths:
        for r in records(path):
            if isinstance(r, dict) and r.get("cands") and isinstance(r.get("chosen"), int) and 0 <= r["chosen"] < len(r["cands"]):
                if r.get("cvals") and len(r["cvals"]) != len(r["cands"]): r.pop("cvals")
                out.append({"duel": r.get("duel"), "chosen": r["chosen"], "plays": tuple(sys.intern(c["play"]) for c in r["cands"]),
                            "soft": bool(r.get("cvals")), "enc": encode([r], vocab, temp, adv_scale)[0]})
                if len(out) % 50000 == 0: print(f"  read {len(out)} decisions", flush=True)
    return out

def split_by_duel(recs, share, seed):
    duels = sorted({r.get("duel") or "?" for r in recs})
    random.Random(seed).shuffle(duels)
    k = max(1, int(len(duels) * share)) if len(duels) > 1 else 0
    held = set(duels[:k])
    return [r for r in recs if (r.get("duel") or "?") not in held], [r for r in recs if (r.get("duel") or "?") in held]

# ---------- Model ----------
# Features are stored as integer ids, each decision as one flat array of ids with the offset where each candidate
# starts, so hundreds of thousands of decisions fit in memory. Weights are a list indexed by id.
class Vocab:
    def __init__(self): self.ids, self.names = {}, []
    def id(self, f):
        i = self.ids.get(f)
        if i is None: i = self.ids[f] = len(self.names); self.names.append(f)
        return i

def targets(r, temp, adv_scale):
    """The training target for one decision: a probability per candidate, the decision's weight, and which
    candidates count as right (the teacher's best, or every play within 0.01 of its best value)."""
    n, y = len(r["cands"]), r["chosen"]
    vals = r.get("cvals")
    if not vals or not temp or sum(v is not None for v in vals) < 2:
        q = [0.0] * n; q[y] = 1.0
        return q, 1.0, {y}
    known = [(v, j) for j, v in enumerate(vals) if v is not None]
    best = max(v for v, _ in known)
    ok = {j for v, j in known if v >= best - 0.01} | {y}
    e = {j: math.exp((v - best) / temp) for v, j in known}
    z = sum(e.values())
    q = [e.get(j, 0.0) / z for j in range(n)]
    # The gap to the best play that scored differently; a gap of 0 means the teacher saw nothing to choose between.
    lower = [v for v, _ in known if v < best - 1e-9]
    gap = best - max(lower) if lower else 0.0
    weight = min(1.0, 0.1 + gap / adv_scale) if adv_scale else 1.0
    return q, weight, ok

def encode(recs, vocab, temp=0.0, adv_scale=0.0):
    out = []
    for r in recs:
        flat, offs = array("I"), [0]
        for c in r["cands"]:
            flat.extend(vocab.id(f) for f in featurize(r, c)); offs.append(len(flat))
        q, weight, ok = targets(r, temp, adv_scale)
        out.append((flat, tuple(offs), r["chosen"], array("f", q), weight, frozenset(ok)))
    return out

def scores(w, d):
    flat, offs = d[0], d[1]
    return [sum(w[i] for i in flat[offs[j]:offs[j + 1]]) for j in range(len(offs) - 1)]

def softmax(xs):
    m = max(xs)
    e = [math.exp(x - m) for x in xs]
    z = sum(e)
    return [v / z for v in e]

def evaluate(w, data):
    if not data:
        return {"n": 0}
    top1 = top3 = near = 0
    ll = 0.0
    for d in data:
        s, y, ok = scores(w, d), d[2], d[5]
        order = sorted(range(len(s)), key=lambda i: -s[i])
        top1 += order[0] == y
        top3 += y in order[:3]
        near += order[0] in ok
        ll += math.log(max(softmax(s)[y], 1e-12))
    n = len(data)
    return {"n": n, "top1": top1 / n, "top3": top3 / n, "near": near / n, "loglik": ll / n}

def train(data, dev, size, epochs, lr, l2, seed):
    w, g2 = [0.0] * size, [0.0] * size
    rnd = random.Random(seed)
    best, best_w, best_ep, since = None, None, 0, 0
    order = list(range(len(data)))
    for ep in range(1, epochs + 1):
        rnd.shuffle(order)
        for i in order:
            d = data[i]; flat, offs, q, weight = d[0], d[1], d[3], d[4]
            p = softmax(scores(w, d))
            grad = defaultdict(float)
            for j in range(len(offs) - 1):
                g = (p[j] - q[j]) * weight
                if g > 1e-6 or g < -1e-6:
                    for f in flat[offs[j]:offs[j + 1]]:
                        grad[f] += g
            for f, g in grad.items():
                g += l2 * w[f]
                g2[f] += g * g
                w[f] -= lr * g / (math.sqrt(g2[f]) + 1e-8)
        m = evaluate(w, dev) if dev else evaluate(w, data)
        print(f"  epoch {ep:3d}: {'held-out' if dev else 'training'} top-1 {m['top1']:.3f}, near-best {m['near']:.3f}, log-likelihood {m['loglik']:.3f}", flush=True)
        # Keeps the epoch whose picks were most often among the teacher's best (the exact pick, without teacher values).
        if best is None or m["near"] > best + 1e-4:
            best, best_w, best_ep, since = m["near"], list(w), ep, 0
        else:
            since += 1
            if since >= 4:
                print("  stopping early: no improvement for 4 epochs")
                break
    return best_w, best_ep

def baselines(train_data, test_recs):
    # Most common kind of play: how often the chosen play type wins among the types offered.
    chosen_types = Counter()
    for r in train_data:
        chosen_types[r["plays"][r["chosen"]]] += 1
    rand = sum(1 / len(r["plays"]) for r in test_recs) / max(1, len(test_recs))
    hits = 0
    for r in test_recs:
        best = max(range(len(r["plays"])), key=lambda i: chosen_types[r["plays"][i]])
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
    ap.add_argument("--soft-temp", type=float, default=0.0, help="temperature for soft targets from teacher values (try 0.05); 0, the default, trains on the chosen play only")
    ap.add_argument("--adv-scale", type=float, default=0.0, help="a decision counts in full once its best play beats the next by this much (try 0.1); 0, the default, weights all alike")
    a = ap.parse_args()

    vocab = Vocab()
    recs = load(a.data, vocab, a.soft_temp, a.adv_scale)
    if not recs:
        sys.exit("No usable decisions in those files. Record some plays first.")
    duels = len({r.get("duel") for r in recs})
    soft = sum(r["soft"] for r in recs)
    print(f"{len(recs)} decisions from {duels} duels, {sum(len(r['plays']) for r in recs) / len(recs):.1f} plays to choose from on average"
          + (f"; {soft} carry teacher values" if soft else ""))
    tr, te = split_by_duel(recs, a.holdout, a.seed)
    if not te:
        print("Only one duel recorded, so there's nothing to test on. Record more duels for a real score.")
    tr_d, te_d = [r["enc"] for r in tr], [r["enc"] for r in te]
    print(f"Training on {len(tr)} decisions, testing on {len(te)} from duels it never sees.")
    w, best_ep = train(tr_d, te_d, len(vocab.names), a.epochs, a.lr, a.l2, a.seed)
    m = evaluate(w, te_d) if te_d else evaluate(w, tr_d)
    if te:
        rand, common = baselines(tr, te)
        print(f"\nOn held-out duels: picks your play {m['top1']:.1%} of the time, one of the teacher's best {m['near']:.1%}, and has it in its top 3 {m['top3']:.1%} of the time.")
        print(f"For comparison: picking at random gets {rand:.1%}, and picking the most common kind of play gets {common:.1%}.")
    # Refit on everything, for as many epochs as worked best on the held-out duels, before exporting.
    print(f"\nRefitting on all decisions for {best_ep} epochs for the final model...")
    w, _ = train(tr_d + te_d, [], len(vocab.names), best_ep, a.lr, a.l2, a.seed)
    w = dict(zip(vocab.names, w))
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
