"""
Unit tests for chart/evaluation.py — straightening, scoring strategies,
and top-result selection.
"""
import datetime as dt
import math
import unittest

from claytonlib.chart.evaluation import (
    FRAMES_PER_LINK,
    straighten_link,
    straighten_chain,
    _gather_top5,
    _gather_best,
    _make_top_result,
    SlidingWindowSum,
    NormalWindow,
)

_BASE_DELAY = 1000
_SETUP = 5
_T0 = dt.datetime(2000, 1, 1, 12, 0, 0)


class TestStraightenLink(unittest.TestCase):

    def test_all_zeros(self):
        self.assertEqual(straighten_link(0), [0.0] * FRAMES_PER_LINK)

    def test_frame0_bit0_full_weight(self):
        # bit 0 set → frame 0, seed A, weight (30-0)/30 = 1.0
        result = straighten_link(1)
        self.assertAlmostEqual(result[0], 1.0)
        self.assertEqual(result[1:], [0.0] * (FRAMES_PER_LINK - 1))

    def test_frame0_bit1_zero_weight(self):
        # bit 1 set → frame 0, seed B, weight 0/30 = 0.0
        result = straighten_link(2)
        self.assertEqual(result, [0.0] * FRAMES_PER_LINK)

    def test_frame1_bit0_weight(self):
        # bit 2 set → frame 1, seed A, weight (30-1)/30 = 29/30
        result = straighten_link(4)
        self.assertAlmostEqual(result[1], 29 / 30)
        self.assertEqual(result[0], 0.0)

    def test_frame1_bit1_weight(self):
        # bit 3 set → frame 1, seed B, weight 1/30
        result = straighten_link(8)
        self.assertAlmostEqual(result[1], 1 / 30)

    def test_frame1_both_bits_sum_to_one(self):
        # both seeds succeed at frame 1 → 29/30 + 1/30 = 1.0
        result = straighten_link(4 | 8)
        self.assertAlmostEqual(result[1], 1.0)

    def test_frame29_bit1_full_weight(self):
        # bit 59 set → frame 29, seed B, weight 29/30
        result = straighten_link(1 << 59)
        self.assertAlmostEqual(result[29], 29 / 30)

    def test_output_length(self):
        self.assertEqual(len(straighten_link(0xFFFF_FFFF_FFFF_FFFF)), FRAMES_PER_LINK)

    def test_scores_in_range(self):
        for score in straighten_link(0xFFFF_FFFF_FFFF_FFFF):
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class TestStraightenChain(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(straighten_chain([]), [])

    def test_length(self):
        self.assertEqual(len(straighten_chain([0, 0, 0])), 3 * FRAMES_PER_LINK)

    def test_concatenation_order(self):
        # First link all-success frame 0, second link zero
        link_a = 1   # bit 0 → frame 0 score 1.0
        link_b = 0
        result = straighten_chain([link_a, link_b])
        self.assertAlmostEqual(result[0], 1.0)
        self.assertEqual(result[FRAMES_PER_LINK:], [0.0] * FRAMES_PER_LINK)


class TestSlidingWindowSum(unittest.TestCase):

    def test_even_window_raises(self):
        with self.assertRaises(ValueError):
            SlidingWindowSum(window=4)

    def test_edges_are_zero(self):
        s = SlidingWindowSum(window=3)
        flat = [1.0] * 10
        result = s.score(flat)
        self.assertEqual(result[0], 0.0)
        self.assertEqual(result[-1], 0.0)

    def test_uniform_flat_interior(self):
        s = SlidingWindowSum(window=3)
        flat = [1.0] * 10
        result = s.score(flat)
        for v in result[1:-1]:
            self.assertAlmostEqual(v, 3.0)

    def test_single_spike(self):
        s = SlidingWindowSum(window=3)
        flat = [0.0] * 10
        flat[5] = 1.0
        result = s.score(flat)
        # frames 4, 5, 6 should each have score 1.0
        self.assertAlmostEqual(result[4], 1.0)
        self.assertAlmostEqual(result[5], 1.0)
        self.assertAlmostEqual(result[6], 1.0)
        # frame 3 and 7 should be 0 (spike not in their window)
        self.assertAlmostEqual(result[3], 0.0)
        self.assertAlmostEqual(result[7], 0.0)

    def test_too_short_flat(self):
        s = SlidingWindowSum(window=5)
        result = s.score([1.0] * 4)
        self.assertEqual(result, [0.0] * 4)

    def test_score_to_probability(self):
        s = SlidingWindowSum(window=7)
        self.assertAlmostEqual(s.score_to_probability(7.0), 1.0)
        self.assertAlmostEqual(s.score_to_probability(3.5), 0.5)

    def test_filename(self):
        self.assertEqual(SlidingWindowSum(window=13).filename, "sliding_window_13")


class TestNormalWindow(unittest.TestCase):

    def test_low_sigma_raises(self):
        with self.assertRaises(ValueError):
            NormalWindow(sigma_frames=0.5)

    def test_edges_are_zero(self):
        s = NormalWindow(sigma_frames=2.0)
        flat = [1.0] * 20
        result = s.score(flat)
        self.assertEqual(result[0], 0.0)
        self.assertEqual(result[-1], 0.0)

    def test_weights_sum_to_one_at_interior(self):
        # For a flat-ones input, score at any interior frame = sum of weights = 1.0
        s = NormalWindow(sigma_frames=3.0)
        flat = [1.0] * 40
        result = s.score(flat)
        for v in result[s._hw: len(flat) - s._hw]:
            self.assertAlmostEqual(v, 1.0, places=10)

    def test_scores_in_range(self):
        s = NormalWindow(sigma_frames=2.0)
        flat = [0.5] * 20
        for v in s.score(flat):
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.0)

    def test_symmetry(self):
        s = NormalWindow(sigma_frames=2.0)
        flat = [0.0] * 30
        flat[15] = 1.0
        result = s.score(flat)
        hw = s._hw
        for k in range(1, hw + 1):
            self.assertAlmostEqual(result[15 - k], result[15 + k])

    def test_score_to_probability_identity(self):
        s = NormalWindow(sigma_frames=2.0)
        self.assertAlmostEqual(s.score_to_probability(0.75), 0.75)

    def test_filename_integer(self):
        self.assertEqual(NormalWindow(sigma_frames=12.0).filename, "normal_12")

    def test_filename_float(self):
        self.assertEqual(NormalWindow(sigma_frames=8.5).filename, "normal_8.5")


