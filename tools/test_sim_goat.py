"""Checks the Goat simulator's rules on small set-up positions.

Usage: python3 tools/test_sim_goat.py
"""
import os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim_goat as S

CARDS = S.load_cards()

def game(hand=(), mon=(), st=(), gy=(), deck=(), op_hand=(), op_mon=(), op_st=(), op_deck=(), phase="M1", turn=3):
    """A game at the start of P1's turn `turn`, with the zones given by card name. "fd:Name" is face-down."""
    decks = {"a": ("A", ["Kuriboh"] * 40), "b": ("B", ["Kuriboh"] * 40)}
    g = S.Game(decks, CARDS, random.Random(1), [S.scripted, S.scripted], False, "t")
    g.active, g.turn, g.phase = 0, turn, phase
    me, op = g.p
    def fill(pl, zone, names, i):
        lst = []
        for n in names:
            fd = n.startswith("fd:")
            c = g.make(n[3:] if fd else n); c.owner = i; c.fd = fd; c.set_turn = 1
            if zone in ("mon",) and fd: c.pos = "DEF"
            lst.append(c)
        setattr(pl, zone, lst)
    for pl, i, h, m, s, gyard, d in ((me, 0, hand, mon, st, gy, deck), (op, 1, op_hand, op_mon, op_st, (), op_deck)):
        fill(pl, "hand", h, i); fill(pl, "mon", m, i); fill(pl, "st", s, i); fill(pl, "gy", gyard, i)
        fill(pl, "deck", d or ["Kuriboh"] * 10, i)
    me.drew = True
    return g, me, op

def key(pl, name, play, target=None):
    c = next(x for x in pl.hand + pl.mon + pl.st if x.name == name)
    return f"card|{c.uid}|{play}" + (f"|{target.uid}" if target else "")

def names(zone): return [c.name for c in zone]

def check(cond, what):
    if not cond: raise AssertionError(what)

def test_tokens_arent_tributed():
    g, me, op = game(hand=["Zaborg the Thunder Monarch"])
    for _ in range(2):
        t = S.Card("tok" + str(me.plays), "Sheep Token", None); t.pos = "DEF"; me.mon.append(t); me.plays += 1
    k = key(me, "Zaborg the Thunder Monarch", "Normal Summon")
    check(k not in S.legal(g, me, g.candidates(me)), "a Tribute Summon over tokens alone is offered as legal")
    g.apply(me, k)
    check(names(me.hand) == ["Zaborg the Thunder Monarch"] and len(me.mon) == 2, "tokens were tributed for Zaborg")

def test_spirits_return():
    g, me, op = game(hand=["Asura Priest"])
    g.apply(me, key(me, "Asura Priest", "Normal Summon"))
    check(names(me.mon) == ["Asura Priest"], "Asura wasn't summoned")
    g.end_turn()
    check(names(me.hand) == ["Asura Priest"] and not me.mon, "Asura Priest didn't return to the hand in the End Phase")

def test_asura_attacks_every_monster():
    g, me, op = game(mon=["Asura Priest"], op_mon=["Kuriboh", "Sangan"], phase="BP")
    a = me.mon[0]
    g.apply(me, key(me, "Asura Priest", "Attack", op.mon[0]))
    check(len(op.mon) == 1, "Asura's first attack didn't destroy Kuriboh")
    check(key(me, "Asura Priest", "Attack", op.mon[0]) in S.legal(g, me, g.candidates(me)), "Asura can't attack a second monster")
    g.apply(me, key(me, "Asura Priest", "Attack", op.mon[0]))
    check(not op.mon, "Asura's second attack didn't destroy Sangan")
    check(key(me, "Asura Priest", "Attack directly") not in S.legal(g, me, g.candidates(me)), "Asura could attack directly after attacking monsters")
    g2, me2, op2 = game(mon=["Gemini Elf"], op_mon=["Kuriboh", "Sangan"], phase="BP")
    g2.apply(me2, key(me2, "Gemini Elf", "Attack", op2.mon[0]))
    check(not any("|Attack" in k for k in S.legal(g2, me2, g2.candidates(me2))), "an ordinary monster got a second attack")

