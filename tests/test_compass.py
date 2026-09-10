"""
Unit tests for compass.py — input parsing, seed generation, and action filtering.
"""
import copy
import datetime as dt
import unittest
from unittest.mock import patch

from claytonlib.chart import STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE
from claytonlib.compass import (
    CompassAction,
    CompassOptions,
    CompassSafariInput,
    ParseError,
    UndoAction,
    _action_to_str,
    _apply_action,
    _evaluate_context,
    _generate_candidates,
    _generate_candidates_calibrated,
    _second_of_frame,
    parse_input,
)
from claytonlib.safari import SafariContext, SafariStep, safari_pokemon_by_name
from claytonlib.times import calculate_seed

# Fixed test parameters. KEY_SEED matches the chart test fixture.
KEY_SEED   = 0xF613_087B
BASE_DELAY = KEY_SEED & 0xFFFF   # 2171
TIME_A     = dt.datetime(2000, 4, 30, 19, 57, 59)

# A target_delay on a valid frame boundary (frame 0 of second 10).
TARGET_DELAY = BASE_DELAY + 10 * 60  # 2771


def _fake_get_times(key_seed):
    return key_seed & 0xFFFF, [TIME_A]


def _make_inputs(**kwargs):
    pokemon = safari_pokemon_by_name('metang')
    defaults = dict(
        pokemon=pokemon,
        strategy=STRATEGY_ONLY_BALLS,
        criteria=CRITERIA_CAPTURE,
        window=4,
        initial_time=TIME_A,
        key_seed=KEY_SEED,
        target_delay=TARGET_DELAY,
    )
    defaults.update(kwargs)
    with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
        return CompassSafariInput(**defaults)


# ---------------------------------------------------------------------------
# parse_input
# ---------------------------------------------------------------------------

