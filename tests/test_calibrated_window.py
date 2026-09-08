"""Tests for chart.CalibratedLandingWindow (the sigma(M) heteroscedastic kernel)."""
import datetime as dt
import math
import unittest

from claytonlib.calibration import CalibrationModel
from claytonlib.chart.evaluation import (
    CalibratedLandingWindow, cumulative_frames,
)


def _spike(n, idx):
    """A success mask that is 1.0 at idx, 0 elsewhere."""
    f = [0.0] * n
    f[idx] = 1.0
    return f


class TestCalibratedLandingWindow(unittest.TestCase):
    def setUp(self):
        # Line model: F_b = 0 + 0.06*M, so delay D maps to M = D/0.06.
        # jitter_c = 0.06 -> sigma(M) = 0.06*sqrt(M) frames.
        self.model = CalibrationModel(kind="line", beta=0.06, alpha=0.0,
                                      jitter_c=0.06, jitter_rms=10.0,
                                      n_fit=10, sxx=1e11, m_bar=300000.0)
        self.base_delay = 0
        self.setup = 0

    def _strat(self, **kw):
        return CalibratedLandingWindow(self.model, self.base_delay, self.setup, **kw)

    def test_score_to_probability_identity_and_bounded(self):
        strat = self._strat()
        n = 4000
        flat = [1.0] * n  # a plateau of guaranteed success
        scored = strat.score(flat)
        # A full plateau should score ~1.0 everywhere in the interior.
        mid = n // 2
        self.assertAlmostEqual(scored[mid], 1.0, places=6)
        self.assertTrue(all(0.0 <= s <= 1.0 + 1e-9 for s in scored))

    def test_kernel_width_grows_with_delay(self):
        # Peak height of a smoothed unit spike ~ 1/(sqrt(2 pi) sigma); a wider kernel at a
        # later (higher-delay -> higher-M) frame yields a LOWER peak.  Compare two spikes.
        strat = self._strat()
        n = 40000
        early, late = 4000, 36000
        peak_early = strat.score(_spike(n, early))[early]
        peak_late = strat.score(_spike(n, late))[late]
        self.assertGreater(peak_early, peak_late)  # tighter kernel early => taller peak

    def test_measured_sigma_matches_model(self):
        # Build a lone spike, smooth it, and recover the kernel sigma from the second moment;
        # it should match model.jitter_sigma(M) at that frame.
        strat = self._strat()
        n = 40000
        idx = 20000
        scored = strat.score(_spike(n, idx))
        # second moment about idx over the whole array
        total = sum(scored)
        var = sum(scored[k] * (k - idx) ** 2 for k in range(n)) / total
        measured = math.sqrt(var)
        M = self.model.solve(idx)  # delay==idx here (base_delay=0, setup=0)
        expected = self.model.jitter_sigma(M)
        # 2-sigma truncation slightly understates the variance; allow ~15%.
        self.assertAlmostEqual(measured / expected, 1.0, delta=0.15)

    def test_sigma_floor_prevents_degenerate_kernel(self):
        strat = self._strat(sigma_floor=0.5)
        # At delay 0, M=0 -> jitter 0, but the floor keeps sigma>=0.5.
        self.assertGreaterEqual(strat._sigma_frames(0.0), 0.5)

    def test_include_calibration_widens_kernel(self):
        base = self._strat(include_calibration=False)
        wide = self._strat(include_calibration=True)
        M = 600000
        self.assertGreater(wide._sigma_frames(M), base._sigma_frames(M))

    def test_setup_offset_shifts_delay_mapping(self):
        # With a nonzero setup, frame i maps to a higher delay (cumulative_frames(setup)+i),
        # hence a larger sigma than the same i at setup=0.
        s0 = CalibratedLandingWindow(self.model, 0, 0)
        s5 = CalibratedLandingWindow(self.model, 0, 300)  # ~300 s of setup => big delay offset
        self.assertGreater(cumulative_frames(300), 0)
        sig0 = s0._sigmas(10)
        sig5 = s5._sigmas(10)
        self.assertGreater(sig5[0], sig0[0])

    def test_filename_stable_and_descriptive(self):
        self.assertEqual(self._strat(sigma_cutoff=2.0).filename,
                         "calibrated_landing_calib_2sig")
        self.assertEqual(self._strat(include_calibration=True, sigma_cutoff=3.0).filename,
                         "calibrated_landing_calibband_3sig")

    def test_evaluate_returns_top_results(self):
        # Small synthetic chain: build links so a couple of frames are successes.
        # Use straighten-compatible packed links: bit 2j=seed_a, 2j+1=seed_b.
        from claytonlib.chart.evaluation import _WIDTH_BIT
        # two 60-frame links, mark frame 30 of link 0 as a success on both a and b
        link0 = (1 << (2 * 30)) | (1 << (2 * 30 + 1))
        link1 = 0
        strat = self._strat()
        results = strat.evaluate([link0, link1], base_delay=0, setup_delay_seconds=0,
                                 initial_time=dt.datetime(2000, 1, 1))
        self.assertTrue(results)
        self.assertLessEqual(len(results), 5)
        # top result should be near frame 30 (the success region)
        self.assertTrue(any(abs(r.delay - 30) <= 5 for r in results))


if __name__ == "__main__":
    unittest.main()
