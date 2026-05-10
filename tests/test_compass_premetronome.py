"""
Unit tests for compass_premetronome.py — move resolution, simulation, and filtering.
"""
import datetime as dt
import unittest
from unittest.mock import patch

from claytonlib.compass_premetronome import (
    CompassPremetronomeInput,
    MetronomeOpponent,
    Move,
    _filter_by_move,
    _generate_metronome_candidates,
    _simulate_metronome,
    resolve_move,
    suggest_moves,
)

# Fixed test parameters shared with compass tests.
KEY_SEED   = 0xF613_087B
BASE_DELAY = KEY_SEED & 0xFFFF   # 2171
TIME_A     = dt.datetime(2000, 4, 30, 19, 57, 59)
TARGET_DELAY = BASE_DELAY + 10 * 60  # 2771


def _fake_get_times(key_seed):
    return key_seed & 0xFFFF, [TIME_A]


def _make_inputs(**kwargs):
    defaults = dict(
        opponent=MetronomeOpponent.MAGIKARP,
        key_seed=KEY_SEED,
        target_delay=TARGET_DELAY,
        initial_time=TIME_A,
        window=4,
    )
    defaults.update(kwargs)
    return CompassPremetronomeInput(**defaults)


def _candidates(**kwargs):
    inp = _make_inputs(**kwargs)
    with patch('claytonlib.compass_premetronome.get_times', side_effect=_fake_get_times):
        return _generate_metronome_candidates(inp), inp


# ---------------------------------------------------------------------------
# resolve_move
# ---------------------------------------------------------------------------

class TestResolveMove(unittest.TestCase):

    def test_exact_match(self):
        m = resolve_move('Flamethrower')
        self.assertIsNotNone(m)
        self.assertEqual(m.name, 'Flamethrower')
        self.assertEqual(m.number, 53)

    def test_case_insensitive(self):
        self.assertEqual(resolve_move('flamethrower'), resolve_move('FLAMETHROWER'))

    def test_leading_trailing_whitespace(self):
        self.assertEqual(resolve_move('  Flamethrower  '), resolve_move('Flamethrower'))

    def test_hyphen_normalised_to_space(self):
        # "Swords-Dance" should resolve the same as "Swords Dance"
        self.assertEqual(resolve_move('Swords-Dance'), resolve_move('Swords Dance'))

    def test_underscore_normalised_to_space(self):
        self.assertEqual(resolve_move('Swords_Dance'), resolve_move('Swords Dance'))

    def test_unknown_returns_none(self):
        self.assertIsNone(resolve_move('Notamove'))

    def test_empty_string_returns_none(self):
        self.assertIsNone(resolve_move(''))

    def test_returns_move_instance(self):
        m = resolve_move('Tackle')
        self.assertIsInstance(m, Move)

    def test_number_is_correct(self):
        m = resolve_move('Tackle')
        self.assertEqual(m.number, 33)

    def test_multi_word_move(self):
        m = resolve_move('Swords Dance')
        self.assertIsNotNone(m)
        self.assertEqual(m.number, 14)


# ---------------------------------------------------------------------------
# suggest_moves
# ---------------------------------------------------------------------------

class TestSuggestMoves(unittest.TestCase):

    def test_returns_list(self):
        self.assertIsInstance(suggest_moves('thunder'), list)

    def test_substring_match(self):
        results = suggest_moves('thunder')
        names = [m.name.lower() for m in results]
        self.assertTrue(all('thunder' in n for n in names))

    def test_limit_respected(self):
        results = suggest_moves('thunder', n=2)
        self.assertLessEqual(len(results), 2)

    def test_no_match_returns_empty(self):
        self.assertEqual(suggest_moves('zzzznotamove'), [])

    def test_default_limit_is_three(self):
        # 'thunder' matches several moves; default should return at most 3
        results = suggest_moves('thunder')
        self.assertLessEqual(len(results), 3)


# ---------------------------------------------------------------------------
# Metronome usability flags
# ---------------------------------------------------------------------------

