"""Tests for app.facade.Facade over an in-temp FileStore."""
import inspect
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore

_GOOD_USER = dict(
    species="Chansey", ability="Natural Cure", moveset=["Metronome"],
    lagging_tail=True, gender="female", level=30,
)


class TestFacadePywebviewBridgeCompat(unittest.TestCase):
    """pywebview's js_api bridge only exposes attributes where inspect.ismethod()
    is True (webview/util.py get_functions). A @staticmethod, accessed through an
    instance, is a plain function -- ismethod() is False -- so pywebview silently
    DROPS it from window.pywebview.api with no error on the Python side; the JS
    call then fails with "... is not a function". Guard against reintroducing this:
    every public Facade attribute must be a real bound instance method.
    """

    def test_all_public_attrs_are_bound_instance_methods(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        offenders = [
            name for name in dir(api)
            if not name.startswith("_") and not inspect.ismethod(getattr(api, name))
        ]
        self.assertEqual(offenders, [],
            f"these Facade attributes won't reach window.pywebview.api "
            f"(likely @staticmethod -- use a plain instance method instead): {offenders}")


class TestFacade(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    # profiles -----------------------------------------------------------

    def test_create_and_list_profiles(self):
        self.assertEqual(self.api.list_profiles(), [])
        p = self.api.create_profile({"name": "Silver", "trainer_name": "Ash", "version": "SoulSilver"})
        listed = self.api.list_profiles()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "Silver")
        self.assertFalse(listed[0]["has_valid_metronome_user"])
        self.assertEqual(self.api.get_profile(p["id"])["trainer_name"], "Ash")
        self.assertEqual(self.api.get_profile(p["id"])["version"], "SoulSilver")

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

    def test_duplicate_user_name_is_allowed(self):
        p = self.api.create_profile({"name": "Silver"})
        a = self.api.add_metronome_user(p["id"], {"name": "Chansey", **_GOOD_USER})
        b = self.api.add_metronome_user(p["id"], {"name": "chansey", **_GOOD_USER})
        self.assertNotEqual(a["user_id"], b["user_id"])

    def test_hard_error_ability_is_still_creatable_but_flagged(self):
        # The user must always be able to create whatever metronome user they want -- a
        # hard_errors() issue blocks SELECTING this user in Metronome Compass, not
        # creating it (clayton-b42.10.2).
        p = self.api.create_profile({"name": "Silver"})
        res = self.api.add_metronome_user(p["id"], {
            "name": "Bad", **{**_GOOD_USER, "ability": "Cute Charm"}})
        self.assertTrue(res["hard_errors"])
        saved = self.api.get_profile(p["id"])["metronome_users"]
        self.assertEqual(len(saved), 1)
        self.assertTrue(saved[0]["hard_errors"])
        self.assertFalse(saved[0]["is_suitable"])

    def test_prospective_hard_errors_helper(self):
        self.assertEqual(self.api.metronome_user_hard_errors({"name": "x", **_GOOD_USER}), [])
        errs = self.api.metronome_user_hard_errors(
            {"name": "x", **{**_GOOD_USER, "ability": "Magic Guard"}})
        self.assertTrue(errs)
        self.assertTrue(any("Magic Guard" in e for e in errs))

    def test_list_metronome_species(self):
        species = self.api.list_metronome_species()
        self.assertEqual(len(species), 14)
        by_name = {s["name"]: s for s in species}
        self.assertIn("Chansey", by_name)
        chansey = by_name["Chansey"]
        self.assertIn("Metronome", chansey["moves"])
        self.assertEqual(chansey["gender"], "female_only")
        self.assertIn("Serene Grace", chansey["blocking_abilities"])
        self.assertNotIn("Natural Cure", chansey["blocking_abilities"])
        granbull = by_name["Granbull"]
        self.assertEqual(granbull["blocking_abilities"], [])

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
        e["last_target"] = {"initial_time": "2025-07-24T14:45:56", "vector_ms": 327919}
        saved = self.api.save_expedition(e)
        self.assertEqual(self.api.get_expedition(e["id"])["last_target"]["vector_ms"], 327919)

    def test_save_expedition_requires_id(self):
        p = self.api.create_profile({"name": "P1"})
        with self.assertRaises(ValueError):
            self.api.save_expedition({"name": "x", "profile_id": p["id"]})

    def test_list_safari_areas(self):
        areas = self.api.list_safari_areas()
        self.assertIn("Peak", areas)
        self.assertGreaterEqual(len(areas), 12)

    def test_delete_expedition_cascades_its_charts_and_targets(self):
        # Round 12 feedback: a Delete button needs an accurate "what will be deleted"
        # summary, which only makes sense if delete actually cascades rather than leaving
        # orphaned charts/targets pointing at a gone expedition_id.
        p = self.api.create_profile({"name": "P1"})
        e = self.api.create_expedition({"name": "Metang", "profile_id": p["id"]})
        c = self.api.create_chart(e["id"], {"name": "Balls", "strategy_name": "only-balls",
                                            "criteria_name": "capture"})
        self.api.save_target(e["id"], c["id"], {"name": "T1", "initial_time": "2025-07-24T14:45:56", "vector_ms": 300000, "target_delay": 100, "p": 0.5, "sigma": 10.0})

        summary = self.api.expedition_delete_summary(e["id"])
        self.assertEqual(summary, {"charts": 1, "targets": 1})

        self.assertTrue(self.api.delete_expedition(e["id"]))
        self.assertEqual(self.api.list_charts(e["id"]), [])
        self.assertEqual(self.api.list_targets(e["id"]), [])
        self.assertIsNone(self.api._store.read("expeditions", e["id"]))

    def test_delete_profile_refuses_while_expeditions_exist(self):
        # Round 13 feedback: deleting a profile must NOT delete its expeditions -- the
        # earlier (round 12) behavior cascaded them away, which turned out to be the wrong
        # call. delete_profile now refuses outright while any exist, rather than silently
        # orphaning them (their profile_id would point at nothing) or silently skipping them
        # (which would contradict "delete everything the profile owns").
        p = self.api.create_profile({"name": "P1"})
        e = self.api.create_expedition({"name": "Metang", "profile_id": p["id"]})

        summary = self.api.profile_delete_summary(p["id"])
        self.assertEqual(summary["expeditions"], 1)
        self.assertEqual(summary["expedition_names"], ["Metang"])

        with self.assertRaises(ValueError):
            self.api.delete_profile(p["id"])
        # Nothing was touched.
        self.assertIsNotNone(self.api._store.read("profiles", p["id"]))
        self.assertIsNotNone(self.api._store.read("expeditions", e["id"]))

    def test_delete_profile_cascades_runs_and_models_once_expeditions_are_gone(self):
        p = self.api.create_profile({"name": "P1"})
        e = self.api.create_expedition({"name": "Metang", "profile_id": p["id"]})
        self.api.save_metronome_run(p["id"], {"tag": "t", "vector_ms": 300000,
                                              "a_seed": {"seed": 1}, "b_seed": {"seed": 2}})
        self.api.add_metronome_user(p["id"], {"name": "Chansey", **_GOOD_USER})
        self.assertTrue(self.api.delete_expedition(e["id"]))  # delete it individually first

        summary = self.api.profile_delete_summary(p["id"])
        self.assertEqual(summary["expeditions"], 0)
        self.assertEqual(summary["runs"], 1)
        self.assertGreaterEqual(summary["calibration_models"], 1)  # Standard, auto-created
        self.assertEqual(summary["metronome_users"], 1)

        self.assertTrue(self.api.delete_profile(p["id"]))
        self.assertEqual(self.api.list_runs(p["id"], "metronome"), [])
        self.assertEqual(self.api.list_calibration_models(p["id"]), [])
        self.assertIsNone(self.api._store.read("profiles", p["id"]))

    def test_list_safari_areas_for_pokemon(self):
        self.assertEqual(self.api.list_safari_areas_for_pokemon("metang"), ["Mountain"])

    def test_safari_block_requirement(self):
        self.assertEqual(self.api.safari_block_requirement("Mountain", "metang"),
                         {"block_type": "peak", "quantity": 56})
        self.assertIsNone(self.api.safari_block_requirement("Plains", "metang"))


if __name__ == "__main__":
    unittest.main()
