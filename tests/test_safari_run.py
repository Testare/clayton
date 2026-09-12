"""Tests for save_safari_run / load_safari_runs (safari-compass run persistence)."""
import builtins
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import calibration_tools as ct  # noqa: E402


@contextmanager
def _answers(seq):
    """Feed `seq` to builtins.input in order, restoring it afterwards."""
    it = iter(seq)
    orig = builtins.input
    builtins.input = lambda prompt="": next(it)
    try:
        yield
    finally:
        builtins.input = orig


class TestSaveSafariRun(unittest.TestCase):
    def _path(self):
        return os.path.join(tempfile.mkdtemp(), "safari_runs.jsonl")

    def _read(self, path):
        with open(path) as f:
            return [json.loads(l) for l in f if l.strip()]

    def test_unique_seed_recorded(self):
        p = self._path()
        # Only three prompts now: tag, notes, confirm.  target_timer_delay is passed in; there is
        # no timer-calibration / fresh-boot / prior-battles prompt for safari runs.
        with _answers(["safari test", "", "y"]):
            rec = ct.save_safari_run(["0x0C0E02CA"], path="mmb0F", save_path=p,
                                     target_timer_delay=300000)
        self.assertIsNotNone(rec)
        rows = self._read(p)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["seed"], 0x0C0E02CA)
        self.assertEqual(r["seed_hex"], "0x0C0E02CA")
        self.assertEqual(r["n_matched"], 1)
        self.assertEqual(r["matched_seeds"], ["0x0C0E02CA"])
        self.assertEqual(r["path"], "mmb0F")
        self.assertEqual(r["target_timer_delay"], 300000)
        # Dropped for safari runs: calibration, fresh_boot, prior_battles.
        self.assertNotIn("target_timer_calibration", r)
        self.assertNotIn("fresh_boot", r)
        self.assertNotIn("prior_battles", r)
        self.assertIsNone(r["delay"])  # no inputs given -> not derivable
        self.assertIsNone(r["frame_delta"])  # no target frame without inputs

    def test_ambiguous_leaves_seed_null(self):
        p = self._path()
        with _answers(["amb", "", "y"]):
            rec = ct.save_safari_run(["0xAAAA1111", "0xBBBB2222"], path="mm0", save_path=p,
                                     target_timer_delay=300000)
        self.assertIsNotNone(rec)
        r = self._read(p)[0]
        self.assertIsNone(r["seed"])
        self.assertIsNone(r["seed_hex"])
        self.assertEqual(r["n_matched"], 2)
        self.assertNotIn("prior_battles", r)                 # dropped
        self.assertEqual(len(r["matched_seeds"]), 2)

    def test_decline_does_not_write(self):
        p = self._path()
        with _answers(["t", "", "n"]):
            rec = ct.save_safari_run(["0x1"], path="F", save_path=p, target_timer_delay=300000)
        self.assertIsNone(rec)
        self.assertFalse(os.path.exists(p))

    def test_path_prompted_when_omitted(self):
        p = self._path()
        # path not passed -> a "Safari path" prompt is inserted between tag and notes.
        with _answers(["t", "bb0C", "notes here", "y"]):
            ct.save_safari_run(["0x2"], save_path=p, target_timer_delay=300000)
        r = self._read(p)[0]
        self.assertEqual(r["path"], "bb0C")
        self.assertEqual(r["notes"], "notes here")

    def test_defaults_from_previous_run(self):
        p = self._path()
        with _answers(["first", "", "y"]):
            ct.save_safari_run(["0x3"], path="F", save_path=p, target_timer_delay=420000)
        # blank tag -> reuse "first"; target_timer_delay omitted -> reuse previous (420000).
        with _answers(["", "", "y"]):
            ct.save_safari_run(["0x4"], path="C", save_path=p)
        rows = self._read(p)
        self.assertEqual(rows[1]["tag"], "first")
        self.assertEqual(rows[1]["target_timer_delay"], 420000)

    def test_load_safari_runs(self):
        p = self._path()
        with _answers(["t", "", "y"]):
            ct.save_safari_run(["0x5"], path="F", save_path=p, target_timer_delay=300000)
        rows = ct.load_safari_runs(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seed"], 5)

    def test_calibrated_inputs_record_frame_second_delta(self):
        # A calibrated CompassSafariInput lets the loop-back recover (frame, second, δ).
        import datetime as dt
        from unittest.mock import patch
        from claytonlib.calibration import CalibrationModel
        from claytonlib.safari import safari_pokemon_by_name
        from claytonlib.chart import STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE
        from claytonlib.compass import CompassSafariInput, calibrated_candidates

        KEY = 0xF613087B
        TIME_A = dt.datetime(2000, 4, 30, 19, 57, 59)

        def fake_get_times(key_seed):
            return key_seed & 0xFFFF, [TIME_A]

        model = CalibrationModel(kind="line", beta=0.06, alpha=float(KEY & 0xFFFF),
                                 jitter_c=0.128)
        with patch('claytonlib.times.get_times', side_effect=fake_get_times), \
             patch('claytonlib.compass._core.get_times', side_effect=fake_get_times):
            inp = CompassSafariInput.from_expedition_target(
                model=model, M=5000, initial_time=TIME_A, key_seed=KEY,
                max_target_seconds=30, pokemon=safari_pokemon_by_name('metang'),
                strategy=STRATEGY_ONLY_BALLS, criteria=CRITERIA_CAPTURE,
                second_offsets=(-1, 0, 1))
            cands, meta = calibrated_candidates(inp)
            seed = cands[len(cands) // 2][1]
            m = meta[seed]

            p = self._path()
            with _answers(["cal", "", "y"]):     # tag, notes, confirm
                rec = ct.save_safari_run([f"0x{seed:08X}"], inputs=inp,
                                         path="mmb0", save_path=p, target_timer_delay=5000)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["seed"], seed)
        self.assertEqual(rec["frame"], m["frame"])
        self.assertEqual(rec["second_offset"], m["delta"])
        self.assertEqual(rec["delay"], m["frame"])   # frame is the F_b analog
        self.assertIsNotNone(rec["second"])
        # Frame hit + target frame + signed miss are recorded (the calibration signal).
        self.assertEqual(rec["target_frame"], round(inp.frame_center))
        self.assertEqual(rec["frame_delta"], m["frame"] - round(inp.frame_center))
        self.assertNotIn("fresh_boot", rec)
        self.assertNotIn("prior_battles", rec)


if __name__ == "__main__":
    unittest.main()
