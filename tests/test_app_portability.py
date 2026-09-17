"""Tests for export/import (expeditions, profile bundles, calibration models)."""
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
        self.chart = self.api.create_chart(self.eid, {
            "name": "Balls only", "strategy_name": "only-balls", "criteria_name": "capture"})
        self.target = self.api.save_target(self.eid, self.chart["id"], {
            "name": "Best pick", "initial_time": "2000-05-30T14:59:59", "vector_ms": 300000,
            "target_delay": 4500, "p": 0.42, "sigma": 3.1})

    def _empty_counts(self, **override):
        base = {"expeditions": 0, "charts": 0, "targets": 0, "runs": 0, "calibration_models": 0}
        base.update(override)
        return base

    # -- bundle: shape / exclusion -----------------------------------------

    def test_envelope_shape(self):
        env = self.api.export_profile_bundle(self.pid)
        self.assertTrue(env["clayton_export"])
        self.assertEqual(env["kind"], "profile_bundle")
        self.assertEqual(env["version"], 1)
        self.assertEqual(len(env["data"]["expeditions"]), 1)
        self.assertEqual(len(env["data"]["charts"]), 1)
        self.assertEqual(len(env["data"]["targets"]), 1)
        self.assertEqual(len(env["data"]["runs"]), 1)

    def test_standard_runs_not_exported(self):
        self.api.save_metronome_run(self.pid, {"tag": "Standard", "a_seed": {}, "b_seed": {}})
        env = self.api.export_profile_bundle(self.pid)
        self.assertTrue(all(r["tag"] != "Standard" for r in env["data"]["runs"]))

    def test_excluded_runs_dropped_when_asked(self):
        r2 = self.api.save_metronome_run(self.pid, {"tag": "bad", "a_seed": {}, "b_seed": {}})
        self.api.set_run_excluded(r2["id"], True)

        with_excluded = self.api.export_profile_bundle(self.pid, include_excluded=True)
        self.assertEqual(len(with_excluded["data"]["runs"]), 2)

        without_excluded = self.api.export_profile_bundle(self.pid, include_excluded=False)
        self.assertEqual(len(without_excluded["data"]["runs"]), 1)
        self.assertEqual(without_excluded["data"]["runs"][0]["tag"], "300s")

    # -- bundle: round trip into a fresh store (no collision) --------------

    def test_round_trip_into_fresh_store(self):
        env = self.api.export_profile_bundle(self.pid)
        fresh = Facade(FileStore(tempfile.mkdtemp()))
        res = fresh.import_profile_bundle(env)
        self.assertNotIn("collision", res)
        self.assertEqual(res["counts"], self._empty_counts(
            expeditions=1, charts=1, targets=1, runs=1,
            calibration_models=1))  # the seeded "Standard" model travels with the bundle too

        profiles = fresh.list_profiles()
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Silver")
        exps = fresh.list_expeditions(res["profile_id"])
        self.assertEqual([e["name"] for e in exps], ["Metang"])
        runs = fresh.list_runs(res["profile_id"])
        self.assertEqual(runs[0]["vector_ms"], 300000)
        # children are re-pointed at the NEW profile id...
        self.assertEqual(runs[0]["profile_id"], res["profile_id"])
        self.assertEqual(exps[0]["profile_id"], res["profile_id"])
        # ...and a target's chart_id is re-pointed at the NEW chart id, not the old one.
        targets = fresh.list_targets(exps[0]["id"])
        charts = fresh.list_charts(exps[0]["id"])
        self.assertEqual(targets[0]["chart_id"], charts[0]["id"])
        self.assertNotEqual(charts[0]["id"], self.chart["id"])

    # -- bundle: same-name collision ----------------------------------------

    def test_reimport_same_store_is_a_collision(self):
        env = self.api.export_profile_bundle(self.pid)
        res = self.api.import_profile_bundle(env)  # same store, same profile NAME
        self.assertTrue(res.get("collision"))
        self.assertEqual(res["existing_id"], self.pid)
        self.assertEqual(len(self.api.list_profiles()), 1)  # nothing imported yet

    def test_collision_resolved_new_makes_a_separate_copy(self):
        env = self.api.export_profile_bundle(self.pid)
        res = self.api.import_profile_bundle(env, on_collision="new")
        self.assertNotIn("collision", res)
        self.assertFalse(res["merged"])
        self.assertNotEqual(res["profile_id"], self.pid)
        self.assertEqual(len(self.api.list_profiles()), 2)

    def test_collision_resolved_merge_folds_into_existing_profile(self):
        env = self.api.export_profile_bundle(self.pid)
        res = self.api.import_profile_bundle(env, on_collision="merge")
        self.assertTrue(res["merged"])
        self.assertEqual(res["profile_id"], self.pid)          # folded into the SAME profile
        self.assertEqual(len(self.api.list_profiles()), 1)     # no new profile created

        exps = self.api.list_expeditions(self.pid)
        self.assertEqual(len(exps), 2)                          # original + merged-in copy
        runs = self.api.list_runs(self.pid)
        self.assertEqual(len(runs), 2)
        # The existing profile's own fields (its metronome user) are untouched.
        self.assertEqual(len(self.api.get_profile(self.pid)["metronome_users"]), 1)

    def test_merge_does_not_disturb_active_model_or_collide_numbers(self):
        # The shared setUp's run has no a_seed/b_seed "time" (not fittable) -- give this
        # test its own properly-fittable runs so preview_calibration has something to fit.
        # self.pid already has model #1 -- the seeded "Standard" model -- from create_profile.
        for i, (M, Fb) in enumerate([(180000, 11500), (220000, 13900), (260000, 16300),
                                     (300000, 18700), (340000, 21100), (380000, 23500)]):
            self.api.save_metronome_run(self.pid, {
                "tag": "session1", "vector_ms": M,
                "a_seed": {"time": "2025-07-24T14:45:56", "delay": 700},
                "b_seed": {"time": "2025-07-24T14:46:01", "delay": Fb}})
        report = self.api.preview_calibration(self.pid)
        active = self.api.save_calibration_model(self.pid, {"name": "v1", "preview": report})
        self.assertTrue(active["active"])
        self.assertEqual(len(self.api.list_calibration_models(self.pid)), 2)  # Standard + v1

        env = self.api.export_profile_bundle(self.pid)  # bundle includes both models
        res = self.api.import_profile_bundle(env, on_collision="merge")
        self.assertEqual(res["counts"]["calibration_models"], 2)

        models = self.api.list_calibration_models(self.pid)
        self.assertEqual(len(models), 4)                       # 2 original + 2 merged-in copies
        numbers = sorted(m["number"] for m in models)
        self.assertEqual(numbers, [1, 2, 3, 4])                 # no number collision
        active_models = [m for m in models if m["active"]]
        self.assertEqual([m["id"] for m in active_models], [active["id"]])  # still just the original

    def test_rejects_foreign_envelope(self):
        with self.assertRaises(ValueError):
            self.api.import_profile_bundle({"not": "a clayton export"})
        with self.assertRaises(ValueError):
            self.api.import_profile_bundle({"clayton_export": True, "version": 999,
                                            "kind": "profile_bundle", "data": {"profile": {}}})


