"""Phase 2 at any HP, not only at 1.

**The third relaxation of the same gate, and each had the same shape.** It began as "1 HP and
permanently paralyzed", which made ``b`` a single constant (sec 2.2). Sleep broke the constant and
the solver was taught to cope rather than refuse. Then "some holding status" went: a target we
cannot status is not unreachable, only a smaller ``b``. HP is that argument once more.

**Why it had to happen now.** Dialga cannot be brought to 1 HP by a Smeargle at all — Steel
resists False Swipe and Pressure halves 40 PP to 20 uses against the 20–27 hits it needs — so the
gate refused a target that is perfectly catchable at full HP. And the figures favour it: catch rate
30 and 45 mean full HP asleep in a Dusk Ball is ``b=47661``/``b=52428`` against ``33824`` for
Suicune at 1 HP in the same ball.

**What it costs**, and the invariant that makes it sound: `max_reachable_threshold` maximises over
every status a path can reach but *not* over every HP, so a plan that chipped the target could
reach a bigger ``b`` than the window precomputation priced — and pruning at the smaller figure can
prove unreachability the bigger one disproves, which is the unsoundness the status version of this
gate was fixed for. So Phase 2 holds the target's HP still (`holds_target_hp`) and chipping stays
in Phase 1, where it already was.

At 1 HP every one of these is a no-op, which is the point: no pre-existing run changes.

(clayton-6xu.9.1)
"""
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
from claytonlib.battle_compass.solver import (
    SolverConfig, Unreachable, holds_target_hp, solve, target_threshold,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.moves import resolve_move

HUNT = HuntConfig(target_catch_rate=3, capture_ball="Fast Ball")


def _suicune(**kwargs) -> Battler:
    fields = dict(
        name="Suicune", level=40, types=tuple(species("suicune")["types"]),
        stats=derive_species_stats("suicune", 40, "Bold"),
        moves=("Rain Dance", "Gust", "Aurora Beam", "Mist"), pp=(5, 35, 20, 30),
        hp=1, status=Status.PARALYSIS)
    fields.update(kwargs)
    return Battler(**fields)


def _ours() -> Battler:
    return Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15))


def _state(hp: int = 1, seed: int = 0xEC1504DC) -> BattleState:
    return BattleState(ours=_ours(), target=_suicune(hp=hp), rng=seed, phase=2)


class TestTheGateIsGone(unittest.TestCase):

    def test_one_hp_still_solves_exactly_as_it_did(self):
        """The regression guard that matters most: the whole v1 fixture runs through this gate."""
        self.assertNotIsInstance(solve(_state(1), HUNT, SolverConfig()), Unreachable)

    def test_and_so_does_every_hp_up_to_full(self):
        full = _suicune().max_hp
        for hp in (1, 2, 50, full // 2, full):
            with self.subTest(hp=hp):
                result = solve(_state(hp), HUNT, SolverConfig())
                if isinstance(result, Unreachable):
                    # An honest empty window search is allowed at a smaller b; a PRECONDITION
                    # refusal is what must no longer happen.
                    self.assertNotIn("precondition", result.reason)
                    self.assertNotIn("not 1", result.reason)

    def test_a_fainted_target_is_still_refused_and_proven(self):
        """The one HP left that blocks, and it is an observation rather than a precondition."""
        result = solve(_state(0), HUNT, SolverConfig())
        self.assertIsInstance(result, Unreachable)
        self.assertTrue(result.proven)
        self.assertIn("fainted", result.reason)


class TestTheThresholdFollowsTheHp(unittest.TestCase):
    """`b` was always computed from the live HP -- which is why the arithmetic needed no change."""

    def test_a_lower_hp_is_a_bigger_b(self):
        full = _suicune().max_hp
        self.assertGreater(target_threshold(_state(1), HUNT),
                           target_threshold(_state(full), HUNT))

    def test_it_moves_monotonically(self):
        full = _suicune().max_hp
        thresholds = [target_threshold(_state(hp), HUNT) for hp in (1, full // 4, full // 2, full)]
        self.assertEqual(thresholds, sorted(thresholds, reverse=True))


class TestThePlanHoldsTheTargetStill(unittest.TestCase):
    """The invariant that licenses searching at any HP."""

    def test_a_status_move_always_holds(self):
        self.assertTrue(holds_target_hp(resolve_move("Mean Look"), _state(100)))
        self.assertTrue(holds_target_hp(resolve_move("Spore"), _state(100)))

    def test_false_swipe_holds_at_one_hp_because_of_its_floor(self):
        """Effect 101 makes it deal exactly zero there, which is what kept it legal as unlimited
        filler -- and still does."""
        self.assertTrue(holds_target_hp(resolve_move("False Swipe"), _state(1)))

    def test_false_swipe_does_NOT_hold_above_one_hp(self):
        """Not because it is dangerous -- it cannot faint anything -- but because it would move
        `b` out from under the window precomputation."""
        self.assertFalse(holds_target_hp(resolve_move("False Swipe"), _state(100)))

    def test_a_move_the_target_is_immune_to_holds_at_any_hp(self):
        """A False Swipe at an unidentified Giratina is a genuine constant-cost filler: the type
        chart zeroes it, so it moves nothing. Refusing it would refuse a turn the game plays."""
        ghost = Battler(name="Giratina", level=47, types=("Ghost", "Dragon"),
                        stats=derive_species_stats("giratina-origin", 47, "Timid", ivs=31),
                        moves=("Shadow Force",), pp=(5,), ability="Levitate")
        state = BattleState(ours=_ours(), target=ghost, rng=0xEC1504DC, phase=2)
        self.assertTrue(holds_target_hp(resolve_move("False Swipe"), state))

    def test_a_solved_plan_really_does_leave_the_hp_alone(self):
        """Driven through `simulate_turn` rather than read off the filter, so it is the plan being
        checked and not the predicate."""
        for hp in (50, _suicune().max_hp):
            with self.subTest(hp=hp):
                result = solve(_state(hp), HUNT, SolverConfig())
                if isinstance(result, Unreachable):
                    continue
                state = _state(hp)
                for step in result.steps:
                    state = simulate_turn(state, step.action, HUNT, item_code=step.item)
                    self.assertIn(state.target.hp, (hp, 0))


class TestTheDeclarationIsNoLongerUnconditional(unittest.TestCase):
    """`enter_pinning` forces 1 HP by default, because the player's HP bar beats our model. It
    must not force it on a hunt that is deliberately solving higher up."""

    def _session(self, hp):
        from claytonlib.battle_compass.candidates import Candidate
        from claytonlib.battle_compass.identify import Session

        return Session([Candidate(seed=0xEC1504DC, frame=1, second=0)],
                       _ours(), _suicune(hp=hp), HUNT)

    def test_the_default_still_declares_one(self):
        session = self._session(37)
        session.enter_pinning()
        self.assertEqual(next(iter(session.states.values())).target.hp, 1)

    def test_none_trusts_the_simulation_instead(self):
        """The full-HP hunt. Forcing 1 here would price every throw against a `b` the battle does
        not have and plan a capture that cannot land -- worse than refusing, because it looks like
        a plan."""
        session = self._session(37)
        session.enter_pinning(declared_hp=None)
        self.assertEqual(next(iter(session.states.values())).target.hp, 37)

    def test_an_explicit_figure_is_adopted(self):
        session = self._session(200)
        session.enter_pinning(declared_hp=120)
        self.assertEqual(next(iter(session.states.values())).target.hp, 120)


if __name__ == "__main__":
    unittest.main()
