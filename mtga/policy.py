"""The Arena play-ranking model: features for each candidate play, and scoring. tools/train_mtga_policy.py fits the weights.

Like tools/train_policy.py, it's a linear ranker: a play's score is the sum of its features' weights. Python alone uses
these features, because the local server does the scoring. Bump FEATURES_VERSION when they change.
"""
import json, math

FEATURES_VERSION = 1


def bucket(n, *cuts):
    if n is None: return "?"
    for c in cuts:
        if n <= c: return f"<={c}"
    return f">{cuts[-1]}"


def featurize(r, c):
    play, f = c["play"], []
    phase = "own" if r["myTurn"] else "opp"
    when = f"{phase}|{r['phase']}|{'stack' if r['stack'] else 'empty'}"
    mine = sum(x[0] for x in r["mine"])
    theirs = sum(x[0] for x in r["theirs"])
    board = bucket(mine - theirs, -6, -1, 0, 5)
    f += [f"p|{play}", f"p|{play}|{when}", f"p|{play}|board{board}", f"p|{play}|oppStack{r['oppOnStack']}", f"p|{play}|hand{bucket(len(r['hand']), 1, 3, 6)}"]
    if r.get("brawl"): f += [f"brawl|{play}", f"brawl|{play}|{when}"]
    if r["kind"] == "attack":
        a = r["attacker"]
        blockers = [x for x in r["theirs"] if not x[2]]
        f += [f"a|{play}|blockers{bucket(len(blockers), 0, 1, 3)}", f"a|{play}|name|{a['name']}",
              f"a|{play}|outsized{a['power'] > max([x[1] for x in blockers], default=-1)}", f"a|{play}|safe{a['toughness'] > max([x[0] for x in blockers], default=-1)}",
              f"a|{play}|lethal{mine >= (r['oppLife'] or 99)}", f"a|{play}|cmd{a.get('commander')}"]
        return f
    f += [f"p|{play}|mana{bucket(r['mana'], 0, 2, 4, 7)}", f"p|{play}|turn{bucket(r['turn'], 4, 10, 18)}", f"p|{play}|oppMana{bucket(r['oppMana'], 0, 2, 4)}"]
    if play == "Pass":
        f += [f"pass|land{r['landPlayed']}", f"pass|canPlayMore{r['myTurn'] and r['phase'] in ('Main1', 'Main2') and r['mana'] > 0}"]
        return f
    f += [f"n|{c.get('name')}", f"n|{c.get('name')}|{when}", f"ct|{c.get('ctype')}|{when}", f"cost|{bucket(c.get('cost', 0), 1, 3, 5, 7)}", f"spare|{bucket(r['mana'] - c.get('cost', 0), 0, 2)}"]
    for t in c.get("tags") or "": f += [f"tag|{t}|{when}", f"tag|{t}|board{board}"]
    if c.get("commander"):
        # Each earlier cast from the command zone adds two mana.
        f += ["cmd", f"cmd|casts{bucket(r['commanderCasts'], 0, 1, 2)}", f"cmd|{when}", f"cmd|board{board}"]
    return f


def suggestions_allowed(event, replay=False):
    """Only against Arena's built-in bot, or a replay. Advice mid-game against a person isn't fair on them."""
    return replay or (event or "").startswith("AIBotMatch")


def rank(model, rec):
    """Candidates with their chance under the model, best first."""
    w = model["weights"]
    scores = [sum(w.get(x, 0.0) for x in featurize(rec, c)) for c in rec["cands"]]
    top = max(scores)
    ps = [math.exp(s - top) for s in scores]
    z = sum(ps)
    return sorted(((p / z, c) for p, c in zip(ps, rec["cands"])), key=lambda x: -x[0])


def load(path):
    with open(path, encoding="utf-8") as f: model = json.load(f)
    if model.get("kind") != "mtga-odds-policy": raise ValueError("That isn't a model for this tool.")
    if model.get("featuresVersion") != FEATURES_VERSION: raise ValueError("That model was trained on older features. Train it again.")
    return model