def test_premature_burial_is_tied_to_its_monster():
    g, me, op = game(hand=["Premature Burial"], gy=["Gemini Elf"], op_hand=["Heavy Storm"])
    g.apply(me, key(me, "Premature Burial", "Activate ST"))
    check(names(me.mon) == ["Gemini Elf"] and names(me.st) == ["Premature Burial"] and me.lp == 7200, "Premature Burial didn't revive and stay on the field")
    check(me.st[0].link is me.mon[0] and me.mon[0].link is me.st[0], "Premature Burial isn't linked to its monster")
    g.active = 1
    g.apply(op, key(op, "Heavy Storm", "Activate ST"))
    check(not me.st and not me.mon and names(me.gy) == ["Gemini Elf", "Premature Burial"], f"destroying Premature Burial didn't take the monster: mon={names(me.mon)} gy={names(me.gy)}")

def test_tributing_the_monster_sends_premature_to_the_graveyard():
    g, me, op = game(hand=["Premature Burial", "Zaborg the Thunder Monarch"], gy=["Gemini Elf"])
    g.apply(me, key(me, "Premature Burial", "Activate ST"))
    g.apply(me, key(me, "Zaborg the Thunder Monarch", "Normal Summon"))
    check(names(me.mon) == ["Zaborg the Thunder Monarch"] and not me.st, "Premature Burial stayed after its monster was tributed")

def test_snatch_steal_returns_the_monster():
    g, me, op = game(hand=["Snatch Steal"], op_mon=["Gemini Elf"], op_hand=["Mystical Space Typhoon"])
    g.apply(me, key(me, "Snatch Steal", "Activate ST"))
    check(names(me.mon) == ["Gemini Elf"] and names(me.st) == ["Snatch Steal"], "Snatch Steal didn't take the monster and stay")
    lp = me.lp
    g.active = 1; g.play_turn.__func__  # the Standby gain is checked through play_turn below
    g.apply(op, key(op, "Mystical Space Typhoon", "Activate ST"))
    check(not me.mon and names(op.mon) == ["Gemini Elf"] and not me.st, f"the monster didn't go back when Snatch Steal was destroyed: me={names(me.mon)} op={names(op.mon)}")
    g2, me2, op2 = game(hand=["Snatch Steal"], op_mon=["Gemini Elf"], op_deck=["Kuriboh"] * 10)
    g2.apply(me2, key(me2, "Snatch Steal", "Activate ST"))
    g2.end_turn(); lp = op2.lp
    g2.policies = [lambda *a: "global|End turn"] * 2
    g2.play_turn()
    check(op2.lp == lp + 1000, "Snatch Steal's owner didn't gain 1000 in their Standby Phase")

def test_sangan_only_searches_from_the_field():
    g, me, op = game(hand=["Sangan", "Graceful Charity"], deck=["Magician of Faith"] + ["Kuriboh"] * 9)
    g.to_gy(me, me.hand[0])
    check(all(c.name != "Magician of Faith" for c in me.hand), "Sangan searched when discarded from the hand")
    g2, me2, op2 = game(mon=["Sangan"], deck=["Magician of Faith"] + ["Kuriboh"] * 9)
    g2.to_gy(me2, me2.mon[0])
    check(names(me2.hand) == ["Magician of Faith"], "Sangan didn't search when it left the field")

def test_fusilier_summons_without_tribute():
    g, me, op = game(hand=["Fusilier Dragon, the Dual-Mode Beast"])
    k = key(me, "Fusilier Dragon, the Dual-Mode Beast", "Normal Summon")
    check(k in S.legal(g, me, g.candidates(me)), "Fusilier's tribute-less summon isn't legal")
    g.apply(me, k)
    check(len(me.mon) == 1 and me.mon[0].atk == 1400 and me.mon[0].def_ == 1000, "Fusilier didn't land as a 1400/1000")

def test_nightmare_wheel_locks_and_burns():
    g, me, op = game(st=["fd:Nightmare Wheel"], op_mon=["Gemini Elf"], op_deck=["Kuriboh"] * 10)
    g.apply(me, key(me, "Nightmare Wheel", "Activate ST"))
    elf = op.mon[0]
    check(g.is_locked(elf) and names(me.st) == ["Nightmare Wheel"], "Nightmare Wheel didn't lock the monster")
    g.end_turn(); g.phase = "BP"
    check(not g.can_attack(op, elf), "a monster held by Nightmare Wheel could attack")
    g.end_turn(); lp = op.lp
    g.policies = [lambda *a: "global|End turn"] * 2
    g.play_turn()
    check(op.lp == lp - 500, "Nightmare Wheel didn't burn 500 in the Standby Phase")
    g.destroy(me, me.st[0])
    check(not g.is_locked(elf), "the lock outlived Nightmare Wheel")

