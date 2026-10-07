"""The facade surface for a live Battle Compass run, and its UI wiring."""
import re
import pathlib
import tempfile
import unittest
from dataclasses import replace

from app.facade import Facade
from app.hunt_session import HuntSessionRegistry
from app.store import FileStore

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

LEAD = {
    "name": "Smeargle", "species": "smeargle", "level": 60, "ability": "Technician",
    "stats": {"hp": 170, "atk": 65, "def": 80, "spa": 60, "spd": 80, "spe": 160},
    "moveset": ["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    # Keyed by 1-based move NUMBER, which is what the party form writes and what every saved
    # profile holds. This fixture used 0-based keys, matching the facade's own (wrong) reader --
    # so the test agreed with the bug and move 2 silently got move 1's PP.
    "max_pp": {"1": 40, "2": 5, "3": 20, "4": 15},
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

    def test_a_ball_is_accepted_during_setup(self):
        """The Phase 1 ban is lifted (notes/seed_separation.md sec 2a). Phase 1 is where a probe
        is cheapest, so it is the last place a throw should have been forbidden."""
        predicted = self.facade.hunt_session_predict(self.sid, "C")[self._truth()]
        snap = self.facade.hunt_session_observe(self.sid, "C", [predicted])
        self.assertEqual(len(snap["turns"]), 1)
        self.assertIsNone(snap["contradiction"])

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

    #: Things an inline handler may legitimately call that this page does not define.
    #: Needed because an onkeydown is often a small statement rather than a single call --
    #: `if(event.key==='Enter'){event.preventDefault();huntAppendFrameElm();}` names two
    #: functions and only one of them is ours. The alternative was to match just the first
    #: call, which quietly stopped checking the handler that actually matters.
    DOM_BUILTINS = {"preventDefault", "stopPropagation", "focus", "blur", "click"}

    def test_the_run_page_defines_every_handler_its_markup_references(self):
        run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        referenced = set(re.findall(r'onclick="(\w+)\(', run))
        for handler in re.findall(r'onkeydown="([^"]*)"', run):
            referenced |= set(re.findall(r"(\w+)\(", handler))
        referenced -= self.DOM_BUILTINS
        referenced -= {"if"}                      # `if(` is not a call
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
        """Still the rule for genuinely unavailable actions -- an empty bench. Balls are no
        longer among them: they are offered with their risk stated rather than withheld."""
        self.assertTrue("function hrChipOff(" in self.html)
        self.assertIn("Nobody else on the hunt's party", self.html)

    def test_the_ball_chips_carry_their_stakes_rather_than_being_disabled(self):
        self.assertTrue("function hrStandardBallWarning(" in self.html)
        self.assertIn("if it lands, the run is won", self.html)
        self.assertIn("wrong ball and the run is lost", self.html)

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
        facade, hunt_id = self._hunt_with_pp({"1": 32, "2": 35})
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["pp"], [32, 35])

    def test_each_move_gets_its_own_recorded_pp_and_not_the_previous_ones(self):
        """The regression, stated as the failure. `max_pp` is keyed by 1-based move NUMBER, and
        reading it with a 0-based slot gave move 2 move 1's PP, move 3 move 2's, never read move
        4's at all, and dropped move 1 through to the base-PP fallback -- which then looked like
        it was working. Two distinct values, so a shift of one is visible."""
        facade, hunt_id = self._hunt_with_pp({"1": 7, "2": 29})
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours"]["pp"], [7, 29])

    def test_a_four_move_set_is_not_shifted_either(self):
        """Move 4's PP was never read at all under the old indexing, so a 2-move fixture cannot
        catch that half of it."""
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        lead = facade.add_party_pokemon(profile_id, dict(
            LEAD, max_pp={"1": 11, "2": 22, "3": 33, "4": 44}))["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({"target": TARGET, "party": [{"pokemon_id": lead}],
                     "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
                     "initial_time": "2026-01-01T12:00:00", "vector_ms": 120000,
                     "seconds_window": 0, "delay_window": 10})
        facade.save_hunt(hunt)
        snap = facade.hunt_session_start(hunt["id"])["snapshot"]
        self.assertEqual(snap["ours"]["pp"], [11, 22, 33, 44])

    def test_zero_is_treated_as_unrecorded_rather_than_as_no_pp(self):
        """A configured 0 cannot mean 'this move is unusable' -- it means nobody filled it in."""
        facade, hunt_id = self._hunt_with_pp({"1": 0, "2": 0})
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
        """Through hrHpInput now rather than inline, since the field also has to strip
        non-digits -- but the invariant is the same: typing HP re-evaluates the button."""
        hp_field = self.html[self.html.index('id="hrHp"'):]
        hp_field = hp_field[:hp_field.index(">")]
        self.assertIn("hrHpInput(this)", hp_field)
        handler = self.html[self.html.index("function hrHpInput("):]
        handler = handler[:handler.index("\n}") + 2]
        self.assertIn("hrRefreshPreview()", handler)
        self.assertIn("_hrTurn.hp", handler)

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
    """A doomed move needs no question only when it ALSO cannot miss.

    Spore against an already-paralyzed Suicune renders as the bare slot token and there is
    genuinely nothing to ask. Sing is doomed in the same way and can still miss, so it has two
    distinguishable outcomes -- `M1-` against the bare `M1` -- and this class previously pinned
    the rule that suppressed both, string-matching `can_miss && !guaranteed_fail` straight out of
    the page. That left Sing unreportable and discarded the only observation that separates seeds
    an RTC second apart (notes/seed_separation.md).
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_missed_is_gated_on_can_miss_alone(self):
        self.assertIn("if (info.can_miss)", self.html)
        self.assertNotIn("info.can_miss && !info.guaranteed_fail", self.html)

    def test_a_doomed_move_is_still_asked_about_when_it_can_miss(self):
        """The branch that makes the two cases differ, on both sides of the battle."""
        self.assertGreaterEqual(self.html.count("} else if (info.guaranteed_fail){"), 2)
        self.assertGreaterEqual(self.html.count("if (info.can_miss)\n"
                                                "      opts2.push(hrChip(\"It failed\""), 0)
        self.assertIn('hrChip("It failed"', self.html)

    def test_it_is_checked_on_both_sides(self):
        self.assertGreaterEqual(self.html.count("guaranteed_fail"), 3)

    def test_the_skipped_step_explains_itself(self):
        """Silence would read as a question the page forgot to ask. Only reachable now for a
        doomed move that cannot miss, which is the case it was written for."""
        self.assertIn("had no", self.html)
        self.assertIn("needs no reporting", self.html)

    def test_a_doomed_missable_move_has_two_outcomes_the_simulator_renders(self):
        """The contract the question depends on, checked against the simulator rather than
        against the page's own source."""
        from claytonlib.battle_compass import tokens as tok
        from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
        from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.battle_compass.targets import moveset
        from claytonlib.moves import resolve_move

        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                       moves=("Sing", "False Swipe"), pp=(15, 40))
        mv = moveset("suicune")
        target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                         stats=derive_species_stats("suicune", 40, "Bold"), moves=mv,
                         pp=tuple(resolve_move(m).pp for m in mv), status=Status.PARALYSIS)
        hunt = HuntConfig(target_catch_rate=3)
        seen = set()
        for seed in range(0xEC1504DC, 0xEC1504DC + 300):
            nxt = simulate_turn(BattleState(ours=ours, target=target, rng=seed, phase=1),
                                Action.MOVE_1, hunt)
            seen.add(tok.render_turn(tok.normalise(nxt.log[-1])).split("E")[0])
        self.assertEqual(seen, {"M1", "M1-"})

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


