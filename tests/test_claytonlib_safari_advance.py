"""Tests for claytonlib.safari_advance — the app-facing port of utils/safari_advance.py's
pure functions (see tests/test_safari_advance.py for the exhaustive original-module suite;
this covers the ported subset plus the one behavior change: margin_guide returns
(guide, truncated) instead of printing a warning)."""
import unittest
from unittest.mock import patch

from claytonlib import safari_advance as sa

# Same worked example as tests/test_safari_advance.py (notes/safari_calibration_notebook.md).
EX_RNG_CALLS = 3
EX_ELM = "KKPEKEEPPEKK"


class TestFrameCandidates(unittest.TestCase):
    def test_ambiguous_then_disambiguated(self):
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEK"), [8, 14])
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEKE"), [9])
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEKK"), [15])

    def test_raw_input_is_cleaned(self):
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "p e k"), [8, 14])

    def test_calls_absent_from_sequence_give_no_frame(self):
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "KKK"), [])

    def test_max_offset_drops_late_matches(self):
        self.assertEqual(
            sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEK", max_offset=2), [8])


class TestAdvanceContext(unittest.TestCase):
    def test_matches_real_generation_and_recovers_true_frame(self):
        seed = 0x0C0E02C2
        prev_routes = {"r": 0, "e": 0, "l": 0}
        rng_calls, elm = sa.advance_context(seed, prev_routes, count=128)
        self.assertGreater(len(elm), 40)
        true_frame = rng_calls + 30
        i = true_frame - rng_calls
        heard = elm[i - 8:i]
        self.assertIn(true_frame, sa.frame_candidates(rng_calls, elm, heard))


class TestPlanAdvances(unittest.TestCase):
    def test_worked_example_frame_9_to_81(self):
        p = sa.plan_advances(9, 81)
        self.assertEqual(p.scent_frame, 81)
        self.assertEqual(p.total_advances, 72)
        self.assertEqual(p.chatot_advances, 69)
        self.assertEqual(p.chatot_flips, 34.5)
        self.assertEqual(p.land_frame, 78)
        self.assertEqual(p.elm_before_scent, 3)

    def test_short_distance_uses_only_elm_no_chatot(self):
        p = sa.plan_advances(79, 81)
        self.assertEqual(p.total_advances, 2)
        self.assertEqual(p.chatot_advances, 0)
        self.assertEqual(p.elm_before_scent, 2)

    def test_overshoot_raises(self):
        with self.assertRaises(ValueError):
            sa.plan_advances(90, 81)

    def test_one_or_two_leftover_advances_fold_into_elm_not_a_half_flip(self):
        p = sa.plan_advances(0, 5, margin=3)  # total=5, naive chatot=2 -> folds in
        self.assertEqual(p.chatot_advances, 0)
        self.assertEqual(p.elm_before_scent, 5)


class TestMarginGuideAndAmbiguity(unittest.TestCase):
    def test_guide_brackets_the_margin_and_marks_scent(self):
        rng_calls, elm = sa.advance_context(0x0D0E02BA, {}, count=150)
        plan = sa.plan_advances(rng_calls, rng_calls + 81)
        guide, truncated = sa.margin_guide(rng_calls, elm, plan)
        self.assertFalse(truncated)
        self.assertIn("[", guide)
        self.assertIn("]!", guide)
        bracket = guide[guide.index("[") + 1:guide.index("]")]
        self.assertEqual(len(bracket), plan.elm_before_scent)

    def test_truncated_when_elm_too_short(self):
        rng_calls, elm = sa.advance_context(0x0D0E02BA, {}, count=10)
        plan = sa.plan_advances(rng_calls, rng_calls + 81)  # needs far more than 10 calls
        _guide, truncated = sa.margin_guide(rng_calls, elm, plan)
        self.assertTrue(truncated)

    def test_land_frame_before_rel_end_raises(self):
        plan = sa.plan_advances(0, 1)  # land_frame will be < rng_calls if rng_calls > 0
        with self.assertRaises(ValueError):
            sa.margin_guide(5, "PEK", plan)

    def test_ambiguous_repeat_is_flagged(self):
        # bracket "EEE" immediately followed by another "E" -> the pattern continues past the
        # bracket, so a one-off landing error would be invisible.
        rng_calls = 0
        elm = "EEEEE" + "K" * 20
        plan = sa.plan_advances(0, 3, margin=3)  # elm_before_scent=3, land_frame=0
        self.assertTrue(sa.margin_ambiguous(rng_calls, elm, plan))

    def test_unambiguous_when_bracket_is_bounded(self):
        rng_calls = 0
        elm = "K" + "EEE" + "K" * 20
        plan = sa.plan_advances(1, 4, margin=3)  # bracket = elm[1:4] = "EEE", bounded by K's
        self.assertFalse(sa.margin_ambiguous(rng_calls, elm, plan))


class TestDescribePlan(unittest.TestCase):
    def test_mentions_chatot_and_elm_steps(self):
        p = sa.plan_advances(9, 81)
        text = sa.describe_plan(p, guide="EKPPK[PKE]!PPE")
        self.assertIn("chatot flips", text)
        self.assertIn("Elm calls", text)
        self.assertIn("Guide:", text)

    def test_no_chatot_line_when_none_needed(self):
        p = sa.plan_advances(79, 81)
        text = sa.describe_plan(p)
        self.assertIn("no chatot flips needed", text)


class TestFindInHouseFrame(unittest.TestCase):
    """clayton-b42.6.13: the in-house target-frame search (vs a Pokefinder handoff)."""

    _SEED = 0x0D0E02BA

    def test_finds_the_nearest_target_frame(self):
        res = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning",
                                     {"peak": 56}, target="metang")
        self.assertGreaterEqual(res["frame"], 3)  # respects the search_margin floor
        self.assertFalse(res["all_ambiguous"])

    def test_aim_advance_picks_closest_to_that_advance_not_the_nearest_overall(self):
        nearest = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning", {"peak": 56})
        aimed = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning", {"peak": 56},
                                       aim_advance=100)
        self.assertLessEqual(abs(aimed["frame"] - 100), abs(nearest["frame"] - 100))

    def test_raises_when_species_never_occupies_a_slot(self):
        with self.assertRaises(ValueError):
            sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning", {},
                                   target="not-a-real-species")

    def test_search_margin_is_a_floor_on_the_returned_frame(self):
        res = sa.find_in_house_frame(self._SEED, {}, 50, "Mountain", "morning",
                                     {"peak": 56}, search_margin=10)
        self.assertGreaterEqual(res["frame"], 60)


