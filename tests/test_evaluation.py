"""
Unit tests for chart/evaluation.py — straightening, scoring strategies,
and top-result selection.
"""
import datetime as dt
import math
import unittest

from claytonlib.chart.evaluation import (
    MAX_FRAMES_PER_LINK,
    SPF,
    straighten_link,
    straighten_chain,
    _gather_top5,
    _gather_best,
    _build_frame_info,
    cumulative_frames,
    frames_in_second,
    SlidingWindowSum,
    NormalWindow,
)

_BASE_DELAY = 1000
_SETUP = 5
_T0 = dt.datetime(2000, 1, 1, 12, 0, 0)


def _make_tables(n_frames):
    """Build (delays, link_indices) covering n_frames from _SETUP with _BASE_DELAY.

    Uses zero-bitmask links (all 30-frame, since first 29-frame second is s≈11).
    """
    n_links = (n_frames + MAX_FRAMES_PER_LINK - 1) // MAX_FRAMES_PER_LINK
    links = [0] * n_links
    delays, link_indices = _build_frame_info(links, _BASE_DELAY, _SETUP)
    return delays[:n_frames], link_indices[:n_frames]


# ---------------------------------------------------------------------------
# Frame-rate helpers
# ---------------------------------------------------------------------------

class TestFrameRateHelpers(unittest.TestCase):

    def test_frames_in_second_returns_30_for_early_seconds(self):
        # First 29-frame second is around s=11
        for s in range(11):
            self.assertEqual(frames_in_second(s), 30, f"expected 30 at s={s}")

    def test_frames_in_second_returns_29_at_s11(self):
        self.assertEqual(frames_in_second(11), 29)

    def test_sum_of_frames_approximates_fps(self):
        N = 1000
        total = sum(frames_in_second(s) for s in range(N))
        from claytonlib.chart.evaluation import FPS
        self.assertAlmostEqual(total / N, FPS, delta=1.0)


# ---------------------------------------------------------------------------
# straighten_link
# ---------------------------------------------------------------------------

class TestStraightenLink(unittest.TestCase):

    def test_all_zeros(self):
        self.assertEqual(straighten_link(0, 0), [0.0] * MAX_FRAMES_PER_LINK)

    def test_frame0_bit0_full_weight(self):
        # bit 0 set → frame 0, seed A, weight_a = 1.0 (weight_b = SPF*0 = 0)
        result = straighten_link(1, 0)
        self.assertAlmostEqual(result[0], 1.0)
        self.assertEqual(result[1:], [0.0] * (MAX_FRAMES_PER_LINK - 1))

    def test_frame0_bit1_zero_weight(self):
        # bit 1 set → frame 0, seed B, weight_b = SPF*0 = 0.0
        result = straighten_link(2, 0)
        self.assertEqual(result, [0.0] * MAX_FRAMES_PER_LINK)

    def test_frame1_bit0_weight(self):
        # bit 2 set → frame 1, seed A, weight_a = 1 - SPF
        result = straighten_link(4, 0)
        self.assertAlmostEqual(result[1], 1.0 - SPF)
        self.assertEqual(result[0], 0.0)

    def test_frame1_bit1_weight(self):
        # bit 3 set → frame 1, seed B, weight_b = SPF
        result = straighten_link(8, 0)
        self.assertAlmostEqual(result[1], SPF)

    def test_frame1_both_bits_sum_to_one(self):
        # both seeds succeed at frame 1 → weight_a + weight_b = 1.0
        result = straighten_link(4 | 8, 0)
        self.assertAlmostEqual(result[1], 1.0)

    def test_frame29_bit1_full_weight(self):
        # bit 59 set → frame 29, seed B, weight_b = min(1, SPF * 29)
        result = straighten_link(1 << 59, 0)
        self.assertAlmostEqual(result[29], min(1.0, SPF * 29))

    def test_29_frame_link_output_length(self):
        # Bit 62 set → 29-frame link
        result = straighten_link(1 << 62, 0)
        self.assertEqual(len(result), 29)

    def test_30_frame_link_output_length(self):
        # Bit 62 clear → 30-frame link
        result = straighten_link(0, 0)
        self.assertEqual(len(result), MAX_FRAMES_PER_LINK)

    def test_scores_in_range(self):
        # All bits set except bit 62 (30-frame link)
        mask = 0xBFFF_FFFF_FFFF_FFFF
        for score in straighten_link(mask, 0):
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

    def test_nonzero_offset_increases_initial_weight_b(self):
        # At s=5, offset_frames(5) > 0, so frame 0 has non-zero weight_b
        from claytonlib.chart.evaluation import offset_frames
        s = 5
        off = offset_frames(s)
        result = straighten_link(2, s)  # bit 1 = seed_b at frame 0
        expected_wb = min(1.0, SPF * off)
        self.assertAlmostEqual(result[0], expected_wb)


# ---------------------------------------------------------------------------
# straighten_chain
# ---------------------------------------------------------------------------

