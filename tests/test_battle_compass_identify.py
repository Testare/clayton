"""Candidate generation and narrowing.

The headline finding these tests pin down, as corrected: the frame axis is easy to identify and
the second axis is *slow* -- median 19 turns -- not impossible. The second lives in the seed's
top 8 bits and an LCRNG difference of k*2**24 stays there, but a roll is ``state >> 16``, so it
differs by 256*c and only moduli DIVIDING 256 are blind to it. ``% 4`` and ``% 16`` are; ``% 3``
(the move choice once PP drops) and ``% 100`` (accuracy, procs) are not.
"""
import datetime as dt
import unittest

from app.chart import global_calibration_models
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.candidates import (
    CANDIDATES_PER_SECOND, estimate_size, generate,
)
from claytonlib.battle_compass.identify import SECOND_SIBLING_MEDIAN_TURNS, Phase, Session
from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status

KEY_SEED = 0xEC1504DC
INITIAL_TIME = dt.datetime(2026, 9, 29, 12, 0, 0)
VECTOR_MS = 382791
CONFIG = HuntConfig(target_catch_rate=3)


def _model():
    return global_calibration_models()["linear"]


def _target(**overrides) -> Battler:
    fields = dict(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                  stats=derive_species_stats("suicune", 40, "Bold"),
                  moves=("Rain Dance", "Gust", "Aurora Beam", "Mist"), pp=(5, 35, 20, 30),
                  hp=1, status=Status.PARALYSIS)
    fields.update(overrides)
    return Battler(**fields)


def _ours() -> Battler:
    stats = {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160}
    return Battler(name="Smeargle", level=58, types=("Normal",), stats=stats,
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15))


def _window(**kwargs):
    return generate(_model(), key_seed=KEY_SEED, initial_time=INITIAL_TIME,
                    vector_ms=VECTOR_MS, **kwargs)


def _second_sibling_truth(window):
    """A candidate that definitely has siblings differing ONLY in the RTC second.

    Picked deliberately rather than by index: `generate` sorts centre-first, so which seed sits
    at a given position depends on where the window is centred, and a magic index silently stops
    testing what it was written for when the centring changes (which is exactly what happened
    when candidates.centre was corrected).
    """
    centre_frame = window.frame_centre
    siblings = [c for c in window.candidates if c.frame == centre_frame]
    assert len(siblings) > 1, "this window has no second-only siblings to be ambiguous about"
    return siblings[0].seed

def _session(window, phase=Phase.PINNING) -> Session:
    return Session(list(window.candidates), _ours(), _target(), CONFIG, phase=phase)


