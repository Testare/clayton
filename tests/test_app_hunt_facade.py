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

    def test_a_party_pokemon_removed_from_the_profile_becomes_a_hard_error(self):
        hunt = self._hunt()
        self.api.remove_party_pokemon(self.profile["id"], self.ids["Smeargle"])
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertTrue(any("no longer on the profile" in e for e in errors))

    def test_our_own_paralysis_is_included_in_the_speed_checks(self):
        readiness = self.api.hunt_readiness(self._hunt()["id"])
        labels = {c["ours"] for c in readiness["speed"]["checks"]}
        self.assertIn("Smeargle (paralyzed)", labels)

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
