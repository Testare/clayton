"""Static checks on app/web/index.html.

The front end reaches Python through ``window.pywebview.api``, which is populated by
reflection: a name that isn't a bound method on the Facade is simply absent, and calling it
fails at runtime in the browser with nothing logged on the Python side.  Nothing else in the
suite would catch a typo or a rename, so these two checks do.
"""
import re
import shutil
import subprocess
import tempfile
import pathlib
import re
import unittest
from pathlib import Path

from app.facade import Facade

_INDEX = Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"
_HTML = _INDEX.read_text()


def _function_body(name: str) -> str:
    """Source of one top-level JS function, for assertions scoped to it.

    Matching against the whole 4,000-line file both risks false positives and produces
    unreadable failures, since assertIn puts the entire haystack in the message.
    """
    start = _HTML.index(f"function {name}(")
    depth, i = 0, _HTML.index("{", start)
    for j in range(i, len(_HTML)):
        if _HTML[j] == "{":
            depth += 1
        elif _HTML[j] == "}":
            depth -= 1
            if depth == 0:
                return _HTML[start:j + 1]
    raise AssertionError(f"unbalanced body for {name}")
# api("method_name", ...) — the only way the UI calls Python.
_API_CALLS = re.compile(r'\bapi\(\s*"([A-Za-z_][A-Za-z0-9_]*)"')


