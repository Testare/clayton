"""The run page's Seed A step, and the target spread a missed key seed forces.

Battle Compass had only ever searched for Seed B, because that is the novel part. A real run
pins Seed A first, exactly as the Metronome and Safari compasses do -- and if the Seed A it pins
is not the key seed, the Suicune in front of the player is a DIFFERENT Pokemon from the one the
hunt was planned around. Every damage figure in the simulation derives from its nature and IVs,
so the run has to be told them.
"""
import pathlib
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

LEAD = {
    "name": "Smeargle", "species": "smeargle", "level": 58, "ability": "Technician",
    "stats": {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
    "moveset": ["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    # Keyed by 1-based move NUMBER, which is what the party form writes and what every saved
    # profile holds. This fixture used 0-based keys, matching the facade's own (wrong) reader --
    # so the test agreed with the bug and move 2 silently got move 1's PP.
    "max_pp": {"1": 40, "2": 5, "3": 20, "4": 15},
}
#: The configured spread -- what the KEY SEED would produce. All 31s, deliberately unlike the
#: override below so a stat difference proves which one a run used.
CONFIGURED = {"species": "suicune", "level": 40, "nature": "Bold",
              "ivs": {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}}
#: The real test2.jsonl spread. Its derived stats are emulator-verified
#: (141/63/119/89/109/84), which is what makes it the right fixture here.
ACTUAL_TEXT = "29 15 31 31 31 28"
ACTUAL_STATS = {"hp": 141, "atk": 63, "def": 119, "spa": 89, "spd": 109, "spe": 84}


def _ready_hunt():
    facade = Facade(FileStore(tempfile.mkdtemp()))
    profile_id = facade.create_profile({"name": "T"})["id"]
    lead = facade.add_party_pokemon(profile_id, LEAD)["pokemon_id"]
    hunt = facade.create_hunt({"name": "Suicune", "profile_id": profile_id})
    hunt.update({
        "target": CONFIGURED,
        "party": [{"pokemon_id": lead, "held_item": "Silk Scarf"}],
        "capture_ball": "Fast Ball", "key_seed": 0x2D005C61,
        "initial_time": "2026-01-01T12:00:00", "vector_ms": 5000,
        "seconds_window": 0, "delay_window": 10,
    })
    facade.save_hunt(hunt)
    return facade, hunt["id"]


class TestTheSetupCarriesWhatSeedANeeds(unittest.TestCase):
    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()

    def test_it_offers_every_nature(self):
        self.assertEqual(len(self.facade.hunt_run_setup(self.hunt_id)["natures"]), 25)

    def test_it_reports_the_configured_spread_as_text_for_prefilling(self):
        """Prefilled rather than blank because on a key-seed hit it IS the answer, and on a near
        miss it is the right thing to edit."""
        spread = self.facade.hunt_run_setup(self.hunt_id)["configured_spread"]
        self.assertEqual(spread["nature"], "Bold")
        self.assertEqual(spread["text"], "31 31 31 31 31 31")

    def test_a_hunt_with_incomplete_ivs_reports_empty_text_rather_than_failing(self):
        """The run page must open regardless of configuration -- that is the whole point of
        hunt_run_setup -- so a half-entered spread cannot be allowed to raise here."""
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        hunt = facade.create_hunt({"name": "Bare", "profile_id": profile_id})
        hunt.update({"target": {"species": "suicune", "level": 40, "nature": "",
                                "ivs": {"hp": 31}}})
        facade.save_hunt(hunt)
        self.assertEqual(facade.hunt_run_setup(hunt["id"])["configured_spread"]["text"], "")


class TestSeedADefaultsPersist(unittest.TestCase):
    """The roamers' starting positions belong to the SAVE FILE, not to the run, so retyping them
    every attempt is pure friction -- the same reason Safari Compass keeps them per expedition."""

    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()

    def test_they_start_empty(self):
        self.assertEqual(self.facade.hunt_run_setup(self.hunt_id)["seed_a_defaults"], {})

    def test_saving_them_survives_a_reload_of_the_setup(self):
        self.facade.hunt_save_seed_a_defaults(
            self.hunt_id, {"startrel": "31 30 7", "seconds_window": 3, "match_parity": True})
        got = self.facade.hunt_run_setup(self.hunt_id)["seed_a_defaults"]
        self.assertEqual(got["startrel"], "31 30 7")
        self.assertEqual(got["seconds_window"], 3)
        self.assertTrue(got["match_parity"])

    def test_saving_merges_rather_than_replaces(self):
        self.facade.hunt_save_seed_a_defaults(self.hunt_id, {"startrel": "31 30 7"})
        self.facade.hunt_save_seed_a_defaults(self.hunt_id, {"delay_window": 20})
        got = self.facade.hunt_run_setup(self.hunt_id)["seed_a_defaults"]
        self.assertEqual(got, {"startrel": "31 30 7", "delay_window": 20})


class TestValidatingATypedSpread(unittest.TestCase):
    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()

    def _check(self, nature, ivs):
        return self.facade.hunt_parse_target_spread(self.hunt_id, nature, ivs)

    def test_a_good_spread_comes_back_with_the_stats_it_derives(self):
        """The derived stats are returned deliberately: they are the only part of this the player
        can check against something they can see. A transposed pair of IVs is invisible in the
        spread itself and obvious the moment the HP it implies disagrees with the HP bar."""
        result = self._check("Bold", ACTUAL_TEXT)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stats"], ACTUAL_STATS)

    def test_the_fixture_stats_are_the_emulator_verified_ones(self):
        """Not an arbitrary spread: these are the numbers gdb wrote into test2.jsonl and that
        the 38-turn replay reproduces exactly."""
        self.assertEqual(self._check("Bold", ACTUAL_TEXT)["stats"]["hp"], 141)
        self.assertEqual(self._check("Bold", ACTUAL_TEXT)["stats"]["def"], 119)

    def test_a_short_spread_is_refused_with_the_count(self):
        result = self._check("Bold", "29 15 31")
        self.assertFalse(result["ok"])
        self.assertIn("got 3", result["problem"])

    def test_an_out_of_range_iv_is_refused(self):
        self.assertIn("32", self._check("Bold", "29 15 32 31 31 28")["problem"])

    def test_an_unknown_nature_is_refused_by_name(self):
        result = self._check("Bolder", ACTUAL_TEXT)
        self.assertFalse(result["ok"])
        self.assertIn("Bolder", result["problem"])

    def test_half_an_entry_is_refused_rather_than_completed_from_the_configuration(self):
        """A nature from one Suicune mixed with IVs from another derives stats that belong to no
        Pokemon at all, and nothing downstream would notice."""
        self.assertFalse(self._check("", ACTUAL_TEXT)["ok"])
        self.assertFalse(self._check("Bold", "")["ok"])

    def test_the_nature_list_comes_back_even_on_failure(self):
        """So a page that renders the dropdown from this response still has one to render."""
        self.assertEqual(len(self._check("Bold", "nonsense")["natures"]), 25)


class TestTheOverrideReachesTheRun(unittest.TestCase):
    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()

    def test_without_an_override_the_configured_spread_is_used(self):
        started = self.facade.hunt_session_start(self.hunt_id)
        self.assertIsNone(started["target_spread"])
        self.assertEqual(started["snapshot"]["target"]["max_hp"], 142)   # all-31s Suicune

    def test_with_an_override_the_run_simulates_the_other_suicune(self):
        started = self.facade.hunt_session_start(
            self.hunt_id, {"target_nature": "Bold", "target_ivs": ACTUAL_TEXT})
        self.assertEqual(started["snapshot"]["target"]["max_hp"], 141)
        self.assertEqual(started["target_spread"]["stats"], ACTUAL_STATS)

    def test_the_override_is_never_written_back_to_the_hunt(self):
        """hunt.target is the PLAN -- the spread every future attempt is aimed at. Overwriting it
        with one run's actual spread would lose the thing being targeted."""
        self.facade.hunt_session_start(
            self.hunt_id, {"target_nature": "Timid", "target_ivs": "0 0 0 0 0 0"})
        stored = self.facade.get_hunt(self.hunt_id)["target"]
        self.assertEqual(stored["nature"], "Bold")
        self.assertEqual(stored["ivs"], CONFIGURED["ivs"])

    def test_a_bad_override_refuses_the_run_rather_than_starting_a_wrong_one(self):
        for bad in ({"target_nature": "Bold", "target_ivs": "29 15 31"},
                    {"target_nature": "", "target_ivs": ACTUAL_TEXT},
                    {"target_nature": "Bold", "target_ivs": ""}):
            with self.assertRaises(ValueError, msg=str(bad)):
                self.facade.hunt_session_start(self.hunt_id, bad)

    def test_the_override_changes_what_the_simulation_is_working_from(self):
        """The point of all of it. The snapshot exposes max HP and effective Speed directly, and
        both move; the Defence that decides how much False Swipe takes off is in the returned
        spread. A run on the wrong spread desynchronises rather than merely being imprecise."""
        plain = self.facade.hunt_session_start(self.hunt_id)
        other = self.facade.hunt_session_start(
            self.hunt_id, {"target_nature": "Timid", "target_ivs": "0 0 0 0 0 0"})
        self.assertNotEqual(plain["snapshot"]["target"]["max_hp"],
                            other["snapshot"]["target"]["max_hp"])
        self.assertNotEqual(plain["snapshot"]["target"]["effective_speed"],
                            other["snapshot"]["target"]["effective_speed"])
        configured = self.facade.hunt_parse_target_spread(
            self.hunt_id, "Bold", "31 31 31 31 31 31")["stats"]
        self.assertNotEqual(configured["def"], other["target_spread"]["stats"]["def"])

    def test_which_stats_the_two_fixture_spreads_actually_differ_in(self):
        """Worth pinning, because it is a trap for anyone testing this -- it caught me. The
        configured spread (Bold, all 31s) and test2's actual spread (Bold, 29/15/31/31/31/28)
        share Def, Sp. Atk AND Sp. Def IVs of 31, so those three stats are byte-identical and
        False Swipe takes exactly the same amount off either Suicune. Only HP, Attack and Speed
        move. So an override is checked on max HP, not on outgoing damage."""
        configured = self.facade.hunt_parse_target_spread(
            self.hunt_id, "Bold", "31 31 31 31 31 31")["stats"]
        actual = self.facade.hunt_parse_target_spread(self.hunt_id, "Bold", ACTUAL_TEXT)["stats"]
        self.assertEqual([k for k in configured if configured[k] != actual[k]],
                         ["hp", "atk", "spe"])
        self.assertEqual(configured["def"], actual["def"])

    def test_a_different_defence_really_does_change_outgoing_damage(self):
        """Stated against the damage model rather than inferred from the stat, since "the number
        differs" is only interesting if the simulation reads it. Uses a spread that genuinely
        differs in Defence -- see the test above for why the obvious pair does not."""
        from claytonlib.battle.damage import Attacker, Defender, damage
        from claytonlib.moves import resolve_move
        attacker = Attacker(level=58, attack=65, special_attack=45, types=("Normal",),
                            ability="Technician", held_item="Silk Scarf")
        move = resolve_move("False Swipe")
        hit = {}
        for label, text in (("configured", "31 31 31 31 31 31"), ("weak", "0 0 0 0 0 0")):
            stats = self.facade.hunt_parse_target_spread(self.hunt_id, "Bold", text)["stats"]
            hit[label] = damage(
                move, attacker,
                Defender(defence=stats["def"], special_defence=stats["spd"], types=("Water",)),
                roll=100)
        self.assertNotEqual(hit["configured"], hit["weak"])
        self.assertGreater(hit["weak"], hit["configured"])


class TestThePageIsWiredUp(unittest.TestCase):
    """Static checks only -- there is no JS engine here -- but they catch the mistakes that
    actually happen: a handler the markup calls that does not exist, and a facade method the
    page names that the facade does not have."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_seed_a_reuses_the_other_compasses_calls(self):
        """This step is not novel and must not look novel. Same endpoints, same candidate
        table, same summary line as Metronome and Safari Compass."""
        for fragment in ('api("metronome_seed_a", _hsa.seedAParams)',
                         'api("metronome_key_seed_info"',
                         'renderCandA(_hsa.candidates, "huntPickSeedA")',
                         '_seedASummary(_hsa.seedA)'):
            self.assertIn(fragment, self.html, fragment)

    def test_the_spread_panel_is_only_rendered_on_a_key_seed_miss(self):
        self.assertIn("const needSpread = !!_hsa?.seedA && !huntSeedAIsKeySeed();", self.html)
        self.assertIn('${needSpread ? `<div class="panel ${spreadLocked ? "locked" : ""}" '
                      'id="hsa-spread">', self.html)

    def test_seed_b_is_locked_until_seed_a_is_identified(self):
        self.assertIn("const seedBLocked = blocked || !_hsa?.seedA;", self.html)

    def test_starting_is_gated_on_the_spread_when_it_is_needed(self):
        self.assertIn("return huntSeedAIsKeySeed() || _hsa.spreadConfirmed;", self.html)

    def test_the_blocked_button_says_why(self):
        """A disabled button with no explanation reads as a broken page."""
        self.assertIn("function huntStartBlockedReason(", self.html)
        self.assertIn("enter this Suicune's nature and IVs", self.html)

    def test_the_spread_is_sent_only_when_it_applies(self):
        self.assertIn("function huntSpreadParams(", self.html)
        self.assertIn("...huntSpreadParams()", self.html)

    def test_changing_seed_a_discards_the_spread_and_the_window(self):
        """A different Seed A is a different Suicune and a different battle seed, so keeping
        either would carry a stale answer into the new run."""
        self.assertIn("_hsa.spread = null; _hsa.spreadConfirmed = false;", self.html)

    def test_the_facade_has_every_method_the_seed_a_step_calls(self):
        import re
        for name in set(re.findall(r'api\("(hunt_[a-z_]+)"', self.html)):
            self.assertTrue(hasattr(Facade, name), f"facade has no {name}")

    def test_the_js_spread_check_agrees_with_the_python_parser(self):
        """Two implementations exist on purpose -- the page turns the field red as you type, the
        facade is the authority -- so the cases they could disagree on are pinned here."""
        import re

        from claytonlib.battle.stats import parse_iv_spread
        self.assertIn("function huntSpreadLooksValid(", self.html)
        for text, expected in [("29 15 31 31 31 28", True), ("31 31 31 31 31 31", True),
                               ("0 0 0 0 0 0", True), ("29 15 31 31 31", False),
                               ("29 15 31 31 31 28 7", False), ("29 15 31 x 31 28", False),
                               ("29 15 32 31 31 28", False), ("", False)]:
            tokens = [t for t in re.split(r"\s+", text.replace(",", " ")) if t]
            js = (len(tokens) == 6
                  and all(re.fullmatch(r"\d+", t) and int(t) <= 31 for t in tokens))
            self.assertEqual(js, expected, f"js check on {text!r}")
            try:
                parse_iv_spread(text)
                python_ok = True
            except ValueError:
                python_ok = False
            self.assertEqual(python_ok, expected, f"python parser on {text!r}")


class TestTheSpreadFieldsStartEmpty(unittest.TestCase):
    """The configured spread is NOT prefilled into them, and that is the whole safety property.

    This step is only ever reached when Seed A is not the key seed -- which is exactly when the
    configured spread is wrong. Prefilling it would validate instantly, enable Start, and send a
    run out simulating a Suicune that is not there. An empty field cannot do that.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_run_state_initialises_them_blank(self):
        self.assertIn('nature: "", ivs: "", spread: null, spreadConfirmed: false,', self.html)

    def test_the_configured_spread_is_shown_as_reference_not_as_a_value(self):
        self.assertIn("which is <i>not</i> what you are", self.html)
        self.assertIn("the fields start empty on", self.html)

    def test_the_start_button_is_disabled_the_moment_the_field_is_touched(self):
        """Not 250ms later when the debounced check returns -- in between, the button would
        still be offering to start a run on a spread the player is mid-way through changing."""
        self.assertIn("huntRenderStartButton();          // disable NOW", self.html)


class TestTheAdvanceFrameStep(unittest.TestCase):
    """Seed A's advance FRAME, which is a different question from which seed it is.

    For a static A-press encounter the frame is what generates the Pokemon, so it answers one of
    two questions depending on where Seed A landed: how to reach the Suicune that was planned
    for, or which Suicune is about to appear.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_it_reuses_the_two_generic_facade_calls(self):
        """Neither takes anything Safari-specific -- a seed, the roamer routes and frame
        numbers -- which is what makes them reusable here without a fork."""
        self.assertIn('api("safari_compass_identify_frame"', self.html)
        self.assertIn('api("safari_compass_plan_frame"', self.html)

    def test_it_does_not_reuse_the_in_house_target_frame_search(self):
        """safari_compass_find_target_frame searches a Safari AREA's encounter slots for a
        species. That has no meaning for a static encounter, and it is the source of the
        optional target-frame field this page is explicitly not supposed to have."""
        run = self.html[self.html.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        # The CALL, not the string: the only mention in this region is the comment explaining
        # why it is not used, and a test that forbade the name would forbid the explanation.
        self.assertNotIn('api("safari_compass_find_target_frame"', run)
        self.assertNotIn("sac-target-frame", run)
        self.assertNotIn("aim_advance", run)

    def test_the_target_frame_is_only_used_on_an_exact_key_seed_hit(self):
        """key_seed_advances was computed against the key seed's own stream. On any other Seed A
        it is a number from a different battle and routing to it would be worse than useless."""
        self.assertIn("function huntKeySeedTargetFrame(", self.html)
        self.assertIn("return (huntSeedAIsKeySeed() && _huntSetup?.key_seed_advances != null)",
                      self.html)

    def test_a_non_key_seed_identifies_the_frame_and_stops_there(self):
        self.assertIn("Seed A is not the key seed, so no target frame", self.html)
        self.assertIn("Look up the Suicune at frame", self.html)

    def test_the_route_is_worded_for_an_a_press_not_sweet_scent(self):
        """The plan is the same arithmetic; the terminal action is not. plan_frame_route's own
        field names stay Safari-flavoured (elm_before_scent, scent_frame) and are left alone --
        only the wording here changes."""
        self.assertIn("then press A on Suicune.", self.html)
        self.assertIn('(press A at the "!")', self.html)

    def test_the_spread_panel_waits_for_the_frame(self):
        """Until the frame is pinned there is nothing to look the spread up BY."""
        self.assertIn("const spreadLocked = _hsa?.pinnedFrame == null;", self.html)

    def test_seed_b_is_deliberately_not_gated_on_the_frame(self):
        """A player who already knows they are on the right frame should not have to re-derive
        it to get on with the battle."""
        self.assertIn("const seedBLocked = blocked || !_hsa?.seedA;", self.html)

    def test_changing_seed_a_discards_the_pinned_frame(self):
        """A frame is an offset into one seed's Elm stream; carried onto another seed it is a
        confidently wrong number."""
        self.assertIn("_hsa.pinnedFrame = null; _hsa.frameGuide = null;", self.html)

    def test_the_elm_calls_typed_for_seed_a_carry_into_the_frame_step(self):
        """They are the same calls -- the ones heard since the seed loaded. Prefilled rather
        than applied, so a mistyped call can be fixed first."""
        self.assertIn('const elmHeard = $("hsa-elm")?.value || "";', self.html)
        self.assertIn("_hsa.frameElmPrefill = elmHeard;", self.html)

    def test_re_pinning_moves_the_heard_calls_back_into_the_field(self):
        """Rather than discarding them: the usual reason to come back is one mistyped call in an
        otherwise correct sequence."""
        self.assertIn("const moved = _hsa.frameObservedElm", self.html)


class TestTheSetupCarriesTheFrameInputs(unittest.TestCase):
    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()

    def test_it_reports_the_hunts_planned_advance_frame(self):
        hunt = self.facade.get_hunt(self.hunt_id)
        hunt["key_seed_advances"] = 81
        self.facade.save_hunt(hunt)
        self.assertEqual(self.facade.hunt_run_setup(self.hunt_id)["key_seed_advances"], 81)

    def test_an_unset_advance_frame_is_none_rather_than_a_default(self):
        """A guessed frame would plan a confident route to the wrong Suicune, so there is no
        default -- the page simply does not offer a route without one."""
        self.assertIsNone(self.facade.hunt_run_setup(self.hunt_id)["key_seed_advances"])

    def test_the_elm_margin_is_the_shared_default_not_an_invented_per_hunt_setting(self):
        from app.models import _default_preferences
        self.assertEqual(self.facade.hunt_run_setup(self.hunt_id)["elm_margin"],
                         _default_preferences()["elm_calls_after_flips"])

    def test_identifying_a_frame_works_off_a_hunt_seed(self):
        """End to end through the facade, since the call was written for Safari Compass and this
        is the first time a Hunt has driven it."""
        result = self.facade.safari_compass_identify_frame(
            {"seed": 0x2D005C61, "prev_routes": {"r": 31, "e": 30, "l": 7},
             "observed_elm": ""})
        self.assertIn("frames", result)
        self.assertGreater(len(result["frames"]), 0)

    def test_planning_a_route_works_off_a_hunt_seed(self):
        plan = self.facade.safari_compass_plan_frame(
            {"seed": 0x2D005C61, "prev_routes": {"r": 31, "e": 30, "l": 7},
             "current_frame": 10, "encounter_frame": 81, "margin": 3})
        self.assertEqual(plan["encounter_frame"], 81)
        self.assertEqual(plan["current_frame"], 10)
        self.assertTrue(plan["guide"])


class TestSafariCompassIsUntouched(unittest.TestCase):
    """The reuse must not cost Safari Compass anything -- its in-house search and its Pokefinder
    target-frame field both stay exactly where they were."""

    def setUp(self):
        self.html = INDEX.read_text()

    def test_its_in_house_search_is_still_there(self):
        self.assertIn("function renderInHouseFrameSearch(", self.html)
        self.assertIn("function sacFindTargetFrame(", self.html)
        self.assertIn('api("safari_compass_find_target_frame"', self.html)

    def test_its_optional_target_frame_field_is_still_there(self):
        self.assertIn('id="sac-target-frame"', self.html)
        self.assertIn("function _sacAimAdvanceField(", self.html)

    def test_its_own_frame_guide_still_says_sweet_scent(self):
        self.assertIn('(Sweet scent at the "!")', self.html)

    def test_the_facade_still_exposes_the_search_it_does_not_use_here(self):
        self.assertTrue(callable(getattr(Facade, "safari_compass_find_target_frame", None)))


class TestKeySeedHitVersusFrameToAimFor(unittest.TestCase):
    """Two separate questions that it is tempting to collapse into one.

    A hunt can land on its key seed and still have no `key_seed_advances` configured. Treating
    "no target frame" as "not the key seed" printed "Seed A is not the key seed" at someone who
    had just hit it -- and would have asked them for a spread they did not need.
    """

    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_two_conditions_are_tracked_separately(self):
        self.assertIn("const onKeySeed = huntSeedAIsKeySeed();", self.html)
        self.assertIn("// THREE cases, not two.", self.html)

    def test_a_key_seed_hit_without_a_planned_frame_says_so(self):
        self.assertIn("but this hunt has no planned advance frame configured", self.html)
        self.assertIn("No planned advance frame is configured for this hunt", self.html)

    def test_the_spread_is_still_skipped_on_a_key_seed_hit(self):
        """It keys off the SEED, not off whether a frame was configured -- the configured spread
        is the key seed's either way."""
        self.assertIn("const needSpread = !!_hsa?.seedA && !huntSeedAIsKeySeed();", self.html)

    def test_a_failed_plan_is_not_a_dead_end(self):
        """The in-flight state is also where a thrown plan lands, and a toast has faded by the
        time the player looks."""
        self.assertIn('onclick="huntPlanFrameRoute(${target})">Retry', self.html)


class TestSavingAHuntRun(unittest.TestCase):
    """A finished run had nowhere to go. Runs are profile-owned like the other two kinds, with
    `hunt_id` a back-reference: a hunt is attempted many times, and deleting one should not take
    its history with it."""

    def setUp(self):
        self.facade, self.hunt_id = _ready_hunt()
        started = self.facade.hunt_session_start(self.hunt_id)
        self.sid = started["session_id"]
        truth = started["snapshot"]["candidates"][0]["seed"]
        predicted = self.facade.hunt_session_predict(self.sid, "M1")[truth]
        self.facade.hunt_session_observe(self.sid, "M1", [predicted])
        self.profile_id = self.facade.get_hunt(self.hunt_id)["profile_id"]

    def test_the_record_can_be_previewed_before_committing(self):
        record = self.facade.hunt_session_run_record(self.sid)
        self.assertEqual(record["turns"], 1)
        self.assertEqual(record["hunt_id"], self.hunt_id)
        self.assertEqual(record["hunt_name"], "Suicune")
        self.assertEqual(record["vector_ms"], 5000)

    def test_saving_stores_a_battle_kind_run(self):
        run = self.facade.save_hunt_run(self.sid, {"tag": "BC1"})
        self.assertEqual(run["kind"], "battle")
        self.assertEqual(run["hunt_id"], self.hunt_id)
        self.assertEqual(run["tag"], "BC1")
        self.assertEqual(len(self.facade.list_runs(self.profile_id, "battle")), 1)

    def test_it_does_not_show_up_among_the_other_kinds(self):
        """A third kind alongside metronome and safari, not mixed into either -- they feed fits
        this one deliberately does not."""
        self.facade.save_hunt_run(self.sid, {})
        self.assertEqual(self.facade.list_runs(self.profile_id, "safari"), [])
        self.assertEqual(self.facade.list_runs(self.profile_id, "metronome"), [])
        self.assertEqual(len(self.facade.list_runs(self.profile_id)), 1)

    def test_an_unfinished_run_saves_as_abandoned(self):
        """Saveable at any point. A half-finished run is still a real observation of where the
        seed landed."""
        self.assertEqual(self.facade.save_hunt_run(self.sid, {})["outcome"], "abandoned")

    def test_the_spread_is_stored_so_the_run_can_be_reproduced(self):
        """Without it a run on a non-key-seed Seed A is unreplayable -- and that is most runs."""
        run = self.facade.save_hunt_run(self.sid, {
            "target_spread": {"nature": "Bold", "ivs": ACTUAL_TEXT}})
        self.assertEqual(run["target_spread"], {"nature": "Bold", "ivs": ACTUAL_TEXT})

    def test_the_page_supplies_the_half_the_session_never_saw(self):
        """Seed A and its advance frame are identified before the session exists."""
        run = self.facade.save_hunt_run(self.sid, {
            "a_seed": {"seed_hex": "0x2D005C61"}, "advance_frame": 81, "elm_calls": 3})
        self.assertEqual(run["a_seed"]["seed_hex"], "0x2D005C61")
        self.assertEqual(run["advance_frame"], 81)
        self.assertEqual(run["elm_calls"], 3)

    def test_the_path_is_stored(self):
        self.assertTrue(self.facade.save_hunt_run(self.sid, {})["path"])


class TestTheSaveRunUi(unittest.TestCase):
    def setUp(self):
        self.html = INDEX.read_text()

    def test_a_finished_run_offers_to_save(self):
        self.assertIn("function openSaveHuntRunModal(", self.html)
        self.assertIn('onclick="openSaveHuntRunModal()">Save run', self.html)

    def test_it_is_offered_on_every_ending_not_only_a_win(self):
        """A wrong-ball or wiped-out run is the more informative record."""
        self.assertIn("const saveBar =", self.html)
        self.assertIn("${saveBar}</div>`\n    : s.party_wiped", self.html)

    def test_a_run_in_progress_can_be_saved_too(self):
        self.assertIn('${s.over || !s.turns.length ? "" :', self.html)

    def test_the_record_comes_from_the_session_not_the_page(self):
        self.assertIn('api("hunt_session_run_record", _huntRun)', self.html)

    def test_the_page_contributes_seed_a_and_the_spread(self):
        self.assertIn("a_seed: (_hsa && _hsa.seedA) ? _hsa.seedA : {},", self.html)
        self.assertIn("? {nature: _hsa.nature, ivs: _hsa.ivs} : {},", self.html)


class TestPressureIsDerivedNotDefaulted(unittest.TestCase):
    """HuntConfig.target_has_pressure defaults True and the facade never set it."""

    def test_a_pressure_target_still_doubles_our_pp(self):
        facade, hunt_id = _ready_hunt()
        facade.hunt_session_start(hunt_id)
        sid = facade._hunt_sessions.for_hunt(hunt_id)[0]
        self.assertTrue(facade._hunt_sessions.get(sid).config.target_has_pressure,
                        "Suicune has Pressure")

    def test_a_levitate_target_does_not(self):
        """Latias has Levitate. Assuming Pressure here would halve every PP budget."""
        facade, hunt_id = _ready_hunt()
        hunt = facade.get_hunt(hunt_id)
        hunt["target"] = dict(CONFIGURED, species="latias")
        facade.save_hunt(hunt)
        facade.hunt_session_start(hunt_id)
        sid = facade._hunt_sessions.for_hunt(hunt_id)[0]
        self.assertFalse(facade._hunt_sessions.get(sid).config.target_has_pressure)

    def test_it_changes_the_pp_a_turn_actually_spends(self):
        """The consequence, not just the flag."""
        from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
        from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.battle_compass.targets import moveset
        from claytonlib.moves import resolve_move

        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79,
                              "spe": 160},
                       moves=("False Swipe", "Mean Look"), pp=(40, 5))
        mv = moveset("suicune")
        target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                         stats=derive_species_stats("suicune", 40, "Bold"), moves=mv,
                         pp=tuple(resolve_move(m).pp for m in mv),
                         hp=1, status=Status.PARALYSIS)
        spent = {}
        for label, pressure in (("pressure", True), ("levitate", False)):
            state = BattleState(ours=ours, target=target, rng=0xEC1504DC, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1,
                                HuntConfig(target_catch_rate=3, target_has_pressure=pressure))
            spent[label] = 40 - nxt.ours.pp_left(0)
        self.assertEqual(spent, {"pressure": 2, "levitate": 1})
