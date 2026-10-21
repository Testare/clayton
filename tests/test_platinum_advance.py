"""Platinum's advance frame: identification from pitches, and the Journal-flip route.

The claim this file exists to defend is that the route arithmetic is **shared**, not reimplemented:
Platinum's bulk unit (a Journal flip) is 2 advances just like an HGSS chatot flip, and its margin
unit (a chatot cry) is 1 just like an Elm call, so `safari_advance.plan_advances` serves both. If
someone later "simplifies" that into two code paths, the agreement tests here fail.

Also pinned: `safari_advance`'s Elm primitives still behave exactly as before, since every Elm
caller in the app depends on that — and that there is **no pitch identification at all**. A pitch
is output: the player knows their frame by arithmetic (loaded on frame 0, counting what they do)
and the margin is how they check it, so nothing here parses or searches for one (clayton-6xu.5).
"""
import unittest

from claytonlib.chatot_pitch import bucket_of, format_sequence, pitch_values
from claytonlib.platinum_advance import (
    DEFAULT_PITCH_MARGIN, JOURNAL_FLIP_ADVANCES, PLATINUM_START_FRAME, filter_flips,
    generate_flip_candidates_near, pitch_context, plan_route,
)
from claytonlib.safari_advance import (
    _all_start_positions, frame_candidates, margin_ambiguous, margin_guide, plan_advances,
)

SEED = 0x0C0E02CA


class TestGeneralisedPrimitivesKeepTheElmBehaviour(unittest.TestCase):
    """The HGSS path is reached from four facade methods; it must not have moved."""

    def test_string_search_finds_overlapping_positions(self):
        self.assertEqual(_all_start_positions("PEPEPE", "PE"), [0, 2, 4])

    def test_empty_needle_matches_every_position(self):
        self.assertEqual(_all_start_positions("PEK", ""), [0, 1, 2, 3])

    def test_raw_elm_input_is_still_cleaned(self):
        """Lower case and stray punctuation were always forgiven for Elm input."""
        self.assertEqual(frame_candidates(5, "PEEKP", "e ek"), frame_candidates(5, "PEEKP", "EEK"))

    def test_elm_guide_still_renders_bare_letters(self):
        plan = plan_advances(10, 20, margin=3)
        guide, truncated = margin_guide(0, "P" * 40, plan)
        self.assertEqual(guide, "PPPPP[PPP]!PPP")
        self.assertFalse(truncated)


class TestPitchContext(unittest.TestCase):

    def test_returns_the_offset_it_was_given(self):
        """Unlike HGSS, the leading offset is given rather than derived -- there is no REL."""
        offset, pitches = pitch_context(SEED, count=5, start_frame=23)
        self.assertEqual(offset, 23)
        self.assertEqual(pitches, pitch_values(SEED, 5))

    def test_default_offset_is_zero(self):
        self.assertEqual(pitch_context(SEED, count=1)[0], 0)


