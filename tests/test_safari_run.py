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
        # tag, delay, cal, fresh_boot, prior_battles, notes, confirm
        answers = ["safari test", "300000", "-5000", "", "", "", "y"]
        with _answers(answers):
            rec = ct.save_safari_run(["0x0C0E02CA"], path="mmb0F", save_path=p)
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
        self.assertEqual(r["target_timer_calibration"], -5000)
        self.assertTrue(r["fresh_boot"])
        self.assertEqual(r["prior_battles"], 0)
        self.assertIsNone(r["delay"])  # no inputs given -> not derivable

    def test_ambiguous_leaves_seed_null(self):
        p = self._path()
        answers = ["amb", "300000", "-5000", "y", "1", "", "y"]
        with _answers(answers):
            rec = ct.save_safari_run(["0xAAAA1111", "0xBBBB2222"], path="mm0", save_path=p)
        self.assertIsNotNone(rec)
        r = self._read(p)[0]
        self.assertIsNone(r["seed"])
        self.assertIsNone(r["seed_hex"])
        self.assertEqual(r["n_matched"], 2)
        self.assertEqual(r["prior_battles"], 1)
        self.assertEqual(len(r["matched_seeds"]), 2)

    def test_decline_does_not_write(self):
        p = self._path()
        answers = ["t", "300000", "0", "", "", "", "n"]
        with _answers(answers):
            rec = ct.save_safari_run(["0x1"], path="F", save_path=p)
        self.assertIsNone(rec)
        self.assertFalse(os.path.exists(p))

    def test_path_prompted_when_omitted(self):
        p = self._path()
        # path not passed -> extra "Safari path" prompt inserted before notes
        answers = ["t", "300000", "0", "", "", "bb0C", "notes here", "y"]
        with _answers(answers):
            ct.save_safari_run(["0x2"], save_path=p)
        r = self._read(p)[0]
        self.assertEqual(r["path"], "bb0C")
        self.assertEqual(r["notes"], "notes here")

    def test_defaults_from_previous_run(self):
        p = self._path()
        with _answers(["first", "420000", "-5000", "", "", "", "y"]):
            ct.save_safari_run(["0x3"], path="F", save_path=p)
        # blank tag/delay/cal -> reuse previous (420000/-5000); blank fresh -> True
        with _answers(["", "", "", "", "", "", "y"]):
            ct.save_safari_run(["0x4"], path="C", save_path=p)
        rows = self._read(p)
        self.assertEqual(rows[1]["tag"], "first")
        self.assertEqual(rows[1]["target_timer_delay"], 420000)
        self.assertEqual(rows[1]["target_timer_calibration"], -5000)

    def test_load_safari_runs(self):
        p = self._path()
        with _answers(["t", "300000", "0", "", "", "", "y"]):
            ct.save_safari_run(["0x5"], path="F", save_path=p)
        rows = ct.load_safari_runs(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seed"], 5)


if __name__ == "__main__":
    unittest.main()
