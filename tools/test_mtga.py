"""Tests for the MTG Arena odds tool.

Usage: python3 tools/test_mtga.py [--no-corpus]
  - Parser checks on hand-written game states, including that hidden opponent cards never get a name.
  - Parser checks on real, sanitized Arena logs from github.com/manasight/manasight-corpus, downloaded to tools/.cache/mtg/corpus.
  - Odds checks against exact math, run with macOS's built-in JavaScript engine (osascript), so those need a Mac.
"""
import gzip, json, os, shutil, subprocess, sys, tempfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mtga"))
from tracker import Tracker, format_of
from decisions import Recorder
import policy

CORPUS = os.path.join(ROOT, "tools", ".cache", "mtg", "corpus")
CORPUS_URL = "https://raw.githubusercontent.com/manasight/manasight-corpus/main/corpus/"
LOGS = ["session_2026-02-23_0000_standard-bo1", "session_2026-03-11_2124_trad-standard-bo3", "session_2026-03-11_1847_quick-draft-selesnya", "session_2026-04-27_2230", "session_2026-03-15_1157_detailed_logs_disabled"]
SECRET, BOLT, FOREST, BEAR = 999001, 999002, 999003, 999004
CARDS = {BOLT: ("Lightning Bolt", "I", ""), FOREST: ("Forest", "L", "G"), BEAR: ("Grizzly Bears", "C", ""), SECRET: ("Secret Card", "I", "")}
failures = []


def check(cond, what):
    print(("  ok    " if cond else "  FAIL  ") + what)
    if not cond: failures.append(what)


# ---------- A tiny game in Arena's message format ----------
ZONES = [
    {"zoneId": 1, "type": "ZoneType_Hand", "visibility": "Visibility_Private", "ownerSeatId": 1, "objectInstanceIds": []},
    {"zoneId": 2, "type": "ZoneType_Hand", "visibility": "Visibility_Private", "ownerSeatId": 2, "objectInstanceIds": [20, 21, 22]},
    {"zoneId": 3, "type": "ZoneType_Library", "visibility": "Visibility_Hidden", "ownerSeatId": 2, "objectInstanceIds": list(range(100, 150))},
    {"zoneId": 4, "type": "ZoneType_Battlefield", "visibility": "Visibility_Public", "objectInstanceIds": [30, 31]},
    {"zoneId": 5, "type": "ZoneType_Stack", "visibility": "Visibility_Public", "objectInstanceIds": []},
    {"zoneId": 6, "type": "ZoneType_Graveyard", "visibility": "Visibility_Public", "ownerSeatId": 2, "objectInstanceIds": []},
    {"zoneId": 7, "type": "ZoneType_Exile", "visibility": "Visibility_Public", "objectInstanceIds": []},
]


def obj(i, grp, zone, owner=2, vis="Visibility_Public", **kw):
    return dict({"instanceId": i, "grpId": grp, "type": "GameObjectType_Card", "zoneId": zone, "visibility": vis, "ownerSeatId": owner, "controllerSeatId": owner}, **kw)


def full_state():
    return {"type": "GameStateType_Full", "gameInfo": {"matchID": "m1", "gameNumber": 1}, "zones": json.loads(json.dumps(ZONES)),
            "gameObjects": [obj(30, FOREST, 4, cardTypes=["CardType_Land"]), obj(31, FOREST, 4, cardTypes=["CardType_Land"])],
            "players": [{"systemSeatNumber": 1, "lifeTotal": 20}, {"systemSeatNumber": 2, "lifeTotal": 20}],
            "turnInfo": {"turnNumber": 1, "activePlayer": 1, "phase": "Phase_Main1", "step": "Step_Main1"}}


def send(t, **state):
    state.setdefault("type", "GameStateType_Diff")
    t.on_message({"systemSeatIds": [1], "gameStateMessage": state})


def transfer(i, category, src, dest):
    return {"type": ["AnnotationType_ZoneTransfer"], "affectedIds": [i], "details": [{"key": "zone_src", "valueInt32": [src]}, {"key": "zone_dest", "valueInt32": [dest]}, {"key": "category", "valueString": [category]}]}


def fresh():
    t = Tracker(CARDS)
    send(t, **full_state())
    return t


