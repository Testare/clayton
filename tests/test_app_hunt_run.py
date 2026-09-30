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
        self.assertIn("before Seed A's own frame", result["problem"])
        self.assertIn("MILLISECONDS", result["problem"])

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


class TestTheRunPageIsAnInterview(unittest.TestCase):
    """Not a box you type a token string into. The grammar belongs in the tool, not in the
    player's head over dozens of turns -- and a typo would be indistinguishable from a wrong
    model constant, which is the one diagnosis the whole design depends on."""

    def setUp(self):
        self.html = INDEX.read_text()
        self.run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        self.run = self.run[:self.run.index("async function huntConfigure(id){")]

    def test_there_is_no_free_text_token_input(self):
        self.assertFalse('placeholder="e.g. M1hE3hHP130"' in self.html)
        self.assertFalse('id="hrTokens"' in self.html)

    def test_there_is_no_raw_action_code_dropdown(self):
        """M1/M2/C/P meant nothing to read; the chips carry move names instead."""
        self.assertFalse('<select id="hrAction">' in self.html)

    def test_it_asks_questions_and_assembles_the_tokens_itself(self):
        for fn in ("hrInterview", "hrTokens", "hrChips", "hrChip", "hrSet", "hrTurnReset"):
            self.assertTrue(f"function {fn}(" in self.html, fn)

    def test_the_questions_are_driven_by_move_metadata(self):
        """So a status move is never asked whether it crit, and a never-miss move is never
        offered 'missed'."""
        for flag in ("damaging", "can_miss", "has_secondary"):
            self.assertIn(flag, self.run)

    def test_the_secondary_effect_is_asked_about(self):
        """Aurora Beam's Attack drop renders its own token; without a question for it, 96 of 456
        predictable turns were unreportable."""
        self.assertIn("extra effect happen", self.run)
        self.assertIn("~", self.run)

    def test_hp_is_only_asked_when_something_changed_it(self):
        self.assertTrue("function hrNeedsHp(" in self.html)

    def test_the_assembled_tokens_are_shown_before_submitting(self):
        """What the player confirms must be exactly what is applied."""
        self.assertIn("hrPreview", self.run)
        self.assertIn("Reporting", self.run)

    def test_move_names_reach_the_chips(self):
        self.assertIn("move_info", self.run)
        self.assertIn("m.name", self.run)


class TestVectorMsPresentation(unittest.TestCase):
    """Vector ms is in MILLISECONDS, and 120 vs 120000 is the mistake the unit invites."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_both_vector_fields_suggest_a_realistic_value(self):
        self.assertEqual(self.html.count('placeholder="300000"'), 4)

    def test_the_last_three_digits_are_shaded_like_the_other_pages(self):
        self.assertTrue("fmtVectorMs(h.vector_ms)" in self.html)
        self.assertTrue("huntVectorHint" in self.html)
        self.assertTrue(".ms-tail" in self.html.split("</style>")[0])

    def test_the_run_page_shows_the_duration_too(self):
        """A duration makes a wrong unit obvious at a glance."""
        self.assertIn("fmtDuration", self.html[self.html.index("function huntVectorHint"):
                                               self.html.index("function huntTargetingFromForm")])


class TestPartyOrdering(unittest.TestCase):
    """The lead is the Pokemon Battle Compass simulates as active, so the order decides whose
    Speed sets turn order and whose moves M1-M4 mean. It was not visible or changeable."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_there_is_a_send_out_order_section(self):
        self.assertIn("Send-out order", self.html)

    def test_it_can_be_reordered(self):
        self.assertTrue("function huntMoveParty(" in self.html)
        self.assertIn("huntMoveParty(", self.html)

    def test_the_lead_is_labelled(self):
        self.assertIn('badge ok">lead', self.html)

    def test_reordering_the_party_changes_which_pokemon_leads(self):
        """The functional consequence, exercised through the facade."""
        facade, hunt_id = _ready_hunt()
        hunt = facade.get_hunt(hunt_id)
        profile_id = hunt["profile_id"]
        second = facade.add_party_pokemon(profile_id, dict(LEAD, name="Slowpoke"))["pokemon_id"]
        hunt["party"] = [{"pokemon_id": second, "held_item": ""},
                         hunt["party"][0]]
        facade.save_hunt(hunt)
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["name"], "Slowpoke")


