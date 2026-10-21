"""base_stats.json holds every Gen 4 species, with the game's own numbers.

It used to hold 26, fetched from PokeAPI with a hand-maintained list of post-Gen-4 changes to
correct for. That works for 26 and cannot work for 493: it only catches what somebody thought to
look up, and a silently-modern stat does not announce itself -- it mis-derives a target's whole
spread from the entered IVs, and the run contradicts on the first hit.

So the source is now `files/poketool/personal/personal.json` from the decompilation, which is
Gen-4-exact by construction. Electrode is the reported example: **Speed 140** here, 150 from
Gen 8 onward.

clayton-rp2.
"""
import unittest

from claytonlib._resources import basedata_json
from claytonlib.battle.stats import abilities, species

DATA = basedata_json("base_stats.json")
LAST_GEN4_DEX = 493

#: Rows for a SPECIES, which is what a dex number names. A form row carries `forme_of` and shares
#: its base species' number, so the "one row per dex number" invariant is about these only.
SPECIES_ROWS = {k: e for k, e in DATA.items() if "forme_of" not in e}
#: The nine alternate forms, which exist in the file because Platinum's Distortion World Giratina
#: is the Origin forme -- a different stat line AND a different ability from the species row
#: (clayton-6xu.3.4).
FORME_ROWS = {k: e for k, e in DATA.items() if "forme_of" in e}


class TestCoverage(unittest.TestCase):
    def test_every_gen4_species_is_present(self):
        self.assertEqual(len(SPECIES_ROWS), LAST_GEN4_DEX)

    def test_the_dex_numbers_are_exactly_one_through_493(self):
        self.assertEqual(sorted(e["dex_no"] for e in SPECIES_ROWS.values()),
                         list(range(1, LAST_GEN4_DEX + 1)))

    def test_no_species_is_duplicated_under_two_keys(self):
        """`giratina` and `giratina-altered` both appeared for one ROM row when the alias was
        added to the key map instead of replacing the naive key -- 494 entries for 493 species."""
        self.assertEqual(len({e["dex_no"] for e in SPECIES_ROWS.values()}), LAST_GEN4_DEX)


class TestTheFormes(unittest.TestCase):
    """Nine rows, each a form of a species that is also in the file.

    They are here for one reason: Platinum's Distortion World Giratina is the **Origin** forme,
    which is 120/100/120/100 with **Levitate** against Altered's 100/120/100/120 with
    **Pressure**. A species-keyed table could hold only one of the two, so `has_pressure` asked
    about the species would be wrong for one of the two fights -- and wrong in the expensive
    direction, since assuming Pressure halves every PP budget the solver plans against.
    """

    def test_there_are_twelve_of_them(self):
        self.assertEqual(len(FORME_ROWS), 12)

    def test_each_names_a_base_species_that_exists(self):
        for key, entry in FORME_ROWS.items():
            with self.subTest(key):
                self.assertIn(entry["forme_of"], SPECIES_ROWS)

    def test_a_forme_shares_its_species_dex_number(self):
        """Because that is what a dex number is. Giratina Origin is 487, like Altered."""
        for key, entry in FORME_ROWS.items():
            with self.subTest(key):
                self.assertEqual(entry["dex_no"], DATA[entry["forme_of"]]["dex_no"])

    def test_giratinas_two_formes_differ_in_stats_and_ability(self):
        altered, origin = species("giratina-altered"), species("giratina-origin")
        self.assertEqual(altered["base_stats"]["def"], 120)
        self.assertEqual(origin["base_stats"]["def"], 100)
        self.assertEqual(altered["base_stats"]["atk"], 100)
        self.assertEqual(origin["base_stats"]["atk"], 120)
        self.assertEqual(abilities("giratina-altered"), ("Pressure",))
        self.assertEqual(abilities("giratina-origin"), ("Levitate",))
        # Everything else about them agrees, which is why only these two fields are checked.
        self.assertEqual(altered["types"], origin["types"])
        self.assertEqual(altered["catch_rate"], origin["catch_rate"])

    def test_a_bare_giratina_is_now_ambiguous_rather_than_silently_altered(self):
        """It used to resolve to `giratina-altered` through the suffix fallback, because that was
        the only match. With both formes present the honest answer is a refusal naming them --
        and `targets.resolve` gives the same answer for the same reason."""
        with self.assertRaises(KeyError) as caught:
            species("giratina")
        self.assertIn("giratina-origin", str(caught.exception))

    def test_the_keys_the_project_already_used_still_resolve(self):
        """A regenerate must not rename an existing key: `targets.py`, saved hunts and party
        rows all refer to species by these strings."""
        for key in ("suicune", "ho-oh", "lugia", "latias", "latios", "magneton", "ampharos",
                    "smeargle", "chatot", "natu", "giratina-altered", "mamoswine", "togekiss",
                    "granbull", "sudowoodo", "snorlax", "gyarados", "magnemite"):
            with self.subTest(key):
                self.assertIn(key, DATA)

    def test_awkwardly_named_species_came_through(self):
        for key in ("nidoran-f", "nidoran-m", "farfetchd", "mr-mime", "mime-jr", "porygon-z",
                    "ho-oh", "deoxys", "wormadam", "rotom", "shaymin"):
            with self.subTest(key):
                self.assertIn(key, DATA)


