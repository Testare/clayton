"""The reporting grammar (notes/battle_compass.md sec 13)."""
import unittest

from claytonlib.battle_compass import tokens as tok


class TestRendering(unittest.TestCase):
    def test_hp_is_three_zero_padded_digits(self):
        self.assertEqual(tok.hp_token(50), "HP050")
        self.assertEqual(tok.hp_token(1), "HP001")
        self.assertEqual(tok.hp_token(714), "HP714")

    def test_hp_out_of_renderable_range_raises(self):
        """Three digits always suffice -- the largest Gen 4 HP stat is 714."""
        for value in (-1, 1000):
            with self.assertRaises(ValueError):
                tok.hp_token(value)

    def test_move_tokens_are_one_based(self):
        self.assertEqual(tok.our_move_token(0), "M1")
        self.assertEqual(tok.target_move_token(3), "E4")

    def test_out_of_range_slots_raise(self):
        for fn in (tok.our_move_token, tok.target_move_token):
            for slot in (-1, 4):
                with self.assertRaises(ValueError):
                    fn(slot)

    def test_prevented_tokens_put_the_status_after_the_actor(self):
        self.assertEqual(tok.prevented_token("E", "par"), "Epar")
        with self.assertRaises(ValueError):
            tok.prevented_token("X", "par")

    def test_ball_tokens_distinguish_the_two_ball_types(self):
        """A failed capture ball must not render like a failed standard ball, or the log cannot
        say which ball was spent."""
        self.assertEqual(tok.ball_token(1), "P1")
        self.assertEqual(tok.ball_token(1, capture_ball=True), "C1")
        self.assertEqual(tok.ball_token(0, captured=True), "Pc")
        self.assertEqual(tok.ball_token(0, captured=True, capture_ball=True), "C")

    def test_a_shake_count_above_three_is_a_capture_not_a_shake(self):
        with self.assertRaises(ValueError):
            tok.ball_token(4)

    def test_item_codes_must_be_lowercase_detail(self):
        self.assertEqual(tok.item_token("hp"), "Ihp")
        for bad in ("", "HP"):
            with self.assertRaises(ValueError):
                tok.item_token(bad)

    def test_switch_tokens_cover_the_party(self):
        self.assertEqual(tok.switch_token(1), "S1")
        for slot in (0, 7):
            with self.assertRaises(ValueError):
                tok.switch_token(slot)

    def test_the_worked_example_from_the_design_doc(self):
        path = tok.render_path([["E3", "h", tok.hp_token(50)],
                                ["Ihp", "E2", "!", "~", tok.hp_token(100)],
                                ["E4", "M2", "h"]])
        self.assertEqual(path, "E3hHP050 IhpE2!~HP100 E4M2h")


class TestTokenising(unittest.TestCase):
    """Provided for fixtures and bug reports; the tool itself only ever renders (sec 13.1)."""

    def test_longest_match_keeps_hp_together(self):
        self.assertEqual(tok.tokenise("E3hHP050"), ["E3h", "HP050"])

    def test_bag_action_then_move_then_hp(self):
        self.assertEqual(tok.tokenise("IhpE2!~HP100"), ["Ihp", "E2!~", "HP100"])

    def test_a_status_detail_starting_with_an_action_letter_is_not_split(self):
        """`par` begins with `p`, but details are lowercase so they cannot open an action."""
        self.assertEqual(tok.tokenise("Epar"), ["Epar"])
        self.assertEqual(tok.tokenise("M1hEpar"), ["M1h", "Epar"])

    def test_snapping_out_of_confusion_keeps_its_slot(self):
        self.assertEqual(tok.tokenise("Escfz2h"), ["Escfz2h"])

    def test_round_trips_a_rendered_path(self):
        path = "M1hE3!HP103 C1E3hHP059"
        self.assertEqual([tok.tokenise(t) for t in tok.split_turns(path)],
                         [["M1h", "E3!", "HP103"], ["C1", "E3h", "HP059"]])

    def test_text_with_no_action_prefix_raises(self):
        with self.assertRaises(ValueError):
            tok.tokenise("hhh")

    def test_a_longer_prefix_is_always_tried_first(self):
        """The scanner takes the FIRST prefix that matches, so order is the real invariant.

        Mostly the set is prefix-free -- "H" alone is deliberately not an action, which is what
        lets "HP" be two characters. "XX" is the exception: a wipe has to be tried before a
        single "X" or it would tokenise as two separate faints.
        """
        order = list(tok.ACTION_PREFIXES)
        for a in order:
            for b in order:
                if a != b and b.startswith(a):
                    self.assertLess(order.index(b), order.index(a),
                                    f"{b} extends {a} and must be tried before it")

    def test_a_wipe_is_one_token_not_two(self):
        self.assertEqual(tok.tokenise("XX"), ["XX"])
        self.assertEqual(tok.tokenise("E1hXX"), ["E1h", "XX"])


