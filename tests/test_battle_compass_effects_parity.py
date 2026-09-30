"""battle_compass.sim against metronome_compass.effects, for the nine fixture moves.

The reason duplicating nine of 235 effect handlers was judged cheap (sec 15.2): the existing ones
are already verified for the Blackthorn matchup, so every duplicate comes with a free reference
implementation. This is that check, and it earned itself on its first run -- Spore spent one RNG
advance here and two there, because applying sleep costs a hidden duration roll that
``execute_move`` never spent. A wrong advance count is the worst class of bug in this tool: every
turn after it is measured against the wrong offset, so the true seed is eliminated.

Per-move advance counts should be matchup-independent (accuracy, crit, damage, proc, duration),
which is exactly what makes the comparison meaningful across two different battles.
"""
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.sim import (
    SLEEP_DURATION_MIN, SLEEP_DURATION_SPAN, execute_move, move_roll_cost,
)
from claytonlib.battle_compass.state import Battler, Status
from claytonlib.metronome_compass.context import RngContext
from claytonlib.metronome_compass.effects import EFFECT_HANDLERS, simulate_move_execution
from claytonlib.metronome_compass.path import MetronomeBattleState, apply_entry_ability
from claytonlib.moves import resolve_move
from claytonlib.safari import advance_rng

#: The nine the section 11 fixture needs: Suicune's four and our five.
FIXTURE_MOVES = ("Rain Dance", "Gust", "Aurora Beam", "Mist",
                 "False Swipe", "Mean Look", "Sweet Scent", "Spore", "Thunder Wave")

SEEDS = (0x12345678, 0xEC1504DC, 0xABCDEF01, 0x00FF00FF, 0x5A5A5A5A, 0x0BADF00D)


def _advance_steps(start: int, end: int, limit: int = 40) -> int | None:
    """How many LCRNG steps separate two states, or None beyond `limit`.

    Counting this way rather than instrumenting either implementation keeps the comparison
    black-box: it measures the stream position each one actually leaves behind.
    """
    state = start
    for steps in range(limit + 1):
        if state == end:
            return steps
        state = advance_rng(state)
    return None


def _metronome_advances(move_name: str, seed: int) -> int | None:
    """Advances `metronome_compass.effects` spends executing this move."""
    move = resolve_move(move_name)
    ctx = RngContext(seed)
    state = MetronomeBattleState()
    state.target_level = 40
    apply_entry_ability(state)
    ctx.battle_state["state"] = state
    ctx.battle_state["opposite_gender"] = False
    ctx.battle_state["user_move_types"] = ["Normal"]
    simulate_move_execution(ctx, move)
    return _advance_steps(seed, ctx.rng)


def _ours(**kw) -> Battler:
    fields = dict(name="Smeargle", level=60, types=("Normal",),
                  stats={**derive_species_stats("smeargle", 60, "Hardy"), "atk": 65},
                  moves=FIXTURE_MOVES[:4], pp=(10,) * 4)
    fields.update(kw)
    return Battler(**fields)


def _target(**kw) -> Battler:
    fields = dict(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                  stats=derive_species_stats("suicune", 40, "Bold"),
                  moves=("Gust",), pp=(35,))
    fields.update(kw)
    return Battler(**fields)


class TestEveryFixtureMoveHasAReference(unittest.TestCase):
    def test_all_nine_are_implemented_in_effects_py(self):
        """Otherwise there is nothing to validate against and the duplication is not cheap."""
        for name in FIXTURE_MOVES:
            move = resolve_move(name)
            self.assertIn(move.effect, EFFECT_HANDLERS,
                          f"{name} (effect {move.effect}) has no reference handler")


