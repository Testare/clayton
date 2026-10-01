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
    "max_pp": {"0": 40, "1": 5, "2": 20, "3": 15},
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
        self.assertIn('${needSpread ? `<div class="panel" id="hsa-spread">', self.html)

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
