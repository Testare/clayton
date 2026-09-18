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

    def test_setup_max_bound_M_not_battle_second(self):
        # setup/max bound the countdown M (seconds); with a real rtc_offset the battle second is
        # M/1000+offset, so no target M may dip below setup, and battle seconds run above max.
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_c=None,
                                 jitter_rms=8.0, rtc_offset_seconds=5.0)  # 5 s encounter lead
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        cmap = CanonMap({})
        setup, maxt = 180, 200
        ranked = rank_targets(cmap, model, t0, 1000, setup, maxt, step=50)
        self.assertTrue(ranked)
        Ms = [r["M"] for r in ranked]
        self.assertGreaterEqual(min(Ms), setup * 1000)      # never below the setup floor
        self.assertLessEqual(max(Ms), maxt * 1000)
        # battle seconds are M/1000 + 5, so they exceed max (185..205), not clipped to [setup,max]
        self.assertTrue(all(r["second"] >= setup + 5 for r in ranked))

    def test_no_capture_anywhere_all_zero(self):
        model = CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_rms=8.0)
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        cmap = CanonMap({})  # nothing captured
        ranked = rank_targets(cmap, model, t0, 1000, 5, 15, step=2)
        self.assertTrue(ranked)
        self.assertTrue(all(r["p"] == 0.0 for r in ranked))


class TestSecondMarginalization(unittest.TestCase):
    """Capture is marginalized over the RTC-second distribution (σ_S), same frame center."""

    def _model(self, sigma_s):
        # Fb model so frame(M)=0.06*M ignores base; μ = M/1000 (rtc_offset 0).
        return CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_c=None,
                                jitter_rms=8.0, rtc_offset_seconds=0.0, rtc_offset_std=sigma_s)

    def test_sigma_zero_is_single_second(self):
        from claytonlib.chart.scorer import marginal_capture
        model = self._model(0.0)
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        mdmsh20 = mdmsh_of(t0 + dt.timedelta(seconds=20))
        cmap = CanonMap({mdmsh20: [_all_set(1000, 1400)]})
        mc = marginal_capture(cmap, model, t0, 20000, 1000, k=3.5)  # μ=20.0
        self.assertEqual(len(mc["breakdown"]), 1)      # deterministic single second
        self.assertGreater(mc["p"], 0.99)

    def test_split_second_is_penalised(self):
        from claytonlib.chart.scorer import marginal_capture
        model = self._model(0.25)  # μ=20.0 concentrates ~95%; μ=20.5 splits ~48/48
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        # only second 20's mdmsh is captured; second 21's is a different (uncaptured) mdmsh
        mdmsh20 = mdmsh_of(t0 + dt.timedelta(seconds=20))
        cmap = CanonMap({mdmsh20: [_all_set(1000, 1400)]})
        clean = marginal_capture(cmap, model, t0, 20000, 1000, k=3.5)  # μ=20.0 (concentrated)
        split = marginal_capture(cmap, model, t0, 20500, 1000, k=3.5)  # μ=20.5 (split w/ s=21)
        self.assertGreater(clean["p"], 0.9)
        self.assertTrue(0.4 < split["p"] < 0.65)       # ~half its mass leaks to the uncaptured second
        self.assertLess(split["p"], clean["p"])        # the split M is penalised
        self.assertGreaterEqual(len(split["breakdown"]), 2)  # multiple seconds shown
        # same frame center at every second (not recentered per second)
        self.assertEqual({b["F"] for b in split["breakdown"]}, {model.frame(20500, 1000)})

    def test_rank_boot_marginal_orders_by_marginal_p(self):
        from claytonlib.chart.scorer import rank_boot_marginal
        model = self._model(0.3)
        s0 = 20
        F0 = round(model.mean(s0 * 1000))
        t_a = dt.datetime(2000, 6, 1, 14, 0, 0)
        t_b = dt.datetime(2000, 6, 2, 14, 30, 15)
        mdmsh_a = mdmsh_of(t_a + dt.timedelta(seconds=s0))
        cmap = CanonMap({mdmsh_a: [_all_set(F0 - 60, F0 + 60)]})
        rows = rank_boot_marginal(cmap, model, [t_a, t_b], 1000, 5, 40, step=1, k=3.0)
        self.assertTrue(rows)
        self.assertTrue(all(a["p"] >= b["p"] for a, b in zip(rows, rows[1:])))  # sorted desc
        self.assertEqual(len(rows), 2)                 # one row per boot phase
        self.assertEqual(rows[0]["initial_time"], t_a)  # the boot whose second-20 mdmsh is captured


