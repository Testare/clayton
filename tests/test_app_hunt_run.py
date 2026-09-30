"""The facade surface for a live Battle Compass run, and its UI wiring."""
import re
import pathlib
import tempfile
import unittest

from app.facade import Facade
from app.hunt_session import HuntSessionRegistry
from app.store import FileStore

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

LEAD = {
    "name": "Smeargle", "species": "smeargle", "level": 60, "ability": "Technician",
    "stats": {"hp": 170, "atk": 65, "def": 80, "spa": 60, "spd": 80, "spe": 160},
    "moveset": ["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    "max_pp": {"0": 40, "1": 5, "2": 20, "3": 15},
}
TARGET = {"species": "suicune", "level": 40, "nature": "Bold",
          "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31}}


def _ready_hunt(**overrides):
    facade = Facade(FileStore(tempfile.mkdtemp()))
    profile_id = facade.create_profile({"name": "T"})["id"]
    lead = facade.add_party_pokemon(profile_id, LEAD)["pokemon_id"]
    hunt = facade.create_hunt({"name": "Suicune", "profile_id": profile_id})
    hunt.update({
        "target": TARGET, "party": [{"pokemon_id": lead, "held_item": "Silk Scarf"}],
        "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
        "initial_time": "2026-01-01T12:00:00", "vector_ms": 5000,
        "seconds_window": 0, "delay_window": 10,
    })
    hunt.update(overrides)
    facade.save_hunt(hunt)
    return facade, hunt["id"]


class TestStartingARun(unittest.TestCase):
    def test_a_configured_hunt_starts(self):
        facade, hunt_id = _ready_hunt()
        self.assertEqual(facade.hunt_readiness(hunt_id)["hard_errors"], [])
        started = facade.hunt_session_start(hunt_id)
        self.assertTrue(started["session_id"])
        self.assertEqual(started["hunt_id"], hunt_id)
        self.assertGreater(started["snapshot"]["survivors"], 0)

    def test_the_battlers_come_from_stored_configuration(self):
        facade, hunt_id = _ready_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["name"], "Smeargle")
        self.assertEqual(snap["ours"]["max_hp"], 170)
        self.assertEqual(snap["ours"]["pp"], [40, 5, 20, 15])
        self.assertEqual(snap["target"]["name"], "Suicune")
        # Derived from the configured IVs/nature, not entered.
        self.assertEqual(snap["target"]["max_hp"], 142)

    def test_the_targets_moveset_is_the_encounters_in_slot_order(self):
        """Slot order is what the E1-E4 tokens mean and what the selection roll indexes."""
        facade, hunt_id = _ready_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["target"]["moves"],
                         ["Rain Dance", "Gust", "Aurora Beam", "Mist"])
        self.assertEqual(snap["target"]["pp"], [5, 35, 20, 30])

    def test_the_catch_rate_comes_from_the_species_table(self):
        """Not hand-entered: it is objective species data (PokeAPI capture_rate = 3)."""
        from claytonlib.battle.stats import species
        self.assertEqual(species("suicune")["catch_rate"], 3)

    def test_an_unready_hunt_is_refused_with_its_reasons(self):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        hunt = facade.create_hunt({"name": "Bare", "profile_id": profile_id})
        with self.assertRaises(ValueError) as caught:
            facade.hunt_session_start(hunt["id"])
        self.assertIn("not ready", str(caught.exception))

    def test_a_fast_ball_on_suicune_is_not_matched(self):
        """Base Speed 85 misses the Fast Ball's 100 threshold -- the hard case the tool is for."""
        facade, hunt_id = _ready_hunt()
        facade.hunt_session_start(hunt_id)
        session = facade._hunt_sessions.get(facade._hunt_sessions.for_hunt(hunt_id)[0])
        self.assertFalse(session.config.fast_ball_matched)
        self.assertEqual(session.config.target_catch_rate, 3)


