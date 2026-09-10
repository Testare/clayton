"""Tests for the expedition loop-back: export + auto-refresh of the CalibrationModel artifact."""
import builtins
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager

from claytonlib.calibration import CalibrationModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import calibration_tools as ct  # noqa: E402


@contextmanager
def _answers(seq):
    it = iter(seq)
    orig = builtins.input
    builtins.input = lambda prompt="": next(it)
    try:
        yield
    finally:
        builtins.input = orig


def _write_runs(path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _run_rec(M, Fb, cal=0):
    ta = dt.datetime(2025, 1, 1, 14, 45, 55)
    tb = ta + dt.timedelta(seconds=round(M / 1000) + 5)
    return {
        "tag": "t", "target_timer_delay": M - cal, "target_timer_calibration": cal,
        "fresh_boot": True, "prior_battles": 0, "notes": "",
        "a_seed": {"seed": 1, "delay": 680, "time": ta.isoformat()},
        "b_seed": {"seed": 2, "delay": Fb, "time": tb.isoformat()},
    }


class TestExport(unittest.TestCase):
    def test_export_writes_loadable_artifact(self):
        d = tempfile.mkdtemp()
        runs = os.path.join(d, "runs.jsonl")
        out = os.path.join(d, "model.json")
        _write_runs(runs, [_run_rec(M, round(0.06 * M) + 680)
                           for M in (180000, 240000, 300000, 360000, 420000)])
        cm = ct.export_calibration_model(runs_path=runs, out_path=out)
        self.assertTrue(os.path.exists(out))
        loaded = CalibrationModel.load(out)
        self.assertEqual(loaded, cm)
        # sane slope near the synthetic 0.06 frames/ms
        self.assertAlmostEqual(loaded.slope(300000), 0.06, delta=0.01)


class TestAutoLoopback(unittest.TestCase):
    def test_save_compass_run_default_does_not_touch_model(self):
        # Saving a run must NOT change the shared model by default (would invalidate a chart).
        d = tempfile.mkdtemp()
        runs = os.path.join(d, "runs.jsonl")
        out = os.path.join(d, "model.json")
        _write_runs(runs, [_run_rec(M, round(0.06 * M) + 680) for M in (180000, 300000)])
        a = {"seed": 1, "delay": 680, "time": dt.datetime(2025, 1, 1, 14, 45, 55)}
        b = {"seed": 2, "delay": 12000, "time": dt.datetime(2025, 1, 1, 14, 49, 0)}
        with _answers(["t", "200000", "0", "", "y"]):
            rec = ct.save_compass_run(a, b, path=runs, model_path=out)
        self.assertIsNotNone(rec)
        self.assertFalse(os.path.exists(out))  # model left untouched

    def test_save_compass_run_opt_in_refreshes_model(self):
        d = tempfile.mkdtemp()
        runs = os.path.join(d, "runs.jsonl")
        out = os.path.join(d, "model.json")
        _write_runs(runs, [_run_rec(M, round(0.06 * M) + 680)
                           for M in (180000, 240000, 300000, 360000)])
        a = {"seed": 1, "delay": 680, "time": dt.datetime(2025, 1, 1, 14, 45, 55)}
        b = {"seed": 2, "delay": round(0.06 * 450000) + 680,
             "time": dt.datetime(2025, 1, 1, 14, 53, 30)}
        with _answers(["t", "450000", "0", "", "y"]):
            rec = ct.save_compass_run(a, b, path=runs, update_model=True, model_path=out)
        self.assertIsNotNone(rec)
        self.assertTrue(os.path.exists(out))
        self.assertEqual(CalibrationModel.load(out).n_runs, 5)


class TestUpdateCalibrationModel(unittest.TestCase):
    def _runs(self):
        d = tempfile.mkdtemp()
        runs = os.path.join(d, "runs.jsonl")
        out = os.path.join(d, "model.json")
        _write_runs(runs, [_run_rec(M, round(0.06 * M) + 680)
                           for M in (180000, 240000, 300000, 360000)])
        return runs, out

    def test_confirm_writes(self):
        runs, out = self._runs()
        with _answers(["y"]):
            cm = ct.update_calibration_model(runs_path=runs, out_path=out)
        self.assertIsNotNone(cm)
        self.assertTrue(os.path.exists(out))

    def test_decline_does_not_write(self):
        runs, out = self._runs()
        with _answers(["n"]):
            cm = ct.update_calibration_model(runs_path=runs, out_path=out)
        self.assertIsNone(cm)
        self.assertFalse(os.path.exists(out))

    def test_assume_yes_writes_without_prompt(self):
        runs, out = self._runs()
        cm = ct.update_calibration_model(runs_path=runs, out_path=out, assume_yes=True)
        self.assertIsNotNone(cm)
        self.assertTrue(os.path.exists(out))

    def test_no_change_is_noop(self):
        runs, out = self._runs()
        ct.update_calibration_model(runs_path=runs, out_path=out, assume_yes=True)
        mtime = os.path.getmtime(out)
        # re-running with the SAME runs: no change -> returns None, does not rewrite
        cm = ct.update_calibration_model(runs_path=runs, out_path=out, assume_yes=True)
        self.assertIsNone(cm)
        self.assertEqual(os.path.getmtime(out), mtime)


class TestExpeditionLoader(unittest.TestCase):
    def test_load_default_none_when_absent(self):
        missing = os.path.join(tempfile.mkdtemp(), "nope.json")
        self.assertIsNone(CalibrationModel.load_default(missing))

    def test_load_default_reads_file(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=250.0, n_runs=5)
        path = os.path.join(tempfile.mkdtemp(), "model.json")
        cm.save(path)
        self.assertEqual(CalibrationModel.load_default(path), cm)

    def test_expedition_delegates_to_load_default(self):
        from unittest.mock import patch
        from claytonlib.expedition import Expedition
        sentinel = CalibrationModel(kind="line", beta=0.06, alpha=250.0, n_runs=7)
        with patch("claytonlib.calibration.CalibrationModel.load_default",
                   return_value=sentinel):
            got = Expedition("loopback-test").calibration_model()
        self.assertEqual(got, sentinel)


if __name__ == "__main__":
    unittest.main()