class TestApiCallsResolve(unittest.TestCase):
    def test_every_api_call_names_a_real_facade_method(self):
        facade_methods = {name for name in dir(Facade) if not name.startswith("_")}
        called = set(_API_CALLS.findall(_HTML))
        self.assertTrue(called, "no api() calls found — has the call shape changed?")
        missing = sorted(called - facade_methods)
        self.assertEqual(
            missing, [],
            "index.html calls Facade methods that do not exist. pywebview drops unknown "
            "names silently, so this would fail only in the browser:\n  "
            + "\n  ".join(missing))

    def test_battle_compass_methods_are_actually_wired_up(self):
        """Guards against the Hunts UI being added without its facade calls, or vice versa."""
        called = set(_API_CALLS.findall(_HTML))
        for method in ("list_hunts", "get_hunt", "create_hunt", "save_hunt", "delete_hunt",
                       "set_hunt_completed", "hunt_readiness",
                       "add_party_pokemon", "update_party_pokemon", "remove_party_pokemon"):
            self.assertIn(method, called, f"{method} is never called from the UI")

    def test_glass_methods_are_actually_wired_up(self):
        """Same guard as Battle Compass: the Glass UI and its facade surface move together."""
        called = set(_API_CALLS.findall(_HTML))
        for method in ("list_seeds", "get_seed", "create_seed", "save_seed", "delete_seed",
                       "seed_readout", "seed_save_seed_a_defaults", "seed_add_history",
                       "seed_clear_history"):
            self.assertIn(method, called, f"{method} is never called from the UI")

    def test_glass_reuses_the_shared_seed_a_and_frame_calls(self):
        """Glass is thin on purpose: identifying Seed A and routing to a frame are the calls
        the other compasses already make, not new ones (notes/glass.md)."""
        for fn, call in (("glassGenerateSeedA", "metronome_seed_a"),
                         ("glassGenerateSeedA", "metronome_key_seed_info"),
                         ("glassIdentifyFrame", "safari_compass_identify_frame"),
                         ("glassPlanRoute", "safari_compass_plan_frame")):
            self.assertIn(f'api("{call}"', _function_body(fn),
                          f"{fn} should reach {call}")

    def test_glass_wires_up_the_platinum_seed_a_surface(self):
        """Platinum identifies Seed A from coin flips, and routes with a pitch margin."""
        called = set(_API_CALLS.findall(_HTML))
        for method in ("list_games", "platinum_seed_a", "platinum_key_seed_info",
                       "platinum_plan_frame"):
            self.assertIn(method, called, f"{method} is never called from the UI")

    def test_the_player_is_never_asked_to_report_a_pitch(self):
        """A pitch is output, not input (clayton-6xu.5).

        The player knows their advance frame by arithmetic -- they load on frame 0 and count what
        they do -- so the pitch margin is an error CHECK on a number they already have. An
        earlier version of Glass asked them to type pitches in and derived the frame from them,
        which is measuring something already known. There is no facade call for it and no control
        that accepts one.
        """
        called = set(_API_CALLS.findall(_HTML))
        self.assertNotIn("platinum_identify_frame", called)
        panel = _function_body("renderGlassPlatinumRoute")
        self.assertNotIn("gl-frame-elm-new", panel)
        # The only input in the Platinum panel is where to go.
        self.assertEqual(panel.count("<input"), 1)
        self.assertIn("gl-routeto", panel)

    def test_the_platinum_panel_states_the_frame_rather_than_asking_for_it(self):
        panel = _function_body("renderGlassPlatinumRoute")
        self.assertIn("You are on advance frame", panel)
        for gone in ("Apply", "Re-pin", "keep listening"):
            self.assertNotIn(gone, panel, f"the Platinum panel should not offer {gone!r}")

    def test_glass_picks_its_seed_a_signal_from_the_descriptor_not_the_game_name(self):
        """One predicate, asked of the descriptor the facade builds. Branching on the game name
        in each renderer is how a two-game fork becomes a five-game mess."""
        body = _function_body("glassIsPlatinum")
        self.assertIn("flips_pitch", body)
        for renderer in ("renderGlassSeedA", "renderGlassFrame", "glassRouteHtml"):  # noqa
            text = _function_body(renderer)
            self.assertIn("glassIsPlatinum", text, f"{renderer} should ask the predicate")
            self.assertNotIn("Platinum\"", text,
                             f"{renderer} should not branch on the game's NAME")

    def test_glass_keeps_both_games_on_one_route_renderer(self):
        """The two plans are the same arithmetic with different nouns (a blind 2-advance bulk
        action, then a readable 1-advance margin), so one renderer reads either payload."""
        body = _function_body("glassRouteHtml")
        for key in ("journal_flips", "cries_before_target", "chatot_flips", "elm_before_scent"):
            self.assertIn(key, body, f"glassRouteHtml should read {key}")

    def test_the_elm_identification_path_is_hgss_only(self):
        """Appending heard calls and identifying from them is HGSS machinery. Platinum returns
        from renderGlassFrame before reaching it, and glassIdentifyFrame has no Platinum branch
        left to take."""
        self.assertNotIn("glassIsPlatinum", _function_body("glassAppendFrameElm"))
        self.assertNotIn("platinum", _function_body("glassIdentifyFrame"))
        self.assertIn("renderGlassPlatinumRoute", _function_body("renderGlassFrame"))

    def test_glass_surfaces_the_platinum_hygiene_note(self):
        """A randomly-moving NPC spends an advance of its own and the in-game menu freezes them.
        It is the one instruction a player cannot recover from forgetting, so the page must show
        it rather than leaving it in the notes -- and now that the frame is counted rather than
        measured, an NPC stealing an advance is the error the pitch margin has to catch."""
        self.assertIn("hygiene_note", _function_body("renderGlassPlatinumRoute"))

    def test_glass_never_tells_the_player_to_sweet_scent(self):
        """A Seed in Glass has no encounter method, so the route guide carries no verb: the
        facade's `method` only chooses between Sweet Scent and casting a rod."""
        body = _function_body("glassRouteHtml") + _function_body("glassPlanRoute")
        for verb in ("Sweet Scent", "cast the", "method:"):
            self.assertNotIn(verb, body, f"the Glass route guide mentions {verb!r}")

    def test_glass_answers_a_backwards_route_before_the_facade_does(self):
        """plan_advances' own overshoot message ends in "Sweet Scent", so the page catches the
        case first -- the ordinary mistake deserves the better message anyway."""
        body = _function_body("glassPlanRoute")
        self.assertIn("< _glass.pinnedFrame", body)
        self.assertIn("behind you", body)

    def test_the_time_picker_asks_for_a_year_only_where_it_matters(self):
        """Glass shows an absolute delay, which moves with the year; nothing else does, so no
        other caller may grow a field with no consequence."""
        opens = re.findall(r"openTimePicker\(([^;]*?)\)", _HTML)
        with_year = [call for call in opens if "year" in call]
        self.assertEqual(len(with_year), 1, f"expected exactly one year-mode picker: {with_year}")
        self.assertIn("glassPickTime", with_year[0])

    def test_the_metronome_area_reaches_both_owner_kinds_through_the_facade(self):
        called = set(_API_CALLS.findall(_HTML))
        for method in ("get_hunt", "save_hunt", "get_expedition", "save_expedition"):
            self.assertIn(method, called, f"{method} is never called from the UI")


