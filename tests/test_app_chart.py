"""Tests for app.chart (the Safari Chart bridge) and its facade wiring.

claytonlib's canon-map/report/calibration-model storage is CWD-relative by design (the
notebook convention this app inherited — see app/chart.py's module docstring and
app/main.py's _chdir_into_app_data). Tests that exercise real precompute/rank/examine
therefore run inside an isolated temp CWD so they never touch the repo's own data/, and
use a small synthetic calibration model + a tiny setup/max range so the (real,
unmocked) precompute stays fast and deterministic.
"""
import contextlib
import datetime as dt
import os
import tempfile
import time
import unittest

from app import chart
from app.facade import Facade
from app.store import FileStore
from claytonlib.calibration import CalibrationModel


@contextlib.contextmanager
def _isolated_cwd():
    """Run the wrapped block inside a fresh temp directory, restoring the CWD after."""
    prev = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        os.chdir(tmp)
        try:
            yield tmp
        finally:
            os.chdir(prev)


def _write_synthetic_model():
    """A deterministic, simple linear model — legacy 'Fb' target (mean(M) is the frame
    directly), a tiny sqrt(M) jitter, and a fixed (non-wandering) RTC second so the ranking
    math stays single-second-simple in tests."""
    model = CalibrationModel(
        kind="line", target="Fb", beta=0.06, alpha=0.0,
        jitter_c=0.15, rtc_offset_seconds=0.0, rtc_offset_std=0.0, n_runs=10,
    )
    CalibrationModel.save_set({"linear": model})
    return model


_EXP = {"id": "e1", "pokemon": "metang", "key_seed": 0x0D0E02BA}
_CHART = {"id": "c1", "strategy_name": "only-balls", "criteria_name": "capture",
          "setup_delay_seconds": 0, "max_target_seconds": 2}


class TestReferenceData(unittest.TestCase):
    def test_list_strategies_and_criteria_have_names_and_descriptions(self):
        for row in chart.list_strategies():
            self.assertIn("name", row)
            self.assertTrue(row["description"])
            self.assertTrue(row["label"])
        for row in chart.list_criteria():
            self.assertIn("name", row)
            self.assertTrue(row["description"])
            self.assertTrue(row["label"])

    def test_machete_criteria_defaults_to_5_balls(self):
        row = next(c for c in chart.list_criteria() if c["name"] == "machete-turns-after-balls")
        n_balls = next(p for p in row["params"] if p["key"] == "n_balls")
        self.assertEqual(n_balls["default"], 5)
        self.assertNotIn("e.g.", row["description"])

    def test_parameterized_criteria_templates_resolve_for_real(self):
        """Every parameterized criteria's `template`, filled with its `params`' defaults,
        must be a name that _resolve_criteria actually accepts — the Create Chart form
        builds exactly this string client-side."""
        from claytonlib.expedition._config import _resolve_criteria
        for row in chart.list_criteria():
            if not row["params"]:
                _resolve_criteria(row["name"])  # fixed criteria are looked up by their own name
                continue
            name = row["template"]
            for p in row["params"]:
                name = name.replace("{" + p["key"] + "}", str(p["default"]))
            resolved = _resolve_criteria(name)
            self.assertEqual(resolved.name, name)

    def test_list_safari_pokemon_matches_the_case_the_lookup_expects(self):
        names = chart.list_safari_pokemon()
        self.assertIn("metang", names)
        # The whole point of this dropdown: safari_pokemon_by_name is case-sensitive, so the
        # values offered must be exactly what it will accept.
        from claytonlib.safari import safari_pokemon_by_name
        for n in ("metang", "pidgey", "mr-mime"):
            self.assertIn(n, names)
            safari_pokemon_by_name(n)  # must not raise


class TestCalibrationModelBridge(unittest.TestCase):
    def test_no_model_returns_none(self):
        with _isolated_cwd():
            self.assertIsNone(chart.summarize_models(chart.global_calibration_models()))

    def test_model_present_is_summarized(self):
        with _isolated_cwd():
            _write_synthetic_model()
            summary = chart.summarize_models(chart.global_calibration_models())
            self.assertEqual(summary["available"], ["linear"])
            self.assertEqual(summary["models"]["linear"]["n_runs"], 10)


