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
    CompassSafariInput,
    ParseError,
    UndoAction,
    _action_to_str,
    _apply_action,
    _evaluate_context,
    _generate_candidates,
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
    with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
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
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput(**self._base_kwargs())
        self.assertEqual(inp.target_delay, TARGET_DELAY)

    def test_missing_target_delay_raises(self):
        kw = self._base_kwargs()
        kw['target_delay'] = None
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
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
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
            inp = CompassSafariInput(**kw)
        self.assertEqual(inp.target_seed, expected_seed)

    def test_mismatched_target_seed_raises(self):
        kw = self._base_kwargs()
        kw['target_seed'] = 0xDEADBEEF
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
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
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
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
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
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

    def test_delays_step_by_two(self):
        cands, _ = self._candidates(window=10)
        delays = sorted(set(d for _, _, d in cands))
        for i in range(len(delays) - 1):
            self.assertEqual(delays[i + 1] - delays[i], 2)

    def test_delay_parity_matches_base(self):
        cands, _ = self._candidates(window=10)
        for _, _, d in cands:
            self.assertEqual((d - BASE_DELAY) % 2, 0)

    def test_frame0_delay_has_one_seed(self):
        # A delay where (delay - base) % 60 == 0 → frame_j = 0 → one seed
        frame0_delay = BASE_DELAY + 10 * 60  # exactly frame 0 of second 10
        cands, _ = self._candidates(target_delay=frame0_delay, window=0)
        self.assertEqual(len(cands), 1)

    def test_nonzero_frame_delay_has_two_seeds(self):
        # A delay where frame_j > 0 → two seeds
        frame15_delay = BASE_DELAY + 10 * 60 + 30  # frame 15
        cands, _ = self._candidates(target_delay=frame15_delay, window=0)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0][2], cands[1][2])  # same delay, different seeds

    def test_seeds_are_correct_at_frame0(self):
        frame0_delay = BASE_DELAY + 10 * 60
        cands, _ = self._candidates(target_delay=frame0_delay, window=0)
        _, seed, _ = cands[0]
        second_idx = 10
        time_at = TIME_A + dt.timedelta(seconds=second_idx)
        expected = calculate_seed(time_at, BASE_DELAY + second_idx * 60)
        self.assertEqual(seed, expected)

    def test_starting_ball_count_applied(self):
        from claytonlib.compass import compass_config
        original = compass_config().starting_ball_count
        compass_config().starting_ball_count = 25
        try:
            cands, _ = self._candidates(window=0)
            for ctx, _, _ in cands:
                self.assertEqual(ctx.balls_remaining, 25)
        finally:
            compass_config().starting_ball_count = original

    def test_sorted_by_delay_then_seed(self):
        cands, _ = self._candidates(window=10)
        for i in range(len(cands) - 1):
            d_a, s_a = cands[i][2], cands[i][1]
            d_b, s_b = cands[i + 1][2], cands[i + 1][1]
            self.assertLessEqual((d_a, s_a), (d_b, s_b))


# ---------------------------------------------------------------------------
# _apply_action
# ---------------------------------------------------------------------------

class TestApplyAction(unittest.TestCase):

    def setUp(self):
        inp = _make_inputs(window=30)
        with patch('claytonlib.compass.get_times', side_effect=_fake_get_times):
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
