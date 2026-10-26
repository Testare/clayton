"""Two interview questions that could not be answered truthfully.

Both are the same family of bug, and `hrStatusWeJustApplied` was already the fix for a third of
them: **the snapshot's option lists describe the state the turn OPENED in**, while half of a turn
happens before the other half. A Flash resolves before Ho-Oh's Punishment, so it can make a
100%-accuracy move miss on the very turn it is used -- the simulator has always modelled that, and
the page offered no chip to report it (clayton-957.10.8).

The other is plainer: the page asserted what every secondary effect does, in Suicune's words
(clayton-957.10.9).
"""
import unittest
from pathlib import Path

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import move_info
from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.moves import resolve_move

INDEX = Path(__file__).resolve().parents[1] / "app" / "web" / "index.html"
HUNT = HuntConfig(target_catch_rate=3)
#: Flash lands and Punishment misses, on the same turn. The turn the player played and could not
#: report: `M2E2-`.
FLASH_THEN_MISS_SEED = 0x103C


def ampharos(**kw):
    fields = dict(name="Ampharos", level=93, types=("Electric",),
                  stats={"hp": 311, "atk": 137, "def": 182, "spa": 336, "spd": 210, "spe": 143},
                  moves=("Light Screen", "Flash", "Discharge", "Signal Beam"),
                  pp=(30, 20, 15, 15), held_item="Leftovers", ability="Static")
    fields.update(kw)
    return Battler(**fields).with_hp(311)


def hooh(**kw):
    moves = moveset("ho-oh")   # the Lv70 SoulSilver set
    fields = dict(name="Ho-Oh", level=70, types=tuple(species("ho-oh")["types"]),
                  stats=derive_species_stats("ho-oh", 70, "Serious"), moves=moves,
                  pp=tuple(resolve_move(m).pp for m in moves), ability="Pressure")
    fields.update(kw)
    return Battler(**fields)


class TestTheSimulatorPredictsTheMissAlready(unittest.TestCase):
    """The half that was never broken, pinned first -- because it is what makes the missing chip
    a reporting bug rather than a modelling one."""

    def _turn(self, seed, action=Action.MOVE_2):
        state = BattleState(ours=ampharos(), target=hooh(status=Status.PARALYSIS),
                            rng=seed, phase=1)
        nxt = simulate_turn(state, action, HUNT)
        return tok.render_turn(tok.normalise(nxt.log[-1])), nxt

    def test_punishment_misses_on_the_turn_we_flash(self):
        rendered, nxt = self._turn(FLASH_THEN_MISS_SEED)
        self.assertEqual(rendered, "M2E2-")
        self.assertEqual(nxt.target.accuracy_stage, -1,
                         "the drop resolved before the target's half of the turn")

    def test_it_cannot_miss_on_a_turn_we_do_not_flash(self):
        """Light Screen touches no stage, so Punishment stays at 100 and the accuracy roll has
        nothing to fail against. Without this the test above could pass for the wrong reason."""
        for seed in range(0x1000, 0x1000 + 3000):
            rendered, _ = self._turn(seed, Action.MOVE_1)
            self.assertNotIn("E2-", rendered)


