"""Turn downloaded DuelingBook replays into training decisions, in the same record format as the extension
and tools/sim_goat.py, labelled with who won each game.

Usage:
  python3 tools/replay_records.py -o replay-training.json            # every replay in tools/.cache/replays
  python3 tools/replay_records.py --check 11584-65959086              # print one replay's decisions, to eyeball

Download the replays first with tools/fetch_replays.py.

A replay is the list of plays DuelingBook sent during the match, each with a log line such as
'Set "Jar of Greed" from hand (1/6) to S-3' and, since replays show both players' private logs, the names of
cards drawn and set. Following those lines rebuilds both boards play by play: hands, monster and Spell & Trap
zones (with face-down and battle positions), Graveyards, banished cards, deck sizes and Life Points.

At each play the turn player makes that the auto-player could also make (summons, sets, activations, flip
summons, position changes, attacks, going to the Battle Phase, Main Phase 2 or ending the turn), the board
as that player saw it becomes a decision record: the opponent's face-down cards and hand are hidden, the
candidate plays are listed the way tools/sim_goat.py lists DuelingBook's menus, and "chosen" is what the
human did. The start-of-turn draw and phase steps are decisions too, and so are the draws an effect owes
(Pot of Greed, Graceful Charity, Jar of Greed, Dekoichi) and Graceful Charity's discards: the simulator and
the auto-player both leave those clicks to the model. Other plays that only carry out an effect (a Sangan
search, paying a cost, sending a resolved spell to the Graveyard) aren't decisions, and don't count as the
player's plays either, so the records' last play and turn history mean what they mean in the simulator.

Each record also gets "won" (1 if this player won the game, 0 if they lost, absent if the replay doesn't say)
and "ret", the game's result from this player's side (+1 or -1), which tools/train_policy.py --awr uses to
weight decisions by how much better than expected they turned out.
"""
import argparse, glob, json, os, re, sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
REPLAYS = os.path.join(HERE, ".cache", "replays")
GLOBAL_PLAYS = ["Enter DP", "Enter SP", "Enter M1", "Enter BP", "Enter M2", "Enter EP", "End turn"]
PHASES = {"Enter SP": "SP", "Enter M1": "M1", "Enter BP": "BP", "Enter M2": "M2", "Enter EP": "EP"}
# The draws an effect leaves the player to make, as the simulator owes them (sim_goat.py obligations). Draws
# the simulator makes by itself (Morphing Jar, Card Destruction) aren't decisions there, so not here either.
EFFECT_DRAWS = {"Pot of Greed": 2, "Graceful Charity": 3, "Upstart Goblin": 1, "Jar of Greed": 1, "Reckless Greed": 2}

QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
ZONE = re.compile(r'\b([MS])(2?)-(\d)\b')

def load_card_db():
    path = os.path.join(HERE, ".cache", "cardinfo_misc.json")
    if not os.path.exists(path): return {}
    out = {}
    for c in json.load(open(path, encoding="utf-8")):
        t = c.get("type", "")
        out[c["name"]] = {"ctype": "Monster" if "Monster" in t else "Spell" if "Spell" in t else "Trap" if "Trap" in t else None,
                          "atk": c.get("atk"), "def": c.get("def"), "level": c.get("level"), "attr": c.get("attribute") or ""}
    return out

def num(x):
    try: return int(x)
    except (TypeError, ValueError): return None

class Card:
    __slots__ = ("name", "fd", "pos", "owner", "id", "set_turn")
    def __init__(self, name, owner, fd=False, pos="ATK", cid=None, set_turn=0):
        self.name, self.owner, self.fd, self.pos, self.id, self.set_turn = name, owner, fd, pos, cid, set_turn

class Side:
    def __init__(self, name, deck):
        self.name, self.deck = name, deck
        self.hand, self.gy, self.ban = [], [], []
        self.M, self.S = {}, {}  # slot (1-5) -> Card
        self.lp = 8000
        self.reset_turn()
    def reset_turn(self):
        self.plays = self.summons = self.draws = self.discards = self.owed_draws = self.owed_discards = 0
        self.last = self.last_card = None
        self.history = []

