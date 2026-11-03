"""A simplified Goat format simulator that writes training decisions for the auto-play model.

Usage:
  python3 tools/sim_goat.py --games 600 -o sim-training.json            # scripted player vs itself
  python3 tools/sim_goat.py --games 200 --model policy.json --eval      # learned model vs scripted player

The decks are in tools/decks/*.txt. Every game deals two of them at random. A scripted player makes each
play using rules of thumb for Goat format: draw spells first, clear backrow, remove threats, summon the best
beater or set a flip monster, attack only into battles it wins, and keep traps for the opponent's turn. Each
play it makes is written in the same record format the extension records (see extension/features.js),
with candidate plays named as DuelingBook's menus name them, so tools/train_policy.py trains on the result
exactly as it would on recorded duels.

This is a rough model of the game, not a rules engine: card effects are simplified, chains are one deep,
and the opponent's traps follow fixed habits. A model trained on it learns the scripted player's habits for
each deck, which makes a reasonable starting point before you record your own duels.
"""
import argparse, json, math, os, random, sys, time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GLOBAL_PLAYS = ["Enter DP", "Enter SP", "Enter M1", "Enter BP", "Enter M2", "Enter EP", "End turn"]
MAX_TURNS = 40

# ---------- Cards ----------
def load_cards():
    path = os.path.join(HERE, ".cache", "cardinfo_misc.json")
    if not os.path.exists(path):
        sys.exit("Card data missing: run python3 tools/train_decks.py once to download it.")
    return {c["name"]: c for c in json.load(open(path, encoding="utf-8"))}

def load_decks(names):
    decks = {}
    for fn in sorted(os.listdir(os.path.join(HERE, "decks"))):
        if not fn.endswith(".txt"): continue
        title, cards = fn[:-4], []
        for line in open(os.path.join(HERE, "decks", fn), encoding="utf-8"):
            line = line.strip()
            if line.startswith("# ") and title == fn[:-4]: title = line[2:]; continue
            if not line or line.startswith("#"): continue
            n, name = line.split(" ", 1)
            cards += [name] * int(n)
        if names and fn[:-4] not in names: continue
        decks[fn[:-4]] = (title, cards)
    return decks

def load_fl_decks(n):
    """The n most recent Format Library topping Goat decks (cached by tools/train_decks.py), titled by deck type."""
    lp, dp = os.path.join(HERE, ".cache", "fl_list_goat.json"), os.path.join(HERE, ".cache", "fl_decks_goat.json")
    if not os.path.exists(dp): sys.exit("Format Library decks missing: run python3 tools/train_decks.py once to download them.")
    meta = {str(r["id"]): r for r in json.load(open(lp, encoding="utf-8"))}
    got = json.load(open(dp, encoding="utf-8"))
    rows = sorted(((meta.get(k, {}).get("publishDate") or "", k, v) for k, v in got.items() if 40 <= len(v.get("names") or []) <= 60), reverse=True)
    decks = {}
    for date, k, v in rows[:n]:
        decks["fl" + k] = (meta.get(k, {}).get("deckTypeName") or "Other", [x for x in v["names"] if x])
    return decks

ATK_TRAPS = {"Mirror Force", "Sakuretsu Armor", "Compulsory Evacuation Device", "Ring of Destruction", "Raigeki Break"}
SUM_TRAPS = {"Torrential Tribute", "Solemn Judgment", "Compulsory Evacuation Device"}
FLIP = {"Magician of Faith", "Gravekeeper's Spy", "Dekoichi the Battlechanted Locomotive", "Night Assailant"}
SPECIAL = {"Black Luster Soldier - Envoy of the Beginning", "Chaos Sorcerer", "Swift Gaia the Fierce Knight"}
DRAW_SPELLS = {"Pot of Greed", "Graceful Charity", "Upstart Goblin"}
ATK_TRAPS |= {"Magic Cylinder"}
SUM_TRAPS |= {"Bottomless Trap Hole", "Phoenix Wing Wind Blast"}
FLIP |= {"Morphing Jar", "Cyber Jar", "Magical Merchant", "Des Koala", "Mask of Darkness", "Dark Mimic LV1"}
# Cards that stay face-up on the field once activated, and what they lock.
CONTINUOUS = {"Royal Decree", "Gravity Bind", "Level Limit - Area B", "Swords of Revealing Light", "Skill Drain"}
NO_BIG_ATTACKS = {"Gravity Bind", "Level Limit - Area B"}
# Monsters that search a monster of an attribute when destroyed by battle, with 1500 or less ATK.
FLOATERS = {"Mystic Tomato": "DARK", "Giant Rat": "EARTH", "Shining Angel": "LIGHT"}
# Spells the scripted player casts as removal or plusses on its own turn, with when they're worth it.
STEALS = {"Snatch Steal", "Creature Swap", "Metamorphosis", "Mind Control", "Brain Control"}

class Card:
    __slots__ = ("uid", "name", "kind", "race", "atk", "def_", "level", "attr", "mtype", "fd", "pos", "set_turn", "attacked", "token")
    def __init__(self, uid, name, info):
        self.uid, self.name = uid, name
        t = info["type"] if info else "Token"
        self.kind = "Monster" if "Monster" in t or t == "Token" else "Spell" if "Spell" in t else "Trap"
        self.race = (info or {}).get("race", "")
        self.atk = (info or {}).get("atk", 0) or 0
        self.def_ = (info or {}).get("def", 0) or 0
        self.level = (info or {}).get("level", 0) or 0
        self.attr = (info or {}).get("attribute", "")
        self.mtype = (info or {}).get("race", "")
        self.fd, self.pos, self.set_turn, self.attacked, self.token = False, "ATK", 0, False, info is None

class Player:
    def __init__(self, name, deck_title, cards, rnd):
        self.name, self.deck_title = name, deck_title
        self.deck = cards[:]; rnd.shuffle(self.deck)
        self.hand, self.mon, self.st, self.gy, self.ban = [], [], [], [], []
        self.lp, self.plays, self.summons, self.obligations = 8000, 0, 0, []
        self.skip_draw, self.drew = False, False
        self.draws, self.discards, self.last, self.last_card, self.history = 0, 0, None, None, []
        self.borrowed, self.no_attack_turns, self.lost_monster = [], 0, False