def test_xing_zhen_hu_locks_set_cards():
    g, me, op = game(st=["fd:Xing Zhen Hu"], op_st=["fd:Mirror Force", "fd:Sakuretsu Armor"], mon=["Gemini Elf"])
    g.apply(me, key(me, "Xing Zhen Hu", "Activate ST"))
    check(all(g.is_locked(x) for x in op.st), "Xing Zhen Hu didn't lock both set cards")
    check(not g.ready(op, {"Mirror Force", "Sakuretsu Armor"}), "locked traps count as ready")

def test_reckless_greed_skips_two_draws():
    g, me, op = game(st=["fd:Reckless Greed"])
    g.apply(me, key(me, "Reckless Greed", "Activate ST"))
    check(me.obligations == [("draw", 2)] and me.skip_draw == 2, "Reckless Greed didn't owe two draws and skip two")

def test_night_assailant_discard_returns_a_flip_monster():
    g, me, op = game(hand=["Night Assailant"], gy=["Magician of Faith"])
    g.to_gy(me, me.hand[0])
    check(names(me.hand) == ["Magician of Faith"], "Night Assailant discarded from the hand didn't return Magician of Faith")

def test_cyber_stein_pays_for_lethal():
    g, me, op = game(hand=["Cyber-Stein"])
    op.lp = 4000
    g.apply(me, key(me, "Cyber-Stein", "Normal Summon"))
    check(names(me.mon) == ["Cyber-Stein", "Blue-Eyes Ultimate Dragon"] and me.lp == 3000, f"Cyber-Stein didn't bring the dragon for lethal: {names(me.mon)} lp={me.lp}")
    g2, me2, op2 = game(hand=["Cyber-Stein"], op_mon=["Gemini Elf", "Gemini Elf", "Gemini Elf"])
    g2.apply(me2, key(me2, "Cyber-Stein", "Normal Summon"))
    check(names(me2.mon) == ["Cyber-Stein"] and me2.lp == 8000, "Cyber-Stein paid 5000 into a full board at 8000")

def test_zombyra_cant_attack_directly():
    g, me, op = game(mon=["Zombyra the Dark"], phase="BP")
    check(key(me, "Zombyra the Dark", "Attack directly") not in S.legal(g, me, g.candidates(me)), "Zombyra could attack directly")

def test_clone_keeps_links():
    g, me, op = game(hand=["Premature Burial"], gy=["Gemini Elf"])
    g.apply(me, key(me, "Premature Burial", "Activate ST"))
    c, me2 = g.clone(me, random.Random(2))
    check(me2.st[0].link is me2.mon[0] and me2.mon[0].link is me2.st[0], "a clone's links point at the original game's cards")
    check(me2.st[0] is not me.st[0], "the clone shares cards with the original")

def test_teacher_keeps_the_important_plays():
    g, me, op = game(hand=["Gemini Elf", "Kuriboh", "Sangan", "Mystic Tomato", "Blade Knight", "Mirror Force", "Sakuretsu Armor"], mon=["Gemini Elf"], phase="M1")
    uniq, same, info = S.teacher_candidates(g, me, g.candidates(me), 14)
    plays = {info[k][0] for k in uniq}
    check("End turn" in plays and "Set ST" in plays and "Enter BP" in plays, f"the teacher's list lost End turn, Set ST or Enter BP: {sorted(plays)}")
    check(len(uniq) <= 14, "the teacher looks at more plays than its cap")

def test_scapegoat_metamorphosis_makes_thousand_eyes():
    g, me, op = game(hand=["Scapegoat", "Metamorphosis"], op_mon=["Jinzo"])
    check(key(me, "Metamorphosis", "Activate ST") not in S.legal(g, me, g.candidates(me)), "Metamorphosis is legal with no level 1 monster")
    check(S.scripted(g, me, g.candidates(me)) == key(me, "Scapegoat", "Activate ST"), "the scripted player didn't Scapegoat first for Metamorphosis")
    g.apply(me, key(me, "Scapegoat", "Activate ST"))
    check(S.scripted(g, me, g.candidates(me)) == key(me, "Metamorphosis", "Activate ST"), "the scripted player didn't follow with Metamorphosis")
    g.apply(me, key(me, "Metamorphosis", "Activate ST"))
    ter = next(x for x in me.mon if x.name == S.TER)
    check(len(me.mon) == 4 and not op.mon, f"Metamorphosis didn't turn a token into Thousand-Eyes and absorb Jinzo: {names(me.mon)} / {names(op.mon)}")
    check(ter.eats and ter.eats.name == "Jinzo" and ter.atk == 2400 and names(me.st) == ["Jinzo"], "Thousand-Eyes didn't gain Jinzo's stats or keep it as an equip")
    check(names(op.gy) == [] and "Metamorphosis" in names(me.gy), "the wrong cards went to the graveyard")