class TestParseInput(unittest.TestCase):

    def _actions(self, text):
        result = parse_input(text)
        self.assertIsInstance(result, list)
        return result

    def _error(self, text):
        result = parse_input(text)
        self.assertIsInstance(result, ParseError)
        return result

    # Basic step mapping
    def test_mud(self):
        [a] = self._actions('m')
        self.assertEqual(a.step, SafariStep.MUD)
        self.assertFalse(a.uncertain)

    def test_mud_critical_uppercase(self):
        [a] = self._actions('M')
        self.assertEqual(a.step, SafariStep.MUD_CRITICAL)

    def test_mud_critical_alias_a(self):
        [a] = self._actions('a')
        self.assertEqual(a.step, SafariStep.MUD_CRITICAL)

    def test_bait(self):
        [a] = self._actions('b')
        self.assertEqual(a.step, SafariStep.BAIT)

    def test_bait_critical_uppercase(self):
        [a] = self._actions('B')
        self.assertEqual(a.step, SafariStep.BAIT_CRITICAL)

    def test_bait_critical_alias_e(self):
        [a] = self._actions('e')
        self.assertEqual(a.step, SafariStep.BAIT_CRITICAL)

    def test_ball_shakes(self):
        actions = self._actions('0123')
        steps = [a.step for a in actions]
        self.assertEqual(steps, [
            SafariStep.BALL_0, SafariStep.BALL_1,
            SafariStep.BALL_2, SafariStep.BALL_3,
        ])

    def test_fled(self):
        [a] = self._actions('F')
        self.assertEqual(a.step, SafariStep.FLED)

    def test_captured(self):
        [a] = self._actions('C')
        self.assertEqual(a.step, SafariStep.CAPTURED)

    def test_undo(self):
        [u] = self._actions('u')
        self.assertIsInstance(u, UndoAction)

    # Uncertain prefix
    def test_uncertain_bait(self):
        [a] = self._actions('?b')
        self.assertEqual(a.step, SafariStep.BAIT)
        self.assertTrue(a.uncertain)

    def test_uncertain_bait_uppercase(self):
        [a] = self._actions('?B')
        self.assertEqual(a.step, SafariStep.BAIT)
        self.assertTrue(a.uncertain)

    def test_uncertain_bait_alias(self):
        [a] = self._actions('?e')
        self.assertEqual(a.step, SafariStep.BAIT)
        self.assertTrue(a.uncertain)

    def test_uncertain_mud(self):
        [a] = self._actions('?m')
        self.assertEqual(a.step, SafariStep.MUD)
        self.assertTrue(a.uncertain)

    def test_uncertain_mud_alias(self):
        [a] = self._actions('?a')
        self.assertEqual(a.step, SafariStep.MUD)
        self.assertTrue(a.uncertain)

    def test_uncertain_ball_all_digits_canonical(self):
        # ?0, ?1, ?2, ?3 all map to BALL_0 as the canonical representative
        for ch in '0123':
            [a] = self._actions(f'?{ch}')
            self.assertEqual(a.step, SafariStep.BALL_0)
            self.assertTrue(a.uncertain)

    # Sequence parsing
    def test_sequence(self):
        actions = self._actions('b23')
        self.assertEqual(len(actions), 3)
        self.assertEqual(actions[0].step, SafariStep.BAIT)
        self.assertEqual(actions[1].step, SafariStep.BALL_2)
        self.assertEqual(actions[2].step, SafariStep.BALL_3)

    def test_spaces_and_commas_ignored(self):
        a = self._actions('b, 2, 3')
        b = self._actions('b23')
        self.assertEqual(len(a), len(b))
        for x, y in zip(a, b):
            self.assertEqual(x.step, y.step)

    # Error cases
    def test_unknown_char_returns_error(self):
        err = self._error('bxz')
        self.assertIn('x', err.unknown_chars)
        self.assertIn('z', err.unknown_chars)

    def test_unknown_char_does_not_include_valid(self):
        err = self._error('bx')
        self.assertNotIn('b', err.unknown_chars)

    def test_bare_question_mark_is_error(self):
        err = self._error('?')
        self.assertIn('?', err.unknown_chars)

    def test_all_unknown_chars_reported(self):
        err = self._error('xyz')
        self.assertEqual(err.unknown_chars, {'x', 'y', 'z'})

    def test_error_blocks_entire_input(self):
        # Even if some chars are valid, the whole input is rejected
        result = parse_input('b x 2')
        self.assertIsInstance(result, ParseError)

    # _action_to_str round-trip
    def test_action_str_certain(self):
        self.assertEqual(_action_to_str(CompassAction(SafariStep.BAIT)), 'b')
        self.assertEqual(_action_to_str(CompassAction(SafariStep.MUD_CRITICAL)), 'M')
        self.assertEqual(_action_to_str(CompassAction(SafariStep.BALL_2)), '2')

    def test_action_str_uncertain_bait(self):
        self.assertEqual(_action_to_str(CompassAction(SafariStep.BAIT, uncertain=True)), '?b')

    def test_action_str_uncertain_mud(self):
        self.assertEqual(_action_to_str(CompassAction(SafariStep.MUD, uncertain=True)), '?m')

    def test_action_str_uncertain_ball(self):
        self.assertEqual(_action_to_str(CompassAction(SafariStep.BALL_0, uncertain=True)), '?0')


# ---------------------------------------------------------------------------
# CompassSafariInput validation
# ---------------------------------------------------------------------------

class TestCompassSafariInputValidation(unittest.TestCase):

    def _base_kwargs(self):
        return dict(
            pokemon=safari_pokemon_by_name('metang'),
            strategy=STRATEGY_ONLY_BALLS,
            criteria=CRITERIA_CAPTURE,
            window=4,
            initial_time=TIME_A,
            key_seed=KEY_SEED,
            target_delay=TARGET_DELAY,
        )

    def test_valid_construction(self):
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput(**self._base_kwargs())
        self.assertEqual(inp.target_delay, TARGET_DELAY)

    def test_missing_target_delay_raises(self):
        kw = self._base_kwargs()
        kw['target_delay'] = None
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            with self.assertRaises(ValueError):
                CompassSafariInput(**kw)

    def test_missing_key_seed_raises(self):
        kw = self._base_kwargs()
        kw['key_seed'] = None
        with self.assertRaises(ValueError):
            CompassSafariInput(**kw)

    def test_valid_target_seed_passes(self):
        # Compute the actual seed at TARGET_DELAY frame 0 from TIME_A
        second_idx = (TARGET_DELAY - BASE_DELAY) // 60
        time_at = TIME_A + dt.timedelta(seconds=second_idx)
        expected_seed = calculate_seed(time_at, BASE_DELAY + second_idx * 60)
        kw = self._base_kwargs()
        kw['target_seed'] = expected_seed
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput(**kw)
        self.assertEqual(inp.target_seed, expected_seed)

    def test_mismatched_target_seed_raises(self):
        kw = self._base_kwargs()
        kw['target_seed'] = 0xDEADBEEF
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            with self.assertRaises(ValueError):
                CompassSafariInput(**kw)

    def test_from_chart_copies_key_fields(self):
        from claytonlib.chart import ChartSafariInput
        chart = ChartSafariInput(
            key_seed=KEY_SEED,
            setup_delay_seconds=5,
            max_target_seconds=10,
            strategy=STRATEGY_ONLY_BALLS,
            criteria=CRITERIA_CAPTURE,
            pokemon=safari_pokemon_by_name('metang'),
        )
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput.from_chart(
                chart,
                window=4,
                initial_time=TIME_A,
                target_delay=TARGET_DELAY,
            )
        self.assertEqual(inp.key_seed, KEY_SEED)
        self.assertEqual(inp.pokemon, chart.pokemon)
        self.assertEqual(inp.strategy, chart.strategy)
        self.assertEqual(inp.criteria, chart.criteria)


