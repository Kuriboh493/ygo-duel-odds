"""Fine-tune a trained Goat model by reinforcement learning: it plays games in tools/sim_goat.py and its weights
move toward the plays it made in games it won and away from the ones in games it lost.

Usage:
  python3 tools/rl_selfplay.py --init replay-policy.json -o goat-rl.json --batches 60 --jobs 6

This is REINFORCE (policy gradient) on the same linear model the extension runs. In each batch, the model
plays --batch-games games against a mix of opponents (the scripted player, the model it started from, and
itself), choosing each play at random in proportion to how much it likes it, so it tries plays it wouldn't
otherwise make. After the batch, every play it made gets credit equal to the game's result (+1 win, -1 loss)
minus the average result against that opponent, and the weights move along the gradient of the log-probability
of those plays. AdaGrad keeps the step per feature sensible, and --anchor pulls the weights back toward the
starting model, so it doesn't forget what it learned from people's games while it learns from its own.

Every --eval-every batches, the current model plays --eval-games games against the scripted player the way the
extension plays (always its top play), with the same deals each time, and the best one so far is written to -o.
"""
import argparse, json, math, os, random, sys, tempfile, time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_goat as S
from train_policy import featurize

_W = {}
def _init(a):
    _W["a"], _W["cards"] = a, S.load_cards()
    _W["decks"] = S.load_fl_decks(a.fl, None) if a.fl else S.load_decks(None)
    _W["init"] = json.load(open(a.init))
    _W["ver"], _W["w"] = None, None

def weights(path, ver):
    if _W["ver"] != ver:
        _W["w"], _W["ver"] = json.load(open(path)), ver
    return _W["w"]

def sampler(w, rnd, grad, temp):
    """A player that picks among the legal plays with probability softmax(score / temp), and adds the gradient
    of log-probability of each pick to grad."""
    def play(game, pl, cands):
        keys = S.legal(game, pl, cands)
        if len(keys) == 1: return keys[0]
        rec = game.build_record(pl, cands)
        by_key = {c["key"]: c for c in rec["cands"]}
        feats = [featurize(rec, by_key[k]) for k in keys]
        sc = [sum(w.get(f, 0.0) for f in fs) / temp for fs in feats]
        m = max(sc); e = [math.exp(s - m) for s in sc]; z = sum(e); p = [x / z for x in e]
        r, acc, j = rnd.random(), 0.0, len(p) - 1
        for i, x in enumerate(p):
            acc += x
            if r < acc: j = i; break
        if grad is not None:
            for i, fs in enumerate(feats):
                g = (1.0 if i == j else 0.0) - p[i]
                if abs(g) > 1e-4:
                    for f in fs: grad[f] += g / temp
        return keys[j]
    return play

def _game(task):
    """One training game in a worker: returns (opponent kind, result for the learner, gradient, learner decisions)."""
    a, g, opp, wpath, ver = _W["a"], task[0], task[1], task[2], task[3]
    rnd = random.Random(a.seed * 7919 + g)
    w = weights(wpath, ver)
    grad = defaultdict(float)
    seat = g % 2
    learner = sampler(w, rnd, grad, a.temp)
    other = {"scripted": lambda: S.scripted,
             "init": lambda: S.model_player(_W["init"], 0.0, random.Random(rnd.random())),
             "self": lambda: sampler(w, random.Random(rnd.random()), None, a.temp)}[opp]()
    pols = [None, None]; pols[seat], pols[1 - seat] = learner, other
    game = S.Game(_W["decks"], _W["cards"], rnd, pols, False, f"rl{g}")
    win = game.run()
    res = 1.0 if win is game.p[seat] else -1.0 if win else 0.0
    return opp, res, dict(grad)

