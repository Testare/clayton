"""Tests for chart.grid — the swap-axes capture-grid storage foundation."""
import math
import os
import tempfile
import unittest

from claytonlib.chart.grid import (
    BandPolicy, GridFile, build_header, pack_row, get_bit, iter_set_bits,
    GRID_FORMAT_VERSION,
)
from claytonlib.chart.evaluation import delay_at_second


class TestBandPolicy(unittest.TestCase):
    def test_half_width_grows_as_sqrt(self):
        p = BandPolicy()
        w1 = p.half_width(10000)
        w4 = p.half_width(40000)
        # 4x the frame -> 4x the M -> 2x the half-width (sqrt)
        self.assertAlmostEqual(w4 / w1, 2.0, delta=0.05)

    def test_half_width_monotonic_and_positive(self):
        p = BandPolicy()
        widths = [p.half_width(f) for f in (1000, 5000, 20000, 40000)]
        self.assertTrue(all(b >= a for a, b in zip(widths, widths[1:])))
        self.assertTrue(all(w > 0 for w in widths))

    def test_ceiling_above_measured(self):
        # c_ceiling must sit above the ~0.128 fitted value with margin.
        self.assertGreater(BandPolicy().c_ceiling, 0.128)

    def test_zero_frame_zero_width(self):
        self.assertEqual(BandPolicy().half_width(0), 0)


class TestHeaderGeometry(unittest.TestCase):
    def test_build_header_shape(self):
        h = build_header(base_delay=1000, setup_delay_seconds=5, max_target_seconds=20)
        self.assertEqual(h.format_version, GRID_FORMAT_VERSION)
        self.assertEqual(h.n_seconds, 20 - 5 + 1)
        self.assertEqual(h.row_width_bits, 2 * h.w_max + 1)
        # w_max is the widest band = the last (largest-frame) second's band
        p = h.band_policy()
        self.assertEqual(h.w_max, p.half_width(h.center(h.n_seconds - 1)))

    def test_center_matches_delay_at_second(self):
        h = build_header(base_delay=1000, setup_delay_seconds=5, max_target_seconds=12)
        for r in range(h.n_seconds):
            self.assertEqual(h.center(r), delay_at_second(1000, 5 + r))

    def test_frame_bit_roundtrip(self):
        h = build_header(base_delay=1000, setup_delay_seconds=5, max_target_seconds=30)
        r = 3
        c = h.center(r)
        for frame in (c - h.w_max, c, c + h.w_max):
            bit = h.frame_to_bit(r, frame)
            self.assertIsNotNone(bit)
            self.assertEqual(h.bit_to_frame(r, bit), frame)
        # outside the padded band -> None
        self.assertIsNone(h.frame_to_bit(r, c + h.w_max + 1))
        self.assertIsNone(h.frame_to_bit(r, c - h.w_max - 1))

    def test_eval_half_width_le_w_max(self):
        h = build_header(base_delay=1000, setup_delay_seconds=5, max_target_seconds=30)
        for r in range(h.n_seconds):
            self.assertLessEqual(h.eval_half_width(r), h.w_max)