# ---------------------------------------------------------------------------
# _generate_candidates
# ---------------------------------------------------------------------------

class TestGenerateCandidates(unittest.TestCase):

    def _candidates(self, **kwargs):
        inp = _make_inputs(**kwargs)
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            return _generate_candidates(inp), inp

    def test_no_duplicate_seeds(self):
        cands, _ = self._candidates(window=10)
        seeds = [s for _, s, _ in cands]
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_delays_in_window(self):
        window = 10
        cands, inp = self._candidates(window=window)
        for _, _, d in cands:
            self.assertGreaterEqual(d, inp.target_delay - window)
            self.assertLessEqual(d, inp.target_delay + window)

    def test_delays_step_by_one(self):
        cands, _ = self._candidates(window=10)
        delays = sorted(set(d for _, _, d in cands))
        for i in range(len(delays) - 1):
            self.assertEqual(delays[i + 1] - delays[i], 1)

    def test_frame0_delay_has_two_seeds(self):
        # A delay at frame_j = 0 now generates both seed_a and seed_b
        frame0_delay = BASE_DELAY + 10 * 60  # exactly frame 0 of second 10
        cands, _ = self._candidates(target_delay=frame0_delay, window=0)
        self.assertEqual(len(cands), 2)

    def test_nonzero_frame_delay_has_two_seeds(self):
        # A delay where frame_j > 0 → two seeds
        frame15_delay = BASE_DELAY + 10 * 60 + 30  # frame 15
        cands, _ = self._candidates(target_delay=frame15_delay, window=0)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0][2], cands[1][2])  # same delay, different seeds

    def test_seeds_are_correct_at_frame0(self):
        frame0_delay = BASE_DELAY + 10 * 60
        cands, _ = self._candidates(target_delay=frame0_delay, window=0)
        seeds = [s for _, s, _ in cands]
        second_idx = 10
        time_at = TIME_A + dt.timedelta(seconds=second_idx)
        expected = calculate_seed(time_at, BASE_DELAY + second_idx * 60)
        self.assertIn(expected, seeds)

    def test_starting_ball_count_applied(self):
        cands, _ = self._candidates(window=0, options=CompassOptions(starting_ball_count=25))
        for ctx, _, _ in cands:
            self.assertEqual(ctx.balls_remaining, 25)

    def test_sorted_by_delay_then_seed(self):
        cands, _ = self._candidates(window=10)
        for i in range(len(cands) - 1):
            d_a, s_a = cands[i][2], cands[i][1]
            d_b, s_b = cands[i + 1][2], cands[i + 1][1]
            self.assertLessEqual((d_a, s_a), (d_b, s_b))


# ---------------------------------------------------------------------------
# Calibrated (second, frame) candidate generation  (b70.1 / b70.3)
# ---------------------------------------------------------------------------

def _line_model(beta=0.06, alpha=float(BASE_DELAY), jitter_c=0.128):
    from claytonlib.calibration import CalibrationModel
    return CalibrationModel(kind="line", beta=beta, alpha=alpha, jitter_c=jitter_c)