class TestMetronomeUsability(unittest.TestCase):

    # Disallowed moves must not be usable
    def _assert_disallowed(self, name):
        m = resolve_move(name)
        self.assertIsNotNone(m, f"Move not found: {name}")
        self.assertFalse(m.metronome_usable, f"{name} should be disallowed")

    def _assert_allowed(self, name):
        m = resolve_move(name)
        self.assertIsNotNone(m, f"Move not found: {name}")
        self.assertTrue(m.metronome_usable, f"{name} should be allowed")

    def test_metronome_disallowed(self):      self._assert_disallowed('Metronome')
    def test_struggle_disallowed(self):       self._assert_disallowed('Struggle')
    def test_sketch_disallowed(self):         self._assert_disallowed('Sketch')
    def test_mimic_disallowed(self):          self._assert_disallowed('Mimic')
    def test_chatter_disallowed(self):        self._assert_disallowed('Chatter')
    def test_sleep_talk_disallowed(self):     self._assert_disallowed('Sleep Talk')
    def test_assist_disallowed(self):         self._assert_disallowed('Assist')
    def test_mirror_move_disallowed(self):    self._assert_disallowed('Mirror Move')
    def test_counter_disallowed(self):        self._assert_disallowed('Counter')
    def test_mirror_coat_disallowed(self):    self._assert_disallowed('Mirror Coat')
    def test_protect_disallowed(self):        self._assert_disallowed('Protect')
    def test_detect_disallowed(self):         self._assert_disallowed('Detect')
    def test_endure_disallowed(self):         self._assert_disallowed('Endure')
    def test_destiny_bond_disallowed(self):   self._assert_disallowed('Destiny Bond')
    def test_thief_disallowed(self):          self._assert_disallowed('Thief')
    def test_follow_me_disallowed(self):      self._assert_disallowed('Follow Me')
    def test_snatch_disallowed(self):         self._assert_disallowed('Snatch')
    def test_helping_hand_disallowed(self):   self._assert_disallowed('Helping Hand')
    def test_covet_disallowed(self):          self._assert_disallowed('Covet')
    def test_trick_disallowed(self):          self._assert_disallowed('Trick')
    def test_focus_punch_disallowed(self):    self._assert_disallowed('Focus Punch')
    def test_feint_disallowed(self):          self._assert_disallowed('Feint')
    def test_copycat_disallowed(self):        self._assert_disallowed('Copycat')
    def test_me_first_disallowed(self):       self._assert_disallowed('Me First')
    def test_switcheroo_disallowed(self):     self._assert_disallowed('Switcheroo')

    def test_flamethrower_allowed(self):      self._assert_allowed('Flamethrower')
    def test_tackle_allowed(self):            self._assert_allowed('Tackle')
    def test_shadow_force_allowed(self):      self._assert_allowed('Shadow Force')

    def test_disallowed_count(self):
        from claytonlib.compass_premetronome import _load_moves
        disallowed = [m for m in _load_moves() if not m.metronome_usable]
        self.assertEqual(len(disallowed), 25)

    def test_total_move_count(self):
        from claytonlib.compass_premetronome import _load_moves
        self.assertEqual(len(_load_moves()), 467)


# ---------------------------------------------------------------------------
# _simulate_metronome
# ---------------------------------------------------------------------------

class TestSimulateMetronome(unittest.TestCase):

    # Known fixture: seed 0x12345678 produces Fire Blast (126).
    FIXTURE_SEED = 0x12345678
    FIXTURE_MOVE = 126  # Fire Blast

    def test_known_seed_produces_known_move(self):
        self.assertEqual(_simulate_metronome(self.FIXTURE_SEED), self.FIXTURE_MOVE)

    def test_result_is_deterministic(self):
        self.assertEqual(
            _simulate_metronome(self.FIXTURE_SEED),
            _simulate_metronome(self.FIXTURE_SEED),
        )

    def test_result_is_usable_move(self):
        from claytonlib.compass_premetronome import _moves_by_number
        move_num = _simulate_metronome(self.FIXTURE_SEED)
        move = _moves_by_number()[move_num]
        self.assertTrue(move.metronome_usable)

    def test_result_in_valid_range(self):
        move_num = _simulate_metronome(self.FIXTURE_SEED)
        self.assertGreaterEqual(move_num, 1)
        self.assertLessEqual(move_num, 467)

    def test_different_seeds_may_differ(self):
        # Not guaranteed to differ, but with two well-separated seeds they should.
        a = _simulate_metronome(0x00000001)
        b = _simulate_metronome(0xDEADBEEF)
        # We just verify both are valid; coincidental equality is allowed.
        self.assertGreaterEqual(a, 1)
        self.assertGreaterEqual(b, 1)

    def test_result_never_disallowed(self):
        from claytonlib.compass_premetronome import _moves_by_number
        by_num = _moves_by_number()
        # Sample a spread of seeds
        for seed in [0x00000000, 0x12345678, 0xDEADBEEF, 0xFFFFFFFF, 0xABCD1234]:
            num = _simulate_metronome(seed)
            self.assertTrue(by_num[num].metronome_usable,
                            f"seed 0x{seed:08X} produced disallowed move {by_num[num].name}")


# ---------------------------------------------------------------------------
# _generate_metronome_candidates
# ---------------------------------------------------------------------------