class TestZeroOptionsCountsAsAnswered(unittest.TestCase):
    """A guaranteed failure leaves NO options -- not one, none. `hrAutoAnswer` tested
    `options.length !== 1`, so zero fell through and rendered "What happened to Spore?" above an
    empty row.

    There is no JS engine here, so this pairs a static guard on the branch with a Python check
    that the zero case is genuinely reachable. The previous test computed the offered set inside
    the test, duplicating the page's logic instead of exercising it -- which is exactly why it
    passed while the page was broken.
    """

    def setUp(self):
        self.html = INDEX.read_text()
        body = self.html[self.html.index("function hrAutoAnswer("):]
        self.body = body[:body.index("\n}") + 2]

    def test_it_auto_answers_zero_options(self):
        self.assertIn("options.length > 1", self.body)

    def test_it_no_longer_requires_exactly_one(self):
        """The precise regression, pinned by its shape."""
        self.assertNotIn("options.length !== 1", self.body)
        self.assertNotIn("options.length != 1", self.body)

    def test_both_outcome_questions_go_through_it(self):
        """So neither side can render an empty question."""
        self.assertIn("hrAutoAnswer(opts,", self.html)
        self.assertIn("hrAutoAnswer(opts2,", self.html)

    def test_a_guaranteed_failure_really_does_offer_nothing(self):
        """Proves the static guard above protects a reachable case rather than a hypothetical.

        Mirrors the page's option-building rules for a non-damaging, unmissable, guaranteed-fail
        move with no prevention markers available.
        """
        from claytonlib.battle_compass.hunt_session import (
            move_info, prevention_options, resolution_options,
        )
        from claytonlib.battle_compass.state import Status

        facade, hunt_id = _ready_hunt()
        started = facade.hunt_session_start(hunt_id)
        session = facade._hunt_sessions.get(started["session_id"])
        state = next(iter(session._session.states.values()))
        # The reported situation: target already paralyzed, we are not statused.
        target = replace(state.target, status=Status.PARALYSIS)
        spore = {m["name"]: m for m in move_info(state.ours, target)}["Spore"]

        self.assertTrue(spore["guaranteed_fail"])
        self.assertFalse(spore["damaging"])
        self.assertFalse(spore["can_miss"])
        self.assertEqual(prevention_options(state.ours, target, actor_moves_first=True), [])
        self.assertEqual(resolution_options(state.ours), [])

        # Count what the page would build: no "it worked" (guaranteed_fail), no "missed"
        # (can_miss false), no prevention, no resolution.
        options = 0
        if spore["damaging"]:
            options += 2
        elif not spore["guaranteed_fail"]:
            options += 1
        if spore["can_miss"] and not spore["guaranteed_fail"]:
            options += 1
        self.assertEqual(options, 0, "the zero-option case is unreachable, so the guard is moot")

    def test_the_skipped_question_still_says_why(self):
        """Silence where a question was would read as a page that forgot to ask."""
        self.assertIn("had no", self.html)
        self.assertIn("needs no reporting", self.html)