class TestCalibratedCandidateGeneration(unittest.TestCase):

    # M chosen so F* = alpha + beta*M lands ~300 frames past base_delay (well inside range).
    M = 5000
    MAX_SECONDS = 30

    def _input(self, **kwargs):
        model = _line_model()
        defaults = dict(
            model=model, M=self.M, initial_time=TIME_A, key_seed=KEY_SEED,
            max_target_seconds=self.MAX_SECONDS,
            pokemon=safari_pokemon_by_name('metang'),
            strategy=STRATEGY_ONLY_BALLS, criteria=CRITERIA_CAPTURE,
        )
        defaults.update(kwargs)
        with patch('claytonlib.times.get_times', side_effect=_fake_get_times), \
             patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput.from_expedition_target(**defaults)
        return inp, model

    def _candidates(self, **kwargs):
        inp, model = self._input(**kwargs)
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            return _generate_candidates_calibrated(inp), inp, model

    def test_from_expedition_target_sets_calibrated_fields(self):
        inp, model = self._input()
        self.assertTrue(inp.calibrated)
        self.assertEqual(inp.frame_center, model.mean(self.M))
        self.assertAlmostEqual(inp.sigma, model.jitter_sigma(self.M))
        self.assertIsNone(inp.target_delay)
        # target_second is the band containing F*
        self.assertEqual(_second_of_frame(BASE_DELAY, round(inp.frame_center)),
                         inp.target_second)

    def test_one_seed_per_frame_no_seed_a_b(self):
        # δ=0: exactly one candidate per frame in [F*-kσ, F*+kσ] (no a/b duality)
        cands, inp, _ = self._candidates()
        sigma = inp.sigma
        lo = max(BASE_DELAY, int(inp.frame_center - inp.k * sigma))
        hi = int(inp.frame_center + inp.k * sigma) + 1  # ceil bound tolerance
        frames = [f for _, _, f in cands]
        self.assertEqual(len(frames), len(set(frames)))  # no duplicate frames
        self.assertGreaterEqual(min(frames), lo)
        self.assertLessEqual(max(frames), hi)

    def test_frames_span_the_sigma_window(self):
        cands, inp, _ = self._candidates()
        frames = sorted(f for _, _, f in cands)
        # window half-width in frames
        half = inp.k * inp.sigma
        self.assertLessEqual(abs(frames[0] - (inp.frame_center - half)), 1.0)
        self.assertLessEqual(abs(frames[-1] - (inp.frame_center + half)), 1.0)

    def test_seed_matches_calculate_seed_at_band_second(self):
        cands, inp, _ = self._candidates()
        for _, seed, frame in cands:
            s = _second_of_frame(BASE_DELAY, frame)
            expected = calculate_seed(TIME_A + dt.timedelta(seconds=s), frame)
            self.assertEqual(seed, expected)

    def test_no_duplicate_seeds(self):
        cands, _, _ = self._candidates()
        seeds = [s for _, s, _ in cands]
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_second_offsets_widen_candidate_set(self):
        base, _, _ = self._candidates()
        wide, inp, _ = self._candidates(second_offsets=(-1, 0, 1))
        self.assertGreater(len(wide), len(base))
        # every base (δ=0) seed still present in the widened set
        self.assertTrue(set(s for _, s, _ in base) <= set(s for _, s, _ in wide))

    def test_offset_seeds_use_shifted_second_same_frame(self):
        # A +1 δ candidate is calculate_seed(initial_time + (s+1), frame) at the same frame.
        cands, inp, _ = self._candidates(second_offsets=(1,))
        for _, seed, frame in cands:
            s = _second_of_frame(BASE_DELAY, frame) + 1
            expected = calculate_seed(TIME_A + dt.timedelta(seconds=s), frame)
            self.assertEqual(seed, expected)

    def test_starting_ball_count_applied(self):
        cands, _, _ = self._candidates(options=CompassOptions(starting_ball_count=25))
        for ctx, _, _ in cands:
            self.assertEqual(ctx.balls_remaining, 25)

    def test_sorted_by_frame_then_seed(self):
        cands, _, _ = self._candidates(second_offsets=(-1, 0, 1))
        for i in range(len(cands) - 1):
            self.assertLessEqual((cands[i][2], cands[i][1]),
                                 (cands[i + 1][2], cands[i + 1][1]))

    def test_narrowing_still_works(self):
        # An observed ball outcome filters the calibrated set the same way as legacy.
        cands, _, _ = self._candidates()
        action = CompassAction(step=SafariStep.BALL_0)
        filtered = _apply_action(cands, action, filter_fled=False)
        self.assertLessEqual(len(filtered), len(cands))
        pokemon = safari_pokemon_by_name('metang')
        for _, seed, _ in filtered:
            orig = SafariContext.start_encounter(seed, pokemon)
            self.assertEqual(orig.throw_ball(), SafariStep.BALL_0)

    def test_calibrated_input_requires_sigma_and_second(self):
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            with self.assertRaises(ValueError):
                CompassSafariInput(
                    pokemon=safari_pokemon_by_name('metang'),
                    strategy=STRATEGY_ONLY_BALLS, criteria=CRITERIA_CAPTURE,
                    initial_time=TIME_A, key_seed=KEY_SEED,
                    frame_center=2471.0,  # sigma/target_second missing
                )