class TestExpeditionPortability(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "Silver"})["id"]
        self.eid = self.api.create_expedition(
            {"name": "Metang", "profile_id": self.pid, "pokemon": "metang", "key_seed": 42})["id"]
        self.chart = self.api.create_chart(self.eid, {
            "name": "Balls only", "strategy_name": "only-balls", "criteria_name": "capture"})
        self.api.save_target(self.eid, self.chart["id"], {
            "name": "Best pick", "initial_time": "2000-05-30T14:59:59", "vector_ms": 300000,
            "target_delay": 4500, "p": 0.42, "sigma": 3.1})

    def test_export_shape(self):
        env = self.api.export_expedition(self.eid)
        self.assertEqual(env["kind"], "expedition")
        self.assertEqual(env["data"]["expedition"]["name"], "Metang")
        self.assertEqual(len(env["data"]["charts"]), 1)
        self.assertEqual(len(env["data"]["targets"]), 1)

    def test_import_into_a_different_profile_no_collision(self):
        env = self.api.export_expedition(self.eid)
        other = self.api.create_profile({"name": "Other"})["id"]
        res = self.api.import_expedition(other, env)
        self.assertNotIn("collision", res)
        self.assertEqual(res["counts"], {"charts": 1, "targets": 1})
        exps = self.api.list_expeditions(other)
        self.assertEqual([e["name"] for e in exps], ["Metang"])
        self.assertNotEqual(exps[0]["id"], self.eid)

    def test_reimport_same_profile_is_a_collision(self):
        env = self.api.export_expedition(self.eid)
        res = self.api.import_expedition(self.pid, env)
        self.assertTrue(res.get("collision"))
        self.assertEqual(res["existing_id"], self.eid)
        self.assertEqual(len(self.api.list_expeditions(self.pid)), 1)  # nothing imported yet

    def test_collision_copy_creates_a_second_expedition(self):
        env = self.api.export_expedition(self.eid)
        res = self.api.import_expedition(self.pid, env, on_collision="copy")
        self.assertNotIn("collision", res)
        self.assertNotEqual(res["expedition_id"], self.eid)
        self.assertEqual(len(self.api.list_expeditions(self.pid)), 2)

    def test_collision_replace_overwrites_in_place(self):
        env = self.api.export_expedition(self.eid)
        res = self.api.import_expedition(self.pid, env, on_collision="replace")
        self.assertEqual(res["expedition_id"], self.eid)   # SAME id, not a copy
        self.assertEqual(len(self.api.list_expeditions(self.pid)), 1)


