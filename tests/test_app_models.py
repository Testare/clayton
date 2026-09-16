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

    def test_duplicate_name_rejected_case_insensitively(self):
        p = Profile(name="Silver")
        p.add_metronome_user("Chansey", **_GOOD_USER)
        with self.assertRaises(ValueError):
            p.add_metronome_user("chansey", **_GOOD_USER)

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

        bad = MetronomeUser(id=2, name="bad", species="Ditto", moveset=[], lagging_tail=False)
        w = bad.suitability_warnings()
        self.assertFalse(bad.is_suitable)
        self.assertTrue(any("Chansey" in m for m in w))
        self.assertTrue(any("Metronome" in m for m in w))
        self.assertTrue(any("Lagging Tail" in m for m in w))

    def test_profile_has_valid_user(self):
        p = Profile(name="Silver")
        self.assertFalse(p.has_valid_metronome_user)
        p.add_metronome_user("bad", species="Ditto", moveset=[], lagging_tail=False)
        self.assertFalse(p.has_valid_metronome_user)
        p.add_metronome_user("good", **_GOOD_USER)
        self.assertTrue(p.has_valid_metronome_user)


class TestSerialization(unittest.TestCase):
    def test_profile_round_trip(self):
        p = Profile(name="Silver", tid=1234, sid=5678, console="my DS Lite")
        p.add_metronome_user("Chansey A", **_GOOD_USER)
        p.add_metronome_user("Chansey B", **_GOOD_USER)
        p.remove_metronome_user(1)
        restored = Profile.from_dict(p.to_dict())
        self.assertEqual(restored.to_dict(), p.to_dict())
        # Counter and remaining user survive the round trip.
        self.assertEqual(restored.next_metronome_user_id, 3)
        self.assertEqual([u.id for u in restored.metronome_users], [2])

    def test_expedition_round_trip_and_defaults(self):
        e = Expedition(name="Metang hunt", profile_id="p1", pokemon="metang", chatots=2)
        self.assertEqual(e.preferences["elm_calls_after_flips"], 3)
        restored = Expedition.from_dict(e.to_dict())
        self.assertEqual(restored.to_dict(), e.to_dict())

    def test_expedition_preferences_merge_defaults(self):
        # An older doc missing a newer preference key still loads with the default.
        e = Expedition.from_dict({"name": "x", "profile_id": "p1", "preferences": {}})
        self.assertEqual(e.preferences["elm_calls_after_flips"], 3)


if __name__ == "__main__":
    unittest.main()
