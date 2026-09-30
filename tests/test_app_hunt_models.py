"""Tests for the Battle Compass entities: PartyPokemon, Profile.party, Hunt.

The split under test comes from notes/battle_compass.md sec 15.4: party Pokemon live on the
profile because they are reused across hunts, held items and the target live on the hunt, and a
Hunt carries configuration only — never mid-battle state.
"""
import unittest

from app.models import Hunt, HuntSlot, HuntTarget, PartyPokemon, Profile, STAT_KEYS

# The section 11 reference fixture.
SMEARGLE = dict(
    species="smeargle", level=60, ability="Technician", gender="male",
    stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
    moveset=["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    max_pp={"1": 40, "2": 5, "3": 20, "4": 15},
)
MAGNETON = dict(
    species="magneton", level=30, ability="Sturdy",
    stats={"hp": 79, "atk": 50, "def": 65, "spa": 77, "spd": 56, "spe": 56},
    moveset=["Thunder Wave"], max_pp={"1": 20},
)
MAMOSWINE = dict(
    species="mamoswine", level=90,
    stats={"hp": 325, "atk": 300, "def": 200, "spa": 180, "spd": 140, "spe": 190},
)
PERFECT_IVS = {k: 31 for k in STAT_KEYS}


def _configured_hunt(profile: Profile) -> Hunt:
    return Hunt(
        name="Fast Ball Suicune", profile_id=profile.id, capture_ball="Fast Ball",
        target=HuntTarget(species="suicune", level=40, nature="Bold", ivs=dict(PERFECT_IVS)),
        party=[HuntSlot(pokemon_id=p.id) for p in profile.party],
        key_seed=0xEC1504DC, initial_time="2026-09-28T12:00:00",
        vector_ms=382791,
    )


class TestPartyPokemon(unittest.TestCase):
    def test_a_fully_entered_pokemon_has_no_errors_or_warnings(self):
        p = PartyPokemon(id=1, name="Smeargle", **SMEARGLE)
        self.assertEqual(p.hard_errors(), [])
        self.assertEqual(p.warnings(), [])
        self.assertEqual(p.speed, 160)

    def test_stats_are_required_because_the_simulation_cannot_work_around_them(self):
        p = PartyPokemon(id=1, name="Smeargle", species="smeargle", level=60)
        errors = " ".join(p.hard_errors())
        for stat in STAT_KEYS:
            self.assertIn(stat, errors)

    def test_species_and_level_are_required(self):
        p = PartyPokemon(id=1, name="Nameless")
        joined = " ".join(p.hard_errors())
        self.assertIn("species", joined)
        self.assertIn("level", joined)

    def test_more_than_four_moves_is_an_error(self):
        p = PartyPokemon(id=1, name="Smeargle", **{**SMEARGLE,
                                                   "moveset": ["a", "b", "c", "d", "e"]})
        self.assertTrue(any("at most 4" in e for e in p.hard_errors()))

    def test_a_movesless_wall_is_allowed_but_warns_about_struggle(self):
        """Mamoswine's role in the fixture: revive insurance, never attacking."""
        p = PartyPokemon(id=3, name="Mamoswine", **MAMOSWINE)
        self.assertEqual(p.hard_errors(), [])
        self.assertTrue(any("Struggle" in w for w in p.warnings()))

    def test_missing_max_pp_warns_per_slot(self):
        p = PartyPokemon(id=1, name="Smeargle", **{**SMEARGLE, "max_pp": {"1": 40}})
        warnings = " ".join(p.warnings())
        for move in ("Mean Look", "Sweet Scent", "Spore"):
            self.assertIn(move, warnings)
        self.assertNotIn("False Swipe", warnings)

    def test_missing_ability_warns(self):
        p = PartyPokemon(id=1, name="Smeargle", **{**SMEARGLE, "ability": None})
        self.assertTrue(any("ability" in w for w in p.warnings()))

    def test_speed_is_none_when_not_entered(self):
        self.assertIsNone(PartyPokemon(id=1, name="x").speed)

    def test_roundtrip(self):
        p = PartyPokemon(id=7, name="Smeargle", **SMEARGLE)
        self.assertEqual(PartyPokemon.from_dict(p.to_dict()).to_dict(), p.to_dict())


class TestProfileParty(unittest.TestCase):
    def test_ids_increment_and_never_rewind(self):
        profile = Profile(name="Gold")
        a = profile.add_party_pokemon("Smeargle", **SMEARGLE)
        b = profile.add_party_pokemon("Magneton", **MAGNETON)
        self.assertEqual((a.id, b.id), (1, 2))
        profile.remove_party_pokemon(a.id)
        c = profile.add_party_pokemon("Mamoswine", **MAMOSWINE)
        self.assertEqual(c.id, 3, "a removed id must never be reused")

    def test_creation_only_needs_a_name(self):
        """So a half-entered Pokemon can be saved and finished later; hard_errors gates use."""
        profile = Profile(name="Gold")
        pokemon = profile.add_party_pokemon("Work in progress")
        self.assertNotEqual(pokemon.hard_errors(), [])

    def test_blank_name_is_rejected(self):
        with self.assertRaises(ValueError):
            Profile(name="Gold").add_party_pokemon("   ")

    def test_party_pokemon_are_editable_unlike_metronome_users(self):
        """Stats change as a Pokemon levels, so unlike a metronome user it is mutable."""
        profile = Profile(name="Gold")
        pokemon = profile.add_party_pokemon("Magneton", **MAGNETON)
        profile.update_party_pokemon(pokemon.id, level=31)
        self.assertEqual(profile.get_party_pokemon(pokemon.id).level, 31)

    def test_update_rejects_unknown_fields_and_id_changes(self):
        profile = Profile(name="Gold")
        pokemon = profile.add_party_pokemon("Magneton", **MAGNETON)
        for field in ("nickname", "id"):
            with self.assertRaises(ValueError, msg=field):
                profile.update_party_pokemon(pokemon.id, **{field: 99})

    def test_operations_on_an_unknown_id_raise(self):
        profile = Profile(name="Gold")
        for op in (profile.update_party_pokemon, profile.remove_party_pokemon):
            with self.assertRaises(ValueError):
                op(99)

    def test_roundtrip_preserves_party_and_counter(self):
        profile = Profile(name="Gold")
        profile.add_party_pokemon("Smeargle", **SMEARGLE)
        profile.add_party_pokemon("Magneton", **MAGNETON)
        restored = Profile.from_dict(profile.to_dict())
        self.assertEqual([(p.id, p.name) for p in restored.party],
                         [(1, "Smeargle"), (2, "Magneton")])
        self.assertEqual(restored.next_party_pokemon_id, 3)

    def test_profiles_written_before_battle_compass_still_load(self):
        restored = Profile.from_dict({"name": "Legacy"})
        self.assertEqual(restored.party, [])
        self.assertEqual(restored.next_party_pokemon_id, 1)


class TestHuntTarget(unittest.TestCase):
    def test_a_configured_target_is_valid(self):
        target = HuntTarget(species="suicune", level=40, nature="Bold", ivs=dict(PERFECT_IVS))
        self.assertEqual(target.hard_errors(), [])

    def test_ivs_and_nature_are_required_because_the_damage_filter_needs_them(self):
        """An unknown Sp. Atk makes the incoming-damage filter unsound, not merely vague."""
        target = HuntTarget(species="suicune", level=40)
        joined = " ".join(target.hard_errors())
        self.assertIn("nature", joined)
        self.assertIn("IV", joined)

    def test_out_of_range_ivs_are_rejected(self):
        target = HuntTarget(species="suicune", level=40, nature="Bold",
                            ivs={**PERFECT_IVS, "spa": 32})
        self.assertTrue(any("out of range" in e for e in target.hard_errors()))

    def test_roundtrip(self):
        target = HuntTarget(species="suicune", level=40, nature="Bold", ivs=dict(PERFECT_IVS))
        self.assertEqual(HuntTarget.from_dict(target.to_dict()).to_dict(), target.to_dict())


class TestHunt(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(name="Gold")
        self.profile.add_party_pokemon("Magneton", **MAGNETON)
        self.profile.add_party_pokemon("Smeargle", **SMEARGLE)
        self.profile.add_party_pokemon("Mamoswine", **MAMOSWINE)

    def test_a_fully_configured_hunt_has_no_errors(self):
        hunt = _configured_hunt(self.profile)
        self.assertEqual(hunt.hard_errors(self.profile), [])

    def test_an_empty_hunt_reports_every_missing_piece(self):
        errors = " ".join(Hunt(name="New", profile_id=self.profile.id).hard_errors())
        for expected in ("species", "capture ball", "party pokemon", "key seed",
                         "initial time", "Vector ms"):
            self.assertIn(expected, errors)

    def test_seed_targeting_is_required_because_it_centres_the_candidate_window(self):
        hunt = _configured_hunt(self.profile)
        hunt.key_seed = None
        hunt.vector_ms = None
        joined = " ".join(hunt.hard_errors(self.profile))
        self.assertIn("key seed", joined)
        self.assertIn("Vector ms", joined)

    def test_a_party_pokemon_removed_from_the_profile_is_reported(self):
        hunt = _configured_hunt(self.profile)
        self.profile.remove_party_pokemon(2)
        self.assertTrue(any("no longer on the profile" in e
                            for e in hunt.hard_errors(self.profile)))

    def test_party_pokemon_errors_surface_with_the_pokemon_name(self):
        self.profile.update_party_pokemon(2, stats={})
        hunt = _configured_hunt(self.profile)
        self.assertTrue(any(e.startswith("Smeargle:") for e in hunt.hard_errors(self.profile)))

    def test_party_is_not_validated_without_a_profile(self):
        """The hunt document alone cannot resolve pokemon ids."""
        self.profile.update_party_pokemon(2, stats={})
        hunt = _configured_hunt(self.profile)
        self.assertEqual(hunt.hard_errors(), [])

    def test_held_items_belong_to_the_hunt_not_the_profile(self):
        hunt = _configured_hunt(self.profile)
        hunt.party[1].held_item = "Silk Scarf"
        restored = Hunt.from_dict(hunt.to_dict())
        self.assertEqual(restored.party[1].held_item, "Silk Scarf")
        self.assertFalse(hasattr(self.profile.get_party_pokemon(2), "held_item"))

    def test_carries_no_mid_battle_state(self):
        """A Hunt is configuration; the live encounter lives in Battle Compass (sec 15.4)."""
        keys = Hunt(name="x", profile_id="y").to_dict().keys()
        for absent in ("current_hp", "rng_offset", "candidates", "stat_stages", "turn"):
            self.assertNotIn(absent, keys)

    def test_roundtrip(self):
        hunt = _configured_hunt(self.profile)
        self.assertEqual(Hunt.from_dict(hunt.to_dict()).to_dict(), hunt.to_dict())


if __name__ == "__main__":
    unittest.main()


class TestCalibrationModelIsNotHuntConfiguration(unittest.TestCase):
    """Calibration models are profile-scoped, with one marked active, and every profile is
    seeded with a bundled "Standard" model active by default. So there is never a model for a
    hunt to pick -- an Expedition carries no such field either. An earlier version of Hunt did,
    which put an unreachable "pick one in Review Data" blocker on the configure screen.
    """

    def test_hunt_has_no_calibration_model_field(self):
        self.assertNotIn("calibration_model_id", Hunt(name="x", profile_id="y").to_dict())

    def test_a_missing_model_is_not_a_hard_error(self):
        profile = Profile(name="Gold")
        profile.add_party_pokemon("Smeargle", **SMEARGLE)
        hunt = _configured_hunt(profile)
        self.assertEqual(hunt.hard_errors(profile), [])

    def test_documents_written_with_the_old_field_still_load(self):
        hunt = Hunt.from_dict({"name": "legacy", "profile_id": "p",
                               "calibration_model_id": "model-1"})
        self.assertEqual(hunt.name, "legacy")
        self.assertNotIn("calibration_model_id", hunt.to_dict())

    def test_metronome_defaults_live_on_the_hunt_like_an_expedition(self):
        """So the shared calibration tools can run against a hunt without retyping."""
        hunt = Hunt(name="x", profile_id="y")
        self.assertEqual((hunt.last_target, hunt.last_metronome_defaults), ({}, {}))
        hunt.last_target = {"initial_time": "2026-09-29T12:00:00", "vector_ms": 382791}
        hunt.last_metronome_defaults = {"seconds_window": 2}
        restored = Hunt.from_dict(hunt.to_dict())
        self.assertEqual(restored.last_target["vector_ms"], 382791)
        self.assertEqual(restored.last_metronome_defaults["seconds_window"], 2)