class TestRunningTheLoop(unittest.TestCase):
    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()
        started = self.facade.hunt_session_start(self.hunt_id)
        self.sid = started["session_id"]
        self.snap = started["snapshot"]

    def _truth(self):
        return self.snap["candidates"][0]["seed"]

    def test_predict_then_observe_narrows_the_set(self):
        predicted = self.facade.hunt_session_predict(self.sid, "M1")[self._truth()]
        snap = self.facade.hunt_session_observe(self.sid, "M1", [predicted])
        self.assertLess(snap["survivors"], self.snap["survivors"])

    def test_observe_accepts_a_bare_string_as_well_as_a_list(self):
        """The UI sends one rendered turn; a caller may reasonably send either."""
        predicted = self.facade.hunt_session_predict(self.sid, "M1")[self._truth()]
        snap = self.facade.hunt_session_observe(self.sid, "M1", predicted)
        self.assertEqual(len(snap["turns"]), 1)

    def test_undo_returns_the_previous_snapshot(self):
        predicted = self.facade.hunt_session_predict(self.sid, "M1")[self._truth()]
        self.facade.hunt_session_observe(self.sid, "M1", [predicted])
        self.assertEqual(self.facade.hunt_session_undo(self.sid)["survivors"],
                         self.snap["survivors"])

    def test_state_is_readable_without_mutating(self):
        first = self.facade.hunt_session_state(self.sid)
        self.assertEqual(first, self.facade.hunt_session_state(self.sid))

    def test_a_ball_is_refused_during_setup(self):
        with self.assertRaises(ValueError) as caught:
            self.facade.hunt_session_observe(self.sid, "C", ["C0"])
        self.assertIn("wrong ball", str(caught.exception))

    def test_abandoning_closes_the_session(self):
        self.assertTrue(self.facade.hunt_session_abandon(self.sid)["closed"])
        with self.assertRaises(ValueError):
            self.facade.hunt_session_state(self.sid)

    def test_an_unknown_session_says_runs_are_not_persisted(self):
        """Restarting the app ends a run, and the message has to say so or it reads as data loss."""
        with self.assertRaises(ValueError) as caught:
            self.facade.hunt_session_state("nope")
        self.assertIn("memory only", str(caught.exception))


class TestRegistry(unittest.TestCase):
    def test_sessions_are_keyed_per_hunt(self):
        registry = HuntSessionRegistry()
        a = registry.add("hunt-1", object())
        b = registry.add("hunt-2", object())
        self.assertNotEqual(a, b)
        self.assertEqual(registry.for_hunt("hunt-1"), [a])
        self.assertEqual(registry.hunt_of(b), "hunt-2")

    def test_dropping_is_idempotent(self):
        registry = HuntSessionRegistry()
        sid = registry.add("h", object())
        self.assertTrue(registry.drop(sid))
        self.assertFalse(registry.drop(sid))


class TestUiWiring(unittest.TestCase):
    """The stub this replaces was a live toast saying Battle Compass was not built."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_not_built_toast_is_gone(self):
        self.assertFalse("Battle Compass is not built yet" in self.html)

    def test_the_start_button_calls_the_run(self):
        self.assertIn('[["Start Run", "huntRunStart"]]', self.html)

    def test_no_hunt_tool_button_has_a_null_handler(self):
        """A null handler was how the stub was expressed; it must not come back."""
        self.assertFalse('[["Start", null]]' in self.html)
        self.assertFalse(", null]]" in self.html)

    def test_every_facade_method_the_page_calls_exists(self):
        run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        called = set(re.findall(r'api\("(\w+)"', run))
        self.assertTrue(called)
        for method in called:
            self.assertTrue(callable(getattr(Facade, method, None)),
                            f"index.html calls api({method!r}) but Facade has no such method")
        self.assertIn("hunt_session_start", called)

    def test_the_run_page_defines_every_handler_its_markup_references(self):
        run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        referenced = set(re.findall(r'onclick="(\w+)\(', run))
        referenced |= set(re.findall(r"onkeydown=\"[^\"]*?(\w+)\(\)", run))
        self.assertTrue(referenced)
        for name in referenced:
            # assertTrue, not assertIn: a failing assertIn prints the whole page.
            self.assertTrue(f"function {name}(" in self.html or f"{name} = " in self.html,
                            f"markup calls {name}() but nothing defines it")

    def test_every_css_class_the_run_page_uses_is_defined(self):
        run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        css = self.html.split("</style>")[0]
        defined = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))
        used = {c for spec in re.findall(r'class="([^"$]*)"', run) for c in spec.split()}
        self.assertTrue(used)
        self.assertEqual(sorted(c for c in used if c not in defined), [])

    def test_the_page_warns_that_a_window_is_not_a_capture(self):
        """The solver's own caveat has to reach the player, or a window count reads as progress."""
        self.assertTrue("not a reachable one" in self.html)