class TestScriptSyntax(unittest.TestCase):
    """Parse the inline script, so a malformed edit fails here rather than in the browser."""

    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_inline_script_parses(self):
        match = re.search(r"<script>\n(.*)</script>", _HTML, re.S)
        self.assertIsNotNone(match, "no inline <script> block found")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(match.group(1))
            path = handle.name
        result = subprocess.run([shutil.which("node"), "--check", path],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestHuntNavigation(unittest.TestCase):
    """A hunt needs a landing page and a configure page, like an expedition — and it needs
    Metronome Compass, because calibration belongs to the profile rather than to one quest."""

    def test_hunt_has_both_a_landing_and_a_configure_screen(self):
        for fn in ("renderHuntHome", "renderHuntConfigure", "huntConfigure", "openHuntHome"):
            self.assertTrue(f"function {fn}" in _HTML, f"{fn} is missing")

    def test_metronome_tools_are_reachable_from_a_hunt(self):
        body = _function_body("renderHuntHome")
        for handler in ("metronomeNewRun", "metronomeReviewData"):
            self.assertTrue(handler in body,
                            f"{handler} is not offered on the hunt landing page")
        self.assertTrue("'hunt'" in body,
                        "the hunt tools grid does not pass 'hunt' as the owner kind")

    def test_the_expedition_tools_grid_passes_a_bare_id_to_every_handler(self):
        """The regression this guards against: that grid is shared by Metronome Compass, Safari
        Chart and Safari Compass, so injecting an owner kind for the metronome pair's benefit
        handed 'expedition' to chartFindTarget as its expedition id and broke both Safari tools.
        The metronome handlers tolerate a bare id instead (see asOwner)."""
        body = _function_body("openExpeditionHome")
        self.assertIn("${handler}('${esc(id)}')", body,
                      "the shared tools grid must pass only the expedition id")
        self.assertNotIn("'expedition','", body,
                         "the shared grid is injecting an owner kind again")

    def test_the_configure_form_asks_for_an_encounter_method(self):
        """clayton-858: surf and the rods. The method field must come BEFORE the area, since
        it narrows which areas can appear at all (a Lapras is Rocky Beach surf and nothing
        else), and it must reach both the area list and the saved document."""
        body = _function_body("expeditionForm")
        self.assertLess(body.index('name="safari_method"'), body.index('name="safari_area"'),
                        "the method must be asked before the area it narrows")
        self.assertIn('onchange="onExpeditionMethodChange()"', body)
        save = _function_body("saveExpedition")
        for field in ("safari_method", "fishing_happiness_bonus", "fishing_suction_cups"):
            self.assertIn(field, save, f"{field} is never saved")

    def test_the_rod_only_fields_are_hidden_until_a_rod_is_chosen(self):
        self.assertIn('id="exp-fishing-fields" style="display:none"', _HTML)
        body = _function_body("syncExpeditionAreas")
        self.assertIn('isRodMethod(method) ? "" : "none"', body)

    def test_the_frame_guide_never_hardcodes_sweet_scent(self):
        """The verb follows the method: a rod is cast, not scented. Both the one-line summary
        and the Elm-margin guide render the plan's own action."""
        body = _function_body("renderFrameGuideSection")
        self.assertEqual(body.count('g.action || "Sweet Scent"'), 2)

    def test_the_compass_passes_the_method_to_both_facade_calls(self):
        for fn in ("sacFindTargetFrame", "sacPlanFrameRoute"):
            self.assertIn('method: sac.e.safari_method || "grass"', _function_body(fn),
                          f"{fn} doesn't tell the back end which method this expedition uses")
        search = _function_body("sacFindTargetFrame")
        self.assertIn("happiness_bonus: sac.e.fishing_happiness_bonus", search)
        self.assertIn("suction_cups: !!sac.e.fishing_suction_cups", search)

    def test_safari_tools_are_never_handed_an_owner_kind(self):
        """They are expedition-only concepts and take an id, not an owner."""
        for handler in ("chartFindTarget", "chartManageData",
                        "safariCompassNewRun", "safariReviewData"):
            self.assertNotIn(f"{handler}('expedition'", _HTML,
                             f"{handler} is being called with an owner kind")
            self.assertNotIn(f"{handler}('hunt'", _HTML,
                             f"{handler} is being called with an owner kind")

    def test_owner_resolution_accepts_a_bare_id_an_explicit_pair_and_an_object(self):
        """All three shapes are in use: the shared grid passes a bare id, the hunt page passes
        (kind, id), and internal re-entry passes the owner it already has."""
        body = _function_body("asOwner")
        self.assertIn('typeof kind === "object"', body)
        self.assertIn("id === undefined", body)
        self.assertIn('"expedition"', body)

    def test_the_metronome_tools_take_an_owner_rather_than_an_expedition_id(self):
        """Generalised so one implementation serves both; the owner decides where back goes."""
        for fn in ("ownerHome", "ownerLabel", "loadOwner", "saveOwner"):
            self.assertTrue(f"function {fn}" in _HTML, f"{fn} is missing")

    def test_no_hardcoded_expedition_save_remains_in_the_metronome_area(self):
        self.assertFalse('api("save_expedition", {...nr.e' in _HTML,
                         "a metronome default-save still assumes an expedition")

    def test_the_hunt_ui_does_not_ask_for_a_calibration_model(self):
        """It is profile-scoped and always seeded, so asking would be an unreachable blocker."""
        self.assertFalse("calibration_model_id" in _HTML,
                         "the UI still references a per-hunt calibration model")


class TestMarkupReferences(unittest.TestCase):
    """CSS classes used by the markup have to exist, or a panel renders unstyled."""

    def test_grid_and_panel_classes_used_are_defined(self):
        defined = set(re.findall(r"^\s*\.([a-z][a-z0-9-]*)\s*[,{]", _HTML, re.M))
        defined |= set(re.findall(r"\.([a-z][a-z0-9-]*)\{", _HTML))
        for used in ("grid2", "grid3", "grid4", "grid6", "panel", "panel-tight", "row-list",
                     "empty", "section-label", "notice", "badge", "hint", "actions", "field",
                     "tools", "tool-cat"):
            self.assertIn(used, defined, f".{used} is used but never defined")

    def test_nav_buttons_have_a_matching_branch_in_setview(self):
        views = set(re.findall(r'data-view="([a-z]+)"', _HTML))
        handled = set(re.findall(r'view === "([a-z]+)"', _HTML))
        self.assertEqual(views - handled, set(),
                         "a nav button has no setView branch, so it would do nothing")


class TestNoUndeclaredIdentifiers(unittest.TestCase):
    """Catches the whole class of "X is not defined" errors at the first render.

    A real one shipped: an edit script that added module state, its loader functions AND their
    call sites hit an assertion partway through and wrote nothing, but a later script re-applied
    only the call sites. The page referenced `_huntAdvice` with no declaration anywhere and threw
    the moment a run started. The checks in place then only verified `onclick=` handler names, so
    nothing noticed.
    """

    HTML = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

    def setUp(self):
        self.src = self.HTML.read_text()
        self.script = self.src.split("</style>", 1)[-1]

    def _declared(self):
        """Every name the page declares: let/const/var, function, and function parameters."""
        names = set()
        names |= set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)", self.script))
        for kw in ("let", "const", "var"):
            # `let a = 1, b = 2;` -- take every name in the declaration list. No \b before the
            # name: `$` is not a word character, so \b would skip `const $ = ...`.
            for decl in re.findall(rf"(?<![\w$]){kw}\s+([^;\n]*)", self.script):
                names |= set(re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*(?==|,|$|\))",
                                        decl))
        names |= set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*=>", self.script))
        names |= set(re.findall(r"\bfunction\s*\(([^)]*)\)", self.script) and [] or [])
        # Parameters of every function, since they are in scope inside it.
        for params in re.findall(r"function[^(]*\(([^)]*)\)", self.script):
            names |= set(re.findall(r"[A-Za-z_$][\w$]*", params))
        for params in re.findall(r"\(([^)]*)\)\s*=>", self.script):
            names |= set(re.findall(r"[A-Za-z_$][\w$]*", params))
        # catch(e), for(const x of ...), destructuring.
        names |= set(re.findall(r"catch\s*\(\s*([A-Za-z_$][\w$]*)", self.script))
        return names

    def test_every_underscore_module_variable_is_declared(self):
        """Project convention: module-level state is `_`-prefixed. Those are exactly the names a
        partially-applied edit leaves dangling, and they are unambiguous to scan for."""
        declared = self._declared()
        # Not preceded by `.` (a property access) and not followed by `:` (an object-literal
        # key) -- neither is a variable reference.
        used = set(re.findall(r"(?<![\w.$])(_[A-Za-z][\w$]*)\s*(?!:)", self.script))
        used = {n for n in used
                if re.search(rf"(?<![\w.$]){re.escape(n)}\s*(?![\w$:])", self.script)}
        undeclared = sorted(n for n in used if n not in declared)
        self.assertEqual(undeclared, [],
                         f"referenced but never declared: {undeclared}")

    def test_the_check_would_notice_a_missing_declaration(self):
        """Proves the scan has teeth rather than passing vacuously."""
        declared = self._declared()
        self.assertIn("_huntAdvice", declared)
        self.assertNotIn("_huntAdviceThatDoesNotExist", declared)

    def test_every_handler_the_markup_calls_is_defined(self):
        """Inline handlers run in global scope, so a typo here is a runtime error too."""
        declared = self._declared()
        called = set()
        for attr in ("onclick", "onchange", "oninput", "onkeydown", "onsubmit"):
            for body in re.findall(rf'{attr}="([^"]*)"', self.src):
                called |= set(re.findall(r"(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(", body))
        browser = {"return", "if", "event", "true", "false", "Number", "String", "alert",
                   "confirm", "parseInt", "parseFloat", "this"}
        missing = sorted(n for n in called if n not in declared and n not in browser)
        self.assertEqual(missing, [], f"markup calls undefined: {missing}")


