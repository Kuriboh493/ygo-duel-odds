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
import argparse, json, math, os, random, sys
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

ATK_TRAPS = {"Mirror Force", "Sakuretsu Armor", "Compulsory Evacuation Device", "Ring of Destruction", "Raigeki Break"}
SUM_TRAPS = {"Torrential Tribute", "Solemn Judgment", "Compulsory Evacuation Device"}
FLIP = {"Magician of Faith", "Gravekeeper's Spy", "Dekoichi the Battlechanted Locomotive", "Night Assailant"}
SPECIAL = {"Black Luster Soldier - Envoy of the Beginning", "Chaos Sorcerer", "Swift Gaia the Fierce Knight"}
DRAW_SPELLS = {"Pot of Greed", "Graceful Charity"}

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
        for zone in (pl.hand, pl.mon, pl.st):
            if c in zone: zone.remove(c)
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
        return c.atk

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
        pl, op = self.p[self.active], self.p[1 - self.active]
        pl.plays = pl.summons = pl.draws = pl.discards = 0; pl.drew = False; pl.last = pl.last_card = None; pl.history = []; self.phase = "DP"
        for c in pl.mon: c.attacked = False
        policy = self.policies[self.active]
        for _ in range(80):
            if self.winner: return
            cands = self.candidates(pl)
            keys = [k for k, _, _, _ in cands]
            choice = policy(self, pl, cands)
            if choice not in keys: choice = "global|End turn"
            if self.record:
                rec = self.build_record(pl, cands); rec["chosen"] = keys.index(choice); self.records.append(rec)
            pl.plays += 1
            parts = choice.split("|")
            card = next((x for x in pl.hand + pl.mon + pl.st if parts[0] == "card" and x.uid == parts[1]), None)
            pl.last = parts[2] if parts[0] == "card" else parts[1]
            pl.last_card = card.name if card else None
            if choice == "deck|Draw card": pl.draws += 1
            if pl.last == "To GY" and card in pl.hand: pl.discards += 1
            h = f"{pl.last}:{pl.last_card or ''}"
            if h not in pl.history: pl.history.append(h)
            if self.apply(pl, choice): break
        # Whatever an effect still owes ends with the turn: missing draws are lost, and missing discards are made at random.
        for kind, n in pl.obligations:
            if kind == "discard":
                for _ in range(min(n, len(pl.hand))): self.to_gy(pl, self.rnd.choice(pl.hand))
        pl.obligations = []
        self.active, self.turn = 1 - self.active, self.turn + 1

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
                    if c and pl.skip_draw: pl.skip_draw = False
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

    def activate(self, pl, c):
        op = self.opp(pl)
        if c in pl.st and c.fd and c.kind == "Trap" and c.set_turn >= self.turn: return
        n = c.name
        if c in pl.hand: pl.hand.remove(c)
        if c in pl.st: pl.st.remove(c)
        c.fd = False
        if self.respond(op, "spell", c): pl.gy.append(c); return
        if n == "Pot of Greed": pl.obligations.append(("draw", 2))
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
        if n not in ("Premature Burial", "Call of the Haunted"): pl.gy.append(c)

    # ---------- The defending player's traps, with fixed habits ----------
    def ready(self, pl, names):
        return [x for x in pl.st if x.fd and x.name in names and (x.kind == "Spell" or x.set_turn < self.turn)]

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
        a.attacked = True
        if a.name == "Jirai Gumo" and self.rnd.random() < 0.5: self.damage(pl, pl.lp - pl.lp // 2)
        if self.respond(op, "attack", a) or a not in pl.mon: return
        atk = self.eff_atk(pl, a)
        if target_uid is None:
            if op.mon: return
            self.damage(op, atk)
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
        if t.pos == "ATK":
            d = self.eff_atk(op, t)
            if atk > d: self.damage(op, atk - d); self.destroy(op, t, banish=None)
            elif atk < d: self.damage(pl, d - atk); self.destroy(pl, a, banish=None)
            else: self.destroy(op, t, banish=None); self.destroy(pl, a, banish=None)
        else:
            if atk > t.def_: self.destroy(op, t, banish=None)
            elif atk < t.def_: self.damage(pl, t.def_ - atk)

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
        for n in ("Pot of Greed", "Graceful Charity"):
            k = pick("Activate ST", lambda c, n=n: c.name == n and c in pl.hand)
            if k: return k
        k = pick("Activate ST", lambda c: c.name == "Jar of Greed" and c in pl.st and c.set_turn < game.turn)
        if k: return k
        if hand_names["Thunder Dragon"] and any(x.name == "Thunder Dragon" for x in pl.deck):
            k = pick("To GY", lambda c: c.name == "Thunder Dragon" and c in pl.hand)
            if k: return k
        # Heavy Storm hits both sides, so only when they have more set than we do.
        if len(op.st) >= 2 and len(op.st) > len([x for x in pl.st if x.fd]):
            k = pick("Activate ST", lambda c: c.name == "Heavy Storm")
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
                for n in ("Snatch Steal", "Creature Swap", "Metamorphosis"):
                    k = pick("Activate ST", lambda c, n=n: c.name == n and c in pl.hand and (n != "Metamorphosis" or pl.mon))
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
            k = pick("Activate ST", lambda c: c.name == "Reinforcement of the Army")
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
                if c.kind == "Trap" or c.name in ("Scapegoat", "Book of Moon", "Mystical Space Typhoon"):
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

# ---------- A learned model as a player, with the same guards as the extension ----------
def model_player(model):
    sys.path.insert(0, HERE)
    from train_policy import featurize
    w = model["weights"]
    state = {}
    def play(game, pl, cands):
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

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--games", type=int, default=600)
    ap.add_argument("--decks", nargs="*", help="deck file names in tools/decks to use (default: all)")
    ap.add_argument("-o", "--out", default="sim-training.json")
    ap.add_argument("--model", help="a trained policy.json to play against the scripted player")
    ap.add_argument("--eval", action="store_true", help="only report how the model does against the scripted player")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    cards, decks = load_cards(), load_decks(a.decks)
    print("Decks: " + ", ".join(t for t, _ in decks.values()))
    rnd = random.Random(a.seed)
    if a.eval:
        if not a.model: sys.exit("--eval needs --model policy.json")
        model = json.load(open(a.model))
        wins = Counter(); by_deck = Counter(); games_deck = Counter()
        for g in range(a.games):
            seat = g % 2
            pols = [scripted, scripted]; pols[seat] = model_player(model)
            game = Game(decks, cards, rnd, pols, False, f"eval{g}")
            w = game.run()
            res = "model" if w is game.p[seat] else "scripted" if w else "draw"
            wins[res] += 1; games_deck[game.p[seat].deck_title] += 1
            if res == "model": by_deck[game.p[seat].deck_title] += 1
        n = a.games
        print(f"Learned model vs scripted player over {n} games: model won {wins['model']} ({wins['model']/n:.0%}), scripted won {wins['scripted']} ({wins['scripted']/n:.0%}), {wins['draw']} hit the turn limit.")
        for d in games_deck: print(f"  playing {d}: won {by_deck[d]} of {games_deck[d]}")
        return
    recs, results = [], Counter()
    for g in range(a.games):
        game = Game(decks, cards, rnd, [scripted, scripted], True, f"sim{a.seed}-{g}")
        w = game.run()
        results[w.deck_title if w else "turn limit"] += 1
        recs += game.records
        if (g + 1) % 100 == 0: print(f"  {g + 1} games, {len(recs)} decisions")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"kind": "ygo-duel-odds-training", "version": 1, "source": "sim_goat.py", "records": recs}, f, separators=(",", ":"))
    print(f"Wrote {len(recs)} decisions from {a.games} games to {a.out}")
    print("Wins by deck: " + ", ".join(f"{k} {v}" for k, v in results.most_common()))

if __name__ == "__main__":
    main()