class Duel:
    """One game of a match, rebuilt from its plays."""
    def __init__(self, names, decks, first, info, game_id):
        self.s = {n: Side(n, decks.get(n, 40)) for n in names}
        self.names, self.info, self.game_id = names, info, game_id
        self.turn, self.tp, self.phase = 1, first, "DP"
        self.records, self.winner, self.loser = [], None, None
    def opp(self, n): return self.names[1] if n == self.names[0] else self.names[0]
    def card_info(self, name):
        return self.info.get(name) or {}

    # ---------- Board edits ----------
    def zone(self, actor, text, which=0):
        """The (side, kind, slot) of the which-th zone named in a log line, relative to the actor ("M2-3" is the other side's)."""
        z = ZONE.findall(text)
        if len(z) <= which: return None
        k, two, slot = z[which]
        return (self.opp(actor) if two else actor), k, int(slot)
    def take_from(self, actor, text, name, frm):
        """Removes the card a log line moves, from where the line says it came from. Returns its Card, or a new one."""
        s = self.s[actor]
        if frm.startswith("hand"):
            if name in s.hand: s.hand.remove(name)
            elif s.hand: s.hand.pop()
            return Card(name, actor)
        if frm == "GY":
            for side in (s, self.s[self.opp(actor)]):
                if name in side.gy: side.gy.remove(name); return Card(name, side.name)
            return Card(name, actor)
        if frm == "banished":
            for side in (s, self.s[self.opp(actor)]):
                if name in side.ban: side.ban.remove(name); return Card(name, side.name)
            return Card(name, actor)
        if frm in ("Deck", "Extra Deck"):
            if frm == "Deck": s.deck = max(0, s.deck - 1)
            return Card(name, actor)
        z = self.zone(actor, text)
        if z:
            side, k, slot = z
            c = getattr(self.s[side], k).pop(slot, None)
            if c: return c
        return Card(name, actor)
    def place(self, actor, text, c, which=-1):
        z = ZONE.findall(text)
        if not z: return
        k, two, slot = z[which]
        side = self.opp(actor) if two else actor
        getattr(self.s[side], k)[int(slot)] = c

    def apply(self, p, actor):
        """Updates the board for one play."""
        play = p.get("play")
        logs = p.get("log"); logs = logs if isinstance(logs, list) else [logs] if logs else []
        text = next((l.get("private_log") or l.get("public_log") or "" for l in logs if l.get("type") != "chat"), "")
        q = QUOTED.findall(text)
        name = (p.get("card") or {}).get("name") if isinstance(p.get("card"), dict) else None
        name = name or (q[0].replace('\\"', '"') if q else None)
        s = self.s.get(actor)
        if s is None: return
        m = re.search(r'from (hand|Deck|Extra Deck|GY|[MS]2?-\d)', text)
        frm = m.group(1) if m else ("banished" if " banished " in text else None)
        if play == "Draw card":
            s.hand.append(name or "?"); s.deck = max(0, s.deck - 1)
        elif play == "Life points":
            if p.get("life") is not None: s.lp = num(p["life"])
        elif play in ("Normal Summon", "Set monster", "SS ATK", "SS DEF", "Activate ST", "Set ST", "To ST"):
            if play == "Set monster" and text.startswith("Set ") and " in M" in text and frm is None:
                # Turned face-down where it stands (Book of Moon).
                z = self.zone(actor, text)
                if z and z[2] in getattr(self.s[z[0]], z[1]):
                    c = getattr(self.s[z[0]], z[1])[z[2]]; c.fd, c.pos = True, "DEF"
                return
            if play == "Activate ST" and frm is None:
                z = self.zone(actor, text)
                if z and z[2] in getattr(self.s[z[0]], z[1]): getattr(self.s[z[0]], z[1])[z[2]].fd = False
                return
            c = self.take_from(actor, text, name, frm or "hand")
            c.name, c.id, c.set_turn = name or c.name, p.get("id"), self.turn
            c.fd = play in ("Set monster", "Set ST")
            c.pos = "DEF" if play in ("Set monster", "SS DEF") else "ATK"
            self.place(actor, text, c)
        elif play in ("Flip", "Flip Summon"):
            z = self.zone(actor, text)
            if z and z[2] in getattr(self.s[z[0]], z[1]):
                c = getattr(self.s[z[0]], z[1])[z[2]]; c.fd = False
                if play == "Flip Summon": c.pos = "ATK"
        elif play in ("To ATK", "To DEF"):
            z = self.zone(actor, text)
            if z and z[2] in getattr(self.s[z[0]], z[1]):
                c = getattr(self.s[z[0]], z[1])[z[2]]; c.pos = play[3:]; c.fd = False
        elif play == "Move":
            if frm and frm[0] in "MS":
                c = self.take_from(actor, text, name, frm)
                self.place(actor, text, c, which=1)
        elif play in ("To GY", "Banish", "To hand", "To T Deck", "To B Deck", "Remove Token"):
            if frm is None and play != "Remove Token": return
            c = self.take_from(actor, text, name, frm or "")
            if play == "Remove Token": return
            owner = self.s.get(p.get("owner") or c.owner) or s
            if play == "To GY": owner.gy.append(c.name)
            elif play == "Banish": owner.ban.append(c.name)
            elif play == "To hand": owner.hand.append(c.name)
            else: owner.deck += 1
        elif play == "Summon Token":
            self.place(actor, text, Card("Sheep Token", actor, pos="DEF" if "DEF" in text else "ATK", set_turn=self.turn))

    # ---------- Records ----------
    def card_rec(self, name, zone, fd, pos, reveal):
        p = (("FD" if fd else pos) if zone == "monster" else ("FD" if fd else None))
        if not reveal and (fd or zone == "hand"): return {"zone": zone, "pos": "FD"}
        i = self.card_info(name) if name != "Sheep Token" else {"ctype": "Monster", "atk": 0, "def": 0, "level": 1}
        mon = i.get("ctype") == "Monster"
        return {"name": name, "ctype": i.get("ctype"), "zone": zone, "pos": p,
                "atk": num(i.get("atk")) if mon else None, "def": num(i.get("def")) if mon else None, "level": num(i.get("level")) or None}
    def candidates(self, me):
        """Every play on the menus, the way sim_goat.py lists them: (key, play, card rec, target rec)."""
        s, o, out = self.s[me], self.s[self.opp(me)], []
        add = lambda key, play, card, target=None: out.append({"key": key, "play": play, "card": card, "target": target})
        free_m, free_s = len(s.M) < 5, len(s.S) < 5
        for i, n in enumerate(s.hand):
            info, cr = self.card_info(n), self.card_rec(n, "hand", False, None, True)
            if info.get("ctype") == "Monster":
                if free_m:
                    for p in ("Normal Summon", "Set monster", "SS ATK", "SS DEF"): add(f"card|h{i}|{p}", p, cr)
            else:
                if free_s:
                    if info.get("ctype") == "Spell": add(f"card|h{i}|Activate ST", "Activate ST", cr)
                    add(f"card|h{i}|Set ST", "Set ST", cr)
            add(f"card|h{i}|To GY", "To GY", cr)
        for slot, c in sorted(s.M.items()):
            cr = self.card_rec(c.name, "monster", c.fd, c.pos, True)
            if c.fd: add(f"card|m{slot}|Flip Summon", "Flip Summon", cr)
            else:
                ch = "To DEF" if c.pos == "ATK" else "To ATK"
                add(f"card|m{slot}|{ch}", ch, cr)
                if self.phase == "BP" and c.pos == "ATK":
                    for ts, t in sorted(o.M.items()):
                        add(f"card|m{slot}|Attack|{ts}", "Attack", cr, self.card_rec(t.name, "monster", t.fd, t.pos, False))
                    add(f"card|m{slot}|Attack directly", "Attack directly", cr)
            add(f"card|m{slot}|To GY", "To GY", cr)
        for slot, c in sorted(s.S.items()):
            cr = self.card_rec(c.name, "spell/trap", c.fd, None, True)
            if c.fd: add(f"card|s{slot}|Activate ST", "Activate ST", cr)
            add(f"card|s{slot}|To GY", "To GY", cr)
        if s.deck:
            add("deck|Draw card", "Draw card", {"zone": "deck"}); add("deck|Shuffle deck", "Shuffle deck", {"zone": "deck"})
        for g in GLOBAL_PLAYS: add(f"global|{g}", g, None)
        return out
    def build_record(self, me):
        s, o = self.s[me], self.s[self.opp(me)]
        light = sum(self.card_info(n).get("attr") == "LIGHT" for n in s.gy)
        dark = sum(self.card_info(n).get("attr") == "DARK" for n in s.gy)
        return {"v": 2, "turn": self.turn, "phase": self.phase, "myTurn": True, "playsThisTurn": s.plays, "summonsThisTurn": s.summons,
                "drawsThisTurn": s.draws, "discardsThisTurn": s.discards, "lastPlay": s.last, "lastCard": s.last_card, "turnHistory": list(s.history),
                "solo": False, "fmt": "goat", "duel": self.game_id, "player": me,
                "me": {"lp": s.lp, "deck": s.deck, "hand": [self.card_rec(n, "hand", False, None, True) for n in s.hand],
                       "mon": [self.card_rec(c.name, "monster", c.fd, c.pos, True) for _, c in sorted(s.M.items())],
                       "st": [self.card_rec(c.name, "spell/trap", c.fd, None, True) for _, c in sorted(s.S.items())],
                       "gy": len(s.gy), "gyLight": light, "gyDark": dark, "ban": len(s.ban)},
                "opp": {"lp": o.lp, "deck": o.deck, "hand": len(o.hand),
                        "mon": [self.card_rec(c.name, "monster", c.fd, c.pos, False) for _, c in sorted(o.M.items())],
                        "st": [self.card_rec(c.name, "spell/trap", c.fd, None, False) for _, c in sorted(o.S.items())],
                        "gy": len(o.gy), "ban": len(o.ban)},
                "cands": self.candidates(me)}
    def chosen_key(self, p, actor, text):
        """The candidate key for a play the turn player made, or None when it isn't one of the auto-player's decisions."""
        play, s = p.get("play"), self.s[actor]
        q = [x.replace('\\"', '"') for x in QUOTED.findall(text)]
        name = (p.get("card") or {}).get("name") if isinstance(p.get("card"), dict) else (q[0] if q else None)
        # The start of the turn: draw, then on to the Standby Phase and Main Phase 1. There's no choice in it, but the
        # model has to learn it, as it picks the extension's plays in every phase.
        if self.phase == "DP" and play == "Draw card" and s.draws == 0:
            return "deck|Draw card"
        if play in ("Enter SP", "Enter M1") and self.phase in ("DP", "SP"):
            return f"global|{play}"
        if play in ("Enter BP", "Enter M2"):
            return f"global|{play}" if self.phase in ("M1", "BP") else None
        if play in ("End turn", "Enter EP"):
            return "global|End turn" if self.phase in ("M1", "BP", "M2") else None
        if self.phase not in ("M1", "BP", "M2"): return None
        if play == "Draw card": return "deck|Draw card" if s.owed_draws > 0 else None
        from_hand = "from hand" in text
        def hand_key(p_):
            n = q[0] if q else name
            return f"card|h{s.hand.index(n)}|{p_}" if n in s.hand else None
        def slot_key(p_, kind="M"):
            z = self.zone(actor, text)
            return f"card|{kind.lower()}{z[2]}|{p_}" if z and z[0] == actor and z[1] == kind and z[2] in getattr(s, kind) else None
        if play in ("Normal Summon", "SS ATK", "SS DEF"):
            return hand_key(play) if from_hand else None
        if play == "Set monster":
            return hand_key(play) if from_hand else None
        if play == "Set ST":
            return hand_key(play) if from_hand else None
        if play == "Activate ST":
            return hand_key(play) if from_hand else slot_key(play, "S")
        if play in ("Flip Summon", "To ATK", "To DEF"):
            return slot_key(play)
        if play == "Attack directly":
            return slot_key(play) if self.phase == "BP" else None
        if play == "Attack":
            if self.phase != "BP": return None
            z = ZONE.findall(text)  # 'Attacked "T" in M-a with "A" in M-b': the target is on the other side
            if len(z) < 2: return None
            ts, as_ = int(z[0][2]), int(z[1][2])
            if as_ in s.M and ts in self.s[self.opp(actor)].M: return f"card|m{as_}|Attack|{ts}"
            return None
        if play == "To GY" and from_hand and (name == "Thunder Dragon" or s.owed_discards > 0):
            return hand_key(play)
        return None
    def count(self, actor, play, text, name):
        """The turn's bookkeeping for a recorded decision. Only decisions count, as in the simulator: the
        human's other clicks (sending a resolved spell to the Graveyard, say) aren't plays the model makes."""
        s = self.s[actor]
        s.plays += 1
        if play in ("Normal Summon", "Set monster") and "from hand" in text: s.summons += 1
        if play == "Draw card": s.draws += 1; s.owed_draws = max(0, s.owed_draws - 1)
        if play == "To GY" and "from hand" in text:
            s.discards += 1; s.owed_discards = max(0, s.owed_discards - 1)
        if play == "Activate ST": s.owed_draws += EFFECT_DRAWS.get(name, 0)
        if play == "Activate ST" and name == "Graceful Charity": s.owed_discards = 2
        if play == "Flip Summon" and name == "Dekoichi the Battlechanted Locomotive": s.owed_draws += 1
        own = name if play not in GLOBAL_PLAYS and play not in ("Draw card", "Shuffle deck") else None
        h = f"{play}:{own or ''}"
        if h not in s.history: s.history.append(h)
        s.last, s.last_card = play, own

    def step(self, p):
        play, actor = p.get("play"), p.get("username")
        if actor not in self.s: return
        logs = p.get("log"); logs = logs if isinstance(logs, list) else [logs] if logs else []
        text = next((l.get("private_log") or l.get("public_log") or "" for l in logs if l.get("type") != "chat"), "")
        if play == "Start turn":
            if actor != self.tp: self.turn += 1
            self.tp, self.phase = actor, "DP"
            self.s[actor].reset_turn()
            return
        if play == "Admit defeat":
            self.loser, self.winner = actor, self.opp(actor)
            return
        if actor == self.tp:
            # Built before the play changes anything, so the record shows the board (and phase) the player decided on.
            key = self.chosen_key(p, actor, text)
            if key:
                rec = self.build_record(actor)
                keys = [c["key"] for c in rec["cands"]]
                if key in keys:
                    rec["chosen"] = keys.index(key)
                    self.records.append(rec)
                    q = QUOTED.findall(text)
                    self.count(actor, play, text, (p.get("card") or {}).get("name") if isinstance(p.get("card"), dict) else (q[0] if q else None))
        self.apply(p, actor)
        if play in PHASES and actor == self.tp: self.phase = PHASES[play]
        if play == "End turn" and actor == self.tp: self.phase = "EP"
        # A player at 0 LP has lost, whether or not anyone pressed Admit defeat.
        if play == "Life points" and self.s[actor].lp is not None and self.s[actor].lp <= 0 and not self.winner:
            self.loser, self.winner = actor, self.opp(actor)

