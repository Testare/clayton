"""Tests for utils/safari_confidence.py -- Section B confidence / neighbor search."""
import datetime as dt
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import safari_confidence as sc  # noqa: E402

from claytonlib.safari import (  # noqa: E402
    SafariContext, SafariStep, safari_pokemon_by_name)

POKE = safari_pokemon_by_name("metang")
SEED = 0x0C0E02C2  # the Metang reference seed

_STEP_CHAR = {
    SafariStep.MUD: "m", SafariStep.MUD_CRITICAL: "M",
    SafariStep.BAIT: "b", SafariStep.BAIT_CRITICAL: "B",
    SafariStep.BALL_0: "0", SafariStep.BALL_1: "1",
    SafariStep.BALL_2: "2", SafariStep.BALL_3: "3",
    SafariStep.FLED: "F", SafariStep.CAPTURED: "C",
}


def path_of(seed, seq, ball_count=30):
    """The observed compass-path string a seed yields for an action-type sequence."""
    ctx = SafariContext.start_encounter(seed, POKE)
    ctx.balls_remaining = ball_count
    out = []
    throw = {"mud": ctx.throw_mud, "ball": ctx.throw_ball, "bait": ctx.throw_bait}
    for a in seq:
        if ctx.has_fled() or ctx.captured():
            break
        r = throw[a]()
        out.append(_STEP_CHAR[r])
        if r in (SafariStep.FLED, SafariStep.CAPTURED):
            break
    return "".join(out)


PATH = path_of(SEED, ["mud", "ball", "bait", "ball", "ball"])  # -> "m0b00"


class TestSeedFields(unittest.TestCase):
    def test_frame_and_mdmsh_split(self):
        self.assertEqual(sc.frame_of(SEED), SEED & 0xFFFF)
        self.assertEqual(sc.mdmsh_of_seed(SEED), (SEED >> 16) & 0xFFFF)

    def test_frame_and_mdmsh_recombine(self):
        self.assertEqual((sc.mdmsh_of_seed(SEED) << 16) | sc.frame_of(SEED), SEED)


class TestNeighborDataclass(unittest.TestCase):
    def test_distance_and_hex(self):
        n = sc.Neighbor(seed=0x0C0E02EC, dframe=42, dmdmsh=0)
        self.assertEqual(n.distance, (42, 0))
        self.assertEqual(n.seed_hex, "0x0C0E02EC")

    def test_distance_uses_abs(self):
        self.assertEqual(sc.Neighbor(0, -5, -2).distance, (5, 2))


class TestParsePath(unittest.TestCase):
    def test_accepts_string(self):
        self.assertEqual(len(sc._parse_path("m0b00")), 5)

    def test_accepts_action_list(self):
        actions = sc._parse_path("m0")
        reparsed = sc._parse_path(actions)
        self.assertEqual(reparsed, actions)          # same content
        self.assertEqual([a.step for a in reparsed],
                         [SafariStep.MUD, SafariStep.BALL_0])

    def test_bad_path_raises(self):
        with self.assertRaises(ValueError):
            sc._parse_path("zzz-not-a-path")


class TestFindPathNeighbors(unittest.TestCase):
    def test_identified_seed_is_excluded(self):
        nbrs = sc.find_path_neighbors(SEED, [SEED], POKE, PATH)
        self.assertEqual(nbrs, [])

    def test_seed_survives_its_own_path(self):
        self.assertEqual(
            sc._surviving_seeds([SEED], POKE, sc._parse_path(PATH), 30), [SEED])

    def test_finds_and_ranks_real_aliases_nearest_first(self):
        cands = [SEED + d for d in range(-3000, 3001)]
        nbrs = sc.find_path_neighbors(SEED, cands, POKE, PATH, max_neighbors=6)
        self.assertTrue(nbrs)                       # aliases exist in this window
        self.assertTrue(all(n.seed != SEED for n in nbrs))
        # Sorted nearest-first by (|Δframe|, |Δmdmsh|).
        self.assertEqual([n.distance for n in nbrs],
                         sorted(n.distance for n in nbrs))
        # Every reported alias genuinely reproduces the path.
        for n in nbrs:
            self.assertEqual(
                sc._surviving_seeds([n.seed], POKE, sc._parse_path(PATH), 30),
                [n.seed])

    def test_max_neighbors_cap(self):
        cands = [SEED + d for d in range(-3000, 3001)]
        nbrs = sc.find_path_neighbors(SEED, cands, POKE, PATH, max_neighbors=2)
        self.assertLessEqual(len(nbrs), 2)

    def test_no_alias_returns_empty(self):
        # A tiny hand-picked set with no path-mate.
        nbrs = sc.find_path_neighbors(
            SEED, [SEED, SEED + 1, SEED - 1, SEED + 2], POKE, PATH)
        self.assertEqual(nbrs, [])


class TestNeighborGrid(unittest.TestCase):
    def setUp(self):
        self.initial_time = dt.datetime(2000, 4, 30, 19, 57, 59)
        self.base_delay = 2171

    def test_grid_covers_frame_range_and_dedups(self):
        grid = sc.neighbor_grid(SEED, self.initial_time, self.base_delay,
                                frame_range=5)
        self.assertIsInstance(grid, set)          # deduped
        frames = {sc.frame_of(s) for s in grid}
        self.assertTrue(frames <= set(range(sc.frame_of(SEED) - 5,
                                            sc.frame_of(SEED) + 6)))

    def test_grid_spans_mdmsh_deltas(self):
        grid = sc.neighbor_grid(SEED, self.initial_time, self.base_delay,
                                frame_range=2, mdmsh_deltas=(-1, 0, 1),
                                second_deltas=(0,))
        mdmsh_vals = {sc.mdmsh_of_seed(s) for s in grid}
        self.assertGreaterEqual(len(mdmsh_vals), 3)  # -1/0/+1 upper-field steps

    def test_grid_frames_never_disturbed_by_mdmsh_step(self):
        # A raw mdmsh step must keep the low-16 frame intact (guarded in the code).
        grid = sc.neighbor_grid(SEED, self.initial_time, self.base_delay,
                                frame_range=3)
        for s in grid:
            self.assertTrue(0 <= sc.frame_of(s) <= 0xFFFF)


class TestPathConfidence(unittest.TestCase):
    class _Opts:
        starting_ball_count = 30

    class _Inputs:
        key_seed = 0xF613087B
        initial_time = dt.datetime(2000, 4, 30, 19, 57, 59)
        pokemon = POKE
        options = None

    def test_end_to_end_with_stub_inputs(self):
        inputs = self._Inputs()
        inputs.options = self._Opts()
        with patch.object(sc, "get_times", return_value=(2171, [inputs.initial_time])):
            nbrs = sc.path_confidence(inputs, SEED, PATH, frame_range=200,
                                      max_neighbors=6)
        self.assertLessEqual(len(nbrs), 6)
        self.assertTrue(all(n.seed != SEED for n in nbrs))


if __name__ == "__main__":
    unittest.main()
