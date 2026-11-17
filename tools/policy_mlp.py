"""A small neural network on top of train_policy.py's linear ranker (train_policy.py --hidden N). Needs numpy.

Each candidate play is scored as

    score = sum of its feature weights                     (the linear model, unchanged)
          + v . relu(b + sum of its features' embeddings)  (one hidden layer of N units)

The hidden layer lets features combine: the linear model can only add up "Normal Summon of Sangan" and
"opponent has 2 monsters" separately, while a hidden unit can fire only when both hold. Only features seen in at
least --min-count training decisions get an embedding; rarer ones keep just their linear weight, which keeps the
exported model small. Training is mini-batch AdaGrad with L2 on the rows a batch touches, like the linear trainer.

All decisions are held in flat numpy arrays: F holds every candidate's feature ids back to back, clen how many each
candidate has, and dn how many candidates each decision has, so 600k decisions fit in a few hundred MB.
"""
import math, time
import numpy as np


class Data:
    """Decisions encoded by train_policy.encode, packed into flat arrays."""
    def __init__(self, encs):
        self.n = len(encs)
        self.F = np.concatenate([np.frombuffer(e[0], dtype=np.uint32) for e in encs]) if encs else np.zeros(0, np.uint32)
        self.clen = np.concatenate([np.diff(np.asarray(e[1], dtype=np.int64)) for e in encs]).astype(np.int32) if encs else np.zeros(0, np.int32)
        self.dn = np.array([len(e[1]) - 1 for e in encs], dtype=np.int32)
        self.q = np.concatenate([np.frombuffer(e[3], dtype=np.float32) for e in encs]) if encs else np.zeros(0, np.float32)
        self.wt = np.array([e[4] for e in encs], dtype=np.float32)
        self.chosen = np.array([e[2] for e in encs], dtype=np.int64)
        ok = np.zeros(len(self.clen), dtype=bool)
        self.d0 = np.concatenate([[0], np.cumsum(self.dn)[:-1]]).astype(np.int64) if encs else np.zeros(0, np.int64)
        for i, e in enumerate(encs):
            for j in e[5]: ok[self.d0[i] + j] = True
        self.ok = ok
        self.c0 = np.concatenate([[0], np.cumsum(self.clen)[:-1]]).astype(np.int64) if len(self.clen) else np.zeros(0, np.int64)

    def __add__(self, other):
        out = Data([])
        out.n = self.n + other.n
        for k in ("F", "clen", "dn", "q", "wt", "chosen", "ok"):
            setattr(out, k, np.concatenate([getattr(self, k), getattr(other, k)]))
        out.d0 = np.concatenate([[0], np.cumsum(out.dn)[:-1]]).astype(np.int64)
        out.c0 = np.concatenate([[0], np.cumsum(out.clen)[:-1]]).astype(np.int64)
        return out


def _ranges(starts, lens):
    """Concatenated aranges [starts[i], starts[i] + lens[i]) as one index array."""
    tot = int(lens.sum())
    if not tot: return np.zeros(0, np.int64)
    ends = np.cumsum(lens)
    return np.arange(tot, dtype=np.int64) - np.repeat(ends - lens, lens) + np.repeat(starts, lens)