class TestRankReportCache(unittest.TestCase):
    """Ranking sweeps every candidate boot time and takes ~35 s on real data, so the finished
    report is cached ON DISK next to the canon map (clayton-fry.5) — surviving a restart, which
    is exactly when re-waiting hurts most."""

    def setUp(self):
        chart.clear_rank_cache()
        self.addCleanup(chart.clear_rank_cache)

    def _ranked(self, **params):
        return chart.rank_best_per_time(_EXP, _CHART, {"linear": _write_synthetic_model()},
                                        {"limit": 5, **params})

    def _build(self):
        models = {"linear": _write_synthetic_model()}
        chart.precompute_runner(_EXP, _CHART, models)(lambda **kw: None)
        return models

    def test_second_call_is_served_from_the_report_file(self):
        with _isolated_cwd():
            self._build()
            first = self._ranked()
            self.assertFalse(first["cached"])
            self.assertTrue(os.path.exists(chart._rank_report_path(_EXP, _CHART)))

            chart.clear_rank_cache()          # simulate an app restart: file survives, memo doesn't
            second = self._ranked()
            self.assertTrue(second["cached"])
            self.assertEqual(second["top"], first["top"])
            self.assertEqual(second["per_time_count"], first["per_time_count"])

    def test_limit_is_not_part_of_the_key_so_it_slices_the_cached_list(self):
        with _isolated_cwd():
            self._build()
            self._ranked(limit=5)
            few = self._ranked(limit=2)
            self.assertTrue(few["cached"])
            self.assertLessEqual(len(few["top"]), 2)

    def test_a_different_sweep_parameter_misses(self):
        with _isolated_cwd():
            self._build()
            self._ranked(step=4)
            self.assertFalse(self._ranked(step=2)["cached"])

    def test_a_different_calibration_model_misses(self):
        with _isolated_cwd():
            models = self._build()
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            other = CalibrationModel(kind="line", target="Fb", beta=0.061, alpha=1.0,
                                     jitter_c=0.15, rtc_offset_seconds=0.0, n_runs=10)
            res = chart.rank_best_per_time(_EXP, _CHART, {"linear": other}, {"limit": 5})
            self.assertFalse(res["cached"])

    def test_a_different_advance_count_misses(self):
        # key_seed_advances feeds the per-advance safari offset, so it changes the ranking.
        with _isolated_cwd():
            models = self._build()
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            other_exp = dict(_EXP, key_seed_advances=81)
            res = chart.rank_best_per_time(other_exp, _CHART, models, {"limit": 5})
            self.assertFalse(res["cached"])

    def test_expeditions_sharing_a_canon_map_get_their_own_report(self):
        # The canon map is deliberately shared between expeditions with the same pokemon +
        # key seed + strategy + criteria. One report file between them would mean each
        # invalidating the other's on every rank -- correct, but alternating 35 s waits.
        with _isolated_cwd():
            models = self._build()
            twin = dict(_EXP, id="e2")
            self.assertNotEqual(chart._rank_report_path(_EXP, _CHART),
                                chart._rank_report_path(twin, _CHART))
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            chart.rank_best_per_time(twin, _CHART, models, {"limit": 5})
            chart.clear_rank_cache()
            self.assertTrue(chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})["cached"])

    def test_charts_sharing_a_canon_map_get_their_own_report(self):
        # The canon signature omits setup/max, so two charts differing ONLY in window share a
        # map — but the window IS in the cache key, so they must not share a report file.
        with _isolated_cwd():
            models = self._build()
            wider = dict(_CHART, id="c2", max_target_seconds=3)
            self.assertNotEqual(chart._rank_report_path(_EXP, _CHART),
                                chart._rank_report_path(_EXP, wider))
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            chart.rank_best_per_time(_EXP, wider, models, {"limit": 5})
            chart.clear_rank_cache()
            self.assertTrue(chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})["cached"])

    def test_a_cached_slice_equals_a_fresh_compute_at_that_limit(self):
        # limit is deliberately NOT in the key. That is only sound because the ranking is
        # complete before the cut and the cut is a pure prefix — which was NOT true of an
        # earlier version that refined only the already-cut top-K, so it is worth pinning.
        with _isolated_cwd():
            models = self._build()
            wide = chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 15})
            narrow_cached = chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 3})
            self.assertTrue(narrow_cached["cached"])

            os.remove(chart._rank_report_path(_EXP, _CHART))
            chart.clear_rank_cache()
            narrow_fresh = chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 3})
            self.assertFalse(narrow_fresh["cached"])

            self.assertEqual(narrow_cached["top"], narrow_fresh["top"])
            self.assertEqual(narrow_cached["top"], wide["top"][:3])
            self.assertEqual(narrow_cached["per_time_count"], wide["per_time_count"])

    def test_a_corrupt_report_recomputes_instead_of_breaking(self):
        with _isolated_cwd():
            self._build()
            self._ranked()
            with open(chart._rank_report_path(_EXP, _CHART), "w") as f:
                f.write("{not json at all")
            chart.clear_rank_cache()
            res = self._ranked()
            self.assertFalse(res["cached"])
            self.assertTrue(res["top"])

    def test_deleting_the_canon_removes_every_report_derived_from_it(self):
        with _isolated_cwd():
            models = self._build()
            twin = dict(_EXP, id="e2")
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            chart.rank_best_per_time(twin, _CHART, models, {"limit": 5})
            chart.delete_canon(_EXP, _CHART)
            self.assertFalse(os.path.exists(chart._rank_report_path(_EXP, _CHART)))
            self.assertFalse(os.path.exists(chart._rank_report_path(twin, _CHART)))