def test_hidden():
    print("Hidden cards")
    t = fresh()
    # Their hand holds a card the log names but addresses only to themselves. So does their library. And a list of their options.
    send(t, gameObjects=[obj(20, SECRET, 2, vis="Visibility_Private", viewers=[2]), obj(100, SECRET, 3, vis="Visibility_Hidden"), obj(40, SECRET, 7, isFacedown=True)],
         actions=[{"seatId": 2, "action": {"actionType": "ActionType_Cast", "instanceId": 20, "grpId": SECRET}}])
    z = {"zoneId": 7, "type": "ZoneType_Exile", "visibility": "Visibility_Public", "objectInstanceIds": [40]}
    send(t, zones=[z])
    text = json.dumps(t.view())
    check("Secret Card" not in text, "A private card, a library card, a face-down exile and the actions list never get a name")
    check(t.view()["lost"] == 1, "A face-down exiled card counts as hidden")
    check(len(t.view()["hand"]) == 3 and t.view()["handCount"] == 3, "Their unnamed hand cards stay anonymous slots")
    # Shown to me by a Duress effect: I do know this one.
    send(t, gameObjects=[obj(21, BOLT, 2, vis="Visibility_Private", viewers=[2, 1])])
    check(t.view()["kh"] == {"Lightning Bolt": 1}, "A card revealed to me counts as known in their hand")
    check(t.view()["seen"].get("Lightning Bolt") == 1, "...and proves the deck runs it")


def test_evidence():
    print("Evidence")
    t = fresh()
    my_spell = obj(50, BEAR, 5, owner=1, cardTypes=["CardType_Creature"])
    stack = {"zoneId": 5, "type": "ZoneType_Stack", "visibility": "Visibility_Public", "objectInstanceIds": [50]}
    send(t, zones=[stack], gameObjects=[my_spell], annotations=[transfer(50, "CastSpell", 1, 5)])
    check(t.view()["pending"] == 1, "My spell opens a response window")
    check(t.view()["mana"] == ["G", "G"], "Open mana is read from their untapped lands")
    send(t, annotations=[transfer(50, "Resolve", 5, 4)])
    ev = t.view()["hand"][0]["ev"]
    check(len(ev) == 1 and ev[0]["tags"] == ["c"] and ev[0]["mana"] == ["G", "G"], "It resolving counts against creature counters, with the mana they had then")

    t = fresh()
    send(t, zones=[stack], gameObjects=[my_spell], annotations=[transfer(50, "CastSpell", 1, 5)])
    send(t, gameObjects=[obj(51, BOLT, 5)], annotations=[transfer(51, "CastSpell", 2, 5)])
    check(t.view()["pending"] == 0, "Their response closes the window")
    send(t, annotations=[transfer(50, "Resolve", 5, 4)])
    check(not t.view()["hand"][0]["ev"], "...and logs no evidence")

    t = fresh()
    send(t, turnInfo={"turnNumber": 2, "activePlayer": 2, "step": "Step_Upkeep"})
    send(t, turnInfo={"turnNumber": 3, "activePlayer": 1, "step": "Step_Upkeep"})
    ev = t.view()["hand"][0]["ev"]
    check(len(ev) == 1 and ev[0].get("land"), "A turn with no land drop counts against lands in hand")
    t = fresh()
    send(t, turnInfo={"turnNumber": 2, "activePlayer": 2, "step": "Step_Upkeep"})
    send(t, annotations=[transfer(30, "PlayLand", 2, 4)])
    send(t, turnInfo={"turnNumber": 3, "activePlayer": 1, "step": "Step_Upkeep"})
    check(not t.view()["hand"][0]["ev"], "A land drop logs no such evidence")

    check(format_of("Constructed_BestOf3") == "standard" and format_of("Ladder") == "standard" and format_of("Historic_Play") == "historic" and format_of("QuickDraft_ECL_20260223") == "limited", "Event names map to formats")


