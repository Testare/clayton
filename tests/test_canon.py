"""Tests for chart.canon — the mdmsh-keyed canonical capture map (Phase 1)."""
import datetime as dt
import os
import tempfile
import unittest

from claytonlib.calibration import CalibrationModel
from claytonlib.chart.canon import (
    mdmsh_of, seed_for_mdmsh, needed_ranges, SeedCache, build_canon, _merge_intervals,
)
from claytonlib.chart.grid import BandPolicy
from claytonlib.times import calculate_seed

# A line calibration whose mean(M) ~ base_delay + s*60 for M ~ s*1000 (so the frame bands land
# near the old delay_at_second centers used by these fixtures).  rtc_offset_seconds=0 => RTC second
# is exactly M/1000 from the initial seed.
MODEL = CalibrationModel(kind="line", beta=0.06, alpha=1000.0, jitter_c=0.128, rtc_offset_seconds=0.0)


class TestMdmsh(unittest.TestCase):
    def test_mdmsh_of(self):
        t = dt.datetime(2000, 9, 18, 21, 32, 42)
        self.assertEqual(mdmsh_of(t), ((9 * 18 + 32 + 42) & 0xFF, 21))

    def test_seed_matches_calculate_seed(self):
        t = dt.datetime(2000, 5, 31, 21, 58, 23)
        for frame in (0, 100, 25298, 60000):
            self.assertEqual(seed_for_mdmsh(mdmsh_of(t), frame), calculate_seed(t, frame))

    def test_merge_intervals(self):
        self.assertEqual(_merge_intervals([(0, 5), (6, 10), (20, 25)]), [(0, 10), (20, 25)])
        self.assertEqual(_merge_intervals([(0, 5), (3, 8)]), [(0, 8)])


class TestNeededRanges(unittest.TestCase):
    def test_stats_and_collapse(self):
        # a handful of RNG-equivalent times (same mdms sum + hour) collapse to few seeds
        times = [dt.datetime(2000, 9, 18, 21, 32, 42),
                 dt.datetime(2000, 9, 21, 21, 6, 41),   # different date, may share mdmsh at s
                 dt.datetime(2000, 9, 18, 21, 32, 42)]  # exact dup -> deduped by phase
        ranges, stats = needed_ranges(1000, times, 5, 20, MODEL)
        self.assertEqual(stats["n_candidate_times"], 3)
        self.assertLessEqual(stats["n_phase_classes"], 2)  # the exact dup collapses
        self.assertGreater(stats["n_distinct_seeds"], 0)
        self.assertGreaterEqual(stats["reuse_factor"], 1.0)

    def test_ranges_cover_expected_frames(self):
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        policy = BandPolicy()
        ranges, _ = needed_ranges(1000, times, 5, 8, MODEL, policy)
        # every listed range is within some second's band and non-empty
        for mdmsh, rs in ranges.items():
            for lo, hi in rs:
                self.assertLessEqual(lo, hi)


class TestSeedCache(unittest.TestCase):
    def test_memo_and_persist(self):
        calls = []
        fn = lambda s: (calls.append(s), s % 2 == 0)[1]
        path = os.path.join(tempfile.mkdtemp(), "cache.json")
        c = SeedCache(path)
        self.assertTrue(c.get_or_eval(4, fn))
        self.assertFalse(c.get_or_eval(5, fn))
        self.assertTrue(c.get_or_eval(4, fn))  # hit, no new call
        self.assertEqual(len(calls), 2)
        self.assertEqual((c.hits, c.misses), (1, 2))
        c.save()
        # reload -> all hits, fn never called again
        calls.clear()
        c2 = SeedCache(path)
        self.assertTrue(c2.get_or_eval(4, fn))
        self.assertFalse(c2.get_or_eval(5, fn))
        self.assertEqual(calls, [])
        self.assertEqual(c2.misses, 0)