def _eval(task):
    a, g, model = _W["a"], task[0], task[1]
    rnd = random.Random(10**6 + g)  # the same deals at every evaluation
    seat = g % 2
    pols = [S.scripted, S.scripted]; pols[seat] = S.model_player(model, 0.0, random.Random(rnd.random()))
    game = S.Game(_W["decks"], _W["cards"], rnd, pols, False, f"ev{g}")
    win = game.run()
    return 1 if win is game.p[seat] else 0

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--init", required=True, help="the model to start from (a policy.json from train_policy.py)")
    ap.add_argument("-o", "--out", default="goat-rl.json")
    ap.add_argument("--batches", type=int, default=60)
    ap.add_argument("--batch-games", type=int, default=120)
    ap.add_argument("--mix", default="scripted:2,init:1,self:1", help="opponents and their shares in each batch")
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--anchor", type=float, default=0.01, help="pull toward the starting weights, per batch")
    ap.add_argument("--temp", type=float, default=1.0, help="sampling temperature while training")
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--eval-games", type=int, default=300)
    ap.add_argument("--fl", type=int, default=300, help="deal from the N most recent Format Library topping decks (as sim_goat.py --fl)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()

    init = json.load(open(a.init))
    w0 = dict(init["weights"]); w = dict(w0)
    g2 = defaultdict(float)
    mix = []
    for part in a.mix.split(","):
        k, n = part.split(":"); mix += [k] * int(n)
    tmpdir = tempfile.mkdtemp(prefix="rl-goat-")
    wpath = os.path.join(tmpdir, "w.json")
    import multiprocessing as mp
    pool = mp.Pool(a.jobs, initializer=_init, initargs=(a,))

    def evaluate(model):
        wins = sum(pool.imap_unordered(_eval, [(g, model) for g in range(a.eval_games)], chunksize=4))
        return wins / a.eval_games

    def as_model(ww, extra):
        return dict(init, trained=time.strftime("%Y-%m-%d %H:%M"), weights={f: round(v, 4) for f, v in ww.items() if abs(v) >= 1e-3},
                    rl=extra)

    t0 = time.time()
    best = evaluate(init); best_b = 0
    print(f"Starting model wins {best:.1%} of {a.eval_games} games against the scripted player.", flush=True)
    json.dump(as_model(w, {"batches": 0, "vsScripted": best}), open(a.out, "w"), separators=(",", ":"))
    g = 0
    for b in range(1, a.batches + 1):
        json.dump(w, open(wpath, "w"), separators=(",", ":"))
        tasks = [(g + i, mix[(g + i) % len(mix)], wpath, b) for i in range(a.batch_games)]
        g += a.batch_games
        res = list(pool.imap_unordered(_game, tasks, chunksize=2))
        by = defaultdict(list)
        for opp, r, _ in res: by[opp].append(r)
        base = {k: sum(v) / len(v) for k, v in by.items()}
        step = defaultdict(float)
        for opp, r, gr in res:
            adv = r - base[opp]
            if adv == 0: continue
            for f, x in gr.items(): step[f] += adv * x / len(res)
        for f, x in step.items():
            g2[f] += x * x
            w[f] = w.get(f, 0.0) + a.lr * x / (math.sqrt(g2[f]) + 1e-8)
        if a.anchor:
            for f in list(w):
                w[f] -= a.anchor * (w[f] - w0.get(f, 0.0))
        line = ", ".join(f"vs {k} {(sum(v) / len(v) + 1) / 2:.0%}" for k, v in sorted(by.items()))
        print(f"batch {b:3d}: won {line} ({len(step)} weights moved, {time.time() - t0:.0f} s)", flush=True)
        if b % a.eval_every == 0 or b == a.batches:
            m = as_model(w, {"batches": b})
            wr = evaluate(m)
            note = ""
            if wr > best:
                best, best_b = wr, b
                m["rl"]["vsScripted"] = wr
                json.dump(m, open(a.out, "w"), separators=(",", ":")); note = " (best so far, saved)"
            print(f"  eval after batch {b}: wins {wr:.1%} against the scripted player{note}", flush=True)
    pool.close()
    print(f"Best: {best:.1%} after batch {best_b}, written to {a.out}")

if __name__ == "__main__":
    main()