class TestValidation(unittest.TestCase):
    def test_a_well_formed_turn_has_no_problems(self):
        self.assertEqual(tok.validate_turn(tok.tokenise("M1hE2hHP120")), [])

    def test_taking_a_hit_without_reporting_hp_is_invalid(self):
        """The self-checking property: a forgotten HP is a parse error, not a wrong state."""
        problems = tok.validate_turn(tok.tokenise("E3h"))
        self.assertEqual(len(problems), 1)
        self.assertIn("HP token", problems[0])

    def test_a_turn_with_no_hit_needs_no_hp(self):
        self.assertEqual(tok.validate_turn(tok.tokenise("E4M2h")), [])

    def test_a_crit_also_requires_hp(self):
        self.assertTrue(tok.validate_turn(tok.tokenise("E3!")))

    def test_a_bag_action_after_a_move_is_invalid(self):
        """Bag actions resolve before any move, so they cannot appear after one (sec 12.1)."""
        problems = tok.validate_turn(["M1", "h", "Ihp"])
        self.assertTrue(any("resolve first" in p for p in problems))

    def test_nothing_may_follow_a_terminal_token(self):
        for terminal in ("C", "Pc"):
            self.assertTrue(tok.validate_turn([terminal, "E1"]), terminal)
        # A successful throw alone is the whole turn: the ball resolves first and ends the battle
        # before the target can act.
        self.assertEqual(tok.validate_turn(["C"]), [])

    def test_a_move_and_a_ball_cannot_share_a_turn(self):
        """You pick one action. A ball is a bag action and resolves before any move, so a turn
        containing both is impossible rather than merely unusual."""
        self.assertTrue(tok.validate_turn(["M1", "h", "C"]))

    def test_a_malformed_hp_token_is_reported(self):
        self.assertTrue(tok.validate_turn(["HPxyz"]))

    def test_hp_from_token_only_matches_hp(self):
        self.assertEqual(tok.hp_from_token("HP050"), 50)
        self.assertIsNone(tok.hp_from_token("HP5"))
        self.assertIsNone(tok.hp_from_token("M1"))


