"""Tests for app.facade.Facade over an in-temp FileStore."""
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore

_GOOD_USER = dict(
    species="Chansey", ability="Natural Cure", moveset=["Metronome"],
    lagging_tail=True, gender="female", level=30,
)


class TestFacade(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    # profiles -----------------------------------------------------------

    def test_create_and_list_profiles(self):
        self.assertEqual(self.api.list_profiles(), [])
        p = self.api.create_profile({"name": "Silver", "tid": 12345})
        listed = self.api.list_profiles()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "Silver")
        self.assertFalse(listed[0]["has_valid_metronome_user"])
        self.assertEqual(self.api.get_profile(p["id"])["tid"], 12345)

    def test_create_profile_requires_name(self):
        with self.assertRaises(ValueError):
            self.api.create_profile({"name": "   "})

    def test_profiles_persist_across_instances(self):
        p = self.api.create_profile({"name": "Silver"})
        fresh = Facade(FileStore(self._tmp.name))
        self.assertEqual([x["id"] for x in fresh.list_profiles()], [p["id"]])

    # metronome users ----------------------------------------------------

    def test_add_metronome_user_returns_warnings(self):
        p = self.api.create_profile({"name": "Silver"})
        res = self.api.add_metronome_user(p["id"], {"name": "Chansey A", **_GOOD_USER})
        self.assertEqual(res["warnings"], [])
        self.assertEqual(res["user_id"], 1)
        self.assertTrue(res["profile"]["has_valid_metronome_user"])

    def test_add_unsuitable_user_warns_but_saves(self):
        p = self.api.create_profile({"name": "Silver"})
        res = self.api.add_metronome_user(p["id"], {"name": "Ditto", "species": "Ditto"})
        self.assertTrue(res["warnings"])
        self.assertFalse(res["profile"]["has_valid_metronome_user"])
        # It's still stored (warnings, not a hard block).
        self.assertEqual(len(self.api.get_profile(p["id"])["metronome_users"]), 1)

    def test_duplicate_user_name_raises(self):
        p = self.api.create_profile({"name": "Silver"})
        self.api.add_metronome_user(p["id"], {"name": "Chansey", **_GOOD_USER})
        with self.assertRaises(ValueError):
            self.api.add_metronome_user(p["id"], {"name": "chansey", **_GOOD_USER})

    def test_remove_metronome_user(self):
        p = self.api.create_profile({"name": "Silver"})
        r = self.api.add_metronome_user(p["id"], {"name": "A", **_GOOD_USER})
        res = self.api.remove_metronome_user(p["id"], r["user_id"])
        self.assertEqual(res["removed"]["name"], "A")
        self.assertEqual(res["profile"]["metronome_users"], [])

    def test_get_profile_exposes_per_user_suitability(self):
        p = self.api.create_profile({"name": "Silver"})
        self.api.add_metronome_user(p["id"], {"name": "A", **_GOOD_USER})
        u = self.api.get_profile(p["id"])["metronome_users"][0]
        self.assertTrue(u["is_suitable"])
        self.assertEqual(u["warnings"], [])

    def test_prospective_warnings_helper(self):
        self.assertEqual(self.api.metronome_user_warnings({"name": "x", **_GOOD_USER}), [])
        self.assertTrue(self.api.metronome_user_warnings({"name": "x", "species": "Ditto"}))

    # expeditions --------------------------------------------------------

    def test_create_expedition_requires_existing_profile(self):
        with self.assertRaises(ValueError):
            self.api.create_expedition({"name": "hunt", "profile_id": "ghost"})

    def test_create_list_and_scope_expeditions(self):
        p1 = self.api.create_profile({"name": "P1"})
        p2 = self.api.create_profile({"name": "P2"})
        self.api.create_expedition({"name": "Metang", "profile_id": p1["id"], "pokemon": "metang"})
        self.api.create_expedition({"name": "Other", "profile_id": p2["id"]})
        self.assertEqual(len(self.api.list_expeditions()), 2)
        scoped = self.api.list_expeditions(profile_id=p1["id"])
        self.assertEqual([e["name"] for e in scoped], ["Metang"])

    def test_save_expedition_upserts(self):
        p = self.api.create_profile({"name": "P1"})
        e = self.api.create_expedition({"name": "Metang", "profile_id": p["id"]})
        e["chatots"] = 2
        e["last_target"] = {"initial_time": "2025-07-24T14:45:56", "vector_ms": 327919}
        saved = self.api.save_expedition(e)
        self.assertEqual(saved["chatots"], 2)
        self.assertEqual(self.api.get_expedition(e["id"])["last_target"]["vector_ms"], 327919)

    def test_save_expedition_requires_id(self):
        p = self.api.create_profile({"name": "P1"})
        with self.assertRaises(ValueError):
            self.api.save_expedition({"name": "x", "profile_id": p["id"]})

    def test_list_safari_areas(self):
        areas = self.api.list_safari_areas()
        self.assertIn("Peak", areas)
        self.assertGreaterEqual(len(areas), 12)


if __name__ == "__main__":
    unittest.main()