class TestRankProgress(unittest.TestCase):
    """A cold rank is ~35 s, so it reports progress (clayton-6n6.2). Measured on a real chart,
    the refine pass is 96.7% of that and the frame sweep 3.3% — so the two phases are reported
    separately and the bar tracks refine."""

    def setUp(self):
        chart.clear_rank_cache()
        self.addCleanup(chart.clear_rank_cache)

    def test_both_phases_report_and_refine_reaches_its_total(self):
        with _isolated_cwd():
            models = {"linear": _write_synthetic_model()}
            chart.precompute_runner(_EXP, _CHART, models)(lambda **kw: None)
            seen = []
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5},
                                     progress=lambda **kw: seen.append(kw))
            phases = [s["phase"] for s in seen]
            self.assertIn("scan", phases)
            self.assertIn("refine", phases)
            # Scan is reported before refine, and refine finishes on its total so the bar
            # can't be left stranded short of 100%.
            self.assertLess(phases.index("scan"), phases.index("refine"))
            last = [s for s in seen if s["phase"] == "refine"][-1]
            self.assertEqual(last["done"], last["total"])
            for snap in seen:
                self.assertLessEqual(snap["done"], snap["total"])

    def test_progress_is_optional(self):
        with _isolated_cwd():
            models = {"linear": _write_synthetic_model()}
            chart.precompute_runner(_EXP, _CHART, models)(lambda **kw: None)
            self.assertTrue(chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})["top"])

    def test_cached_only_returns_the_report_without_loading_the_map(self):
        with _isolated_cwd():
            models = {"linear": _write_synthetic_model()}
            chart.precompute_runner(_EXP, _CHART, models)(lambda **kw: None)
            self.assertIsNone(chart.rank_cached_only(_EXP, _CHART, models, {"limit": 5}))
            full = chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            hit = chart.rank_cached_only(_EXP, _CHART, models, {"limit": 5})
            self.assertIsNotNone(hit)
            self.assertTrue(hit["cached"])
            self.assertEqual(hit["top"], full["top"])

    def test_facade_serves_a_cached_rank_without_starting_a_session(self):
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            pid = api.create_profile({"name": "P"})["id"]
            eid = api.create_expedition({"name": "E", "profile_id": pid,
                                         "pokemon": "metang", "key_seed": 0x0D0E02BA})["id"]
            cid = api.create_chart(eid, {"name": "Balls", "strategy_name": "only-balls",
                                         "criteria_name": "capture",
                                         "setup_delay_seconds": 0, "max_target_seconds": 2})["id"]
            sess = api.chart_precompute_start(eid, cid)
            while not api.chart_precompute_poll(sess["session_id"])["done"]:
                time.sleep(0.05)
            api.chart_rank_best_per_time(eid, cid, {"limit": 5, "step": 4})

            snap = api.chart_rank_start(eid, cid, {"limit": 5, "step": 4})
            self.assertTrue(snap["done"])
            self.assertIsNone(snap["session_id"])      # no background thread was needed
            self.assertTrue(snap["result"]["cached"])


class TestDeleteChartCascadesCanon(unittest.TestCase):
    """Deleting a chart should take its computed data with it — but a canon map is keyed by
    pokemon + key seed + strategy + criteria, not by chart id, so it must survive while another
    chart still maps to it (clayton-6n6.4)."""

    def setUp(self):
        chart.clear_rank_cache()
        self.addCleanup(chart.clear_rank_cache)

    def _built(self, api, eid, name, **chart_fields):
        cid = api.create_chart(eid, {"name": name, "strategy_name": "only-balls",
                                     "criteria_name": "capture", "setup_delay_seconds": 0,
                                     "max_target_seconds": 2, **chart_fields})["id"]
        sess = api.chart_precompute_start(eid, cid)
        while not api.chart_precompute_poll(sess["session_id"])["done"]:
            time.sleep(0.05)
        return cid

    def test_sole_chart_takes_its_canon_map_with_it(self):
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            pid = api.create_profile({"name": "P"})["id"]
            eid = api.create_expedition({"name": "E", "profile_id": pid,
                                         "pokemon": "metang", "key_seed": 0x0D0E02BA})["id"]
            cid = self._built(api, eid, "Balls")
            exp, c = api.get_expedition(eid), api.get_chart(cid)
            self.assertTrue(os.path.exists(chart.canon_path(exp, c)))
            api.chart_rank_best_per_time(eid, cid, {"limit": 5, "step": 4})

            self.assertTrue(api.delete_chart(cid))
            self.assertFalse(os.path.exists(chart.canon_path(exp, c)))
            self.assertFalse(os.path.exists(chart.rank_report_path(exp, c)))

    def test_a_shared_canon_map_survives_until_the_last_chart_goes(self):
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            pid = api.create_profile({"name": "P"})["id"]
            e1 = api.create_expedition({"name": "E1", "profile_id": pid,
                                        "pokemon": "metang", "key_seed": 0x0D0E02BA})["id"]
            e2 = api.create_expedition({"name": "E2", "profile_id": pid,
                                        "pokemon": "metang", "key_seed": 0x0D0E02BA})["id"]
            c1 = self._built(api, e1, "Balls one")
            c2 = self._built(api, e2, "Balls two")
            exp1, ch1 = api.get_expedition(e1), api.get_chart(c1)
            exp2, ch2 = api.get_expedition(e2), api.get_chart(c2)
            # Same pokemon + key seed + strategy + criteria => one shared canon map.
            self.assertEqual(chart.canon_path(exp1, ch1), chart.canon_path(exp2, ch2))
            api.chart_rank_best_per_time(e1, c1, {"limit": 5, "step": 4})
            api.chart_rank_best_per_time(e2, c2, {"limit": 5, "step": 4})

            api.delete_chart(c1)
            self.assertTrue(os.path.exists(chart.canon_path(exp2, ch2)))    # still in use
            self.assertFalse(os.path.exists(chart.rank_report_path(exp1, ch1)))
            self.assertTrue(os.path.exists(chart.rank_report_path(exp2, ch2)))

            api.delete_chart(c2)
            self.assertFalse(os.path.exists(chart.canon_path(exp2, ch2)))   # last one out

    def test_deleting_a_chart_with_no_computed_data_is_fine(self):
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            pid = api.create_profile({"name": "P"})["id"]
            eid = api.create_expedition({"name": "E", "profile_id": pid,
                                         "pokemon": "metang", "key_seed": 0x0D0E02BA})["id"]
            cid = api.create_chart(eid, {"name": "Balls", "strategy_name": "only-balls",
                                         "criteria_name": "capture"})["id"]
            self.assertTrue(api.delete_chart(cid))
            self.assertFalse(api.delete_chart(cid))    # already gone