class TestPlanRoute(unittest.TestCase):

    def test_journal_flips_are_two_advances_each(self):
        plan = plan_route(SEED, 40, current_frame=0)
        self.assertEqual(plan["journal_advances"],
                         plan["journal_flips"] * JOURNAL_FLIP_ADVANCES)

    def test_the_bulk_is_always_even_because_there_is_no_half_journal_flip(self):
        """HGSS tolerates an odd bulk (half a chatot flip is one cry); a Journal page turn is
        2 advances or nothing, so an odd bulk would be unperformable."""
        for target in range(1, 60):
            plan = plan_route(SEED, target, current_frame=0)
            self.assertEqual(plan["journal_advances"] % 2, 0, f"target {target}")
            self.assertEqual(plan["journal_flips"], plan["journal_advances"] // 2)

    def test_the_leftover_advance_becomes_an_extra_cry(self):
        """Shifting it into the margin costs nothing and lengthens the readable part by one."""
        plan = plan_route(SEED, 30, current_frame=4, margin=3)
        self.assertEqual(plan["cries_before_target"], 4)
        self.assertEqual(plan["journal_advances"], 22)

    def test_the_pieces_add_up_to_the_distance(self):
        for current, target in ((0, 40), (4, 30), (10, 11), (7, 7)):
            plan = plan_route(SEED, target, current_frame=current)
            self.assertEqual(plan["journal_advances"] + plan["cries_before_target"],
                             target - current, f"{current} -> {target}")
            self.assertEqual(plan["total_advances"], target - current)

    def test_land_frame_is_where_the_flips_leave_you(self):
        plan = plan_route(SEED, 30, current_frame=4)
        self.assertEqual(plan["land_frame"], 4 + plan["journal_advances"])
        self.assertEqual(plan["land_frame"] + plan["cries_before_target"], 30)

    def test_a_short_distance_is_all_cries(self):
        plan = plan_route(SEED, 12, current_frame=10)
        self.assertEqual(plan["journal_flips"], 0)
        self.assertEqual(plan["cries_before_target"], 2)

    def test_a_zero_distance_plans_nothing(self):
        plan = plan_route(SEED, 10, current_frame=10)
        self.assertEqual((plan["journal_flips"], plan["cries_before_target"]), (0, 0))

    def test_a_backwards_route_raises(self):
        with self.assertRaises(ValueError):
            plan_route(SEED, 10, current_frame=20)

    def test_guide_shows_numbers_in_the_margin_and_buckets_around_it(self):
        """The decided display: the margin is what you listen to, so it carries the exact
        number; the context only has to be recognisable if you land early or overshoot."""
        plan = plan_route(SEED, 30, current_frame=4)
        guide = plan["guide"]
        inside = guide[guide.index("[") + 1:guide.index("]")]
        before = guide[:guide.index("[")]
        self.assertIn("(", inside)
        self.assertNotIn("(", before)
        # Every bracketed token is a bucket with its number, and there is one per cry.
        self.assertEqual(inside.count("("), plan["cries_before_target"])

    def test_guide_marks_the_target_frame_after_the_bracket(self):
        self.assertIn("]!", plan_route(SEED, 30, current_frame=4)["guide"])

    def test_description_speaks_platinum_and_carries_no_encounter_verb(self):
        """Glass learned this once already: a route that ends in "then Sweet Scent" is true of an
        expedition and meaningless for a Seed (notes/glass.md, As built)."""
        text = plan_route(SEED, 30, current_frame=4)["description"]
        self.assertIn("Journal flips", text)
        self.assertIn("Chatot cries", text)
        for verb in ("Sweet Scent", "rod", "cast"):
            self.assertNotIn(verb, text)

    def test_one_cry_is_singular(self):
        self.assertIn("1 Chatot cry", plan_route(SEED, 11, current_frame=10)["description"])

    def test_ambiguity_is_judged_in_buckets(self):
        """What a 1-2 frame landing error would look like is a question about what the player
        HEARS, and they hear a bucket -- so ambiguity compares buckets, not exact values."""
        offset, pitches = pitch_context(SEED, count=80)
        plan = plan_advances(4, 30, margin=4)
        same_bucket = lambda a, b: bucket_of(a) == bucket_of(b)
        # The bucket-level test is weaker than exact equality, so it can only ever flag MORE.
        exact = margin_ambiguous(offset, pitches, plan)
        bucketed = margin_ambiguous(offset, pitches, plan, same=same_bucket)
        self.assertTrue(bucketed or not exact)

    def test_a_flagged_margin_really_does_repeat(self):
        """Find a seed/target whose margin is ambiguous, and show the repeat exists."""
        offset, pitches = pitch_context(SEED, count=400)
        same_bucket = lambda a, b: bucket_of(a) == bucket_of(b)
        found = False
        for target in range(10, 200):
            plan = plan_advances(0, target, margin=2)
            if margin_ambiguous(offset, pitches, plan, same=same_bucket):
                lo = plan.land_frame
                hi = lo + plan.elm_before_scent
                bracket = [bucket_of(v) for v in pitches[lo:hi]]
                shifted = [[bucket_of(v) for v in pitches[lo + p:hi + p]] for p in (-2, -1, 1, 2)]
                self.assertIn(bracket, shifted, f"target {target} flagged but nothing repeats")
                found = True
                break
        self.assertTrue(found, "no ambiguous margin found in 190 targets -- widen the search")

    def test_default_margin_is_three_cries(self):
        plan = plan_route(SEED, 40, current_frame=0)
        self.assertLessEqual(DEFAULT_PITCH_MARGIN, plan["cries_before_target"])
        self.assertLessEqual(plan["cries_before_target"], DEFAULT_PITCH_MARGIN + 1)


class TestAgreementWithTheHgssArithmetic(unittest.TestCase):
    """The two games' routes are the same plan with different nouns. Pin that."""

    def test_same_distance_splits_the_same_way_when_the_bulk_is_even(self):
        # 41 - 3 = 38, already even, so there is no parity shift and the two must agree exactly.
        hgss = plan_advances(0, 41, margin=3)
        platinum = plan_route(SEED, 41, current_frame=0, margin=3)
        self.assertEqual(hgss.chatot_advances, platinum["journal_advances"])
        self.assertEqual(hgss.elm_before_scent, platinum["cries_before_target"])
        self.assertEqual(hgss.land_frame, platinum["land_frame"])

    def test_platinum_differs_from_hgss_only_by_the_parity_shift(self):
        """When HGSS would leave an odd bulk, Platinum moves exactly one advance to the margin."""
        hgss = plan_advances(4, 30, margin=3)
        platinum = plan_route(SEED, 30, current_frame=4, margin=3)
        self.assertEqual(hgss.chatot_advances % 2, 1)           # 23, i.e. 11.5 flips
        self.assertEqual(platinum["journal_advances"], hgss.chatot_advances - 1)
        self.assertEqual(platinum["cries_before_target"], hgss.elm_before_scent + 1)


class TestFlipCandidates(unittest.TestCase):
    """The flips half of identification: which seed, at no cost to the advance frame."""

    def setUp(self):
        import datetime as dt
        self.when = dt.datetime(2026, 6, 15, 21, 30, 30)
        self.delay = 650          # the community figure for DPPt's minimum delay
        self.rows = generate_flip_candidates_near(self.when, self.delay, 1, 20)

    def _truth(self):
        """The row at the centre of the grid -- zero delta on both axes."""
        return next(r for r in self.rows
                    if r["delay_delta"] == 0 and r["sec_delta"] == 0)

    def test_the_grid_covers_both_windows(self):
        self.assertEqual({r["delay_delta"] for r in self.rows}, set(range(-20, 21)))
        self.assertEqual({r["sec_delta"] for r in self.rows}, {-1, 0, 1})

    def test_rows_are_ordered_by_time_then_delay(self):
        keys = [(r["time"], r["delay"]) for r in self.rows]
        self.assertEqual(keys, sorted(keys))

    def test_every_row_carries_both_signals(self):
        for row in self.rows:
            self.assertEqual(len(row["flips"]), 20)
            self.assertEqual(set(row["flips"]) - {"H", "T"}, set())
            self.assertEqual(len(row["pitches"]), 12)
            self.assertIn("(", row["pitch_display"])

    def test_seeds_are_unique(self):
        seeds = [r["seed"] for r in self.rows]
        self.assertEqual(len(set(seeds)), len(seeds))

    def test_the_seed_matches_the_shared_formula(self):
        from claytonlib.calibration_tools import seed_for
        row = self._truth()
        self.assertEqual(row["seed"], seed_for(row["time"], row["delay"]))

    def test_match_parity_halves_the_grid(self):
        parity = generate_flip_candidates_near(self.when, self.delay, 1, 20, match_parity=True)
        self.assertTrue(all(r["delay"] % 2 == self.delay % 2 for r in parity))
        self.assertLess(len(parity), len(self.rows))

    def test_negative_delays_are_skipped(self):
        rows = generate_flip_candidates_near(self.when, 3, 0, 10)
        self.assertTrue(all(r["delay"] >= 0 for r in rows))

    def test_no_observation_keeps_everything(self):
        self.assertEqual(len(filter_flips(self.rows, "")), len(self.rows))

    def test_the_true_seed_always_survives_its_own_flips(self):
        truth = self._truth()
        for n in range(len(truth["flips"]) + 1):
            self.assertIn(truth, filter_flips(self.rows, truth["flips"][:n]), f"{n} flips")

    def test_ten_flips_pin_a_single_candidate(self):
        """The claim the UI makes to the player. ~123 candidates, one bit per flip."""
        truth = self._truth()
        survivors = filter_flips(self.rows, truth["flips"][:10])
        self.assertEqual(survivors, [truth])

    def test_narrowing_is_monotonic(self):
        truth = self._truth()
        counts = [len(filter_flips(self.rows, truth["flips"][:n])) for n in range(0, 13)]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_filtering_is_a_prefix_test_not_a_search(self):
        """Unlike Elm calls, there is no unknown join offset: the coin app is opened fresh."""
        truth = self._truth()
        shifted = truth["flips"][2:8]
        if not truth["flips"].startswith(shifted):
            self.assertNotIn(truth, filter_flips(self.rows, shifted))

    def test_rtc_second_siblings_are_separated_by_flips(self):
        """The axis Battle Compass defaults `second_window` to 0 to avoid, made cheap."""
        truth = self._truth()
        siblings = [r for r in self.rows
                    if r["delay"] == truth["delay"] and r["sec_delta"] != 0]
        self.assertTrue(siblings)
        survivors = filter_flips(self.rows, truth["flips"][:10])
        for sibling in siblings:
            self.assertNotIn(sibling, survivors)

    def test_flips_cost_no_advances_so_narrowing_does_not_move_the_frame(self):
        """The property that makes this nicer than HGSS: the two signals are different
        generators, so narrowing by flips leaves the advance frame exactly where it was -- which
        is why a freshly identified Platinum seed is still on PLATINUM_START_FRAME."""
        truth = self._truth()
        before = pitch_context(truth["seed"], count=8)
        filter_flips(self.rows, truth["flips"][:10])
        self.assertEqual(pitch_context(truth["seed"], count=8), before)
        self.assertEqual(PLATINUM_START_FRAME, 0)


if __name__ == "__main__":
    unittest.main()
