"""Candidate generation and narrowing.

The headline finding these tests pin down: the frame axis is easy to identify and the second axis
is impossible to, because the second lives in the seed's top 8 bits and every in-game modulo
reads only the low ones.
"""
import datetime as dt
import unittest

from app.chart import global_calibration_models
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.candidates import (
    CANDIDATES_PER_SECOND, estimate_size, generate,
)
from claytonlib.battle_compass.identify import Phase, Session
from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status

KEY_SEED = 0xEC1504DC
INITIAL_TIME = dt.datetime(2026, 9, 29, 12, 0, 0)
VECTOR_MS = 382791
CONFIG = HuntConfig(target_catch_rate=3)


def _model():
    return global_calibration_models()["linear"]


def _target() -> Battler:
    return Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                   stats=derive_species_stats("suicune", 40, "Bold"),
                   moves=("Rain Dance", "Gust", "Aurora Beam", "Mist"), pp=(5, 35, 20, 30),
                   hp=1, status=Status.PARALYSIS)


def _ours() -> Battler:
    stats = {**derive_species_stats("smeargle", 60, "Hardy"), "atk": 65}
    return Battler(name="Smeargle", level=60, types=("Normal",), stats=stats,
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15))


def _window(**kwargs):
    return generate(_model(), key_seed=KEY_SEED, initial_time=INITIAL_TIME,
                    vector_ms=VECTOR_MS, **kwargs)


def _session(window, phase=Phase.PINNING) -> Session:
    return Session(list(window.candidates), _ours(), _target(), CONFIG, phase=phase)


def _play(session: Session, truth: int, turns: int, action=Action.MOVE_1):
    """Feed `session` the observations the true seed actually produces."""
    state = BattleState(ours=_ours(), target=_target(), rng=truth, phase=2)
    results = []
    for _ in range(turns):
        state = simulate_turn(state, action, CONFIG)
        results.append(session.observe(action, state.log[-1]))
        if session.identified:
            break
    return results


class TestCandidateGeneration(unittest.TestCase):
    def test_the_grid_is_uniform_and_deduplicated(self):
        window = _window(frame_window=10, second_window=1)
        self.assertEqual(len(set(window.seeds)), len(window))
        self.assertLessEqual(len(window), estimate_size(10, 1))

    def test_the_centre_comes_from_the_model(self):
        window = _window()
        self.assertEqual(window.frame_centre,
                         round(_model().frame(VECTOR_MS, KEY_SEED & 0xFFFF)))
        self.assertEqual(window.second_centre, _model().battle_second_offset(VECTOR_MS))

    def test_the_second_is_not_derived_from_the_frame(self):
        """Coupling the two axes once produced a candidate set disjoint from the chart's."""
        wide, narrow = _window(frame_window=200), _window(frame_window=1)
        self.assertEqual(wide.second_centre, narrow.second_centre)

    def test_the_second_window_defaults_to_zero(self):
        """Because observation cannot correct it — see TestSecondAmbiguity."""
        self.assertEqual(len(set(c.second for c in _window().candidates)), 1)

    def test_frames_below_the_key_seeds_base_delay_are_skipped(self):
        from claytonlib.times import get_times
        base, _ = get_times(KEY_SEED)
        for candidate in _window(frame_window=100000).candidates:
            self.assertGreaterEqual(candidate.frame, base)

    def test_candidates_are_ordered_by_proximity_to_the_centre(self):
        window = _window(frame_window=5, second_window=1)
        deltas = [abs(c.frame - window.frame_centre) for c in window.candidates]
        self.assertEqual(deltas, sorted(deltas))

    def test_negative_windows_are_rejected(self):
        for kwargs in ({"frame_window": -1}, {"second_window": -1}):
            with self.assertRaises(ValueError):
                _window(**kwargs)

    def test_size_estimate_is_useful_before_generating(self):
        self.assertEqual(estimate_size(60, 0), 121)
        self.assertEqual(estimate_size(60, 2), 605)

    def test_a_second_of_slack_costs_about_the_documented_number(self):
        self.assertAlmostEqual(CANDIDATES_PER_SECOND, 120, delta=5)


