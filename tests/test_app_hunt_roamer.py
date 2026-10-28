"""A Cresselia hunt through the facade: the roamer mode, end to end but for the page.

The Hunt side of `notes/roamers.md` sec 8's decision -- a roamer is a MODE on Hunt rather than a
separate tool, because what changes is how the seed is acquired and how the battle opens, and
nothing downstream changes at all.

Four claims carry the mode, and each is a class here:

* the kind is **derived from the encounter row**, on every write, and never configured;
* a roamer is centred on a **stopwatch reading** through a `StopwatchVector`, never on a Vector ms
  through the calibration model -- and the two fields are separate so neither can be read as the
  other;
* the run page is told to **skip Seed A**, because there is nothing to identify;
* the session simulates a roamer, so it can lose the run to a flee.

(clayton-957.35.13, .17)
"""
import tempfile
import unittest

from app.facade import Facade
from app.models import ENCOUNTER_ROAMER, ENCOUNTER_STATIC
from app.store import FileStore

STATS = ("hp", "atk", "def", "spa", "spd", "spe")

#: Hour byte 21 -- night, which is what makes a Dusk Ball x3.5 on this hunt.
NIGHT_SEED = 0x961502A4
INITIAL = "2026-06-15T21:30:30"
#: Two minutes of walking between routes before the roamer turned up.
STOPWATCH_MS = 120_000


class RoamerHuntCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))
        self.profile = self.api.create_profile({"name": "Plat", "game": "platinum"})["id"]

    def tearDown(self):
        self._tmp.cleanup()

    #: A Smeargle that outspeeds Cresselia's 100 and can trap it -- the only shape that works,
    #: and Mean Look is in SLOT 1 because the tests throw it on turn 1.
    SMEARGLE = dict(
        name="Smeargle", species="smeargle", level=64, ability="Own Tempo",
        stats={"hp": 154, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
        moveset=["Mean Look", "False Swipe", "Spore", "Foresight"],
        max_pp={"1": 5, "2": 40, "3": 15, "4": 40},
    )

    def _party(self):
        if not getattr(self, "_smeargle", None):
            self._smeargle = self.api.add_party_pokemon(
                self.profile, self.SMEARGLE)["pokemon_id"]
        return [{"pokemon_id": self._smeargle}]

    def _hunt(self, species="cresselia", level=50, **fields):
        # Named after the species, because hunt names are unique across every profile and
        # several of these tests build a roamer hunt and a static one side by side.
        created = self.api.create_hunt({"profile_id": self.profile,
                                        "name": f"Hunt {species}"})
        doc = dict(created)
        doc.update({
            "target": {"species": species, "level": level, "nature": "Modest",
                       "ivs": {k: 31 for k in STATS}},
            "key_seed": NIGHT_SEED, "initial_time": INITIAL,
            "stopwatch_ms": STOPWATCH_MS,
            "capture_ball": "Timer Ball",
            "party": self._party(),
        })
        doc.update(fields)
        return self.api.save_hunt(doc)


class TestTheKindIsDerived(RoamerHuntCase):

    def test_a_cresselia_hunt_is_a_roamer_hunt(self):
        self.assertEqual(self._hunt()["encounter_kind"], ENCOUNTER_ROAMER)

    def test_a_static_target_on_the_same_profile_is_not(self):
        self.assertEqual(self._hunt(species="uxie", level=50)["encounter_kind"],
                         ENCOUNTER_STATIC)

    def test_changing_the_species_changes_the_kind(self):
        hunt = self._hunt()
        hunt["target"] = {**hunt["target"], "species": "uxie", "level": 50}
        self.assertEqual(self.api.save_hunt(hunt)["encounter_kind"], ENCOUNTER_STATIC)

    def test_an_unconfigured_hunt_is_left_alone_rather_than_stamped_static(self):
        """A hunt on its way to a species is not a static hunt."""
        created = self.api.create_hunt({"profile_id": self.profile, "name": "Blank"})
        self.assertEqual(created["encounter_kind"], ENCOUNTER_STATIC)
        self.assertEqual(created["target"]["species"], "")

    def test_the_kind_survives_a_round_trip(self):
        hunt_id = self._hunt()["id"]
        self.assertEqual(self.api.get_hunt(hunt_id)["encounter_kind"], ENCOUNTER_ROAMER)

    def test_a_hunt_written_before_roamers_existed_loads_as_static(self):
        from app.models import Hunt

        self.assertEqual(Hunt.from_dict({"name": "Old", "profile_id": "p"}).encounter_kind,
                         ENCOUNTER_STATIC)
        self.assertEqual(
            Hunt.from_dict({"name": "Odd", "profile_id": "p",
                            "encounter_kind": "nonsense"}).encounter_kind,
            ENCOUNTER_STATIC)


class TestItAsksForAStopwatchNotACountdown(RoamerHuntCase):

    def test_a_roamer_needs_a_stopwatch_reading(self):
        hunt = self._hunt(stopwatch_ms=None)
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertTrue([e for e in errors if "stopwatch reading" in e], errors)

    def test_and_does_not_need_a_vector_ms(self):
        hunt = self._hunt(vector_ms=None)
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertEqual([e for e in errors if "Vector ms" in e], [])

    def test_a_static_hunt_still_needs_its_vector_ms(self):
        hunt = self._hunt(species="uxie", level=50, vector_ms=None)
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertTrue([e for e in errors if "Vector ms" in e], errors)

    def test_a_nonsense_reading_is_refused(self):
        hunt = self._hunt(stopwatch_ms=0)
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertTrue([e for e in errors if "greater than zero" in e], errors)


class TestTheWindowIsCentredOnTheReading(RoamerHuntCase):

    def test_the_centre_is_the_key_seeds_delay_plus_the_measured_frames(self):
        from claytonlib.battle_compass.candidates import seed_a_delay
        from claytonlib.stopwatch import StopwatchVector
        import datetime as dt

        probe = self.api.hunt_candidates(self._hunt()["id"])
        expected = (seed_a_delay(NIGHT_SEED, dt.datetime.fromisoformat(INITIAL))
                    + round(StopwatchVector().frames_in(STOPWATCH_MS)))
        self.assertEqual(probe["frame_centre"], expected)
        self.assertEqual(probe["second_centre"], 120)

    def test_it_is_not_the_calibration_models_centre(self):
        """The whole point of `_centring_model`: the fitted intercept belongs to a countdown."""
        roamer = self.api.hunt_candidates(self._hunt()["id"])
        static = self.api.hunt_candidates(
            self._hunt(species="uxie", level=50, vector_ms=STOPWATCH_MS)["id"])
        self.assertNotEqual(roamer["frame_centre"], static["frame_centre"])

    def test_the_probe_says_which_kind_it_centred(self):
        probe = self.api.hunt_candidates(self._hunt()["id"])
        self.assertEqual(probe["encounter_kind"], ENCOUNTER_ROAMER)
        self.assertGreaterEqual(probe["suggested_frame_window"], 60)
        self.assertGreaterEqual(probe["suggested_second_window"], 1)

    def test_a_static_hunt_gets_no_suggestions(self):
        probe = self.api.hunt_candidates(
            self._hunt(species="uxie", level=50, vector_ms=STOPWATCH_MS)["id"])
        self.assertIsNone(probe["suggested_frame_window"])
        self.assertIsNone(probe["suggested_second_window"])

    def test_a_missing_reading_is_reported_in_the_right_words(self):
        probe = self.api.hunt_candidates(self._hunt(stopwatch_ms=None)["id"])
        self.assertFalse(probe["ok"])
        self.assertIn("stopwatch reading", probe["problem"])

    def test_the_page_may_override_the_reading(self):
        hunt_id = self._hunt()["id"]
        a = self.api.hunt_candidates(hunt_id, {"stopwatch_ms": 60_000})
        b = self.api.hunt_candidates(hunt_id, {"stopwatch_ms": 180_000})
        self.assertLess(a["frame_centre"], b["frame_centre"])
        self.assertEqual(b["second_centre"] - a["second_centre"], 120)


class TestTheRunPage(RoamerHuntCase):

    def test_it_is_told_to_skip_seed_a(self):
        setup = self.api.hunt_run_setup(self._hunt()["id"])
        self.assertTrue(setup["skips_seed_a"])
        self.assertEqual(setup["encounter_kind"], ENCOUNTER_ROAMER)
        self.assertEqual(setup["targeting"]["stopwatch_ms"], STOPWATCH_MS)

    def test_a_static_run_still_identifies_seed_a(self):
        setup = self.api.hunt_run_setup(
            self._hunt(species="uxie", level=50, vector_ms=STOPWATCH_MS)["id"])
        self.assertFalse(setup["skips_seed_a"])


class TestTheSessionSimulatesARoamer(RoamerHuntCase):

    def test_a_run_starts_and_knows_the_target_can_leave(self):
        hunt_id = self._hunt(seconds_window=1, delay_window=4)["id"]
        started = self.api.hunt_session_start(hunt_id)
        self.assertIsNotNone(started["session_id"], started.get("problem"))
        snapshot = started["snapshot"]
        self.assertIn("target_fled", snapshot)
        self.assertFalse(snapshot["target_fled"])

    def test_the_session_config_carries_the_roamer_flag(self):
        hunt_id = self._hunt(seconds_window=1, delay_window=4)["id"]
        started = self.api.hunt_session_start(hunt_id)
        session = self.api._hunt_sessions.get(started["session_id"])
        self.assertTrue(session.config.target_is_roamer)

    def test_every_candidate_predicts_the_trap_refusing_the_escape(self):
        """Our Mean Look outspeeds it, so turn 1 is 'Etrp' for the whole window -- and that is
        deterministic, which is why it eliminates nothing."""
        from claytonlib.battle_compass import tokens as tok
        from claytonlib.battle_compass.state import Action

        hunt_id = self._hunt(seconds_window=1, delay_window=4)["id"]
        started = self.api.hunt_session_start(hunt_id)
        session = self.api._hunt_sessions.get(started["session_id"])
        predictions = session.predict(Action.MOVE_1)
        self.assertTrue(predictions)
        self.assertTrue(all(tok.escape_failed_token() in p for p in predictions.values()),
                        predictions)

    def test_a_static_hunt_on_the_same_profile_does_not_get_the_flag(self):
        hunt_id = self._hunt(species="uxie", level=50, vector_ms=STOPWATCH_MS,
                             seconds_window=1, delay_window=4)["id"]
        started = self.api.hunt_session_start(hunt_id)
        session = self.api._hunt_sessions.get(started["session_id"])
        self.assertFalse(session.config.target_is_roamer)