class TestPreventionAndResolutionMarkers(unittest.TestCase):
    """Sleep and freeze need no wearing-off marker -- the move happening proves the status
    ended. Confusion breaks that inference, because a confused Pokemon can attack normally, so
    snapping out is the one status change that must be reported explicitly (sec 13.4)."""

    def test_a_prevented_move_carries_no_slot(self):
        self.assertEqual(tok.prevented_token("M", "par"), "Mpar")
        self.assertEqual(tok.prevented_token("E", "slp"), "Eslp")
        self.assertEqual(tok.prevented_token("E", "fln"), "Efln")

    def test_a_confusion_self_hit_is_a_prevention(self):
        self.assertEqual(tok.prevented_token("M", "cfz"), "Mcfz")

    def test_snapping_out_of_confusion_keeps_its_slot(self):
        """The move completes, so a number always follows scfz."""
        self.assertEqual(tok.resolved_token("M", "scfz", 1), "Mscfz2")

    def test_a_resolution_token_takes_the_usual_move_detail(self):
        turn = [tok.resolved_token("M", "scfz", 1), tok.CRIT, tok.target_move_token(2), tok.HIT, tok.hp_token(60)]
        self.assertEqual(tok.render_turn(turn), "Mscfz2!E3hHP060")
        self.assertEqual(tok.validate_turn(turn), [])

    def test_longest_match_keeps_scfz_from_parsing_as_cfz(self):
        self.assertEqual(tok.tokenise("Mscfz2h"), ["Mscfz2h"])
        self.assertEqual(tok.STATUS_MARKERS[0], "scfz")

    def test_a_status_that_cannot_prevent_a_move_is_rejected(self):
        for status in ("brn", "psn", "scfz", "nonsense"):
            with self.assertRaises(ValueError, msg=status):
                tok.prevented_token("M", status)

    def test_a_prevention_marker_is_not_a_resolution_marker(self):
        with self.assertRaises(ValueError):
            tok.resolved_token("M", "par", 0)

    def test_a_prevention_with_a_slot_is_invalid(self):
        self.assertTrue(any("no slot may follow" in p
                            for p in tok.validate_turn(["Mpar2", tok.target_move_token(0)])))

    def test_a_resolution_without_a_slot_is_invalid(self):
        self.assertTrue(any("a slot must follow" in p
                            for p in tok.validate_turn(["Mscfz", tok.target_move_token(0)])))

    def test_our_confusion_self_hit_demands_an_hp_token(self):
        """It damages us with no E token present, which the earlier rule keyed on."""
        self.assertTrue(tok.turn_requires_hp(["Mcfz", tok.target_move_token(0)]))
        self.assertIn("the target hit us, so this turn needs an HP token",
                      tok.validate_turn(["Mcfz", tok.target_move_token(0)]))
        self.assertEqual(tok.validate_turn(["Mcfz", tok.hp_token(88), tok.target_move_token(0)]), [])

    def test_the_targets_confusion_self_hit_does_not(self):
        """It damages the target, not us."""
        self.assertFalse(tok.turn_requires_hp(["M1", tok.HIT, "Ecfz"]))


class TestAHealingItemRequiresHp(unittest.TestCase):
    """The rule has always read "present exactly when our HP changed, for ANY reason", but the
    healing-item case was missing. Since items actually heal now, the simulator emitted
    `IspEparHP150` while this said no HP was needed -- and the interview asks on the strength of
    this, so a potion turn was reported without the token the simulator predicts."""

    def test_a_potion_requires_it(self):
        self.assertTrue(tok.turn_requires_hp(["Isp", "Epar"]))
        self.assertTrue(tok.turn_requires_hp(["Ip", "Epar"]))
        self.assertTrue(tok.turn_requires_hp(["Imp", "Epar"]))

    def test_a_full_restore_requires_it(self):
        self.assertTrue(tok.turn_requires_hp(["Ifr", "Epar"]))

    def test_a_non_healing_item_does_not(self):
        """Full Heal cures status without restoring HP; the X items touch neither."""
        for code in ("fh", "xsd", "xd", "gs"):
            self.assertFalse(tok.turn_requires_hp([f"I{code}", "Epar"]), code)

    def test_an_unknown_item_code_does_not_crash(self):
        self.assertFalse(tok.turn_requires_hp(["Izzz", "Epar"]))

    def test_it_agrees_with_the_simulator_for_every_item(self):
        """The invariant that was broken: what the simulator renders and what the rule demands
        have to match, or a correct report is rejected or an incorrect one accepted."""
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.battle_compass import items
        from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
        from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
        from claytonlib.battle_compass.targets import moveset
        from claytonlib.moves import resolve_move

        hunt = HuntConfig(target_catch_rate=3)
        moves = moveset("suicune")
        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                       moves=("False Swipe",), pp=(40,), hp=100)
        target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                         stats=derive_species_stats("suicune", 40, "Bold"), moves=moves,
                         pp=tuple(resolve_move(m).pp for m in moves),
                         hp=1, status=Status.PARALYSIS)
        for entry in items.ITEMS:
            state = BattleState(ours=ours, target=target, rng=0xEC1504DC, phase=2)
            nxt = simulate_turn(state, Action.ITEM, hunt, item_code=entry.code)
            fragments = list(nxt.log[-1])
            emitted = any(t.startswith("HP") for t in tok.normalise(fragments))
            required = tok.turn_requires_hp(fragments)
            self.assertEqual(emitted, required,
                             f"{entry.name}: simulator emits HP={emitted}, rule requires "
                             f"{required}")