# ---------------------------------------------------------------------------
# Landing prior + posterior ranking  (b70.2 / b70.4)
# ---------------------------------------------------------------------------

class TestCalibratedPriors(unittest.TestCase):

    M = 5000
    MAX_SECONDS = 30

    def _gen(self, **kwargs):
        from claytonlib.compass import calibrated_candidates
        model = _line_model()
        with patch('claytonlib.times.get_times', side_effect=_fake_get_times), \
             patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput.from_expedition_target(
                model=model, M=self.M, initial_time=TIME_A, key_seed=KEY_SEED,
                max_target_seconds=self.MAX_SECONDS,
                pokemon=safari_pokemon_by_name('metang'),
                strategy=STRATEGY_ONLY_BALLS, criteria=CRITERIA_CAPTURE,
                **kwargs,
            )
            cands, meta = calibrated_candidates(inp)
        return cands, meta, inp

    def test_meta_has_frame_delta_prior_per_seed(self):
        cands, meta, _ = self._gen(second_offsets=(-1, 0, 1))
        for _, seed, frame in cands:
            self.assertIn(seed, meta)
            m = meta[seed]
            self.assertEqual(m["frame"], frame)
            self.assertIn(m["delta"], (-1, 0, 1))
            self.assertGreater(m["prior"], 0.0)

    def test_prior_peaks_at_center_frame_and_delta_zero(self):
        _, meta, inp = self._gen(second_offsets=(-1, 0, 1))
        # the highest-prior seed should be near F* with δ=0
        top = max(meta.values(), key=lambda m: m["prior"])
        self.assertEqual(top["delta"], 0)
        self.assertLessEqual(abs(top["frame"] - inp.frame_center), 1.0)

    def test_delta_zero_prior_exceeds_offset_prior_same_frame(self):
        # At a fixed frame, δ=0 must carry more prior mass than δ=±1.
        _, meta, _ = self._gen(second_offsets=(-1, 0, 1))
        by_frame = {}
        for seed, m in meta.items():
            by_frame.setdefault(m["frame"], {})[m["delta"]] = m["prior"]
        checked = 0
        for frame, byd in by_frame.items():
            if {-1, 0, 1} <= set(byd):
                self.assertGreater(byd[0], byd[1])
                self.assertGreater(byd[0], byd[-1])
                checked += 1
        self.assertGreater(checked, 0)

    def test_posteriors_normalize_to_one(self):
        from claytonlib.compass import posteriors
        cands, meta, _ = self._gen(second_offsets=(-1, 0, 1))
        seeds = [s for _, s, _ in cands]
        post = posteriors(seeds, meta)
        self.assertAlmostEqual(sum(post.values()), 1.0, places=9)

    def test_posteriors_subset_renormalizes(self):
        from claytonlib.compass import posteriors
        cands, meta, _ = self._gen(second_offsets=(-1, 0, 1))
        seeds = [s for _, s, _ in cands][:5]
        post = posteriors(seeds, meta)
        self.assertAlmostEqual(sum(post.values()), 1.0, places=9)
        # a lone survivor has posterior 1.0
        one = posteriors([seeds[0]], meta)
        self.assertAlmostEqual(one[seeds[0]], 1.0, places=9)

    def test_offset_weight_monotonic(self):
        from claytonlib.compass import _offset_weight
        self.assertGreater(_offset_weight(0, 0.6), _offset_weight(1, 0.6))
        self.assertGreater(_offset_weight(1, 0.6), _offset_weight(2, 0.6))
        self.assertEqual(_offset_weight(-1, 0.6), _offset_weight(1, 0.6))

    def test_frame_weight_peaks_at_center(self):
        from claytonlib.compass import _frame_weight
        self.assertGreater(_frame_weight(100, 100.0, 5.0), _frame_weight(103, 100.0, 5.0))
        self.assertEqual(_frame_weight(97, 100.0, 5.0), _frame_weight(103, 100.0, 5.0))

    def test_print_status_calibrated_ranks_and_returns(self):
        from claytonlib.compass import _print_status_calibrated
        cands, meta, inp = self._gen(second_offsets=(-1, 0, 1))
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ranked = _print_status_calibrated(cands, len(cands), round(inp.frame_center),
                                              meta, [], None, CRITERIA_CAPTURE, inp.options)
        out = buf.getvalue()
        self.assertIn("P(land)", out)
        self.assertIn("Most likely", out)
        # returned list is posterior-desc
        posts = [p for _, p, _ in ranked]
        self.assertEqual(posts, sorted(posts, reverse=True))
        self.assertAlmostEqual(sum(posts), 1.0, places=9)