class TestMidTurnStatusIsSymmetric(unittest.TestCase):
    """A status landed by whoever moved FIRST is live before the other half of the same turn.

    The page already added the option for a status WE landed; the mirror -- one the TARGET landed
    on us -- was missing, which left two turns unreportable: Darkrai's Hypnosis (our move simply
    does not happen) and Latios's Dragon Breath paralysis, which has been a configured target all
    along (clayton-6xu.3.3).
    """

    def test_both_directions_exist(self):
        self.assertIn("function hrStatusWeJustApplied", _HTML)
        self.assertIn("function hrStatusTargetJustApplied", _HTML)

    def test_it_reads_the_targets_reported_move_not_the_opening_state(self):
        body = _function_body("hrStatusTargetJustApplied")
        self.assertIn("hrTargetMoveInfo()", body)
        self.assertIn("applies_status", body)
        self.assertIn("secondary_status", body)

    def test_it_only_applies_when_the_target_moved_first(self):
        """Our half is already over otherwise, so the status cannot have stopped it."""
        body = _function_body("hrStatusTargetJustApplied")
        self.assertIn("hrWeActFirst()", body)

    def test_a_landed_hypnosis_short_circuits_our_half_of_the_turn(self):
        body = _function_body("hrOurOutcomeBlock")
        self.assertIn('hrStatusTargetJustApplied() === "slp"', body)
        self.assertIn("fell asleep before its turn", body)

    def test_paralysis_joins_the_options_rather_than_replacing_them(self):
        """It only MIGHT stop the move, unlike sleep -- the same asymmetry the target side
        already makes."""
        body = _function_body("hrOurOutcomeBlock")
        self.assertIn('hrStatusTargetJustApplied() === "par"', body)
        self.assertIn("was fully paralyzed", body)


