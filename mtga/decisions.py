"""Turns Arena's log into training records: what you could do at each decision, and what you did.

Arena logs the plays it offers (ActionsAvailableReq, DeclareAttackersReq) and your answers, joined by respId.
A record holds your own cards and what both players can see of the opponent, the same rule as tracker.py.
"""
import json
from tracker import Tracker, CARD_OBJECTS, format_of

SKIP_ACTIONS = {"ActionType_Activate_Mana", "ActionType_FloatMana"}
OUTGOING = "clientToMatchServiceMessageType"


def load_details(path=None):
    """Card name -> (mana value, tags), from mtg-cards.js."""
    import os
    src = open(path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "mtg-cards.js"), encoding="utf-8").read()
    data = json.loads(src[src.index("window.MTG_CARD_DATA = ") + 23:].rstrip().rstrip(";"))
    out = {}
    for line in data.split("\n"):
        f = line.split("\t")
        out[f[0]] = (int(f[2]), f[5])
    return out


class Recorder(Tracker):
    def __init__(self, cards=None, on_game_end=None, on_decision=None, details=None):
        super().__init__(cards, on_game_end)
        self.on_decision = on_decision
        self.details = load_details() if details is None else details
        self.pending = {}      # msgId -> record waiting for an answer
        self.latest = None     # the newest unanswered decision
        self.combat = None     # attackers offered this combat, and those selected so far
        self.buffer = None
        self.depth = 0
        self.decisions = 0

    # Your answers are pretty-printed over several lines, unlike what the server sends.
    def feed(self, line):
        if self.buffer is not None:
            self.buffer.append(line)
            self.depth += line.count("{") - line.count("}")
            if self.depth <= 0 or len(self.buffer) > 3000:
                text, self.buffer = "\n".join(self.buffer), None
                if OUTGOING in text[:400]:
                    blob = self.parse(text)
                    if blob: self.on_answer(blob.get("payload") or {})
            return
        if line == "{":
            self.buffer, self.depth = [line], 1
            return
        super().feed(line)

    def on_message(self, m):
        super().on_message(m)
        g = self.game
        if not g or g.over: return
        seats = m.get("systemSeatIds") or []
        if seats and seats[0] != g.me: return
        if m.get("type") == "GREMessageType_ActionsAvailableReq": self.on_actions(g, m)
        elif m.get("type") == "GREMessageType_DeclareAttackersReq": self.on_attackers(g, m)

    # ---------- Situation ----------
    def creatures(self, g, seat):
        out = []
        for o in self.in_zone(g, self.zone_of(g, "ZoneType_Battlefield")):
            if o.get("controllerSeatId") == seat and "CardType_Creature" in (o.get("cardTypes") or []):
                out.append([(o.get("power") or {}).get("value", 0), (o.get("toughness") or {}).get("value", 0), bool(o.get("isTapped"))])
        return out

    def situation(self, g):
        info = g.turn_info
        life = lambda seat: (g.players.get(seat) or {}).get("lifeTotal")
        hand = [self.name_of(o) for o in self.in_zone(g, self.zone_of(g, "ZoneType_Hand", g.me))]
        stack = self.in_zone(g, self.zone_of(g, "ZoneType_Stack"))
        lands = sum(1 for o in self.in_zone(g, self.zone_of(g, "ZoneType_Battlefield")) if o.get("controllerSeatId") == g.me and "CardType_Land" in (o.get("cardTypes") or []))
        return {"turn": info.get("turnNumber", 0), "phase": (info.get("phase") or "").replace("Phase_", ""), "step": (info.get("step") or "").replace("Step_", ""),
                "myTurn": info.get("activePlayer") == g.me, "life": life(g.me), "oppLife": life(g.opp), "hand": hand,
                "mine": self.creatures(g, g.me), "theirs": self.creatures(g, g.opp), "lands": lands, "mana": len(self.untapped_mana(g, seat=g.me)),
                "oppMana": len(self.untapped_mana(g)), "oppHand": len(self.zone_of(g, "ZoneType_Hand", g.opp).get("objectInstanceIds", [])),
                "stack": len(stack), "oppOnStack": any(o.get("controllerSeatId") == g.opp for o in stack), "landPlayed": g.my_land_played,
                "commanderCasts": g.commander_casts, "brawl": g.variant == "GameVariant_Brawl"}

    def base(self, g, kind):
        return dict(self.situation(g), kind=kind, game=f"{g.match}#{g.number}", event=self.event, fmt=format_of(self.event))

    def card_fields(self, g, grp, instance):
        o = g.objects.get(instance) or {"grpId": grp}
        name = self.name_of(dict(o, grpId=grp or o.get("grpId")))
        cmc, tags = self.details.get(name, (0, ""))
        return {"name": name, "cmc": cmc, "tags": tags, "ctype": next((t.replace("CardType_", "") for t in (o.get("cardTypes") or [])), ""),
                "commander": self.zone_type(g, o) == "ZoneType_Command"}

    # ---------- Decisions ----------
    def on_actions(self, g, m):
        self.latest = None
        cands = []
        for a in (m.get("actionsAvailableReq") or {}).get("actions", []):
            t = a.get("actionType")
            if t in SKIP_ACTIONS: continue
            c = {"key": self.action_key(a), "play": (t or "").replace("ActionType_", ""), "cost": sum(x.get("count", 0) for x in a.get("manaCost") or [])}
            if t != "ActionType_Pass": c.update(self.card_fields(g, a.get("grpId"), a.get("instanceId")))
            cands.append(c)
        if not any(c["play"] == "Pass" for c in cands): cands.append({"key": "ActionType_Pass||", "play": "Pass", "cost": 0})
        if len(cands) < 2: return
        rec = dict(self.base(g, "priority"), cands=cands)
        self.pending[m.get("msgId")] = rec
        self.latest = [rec]

    @staticmethod
    def action_key(a):
        t = a.get("actionType")
        return f"{t}||" if t == "ActionType_Pass" else f"{t}|{a.get('instanceId')}|{a.get('abilityGrpId') or ''}"

    def on_attackers(self, g, m):
        offered = (m.get("declareAttackersReq") or {}).get("qualifiedAttackers") or []
        if self.combat and self.combat["game"] == (g.match, g.number, g.turn_info.get("turnNumber")): return
        recs = {}
        for a in offered:
            i = a.get("attackerInstanceId")
            o = g.objects.get(i) or {}
            attacker = dict(self.card_fields(g, o.get("grpId"), i), power=(o.get("power") or {}).get("value", 0), toughness=(o.get("toughness") or {}).get("value", 0))
            recs[i] = dict(self.base(g, "attack"), attacker=attacker, cands=[{"key": "attack", "play": "Attack"}, {"key": "hold", "play": "Hold"}])
        if not recs: return
        self.combat = {"game": (g.match, g.number, g.turn_info.get("turnNumber")), "recs": recs, "selected": set()}
        self.latest = list(recs.values())

    def on_answer(self, p):
        t = p.get("type")
        if t == "ClientMessageType_PerformActionResp":
            rec = self.pending.pop(p.get("respId"), None)
            actions = (p.get("performActionResp") or {}).get("actions") or []
            if rec and actions:
                key = self.action_key(actions[0])
                if any(c["key"] == key for c in rec["cands"]): self.emit(rec, key)
            self.latest = None
        elif t == "ClientMessageType_DeclareAttackersResp" and self.combat:
            r = p.get("declareAttackersResp") or {}
            self.combat["selected"] = set(self.combat["recs"]) if r.get("autoDeclare") else {a.get("attackerInstanceId") for a in r.get("selectedAttackers") or []}
        elif t == "ClientMessageType_SubmitAttackersReq" and self.combat:
            for i, rec in self.combat["recs"].items(): self.emit(rec, "attack" if i in self.combat["selected"] else "hold")
            self.combat["recs"] = {}
            self.latest = None

    def emit(self, rec, key):
        rec = dict(rec, chosen=key)
        self.decisions += 1
        if self.on_decision: self.on_decision(rec)
