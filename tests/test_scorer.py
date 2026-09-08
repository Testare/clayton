"""Tests for chart.scorer — Phase 2 ranking of commanded countdowns over the canon map."""
import datetime as dt
import unittest

from claytonlib.calibration import CalibrationModel
from claytonlib.chart.canon import CanonMap, mdmsh_of
from claytonlib.chart.grid import pack_row
from claytonlib.chart.scorer import (
    capture_probability, rank_targets, distinct_targets, _centers,
)


def _all_set(lo, hi):
    return (lo, hi, pack_row(hi - lo + 1, range(hi - lo + 1)))


class TestCenters(unittest.TestCase):
    def test_centers_match_delay_at_second(self):
        from claytonlib.chart.evaluation import delay_at_second
        c = _centers(1000, 20)
        for s in range(21):
            self.assertEqual(c[s], delay_at_second(1000, s))


class TestCaptureProbability(unittest.TestCase):
    def setUp(self):
        # constant sigma=10 (jitter_c None -> jitter_rms); mean(M)=0.06*M
        self.model = CalibrationModel(kind="line", beta=0.06, alpha=0.0,
                                      jitter_c=None, jitter_rms=10.0)
        self.mdmsh = (42, 21)

    def test_full_region_gives_p_near_one(self):
        F = 12000
        cmap = CanonMap({self.mdmsh: [_all_set(F - 200, F + 200)]})
        M = self.model.solve(F)
        cp = capture_probability(cmap, self.model, self.mdmsh, M, k=3.5)
        self.assertGreater(cp["p"], 0.99)

    def test_empty_region_gives_zero(self):
        cmap = CanonMap({self.mdmsh: [(0, 0, b"\x00")]})
        cp = capture_probability(cmap, self.model, self.mdmsh, self.model.solve(12000))
        self.assertEqual(cp["p"], 0.0)

    def test_edge_of_region_between_zero_and_one(self):
        F = 12000
        # captured only for frames >= F (right half) -> ~50% weight at the center
        cmap = CanonMap({self.mdmsh: [_all_set(F, F + 500)]})
        cp = capture_probability(cmap, self.model, self.mdmsh, self.model.solve(F))
        self.assertTrue(0.3 < cp["p"] < 0.7)

    def test_unknown_mdmsh_is_zero(self):
        cmap = CanonMap({self.mdmsh: [_all_set(11000, 13000)]})
        cp = capture_probability(cmap, self.model, (7, 7), self.model.solve(12000))
        self.assertEqual(cp["p"], 0.0)


class TestRankTargets(unittest.TestCase):
    def test_finds_the_captured_target(self):
        base_delay = 1000
        setup, maxt = 5, 40
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0,
                                 jitter_c=None, jitter_rms=8.0)
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        centers = _centers(base_delay, maxt)
        # put a captured region at the mdmsh of second 20, around its centre frame
        s0 = 20
        F0 = centers[s0]
        mdmsh0 = mdmsh_of(t0 + dt.timedelta(seconds=s0))
        cmap = CanonMap({mdmsh0: [_all_set(F0 - 60, F0 + 60)]})

        ranked = rank_targets(cmap, model, t0, base_delay, setup, maxt, step=1, k=3.0)
        self.assertTrue(ranked)
        best = ranked[0]
        self.assertGreater(best["p"], 0.95)
        self.assertEqual(best["second"], s0)
        self.assertLessEqual(abs(best["F"] - F0), 20)
        # sorted by p descending
        self.assertTrue(all(a["p"] >= b["p"] for a, b in zip(ranked, ranked[1:])))

    def test_no_capture_anywhere_all_zero(self):
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_rms=8.0)
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        cmap = CanonMap({})  # nothing captured
        ranked = rank_targets(cmap, model, t0, 1000, 5, 15, step=2)
        self.assertTrue(ranked)
        self.assertTrue(all(r["p"] == 0.0 for r in ranked))


class TestDistinctTargets(unittest.TestCase):
    def test_collapses_clusters(self):
        ranked = [{"F": 1000, "p": 0.9}, {"F": 1002, "p": 0.89}, {"F": 1300, "p": 0.8},
                  {"F": 1301, "p": 0.79}, {"F": 2000, "p": 0.5}]
        picked = distinct_targets(ranked, min_separation=100, n=3)
        self.assertEqual([r["F"] for r in picked], [1000, 1300, 2000])


if __name__ == "__main__":
    unittest.main()
