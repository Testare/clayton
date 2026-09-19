"""Tests for app.models (Profile, MetronomeUser, Expedition)."""
import unittest

from app.models import Expedition, MetronomeUser, Profile

# A metronome user that passes every P0 suitability check.
_GOOD_USER = dict(
    species="Chansey",
    ability="Natural Cure",
    moveset=["Metronome"],
    lagging_tail=True,
    gender="female",
    level=30,
)


class TestMetronomeUsers(unittest.TestCase):
    def test_ids_increment_from_one(self):
        p = Profile(name="Silver")
        a = p.add_metronome_user("Chansey A", **_GOOD_USER)
        b = p.add_metronome_user("Chansey B", **_GOOD_USER)
        self.assertEqual((a.id, b.id), (1, 2))
        self.assertEqual(p.next_metronome_user_id, 3)

    def test_ids_never_reused_after_removal(self):
        p = Profile(name="Silver")
        a = p.add_metronome_user("A", **_GOOD_USER)
        p.add_metronome_user("B", **_GOOD_USER)
        p.remove_metronome_user(a.id)
        c = p.add_metronome_user("C", **_GOOD_USER)
        self.assertEqual(c.id, 3)  # not 1 — the counter never rewinds

    def test_duplicate_names_are_allowed(self):
        # Names are display-only now -- the id (not the name) is the real unique key runs
        # reference, so a same-named second user is fine (the UI disambiguates for display
        # by appending "#<id>" only when a collision actually exists).
        p = Profile(name="Silver")
        a = p.add_metronome_user("Chansey", **_GOOD_USER)
        b = p.add_metronome_user("chansey", **_GOOD_USER)
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(len(p.metronome_users), 2)

    def test_hard_error_ability_is_still_creatable(self):
        # The user must always be able to create whatever metronome user they want -- a
        # hard_errors() issue (e.g. Serene Grace) blocks SELECTING this user in Metronome
        # Compass, not creating it (clayton-b42.10.2).
        p = Profile(name="Silver")
        u = p.add_metronome_user("Bad", **{**_GOOD_USER, "ability": "Serene Grace"})
        self.assertEqual(len(p.metronome_users), 1)
        self.assertTrue(u.hard_errors())
        self.assertFalse(u.is_suitable)

    def test_blank_name_rejected(self):
        p = Profile(name="Silver")
        with self.assertRaises(ValueError):
            p.add_metronome_user("   ", **_GOOD_USER)

    def test_remove_unknown_raises(self):
        p = Profile(name="Silver")
        with self.assertRaises(ValueError):
            p.remove_metronome_user(99)

    def test_no_edit_method_exposed(self):
        # Immutability is a design guarantee: there must be no update/edit affordance.
        self.assertFalse(hasattr(Profile, "update_metronome_user"))
        self.assertFalse(hasattr(Profile, "edit_metronome_user"))

    def test_suitability_warnings(self):
        good = MetronomeUser(id=1, name="ok", **_GOOD_USER)
        self.assertTrue(good.is_suitable)
        self.assertEqual(good.suitability_warnings(), [])

        # Not knowing Metronome and not holding a Lagging Tail are hard errors (round 9
        # feedback), not soft warnings -- only the off-species check is still advisory here.
        bad = MetronomeUser(id=2, name="bad", species="Ditto", moveset=[], lagging_tail=False)
        w = bad.suitability_warnings()
        self.assertFalse(bad.is_suitable)
        self.assertTrue(any("Chansey" in m for m in w))
        self.assertFalse(any("does not know Metronome" in m for m in w))
        self.assertFalse(any("Lagging Tail" in m for m in w))

    def test_hard_errors(self):
        clean = MetronomeUser(id=1, name="ok", **_GOOD_USER)
        self.assertEqual(clean.hard_errors(), [])

        for ability in ("Serene Grace", "Cute Charm", "Magic Guard"):
            blocked = MetronomeUser(id=2, name="bad", **{**_GOOD_USER, "ability": ability})
            errs = blocked.hard_errors()
            self.assertTrue(errs, ability)
            self.assertTrue(any(ability in e for e in errs))
            # A hard-error ability doesn't ALSO show up as a redundant soft warning...
            self.assertFalse(any("ability should be" in w for w in blocked.suitability_warnings()))
            # ...but it DOES count toward is_suitable (which governs Metronome Compass
            # selectability), even though suitability_warnings() itself is empty here.
            self.assertEqual(blocked.suitability_warnings(), [])
            self.assertFalse(blocked.is_suitable)

    def test_not_knowing_metronome_is_a_hard_error(self):
        u = MetronomeUser(id=1, name="no-metronome", **{**_GOOD_USER, "moveset": ["Tackle"]})
        errs = u.hard_errors()
        self.assertTrue(any("does not know Metronome" in e for e in errs))
        self.assertFalse(u.is_suitable)
        # Still fully creatable -- Profile.add_metronome_user never blocks on this.
        p = Profile(name="Silver")
        created = p.add_metronome_user("no-metronome", **{**_GOOD_USER, "moveset": ["Tackle"]})
        self.assertEqual(len(p.metronome_users), 1)
        self.assertTrue(created.hard_errors())

    def test_not_holding_lagging_tail_is_a_hard_error(self):
        u = MetronomeUser(id=1, name="no-tail", **{**_GOOD_USER, "lagging_tail": False})
        errs = u.hard_errors()
        self.assertTrue(any("Lagging Tail" in e for e in errs))
        self.assertFalse(u.is_suitable)

    def test_profile_has_valid_user(self):
        p = Profile(name="Silver")
        self.assertFalse(p.has_valid_metronome_user)
        p.add_metronome_user("bad", species="Ditto", moveset=[], lagging_tail=False)
        self.assertFalse(p.has_valid_metronome_user)
        p.add_metronome_user("good", **_GOOD_USER)
        self.assertTrue(p.has_valid_metronome_user)


class TestSerialization(unittest.TestCase):
    def test_profile_round_trip(self):
        p = Profile(name="Silver", trainer_name="Ash", version="SoulSilver", console="my DS Lite")
        p.add_metronome_user("Chansey A", **_GOOD_USER)
        p.add_metronome_user("Chansey B", **_GOOD_USER)
        p.remove_metronome_user(1)
        restored = Profile.from_dict(p.to_dict())
        self.assertEqual(restored.to_dict(), p.to_dict())
        # Counter and remaining user survive the round trip.
        self.assertEqual(restored.next_metronome_user_id, 3)
        self.assertEqual([u.id for u in restored.metronome_users], [2])

    def test_expedition_round_trip_and_defaults(self):
        e = Expedition(name="Metang hunt", profile_id="p1", pokemon="metang")
        self.assertEqual(e.preferences["elm_calls_after_flips"], 3)
        restored = Expedition.from_dict(e.to_dict())
        self.assertEqual(restored.to_dict(), e.to_dict())

    def test_expedition_preferences_merge_defaults(self):
        # An older doc missing a newer preference key still loads with the default.
        e = Expedition.from_dict({"name": "x", "profile_id": "p1", "preferences": {}})
        self.assertEqual(e.preferences["elm_calls_after_flips"], 3)


if __name__ == "__main__":
    unittest.main()