def _play(session: Session, truth: int, turns: int, action=Action.MOVE_1):
    """Feed `session` the observations the true seed actually produces.

    ``opening_rng``, not ``rng=truth``. This line used the raw seed, which is where six of this
    file's assertions came from and why they all passed while the real thing was broken: the
    fixture and ``Session`` made the same wrong assumption about where turn 1 starts, so they
    agreed with each other and disagreed only with the game. Against
    ``data/battle_logs/test2.jsonl`` the true seed was eliminated on turn 1. The convention now
    lives in one place, so a fixture cannot drift from the simulator again.
    """
    state = BattleState(ours=_ours(), target=_target(),
                        rng=opening_rng(truth, CONFIG), phase=2)
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

    def test_the_centre_is_seed_as_delay_plus_the_predicted_difference(self):
        """Vector ms is the GAP between Seed A and Seed B, not an absolute position.

        This test previously asserted ``frame_centre == round(model.frame(M, low16))`` -- the
        model's output used directly -- which is the bug it was meant to guard: that put the
        centre a couple of hundred frames *below* the key seed's own delay and emptied every
        window. See candidates.centre and app.metronome.seed_b_center.
        """
        from claytonlib.battle_compass.candidates import seed_a_delay
        window = _window()
        base_low16 = KEY_SEED & 0xFFFF
        difference = round(_model().frame(VECTOR_MS, base_low16) - base_low16)
        self.assertEqual(window.frame_centre,
                         seed_a_delay(KEY_SEED, INITIAL_TIME) + difference)
        self.assertEqual(window.second_centre, _model().battle_second_offset(VECTOR_MS))

    def test_the_centre_agrees_with_the_metronome_path(self):
        """The same quantity computed by the tool that always had it right."""
        from app.metronome import seed_b_center
        _, b_delay = seed_b_center(KEY_SEED, INITIAL_TIME, VECTOR_MS, _model())
        self.assertEqual(_window().frame_centre, b_delay)

    def test_the_second_is_not_derived_from_the_frame(self):
        """Coupling the two axes once produced a candidate set disjoint from the chart's."""
        wide, narrow = _window(frame_window=200), _window(frame_window=1)
        self.assertEqual(wide.second_centre, narrow.second_centre)

    def test_the_second_window_defaults_to_zero(self):
        """Because it costs ~19 extra turns for five times the candidates, not because
        observation cannot correct it — see TestSecondAmbiguity."""
        self.assertEqual(len(set(c.second for c in _window().candidates)), 1)

    def test_frames_below_seed_as_own_delay_are_skipped(self):
        """Seed B cannot precede Seed A. The floor is Seed A's delay for the TARGET YEAR, not
        get_times()'s year-2000 delay -- those differ by (year - 2000)."""
        from claytonlib.battle_compass.candidates import seed_a_delay
        floor = seed_a_delay(KEY_SEED, INITIAL_TIME)
        for candidate in _window(frame_window=100000).candidates:
            self.assertGreaterEqual(candidate.frame, floor)

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
    """Candidates differing only in the RTC second separate SLOWLY, not never.

    The invariant is real -- an LCRNG difference of k*2**24 stays a multiple of 2**24 forever --
    but the conclusion drawn from it here was wrong. A roll is ``state >> 16``, so it differs by
    256*c: the % 4 move choice and % 16 crit/damage rolls are identical, but % 100 accuracy and
    proc rolls are not. Measured median 19 turns for this fixture.
    """

    def test_the_lcrng_difference_stays_in_the_top_eight_bits(self):
        """The part that IS true, and the reason the second is slow rather than free."""
        from claytonlib.safari import advance_rng
        a, b = 0xEC1504DC, (0xEC1504DC + (1 << 24)) & 0xFFFFFFFF
        for _ in range(50):
            a, b = advance_rng(a), advance_rng(b)
            self.assertEqual(((b - a) & 0xFFFFFFFF) % (1 << 24), 0)

    def test_the_low_moduli_really_are_identical(self):
        """% 4 (move choice) and % 16 (crit, damage) cannot see the second, because 256 is a
        multiple of both."""
        from claytonlib.safari import advance_rng
        a, b = 0xEC1504DC, (0xEC1504DC + (1 << 24)) & 0xFFFFFFFF
        for _ in range(200):
            a, b = advance_rng(a), advance_rng(b)
            self.assertEqual((a >> 16) % 4, (b >> 16) % 4)
            self.assertEqual((a >> 16) % 16, (b >> 16) % 16)

    def test_percent_one_hundred_does_see_it(self):
        """Which is what makes the second identifiable at all: 100 does not divide 256."""
        from claytonlib.safari import advance_rng
        a, b = 0xEC1504DC, (0xEC1504DC + (1 << 24)) & 0xFFFFFFFF
        differing = 0
        for _ in range(200):
            a, b = advance_rng(a), advance_rng(b)
            differing += ((a >> 16) % 100) != ((b >> 16) % 100)
        self.assertGreater(differing, 150, "% 100 should almost always differ")

    def test_a_second_window_resolves_eventually(self):
        """It used to be asserted that it never would."""
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, _second_sibling_truth(window), turns=60)
        self.assertIsNotNone(session.identified,
                             "second-siblings should separate within 60 turns")

    def test_it_is_slow_though(self):
        """Twelve turns was the old test's budget, and is usually not enough."""
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, _second_sibling_truth(window), turns=8)
        self.assertGreater(len(session.survivors), 1)

    def test_it_is_diagnosed_as_second_only(self):
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, _second_sibling_truth(window), turns=6)
        ambiguity = session.ambiguity()
        self.assertTrue(ambiguity["frame_pinned"])
        self.assertTrue(ambiguity["second_only"])
        # Separable -- slowly. This was False, and the advice told the player to restart.
        self.assertTrue(ambiguity["separable_by_moves"])
        self.assertEqual(ambiguity["expected_turns"], SECOND_SIBLING_MEDIAN_TURNS)

    def test_the_advice_no_longer_claims_it_is_hopeless(self):
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, _second_sibling_truth(window), turns=6)
        advice = session.ambiguity()["advice"]
        self.assertIn("not impossible", advice)
        self.assertNotIn("will not help", advice)

    def test_most_single_turns_do_not_separate_them(self):
        """Which is why it takes ~19: any one turn usually looks identical."""
        window = _window(frame_window=60, second_window=2)
        session = _session(window)
        _play(session, _second_sibling_truth(window), turns=6)
        identical = sum(
            len(set(session.predict(a).values())) == 1
            for a in (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4, Action.ITEM))
        # Most, not all: modelling field conditions gave the target's failing moves their own
        # offsets, so a couple of actions now distinguish seconds where none used to.
        self.assertGreaterEqual(identical, 3)

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
    def test_balls_are_accepted_in_every_phase_including_setup(self):
        """The Phase 1 ban is gone, and both halves of it were wrong.

        The capture ball never carried a risk -- a landing wins the run -- so refusing it only
        discarded information. A standard ball does carry one, but it gets *cheaper* the earlier
        it is thrown (0.35% per throw at full HP against 1.25% at 1 HP and paralyzed), so a ban
        that deferred throws out of Phase 1 pushed them to where they cost most. What replaces it
        is disclosure: `HuntSession.standard_ball_risk` (notes/seed_separation.md sec 2a).
        """
        for phase in (Phase.SETUP, Phase.PINNING, Phase.SOLVING):
            for action in (Action.CAPTURE_BALL, Action.STANDARD_BALL):
                session = _session(_window(frame_window=5), phase=phase)
                predicted = session.predict(action)[session.survivors[0]]
                result = session.observe(action, (predicted,))
                self.assertFalse(result.contradiction, f"{phase.name}/{action.value}")

    def test_no_phase_carries_a_ball_gate_any_more(self):
        """`balls_allowed` is gone rather than pinned to True: a flag that is always true tells a
        caller nothing, and leaving it invited the gate to grow back."""
        for phase in (Phase.SETUP, Phase.PINNING, Phase.SOLVING):
            self.assertFalse(hasattr(phase, "balls_allowed"))

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

    def test_ranking_includes_balls_during_setup(self):
        """And ranks them on information alone. A standard ball's chance of ending the run is
        priced nowhere in this score, which is why the risk is reported beside it, not folded in.
        """
        session = _session(_window(frame_window=5), phase=Phase.SETUP)
        actions = [a for a, _ in session.rank_actions(
            [Action.MOVE_1, Action.CAPTURE_BALL, Action.STANDARD_BALL])]
        self.assertEqual(set(actions),
                         {Action.MOVE_1, Action.CAPTURE_BALL, Action.STANDARD_BALL})

    def test_a_ball_separates_better_than_a_move_that_cannot_miss(self):
        """The reason lifting the ban is a gain and not just a permission. The shake check is a
        magnitude comparison, so it sees differences that `% 4` and `% 16` are blind to."""
        session = _session(_window(frame_window=60), phase=Phase.SETUP)
        scores = dict(session.rank_actions([Action.MOVE_1, Action.CAPTURE_BALL]))
        self.assertLess(scores[Action.CAPTURE_BALL], scores[Action.MOVE_1])

    def test_a_partition_covers_every_survivor_exactly_once(self):
        session = _session(_window(frame_window=20))
        groups = session.partition(Action.MOVE_1)
        self.assertEqual(sum(len(g) for g in groups.values()), len(session.survivors))