class TestCanonDiskUsage(unittest.TestCase):
    def test_counts_map_meta_and_report_and_reads_human(self):
        with _isolated_cwd():
            models = {"linear": _write_synthetic_model()}
            self.assertEqual(chart.canon_disk_usage(_EXP, _CHART)["bytes"], 0)
            chart.precompute_runner(_EXP, _CHART, models)(lambda **kw: None)
            after_build = chart.canon_disk_usage(_EXP, _CHART)["bytes"]
            self.assertGreater(after_build, 0)
            chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5})
            self.assertGreater(chart.canon_disk_usage(_EXP, _CHART)["bytes"], after_build)
            self.assertIn("B", chart.canon_status(_EXP, _CHART)["human"])

    def test_human_bytes_scales(self):
        self.assertEqual(chart._human_bytes(0), "0 B")
        self.assertEqual(chart._human_bytes(512), "512 B")
        self.assertEqual(chart._human_bytes(1024), "1.0 KB")
        self.assertEqual(chart._human_bytes(4404019), "4.2 MB")


class TestPerAdvanceOffsetReachesTheChart(unittest.TestCase):
    """The chart's premise is the key-seed run — hit key_seed, advance key_seed_advances
    times, Sweet Scent — so key_seed_advances is the advance count a per-advance safari
    offset must be evaluated at (clayton-6h2.5)."""

    def _model(self, **kw):
        return CalibrationModel(kind="line", target="Fb", beta=0.06, alpha=100.0,
                                jitter_c=0.15, safari_offset=-400.0, **kw)

    def test_advances_come_from_the_expedition(self):
        exp = dict(_EXP, key_seed_advances=81)
        models = {"linear": self._model(safari_offset_per_advance=-2.0)}
        picked = chart._pick_model(models, "linear", True, chart._advances(exp))
        # 100 + (-400) + (-2 * 81)
        self.assertAlmostEqual(picked.alpha, -462.0)

    def test_missing_key_seed_advances_is_zero_not_a_crash(self):
        self.assertEqual(chart._advances(dict(_EXP)), 0)
        self.assertEqual(chart._advances(dict(_EXP, key_seed_advances=None)), 0)

    def test_a_model_without_the_term_is_unaffected_by_the_advance_count(self):
        models = {"linear": self._model()}
        with_adv = chart._pick_model(models, "linear", True, 81)
        without = chart._pick_model(models, "linear", True, 0)
        self.assertEqual(with_adv.alpha, without.alpha)

    def test_use_safari_offset_false_skips_both_terms(self):
        models = {"linear": self._model(safari_offset_per_advance=-2.0)}
        self.assertEqual(chart._pick_model(models, "linear", False, 81).alpha, 100.0)

    def test_precompute_folds_the_same_advance_count_the_rankers_use(self):
        # The canon is built over the FRAME RANGE the folded model asks for, so precompute
        # must fold the identical shift -- otherwise the ranked frames fall outside the canon.
        exp = dict(_EXP, key_seed_advances=81)
        models = {"linear": self._model(safari_offset_per_advance=-2.0)}
        seen = {}
        with _isolated_cwd():
            import claytonlib.chart as clchart
            orig = clchart.precompute_canon

            def spy(base_delay, times, setup, maxt, pokemon, strategy, criteria, store,
                    folded, **kw):
                seen["alpha"] = folded["linear"].alpha
                return {}

            clchart.precompute_canon = spy
            try:
                chart.precompute_runner(exp, _CHART, models)(lambda **kw: None)
            finally:
                clchart.precompute_canon = orig
        self.assertAlmostEqual(seen["alpha"],
                               chart._pick_model(models, "linear", True, 81).alpha)


