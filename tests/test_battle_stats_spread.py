"""Parsing a typed IV spread.

The run page asks for six IVs as one string once Seed A turns out not to be the key seed. One
parser serves it, because the interesting failure is silent: a spread short by one value shifts
every later stat by a position, and five plausible IVs with a missing Speed looks exactly like a
correct entry until the simulation desynchronises mid-battle.
"""
import unittest

from claytonlib.battle.stats import (
    MAX_IV, NATURES, STAT_KEYS, format_iv_spread, nature_names, parse_iv_spread,
)


class TestTheSpreadOrder(unittest.TestCase):
    def test_it_is_the_order_the_whole_project_uses(self):
        """hp/atk/def/spa/spd/spe. A spread read in the wrong order is still six valid IVs, so
        nothing downstream would object -- which is why this is pinned rather than assumed."""
        self.assertEqual(STAT_KEYS, ("hp", "atk", "def", "spa", "spd", "spe"))

    def test_it_matches_the_apps_own_key_order(self):
        from app.models import STAT_KEYS as APP_KEYS
        self.assertEqual(tuple(APP_KEYS), STAT_KEYS)


class TestParsing(unittest.TestCase):
    def test_a_normal_spread(self):
        self.assertEqual(parse_iv_spread("29 15 31 31 31 28"),
                         {"hp": 29, "atk": 15, "def": 31, "spa": 31, "spd": 31, "spe": 28})

    def test_extra_whitespace_and_commas_are_tolerated(self):
        """A player pasting from Pokefinder may bring either."""
        self.assertEqual(parse_iv_spread("  29   15 31  31 31 28 "),
                         parse_iv_spread("29,15,31,31,31,28"))

    def test_the_boundary_values_are_legal(self):
        self.assertEqual(set(parse_iv_spread("0 0 0 0 0 0").values()), {0})
        self.assertEqual(set(parse_iv_spread("31 31 31 31 31 31").values()), {MAX_IV})

    def test_round_trips_through_format(self):
        text = "29 15 31 31 31 28"
        self.assertEqual(format_iv_spread(parse_iv_spread(text)), text)


class TestItSaysWhatIsWrong(unittest.TestCase):
    """"Invalid IVs" sends the player back to count on their fingers, so each message names the
    actual problem."""

    def _problem(self, text):
        with self.assertRaises(ValueError) as caught:
            parse_iv_spread(text)
        return str(caught.exception)

    def test_too_few_reports_the_count_and_the_expected_order(self):
        problem = self._problem("29 15 31 31 31")
        self.assertIn("got 5", problem)
        self.assertIn("hp/atk/def/spa/spd/spe", problem)

    def test_too_many_reports_the_count(self):
        self.assertIn("got 7", self._problem("29 15 31 31 31 28 7"))

    def test_nothing_at_all_says_so_rather_than_naming_zero_values(self):
        self.assertIn("(nothing)", self._problem("   "))

    def test_a_non_number_is_named_by_its_stat(self):
        self.assertIn("spa='x'", self._problem("29 15 31 x 31 28"))

    def test_out_of_range_names_every_offender_not_just_the_first(self):
        problem = self._problem("29 15 32 31 31 -1")
        self.assertIn("def=32", problem)
        self.assertIn("spe=-1", problem)

    def test_a_missing_stat_is_rejected_by_format_too(self):
        with self.assertRaises(ValueError) as caught:
            format_iv_spread({"hp": 1, "atk": 2})
        self.assertIn("missing", str(caught.exception))


class TestNatureNames(unittest.TestCase):
    def test_all_twenty_five_in_alphabetical_order(self):
        names = nature_names()
        self.assertEqual(len(names), 25)
        self.assertEqual(list(names), sorted(NATURES))

    def test_every_name_the_picker_offers_derives_stats(self):
        """So a dropdown built from this list cannot contain an entry the deriver rejects."""
        from claytonlib.battle.stats import derive_species_stats
        for name in nature_names():
            stats = derive_species_stats("suicune", 40, name, ivs=31)
            self.assertEqual(set(stats), set(STAT_KEYS), name)
