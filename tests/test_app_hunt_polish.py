"""The nine run-page items from notes/feedback_battle_compass.md.

Mostly static checks on the page, since there is no JS engine here -- but each one pins the
*reason* the change was made, so a later edit that undoes it fails with the explanation attached
rather than with "string not found".
"""
import json
import pathlib
import re
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore
from claytonlib.battle.catch import SHAKE_MESSAGES, shake_message
from claytonlib.battle_compass import tokens as tok

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"
HTML = INDEX.read_text()

OURS_MOVES = ("False Swipe", "Mean Look", "Sweet Scent", "Spore")
TARGET_MOVES = ("Rain Dance", "Gust", "Aurora Beam", "Mist")
PROSE = dict(ours="Smeargle", ours_moves=OURS_MOVES, target="Suicune",
             target_moves=TARGET_MOVES, capture_ball="Fast Ball")


class TestShakeMessages(unittest.TestCase):
    """1. "Remembering the message is easier than remembering the shake count." So the message is
    the chip's label and the count is its subtitle, which is the way round a player recalls it."""

    def test_the_ladder_is_the_rom_one(self):
        """Strictly ordered, and the pair in the middle is the one that gets transcribed wrong:
        "Almost had it" is TWO and "so close, too" is three."""
        self.assertEqual(shake_message(0), "Oh, no! The Pokémon broke free!")
        self.assertEqual(shake_message(1), "Aww! It appeared to be caught!")
        self.assertEqual(shake_message(2), "Aargh! Almost had it!")
        self.assertEqual(shake_message(3), "Gah! It was so close, too!")

    def test_out_of_range_raises_rather_than_wrapping(self):
        for n in (-1, 4, 99):
            with self.assertRaises(ValueError):
                shake_message(n)

    def test_the_page_list_matches_the_python_one_exactly(self):
        """The cross-boundary check. A page that drifted here would have the player report a
        shake count they never saw -- and this component has already been bitten three times by
        a convention written in one module and read in another with no test spanning both."""
        block = HTML[HTML.index("const HR_SHAKE_MESSAGES = ["):]
        block = block[:block.index("];") + 2]
        page = re.findall(r'"((?:[^"\\]|\\.)*)"', block)
        decoded = [json.loads(f'"{item}"') for item in page]
        self.assertEqual(decoded, list(SHAKE_MESSAGES))

    def test_the_chips_are_labelled_by_message_with_the_count_as_the_hint(self):
        self.assertIn("const opts = HR_SHAKE_MESSAGES.map((msg, n) => hrChip(", HTML)
        self.assertIn("What did the game say?", HTML)

    def test_the_count_is_still_shown_once_chosen(self):
        """Because the token is written in shakes, so the player should see the translation."""
        self.assertIn("That is\n        <b>${Number(t.ours.result)} shake", HTML)


