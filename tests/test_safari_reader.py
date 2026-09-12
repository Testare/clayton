"""Tests for utils/safari_reader.py -- the pure logic of the Safari GDB reader (ctd.14)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import safari_reader as sr  # noqa: E402


class TestExpandActionScript(unittest.TestCase):
    def test_worked_example(self):
        # From the spec: "6B6C1M" = 6 Bait, 6 Ball, 1 Mud.
        self.assertEqual(sr.expand_action_script("6B6C1M"),
                         ["B"] * 6 + ["C"] * 6 + ["M"])

    def test_empty_is_no_scripted_actions(self):
        self.assertEqual(sr.expand_action_script(""), [])
        self.assertEqual(sr.expand_action_script("   "), [])

    def test_case_insensitive(self):
        self.assertEqual(sr.expand_action_script("2b1m1c"), ["B", "B", "M", "C"])

    def test_multi_digit_counts(self):
        self.assertEqual(sr.expand_action_script("12C"), ["C"] * 12)

    def test_action_without_count_raises(self):
        with self.assertRaises(ValueError):
            sr.expand_action_script("B")

    def test_trailing_count_raises(self):
        with self.assertRaises(ValueError):
            sr.expand_action_script("6B3")

    def test_unknown_char_raises(self):
        with self.assertRaises(ValueError):
            sr.expand_action_script("6X")


class TestParseSafariSeedLine(unittest.TestCase):
    def test_seed_with_actions(self):
        seed, actions = sr.parse_safari_seed_line("0x080E2B7C 6B6C1M")
        self.assertEqual(seed, 0x080E2B7C)
        self.assertEqual(actions, ["B"] * 6 + ["C"] * 6 + ["M"])

    def test_bare_seed_has_no_actions(self):
        self.assertEqual(sr.parse_safari_seed_line("080E2B7C"), (0x080E2B7C, []))

    def test_blank_and_comment_skipped(self):
        self.assertIsNone(sr.parse_safari_seed_line(""))
        self.assertIsNone(sr.parse_safari_seed_line("   "))
        self.assertIsNone(sr.parse_safari_seed_line("# a note"))

    def test_extra_whitespace(self):
        seed, actions = sr.parse_safari_seed_line("  0x1  3C  ")
        self.assertEqual((seed, actions), (1, ["C", "C", "C"]))


class TestActionAt(unittest.TestCase):
    def test_scripted_then_balls_forever(self):
        actions = ["B", "M"]
        self.assertEqual(sr.action_at(actions, 0), "B")
        self.assertEqual(sr.action_at(actions, 1), "M")
        self.assertEqual(sr.action_at(actions, 2), "C")   # ran out -> ball
        self.assertEqual(sr.action_at(actions, 99), "C")

    def test_empty_is_all_balls(self):
        self.assertEqual(sr.action_at([], 0), "C")


class TestActionKeys(unittest.TestCase):
    def test_first_turn_opens_at_ball(self):
        # last=None: 's' lands on Ball, then navigate, then throw.
        self.assertEqual(sr.action_keys("C"), ["s", "space"])
        self.assertEqual(sr.action_keys("B"), ["s", "a", "space"])
        self.assertEqual(sr.action_keys("M"), ["s", "d", "space"])

    def test_from_ball(self):
        self.assertEqual(sr.action_keys("C", last="C"), ["space"])
        self.assertEqual(sr.action_keys("B", last="C"), ["a", "space"])
        self.assertEqual(sr.action_keys("M", last="C"), ["d", "space"])

    def test_from_bait(self):
        self.assertEqual(sr.action_keys("B", last="B"), ["space"])          # stay on bait
        self.assertEqual(sr.action_keys("C", last="B"), ["w", "space"])     # bait -> ball
        self.assertEqual(sr.action_keys("M", last="B"), ["w", "d", "space"])  # bait -> mud

    def test_from_mud(self):
        self.assertEqual(sr.action_keys("M", last="M"), ["space"])          # stay on mud
        self.assertEqual(sr.action_keys("C", last="M"), ["w", "space"])     # mud -> ball
        self.assertEqual(sr.action_keys("B", last="M"), ["w", "a", "space"])  # mud -> bait

    def test_case_insensitive(self):
        self.assertEqual(sr.action_keys("b"), ["s", "a", "space"])
        self.assertEqual(sr.action_keys("m", last="b"), ["w", "d", "space"])

    def test_unknown_raises(self):
        with self.assertRaises(ValueError):
            sr.action_keys("X")
        with self.assertRaises(ValueError):
            sr.action_keys("C", last="X")


PROMPT = "What will Ethan throw?"


class TestSanitizeMessage(unittest.TestCase):
    def test_newlines_become_spaces(self):
        self.assertEqual(sr.sanitize_message("What will Ethan\nthrow?"),
                         "What will Ethan throw?")

    def test_collapses_runs_of_whitespace(self):
        self.assertEqual(sr.sanitize_message("Aargh!  Almost\n\nhad it!"),
                         "Aargh! Almost had it!")

    def test_strips_control_markers(self):
        self.assertEqual(sr.sanitize_message("[VAR:0x0100] is beside itself\nwith anger!"),
                         "is beside itself with anger!")
        self.assertEqual(sr.sanitize_message("Gotcha![WAIT]\n[VAR:0x0100] was caught!"),
                         "Gotcha! was caught!")


class TestMatchingThroughNewlines(unittest.TestCase):
    def test_driver_prompt_with_newline_still_acts(self):
        d = sr.ActionDriver(["B"], sr.MsgMap(prompt="What will Ethan throw?"))
        self.assertEqual(d.on_message("What will Ethan\nthrow?"), ("keys", ["s", "a", "space"]))

    def test_path_matches_message_with_newline_and_var(self):
        path, ended = sr.messages_to_path(
            [{"msg": "[VAR:0x0100] is beside itself\nwith anger!"},
             {"msg": "Gotcha![WAIT] [VAR:0x0100] was\ncaught!"}], MAP)
        self.assertEqual((path, ended), ("MC", True))


class TestActionDriver(unittest.TestCase):
    def _map(self):
        return sr.MsgMap(prompt=PROMPT, capture="was caught!", flee="fled!",
                         out_of_balls="Announcer:")

    def test_first_prompt_acts_immediately(self):
        d = sr.ActionDriver(["B"], self._map())
        self.assertEqual(d.on_message(PROMPT), ("keys", ["s", "a", "space"]))

    def test_redrawn_prompt_not_acted_twice(self):
        d = sr.ActionDriver(["B", "C"], self._map())
        self.assertEqual(d.on_message(PROMPT)[0], "keys")   # turn 1 acts
        self.assertIsNone(d.on_message(PROMPT))             # redraw (no message between) -> ignored
        d.on_message("Metang is eating!")                   # a message => turn advanced -> re-arm
        self.assertEqual(d.on_message(PROMPT), ("keys", ["w", "space"]))  # bait -> ball

    def test_unrecognized_outcome_message_does_not_deadlock(self):
        # Regression (the reported stall): the mud "crit" message need NOT be in the map -- ANY
        # non-prompt message re-arms, so a message the map doesn't know still advances the run.
        d = sr.ActionDriver(["M", "C"], self._map())        # map has NO mud/ball strings
        self.assertEqual(d.on_message(PROMPT), ("keys", ["s", "d", "space"]))  # turn 1 mud
        d.on_message("Metang is beside itself with anger!")  # unknown to the map -> still re-arms
        self.assertEqual(d.on_message(PROMPT), ("keys", ["w", "space"]))  # mud -> ball

    def test_cursor_tracked_across_turns(self):
        d = sr.ActionDriver(["B", "B", "M", "C"], self._map())
        seqs = [d.on_message(PROMPT)]                       # first prompt acts
        for _ in range(3):
            d.on_message("...some outcome...")             # re-arm between turns
            seqs.append(d.on_message(PROMPT))
        self.assertEqual([s[1] for s in seqs], [
            ["s", "a", "space"],    # turn1 bait: nothing->ball->bait->throw
            ["space"],              # bait -> bait (stay)
            ["w", "d", "space"],    # bait -> mud
            ["w", "space"],         # mud -> ball
        ])

    def test_balls_forever_after_script(self):
        d = sr.ActionDriver(["B"], self._map())
        d.on_message(PROMPT)                                # bait
        d.on_message("...outcome...")
        self.assertEqual(d.on_message(PROMPT), ("keys", ["w", "space"]))  # exhausted -> ball

    def test_terminal_messages(self):
        m = self._map()
        self.assertEqual(sr.ActionDriver([], m).on_message("Gotcha! Metang was caught!"),
                         ("end", "captured"))
        self.assertEqual(sr.ActionDriver([], m).on_message("Metang fled!"), ("end", "fled"))
        self.assertEqual(sr.ActionDriver([], m).on_message("Announcer: no balls"),
                         ("end", "out_of_balls"))


# The REAL safari messages (from compass/_display.py); name-agnostic substrings.  Crit
# variants are checked first so they win over their non-crit counterparts.
MAP = sr.MsgMap(
    prompt="What will",
    bait="is eating!", bait_crit="is busy eating!",
    mud="is angry!", mud_crit="is beside itself with anger!",
    ball_0="broke free!", ball_1="appeared to be caught!",
    ball_2="Almost had it!", ball_3="so close, too!",
    capture="was caught!", flee="fled!",
    out_of_balls="Announcer:",
)


def _msgs(*texts):
    return [{"msg": t} for t in texts]


class TestMessagesToPath(unittest.TestCase):
    def test_bait_mud_and_crits(self):
        path, ended = sr.messages_to_path(_msgs(
            "Metang is eating!", "Metang is beside itself with anger!",
            "Metang is busy eating!", "Metang is angry!"), MAP)
        self.assertEqual(path, "bMBm")
        self.assertFalse(ended)

    def test_each_ball_outcome_digit(self):
        cases = [("Oh, no! The Pokémon broke free!", "0"),
                 ("Aww! It appeared to be caught!", "1"),
                 ("Aargh! Almost had it!", "2"),
                 ("Shoot! It was so close, too!", "3")]
        for msg, tok in cases:
            self.assertEqual(sr.messages_to_path(_msgs(msg), MAP), (tok, False))

    def test_ball_one_not_confused_with_capture(self):
        # "appeared to be caught!" must resolve to '1', not the capture 'C'.
        self.assertEqual(sr.messages_to_path(_msgs("Aww! It appeared to be caught!"), MAP),
                         ("1", False))

    def test_capture_is_terminal_C(self):
        path, ended = sr.messages_to_path(
            _msgs("Aargh! Almost had it!", "Gotcha! Metang was caught!", "after"), MAP)
        self.assertEqual(path, "2C")
        self.assertTrue(ended)

    def test_flee_is_terminal_F(self):
        path, ended = sr.messages_to_path(_msgs("Metang is eating!", "Metang fled!", "nope"), MAP)
        self.assertEqual(path, "bF")
        self.assertTrue(ended)

    def test_out_of_balls_ends_without_token(self):
        path, ended = sr.messages_to_path(
            _msgs("Oh, no! The Pokémon broke free!", "Announcer: ...out of balls"), MAP)
        self.assertEqual(path, "0")
        self.assertTrue(ended)

    def test_full_run_example(self):
        # bait, ball(1 shake), mud, ball -> capture
        path, ended = sr.messages_to_path(_msgs(
            "Metang is eating!",
            "Aww! It appeared to be caught!",
            "Metang is angry!",
            "Gotcha! Metang was caught!",
        ), MAP)
        self.assertEqual(path, "b1mC")
        self.assertTrue(ended)

    def test_accepts_plain_strings_and_ignores_rolls(self):
        results = ["Metang is eating!", {"addr": 0x1, "val": 5}, {"msg": "Metang fled!"}]
        self.assertEqual(sr.messages_to_path(results, MAP), ("bF", True))

    def test_unset_fields_never_match(self):
        # An empty MsgMap yields an empty, unfinished path regardless of messages.
        self.assertEqual(sr.messages_to_path(_msgs("anything", "at all"), sr.MsgMap()),
                         ("", False))


if __name__ == "__main__":
    unittest.main()
