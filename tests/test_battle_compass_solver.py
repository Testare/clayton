"""Phase 2: steering the RNG to a capture.

The important assertion here is the last class: it measures the reachability claim section 1.1
made from an illustrative cost model, against the real simulator.
"""
import statistics
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle.turn import max_turn_advances
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.solver import (
    BALL_PRICE, BASE_DISTANCE, COST_DIVISOR, ITEM_PRICES, Solution, SolverConfig, Unreachable,
    capture_windows_in_horizon, choose_item, distance_of, solve, target_threshold,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status

SEED = 0xEC1504DC
HUNT = HuntConfig(target_catch_rate=3)
#: Smeargle's worst single incoming hit: a max-roll critical Aurora Beam (sec 11.2).
DANGER_FLOOR = 58


def _state(seed=SEED, **target_overrides) -> BattleState:
    target_fields = dict(
        name="Suicune", level=40, types=tuple(species("suicune")["types"]),
        stats=derive_species_stats("suicune", 40, "Bold"),
        moves=("Rain Dance", "Gust", "Aurora Beam", "Mist"), pp=(5, 35, 20, 30),
        hp=1, status=Status.PARALYSIS)
    target_fields.update(target_overrides)
    stats = {**derive_species_stats("smeargle", 60, "Hardy"), "atk": 65}
    ours = Battler(name="Smeargle", level=60, types=("Normal",), stats=stats,
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15))
    return BattleState(ours=ours, target=Battler(**target_fields), rng=seed, phase=2)


def _config(**kwargs) -> SolverConfig:
    fields = dict(danger_floor=DANGER_FLOOR)
    fields.update(kwargs)
    return SolverConfig(**fields)


class TestDistanceFunction(unittest.TestCase):
    """sec 12.7: one scalar prices turns against money, so neither dominates."""

    def test_a_free_action_costs_the_base(self):
        self.assertEqual(distance_of(0), BASE_DISTANCE)

    def test_the_documented_examples(self):
        self.assertEqual(distance_of(BALL_PRICE), 19)      # a ball is barely worse than free
        self.assertEqual(distance_of(ITEM_PRICES["xsd"]), 22)
        self.assertEqual(distance_of(1500), 45)            # exactly three free turns

    def test_one_turn_is_worth_the_documented_exchange_rate(self):
        self.assertEqual(BASE_DISTANCE * COST_DIVISOR, 750)

    def test_parameters_are_tunable(self):
        self.assertEqual(distance_of(1000, base=10, divisor=100), 20)

    def test_a_negative_price_is_rejected(self):
        with self.assertRaises(ValueError):
            distance_of(-1)


class TestItemTiering(unittest.TestCase):
    """One USE_ITEM action, resolved deterministically -- branching on which item would multiply
    the search for no reachability gain, since every item costs zero RNG advances (sec 12.2)."""

    def test_a_full_heal_when_at_or_below_the_danger_floor(self):
        state = _state()
        state.ours = state.ours.with_hp(DANGER_FLOOR)
        self.assertEqual(choose_item(state, _config())[0], "hp")

    def test_an_x_sp_def_while_defences_are_unmaxed(self):
        self.assertEqual(choose_item(_state(), _config())[0], "xsd")

    def test_a_plain_potion_once_defences_are_maxed_and_hp_is_down(self):
        state = _state()
        state.ours = state.ours.with_hp(100)
        object.__setattr__(state.ours, "spdef_stage", 6)
        self.assertEqual(choose_item(state, _config())[0], "p")

    def test_the_tiering_is_deterministic(self):
        state = _state()
        self.assertEqual(choose_item(state, _config()), choose_item(state, _config()))


class TestCaptureWindows(unittest.TestCase):
    def test_windows_are_dense_at_the_suicune_threshold(self):
        """About one offset in 79 starts a window, so an empty result is a strong signal."""
        threshold = target_threshold(_state(), HUNT)
        self.assertEqual(threshold, 21845)
        windows = capture_windows_in_horizon(SEED, threshold, 4000)
        self.assertGreater(len(windows), 20)

    def test_an_impossible_threshold_yields_no_windows(self):
        self.assertEqual(capture_windows_in_horizon(SEED, 1, 4000), [])

    def test_an_empty_horizon_is_a_real_proof_of_unreachability(self):
        """Unlike an exhausted search, this one holds however the search is pruned: the horizon
        bounds every roll reachable in max_turns, so no window means no capture."""
        result = solve(_state(), HUNT, _config(max_turns=1))
        self.assertIsInstance(result, Unreachable)
        self.assertEqual(result.capture_windows, 0)
        self.assertTrue(result.proven)
        self.assertIn("upper bound", result.reason)

    def test_the_horizon_is_sized_by_the_derived_turn_bound(self):
        """A magic constant here would silently weaken the proof above."""
        result = solve(_state(), HUNT, _config(max_turns=1))
        self.assertIn(str(max_turn_advances()), result.reason)

    def test_a_short_horizon_finds_fewer(self):
        threshold = target_threshold(_state(), HUNT)
        self.assertLess(len(capture_windows_in_horizon(SEED, threshold, 200)),
                        len(capture_windows_in_horizon(SEED, threshold, 4000)))


class TestPreconditions(unittest.TestCase):
    """The solver asserts its preconditions rather than coping without them: a target at exactly
    1 HP and paralyzed is what makes b a single constant (sec 2.2)."""

    def test_a_target_above_one_hp_is_refused(self):
        result = solve(_state(hp=50), HUNT, _config())
        self.assertIsInstance(result, Unreachable)
        self.assertFalse(result.proven)
        self.assertIn("1 HP", result.reason)

    def test_an_unparalyzed_target_is_refused(self):
        result = solve(_state(status=Status.NONE), HUNT, _config())
        self.assertIsInstance(result, Unreachable)
        self.assertIn("paralyzed", result.reason)

    def test_refusal_is_not_reported_as_a_proof(self):
        """It says nothing about the seed, so it must not look like unreachability."""
        self.assertFalse(solve(_state(hp=50), HUNT, _config()).proven)