class TestTheUiIsReadable(unittest.TestCase):
    """.chip is used on <button> here, and a button's UA color is black -- which on the dark
    surface was black on dark grey. .btn always set color explicitly; .chip never did, because
    every prior use was on a <span>, which inherits it."""

    def setUp(self):
        self.css = INDEX.read_text().split("</style>")[0]

    def test_chips_set_their_own_colour(self):
        import re
        rule = re.search(r"\.chip\{([^}]*)\}", self.css).group(1)
        self.assertIn("color:var(--ink)", rule.replace(" ", ""))

    def test_chips_do_not_inherit_a_button_ua_font(self):
        import re
        rule = re.search(r"\.chip\{([^}]*)\}", self.css).group(1)
        self.assertIn("font:inherit", rule.replace(" ", ""))

    def test_a_disabled_chip_looks_disabled(self):
        self.assertIn(".chip:disabled", self.css)


class TestNoActionSilentlyVanishes(unittest.TestCase):
    """An action that is simply absent reads as a missing feature. Balls during setup are
    forbidden on purpose (sec 2.3), so they are shown disabled with the reason."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_forbidden_actions_are_shown_with_a_reason(self):
        self.assertTrue("function hrChipOff(" in self.html)
        self.assertIn("WRONG ball", self.html)

    def test_an_empty_bench_explains_why_switching_is_unavailable(self):
        self.assertIn("Nobody else on the hunt's party", self.html)


class TestTrivialQuestionsAreNotAsked(unittest.TestCase):
    """Rain Dance cannot miss and deals no damage, so 'did it work?' has one answer -- which is
    deducible from the move, not something to ask about."""

    def test_a_single_option_question_is_skipped(self):
        html = INDEX.read_text()
        self.assertTrue("function hrAutoAnswer(" in html)
        self.assertTrue("hrAutoAnswer(opts2" in html, "the target outcome must use it")

    def test_rain_dance_has_exactly_one_possible_outcome(self):
        """Which is what makes it skippable; Aurora Beam has several and must still be asked."""
        from claytonlib.battle_compass.hunt_session import move_info
        from claytonlib.battle_compass.state import Battler
        from claytonlib.battle_compass.targets import moveset
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.moves import resolve_move
        moves = moveset("suicune")
        target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                         stats=derive_species_stats("suicune", 40, "Bold"), moves=moves,
                         pp=tuple(resolve_move(m).pp for m in moves))
        info = {m["name"]: m for m in move_info(target)}
        rain = info["Rain Dance"]
        self.assertFalse(rain["damaging"])
        self.assertFalse(rain["can_miss"])
        beam = info["Aurora Beam"]
        self.assertTrue(beam["damaging"] or beam["can_miss"])


class TestThePpFallback(unittest.TestCase):
    """Unrecorded max PP became 0, which made every move unusable -- so the run offered only
    'use an item' and 'switch'. It is only a WARNING on the party Pokemon, so the hunt still
    reported itself ready and the failure appeared at the worst moment."""

    def _hunt_with_pp(self, max_pp):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        fields = dict(LEAD, moveset=["Thunder Wave", "Tackle"])
        if max_pp is None:
            fields.pop("max_pp", None)
        else:
            fields["max_pp"] = max_pp
        lead = facade.add_party_pokemon(profile_id, fields)["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({"target": TARGET, "party": [{"pokemon_id": lead}],
                     "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
                     "initial_time": "2026-01-01T12:00:00", "vector_ms": 120000,
                     "seconds_window": 0, "delay_window": 10})
        facade.save_hunt(hunt)
        return facade, hunt["id"]

    def test_unrecorded_pp_falls_back_to_the_moves_base_pp(self):
        facade, hunt_id = self._hunt_with_pp(None)
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["pp"], [20, 35])   # Thunder Wave 20, Tackle 35

    def test_the_moves_are_therefore_offered(self):
        facade, hunt_id = self._hunt_with_pp(None)
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertIn("M1", snap["legal_actions"])
        self.assertIn("M2", snap["legal_actions"])

    def test_a_recorded_value_still_wins(self):
        """It is the max, PP Ups included, so it can exceed the move's base PP."""
        facade, hunt_id = self._hunt_with_pp({"0": 32, "1": 35})
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["pp"], [32, 35])

    def test_zero_is_treated_as_unrecorded_rather_than_as_no_pp(self):
        """A configured 0 cannot mean 'this move is unusable' -- it means nobody filled it in."""
        facade, hunt_id = self._hunt_with_pp({"0": 0, "1": 0})
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["pp"], [20, 35])


