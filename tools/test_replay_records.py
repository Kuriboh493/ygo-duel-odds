"""Checks tools/replay_records.py on a small hand-written replay: boards are rebuilt from the log lines, the
human's plays become the chosen candidates, hidden cards stay hidden, and the game's winner is recorded.

  python3 tools/test_replay_records.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import replay_records as R

def card(name, ctype, atk=None, def_=None, level=None):
    return {"name": name, "serial_number": "0", "card_type": ctype, "atk": atk, "def": def_, "level": level, "attribute": "LIGHT"}

def log(user, text, private=None):
    return {"public_log": text, "private_log": private or text, "type": "duel", "username": user}

def play(name, user, text, **kw):
    return dict({"play": name, "username": user, "log": log(user, text)}, **kw)

A, B = "alice", "bob"
REPLAY = {
    "player1": {"username": A, "main_total": 40}, "player2": {"username": B, "main_total": 40},
    "plays": [
        {"play": "Pick first", "username": A, "order": [A, B], "log":
            [log(A, "Chose to go first")] + [log(A, "Drew a card", f'Drew "{n}"') for n in ["Sangan", "Jinzo", "Heavy Storm", "Sakuretsu Armor", "Pot of Greed"]]
            + [log(B, "Drew a card", f'Drew "{n}"') for n in ["Breaker the Magical Warrior", "Mirror Force", "Snatch Steal", "Sangan", "Book of Moon"]]},
        play("Draw card", A, "Drew a card", card=card("Tsukuyomi", "Monster", "1100", "1400", 4)),
        play("Enter SP", A, "Entered Standby Phase"),
        play("Enter M1", A, "Entered Main Phase 1"),
        play("Set monster", A, 'Set "Sangan" from hand (1/6) to M-3'),
        play("Set ST", A, 'Set "Sakuretsu Armor" from hand (3/5) to S-2'),
        play("End turn", A, "Ended turn"),
        play("Start turn", B, "Entered Draw Phase"),
        play("Draw card", B, "Drew a card", card=card("Nobleman of Crossout", "Spell")),
        play("Enter SP", B, "Entered Standby Phase"),
        play("Enter M1", B, "Entered Main Phase 1"),
        play("Normal Summon", B, 'Normal Summoned "Breaker the Magical Warrior" from hand (1/6) to M-3',
             card=card("Breaker the Magical Warrior", "Monster", "1600", "1000", 4)),
        play("Enter BP", B, "Entered Battle Phase"),
        play("Attack", B, 'Attacked Set card in M-3 with "Breaker the Magical Warrior" in M-3'),
        play("Flip", A, 'Flipped Set "Sangan" in M-3', card=card("Sangan", "Monster", "1000", "600", 3)),
        play("To GY", A, 'Sent "Sangan" from M-3 to GY'),
        play("Life points", A, "Lost 8000 LP", life=0),
    ],
}

def test_records():
    recs, games = R.convert(REPLAY, {}, "t")
    picks = [(r["player"], r["phase"], r["cands"][r["chosen"]]["play"], (r["cands"][r["chosen"]].get("card") or {}).get("name")) for r in recs]
    assert picks == [
        (A, "DP", "Draw card", None), (A, "DP", "Enter SP", None), (A, "SP", "Enter M1", None),
        (A, "M1", "Set monster", "Sangan"), (A, "M1", "Set ST", "Sakuretsu Armor"), (A, "M1", "End turn", None),
        (B, "DP", "Draw card", None), (B, "DP", "Enter SP", None), (B, "SP", "Enter M1", None),
        (B, "M1", "Normal Summon", "Breaker the Magical Warrior"), (B, "M1", "Enter BP", None), (B, "BP", "Attack", "Breaker the Magical Warrior"),
    ], picks
    attack = recs[-1]
    # Bob sees Alice's set monster and set card as face-down, and her hand only as a count.
    assert attack["opp"]["mon"] == [{"zone": "monster", "pos": "FD"}], attack["opp"]
    assert attack["opp"]["st"] == [{"zone": "spell/trap", "pos": "FD"}]
    assert attack["opp"]["hand"] == 4 and len(attack["me"]["hand"]) == 5
    assert attack["cands"][attack["chosen"]]["target"]["pos"] == "FD"
    assert attack["me"]["mon"][0]["atk"] == 1600 and attack["summonsThisTurn"] == 1
    # Alice hit 0 LP, so Bob won.
    assert games == [(B, A, 12)], games
    assert {r["player"]: r["won"] for r in recs} == {A: 0, B: 1}

def test_effect_draws_and_discards():
    """Pot of Greed's draws and Graceful Charity's draws and discards are decisions; a discard for a cost isn't."""
    replay = {
        "player1": {"username": A, "main_total": 40}, "player2": {"username": B, "main_total": 40},
        "plays": [
            {"play": "Pick first", "username": A, "order": [A, B], "log":
                [log(A, "Chose to go first")] + [log(A, "Drew a card", f'Drew "{n}"') for n in ["Sangan", "Jinzo", "Graceful Charity", "Sakuretsu Armor", "Pot of Greed"]]
                + [log(B, "Drew a card", f'Drew "{n}"') for n in ["Breaker the Magical Warrior", "Mirror Force", "Snatch Steal", "Sangan", "Book of Moon"]]},
            play("Draw card", A, "Drew a card", card=card("Tsukuyomi", "Monster", "1100", "1400", 4)),
            play("Enter SP", A, "Entered Standby Phase"),
            play("Enter M1", A, "Entered Main Phase 1"),
            play("To GY", A, 'Sent "Jinzo" from hand to GY'),
            play("Activate ST", A, 'Activated "Pot of Greed" from hand (5/5) to S-3', card=card("Pot of Greed", "Spell")),
            play("Draw card", A, "Drew a card", card=card("Heavy Storm", "Spell")),
            play("Draw card", A, "Drew a card", card=card("Scapegoat", "Spell")),
            play("To GY", A, 'Sent "Pot of Greed" from S-3 to GY'),
            play("Activate ST", A, 'Activated "Graceful Charity" from hand (2/6) to S-3', card=card("Graceful Charity", "Spell")),
            play("Draw card", A, "Drew a card", card=card("Mirror Force", "Trap")),
            play("Draw card", A, "Drew a card", card=card("Sinister Serpent", "Monster", "300", "250", 1)),
            play("Draw card", A, "Drew a card", card=card("Book of Moon", "Spell")),
            play("To GY", A, 'Sent "Sinister Serpent" from hand to GY'),
            play("To GY", A, 'Sent "Tsukuyomi" from hand to GY'),
            play("To GY", A, 'Sent "Graceful Charity" from S-3 to GY'),
            play("To GY", A, 'Sent "Sangan" from hand to GY'),
            play("Draw card", A, "Drew a card", card=card("Metamorphosis", "Spell")),  # a draw no effect owes: not a decision
            play("End turn", A, "Ended turn"),
        ],
    }
    recs, _ = R.convert(replay, {}, "t")
    picks = [(r["cands"][r["chosen"]]["play"], (r["cands"][r["chosen"]].get("card") or {}).get("name")) for r in recs if r["phase"] == "M1"]
    assert picks == [("Activate ST", "Pot of Greed"), ("Draw card", None), ("Draw card", None),
                     ("Activate ST", "Graceful Charity"), ("Draw card", None), ("Draw card", None), ("Draw card", None),
                     ("To GY", "Sinister Serpent"), ("To GY", "Tsukuyomi"), ("End turn", None)], picks
    first_draw = next(r for r in recs if r["phase"] == "M1" and r["cands"][r["chosen"]]["play"] == "Draw card")
    assert first_draw["lastPlay"] == "Activate ST" and first_draw["lastCard"] == "Pot of Greed", first_draw
    # Only decisions count as plays: sending the used Pot of Greed to the Graveyard doesn't, so when Graceful
    # Charity is activated the last play is still the second draw, as it would be in the simulator.
    gc = next(r for r in recs if (r["cands"][r["chosen"]].get("card") or {}).get("name") == "Graceful Charity")
    assert gc["lastPlay"] == "Draw card" and gc["drawsThisTurn"] == 3 and gc["playsThisTurn"] == 6, gc
    assert gc["turnHistory"] == ["Draw card:", "Enter SP:", "Enter M1:", "Activate ST:Pot of Greed"], gc["turnHistory"]

if __name__ == "__main__":
    test_records(); print("ok   test_records")
    test_effect_draws_and_discards(); print("ok   test_effect_draws_and_discards")