# ---------------------------------------------------------------------------
# Mass-bounded window + prior-weighted Jane offload  (b70.5)
# ---------------------------------------------------------------------------

class TestMassCapAndEffectiveCount(unittest.TestCase):

    M = 5000
    MAX_SECONDS = 30

    def _gen(self, mass_cap=None, **kwargs):
        from claytonlib.compass import calibrated_candidates, CompassOptions
        model = _line_model()
        opts = CompassOptions(mass_cap=mass_cap)
        with patch('claytonlib.times.get_times', side_effect=_fake_get_times), \
             patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput.from_expedition_target(
                model=model, M=self.M, initial_time=TIME_A, key_seed=KEY_SEED,
                max_target_seconds=self.MAX_SECONDS,
                pokemon=safari_pokemon_by_name('metang'),
                strategy=STRATEGY_ONLY_BALLS, criteria=CRITERIA_CAPTURE,
                options=opts, **kwargs)
            cands, meta = calibrated_candidates(inp)
        return cands, meta, inp

    def test_mass_cap_shrinks_set_but_keeps_high_prior(self):
        full, full_meta, _ = self._gen(mass_cap=None, second_offsets=(-1, 0, 1))
        capped, cap_meta, _ = self._gen(mass_cap=0.90, second_offsets=(-1, 0, 1))
        self.assertLess(len(capped), len(full))
        # the highest-prior seed survives the cap
        top = max(full_meta, key=lambda s: full_meta[s]["prior"])
        self.assertIn(top, cap_meta)

    def test_mass_cap_covers_at_least_target_mass(self):
        full, full_meta, _ = self._gen(mass_cap=None, second_offsets=(-1, 0, 1))
        total = sum(m["prior"] for m in full_meta.values())
        _, cap_meta, _ = self._gen(mass_cap=0.90, second_offsets=(-1, 0, 1))
        kept = sum(m["prior"] for m in cap_meta.values())
        self.assertGreaterEqual(kept / total, 0.90)

    def test_mass_cap_none_keeps_full_window(self):
        full, _, _ = self._gen(mass_cap=None, second_offsets=(-1, 0, 1))
        also, _, _ = self._gen(second_offsets=(-1, 0, 1))
        self.assertEqual(len(full), len(also))

    def test_effective_count_small_when_concentrated(self):
        from claytonlib.compass import _effective_count
        _, meta, _ = self._gen(second_offsets=(-1, 0, 1))
        seeds = list(meta)
        eff = _effective_count(seeds, meta, mass=0.99)
        # far fewer than the raw count when the posterior concentrates near F*
        self.assertLess(eff, len(seeds))
        self.assertGreater(eff, 0)

    def test_effective_count_lone_survivor_is_one(self):
        from claytonlib.compass import _effective_count
        _, meta, _ = self._gen(second_offsets=(-1, 0, 1))
        one = next(iter(meta))
        self.assertEqual(_effective_count([one], meta, mass=0.99), 1)


# ---------------------------------------------------------------------------
# Graceful widen + path replay  (b70.6)
# ---------------------------------------------------------------------------

