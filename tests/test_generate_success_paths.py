"""Tests for utils/generate_success_paths.py (path -> slurper command conversion + full path build)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import generate_success_paths as gsp  # noqa: E402
import safari_reader as sr  # noqa: E402
from claytonlib.safari import safari_pokemon_by_name  # noqa: E402


class TestPathToCommand(unittest.TestCase):
    def test_example_from_spec(self):
        self.assertEqual(gsp.path_to_command("bbbMm031mC"), "3b2m3c1m1c")

    def test_crit_tokens_share_their_type(self):
        # B/b are the same action type (bait); M/m the same (mud).
        self.assertEqual(gsp.path_to_command("bBBm"), "3b1m")
        self.assertEqual(gsp.path_to_command("MMMM"), "4m")

    def test_all_ball_tokens_are_type_c(self):
        self.assertEqual(gsp.path_to_command("0123C"), "5c")

    def test_single_group(self):
        self.assertEqual(gsp.path_to_command("bbbbbb"), "6b")

    def test_flee_token_rejected(self):
        with self.assertRaises(ValueError):
            gsp.path_to_command("bbF")

    def test_command_round_trips_through_slurper_parser(self):
        # The emitted command must decode (via the slurper's own parser) to the exact
        # per-turn action-type sequence of the path.
        path = "bbbMm031mC"
        cmd = gsp.path_to_command(path)
        tmap = {"b": "B", "B": "B", "m": "M", "M": "M",
                "0": "C", "1": "C", "2": "C", "3": "C", "C": "C"}
        self.assertEqual(sr.expand_action_script(cmd), [tmap[c] for c in path])


class TestBuildFullPath(unittest.TestCase):
    def test_known_metang_seed_captures_with_fixed_prefix(self):
        poke = safari_pokemon_by_name("metang")
        full, note = gsp.build_full_path(0x080E2B7C, poke, balls=30, max_turns=None)
        self.assertIsNone(note)
        self.assertIsNotNone(full)
        self.assertTrue(full.endswith("C"))
        # first 6 tokens are bait, next 5 are balls (the fixed chart prefix).
        self.assertTrue(all(c in "bB" for c in full[:6]), full[:6])
        self.assertTrue(all(c in "0123C" for c in full[6:11]), full[6:11])


if __name__ == "__main__":
    unittest.main()
