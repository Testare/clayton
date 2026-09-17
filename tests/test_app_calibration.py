"""Tests for app.calibration (the Calibrate Model bridge) and its facade wiring."""
import datetime as dt
import tempfile
import unittest

from app import calibration
from app.facade import Facade
from app.store import FileStore
from tests.test_app_chart import _isolated_cwd


def _seed(time: dt.datetime, delay: int) -> dict:
    return {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "delay": delay}


_BASE = dt.datetime(2025, 7, 24, 14, 45, 56)

# Six clean runs on a straight F_b-vs-M trend (Fb = 700 + 0.06*M), enough for Theil-Sen +
# outlier screening (_robust_flags needs >= 4 finite residuals) to both engage meaningfully.
_CLEAN = [(180000, 11500), (220000, 13900), (260000, 16300), (300000, 18700),
          (340000, 21100), (380000, 23500)]
_OUTLIER_M, _OUTLIER_FB = 260000, 30000  # wildly off the trend at the same M as a clean run


def _run_dict(tag, M, Fb, excluded=False):
    return {
        "kind": "metronome", "tag": tag, "vector_ms": M, "target_timer_calibration": 0,
        "excluded": excluded,
        "a_seed": _seed(_BASE, 700),
        "b_seed": _seed(_BASE + dt.timedelta(seconds=5), Fb),
    }


class TestRecordForRun(unittest.TestCase):
    def test_valid_run_converts(self):
        run = {"id": "r1", **_run_dict("t", 200000, 12000)}
        rec = calibration._record_for_run(run)
        self.assertEqual(rec["_run_id"], "r1")
        self.assertEqual(rec["target_timer_delay"], 200000)
        self.assertEqual(rec["a_seed"]["delay"], 700)

    def test_missing_vector_ms_skipped(self):
        run = {"id": "r1", "kind": "metronome", "a_seed": _seed(_BASE, 700),
               "b_seed": _seed(_BASE, 800), "vector_ms": None}
        self.assertIsNone(calibration._record_for_run(run))

    def test_missing_seed_skipped(self):
        run = {"id": "r1", "kind": "metronome", "vector_ms": 1000, "a_seed": {}, "b_seed": {}}
        self.assertIsNone(calibration._record_for_run(run))

    def test_safari_run_skipped(self):
        run = {"id": "r1", "kind": "safari", "vector_ms": 1000,
               "a_seed": _seed(_BASE, 700), "b_seed": _seed(_BASE, 800)}
        self.assertIsNone(calibration._record_for_run(run))


class TestEffectiveIncluded(unittest.TestCase):
    def test_manual_and_tag_and_incomplete_and_ok(self):
        runs = [
            {"id": "ok", **_run_dict("keep", 200000, 12000)},
            {"id": "manual", **_run_dict("keep", 210000, 12500, excluded=True)},
            {"id": "tagged", **_run_dict("bad-tag", 220000, 13000)},
            {"id": "incomplete", "kind": "metronome", "tag": "keep", "vector_ms": None,
             "a_seed": {}, "b_seed": {}},
        ]
        records, reasons = calibration.effective_included(runs, {"bad-tag"})
        self.assertEqual([r["_run_id"] for r in records], ["ok"])
        self.assertEqual(reasons, {"manual": "manual", "tagged": "tag:bad-tag",
                                   "incomplete": "incomplete"})


def _safari_run_dict(tag, vector_ms, seed, frame, a_delay=700, excluded=False):
    return {
        "kind": "safari", "tag": tag, "vector_ms": vector_ms, "target_timer_calibration": 0,
        "excluded": excluded,
        "a_seed": {"delay": a_delay},
        "b_seed": {"seed": seed, "seed_hex": f"0x{seed:08X}", "frame": frame},
    }