class TestGatherTop5(unittest.TestCase):

    def _make_scored(self, n, hot_indices):
        scored = [0.0] * n
        for i, v in hot_indices:
            scored[i] = v
        return scored

    def test_returns_up_to_five(self):
        scored = [1.0] * 10
        results = _gather_top5(scored, _BASE_DELAY, _SETUP, _T0)
        self.assertEqual(len(results), 5)

    def test_fewer_than_five_frames(self):
        scored = [1.0] * 3
        results = _gather_top5(scored, _BASE_DELAY, _SETUP, _T0)
        self.assertEqual(len(results), 3)

    def test_sorted_by_score_descending(self):
        scored = [0.1, 0.5, 0.9, 0.3, 0.7] + [0.0] * 25
        results = _gather_top5(scored, _BASE_DELAY, _SETUP, _T0)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_tie_broken_by_lower_delay(self):
        # Two frames with same score; lower index (lower delay) should appear first
        scored = [0.0] * 30
        scored[5] = 0.8
        scored[10] = 0.8
        results = _gather_top5(scored, _BASE_DELAY, _SETUP, _T0)
        self.assertLess(results[0].delay, results[1].delay)

    def test_delay_formula(self):
        scored = [0.0] * FRAMES_PER_LINK
        scored[3] = 1.0  # frame 3, link 0
        results = _gather_top5(scored, _BASE_DELAY, _SETUP, _T0)
        expected_delay = _BASE_DELAY + (_SETUP + 0) * 60 + 3 * 2
        self.assertEqual(results[0].delay, expected_delay)

    def test_time_string_format(self):
        scored = [1.0] + [0.0] * 29
        results = _gather_top5(scored, _BASE_DELAY, _SETUP, _T0)
        # Should be parseable as HH:MM:SS
        dt.datetime.strptime(results[0].time, "%H:%M:%S")


class TestGatherBest(unittest.TestCase):

    def test_first_result_is_global_best(self):
        scored = [0.0] * 60
        scored[10] = 0.9
        scored[20] = 0.5
        results = _gather_best(scored, _BASE_DELAY, _SETUP, _T0, n=5)
        self.assertAlmostEqual(results[0].score, 0.9)

    def test_each_result_has_strictly_lower_delay(self):
        scored = [0.0] * 90
        scored[60] = 0.9  # high score, high delay (link 2, frame 0)
        scored[30] = 0.6  # medium score, medium delay (link 1, frame 0)
        scored[0]  = 0.3  # lower score, low delay (link 0, frame 0)
        results = _gather_best(scored, _BASE_DELAY, _SETUP, _T0, n=5)
        delays = [r.delay for r in results]
        self.assertEqual(delays, sorted(delays, reverse=True))
        for i in range(len(delays) - 1):
            self.assertGreater(delays[i], delays[i + 1])

    def test_skips_zeros(self):
        scored = [0.0] * 60
        scored[5] = 0.7
        results = _gather_best(scored, _BASE_DELAY, _SETUP, _T0, n=5)
        self.assertEqual(len(results), 1)

    def test_respects_n_limit(self):
        scored = [float(i) / 90 for i in range(90)]
        results = _gather_best(scored, _BASE_DELAY, _SETUP, _T0, n=3)
        self.assertLessEqual(len(results), 3)

    def test_tie_on_score_prefers_lower_delay(self):
        # Two frames with same score; best should pick lower delay to maximise
        # room for subsequent results
        scored = [0.0] * 60
        scored[10] = 0.8
        scored[20] = 0.8
        results = _gather_best(scored, _BASE_DELAY, _SETUP, _T0, n=2)
        # First result should be the one with lower delay (more room after it)
        self.assertLess(results[0].delay,
                        _BASE_DELAY + (_SETUP + 0) * 60 + 20 * 2 + 1)


if __name__ == '__main__':
    unittest.main()