class TestWidenAndReplay(unittest.TestCase):

    M = 5000
    MAX_SECONDS = 30

    def _inp(self, **kwargs):
        model = _line_model()
        with patch('claytonlib.times.get_times', side_effect=_fake_get_times), \
             patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            return CompassSafariInput.from_expedition_target(
                model=model, M=self.M, initial_time=TIME_A, key_seed=KEY_SEED,
                max_target_seconds=self.MAX_SECONDS,
                pokemon=safari_pokemon_by_name('metang'),
                strategy=STRATEGY_ONLY_BALLS, criteria=CRITERIA_CAPTURE, **kwargs)

    def _gen(self, inp):
        from claytonlib.compass import calibrated_candidates
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            return calibrated_candidates(inp)

    def test_replay_reproduces_manual_narrowing(self):
        from claytonlib.compass import _replay_path
        inp = self._inp(second_offsets=(-1, 0, 1))
        cands, _ = self._gen(inp)
        path = [CompassAction(step=SafariStep.BALL_0)]
        manual = _apply_action(cands, path[0], filter_fled=False)
        cache, pending = _replay_path(cands, path)
        current = pending[1] if pending is not None else cache[-1][1]
        self.assertEqual(sorted(s for _, s, _ in current),
                         sorted(s for _, s, _ in manual))

    def test_prompt_widen_both_axes(self):
        from claytonlib.compass import _prompt_widen
        inp = self._inp(second_offsets=(0,), k=3.5)
        with patch('builtins.input', side_effect=['b', '5', '2']):
            wider = _prompt_widen(inp)
        self.assertEqual(wider.k, 5.0)
        self.assertEqual(tuple(wider.second_offsets), (-2, -1, 0, 1, 2))
        # original untouched (dataclasses.replace returns a new object)
        self.assertEqual(inp.k, 3.5)
        self.assertEqual(tuple(inp.second_offsets), (0,))

    def test_prompt_widen_decline_returns_none(self):
        from claytonlib.compass import _prompt_widen
        inp = self._inp(second_offsets=(0,))
        with patch('builtins.input', side_effect=['n']):
            self.assertIsNone(_prompt_widen(inp))

    def test_prompt_widen_no_change_returns_none(self):
        import io, contextlib
        from claytonlib.compass import _prompt_widen
        inp = self._inp(second_offsets=(-1, 0, 1), k=3.5)
        # choose frame, but enter blank → keeps current → no change
        with patch('builtins.input', side_effect=['f', '']), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(_prompt_widen(inp))

    def test_widen_recovers_offset_match_preserving_path(self):
        """A path that empties the δ=0 set is recovered by widening to include the δ=±1 truth,
        with the observed path re-applied to the expanded set."""
        from claytonlib.compass import _replay_path, _prompt_widen
        narrow = self._inp(second_offsets=(0,))
        wide_all, meta_wide = self._gen(self._inp(second_offsets=(-1, 1)))  # δ=±1 only
        cands0, _ = self._gen(narrow)
        pokemon = safari_pokemon_by_name('metang')
        STEP_CHAR = {SafariStep.BALL_0: SafariStep.BALL_0, SafariStep.BALL_1: SafariStep.BALL_1,
                     SafariStep.BALL_2: SafariStep.BALL_2, SafariStep.BALL_3: SafariStep.BALL_3}

        # find a δ=±1 truth whose ball-throw prefix empties the δ=0 set
        found = None
        for _, truth, _ in wide_all:
            ctx = SafariContext.start_encounter(truth, pokemon)
            ctx.balls_remaining = 30
            path = []
            for _ in range(8):
                if not ctx.is_watching():
                    break
                path.append(CompassAction(step=STEP_CHAR[ctx.throw_ball()]))
                cache, pending = _replay_path(cands0, path)
                narrow_now = pending[1] if pending is not None else cache[-1][1]
                if len(narrow_now) == 0:
                    found = (truth, list(path))
                    break
            if found:
                break
        self.assertIsNotNone(found, "expected some δ=±1 truth to empty the δ=0 set")
        truth, path = found

        # widen seconds to ±1 and re-apply the path
        with patch('builtins.input', side_effect=['s', '1']):
            wider = _prompt_widen(narrow)
        self.assertEqual(tuple(wider.second_offsets), (-1, 0, 1))
        cands1, _ = self._gen(wider)
        cache, pending = _replay_path(cands1, path)
        current = pending[1] if pending is not None else cache[-1][1]
        self.assertGreater(len(current), 0)              # match recovered
        self.assertIn(truth, [s for _, s, _ in current])  # the truth is among survivors


# ---------------------------------------------------------------------------
# _apply_action
# ---------------------------------------------------------------------------