class TestPrecomputeRankExamine(unittest.TestCase):
    def test_precompute_requires_a_calibration_model(self):
        with _isolated_cwd():
            with self.assertRaises(ValueError):
                chart.precompute_runner(_EXP, _CHART, {})

    def test_full_round_trip(self):
        with _isolated_cwd():
            _write_synthetic_model()
            models = chart.global_calibration_models()

            self.assertFalse(chart.canon_status(_EXP, _CHART)["built"])

            runner = chart.precompute_runner(_EXP, _CHART, models, workers=1)
            progress_calls = []
            stats = runner(lambda **kw: progress_calls.append(kw))
            self.assertGreater(stats["n_distinct_seeds"], 0)
            self.assertGreater(len(progress_calls), 0)
            self.assertIn("done", progress_calls[0])

            status = chart.canon_status(_EXP, _CHART)
            self.assertTrue(status["built"])
            self.assertEqual(status["last_setup"], 0)
            self.assertEqual(status["last_max"], 2)

            ranked = chart.rank_best_per_time(_EXP, _CHART, models, {"limit": 5, "step": 4})
            self.assertIn("top", ranked)
            self.assertGreater(ranked["per_time_count"], 0)

            # Re-running precompute is a fast no-op extend, not a rebuild (idempotent).
            stats2 = runner(lambda **kw: None)
            self.assertEqual(stats2.get("evaluated_this_run", 0), 0)

            if ranked["top"]:
                row = ranked["top"][0]
                for key in ("vector_ms", "target_delay", "second", "mdmsh", "p", "sigma",
                            "initial_time", "tod"):
                    self.assertIn(key, row)
                self.assertIn(row["tod"], ("morning", "day", "night"))

                ex = chart.examine(_EXP, _CHART, models, row["initial_time"], row["vector_ms"], {})
                self.assertGreaterEqual(ex["p"], 0.0)
                self.assertLessEqual(ex["p"], 1.0)
                self.assertTrue(ex["seconds"])

                at_time = chart.rank_at_time(_EXP, _CHART, models, row["initial_time"], {"limit": 3})
                self.assertTrue(at_time)
                self.assertIn("vector_ms", at_time[0])

            # Manage Data: deleting the canon map removes it and un-builds status.
            self.assertTrue(chart.delete_canon(_EXP, _CHART))
            self.assertFalse(chart.canon_status(_EXP, _CHART)["built"])
            self.assertFalse(chart.delete_canon(_EXP, _CHART))  # already gone -> False

    def test_rank_and_examine_need_canon_first(self):
        with _isolated_cwd():
            _write_synthetic_model()
            models = chart.global_calibration_models()
            with self.assertRaises(ValueError):
                chart.rank_best_per_time(_EXP, _CHART, models, {})
            with self.assertRaises(ValueError):
                chart.examine(_EXP, _CHART, models, "2000-01-01T00:00:00", 1000, {})


class TestRankAtTimeDeclustering(unittest.TestCase):
    """clayton-b42.9.4: rank_at_time declusters by default (distinct_targets) so the top-N
    are genuinely different targets, not a cluster of near-identical frames around one peak."""

    def _hand_built_canon(self, chart_cfg):
        from claytonlib.chart.canon import mdmsh_of
        from claytonlib.chart.grid import pack_row
        model = CalibrationModel(kind="line", target="Fb", beta=0.06, alpha=0.0,
                                 jitter_c=None, jitter_rms=3.0, rtc_offset_seconds=0.0,
                                 rtc_offset_std=0.0, n_runs=10)
        t0 = dt.datetime(2000, 6, 1, 21, 0, 0)
        # Two widely-separated commanded countdowns -> two different modal RTC seconds -> two
        # different mdmsh -> genuinely distinct targets (not two frames of the SAME spike).
        M_a, M_b = 2000.0, 10000.0
        F_a, F_b = round(model.mean(M_a)), round(model.mean(M_b))
        mdmsh_a = mdmsh_of(t0 + dt.timedelta(seconds=round(M_a / 1000)))
        mdmsh_b = mdmsh_of(t0 + dt.timedelta(seconds=round(M_b / 1000)))

        store = chart._canon_store(_EXP, chart_cfg)
        store.append_range(mdmsh_a, F_a - 3, F_a + 3, pack_row(7, range(7)))
        store.append_range(mdmsh_b, F_b - 3, F_b + 3, pack_row(7, range(7)))
        store.write_meta({"built": True})
        return t0, F_a, F_b, {"linear": model}

    def test_default_min_separation_surfaces_both_clusters(self):
        with _isolated_cwd():
            wide_chart = {**_CHART, "setup_delay_seconds": 0, "max_target_seconds": 15}
            t0, F_a, F_b, models = self._hand_built_canon(wide_chart)

            rows = chart.rank_at_time(_EXP, wide_chart, models, t0.isoformat(), {"limit": 5})
            fs = [r["target_delay"] for r in rows]
            self.assertTrue(any(abs(f - F_a) <= 3 for f in fs), fs)
            self.assertTrue(any(abs(f - F_b) <= 3 for f in fs), fs)
            # And they're not just every frame in one region repeated -- each pick is
            # genuinely min_separation apart from every other pick.
            for i, f1 in enumerate(fs):
                for f2 in fs[i + 1:]:
                    self.assertGreaterEqual(abs(f1 - f2), 30)

    def test_min_separation_zero_returns_the_raw_clustered_ranking(self):
        with _isolated_cwd():
            wide_chart = {**_CHART, "setup_delay_seconds": 0, "max_target_seconds": 15}
            t0, F_a, F_b, models = self._hand_built_canon(wide_chart)

            rows = chart.rank_at_time(_EXP, wide_chart, models, t0.isoformat(),
                                      {"limit": 5, "min_separation": 0})
            fs = [r["target_delay"] for r in rows]
            # Without declustering, at least two of the top picks sit right next to each
            # other inside the SAME 7-frame captured spike (unlike the declustered version,
            # where every pick is forced >= 30 frames from every other).
            self.assertTrue(any(abs(f1 - f2) < 7 for i, f1 in enumerate(fs) for f2 in fs[i+1:]), fs)


