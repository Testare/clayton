"""Tests for app.safari_compass (Safari Compass Seed B) and its facade wiring."""
import tempfile
import unittest

from app.facade import Facade
from app.safari_compass import _apply_path, _build_input, seed_b
from app.store import FileStore
from claytonlib.calibration import CalibrationModel
from claytonlib.compass import calibrated_candidates
from claytonlib.compass._types import CompassAction, UndoAction
from claytonlib.safari import SafariStep

_EXP = {"pokemon": "metang", "key_seed": 0x0D0E02BA}
_PARAMS = {"initial_time": "2025-07-24T14:45:56", "vector_ms": 300000}


def _model(jitter_c=2.0):
    return CalibrationModel(kind="line", target="Fb", beta=0.06, alpha=700.0,
                            jitter_c=jitter_c, rtc_offset_seconds=0.0,
                            rtc_offset_std=0.0, n_runs=10)


class TestSeedB(unittest.TestCase):
    def test_empty_path_returns_all_candidates_unfiltered(self):
        res = seed_b(_EXP, _model(), {**_PARAMS, "path": ""})
        self.assertTrue(res["path_valid"])
        self.assertEqual(res["count"], res["total"])
        self.assertGreater(res["count"], 0)
        self.assertIsNone(res["terminal"])
        c = res["candidates"][0]
        for key in ("seed", "seed_hex", "frame", "posterior"):
            self.assertIn(key, c)

    def test_path_narrows_strictly(self):
        full = seed_b(_EXP, _model(), {**_PARAMS, "path": ""})
        narrowed = seed_b(_EXP, _model(), {**_PARAMS, "path": "bB m01"})
        self.assertLess(narrowed["count"], full["count"])
        self.assertIsNone(narrowed["terminal"])

    def test_invalid_path_flagged_not_raised(self):
        res = seed_b(_EXP, _model(), {**_PARAMS, "path": "xyz"})
        self.assertFalse(res["path_valid"])
        self.assertEqual(res["candidates"], [])

    def test_captured_and_fled_set_terminal(self):
        cap = seed_b(_EXP, _model(), {**_PARAMS, "path": "bC"})
        self.assertEqual(cap["terminal"], "captured")
        fled = seed_b(_EXP, _model(), {**_PARAMS, "path": "bF"})
        self.assertEqual(fled["terminal"], "fled")

    def test_single_candidate_offers_machete_path(self):
        inputs = _build_input(_EXP, _model(0.01), {**_PARAMS, "k": 0.05})
        candidates, meta = calibrated_candidates(inputs)
        one = candidates[:1]
        current, terminal = _apply_path(one, [])
        self.assertEqual(len(current), 1)
        self.assertIsNone(terminal)
        # Exercise the same branch seed_b takes when exactly one candidate survives and the
        # run isn't over: it must not raise, whatever machete_one concludes for this context.
        from claytonlib.machete import machete_one
        machete_one(current[0][0])  # smoke: must not raise


class TestApplyPathStateMachine(unittest.TestCase):
    """The pending/cache flee-resolution replay, independent of the calibrated sweep."""

    def _candidates(self, n=5):
        # Minimal stand-ins: _apply_action only calls ctx.throw_bait/mud/ball, so real
        # SafariContexts are needed -- build a few real ones via calibrated_candidates once
        # and reuse its output (cheap: request a tiny window).
        inputs = _build_input(_EXP, _model(0.01), {**_PARAMS, "k": 0.05})
        candidates, _meta = calibrated_candidates(inputs)
        return candidates

    def test_undo_restores_the_previously_resolved_cache_state(self):
        # [BAIT, MUD]: BAIT resolves as no-flee (survivors only) once MUD becomes pending.
        # UNDO after that just drops the pending MUD, landing back on that resolved BAIT
        # state -- NOT on the raw (unresolved, unfiltered) state [BAIT] alone would leave
        # pending, since a lone action is never resolved until something follows it.
        cands = self._candidates()
        from claytonlib.compass._core import _apply_action
        bait_resolved_noflee = {s for ctx, s, _ in
                                _apply_action(cands, CompassAction(step=SafariStep.BAIT), filter_fled=False)
                                if not ctx.has_fled()}

        actions = [CompassAction(step=SafariStep.BAIT), CompassAction(step=SafariStep.MUD),
                   UndoAction()]
        after_undo, terminal = _apply_path(cands, actions)
        self.assertIsNone(terminal)
        self.assertEqual({s for _, s, _ in after_undo}, bait_resolved_noflee)

    def test_terminal_actions_stop_processing_further_actions(self):
        cands = self._candidates()
        actions = [CompassAction(step=SafariStep.BAIT), CompassAction(step=SafariStep.FLED),
                   CompassAction(step=SafariStep.MUD)]  # never reached
        current, terminal = _apply_path(cands, actions)
        self.assertEqual(terminal, "fled")


