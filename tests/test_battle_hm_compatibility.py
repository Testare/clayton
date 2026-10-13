"""HM compatibility, read out of the decompilation rather than from PokeAPI.

`access_warnings` can say "nobody knows Surf or Whirlpool". The useful next sentence is who
*could* learn it -- and for the Lugia party the answer is nobody at all, which is a party-planning
fact a player would otherwise find by checking six move pools by hand.

PokeAPI is the wrong source for this specifically: the HM list itself differs inside Gen 4 (HGSS
made Flash a TM where DPPt had it as HM05) and move pools have shifted every generation since.
`one-offs/populate_hm_compatibility.py` reads `files/poketool/personal/personal.json`, whose
`hms` entries are 1-based HM01..HM08.

clayton-957.29.
"""
import unittest

from claytonlib.battle.stats import can_learn_hm, learnable_hms, species
from claytonlib.battle_compass.targets import access_warnings

#: The planned Lugia party.
PARTY = {"Natu": ["Teleport"], "Magneton": ["Thunder Wave"], "Ampharos": ["Flash"],
         "Smeargle": ["False Swipe"], "Chatot": ["Sing"]}
SPECIES = {"Natu": "natu", "Magneton": "magneton", "Ampharos": "ampharos",
           "Smeargle": "smeargle", "Chatot": "chatot"}


class TestTheDataLandedCorrectly(unittest.TestCase):
    def test_the_indexing_probes_hold(self):
        """The same species the populator checks, asserted again here so the shipped DATA is
        verified and not just the script that produced it. A one-off that stops being run is the
        normal way for this kind of file to drift."""
        self.assertEqual(set(learnable_hms("gyarados")),
                         {"Surf", "Strength", "Whirlpool", "Rock Smash", "Waterfall"})

    def test_an_empty_list_is_a_real_answer_not_a_missing_one(self):
        """Natu, Magneton and Smeargle genuinely learn no HM at all, so `()` has to mean that
        rather than "not recorded" -- which is why `can_learn_hm` is three-valued and this is
        not."""
        for name in ("natu", "magneton", "smeargle"):
            with self.subTest(name):
                self.assertEqual(learnable_hms(name), ())
                self.assertIn("hms", species(name))
                self.assertIs(can_learn_hm(name, "Surf"), False)

    def test_every_recorded_species_has_the_field(self):
        from claytonlib._resources import basedata_json

        for key, entry in basedata_json("base_stats.json").items():
            with self.subTest(key):
                self.assertIn("hms", entry, f"{key} missing HM data")

    def test_the_names_are_spelled_as_the_move_table_spells_them(self):
        """Or `can_learn_hm` would silently never match, and `access_warnings` would report that
        nobody can carry a move everyone can."""
        from claytonlib._resources import basedata_json
        from claytonlib.moves import resolve_move

        seen = {hm for entry in basedata_json("base_stats.json").values()
                for hm in entry.get("hms", ())}
        self.assertTrue(seen)
        for hm in sorted(seen):
            with self.subTest(hm):
                self.assertIsNotNone(resolve_move(hm))

    def test_flash_is_not_an_hm_in_hgss(self):
        """It is TM70 here and was HM05 in DPPt -- the concrete reason this data had to come from
        the HGSS decomp. Ampharos carries Flash in the plan and must not be credited with an HM
        slot for it."""
        from claytonlib._resources import basedata_json

        for entry in basedata_json("base_stats.json").values():
            self.assertNotIn("Flash", entry.get("hms", ()))

    def test_every_entry_is_rom_sourced_now(self):
        """This used to assert the opposite for two species, and rightly: `source: rom` meant
        "the BASE STATS were transcribed from the decomp", and the HM import must not have
        claimed it of PokeAPI-fetched stats. clayton-rp2 made it true of all 493 by rebuilding
        the whole file from the ROM, so the claim is now universal rather than per-entry."""
        from claytonlib._resources import basedata_json

        data = basedata_json("base_stats.json")
        for key in ("ampharos", "magneton", "lugia", "electrode", "tentacruel"):
            with self.subTest(key):
                self.assertEqual(data[key].get("source"), "rom")


