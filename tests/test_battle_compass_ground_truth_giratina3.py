"""Ground truth: ``data/battle_logs/giratina3.jsonl`` -- 21 turns, the richest log yet.

A gdb capture at seed ``0x49022ff1`` running most of the real Giratina plan: a Lv54 Magneton
paralyses and Screeches it, a Lv64 Smeargle comes in to Foresight and False Swipe it to 1 HP, and a
Lv52 Honchkrow with Leftovers takes over for the ball throws, Hazing off Ancient Power boosts and
finishing with a Mean Look.

**It found one bug.** Turn 6 is a switch turn whose Shadow Force FIRE lands on the incoming
Normal-typed Smeargle and does nothing -- and the simulator spent 14 advances against the game's
16. The control is `giratina2.jsonl`'s turn 6, which is the same shape *without* the charge:

=================================================  ==================
turn                                               trailing advances
=================================================  ==================
``giratina2`` T6: ineffective Ominous Wind          **4**
``giratina3`` T6: ineffective Shadow Force (fire)   **6**
=================================================  ==================

So a charge that COMPLETES runs its cleanup whether or not the hit connected --
`effect_script_0272.s` reaches `_055` by falling through the fire branch, before any hit verdict
is applied -- and that cleanup is the two-advance block. The post-move block therefore has three
sources, not one: an ordinary successful move, a completing charge, and a prevented turn that
BREAKS one. Only an ineffective *ordinary* move runs no subscript and so forfeits it
(clayton-6xu.3.14).

**What it confirms**, none of it needing a change: the ball path, including that the rolls spent
are shakes + 1 and that the shake count matches the message the player reads; Leftovers;
Foresight landing and making the next False Swipe connect against a Ghost; Haze; Mean Look; and
the whole Shadow Force cycle twice over.

**And it corroborates the no-ball-while-vanished rule from the player's own behaviour**: on turn
16, with Giratina away, Testare used Haze rather than a ball -- the only turn in a long run of
throws that is not one.
"""
import json
import unittest
from pathlib import Path

from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass import tokens as tok

_LOG = Path(__file__).resolve().parent.parent / "data" / "battle_logs" / "giratina3.jsonl"

SELECT = "0x02260e1a"
BEFORE = "0x0224c6d4"
#: The shake roll, identified by this log: it appears only on turns whose message is "used one
#: Poke Ball!", once per shake plus one for the failure that ends the sequence.
SHAKE = "0x0224a938"


def _records():
    return json.loads(_LOG.read_text())


def _turns():
    """``[(selects, total, [roll kinds], [messages]), ...]`` per turn."""
    events = []
    for record in _records()["records"]:
        kind = next(iter(record))
        if kind == "roll":
            events.append(("roll", record[kind]["addr"]))
        elif kind == "msg":
            events.append(("msg", " ".join(record[kind].split())))
    starts = [i for i, e in enumerate(events)
              if e == ("roll", BEFORE) and (i == 0 or events[i - 1] != ("roll", BEFORE))]
    out = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(events)
        gap = starts[n - 1] if n else 0
        selects = sum(1 for e in events[gap:i] if e == ("roll", SELECT))
        kinds = [e[1] for e in events[i:end] if e[0] == "roll" and e[1] != SELECT]
        msgs = [e[1] for e in events[i:end] if e[0] == "msg" and "What will" not in e[1]]
        out.append((selects, len(kinds) + selects, kinds, msgs))
    return out


def _magneton() -> Battler:
    """Bright Powder confirmed by Testare. **This log does not validate it**, and that is worth
    saying: it cuts the attacker's accuracy by a tenth, and no accuracy verdict in these 21 turns
    happens to land in that band -- the run matches identically with and without it. It is here
    because it is the real party, not because anything here depends on it.
    """
    return Battler(name="THE RADIO", level=54, types=("Electric", "Steel"),
                   stats={"hp": 134, "atk": 106, "def": 113,
                          "spa": 148, "spd": 101, "spe": 118},
                   moves=("Thunder Wave", "Screech", "Supersonic", "Sonic Boom"),
                   pp=(20, 40, 20, 20), ability="Sturdy", held_item="Bright Powder",
                   party_slot=1)