class TestSeedBreakdown(unittest.TestCase):
    """Individual (frame, seed) rows for one candidate second — the per-seed drill-down
    behind Examine target, mirroring the notebook's chart_check_target_landing()."""

    def _model(self, sigma_s=0.0):
        return CalibrationModel(kind="line", beta=0.06, alpha=0.0, jitter_c=None,
                                jitter_rms=8.0, rtc_offset_seconds=0.0, rtc_offset_std=sigma_s)

    def test_unknown_second_returns_none(self):
        from claytonlib.chart.scorer import seed_breakdown
        model = self._model()
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        mdmsh20 = mdmsh_of(t0 + dt.timedelta(seconds=20))
        cmap = CanonMap({mdmsh20: [_all_set(1000, 1400)]})
        result = seed_breakdown(cmap, model, t0, 20000, 1000, second=99, k=3.5)
        self.assertIsNone(result)

    def test_rows_cover_the_full_window_hit_and_weight_are_consistent(self):
        from claytonlib.chart.scorer import seed_breakdown
        from claytonlib.chart.canon import seed_for_mdmsh
        model = self._model()
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        mdmsh20 = mdmsh_of(t0 + dt.timedelta(seconds=20))
        cmap = CanonMap({mdmsh20: [_all_set(1000, 1400)]})  # every frame in [1000,1400] captured
        result = seed_breakdown(cmap, model, t0, 20000, 1000, second=20, k=3.5)
        self.assertIsNotNone(result)
        self.assertEqual(result["second"], 20)
        self.assertFalse(result["truncated"])
        self.assertEqual(result["total_frames"], len(result["rows"]))
        F = result["F"]
        lo, hi = int(F - 3.5 * result["sigma"]), int(F + 3.5 * result["sigma"])
        for row in result["rows"]:
            self.assertTrue(lo <= row["frame"] <= hi + 1)
            self.assertEqual(row["seed"], seed_for_mdmsh(mdmsh20, row["frame"]))
            # Every frame in [1000, 1400] is captured; rows outside that band are not.
            self.assertEqual(row["hit"], 1000 <= row["frame"] <= 1400)
            self.assertEqual(row["delta"], row["frame"] - round(F))
        # weight%/cum_capture% are monotonic-consistent: cum% never exceeds 100 and is
        # non-decreasing as frame increases (each step adds a non-negative weighted hit).
        cums = [row["cum_capture_pct"] for row in result["rows"]]
        self.assertTrue(all(a <= b + 1e-9 for a, b in zip(cums, cums[1:])))
        self.assertLessEqual(cums[-1], 100.0 + 1e-6)
        # the center (delta==0) row exists and carries meaningful weight
        center_rows = [row for row in result["rows"] if row["delta"] == 0]
        self.assertEqual(len(center_rows), 1)
        self.assertGreater(center_rows[0]["weight_pct"], 0)

    def test_max_rows_truncates_but_keeps_exact_totals(self):
        from claytonlib.chart.scorer import seed_breakdown
        model = self._model()
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        mdmsh20 = mdmsh_of(t0 + dt.timedelta(seconds=20))
        cmap = CanonMap({mdmsh20: [_all_set(1000, 1400)]})
        full = seed_breakdown(cmap, model, t0, 20000, 1000, second=20, k=3.5, max_rows=None)
        capped = seed_breakdown(cmap, model, t0, 20000, 1000, second=20, k=3.5, max_rows=10)
        self.assertFalse(full["truncated"])
        self.assertTrue(capped["truncated"])
        self.assertEqual(capped["total_frames"], full["total_frames"])
        self.assertEqual(len(capped["rows"]), 10)
        # the capped window is centered on delta=0
        deltas = [row["delta"] for row in capped["rows"]]
        self.assertIn(0, deltas)
        # cum_capture_pct for a shared frame matches between full and capped (same denominator)
        full_by_frame = {row["frame"]: row["cum_capture_pct"] for row in full["rows"]}
        for row in capped["rows"]:
            self.assertAlmostEqual(row["cum_capture_pct"], full_by_frame[row["frame"]], places=6)


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