class TestPreviewFit(unittest.TestCase):
    def test_no_fittable_runs_raises(self):
        with self.assertRaises(ValueError):
            calibration.preview_fit([], [], [])

    def test_fit_report_shape_and_reasons(self):
        runs = [{"id": f"clean-{i}", **_run_dict("session1", M, Fb)}
                for i, (M, Fb) in enumerate(_CLEAN)]
        runs.append({"id": "outlier-1", **_run_dict("session1", _OUTLIER_M, _OUTLIER_FB)})
        runs.append({"id": "excluded-1", **_run_dict("standard", 400000, 25000, excluded=True)})

        report = calibration.preview_fit(runs, [], excluded_tags=[])

        self.assertEqual(report["n_input"], len(runs))
        self.assertEqual(report["n_pre_excluded"], 1)          # the manually-excluded one
        self.assertEqual(report["n_runs"], len(runs) - 1)      # everything but the pre-excluded
        self.assertIn("linear", report["artifact"]["models"])
        self.assertEqual(report["artifact"]["format"], "modelset")
        self.assertIn("linear", report["stats"])
        self.assertEqual(report["n_safari_input"], 0)
        self.assertEqual(report["safari_offset"], {})

        # The outlier is off-trend enough to be flagged by calibrate_timer's own screening.
        self.assertEqual(report["reasons"].get("outlier-1"), "outlier")
        self.assertEqual(report["reasons"].get("excluded-1"), "manual")
        self.assertNotIn("clean-0", report["reasons"])  # clean runs carry no reason at all

    def test_tag_exclusion_removes_a_whole_tag_from_the_fit(self):
        runs = [{"id": f"clean-{i}", **_run_dict("keep", M, Fb)}
                for i, (M, Fb) in enumerate(_CLEAN)]
        runs.append({"id": "std-1", **_run_dict("Standard", 400000, 25000)})

        report = calibration.preview_fit(runs, [], excluded_tags=["Standard"])
        self.assertEqual(report["reasons"].get("std-1"), "tag:Standard")
        self.assertEqual(report["n_pre_excluded"], 1)

    def test_safari_runs_fit_the_offset_against_the_new_model(self):
        metronome_runs = [{"id": f"clean-{i}", **_run_dict("keep", M, Fb)}
                          for i, (M, Fb) in enumerate(_CLEAN)]
        # Fabricate safari runs whose (seed, frame) sit exactly `offset` frames above what
        # the FITTED linear model predicts for their M -- can't know that model's beta/alpha
        # up front, so fit metronome-only first, then build safari points relative to it.
        pre = calibration.preview_fit(metronome_runs, [], [])
        from claytonlib.calibration import CalibrationModel
        linear = CalibrationModel.from_dict(pre["artifact"]["models"]["linear"])
        offset = 12.0
        safari_runs = []
        for i, M in enumerate([200000, 260000, 320000]):
            frame = round(linear.frame(M, 700) + offset)
            safari_runs.append({"id": f"sf-{i}", **_safari_run_dict("s", M, 100 + i, frame)})

        report = calibration.preview_fit(metronome_runs, safari_runs, [])
        self.assertEqual(report["n_safari_input"], 3)
        self.assertEqual(report["n_safari_fit"], 3)
        self.assertEqual(report["n_safari_pre_excluded"], 0)
        self.assertIn("linear", report["safari_offset"])
        self.assertAlmostEqual(report["safari_offset"]["linear"]["offset"], offset, delta=0.5)
        self.assertEqual(report["safari_offset"]["linear"]["n"], 3)
        # Folded into the artifact model itself, not just reported separately.
        self.assertAlmostEqual(report["artifact"]["models"]["linear"]["safari_offset"],
                               offset, delta=0.5)

    def test_safari_run_exclusion_reasons(self):
        metronome_runs = [{"id": f"clean-{i}", **_run_dict("keep", M, Fb)}
                          for i, (M, Fb) in enumerate(_CLEAN)]
        safari_runs = [
            {"id": "sf-manual", **_safari_run_dict("s", 200000, 1, 12000, excluded=True)},
            {"id": "sf-tagged", **_safari_run_dict("bad", 200000, 2, 12000)},
            {"id": "sf-incomplete", "kind": "safari", "vector_ms": None,
             "a_seed": {}, "b_seed": {}},
        ]
        report = calibration.preview_fit(metronome_runs, safari_runs, excluded_tags=["bad"])
        self.assertEqual(report["reasons"].get("sf-manual"), "manual")
        self.assertEqual(report["reasons"].get("sf-tagged"), "tag:bad")
        self.assertEqual(report["reasons"].get("sf-incomplete"), "incomplete")
        self.assertEqual(report["n_safari_fit"], 0)
        self.assertEqual(report["safari_offset"], {})

    def test_safari_offset_absent_when_no_usable_safari_runs(self):
        metronome_runs = [{"id": f"clean-{i}", **_run_dict("keep", M, Fb)}
                          for i, (M, Fb) in enumerate(_CLEAN)]
        report = calibration.preview_fit(metronome_runs, [], [])
        self.assertEqual(report["safari_offset"], {})
        self.assertIsNone(report["artifact"]["models"]["linear"]["safari_offset"])