def card_infos(replay, db):
    """Card names to type and stats: DuelingBook's card objects in the replay, then the card database."""
    info = dict(db)
    def walk(x):
        if isinstance(x, dict):
            if "serial_number" in x and "name" in x:
                t = x.get("card_type")
                info[x["name"]] = {"ctype": t if t in ("Monster", "Spell", "Trap") else ("Monster" if t else None),
                                   "atk": num(x.get("atk")), "def": num(x.get("def")), "level": num(x.get("level")), "attr": x.get("attribute") or ""}
                return
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(replay.get("plays"))
    return info

def convert(replay, db, rid="?"):
    """Records from one replay, and a summary of each game: (records, [(winner, loser, decisions), ...])."""
    info = card_infos(replay, db)
    p1, p2 = (replay.get("player1") or {}), (replay.get("player2") or {})
    names = [p1.get("username"), p2.get("username")]
    if not all(names) or replay.get("tag_duel"): return [], []
    decks = {p1["username"]: num(p1.get("main_total")) or 40, p2["username"]: num(p2.get("main_total")) or 40}
    out, games, duel, g = [], [], None, 0
    def finish():
        if not duel: return
        for r in duel.records:
            if duel.winner:
                r["won"] = int(r["player"] == duel.winner)
                r["ret"] = 1 if r["won"] else -1
        out.extend(duel.records)
        games.append((duel.winner, duel.loser, len(duel.records)))
    for p in replay.get("plays") or []:
        play = p.get("play")
        if play == "Begin next duel":
            for side in ("player1", "player2"):
                x = p.get(side) or {}
                if x.get("username") in decks: decks[x["username"]] = num(x.get("main_total")) or 40
            continue
        if play == "Pick first":
            finish(); g += 1
            order = p.get("order") or names
            duel = Duel(names, decks, order[0], info, f"{rid}-g{g}")
            for l in p.get("log") or []:
                m = QUOTED.search(l.get("private_log") or "")
                if (l.get("private_log") or "").startswith("Drew") and m and l.get("username") in duel.s:
                    s = duel.s[l["username"]]; s.hand.append(m.group(1).replace('\\"', '"')); s.deck = max(0, s.deck - 1)
            continue
        if duel and not duel.winner: duel.step(p)
    finish()
    return out, games

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default="replay-training.json")
    ap.add_argument("--dir", default=REPLAYS)
    ap.add_argument("--check", metavar="REPLAY ID", help="print one replay's decisions instead of writing a file")
    a = ap.parse_args()
    db = load_card_db()
    if a.check:
        r = json.load(open(os.path.join(a.dir, a.check + ".json"), encoding="utf-8"))
        recs, games = convert(r, db, a.check)
        for rec in recs:
            c = rec["cands"][rec["chosen"]]
            me = rec["me"]
            print(f"{rec['duel']} t{rec['turn']} {rec['phase']} {rec['player'][:12]:12} LP {me['lp']}-{rec['opp']['lp']} hand {len(me['hand'])} "
                  f"mon {len(me['mon'])}v{len(rec['opp']['mon'])}: {c['play']} {(c['card'] or {}).get('name') or ''}"
                  + (f" -> {(c['target'] or {}).get('name') or 'set card'}" if c.get("target") else "") + f"  ({len(rec['cands'])} options)")
        print("Games:", games)
        return
    files = sorted(glob.glob(os.path.join(a.dir, "*.json")))
    if not files: sys.exit("No replays downloaded yet: run python3 tools/fetch_replays.py first.")
    n = n_games = decided = 0
    plays = Counter()
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "ygo-duel-odds-training", "version": 1, "source": "replay_records.py"}, separators=(",", ":"))[:-1] + ',"records":[')
        for path in files:
            rid = os.path.basename(path)[:-5]
            try:
                recs, games = convert(json.load(open(path, encoding="utf-8")), db, rid)
            except Exception as e:
                print(f"  {rid}: skipped ({type(e).__name__}: {e})"); continue
            for rec in recs:
                if n: f.write(",")
                f.write(json.dumps(rec, separators=(",", ":"))); n += 1
                plays[rec["cands"][rec["chosen"]]["play"]] += 1
            n_games += len(games); decided += sum(1 for w, _, _ in games if w)
        f.write("]}")
    print(f"Wrote {n} decisions from {n_games} games in {len(files)} replays ({decided} games with a known winner) to {a.out}")
    print("Plays chosen: " + ", ".join(f"{k} {v}" for k, v in plays.most_common()))

if __name__ == "__main__":
    main()