class TestPlainLanguageTurns(unittest.TestCase):
    """2 and 7 share this: one renderer for the solver's recommendation and the history tooltip,
    so they cannot describe the same turn differently."""

    def test_a_full_turn_reads_as_sentences(self):
        self.assertEqual(
            tok.explain_turn(["M1hE3h~HP103"], **PROSE),
            ["Smeargle used False Swipe and hit Suicune",
             "Suicune used Aurora Beam and hit Smeargle, and its extra effect happened",
             "Smeargle ended the turn on 103 HP"])

    def test_every_prevention_marker_has_words(self):
        """Checked against the prose table rather than by asserting the code is absent from the
        output -- "par" is a substring of "paralyzed", so that assertion passed for the wrong
        reason and would have missed a marker that really did fall through."""
        for marker in tok.PREVENTION_DETAIL:
            said = tok.explain_turn([f"E{marker}"], **PROSE)[0]
            self.assertTrue(said.startswith("Suicune "), said)
            self.assertNotEqual(said, f"Suicune {marker}",
                                f"{marker} fell through to its raw code")
            self.assertIn(marker, tok._PREVENTION_PROSE, f"{marker} has no entry in the table")

    def test_a_miss_and_a_crit_are_distinguished(self):
        self.assertIn("missed", tok.explain_turn(["M4-"], **PROSE)[0])
        self.assertIn("critical hit", tok.explain_turn(["M1!"], **PROSE)[0])

    def test_the_two_captures_say_which_is_the_win(self):
        self.assertIn("run is won", tok.explain_turn(["C"], **PROSE)[0])
        self.assertIn("WRONG ball", tok.explain_turn(["Pc"], **PROSE)[0])

    def test_a_ball_throw_quotes_the_message_the_player_saw(self):
        said = tok.explain_turn(["C2"], **PROSE)[0]
        self.assertIn("Aargh! Almost had it!", said)
        self.assertIn("2 shakes", said)

    def test_one_shake_is_singular(self):
        self.assertIn("1 shake)", tok.explain_turn(["C1"], **PROSE)[0])

    def test_an_item_is_named_when_a_lookup_is_given(self):
        said = tok.explain_turn(["Ihp"], item_name=lambda c: "a Hyper Potion", **PROSE)[0]
        self.assertIn("Hyper Potion", said)

    def test_without_a_lookup_it_degrades_to_the_code_rather_than_raising(self):
        self.assertIn("hp", tok.explain_turn(["Ihp"], **PROSE)[0])

    def test_an_unknown_move_slot_falls_back_to_its_number(self):
        """A bench Pokemon with fewer moves must not index off the end."""
        self.assertIn("move 4", tok.explain_turn(["M4h"], ours="X", ours_moves=("Tackle",),
                                                 target="Y")[0])

    def test_no_token_the_simulator_renders_is_left_as_a_bare_code(self):
        """Swept over a real run so this cannot pass by only covering the tokens I thought of."""
        from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
        from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.moves import resolve_move

        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                       moves=OURS_MOVES, pp=(40, 5, 20, 15))
        target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                         stats=derive_species_stats("suicune", 40, "Bold"), moves=TARGET_MOVES,
                         pp=tuple(resolve_move(m).pp for m in TARGET_MOVES),
                         hp=1, status=Status.PARALYSIS)
        hunt = HuntConfig(target_catch_rate=3)
        seen = set()
        for seed in range(0xEC1504DC, 0xEC1504DC + 120):
            for action in (Action.MOVE_1, Action.MOVE_3, Action.MOVE_4,
                           Action.CAPTURE_BALL, Action.STANDARD_BALL):
                state = BattleState(ours=ours, target=target,
                                    rng=opening_rng(seed, hunt), phase=2)
                nxt = simulate_turn(state, action, hunt)
                seen |= set(tok.normalise(nxt.log[-1]))
        self.assertGreater(len(seen), 10)
        for token in seen:
            said = tok.explain_turn([token], **PROSE)[0]
            self.assertNotEqual(said, token, f"{token} has no plain-language form")


class TestTheSessionExplainsItsOwnTurns(unittest.TestCase):
    def setUp(self):
        from tests.test_battle_compass_capture_turn import _pinned_session
        self.session = _pinned_session()

    def test_the_recommended_step_carries_its_explanation(self):
        nxt = self.session.snapshot()["solution"]["next"]
        self.assertTrue(nxt["explain"])
        self.assertIn("Fast Ball", nxt["explain"][0])

    def test_each_reported_turn_carries_one(self):
        from claytonlib.battle_compass.state import Action
        seed = self.session.survivors[0]
        self.session.observe(Action.MOVE_1, (self.session.predict(Action.MOVE_1)[seed],))
        turn = self.session.snapshot()["turns"][0]
        self.assertTrue(turn["explain"])
        self.assertIn("False Swipe", " ".join(turn["explain"]))

    def test_the_history_is_replayed_so_a_pre_switch_turn_names_the_right_moves(self):
        """`explain` uses the CURRENT active Pokemon, which is right for a recommendation and
        wrong for history. `explain_history` replays instead -- which is the same hazard that
        keeps the action column in codes."""
        self.assertIn("def explain_history", (
            pathlib.Path(__file__).resolve().parent.parent
            / "claytonlib" / "battle_compass" / "hunt_session.py").read_text())


