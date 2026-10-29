"""Checks that extension/features.js and tools/train_policy.py compute identical features.

Usage: python3 tools/test_features.py
Runs the JavaScript copy with macOS's built-in JavaScript engine (osascript), so it needs a Mac.
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from train_policy import featurize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mon = lambda n, atk, d, pos="ATK", lvl=4: {"name": n, "ctype": "Monster", "zone": "monster", "pos": pos, "atk": atk, "def": d, "level": lvl}
FIXTURES = [
    {"phase": "M1", "myTurn": True, "turn": 3, "playsThisTurn": 2, "summonsThisTurn": 1, "drawsThisTurn": 4, "discardsThisTurn": 1, "lastPlay": "Activate ST", "lastCard": "Pot of Greed",
     "turnHistory": ["Draw card:", "Activate ST:Graceful Charity", "To GY:Sangan"],
     "me": {"lp": 8000, "deck": 30, "hand": [{"name": "Sangan"}] * 4, "mon": [mon("Sangan", 1000, 600)], "st": [], "gy": 2, "gyLight": 1, "gyDark": 0, "ban": 0},
     "opp": {"lp": 3500, "deck": 31, "hand": 5, "mon": [{"pos": "FD"}, {"name": "Sangan", "pos": "ATK", "atk": 1000, "def": 600}], "st": [{"pos": "FD"}, {"pos": "FD"}], "gy": 1, "ban": 0},
     "cands": [
         {"key": "card|1|Normal Summon", "play": "Normal Summon", "card": {"name": "Breaker the Magical Warrior", "ctype": "Monster", "zone": "hand", "atk": "1600", "def": "1000", "level": "4"}, "target": None},
         {"key": "card|2|Attack|9", "play": "Attack", "card": mon("Sangan", 1000, 600), "target": {"pos": "FD"}},
         {"key": "card|3|Attack|8", "play": "Attack", "card": mon("Jinzo", 2400, 1500, lvl=6), "target": {"name": "Spirit Reaper", "pos": "DEF", "atk": 300, "def": 200}},
         {"key": "card|4|Attack|7", "play": "Attack", "card": mon("Tsukuyomi", 1100, 1400), "target": {"name": "Sangan", "pos": "ATK", "atk": 1100, "def": 600}},
         {"key": "global|End turn", "play": "End turn", "card": None, "target": None},
         {"key": "deck|Draw card", "play": "Draw card", "card": {"zone": "deck"}, "target": None},
     ], "chosen": 0},
    {"phase": "", "myTurn": False, "playsThisTurn": None, "summonsThisTurn": "2.5",
     "me": {"lp": None, "hand": [], "mon": [], "st": []}, "opp": {"lp": "?", "hand": None, "mon": [], "st": []},
     "cands": [{"key": "card|5|Activate", "play": "Activate", "card": {"name": "Black Luster Soldier - Envoy of the Beginning", "ctype": "Monster", "zone": "hand", "atk": "?", "def": None, "level": 8}, "target": {"pos": "ATK", "atk": None}}], "chosen": 0},
    {"cands": [{"key": "global|Enter BP", "play": "Enter BP"}], "chosen": 0},
]

def js_features():
    js = open(os.path.join(ROOT, "extension", "features.js"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(FIXTURES, f); path = f.name
    script = f"""
ObjC.import('Foundation');
const read = p => $.NSString.stringWithContentsOfFileEncodingError(p, 4, null).js;
eval(read({json.dumps(os.path.join(ROOT, 'extension', 'features.js'))}) + "; this.featurize = featurize;");
const recs = JSON.parse(read({json.dumps(path)}));
JSON.stringify(recs.map(r => r.cands.map(c => featurize(r, c))));
"""
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", script], capture_output=True, text=True)
    os.unlink(path)
    if out.returncode:
        sys.exit("JavaScript side failed: " + out.stderr)
    return json.loads(out.stdout)

def main():
    js = js_features()
    py = [[featurize(r, c) for c in r["cands"]] for r in FIXTURES]
    bad = 0
    for ri, (a, b) in enumerate(zip(js, py)):
        for ci, (fa, fb) in enumerate(zip(a, b)):
            if fa != fb:
                bad += 1
                print(f"record {ri}, candidate {ci} differs:\n  only in JS:     {sorted(set(fa) - set(fb))}\n  only in Python: {sorted(set(fb) - set(fa))}\n  order same: {fa == fb}")
    n = sum(len(x) for x in py)
    print(f"{n - bad} of {n} candidates match." if bad else f"All {n} candidates have identical features in JavaScript and Python.")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
