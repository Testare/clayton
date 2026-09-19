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

    def _force_single_candidate(self, mock_apply_path):
        # seed_b only reaches the machete_one branch when exactly one candidate survives and
        # the run isn't over -- force that deterministically rather than relying on k/jitter
        # tuning to happen to narrow the real calibrated set down to one.
        inputs = _build_input(_EXP, _model(0.01), {**_PARAMS})
        candidates, _meta = calibrated_candidates(inputs)
        ctx, seed, frame = candidates[0]
        mock_apply_path.return_value = ([(ctx, seed, frame)], None)

    def test_machete_max_turns_is_threaded_through_from_params(self):
        # clayton-b42.7.11: the Preferences "Safari Compass Machete depth" setting must reach
        # machete_one's max_turns, not silently use its own default regardless of the param.
        from unittest.mock import patch
        with patch("app.safari_compass._apply_path") as mock_apply, \
             patch("claytonlib.machete.machete_one", return_value=None) as mocked:
            self._force_single_candidate(mock_apply)
            seed_b(_EXP, _model(0.01), {**_PARAMS, "machete_max_turns": 7})
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.kwargs.get("max_turns"), 7)

    def test_machete_max_turns_defaults_to_50_when_absent(self):
        from unittest.mock import patch
        with patch("app.safari_compass._apply_path") as mock_apply, \
             patch("claytonlib.machete.machete_one", return_value=None) as mocked:
            self._force_single_candidate(mock_apply)
            seed_b(_EXP, _model(0.01), {**_PARAMS})
            mocked.assert_called_once()
            self.assertEqual(mocked.call_args.kwargs.get("max_turns"), 50)

    def test_flee_flags_present_when_five_or_fewer_candidates_remain(self):
        # clayton-b42.10.8: force exactly 5 surviving candidates (deterministically, rather
        # than relying on k/jitter tuning) and confirm every row carries its own
        # (possibly-empty) flee_flags list.
        from unittest.mock import patch
        with patch("app.safari_compass._apply_path") as mock_apply:
            inputs = _build_input(_EXP, _model(0.01), {**_PARAMS})
            candidates, _meta = calibrated_candidates(inputs)
            five = candidates[:5]
            mock_apply.return_value = (five, None)
            res = seed_b(_EXP, _model(0.01), {**_PARAMS})
        self.assertEqual(len(res["candidates"]), 5)
        for row in res["candidates"]:
            self.assertIn("flee_flags", row)
            self.assertIsInstance(row["flee_flags"], list)
            for flag in row["flee_flags"]:
                self.assertIn("code", flag); self.assertIn("tooltip", flag)

    def test_flee_flags_absent_when_more_than_five_candidates_remain(self):
        from unittest.mock import patch
        with patch("app.safari_compass._apply_path") as mock_apply:
            inputs = _build_input(_EXP, _model(0.01), {**_PARAMS})
            candidates, _meta = calibrated_candidates(inputs)
            six = candidates[:6]
            mock_apply.return_value = (six, None)
            res = seed_b(_EXP, _model(0.01), {**_PARAMS, "limit": 6})
        self.assertEqual(len(res["candidates"]), 6)
        for row in res["candidates"]:
            self.assertNotIn("flee_flags", row)

    def test_flee_flags_absent_on_a_terminal_result(self):
        cap = seed_b(_EXP, _model(), {**_PARAMS, "path": "bC"})
        self.assertEqual(cap["terminal"], "captured")
        for row in cap["candidates"]:
            self.assertNotIn("flee_flags", row)


class TestWidenSearchWindow(unittest.TestCase):
    """clayton-b42.9.2: raising k alone barely changes the candidate set, because mass_cap
    (default 0.999) is already the binding constraint well before k=3.5 -- a k=3.5sigma
    window already covers ~99.95% of the Gaussian's mass. expand_frames/expand_seconds
    (the actual "widen search window" fix) must drop mass_cap to have a real effect."""

    def test_raising_k_alone_barely_moves_the_candidate_count(self):
        base = seed_b(_EXP, _model(), {**_PARAMS, "path": ""})
        bumped = seed_b(_EXP, _model(), {**_PARAMS, "path": "", "k": 3.5 + 1.5})
        # Not literally zero movement (the tail beyond the OLD k=3.5 is now inside the sweep,
        # but mass_cap still trims it down) -- the point is it's nowhere near proportional to
        # how much wider the raw k window became.
        self.assertLess(bumped["total"], base["total"] * 1.2)

    def test_expand_frames_and_seconds_meaningfully_grows_the_candidate_set(self):
        base = seed_b(_EXP, _model(), {**_PARAMS, "path": ""})
        widened = seed_b(_EXP, _model(), {
            **_PARAMS, "path": "", "expand_frames": 200, "expand_seconds": 2})
        self.assertGreater(widened["total"], base["total"] * 2)

    def test_expand_window_drops_mass_cap_and_grows_k_and_seconds(self):
        from app.safari_compass import expand_window
        inputs = _build_input(_EXP, _model(), {**_PARAMS})
        self.assertEqual(inputs.options.mass_cap, 0.999)
        sigma = inputs.sigma
        cur_maxoff = max(abs(d) for d in inputs.second_offsets)

        widened = expand_window(inputs, add_frames=100, add_seconds=3)
        self.assertIsNone(widened.options.mass_cap)
        self.assertAlmostEqual(widened.k, inputs.k + 100 / sigma)
        self.assertEqual(max(abs(d) for d in widened.second_offsets), cur_maxoff + 3)
        # Original input is untouched.
        self.assertEqual(inputs.options.mass_cap, 0.999)

    def test_expand_window_with_zero_frames_and_seconds_still_drops_mass_cap(self):
        # A no-op expand amount shouldn't change k/second_offsets, but mass_cap dropping is
        # the whole point of calling this at all -- zero args still needs to do that much.
        from app.safari_compass import expand_window
        inputs = _build_input(_EXP, _model(), {**_PARAMS})
        widened = expand_window(inputs, add_frames=0, add_seconds=0)
        self.assertIsNone(widened.options.mass_cap)
        self.assertEqual(widened.k, inputs.k)
        self.assertEqual(widened.second_offsets, inputs.second_offsets)


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

    def test_save_safari_run_carries_the_frame_guide(self):
        run = self.api.save_safari_run(self.pid, {
            "tag": "sc1", "vector_ms": 300000,
            "a_seed": {"seed": 1, "seed_hex": "0x1"},
            "b_seed": {"seed": 2, "seed_hex": "0x2", "frame": 18700},
            "elm_calls": 3, "chatot_flips": 34.5, "advance_frame": 81,
            "frame_guide": "On advance frame 9; want an encounter on frame 81..."})
        self.assertEqual(run["chatot_flips"], 34.5)
        self.assertIn("advance frame 9", run["frame_guide"])


