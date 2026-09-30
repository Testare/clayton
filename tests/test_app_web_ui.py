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