def test_corpus():
    print("Real Arena logs")
    os.makedirs(CORPUS, exist_ok=True)
    totals = {"objects": 0, "unknown": 0, "states": 0, "right_size": 0, "games": 0, "evidence": 0, "hidden_named": 0}
    from tracker import load_cards
    cards = load_cards()
    for name in LOGS:
        path = os.path.join(CORPUS, name + ".log")
        if not os.path.exists(path):
            with urllib.request.urlopen(CORPUS_URL + name + ".log.gz") as r, gzip.open(r) as g, open(path, "wb") as f: shutil.copyfileobj(g, f)
        ended = []
        t = Tracker(cards, on_game_end=ended.append)
        last = None
        for line in open(path, errors="replace"):
            t.feed(line.rstrip("\n"))
            if t.version == last: continue
            last = t.version
            v = t.view()
            if v["state"] != "duel": continue
            # Hidden cards never carry names in the view's hand slots, by construction. Check every state's accounting.
            total = v["library"] + v["handCount"] + v["lost"] + sum(v["pub"].values())
            totals["states"] += 1
            if total == v["size"]: totals["right_size"] += 1
            totals["evidence"] += sum(len(h["ev"]) for h in v["hand"])
            g = t.game
            for o in t.in_zone(g, t.zone_of(g, "ZoneType_Hand", g.opp)) + t.in_zone(g, t.zone_of(g, "ZoneType_Library", g.opp)):
                if o.get("visibility") == "Visibility_Private" and g.me not in (o.get("viewers") or []) and o.get("grpId") and o.get("grpId") in cards and cards[o["grpId"]][0] in v["kh"]: totals["hidden_named"] += 1
            for n, k in v["pub"].items():
                totals["objects"] += k
                if n.startswith("Unknown card"): totals["unknown"] += k
        totals["games"] += len(ended)
        if "detailed_logs_disabled" in name: check(t.detailed is False and t.messages == 0, "A log with detailed logs off is reported as off")
    known = 1 - totals["unknown"] / max(1, totals["objects"])
    share = totals["right_size"] / max(1, totals["states"])
    print(f"        {totals['states']} game states, {totals['games']} finished games, {known:.1%} of their public cards named, {share:.1%} of states with every card accounted for")
    check(totals["games"] >= 8, "Finds the finished games")
    check(known > 0.97, "Names nearly every public card")
    check(share > 0.9, "Library + hand + public cards adds up to their deck in nearly every state")
    check(totals["evidence"] > 0, "Logs \"no response\" evidence in real games")
    check(totals["hidden_named"] == 0, "No private opponent card is ever named")


def answer(t, payload):
    for line in ["{", json.dumps({"clientToMatchServiceMessageType": "ClientToMatchServiceMessageType_ClientToGREMessage", "payload": payload}, indent=1).split("\n", 1)[1]]:
        for part in line.split("\n"): t.feed(part)


def test_decisions():
    print("Decisions and suggestions")
    got = []
    t = Recorder(CARDS, on_decision=got.append, details={"Lightning Bolt": (1, "r"), "Grizzly Bears": (2, "")})
    state = full_state()
    state["zones"][0]["objectInstanceIds"] = [60, 61]
    state["gameObjects"] += [obj(60, BOLT, 1, owner=1), obj(61, BEAR, 1, owner=1), obj(20, SECRET, 2, vis="Visibility_Private", viewers=[2])]
    state["gameInfo"]["variant"] = "GameVariant_Brawl"
    send(t, **state)
    bolt = {"actionType": "ActionType_Cast", "grpId": BOLT, "instanceId": 60, "manaCost": [{"count": 1}]}
    t.on_message({"type": "GREMessageType_ActionsAvailableReq", "systemSeatIds": [1], "msgId": 9, "actionsAvailableReq": {"actions": [bolt, {"actionType": "ActionType_Activate_Mana", "instanceId": 30}, {"actionType": "ActionType_Pass"}]}})
    answer(t, {"type": "ClientMessageType_PerformActionResp", "respId": 9, "performActionResp": {"actions": [bolt]}})
    check(len(got) == 1 and got[0]["chosen"].startswith("ActionType_Cast|60"), "Joins what was offered to what was chosen")
    check(len(got[0]["cands"]) == 2 and got[0]["brawl"], "Leaves out mana tapping and notices Brawl")
    check("Secret Card" not in json.dumps(got[0]), "A record never holds their hidden cards")
    check(policy.suggestions_allowed("AIBotMatch_Rebalanced") and policy.suggestions_allowed("Ladder", True), "Suggestions work against the bot and in replays")
    check(not any(policy.suggestions_allowed(e) for e in ("Ladder", "Play_Brawl", "Play_Brawl_Historic", "Constructed_BestOf3", None)), "Suggestions stay locked against people")
    model = {"weights": {"n|Lightning Bolt": 2.0}}
    check(policy.rank(model, got[0])[0][1]["play"] == "Cast", "The model ranks plays by their features")