class TestWhichModuliSeeTheRtcSecond(unittest.TestCase):
    """The arithmetic behind the correction. A roll differs by 256*c between second-siblings, so
    a modulus is blind to the second exactly when it divides 256 -- and the original claim
    generalised from the powers of two to every modulus without checking."""

    def test_only_moduli_dividing_256_are_blind(self):
        self.assertEqual([m for m in (2, 3, 4, 16, 100) if 256 % m == 0], [2, 4, 16])
        self.assertEqual([m for m in (2, 3, 4, 16, 100) if 256 % m != 0], [3, 100])

    def test_the_wild_move_choice_separates_seconds_once_pp_drops(self):
        """`% len(usable)`: invariant at 4 and 2 usable moves, NOT at 3. Rain Dance has 5 PP, so
        a long battle reaches 3 early -- which is a stronger discriminator than any proc."""
        from claytonlib.battle_compass.sim import select_target_move
        for pp, expect_differences in (((5, 35, 20, 30), False),     # 4 usable -> % 4
                                       ((0, 35, 20, 30), True),      # 3 usable -> % 3
                                       ((0, 0, 20, 30), False)):     # 2 usable -> % 2
            differing = 0
            for k in range(200):
                a = (KEY_SEED + k * 7919) & 0xFFFFFFFF
                b = (a + (1 << 24)) & 0xFFFFFFFF
                _, pick_a = select_target_move(a, _target(pp=pp))
                _, pick_b = select_target_move(b, _target(pp=pp))
                differing += pick_a != pick_b
            if expect_differences:
                self.assertGreater(differing, 80, f"pp={pp} should separate seconds")
            else:
                self.assertEqual(differing, 0, f"pp={pp} should be blind to the second")

    def test_the_damage_roll_is_blind(self):
        """% 16, so identical -- which is why an HP change never separates seconds."""
        from claytonlib.safari import advance_rng
        a, b = KEY_SEED, (KEY_SEED + (1 << 24)) & 0xFFFFFFFF
        for _ in range(300):
            a, b = advance_rng(a), advance_rng(b)
            self.assertEqual(85 + (a >> 16) % 16, 85 + (b >> 16) % 16)

    def test_the_shake_check_is_not_blind(self):
        """A magnitude comparison, so it sees the second -- but Phase 1 bars balls anyway (2.3)."""
        from claytonlib.battle.catch import shake_threshold
        from claytonlib.safari import advance_rng
        threshold = shake_threshold(3)
        a, b = KEY_SEED, (KEY_SEED + (1 << 24)) & 0xFFFFFFFF
        differing = 0
        for _ in range(400):
            a, b = advance_rng(a), advance_rng(b)
            differing += ((a >> 16) < threshold) != ((b >> 16) < threshold)
        self.assertGreater(differing, 20)


if __name__ == "__main__":
    unittest.main()