class TestSkippedAmbiguousCounting(unittest.TestCase):
    """clayton-b42.10.6: skipped_ambiguous must count only candidates genuinely NEARER to
    the aim than the chosen frame — an earlier version counted every ambiguous candidate in
    the whole search window regardless of distance, so it could report "skipped N nearer
    frame(s)" even when nothing was actually nearer (e.g. when the chosen frame was already
    the closest possible candidate), which is exactly what the user reported as confusing."""

    _SEED = 0x0D0E02BA

    def test_only_counts_ambiguous_candidates_nearer_than_the_chosen_one(self):
        # Frames 10 and 20 are ambiguous, 30 is clean -- aiming from current_frame=0 (so
        # distance == frame value). 30 is the nearest UNAMBIGUOUS candidate, so it's chosen;
        # both 10 and 20 are nearer to the aim AND ambiguous -> genuinely skipped in its favor.
        with patch("claytonlib.safari_encounters.iter_encounter_frames",
                  return_value=[(10, 5), (20, 5), (30, 5)]):
            with patch("claytonlib.safari_advance.margin_ambiguous",
                      side_effect=lambda rng_calls, elm, plan: plan.encounter_frame in (10, 20)):
                res = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning", {"peak": 56})
        self.assertEqual(res["frame"], 30)
        self.assertEqual(res["skipped_ambiguous"], 2)
        self.assertFalse(res["all_ambiguous"])

    def test_does_not_count_ambiguous_candidates_farther_than_the_chosen_one(self):
        # Frame 10 (clean) is already the nearest of ALL candidates -- 20 and 30 being
        # ambiguous is irrelevant, since neither was ever in contention (both are FARTHER
        # from the aim than 10, so 10 wins on distance alone regardless of ambiguity).
        with patch("claytonlib.safari_encounters.iter_encounter_frames",
                  return_value=[(10, 5), (20, 5), (30, 5)]):
            with patch("claytonlib.safari_advance.margin_ambiguous",
                      side_effect=lambda rng_calls, elm, plan: plan.encounter_frame in (20, 30)):
                res = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning", {"peak": 56})
        self.assertEqual(res["frame"], 10)
        self.assertEqual(res["skipped_ambiguous"], 0)

    def test_all_ambiguous_reports_zero_skipped_for_the_closest_pick(self):
        # Every candidate is ambiguous, so the closest one is used anyway (all_ambiguous=True)
        # -- and since it's the closest, nothing was skipped in ITS favor either.
        with patch("claytonlib.safari_encounters.iter_encounter_frames",
                  return_value=[(10, 5), (20, 5)]):
            with patch("claytonlib.safari_advance.margin_ambiguous", return_value=True):
                res = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning", {"peak": 56})
        self.assertTrue(res["all_ambiguous"])
        self.assertEqual(res["frame"], 10)
        self.assertEqual(res["skipped_ambiguous"], 0)

    def test_exact_aim_match_always_reports_zero_skipped(self):
        # aim_advance lands EXACTLY on a candidate frame -- nothing could possibly be
        # nearer than a zero-distance match, so skipped_ambiguous must be 0 regardless of
        # how many OTHER, farther candidates happen to be ambiguous (the user's second
        # reported case: "it landed exactly on target, how could it have skipped frames?").
        with patch("claytonlib.safari_encounters.iter_encounter_frames",
                  return_value=[(100, 5), (150, 5), (200, 5)]):
            with patch("claytonlib.safari_advance.margin_ambiguous",
                      side_effect=lambda rng_calls, elm, plan: plan.encounter_frame in (150, 200)):
                res = sa.find_in_house_frame(self._SEED, {}, 0, "Mountain", "morning",
                                             {"peak": 56}, aim_advance=100)
        self.assertEqual(res["frame"], 100)
        self.assertEqual(res["skipped_ambiguous"], 0)


if __name__ == "__main__":
    unittest.main()
