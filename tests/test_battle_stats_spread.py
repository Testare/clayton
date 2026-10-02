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


class TestAbilitiesAndPressure(unittest.TestCase):
    """`target_has_pressure` was a HuntConfig field defaulting to True that the facade never set,
    so every target was assumed to have Pressure. Right for all three tower birds and wrong for
    both Lati twins -- and the cost is invisible: assuming Pressure where there is none
    double-counts our PP, halving every budget the solver plans against, so a run quietly runs
    out of moves earlier than the plan said it would.
    """

    def test_the_tower_birds_have_pressure(self):
        from claytonlib.battle.stats import has_pressure
        for name in ("suicune", "lugia", "ho-oh"):
            self.assertTrue(has_pressure(name), name)

    def test_the_lati_twins_have_levitate_instead(self):
        from claytonlib.battle.stats import abilities, has_pressure
        for name in ("latias", "latios"):
            self.assertEqual(abilities(name), ("Levitate",), name)
            self.assertFalse(has_pressure(name), name)

    def test_our_own_party_does_not_read_as_pressure(self):
        from claytonlib.battle.stats import has_pressure
        for name in ("smeargle", "magneton", "mamoswine"):
            self.assertFalse(has_pressure(name), name)

    def test_abilities_are_in_slot_order(self):
        from claytonlib.battle.stats import abilities
        self.assertEqual(abilities("smeargle"), ("Own Tempo", "Technician"))

    def test_every_species_in_the_table_has_abilities_recorded(self):
        """So a new row cannot be added without them and silently read as no Pressure."""
        import json
        import pathlib
        data = json.loads((pathlib.Path(__file__).resolve().parent.parent / "claytonlib"
                           / "basedata" / "base_stats.json").read_text())
        missing = [k for k, v in data.items() if not v.get("abilities")]
        self.assertEqual(missing, [])

    def test_the_values_match_the_roms_own_table_where_it_is_available(self):
        """base_stats.json is built from PokeAPI, which reports Gen 9 abilities -- and abilities
        changed after Gen 4 far more often than stats or types did. These came from the ROM's
        personal.json instead, so this checks them against it when the decompilation is present.
        """
        import json
        import pathlib
        rom = pathlib.Path.home() / "arch/pokeheartgold/files/poketool/personal/personal.json"
        if not rom.exists():
            self.skipTest("pokeheartgold decompilation not present")
        personal = json.loads(rom.read_text())["baseStats"]
        data = json.loads((pathlib.Path(__file__).resolve().parent.parent / "claytonlib"
                           / "basedata" / "base_stats.json").read_text())
        for key, entry in data.items():
            expected = [a.replace("ABILITY_", "").title().replace("_", " ")
                        for a in personal[entry["dex_no"]]["abilities"]
                        if a != "ABILITY_NONE"]
            self.assertEqual(entry["abilities"], expected, key)