class TestRankBestPerTimeRefinesBeforeCutting(unittest.TestCase):
    """clayton-b42 feedback 8: refining only the already-cut top-K (an earlier version of
    rank_best_per_time did this) isn't enough -- a boot time whose COARSE score ranks
    outside the top-K never gets refined at all, even if its TRUE (refined) score would be
    the best of everything. Every candidate boot time must be refined BEFORE the cut."""

    def _hand_built_canon(self, chart_cfg):
        from claytonlib.chart.canon import mdmsh_of
        from claytonlib.chart.grid import pack_row
        model = CalibrationModel(kind="line", target="Fb", beta=0.06, alpha=0.0,
                                 jitter_c=None, jitter_rms=1.5, rtc_offset_seconds=0.0,
                                 rtc_offset_std=0.0, n_runs=10)
        s0 = 2
        F_a = round(model.mean(2000.0))          # a step=4-aligned frame (120 % 4 == 0)
        F_target = F_a + 2                        # exactly between two step=4 grid points

        # 6 "filler" boot times, each with a narrow (+/-1) capture band centered EXACTLY on
        # the step=4-aligned F_a -- the coarse sweep finds their true peak directly, no
        # refinement needed/possible, so each scores ~0.69.
        filler_times = [dt.datetime(2000, 6, 1, 21, 0, s) for s in range(6)]
        # 1 "target" boot time, with a WIDER (+/-2) capture band centered on the off-grid
        # F_target -- the coarse sweep only ever samples 2 frames away from its true peak
        # (both step=4 neighbors are equidistant), scoring it the WORST of all 7 (~0.63);
        # refine_near (radius=step-1=3) finds the true peak, raising it to ~0.91 -- the BEST
        # of all 7, and higher than any filler.
        target_time = dt.datetime(2000, 6, 1, 21, 0, 6)

        cmap_data = {}
        for t in filler_times:
            m = mdmsh_of(t + dt.timedelta(seconds=s0))
            cmap_data[m] = [(F_a - 1, F_a + 1, pack_row(3, range(3)))]
        m_target = mdmsh_of(target_time + dt.timedelta(seconds=s0))
        cmap_data[m_target] = [(F_target - 2, F_target + 2, pack_row(5, range(5)))]

        store = chart._canon_store(_EXP, chart_cfg)
        for mdmsh, ranges in cmap_data.items():
            for lo, hi, bm in ranges:
                store.append_range(mdmsh, lo, hi, bm)
        store.write_meta({"built": True})
        return filler_times, target_time, {"linear": model}

    def test_the_off_grid_boot_time_still_surfaces_as_best_within_a_small_limit(self):
        from unittest.mock import patch
        with _isolated_cwd():
            wide_chart = {**_CHART, "setup_delay_seconds": 0, "max_target_seconds": 15}
            filler_times, target_time, models = self._hand_built_canon(wide_chart)
            candidate_times = filler_times + [target_time]

            # rank_best_per_time sources its candidate boot times from get_times(key_seed) --
            # stub it to exactly the 7 phases this test controls, rather than the key seed's
            # real (much larger) set of valid times.
            with patch("app.chart.get_times", return_value=(0, candidate_times)):
                # limit=3: under the old refine-after-cut behavior, the target's coarse score
                # (worst of all 7) would place it outside this top-3 BEFORE any refinement
                # ever ran, so it could never be reported here at all.
                ranked = chart.rank_best_per_time(_EXP, wide_chart, models, {"limit": 3, "step": 4})
            self.assertEqual(ranked["per_time_count"], 7)  # all 7 boot times still counted
            top_times = [r["initial_time"] for r in ranked["top"]]
            self.assertIn(target_time.strftime(chart._TIME_FMT), top_times)
            best = ranked["top"][0]
            self.assertEqual(best["initial_time"], target_time.strftime(chart._TIME_FMT))
            self.assertGreater(best["p"], 0.85)  # the refined value, not the coarse ~0.63

    def test_per_time_is_resorted_by_refined_p_before_best_per_scenario(self):
        """The ACTUAL root cause behind the 'Ranked Targets misses an obviously-better
        target' bug reported (and NOT fixed) across rounds 7, 8, and 11's first attempt:
        per_time enters the refine loop p-desc sorted by COARSE score (rank_boot_marginal's
        own sort), but refining updates each row's `p` in place -- the list was never
        re-sorted by the NEW (refined) p afterward. best_per_scenario's own docstring
        requires p-desc sorted input: it keeps only the FIRST row seen per (second, mdmsh)
        key via dict.setdefault, trusting sort order to make that the highest-p one. Fed
        stale (coarse-order) input, it can discard a genuinely higher-refined-p row in favor
        of a lower one that merely had a better COARSE score (and so sorted earlier) --
        confirmed directly against a real profile/chart/canon map, where this was silently
        dropping the actual best target from the ranked list entirely. This test doesn't
        need two boot times to collide on the same (second, mdmsh) scenario (rare to
        engineer by hand, common with thousands of real candidate times) -- it instead
        verifies the underlying invariant directly: whatever best_per_scenario is actually
        called with must already be in refined-p-desc order, regardless of what the coarse
        order was."""
        from unittest.mock import patch
        import app.chart as chart_mod
        with _isolated_cwd():
            wide_chart = {**_CHART, "setup_delay_seconds": 0, "max_target_seconds": 15}
            filler_times, target_time, models = self._hand_built_canon(wide_chart)
            candidate_times = filler_times + [target_time]

            captured = {}
            real_best_per_scenario = chart_mod.best_per_scenario
            def _spy(ranked):
                captured["ranked"] = list(ranked)
                return real_best_per_scenario(ranked)

            with patch("app.chart.get_times", return_value=(0, candidate_times)), \
                 patch("app.chart.best_per_scenario", side_effect=_spy):
                chart_mod.rank_best_per_time(_EXP, wide_chart, models, {"limit": 3, "step": 4})

            ranked = captured["ranked"]
            self.assertEqual(len(ranked), 7)
            # The target boot time's coarse score is the WORST of the 7 (see
            # _hand_built_canon's own comment) but its REFINED score is the best -- if the
            # list fed to best_per_scenario were still coarse-ordered, this would be false.
            self.assertTrue(all(a["p"] >= b["p"] for a, b in zip(ranked, ranked[1:])),
                            "per_time passed to best_per_scenario is not p-desc sorted by "
                            "the REFINED p -- best_per_scenario's setdefault will silently "
                            "keep the wrong row whenever two boot times collide on scenario")
            self.assertEqual(ranked[0]["initial_time"], target_time)

    def test_a_true_peak_far_from_the_single_best_coarse_point_still_surfaces(self):
        """Round 11 feedback: refine_near's radius around only the SINGLE best coarse-sampled
        point per boot time still isn't enough -- if a decoy sits exactly on a step=4 grid
        point (so the coarse sweep locks onto it) and the TRUE, higher peak sits more than
        `radius` frames away, a single-point refine never reaches it. Reproduced directly
        against claytonlib.chart.scorer before this fix (0 out of 392 tested gap/width
        combinations passed with keep_top_k=1; all passed with keep_top_k=5) -- this exercises
        the same failure mode through the real app.chart.rank_best_per_time entry point."""
        from unittest.mock import patch
        from claytonlib.chart.canon import mdmsh_of
        from claytonlib.chart.grid import pack_row
        with _isolated_cwd():
            wide_chart = {**_CHART, "setup_delay_seconds": 0, "max_target_seconds": 15}
            model = CalibrationModel(kind="line", target="Fb", beta=0.06, alpha=0.0,
                                     jitter_c=None, jitter_rms=1.0, rtc_offset_seconds=0.0,
                                     rtc_offset_std=0.0, n_runs=10)
            s0 = 2
            F_decoy = round(model.mean(2000.0))
            F_decoy -= F_decoy % 4  # land exactly on a step=4 grid point
            F_true = F_decoy + 22   # far enough that no coarse point within radius=3 reaches it

            t = dt.datetime(2000, 6, 1, 21, 0, s0)
            m = mdmsh_of(t + dt.timedelta(seconds=s0))
            store = chart._canon_store(_EXP, wide_chart)
            store.append_range(m, F_decoy - 1, F_decoy + 1, pack_row(3, range(3)))    # decoy
            store.append_range(m, F_true - 2, F_true + 2, pack_row(5, range(5)))       # true peak (wider)
            store.write_meta({"built": True})

            with patch("app.chart.get_times", return_value=(0, [t])):
                ranked = chart.rank_best_per_time(_EXP, wide_chart, {"linear": model},
                                                  {"limit": 3, "step": 4})
            self.assertEqual(ranked["per_time_count"], 1)
            best = ranked["top"][0]
            self.assertLessEqual(abs(best["target_delay"] - F_true), 2)  # found the true peak, not the decoy
            self.assertGreater(best["p"], 0.9)                # the true peak's real height


