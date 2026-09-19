"""Tests for claytonlib.metronome_species."""
import unittest

from claytonlib.metronome_species import (
    MetronomeSpecies,
    list_metronome_species,
    metronome_species_by_name,
)

_EXPECTED_NAMES = [
    "Happiny", "Chansey", "Blissey",
    "Cleffa", "Clefairy", "Clefable",
    "Mew",
    "Togepi", "Togetic", "Togekiss",
    "Munchlax", "Snorlax",
    "Snubbull", "Granbull",
]


class TestListMetronomeSpecies(unittest.TestCase):
    def test_returns_all_species_in_display_order(self):
        names = [s.name for s in list_metronome_species()]
        self.assertEqual(names, _EXPECTED_NAMES)

    def test_every_species_learns_metronome(self):
        for s in list_metronome_species():
            self.assertIn("Metronome", s.moves, s.name)

    def test_every_species_has_real_data(self):
        for s in list_metronome_species():
            self.assertIsInstance(s, MetronomeSpecies)
            self.assertGreater(s.dex_no, 0)
            self.assertIn(s.gender, ("female_only", "male_only", "genderless", "both"))
            self.assertTrue(s.abilities)
            self.assertGreater(len(s.moves), 10)  # sanity: not an empty/truncated scrape

    def test_chansey_line_is_female_only_with_serene_grace(self):
        for name in ("Happiny", "Chansey", "Blissey"):
            s = metronome_species_by_name(name)
            self.assertEqual(s.gender, "female_only")
            self.assertIn("Serene Grace", s.abilities)
            self.assertIn("Natural Cure", s.abilities)

    def test_togepi_line_also_carries_serene_grace(self):
        # A second family besides Chansey's carries Serene Grace -- easy to assume it's
        # Chansey-exclusive, so this is worth its own regression test.
        for name in ("Togepi", "Togetic", "Togekiss"):
            s = metronome_species_by_name(name)
            self.assertIn("Serene Grace", s.abilities)

    def test_ability_pair_changes_on_evolution(self):
        # Munchlax -> Snorlax and Snubbull -> Granbull both change their ability pair on
        # evolving -- a species-driven UI can't just inherit the base form's abilities.
        self.assertEqual(metronome_species_by_name("Munchlax").abilities,
                         ("Pickup", "Thick Fat"))
        self.assertEqual(metronome_species_by_name("Snorlax").abilities,
                         ("Immunity", "Thick Fat"))
        self.assertEqual(metronome_species_by_name("Snubbull").abilities,
                         ("Intimidate", "Run Away"))
        self.assertEqual(metronome_species_by_name("Granbull").abilities,
                         ("Intimidate", "Quick Feet"))

    def test_mew_is_genderless_with_a_single_ability(self):
        s = metronome_species_by_name("Mew")
        self.assertEqual(s.gender, "genderless")
        self.assertEqual(s.abilities, ("Synchronize",))

    def test_unknown_species_returns_none(self):
        self.assertIsNone(metronome_species_by_name("Ditto"))

    def test_every_move_resolves_against_the_canonical_move_list(self):
        # The scraper already checks this at generation time (and prints unresolved names),
        # but re-verify here so a hand-edit of the JSON can't silently introduce a typo'd
        # move name that nothing downstream would ever catch.
        from claytonlib.moves import resolve_move
        for s in list_metronome_species():
            for move in s.moves:
                self.assertIsNotNone(resolve_move(move), f"{s.name}: {move!r}")