class TestAdvanceCountParity(unittest.TestCase):
    """The check that matters. An advance count that differs by one desynchronises every
    subsequent turn, which reads as "the model constant is wrong" rather than as a bug here."""

    def test_every_move_spends_the_same_advances(self):
        mismatches = []
        for name in FIXTURE_MOVES:
            move = resolve_move(name)
            for seed in SEEDS:
                reference = _metronome_advances(name, seed)
                _, outcome = execute_move(seed, move, _ours(), _target(), actor="M", slot=0)
                if reference != outcome.rolls:
                    mismatches.append(f"{name} @ {seed:#010x}: effects.py {reference}, "
                                      f"sim {outcome.rolls}")
        self.assertEqual(mismatches, [], "; ".join(mismatches))

    def test_the_comparison_is_not_vacuous(self):
        """Every count must actually have been measured, not silently None."""
        for name in FIXTURE_MOVES:
            self.assertIsNotNone(_metronome_advances(name, SEEDS[0]), name)

    def test_the_counts_span_a_real_range(self):
        """If everything cost the same the test would prove nothing."""
        counts = {_metronome_advances(n, SEEDS[0]) for n in FIXTURE_MOVES}
        self.assertGreaterEqual(len(counts), 4)
        self.assertIn(0, counts)


class TestSleepCostsItsDurationRoll(unittest.TestCase):
    """What the parity check found. Applying sleep rolls `2 + RAND % 4` for its duration --
    invisible to the player at the time, and one extra advance."""

    def test_spore_spends_two_advances_when_it_lands(self):
        move = resolve_move("Spore")
        for seed in SEEDS:
            _, outcome = execute_move(seed, move, _ours(), _target(), actor="M", slot=0)
            self.assertTrue(outcome.successful)
            self.assertEqual(outcome.rolls, 2, f"{seed:#010x}")

    def test_it_spends_only_one_when_it_fails(self):
        """No status was applied, so there is no duration to roll -- and this is the case that
        matters in practice, since Spore is filler after paralysis lands (sec 11.5)."""
        move = resolve_move("Spore")
        already = _target(status=Status.PARALYSIS)
        for seed in SEEDS:
            _, outcome = execute_move(seed, move, _ours(), already, actor="M", slot=0)
            self.assertFalse(outcome.successful)
            self.assertEqual(outcome.rolls, 1, f"{seed:#010x}")

    def test_the_duration_is_in_range(self):
        move = resolve_move("Spore")
        seen = set()
        for seed in range(0xEC1504DC, 0xEC1504DC + 200):
            _, outcome = execute_move(seed, move, _ours(), _target(), actor="M", slot=0)
            seen.add(outcome.sleep_turns)
        self.assertEqual(seen, set(range(SLEEP_DURATION_MIN,
                                         SLEEP_DURATION_MIN + SLEEP_DURATION_SPAN)))

    def test_paralysis_has_no_duration_roll(self):
        """Thunder Wave is permanent, so it spends its accuracy check and nothing more."""
        move = resolve_move("Thunder Wave")
        _, outcome = execute_move(SEEDS[0], move, _ours(), _target(), actor="M", slot=0)
        self.assertEqual(outcome.rolls, 1)
        self.assertEqual(outcome.sleep_turns, 0)


class TestMoveRollCostIsOnlyABound(unittest.TestCase):
    """It cannot be a count: the real cost depends on the outcome. Sleep's duration roll happens
    only when the status lands, and a missed move spends no damage rolls."""

    def test_it_is_never_below_the_real_cost(self):
        for name in FIXTURE_MOVES:
            move = resolve_move(name)
            for seed in SEEDS:
                _, outcome = execute_move(seed, move, _ours(), _target(), actor="M", slot=0)
                self.assertLessEqual(outcome.rolls, move_roll_cost(move),
                                     f"{name} @ {seed:#010x} exceeded its own bound")

    def test_the_bound_includes_sleeps_duration_roll(self):
        self.assertEqual(move_roll_cost(resolve_move("Spore")), 2)

    def test_a_failed_status_move_comes_in_under_the_bound(self):
        """Which is the point of calling it a bound."""
        move = resolve_move("Spore")
        _, outcome = execute_move(SEEDS[0], move, _ours(), _target(status=Status.PARALYSIS),
                                  actor="M", slot=0)
        self.assertLess(outcome.rolls, move_roll_cost(move))


if __name__ == "__main__":
    unittest.main()