class TestThePageOpensOnConfigurationAlone(unittest.TestCase):
    """The reported bug: an empty candidate window raised, so the run page could not be opened
    at all. But finding the seed is what the run is *for* -- every other compass opens its page
    and searches from it. Only a hunt that is not configured should keep you out."""

    def test_setup_opens_even_with_no_targeting_at_all(self):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        hunt = facade.create_hunt({"name": "Bare", "profile_id": profile_id})
        setup = facade.hunt_run_setup(hunt["id"])
        self.assertEqual(setup["hunt_id"], hunt["id"])
        self.assertTrue(setup["hard_errors"], "a bare hunt should report what it is missing")

    def test_setup_opens_when_the_window_would_be_empty(self):
        facade, hunt_id = _ready_hunt(vector_ms=1000)
        setup = facade.hunt_run_setup(hunt_id)
        self.assertEqual(setup["hard_errors"], [])
        self.assertEqual(setup["targeting"]["vector_ms"], 1000)

    def test_an_empty_window_is_reported_not_raised(self):
        facade, hunt_id = _ready_hunt(vector_ms=1000)
        result = facade.hunt_candidates(hunt_id)
        self.assertFalse(result["ok"])
        self.assertEqual(result["candidates"], 0)
        self.assertIn("does not start until frame", result["problem"])

    def test_starting_with_an_empty_window_returns_the_problem(self):
        facade, hunt_id = _ready_hunt(vector_ms=1000)
        started = facade.hunt_session_start(hunt_id)
        self.assertIsNone(started["session_id"])
        self.assertTrue(started["problem"])

    def test_the_targeting_can_be_corrected_from_the_page(self):
        facade, hunt_id = _ready_hunt(vector_ms=1000)
        started = facade.hunt_session_start(hunt_id, {"vector_ms": 5000})
        self.assertTrue(started["session_id"])
        self.assertGreater(started["snapshot"]["survivors"], 0)

    def test_a_correction_is_saved_back_to_the_hunt(self):
        """Or the next run would start from the window that just failed."""
        facade, hunt_id = _ready_hunt(vector_ms=1000)
        facade.hunt_session_start(hunt_id, {"vector_ms": 5000, "delay_window": 25})
        hunt = facade.get_hunt(hunt_id)
        self.assertEqual(hunt["vector_ms"], 5000)
        self.assertEqual(hunt["delay_window"], 25)

    def test_configuration_errors_do_still_block_starting(self):
        """These are exact simulation requirements -- a missing Speed desynchronises rather
        than degrades -- so they remain the one hard gate."""
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        hunt = facade.create_hunt({"name": "Bare", "profile_id": profile_id})
        with self.assertRaises(ValueError) as caught:
            facade.hunt_session_start(hunt["id"])
        self.assertIn("not ready", str(caught.exception))

    def test_incomplete_targeting_says_which_field(self):
        facade, hunt_id = _ready_hunt()
        result = facade.hunt_candidates(hunt_id, {"key_seed": "", "initial_time": "",
                                                  "vector_ms": ""})
        self.assertFalse(result["ok"])
        for field in ("key seed", "initial time", "vector ms"):
            self.assertIn(field, result["problem"])

    def test_a_blank_field_means_blank_rather_than_the_stored_value(self):
        """The page sends every field, so a cleared one is a deliberate act. Falling back to the
        stored value would silently ignore the edit the player just made."""
        facade, hunt_id = _ready_hunt()
        self.assertIn("initial time",
                      facade.hunt_candidates(hunt_id, {"initial_time": ""})["problem"])
        self.assertIn("vector ms",
                      facade.hunt_candidates(hunt_id, {"vector_ms": ""})["problem"])
        self.assertIn("key seed",
                      facade.hunt_candidates(hunt_id, {"key_seed": ""})["problem"])

    def test_an_absent_field_does_fall_back_to_the_hunt(self):
        facade, hunt_id = _ready_hunt()
        self.assertTrue(facade.hunt_candidates(hunt_id, {})["ok"])
        self.assertTrue(facade.hunt_candidates(hunt_id)["ok"])

    def test_a_window_centred_below_the_base_delay_explains_itself(self):
        """The two causes of an empty window need opposite fixes, so a bare zero is not enough."""
        import datetime as dt
        from claytonlib.battle_compass.candidates import generate
        facade, hunt_id = _ready_hunt()
        hunt = facade.get_hunt(hunt_id)
        model = facade._resolve_calibration_models(hunt["profile_id"])["linear"]
        window = generate(model, key_seed=hunt["key_seed"],
                          initial_time=dt.datetime(2026, 1, 1, 12, 0, 0),
                          vector_ms=1000, frame_window=60, second_window=0)
        self.assertEqual(len(window), 0)
        self.assertEqual(window.skipped_below_base_delay, 121)
        self.assertIn("cannot precede", window.why_empty())

    def test_a_healthy_window_has_nothing_to_explain(self):
        import datetime as dt
        from claytonlib.battle_compass.candidates import generate
        facade, hunt_id = _ready_hunt()
        hunt = facade.get_hunt(hunt_id)
        model = facade._resolve_calibration_models(hunt["profile_id"])["linear"]
        window = generate(model, key_seed=hunt["key_seed"],
                          initial_time=dt.datetime(2026, 1, 1, 12, 0, 0),
                          vector_ms=5000, frame_window=60, second_window=0)
        self.assertTrue(len(window))
        self.assertIsNone(window.why_empty())


if __name__ == "__main__":
    unittest.main()
