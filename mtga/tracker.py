"""Reads MTG Arena's Player.log and keeps the opponent's public information, the way extension/tracker.js does for DuelingBook.

Arena logs every game state it receives. The parser only trusts what both players can see, or what this player was shown:
  - An opponent's card is named only when its object is public or lists this player as a viewer.
  - The `actions` list on game states is never read. It can include the opponent's options, which aren't public.
Everything is a pure function of the log's lines, so a whole log can be replayed for testing.
"""
import json, os, re

ROOT = os.path.dirname(os.path.abspath(__file__))
CARD_OBJECTS = {"GameObjectType_Card", "GameObjectType_Adventure", "GameObjectType_MDFCBack", "GameObjectType_SplitCard", "GameObjectType_Omen"}
PUBLIC_ZONES = {"ZoneType_Battlefield", "ZoneType_Graveyard", "ZoneType_Exile", "ZoneType_Stack", "ZoneType_Command"}
BASIC_MANA = {"SubType_Plains": "W", "SubType_Island": "U", "SubType_Swamp": "B", "SubType_Mountain": "R", "SubType_Forest": "G"}
TYPE_CODE = (("CardType_Land", "L"), ("CardType_Creature", "C"), ("CardType_Instant", "I"), ("CardType_Sorcery", "S"), ("CardType_Planeswalker", "P"), ("CardType_Battle", "B"), ("CardType_Artifact", "A"), ("CardType_Enchantment", "E"))
BASIC_NAME = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
ATTACK_WEIGHT = 0.5     # a player holds a trick through an attack far more readily than they let a key spell resolve
LOG_MAX = 300


def load_cards(path=None):
    """Arena id -> (name, type code, mana produced), from mtg-cards.js."""
    src = open(path or os.path.join(ROOT, "mtg-cards.js"), encoding="utf-8").read()
    data = json.loads(src[src.index("window.MTG_CARD_DATA = ") + 23:].rstrip().rstrip(";"))
    cards = {}
    for line in data.split("\n"):
        f = line.split("\t")
        for i in f[6].split(","):
            if i: cards[int(i)] = (f[0], f[1], f[4])
    return cards


def format_of(event):
    e = (event or "").lower()
    if re.search(r"draft|sealed|cube|jumpin", e): return "limited"
    if "rebalanced" in e: return "alchemy"
    if "brawl" in e: return "brawl"
    for fmt in ("explorer", "historic", "alchemy", "timeless"):
        if fmt in e: return fmt
    return "standard"


def detail(a, key):
    for d in a.get("details", []):
        if d.get("key") == key:
            for field in ("valueInt32", "valueString", "valueUint32"):
                if d.get(field): return d[field]
    return []


class Game:
    """One game of a match, from this player's seat."""
    def __init__(self, match, number, me):
        self.match, self.number, self.me = match, number, me
        self.opp = 3 - me
        self.objects, self.zones, self.players = {}, {}, {}
        self.turn_info = {}
        self.known = {}          # instance id -> card name, for hidden-zone cards this player has seen
        self.seen = {}           # card -> most copies identified at once this game
        self.ev = {}             # hand instance id -> evidence
        self.ev_seq = 0
        self.land_played = False
        self.my_land_played = False
        self.commander_casts = 0  # my commander's casts from the command zone, for its tax
        self.variant = None
        self.windows = []        # my plays the opponent could still respond to
        self.log = []
        self.last_turn = 0
        self.size = 0
        self.started = None
        self.over = False


