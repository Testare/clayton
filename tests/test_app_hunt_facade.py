"""Facade coverage for the Battle Compass surface: party Pokemon and Hunts."""
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore

MAGNETON = dict(
    name="Magneton", species="magneton", level=30, ability="Sturdy",
    stats={"hp": 79, "atk": 50, "def": 65, "spa": 77, "spd": 56, "spe": 56},
    moveset=["Thunder Wave"], max_pp={"1": 20},
)
SMEARGLE = dict(
    name="Smeargle", species="smeargle", level=60, ability="Technician",
    stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
    moveset=["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    max_pp={"1": 40, "2": 5, "3": 20, "4": 15},
)
MAMOSWINE = dict(
    name="Mamoswine", species="mamoswine", level=90,
    stats={"hp": 325, "atk": 300, "def": 200, "spa": 180, "spd": 140, "spe": 190},
)
PERFECT_IVS = {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}


class HuntFacadeCase(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.profile = self.api.create_profile({"name": "Gold"})
        self.ids = {
            spec["name"]: self.api.add_party_pokemon(self.profile["id"], spec)["pokemon_id"]
            for spec in (MAGNETON, SMEARGLE, MAMOSWINE)
        }

    def _hunt(self, **overrides) -> dict:
        fields = {
            "name": "Fast Ball Suicune",
            "profile_id": self.profile["id"],
            "capture_ball": "Fast Ball",
            "target": {"species": "suicune", "level": 40, "nature": "Bold",
                       "ivs": dict(PERFECT_IVS)},
            "party": [{"pokemon_id": self.ids["Magneton"]},
                      {"pokemon_id": self.ids["Smeargle"], "held_item": "Silk Scarf"}],
            "key_seed": 0xEC1504DC,
            "initial_time": "2026-09-29T12:00:00",
            "vector_ms": 382791,
        }
        fields.update(overrides)
        return self.api.create_hunt(fields)


class TestPartyPokemon(HuntFacadeCase):
    def test_added_pokemon_appear_on_the_profile_with_validation(self):
        profile = self.api.get_profile(self.profile["id"])
        self.assertEqual([p["name"] for p in profile["party"]],
                         ["Magneton", "Smeargle", "Mamoswine"])
        by_name = {p["name"]: p for p in profile["party"]}
        self.assertTrue(by_name["Smeargle"]["is_hunt_ready"])
        self.assertEqual(by_name["Smeargle"]["warnings"], [])

    def test_a_moveless_wall_is_hunt_ready_but_warns(self):
        by_name = {p["name"]: p for p in self.api.get_profile(self.profile["id"])["party"]}
        self.assertTrue(by_name["Mamoswine"]["is_hunt_ready"])
        self.assertTrue(any("Struggle" in w for w in by_name["Mamoswine"]["warnings"]))

    def test_a_half_entered_pokemon_saves_but_is_not_hunt_ready(self):
        result = self.api.add_party_pokemon(self.profile["id"], {"name": "Work in progress"})
        self.assertNotEqual(result["hard_errors"], [])
        by_id = {p["id"]: p for p in result["profile"]["party"]}
        self.assertFalse(by_id[result["pokemon_id"]]["is_hunt_ready"])

    def test_updating_stats_is_allowed_and_persists(self):
        self.api.update_party_pokemon(self.profile["id"], self.ids["Magneton"],
                                      {**MAGNETON, "level": 31})
        profile = self.api.get_profile(self.profile["id"])
        by_name = {p["name"]: p for p in profile["party"]}
        self.assertEqual(by_name["Magneton"]["level"], 31)

    def test_an_update_without_a_name_does_not_blank_it(self):
        fields = {k: v for k, v in MAGNETON.items() if k != "name"}
        self.api.update_party_pokemon(self.profile["id"], self.ids["Magneton"],
                                      {**fields, "level": 32})
        by_name = {p["name"]: p for p in self.api.get_profile(self.profile["id"])["party"]}
        self.assertIn("Magneton", by_name)
        self.assertEqual(by_name["Magneton"]["level"], 32)

    def test_removal_reports_which_hunts_referenced_it(self):
        self._hunt()
        result = self.api.remove_party_pokemon(self.profile["id"], self.ids["Smeargle"])
        self.assertEqual(result["removed"]["name"], "Smeargle")
        self.assertEqual(result["affected_hunts"], ["Fast Ball Suicune"])

    def test_removing_an_unreferenced_pokemon_affects_no_hunts(self):
        self._hunt()
        result = self.api.remove_party_pokemon(self.profile["id"], self.ids["Mamoswine"])
        self.assertEqual(result["affected_hunts"], [])


class TestHuntCrud(HuntFacadeCase):
    def test_create_list_get_roundtrip(self):
        hunt = self._hunt()
        listed = self.api.list_hunts(self.profile["id"])
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["target"], "suicune")
        self.assertEqual(listed[0]["capture_ball"], "Fast Ball")
        self.assertEqual(self.api.get_hunt(hunt["id"])["name"], "Fast Ball Suicune")

    def test_a_hunt_needs_a_name_and_a_profile(self):
        with self.assertRaises(ValueError):
            self.api.create_hunt({"profile_id": self.profile["id"]})
        with self.assertRaises(ValueError):
            self.api.create_hunt({"name": "Nameless profile"})

    def test_a_hunt_referencing_a_missing_profile_fails_early(self):
        with self.assertRaises(ValueError):
            self.api.create_hunt({"name": "Orphan", "profile_id": "nope"})

    def test_names_are_unique_across_profiles(self):
        self._hunt()
        other = self.api.create_profile({"name": "Silver"})
        with self.assertRaises(ValueError) as caught:
            self.api.create_hunt({"name": "fast ball suicune", "profile_id": other["id"]})
        self.assertIn("already exists", str(caught.exception))

    def test_a_hunt_does_not_collide_with_itself_on_save(self):
        hunt = self._hunt()
        hunt["capture_ball"] = "Timer Ball"
        self.assertEqual(self.api.save_hunt(hunt)["capture_ball"], "Timer Ball")

    def test_save_requires_an_id(self):
        with self.assertRaises(ValueError):
            self.api.save_hunt({"name": "x", "profile_id": self.profile["id"]})

    def test_completed_hunts_sort_below_incomplete_ones(self):
        first = self._hunt()
        self._hunt(name="Another hunt")
        self.api.set_hunt_completed(first["id"], True)
        self.assertEqual([h["name"] for h in self.api.list_hunts()],
                         ["Another hunt", "Fast Ball Suicune"])

    def test_listing_filters_by_profile(self):
        self._hunt()
        other = self.api.create_profile({"name": "Silver"})
        self.assertEqual(self.api.list_hunts(other["id"]), [])

    def test_deleting_a_hunt_leaves_the_party_alone(self):
        hunt = self._hunt()
        self.assertTrue(self.api.delete_hunt(hunt["id"]))
        self.assertEqual(self.api.list_hunts(), [])
        self.assertEqual(len(self.api.get_profile(self.profile["id"])["party"]), 3)

    def test_getting_a_missing_hunt_raises(self):
        with self.assertRaises(ValueError):
            self.api.get_hunt("nope")

    def test_a_hunt_document_carries_no_mid_battle_state(self):
        """Configuration only; the encounter itself runs in Battle Compass (sec 15.4)."""
        doc = self._hunt()
        for absent in ("current_hp", "rng_offset", "candidates", "turn", "stat_stages"):
            self.assertNotIn(absent, doc)


class TestHuntReadiness(HuntFacadeCase):
    def test_the_fixture_party_is_ready_and_scores_well(self):
        readiness = self.api.hunt_readiness(self._hunt()["id"])
        self.assertEqual(readiness["hard_errors"], [])
        self.assertEqual(readiness["alphabet"]["reachability_percent"], 99)
        self.assertEqual(readiness["alphabet"]["warnings"], [])
        self.assertEqual(readiness["speed"]["warnings"], [])

    def test_target_stats_are_derived_from_the_entered_ivs_and_nature(self):
        readiness = self.api.hunt_readiness(self._hunt()["id"])
        self.assertEqual(readiness["target_stats"],
                         {"hp": 142, "atk": 69, "def": 119, "spa": 89, "spd": 109, "spe": 85})

    def test_an_incomplete_hunt_reports_hard_errors_and_no_target_stats(self):
        hunt = self.api.create_hunt({"name": "Bare", "profile_id": self.profile["id"]})
        readiness = self.api.hunt_readiness(hunt["id"])
        self.assertNotEqual(readiness["hard_errors"], [])
        self.assertIsNone(readiness["target_stats"])

    def test_a_single_move_party_is_warned_about(self):
        """The ~36% case: one filler action makes most seeds unwinnable (sec 1.1)."""
        hunt = self._hunt(party=[{"pokemon_id": self.ids["Magneton"]}])
        alphabet = self.api.hunt_readiness(hunt["id"])["alphabet"]
        # Thunder Wave alone, plus the ball and item costs the mechanics always provide.
        self.assertLessEqual(alphabet["reachability_percent"], 99)
        self.assertIn("Thunder Wave", " ".join(alphabet["costs_by_action"]))

    def test_the_party_battlers_carry_their_ABILITY(self):
        """A regression test for a one-field omission with a wide blast radius.

        `_survivability_warnings` built every party Battler without `ability`, so the readiness
        advice judged the whole party ability-less: an Insomnia holder was told a target could
        sleep it, an Early Bird holder got the unhalved sleep clock, and the sentence naming the
        carrier could never fire because `_sleep_answer` had nothing to find. The RUN path has
        always passed it (`hunt_run_setup`'s `battler_for`), so the simulation was right and only
        the pre-hunt advice was wrong -- which is exactly the kind of bug a test on the facade
        catches and a test on `survivability_warnings` cannot (clayton-4wr.1.3).

        Darkrai rather than Suicune, because Suicune cannot sleep anybody and the warning that
        reads the ability would not fire either way.
        """
        noctowl = self.api.add_party_pokemon(self.profile["id"], {
            "name": "Noctowl", "species": "noctowl", "level": 50, "ability": "Insomnia",
            "stats": {"hp": 180, "atk": 70, "def": 60,
                      "spa": 86, "spd": 96, "spe": 80}})["pokemon_id"]
        hunt = self._hunt(
            target={"species": "darkrai", "level": 50, "nature": "Timid",
                    "ivs": dict(PERFECT_IVS)},
            party=[{"pokemon_id": self.ids["Smeargle"]}, {"pokemon_id": noctowl}])
        warnings = " ".join(self.api.hunt_readiness(hunt["id"])["survivability"])
        self.assertIn("Noctowl (Insomnia) is immune to it", warnings)
        # And the carrier itself is no longer warned about a state it cannot enter.
        self.assertNotIn("Noctowl (180 HP) loses", warnings)

    def test_a_party_pokemon_removed_from_the_profile_becomes_a_hard_error(self):
        hunt = self._hunt()
        self.api.remove_party_pokemon(self.profile["id"], self.ids["Smeargle"])
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertTrue(any("no longer on the profile" in e for e in errors))

    def test_our_own_paralysis_is_included_only_when_the_target_can_inflict_it(self):
        """Suicune cannot paralyze -- Rain Dance / Gust / Aurora Beam / Mist, and Pressure
        rather than Static -- so those rows are a state the player cannot reach. They used to
        appear for every target because `include_our_paralysis` defaulted on and nothing derived
        it (clayton-36b), which halved the table's signal.
        """
        readiness = self.api.hunt_readiness(self._hunt()["id"])
        labels = {c["ours"] for c in readiness["speed"]["checks"]}
        self.assertNotIn("Smeargle (paralyzed)", labels)
        self.assertIn("Smeargle", labels)

    def test_and_they_come_back_against_a_target_that_CAN(self):
        """Asserted through `speed_checks` rather than a hunt, because no configured target has
        a paralysing move yet -- effect 6 is in MODELLED_OUR_EFFECTS only, so a Dragon Breath
        target is still refused. The roamer Lati twins are what will need this."""
        from claytonlib.battle.readiness import speed_checks

        labels = {c.ours for c in speed_checks({"Smeargle": 160}, 80,
                                               include_our_paralysis=True)}
        self.assertIn("Smeargle (paralyzed)", labels)

    def test_every_party_member_is_speed_checked_not_only_the_lead(self):
        """A tie spends extra rolls the simulator does not model, so a bench member that ties
        the target breaks the run the moment it is sent out -- which, now that a faint switches
        a replacement in, happens without anyone choosing it."""
        readiness = self.api.hunt_readiness(self._hunt()["id"])
        labels = {c["ours"] for c in readiness["speed"]["checks"]}
        self.assertIn("Magneton", labels)
        self.assertIn("Smeargle", labels)

    def test_an_unknown_target_species_is_reported_not_raised(self):
        hunt = self._hunt(target={"species": "missingno", "level": 40, "nature": "Bold",
                                  "ivs": dict(PERFECT_IVS)})
        self.assertIn("error", self.api.hunt_readiness(hunt["id"])["target_stats"])


if __name__ == "__main__":
    unittest.main()


class TestCalibrationModel(HuntFacadeCase):
    """A hunt uses the profile's active calibration model. There is nothing to pick, which is
    why readiness reports it rather than demanding it."""

    def test_readiness_reports_the_active_model_without_blocking(self):
        readiness = self.api.hunt_readiness(self._hunt()["id"])
        self.assertIn("calibration_model", readiness)
        self.assertEqual(
            [e for e in readiness["hard_errors"] if "calibration" in e.lower()], [])

    def test_a_fresh_profile_already_has_a_model_resolved(self):
        """Profiles are seeded with a bundled Standard model active, so this is never empty."""
        self.assertIsNotNone(self.api.hunt_readiness(self._hunt()["id"])["calibration_model"])


class TestMetronomeToolsWorkFromAHunt(HuntFacadeCase):
    """The Hunts UI offers Metronome Compass, because calibration belongs to the profile rather
    than to one quest. The tools reach it through the owner document, so a hunt has tosupport the
    same reads and writes an expedition does."""

    def test_a_hunt_round_trips_the_metronome_defaults_the_tools_store(self):
        hunt = self._hunt()
        hunt["last_target"] = {"initial_time": "2026-09-29T12:00:00", "vector_ms": 382791}
        hunt["last_metronome_defaults"] = {"seconds_window": 2, "delay_window": 10,
                                           "startrel": "", "tag": "t"}
        saved = self.api.save_hunt(hunt)
        self.assertEqual(saved["last_target"]["vector_ms"], 382791)
        reloaded = self.api.get_hunt(hunt["id"])
        self.assertEqual(reloaded["last_metronome_defaults"]["delay_window"], 10)

    def test_a_hunt_exposes_the_profile_id_the_tools_need(self):
        self.assertEqual(self.api.get_hunt(self._hunt()["id"])["profile_id"],
                         self.profile["id"])


class TestHuntAccess(HuntFacadeCase):
    """Reaching the encounter, which `hunt_readiness` was not asking about at all.

    Exercised through the facade rather than against `targets.access_warnings` directly, because
    the thing that was missing was the WIRING: the check is useless if the key never reaches the
    page. `move_coverage` gets the same treatment for the same reason -- it was computed from the
    day it was written and never rendered.
    """

    LAPRAS = dict(
        name="Lapras", species="lapras", level=40,
        stats={"hp": 150, "atk": 85, "def": 80, "spa": 85, "spd": 95, "spe": 60},
        moveset=["Surf", "Whirlpool", "Strength", "Waterfall"],
        max_pp={"1": 15, "2": 15, "3": 15, "4": 15},
    )

    def _lugia_hunt(self, **overrides):
        fields = {
            "name": "Love Ball Lugia",
            "capture_ball": "Love Ball",
            "target": {"species": "lugia", "level": 45, "nature": "Serious",
                       "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 17,
                               "spd": 31, "spe": 31}},
        }
        fields.update(overrides)
        return self._hunt(**fields)

    def test_a_lugia_hunt_warns_that_nobody_can_get_there(self):
        readiness = self.api.hunt_readiness(self._lugia_hunt()["id"])
        field = [w for w in readiness["access"] if "Nothing knows" in w]
        self.assertEqual(len(field), 1)
        self.assertIn("Surf or Whirlpool", field[0])
        self.assertIn("Whirl Islands", field[0])

    def test_it_is_a_warning_and_not_a_hard_error(self):
        """The player may be bringing a mule the hunt's party list does not mention, or may
        already be standing in front of the encounter."""
        readiness = self.api.hunt_readiness(self._lugia_hunt()["id"])
        self.assertEqual(readiness["hard_errors"], [])
        self.assertNotEqual(readiness["access"], [])

    def test_a_covered_party_goes_completely_quiet(self):
        """No Silver Wing nag left over: a key item you either have or cannot reach the encounter
        to try, so warning about it forever tells nobody anything."""
        mule = self.api.add_party_pokemon(self.profile["id"], self.LAPRAS)["pokemon_id"]
        hunt = self._lugia_hunt(party=[{"pokemon_id": self.ids["Magneton"]},
                                       {"pokemon_id": self.ids["Smeargle"],
                                        "held_item": "Silk Scarf"},
                                       {"pokemon_id": mule}])
        self.assertEqual(self.api.hunt_readiness(hunt["id"])["access"], [])

    def test_a_suicune_hunt_has_nothing_to_report(self):
        self.assertEqual(self.api.hunt_readiness(self._hunt()["id"])["access"], [])

    def test_the_requirement_is_reported_before_a_party_exists(self):
        """The most useful moment to hear "you will need Surf and Whirlpool"."""
        hunt = self._lugia_hunt(party=[])
        readiness = self.api.hunt_readiness(hunt["id"])
        self.assertEqual([w for w in readiness["access"] if "Nothing knows" in w and "of 6" in w],
                         [], "an unconfigured hunt does no slot arithmetic")
        self.assertEqual(len([w for w in readiness["access"] if "Nothing knows" in w]), 1)

    def test_surf_and_whirlpool_report_differently_in_move_coverage(self):
        """Surf is inert here (effect 257 is the Dive mirror of Gust's 149) and Whirlpool is
        not (effect 261 binds), so a mule's own moveset must not read as one undifferentiated
        warning."""
        mule = self.api.add_party_pokemon(self.profile["id"], self.LAPRAS)["pokemon_id"]
        hunt = self._lugia_hunt(party=[{"pokemon_id": self.ids["Smeargle"]},
                                       {"pokemon_id": mule}])
        coverage = self.api.hunt_readiness(hunt["id"])["move_coverage"]
        flagged = {c["move"]: c for c in coverage}
        self.assertNotIn("Surf", flagged)
        self.assertNotIn("Strength", flagged)
        self.assertNotIn("Waterfall", flagged)
        self.assertIn("Whirlpool", flagged)
        self.assertEqual(flagged["Whirlpool"]["pokemon"], "Lapras")
        self.assertIn("desynchronising", flagged["Whirlpool"]["reason"])