class TestTheVanishedTargetIsExplained(unittest.TestCase):
    """Shadow Force's charge turn: nothing we do can reach Giratina that turn.

    Worth a line on the page rather than leaving it to be inferred -- four moves missing in a row
    with no explanation reads as a broken tool. And it is a MISS, not a prevention: the move
    happened and spent its rolls, so it cannot ride on `guaranteed_fail`, which renders as a bare
    slot token (clayton-6xu.3.4).
    """

    def test_our_outcome_block_short_circuits_on_a_vanished_target(self):
        body = _function_body("hrOurOutcomeBlock")
        self.assertIn("s.target.vanished", body)
        self.assertIn("is away", body)

    def test_it_records_a_miss_rather_than_a_prevention(self):
        body = _function_body("hrOurOutcomeBlock")
        vanished = body[body.index("s.target.vanished"):]
        self.assertIn('result: "-"', vanished[:400])


if __name__ == "__main__":
    unittest.main()


class TestTheTauntRefusalIsOfferedAndSettled(unittest.TestCase):
    """The turn a Taunt lands, the target's already-selected status move is refused by name.

    It needs its own handling in the page for the same reason a mid-turn status does -- the
    snapshot's flags describe the state the turn OPENED in, when nothing was taunted -- but the
    opposite treatment: a status only MIGHT stop the move, while the Taunt refusal has no roll
    behind it at all, so it is stated rather than asked (clayton-6xu.7.6).
    """

    def test_the_predicate_exists_and_reads_our_reported_move(self):
        self.assertIn("function hrTauntWeJustApplied", _HTML)
        body = _function_body("hrTauntWeJustApplied")
        self.assertIn("hrOurMoveInfo()", body)
        self.assertIn("applies_taunt", body)

    def test_it_only_applies_when_we_moved_first(self):
        """Otherwise the target's turn is over before the Taunt exists."""
        self.assertIn("hrWeActFirst()", _function_body("hrTauntWeJustApplied"))

    def test_a_missed_or_failed_taunt_does_not_count(self):
        body = _function_body("hrTauntWeJustApplied")
        self.assertIn("guaranteed_fail", body)
        self.assertIn('t.ours.result === ""', body)

    def test_the_refusal_test_is_the_roms_power_test_not_the_category(self):
        """`taunt_refusable` is published as `not move.power`, which is what
        CHECK_STATUS_STATE_TAUNT tests."""
        self.assertIn("taunt_refusable", _function_body("hrTauntRefuses"))

    def test_the_move_chip_says_the_move_will_be_blocked(self):
        """The player saw "The wild UXIE can't use Amnesia after the taunt!", so the move is on
        offer -- it was selected -- and the chip has to say what became of it."""
        body = _function_body("hrTargetBlocks")
        self.assertIn("hrTauntRefuses(m)", body)
        self.assertIn("blocked by the taunt", body)

    def test_the_outcome_is_settled_rather_than_asked(self):
        """One possible answer, so asking invites a guess at a different one."""
        body = _function_body("hrTargetBlocks")
        self.assertIn("hrTauntRefuses(info)", body)
        self.assertIn("after the taunt", body)

    def test_the_token_keeps_the_slot(self):
        """The one prevention that does, because the game named the move -- so the result rides
        in the move detail where `hrTokens` already concatenates it, not in `prevented`."""
        body = _function_body("hrTargetBlocks")
        self.assertIn('result: "tnt"', body)
        self.assertNotIn("prevented:'tnt'", body)
        self.assertNotIn('prevented: "tnt"', body)

    def test_the_marker_matches_the_python_grammar(self):
        """A marker the two sides spell differently renders a token no candidate can match."""
        from claytonlib.battle_compass.tokens import TAUNTED
        self.assertEqual(TAUNTED, "tnt")
        self.assertIn(f'result: "{TAUNTED}"', _function_body("hrTargetBlocks"))

    def test_a_refused_turn_needs_no_hp(self):
        """`hrNeedsHp` keys on the hit markers, and a refused move dealt no damage -- so this is
        really a check that `tnt` contains neither of them, which is what would otherwise make
        the page demand an HP number for a turn that had none."""
        from claytonlib.battle_compass.tokens import CRIT, HIT, TAUNTED
        self.assertNotIn(HIT, TAUNTED)
        self.assertNotIn(CRIT, TAUNTED)