class Tracker:
    def __init__(self, cards=None, on_game_end=None):
        self.cards = load_cards() if cards is None else cards
        self.on_game_end = on_game_end
        self.game = None
        self.names = {}            # seat -> screen name
        self.event = None
        self.match = None
        self.detailed = None       # None until the log says either way
        self.version = 0
        self.lines = self.messages = 0
        self.unknown_ids = set()

    # ---------- Lines ----------
    def feed(self, line):
        self.lines += 1
        if line.startswith("DETAILED LOGS:"):
            self.detailed = "ENABLED" in line
            self.version += 1
            return
        if not line.startswith("{"): return
        head = line[:400]
        if "greToClientEvent" in head:
            blob = self.parse(line)
            if blob:
                for m in blob["greToClientEvent"].get("greToClientMessages", []): self.on_message(m)
        elif "matchGameRoomStateChangedEvent" in head:
            blob = self.parse(line)
            if blob: self.on_room(blob["matchGameRoomStateChangedEvent"])

    @staticmethod
    def parse(line):
        # A line still being written, or cut off by the game closing, isn't an error.
        try: return json.loads(line)
        except ValueError: return None

    def on_room(self, ev):
        info = ev.get("gameRoomInfo", {})
        cfg = info.get("gameRoomConfig", {})
        for p in cfg.get("reservedPlayers", []) + info.get("players", []):
            if p.get("systemSeatId") and p.get("playerName"): self.names[p["systemSeatId"]] = p["playerName"]
            if p.get("eventId"): self.event = p["eventId"]
        self.match = cfg.get("matchId") or self.match
        if info.get("stateType") == "MatchGameRoomStateType_MatchCompleted":
            self.finish()
            self.game = None
        self.version += 1

    def on_message(self, m):
        state = m.get("gameStateMessage")
        if not state: return
        self.messages += 1
        seats = m.get("systemSeatIds") or []
        info = state.get("gameInfo") or {}
        if info.get("matchID") and seats:
            number = info.get("gameNumber", 1)
            g = self.game
            if not g or g.match != info["matchID"] or g.number != number or g.me != seats[0]:
                self.finish()
                self.game = Game(info["matchID"], number, seats[0])
                self.game.started = m.get("timestamp")
        g = self.game
        if not g: return
        if info.get("variant"): g.variant = info["variant"]
        if state.get("type") == "GameStateType_Full":
            g.objects, g.zones = {}, {}
        for z in state.get("zones", []): g.zones[z["zoneId"]] = z
        for o in state.get("gameObjects", []): g.objects[o["instanceId"]] = o
        for p in state.get("players", []): g.players[p.get("systemSeatNumber")] = p
        previous = dict(g.turn_info)
        if state.get("turnInfo"): g.turn_info.update(state["turnInfo"])
        # Annotations can name objects this same message deletes, so deletions come after.
        for a in state.get("annotations", []): self.on_annotation(g, a)
        for i in state.get("diffDeletedInstanceIds", []): g.objects.pop(i, None)
        self.on_steps(g, previous)
        self.update_seen(g)
        if info.get("stage") == "GameStage_GameOver" or info.get("matchState") == "MatchState_GameComplete":
            self.finish()
        self.version += 1

    # ---------- Reading the board ----------
    def zone_type(self, g, o): return (g.zones.get(o.get("zoneId")) or {}).get("type")

    def name_of(self, o):
        grp = o.get("grpId")
        c = self.cards.get(grp) or self.cards.get(o.get("overlayGrpId")) or self.cards.get(o.get("othersideGrpId"))
        if c: return c[0]
        # Arena gives each set's basic lands their own ids, which Scryfall doesn't always list.
        if "CardType_Land" in (o.get("cardTypes") or []) and "SuperType_Basic" in (o.get("superTypes") or []):
            for sub, mana in BASIC_MANA.items():
                if sub in (o.get("subtypes") or []): return BASIC_NAME[mana]
        if not grp: return "a card"
        self.unknown_ids.add(grp)
        return f"Unknown card #{grp}"

    def can_see(self, g, o):
        """Whether this player has really been shown this object. Never true for a hidden opponent's card."""
        if o.get("isFacedown") or o.get("facedown"): return False
        return o.get("visibility") == "Visibility_Public" or g.me in (o.get("viewers") or [])

    def in_zone(self, g, z):
        return [g.objects[i] for i in z.get("objectInstanceIds", []) if i in g.objects]

    def zone_of(self, g, ztype, seat=None):
        for z in g.zones.values():
            if z.get("type") == ztype and (seat is None or z.get("ownerSeatId") == seat): return z
        return {}

    def public_cards(self, g):
        """The opponent's identified cards outside their hand and library, and how many are face-down there."""
        pub, lost = {}, 0
        for z in g.zones.values():
            if z.get("type") not in PUBLIC_ZONES: continue
            for o in self.in_zone(g, z):
                if o.get("ownerSeatId") != g.opp or o.get("type") not in CARD_OBJECTS: continue
                if o.get("type") != "GameObjectType_Card" and z.get("type") != "ZoneType_Stack": continue
                if not self.can_see(g, o):
                    lost += 1
                    continue
                n = self.name_of(o)
                pub[n] = pub.get(n, 0) + 1
        return pub, lost

    def hand_cards(self, g):
        """The opponent's hand: cards this player knows by name, then instance ids of the unknown ones."""
        z = self.zone_of(g, "ZoneType_Hand", g.opp)
        known, slots = {}, []
        for i in z.get("objectInstanceIds", []):
            o = g.objects.get(i)
            name = None
            if o and o.get("type") == "GameObjectType_RevealedCard" and self.can_see(g, o): name = self.name_of(o)
            elif o and o.get("type") in CARD_OBJECTS and self.can_see(g, o): name = self.name_of(o)
            elif i in g.known: name = g.known[i]
            if name: known[name] = known.get(name, 0) + 1
            else: slots.append(i)
        return known, slots

    def untapped_mana(self, g, include_tapped=False, seat=None):
        """What each of a player's permanents can pay, one string per source, the opponent's by default. Summoning-sick creatures can't tap."""
        seat = seat or g.opp
        out = []
        for o in self.in_zone(g, self.zone_of(g, "ZoneType_Battlefield")):
            if o.get("controllerSeatId") != seat or o.get("type") != "GameObjectType_Card": continue
            if o.get("isTapped") and not include_tapped: continue
            types = o.get("cardTypes") or []
            if "CardType_Creature" in types and o.get("hasSummoningSickness") and not include_tapped: continue
            c = self.cards.get(o.get("grpId"))
            produced = c[2] if c else "".join(BASIC_MANA[s] for s in o.get("subtypes", []) if s in BASIC_MANA)
            if produced: out.append(produced)
        return out

    def update_seen(self, g):
        pub, _ = self.public_cards(g)
        known, _ = self.hand_cards(g)
        total = dict(pub)
        for n, k in known.items(): total[n] = total.get(n, 0) + k
        # A public reveal from the library (a scry shown to both, an impulse draw) also proves the card is in the deck.
        for o in self.in_zone(g, self.zone_of(g, "ZoneType_Library", g.opp)):
            if self.can_see(g, o) and o.get("grpId"):
                n = self.name_of(o)
                total[n] = total.get(n, 0) + 1
        for n, k in total.items():
            if k > g.seen.get(n, 0): g.seen[n] = k
        hand = len(self.zone_of(g, "ZoneType_Hand", g.opp).get("objectInstanceIds", []))
        library = len(self.zone_of(g, "ZoneType_Library", g.opp).get("objectInstanceIds", []))
        _, lost = self.public_cards(g)
        g.size = max(g.size, hand + library + lost + sum(pub.values()))

    # ---------- Evidence and the log ----------
    def add_log(self, g, msg):
        g.log.append({"t": g.turn_info.get("turnNumber", 0), "msg": msg})
        if len(g.log) > LOG_MAX: del g.log[:len(g.log) - LOG_MAX]

    def on_annotation(self, g, a):
        kinds = a.get("type") or []
        if "AnnotationType_ObjectIdChanged" in kinds:
            old, new = (detail(a, "orig_id") or [None])[0], (detail(a, "new_id") or [None])[0]
            if old is None or new is None: return
            # A card that was public and goes back to hand stays known. A face-up copy leaving public view is still that card.
            o = g.objects.get(old) or g.objects.get(new)
            # In the library the card is shuffled away from what was known about it.
            if self.zone_type(g, g.objects.get(new) or {}) == "ZoneType_Library": pass
            elif old in g.known: g.known[new] = g.known[old]
            elif o and o.get("ownerSeatId") == g.opp and o.get("type") in CARD_OBJECTS and o.get("grpId") and self.can_see(g, o) and self.zone_type(g, o) in PUBLIC_ZONES:
                g.known[new] = self.name_of(o)
            if old in g.ev: g.ev[new] = g.ev.pop(old)
        if "AnnotationType_ZoneTransfer" in kinds:
            self.on_transfer(g, a)

    def on_transfer(self, g, a):
        category = (detail(a, "category") or [None])[0]
        src = g.zones.get((detail(a, "zone_src") or [None])[0]) or {}
        dest = g.zones.get((detail(a, "zone_dest") or [None])[0]) or {}
        for i in a.get("affectedIds", []):
            o = g.objects.get(i) or {}
            if o.get("type") == "GameObjectType_Ability": continue
            owner = o.get("controllerSeatId") or o.get("ownerSeatId") or src.get("ownerSeatId") or dest.get("ownerSeatId")
            if category == "PlayLand" and owner == g.me: g.my_land_played = True
            if category == "CastSpell" and owner == g.me and src.get("type") == "ZoneType_Command": g.commander_casts += 1
            if category == "PlayLand" and owner == g.opp:
                g.land_played = True
                self.add_log(g, f"They played {self.name_of(o)}.")
            elif category == "CastSpell":
                if owner == g.opp:
                    if g.windows:
                        self.add_log(g, "They responded, so no \"no response\" evidence was logged.")
                        g.windows = []
                    self.add_log(g, f"They cast {self.name_of(o)}.")
                elif owner == g.me:
                    creature = "CardType_Creature" in (o.get("cardTypes") or [])
                    g.windows.append({"spell": i, "tags": ["c"] if creature else ["n"], "mana": self.untapped_mana(g), "why": f"Let your {self.name_of(o)} resolve", "w": 1})
            elif category in ("Resolve", "Countered") and owner == g.me:
                self.close_spell(g, i, category == "Resolve")
            elif owner == g.opp and category == "Discard":
                self.add_log(g, f"They discarded {self.name_of(o)}.")
            elif owner == g.opp and category == "Draw":
                self.add_log(g, "They drew a card.")

    def close_spell(self, g, spell, resolved):
        for w in list(g.windows):
            # The spell's instance id can change as it moves, so a lone open window is the one resolving.
            if w.get("spell") == spell or (len(g.windows) == 1 and w.get("spell") is not None):
                g.windows.remove(w)
                if resolved: self.commit(g, w)
                return

    def commit(self, g, w):
        _, slots = self.hand_cards(g)
        if not slots or not w["mana"]: return
        g.ev_seq += 1
        for i in slots:
            g.ev.setdefault(i, []).append({"n": g.ev_seq, "tags": w["tags"], "mana": w["mana"], "w": w["w"], "why": w["why"]})
        self.add_log(g, f"Auto: {w['why']} with {len(w['mana'])} mana open.")

    def on_steps(self, g, previous):
        info = g.turn_info
        turn = info.get("turnNumber", 0)
        my_turn = info.get("activePlayer") == g.me
        # Attacking: if the whole combat passes with their mana up and no play, tricks and removal are less likely.
        if my_turn and info.get("step") == "Step_DeclareBlock" and previous.get("step") != info.get("step"):
            attacking = [o for o in g.objects.values() if o.get("controllerSeatId") == g.me and o.get("attackState") in ("AttackState_Attacking", "AttackState_Declared")]
            if attacking: g.windows.append({"spell": None, "tags": ["r", "t", "f"], "mana": self.untapped_mana(g), "why": "Took your attack without a play", "w": ATTACK_WEIGHT})
        if info.get("step") == "Step_EndCombat" and previous.get("step") != info.get("step"):
            for w in [w for w in g.windows if w.get("spell") is None]:
                g.windows.remove(w)
                self.commit(g, w)
        if turn and turn != g.last_turn:
            # They had a whole turn and made no land drop: nothing in their hand is a land, near enough.
            if g.last_turn and previous.get("activePlayer") == g.opp and not g.land_played:
                _, slots = self.hand_cards(g)
                if slots:
                    g.ev_seq += 1
                    for i in slots: g.ev.setdefault(i, []).append({"n": g.ev_seq, "land": True, "why": "Missed a land drop"})
                    self.add_log(g, f"Auto: missed their land drop on turn {g.last_turn}, so their hand probably has no lands.")
            g.windows = []
            g.land_played = False
            g.my_land_played = False
            g.last_turn = turn

    # ---------- Finishing ----------
    def finish(self):
        g = self.game
        if not g or g.over: return
        g.over = True
        if self.on_game_end and sum(g.seen.values()) >= 4:
            self.on_game_end({"fmt": format_of(self.event), "opp": self.names.get(g.opp) or "Opponent", "match": g.match, "game": g.number, "seen": dict(g.seen), "size": g.size or 60})

    # ---------- The panel's view ----------
    def view(self):
        base = {"version": self.version, "detailed": self.detailed, "lines": self.lines}
        g = self.game
        if not g or not g.zones or g.over:
            return dict(base, state="idle")
        pub, lost = self.public_cards(g)
        known, slots = self.hand_cards(g)
        library = len(self.zone_of(g, "ZoneType_Library", g.opp).get("objectInstanceIds", []))
        # The first message of a game can arrive before its zones are filled.
        if not library and not slots and not pub: return dict(base, state="idle")
        life = lambda seat: (g.players.get(seat) or {}).get("lifeTotal")
        types = {}
        # Cards the database doesn't have yet still get a type from the log, for land odds.
        for o in g.objects.values():
            if o.get("ownerSeatId") == g.opp and o.get("grpId") and o.get("grpId") not in self.cards and self.can_see(g, o):
                types[self.name_of(o)] = next((c for t, c in TYPE_CODE if t in (o.get("cardTypes") or [])), "?")
        info = g.turn_info
        return dict(base, state="duel", match=g.match, game=g.number, opp=self.names.get(g.opp) or "Opponent", event=self.event, format=format_of(self.event),
                    turn=info.get("turnNumber", 0), phase=info.get("phase"), step=info.get("step"), myTurn=info.get("activePlayer") == g.me,
                    life={"me": life(g.me), "opp": life(g.opp)}, library=library, handCount=len(slots) + sum(known.values()),
                    hand=[{"id": i, "ev": g.ev.get(i, [])} for i in slots], kh=known, pub=pub, seen=dict(g.seen), lost=lost,
                    mana=self.untapped_mana(g), manaAll=self.untapped_mana(g, include_tapped=True), size=g.size,
                    types=types, log=g.log[-120:], pending=len(g.windows))