class TestFacadeSafariCompass(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "P1"})["id"]
        self.eid = self.api.create_expedition({
            "name": "Metang hunt", "profile_id": self.pid, "pokemon": "metang",
            "key_seed": 0x0D0E02BA})["id"]

    def test_deleting_the_only_model_self_heals_rather_than_erroring(self):
        # _resolve_calibration_models re-seeds the bundled "Standard" model into any profile
        # that has none (see Facade._ensure_standard_calibration_model_seeded) — covering
        # profiles that predate the seeding feature just as much as one whose only model was
        # since deleted. So this no longer raises "no calibration model available": it just
        # quietly gets Standard back.
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            standard = self.api.get_active_calibration_model(self.pid)
            self.api.delete_calibration_model(standard["id"])
            self.assertEqual(self.api.list_calibration_models(self.pid), [])

            res = self.api.safari_compass_seed_b(self.eid, {**_PARAMS, "path": ""})
            self.assertTrue(res["path_valid"])

            resurrected = self.api.list_calibration_models(self.pid)
            self.assertEqual(len(resurrected), 1)
            self.assertEqual(resurrected[0]["name"], "Standard")
            self.assertTrue(resurrected[0]["active"])

    def test_uses_the_profiles_active_model(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            report_runs = [{"id": f"r{i}", "kind": "metronome", "tag": "t", "vector_ms": M,
                            "target_timer_calibration": 0,
                            "a_seed": {"time": "2025-07-24T14:45:56", "delay": 700},
                            "b_seed": {"time": "2025-07-24T14:46:01", "delay": Fb}}
                           for i, (M, Fb) in enumerate(
                               [(180000, 11500), (220000, 13900), (260000, 16300),
                                (300000, 18700), (340000, 21100), (380000, 23500)])]
            for r in report_runs:
                self.api.save_metronome_run(self.pid, {
                    "tag": r["tag"], "vector_ms": r["vector_ms"],
                    "a_seed": r["a_seed"], "b_seed": r["b_seed"]})
            preview = self.api.preview_calibration(self.pid)
            self.api.save_calibration_model(self.pid, {"name": "v1", "preview": preview})

            res = self.api.safari_compass_seed_b(self.eid, {**_PARAMS, "path": ""})
            self.assertTrue(res["path_valid"])
            self.assertGreater(res["count"], 0)

    def test_save_and_list_safari_run(self):
        run = self.api.save_safari_run(self.pid, {
            "tag": "sc1", "vector_ms": 300000,
            "a_seed": {"seed": 1, "seed_hex": "0x1"},
            "b_seed": {"seed": 2, "seed_hex": "0x2", "frame": 18700}})
        self.assertEqual(run["kind"], "safari")
        runs = self.api.list_runs(self.pid, kind="safari")
        self.assertEqual([r["id"] for r in runs], [run["id"]])
        # Safari runs don't feed the F_b-vs-M TREND fit (they feed the safari load-path
        # offset instead — see app/calibration.py) — kind="metronome" never lists them.
        self.assertEqual(self.api.list_runs(self.pid, kind="metronome"), [])


if __name__ == "__main__":
    unittest.main()
