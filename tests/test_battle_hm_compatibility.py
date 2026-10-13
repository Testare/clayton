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

    def test_base_stat_provenance_was_not_overwritten(self):
        """`source: rom` in this file means the BASE STATS were transcribed from the decomp. The
        HM import must not have claimed that of species whose stats came from PokeAPI."""
        from claytonlib._resources import basedata_json

        data = basedata_json("base_stats.json")
        self.assertEqual(data["ampharos"].get("source"), "rom")   # was rom before
        self.assertIsNone(data["magneton"].get("source"))          # was absent before
        self.assertIsNone(data["lugia"].get("source"))


class TestTheThreeValuedAnswer(unittest.TestCase):
    def test_unknown_is_distinct_from_no(self):
        """"Cannot carry Surf" and "I have no data" lead to different advice, and collapsing
        them would tell a player their Tentacruel cannot Surf because nothing recorded it."""
        self.assertIs(can_learn_hm("magneton", "Surf"), False)
        self.assertIs(can_learn_hm("gyarados", "Surf"), True)
        with self.assertRaises(KeyError):
            can_learn_hm("tentacruel", "Surf")      # not in base_stats.json at all

    def test_case_and_whitespace_do_not_matter(self):
        for spelling in ("Surf", "surf", "  SURF  "):
            with self.subTest(spelling):
                self.assertIs(can_learn_hm("gyarados", spelling), True)


class TestTheWarningBecomesActionable(unittest.TestCase):
    def test_the_lugia_party_is_told_that_nobody_can_carry_it(self):
        """The finding that justifies the whole import."""
        field = [w for w in access_warnings("lugia", PARTY, SPECIES) if "needs to reach" in w]
        self.assertEqual(len(field), 1)
        self.assertIn("None of your current party can learn either move", field[0])
        self.assertIn("not carrying yet", field[0])
        # The slot advice lives in `_room_note` now and is computed from how many are actually
        # configured -- five here, so nothing has to be dropped.
        self.assertIn("lists 5 of 6", field[0])

    def test_a_capable_party_member_is_named_instead(self):
        party = dict(PARTY, Gyarados=["Waterfall"])
        species_map = dict(SPECIES, Gyarados="gyarados")
        field = [w for w in access_warnings("lugia", party, species_map)
                 if "needs to reach" in w][0]
        self.assertIn("Able to learn: Gyarados (Surf and Whirlpool)", field)
        self.assertNotIn("None of your current party", field)

    def test_the_conjunction_is_AND_for_what_a_carrier_covers(self):
        """"Gyarados (Surf or Whirlpool)" would read as a choice and imply a second carrier is
        still needed."""
        party = dict(PARTY, Gyarados=["Waterfall"])
        species_map = dict(SPECIES, Gyarados="gyarados")
        field = [w for w in access_warnings("lugia", party, species_map)
                 if "needs to reach" in w][0]
        self.assertIn("Surf and Whirlpool", field)
        self.assertIn("knows Surf or Whirlpool", field)      # the missing list stays a disjunction

    def test_an_unrecorded_species_makes_it_stay_SILENT(self):
        """Not "nobody can" -- that would send a player to catch a Pokemon they already own."""
        party = dict(PARTY, Tentacruel=["Cut"])
        species_map = dict(SPECIES, Tentacruel="tentacruel")
        field = [w for w in access_warnings("lugia", party, species_map)
                 if "needs to reach" in w][0]
        self.assertNotIn("None of your current party", field)
        self.assertNotIn("Able to learn", field)

    def test_a_blank_species_also_makes_it_silent(self):
        party = dict(PARTY, Mystery=["Tackle"])
        species_map = dict(SPECIES, Mystery="")
        field = [w for w in access_warnings("lugia", party, species_map)
                 if "needs to reach" in w][0]
        self.assertNotIn("None of your current party", field)

    def test_omitting_the_species_map_keeps_the_original_behaviour(self):
        field = [w for w in access_warnings("lugia", PARTY) if "needs to reach" in w][0]
        self.assertNotIn("Able to learn", field)
        self.assertNotIn("None of your current party", field)

    def test_only_the_MISSING_move_is_suggested_for(self):
        """With Surf already covered, the suggestion must be about Whirlpool alone."""
        party = dict(PARTY, Chatot=["Surf"], Gyarados=["Waterfall"])
        species_map = dict(SPECIES, Gyarados="gyarados")
        field = [w for w in access_warnings("lugia", party, species_map)
                 if "needs to reach" in w][0]
        self.assertIn("knows Whirlpool", field)
        self.assertIn("Able to learn: Gyarados (Whirlpool)", field)


if __name__ == "__main__":
    unittest.main()