class TestFacadeChartCRUD(unittest.TestCase):
    """Pure CRUD needs no calibration model or canon map — an in-temp FileStore is enough."""

    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        p = self.api.create_profile({"name": "P1"})
        self.eid = self.api.create_expedition(
            {"name": "Metang hunt", "profile_id": p["id"], "pokemon": "metang",
             "key_seed": 0x0D0E02BA})["id"]

    def test_create_requires_existing_expedition(self):
        with self.assertRaises(ValueError):
            self.api.create_chart("ghost", {"name": "x", "strategy_name": "only-balls",
                                            "criteria_name": "capture"})

    def test_create_list_get_delete_chart(self):
        c = self.api.create_chart(self.eid, {
            "name": "Balls only", "strategy_name": "only-balls", "criteria_name": "capture"})
        self.assertEqual(c["setup_delay_seconds"], 0)   # default
        self.assertEqual(c["max_target_seconds"], 300)  # default
        self.assertEqual([x["id"] for x in self.api.list_charts(self.eid)], [c["id"]])
        self.assertEqual(self.api.get_chart(c["id"])["name"], "Balls only")
        self.assertTrue(self.api.delete_chart(c["id"]))
        self.assertEqual(self.api.list_charts(self.eid), [])

    def test_update_chart_window(self):
        c = self.api.create_chart(self.eid, {
            "name": "Balls only", "strategy_name": "only-balls", "criteria_name": "capture"})
        updated = self.api.update_chart_window(c["id"], 60, 400)
        self.assertEqual(updated["setup_delay_seconds"], 60)
        self.assertEqual(updated["max_target_seconds"], 400)
        # persisted, not just returned
        self.assertEqual(self.api.get_chart(c["id"])["setup_delay_seconds"], 60)
        # everything else about the chart is untouched
        self.assertEqual(updated["name"], "Balls only")
        self.assertEqual(updated["strategy_name"], "only-balls")

    def test_chart_requires_a_name(self):
        with self.assertRaises(ValueError):
            self.api.create_chart(self.eid, {"name": "  ", "strategy_name": "only-balls",
                                             "criteria_name": "capture"})

    def test_save_target_requires_existing_chart(self):
        with self.assertRaises(ValueError):
            self.api.save_target(self.eid, "ghost", {
                "name": "t", "initial_time": "2000-01-01T00:00:00", "vector_ms": 1000,
                "target_delay": 500, "p": 0.1, "sigma": 2.0})

    def test_target_crud_and_scoping(self):
        c1 = self.api.create_chart(self.eid, {"name": "A", "strategy_name": "only-balls",
                                              "criteria_name": "capture"})
        c2 = self.api.create_chart(self.eid, {"name": "B", "strategy_name": "one-mud-then-balls",
                                              "criteria_name": "capture"})
        t1 = self.api.save_target(self.eid, c1["id"], {
            "name": "First try", "initial_time": "2000-05-30T14:59:59", "vector_ms": 300000,
            "target_delay": 4500, "p": 0.42, "sigma": 3.1, "second": 305, "mdmsh": [88, 14]})
        self.api.save_target(self.eid, c2["id"], {
            "name": "Second try", "initial_time": "2000-05-30T15:00:00", "vector_ms": 310000,
            "target_delay": 4600, "p": 0.30, "sigma": 3.3})

        self.assertEqual(len(self.api.list_targets(self.eid)), 2)
        self.assertEqual([t["name"] for t in self.api.list_targets(self.eid, chart_id=c1["id"])],
                         ["First try"])
        got = self.api.get_target(t1["id"])
        self.assertEqual(got["mdmsh"], [88, 14])
        self.assertTrue(self.api.delete_target(t1["id"]))
        self.assertEqual(len(self.api.list_targets(self.eid)), 1)