if __name__ == "__main__":
    unittest.main()


class TestNormalisation(unittest.TestCase):
    """The simulator emits fragments; the grammar's unit is the merged token. Rules that inspect
    tokens must normalise, or a check like "did anything hit us" silently never fires."""

    def test_fragments_and_merged_tokens_normalise_alike(self):
        fragments = ["M1", "h", "E3", "!", "HP103"]
        merged = ["M1h", "E3!", "HP103"]
        self.assertEqual(tok.normalise(fragments), merged)
        self.assertEqual(tok.normalise(merged), merged)

    def test_turn_requires_hp_works_on_either_form(self):
        for form in (["M1", "h", "E3", "!"], ["M1h", "E3!"]):
            self.assertTrue(tok.turn_requires_hp(form), form)
        for form in (["M1", "h", "E4"], ["M1h", "E4"]):
            self.assertFalse(tok.turn_requires_hp(form), form)

    def test_validation_works_on_either_form(self):
        self.assertTrue(tok.validate_turn(["M1", "h", "E3", "!"]))
        self.assertEqual(tok.validate_turn(["M1", "h", "E3", "!", "HP103"]), [])

class TestBallTokensAreValidated(unittest.TestCase):
    """The gap that let a winning turn be unreportable.

    A malformed ball token is still a well-formed *token* -- right prefix, right position -- so
    nothing in the grammar objected to it. It just matched no candidate's prediction, and the
    player saw a capture they could not report with no indication why. The run UI emitted "Cc",
    having appended the raw "caught it" answer to the "C" prefix; that works for a standard ball
    ("Pc") and is wrong for the capture ball, where the bare "C" IS the capture.
    """

    def test_the_malformed_capture_token_is_rejected(self):
        problems = tok.validate_turn(["Cc"])
        self.assertTrue(problems)
        self.assertIn("not a ball outcome", problems[0])

    def test_both_captures_are_accepted_and_are_the_only_suffixed_forms(self):
        self.assertEqual(tok.validate_turn(["C"]), [])
        self.assertEqual(tok.validate_turn(["Pc"]), [])
        self.assertTrue(tok.validate_turn(["Cp"]))
        self.assertTrue(tok.validate_turn(["P"]))

    def test_every_token_ball_token_can_produce_is_valid(self):
        """Keeps the renderer and the validator from disagreeing about the asymmetry."""
        produced = {tok.ball_token(0, True, capture_ball=True),
                    tok.ball_token(0, True, capture_ball=False)}
        produced |= {tok.ball_token(n, False, capture_ball=cb)
                     for cb in (True, False) for n in range(4)}
        self.assertEqual(produced, set(tok.BALL_TOKENS))
        for token in produced:
            self.assertEqual(tok.validate_turn([token]), [], token)

    def test_a_shake_count_out_of_range_is_rejected(self):
        self.assertTrue(tok.validate_turn(["C4"]))
        self.assertTrue(tok.validate_turn(["P9"]))