class TestSwitchingThroughTheFacade(unittest.TestCase):
    def _two_member_hunt(self):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        mag = facade.add_party_pokemon(profile_id, dict(
            LEAD, name="Magneton", species="magneton", level=30,
            moveset=["Thunder Wave", "Tackle"], max_pp={}))["pokemon_id"]
        sme = facade.add_party_pokemon(profile_id, LEAD)["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({"target": TARGET,
                     "party": [{"pokemon_id": mag}, {"pokemon_id": sme}],
                     "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
                     "initial_time": "2026-01-01T12:00:00", "vector_ms": 120000,
                     "seconds_window": 0, "delay_window": 10})
        facade.save_hunt(hunt)
        return facade, hunt["id"]

    def test_the_bench_reaches_the_snapshot(self):
        facade, hunt_id = self._two_member_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["name"], "Magneton")
        self.assertEqual([b["name"] for b in snap["bench"]], ["Smeargle"])
        self.assertIn("S", snap["legal_actions"])

    def test_switching_changes_who_is_active(self):
        facade, hunt_id = self._two_member_hunt()
        started = facade.hunt_session_start(hunt_id)
        sid, snap = started["session_id"], started["snapshot"]
        truth = snap["candidates"][0]["seed"]
        predicted = facade.hunt_session_predict(sid, "S", bench_slot=0)[truth]
        after = facade.hunt_session_observe(sid, "S", [predicted], bench_slot=0)
        self.assertEqual(after["ours"]["name"], "Smeargle")

    def test_an_item_code_reaches_the_token(self):
        facade, hunt_id = self._two_member_hunt()
        started = facade.hunt_session_start(hunt_id)
        sid, snap = started["session_id"], started["snapshot"]
        truth = snap["candidates"][0]["seed"]
        predicted = facade.hunt_session_predict(sid, "I", item_code="sp")[truth]
        self.assertTrue(predicted.startswith("Isp"), predicted)

    def test_the_page_sends_both_choices(self):
        html = INDEX.read_text()
        self.assertIn("hunt_session_observe", html)
        self.assertIn("itemCode", html)
        self.assertIn("bench", html)