class TestFacadeCalibration(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "P1"})["id"]
        for i, (M, Fb) in enumerate(_CLEAN):
            a = self.api.save_metronome_run(self.pid, {
                "tag": "session1", "vector_ms": M, "a_seed": _seed(_BASE, 700),
                "b_seed": _seed(_BASE + dt.timedelta(seconds=5), Fb)})

    def test_preview_needs_no_saved_model(self):
        report = self.api.preview_calibration(self.pid)
        self.assertGreater(report["n_fit"], 0)

    def test_save_creates_numbered_active_model(self):
        # A fresh profile already has model #1 — the bundled "Standard" model, seeded by
        # create_profile (see Facade._seed_standard_calibration_model) — so the first
        # user-saved fit is #2, and displaces Standard as the active one.
        report = self.api.preview_calibration(self.pid)
        doc = self.api.save_calibration_model(self.pid, {"name": "First fit", "preview": report})
        self.assertEqual(doc["number"], 2)
        self.assertTrue(doc["active"])
        self.assertEqual(self.api.get_active_calibration_model(self.pid)["id"], doc["id"])

    def test_numbers_strictly_increment_and_active_is_exclusive(self):
        report = self.api.preview_calibration(self.pid)
        d1 = self.api.save_calibration_model(self.pid, {"name": "v1", "preview": report})
        d2 = self.api.save_calibration_model(self.pid, {"name": "v2", "preview": report})
        self.assertEqual((d1["number"], d2["number"]), (2, 3))
        models = self.api.list_calibration_models(self.pid)
        self.assertEqual(sorted(m["number"] for m in models), [1, 2, 3])
        active = [m for m in models if m["active"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], d2["id"])  # the newer save is active by default

    def test_set_active_switches_exclusively(self):
        report = self.api.preview_calibration(self.pid)
        d1 = self.api.save_calibration_model(self.pid, {"name": "v1", "preview": report})
        self.api.save_calibration_model(self.pid, {"name": "v2", "preview": report})
        self.api.set_active_calibration_model(self.pid, d1["id"])
        active = [m for m in self.api.list_calibration_models(self.pid) if m["active"]]
        self.assertEqual([m["id"] for m in active], [d1["id"]])

    def test_save_requires_a_preview(self):
        with self.assertRaises(ValueError):
            self.api.save_calibration_model(self.pid, {"name": "no preview"})

    def test_tag_exclusion_via_facade_reflected_in_preview(self):
        self.api.save_metronome_run(self.pid, {
            "tag": "Standard", "vector_ms": 400000, "a_seed": _seed(_BASE, 700),
            "b_seed": _seed(_BASE + dt.timedelta(seconds=5), 25000)})
        before = self.api.preview_calibration(self.pid)
        self.assertEqual(before["n_pre_excluded"], 0)

        p = self.api.set_tag_excluded(self.pid, "Standard", True)
        self.assertEqual(p["excluded_tags"], ["Standard"])

        after = self.api.preview_calibration(self.pid)
        self.assertEqual(after["n_pre_excluded"], 1)

    def test_delete_calibration_model(self):
        report = self.api.preview_calibration(self.pid)
        d = self.api.save_calibration_model(self.pid, {"name": "v1", "preview": report})
        self.assertTrue(self.api.delete_calibration_model(d["id"]))
        # The seeded "Standard" model (#1) is untouched — only the one just created is gone.
        remaining = self.api.list_calibration_models(self.pid)
        self.assertEqual([m["name"] for m in remaining], ["Standard"])