class TestBuildCanon(unittest.TestCase):
    def _cfg(self):
        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE
        return safari_pokemon_by_name("metang"), STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE

    def test_canon_bits_match_direct_evaluation(self):
        from claytonlib.chart import evaluate_seed
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0), dt.datetime(2000, 6, 2, 21, 0, 30)]
        ranges, _ = needed_ranges(1000, times, 5, 8, MODEL)
        cmap, cache = build_canon(ranges, mon, strat, crit)
        checked = 0
        for mdmsh, rs in ranges.items():
            for lo, hi in rs:
                for frame in (lo, (lo + hi) // 2, hi):
                    expected = evaluate_seed(seed_for_mdmsh(mdmsh, frame), mon, strat, crit)
                    self.assertEqual(cmap.captured(mdmsh, frame), expected)
                    checked += 1
        self.assertGreater(checked, 0)

    def test_out_of_range_is_false(self):
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        ranges, _ = needed_ranges(1000, times, 5, 8, MODEL)
        cmap, _ = build_canon(ranges, mon, strat, crit)
        some = next(iter(ranges))
        self.assertFalse(cmap.captured(some, -999999))
        self.assertFalse(cmap.captured((123, 7), 25298))  # unseen mdmsh

    def test_cache_reuse_second_build_all_hits(self):
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        ranges, _ = needed_ranges(1000, times, 5, 8, MODEL)
        cache = SeedCache()
        build_canon(ranges, mon, strat, crit, cache=cache)
        first_misses = cache.misses
        self.assertGreater(first_misses, 0)
        # rebuild with the warm cache -> no new evaluations
        cache.hits = cache.misses = 0
        build_canon(ranges, mon, strat, crit, cache=cache)
        self.assertEqual(cache.misses, 0)
        self.assertGreater(cache.hits, 0)


class TestCanonMapSerialization(unittest.TestCase):
    def test_save_load_round_trip(self):
        from claytonlib.chart import CanonMap, build_canon
        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE
        mon = safari_pokemon_by_name("metang")
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        ranges, _ = needed_ranges(1000, times, 5, 8, MODEL)
        cmap, _ = build_canon(ranges, mon, STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE)
        path = os.path.join(tempfile.mkdtemp(), "canon.jsonl")
        cmap.save(path)
        reloaded = CanonMap.load(path)
        self.assertEqual(reloaded.ranges, cmap.ranges)


class TestPrecomputeCanon(unittest.TestCase):
    def _cfg(self):
        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE
        return safari_pokemon_by_name("metang"), STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE

    def _store(self):
        from claytonlib.chart import CanonStore
        return CanonStore(os.path.join(tempfile.mkdtemp(), "canon.jsonl"))

    def test_precompute_matches_in_memory_build(self):
        from claytonlib.chart import precompute_canon, build_canon
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0), dt.datetime(2000, 6, 2, 21, 0, 30)]
        ranges, _ = needed_ranges(1000, times, 5, 9, MODEL)
        expected, _ = build_canon(ranges, mon, strat, crit)
        store = self._store()
        stats = precompute_canon(1000, times, 5, 9, mon, strat, crit, store, MODEL)
        self.assertGreater(stats["n_distinct_seeds"], 0)
        got = store.load_map()
        self.assertEqual(got.ranges, expected.ranges)
        meta = store.read_meta()
        self.assertEqual(meta["n_mdmsh"], len(ranges))
        self.assertEqual(stats["evaluated_this_run"], stats["n_distinct_seeds"])

    def test_union_over_modelset_covers_both_and_records_built_models(self):
        # precompute over a {key: model} dict must cover the UNION of both models' needed frames
        # and record which fps_model keys the store was built for (the switch guard).
        from claytonlib.chart import precompute_canon
        from claytonlib.chart.canon import _merge_intervals
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        # a second model whose frames sit ABOVE MODEL's (higher intercept) so the union is wider
        hi_model = CalibrationModel(kind="line", beta=0.06, alpha=1400.0, jitter_c=0.128,
                                    rtc_offset_seconds=0.0)
        r_lin, _ = needed_ranges(1000, times, 5, 12, MODEL)
        r_hi, _ = needed_ranges(1000, times, 5, 12, hi_model)
        store = self._store()
        precompute_canon(1000, times, 5, 12, mon, strat, crit, store,
                         {"linear": MODEL, "quad": hi_model})
        self.assertEqual(store.read_meta().get("built_models"), ["linear", "quad"])
        cov = store.done_coverage()
        # every frame either model needs is stored (union coverage)
        for src in (r_lin, r_hi):
            for mdmsh, rs in src.items():
                for lo, hi in rs:
                    for f in (lo, (lo + hi) // 2, hi):
                        self.assertTrue(any(a <= f <= b for a, b in cov.get(mdmsh, [])),
                                        f"{mdmsh} frame {f} not covered by union")

    def test_resume_skips_done_and_completes(self):
        from claytonlib.chart import precompute_canon, build_canon
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        ranges, _ = needed_ranges(1000, times, 5, 12, MODEL)
        expected, _ = build_canon(ranges, mon, strat, crit)
        store = self._store()

        # Interrupt after the first mdmsh: stop the progress callback with an exception.
        class Stop(Exception):
            pass

        def stop_after_one(done, total, stats):
            if done >= 1:
                raise Stop
        with self.assertRaises(Stop):
            precompute_canon(1000, times, 5, 12, mon, strat, crit, store, MODEL, progress=stop_after_one)
        partial = len(store.done_mdmsh())
        self.assertGreaterEqual(partial, 1)
        self.assertLess(partial, len(ranges))  # not finished

        # Resume: completes without redoing the done mdmsh.
        precompute_canon(1000, times, 5, 12, mon, strat, crit, store, MODEL)
        self.assertEqual(len(store.done_mdmsh()), len(ranges))
        self.assertEqual(store.load_map().ranges, expected.ranges)

    def test_parallel_matches_sequential(self):
        import multiprocessing as mp
        from claytonlib.chart import precompute_canon, build_canon
        if "fork" not in mp.get_all_start_methods():
            self.skipTest("fork start method unavailable")
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        ranges, _ = needed_ranges(1000, times, 5, 10, MODEL)
        expected, _ = build_canon(ranges, mon, strat, crit)
        store = self._store()
        precompute_canon(1000, times, 5, 10, mon, strat, crit, store, MODEL, workers=2)
        got = store.load_map()
        for mdmsh, built in expected.ranges.items():
            for lo, hi, _bm in built:
                for f in range(lo, hi + 1):
                    self.assertEqual(got.captured(mdmsh, f), expected.captured(mdmsh, f))

    def test_config_mismatch_refused(self):
        from claytonlib.chart import precompute_canon
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0)]
        store = self._store()
        precompute_canon(1000, times, 5, 8, mon, strat, crit, store, MODEL)
        # different base_delay -> different signature -> refuse (setup/max are NOT in the sig)
        with self.assertRaises(ValueError):
            precompute_canon(2000, times, 5, 8, mon, strat, crit, store, MODEL)

    def test_incremental_extend(self):
        from claytonlib.chart import precompute_canon, build_canon
        mon, strat, crit = self._cfg()
        times = [dt.datetime(2000, 6, 1, 21, 0, 0), dt.datetime(2000, 6, 2, 21, 0, 30)]
        store = self._store()

        # 1) precompute the narrow range [5, 9]
        s_small = precompute_canon(1000, times, 5, 9, mon, strat, crit, store, MODEL)
        # 2) extend to [5, 18] on the SAME store (allowed: setup/max not in signature)
        s_big = precompute_canon(1000, times, 5, 18, mon, strat, crit, store, MODEL)

        # the extend only evaluated the new frames, not the ones already stored
        self.assertGreater(s_big["evaluated_this_run"], 0)
        self.assertLess(s_big["evaluated_this_run"], s_big["n_distinct_seeds"])
        self.assertEqual(s_small["evaluated_this_run"] + s_big["evaluated_this_run"],
                         s_big["n_distinct_seeds"])

        # the resulting store matches a direct one-shot [5, 18] build, frame-by-frame
        # (range partitioning legitimately differs: extend appends gap ranges separately)
        ranges_big, _ = needed_ranges(1000, times, 5, 18, MODEL)
        expected, _ = build_canon(ranges_big, mon, strat, crit)
        got = store.load_map()
        self.assertEqual(set(got.ranges), set(expected.ranges))
        for mdmsh, built in expected.ranges.items():
            for lo, hi, _bm in built:
                for f in range(lo, hi + 1):
                    self.assertEqual(got.captured(mdmsh, f), expected.captured(mdmsh, f),
                                     f"{mdmsh} {f}")


if __name__ == "__main__":
    unittest.main()