class TestTheMoveInfoFlagsTheInterviewNeedsArePublished(unittest.TestCase):
    """A flag the page reads and `move_info` does not publish is `undefined`, so the branch
    reading it is silently dead -- which is how an interview quietly stops offering an outcome.
    Scoped to the interview's own block builders, because `info` and `m` name other things
    elsewhere on the page."""

    #: The functions that are handed a `move_info` entry.
    CONSUMERS = ("hrTargetBlocks", "hrOurOutcomeBlock", "hrTauntRefuses", "hrTauntWeJustApplied",
                 "hrStatusWeJustApplied", "hrStatusTargetJustApplied", "hrSecondaryMark",
                 "hrTargetCanMiss")

    def _published(self) -> set:
        import inspect

        from claytonlib.battle_compass import hunt_session

        return set(re.findall(r'"([a-z_]+)":', inspect.getsource(hunt_session.move_info)))

    def test_every_flag_the_interview_reads_is_published(self):
        published = self._published()
        for name in self.CONSUMERS:
            body = _function_body(name)
            read = set(re.findall(r"\binfo\.([a-z_]+)\b", body))
            with self.subTest(name):
                self.assertEqual(sorted(read - published), [],
                                 f"{name} reads flags move_info does not publish")

    def test_the_two_taunt_flags_are_among_them(self):
        self.assertLessEqual({"taunt_refusable", "applies_taunt"}, self._published())

    def test_the_check_would_notice_a_missing_flag(self):
        """Otherwise the subTest loop above could be passing on an empty read set."""
        body = _function_body("hrTauntWeJustApplied")
        self.assertIn("applies_taunt", set(re.findall(r"\binfo\.([a-z_]+)\b", body)))