class TestTheSnapshotCarriesWhatThePageNeeds(unittest.TestCase):

    def test_a_drop_move_publishes_which_stage_it_drops(self):
        """A LIST since the two-stat family went in -- Tickle drops two -- so the page searches
        it for the stage it cares about rather than indexing."""
        info = {m["name"]: m for m in move_info(ampharos(), hooh())}
        self.assertEqual(info["Flash"]["stat_drop"], [{"stat": "accuracy", "stages": 1}])
        self.assertIsNone(info["Discharge"]["stat_drop"])

    def test_a_two_stat_drop_publishes_both(self):
        """Tickle. Nothing in a configured moveset has it; the shape is what is being pinned,
        because publishing only the first stage would describe half the move."""
        from claytonlib.battle_compass.state import Battler

        tickler = Battler(name="T", level=50, types=("Normal",), stats={"hp": 100},
                          moves=("Tickle",), pp=(20,))
        info = {m["name"]: m for m in move_info(tickler, hooh())}
        self.assertEqual(info["Tickle"]["stat_drop"],
                         [{"stat": "atk", "stages": 1}, {"stat": "def", "stages": 1}])

    def test_a_self_raise_move_publishes_what_it_raises(self):
        """New alongside the rest of the family: a page that showed a drop but not a boost would
        be describing half of a Dragon Dance turn."""
        from claytonlib.battle_compass.state import Battler

        dancer = Battler(name="D", level=50, types=("Normal",), stats={"hp": 100},
                         moves=("Dragon Dance", "Swords Dance", "Discharge"), pp=(20, 30, 15))
        info = {m["name"]: m for m in move_info(dancer, hooh())}
        self.assertEqual(info["Dragon Dance"]["self_raise"],
                         [{"stat": "atk", "stages": 1}, {"stat": "spe", "stages": 1}])
        self.assertEqual(info["Swords Dance"]["self_raise"], [{"stat": "atk", "stages": 2}])
        self.assertIsNone(info["Discharge"]["self_raise"])

    def test_punishment_is_unmissable_at_a_neutral_stage(self):
        """Which is exactly why the page has to work the turn out for itself."""
        info = {m["name"]: m for m in move_info(hooh(), ampharos())}
        self.assertFalse(info["Punishment"]["can_miss"])
        self.assertEqual(info["Punishment"]["effective_accuracy"], 100)

    def test_and_missable_once_the_stage_is_down(self):
        info = {m["name"]: m for m in move_info(hooh(accuracy_stage=-1), ampharos())}
        self.assertTrue(info["Punishment"]["can_miss"])

    def test_safeguard_bypasses_the_check_at_every_stage(self):
        """0 means "no accuracy roll at all", which is not the same as 0%. A drop must not make
        it missable, and this is the field the page gates on."""
        for stage in (0, -1, -6):
            info = {m["name"]: m for m in move_info(hooh(accuracy_stage=stage), ampharos())}
            self.assertEqual(info["Safeguard"]["effective_accuracy"], 0)
            self.assertFalse(info["Safeguard"]["can_miss"])

    def test_the_secondary_is_named_per_move_and_per_side(self):
        info = {m["name"]: m for m in move_info(hooh(), ampharos())}
        self.assertEqual(info["Ancient Power"]["secondary_side"], "attacker")
        self.assertIn("rose", info["Ancient Power"]["secondary_label"])
        self.assertEqual(info["Sacred Fire"]["secondary_side"], "victim")
        self.assertIn("burned", info["Sacred Fire"]["secondary_label"])
        self.assertEqual(info["Sacred Fire"]["secondary_status"], "brn")

    def test_an_empty_slot_carries_the_same_keys(self):
        """The page reads these off every slot, so a three-move Pokemon must not produce
        undefined."""
        gappy = ampharos(moves=("Flash", ""), pp=(20, 0))
        empty = move_info(gappy, hooh())[1]
        self.assertFalse(empty["known"])
        for key in ("stat_drop", "secondary_label", "secondary_side", "secondary_status"):
            self.assertIn(key, empty)
            self.assertIsNone(empty[key])


