"""One spelling per species across the data sets (claytonlib.species_names, clayton-69n).

The bug this guards: safari_zones.json was generated from a veekun DISPLAY-name list, so it
said `nidoran♀`/`farfetch’d`/`mr. mime` while safari_pokemon.json and base_stats.json key on
slugs. Nothing errored -- `areas_for_species` just returned no areas, and four species became
unhuntable in the app. The data is now named by identifier AND every lookup normalizes, so
either half alone would have prevented it.
"""
import json
import unittest
from pathlib import Path

from claytonlib._resources import basedata_json
from claytonlib.battle.stats import species as base_stats_species
from claytonlib.safari import safari_pokemon_by_name
from claytonlib.safari_encounters import (
    areas_for_species, block_requirement_for, locations_for_species, methods_for_species,
    resolve_safari_slots,
)
from claytonlib.species_names import (
    DISPLAY_OVERRIDES, canonical_species_name, display_species_name, species_names_equal,
)

INDEX = Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

ZONES = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "safari_zones.json"

#: The four species whose spelling differed between sources, with every spelling seen.
AWKWARD = {
    "nidoran-f": ["nidoran-f", "Nidoran♀", "NIDORAN F", "nidoran (f)", "Nidoran_F"],
    "nidoran-m": ["nidoran-m", "Nidoran♂", "nidoran m"],
    "farfetchd": ["farfetchd", "Farfetch'd", "Farfetch’d", "farfetch-d", "FARFETCHD"],
    "mr-mime": ["mr-mime", "Mr. Mime", "mr mime", "MR-MIME", "Mr_Mime"],
}


class TestCanonicalSpeciesName(unittest.TestCase):
    def test_every_awkward_spelling_reaches_one_slug(self):
        for canonical, spellings in AWKWARD.items():
            for spelling in spellings:
                self.assertEqual(canonical_species_name(spelling), canonical, spelling)

    def test_already_canonical_names_are_unchanged(self):
        for name in ("metang", "porygon-z", "porygon2", "ho-oh", "giratina-altered", "mime-jr"):
            self.assertEqual(canonical_species_name(name), name)

    def test_it_is_idempotent_over_every_species_we_have(self):
        for name in basedata_json("base_stats.json"):
            self.assertEqual(canonical_species_name(name), name, name)

    def test_whitespace_and_case_do_not_matter(self):
        self.assertEqual(canonical_species_name("  METANG  "), "metang")
        self.assertEqual(canonical_species_name("Mime  Jr."), "mime-jr")

    def test_species_names_equal(self):
        self.assertTrue(species_names_equal("Nidoran♀", "nidoran-f"))
        self.assertTrue(species_names_equal("Farfetch’d", "farfetch-d"))
        self.assertFalse(species_names_equal("nidoran-f", "nidoran-m"))

    def test_it_normalizes_spelling_not_forms(self):
        # Finding `giratina-altered` from `Giratina` is the lookup's job, not this function's.
        self.assertEqual(canonical_species_name("Giratina"), "giratina")


class TestDisplaySpeciesName(unittest.TestCase):
    """The other direction: a slug shown to a person should read like the Pokedex."""

    def test_the_five_irregulars(self):
        self.assertEqual(display_species_name("nidoran-f"), "Nidoran♀")
        self.assertEqual(display_species_name("nidoran-m"), "Nidoran♂")
        self.assertEqual(display_species_name("farfetchd"), "Farfetch’d")
        self.assertEqual(display_species_name("mr-mime"), "Mr. Mime")
        self.assertEqual(display_species_name("mime-jr"), "Mime Jr.")

    def test_the_regular_rule(self):
        self.assertEqual(display_species_name("metang"), "Metang")
        self.assertEqual(display_species_name("porygon-z"), "Porygon-Z")
        self.assertEqual(display_species_name("porygon2"), "Porygon2")
        self.assertEqual(display_species_name("ho-oh"), "Ho-Oh")

    def test_it_accepts_any_spelling_of_the_input(self):
        for spelling in ("Nidoran♀", "nidoran-f", "NIDORAN F"):
            self.assertEqual(display_species_name(spelling), "Nidoran♀", spelling)

    def test_it_round_trips_for_every_species_we_have(self):
        for name in basedata_json("base_stats.json"):
            self.assertEqual(canonical_species_name(display_species_name(name)), name, name)

    def test_the_app_mirrors_the_override_map(self):
        """The UI's own capName carries a copy (it can't call Python per keystroke); this is
        what keeps the copy honest."""
        html = INDEX.read_text()
        for slug, display in DISPLAY_OVERRIDES.items():
            # The JS map is written with \uXXXX escapes, which is what json.dumps emits too.
            entry = f"{json.dumps(slug)}: {json.dumps(display)}"
            self.assertIn(entry, html,
                          f"app/web/index.html's SPECIES_DISPLAY is missing {entry}")
        self.assertEqual(html.count("SPECIES_DISPLAY"), 2)  # defined once, used once


