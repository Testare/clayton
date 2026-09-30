"""Phase 2: steering the RNG to a capture.

The important assertion here is the last class: it measures the reachability claim section 1.1
made from an illustrative cost model, against the real simulator.
"""
import statistics
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle.turn import max_turn_advances
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.solver import (
    BALL_PRICE, BASE_DISTANCE, COST_DIVISOR, ITEM_PRICES, Solution, SolverConfig, Unreachable,
    TURNS_PER_PP, capture_windows_in_horizon, choose_item, distance_of, remaining_target_pp,
    solve, struggle_deadline, target_threshold,
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

    def test_collapsing_is_cheaper(self):
        """Was a 10x reduction before field conditions were modelled; now ~5x, because rain,
        mist and the target's PP entered _dominance_key and made the exhaustive search's buckets
        finer."""
        fast = solve(_state(), HUNT, _config())
        slow = solve(_state(), HUNT, _config(collapse_offsets=False, max_states=200_000))
        self.assertLess(fast.states_explored * 2, slow.states_explored)

    def test_collapsing_is_never_better_than_optimal(self):
        """It cannot beat the exhaustive search, and usually ties it.

        It no longer always ties. Modelling field conditions means two arrivals at one offset can
        disagree about rain, mist or the target's PP -- which decides whether the target's next
        move FAILS and so which offset the next turn reaches. On the fixture seed the collapsed
        search now costs one extra turn (distance 90 against an optimal 75). That is a real
        limitation of the default, measured rather than assumed.
        """
        ties = 0
        for delta in (2, 3, 7, 8, 11):
            fast = solve(_state(SEED + delta), HUNT, _config())
            slow = solve(_state(SEED + delta), HUNT,
                         _config(collapse_offsets=False, max_states=200_000))
            self.assertIsInstance(fast, Solution)
            self.assertIsInstance(slow, Solution)
            self.assertGreaterEqual(fast.total_distance, slow.total_distance, f"seed +{delta}")
            ties += fast.total_distance == slow.total_distance
        self.assertGreater(ties, 0, "it should still usually tie")

    def test_the_exhaustive_search_is_affordable(self):
        """It is the fallback when the default's suboptimality matters, so it has to be usable."""
        import time
        start = time.time()
        result = solve(_state(), HUNT, _config(collapse_offsets=False, max_states=400_000))
        self.assertIsInstance(result, Solution)
        self.assertLess(time.time() - start, 10.0)

    #: Two capture windows in a 2-turn horizon, but no action sequence reaches either.
    EXHAUSTING_SEED = 0xF2A74DE4

    def test_only_the_exhaustive_search_claims_a_proof(self):
        """A heuristic exhaustion says nothing about the seed, so it must not claim one."""
        result = solve(_state(self.EXHAUSTING_SEED), HUNT, _config(max_turns=2))
        self.assertIsInstance(result, Unreachable)
        self.assertGreater(result.capture_windows, 0, "this seed must reach the search, not the "
                                                      "window proof, to test anything")
        self.assertFalse(result.proven)
        self.assertIn("cheapest arrival", result.reason)

    def test_the_exhaustive_search_does_claim_one(self):
        result = solve(_state(self.EXHAUSTING_SEED), HUNT,
                       _config(max_turns=2, collapse_offsets=False))
        self.assertIsInstance(result, Unreachable)
        self.assertTrue(result.proven)
        self.assertEqual(result.searched_turns, 2)

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


class TestStruggleDeadline(unittest.TestCase):
    """The simulator does not model Struggle -- with no usable slot it spends no roll and deals
    no damage, so those turns would be silently wrong. And in reality Struggle recoil kills a
    1 HP target, losing the legendary. So the search must stop short of it."""

    def test_the_deadline_is_two_and_a_half_times_remaining_pp(self):
        """Not total PP: a fully-paralyzed turn costs the target none, so the battle outlasts
        its PP -- and by Phase 2 some of that PP is already spent."""
        self.assertEqual(remaining_target_pp(_state().target), 90)
        self.assertEqual(struggle_deadline(_state().target), 225)

    def test_the_factor_is_configurable(self):
        self.assertEqual(struggle_deadline(_state().target, turns_per_pp=1.0), 90)

    def test_remaining_pp_is_what_counts_not_the_full_moveset(self):
        """Phase 2 starts after the identification turns have already burned PP."""
        state = _state()
        state.target = replace(state.target, pp=(1, 5, 2, 0))
        self.assertEqual(remaining_target_pp(state.target), 8)
        self.assertEqual(struggle_deadline(state.target), 20)

    def test_the_deadline_clamps_a_larger_configured_ceiling(self):
        result = solve(_state(), HUNT, _config(max_turns=1000))
        if isinstance(result, Solution):
            self.assertLessEqual(result.turns, 225)

    def test_a_lower_ceiling_still_wins(self):
        result = solve(_state(), HUNT, _config(max_turns=4))
        if isinstance(result, Solution):
            self.assertLessEqual(result.turns, 4)

    def test_the_exact_cutoff_is_applied_per_path_not_by_the_estimate(self):
        """A branch is cut the moment the target has no usable move, whatever the turn budget
        says -- that is exact, where the 2.5x figure is only a search-sizing estimate."""
        state = _state()
        state.target = replace(state.target, pp=(3, 0, 0, 0))
        result = solve(state, HUNT, _config(collapse_offsets=False))
        if isinstance(result, Solution):
            # With one move and 3 PP the target reaches Struggle fast, so a capture inside the
            # window is possible; the cutoff is then not what ended the search.
            self.assertLessEqual(result.turns, 7)
            return
        self.assertGreater(result.capture_windows, 0, "must reach the search, not the "
                                                      "window proof, to test anything")
        self.assertTrue(result.stopped_at_struggle)

    def test_a_full_pp_target_never_reaches_struggle_in_a_short_search(self):
        result = solve(_state(), HUNT, _config(max_turns=3))
        if isinstance(result, Unreachable):
            self.assertFalse(result.stopped_at_struggle)

    def test_a_target_with_no_pp_leaves_no_turns_to_search(self):
        state = _state()
        state.target = replace(state.target, pp=(0, 0, 0, 0))
        self.assertEqual(struggle_deadline(state.target), 0)
        self.assertIsInstance(solve(state, HUNT, _config()), Unreachable)


class TestAWindowIsATargetNotAReachableOne(unittest.TestCase):
    """The trap this whole result type exists to label. A capture window says four consecutive
    rolls under b sit at some RNG offset -- nothing about whether any action sequence arrives
    there holding a ball. Windows are dense (~1 offset in 79), so "windows exist" is close to
    free information and must never be read as "nearly reachable"."""

    def test_windows_are_found_even_where_no_path_exists(self):
        state = _state(TestOffsetCollapsing.EXHAUSTING_SEED)
        result = solve(state, HUNT, _config(max_turns=2))
        self.assertIsInstance(result, Unreachable)
        self.assertGreater(result.capture_windows, 0)

    def test_the_reason_says_targets_were_found_but_not_reached(self):
        result = solve(_state(TestOffsetCollapsing.EXHAUSTING_SEED), HUNT, _config(max_turns=2))
        self.assertIn("capture window", result.reason)
        self.assertIn("no action sequence arrives", result.reason)

    def test_the_reason_names_what_limited_the_search(self):
        """So a caller can tell "we looked everywhere" from "we stopped looking"."""
        collapsed = solve(_state(TestOffsetCollapsing.EXHAUSTING_SEED), HUNT, _config(max_turns=2))
        self.assertIn("cheapest arrival", collapsed.reason)
        capped = solve(_state(), HUNT, _config(max_states=5))
        self.assertIn("gave up", capped.reason)
        self.assertIn("says nothing about the seed", capped.reason)

    def test_the_window_count_is_reported_even_when_the_search_gave_up(self):
        """Or the count would look like zero and read as a proof."""
        result = solve(_state(), HUNT, _config(max_states=5))
        self.assertGreater(result.capture_windows, 0)
        self.assertFalse(result.proven)

    def test_many_windows_and_no_path_is_an_ordinary_outcome(self):
        """Not a contradiction to be explained away."""
        result = solve(_state(TestOffsetCollapsing.EXHAUSTING_SEED), HUNT, _config(max_turns=2))
        self.assertFalse(isinstance(result, Solution))
        self.assertGreaterEqual(result.capture_windows, 1)

    def test_every_unreachable_reports_the_budget_it_searched(self):
        """`proven` is bounded by it, so the number has to travel with the claim."""
        for config in (_config(max_turns=2), _config(max_states=5), _config(max_turns=1)):
            result = solve(_state(TestOffsetCollapsing.EXHAUSTING_SEED), HUNT, config)
            if isinstance(result, Unreachable):
                self.assertGreater(result.searched_turns, 0)

    def test_a_precondition_refusal_claims_nothing_at_all(self):
        result = solve(_state(hp=50), HUNT, _config())
        self.assertFalse(result.proven)
        self.assertEqual(result.capture_windows, 0)
        self.assertFalse(result.stopped_at_struggle)

    def test_no_window_in_the_horizon_is_the_one_real_proof(self):
        """The search can never prove a seed hopeless, because paralysis gives the battle no
        provable turn bound. The window scan can, within its horizon: no four consecutive rolls
        under b means no throw captures, however you arrive."""
        result = solve(_state(), HUNT, _config(max_turns=1))
        self.assertEqual(result.capture_windows, 0)
        self.assertTrue(result.proven)
        self.assertEqual(result.searched_turns, 1)


if __name__ == "__main__":
    unittest.main()