def test_thousand_eyes_locks_attacks_and_shields_itself():
    g, me, op = game(hand=["Scapegoat", "Metamorphosis"], op_mon=["Jinzo", "Gemini Elf"])
    g.apply(me, key(me, "Scapegoat", "Activate ST")); g.apply(me, key(me, "Metamorphosis", "Activate ST"))
    ter = next(x for x in me.mon if x.name == S.TER)
    g.end_turn(); g.phase = "BP"
    elf = op.mon[0]
    check(not g.can_attack(op, elf), "a monster attacked while Thousand-Eyes Restrict was face-up")
    g.active = 0; g.phase = "BP"
    g.battle_destroy(me, ter)
    check(ter in me.mon and ter.eats is None and ter.atk == 0 and "Jinzo" in names(op.gy), "Thousand-Eyes didn't lose its meal instead of itself in battle")

def test_thousand_eyes_leaving_takes_its_meal():
    g, me, op = game(hand=["Scapegoat", "Metamorphosis"], op_mon=["Jinzo"])
    g.apply(me, key(me, "Scapegoat", "Activate ST")); g.apply(me, key(me, "Metamorphosis", "Activate ST"))
    ter = next(x for x in me.mon if x.name == S.TER)
    g.destroy(me, ter)
    check(not me.st and "Jinzo" in names(op.gy) and S.TER in names(me.gy), f"Jinzo didn't go to its owner's graveyard with Thousand-Eyes: st={names(me.st)} op gy={names(op.gy)}")

def test_heavy_storm_on_the_meal_strips_thousand_eyes():
    g, me, op = game(hand=["Scapegoat", "Metamorphosis"], op_mon=["Jinzo"], op_hand=["Heavy Storm"])
    g.apply(me, key(me, "Scapegoat", "Activate ST")); g.apply(me, key(me, "Metamorphosis", "Activate ST"))
    ter = next(x for x in me.mon if x.name == S.TER)
    g.active = 1; g.apply(op, key(op, "Heavy Storm", "Activate ST"))
    check(ter in me.mon and ter.eats is None and ter.atk == 0, "Heavy Storm didn't strip Thousand-Eyes back to 0 ATK")

def test_face_down_thousand_eyes_loses_its_meal():
    g, me, op = game(hand=["Scapegoat", "Metamorphosis"], op_mon=["Jinzo"])
    g.apply(me, key(me, "Scapegoat", "Activate ST")); g.apply(me, key(me, "Metamorphosis", "Activate ST"))
    ter = next(x for x in me.mon if x.name == S.TER)
    g.flip_down(ter)
    check(ter.eats is None and ter.atk == 0 and not me.st and "Jinzo" in names(op.gy), "a face-down Thousand-Eyes kept its meal")
    g.end_turn(); g.phase = "BP"
    check(not any(x.name == S.TER and not x.fd for x in me.mon), "the face-down Thousand-Eyes still counts as face-up")

def test_empty_deck_loses():
    g, me, op = game()
    me.deck = []
    g.play_turn()
    check(g.winner is op, "a player with no cards to draw didn't lose")

def test_goat_control_filter():
    decks = S.load_fl_decks(10**6, "goat control")
    check(decks and all(t == "Goat Control" for t, _ in decks.values()), "the deck-type filter let other decks through")

def test_scripted_game_runs():
    decks = S.load_decks(None)
    wins = 0
    for i in range(30):
        g = S.Game(decks, CARDS, random.Random(i), [S.scripted, S.scripted], True, f"t{i}")
        w = g.run()
        wins += w is not None
        for r in g.records: check(0 <= r["chosen"] < len(r["cands"]), "a record's chosen play is out of range")
    check(wins >= 20, f"only {wins} of 30 scripted games ended in a win")

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try: t(); print(f"ok   {t.__name__}")
        except Exception as e:
            failed += 1; print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed} of {len(tests)} passed")
    sys.exit(1 if failed else 0)