class TestStraightenChain(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(straighten_chain([], 0), [])

    def test_length(self):
        self.assertEqual(len(straighten_chain([0, 0, 0], 0)), 3 * MAX_FRAMES_PER_LINK)

    def test_concatenation_order(self):
        # First link all-success frame 0, second link zero
        link_a = 1   # bit 0 → frame 0 score 1.0
        link_b = 0
        result = straighten_chain([link_a, link_b], 0)
        self.assertAlmostEqual(result[0], 1.0)
        self.assertEqual(result[MAX_FRAMES_PER_LINK:], [0.0] * MAX_FRAMES_PER_LINK)

    def test_29_frame_link_shorter(self):
        # A single 29-frame link produces 29 entries
        link_29 = 1 << 62  # bit 62 set = 29-frame
        result = straighten_chain([link_29], 0)
        self.assertEqual(len(result), 29)


# ---------------------------------------------------------------------------
# SlidingWindowSum
# ---------------------------------------------------------------------------

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
        self.assertAlmostEqual(result[4], 1.0)
        self.assertAlmostEqual(result[5], 1.0)
        self.assertAlmostEqual(result[6], 1.0)
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


# ---------------------------------------------------------------------------
# NormalWindow
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _gather_top5
# ---------------------------------------------------------------------------

class TestGatherTop5(unittest.TestCase):

    def test_returns_up_to_five(self):
        scored = [1.0] * 10
        delays, link_indices = _make_tables(10)
        results = _gather_top5(scored, delays, link_indices, _T0, _SETUP)
        self.assertEqual(len(results), 5)

    def test_fewer_than_five_frames(self):
        scored = [1.0] * 3
        delays, link_indices = _make_tables(3)
        results = _gather_top5(scored, delays, link_indices, _T0, _SETUP)
        self.assertEqual(len(results), 3)

    def test_sorted_by_score_descending(self):
        scored = [0.1, 0.5, 0.9, 0.3, 0.7] + [0.0] * 25
        delays, link_indices = _make_tables(len(scored))
        results = _gather_top5(scored, delays, link_indices, _T0, _SETUP)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_tie_broken_by_lower_delay(self):
        scored = [0.0] * 30
        scored[5] = 0.8
        scored[10] = 0.8
        delays, link_indices = _make_tables(30)
        results = _gather_top5(scored, delays, link_indices, _T0, _SETUP)
        self.assertLess(results[0].delay, results[1].delay)

    def test_delay_formula(self):
        scored = [0.0] * MAX_FRAMES_PER_LINK
        scored[3] = 1.0  # frame 3, link 0 (second _SETUP)
        delays, link_indices = _make_tables(MAX_FRAMES_PER_LINK)
        results = _gather_top5(scored, delays, link_indices, _T0, _SETUP)
        expected_delay = _BASE_DELAY + 2 * (cumulative_frames(_SETUP) + 3)
        self.assertEqual(results[0].delay, expected_delay)

    def test_time_string_format(self):
        scored = [1.0] + [0.0] * 29
        delays, link_indices = _make_tables(30)
        results = _gather_top5(scored, delays, link_indices, _T0, _SETUP)
        dt.datetime.strptime(results[0].time, "%H:%M:%S")


# ---------------------------------------------------------------------------
# _gather_best
# ---------------------------------------------------------------------------

class TestGatherBest(unittest.TestCase):

    def test_first_result_is_global_best(self):
        scored = [0.0] * 60
        scored[10] = 0.9
        scored[20] = 0.5
        delays, link_indices = _make_tables(60)
        results = _gather_best(scored, delays, link_indices, _T0, _SETUP, n=5)
        self.assertAlmostEqual(results[0].score, 0.9)

    def test_each_result_has_strictly_lower_delay(self):
        scored = [0.0] * 90
        scored[60] = 0.9
        scored[30] = 0.6
        scored[0]  = 0.3
        delays, link_indices = _make_tables(90)
        results = _gather_best(scored, delays, link_indices, _T0, _SETUP, n=5)
        result_delays = [r.delay for r in results]
        self.assertEqual(result_delays, sorted(result_delays, reverse=True))
        for i in range(len(result_delays) - 1):
            self.assertGreater(result_delays[i], result_delays[i + 1])

    def test_skips_zeros(self):
        scored = [0.0] * 60
        scored[5] = 0.7
        delays, link_indices = _make_tables(60)
        results = _gather_best(scored, delays, link_indices, _T0, _SETUP, n=5)
        self.assertEqual(len(results), 1)

    def test_respects_n_limit(self):
        scored = [float(i) / 90 for i in range(90)]
        delays, link_indices = _make_tables(90)
        results = _gather_best(scored, delays, link_indices, _T0, _SETUP, n=3)
        self.assertLessEqual(len(results), 3)

    def test_tie_on_score_prefers_lower_delay(self):
        scored = [0.0] * 60
        scored[10] = 0.8
        scored[20] = 0.8
        delays, link_indices = _make_tables(60)
        results = _gather_best(scored, delays, link_indices, _T0, _SETUP, n=2)
        # First result should be the lower delay (frame 10 < frame 20)
        self.assertLess(results[0].delay, delays[20])


if __name__ == '__main__':
    unittest.main()