JS_TESTS = r"""
const data = ["Bolt\tI\t1\t{R}\t\tr\t1", "Counterspell\tI\t2\t{U}{U}\t\tcn\t2", "Cancel\tI\t3\t{1}{U}{U}\t\tcn\t3", "Bear\tC\t2\t{1}{G}\t\t\t4", "Island\tL\t0\t\tU\t\t5", "Wrath\tS\t4\t{2}{W}{W}\t\tw\t6", "Dual\tL\t0\t\tUR\t\t7"].join("\n");
const DB = MtgOdds.parseCards(data);
const lookup = n => DB[MtgOdds.norm(n)] || {name:n, type:"?", cmc:0, cost:"", tags:[]};
const out = {};
out.cast = {
  uu: MtgOdds.castable(DB.counterspell, ["U","U"]), ur: MtgOdds.castable(DB.counterspell, ["U","R"]), one: MtgOdds.castable(DB.counterspell, ["U"]),
  dual: MtgOdds.castable(DB.counterspell, ["UR","U"]), generic: MtgOdds.castable(DB.cancel, ["U","U","G"]), shared: MtgOdds.castable(DB.cancel, ["U","G","G"]),
};
const choose = (n, k) => { let r = 1; for (let i = 0; i < k; i++) r = r * (n - i) / (i + 1); return r; };
function runList(counts, view, extra){
  const seen = {}, visible = {};
  for (const o of [view.pub || {}, view.kh || {}]) for (const k in o){ visible[k] = (visible[k] || 0) + o[k]; seen[k] = Math.max(seen[k] || 0, visible[k]); }
  const H = view.library + view.hand.length + (view.lost || 0);
  const M = MtgOdds.buildModel({lookup, comps:[{name:"List", prior:1, list:true, counts, copies:{}, basics:{}}], seen, visible, H});
  const r = MtgOdds.simulate(M, view, Object.assign({N:40000}, extra || {}));
  r.at = name => M.cards.findIndex(c => c.name === name);
  return r;
}
const slots = n => Array.from({length:n}, (_, i) => ({id:i, ev:[]}));
// 4 Bolts in a 60-card deck, a 7-card hand: the exact chance of holding one is 1 - C(56,7)/C(60,7).
{ const r = runList({Bolt:4, Island:56}, {hand:slots(7), library:53, kh:{}, pub:{}, mana:["R"], manaAll:["R"]});
  out.hyper = {got:r.handAny[r.at("Bolt")], want:1 - choose(56,7)/choose(60,7), next:r.nextDraw[r.at("Bolt")], threat:r.threat.removal}; }
// Two Bolts already public leaves 2 in 58, and the hand is 7 of them.
{ const r = runList({Bolt:4, Island:56}, {hand:slots(7), library:51, kh:{}, pub:{Bolt:2}, mana:["R"], manaAll:["R"]});
  out.pub = {got:r.handAny[r.at("Bolt")], want:1 - choose(56,7)/choose(58,7), next:r.nextDraw[r.at("Bolt")], want2:2/58}; }
// Mana gating: Bolt in hand can't be cast without red, and Counterspell needs UU.
{ const view = {hand:slots(7), library:53, kh:{}, pub:{}, mana:["U"], manaAll:["U"]};
  const r = runList({Bolt:4, Counterspell:4, Island:52}, view);
  out.gate = {removal:r.threat.removal, counter:r.threat.counter};
  const r2 = runList({Bolt:4, Counterspell:4, Island:52}, Object.assign({}, view, {mana:["U","U"]}));
  out.gate.counter2 = r2.threat.counter; out.gate.want = 1 - choose(56,7)/choose(60,7); }
// Known hand card: the threat is certain, whatever's hidden.
{ const r = runList({Bolt:4, Island:56}, {hand:slots(6), library:53, kh:{Bolt:1}, pub:{}, mana:["R"], manaAll:["R"]});
  out.known = {threat:r.threat.removal, any:r.handAny[r.at("Bolt")]}; }
// One card in hand, certainly no land drop: the card is the spell, not an Island, nearly every time.
{ const ev = [{n:1, land:true, why:""}];
  const r = runList({Bear:30, Island:30}, {hand:[{id:0, ev}], library:59, kh:{}, pub:{}, mana:[], manaAll:[]});
  out.noland = {pLand:r.landDist[1], want:0.05 * 30 / (0.05 * 30 + 30)}; }
// A window with UU up lowers Counterspell. A window with one U open can't, because they couldn't have paid.
{ const counts = {Counterspell:30, Island:30};
  const with2 = runList(counts, {hand:[{id:0, ev:[{n:1, tags:["n"], mana:["U","U"], w:1, why:""}]}], library:59, kh:{}, pub:{}, mana:[], manaAll:[]}, {strength:1});
  const with1 = runList(counts, {hand:[{id:0, ev:[{n:2, tags:["n"], mana:["U"], w:1, why:""}]}], library:59, kh:{}, pub:{}, mana:[], manaAll:[]}, {strength:1});
  const ign = runList(counts, {hand:[{id:0, ev:[{n:3, tags:["n"], mana:["U","U"], w:1, why:""}]}], library:59, kh:{}, pub:{}, mana:[], manaAll:[]}, {strength:1, ignored:new Set([3])});
  out.window = {paid:with2.handAny[with2.at("Counterspell")], unpaid:with1.handAny[with1.at("Counterspell")], ignored:ign.handAny[ign.at("Counterspell")]}; }
// Archetypes: showing a card shifts the guess to the deck that runs it.
{ const comps = [{name:"Blue", prior:5, copies:{Counterspell:[0,0,0,0,1], Cancel:[0,0,0,0,1]}, basics:{Island:24}}, {name:"Green", prior:5, copies:{Bear:[0,0,0,0,1]}, basics:{Forest:24}}];
  const blank = MtgOdds.buildModel({lookup, comps, seen:{}, visible:{}, H:60});
  const M = MtgOdds.buildModel({lookup, comps, seen:{Counterspell:1}, visible:{Counterspell:1}, H:59});
  const r = MtgOdds.simulate(M, {hand:slots(7), library:52, kh:{}, pub:{Counterspell:1}, mana:["U","U"], manaAll:["U","U"]}, {N:6000});
  out.mix = {before:blank.comps[0].w, after:r.compPost[0], size:M.cards.reduce((a, e, k) => a + r.deckExp[k], 0)}; }
JSON.stringify(out);
"""