class TestApplyAction(unittest.TestCase):

    def setUp(self):
        inp = _make_inputs(window=30)
        with patch('claytonlib.compass._core.get_times', side_effect=_fake_get_times):
            self.candidates = _generate_candidates(inp)
        self.pokemon = safari_pokemon_by_name('metang')

    def _filter(self, step, uncertain=False, filter_fled=False):
        action = CompassAction(step=step, uncertain=uncertain)
        return _apply_action(self.candidates, action, filter_fled=filter_fled)

    def test_filtered_contexts_produce_expected_step(self):
        """Every seed that passes a certain ball filter actually produces that shake count."""
        for target_step in (SafariStep.BALL_0, SafariStep.BALL_1,
                            SafariStep.BALL_2, SafariStep.BALL_3):
            action = CompassAction(step=target_step)
            filtered = _apply_action(self.candidates, action, filter_fled=False)
            for ctx, seed, _ in filtered:
                # Re-simulate from the original seed to verify
                orig = SafariContext.start_encounter(seed, self.pokemon)
                result = orig.throw_ball()
                self.assertEqual(result, target_step)

    def test_uncertain_ball_accepts_all_shake_counts(self):
        uncertain = self._filter(SafariStep.BALL_0, uncertain=True)
        total_certain = sum(
            len(self._filter(s))
            for s in (SafariStep.BALL_0, SafariStep.BALL_1,
                      SafariStep.BALL_2, SafariStep.BALL_3)
        )
        self.assertEqual(len(uncertain), total_certain)

    def test_certain_filters_are_disjoint(self):
        results = [
            set(seed for _, seed, _ in self._filter(s))
            for s in (SafariStep.BALL_0, SafariStep.BALL_1,
                      SafariStep.BALL_2, SafariStep.BALL_3)
        ]
        all_seeds = [s for group in results for s in group]
        self.assertEqual(len(all_seeds), len(set(all_seeds)))

    def test_filter_fled_true_keeps_only_non_fled(self):
        # filter_fled=True means "pokemon didn't flee" — removes fled contexts
        bait = CompassAction(step=SafariStep.BAIT, uncertain=True)
        no_flee = _apply_action(self.candidates, bait, filter_fled=True)
        for ctx, _, _ in no_flee:
            self.assertFalse(ctx.has_fled())

    def test_filter_fled_false_partitions_into_fled_and_non_fled(self):
        # pending (filter_fled=False) = no_flee + fled
        bait = CompassAction(step=SafariStep.BAIT, uncertain=True)
        pending = _apply_action(self.candidates, bait, filter_fled=False)
        no_flee = _apply_action(self.candidates, bait, filter_fled=True)
        fled_only = [c for c, _, _ in pending if c.has_fled()]
        self.assertEqual(len(pending), len(no_flee) + len(fled_only))

    def test_contexts_are_copies(self):
        """Filtering should not mutate the original candidates."""
        original_states = [(copy.copy(ctx), seed, delay)
                           for ctx, seed, delay in self.candidates]
        self._filter(SafariStep.BALL_0)
        for (orig_ctx, _, _), (ctx, _, _) in zip(original_states, self.candidates):
            self.assertEqual(orig_ctx.rng_state, ctx.rng_state)
            self.assertEqual(orig_ctx.turn_count, ctx.turn_count)


# ---------------------------------------------------------------------------
# _evaluate_context
# ---------------------------------------------------------------------------

class TestEvaluateContext(unittest.TestCase):

    def test_returns_bool(self):
        pokemon = safari_pokemon_by_name('metang')
        # Use a seed known from the chart tests to capture on turn 14
        seed = calculate_seed(TIME_A, BASE_DELAY)
        ctx = SafariContext.start_encounter(seed, pokemon)
        result = _evaluate_context(ctx, STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE)
        self.assertIsInstance(result, bool)

    def test_does_not_mutate_context(self):
        pokemon = safari_pokemon_by_name('metang')
        seed = calculate_seed(TIME_A, BASE_DELAY)
        ctx = SafariContext.start_encounter(seed, pokemon)
        rng_before = ctx.rng_state
        _evaluate_context(ctx, STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE)
        self.assertEqual(ctx.rng_state, rng_before)


# ---------------------------------------------------------------------------
# SafariPokemon.name
# ---------------------------------------------------------------------------

class TestSafariPokemonName(unittest.TestCase):

    def test_name_field_set(self):
        pokemon = safari_pokemon_by_name('metang')
        self.assertEqual(pokemon.name, 'metang')

    def test_name_preserved_after_construction(self):
        from claytonlib.safari import SafariPokemon
        p = SafariPokemon('testmon', base_catch_rate=45, base_flee_rate=30)
        self.assertEqual(p.name, 'testmon')


if __name__ == '__main__':
    unittest.main()