class TestFacadeChartCompute(unittest.TestCase):
    """Exercises the facade's compute methods (precompute session, rank, examine, examine_target)
    end to end, through the real (small/synthetic) pipeline, isolated to a temp CWD."""

    def test_precompute_session_rank_and_examine_via_facade(self):
        with _isolated_cwd():
            _write_synthetic_model()
            self.api = Facade(FileStore(tempfile.mkdtemp()))
            p = self.api.create_profile({"name": "P1"})
            eid = self.api.create_expedition(
                {"name": "Metang hunt", "profile_id": p["id"], "pokemon": "metang",
                 "key_seed": 0x0D0E02BA})["id"]
            c = self.api.create_chart(eid, {
                "name": "Balls only", "strategy_name": "only-balls", "criteria_name": "capture",
                "setup_delay_seconds": 0, "max_target_seconds": 2})

            self.assertFalse(self.api.chart_canon_status(eid, c["id"])["built"])

            state = self.api.chart_precompute_start(eid, c["id"])
            # A tiny range finishes near-instantly; poll until done (bounded to avoid a hang).
            # The tiny sleep actually yields to the background thread between polls.
            for _ in range(100):
                if state["done"]:
                    break
                time.sleep(0.02)
                state = self.api.chart_precompute_poll(state["session_id"])
            self.assertTrue(state["done"])
            self.assertIsNone(state["error"])
            self.assertTrue(self.api.chart_canon_status(eid, c["id"])["built"])

            ranked = self.api.chart_rank_best_per_time(eid, c["id"], {"limit": 5, "step": 4})
            if ranked["top"]:
                row = ranked["top"][0]
                saved = self.api.save_target(eid, c["id"], {
                    "name": "Best pick", "initial_time": row["initial_time"],
                    "vector_ms": row["vector_ms"], "target_delay": row["target_delay"],
                    "p": row["p"], "sigma": row["sigma"], "second": row["second"],
                    "mdmsh": row["mdmsh"]})
                ex = self.api.examine_target(saved["id"], {})
                self.assertIn("p", ex)
                self.assertIn("seconds", ex)

                # Per-second seed drill-down (clayton-b42.5.8): both the raw and the
                # saved-target convenience wrapper should agree on the same second.
                second = ex["seconds"][0]["second"]
                br = self.api.chart_examine_second(eid, c["id"], row["initial_time"],
                                                   row["vector_ms"], second, {})
                self.assertEqual(br["second"], second)
                self.assertTrue(br["rows"])
                self.assertIn("seed_hex", br["rows"][0])
                br2 = self.api.examine_target_second(saved["id"], second, {})
                self.assertEqual(br2["second"], second)
                self.assertEqual(len(br2["rows"]), len(br["rows"]))

                with self.assertRaises(ValueError):
                    self.api.chart_examine_second(eid, c["id"], row["initial_time"],
                                                   row["vector_ms"], second + 999, {})


if __name__ == "__main__":
    unittest.main()