class TestFacadeFrameIdentificationAndPlanning(unittest.TestCase):
    """clayton-b42.5.11: Seed A's own advance frame (via Elm calls) + a chatot-flip/Elm-call
    route to a chosen target encounter frame."""

    _SEED = 0x0D0E02BA

    def test_identify_frame_ambiguous_then_pinned(self):
        # Lookahead matches app.metronome._ELM_DISPLAY (15) — a short, near-term window, per
        # notebook convention (clayton-b42.6.10) — so the true frame must fall within it.
        api = Facade(FileStore(tempfile.mkdtemp()))
        first = api.safari_compass_identify_frame({"seed": self._SEED, "observed_elm": ""})
        self.assertFalse(first["pinned"])
        self.assertGreater(len(first["frames"]), 1)

        from claytonlib.safari_advance import advance_context
        rng_calls, elm = advance_context(self._SEED, {}, count=15)
        true_frame = rng_calls + 12
        heard = elm[max(0, true_frame - rng_calls - 8):true_frame - rng_calls]
        pinned = api.safari_compass_identify_frame({"seed": self._SEED, "observed_elm": heard})
        self.assertTrue(pinned["pinned"])
        self.assertEqual(pinned["frame"], true_frame)

    def test_identify_frame_accepts_hex_string_seed(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        by_int = api.safari_compass_identify_frame({"seed": self._SEED, "observed_elm": ""})
        by_hex = api.safari_compass_identify_frame({
            "seed": f"0x{self._SEED:08X}", "observed_elm": ""})
        self.assertEqual(by_int["frames"], by_hex["frames"])

    def test_plan_frame_route(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        plan = api.safari_compass_plan_frame({
            "seed": self._SEED, "current_frame": 9, "encounter_frame": 81})
        self.assertEqual(plan["encounter_frame"], 81)
        self.assertEqual(plan["chatot_flips"], 34.5)
        self.assertIn("[", plan["guide"])
        self.assertIn("Guide:", plan["description"])

    def test_plan_frame_route_overshoot_raises(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            api.safari_compass_plan_frame({
                "seed": self._SEED, "current_frame": 90, "encounter_frame": 81})

    def test_find_target_frame_in_house(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        res = api.safari_compass_find_target_frame({
            "seed": self._SEED, "current_frame": 0, "area": "Mountain", "tod": "morning",
            "block_config": {"peak": 56}, "pokemon": "metang"})
        self.assertIn("frame", res)
        self.assertFalse(res["all_ambiguous"])

    def test_find_target_frame_accepts_aim_advance_as_string_or_int(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        by_str = api.safari_compass_find_target_frame({
            "seed": self._SEED, "current_frame": 0, "area": "Mountain", "tod": "morning",
            "block_config": {"peak": 56}, "pokemon": "metang", "aim_advance": "100"})
        by_int = api.safari_compass_find_target_frame({
            "seed": self._SEED, "current_frame": 0, "area": "Mountain", "tod": "morning",
            "block_config": {"peak": 56}, "pokemon": "metang", "aim_advance": 100})
        self.assertEqual(by_str["frame"], by_int["frame"])

    def test_find_target_frame_raises_for_impossible_species(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            api.safari_compass_find_target_frame({
                "seed": self._SEED, "current_frame": 0, "area": "Mountain", "tod": "morning",
                "block_config": {}, "pokemon": "not-a-real-species"})

    def test_find_target_frame_raises_a_specific_error_when_block_requirement_unmet(self):
        # clayton-b42.10.3: an insufficient block score should error with a specific,
        # actionable message (what's needed vs what's configured) rather than the generic
        # "no frame in range" the underlying search would otherwise raise.
        api = Facade(FileStore(tempfile.mkdtemp()))
        with self.assertRaises(ValueError) as ctx:
            api.safari_compass_find_target_frame({
                "seed": self._SEED, "current_frame": 0, "area": "Mountain", "tod": "morning",
                "block_config": {"peak": 40}, "pokemon": "metang"})
        msg = str(ctx.exception)
        self.assertIn("peak", msg)
        self.assertIn("56", msg)
        self.assertIn("40", msg)


if __name__ == "__main__":
    unittest.main()