class TestSolving(unittest.TestCase):
    def test_a_solution_ends_in_a_capture(self):
        result = solve(_state(), HUNT, _config())
        self.assertIsInstance(result, Solution)
        self.assertEqual(result.steps[-1].action, Action.CAPTURE_BALL)
        self.assertTrue(result.rendered().endswith("C"))

    def test_the_distance_is_the_sum_of_its_steps(self):
        result = solve(_state(), HUNT, _config())
        self.assertEqual(result.total_distance, sum(s.distance for s in result.steps))

    def test_solutions_are_deterministic(self):
        a, b = solve(_state(), HUNT, _config()), solve(_state(), HUNT, _config())
        self.assertEqual(a.rendered(), b.rendered())

    def test_a_wrong_ball_capture_is_never_part_of_a_path(self):
        """It loses the run, so it is pruned rather than costed (sec 2.3)."""
        for delta in range(12):
            result = solve(_state(SEED + delta), HUNT, _config())
            if isinstance(result, Solution):
                self.assertNotIn("Pc", result.rendered(), f"seed +{delta}")

    def test_we_never_faint_along_a_path(self):
        """Sustainability is a hard constraint, not a warning (sec 6.2)."""
        for delta in range(12):
            result = solve(_state(SEED + delta), HUNT, _config())
            if isinstance(result, Solution):
                for step in result.steps:
                    hp = [t for t in step.tokens if t.startswith("HP")]
                    if hp:
                        self.assertGreater(int(hp[0][2:]), 0, f"seed +{delta}")

    def test_the_item_bill_lists_what_the_path_spends(self):
        result = solve(_state(), HUNT, _config())
        for code in result.item_bill():
            self.assertIn(code, ITEM_PRICES)

    def test_a_solution_respects_the_turn_cap(self):
        result = solve(_state(), HUNT, _config(max_turns=3))
        if isinstance(result, Solution):
            self.assertLessEqual(result.turns, 3)


class TestOffsetCollapsing(unittest.TestCase):
    """Whether a throw captures depends only on the RNG offset, so collapsing an offset to its
    cheapest arrival is a strong reduction. It is a heuristic, and reported as one."""

    def test_collapsing_is_far_cheaper(self):
        fast = solve(_state(), HUNT, _config())
        slow = solve(_state(), HUNT, _config(collapse_offsets=False, max_states=200_000))
        self.assertLess(fast.states_explored, slow.states_explored / 10)

    def test_collapsing_finds_the_same_distance(self):
        for delta in (2, 3, 7, 8, 11):
            fast = solve(_state(SEED + delta), HUNT, _config())
            slow = solve(_state(SEED + delta), HUNT,
                         _config(collapse_offsets=False, max_states=200_000))
            self.assertIsInstance(fast, Solution)
            self.assertIsInstance(slow, Solution)
            self.assertEqual(fast.total_distance, slow.total_distance, f"seed +{delta}")

    #: Two capture windows in a 2-turn horizon, but no action sequence reaches either.
    EXHAUSTING_SEED = 0xF2A74DE4

    def test_only_the_exhaustive_search_claims_a_proof(self):
        """A heuristic exhaustion says nothing about the seed, so it must not claim one."""
        result = solve(_state(self.EXHAUSTING_SEED), HUNT, _config(max_turns=2))
        self.assertIsInstance(result, Unreachable)
        self.assertGreater(result.capture_windows, 0, "this seed must reach the search, not the "
                                                      "window proof, to test anything")
        self.assertFalse(result.proven)
        self.assertIn("complete search", result.reason)

    def test_the_exhaustive_search_does_claim_one(self):
        result = solve(_state(self.EXHAUSTING_SEED), HUNT,
                       _config(max_turns=2, collapse_offsets=False))
        self.assertIsInstance(result, Unreachable)
        self.assertTrue(result.proven)
        self.assertIn("exhausted", result.reason)

    def test_hitting_the_state_cap_is_not_a_proof(self):
        result = solve(_state(), HUNT, _config(max_states=5))
        self.assertIsInstance(result, Unreachable)
        self.assertFalse(result.proven)
        self.assertIn("gave up", result.reason)


class TestReachabilityMatchesTheDesignClaim(unittest.TestCase):
    """Section 1.1 predicted ~98-99% of seeds reachable within 40 turns, median ~8, from an
    illustrative cost model built before the simulator existed. This measures the real thing."""

    SAMPLE = 60

    def _sample(self):
        import random
        rng = random.Random(3)
        results = []
        for _ in range(self.SAMPLE):
            results.append(solve(_state(rng.getrandbits(32)), HUNT, _config()))
        return results

    def test_almost_every_seed_is_reachable(self):
        results = self._sample()
        solved = [r for r in results if isinstance(r, Solution)]
        self.assertGreater(len(solved) / len(results), 0.90,
                           "reachability is far below the ~98-99% section 1.1 predicted")

    def test_the_median_turn_count_is_single_digit(self):
        turns = [r.turns for r in self._sample() if isinstance(r, Solution)]
        self.assertLess(statistics.median(turns), 10,
                        "median turn count is worse than section 1.1's ~8")

    def test_the_deadline_is_not_the_binding_constraint(self):
        """At a single-digit median, Suicune's ~120-turn Struggle deadline never binds."""
        turns = [r.turns for r in self._sample() if isinstance(r, Solution)]
        self.assertLess(max(turns), 120)


if __name__ == "__main__":
    unittest.main()
