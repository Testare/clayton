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
        # put a captured region at second 20's mdmsh, around the frame the model lands there:
        # the RTC second is now M-based (M = s0*1000 since rtc_offset_seconds=0), F0 = mean(M).
        s0 = 20
        F0 = round(model.mean(s0 * 1000))
        mdmsh0 = mdmsh_of(t0 + dt.timedelta(seconds=s0))
        cmap = CanonMap({mdmsh0: [_all_set(F0 - 60, F0 + 60)]})

        ranked = rank_targets(cmap, model, t0, base_delay, setup, maxt, step=1, k=3.0)
        self.assertTrue(ranked)
        best = ranked[0]
        self.assertGreater(best["p"], 0.95)
        self.assertEqual(best["second"], s0)
        self.assertLessEqual(abs(best["F"] - F0), 60)  # within the captured region
        # sorted by p descending
        self.assertTrue(all(a["p"] >= b["p"] for a, b in zip(ranked, ranked[1:])))

    def test_no_capture_anywhere_all_zero(self):
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_rms=8.0)
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        cmap = CanonMap({})  # nothing captured
        ranked = rank_targets(cmap, model, t0, 1000, 5, 15, step=2)
        self.assertTrue(ranked)
        self.assertTrue(all(r["p"] == 0.0 for r in ranked))


class TestRankOverTimes(unittest.TestCase):
    def test_finds_pair_and_valid_boot_time(self):
        from claytonlib.chart.scorer import rank_over_times, best_per_scenario
        base_delay = 1000
        setup, maxt = 5, 40
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0,
                                 jitter_c=None, jitter_rms=8.0)
        s0 = 20
        F0 = round(model.mean(s0 * 1000))  # M-based second: M = s0*1000, F0 = mean(M)
        # two candidate boot times with different phases -> different mdmsh at s0
        t_a = dt.datetime(2000, 6, 1, 14, 0, 0)
        t_b = dt.datetime(2000, 6, 2, 14, 30, 15)
        mdmsh_a = mdmsh_of(t_a + dt.timedelta(seconds=s0))
        cmap = CanonMap({mdmsh_a: [_all_set(F0 - 60, F0 + 60)]})

        ranked = rank_over_times(cmap, model, [t_a, t_b], base_delay, setup, maxt, step=1, k=3.0)
        best = best_per_scenario(ranked)
        top = best[0]
        self.assertGreater(top["p"], 0.95)
        self.assertEqual(top["mdmsh"], mdmsh_a)
        # the attached example boot time really yields that mdmsh at that second
        self.assertEqual(mdmsh_of(top["initial_time"] + dt.timedelta(seconds=top["second"])),
                         top["mdmsh"])

    def test_rank_by_boot_time_one_row_each_best(self):
        from claytonlib.chart.scorer import rank_by_boot_time
        base_delay = 1000
        setup, maxt = 5, 40
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0,
                                 jitter_c=None, jitter_rms=8.0)
        t_a = dt.datetime(2000, 6, 1, 14, 0, 0)   # gets the captured mdmsh at s0
        t_b = dt.datetime(2000, 6, 2, 14, 30, 15)  # different phase, no capture
        s0 = 20
        F0 = round(model.mean(s0 * 1000))  # M-based second: M = s0*1000, F0 = mean(M)
        mdmsh_a = mdmsh_of(t_a + dt.timedelta(seconds=s0))
        cmap = CanonMap({mdmsh_a: [_all_set(F0 - 60, F0 + 60)]})

        rows = rank_by_boot_time(cmap, model, [t_a, t_b], base_delay, setup, maxt, step=1, k=3.0)
        self.assertEqual(len(rows), 2)                    # one row per boot time
        boots = {r["initial_time"] for r in rows}
        self.assertEqual(boots, {t_a, t_b})
        by = {r["initial_time"]: r for r in rows}
        self.assertGreater(by[t_a]["p"], 0.95)            # t_a can reach the captured region
        self.assertEqual(by[t_b]["p"], 0.0)               # t_b never sees a capture
        self.assertEqual(rows[0]["initial_time"], t_a)    # sorted best-first

    def test_string_times_accepted(self):
        from claytonlib.chart.scorer import rank_over_times
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_rms=8.0)
        cmap = CanonMap({})
        ranked = rank_over_times(cmap, model, ["2000-06-01 14:00:00", "2000-06-01T14:00:30"],
                                 1000, 5, 12, step=2)
        self.assertTrue(all(r["p"] == 0.0 for r in ranked))


class TestDistinctTargets(unittest.TestCase):
    def test_collapses_clusters(self):
        ranked = [{"F": 1000, "p": 0.9}, {"F": 1002, "p": 0.89}, {"F": 1300, "p": 0.8},
                  {"F": 1301, "p": 0.79}, {"F": 2000, "p": 0.5}]
        picked = distinct_targets(ranked, min_separation=100, n=3)
        self.assertEqual([r["F"] for r in picked], [1000, 1300, 2000])


if __name__ == "__main__":
    unittest.main()
