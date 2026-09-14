"""Tests for utils/safari_advance.py -- Section A Seed-A advance-frame identification."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import safari_advance as sa  # noqa: E402

# The plan doc's worked example (notes/safari_calibration_notebook.md, Section A):
# REL consumed 3 advances, and the seed's Elm string is "KKPEKEEPPEKK".
EX_RNG_CALLS = 3
EX_ELM = "KKPEKEEPPEKK"


class TestCleanElm(unittest.TestCase):
    def test_keeps_only_pek_uppercased(self):
        self.assertEqual(sa.clean_elm("p e,k"), "PEK")
        self.assertEqual(sa.clean_elm("PeKmXz E"), "PEKE")  # M and others dropped

    def test_empty(self):
        self.assertEqual(sa.clean_elm("  , . "), "")


class TestAllStartPositions(unittest.TestCase):
    def test_overlapping_matches_all_reported(self):
        self.assertEqual(sa._all_start_positions("AAAA", "AA"), [0, 1, 2])

    def test_no_match(self):
        self.assertEqual(sa._all_start_positions("KKPEK", "ZZ"), [])

    def test_empty_needle_matches_every_position(self):
        self.assertEqual(sa._all_start_positions("PEK", ""), [0, 1, 2, 3])


class TestFrameCandidatesWorkedExample(unittest.TestCase):
    """current_frame = rng_calls + match_position + len(observed)."""

    def test_pek_is_ambiguous_two_frames(self):
        # "PEK" occurs at positions 2 and 8 -> frames 3+2+3=8 and 3+8+3=14.
        self.assertEqual(
            sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEK"), [8, 14])

    def test_one_more_call_disambiguates_to_frame_9(self):
        # "PEKE" only at position 2 -> frame 3+2+4 = 9 (the "E" branch).
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEKE"), [9])

    def test_one_more_call_disambiguates_to_frame_15(self):
        # "PEKK" only at position 8 -> frame 3+8+4 = 15 (the "K" branch).
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEKK"), [15])

    def test_raw_input_is_cleaned(self):
        self.assertEqual(
            sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "p e k"), [8, 14])

    def test_no_calls_heard_spans_the_whole_window(self):
        # Empty -> position 0..len(elm) -> frames rng_calls .. rng_calls+len(elm).
        self.assertEqual(
            sa.frame_candidates(EX_RNG_CALLS, EX_ELM, ""),
            list(range(3, 3 + len(EX_ELM) + 1)))

    def test_calls_absent_from_sequence_give_no_frame(self):
        self.assertEqual(sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "KKK"), [])

    def test_max_offset_drops_late_matches(self):
        # Only the position-2 match survives max_offset=2 -> frame 8.
        self.assertEqual(
            sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEK", max_offset=2), [8])
        # Both survive a generous cap.
        self.assertEqual(
            sa.frame_candidates(EX_RNG_CALLS, EX_ELM, "PEK", max_offset=8),
            [8, 14])

    def test_frame_is_position_independent_of_rng_calls_offset(self):
        # A different REL cost simply shifts every frame by the same amount.
        self.assertEqual(sa.frame_candidates(10, EX_ELM, "PEK"), [15, 21])


class TestRealSeedRoundTrip(unittest.TestCase):
    """Validate the frame formula against real elm_calls generation."""

    def test_heard_substring_recovers_the_true_frame(self):
        seed = 0x0C0E02C2  # the Metang reference seed
        prev_routes = {"r": 0, "e": 0, "l": 0}
        rng_calls, elm = sa.advance_context(seed, prev_routes, count=128)
        self.assertGreater(len(elm), 40)

        # Player is on true_frame having just heard the last k calls.  The call
        # that landed them on frame f is elm[f - rng_calls - 1], so the last k
        # calls ending on frame f are elm[(f-rng_calls-k):(f-rng_calls)].
        true_frame = rng_calls + 30
        k = 8
        i = true_frame - rng_calls
        heard = elm[i - k:i]

        cands = sa.frame_candidates(rng_calls, elm, heard)
        self.assertIn(true_frame, cands)

    def test_context_from_row_matches_advance_context(self):
        row = {"rng_calls": EX_RNG_CALLS, "elm": EX_ELM}
        self.assertEqual(sa.context_from_row(row), (EX_RNG_CALLS, EX_ELM))


class TestIdentifyFrameDriver(unittest.TestCase):
    def test_returns_immediately_when_seed_calls_are_unique(self):
        def boom(_prompt=""):  # must not be called
            raise AssertionError("input_fn should not be called")
        self.assertEqual(
            sa.identify_frame(EX_RNG_CALLS, EX_ELM, observed="PEKE",
                              input_fn=boom), 9)

    def test_prompts_until_unambiguous(self):
        replies = iter(["E"])  # "PEK" (->8,14) then "E" -> "PEKE" -> 9
        self.assertEqual(
            sa.identify_frame(EX_RNG_CALLS, EX_ELM, observed="PEK",
                              input_fn=lambda _p="": next(replies)), 9)

    def test_ignores_blank_input_then_resolves(self):
        replies = iter(["", "K"])  # blank keeps looping, then "PEKK" -> 15
        self.assertEqual(
            sa.identify_frame(EX_RNG_CALLS, EX_ELM, observed="PEK",
                              input_fn=lambda _p="": next(replies)), 15)

    def test_returns_none_when_calls_do_not_match(self):
        def boom(_prompt=""):
            raise AssertionError("input_fn should not be called")
        self.assertIsNone(
            sa.identify_frame(EX_RNG_CALLS, EX_ELM, observed="KKK",
                              input_fn=boom))


class TestPlanAdvances(unittest.TestCase):
    # You Sweet Scent standing ON the encounter frame (verified in-game): so
    # total = encounter_frame - current_frame, chatot = total - margin.
    def test_worked_example_frame_9_to_81(self):
        p = sa.plan_advances(9, 81)
        self.assertEqual(p.scent_frame, 81)     # press on the encounter frame itself
        self.assertEqual(p.total_advances, 72)  # 81 - 9
        self.assertEqual(p.chatot_advances, 69)
        self.assertEqual(p.chatot_flips, 34.5)  # trailing half flip
        self.assertEqual(p.land_frame, 78)      # 9 + 69
        self.assertEqual(p.elm_before_scent, 3)

    def test_whole_flips_when_gap_is_even(self):
        p = sa.plan_advances(9, 82)             # total 73, chatot 70
        self.assertEqual(p.chatot_advances, 70)
        self.assertEqual(p.chatot_flips, 35.0)
        self.assertEqual(p.land_frame, 79)

    def test_short_distance_uses_only_elm_no_chatot(self):
        p = sa.plan_advances(79, 81)            # scent 81, total 2
        self.assertEqual(p.chatot_flips, 0.0)
        self.assertEqual(p.chatot_advances, 0)
        self.assertEqual(p.elm_before_scent, 2)
        self.assertEqual(p.land_frame, 79)

    def test_exactly_margin_distance_no_chatot(self):
        p = sa.plan_advances(78, 81)            # total 3 == margin
        self.assertEqual(p.chatot_advances, 0)
        self.assertEqual(p.elm_before_scent, 3)

    def test_one_over_margin_uses_half_flip(self):
        p = sa.plan_advances(77, 81)            # total 4 > margin
        self.assertEqual(p.elm_before_scent, 3)
        self.assertEqual(p.chatot_advances, 1)
        self.assertEqual(p.chatot_flips, 0.5)
        self.assertEqual(p.land_frame, 78)

    def test_scent_now_when_already_on_encounter_frame(self):
        p = sa.plan_advances(81, 81)            # total 0
        self.assertEqual(p.total_advances, 0)
        self.assertEqual(p.chatot_advances, 0)
        self.assertEqual(p.elm_before_scent, 0)

    def test_overshoot_raises(self):
        with self.assertRaises(ValueError):
            sa.plan_advances(85, 81)

    def test_custom_margin(self):
        p = sa.plan_advances(9, 81, margin=5)
        self.assertEqual(p.total_advances, 72)
        self.assertEqual(p.elm_before_scent, 5)
        self.assertEqual(p.chatot_advances, 67)
        self.assertEqual(p.land_frame, 76)


class TestMarginGuide(unittest.TestCase):
    def test_format_and_slicing(self):
        # A synthetic elm long enough to cover the scent point + trailing calls.
        rng_calls = 3
        elm = "PEK" * 40  # 120 chars
        plan = sa.plan_advances(9, 81)          # land 77, pre_scent 80, margin 3
        guide = sa.margin_guide(rng_calls, elm, plan, n_before=5, n_after=3)

        j_land = plan.land_frame - rng_calls    # 74
        expected = (elm[j_land - 5:j_land] + "[" + elm[j_land:j_land + 3] + "]!"
                    + elm[j_land + 3:j_land + 6])
        self.assertEqual(guide, expected)
        # Shape matches the plan doc's PEEEP[KPE]!KEP layout.
        self.assertRegex(guide, r"^[PEK]{5}\[[PEK]{3}\]![PEK]{3}$")

    def test_bracket_length_follows_elm_margin(self):
        rng_calls = 3
        elm = "KPE" * 40
        plan = sa.plan_advances(79, 81)         # total 2 -> elm_before_scent = 2
        guide = sa.margin_guide(rng_calls, elm, plan)
        bracket = guide[guide.index("[") + 1:guide.index("]")]
        self.assertEqual(len(bracket), 2)

    def test_regression_scent_on_encounter_frame_not_before(self):
        # In-game finding: pressing Sweet Scent on encounter_frame-1 lands one frame
        # early.  With this Elm string the OLD (off-by-one) code produced
        # "KPKEP[KEK]!PEE"; the corrected code must produce "PKEPK[EKP]!EEP".
        elm = "KPKEPKEKPEEP"
        plan = sa.plan_advances(0, 9)          # scent_frame 9, land 6 (= 9 - margin)
        guide = sa.margin_guide(0, elm, plan, n_before=5, n_after=3)
        self.assertEqual(guide, "PKEPK[EKP]!EEP")

    def test_guide_matches_real_seed_calls(self):
        seed = 0x0C0E02C2
        prev_routes = {"r": 0, "e": 0, "l": 0}
        rng_calls, elm = sa.advance_context(seed, prev_routes, count=128)
        plan = sa.plan_advances(9, 81)
        guide = sa.margin_guide(rng_calls, elm, plan)
        # The bracketed calls are exactly what the player hears leaving land_frame.
        j_land = plan.land_frame - rng_calls
        self.assertEqual(guide[guide.index("[") + 1:guide.index("]")],
                         elm[j_land:j_land + 3])


class TestPromptTargetFrame(unittest.TestCase):
    def test_blank_keeps_default(self):
        self.assertEqual(
            sa.prompt_target_frame(0x0C0E02C2, default=81,
                                   input_fn=lambda _p="": ""), 81)

    def test_reads_typed_frame(self):
        self.assertEqual(
            sa.prompt_target_frame(0x0C0E02C2, input_fn=lambda _p="": "42"), 42)

    def test_reprompts_on_garbage(self):
        replies = iter(["oops", "11"])
        self.assertEqual(
            sa.prompt_target_frame(0x0C0E02C2,
                                   input_fn=lambda _p="": next(replies)), 11)


class TestChooseTargetFrame(unittest.TestCase):
    """The in-house/Pokefinder toggle + exact-seed rule (clayton-ctd.8)."""

    KEY = 0x0C0E02C2
    NEARBY = 0x0C0E02C8  # a different (nearby) seed we actually landed on
    BLOCKS = {"peak": 56}

    def test_exact_seed_ignores_toggle(self):
        # Loaded the key seed exactly -> configured target_advances, whatever the toggle says.
        for use in (True, False):
            self.assertEqual(
                sa.choose_target_frame(self.KEY, key_seed=self.KEY, target_advances=81,
                                       use_inhouse=use, area="Mountain", tod="morning",
                                       blocks=self.BLOCKS), 81)

    def test_inhouse_finds_metang_frame(self):
        # Independently reproduces the frame the user got from Pokefinder for this seed (31).
        frame = sa.choose_target_frame(self.NEARBY, key_seed=self.KEY, target_advances=81,
                                       use_inhouse=True, area="Mountain", tod="morning",
                                       blocks=self.BLOCKS, current_frame=14)
        self.assertEqual(frame, 31)
        self.assertGreater(frame, 14)

    def test_pokefinder_mode_prompts(self):
        frame = sa.choose_target_frame(self.NEARBY, key_seed=self.KEY, target_advances=81,
                                       use_inhouse=False, input_fn=lambda _p="": "27")
        self.assertEqual(frame, 27)

    def test_inhouse_requires_blocks(self):
        with self.assertRaises(ValueError):
            sa.choose_target_frame(self.NEARBY, key_seed=self.KEY, target_advances=81,
                                   use_inhouse=True, blocks=None)

    def test_inhouse_raises_when_target_absent(self):
        with self.assertRaises(RuntimeError):
            sa.choose_target_frame(self.NEARBY, key_seed=self.KEY, target_advances=81,
                                   use_inhouse=True, area="Mountain", tod="morning",
                                   blocks={"peak": 0})  # no Peak -> no Metang


if __name__ == "__main__":
    unittest.main()