class TestCalibrationModelPortability(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "Silver"})["id"]
        for i, (M, Fb) in enumerate([(180000, 11500), (220000, 13900), (260000, 16300),
                                     (300000, 18700), (340000, 21100), (380000, 23500)]):
            self.api.save_metronome_run(self.pid, {
                "tag": "session1", "vector_ms": M,
                "a_seed": {"time": "2025-07-24T14:45:56", "delay": 700},
                "b_seed": {"time": "2025-07-24T14:46:01", "delay": Fb}})
        report = self.api.preview_calibration(self.pid)
        self.model = self.api.save_calibration_model(self.pid, {"name": "v1", "preview": report})

    def test_export_shape(self):
        env = self.api.export_calibration_model(self.model["id"])
        self.assertEqual(env["kind"], "calibration_model")
        self.assertEqual(env["data"]["model"]["name"], "v1")

    def test_import_into_another_profile_gets_a_fresh_inactive_numbered_entry(self):
        # `other` already has its own seeded "Standard" model (#1, active) — see
        # Facade._seed_standard_calibration_model — so the import numbers past it.
        env = self.api.export_calibration_model(self.model["id"])
        other = self.api.create_profile({"name": "Other"})["id"]
        res = self.api.import_calibration_model(other, env)
        self.assertEqual(res["number"], 2)
        imported = self.api.list_calibration_models(other)
        self.assertEqual(len(imported), 2)
        by_id = {m["id"]: m for m in imported}
        self.assertFalse(by_id[res["model_id"]]["active"])
        self.assertNotEqual(res["model_id"], self.model["id"])

    def test_import_numbers_past_existing_models(self):
        # self.pid already has Standard (#1, seeded) + v1 (#2, from setUp) — the import
        # numbers past both.
        env = self.api.export_calibration_model(self.model["id"])
        res = self.api.import_calibration_model(self.pid, env)  # same profile it came from
        self.assertEqual(res["number"], 3)
        self.assertEqual(len(self.api.list_calibration_models(self.pid)), 3)


if __name__ == "__main__":
    unittest.main()
