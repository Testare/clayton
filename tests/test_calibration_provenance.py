"""Tests for run-provenance handling in calibrate_timer (fresh-boot vs battle-contaminated)."""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import calibration_tools as ct  # noqa: E402


def _rec(M, Fb, prior_battles=0, fresh_boot=True, cal=0):
    """A minimal saved-run record: fresh boot at 14:45:55, battle Fb seconds' worth later."""
    ta = dt.datetime(2025, 1, 1, 14, 45, 55)
    tb = ta + dt.timedelta(seconds=round(M / 1000) + 5)
    return {
        "tag": "t", "target_timer_delay": M - cal, "target_timer_calibration": cal,
        "fresh_boot": fresh_boot, "prior_battles": prior_battles, "notes": "",
        "a_seed": {"seed": 1, "delay": 680, "time": ta.isoformat()},
        "b_seed": {"seed": 2, "delay": Fb, "time": tb.isoformat()},
    }


class TestProvenance(unittest.TestCase):
    def _write(self, records):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "runs.jsonl")
        with open(p, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        return p

    def test_parse_bool(self):
        for s in ("y", "yes", "true", "1"):
            self.assertTrue(ct._parse_bool(s))
        for s in ("n", "no", "false", "0"):
            self.assertFalse(ct._parse_bool(s))
        with self.assertRaises(ValueError):
            ct._parse_bool("maybe")

    def test_contaminated_excluded_by_default(self):
        # clean fresh-boot line F_b = 0.06*M + 680, plus a contaminated run 800 frames low.
        recs = [_rec(M, round(0.06 * M) + 680) for M in
                (180000, 240000, 300000, 360000, 420000)]
        recs.append(_rec(360000, round(0.06 * 360000) + 680 - 800, prior_battles=2, fresh_boot=False))
        p = self._write(recs)
        m = ct.calibrate_timer(path=p, verbose=False)
        self.assertEqual(m["n_contaminated"], 1)
        self.assertEqual(m["n_fit"], 5)  # the contaminated run is not in the fit
        # the contaminated run is flagged in the run table
        contaminated = [r for r in m["runs"] if r["contaminated"]]
        self.assertEqual(len(contaminated), 1)
        self.assertEqual(contaminated[0]["prior_battles"], 2)

    def test_fresh_only_false_includes_contaminated(self):
        recs = [_rec(M, round(0.06 * M) + 680) for M in (180000, 240000, 300000, 360000)]
        recs.append(_rec(360000, round(0.06 * 360000) + 680 - 800, prior_battles=1, fresh_boot=False))
        p = self._write(recs)
        m = ct.calibrate_timer(path=p, verbose=False, fresh_only=False)
        self.assertEqual(m["n_contaminated"], 0)
        self.assertEqual(m["n_fit"] + m["n_outliers"], m["n_runs"])

    def test_missing_provenance_treated_as_fresh(self):
        # Old-style records without the fields must be kept (0 contaminated).
        recs = []
        for M in (180000, 240000, 300000, 360000):
            r = _rec(M, round(0.06 * M) + 680)
            del r["prior_battles"]
            del r["fresh_boot"]
            recs.append(r)
        p = self._write(recs)
        m = ct.calibrate_timer(path=p, verbose=False)
        self.assertEqual(m["n_contaminated"], 0)
        self.assertEqual(m["n_fit"], 4)


if __name__ == "__main__":
    unittest.main()