class TestGenerateMetronomeCandidates(unittest.TestCase):

    def test_no_duplicate_seeds(self):
        cands, _ = _candidates(window=10)
        seeds = [s for s, _ in cands]
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_delays_in_window(self):
        window = 10
        cands, inp = _candidates(window=window)
        for _, d in cands:
            self.assertGreaterEqual(d, inp.target_delay - window)
            self.assertLessEqual(d, inp.target_delay + window)

    def test_delays_step_by_one(self):
        cands, _ = _candidates(window=10)
        delays = sorted(set(d for _, d in cands))
        for i in range(len(delays) - 1):
            self.assertEqual(delays[i + 1] - delays[i], 1)

    def test_frame0_delay_has_two_seeds(self):
        frame0_delay = BASE_DELAY + 10 * 60
        cands, _ = _candidates(target_delay=frame0_delay, window=0)
        self.assertEqual(len(cands), 2)

    def test_nonzero_frame_delay_has_two_seeds(self):
        frame15_delay = BASE_DELAY + 10 * 60 + 30
        cands, _ = _candidates(target_delay=frame15_delay, window=0)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0][1], cands[1][1])  # same delay, different seeds

    def test_sorted_by_delay_then_seed(self):
        cands, _ = _candidates(window=10)
        for i in range(len(cands) - 1):
            self.assertLessEqual((cands[i][1], cands[i][0]),
                                 (cands[i + 1][1], cands[i + 1][0]))

    def test_returns_tuples_of_seed_and_delay(self):
        cands, _ = _candidates(window=0)
        for item in cands:
            self.assertEqual(len(item), 2)
            seed, delay = item
            self.assertIsInstance(seed, int)
            self.assertIsInstance(delay, int)

    # second_window tests

    def test_second_window_zero_default(self):
        inp = _make_inputs(window=0)
        self.assertEqual(inp.second_window, 0)

    def test_second_window_increases_candidate_count(self):
        base_cands, _ = _candidates(window=4, second_window=0)
        wider_cands, _ = _candidates(window=4, second_window=2)
        self.assertGreater(len(wider_cands), len(base_cands))

    def test_second_window_no_duplicates(self):
        cands, _ = _candidates(window=4, second_window=2)
        seeds = [s for s, _ in cands]
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_second_window_base_seeds_included(self):
        # All seeds from window=0/second_window=0 are present in a wider window
        base_cands, _ = _candidates(window=4, second_window=0)
        wider_cands, _ = _candidates(window=4, second_window=2)
        base_seeds = {s for s, _ in base_cands}
        wider_seeds = {s for s, _ in wider_cands}
        self.assertTrue(base_seeds.issubset(wider_seeds))

    def test_second_window_sorted_by_delay_then_seed(self):
        cands, _ = _candidates(window=4, second_window=2)
        for i in range(len(cands) - 1):
            self.assertLessEqual((cands[i][1], cands[i][0]),
                                 (cands[i + 1][1], cands[i + 1][0]))


# ---------------------------------------------------------------------------
# _filter_by_move
# ---------------------------------------------------------------------------

class TestFilterByMove(unittest.TestCase):

    def setUp(self):
        self.cands, _ = _candidates(window=30)

    def test_filtered_seeds_produce_target_move(self):
        # Pick the move produced by the first candidate and verify filtering.
        first_seed = self.cands[0][0]
        target_move = _simulate_metronome(first_seed)
        filtered = _filter_by_move(self.cands, target_move)
        for seed, _ in filtered:
            self.assertEqual(_simulate_metronome(seed), target_move)

    def test_nonexistent_move_returns_empty(self):
        # Move number 0 is MOVE_NONE and never produced by the simulation.
        filtered = _filter_by_move(self.cands, 0)
        self.assertEqual(filtered, [])

    def test_filter_is_subset_of_input(self):
        target_move = _simulate_metronome(self.cands[0][0])
        filtered = _filter_by_move(self.cands, target_move)
        filtered_seeds = {s for s, _ in filtered}
        all_seeds = {s for s, _ in self.cands}
        self.assertTrue(filtered_seeds.issubset(all_seeds))

    def test_disjoint_move_filters_partition_candidates(self):
        # Each candidate belongs to exactly one move bucket.
        buckets: dict[int, list] = {}
        for seed, delay in self.cands:
            m = _simulate_metronome(seed)
            buckets.setdefault(m, []).append((seed, delay))
        for move_num, bucket in buckets.items():
            filtered = _filter_by_move(self.cands, move_num)
            self.assertEqual(sorted(filtered), sorted(bucket))

    def test_original_candidates_not_mutated(self):
        original = list(self.cands)
        target_move = _simulate_metronome(self.cands[0][0])
        _filter_by_move(self.cands, target_move)
        self.assertEqual(self.cands, original)


if __name__ == '__main__':
    unittest.main()