def _smeargle() -> Battler:
    """**Technician, and a Silk Scarf** -- and those two were the hardest part of this fixture.

    The log records `"ability": 101`, which is Technician (Smeargle's slot-1 ability; its slot-0 is
    Own Tempo). Guessing Own Tempo cost False Swipe its x1.5 and put the target 20 HP off.

    The **held item is not in the log at all** -- the gdb dump has no item field -- so the Silk
    Scarf was inferred from the damage and then **confirmed by Testare**. The inference is worth
    keeping because it is what makes the figure checkable: turn 8 deals exactly 123, and
    Technician alone spans 90-106 across the sixteen damage rolls while Technician plus the Scarf
    spans 108-127. No roll of the former can reach 123, and the Scarf is the only Normal-boosting
    item, so the item bracket is the only one that fits -- see
    `test_the_held_item_is_the_only_one_that_fits`.
    """
    return Battler(name="CATCHMONKE", level=64, types=("Normal",),
                   stats={"hp": 168, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
                   moves=("Spore", "Foresight", "Mean Look", "False Swipe"),
                   pp=(15, 40, 5, 40), ability="Technician", held_item="Silk Scarf",
                   party_slot=2)


def _honchkrow() -> Battler:
    """Dark/Flying with Leftovers, which is why the HP assertions below are a real check on the
    residual as well as on the damage."""
    return Battler(name="BEEG QRO", level=52, types=("Dark", "Flying"),
                   stats={"hp": 214, "atk": 166, "def": 75,
                          "spa": 110, "spd": 107, "spe": 94},
                   moves=("Taunt", "Haze", "Fly", "Mean Look"), pp=(20, 30, 15, 5),
                   ability="Insomnia", held_item="Leftovers", party_slot=3)


def _giratina() -> Battler:
    """**Giratina-ALTERED, not Origin** -- the log's `"ability": 46` is Pressure, and the stat
    spread agrees: atk 101 against def 132 and spd 132 is the Altered split (lower Attack, higher
    defences). So this is the Turnback Cave encounter, and Pressure doubles OUR PP consumption.
    """
    return Battler(name="Giratina", level=47, types=("Ghost", "Dragon"),
                   stats={"hp": 212, "atk": 101, "def": 132,
                          "spa": 124, "spd": 132, "spe": 104},
                   moves=("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force"),
                   pp=(5, 5, 15, 5), ability="Pressure")


_BALL = Action.STANDARD_BALL
#: Read off the log's messages. Honchkrow's slots are Taunt / Haze / Fly / Mean Look, so Haze is
#: MOVE_2 and Mean Look MOVE_4; the Heal Ball on turn 20 is x1 like the Poke Balls, so it needs no
#: separate action.
PLAN = [(Action.MOVE_1, {}), (Action.MOVE_2, {}), (Action.MOVE_2, {}), (Action.MOVE_2, {}),
        (Action.MOVE_2, {}), (Action.SWITCH, {"bench_slot": 0}), (Action.MOVE_2, {}),
        (Action.MOVE_4, {}), (Action.MOVE_4, {}), (Action.SWITCH, {"bench_slot": 1}),
        (_BALL, {}), (_BALL, {}), (_BALL, {}), (Action.MOVE_2, {}), (_BALL, {}),
        (Action.MOVE_2, {}), (_BALL, {}), (_BALL, {}), (_BALL, {}), (_BALL, {}),
        (Action.MOVE_4, {})]


def _replay():
    config = HuntConfig(target_catch_rate=3, target_has_pressure=True)
    state = BattleState(ours=_magneton(), target=_giratina(),
                        bench=(_smeargle(), _honchkrow()),
                        rng=opening_rng(int(_records()["forced_seed"], 16), config))
    out, previous = [], state.rng_offset
    for action, extra in PLAN:
        state = simulate_turn(state, action, config, **extra)
        out.append((state.rng_offset - previous, tok.render_turn(state.log[-1]), state))
        previous = state.rng_offset
    return out


class TestTheLogIsWhatWeThinkItIs(unittest.TestCase):
    def test_the_seed_was_forced_and_confirmed(self):
        records = _records()
        self.assertEqual(records["forced_seed"], "0x49022ff1")
        self.assertTrue(next(r["seed"] for r in records["records"] if "seed" in r)["confirmed"])

    def test_it_parses_to_twenty_one_turns(self):
        self.assertEqual(len(_turns()), 21)

    def test_the_plan_is_as_long_as_the_log(self):
        self.assertEqual(len(PLAN), len(_turns()))

    def test_it_exercises_the_whole_kit(self):
        joined = " ".join(" ".join(t[3]) for t in _turns())
        for expected in ("Thunder Wave", "Screech", "switch out", "Foresight", "identified",
                         "False Swipe", "Ball", "Leftovers",
                         "Haze", "Mean Look", "vanished instantly", "Shadow Force"):
            with self.subTest(expected):
                self.assertIn(expected, joined)


class TestEveryTurnMatches(unittest.TestCase):
    def test_the_advance_counts_agree(self):
        for n, ((_s, expected, _k, msgs), (got, _r, _st)) in enumerate(
                zip(_turns(), _replay()), 1):
            with self.subTest(turn=n, log_says=" / ".join(msgs)[:60]):
                self.assertEqual(got, expected)

    def test_the_total_agrees(self):
        self.assertEqual(sum(t[0] for t in _replay()), sum(t[1] for t in _turns()))


class TestTheTargetsHpAgrees(unittest.TestCase):
    """**The check the advance counts cannot make, and the first log that allows it.**

    Our token stream carries an HP figure only for OUR side, so a run can match every advance
    count while the damage WE deal is wrong -- and did: this fixture first matched all 21 turns
    with the target 20 HP off, because Smeargle's ability had been guessed as Own Tempo instead of
    Technician. `giratina.jsonl` and `giratina2.jsonl` record battler 0's HP only, so neither
    could have caught it.

    Two figures, and they are the two that matter most in the whole run: the chip to 1 HP.
    """

    def test_the_log_records_the_targets_hp_twice(self):
        recorded = [h["hp"] for r in _records()["records"] if "hp" in r
                    for h in r["hp"] if h["battler"] == 1 and h["hp"] not in (0, 212)]
        self.assertEqual(recorded, [89, 1])

    def test_and_the_simulator_reproduces_both(self):
        trace, seen = [], _giratina().hp      # seeded, or the starting 212 reads as a change
        for _cost, _rendered, state in _replay():
            if state.target.hp != seen:
                trace.append(state.target.hp)
                seen = state.target.hp
        self.assertEqual(trace, [89, 1])

    def test_the_held_item_is_the_only_one_that_fits(self):
        """Why the Silk Scarf is in the fixture. Technician alone cannot reach turn 8's 123 on any
        of the sixteen damage rolls; Technician plus the Scarf brackets it."""
        from claytonlib.battle.damage import Attacker, Defender, damage
        from claytonlib.moves import resolve_move

        false_swipe = resolve_move("False Swipe")
        defender = Defender(defence=132, special_defence=132, types=("Ghost", "Dragon"),
                            defence_stage=-6, identified=True)

        def span(item):
            attacker = Attacker(level=64, attack=71, special_attack=50, types=("Normal",),
                                ability="Technician", held_item=item)
            return (damage(false_swipe, attacker, defender, roll=85),
                    damage(false_swipe, attacker, defender, roll=100))

        low, high = span("")
        self.assertLess(high, 123, "no roll without the item can reach the observed damage")
        low, high = span("Silk Scarf")
        self.assertLessEqual(low, 123)
        self.assertGreaterEqual(high, 123)


class TestTheBugItFound(unittest.TestCase):
    """An ineffective hit on a COMPLETING charge still runs the cleanup."""

    def test_the_fire_turn_is_ineffective_and_still_spends_six(self):
        turn = _turns()[5]
        joined = " ".join(turn[3])
        self.assertIn("Shadow Force", joined)
        self.assertIn("doesn", joined)                 # "It doesn't affect CATCHMONKE..."
        self.assertEqual(turn[2][-6:].count("0x0225b88e"), 6)

    def test_the_simulator_now_agrees(self):
        self.assertEqual(_replay()[5][0], 16)

    def test_an_ineffective_ORDINARY_move_still_forfeits_the_block(self):
        """The distinction the fix rests on, checked inside this same log: turn 8's Ominous Wind
        is ineffective and NOT a fire turn, so it spends four trailing advances where turn 6
        spends six."""
        ordinary = _turns()[7]
        self.assertIn("doesn", " ".join(ordinary[3]))
        self.assertEqual(ordinary[2][-4:].count("0x0225b88e"), 4)
        self.assertNotIn("0x0225b88e", ordinary[2][-5:-4])


class TestTheBallPath(unittest.TestCase):
    """Eight throws, which is the first real exercise the capture path has had against hardware."""

    def _ball_turns(self):
        """Matched on "used one ... Ball", not on "Poke Ball": turn 20 is a HEAL Ball, and keying
        on the species of ball silently dropped it."""
        return [(n, t) for n, t in enumerate(_turns(), 1)
                if any("used one" in m and "Ball" in m for m in t[3])]

    def test_there_are_eight_of_them(self):
        self.assertEqual(len(self._ball_turns()), 8)

    def test_the_rolls_spent_are_shakes_plus_one(self):
        """The ROM stops at the first failed shake, so a 0-shake throw costs one roll and a
        2-shake throw three. Read against the message the player actually sees."""
        shakes_for = {"broke free": 0, "appeared to be caught": 1, "Almost had it": 2}
        for n, turn in self._ball_turns():
            said = next((v for k, v in shakes_for.items()
                         if any(k in m for m in turn[3])), None)
            with self.subTest(turn=n, message=said):
                self.assertIsNotNone(said, "unrecognised ball message")
                self.assertEqual(turn[2].count(SHAKE), said + 1)

    def test_the_simulator_renders_the_same_shake_counts(self):
        replay = _replay()
        for n, turn in self._ball_turns():
            said = next(v for k, v in
                        {"broke free": 0, "appeared to be caught": 1, "Almost had it": 2}.items()
                        if any(k in m for m in turn[3]))
            with self.subTest(turn=n):
                self.assertIn(f"P{said}", replay[n - 1][1])

    def test_nothing_was_caught(self):
        """Two shakes is the most any throw reached, so the run continues -- which is what makes
        all 21 turns comparable."""
        self.assertFalse(_replay()[-1][2].captured)
        self.assertFalse(_replay()[-1][2].captured_in_wrong_ball)


class TestWhatItConfirms(unittest.TestCase):
    def test_foresight_makes_the_next_false_swipe_connect(self):
        """Turn 7 identifies, turn 8 chips. Before Foresight a Normal move did nothing to this
        Ghost, so this is the whole feature working end to end against hardware."""
        replay = _replay()
        self.assertIn("identified", " ".join(_turns()[6][3]))
        self.assertIn("M4h", replay[7][1])
        self.assertLess(replay[7][2].target.hp, replay[6][2].target.hp)

    def test_false_swipe_floors_the_target_at_one(self):
        self.assertEqual(_replay()[8][2].target.hp, 1)

    def test_leftovers_ticks_once_honchkrow_is_out(self):
        joined = " ".join(" ".join(t[3]) for t in _turns()[9:])
        self.assertIn("Leftovers", joined)
        replay = _replay()
        self.assertEqual(replay[9][2].ours.name, "BEEG QRO")

    def test_the_player_never_threw_at_a_vanished_target(self):
        """Corroborates clayton-6xu.3.13 from the player's own behaviour rather than from our
        model: turn 16 opens with Giratina away and is the one turn in a long run of throws that
        is not a throw -- Haze instead."""
        replay = _replay()
        for n, (_cost, rendered, state) in enumerate(replay, 1):
            if n == 1:
                continue
            opened_away = replay[n - 2][2].target.charging_slot is not None
            if opened_away:
                with self.subTest(turn=n):
                    self.assertNotIn("P", rendered.split("E")[0])


if __name__ == "__main__":
    unittest.main()