class TestStandardCalibrationModelSeed(unittest.TestCase):
    """Every fresh profile ships with the bundled 'Standard' model, active by default —
    see Facade._seed_standard_calibration_model / app/resources/standard_calibration_model.json."""

    def test_fresh_profile_has_an_active_standard_model(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        pid = api.create_profile({"name": "P1"})["id"]
        models = api.list_calibration_models(pid)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["number"], 1)
        self.assertEqual(models[0]["name"], "Standard")
        self.assertTrue(models[0]["active"])
        self.assertEqual(models[0]["artifact"]["format"], "modelset")
        self.assertIn("linear", models[0]["artifact"]["models"])

    def test_standard_model_resolves_to_a_usable_calibration_model(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        pid = api.create_profile({"name": "P1"})["id"]
        resolved = api._resolve_calibration_models(pid)
        self.assertIn("linear", resolved)
        self.assertGreater(resolved["linear"].n_runs, 0)

    def test_seeded_model_is_independent_per_profile(self):
        # Two profiles each get their OWN seeded doc (same content, different ids) — deleting
        # one's Standard model must not affect the other's.
        api = Facade(FileStore(tempfile.mkdtemp()))
        p1 = api.create_profile({"name": "P1"})["id"]
        p2 = api.create_profile({"name": "P2"})["id"]
        m1 = api.list_calibration_models(p1)[0]
        m2 = api.list_calibration_models(p2)[0]
        self.assertNotEqual(m1["id"], m2["id"])
        api.delete_calibration_model(m1["id"])
        self.assertEqual(api.list_calibration_models(p1), [])
        self.assertEqual(len(api.list_calibration_models(p2)), 1)


class TestFacadeUsesSavedModelOverGlobalFallback(unittest.TestCase):
    """The real point of this whole feature: once a profile has an active saved model,
    Safari Chart's compute methods must use IT, not the global notebook-file fallback."""

    def test_resolve_prefers_active_saved_model(self):
        # Isolated CWD: without it this would see the REPO's own global
        # data/calibration_model.json (built during earlier app-dev sessions) instead of a
        # clean "nothing saved yet" state.
        with _isolated_cwd():
            self.api = Facade(FileStore(tempfile.mkdtemp()))
            pid = self.api.create_profile({"name": "P1"})["id"]
            for i, (M, Fb) in enumerate(_CLEAN):
                self.api.save_metronome_run(pid, {
                    "tag": "session1", "vector_ms": M, "a_seed": _seed(_BASE, 700),
                    "b_seed": _seed(_BASE + dt.timedelta(seconds=5), Fb)})

            # No user-saved model yet: resolves to the seeded "Standard" model (#1, active
            # by default — see Facade._seed_standard_calibration_model), not the (empty, in
            # this isolated CWD) global notebook file.
            resolved = self.api._resolve_calibration_models(pid)
            self.assertIn("linear", resolved)
            self.assertEqual(resolved["linear"].label, "dF line (deployed)")

            report = self.api.preview_calibration(pid)
            saved = self.api.save_calibration_model(pid, {"name": "v1", "preview": report})

            resolved = self.api._resolve_calibration_models(pid)
            self.assertIn("linear", resolved)
            self.assertAlmostEqual(resolved["linear"].n_runs,
                                   saved["stats"]["linear"]["n_runs"])


if __name__ == "__main__":
    unittest.main()