class TestTheNumbersAreGen4(unittest.TestCase):
    def test_electrode_is_140_not_150(self):
        """The reported case. PokeAPI says 150, which is Gen 8."""
        self.assertEqual(species("electrode")["base_stats"]["spe"], 140)

    def test_a_sample_of_other_post_gen4_stat_changes(self):
        """Species whose stats moved after Gen 4, each pinned at its Gen 4 value. These are
        exactly what a PokeAPI fetch would get wrong, so they are the test that matters."""
        for key, stat, gen4 in (("butterfree", "spa", 80),      # 90 from Gen 6
                                ("beedrill", "atk", 80),         # 90 from Gen 6
                                ("pidgeot", "spe", 91),          # 101 from Gen 6
                                ("pikachu", "def", 30),          # 40 from Gen 6
                                ("raichu", "spe", 100),          # 110 from Gen 6
                                ("nidoqueen", "atk", 82),        # 92 from Gen 6
                                ("nidoking", "atk", 92),         # 102 from Gen 6
                                ("clefable", "spa", 85),         # 95 from Gen 6
                                ("wigglytuff", "spa", 75),       # 85 from Gen 6
                                ("vileplume", "spa", 100),       # 110 from Gen 6
                                ("poliwrath", "atk", 85),        # 95 from Gen 6
                                ("alakazam", "spd", 85),         # 95 from Gen 6
                                ("victreebel", "spd", 60),       # 70 from Gen 6
                                ("golem", "atk", 110),           # 120 from Gen 6
                                ("ampharos", "def", 75)):        # 85 from Gen 6
            with self.subTest(key=key, stat=stat):
                self.assertEqual(species(key)["base_stats"][stat], gen4)

    def test_the_catch_rates_that_disagreed_with_pokeapi(self):
        """Five entries the ROM corrected when it replaced the fetched data. The first four are
        the documented Gen 4 figures; **Rayquaza is 3 in HGSS's own table** where PokeAPI reports
        45, and the ROM is what this tool simulates against."""
        for key, rate in (("dialga", 30), ("palkia", 30), ("groudon", 5), ("kyogre", 5),
                          ("rayquaza", 3)):
            with self.subTest(key):
                self.assertEqual(species(key)["catch_rate"], rate)

    def test_every_entry_is_marked_as_rom_sourced(self):
        for key, entry in DATA.items():
            with self.subTest(key):
                self.assertEqual(entry.get("source"), "rom")


class TestTheShapeIsUnchanged(unittest.TestCase):
    def test_every_entry_has_what_the_code_reads(self):
        for key, entry in DATA.items():
            with self.subTest(key):
                for field in ("name", "dex_no", "base_stats", "types", "abilities",
                              "catch_rate", "hms"):
                    self.assertIn(field, entry)
                self.assertEqual(entry["name"], key)
                self.assertEqual(set(entry["base_stats"]),
                                 {"hp", "atk", "def", "spa", "spd", "spe"})
                self.assertTrue(1 <= len(entry["types"]) <= 2)
                self.assertTrue(1 <= entry["catch_rate"] <= 255)

    def test_a_single_typed_species_stores_one_type(self):
        """The ROM repeats the type in both slots; the project stores one."""
        self.assertEqual(species("electrode")["types"], ["Electric"])
        self.assertEqual(species("magneton")["types"], ["Electric", "Steel"])

    def test_abilities_keep_their_slot_order(self):
        """`has_pressure` and the facade read slot 0, so the order is meaningful."""
        self.assertEqual(abilities("electrode"), ("Soundproof", "Static"))
        self.assertEqual(abilities("lugia"), ("Pressure",))

    def test_the_gen4_ability_spellings_are_kept(self):
        """"Compoundeyes" and "Lightningrod" are what the Gen 4 ability screen says; they became
        two words in Gen 6. A modern spelling here would be the anachronism this import exists
        to remove."""
        self.assertIn("Compoundeyes", abilities("butterfree"))
        self.assertIn("Lightningrod", abilities("rhyhorn"))

    def test_derive_species_stats_works_for_a_newly_added_species(self):
        """The point of the import: any species can now be a target or a party member."""
        from claytonlib.battle.stats import derive_species_stats

        stats = derive_species_stats("tentacruel", 50, "Hardy")
        self.assertEqual(set(stats), {"hp", "atk", "def", "spa", "spd", "spe"})
        self.assertGreater(stats["hp"], 0)


class TestGenderFromTheRom(unittest.TestCase):
    """Decoded because the Love Ball turns on it: ``catchRate *= 8`` needs
    ``attacker.gender != target.gender``, which a genderless species cannot satisfy even against
    itself (notes/lugia_love_ball.md sec 1).
    """

    def test_lugia_is_genderless_which_is_why_the_love_ball_is_times_one(self):
        self.assertTrue(species("lugia")["genderless"])

    def test_the_other_genderless_lines(self):
        for key in ("magnemite", "magneton", "voltorb", "electrode", "staryu", "starmie",
                    "ditto", "porygon", "beldum", "metang", "metagross", "bronzor"):
            with self.subTest(key):
                self.assertTrue(species(key)["genderless"], key)

    def test_a_gendered_species_carries_its_ratio_instead(self):
        self.assertFalse(species("bulbasaur")["genderless"])
        self.assertEqual(species("bulbasaur")["female_ratio"], 0.125)
        self.assertEqual(species("chansey")["female_ratio"], 1.0)
        self.assertEqual(species("tauros")["female_ratio"], 0.0)

    def test_genderless_and_female_ratio_never_coexist(self):
        for key, entry in DATA.items():
            with self.subTest(key):
                self.assertEqual(entry["genderless"], "female_ratio" not in entry)


if __name__ == "__main__":
    unittest.main()