def test_odds():
    print("Odds against exact math")
    if sys.platform != "darwin":
        print("  skipped: needs macOS's JavaScript engine")
        return
    src = open(os.path.join(ROOT, "mtga", "odds.js"), encoding="utf-8").read()
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(src + "\n" + JS_TESTS)
    try:
        r = subprocess.run(["osascript", "-l", "JavaScript", f.name], capture_output=True, text=True, timeout=300)
    finally:
        os.unlink(f.name)
    if r.returncode:
        check(False, "odds.js runs: " + r.stderr.strip()[:400])
        return
    o = json.loads(r.stdout)
    near = lambda a, b, tol=0.01: abs(a - b) <= tol
    c = o["cast"]
    check(c["uu"] and not c["ur"] and not c["one"] and c["dual"], "Colored costs need sources of the right colors")
    check(c["generic"] and not c["shared"], "Generic costs can use any mana, colored symbols can't")
    h = o["hyper"]
    check(near(h["got"], h["want"]), f"Holding one of 4 in 60, 7 cards: {h['got']:.3f}, exact {h['want']:.3f}")
    check(near(h["next"], 4 / 60), f"Next draw is 4/60: {h['next']:.3f}")
    check(near(h["threat"], h["want"]), "With red open, the removal threat equals the chance of holding it")
    p = o["pub"]
    check(near(p["got"], p["want"]), f"Public copies leave the pool: {p['got']:.3f}, exact {p['want']:.3f}")
    check(near(p["next"], p["want2"], 0.005), f"...and the next draw too: {p['next']:.3f}, exact {p['want2']:.3f}")
    g = o["gate"]
    check(g["removal"] == 0 and g["counter"] == 0, "Cards they can't pay for are no threat")
    check(near(g["counter2"], g["want"]), f"With UU open, Counterspell counts: {g['counter2']:.3f}, exact {g['want']:.3f}")
    check(o["known"]["threat"] == 1 and o["known"]["any"] == 1, "A known card in hand is a certain threat")
    check(near(o["noland"]["pLand"], o["noland"]["want"], 0.01), f"Missed land drop: land chance {o['noland']['pLand']:.3f}, exact {o['noland']['want']:.3f}")
    w = o["window"]
    check(w["paid"] < 0.01, f"No response with the mana up rules out a certain Counterspell: {w['paid']:.3f}")
    check(near(w["unpaid"], 0.5, 0.015), f"No response without the mana says nothing: {w['unpaid']:.3f}")
    check(near(w["ignored"], 0.5, 0.015), f"Ignored evidence counts for nothing: {w['ignored']:.3f}")
    m = o["mix"]
    check(near(m["before"], 0.5, 0.001) and m["after"] > 0.99, f"A shown card moves the guess: {m['before']:.2f} to {m['after']:.2f}")
    check(near(m["size"], 60, 0.01), f"Estimated deck adds up to the real deck size: {m['size']:.2f}")


def main():
    test_hidden()
    test_evidence()
    test_decisions()
    test_odds()
    if "--no-corpus" not in sys.argv: test_corpus()
    print(f"\n{len(failures)} failed" if failures else "\nAll passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