class Model:
    def __init__(self, size, hidden, counts, min_count, seed):
        rnd = np.random.default_rng(seed)
        self.w = np.zeros(size, np.float64)
        self.H = hidden
        # row[f] is feature f's embedding row, or -1 if it's too rare to get one.
        common = counts >= min_count
        self.row = np.full(size, -1, np.int64)
        self.row[common] = np.arange(int(common.sum()))
        self.E = rnd.normal(0, 0.1, (int(common.sum()), hidden))
        self.b = np.zeros(hidden)
        self.v = rnd.normal(0, 0.5 / math.sqrt(hidden), hidden)
        self.g2 = {k: np.zeros_like(getattr(self, k)) for k in ("w", "E", "b", "v")}

    def copy_params(self):
        return {k: getattr(self, k).copy() for k in ("w", "E", "b", "v")}

    def set_params(self, p):
        for k, x in p.items(): setattr(self, k, x.copy())

    def forward(self, data, d):
        """Scores every candidate of decisions d. Returns what backward needs."""
        nc = data.dn[d]
        cidx = _ranges(data.d0[d], nc)
        cl = data.clen[cidx]
        f = data.F[_ranges(data.c0[cidx], cl)].astype(np.int64)
        C = len(cidx)
        cof = np.repeat(np.arange(C), cl)
        s = np.bincount(cof, weights=self.w[f], minlength=C)
        r = self.row[f]
        m = r >= 0
        rm, cm = r[m], cof[m]
        pre = np.zeros((C, self.H))
        if len(rm):
            cnt = np.bincount(cm, minlength=C)
            nz = cnt > 0
            pre[nz] = np.add.reduceat(self.E[rm], (np.cumsum(cnt) - cnt)[nz], axis=0)
        z = pre + self.b
        h = np.maximum(z, 0)
        s = s + h @ self.v
        return {"nc": nc, "cidx": cidx, "f": f, "cof": cof, "rm": rm, "cm": cm, "z": z, "h": h, "s": s}

    @staticmethod
    def softmax(s, nc):
        ds = np.cumsum(nc) - nc
        mx = np.maximum.reduceat(s, ds)
        e = np.exp(s - np.repeat(mx, nc))
        return e / np.repeat(np.add.reduceat(e, ds), nc)

    def step(self, data, d, lr, lr_h, l2):
        fw = self.forward(data, d)
        nc = fw["nc"]
        p = self.softmax(fw["s"], nc)
        g = (p - data.q[fw["cidx"]]) * np.repeat(data.wt[d], nc)
        # Linear weights.
        ids, inv = np.unique(fw["f"], return_inverse=True)
        gw = np.bincount(inv, weights=g[fw["cof"]], minlength=len(ids)) + l2 * self.w[ids]
        self.g2["w"][ids] += gw * gw
        self.w[ids] -= lr * gw / (np.sqrt(self.g2["w"][ids]) + 1e-8)
        # Hidden layer.
        z, h = fw["z"], fw["h"]
        gv = h.T @ g + l2 * self.v
        dz = (g[:, None] * self.v[None, :]) * (z > 0)
        gb = dz.sum(0)
        rm = fw["rm"]
        if len(rm):
            rows, rinv = np.unique(rm, return_inverse=True)
            order = np.argsort(rinv, kind="stable")
            cnt = np.bincount(rinv, minlength=len(rows))
            gE = np.add.reduceat(dz[fw["cm"]][order], np.cumsum(cnt) - cnt, axis=0) + l2 * self.E[rows]
            self.g2["E"][rows] += gE * gE
            self.E[rows] -= lr_h * gE / (np.sqrt(self.g2["E"][rows]) + 1e-8)
        for k, gg in (("v", gv), ("b", gb)):
            self.g2[k] += gg * gg
            setattr(self, k, getattr(self, k) - lr_h * gg / (np.sqrt(self.g2[k]) + 1e-8))

    def evaluate(self, data, batch=4096):
        if not data.n: return {"n": 0}
        top1 = top3 = near = 0
        ll = 0.0
        for i in range(0, data.n, batch):
            d = np.arange(i, min(i + batch, data.n))
            fw = self.forward(data, d)
            s, nc = fw["s"], fw["nc"]
            ds = np.cumsum(nc) - nc
            sc = s[ds + data.chosen[d]]
            above = np.add.reduceat((s > np.repeat(sc, nc)).astype(np.int64), ds)
            # The model's pick is the first candidate with the top score, as sorted() picks in train_policy.evaluate.
            mx = np.maximum.reduceat(s, ds)
            first = np.flatnonzero(s == np.repeat(mx, nc))
            seg = np.searchsorted(ds, first, side="right") - 1
            _, k = np.unique(seg, return_index=True)
            pick = first[k]
            top1 += int(((pick - ds) == data.chosen[d]).sum())
            top3 += int((above < 3).sum())
            near += int(data.ok[fw["cidx"][pick]].sum())
            p = self.softmax(s, nc)
            ll += float(np.log(np.maximum(p[ds + data.chosen[d]], 1e-12)).sum())
        n = data.n
        return {"n": n, "top1": top1 / n, "top3": top3 / n, "near": near / n, "loglik": ll / n}


def feature_counts(data, size):
    """How many decisions each feature appears in (counted once per candidate)."""
    return np.bincount(data.F.astype(np.int64), minlength=size)


def train(model, data, dev, epochs, lr, lr_h, l2, batch, seed, log=lambda s: print(s, flush=True)):
    rnd = np.random.default_rng(seed)
    best, best_p, best_ep, since = None, None, 0, 0
    for ep in range(1, epochs + 1):
        t = time.time()
        order = rnd.permutation(data.n)
        for i in range(0, data.n, batch):
            model.step(data, order[i:i + batch], lr, lr_h, l2)
        m = model.evaluate(dev if dev is not None and dev.n else data)
        log(f"  epoch {ep:3d}: {'held-out' if dev is not None and dev.n else 'training'} top-1 {m['top1']:.3f}, near-best {m['near']:.3f}, "
            f"log-likelihood {m['loglik']:.3f}  ({time.time() - t:.0f} s)")
        if best is None or m["near"] > best + 1e-4:
            best, best_p, best_ep, since = m["near"], model.copy_params(), ep, 0
        else:
            since += 1
            if since >= 4:
                log("  stopping early: no improvement for 4 epochs")
                break
    model.set_params(best_p)
    return best_ep


def export(model, names, digits=3):
    """The model as JSON: linear weights plus {"mlp": {dim, b, v, emb: {feature: [N numbers]}}}."""
    weights = {names[i]: round(float(x), 4) for i, x in enumerate(model.w) if abs(x) >= 1e-3}
    emb = {}
    for i in np.flatnonzero(model.row >= 0):
        e = model.E[model.row[i]]
        emb[names[i]] = [round(float(x), digits) for x in e]
    mlp = {"dim": model.H, "b": [round(float(x), 4) for x in model.b], "v": [round(float(x), 4) for x in model.v], "emb": emb}
    return weights, mlp


def from_json(model_json, names):
    """A Model holding a saved model's parameters, indexed by this run's vocabulary (for --score)."""
    w = model_json.get("weights", {})
    mlp = model_json.get("mlp")
    H = mlp["dim"] if mlp else 1
    m = Model.__new__(Model)
    m.H = H
    m.w = np.array([w.get(f, 0.0) for f in names])
    m.row = np.full(len(names), -1, np.int64)
    rows = []
    if mlp:
        for i, f in enumerate(names):
            e = mlp["emb"].get(f)
            if e is not None: m.row[i] = len(rows); rows.append(e)
    m.E = np.array(rows, dtype=np.float64).reshape(len(rows), H)
    m.b = np.array(mlp["b"]) if mlp else np.zeros(H)
    m.v = np.array(mlp["v"]) if mlp else np.zeros(H)
    return m