class TestTheDataSetsAgree(unittest.TestCase):
    """What one-offs/extract_safari_zones.py::check_names_resolve asserts at generation time,
    asserted again here so a hand edit to any of the three files can't drift either."""

    def setUp(self):
        self.zones = json.loads(ZONES.read_text())
        self.rates = basedata_json("safari_pokemon.json")
        self.stats = basedata_json("base_stats.json")

    def _zone_species(self):
        for area, entry in self.zones.items():
            if area.startswith("_"):
                continue
            for method, table in entry.items():
                if method in ("location", "has_water"):
                    continue
                for kind in ("normal", "block"):
                    for tod, rows in table[kind].items():
                        for sp, _lv in rows:
                            yield f"{area}/{method}/{kind}/{tod}", sp

    def test_every_species_in_the_zone_tables_has_catch_and_flee_rates(self):
        missing = sorted({sp for _where, sp in self._zone_species() if sp not in self.rates})
        self.assertEqual(missing, [], "safari_pokemon.json can't rate these")

    def test_every_species_in_the_zone_tables_has_base_stats(self):
        missing = sorted({sp for _where, sp in self._zone_species() if sp not in self.stats})
        self.assertEqual(missing, [], "base_stats.json has never heard of these")

    def test_the_zone_tables_are_already_canonically_spelled(self):
        for where, sp in self._zone_species():
            self.assertEqual(sp, canonical_species_name(sp), f"{sp!r} at {where}")

    def test_every_rated_species_has_base_stats_too(self):
        self.assertEqual([k for k in self.rates if k not in self.stats], [])

    def test_catch_rates_agree_with_the_rom_table(self):
        # They must: safari_pokemon.json's are hand-entered, base_stats.json's are ROM-derived.
        for name, entry in self.rates.items():
            self.assertEqual(entry["catch_rate"], self.stats[name]["catch_rate"], name)


class TestTheFourSpeciesAreHuntableAgain(unittest.TestCase):
    """The user-visible symptom: the app offers these targets from safari_pokemon.json, so
    `areas_for_species` returning [] meant an expedition that could never find an area."""

    EXPECTED_AREAS = {"nidoran-f": ["Savannah"], "nidoran-m": ["Savannah"],
                      "farfetchd": ["Wetland"], "mr-mime": ["Forest"]}

    def test_each_one_resolves_to_its_area(self):
        for name, areas in self.EXPECTED_AREAS.items():
            self.assertEqual(areas_for_species(name), areas, name)
            self.assertTrue(locations_for_species(name), name)

    def test_the_whole_app_target_list_can_find_an_area(self):
        """Every species the app offers as a target must appear SOMEWHERE in the zone tables --
        otherwise picking it yields an expedition with an empty area dropdown."""
        unhuntable = sorted(n for n in basedata_json("safari_pokemon.json")
                            if not areas_for_species(n))
        self.assertEqual(unhuntable, [])

    def test_a_display_spelling_works_everywhere_a_slug_does(self):
        for canonical, spellings in AWKWARD.items():
            area = self.EXPECTED_AREAS[canonical][0]
            for spelling in spellings:
                self.assertEqual(areas_for_species(spelling),
                                 areas_for_species(canonical), spelling)
                self.assertEqual(methods_for_species(area, spelling),
                                 methods_for_species(area, canonical), spelling)
                self.assertEqual(block_requirement_for(area, spelling),
                                 block_requirement_for(area, canonical), spelling)
                self.assertEqual(safari_pokemon_by_name(spelling).name,
                                 safari_pokemon_by_name(canonical).name, spelling)
                self.assertEqual(base_stats_species(spelling)["name"], canonical, spelling)

    def test_they_really_do_occupy_a_slot(self):
        # Not just "the name resolves" -- the species is actually drawable there.
        forest = [sp for sp, _lv in resolve_safari_slots("Forest", "day", {"forest": 99})]
        self.assertIn("mr-mime", forest)

    def test_an_unknown_species_still_fails_loudly(self):
        with self.assertRaises(KeyError) as ctx:
            safari_pokemon_by_name("not-a-real-species")
        self.assertIn("safari_pokemon.json", str(ctx.exception))
        self.assertEqual(areas_for_species("not-a-real-species"), [])


if __name__ == "__main__":
    unittest.main()