class TestRowPacking(unittest.TestCase):
    def test_pack_get_iter(self):
        width = 20
        row = pack_row(width, [0, 5, 19])
        self.assertEqual(len(row), (width + 7) // 8)
        self.assertTrue(get_bit(row, 0))
        self.assertTrue(get_bit(row, 5))
        self.assertTrue(get_bit(row, 19))
        self.assertFalse(get_bit(row, 1))
        self.assertEqual(list(iter_set_bits(row, width)), [0, 5, 19])

    def test_pack_ignores_out_of_range(self):
        row = pack_row(8, [3, 99, -1])
        self.assertEqual(list(iter_set_bits(row, 8)), [3])


class TestGridFile(unittest.TestCase):
    def _grid(self):
        d = tempfile.mkdtemp()
        h = build_header(base_delay=1000, setup_delay_seconds=5, max_target_seconds=25)
        g = GridFile(os.path.join(d, "chain.grid"), header=h)
        g.write_header()
        return g

    def test_header_round_trip(self):
        g = self._grid()
        g2 = GridFile(g.path)
        h2 = g2.read_header()
        self.assertEqual(h2.w_max, g.header.w_max)
        self.assertEqual(h2.n_seconds, g.header.n_seconds)
        self.assertEqual(h2.band_policy(), g.header.band_policy())

    def test_append_read_resume(self):
        g = self._grid()
        rb = g.header.row_bytes()
        # write 3 rows, each marking its centre frame captured
        rows = []
        for r in range(3):
            bit = g.header.frame_to_bit(r, g.header.center(r))
            rows.append(pack_row(g.header.row_width_bits, [bit]))
        g.append_rows(rows)
        self.assertEqual(g.rows_written(), 3)

        # reopen fresh -> resume count survives
        g2 = GridFile(g.path)
        g2.read_header()
        self.assertEqual(g2.rows_written(), 3)
        self.assertEqual(len(g2.read_row(1)), rb)
        # captured() reads the centre bit we set, and rejects out-of-band frames
        self.assertTrue(g2.captured(2, g2.header.center(2)))
        self.assertFalse(g2.captured(2, g2.header.center(2) + 1))
        self.assertFalse(g2.captured(2, g2.header.center(2) + g2.header.w_max + 5))

    def test_read_all(self):
        g = self._grid()
        empty = pack_row(g.header.row_width_bits, [])
        g.append_rows([empty, empty])
        self.assertEqual(len(g.read_all()), 2)

    def test_append_rejects_wrong_width(self):
        g = self._grid()
        with self.assertRaises(ValueError):
            g.append_rows([b"\x00"])  # too short


class TestGridGeneration(unittest.TestCase):
    """generate() must fill rows whose bits agree with a direct evaluate_seed check."""

    def _setup(self):
        import datetime as dt
        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE
        mon = safari_pokemon_by_name("metang")
        # small geometry -> small bands -> fast; cheap (non-machete) criterion
        h = build_header(base_delay=1000, setup_delay_seconds=5, max_target_seconds=8)
        d = tempfile.mkdtemp()
        g = GridFile(os.path.join(d, "chain.grid"), header=h)
        g.write_header()
        t0 = dt.datetime(2000, 4, 30, 21, 57, 59)
        return g, t0, mon, STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE

    def test_generate_fills_all_rows(self):
        g, t0, mon, strat, crit = self._setup()
        n = g.generate(t0, mon, strat, crit)
        self.assertEqual(n, g.header.n_seconds)
        self.assertEqual(g.rows_written(), g.header.n_seconds)

    def test_grid_bits_match_direct_evaluation(self):
        import datetime as dt
        from claytonlib.times import calculate_seed
        from claytonlib.chart import evaluate_seed
        g, t0, mon, strat, crit = self._setup()
        g.generate(t0, mon, strat, crit)
        h = g.header
        for r in range(h.n_seconds):
            t = t0 + dt.timedelta(seconds=h.setup_delay_seconds + r)
            w = h.eval_half_width(r)
            c = h.center(r)
            for frame in (c - w, c, c + w):
                expected = evaluate_seed(calculate_seed(t, frame), mon, strat, crit)
                self.assertEqual(g.captured(r, frame), expected,
                                 f"row {r} frame {frame}")

    def test_generation_resumes(self):
        g, t0, mon, strat, crit = self._setup()
        # write only the first 2 rows by faking a partial file, then resume
        h = g.header
        first_two = []
        import datetime as dt
        from claytonlib.times import calculate_seed
        from claytonlib.chart import evaluate_seed
        for r in range(2):
            t = t0 + dt.timedelta(seconds=h.setup_delay_seconds + r)
            w = h.eval_half_width(r)
            c = h.center(r)
            bits = [frame - (c - h.w_max) for frame in range(c - w, c + w + 1)
                    if evaluate_seed(calculate_seed(t, frame), mon, strat, crit)]
            first_two.append(pack_row(h.row_width_bits, bits))
        g.append_rows(first_two)
        self.assertEqual(g.rows_written(), 2)
        # resume fills the rest, and total equals a fresh full generation's bits
        g.generate(t0, mon, strat, crit)
        self.assertEqual(g.rows_written(), h.n_seconds)


if __name__ == "__main__":
    unittest.main()