class TestTheTauntRefusalIsTestedBeforeTheOtherOutcomes(unittest.TestCase):
    """Order inside `hrTargetBlocks`, which is the fix rather than a tidy-up -- the same kind of
    ordering the `guaranteed_fail`-before-`damaging` comment already pins.

    A refused move never executes, so the refusal dominates both branches that describe how a
    move WENT: `guaranteed_fail` (it ran and did nothing) and `damaging` (it hit us). Asked the
    other way round, Yawn against an Insomnia holder -- which is guaranteed to fail and is also
    refused -- would offer "It failed" for a turn whose only rendering is `E2tnt`.
    """

    def test_the_refusal_short_circuits_before_guaranteed_fail(self):
        body = _function_body("hrTargetBlocks")
        outcome = body[body.index("const base = `{slot:"):]
        self.assertLess(outcome.index("hrTauntRefuses(info)"),
                        outcome.index("info.guaranteed_fail"))

    def test_the_refusal_short_circuits_before_damaging(self):
        body = _function_body("hrTargetBlocks")
        outcome = body[body.index("const base = `{slot:"):]
        self.assertLess(outcome.index("hrTauntRefuses(info)"), outcome.index("info.damaging"))

    def test_it_returns_rather_than_falling_through(self):
        """Otherwise the secondary and Static questions would still be asked about a move that
        never happened."""
        body = _function_body("hrTargetBlocks")
        refusal = body[body.index("hrTauntRefuses(info)"):]
        self.assertIn("return {blocks: out, done: true}", refusal[:600])

    def test_the_player_is_steered_to_the_move_rather_than_a_prevention(self):
        """The refusal reads like a prevention, and picking one would discard the slot."""
        body = _function_body("hrTargetBlocks")
        steer = body[body.index("hrTauntWeJustApplied()"):]
        self.assertIn("pick", steer[:600])
        self.assertIn("was fully paralyzed", steer[:600])

    def test_the_steer_comes_before_the_outcome_question(self):
        body = _function_body("hrTargetBlocks")
        self.assertLess(body.index("hrTauntWeJustApplied()"), body.index("hrTauntRefuses(info)"))