# ---------- Game ----------
class Game:
    def __init__(self, decks, cards, rnd, policies, record, duel_id):
        self.cards, self.rnd, self.policies, self.record, self.duel_id = cards, rnd, policies, record, duel_id
        self.uid = 0
        keys = list(decks)
        a, b = rnd.choice(keys), rnd.choice(keys)
        self.p = [Player("P1", decks[a][0], [self.make(n) for n in decks[a][1]], rnd),
                  Player("P2", decks[b][0], [self.make(n) for n in decks[b][1]], rnd)]
        self.records, self.turn, self.active, self.phase, self.winner = [], 1, rnd.randrange(2), "DP", None
        for pl in self.p:
            for _ in range(5): self.draw(pl)

    def make(self, name):
        self.uid += 1
        return Card(str(self.uid), name, self.cards.get(name))

    def opp(self, pl): return self.p[1] if pl is self.p[0] else self.p[0]

    def draw(self, pl):
        if not pl.deck: self.winner = self.opp(pl); return None
        c = pl.deck.pop(); pl.hand.append(c); return c

    def to_gy(self, pl, c, banish=False):
        if c in pl.mon and not c.token: pl.lost_monster = True
        for zone in (pl.hand, pl.mon, pl.st):
            if c in zone: zone.remove(c)
        # A borrowed monster goes to its owner's graveyard, and isn't handed back at the end of the turn.
        for who in self.p:
            for b in who.borrowed[:]:
                if b[0] is c: who.borrowed.remove(b)
        c.fd, c.attacked, c.pos = False, False, "ATK"
        if c.token: return
        (pl.ban if banish else pl.gy).append(c)
        # Sangan: when it goes to the graveyard from the field, search a monster with 1500 or less ATK.
        if c.name == "Sangan" and not banish:
            opts = [x for x in pl.deck if x.kind == "Monster" and x.atk <= 1500]
            if opts:
                best = max(opts, key=lambda x: (x.name in FLIP, x.atk)); pl.deck.remove(best); pl.hand.append(best)

    def destroy(self, owner_of, c, banish=False):
        for pl in self.p:
            if c in pl.mon or c in pl.st or c in pl.hand:
                if c.name == "Spirit Reaper" and banish is None: return False
                self.to_gy(pl, c, banish=bool(banish)); return True
        return False

    def damage(self, pl, n):
        pl.lp -= max(0, int(n))
        if pl.lp <= 0: self.winner = self.opp(pl)

    def eff_atk(self, pl, c):
        if c.name == "Blade Knight" and len(pl.hand) <= 1: return 2000
        if c.name == "Gyaku-Gire Panda": return c.atk + 500 * len(self.opp(pl).mon)
        return c.atk

    def face_up(self, names):
        return any(x.name in names and not x.fd for pl in self.p for x in pl.st + pl.mon)

    def traps_locked(self):
        """Jinzo or a face-up Royal Decree stops every trap."""
        return self.face_up({"Jinzo", "Royal Decree"})

    def battle_destroy(self, owner, c):
        """Destroys c by battle, and runs what triggers on it."""
        if not self.destroy(owner, c, banish=None): return
        attr = FLOATERS.get(c.name)
        if attr and len(owner.mon) < 5:
            opts = [x for x in owner.deck if x.kind == "Monster" and x.attr == attr and x.atk <= 1500]
            if opts:
                best = max(opts, key=lambda x: x.atk); owner.deck.remove(best); best.fd, best.pos = False, "ATK"; owner.mon.append(best)

    # ---------- What the player could do: named as DuelingBook's menus name them ----------
    def candidates(self, pl):
        op, cands = self.opp(pl), []
        add = lambda key, play, card, target=None: cands.append((key, play, card, target))
        free_mon, free_st = len(pl.mon) < 5, len(pl.st) < 5
        for c in pl.hand:
            if c.kind == "Monster":
                if free_mon:
                    for p in ("Normal Summon", "Set monster", "SS ATK", "SS DEF"): add(f"card|{c.uid}|{p}", p, c)
            else:
                if free_st:
                    if c.kind == "Spell": add(f"card|{c.uid}|Activate ST", "Activate ST", c)
                    add(f"card|{c.uid}|Set ST", "Set ST", c)
            add(f"card|{c.uid}|To GY", "To GY", c)
        for c in pl.mon:
            if c.fd: add(f"card|{c.uid}|Flip Summon", "Flip Summon", c)
            else:
                add(f"card|{c.uid}|{'To DEF' if c.pos == 'ATK' else 'To ATK'}", "To DEF" if c.pos == "ATK" else "To ATK", c)
                if self.phase == "BP" and c.pos == "ATK":
                    for t in op.mon: add(f"card|{c.uid}|Attack|{t.uid}", "Attack", c, t)
                    add(f"card|{c.uid}|Attack directly", "Attack directly", c)
            add(f"card|{c.uid}|To GY", "To GY", c)
        for c in pl.st:
            if c.fd: add(f"card|{c.uid}|Activate ST", "Activate ST", c)
            add(f"card|{c.uid}|To GY", "To GY", c)
        if pl.deck:
            add("deck|Draw card", "Draw card", None); add("deck|Shuffle deck", "Shuffle deck", None)
        for g in GLOBAL_PLAYS: add(f"global|{g}", g, None)
        return cands

    # ---------- Records, in the extension's format ----------
    def card_rec(self, c, zone, reveal):
        pos = (("FD" if c.fd else c.pos) if zone == "monster" else ("FD" if c.fd else None))
        if not reveal and (c.fd or zone == "hand"): return {"zone": zone, "pos": "FD"}
        lvl = c.level or None
        return {"name": c.name if not c.token else "Sheep Token", "ctype": c.kind, "zone": zone, "pos": pos,
                "atk": c.atk if c.kind == "Monster" else None, "def": c.def_ if c.kind == "Monster" else None, "level": lvl}

    def build_record(self, pl, cands):
        op = self.opp(pl)
        zone_of = lambda c: "hand" if c in pl.hand else "monster" if c in pl.mon else "spell/trap" if c in pl.st else "deck"
        return {"v": 2, "turn": self.turn, "phase": self.phase, "myTurn": True, "playsThisTurn": pl.plays, "summonsThisTurn": pl.summons,
                "drawsThisTurn": pl.draws, "discardsThisTurn": pl.discards, "lastPlay": pl.last, "lastCard": pl.last_card, "turnHistory": list(pl.history),
                "solo": True, "fmt": "goat", "duel": self.duel_id, "deck": pl.deck_title,
                "me": {"lp": pl.lp, "deck": len(pl.deck), "hand": [self.card_rec(c, "hand", True) for c in pl.hand],
                       "mon": [self.card_rec(c, "monster", True) for c in pl.mon], "st": [self.card_rec(c, "spell/trap", True) for c in pl.st],
                       "gy": len(pl.gy), "gyLight": sum(x.attr == "LIGHT" for x in pl.gy), "gyDark": sum(x.attr == "DARK" for x in pl.gy), "ban": len(pl.ban)},
                "opp": {"lp": op.lp, "deck": len(op.deck), "hand": len(op.hand), "mon": [self.card_rec(c, "monster", False) for c in op.mon],
                        "st": [self.card_rec(c, "spell/trap", False) for c in op.st], "gy": len(op.gy), "ban": len(op.ban)},
                "cands": [{"key": k, "play": p, "card": self.card_rec(c, zone_of(c), True) if c else ({"zone": "deck"} if k.startswith("deck|") else None),
                           "target": self.card_rec(t, "monster", False) if t else None} for k, p, c, t in cands]}

    # ---------- Playing a turn ----------
    def play_turn(self):
        pl = self.p[self.active]
        pl.plays = pl.summons = pl.draws = pl.discards = 0; pl.drew = False; pl.last = pl.last_card = None; pl.history = []; self.phase = "DP"
        for c in pl.mon: c.attacked = False
        # Sinister Serpent comes back to the hand in the Standby Phase.
        for c in [x for x in pl.gy if x.name == "Sinister Serpent"][:1]: pl.gy.remove(c); pl.hand.append(c)
        pl.lost_monster = False
        self.continue_turn()

    MAX_PLAYS = 80
    def continue_turn(self):
        """Plays the active player's turn from wherever it is, then ends it."""
        pl = self.p[self.active]
        policy = self.policies[self.active]
        while pl.plays < self.MAX_PLAYS:
            if self.winner: return
            cands = self.candidates(pl)
            keys = [k for k, _, _, _ in cands]
            choice = policy(self, pl, cands)
            if choice not in keys: choice = "global|End turn"
            if self.record:
                # The record holds the teacher's choice and, when the teacher measured them, the value of each play.
                # With a separate labeller (DAgger), the game goes on with the actor's play, not the teacher's.
                teacher = self.labellers[self.active] if getattr(self, "labellers", None) else policy
                label = choice if teacher is policy else teacher(self, pl, cands)
                if label not in keys: label = "global|End turn"
                rec = self.build_record(pl, cands); rec["chosen"] = keys.index(label)
                vals = getattr(teacher, "values", None)
                if vals: rec["cvals"] = [round(vals[k], 4) if k in vals else None for k in keys]
                self.records.append(rec)
            if self.step(pl, choice): break
        self.end_turn()

    def step(self, pl, choice):
        """Makes one play and keeps the turn's bookkeeping. Returns True when the turn ends."""
        pl.plays += 1
        parts = choice.split("|")
        card = next((x for x in pl.hand + pl.mon + pl.st if parts[0] == "card" and x.uid == parts[1]), None)
        pl.last = parts[2] if parts[0] == "card" else parts[1]
        pl.last_card = card.name if card else None
        if choice == "deck|Draw card": pl.draws += 1
        if pl.last == "To GY" and card in pl.hand: pl.discards += 1
        h = f"{pl.last}:{pl.last_card or ''}"
        if h not in pl.history: pl.history.append(h)
        return self.apply(pl, choice)

    def end_turn(self):
        pl, op = self.p[self.active], self.p[1 - self.active]
        # Whatever an effect still owes ends with the turn: missing draws are lost, and missing discards are made at random.
        for kind, n in pl.obligations:
            if kind == "discard":
                for _ in range(min(n, len(pl.hand))): self.to_gy(pl, self.rnd.choice(pl.hand))
        pl.obligations = []
        # Monsters taken until the end of the turn go back, and ones brought back for the turn are banished.
        for c, how in pl.borrowed[:]:
            if c in pl.mon:
                pl.mon.remove(c)
                if how == "return" and len(op.mon) < 5: c.attacked = False; op.mon.append(c)
                elif how == "return": op.gy.append(c)
                else: pl.ban.append(c)
        pl.borrowed = []
        if pl.no_attack_turns: pl.no_attack_turns -= 1
        self.active, self.turn = 1 - self.active, self.turn + 1

    # ---------- Copies for looking ahead ----------
    IDENTITY = ("name", "kind", "race", "atk", "def_", "level", "attr", "mtype", "token")
    def clone(self, viewer, rnd):
        """A copy of the game as the viewer could imagine it: their own deck reshuffled, and the opponent's hidden
        cards (hand, deck, face-down cards) dealt again at random, so a look-ahead can't use what they can't see."""
        cmap = {}
        def cc(c):
            if c is None: return None
            n = cmap.get(id(c))
            if n is None:
                n = Card.__new__(Card)
                for f in Card.__slots__: setattr(n, f, getattr(c, f))
                cmap[id(c)] = n
            return n
        g = Game.__new__(Game)
        g.cards, g.rnd, g.policies, g.record, g.duel_id = self.cards, rnd, list(self.policies), False, self.duel_id
        g.uid, g.records, g.turn, g.active, g.phase, g.winner = self.uid, [], self.turn, self.active, self.phase, None
        g.p = []
        for pl in self.p:
            q = Player.__new__(Player)
            q.__dict__.update(pl.__dict__)
            for z in ("deck", "hand", "mon", "st", "gy", "ban"): setattr(q, z, [cc(c) for c in getattr(pl, z)])
            q.obligations, q.history = list(pl.obligations), list(pl.history)
            q.borrowed = [(cc(c), how) for c, how in pl.borrowed]
            g.p.append(q)
        me = g.p[self.p.index(viewer)]; op = g.opp(me)
        rnd.shuffle(me.deck)
        fd_mon = [c for c in op.mon if c.fd]; fd_st = [c for c in op.st if c.fd]; loose = op.hand + op.deck
        ids = [tuple(getattr(c, f) for f in self.IDENTITY) for c in fd_mon + fd_st + loose]
        rnd.shuffle(ids)
        pick = lambda want: next(i for i, x in enumerate(ids) if (x[1] == "Monster") == want)
        out = []
        for slot in fd_mon + fd_st:
            out.append((slot, ids.pop(pick(slot in fd_mon))))
        out += list(zip(loose, ids))
        for c, ident in out:
            for f, v in zip(self.IDENTITY, ident): setattr(c, f, v)
        return g, me

    def value(self, pl):
        """How good the position is for pl, from -1 to 1."""
        if self.winner: return 1.0 if self.winner is pl else -1.0
        op = self.opp(pl)
        cards = lambda p: len(p.hand) + len(p.mon) + len(p.st)
        power = lambda p: sum(self.eff_atk(p, x) for x in p.mon if not x.fd) / 1000
        return math.tanh((pl.lp - op.lp) / 4000 + 0.25 * (cards(pl) - cards(op)) + 0.1 * (power(pl) - power(op)))

    def apply(self, pl, key):
        """Carries out one play. Returns True when the turn ends."""
        op, parts = self.opp(pl), key.split("|")
        if parts[0] == "global":
            g = parts[1]
            if g == "End turn": return True
            self.phase = {"Enter DP": "DP", "Enter SP": "SP", "Enter M1": "M1", "Enter BP": "BP", "Enter M2": "M2", "Enter EP": "EP"}[g]
            return False
        if parts[0] == "deck":
            if parts[1] == "Draw card":
                c = self.draw(pl)
                if self.phase == "DP" and not pl.drew:
                    pl.drew = True
                    if c and pl.skip_draw: pl.skip_draw = False; pl.hand.remove(c); pl.deck.append(c)
                    # Drop Off: they discard the card they just drew.
                    elif c: self.respond(op, "draw", c)
                if pl.obligations and pl.obligations[0][0] == "draw":
                    n = pl.obligations[0][1] - 1
                    pl.obligations[0] = ("draw", n)
                    if n <= 0: pl.obligations.pop(0)
            elif parts[1] == "Shuffle deck": self.rnd.shuffle(pl.deck)
            return False
        uid, play = parts[1], parts[2]
        c = next((x for x in pl.hand + pl.mon + pl.st if x.uid == uid), None)
        if not c: return False
        if play == "To GY":
            in_hand = c in pl.hand
            self.to_gy(pl, c)
            if pl.obligations and pl.obligations[0][0] == "discard" and in_hand:
                n = pl.obligations[0][1] - 1
                pl.obligations[0] = ("discard", n)
                if n <= 0: pl.obligations.pop(0)
            elif c.name == "Thunder Dragon" and in_hand:
                for td in [x for x in pl.deck if x.name == "Thunder Dragon"][:2]: pl.deck.remove(td); pl.hand.append(td)
            return False
        if play in ("Normal Summon", "Set monster", "SS ATK", "SS DEF"):
            self.summon(pl, c, play); return False
        if play == "Flip Summon":
            # A monster can't be Flip Summoned the turn it was Set.
            if c.set_turn >= self.turn: return False
            c.fd, c.pos = False, "ATK"; self.flip_effect(pl, c); self.respond(op, "summon", c); return False
        if play in ("To DEF", "To ATK"):
            c.pos = "DEF" if play == "To DEF" else "ATK"; return False
        if play == "Set ST":
            pl.hand.remove(c); c.fd, c.set_turn = True, self.turn; pl.st.append(c); return False
        if play == "Activate ST":
            self.activate(pl, c); return False
        if play in ("Attack", "Attack directly"):
            self.attack(pl, c, parts[3] if len(parts) > 3 else None); return False
        return False

    def summon(self, pl, c, play):
        op = self.opp(pl)
        tributes = 0 if play.startswith("SS") else (2 if c.level >= 7 else 1 if c.level >= 5 else 0)
        if play.startswith("SS") and c.name in ("Black Luster Soldier - Envoy of the Beginning", "Chaos Sorcerer"):
            light = [x for x in pl.gy if x.attr == "LIGHT"]; dark = [x for x in pl.gy if x.attr == "DARK"]
            if not light or not dark: return
            for x in (light[0], dark[0]): pl.gy.remove(x); pl.ban.append(x)
        if tributes:
            fodder = sorted([x for x in pl.mon], key=lambda x: x.atk)[:tributes]
            if len(fodder) < tributes: return
            for x in fodder: self.to_gy(pl, x)
        pl.hand.remove(c); pl.mon.append(c)
        c.fd = play == "Set monster"; c.pos = "DEF" if play in ("Set monster", "SS DEF") else "ATK"; c.attacked = False; c.set_turn = self.turn
        if play in ("Normal Summon", "Set monster"): pl.summons += 1
        if c.fd: return
        if self.respond(op, "summon", c): return
        # On-summon effects.
        if c.name == "Breaker the Magical Warrior" and op.st: self.destroy(op, self.rnd.choice(op.st))
        elif c.name == "Exiled Force" and op.mon:
            self.destroy(op, max(op.mon, key=lambda x: x.atk)); self.to_gy(pl, c)
        elif c.name == "Tsukuyomi":
            up = [x for x in op.mon if not x.fd]
            if up: t = max(up, key=lambda x: x.atk); t.fd, t.pos = True, "DEF"
        elif c.name in ("Black Luster Soldier - Envoy of the Beginning", "Chaos Sorcerer"):
            ts = [x for x in op.mon if not x.fd] if c.name == "Chaos Sorcerer" else op.mon
            if ts: self.destroy(op, max(ts, key=lambda x: x.atk), banish=True)
        elif c.name == "Zaborg the Thunder Monarch" and tributes and op.mon: self.destroy(op, max(op.mon, key=lambda x: x.atk))
        elif c.name == "Mobius the Frost Monarch" and tributes:
            for x in op.st[:2]: self.destroy(op, x)
        elif c.name == "Dark Magician of Chaos" and tributes:
            sp = [x for x in pl.gy if x.kind == "Spell"]
            if sp: best = next((x for x in sp if x.name in DRAW_SPELLS), sp[-1]); pl.gy.remove(best); pl.hand.append(best)
        # Ignition effects used as soon as the monster lands: discard a card for the effect.
        elif c.name == "Tribe-Infecting Virus" and pl.hand:
            up = [x for x in op.mon if not x.fd]
            if up:
                race = Counter(x.race for x in up).most_common(1)[0][0]
                self.to_gy(pl, min(pl.hand, key=lambda x: (x.name in DRAW_SPELLS, x.atk)))
                for x in [x for p2 in self.p for x in p2.mon if not x.fd and x.race == race and x is not c]:
                    self.destroy(op if x in op.mon else pl, x)
        elif c.name == "Abyss Soldier" and pl.hand and op.mon:
            self.to_gy(pl, min(pl.hand, key=lambda x: (x.name in DRAW_SPELLS, x.atk)))
            t = max(op.mon, key=lambda x: x.atk); op.mon.remove(t); t.fd, t.pos = False, "ATK"; op.hand.append(t)

    def flip_effect(self, pl, c):
        op = self.opp(pl)
        if c.name == "Magician of Faith":
            sp = [x for x in pl.gy if x.kind == "Spell"]
            if sp: best = next((x for x in sp if x.name in DRAW_SPELLS), sp[-1]); pl.gy.remove(best); pl.hand.append(best)
        elif c.name == "Gravekeeper's Spy":
            spy = next((x for x in pl.deck if x.name == "Gravekeeper's Spy"), None)
            if spy and len(pl.mon) < 5: pl.deck.remove(spy); spy.pos = "DEF"; pl.mon.append(spy)
        elif c.name == "Dekoichi the Battlechanted Locomotive": self.draw(pl)
        elif c.name == "Night Assailant" and op.mon: self.destroy(op, max(op.mon, key=lambda x: x.atk))
        elif c.name == "Morphing Jar":
            for who in (pl, op):
                for x in who.hand[:]: self.to_gy(who, x)
                for _ in range(5): self.draw(who)
        elif c.name == "Cyber Jar":
            for who in (pl, op):
                for x in who.mon[:]: self.destroy(who, x)
                for _ in range(2): self.draw(who)
        elif c.name == "Magical Merchant":
            while pl.deck:
                x = pl.deck.pop()
                if x.kind != "Monster": pl.hand.append(x); break
                pl.gy.append(x)
        elif c.name == "Des Koala": self.damage(op, 400 * len(op.hand))
        elif c.name == "Mask of Darkness":
            tr = [x for x in pl.gy if x.kind == "Trap"]
            if tr: pl.gy.remove(tr[-1]); pl.hand.append(tr[-1])
        elif c.name == "Dark Mimic LV1": self.draw(pl)

    def activate(self, pl, c):
        op = self.opp(pl)
        if c in pl.st and c.fd and c.kind == "Trap" and c.set_turn >= self.turn: return
        if c.kind == "Trap" and self.traps_locked(): return
        n = c.name
        if c in pl.hand: pl.hand.remove(c)
        if c in pl.st: pl.st.remove(c)
        c.fd = False
        if self.respond(op, "spell", c): pl.gy.append(c); return
        if n == "Pot of Greed": pl.obligations.append(("draw", 2))
        elif n == "Upstart Goblin": pl.obligations.append(("draw", 1)); op.lp += 1000
        elif n == "Giant Trunade":
            for who in (pl, op):
                for x in who.st[:]: who.st.remove(x); x.fd = False; who.hand.append(x)
        elif n in ("Mind Control", "Brain Control") and op.mon and len(pl.mon) < 5:
            if n == "Brain Control": self.damage(pl, 800)
            ts = [x for x in op.mon if not x.fd] or op.mon
            t = max(ts, key=lambda x: x.atk); op.mon.remove(t); t.fd, t.pos, t.attacked = False, "ATK", False; pl.mon.append(t); pl.borrowed.append((t, "return"))
        elif n == "Smashing Ground":
            up = [x for x in op.mon if not x.fd]
            if up: self.destroy(op, max(up, key=lambda x: x.def_))
        elif n == "Lightning Vortex" and pl.hand:
            self.to_gy(pl, min(pl.hand, key=lambda x: (x.name in DRAW_SPELLS, x.atk)))
            for x in [x for x in op.mon if not x.fd]: self.destroy(op, x)
        elif n == "Swords of Revealing Light":
            op.no_attack_turns = 3
            for x in op.mon: x.fd = False
        elif n == "Enemy Controller":
            up = [x for x in op.mon if not x.fd and x.pos == "ATK"]
            if up: max(up, key=lambda x: x.atk).pos = "DEF"
        elif n == "Phoenix Wing Wind Blast" and pl.hand and (op.mon or op.st):
            self.to_gy(pl, min(pl.hand, key=lambda x: (x.name in DRAW_SPELLS, x.atk)))
            t = max(op.mon, key=lambda x: x.atk) if op.mon else op.st[0]
            (op.mon if t in op.mon else op.st).remove(t); t.fd, t.pos = False, "ATK"; op.deck.append(t)
        elif n in ("Just Desserts", "Secret Barrel", "Ceasefire"):
            self.damage(op, {"Just Desserts": 500 * len(op.mon), "Secret Barrel": 200 * (len(op.hand) + len(op.mon) + len(op.st)),
                             "Ceasefire": 500 * sum(1 for p2 in self.p for x in p2.mon if x.fd or not x.token)}[n])
            if n == "Ceasefire":
                for p2 in self.p:
                    for x in p2.mon: x.fd = False
        elif n == "Ojama Trio":
            for _ in range(min(3, 5 - len(op.mon))):
                t = Card("t" + str(self.rnd.random())[2:9], "Ojama Token", None); t.pos, t.def_ = "DEF", 1000; op.mon.append(t)
        elif n == "Time Seal": op.skip_draw = True
        elif n in ("Reasoning", "Monster Gate"):
            if n == "Monster Gate":
                if not pl.mon: pl.gy.append(c); return
                self.to_gy(pl, min(pl.mon, key=lambda x: x.atk))
            while pl.deck and len(pl.mon) < 5:
                x = pl.deck.pop()
                if x.kind == "Monster" and "Ritual" not in (self.cards.get(x.name) or {}).get("type", "") and "Fusion" not in (self.cards.get(x.name) or {}).get("type", ""):
                    x.fd, x.pos = False, "ATK"; pl.mon.append(x); break
                pl.gy.append(x)
        elif n == "Last Will" and len(pl.mon) < 5:
            opts = [x for x in pl.deck if x.kind == "Monster" and x.atk <= 1500]
            if opts and pl.lost_monster:
                best = max(opts, key=lambda x: (x.name in FLIP or x.name in FLOATERS, x.atk)); pl.deck.remove(best); best.fd, best.pos = False, "DEF"; pl.mon.append(best)
        elif n in ("Dimension Fusion", "Return from the Different Dimension"):
            self.damage(pl, 2000 if n == "Dimension Fusion" else pl.lp // 2)
            for x in sorted([x for x in pl.ban if x.kind == "Monster"], key=lambda x: -x.atk)[:min(2 if n == "Dimension Fusion" else 5, 5 - len(pl.mon))]:
                pl.ban.remove(x); x.fd, x.pos, x.attacked = False, "ATK", False; pl.mon.append(x)
                if n == "Return from the Different Dimension": pl.borrowed.append((x, "banish"))
        elif n == "United We Stand" and pl.mon:
            max(pl.mon, key=lambda x: x.atk).atk += 800 * len(pl.mon)
        elif n == "Graceful Charity": pl.obligations += [("draw", 3), ("discard", 2)]
        elif n == "Jar of Greed": pl.obligations.append(("draw", 1))
        elif n == "Card Destruction":
            for who in (pl, op):
                k = len(who.hand)
                for x in who.hand[:]: self.to_gy(who, x)
                for _ in range(k): self.draw(who)
        elif n == "Delinquent Duo":
            self.damage(pl, 1000)
            for _ in range(min(2, len(op.hand))): self.to_gy(op, self.rnd.choice(op.hand))
        elif n == "Heavy Storm":
            for who in (pl, op):
                for x in who.st[:]: self.to_gy(who, x)
        elif n in ("Mystical Space Typhoon", "Dust Tornado") and op.st: self.destroy(op, self.rnd.choice(op.st))
        elif n == "Nobleman of Crossout":
            fd = [x for x in op.mon if x.fd]
            if fd: self.destroy(op, self.rnd.choice(fd), banish=True)
        elif n in ("Snatch Steal", "Creature Swap") and op.mon and len(pl.mon) < 5:
            t = max(op.mon, key=lambda x: x.atk); op.mon.remove(t); t.fd, t.pos = False, "ATK"; pl.mon.append(t)
            if n == "Creature Swap" and pl.mon[:-1]:
                mine = min(pl.mon[:-1], key=lambda x: x.atk); pl.mon.remove(mine); op.mon.append(mine)
        elif n == "Metamorphosis" and pl.mon and op.mon:
            self.to_gy(pl, min(pl.mon, key=lambda x: x.atk)); self.destroy(op, max(op.mon, key=lambda x: x.atk))
        elif n in ("Premature Burial", "Call of the Haunted"):
            ms = [x for x in pl.gy if x.kind == "Monster"]
            if ms and len(pl.mon) < 5:
                if n == "Premature Burial": self.damage(pl, 800)
                best = max(ms, key=lambda x: x.atk); pl.gy.remove(best); best.fd, best.pos = False, "ATK"; pl.mon.append(best)
        elif n == "Reinforcement of the Army":
            ws = [x for x in pl.deck if x.mtype == "Warrior" and x.level <= 4]
            if ws: best = max(ws, key=lambda x: (x.name == "Exiled Force" and bool(op.mon), x.atk)); pl.deck.remove(best); pl.hand.append(best)
        elif n == "Scapegoat":
            for _ in range(min(4, 5 - len(pl.mon))):
                t = Card("t" + str(self.rnd.random())[2:9], "Sheep Token", None); t.pos = "DEF"; pl.mon.append(t)
        elif n == "Book of Moon" and op.mon:
            t = max(op.mon, key=lambda x: x.atk); t.fd, t.pos = True, "DEF"
        elif n == "Trap Dustshoot" and len(op.hand) >= 4:
            ms = [x for x in op.hand if x.kind == "Monster"]
            if ms: x = self.rnd.choice(ms); op.hand.remove(x); op.deck.insert(0, x)
        elif n in ("Raigeki Break", "Ring of Destruction") and op.mon:
            t = max(op.mon, key=lambda x: x.atk)
            if n == "Ring of Destruction": self.damage(pl, t.atk); self.damage(op, t.atk)
            if n == "Raigeki Break" and pl.hand: self.to_gy(pl, min(pl.hand, key=lambda x: x.atk))
            self.destroy(op, t)
        if n in CONTINUOUS and len(pl.st) < 5: pl.st.append(c)
        elif n not in ("Premature Burial", "Call of the Haunted"): pl.gy.append(c)

    # ---------- The defending player's traps, with fixed habits ----------
    def ready(self, pl, names):
        locked = self.traps_locked()
        return [x for x in pl.st if x.fd and x.name in names and (x.kind == "Spell" or (x.set_turn < self.turn and not locked))]

    def respond(self, pl, event, c):
        """pl may answer the other player's attack, summon, spell or draw. Returns True if c was stopped."""
        op, r = self.opp(pl), self.rnd.random()
        def use(card):
            pl.st.remove(card); card.fd = False; pl.gy.append(card)
        if event == "attack":
            mf = self.ready(pl, {"Mirror Force"})
            if mf and r < 0.85 and (len([x for x in op.mon if x.pos == "ATK" and not x.fd]) >= 2 or self.eff_atk(op, c) >= 1600):
                use(mf[0])
                for x in [x for x in op.mon if x.pos == "ATK" and not x.fd]: self.destroy(op, x)
                return True
            one = self.ready(pl, ATK_TRAPS - {"Mirror Force"})
            if one and r < 0.75 and self.eff_atk(op, c) >= 1400:
                t = one[0]; use(t)
                if t.name == "Compulsory Evacuation Device": op.mon.remove(c); op.hand.append(c)
                elif t.name == "Magic Cylinder": self.damage(op, self.eff_atk(op, c))
                else:
                    if t.name == "Ring of Destruction": self.damage(pl, c.atk); self.damage(op, c.atk)
                    self.destroy(op, c)
                return True
            goat = self.ready(pl, {"Scapegoat", "Book of Moon"})
            if goat and r < 0.6 and self.eff_atk(op, c) >= 1500:
                g = goat[0]; use(g)
                if g.name == "Book of Moon": c.fd, c.pos = True, "DEF"; return True
                for _ in range(min(4, 5 - len(pl.mon))):
                    t = Card("t" + str(self.rnd.random())[2:9], "Sheep Token", None); t.pos = "DEF"; pl.mon.append(t)
                return True
        elif event == "summon" and c.kind == "Monster":
            trap = self.ready(pl, SUM_TRAPS)
            strong = self.eff_atk(op, c) >= 1900 or c.name in SPECIAL
            if trap and ((strong and r < 0.7) or (len(op.mon) >= 2 and r < 0.3)):
                t = trap[0]; use(t)
                if t.name == "Torrential Tribute":
                    for who in (pl, op):
                        for x in who.mon[:]: self.destroy(who, x)
                elif t.name == "Solemn Judgment": self.damage(pl, pl.lp // 2); self.destroy(op, c)
                elif t.name == "Bottomless Trap Hole":
                    if c.atk < 1500: pl.st.append(t); pl.gy.remove(t); t.fd = True; return False
                    self.destroy(op, c, banish=True)
                elif t.name == "Phoenix Wing Wind Blast":
                    if not pl.hand: pl.st.append(t); pl.gy.remove(t); t.fd = True; return False
                    self.to_gy(pl, min(pl.hand, key=lambda x: (x.name in DRAW_SPELLS, x.atk)))
                    op.mon.remove(c); c.fd, c.pos = False, "ATK"; op.deck.append(c)
                else: op.mon.remove(c); op.hand.append(c)
                return True
        elif event == "spell":
            sj = self.ready(pl, {"Solemn Judgment"})
            if sj and r < 0.5 and c.name in DRAW_SPELLS | {"Heavy Storm", "Snatch Steal", "Delinquent Duo"}:
                use(sj[0]); self.damage(pl, pl.lp // 2); return True
        elif event == "draw":
            d = self.ready(pl, {"Drop Off"})
            if d and r < 0.6 and c in op.hand: use(d[0]); self.to_gy(op, c); return True
        return False

    def attack(self, pl, a, target_uid):
        op = self.opp(pl)
        if a.attacked or a.fd or a.pos != "ATK" or self.phase != "BP": return
        if pl.no_attack_turns or (a.level >= 4 and self.face_up(NO_BIG_ATTACKS)): return
        a.attacked = True
        if a.name == "Jirai Gumo" and self.rnd.random() < 0.5: self.damage(pl, pl.lp - pl.lp // 2)
        if self.respond(op, "attack", a) or a not in pl.mon: return
        atk = self.eff_atk(pl, a)
        if target_uid is None:
            if op.mon: return
            self.damage(op, atk); self.on_damage(pl, a)
            if a.name == "Don Zaloog" and op.hand: self.to_gy(op, self.rnd.choice(op.hand))
            return
        t = next((x for x in op.mon if x.uid == target_uid), None)
        if not t: return
        was_fd = t.fd
        if t.fd:
            t.fd = False
            self.flip_effect(op, t)
            if t not in op.mon: return
        if a.name == "Mystic Swordsman LV2" and was_fd or a.name == "Ninja Grandmaster Sasuke" and t.pos == "DEF":
            self.destroy(op, t); return
        if a.name in ("D.D. Warrior Lady", "D.D. Assailant") and t.name != "Spirit Reaper":
            self.destroy(op, t, banish=True); self.destroy(pl, a, banish=True); return
        d = self.eff_atk(op, t) if t.pos == "ATK" else t.def_
        # Injection Fairy Lily pays 2000 for 3000 ATK when that wins or saves the battle.
        if a.name == "Injection Fairy Lily" and atk <= d and pl.lp > 2000: self.damage(pl, 2000); atk += 3000
        if t.name == "Injection Fairy Lily" and t.pos == "ATK" and d <= atk and op.lp > 2000: self.damage(op, 2000); d += 3000
        if t.pos == "ATK":
            if atk > d: self.damage(op, atk - d); self.on_damage(pl, a); self.battle_destroy(op, t)
            elif atk < d: self.damage(pl, d - atk); self.battle_destroy(pl, a)
            else: self.battle_destroy(op, t); self.battle_destroy(pl, a)
        else:
            if atk > d:
                if a.name == "Airknight Parshath": self.damage(op, atk - d); self.on_damage(pl, a)
                self.battle_destroy(op, t)
            elif atk < d: self.damage(pl, d - atk)
        if a.name == "Goblin Attack Force" and a in pl.mon: a.pos = "DEF"

    def on_damage(self, pl, a):
        """What happens when a monster deals battle damage."""
        op = self.opp(pl)
        if a.name == "Airknight Parshath": self.draw(pl)
        elif a.name == "Kycoo the Ghost Destroyer":
            for x in [x for x in op.gy if x.kind == "Monster"][:2]: op.gy.remove(x); op.ban.append(x)

    def run(self):
        while not self.winner and self.turn <= MAX_TURNS: self.play_turn()
        return self.winner

# ---------- The scripted player ----------
def scripted(game, pl, cands):
    op, ph = game.opp(pl), game.phase
    by = {}
    for k, p, c, t in cands: by.setdefault(p, []).append((k, c, t))
    has = lambda k: any(x[0] == k for x in cands)
    pick = lambda play, cond=lambda c: True: next((k for k, c, t in by.get(play, []) if cond(c)), None)
    # Finish what an effect started: draw, then discard the least useful cards.
    if pl.obligations:
        kind = pl.obligations[0][0]
        if kind == "draw" and has("deck|Draw card"): return "deck|Draw card"
        if kind == "discard":
            hand = [c for k, c, t in by.get("To GY", []) if c in pl.hand]
            if hand:
                worst = min(hand, key=lambda c: (c.name in DRAW_SPELLS, c.kind == "Trap", c.atk if c.kind == "Monster" else 1500))
                return f"card|{worst.uid}|To GY"
    if ph == "DP":
        return "deck|Draw card" if not pl.drew and pl.deck else "global|Enter M1"
    if ph in ("SP", "EP"): return "global|Enter M1" if ph == "SP" else "global|End turn"
    if ph == "M1" or ph == "M2":
        hand_names = Counter(c.name for c in pl.hand)
        for n in ("Pot of Greed", "Graceful Charity", "Upstart Goblin"):
            k = pick("Activate ST", lambda c, n=n: c.name == n and c in pl.hand)
            if k: return k
        k = pick("Activate ST", lambda c: c.name == "Jar of Greed" and c in pl.st and c.set_turn < game.turn)
        if k: return k
        if hand_names["Thunder Dragon"] and any(x.name == "Thunder Dragon" for x in pl.deck):
            k = pick("To GY", lambda c: c.name == "Thunder Dragon" and c in pl.hand)
            if k: return k
        # Heavy Storm hits both sides, so only when they have more set than we do.
        if len(op.st) >= 2 and len(op.st) > len([x for x in pl.st if x.fd]):
            k = pick("Activate ST", lambda c: c.name in ("Heavy Storm", "Giant Trunade"))
            if k: return k
        if op.st and len(op.hand) <= 4:
            k = pick("Activate ST", lambda c: c.name == "Mystical Space Typhoon" and c in pl.hand)
            if k: return k
        if op.hand and len(op.hand) >= 2 and pl.lp > 2000:
            k = pick("Activate ST", lambda c: c.name == "Delinquent Duo")
            if k: return k
        if len(op.hand) >= 4:
            k = pick("Activate ST", lambda c: c.name == "Trap Dustshoot" and c in pl.st and c.set_turn < game.turn)
            if k: return k
        if op.mon:
            strong = max(op.mon, key=lambda x: x.atk)
            if any(x.fd for x in op.mon):
                k = pick("Activate ST", lambda c: c.name == "Nobleman of Crossout")
                if k: return k
            if not strong.fd and strong.atk >= 1500:
                for n in sorted(STEALS):
                    k = pick("Activate ST", lambda c, n=n: c.name == n and c in pl.hand and (n != "Metamorphosis" or pl.mon))
                    if k: return k
            if sum(not x.fd for x in op.mon) >= 2:
                k = pick("Activate ST", lambda c: c.name == "Lightning Vortex" and len(pl.hand) >= 2)
                if k: return k
            if not strong.fd:
                k = pick("Activate ST", lambda c: c.name == "Smashing Ground")
                if k: return k
            if max(x.atk for x in op.mon) > max([0] + [game.eff_atk(pl, x) for x in pl.mon]):
                k = pick("Activate ST", lambda c: c.name in ("Swords of Revealing Light", "Phoenix Wing Wind Blast") and (c in pl.hand or c.set_turn < game.turn) and (c.name != "Phoenix Wing Wind Blast" or len(pl.hand) >= 1))
                if k: return k
        # Set traps that pay off on its own turn: burn, locks, and skipping their draw.
        k = pick("Activate ST", lambda c: c in pl.st and c.fd and c.set_turn < game.turn and (
            (c.name == "Just Desserts" and len(op.mon) >= 2) or (c.name == "Secret Barrel" and len(op.hand) + len(op.mon) + len(op.st) >= 5) or
            (c.name == "Ojama Trio" and len(op.mon) <= 2) or c.name == "Time Seal" or
            (c.name == "Royal Decree" and len(op.st) >= 2) or (c.name in NO_BIG_ATTACKS and any(x.level >= 4 for x in op.mon))))
        if k: return k
        if sum(1 for x in pl.ban if x.kind == "Monster") >= 2 and pl.lp > 4000:
            k = pick("Activate ST", lambda c: c.name in ("Dimension Fusion", "Return from the Different Dimension") and (c in pl.hand or c.set_turn < game.turn))
            if k: return k
        if pl.lost_monster:
            k = pick("Activate ST", lambda c: c.name == "Last Will")
            if k: return k
        if ph == "M1":
            light = any(x.attr == "LIGHT" for x in pl.gy); dark = any(x.attr == "DARK" for x in pl.gy)
            if light and dark:
                for n in ("Black Luster Soldier - Envoy of the Beginning", "Chaos Sorcerer"):
                    k = pick("SS ATK", lambda c, n=n: c.name == n)
                    if k: return k
            if len(pl.hand) == 1:
                k = pick("SS ATK", lambda c: c.name == "Swift Gaia the Fierce Knight")
                if k: return k
            k = pick("Activate ST", lambda c: c.name in ("Reinforcement of the Army", "Reasoning") or (c.name == "Monster Gate" and any(x.atk < 1000 for x in pl.mon)))
            if k: return k
            if pl.summons == 0:
                # Tribute a weak monster for a Monarch or another level 5-6 monster.
                fodder = [x for x in pl.mon if not x.token and x.atk < 1500] or [x for x in pl.mon if x.token]
                big = [c for k2, c, t in by.get("Normal Summon", []) if c.level in (5, 6)]
                if fodder and big: return f"card|{max(big, key=lambda c: c.atk).uid}|Normal Summon"
            if op.mon and any(x.pos == "ATK" and not x.fd for x in op.mon):
                k = pick("Activate ST", lambda c: c.name == "Enemy Controller" and c in pl.hand)
                if k: return k
            if any(x.kind == "Monster" for x in pl.gy):
                k = pick("Activate ST", lambda c: c.name == "Premature Burial" and c in pl.hand) or \
                    pick("Activate ST", lambda c: c.name == "Call of the Haunted" and c in pl.st and c.set_turn < game.turn)
                if k: return k
            k = pick("Flip Summon", lambda c: c.name in FLIP and c.set_turn < game.turn)
            if k: return k
            if pl.summons == 0:
                ms = [c for k2, c, t in by.get("Normal Summon", []) if c.level <= 4]
                best_opp = max([0] + [x.atk for x in op.mon if not x.fd])
                beaters = [c for c in ms if c.name not in FLIP and c.atk >= max(1400, best_opp)]
                if beaters and (not op.mon or len(op.st) <= 2):
                    b = max(beaters, key=lambda c: (c.name == "Exiled Force" and bool(op.mon), c.name == "Breaker the Magical Warrior" and bool(op.st), game.eff_atk(pl, c)))
                    return f"card|{b.uid}|Normal Summon"
                flips = [c for k2, c, t in by.get("Set monster", []) if c.level <= 4]
                if flips:
                    s = max(flips, key=lambda c: (c.name in FLIP, c.def_))
                    return f"card|{s.uid}|Set monster"
            if any(c.pos == "ATK" and not c.fd and not c.attacked for c in pl.mon) and game.turn > 1:
                return "global|Enter BP"
        if ph == "BP":
            return "global|Enter M2"
        # Set traps and quick-plays for the opponent's turn, keeping room.
        if len(pl.st) < 4:
            for c in pl.hand:
                if c.kind == "Trap" or c.name in ("Scapegoat", "Book of Moon", "Mystical Space Typhoon", "Swords of Revealing Light"):
                    return f"card|{c.uid}|Set ST"
        if ph == "M2" and pl.summons == 0:
            flips = [c for k2, c, t in by.get("Set monster", []) if c.level <= 4]
            if flips: return f"card|{max(flips, key=lambda c: (c.name in FLIP, c.def_)).uid}|Set monster"
        return "global|End turn" if ph == "M2" else "global|Enter BP" if game.turn > 1 else "global|End turn"
    if ph == "BP":
        attackers = [c for c in pl.mon if c.pos == "ATK" and not c.fd and not c.attacked]
        for a in sorted(attackers, key=lambda c: -game.eff_atk(pl, c)):
            if not op.mon:
                return f"card|{a.uid}|Attack directly"
            atk = game.eff_atk(pl, a)
            wins = [t for t in op.mon if not t.fd and ((t.pos == "ATK" and atk > game.eff_atk(op, t)) or (t.pos == "DEF" and atk > t.def_))]
            if wins: return f"card|{a.uid}|Attack|{max(wins, key=lambda t: t.atk).uid}"
            fds = [t for t in op.mon if t.fd]
            if fds and atk >= 1600: return f"card|{a.uid}|Attack|{fds[0].uid}"
        return "global|Enter M2"
    return "global|End turn"

# ---------- Legal plays ----------
# The simulator offers every menu item, as DuelingBook does, and doesn't stop a play the rules forbid (drawing
# at any time, for example). A look-ahead would find those loopholes, so it only picks from the plays allowed here.
def legal(game, pl, cands):
    op, ph = game.opp(pl), game.phase
    if pl.obligations:
        kind = pl.obligations[0][0]
        want = [k for k, p, c, t in cands if (kind == "draw" and k == "deck|Draw card") or (kind == "discard" and p == "To GY" and c in pl.hand)]
        if want: return want
    if ph == "DP": return ["deck|Draw card"] if not pl.drew and pl.deck else ["global|Enter M1"]
    if ph == "SP": return ["global|Enter M1"]
    if ph == "EP": return ["global|End turn"]
    ok = []
    for k, p, c, t in cands:
        if k.startswith("global|"):
            if (ph == "M1" and p == "Enter BP" and game.turn > 1) or (ph == "BP" and p == "Enter M2") or p == "End turn": ok.append(k)
        elif p in ("Normal Summon", "Set monster"):
            need = 2 if c.level >= 7 else 1 if c.level >= 5 else 0
            if ph in ("M1", "M2") and pl.summons == 0 and len([x for x in pl.mon if not x.token or need == 0]) >= need and "Fusion" not in (game.cards.get(c.name) or {}).get("type", ""): ok.append(k)
        elif p == "SS ATK":
            if ph in ("M1", "M2") and (c.name in ("Black Luster Soldier - Envoy of the Beginning", "Chaos Sorcerer") and any(x.attr == "LIGHT" for x in pl.gy) and any(x.attr == "DARK" for x in pl.gy)
                                       or c.name == "Swift Gaia the Fierce Knight" and len(pl.hand) == 1): ok.append(k)
        elif p == "Flip Summon":
            if ph in ("M1", "M2") and c.set_turn < game.turn: ok.append(k)
        elif p in ("To DEF", "To ATK"):
            if ph in ("M1", "M2") and c.set_turn < game.turn and not c.attacked: ok.append(k)
        elif p == "Activate ST":
            if ph in ("M1", "M2") and (c in pl.hand and c.kind == "Spell" or c in pl.st and c.fd and (c.kind == "Spell" or c.set_turn < game.turn)): ok.append(k)
        elif p == "Set ST":
            if ph in ("M1", "M2"): ok.append(k)
        elif p in ("Attack", "Attack directly"):
            if ph == "BP" and not c.attacked and (p == "Attack" or not op.mon): ok.append(k)
        elif p == "To GY":
            if ph in ("M1", "M2") and c in pl.hand and c.name == "Thunder Dragon": ok.append(k)
    return ok or ["global|End turn"]

# ---------- A look-ahead teacher ----------
def rollout_player(rollouts, horizon, seed, max_cands=8):
    """Tries each legal play in copies of the game (hidden cards dealt again each time), plays every copy on
    with the scripted player for `horizon` more turns, and makes the play that does best on average. It's
    stronger than the scripted player, and a model trained on its choices learns from that.
    Every play gets the same rollouts with the same random seeds, so their values can be compared fairly.
    (Giving extra rollouts to the leaders only made the noisiest estimates win.) The value it saw for each
    play is kept on play.values, for records."""
    rnd = random.Random(seed)
    def play(game, pl, cands):
        play.values = None
        keys = legal(game, pl, cands)
        if len(keys) == 1: return keys[0]
        first = scripted(game, pl, cands)
        # Identical copies of a card are the same play: keep one of each.
        seen, uniq, same = set(), [], {}
        info = {k: (p, c.name if c else None, t.name if t and not t.fd else t.uid if t else None) for k, p, c, t in cands}
        for k in ([first] if first in keys else []) + keys:
            if info[k] in seen: same.setdefault(info[k], []).append(k); continue
            seen.add(info[k]); uniq.append(k); same[info[k]] = [k]
        uniq = uniq[:max_cands]
        seeds = [rnd.random() for _ in range(rollouts)]
        vals = {}
        for k in uniq:
            total = 0.0
            for sd in seeds:
                g, me = game.clone(pl, random.Random(sd))
                g.policies = [scripted, scripted]
                ended = g.step(me, k)
                stop = g.turn + horizon
                if not g.winner:
                    if ended: g.end_turn()
                    else: g.continue_turn()
                    while not g.winner and g.turn < stop and g.turn <= MAX_TURNS: g.play_turn()
                total += g.value(me)
            vals[k] = total / rollouts
        # Ties go to the scripted player's choice, which comes first.
        best = max(uniq, key=lambda k: (vals[k], -uniq.index(k)))
        play.values = {k2: vals[k] for k in uniq for k2 in same[info[k]]}
        return best
    play.values = None
    return play

# ---------- A learned model as a player, with the same guards as the extension ----------
def model_player(model, epsilon=0.0, rnd=None):
    sys.path.insert(0, HERE)
    from train_policy import featurize
    w = model["weights"]
    state = {}
    rnd = rnd or random.Random(0)
    def play(game, pl, cands):
        # Now and then a random legal play instead, so the data covers positions the model wouldn't pick its way into.
        if epsilon and rnd.random() < epsilon: return rnd.choice(legal(game, pl, cands))
        tk = (id(pl), game.turn)
        if state.get("tk") != tk: state.update(tk=tk, used=Counter(), ended=False)
        rec = game.build_record(pl, cands)
        scored = []
        for cand in rec["cands"]:
            fs = featurize(rec, cand)
            known = [f for f in fs if f in w]
            if known: scored.append((sum(w[f] for f in known), cand["key"]))
        for s, k in sorted(scored, reverse=True):
            # One attack per monster per turn, as in the extension.
            rk = "|".join(k.split("|")[:2]) + "|attack" if k.startswith("card|") and k.split("|")[2].startswith("Attack") else k
            limit = {"card": 1, "deck": 8, "global": 1}[k.split("|")[0]]
            if state["used"][rk] >= limit: continue
            state["used"][rk] += 1
            return k
        return "global|End turn"
    return play

_MODELS = {}
def make_player(kind, a, seed, epsilon=0.0):
    if kind == "scripted": return scripted
    if kind == "rollout": return rollout_player(a.rollouts, a.horizon, seed)
    if kind not in _MODELS: _MODELS[kind] = json.load(open(kind))
    return model_player(_MODELS[kind], epsilon, random.Random(seed))

_W = {}
def _init(a):
    _W["a"], _W["cards"] = a, load_cards()
    _W["decks"] = load_fl_decks(a.fl) if a.fl else load_decks(a.decks)

def _game(g):
    """One game, in a worker: returns its records, the winner's deck, and for --eval how the tested side did."""
    a, cards, decks = _W["a"], _W["cards"], _W["decks"]
    rnd = random.Random(a.seed * 1000003 + g)
    if a.eval:
        seat = g % 2
        pols = [make_player(a.opponent, a, rnd.random()), make_player(a.opponent, a, rnd.random())]
        pols[seat] = make_player(a.model or a.teacher, a, rnd.random())
        game = Game(decks, cards, rnd, pols, False, f"eval{g}")
        w = game.run()
        return [], None, ("tested" if w is game.p[seat] else "scripted" if w else "draw"), game.p[seat].deck_title
    actor = a.actor or a.teacher
    pols = [make_player(actor, a, rnd.random(), a.epsilon), make_player(actor, a, rnd.random(), a.epsilon)]
    game = Game(decks, cards, rnd, pols, True, f"sim{a.seed}-{g}")
    if actor != a.teacher: game.labellers = [make_player(a.teacher, a, rnd.random()), make_player(a.teacher, a, rnd.random())]
    w = game.run()
    return game.records, (w.deck_title if w else "turn limit"), None, None

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=600)
    ap.add_argument("--decks", nargs="*", help="deck file names in tools/decks to use (default: all)")
    ap.add_argument("--fl", type=int, default=0, metavar="N",
                    help="deal from the N most recent Format Library topping decks instead of tools/decks (needs tools/train_decks.py run once)")
    ap.add_argument("--teacher", default="scripted", choices=["scripted", "rollout"],
                    help="who makes the recorded plays: the scripted player, or the look-ahead teacher (slower, stronger)")
    ap.add_argument("--actor", help="who makes the plays in recorded games while the teacher labels them (DAgger): a policy.json. Default: the teacher")
    ap.add_argument("--epsilon", type=float, default=0.0, help="how often the actor makes a random legal play instead, 0 to 1")
    ap.add_argument("--opponent", default="scripted", help="who --eval plays against: scripted, rollout, or a policy.json")
    ap.add_argument("--rollouts", type=int, default=6, help="look-ahead copies per candidate play (rollout teacher)")
    ap.add_argument("--horizon", type=int, default=3, help="turns each look-ahead copy plays on (rollout teacher)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("-o", "--out", default="sim-training.json")
    ap.add_argument("--model", help="a trained policy.json to play against the scripted player")
    ap.add_argument("--eval", action="store_true", help="only report how --model (or --teacher rollout) does against the scripted player")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.eval and not a.model and a.teacher == "scripted": sys.exit("--eval needs --model policy.json or --teacher rollout")
    if a.actor and a.teacher != "rollout": sys.exit("--actor needs --teacher rollout to label the plays")
    _init(a)
    titles = Counter(t for t, _ in _W["decks"].values())
    print(f"Decks: {len(_W['decks'])} (" + ", ".join(f"{t} {n}" if n > 1 else t for t, n in titles.most_common(8)) + (", ..." if len(titles) > 8 else "") + ")")
    import multiprocessing as mp
    pool = mp.Pool(a.jobs, initializer=_init, initargs=(a,)) if a.jobs > 1 else None
    it = pool.imap_unordered(_game, range(a.games), chunksize=1) if pool else map(_game, range(a.games))
    results, evals, t0, n_recs = Counter(), Counter(), time.time(), 0
    by_deck, games_deck = Counter(), Counter()
    # Records go to the file as each game finishes, so a long run doesn't pile them up in memory.
    out = None
    if not a.eval:
        out = open(a.out, "w", encoding="utf-8")
        out.write(json.dumps({"kind": "ygo-duel-odds-training", "version": 1, "source": "sim_goat.py", "teacher": a.teacher, "actor": a.actor or a.teacher}, separators=(",", ":"))[:-1] + ',"records":[')
    for i, (r, w, ev, title) in enumerate(it, 1):
        if out:
            for rec in r:
                if n_recs: out.write(",")
                out.write(json.dumps(rec, separators=(",", ":"))); n_recs += 1
        if w: results[w] += 1
        if ev: evals[ev] += 1; games_deck[title] += 1; by_deck[title] += ev == "tested"
        if i % max(1, a.games // 10) == 0: print(f"  {i} games, {n_recs} decisions, {time.time() - t0:.0f} s", flush=True)
    if pool: pool.close()
    if a.eval:
        n, who = a.games, ("Learned model" if a.model else "Look-ahead teacher")
        vs = {"scripted": "scripted player", "rollout": "look-ahead teacher"}.get(a.opponent, os.path.basename(a.opponent))
        print(f"{who} vs {vs} over {n} games: won {evals['tested']} ({evals['tested']/n:.0%}), lost {evals['scripted']} ({evals['scripted']/n:.0%}), {evals['draw']} hit the turn limit.")
        for d, k in games_deck.most_common(8): print(f"  playing {d}: won {by_deck[d]} of {k}")
        return
    out.write("]}"); out.close()
    print(f"Wrote {n_recs} decisions from {a.games} games to {a.out}")
    print("Wins by deck: " + ", ".join(f"{k} {v}" for k, v in results.most_common(10)))

if __name__ == "__main__":
    main()