class TestNarrowing(unittest.TestCase):
    def test_a_wide_frame_window_pins_in_a_few_turns(self):
        window = _window(frame_window=600)
        self.assertGreater(len(window), 1000)
        session = _session(window)
        truth = window.candidates[len(window) // 3].seed
        _play(session, truth, turns=8)
        self.assertEqual(session.identified, truth)

    def test_each_turn_eliminates_candidates(self):
        session = _session(_window(frame_window=60))
        results = _play(session, _window(frame_window=60).candidates[5].seed, turns=3)
        self.assertGreater(results[0].eliminated, 0)

    def test_an_impossible_observation_is_a_contradiction_not_an_empty_set(self):
        """Far likelier to mean a too-narrow window or a wrong constant than that every
        candidate is genuinely excluded — and emptying the set destroys the evidence."""
        session = _session(_window(frame_window=10))
        before = session.survivors
        result = session.observe(Action.MOVE_1, ("M1", "h", "E2", "h", "HP001"))
        self.assertTrue(result.contradiction)
        self.assertEqual(session.survivors, before)
        self.assertTrue(result.rejected, "a contradiction should show what was predicted")

    def test_predictions_are_recorded_for_the_survivors(self):
        session = _session(_window(frame_window=20))
        window = _window(frame_window=20)
        results = _play(session, window.candidates[3].seed, turns=1)
        self.assertEqual(set(results[0].predictions), set(results[0].survivors))

    def test_predict_does_not_advance_the_session(self):
        session = _session(_window(frame_window=10))
        before = session.survivors
        session.predict(Action.MOVE_1)
        self.assertEqual(session.survivors, before)


class TestSecondAmbiguity(unittest.TestCase):
    """The finding: candidates differing only in the RTC second are invisible to every
    modulo-based observable, because the second sits in the seed's top 8 bits and an LCRNG
    difference of k*2**24 stays there forever."""

    def test_a_second_window_stalls_and_never_resolves(self):
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, window.candidates[7].seed, turns=12)
        self.assertIsNone(session.identified)
        self.assertGreater(len(session.survivors), 1)

    def test_the_stall_is_diagnosed_as_second_only(self):
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, window.candidates[7].seed, turns=6)
        ambiguity = session.ambiguity()
        self.assertTrue(ambiguity["frame_pinned"])
        self.assertTrue(ambiguity["second_only"])
        self.assertFalse(ambiguity["separable_by_moves"])
        self.assertIn("top 8 bits", ambiguity["advice"])

    def test_no_move_separates_second_only_survivors(self):
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, window.candidates[7].seed, turns=6)
        for action in (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4, Action.ITEM):
            self.assertEqual(len(set(session.predict(action).values())), 1, action)

    def test_the_default_window_identifies_where_a_second_window_cannot(self):
        window = _window(frame_window=60)
        session = _session(window)
        _play(session, window.candidates[7].seed, turns=8)
        self.assertIsNotNone(session.identified)

    def test_ambiguity_reports_identified_when_pinned(self):
        window = _window(frame_window=60)
        session = _session(window)
        _play(session, window.candidates[7].seed, turns=8)
        self.assertEqual(session.ambiguity()["advice"], "identified")


class TestPhases(unittest.TestCase):
    def test_balls_are_refused_during_setup(self):
        """A standard ball shares the capture ball's multiplier here, so a throw that lands
        catches the target in the wrong ball (sec 2.3)."""
        session = _session(_window(frame_window=5), phase=Phase.SETUP)
        for action in (Action.CAPTURE_BALL, Action.STANDARD_BALL):
            with self.assertRaises(ValueError, msg=action):
                session.observe(action, ("P0",))

    def test_balls_are_allowed_once_pinning(self):
        self.assertFalse(Phase.SETUP.balls_allowed)
        self.assertTrue(Phase.PINNING.balls_allowed)
        self.assertTrue(Phase.SOLVING.balls_allowed)

    def test_the_transition_out_of_setup_is_explicit(self):
        session = _session(_window(frame_window=5), phase=Phase.SETUP)
        session.enter_pinning()
        self.assertIs(session.phase, Phase.PINNING)
        with self.assertRaises(ValueError):
            session.enter_pinning()

    def test_solving_is_blocked_until_the_seed_is_pinned(self):
        session = _session(_window(frame_window=60))
        blockers = session.solver_blockers()
        self.assertTrue(any("not pinned" in b for b in blockers))
        with self.assertRaises(ValueError):
            session.enter_solving()

    def test_solving_is_blocked_while_still_in_setup(self):
        session = _session(_window(frame_window=0), phase=Phase.SETUP)
        self.assertTrue(any("setup" in b for b in session.solver_blockers()))

    def test_solving_starts_once_pinned_at_one_hp_and_paralyzed(self):
        window = _window(frame_window=60)
        session = _session(window)
        _play(session, window.candidates[7].seed, turns=8)
        self.assertEqual(session.solver_blockers(), [])
        session.enter_solving()
        self.assertIs(session.phase, Phase.SOLVING)


class TestInformationGain(unittest.TestCase):
    """Phase 1.5 maximises information gain, where Phase 2 minimises distance (sec 15.3)."""

    def test_expected_survivors_is_lower_for_a_more_separating_action(self):
        session = _session(_window(frame_window=60))
        scored = dict(session.rank_actions([Action.MOVE_1, Action.ITEM]))
        self.assertLessEqual(scored[Action.MOVE_1], len(session.survivors))

    def test_ranking_puts_the_best_action_first(self):
        session = _session(_window(frame_window=60))
        ranked = session.rank_actions([Action.MOVE_1, Action.MOVE_2, Action.ITEM])
        self.assertEqual([score for _, score in ranked], sorted(score for _, score in ranked))

    def test_ranking_excludes_balls_during_setup(self):
        session = _session(_window(frame_window=5), phase=Phase.SETUP)
        actions = [a for a, _ in session.rank_actions(
            [Action.MOVE_1, Action.CAPTURE_BALL, Action.STANDARD_BALL])]
        self.assertEqual(actions, [Action.MOVE_1])

    def test_a_partition_covers_every_survivor_exactly_once(self):
        session = _session(_window(frame_window=20))
        groups = session.partition(Action.MOVE_1)
        self.assertEqual(sum(len(g) for g in groups.values()), len(session.survivors))


if __name__ == "__main__":
    unittest.main()
