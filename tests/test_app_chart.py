"""Tests for app.chart (the Safari Chart bridge) and its facade wiring.

claytonlib's canon-map/report/calibration-model storage is CWD-relative by design (the
notebook convention this app inherited — see app/chart.py's module docstring and
app/main.py's _chdir_into_app_data). Tests that exercise real precompute/rank/examine
therefore run inside an isolated temp CWD so they never touch the repo's own data/, and
use a small synthetic calibration model + a tiny setup/max range so the (real,
unmocked) precompute stays fast and deterministic.
"""
import contextlib
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
        for row in chart.list_criteria():
            self.assertIn("name", row)
            self.assertTrue(row["description"])

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
            self.assertIsNone(chart.calibration_model_summary())

    def test_model_present_is_summarized(self):
        with _isolated_cwd():
            _write_synthetic_model()
            summary = chart.calibration_model_summary()
            self.assertEqual(summary["available"], ["linear"])
            self.assertEqual(summary["models"]["linear"]["n_runs"], 10)


class TestPrecomputeRankExamine(unittest.TestCase):
    def test_precompute_requires_a_calibration_model(self):
        with _isolated_cwd():
            with self.assertRaises(ValueError):
                chart.precompute_runner(_EXP, _CHART)

    def test_full_round_trip(self):
        with _isolated_cwd():
            _write_synthetic_model()

            self.assertFalse(chart.canon_status(_EXP, _CHART)["built"])

            runner = chart.precompute_runner(_EXP, _CHART, workers=1)
            progress_calls = []
            stats = runner(lambda **kw: progress_calls.append(kw))
            self.assertGreater(stats["n_distinct_seeds"], 0)
            self.assertGreater(len(progress_calls), 0)
            self.assertIn("done", progress_calls[0])

            status = chart.canon_status(_EXP, _CHART)
            self.assertTrue(status["built"])
            self.assertEqual(status["last_setup"], 0)
            self.assertEqual(status["last_max"], 2)

            ranked = chart.rank_best_per_time(_EXP, _CHART, {"limit": 5, "step": 4})
            self.assertIn("top", ranked)
            self.assertGreater(ranked["per_time_count"], 0)

            # Re-running precompute is a fast no-op extend, not a rebuild (idempotent).
            stats2 = runner(lambda **kw: None)
            self.assertEqual(stats2.get("evaluated_this_run", 0), 0)

            if ranked["top"]:
                row = ranked["top"][0]
                for key in ("vector_ms", "target_delay", "second", "mdmsh", "p", "sigma", "initial_time"):
                    self.assertIn(key, row)

                ex = chart.examine(_EXP, _CHART, row["initial_time"], row["vector_ms"], {})
                self.assertGreaterEqual(ex["p"], 0.0)
                self.assertLessEqual(ex["p"], 1.0)
                self.assertTrue(ex["seconds"])

                at_time = chart.rank_at_time(_EXP, _CHART, row["initial_time"], {"limit": 3})
                self.assertTrue(at_time)
                self.assertIn("vector_ms", at_time[0])

    def test_rank_and_examine_need_canon_first(self):
        with _isolated_cwd():
            _write_synthetic_model()
            with self.assertRaises(ValueError):
                chart.rank_best_per_time(_EXP, _CHART, {})
            with self.assertRaises(ValueError):
                chart.examine(_EXP, _CHART, "2000-01-01T00:00:00", 1000, {})


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


if __name__ == "__main__":
    unittest.main()