class TestTheSnapshotCarriesTheSpreadInputs(HuntFacadeCase):
    """clayton-1jd: the popup shows derived stats, so it needs what they were derived from."""

    def test_the_hunts_configured_nature_and_ivs_reach_the_snapshot(self):
        snap = self.api.hunt_session_start(self._hunt()["id"])["snapshot"]
        self.assertEqual(snap["target"]["nature"], "Bold")
        self.assertEqual(snap["target"]["ivs"], dict(PERFECT_IVS))

    def test_a_run_OVERRIDE_is_what_gets_shown(self):
        """Not the hunt's stored spread: the popup has to describe the Pokemon this run is
        actually simulating, or it would vouch for numbers nothing used."""
        hunt = self._hunt()
        snap = self.api.hunt_session_start(hunt["id"], {
            "target_nature": "Timid", "target_ivs": "18 15 16 26 1 4"})["snapshot"]
        self.assertEqual(snap["target"]["nature"], "Timid")
        self.assertEqual(snap["target"]["ivs"]["hp"], 18)
        self.assertEqual(snap["target"]["ivs"]["spe"], 4)

    def test_the_derived_stats_and_the_shown_inputs_agree(self):
        """The whole point -- if these could disagree the popup would be worse than nothing."""
        from claytonlib.battle.stats import derive_species_stats

        snap = self.api.hunt_session_start(self._hunt()["id"])["snapshot"]
        target = snap["target"]
        self.assertEqual(
            target["stats"],
            derive_species_stats("suicune", target["level"], target["nature"],
                                 ivs=target["ivs"]))