class TestTheThreeValuedAnswer(unittest.TestCase):
    def test_unknown_is_distinct_from_no(self):
        """"Cannot carry Surf" and "I have no data" lead to different advice, and collapsing
        them would tell a player their Tentacruel cannot Surf because nothing recorded it."""
        self.assertIs(can_learn_hm("magneton", "Surf"), False)
        self.assertIs(can_learn_hm("gyarados", "Surf"), True)
        # Every Gen 4 species is in the file now (clayton-rp2), so "unknown" means Gen 5 and
        # later -- which is the real boundary, and a better test than the arbitrary gap that
        # used to exist. Tentacruel was the example here and is now recorded.
        self.assertIs(can_learn_hm("tentacruel", "Surf"), True)
        with self.assertRaises(KeyError):
            can_learn_hm("zorua", "Surf")

    def test_case_and_whitespace_do_not_matter(self):
        for spelling in ("Surf", "surf", "  SURF  "):
            with self.subTest(spelling):
                self.assertIs(can_learn_hm("gyarados", spelling), True)


class TestTheWarningBecomesActionable(unittest.TestCase):
    def test_the_lugia_party_is_told_that_nobody_can_carry_it(self):
        """The finding that justifies the whole import."""
        advice = access_warnings("lugia", PARTY, SPECIES)[-1]
        self.assertIn("None of your party can learn either move", advice)
        # The slot advice is computed from how many are actually configured -- five here, so
        # nothing has to be dropped.
        self.assertIn("5 of 6 listed", advice)

    def test_a_capable_party_member_is_named_instead(self):
        party = dict(PARTY, Gyarados=["Waterfall"])
        species_map = dict(SPECIES, Gyarados="gyarados")
        advice = access_warnings("lugia", party, species_map)[-1]
        self.assertIn("Can learn: Gyarados (Surf and Whirlpool)", advice)
        self.assertNotIn("None of your party", advice)

    def test_the_conjunction_is_AND_for_what_a_carrier_covers(self):
        """"Gyarados (Surf or Whirlpool)" would read as a choice and imply a second carrier is
        still needed."""
        party = dict(PARTY, Gyarados=["Waterfall"])
        species_map = dict(SPECIES, Gyarados="gyarados")
        warnings = access_warnings("lugia", party, species_map)
        self.assertIn("Surf and Whirlpool", warnings[-1])
        # The missing list stays a disjunction.
        self.assertIn("Nothing knows Surf or Whirlpool", warnings[0])

    def test_an_unrecorded_species_makes_it_stay_SILENT(self):
        """Not "nobody can" -- that would send a player to catch a Pokemon they already own."""
        # A Gen 5 species, since every Gen 4 one is now recorded. Tentacruel used to stand in
        # for "unrecorded" and is now in the file -- which is why the next test exists.
        party = dict(PARTY, Zorua=["Scratch"])
        species_map = dict(SPECIES, Zorua="zorua")
        joined = " ".join(access_warnings("lugia", party, species_map))
        self.assertNotIn("None of your party", joined)
        self.assertNotIn("Can learn", joined)

    def test_a_tentacruel_is_NAMED_now_that_it_is_recorded(self):
        """The payoff of the 493-species import: the carrier the player actually chose is named
        instead of silently skipped."""
        party = dict(PARTY, Tentacruel=["Cut"])
        species_map = dict(SPECIES, Tentacruel="tentacruel")
        advice = access_warnings("lugia", party, species_map)[-1]
        self.assertIn("Can learn: Tentacruel (Surf and Whirlpool)", advice)

    def test_a_blank_species_also_makes_it_silent(self):
        party = dict(PARTY, Mystery=["Tackle"])
        species_map = dict(SPECIES, Mystery="")
        joined = " ".join(access_warnings("lugia", party, species_map))
        self.assertNotIn("None of your party", joined)

    def test_omitting_the_species_map_keeps_the_original_behaviour(self):
        joined = " ".join(access_warnings("lugia", PARTY))
        self.assertNotIn("Can learn", joined)
        self.assertNotIn("None of your party", joined)

    def test_only_the_MISSING_move_is_suggested_for(self):
        """With Surf already covered, the suggestion must be about Whirlpool alone."""
        party = dict(PARTY, Chatot=["Surf"], Gyarados=["Waterfall"])
        species_map = dict(SPECIES, Gyarados="gyarados")
        warnings = access_warnings("lugia", party, species_map)
        self.assertIn("Nothing knows Whirlpool", warnings[0])
        self.assertIn("Can learn: Gyarados (Whirlpool)", warnings[-1])


if __name__ == "__main__":
    unittest.main()
