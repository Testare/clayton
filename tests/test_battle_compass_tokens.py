"""The reporting grammar (notes/battle_compass.md sec 13)."""
import unittest

from claytonlib.battle_compass import tokens as tok


class TestRendering(unittest.TestCase):
    def test_hp_is_three_zero_padded_digits(self):
        self.assertEqual(tok.hp_token(50), "HP050")
        self.assertEqual(tok.hp_token(1), "HP001")
        self.assertEqual(tok.hp_token(714), "HP714")

    def test_hp_out_of_renderable_range_raises(self):
        """Three digits always suffice -- the largest Gen 4 HP stat is 714."""
        for value in (-1, 1000):
            with self.assertRaises(ValueError):
                tok.hp_token(value)

    def test_move_tokens_are_one_based(self):
        self.assertEqual(tok.our_move_token(0), "M1")
        self.assertEqual(tok.target_move_token(3), "E4")

    def test_out_of_range_slots_raise(self):
        for fn in (tok.our_move_token, tok.target_move_token):
            for slot in (-1, 4):
                with self.assertRaises(ValueError):
                    fn(slot)

    def test_prevented_tokens_put_the_status_after_the_actor(self):
        self.assertEqual(tok.prevented_token("E", "par"), "Epar")
        with self.assertRaises(ValueError):
            tok.prevented_token("X", "par")

    def test_ball_tokens_distinguish_the_two_ball_types(self):
        """A failed capture ball must not render like a failed standard ball, or the log cannot
        say which ball was spent."""
        self.assertEqual(tok.ball_token(1), "P1")
        self.assertEqual(tok.ball_token(1, capture_ball=True), "C1")
        self.assertEqual(tok.ball_token(0, captured=True), "Pc")
        self.assertEqual(tok.ball_token(0, captured=True, capture_ball=True), "C")

    def test_a_shake_count_above_three_is_a_capture_not_a_shake(self):
        with self.assertRaises(ValueError):
            tok.ball_token(4)

    def test_item_codes_must_be_lowercase_detail(self):
        self.assertEqual(tok.item_token("hp"), "Ihp")
        for bad in ("", "HP"):
            with self.assertRaises(ValueError):
                tok.item_token(bad)

    def test_switch_tokens_cover_the_party(self):
        self.assertEqual(tok.switch_token(1), "S1")
        for slot in (0, 7):
            with self.assertRaises(ValueError):
                tok.switch_token(slot)

    def test_the_worked_example_from_the_design_doc(self):
        path = tok.render_path([["E3", "h", tok.hp_token(50)],
                                ["Ihp", "E2", "!", "~", tok.hp_token(100)],
                                ["E4", "M2", "h"]])
        self.assertEqual(path, "E3hHP050 IhpE2!~HP100 E4M2h")


class TestTokenising(unittest.TestCase):
    """Provided for fixtures and bug reports; the tool itself only ever renders (sec 13.1)."""

    def test_longest_match_keeps_hp_together(self):
        self.assertEqual(tok.tokenise("E3hHP050"), ["E3h", "HP050"])

    def test_bag_action_then_move_then_hp(self):
        self.assertEqual(tok.tokenise("IhpE2!~HP100"), ["Ihp", "E2!~", "HP100"])

    def test_a_status_detail_starting_with_an_action_letter_is_not_split(self):
        """`par` begins with `p`, but details are lowercase so they cannot open an action."""
        self.assertEqual(tok.tokenise("Epar"), ["Epar"])
        self.assertEqual(tok.tokenise("M1hEpar"), ["M1h", "Epar"])

    def test_snapping_out_of_confusion_keeps_its_slot(self):
        self.assertEqual(tok.tokenise("Escfz2h"), ["Escfz2h"])

    def test_round_trips_a_rendered_path(self):
        path = "M1hE3!HP103 C1E3hHP059"
        self.assertEqual([tok.tokenise(t) for t in tok.split_turns(path)],
                         [["M1h", "E3!", "HP103"], ["C1", "E3h", "HP059"]])

    def test_text_with_no_action_prefix_raises(self):
        with self.assertRaises(ValueError):
            tok.tokenise("hhh")

    def test_action_prefixes_are_prefix_free(self):
        """What lets HP be two characters: H alone is deliberately not an action."""
        for a in tok.ACTION_PREFIXES:
            for b in tok.ACTION_PREFIXES:
                if a != b:
                    self.assertFalse(b.startswith(a), f"{b} starts with {a}")


class TestValidation(unittest.TestCase):
    def test_a_well_formed_turn_has_no_problems(self):
        self.assertEqual(tok.validate_turn(tok.tokenise("M1hE2hHP120")), [])

    def test_taking_a_hit_without_reporting_hp_is_invalid(self):
        """The self-checking property: a forgotten HP is a parse error, not a wrong state."""
        problems = tok.validate_turn(tok.tokenise("E3h"))
        self.assertEqual(len(problems), 1)
        self.assertIn("HP token", problems[0])

    def test_a_turn_with_no_hit_needs_no_hp(self):
        self.assertEqual(tok.validate_turn(tok.tokenise("E4M2h")), [])

    def test_a_crit_also_requires_hp(self):
        self.assertTrue(tok.validate_turn(tok.tokenise("E3!")))

    def test_a_bag_action_after_a_move_is_invalid(self):
        """Bag actions resolve before any move, so they cannot appear after one (sec 12.1)."""
        problems = tok.validate_turn(["M1", "h", "Ihp"])
        self.assertTrue(any("resolve first" in p for p in problems))

    def test_nothing_may_follow_a_terminal_token(self):
        for terminal in ("C", "Pc"):
            self.assertTrue(tok.validate_turn([terminal, "E1"]), terminal)
        # A successful throw alone is the whole turn: the ball resolves first and ends the battle
        # before the target can act.
        self.assertEqual(tok.validate_turn(["C"]), [])

    def test_a_move_and_a_ball_cannot_share_a_turn(self):
        """You pick one action. A ball is a bag action and resolves before any move, so a turn
        containing both is impossible rather than merely unusual."""
        self.assertTrue(tok.validate_turn(["M1", "h", "C"]))

    def test_a_malformed_hp_token_is_reported(self):
        self.assertTrue(tok.validate_turn(["HPxyz"]))

    def test_hp_from_token_only_matches_hp(self):
        self.assertEqual(tok.hp_from_token("HP050"), 50)
        self.assertIsNone(tok.hp_from_token("HP5"))
        self.assertIsNone(tok.hp_from_token("M1"))


if __name__ == "__main__":
    unittest.main()


class TestNormalisation(unittest.TestCase):
    """The simulator emits fragments; the grammar's unit is the merged token. Rules that inspect
    tokens must normalise, or a check like "did anything hit us" silently never fires."""

    def test_fragments_and_merged_tokens_normalise_alike(self):
        fragments = ["M1", "h", "E3", "!", "HP103"]
        merged = ["M1h", "E3!", "HP103"]
        self.assertEqual(tok.normalise(fragments), merged)
        self.assertEqual(tok.normalise(merged), merged)

    def test_turn_requires_hp_works_on_either_form(self):
        for form in (["M1", "h", "E3", "!"], ["M1h", "E3!"]):
            self.assertTrue(tok.turn_requires_hp(form), form)
        for form in (["M1", "h", "E4"], ["M1h", "E4"]):
            self.assertFalse(tok.turn_requires_hp(form), form)

    def test_validation_works_on_either_form(self):
        self.assertTrue(tok.validate_turn(["M1", "h", "E3", "!"]))
        self.assertEqual(tok.validate_turn(["M1", "h", "E3", "!", "HP103"]), [])