class TestThePageOffersTheMiss(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text()

    def test_the_target_side_asks_the_helper_not_the_flag(self):
        self.assertIn("function hrTargetCanMiss(info){", self.html)
        self.assertEqual(self.html.count("if (hrTargetCanMiss(info))"), 2,
                         "both the It-failed chip and the Missed chip")

    def test_it_reads_the_drop_our_move_just_landed(self):
        """Searched rather than indexed, since `stat_drop` is a list of pairs now."""
        self.assertIn("function hrAccuracyDropWeJustApplied(){", self.html)
        self.assertIn('.find(d => d.stat === "accuracy")', self.html)

    def test_a_bypassing_move_is_still_unmissable(self):
        self.assertIn("if (!info.effective_accuracy) return false;", self.html)

    def test_a_missed_flash_drops_nothing(self):
        """`result === ""` is "it worked"; "-" is a miss, and a missed Flash moves no stage."""
        self.assertIn('return t.ours.result === "" ? acc.stages : 0;', self.html)

    def test_it_only_counts_when_we_moved_first(self):
        block = self.html.split("function hrAccuracyDropWeJustApplied(){")[1].split("\n}")[0]
        self.assertIn("hrWeActFirst()", block)
        self.assertIn("t.ours.prevented", block)

    def test_our_own_side_is_left_alone(self):
        """Nothing a configured target can do raises its evasion -- Ancient Power is the five
        stats, not accuracy or evasion -- so our own `can_miss` cannot change mid-turn."""
        self.assertIn("if (info.can_miss)\n    opts.push(hrChip(\"Missed\"", self.html)


class TestThePageNamesTheSecondary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text()

    def test_the_hardcoded_wording_is_gone(self):
        """The literal that asserted Suicune's effect for every move on both sides. Matched as
        the whole template so the comment explaining the fix does not satisfy the test."""
        self.assertNotIn("""Yes — ${esc(hrActive().name)}'s stat fell""", self.html)

    def test_both_sides_go_through_one_helper(self):
        self.assertIn("function hrSecondaryYes(info, attackerName, victimName){", self.html)
        self.assertEqual(self.html.count("hrChip(hrSecondaryYes("), 2)

    def test_the_sides_are_passed_the_right_way_round(self):
        """The target's move: the target is the attacker. Ours: we are."""
        self.assertIn("hrChip(hrSecondaryYes(info, s.target.name, hrActive().name)", self.html)
        self.assertIn("hrChip(hrSecondaryYes(info, hrActive().name, _huntSnap.target.name)",
                      self.html)

    def test_an_undescribed_effect_falls_back_to_a_bare_yes(self):
        self.assertIn('if (!info || !info.secondary_label) return "Yes";', self.html)

    def test_the_name_is_substituted_not_concatenated(self):
        self.assertIn('info.secondary_label.replace("{who}", who)', self.html)


class TestAStatusFromASecondaryIsLiveMidTurn(unittest.TestCase):
    """Discharge paralyzes when its 30% lands, and that reaches the target before its own half of
    the turn -- so "was fully paralyzed" becomes answerable on a turn that opened unstatused."""

    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text()

    def test_the_page_reads_the_secondary_status(self):
        self.assertIn("if (info.secondary_status && hrLanded(t.ours) && t.ours.secondary === true)",
                      self.html)

    def test_it_waits_for_the_secondary_answer(self):
        """`secondary === true` and not merely truthy: undefined is "not asked yet", and guessing
        would offer an option the player cannot have seen."""
        block = self.html.split("function hrStatusWeJustApplied(){")[1].split("\n}")[0]
        self.assertIn("t.ours.secondary === true", block)

    def test_the_primary_route_is_unchanged(self):
        block = self.html.split("function hrStatusWeJustApplied(){")[1].split("\n}")[0]
        self.assertIn("if (info.applies_status){", block)
        self.assertIn("info.guaranteed_fail", block)


class TestStaticGetsAToken(unittest.TestCase):
    """clayton-957.10.13. The one event in a turn that no move announces.

    The game says "Ho-Oh is paralyzed!" with nothing attached, so Static cannot ride on the
    move's question or its `~`. Without a marker of its own the roll was unreportable -- and
    unreportable means unfilterable: two candidates differing only in that 30% rendered the same
    turn, both survived, and the tool held a split belief about the one status the run is for.
    """

    #: Punishment hits Ampharos and Static paralyzes Ho-Oh for it: `E2h*M2HP287`.
    STATIC_SEED = 0x1008

    def _turn(self, seed, action=Action.MOVE_2, **kw):
        state = BattleState(ours=ampharos(), target=hooh(), rng=seed, phase=1, **kw)
        nxt = simulate_turn(state, action, HUNT, **(
            {"bench_slot": 0} if action is Action.SWITCH else {}))
        return tok.render_turn(tok.normalise(nxt.log[-1])), nxt

    def test_the_marker_is_rendered_when_it_fires(self):
        rendered, nxt = self._turn(self.STATIC_SEED)
        self.assertIn("E2h*", rendered)
        self.assertIs(nxt.target.status, Status.PARALYSIS)

    def test_it_is_not_rendered_when_it_does_not(self):
        """Over a sweep, so this is about the marker tracking the outcome rather than one seed."""
        for seed in range(0x1000, 0x1000 + 1500):
            rendered, nxt = self._turn(seed)
            self.assertEqual("*" in rendered, nxt.target.status is Status.PARALYSIS, hex(seed))

    def test_it_is_distinct_from_the_secondary_marker(self):
        """Both can land on one token -- a contact move with a secondary -- so conflating them
        would make a proc indistinguishable from an ability trigger."""
        self.assertNotEqual(tok.STATIC, tok.SECONDARY)

    def test_it_survives_the_grammar(self):
        """A detail marker, so it must not split the token, trip a rule, or satisfy the
        "something hit us" test on its own."""
        self.assertEqual(tok.tokenise("E2h*"), ["E2h*"])
        self.assertEqual(tok.tokenise("S2E2h*HP289"), ["S2", "E2h*", "HP289"])
        self.assertEqual(tok.validate_turn(["M2", "E2h*", "HP287"]), [])
        self.assertEqual(tok.validate_turn(["E1h~*", "HP287"]), [])
        self.assertFalse(tok.turn_requires_hp(["M1h*"]), "our own move hitting them is not us")

    def test_a_static_turn_explains_itself_in_words(self):
        """The player reads prose in three places -- the recommended turn, the history table and
        a contradiction report -- and "E2h*" has to become a sentence in all of them."""
        prose = tok.explain_turn(["E2h*"], ours="Ampharos", target="Ho-Oh",
                                 ours_moves=("Light Screen", "Flash", "Discharge", "Signal Beam"),
                                 target_moves=moveset("ho-oh"))
        joined = " ".join(prose).lower()
        self.assertIn("static", joined)
        self.assertIn("paralyz", joined)

    def test_it_fires_on_a_switch_turn(self):
        """The turn the plan actually brings the Static holder in on: a switch resolves before
        any move, so Ho-Oh's contact move lands on the newcomer."""
        from claytonlib.battle_compass.state import Battler as B
        chatot = B(name="Chatot", level=20, types=("Normal", "Flying"),
                   stats={"hp": 62, "atk": 40, "def": 34, "spa": 55, "spd": 34, "spe": 55},
                   moves=("Growl", "Sing"), pp=(40, 15), ability="Keen Eye",
                   party_slot=1).with_hp(62)
        state = BattleState(ours=chatot, target=hooh(), rng=self.STATIC_SEED, phase=1,
                            bench=(ampharos(party_slot=2),))
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
        self.assertIn("*", rendered)
        self.assertEqual(nxt.ours.name, "Ampharos")
        self.assertIs(nxt.target.status, Status.PARALYSIS)


class TestThePageAsksAboutStatic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = INDEX.read_text()

    def test_there_is_a_question(self):
        self.assertIn("Static paralyze", self.html)
        self.assertIn("function hrStaticPossibleOnTarget(){", self.html)

    def test_it_needs_our_ability_their_contact_and_a_landed_hit(self):
        block = self.html.split("function hrStaticPossibleOnTarget(){")[1].split("\n}")[0]
        self.assertIn('!== "static"', block)
        self.assertIn("info.makes_contact", block)
        self.assertIn("hrLanded(t.target)", block)

    def test_an_already_statused_target_is_not_asked_about(self):
        """Statuses are mutually exclusive, and the roll is not even spent -- including against a
        status we landed earlier in the same turn."""
        block = self.html.split("function hrStaticPossibleOnTarget(){")[1].split("\n}")[0]
        self.assertIn('s.target.status !== "none"', block)
        self.assertIn("hrStatusWeJustApplied()", block)

    def test_the_marker_is_gated_on_the_same_predicate_as_the_question(self):
        self.assertIn("function hrStaticMark(side){", self.html)
        self.assertIn('if (side !== "target" || !hrStaticPossibleOnTarget()) return "";',
                      self.html)

    def test_the_token_carries_it_after_the_secondary(self):
        self.assertIn('+ hrSecondaryMark("target") + hrStaticMark("target")', self.html)

    def test_the_turn_will_not_report_without_the_answer(self):
        self.assertIn("if (hrStaticPossibleOnTarget() && t.target.static === undefined) "
                      "return false;", self.html)

    def test_the_bench_publishes_an_ability_so_a_switch_turn_can_ask(self):
        """hrActive() returns the INCOMING Pokemon on a switch turn, and the bench rows carried
        no ability at all -- so the question was skipped on exactly the turn the plan uses."""
        import inspect

        from claytonlib.battle_compass import hunt_session
        source = inspect.getsource(hunt_session.HuntSession.snapshot)
        self.assertIn('"ability": b.ability', source)


class TestTheProseFollowsTheSwitch(unittest.TestCase):
    """`explain_turn` named whoever was out at the START of the turn for the whole turn.

    Pre-existing, and the Static clause is what made it a wrong statement rather than a vague
    one: the plan's opening turn read "Ho-Oh used Punishment and hit Chatot, and Chatot's Static
    paralyzed Ho-Oh" -- crediting the Pokemon that had already left with an ability it does not
    have. A switch resolves before any move, so everything after an `S` token is the newcomer's.
    """

    def _prose(self, tokens):
        return tok.explain_turn(
            tokens, ours="Chatot", target="Ho-Oh", ours_moves=("Growl", "Sing"),
            target_moves=moveset("ho-oh"),
            party_name=lambda slot: {2: "Ampharos"}.get(slot))

    def test_the_hit_lands_on_the_newcomer(self):
        joined = " ".join(self._prose(["S2", "E2h*", "HP289"]))
        self.assertIn("hit Ampharos", joined)
        self.assertNotIn("hit Chatot", joined)

    def test_the_ability_is_credited_to_the_newcomer(self):
        self.assertIn("Ampharos's Static", " ".join(self._prose(["S2", "E2h*", "HP289"])))

    def test_the_hp_sentence_names_the_newcomer_too(self):
        self.assertIn("Ampharos ended the turn on 289 HP",
                      self._prose(["S2", "E2h*", "HP289"]))

    def test_a_turn_with_no_switch_is_unchanged(self):
        self.assertIn("Chatot ended the turn on 40 HP", self._prose(["E1h", "HP040"]))

    def test_a_faint_rebinds_it_as_well(self):
        prose = " ".join(self._prose(["E2h", "X2"]))
        self.assertIn("Chatot fainted", prose)
        self.assertIn("sent out Ampharos", prose)


class TestTheBurnTickFollowsWhoIsOutAtTheEndOfTheTurn(unittest.TestCase):
    """clayton-957.10.16, reported from a live run: switching from a burned Ampharos to Granbull
    asked *"Did Granbull faint?"* because *"burn takes N at end of turn"* — a burn Ampharos was
    carrying.

    The question already named the incoming Pokemon, correctly: a switch resolves before any move,
    so the newcomer is the one the end-of-turn tick lands on. Only its *reason* was read off the
    lead. Fixed by publishing the figure per Pokemon, which makes every reader name whose it is.
    """

    def _snapshot(self, **kw):
        import datetime as dt

        from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
        from claytonlib.battle_compass.hunt_session import HuntSession

        burned = Battler(**{**{f: getattr(ampharos(), f) for f in (
            "name", "level", "types", "stats", "moves", "pp", "ability", "held_item")},
            "party_slot": 3, **kw})
        granbull = Battler(name="Granbull", level=44, types=("Normal",),
                           stats={"hp": 162, "atk": 109, "def": 122, "spa": 64, "spd": 66,
                                  "spe": 52},
                           moves=("Charm",), pp=(20,), ability="Intimidate", party_slot=4)
        window = CandidateWindow(
            key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
            frame_centre=1000, second_centre=30, frame_window=2, second_window=0,
            candidates=tuple(Candidate(seed=0x100E2BD5 + i, frame=1000 + i, second=30)
                             for i in range(4)))
        return HuntSession(window, burned, hooh(status=Status.PARALYSIS), HUNT,
                           bench=(granbull,)).snapshot()

    def test_the_lead_carries_its_own_figure(self):
        snap = self._snapshot(status=Status.BURN)
        self.assertEqual(snap["ours"]["burn_tick"], 311 // 8)   # this fixture is 311 HP

    def test_an_unburned_bench_member_carries_zero_while_the_lead_burns(self):
        """The reported case exactly."""
        snap = self._snapshot(status=Status.BURN)
        self.assertEqual(snap["bench"][0]["name"], "Granbull")
        self.assertEqual(snap["bench"][0]["status"], "none")
        self.assertEqual(snap["bench"][0]["burn_tick"], 0)

    def test_an_unburned_lead_carries_zero_too(self):
        self.assertEqual(self._snapshot()["ours"]["burn_tick"], 0)

    def test_there_is_no_single_top_level_figure_left_to_misread(self):
        """Removing it is the fix, not an extra: a duplicate that is subtly wrong on switch turns
        invites the same bug back."""
        self.assertNotIn("burn_tick", self._snapshot(status=Status.BURN))

    def test_the_page_reads_it_off_the_active_pokemon(self):
        html = INDEX.read_text()
        self.assertIn("if (hrActive().burn_tick > 0) return true;", html)
        self.assertNotIn("s.burn_tick", html)

    def test_the_hint_names_whose_burn_it_is(self):
        """"burn takes N at end of turn", unattributed, was true of nobody on screen."""
        html = INDEX.read_text()
        self.assertIn("who.burn_tick > 0", html)
        self.assertIn("off ${who.name} at end of turn", html)
