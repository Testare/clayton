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


if __name__ == "__main__":
    unittest.main()
