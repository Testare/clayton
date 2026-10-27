"""An incoming move that cannot affect us, and the switch turn that found it.

Reported: Giratina used Ominous Wind on the turn a Smeargle was switched in, and the interview
asked whether it hit and for how much damage -- despite the immunity. Ghost does nothing to a
Normal type, so the turn renders a bare `E1` and `tokens.turn_requires_hp` asks for no HP.

**Two separate faults, and the switch is only why they showed up together.**

1. The target's outcome block never consulted `deals_nothing` at all. It was published for OUR
   move chips (the `⊘` marker and its hint) and never read on the target's side, so an immune
   INCOMING move offered "Hit us" and "Critical hit" as the only answers to a turn that can render
   neither. Half of Giratina's moveset is Ghost and the planned chipper is a Normal-typed
   Smeargle, so that is most of its turns -- with or without a switch.
2. `target.move_info` is computed against whoever was out when the turn OPENED, which on a switch
   turn is the Pokemon LEAVING. The outgoing Magneton is Electric/Steel and merely *resists*
   Ghost, so even a fixed block 1 would have asked the question against the wrong Pokemon.

The simulator was right throughout: a switch resolves before any move, so `act_ours` swaps first
and `act_target` attacks the newcomer.

(clayton-6xu.3.11)
"""
import unittest
from dataclasses import replace

from claytonlib.battle_compass.hunt_session import move_info
from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass import tokens as tok

SEED = 0x4E0238AB


def _giratina(**kwargs) -> Battler:
    """PP in Ominous Wind alone, so the selection roll must pick the Ghost move."""
    return replace(Battler(
        name="Giratina", level=47, types=("Ghost", "Dragon"),
        stats={"hp": 204, "atk": 96, "def": 145, "spa": 111, "spd": 119, "spe": 90},
        moves=("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force"),
        pp=(5, 0, 0, 0), ability="Levitate"), **kwargs)


def _magneton() -> Battler:
    """The outgoing lead. Electric/Steel, so Ghost RESISTS rather than fails -- which is what
    made the stale `move_info` produce a plausible-looking wrong question."""
    return Battler(name="Magneton", level=54, types=("Electric", "Steel"),
                   stats={"hp": 134, "atk": 106, "def": 113,
                          "spa": 148, "spd": 101, "spe": 118},
                   moves=("Thunder Wave", "Screech"), pp=(20, 40), party_slot=1)


def _smeargle() -> Battler:
    """The incoming chipper. Normal, so Ghost cannot touch it at all."""
    return Battler(name="Smeargle", level=73, types=("Normal",),
                   stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
                   moves=("False Swipe", "Spore"), pp=(40, 15), party_slot=2)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestTheSimulatorWasRight(unittest.TestCase):
    """Pinned first, because it is what makes the rest interview bugs rather than model bugs."""

    def test_the_switch_resolves_before_the_move(self):
        config = _config()
        state = BattleState(ours=_magneton(), target=_giratina(), bench=(_smeargle(),),
                            rng=opening_rng(SEED, config))
        after = simulate_turn(state, Action.SWITCH, config, bench_slot=0)
        self.assertEqual(after.ours.name, "Smeargle")
        self.assertEqual(after.ours.hp, after.ours.max_hp, "the newcomer took nothing")

    def test_and_the_turn_renders_the_bare_slot_with_no_hp(self):
        config = _config()
        state = BattleState(ours=_magneton(), target=_giratina(), bench=(_smeargle(),),
                            rng=opening_rng(SEED, config))
        turn = simulate_turn(state, Action.SWITCH, config, bench_slot=0).log[-1]
        self.assertIn("E1", tok.render_turn(turn))
        self.assertNotIn("h", tok.render_turn(turn))
        self.assertFalse(tok.turn_requires_hp(turn))
        self.assertEqual(tok.validate_turn(list(turn)), [])


class TestTheDefenderDecidesTheQuestion(unittest.TestCase):
    """Fault 2: the rows have to describe whoever the attack LANDS on."""

    def test_the_same_move_answers_differently_for_the_two_pokemon(self):
        """The whole bug in one assertion: Ominous Wind is blocked by the newcomer and merely
        resisted by the one leaving."""
        against_outgoing = {m["name"]: m for m in move_info(_giratina(), _magneton())}
        against_incoming = {m["name"]: m for m in move_info(_giratina(), _smeargle())}
        self.assertFalse(against_outgoing["Ominous Wind"]["deals_nothing"])
        self.assertTrue(against_incoming["Ominous Wind"]["deals_nothing"])

    def test_the_snapshot_publishes_rows_per_bench_member(self):
        rows = self._bench()[0]["incoming_move_info"]
        wind = {m["name"]: m for m in rows}["Ominous Wind"]
        self.assertTrue(wind["deals_nothing"])

    def test_they_describe_the_bench_member_and_not_the_lead(self):
        """Guards against the field being wired to the wrong battler, which would pass the test
        above by accident whenever the lead happened to be immune too."""
        snap = self._snapshot()
        lead = {m["name"]: m for m in snap["target"]["move_info"]}["Ominous Wind"]
        bench = {m["name"]: m
                 for m in snap["bench"][0]["incoming_move_info"]}["Ominous Wind"]
        self.assertNotEqual(lead["deals_nothing"], bench["deals_nothing"])

    def _snapshot(self):
        import datetime as dt

        from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
        from claytonlib.battle_compass.hunt_session import HuntSession

        window = CandidateWindow(
            key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
            frame_centre=1000, second_centre=30, frame_window=0, second_window=0,
            candidates=(Candidate(seed=SEED, frame=1000, second=30),))
        session = HuntSession(window, _magneton(), _giratina(), _config(),
                              bench=(_smeargle(),))
        return session.snapshot()

    def _bench(self):
        return self._snapshot()["bench"]


class TestThePageAsksTheRightThing(unittest.TestCase):
    """Fault 1, plus the routing that fault 2 needed."""

    def setUp(self):
        from pathlib import Path
        self.html = (Path(__file__).resolve().parent.parent
                     / "app" / "web" / "index.html").read_text()

    def test_the_target_block_has_a_no_effect_branch(self):
        self.assertIn("} else if (info.deals_nothing){", self.html)
        self.assertIn("It had no effect", self.html)

    def test_it_is_tested_before_damaging(self):
        """A move can be both: Ominous Wind is a damaging move that deals nothing here, and the
        wrong order offers 'Hit us' for a turn that cannot render it -- the same argument the
        `guaranteed_fail` ordering rests on."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        body = _function_body("hrTargetBlocks")
        outcome = body[body.index("const base = `{slot:"):]
        self.assertLess(outcome.index("info.deals_nothing"), outcome.index("info.damaging"))

    def test_the_auto_answer_does_not_fill_in_a_hit(self):
        """One option means no question is shown, so the auto-answer is what actually lands in the
        token stream -- and it must be the bare slot, not 'h'."""
        for term in ("info.damaging", "!info.guaranteed_fail", "!info.deals_nothing"):
            with self.subTest(term):
                self.assertIn(term, self.html)

    def test_the_rows_are_read_through_the_switch_aware_accessor(self):
        """`s.target.move_info` must not be indexed directly any more: on a switch turn it
        describes the Pokemon leaving."""
        self.assertIn("function hrTargetMoveRows()", self.html)
        self.assertIn("incoming_move_info", self.html)
        self.assertNotIn("s.target.move_info[", self.html)


if __name__ == "__main__":
    unittest.main()
