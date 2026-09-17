"""Tests for export/import (profile bundles)."""
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore

_GOOD_USER = dict(species="Chansey", ability="Natural Cure", moveset=["Metronome"],
                  lagging_tail=True, gender="female", level=30)


class TestPortability(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "Silver", "tid": 12345})["id"]
        self.api.add_metronome_user(self.pid, {"name": "Chansey 1", **_GOOD_USER})
        self.eid = self.api.create_expedition(
            {"name": "Metang", "profile_id": self.pid, "pokemon": "metang", "key_seed": 42})["id"]
        self.api.save_metronome_run(self.pid, {
            "tag": "300s", "vector_ms": 300000, "metronome_user_id": 1,
            "a_seed": {"seed": 1, "seed_hex": "0x1"}, "b_seed": {"seed": 2}})

    def test_envelope_shape(self):
        env = self.api.export_profile_bundle(self.pid)
        self.assertTrue(env["clayton_export"])
        self.assertEqual(env["kind"], "profile_bundle")
        self.assertEqual(env["version"], 1)
        self.assertEqual(len(env["data"]["expeditions"]), 1)
        self.assertEqual(len(env["data"]["runs"]), 1)

    def test_standard_runs_not_exported(self):
        self.api.save_metronome_run(self.pid, {"tag": "Standard", "a_seed": {}, "b_seed": {}})
        env = self.api.export_profile_bundle(self.pid)
        self.assertTrue(all(r["tag"] != "Standard" for r in env["data"]["runs"]))

    def test_round_trip_into_fresh_store(self):
        env = self.api.export_profile_bundle(self.pid)
        fresh = Facade(FileStore(tempfile.mkdtemp()))
        res = fresh.import_profile_bundle(env)
        self.assertEqual(res["counts"], {"expeditions": 1, "runs": 1})
        # The imported copy reproduces the content...
        profiles = fresh.list_profiles()
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Silver")
        exps = fresh.list_expeditions(res["profile_id"])
        self.assertEqual([e["name"] for e in exps], ["Metang"])
        runs = fresh.list_runs(res["profile_id"])
        self.assertEqual(runs[0]["vector_ms"], 300000)
        # ...and children are re-pointed at the NEW profile id.
        self.assertEqual(runs[0]["profile_id"], res["profile_id"])
        self.assertEqual(exps[0]["profile_id"], res["profile_id"])

    def test_import_is_a_copy_not_a_collision(self):
        env = self.api.export_profile_bundle(self.pid)
        res = self.api.import_profile_bundle(env)  # import back into the SAME store
        self.assertNotEqual(res["profile_id"], self.pid)  # fresh id, no overwrite
        self.assertEqual(len(self.api.list_profiles()), 2)

    def test_rejects_foreign_envelope(self):
        with self.assertRaises(ValueError):
            self.api.import_profile_bundle({"not": "a clayton export"})
        with self.assertRaises(ValueError):
            self.api.import_profile_bundle({"clayton_export": True, "version": 999,
                                            "kind": "profile_bundle", "data": {"profile": {}}})

    def test_export_single_expedition(self):
        env = self.api.export_expedition(self.eid)
        self.assertEqual(env["kind"], "expedition")
        self.assertEqual(env["data"]["expedition"]["name"], "Metang")


if __name__ == "__main__":
    unittest.main()