class TestTheReportButtonRecovers(unittest.TestCase):
    """Typing the HP is usually the LAST answer, and its oninput only refreshed the preview text
    -- so with every question answered the button stayed disabled. A rejected turn hit this every
    time, because the answers were cleared and HP had to be retyped."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_report_button_is_addressable(self):
        self.assertIn('id="hrReport"', self.html)

    def test_refreshing_the_preview_also_re_evaluates_the_button(self):
        body = self.html[self.html.index("function hrRefreshPreview()"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("hrReport", body)
        self.assertIn("disabled", body)
        self.assertIn("hrTurnComplete()", body)

    def test_the_hp_field_drives_that_refresh(self):
        self.assertIn("hrRefreshPreview()", self.html)
        hp_field = self.html[self.html.index('id="hrHp"'):]
        hp_field = hp_field[:hp_field.index(">")]
        self.assertIn("hrRefreshPreview", hp_field)

    def test_it_updates_in_place_rather_than_re_rendering(self):
        """A full re-render on each keystroke would steal focus from the HP field."""
        body = self.html[self.html.index("function hrRefreshPreview()"):]
        body = body[:body.index("\n}") + 2]
        self.assertNotIn("renderHuntRun", body)

    def test_a_rejected_turn_keeps_the_answers(self):
        self.assertIn("if (!_huntSnap.contradiction) hrTurnReset();", self.html)

    def test_observing_no_longer_clears_before_the_call(self):
        body = self.html[self.html.index("function huntRunObserve()"):]
        body = body[:body.index("\n}") + 2]
        self.assertNotIn("hrTurnReset()", body)


class TestSwitchHpThroughTheFacade(unittest.TestCase):
    def test_a_no_damage_switch_reports_no_hp(self):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        mag = facade.add_party_pokemon(profile_id, dict(
            LEAD, name="Magneton", species="magneton", level=30,
            stats={"hp": 85, "atk": 50, "def": 70, "spa": 90, "spd": 60, "spe": 60},
            moveset=["Thunder Wave", "Tackle"], max_pp={}))["pokemon_id"]
        sme = facade.add_party_pokemon(profile_id, LEAD)["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({"target": TARGET,
                     "party": [{"pokemon_id": mag}, {"pokemon_id": sme}],
                     "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
                     "initial_time": "2026-01-01T12:00:00", "vector_ms": 120000,
                     "seconds_window": 0, "delay_window": 60})
        facade.save_hunt(hunt)
        started = facade.hunt_session_start(hunt["id"])
        sid = started["session_id"]
        predictions = facade.hunt_session_predict(sid, "S", bench_slot=0)
        # Whatever each candidate predicts, an HP token may only appear with damage.
        for rendered in predictions.values():
            if "Epar" in rendered or "-" in rendered:
                self.assertNotIn("HP", rendered, rendered)


class TestTheHpBarShowsARange(unittest.TestCase):
    """Green to the HP every candidate agrees on, blue for the band they disagree over, track for
    what is certainly gone."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_bar_takes_a_range_rather_than_a_single_value(self):
        body = self.html[self.html.index("function hrBar("):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("range.low", body)
        self.assertIn("range.high", body)

    def test_it_renders_two_sections(self):
        self.assertIn("hr-bar-sure", self.html)
        self.assertIn("hr-bar-maybe", self.html)

    def test_both_sections_are_styled(self):
        css = self.html.split("</style>")[0]
        self.assertIn(".hr-bar-sure", css)
        self.assertIn(".hr-bar-maybe", css)
        self.assertIn(".hr-bar{display:flex}", css.replace(" ", ""))

    def test_an_uncertain_range_is_labelled(self):
        self.assertIn("candidates disagree", self.html)

    def test_danger_is_judged_on_the_worst_case(self):
        """Using the best case would under-warn exactly when it matters."""
        body = self.html[self.html.index("function hrSide("):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("range.low <= danger", body)


class TestPhaseTwoIsEmphasisedAndForceable(unittest.TestCase):
    def setUp(self):
        self.html = INDEX.read_text()

    def test_a_ready_target_gets_an_emphasised_call_to_action(self):
        self.assertIn("ok-cta", self.html)
        self.assertIn("at 1 HP and", self.html)
        self.assertIn(".ok-cta", self.html.split("</style>")[0])

    def test_solving_stays_available_when_the_model_objects(self):
        self.assertIn("Start solving anyway", self.html)
        self.assertTrue("function huntForceSolving(" in self.html)

    def test_it_confirms_first(self):
        body = self.html[self.html.index("function huntForceSolving("):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("confirm(", body)
        self.assertIn("hunt_session_enter_solving", body)
        self.assertIn("true", body)

    def test_the_facade_accepts_the_force_flag(self):
        import inspect
        self.assertIn("force", inspect.signature(Facade.hunt_session_enter_solving).parameters)

    def test_forcing_works_through_the_facade(self):
        facade, hunt_id = _ready_hunt()
        started = facade.hunt_session_start(hunt_id)
        sid = started["session_id"]
        facade.hunt_session_enter_pinning(sid)
        snap = facade.hunt_session_enter_solving(sid, True)
        self.assertEqual(snap["phase"], 3)

    def test_not_forcing_still_refuses(self):
        facade, hunt_id = _ready_hunt()
        sid = facade.hunt_session_start(hunt_id)["session_id"]
        facade.hunt_session_enter_pinning(sid)
        with self.assertRaises(ValueError):
            facade.hunt_session_enter_solving(sid)


class TestHeldItemsReachTheSimulation(unittest.TestCase):
    """Held items live on the HuntSlot, not the party Pokemon, because they change per hunt."""

    def test_the_slots_item_is_used(self):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        lead = facade.add_party_pokemon(profile_id, LEAD)["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({"target": TARGET,
                     "party": [{"pokemon_id": lead, "held_item": "Silk Scarf"}],
                     "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
                     "initial_time": "2026-01-01T12:00:00", "vector_ms": 120000,
                     "seconds_window": 0, "delay_window": 10})
        facade.save_hunt(hunt)
        snap = facade.hunt_session_start(hunt["id"])["snapshot"]
        self.assertEqual(snap["ours"]["held_item"], "Silk Scarf")
        self.assertEqual(snap["ours"]["ability"], "Technician")


class TestGuaranteedFailureIsNotAsked(unittest.TestCase):
    """Spore against an already-paralyzed Suicune renders as the bare slot token, so there is
    nothing to ask -- and "Missed / failed" produced a token no candidate could match."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_a_guaranteed_failure_offers_no_outcome(self):
        self.assertIn("!info.guaranteed_fail", self.html)

    def test_it_is_checked_on_both_sides(self):
        self.assertGreaterEqual(self.html.count("guaranteed_fail"), 4)

    def test_missed_is_gated_on_both_flags(self):
        self.assertIn("info.can_miss && !info.guaranteed_fail", self.html)

    def test_the_skipped_step_explains_itself(self):
        """Silence would read as a question the page forgot to ask."""
        self.assertIn("had no", self.html)
        self.assertIn("needs no reporting", self.html)

    def test_the_facade_reports_the_flags(self):
        facade, hunt_id = _ready_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        for entry in snap["ours"]["move_info"]:
            self.assertIn("guaranteed_fail", entry)
            self.assertIn("can_miss", entry)

    def test_a_hundred_accuracy_move_is_not_offered_a_miss(self):
        facade, hunt_id = _ready_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        by_name = {m["name"]: m for m in snap["ours"]["move_info"] if m["known"]}
        for name in ("False Swipe", "Spore", "Sweet Scent"):
            if name in by_name:
                self.assertFalse(by_name[name]["can_miss"], name)


if __name__ == "__main__":
    unittest.main()