class TestTheOneClickConfirm(unittest.TestCase):
    """2. Reporting through the interview is five or six clicks, and in Phase 2 the predicted
    turn is overwhelmingly what happened."""

    def test_the_box_exists_and_asks_the_question(self):
        self.assertIn("function hrExpectedBlock(", HTML)
        self.assertIn("Did this happen?", HTML)

    def test_it_lists_the_turn_in_words_not_tokens(self):
        self.assertIn("(next.explain || []).map(line", HTML)

    def test_it_still_shows_the_token_it_would_report(self):
        """So a player who does know the grammar can check it before committing."""
        self.assertIn("Reports <code>${esc(next.expect)}</code>", HTML)

    def test_confirming_bypasses_the_interview_entirely(self):
        """No interview state involved, so a half-filled form cannot leak into the report."""
        body = HTML[HTML.index("function hrConfirmExpected()"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn('huntRunDo("hunt_session_observe", next.action, [next.expect]', body)
        self.assertNotIn("_hrTurn", body)

    def test_it_passes_the_solvers_own_item_code(self):
        """The field whose absence had the solver pricing one potion and simulating another."""
        body = HTML[HTML.index("function hrConfirmExpected()"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("next.item || null", body)

    def test_the_interview_is_still_rendered_below_it(self):
        """The whole point of Phase 2 is catching the turn that does NOT match."""
        self.assertIn('${s.over ? "" : hrExpectedBlock()}', HTML)
        self.assertIn("Report the turn you just played", HTML)

    def test_it_is_hidden_once_the_run_is_over(self):
        body = HTML[HTML.index("function hrExpectedBlock()"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("s.over", body)


class TestTheHoverBug(unittest.TestCase):
    """3. `.chip:hover` replaced `.chip.active`'s grass background while leaving
    `color:var(--grass-ink)` -- near-black ink on the near-black surface-2, so the SELECTED chip
    vanished under the cursor."""

    def test_the_active_chip_has_its_own_hover(self):
        self.assertIn(".chip.active:hover:not(:disabled)", HTML)

    def test_it_keeps_both_the_background_and_the_ink(self):
        rule = HTML[HTML.index(".chip.active:hover:not(:disabled)"):]
        rule = rule[:rule.index("}") + 1]
        self.assertIn("background:var(--grass)", rule)
        self.assertIn("color:var(--grass-ink)", rule)

    def test_it_still_gives_hover_feedback(self):
        rule = HTML[HTML.index(".chip.active:hover:not(:disabled)"):]
        rule = rule[:rule.index("}") + 1]
        self.assertIn("brightness", rule)

    def test_it_follows_the_fix_buttons_already_had(self):
        """`.btn.primary:hover` solved this with brightness long ago; the chip just never got it."""
        self.assertIn(".btn.primary:hover{filter:brightness(1.05)}", HTML)


class TestUndoAndTheTurnCounter(unittest.TestCase):
    """4 and 5."""

    def test_undo_sits_with_the_turn_history(self):
        panel = HTML[HTML.index('<div class="section-label">Turns so far</div>'):]
        panel = panel[:panel.index("`);")]
        self.assertIn("Undo last turn", panel)

    def test_it_is_rendered_from_the_first_turn_rather_than_the_second(self):
        """It used to live inside the report block, which only appears once a whole other turn
        has been answered -- so the button was missing exactly when it was wanted."""
        report = HTML[HTML.index('<div class="hr-confirm">'):]
        report = report[:report.index("return blocks.join")]
        self.assertNotIn("Undo last turn", report)

    def test_a_disabled_undo_explains_itself(self):
        self.assertIn("Nothing reported yet.", HTML)

    def test_the_turn_counter_is_on_the_phase_line(self):
        line = HTML[HTML.index('<div class="hr-phase">${esc(s.phase_label)}'):]
        line = line[:line.index("</div>")]
        self.assertIn("Turn ${s.turns.length + (s.over ? 0 : 1)}", line)

    def test_it_counts_the_turn_being_played_not_the_ones_done(self):
        """"Turn 5" should mean the one you are about to report -- and stop advancing once the
        run is over, where there is no next turn."""
        self.assertIn("(s.over ? 0 : 1)", HTML)


class TestPartyStatFieldsFit(unittest.TestCase):
    """6. Six columns in a 440px modal left about one digit of visible text once the input
    padding and the number spinner were taken out."""

    def test_the_party_form_opens_wide(self):
        self.assertIn("`, true);   // wide: six stat columns", HTML)

    def test_the_narrow_columns_lose_the_spinner(self):
        self.assertIn(".grid6 .field input[type=number]{appearance:textfield", HTML)

    def test_they_get_tighter_padding_and_cannot_overflow(self):
        rule = HTML[HTML.index(".grid6 .field input{"):]
        rule = rule[:rule.index("}") + 1]
        self.assertIn("min-width:0", rule)
        self.assertIn("padding-left:7px", rule)

    def test_the_grid_tracks_can_actually_shrink(self):
        """A bare 1fr has an auto minimum, so an input's intrinsic width can push a track past
        its share and overflow the row."""
        self.assertIn(".grid6{display:grid;grid-template-columns:repeat(6,minmax(0,1fr))", HTML)


class TestTheSpreadPopup(unittest.TestCase):
    """8. The search screen shows the spread BEFORE the catch; this shows it during, which is
    when the player can finally hold it next to the Pokemon."""

    def test_the_snapshot_carries_the_full_spread_for_both_sides(self):
        from tests.test_battle_compass_capture_turn import _pinned_session
        snap = _pinned_session().snapshot()
        for side in ("ours", "target"):
            self.assertEqual(set(snap[side]["stats"]),
                             {"hp", "atk", "def", "spa", "spd", "spe"}, side)
            self.assertIsNotNone(snap[side]["level"])
            self.assertTrue(snap[side]["types"])

    def test_the_target_bar_has_a_button_for_it(self):
        self.assertIn("function hrShowSpread(", HTML)
        self.assertIn('onclick="hrShowSpread(\'${side}\')"', HTML)

    def test_both_sides_get_one(self):
        self.assertIn('hrSide("Us:", s.ours, s.danger_floor, "ours")', HTML)
        self.assertIn('hrSide("Target:", s.target, 0, "target")', HTML)

    def test_the_target_popup_says_the_numbers_are_derived_and_what_a_mismatch_means(self):
        self.assertIn("Derived from the nature and IVs", HTML)
        self.assertIn("working from the wrong Pokémon", HTML)

    def test_our_popup_says_they_were_entered_by_hand_instead(self):
        self.assertIn("Entered from the in-game summary screen", HTML)

    def test_it_shows_the_paralysed_speed_alongside_the_raw_one(self):
        """Raw Speed is what the summary screen shows; effective Speed is what decides turn
        order. Showing only one makes the other look wrong."""
        self.assertIn("after paralysis", HTML)


class TestTextIsSelectableAndCopyable(unittest.TestCase):
    """9. "Why can't I select any of the text?" -- both halves of the offer, since each is cheap
    and the cause was outside the page's own CSS."""

    def test_selection_is_stated_rather_than_left_to_the_host(self):
        self.assertIn("-webkit-user-select:text;user-select:text", HTML)

    def test_controls_stay_unselectable(self):
        """Dragging across a chip row should not leave the labels highlighted."""
        self.assertIn("button,.chip,.btn{-webkit-user-select:none;user-select:none}", HTML)

    def test_the_seeds_and_the_path_are_click_to_copy(self):
        self.assertIn("function hrCopyable(", HTML)
        self.assertIn('hrCopyable(s.identified, "the battle seed")', HTML)
        self.assertIn('hrCopyable(a.seed_hex, "Seed A")', HTML)
        self.assertIn('hrCopyable(s.path, "the path so far")', HTML)

    def test_it_falls_back_to_a_selection_when_there_is_no_clipboard(self):
        """A packaged webview may not expose navigator.clipboard, and a toast saying "copy
        failed" is worse than selecting the text so Ctrl+C works."""
        self.assertIn("function hrSelect(", HTML)
        self.assertIn("Selected — press Ctrl+C.", HTML)

    def test_copying_confirms_itself(self):
        """A click with no feedback reads as a click that did nothing."""
        self.assertIn('el.textContent = "copied"', HTML)


class TestNothingRegressed(unittest.TestCase):
    def test_the_page_still_defines_every_handler_the_new_markup_calls(self):
        run = HTML[HTML.index("// --- Battle Compass: the live run"):]
        run = run[:run.index("async function huntConfigure(id){")]
        builtins = {"preventDefault", "stopPropagation", "focus", "blur", "click", "if"}
        referenced = set(re.findall(r'onclick="(\w+)\(', run))
        for handler in re.findall(r'onkeydown="([^"]*)"', run):
            referenced |= set(re.findall(r"(\w+)\(", handler))
        for name in referenced - builtins:
            self.assertTrue(f"function {name}(" in HTML or f"{name} = " in HTML,
                            f"markup calls {name}() but nothing defines it")

    def test_a_run_still_starts_and_reports_a_turn(self):
        from tests.test_app_hunt_seed_a import _ready_hunt
        facade, hunt_id = _ready_hunt()
        started = facade.hunt_session_start(hunt_id)
        sid, truth = started["session_id"], started["snapshot"]["candidates"][0]["seed"]
        predicted = facade.hunt_session_predict(sid, "M1")[truth]
        snap = facade.hunt_session_observe(sid, "M1", [predicted])
        self.assertEqual(len(snap["turns"]), 1)
        self.assertTrue(snap["turns"][0]["explain"])
