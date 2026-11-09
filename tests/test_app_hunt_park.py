"""Parking a Battle Compass run and picking it up later.

Requested from the app: "Have the ability to 'cache' a single battle compass run to resume later;
makes bug fixes easier." That last clause decides the design. Live runs are held in memory
(`HuntSessionRegistry`), and what is stored here is the run's **history** -- the reported turns and
the phase transitions -- not a snapshot of the candidate set. A pickled set would carry the old
simulation's conclusions across the very fix it was parked for; replaying the observations puts the
new model to work on them, and `HuntSession._replay` refuses a history the model can no longer
explain rather than quietly continuing.

ONE slot, deliberately: a live run is something the player is sitting in front of a DS for.
"""
import tempfile
import unittest
from pathlib import Path

from app.facade import Facade
from app.store import FileStore

INDEX = Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

LEAD = {
    "name": "Smeargle", "species": "smeargle", "level": 60, "ability": "Technician",
    "stats": {"hp": 170, "atk": 65, "def": 80, "spa": 60, "spd": 80, "spe": 160},
    "moveset": ["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    "max_pp": {"1": 40, "2": 5, "3": 20, "4": 15},
}
TARGET = {"species": "suicune", "level": 40, "nature": "Bold",
          "ivs": {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}}


class ParkCase(unittest.TestCase):
    def setUp(self):
        self.store = FileStore(tempfile.mkdtemp())
        self.api = Facade(self.store)
        profile = self.api.create_profile({"name": "T"})["id"]
        lead = self.api.add_party_pokemon(profile, LEAD)["pokemon_id"]
        hunt = self.api.create_hunt({"name": "Suicune", "profile_id": profile})
        hunt.update({
            "target": TARGET, "party": [{"pokemon_id": lead, "held_item": "Silk Scarf"}],
            "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
            "initial_time": "2026-01-01T12:00:00", "vector_ms": 180000,
            "seconds_window": 0, "delay_window": 8,
        })
        self.api.save_hunt(hunt)
        self.hunt_id = hunt["id"]

    def _played(self, turns=3):
        """A session with `turns` real turns reported, simulated off the true seed."""
        started = self.api.hunt_session_start(self.hunt_id)
        sid = started["session_id"]
        truth = started["snapshot"]["candidates"][0]["seed"]
        snap = started["snapshot"]
        for _ in range(turns):
            predicted = self.api.hunt_session_predict(sid, "M1")[truth]
            snap = self.api.hunt_session_observe(sid, "M1", [predicted])
            self.assertIsNone(snap["contradiction"], snap["contradiction"])
        return sid, snap

    def _cold(self) -> Facade:
        """A new Facade over the same store, which is what a restart looks like."""
        return Facade(self.store)


class TestParkingKeepsTheRun(ParkCase):
    def test_nothing_is_parked_to_begin_with(self):
        self.assertIsNone(self.api.hunt_session_parked())

    def test_parking_records_the_turns_and_the_path(self):
        sid, snap = self._played()
        doc = self.api.hunt_session_park(sid)
        self.assertEqual(doc["turns"], 3)
        self.assertEqual(doc["path"], snap["path"])
        self.assertEqual(doc["hunt_id"], self.hunt_id)
        self.assertEqual(doc["hunt_name"], "Suicune")
        self.assertTrue(doc["saved_at"])

    def test_it_survives_a_restart(self):
        """The point of the feature. In-memory sessions do not."""
        sid, _ = self._played()
        self.api.hunt_session_park(sid)
        self.assertIsNotNone(self._cold().hunt_session_parked())

    def test_resuming_replays_every_turn(self):
        sid, snap = self._played()
        self.api.hunt_session_park(sid)
        out = self._cold().hunt_session_resume()
        self.assertTrue(out["resumed"])
        self.assertEqual(len(out["snapshot"]["turns"]), 3)
        self.assertEqual(out["snapshot"]["path"], snap["path"])

    def test_and_lands_on_the_same_candidate_set(self):
        """Which is the claim that makes a resume worth anything: the expensive half of a run is
        the eliminations, and they have to come back."""
        sid, snap = self._played()
        self.api.hunt_session_park(sid)
        out = self._cold().hunt_session_resume()
        self.assertEqual(out["snapshot"]["survivors"], snap["survivors"])
        self.assertEqual(out["snapshot"]["identified"], snap["identified"])

    def test_the_phase_comes_back_too(self):
        """Entering Phase 1.5 is a player DECLARATION, not something the tokens imply -- so
        replaying the path alone would drop it and the run would resume one phase behind."""
        sid, _ = self._played()
        self.api.hunt_session_enter_pinning(sid, None)
        before = self.api.hunt_session_state(sid)["phase"]
        self.assertEqual(before, 2)
        self.api.hunt_session_park(sid)
        out = self._cold().hunt_session_resume()
        self.assertEqual(out["snapshot"]["phase"], before)

    def test_a_transition_is_replayed_at_the_turn_it_happened_on(self):
        """Not just "the phase is right at the end": a transition recorded at turn 1 has to be
        re-entered before turn 2 is reported, or the later turns are replayed in the wrong phase.
        """
        started = self.api.hunt_session_start(self.hunt_id)
        sid = started["session_id"]
        truth = started["snapshot"]["candidates"][0]["seed"]
        predicted = self.api.hunt_session_predict(sid, "M1")[truth]
        self.api.hunt_session_observe(sid, "M1", [predicted])
        self.api.hunt_session_enter_pinning(sid, None)
        predicted = self.api.hunt_session_predict(sid, "M1")[truth]
        snap = self.api.hunt_session_observe(sid, "M1", [predicted])
        self.assertIsNone(snap["contradiction"])

        session = self.api._hunt_sessions.get(sid)
        self.assertEqual([(at, int(p)) for at, p in session.transitions], [(1, 2)])
        self.api.hunt_session_park(sid)
        resumed = self._cold()
        out = resumed.hunt_session_resume()
        restored = resumed._hunt_sessions.get(out["session_id"])
        self.assertEqual([(at, int(p)) for at, p in restored.transitions], [(1, 2)])
        self.assertEqual(len(out["snapshot"]["turns"]), 2)

    def test_the_page_blob_is_carried_opaquely(self):
        """A resumed run that lost the Seed A panel would be back at step one with a full
        history behind it -- asking for a seed the candidates are already filtered by."""
        sid, _ = self._played()
        blob = {"hsa": {"seedA": {"seed": 4242}, "pinnedFrame": 73}, "signal": {"kind": "elm"}}
        self.api.hunt_session_park(sid, blob)
        self.assertEqual(self._cold().hunt_session_resume()["page"], blob)

    def test_the_spread_the_run_started_with_is_parked_with_it(self):
        """A Seed A that is not the key seed produces a different Suicune, and the HUNT does not
        remember that spread -- it is per attempt. Losing it would resume against the wrong
        target's stats, which is a silently wrong run rather than a visibly broken one."""
        started = self.api.hunt_session_start(
            self.hunt_id, {"target_nature": "Timid", "target_ivs": "31 31 31 31 31 31"})
        sid = started["session_id"]
        doc = self.api.hunt_session_park(sid)
        self.assertEqual(doc["params"]["target_nature"], "Timid")
        self.assertEqual(doc["params"]["target_ivs"]["spe"], 31)
        resumed = self._cold()
        out = resumed.hunt_session_resume()
        self.assertEqual(resumed._hunt_sessions.get(out["session_id"]).target_nature, "Timid")

    def test_the_window_parked_is_the_one_in_use_not_the_hunts(self):
        """A mid-run widen moves the window, and resuming into a narrower one would refuse the
        history it was widened to explain."""
        sid, _ = self._played(turns=1)
        self.api.hunt_session_widen(sid)
        widened = self.api.hunt_session_state(sid)["window"]
        doc = self.api.hunt_session_park(sid)
        self.assertEqual(doc["params"]["delay_window"], widened["frame_window"])
        out = self._cold().hunt_session_resume()
        self.assertEqual(out["snapshot"]["window"]["frame_window"], widened["frame_window"])


class TestTheSlotHoldsExactlyOne(ParkCase):
    def test_parking_again_replaces_it(self):
        sid, _ = self._played(turns=1)
        first = self.api.hunt_session_park(sid)
        sid2, _ = self._played(turns=3)
        second = self.api.hunt_session_park(sid2)
        self.assertNotEqual(first["turns"], second["turns"])
        self.assertEqual(self.api.hunt_session_parked()["turns"], second["turns"])

    def test_discarding_it_leaves_nothing(self):
        sid, _ = self._played(turns=1)
        self.api.hunt_session_park(sid)
        self.assertTrue(self.api.hunt_session_unpark())
        self.assertIsNone(self.api.hunt_session_parked())
        self.assertFalse(self.api.hunt_session_unpark())

    def test_resuming_keeps_the_record(self):
        """A resume that goes wrong should be repeatable, and parking again overwrites anyway."""
        sid, _ = self._played(turns=1)
        self.api.hunt_session_park(sid)
        cold = self._cold()
        cold.hunt_session_resume()
        self.assertIsNotNone(cold.hunt_session_parked())

    def test_resuming_with_nothing_parked_says_so(self):
        with self.assertRaises(ValueError) as caught:
            self.api.hunt_session_resume()
        self.assertIn("no parked", str(caught.exception))


class TestWhatIsStoredIsTheHistory(ParkCase):
    """Not the state. The distinction is the feature."""

    def test_the_history_carries_each_turns_action_and_its_extras(self):
        """A turn is not fully described by what it rendered: an item's code and a switch's bench
        index are part of the ACTION, and `_replay` needs them."""
        sid, _ = self._played(turns=1)
        history = self.api._hunt_sessions.get(sid).history()
        self.assertEqual(len(history["turns"]), 1)
        row = history["turns"][0]
        self.assertEqual(row["action"], "M1")
        self.assertTrue(row["tokens"])
        for key in ("item_code", "bench_slot", "replacement"):
            self.assertIn(key, row)

    def test_it_is_json_safe(self):
        import json

        sid, _ = self._played(turns=2)
        self.api.hunt_session_enter_pinning(sid, None)
        doc = self.api.hunt_session_park(sid)
        self.assertEqual(json.loads(json.dumps(doc))["turns"], doc["turns"])

    def test_a_history_the_model_can_no_longer_explain_is_refused_loudly(self):
        """The honest outcome when a fix really does change what a turn means: pressing on would
        report later turns against a state the game never reached."""
        sid, _ = self._played(turns=1)
        self.api.hunt_session_park(sid)
        doc = self.api.hunt_session_parked()
        # Stand in for "the simulator changed under the run" by corrupting one recorded turn.
        doc["history"]["turns"][0]["tokens"] = ["M1", "E1", "HP001"]
        self.store.write("run_cache", "current", doc)
        with self.assertRaises(ValueError) as caught:
            self._cold().hunt_session_resume()
        self.assertIn("no longer matches", str(caught.exception))


class TestThePageOffersIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text()

    def test_the_run_page_can_park(self):
        self.assertIn("function huntParkRun(){", self.html)
        self.assertIn(">Park run</button>", self.html)

    def test_it_hands_the_seed_a_panel_over_with_it(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        body = _function_body("huntParkRun")
        self.assertIn('api("hunt_session_park", _huntRun, {hsa: _hsa', body)

    def test_both_hunt_screens_offer_the_resume(self):
        """The list is where you land after restarting the app; the hunt page is where you would
        otherwise start a second run over the top of the parked one."""
        self.assertIn("function huntParkedBanner(){", self.html)
        self.assertEqual(self.html.count("${huntParkedBanner()}"), 2)
        self.assertIn("function huntResumeParked(){", self.html)
        self.assertIn("function huntDiscardParked(){", self.html)

    def test_resuming_goes_through_the_same_state_builder_as_starting(self):
        """The bug that made resuming look like it did nothing (round 10 feedback).

        A run page needs half a dozen page globals, and `_hrTurn` is the sharp one: it starts
        null and `hrTurnReset` is what fills it, so the interview threw on `t.action`,
        `renderHuntRun` threw with it, and the page stayed on whatever was there before. A render
        that throws leaves no error on screen, so it reads as "resume does nothing" rather than
        as a failure.

        The fix is structural rather than a longer list of assignments: the state-building half of
        `huntRunStart` has a name now, and both routes call it. So a global added there is not a
        thing resume has to remember separately.
        """
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        self.assertIn("async function huntRunLoadState(id){", self.html)
        for caller in ("huntRunStart", "huntResumeParked"):
            self.assertIn("huntRunLoadState(", _function_body(caller), caller)
        # And the one global the builder deliberately does NOT own, because it is per turn.
        self.assertIn("hrTurnReset();", _function_body("huntResumeParked"))

    def test_the_interview_cannot_be_blanked_by_a_missing_turn_reset_again(self):
        """Defence in depth on the same failure: the route is fixed, and the next one cannot fail
        silently the same way."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        self.assertIn("if (!_hrTurn) hrTurnReset();", _function_body("hrInterview"))

    def test_the_state_builder_sets_everything_the_run_page_reads(self):
        """Named one by one, because each was a separate silent failure: `_hrTurn` blanked the
        page, `_huntRunHunt` broke End run, `_huntSetup` made a resumed roamer look static, and
        `_hunt` meant a resumed winning run could not be marked complete."""
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        body = _function_body("huntRunLoadState")
        for name in ("_huntRunHunt = id", "_huntSetup = await api(", "_hsaSignal =",
                     "_hsa = {", '_hunt = await api("get_hunt"'):
            self.assertIn(name, body, name)

    def test_it_says_it_is_working_rather_than_going_quiet(self):
        """The other half of the report: "needs a loading bar if it is running". Resuming
        regenerates the candidate window and replays every turn against every candidate, which is
        seconds with no output."""
        self.assertIn("function renderHuntResuming(parked){", self.html)
        self.assertIn("progress-bar indeterminate", self.html)
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        body = _function_body("huntResumeParked")
        shown = body.index("renderHuntResuming(parked)")
        worked = body.index('api("hunt_session_resume")')
        self.assertLess(shown, worked, "the progress bar has to go up BEFORE the slow call")

    def test_a_failure_does_not_leave_the_progress_bar_up_for_ever(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        body = _function_body("huntResumeParked")
        self.assertIn("} catch (e) {", body)
        self.assertIn("renderHunts();", body)
        # An empty window is not a resume failure, so it lands where the window controls are.
        self.assertIn("renderHuntSetup();", body)

    def test_discarding_asks_first(self):
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_app_web_ui import _function_body

        self.assertIn("confirm(", _function_body("huntDiscardParked"))


if __name__ == "__main__":
    unittest.main()
