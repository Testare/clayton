"""Type chart, checked against the ROM table recorded in notes/ss_rng/effectiveness_chart.md.

claytonlib/battle/types.py was generated from that file; this test re-parses it so the two
cannot drift apart silently.
"""
import re
import unittest
from pathlib import Path

from claytonlib.battle.types import TYPE_CHART, effectiveness, type_multiplier

_NOTES = Path(__file__).resolve().parent.parent / "notes" / "ss_rng" / "effectiveness_chart.md"
_EFFECTS = {"Super effective": 2.0, "Not very effective": 0.5, "No effect": 0.0}
# The ROM table brackets the two Foresight-removable Ghost immunities with these markers.
_SENTINELS = {"FORESIGHT", "ENDTABLE"}


def _parse_notes() -> dict[tuple[str, str], float]:
    chart = {}
    for line in _NOTES.read_text().splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*([A-Za-z ]+?)\s*\|", line)
        if not m:
            continue
        _, attacking, defending, effect = m.groups()
        if attacking in _SENTINELS or defending in _SENTINELS:
            continue
        chart[(attacking.capitalize(), defending.capitalize())] = _EFFECTS[effect]
    return chart


class TestChartMatchesNotes(unittest.TestCase):
    def test_chart_is_exactly_the_rom_table(self):
        self.assertEqual(TYPE_CHART, _parse_notes())

    def test_notes_table_is_the_expected_size(self):
        """Guards against a truncated read of the notes file making the test vacuous."""
        self.assertEqual(len(_parse_notes()), 110)


class TestEffectiveness(unittest.TestCase):
    def test_absent_matchups_are_neutral(self):
        self.assertEqual(type_multiplier("Normal", "Normal"), 1.0)

    def test_names_are_case_insensitive(self):
        self.assertEqual(type_multiplier("ice", "STEEL"), 0.5)

    def test_dual_types_multiply(self):
        # Electric resists Flying and so does Steel, so Magneton takes a quarter.
        self.assertEqual(effectiveness("Flying", ("Steel", "Electric")), 0.25)

    def test_immunity_in_either_half_zeroes_the_result(self):
        self.assertEqual(effectiveness("Electric", ("Ground", "Rock")), 0.0)
        self.assertEqual(effectiveness("Normal", ("Ghost", "Poison")), 0.0)

    def test_single_type_may_be_passed_as_a_string(self):
        self.assertEqual(effectiveness("Ice", "Dragon"), 2.0)

    def test_gen4_specifics(self):
        """Steel resisted Ghost and Dark until Gen 6; there is no Fairy type."""
        self.assertEqual(type_multiplier("Ghost", "Steel"), 0.5)
        self.assertEqual(type_multiplier("Dark", "Steel"), 0.5)
        self.assertNotIn("Fairy", {t for pair in TYPE_CHART for t in pair})


class TestFixtureMatchups(unittest.TestCase):
    """Suicune only ever attacks with Ice (Aurora Beam) and Flying (Gust)."""

    PARTY = {
        "Magneton": ("Steel", "Electric"),
        "Smeargle": ("Normal",),
        "Mamoswine": ("Ice", "Ground"),
    }

    def test_aurora_beam(self):
        self.assertEqual(effectiveness("Ice", self.PARTY["Magneton"]), 0.5)
        self.assertEqual(effectiveness("Ice", self.PARTY["Smeargle"]), 1.0)
        # Ice resists Ice but is super effective on Ground, so Mamoswine nets neutral.
        self.assertEqual(effectiveness("Ice", self.PARTY["Mamoswine"]), 1.0)

    def test_gust(self):
        self.assertEqual(effectiveness("Flying", self.PARTY["Magneton"]), 0.25)
        self.assertEqual(effectiveness("Flying", self.PARTY["Smeargle"]), 1.0)
        self.assertEqual(effectiveness("Flying", self.PARTY["Mamoswine"]), 1.0)

    def test_nothing_suicune_has_is_super_effective_on_the_party(self):
        for types in self.PARTY.values():
            for attacking in ("Ice", "Flying"):
                self.assertLessEqual(effectiveness(attacking, types), 1.0)


if __name__ == "__main__":
    unittest.main()