class TestTheCaptureBallPickerIsAlwaysPopulated(unittest.TestCase):
    """The picker came up empty on a Platinum hunt, and the cause was not Platinum.

    `huntConfigure` fetched the ball list inside its `_hunt.id !== id` guard, and `openHuntHome`
    loads the same hunt WITHOUT the ball list -- so Hunt home -> Configure skipped the fetch
    entirely and `_huntBalls` stayed null, leaving the Capture ball select with nothing in it but
    its own placeholder. It only looked game-specific because the global survives between
    screens: a session that had been through the Hunts list already had a list cached, and a
    brand-new Platinum profile had not.

    Keying the cache on the PROFILE fixes the other half too -- an HGSS hunt's apricorn balls
    surviving into a Platinum hunt's picker.
    """

    def test_the_fetch_is_outside_the_hunt_identity_guard(self):
        body = _function_body("huntConfigure")
        guard = body.index('_hunt.id !== id')
        closing = body.index("}", body.index('get_profile'))
        self.assertGreater(body.index('"list_balls"'), closing,
                           "the ball fetch is back inside the hunt-id guard")
        self.assertLess(guard, body.index('"list_balls"'))

    def test_the_cache_is_keyed_on_the_profile(self):
        body = _function_body("huntConfigure")
        self.assertIn("_huntBallsFor !== _hunt.profile_id", body)
        self.assertIn("_huntBallsFor = _hunt.profile_id", body)

    def test_the_key_is_declared(self):
        self.assertIn("let _huntBallsFor", _HTML)

    def test_a_null_list_is_refetched(self):
        """Not merely a profile mismatch: the first visit has no list at all, and "" === "" would
        otherwise look like a hit."""
        self.assertIn("_huntBalls === null", _function_body("huntConfigure"))

    def test_open_hunt_home_still_does_not_fetch_balls(self):
        """It has no picker, so the fix belongs in huntConfigure rather than in both -- but if
        that ever changes, this is the test that says the two were meant to differ."""
        self.assertNotIn('"list_balls"', _function_body("openHuntHome"))

    def test_the_picker_keeps_rendering_a_stored_choice(self):
        """The old behaviour that must survive: a ball absent from this game still appears,
        selected, so a stored choice is never silently dropped."""
        body = _function_body("huntBallOptions")
        self.assertIn("names.unshift(chosen)", body)


class TestTheCoinFlipBoxesUpperCaseAsYouType(unittest.TestCase):
    """Cosmetic, deliberately: `coin_flips.clean_flips` upper-cases before matching, so a
    lowercase "htth" already narrows correctly. The box should still read the way it means."""

    def test_both_flip_inputs_are_wired(self):
        """Hunts and Glass each have their own Seed A panel and their own flip box."""
        for element in ("hsa-flips", "gl-flips"):
            with self.subTest(element):
                tag = _HTML[_HTML.index(f'id="{element}"'):]
                tag = tag[:tag.index(">")]
                self.assertIn("upperCaseInput(this)", tag)

    def test_it_still_narrows_on_the_same_keystroke(self):
        """The upper-casing must not replace the narrow call, only precede it."""
        for element, narrow in (("hsa-flips", "huntNarrowSeedA()"),
                                ("gl-flips", "glassNarrowSeedA()")):
            with self.subTest(element):
                tag = _HTML[_HTML.index(f'id="{element}"'):]
                tag = tag[:tag.index(">")]
                self.assertLess(tag.index("upperCaseInput(this)"), tag.index(narrow))

    def test_the_caret_is_preserved(self):
        """Assigning `value` parks the cursor at the end, which mid-word is worse than the
        lowercase was. Same technique as `hrHpInput`."""
        body = _function_body("upperCaseInput")
        self.assertIn("selectionStart", body)
        self.assertIn("setSelectionRange", body)

    def test_it_does_nothing_when_there_is_nothing_to_do(self):
        """No write at all for already-upper input, so a plain "HTTH" never touches the caret."""
        body = _function_body("upperCaseInput")
        self.assertIn("if (upper === el.value) return;", body)

    def test_the_selection_read_is_guarded(self):
        """`selectionStart` throws on some input types in some engines, which `mount` already
        works around the same way."""
        body = _function_body("upperCaseInput")
        self.assertIn("try {", body)
        self.assertEqual(body.count("catch"), 2)


class TestLowercaseFlipsAlreadyMatch(unittest.TestCase):
    """The Python half, so the UI change stays cosmetic rather than load-bearing."""

    def test_clean_flips_upper_cases(self):
        from claytonlib.coin_flips import clean_flips

        self.assertEqual(clean_flips("htth"), "HTTH")
        self.assertEqual(clean_flips("h t, T-h"), "HTTH")

    def test_a_lowercase_sequence_narrows_identically(self):
        from claytonlib.coin_flips import flip_sequence, flips_match

        seed = 0x0C0E02CA
        flips = flip_sequence(seed, 8)
        self.assertTrue(flips_match(seed, flips))
        self.assertTrue(flips_match(seed, flips.lower()))
