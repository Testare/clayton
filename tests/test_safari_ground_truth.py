"""Validate claytonlib's safari model against the emulator ground truth (safari_seeds/*.jsonl).

Reconstructs each recorded battle's path from its logged messages and replays it through
claytonlib (utils/validate_safari); a match means claytonlib reproduces the emulator.  Skips
cleanly when no ground-truth data is present (the JSONL files are gathered artifacts).
"""
import glob
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import validate_safari as vs  # noqa: E402

GT_DIR = os.path.join(os.path.dirname(__file__), "..", "safari_seeds")

# (seed, reconstructed path) records where claytonlib is KNOWN to diverge from the emulator.
# Empty: the safari catch-rate /3 fix (clayton-ctd.15) makes claytonlib reproduce all recorded
# battles.  Add an entry here (with a tracking bead) if a new divergence is found.
KNOWN_DIVERGENCES: set = set()


class TestSafariGroundTruth(unittest.TestCase):
    def test_claytonlib_reproduces_emulator_paths(self):
        files = sorted(glob.glob(os.path.join(GT_DIR, "*.jsonl")))
        if not files:
            self.skipTest("no safari_seeds/*.jsonl ground-truth data")
        for path in files:
            for r in vs.validate_file(path):
                key = (r["seed"], r["gt_path"])
                with self.subTest(file=os.path.basename(path), seed=r["seed"],
                                  path=r["gt_path"]):
                    if key in KNOWN_DIVERGENCES:
                        self.assertFalse(
                            r["matched"],
                            "known divergence now MATCHES -- remove it from KNOWN_DIVERGENCES "
                            "(clayton-ctd.15 fixed?)")
                    else:
                        self.assertTrue(
                            r["matched"],
                            f"claytonlib diverges from emulator at token {r['diverge_index']}: "
                            f"observed {r['gt_path']!r} vs claytonlib {r['generated']!r}")


if __name__ == "__main__":
    unittest.main()