class TestStaleHpCannotSurvive(unittest.TestCase):
    """Reported: pick Gust (damaging), type an HP, then change the target's move to Rain Dance --
    the HP token stayed in the report though the turn no longer has one. hrTokens pushed it
    whenever the FIELD was filled in, rather than when the rule says the turn has one."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_token_is_gated_on_the_rule(self):
        self.assertIn('hrNeedsHp() && t.hp !== ""', self.html)

    def test_the_value_is_dropped_when_it_stops_applying(self):
        self.assertIn('if (path !== "hp" && !hrNeedsHp()) t.hp = "";', self.html)

    def test_changing_an_answer_re_evaluates_it(self):
        """The clear has to sit in hrSet, which is what every chip goes through."""
        body = self.html[self.html.index("function hrSet("):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("hrNeedsHp()", body)

    def test_a_healing_item_is_asked_about(self):
        """The other half of the same hole: the simulator emits HP after a potion, so the
        interview has to prompt for it or the report contradicts."""
        body = self.html[self.html.index("function hrNeedsHp("):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("entry.heals", body)
        self.assertIn('t.action === "I"', body)

    def test_the_snapshot_carries_the_heals_flag_the_page_needs(self):
        facade, hunt_id = _ready_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        by_code = {i["code"]: i for i in snap["items"]}
        self.assertTrue(by_code["sp"]["heals"])
        self.assertFalse(by_code["xsd"]["heals"])


class TestWideningMidRun(unittest.TestCase):
    """Recovery for "no candidate predicted that turn" when the cause was the window rather than
    a mistyped answer. Restarting would discard every turn already reported -- and those turns are
    exactly what filters the newly admitted candidates, so replaying them costs no information."""

    def _run_with_a_narrow_window(self):
        facade, hunt_id = _ready_hunt(delay_window=8, seconds_window=0)
        started = facade.hunt_session_start(hunt_id)
        return facade, hunt_id, started["session_id"], started["snapshot"]

    def test_widening_keeps_the_turns_already_reported(self):
        facade, _, sid, snap = self._run_with_a_narrow_window()
        truth = snap["candidates"][0]["seed"]
        predicted = facade.hunt_session_predict(sid, "M1")[truth]
        facade.hunt_session_observe(sid, "M1", [predicted])
        widened = facade.hunt_session_widen(sid)
        self.assertEqual(len(widened["turns"]), 1)

    def test_it_admits_candidates_that_explain_the_history(self):
        facade, _, sid, snap = self._run_with_a_narrow_window()
        truth = snap["candidates"][0]["seed"]
        predicted = facade.hunt_session_predict(sid, "M1")[truth]
        before = facade.hunt_session_observe(sid, "M1", [predicted])["survivors"]
        after = facade.hunt_session_widen(sid)["survivors"]
        self.assertGreaterEqual(after, before)

    def test_the_frame_range_doubles_by_default(self):
        """And the SECOND range is left alone, because widening it admits candidates no move can
        ever separate (sec 17.1)."""
        facade, _, sid, _ = self._run_with_a_narrow_window()
        widened = facade.hunt_session_widen(sid)
        self.assertEqual(widened["widened"]["frame_window"], 16)
        self.assertEqual(widened["widened"]["second_window"], 0)

    def test_it_clears_a_contradiction(self):
        facade, _, sid, snap = self._run_with_a_narrow_window()
        truth = snap["candidates"][0]["seed"]
        facade.hunt_session_observe(sid, "M1", [facade.hunt_session_predict(sid, "M1")[truth]])
        rejected = facade.hunt_session_observe(sid, "M1", ["M1hE3hHP001"])
        self.assertIsNotNone(rejected["contradiction"])
        self.assertIsNone(facade.hunt_session_widen(sid)["contradiction"])

    def test_narrowing_is_refused(self):
        """It would discard candidates the player never ruled out, and could make an accepted
        turn unexplainable."""
        facade, _, sid, _ = self._run_with_a_narrow_window()
        with self.assertRaises(ValueError) as caught:
            facade.hunt_session_widen(sid, frame_window=2)
        self.assertIn("narrow", str(caught.exception))

    def test_each_widening_is_recorded(self):
        facade, _, sid, _ = self._run_with_a_narrow_window()
        facade.hunt_session_widen(sid)
        snap = facade.hunt_session_widen(sid)
        self.assertEqual(len(snap["widenings"]), 2)
        self.assertEqual([w["frame_window"] for w in snap["widenings"]], [16, 32])

    def test_it_is_remembered_on_the_hunt(self):
        """So a restart does not begin from the window that already failed."""
        facade, hunt_id, sid, _ = self._run_with_a_narrow_window()
        facade.hunt_session_widen(sid)
        self.assertEqual(facade.get_hunt(hunt_id)["delay_window"], 16)

    def test_a_second_can_be_added_explicitly(self):
        facade, _, sid, _ = self._run_with_a_narrow_window()
        widened = facade.hunt_session_widen(sid, second_window=1)
        self.assertEqual(widened["widened"]["second_window"], 1)
        self.assertGreater(widened["survivors"], 0)

    def test_the_page_offers_both_and_prices_the_second_axis(self):
        """The warning used to say seconds could NEVER be told apart. They can -- median 19
        turns -- so it now states the cost instead of claiming impossibility."""
        html = INDEX.read_text()
        self.assertTrue("function huntWiden(" in html)
        self.assertTrue("function huntWidenSeconds(" in html)
        self.assertIn("19 turns", html)
        self.assertFalse("no move can ever tell apart" in html)

    def test_the_notice_no_longer_tells_you_to_restart(self):
        html = INDEX.read_text()
        self.assertFalse("restart with a wider window" in html)


class TestTheAdvicePanelIsReadable(unittest.TestCase):
    def setUp(self):
        self.html = INDEX.read_text()

    def test_it_renders_the_label_not_the_code(self):
        run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        self.assertIn("a.label", run)
        self.assertNotIn("<code>${esc(a.action)}</code>", run)

    def test_the_facade_supplies_labels(self):
        facade, hunt_id = _ready_hunt()
        sid = facade.hunt_session_start(hunt_id)["session_id"]
        facade.hunt_session_enter_pinning(sid)
        rows = facade.hunt_session_advice(sid)["advice"]
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("label", row)
            self.assertNotEqual(row["label"], row["action"])
        labels = {r["label"] for r in rows}
        self.assertTrue(any(l.startswith("Use ") for l in labels), labels)


class TestTheBallRiskGauge(unittest.TestCase):
    """A plain Poke Ball that LANDS loses the run, so the percentage of candidates it would catch
    is the gauge for whether throwing one is free information or a gamble."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_facade_reports_it_with_the_advice(self):
        """Same sweep over every candidate, so it costs nothing extra."""
        facade, hunt_id = _ready_hunt()
        sid = facade.hunt_session_start(hunt_id)["session_id"]
        facade.hunt_session_enter_pinning(sid)
        risk = facade.hunt_session_advice(sid)["standard_ball_risk"]
        self.assertIn("percent", risk)
        self.assertIn("would_catch", risk)
        self.assertIn("candidates", risk)
        self.assertIn("safe", risk)

    def test_it_is_reported_during_setup(self):
        """It used to be suppressed here, on the reasoning that Phase 1 forbade balls. With the
        ban lifted this is the phase where the figure matters most, because it is the phase where
        a probe is cheapest."""
        facade, hunt_id = _ready_hunt()
        sid = facade.hunt_session_start(hunt_id)["session_id"]
        risk = facade.hunt_session_advice(sid)["standard_ball_risk"]
        self.assertIsNotNone(risk)
        self.assertTrue(risk["matches_capture_ball"])

    def test_the_advice_ranks_balls_alongside_moves(self):
        facade, hunt_id = _ready_hunt()
        sid = facade.hunt_session_start(hunt_id)["session_id"]
        offered = {row["action"] for row in facade.hunt_session_advice(sid)["advice"]}
        self.assertIn("C", offered)
        self.assertIn("P", offered)

    def test_the_page_renders_it(self):
        self.assertTrue("function huntBallRisk(" in self.html)
        self.assertIn("would catch on", self.html)

    def test_it_says_safe_when_nothing_would_catch(self):
        self.assertIn("Poké Ball is safe right now", self.html)

    def test_it_explains_why_a_catch_is_bad(self):
        """The counter-intuitive part: catching is the failure, not the success."""
        self.assertIn("wrong ball", self.html)

    def test_it_is_invalidated_with_the_advice(self):
        """Or a stale percentage would describe the previous turn."""
        body = self.html[self.html.index("function huntAdviceInvalidate()"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("_huntBallRisk", body)


if __name__ == "__main__":
    unittest.main()


class TestTypedTargetingSurvivesARedraw(unittest.TestCase):
    """hunt_candidates deliberately does not persist, so the page renders targeting from the
    stored hunt -- and every redraw reverted whatever was typed. Survivable while the page only
    redrew on Search; not once identifying Seed A redraws it twice.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_render_captures_the_live_fields_first(self):
        self.assertIn("function huntCaptureTargeting(", self.html)
        self.assertIn("function renderHuntSetup(){\n  huntCaptureTargeting();", self.html)

    def test_it_is_a_no_op_before_the_fields_exist(self):
        self.assertIn('if (!_huntSetup || !$("hrKeySeed")) return;', self.html)

    def test_the_time_picker_writes_the_field_not_the_record(self):
        """Because the capture reads the DOM back, setting the record and re-rendering would
        overwrite the picked time with the stale field value."""
        self.assertIn("// Write the FIELD, not the targeting record.", self.html)

    def test_hunt_candidates_still_does_not_persist(self):
        """The premise. If it ever starts persisting, the capture is redundant rather than
        wrong -- but the comment above it would be a lie, so pin the premise."""
        facade, hunt_id = _ready_hunt()
        before = facade.get_hunt(hunt_id)["vector_ms"]
        facade.hunt_candidates(hunt_id, {"key_seed": "0x2D005C61",
                                         "initial_time": "2026-01-01T12:00:00",
                                         "vector_ms": 99999, "delay_window": 10,
                                         "seconds_window": 0})
        self.assertEqual(facade.get_hunt(hunt_id)["vector_ms"], before)


class TestTheHpFieldIsNotEditedByAccident(unittest.TestCase):
    """Typing an HP and clicking "Report turn" sometimes changed the HP instead of reporting.

    Two independent causes, both fixed, because there is no way to tell from the report which
    one fired and each is a real hazard:

    1. `huntAdviceLoad` ended with a full `renderHuntRun()`. Ranking takes seconds at a few
       thousand candidates, so that reply lands long after the page did -- by which time the
       player is answering the NEXT turn. It rebuilt the interview underneath them, destroying
       and recreating the HP input (losing the caret), and a re-render landing between mousedown
       and mouseup on the button swallowed the click entirely.
    2. The field was `type="number"`. A focused number input changes its own value on a scroll
       wheel, and the field sits directly above the Report button -- so scrolling down to reach
       the button silently edited the HP on the way past. Its spinner arrows are also easy to
       clip when aiming for the button.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_advice_panel_updates_in_place(self):
        self.assertIn("function huntAdvicePanel(", self.html)
        self.assertIn("function huntRefreshAdvice(", self.html)
        self.assertIn('<div id="hrAdvice">', self.html)

    def test_the_advice_load_no_longer_re_renders_the_page(self):
        body = self.html[self.html.index("async function huntAdviceLoad()"):]
        body = body[:body.index("\n}\n") + 3]
        self.assertNotIn("renderHuntRun()", body)
        self.assertEqual(body.count("huntRefreshAdvice()"), 2,
                         "both the loading state and the result should refresh in place")

    def test_it_still_falls_back_to_a_full_render_when_the_container_is_gone(self):
        """A finished run drops the advice panel entirely, so the refresh has nowhere to write
        and must not silently do nothing."""
        body = self.html[self.html.index("function huntRefreshAdvice()"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("else renderHuntRun();", body)

    def test_the_hp_field_is_not_a_number_input(self):
        field = self.html[self.html.index('id="hrHp"'):]
        field = field[:field.index(">")]
        self.assertNotIn('type="number"', field)
        self.assertIn('inputmode="numeric"', field)

    def test_it_keeps_the_numeric_keypad_without_the_wheel_hazard(self):
        field = self.html[self.html.index('id="hrHp"'):]
        field = field[:field.index(">")]
        self.assertIn('pattern="[0-9]*"', field)

    def test_non_digits_are_stripped_rather_than_reaching_the_token_builder(self):
        handler = self.html[self.html.index("function hrHpInput("):]
        handler = handler[:handler.index("\n}") + 2]
        self.assertIn("replace(/\\D+/g", handler)

    def test_stripping_preserves_the_caret(self):
        """Rewriting value sends the caret to the end, which transposes digits for anyone typing
        at speed -- the same class of problem as the re-render."""
        handler = self.html[self.html.index("function hrHpInput("):]
        handler = handler[:handler.index("\n}") + 2]
        self.assertIn("setSelectionRange", handler)

    def test_enter_in_the_hp_field_does_not_also_submit_a_form(self):
        field = self.html[self.html.index('id="hrHp"'):]
        field = field[:field.index(">")]
        self.assertIn("event.preventDefault()", field)


class TestFocusSurvivesARerender(unittest.TestCase):
    """Filling a stat and tabbing to the next field: the next field gained focus and then lost it.

    Every field on the hunt-configure page is `onchange` -> save -> re-render, and Tab fires the
    change on the field you LEFT. So the field you moved to was built, focused by the browser,
    and then destroyed a couple of awaits later when `mount` replaced innerHTML. Same class as
    the HP-field bug: an async reply re-rendering a region the player is working in.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_mount_restores_focus(self):
        body = self.html[self.html.index("function mount(html){"):]
        body = body[:body.index("\n}\n") + 3]
        self.assertIn("document.activeElement", body)
        self.assertIn("after.focus()", body)

    def test_it_keys_on_the_elements_own_id_rather_than_guessing(self):
        """So nothing is restored by position or index: no id, or no surviving element with that
        id, means focus is simply left alone."""
        body = self.html[self.html.index("function mount(html){"):]
        body = body[:body.index("\n}\n") + 3]
        self.assertIn("before.id ? before.id : null", body)
        self.assertIn("if (!after", body)

    def test_only_text_entry_controls_are_eligible(self):
        """Stealing focus back onto a button would change what Enter and Space do."""
        body = self.html[self.html.index("function mount(html){"):]
        body = body[:body.index("\n}\n") + 3]
        self.assertIn("/^(INPUT|SELECT|TEXTAREA)$/", body)

    def test_the_caret_is_preserved(self):
        """Refocusing without it sends the cursor to the end, which transposes digits for anyone
        typing at speed -- the same secondary problem the HP field had."""
        body = self.html[self.html.index("function mount(html){"):]
        body = body[:body.index("\n}\n") + 3]
        self.assertIn("selectionStart", body)
        self.assertIn("setSelectionRange", body)

    def test_the_caret_read_and_write_are_both_guarded(self):
        """`selectionStart` throws on number and date inputs in some engines, and the stat fields
        this was reported against are all type=number."""
        body = self.html[self.html.index("function mount(html){"):]
        body = body[:body.index("\n}\n") + 3]
        self.assertEqual(body.count("try {"), 2, body)

    def test_every_field_on_the_configure_page_has_an_id_to_key_on(self):
        """The fix is inert for a field without one, so this is the half that makes it work."""
        import re
        body = self.html[self.html.index("function renderHuntConfigure()"):]
        body = body[:body.index("\n}\n")]
        without = [attrs.strip()[:60] for tag, attrs in
                   re.findall(r"<(input|select)([^>]*)>", body) if "id=" not in attrs]
        self.assertEqual(without, [])

    def test_the_per_member_fields_key_their_ids_on_the_member(self):
        """A party row's id has to be stable across the re-render, and unique within it."""
        self.assertIn('id="hc-party-${p.id}"', self.html)
        self.assertIn('id="hc-held-${p.id}"', self.html)


class TestTheConfigureTabHasATimePicker(unittest.TestCase):
    """The set of initial times a key seed can be loaded at is fixed and small, so every other
    tool offers a picker rather than asking you to type one."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_button_is_there(self):
        self.assertIn("onclick=\"openTimePicker(${h.key_seed ?? \"null\"}, huntConfigurePickTime)\"",
                      self.html)

    def test_its_handler_saves_through_the_normal_path(self):
        body = self.html[self.html.index("function huntConfigurePickTime("):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('huntSetField("initial_time", t)', body)
        self.assertIn("closeModal()", body)

    def test_it_reuses_the_shared_picker(self):
        """Rather than a second implementation that could drift from `times_on_date`."""
        self.assertIn("function openTimePicker(keySeed, onPick){", self.html)

    def test_the_picker_handles_a_missing_key_seed_itself(self):
        """So the button needs no guard of its own -- openTimePicker toasts and returns."""
        body = self.html[self.html.index("function openTimePicker(keySeed, onPick){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("Set a key seed first.", body)


class TestAFreshlyAppliedStatusReachesTheOptions(unittest.TestCase):
    """Reported: using Spore on an awake Latias, "Latias remains asleep" was not offered as
    something Latias could have done -- when it is in fact the ONLY thing it could have done.

    The cause is a timing mismatch rather than a missing option. `prevention_options` is built
    from the state the turn OPENED in, where the target was still awake; the status our move
    applies lands between that and the target's half of the same turn. So the page has to add it,
    which is what `applies_status` on `move_info` is for.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_move_info_says_which_status_a_move_inflicts(self):
        from claytonlib.battle_compass.hunt_session import move_info

        facade, hunt_id = _ready_hunt()
        started = facade.hunt_session_start(hunt_id)
        session = facade._hunt_sessions.get(started["session_id"])
        state = next(iter(session._session.states.values()))
        info = {m["name"]: m for m in move_info(state.ours, state.target)}
        self.assertEqual(info["Spore"]["applies_status"], "slp")
        self.assertIsNone(info["False Swipe"]["applies_status"])
        self.assertIsNone(info["Mean Look"]["applies_status"])

    def test_an_empty_slot_still_carries_the_key(self):
        """The page reads it unconditionally, so a missing key would read as `undefined` and
        quietly disable the whole rule."""
        from claytonlib.battle_compass.hunt_session import move_info
        from claytonlib.battle_compass.state import Battler

        bare = Battler(name="X", level=5, types=("Normal",),
                       stats={"hp": 20, "atk": 5, "def": 5, "spa": 5, "spd": 5, "spe": 5},
                       moves=("",), pp=(0,))
        self.assertIn("applies_status", move_info(bare)[0])
        self.assertIn("flinch_secondary", move_info(bare)[0])

    def test_the_page_derives_it_from_our_answered_move(self):
        body = self.html[self.html.index("function hrStatusWeJustApplied(){"):]
        body = body[:body.index("\n}") + 2]
        # Exactly the four escapes the report names: we moved second, we never got the move off,
        # it went ahead and failed, or it missed.
        self.assertIn("if (!hrWeActFirst()) return null;", body)
        self.assertIn("t.ours.prevented", body)
        self.assertIn("info.guaranteed_fail", body)
        self.assertIn('t.ours.result === ""', body)

    def test_sleep_settles_the_targets_whole_turn(self):
        """Sleep lasts a minimum of two turns, so a target put to sleep before its own turn
        cannot act on it -- one answer, not a question."""
        body = self.html[self.html.index("function hrTargetBlocks(){"):]
        self.assertIn('hrStatusWeJustApplied() === "slp"', body)
        self.assertIn('t.target = {prevented: "slp"}', body)

    def test_paralysis_joins_the_options_instead_of_replacing_them(self):
        body = self.html[self.html.index("function hrTargetBlocks(){"):]
        self.assertIn('hrStatusWeJustApplied() === "par"', body)


class TestAnInvisibleFlinchIsNotAsked(unittest.TestCase):
    """Reported: the interview asked whether Zen Headbutt's extra effect procced on turns where
    Latias moved AFTER us. A flinch is announced on the victim's turn, so a flincher that moves
    second shows nothing -- the answer was a guess, and the `~` it produced then filtered the
    candidate set on it.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_move_info_flags_a_flinching_move(self):
        from claytonlib.battle_compass.hunt_session import move_info
        from claytonlib.battle_compass.state import Battler
        from claytonlib.moves import resolve_move

        b = Battler(name="Latias", level=40, types=("Psychic", "Dragon"),
                    stats={"hp": 120, "atk": 80, "def": 90, "spa": 110, "spd": 110, "spe": 110},
                    moves=("Zen Headbutt", "Mist Ball"),
                    pp=tuple(resolve_move(m).pp for m in ("Zen Headbutt", "Mist Ball")))
        info = {m["name"]: m for m in move_info(b)}
        self.assertTrue(info["Zen Headbutt"]["flinch_secondary"])
        self.assertTrue(info["Zen Headbutt"]["has_secondary"])
        # Mist Ball drops Sp. Atk, which the player SEES -- so it keeps its question.
        self.assertFalse(info["Mist Ball"]["flinch_secondary"])
        self.assertTrue(info["Mist Ball"]["has_secondary"])

    def test_neither_side_asks_the_question_for_one(self):
        for fn in ("function hrOurSecondaryBlock(){", "function hrTargetBlocks(){"):
            body = self.html[self.html.index(fn):]
            body = body[:body.index("\n}\n") + 3]
            self.assertIn("flinch_secondary", body, fn)

    def test_the_marker_is_deduced_from_the_victims_answer(self):
        body = self.html[self.html.index("function hrSecondaryMark(side){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('victim.prevented === "fln"', body)

    def test_an_unanswerable_question_cannot_hold_the_turn_open(self):
        """The informational note renders where the question was, so the gate had to stop
        keying on `secondary === undefined` or the turn would never become reportable."""
        self.assertIn("function hrOurSecondaryPending(){", self.html)
        self.assertIn("if (hrOurSecondaryPending()) return blocks.join", self.html)
        body = self.html[self.html.index("function hrOurSecondaryPending(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("!info.flinch_secondary", body)

    def test_a_bag_action_rules_the_flinch_out_on_its_own(self):
        """Reported: a switch turn still showed the `~`. An item, either ball, a switch or a
        Revive resolves BEFORE any move, so we have already had our turn and there is no move
        left to flinch -- and that is the reason, not the turn order those actions also force.
        Checked separately so it cannot regress if the two ever come apart."""
        body = self.html[self.html.index("function hrFlinchPossibleOnUs(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('!t.action.startsWith("M")', body)

    def test_the_marker_and_the_question_share_one_predicate(self):
        """So the page cannot emit a `~` for a flinch it never offered."""
        body = self.html[self.html.index("function hrSecondaryMark(side){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("hrFlinchPossibleOnTarget()", body)
        self.assertIn("hrFlinchPossibleOnUs()", body)
        self.assertIn("if (!possible) return \"\";", body)

    def test_the_flinch_option_needs_a_flinching_move_that_actually_landed(self):
        """`prevention_options` can only check the MOVESET, so "flinched" was on offer whenever
        the target held Zen Headbutt at all -- including turns it used something else."""
        for fn in ("function hrFlinchPossibleOnUs(){", "function hrFlinchPossibleOnTarget(){"):
            body = self.html[self.html.index(fn):]
            body = body[:body.index("\n}") + 2]
            self.assertIn("flinch_secondary", body, fn)
            self.assertIn("hrLanded(", body, fn)

    def test_the_skipped_question_still_says_why(self):
        self.assertIn("a flinch would never have shown", self.html)


class TestTheInterviewCanReportAFaint(unittest.TestCase):
    """A faint is a turn, not an ending, so the interview has to be able to say so: did we go
    down, who came in, and no HP token either way.

    The token stream is X<party slot> or XX, and the advance accounting behind it is measured
    in-game (notes/ss_rng/fainting.md).
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_faint_question_comes_before_the_hp_one(self):
        """Because it REPLACES it. `tokens.validate_turn` rejects a turn carrying both, so a
        page that asked for HP first would build an invalid report and then have to retract it.
        """
        faint = self.html.index("Did ${who.name} faint?")
        hp = self.html.index("'s HP now?")
        self.assertLess(faint, hp)

    def test_a_faint_turn_asks_for_no_hp(self):
        body = self.html[self.html.index("function hrNeedsHp(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("if (hrFainted()) return false;", body)

    def test_it_asks_who_came_in_and_offers_only_the_standing(self):
        self.assertIn("Who did you send out?", self.html)
        body = self.html[self.html.index("function hrHealthyBench(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("!b.fainted", body)

    def test_a_switch_then_a_faint_offers_the_pokemon_that_just_left(self):
        """A switch resolves before any move, so by the time the replacement is chosen the
        Pokemon we switched TO is the one that went down and the one it replaced is available
        again. A bench index from the pre-turn snapshot would name the wrong Pokemon."""
        body = self.html[self.html.index("function hrHealthyBench(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('t.action !== "S"', body)
        self.assertIn("outgoing", body)

    def test_the_replacement_travels_as_a_party_slot(self):
        body = self.html[self.html.index("function hrFaintToken(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("b.party_slot === t.replacement", body)

    def test_a_wipe_needs_no_replacement_and_says_so(self):
        body = self.html[self.html.index("function hrFaintToken(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('return "XX"', body)
        self.assertIn("Nothing left to send out", self.html)

    def test_the_token_names_the_stable_party_slot(self):
        """Not the bench position: HGSS never reorders a party, so the number the player reads
        in-game is the number the token has to carry."""
        body = self.html[self.html.index("function hrFaintToken(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('"X" + chosen.party_slot', body)

    def test_an_unanswered_faint_question_is_not_a_no(self):
        body = self.html[self.html.index("function hrTurnComplete(){"):]
        body = body[:body.index("\n  return true;\n}") + 17]
        self.assertIn("t.fainted === undefined) return false", body)
        self.assertIn("hrFaintToken() === null) return false", body)

    def test_fainted_before_moving_is_an_action_gated_on_turn_order(self):
        """Offered only when the target could lead -- by Speed, by its own priority move, or by
        ours being slower-bracket. If we always move first it cannot have happened."""
        self.assertIn('s.legal_actions.includes("X")', self.html)
        self.assertIn("fainted before moving", self.html)

    def test_reporting_it_skips_our_half_of_the_turn_entirely(self):
        """The move we picked never executed, so there is no outcome to report and no PP spent --
        which is why the token stream need not say which move it was."""
        body = self.html[self.html.index("function hrTokens(){"):]
        self.assertIn('if (t.action === "X"){', body)
        interview = self.html[self.html.index("function hrInterview(){"):]
        self.assertIn('if (hrWeActFirst() && t.action !== "X"){', interview)

    def test_its_turn_order_matches_the_simulator(self):
        """Saying we were fainted before moving IS saying the target went first."""
        body = self.html[self.html.index("function hrWeActFirst(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('if (t.action === "X") return false;', body)

    def test_a_ko_hides_the_attackers_secondary_effect(self):
        """Verified: the roll is spent, the outcome is never shown. Asking anyway would filter
        the candidate set on something the player could not have seen."""
        body = self.html[self.html.index("function hrSecondaryMark(side){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('if (side === "target" && hrFainted()) return "";', body)

    def test_the_replacement_reaches_the_facade(self):
        import inspect

        from app.facade import Facade

        body = self.html[self.html.index("function huntRunObserve(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("t.replacement", body)
        # Same name on both sides of the bridge, or the keyword silently goes nowhere.
        self.assertIn("replacement",
                      inspect.signature(Facade.hunt_session_observe).parameters)


class TestTheInterviewCanReportARevive(unittest.TestCase):
    """The one bag item used on somebody who is NOT out, which is why it carries a party slot."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_it_is_offered_only_while_somebody_is_down(self):
        self.assertIn('s.legal_actions.includes("R")', self.html)

    def test_it_asks_who_and_offers_only_the_fainted(self):
        self.assertIn("Revived who?", self.html)
        start = self.html.index('} else if (t.action === "R"){')
        body = self.html[start + 1:]
        body = body[:body.index("} else if")]
        self.assertIn("b.fainted", body)

    def test_it_renders_the_stable_party_slot(self):
        body = self.html[self.html.index("function hrTokens(){"):]
        self.assertIn('(t.action === "S" ? "S" : "R") + member.party_slot', body)

    def test_the_session_prices_it(self):
        from claytonlib.battle_compass import items

        facade, hunt_id = _ready_hunt()
        started = facade.hunt_session_start(hunt_id)
        snap = started["snapshot"]
        self.assertEqual(snap["revive_price"], items.REVIVE_PRICE)

    def test_it_is_not_offered_among_the_potions(self):
        """Every entry in `items` is used on whoever is out; a Revive is not."""
        facade, hunt_id = _ready_hunt()
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertNotIn("rev", {i["code"] for i in snap["items"]})


class TestPartySlotsReachThePage(unittest.TestCase):
    """clayton-0w3.1: the S token's digit used to be a position in a shifting bench, so
    switching out and back emitted the same number twice."""

    def test_the_bench_carries_both_numbers(self):
        """`slot` is the bench index every call back into the session takes; `party_slot` is what
        the player sees and what the tokens name. They stop agreeing after the first switch."""
        facade, hunt_id = _ready_hunt()
        profile_id = facade.list_profiles()[0]["id"]
        second = facade.add_party_pokemon(profile_id, dict(LEAD, name="Magneton"))["pokemon_id"]
        hunt = facade.get_hunt(hunt_id)
        lead = hunt["party"][0]
        hunt["party"] = [lead, {"pokemon_id": second, "held_item": ""}]
        facade.save_hunt(hunt)
        snap = facade.hunt_session_start(hunt_id)["snapshot"]
        self.assertEqual(snap["ours_party_slot"], 1)
        self.assertEqual([(b["slot"], b["party_slot"]) for b in snap["bench"]], [(0, 2)])

    def test_the_page_reads_the_party_slot_for_a_switch(self):
        html = INDEX.read_text()
        body = html[html.index("function hrTokens(){"):]
        self.assertIn("member.party_slot", body)
        self.assertNotIn('parts.push("S" + (t.ours.bench + 2))', body)
