"""Taunt, and the first move of ours that changes what the TARGET's turn costs.

Everything before it either hurt the target (False Swipe), statused it (Thunder Wave, Sing) or
degraded it (Flash, Screech). Taunt takes moves away: while it runs the target cannot *select* a
move with no power, which makes the whole status half of its moveset unavailable for 3-5 turns.

Against the configured encounters that is: Uxie's Yawn and Amnesia, Azelf's Nasty Plot, Heatran's
Metal Sound and Scary Face, Darkrai's Hypnosis, Nightmare and Double Team, Suicune's Rain Dance
and Mist, Ho-Oh's Safeguard, Latios's Protect and Refresh.

**The mechanism was not the obvious one, and the obvious one would have been wrong.** The ROM has
a `subscript_move_fail_taunted` whose message reads exactly like "the wild side picks a status
move and is then refused for it" -- and modelled that way, every taunted turn would have spent two
post-successful-move advances the game does not spend, and picked the wrong move besides. What
actually happens is that `TrainerAI_Init` zeroes the move's SCORE, so it drops out of the
max-score tie list the wild pick draws from and the selection modulus shrinks. See
`Battler.usable_slots`, which carries the citation.

**And then exactly one turn turned out to work the obvious way after all: the turn the Taunt
LANDS.** The score-zeroing happens at SELECTION time, so a target that chose before the Taunt
existed had nothing narrowed, and `CHECK_STATUS_STATE_TAUNT` refuses the move it already picked.
Measured in data/battle_logs/uxie1.jsonl turn 14 -- "The wild UXIE can't use Amnesia after the
taunt!", with `sub_seq:subscript_move_fail_taunted` on the phase record -- which is not a corner
case: a Taunt is thrown to land, and we outspeed a paralyzed target by construction. So both
halves are modelled, and they are modelled in different places: the narrowing in `usable_slots`,
the refusal in `sim.taunt_refuses` with a token of its own (`tokens.TAUNTED`).

(clayton-4wr.1.2, clayton-6xu.7.6)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import field_conditions, move_info
from claytonlib.battle_compass.sim import (
    EFFECT_TAUNT, MODELLED_OUR_EFFECTS, SOUND_MOVES, TAUNT_TURNS_MIN, TAUNT_TURNS_SPAN,
    HuntConfig, can_miss, execute_move, move_roll_cost, opening_rng, select_target_move,
    sent_out, simulate_turn, taunt_refuses, unselectable_reason, will_fail,
)
from claytonlib.battle import turn as turn_costs
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import moveset, target_ability
from claytonlib.moves import resolve_move

SEEDS = range(0x0C0E0200, 0x0C0E0240)

TAUNT = resolve_move("Taunt")


def _target(name: str, level: int = 50, **kwargs) -> Battler:
    moves = moveset(name)
    return replace(Battler(
        name=name, level=level, types=tuple(species(name)["types"]),
        stats=derive_species_stats(name, level, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability(name)), **kwargs)


def _honchkrow(**kwargs) -> Battler:
    """The Pokemon the kit is built around: Dark/Flying, Insomnia, carrying Taunt."""
    return replace(Battler(
        name="Honchkrow", level=55, types=("Dark", "Flying"), ability="Insomnia",
        stats={"hp": 250, "atk": 150, "def": 90, "spa": 120, "spd": 95, "spe": 110},
        moves=("Taunt", "Haze"), pp=(20, 30)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestWhatItCosts(unittest.TestCase):

    def test_it_lands_for_three_to_five_turns(self):
        """`subscript_taunt_start.s` is `Random 2, 3`, which `BtlCmd_Random` reads as
        ``(rand % (2 + 1)) + 3``."""
        self.assertEqual((TAUNT_TURNS_MIN, TAUNT_TURNS_SPAN), (3, 3))
        seen = set()
        for seed in SEEDS:
            _, outcome = execute_move(seed, TAUNT, _honchkrow(), _target("uxie"),
                                      actor="M", slot=0)
            seen.add(outcome.starts_taunt)
        self.assertEqual(seen, {3, 4, 5})

    def test_two_rolls_when_it_lands_and_one_when_it_fails(self):
        """Accuracy 100, so the accuracy roll is spent; the duration roll sits past the
        already-taunted check, so a second Taunt does not pay it."""
        self.assertEqual(move_roll_cost(TAUNT), 2)
        _, landed = execute_move(0x0C0E02CA, TAUNT, _honchkrow(), _target("uxie"),
                                 actor="M", slot=0)
        _, failed = execute_move(0x0C0E02CA, TAUNT, _honchkrow(),
                                 _target("uxie", taunted_turns=2), actor="M", slot=0)
        self.assertEqual((landed.rolls, failed.rolls), (2, 1))
        self.assertTrue(landed.successful)
        self.assertFalse(failed.successful)
        self.assertEqual(failed.starts_taunt, 0)

    def test_it_cannot_miss_but_still_spends_the_accuracy_roll(self):
        """100 accuracy at a neutral stage can never fail the check, and the roll is spent
        anyway -- `CheckMoveHitAccuracy` only skips it for accuracy 0."""
        self.assertFalse(can_miss(TAUNT, 0))
        self.assertEqual(TAUNT.accuracy, 100)

    def test_a_second_one_fails_rather_than_extending(self):
        self.assertFalse(will_fail(TAUNT, _target("uxie")))
        self.assertTrue(will_fail(TAUNT, _target("uxie", taunted_turns=1)))

    def test_the_counter_runs_down_and_spends_nothing_doing_it(self):
        """`MON_COND_CHECK_STATE_TAUNT` decrements and prints 'wore off'. No Random anywhere, so
        it needs no position inside the measured end-of-turn advances."""
        config = _config()
        # Nothing but Swift, so the target's own turn costs the same every turn and the only
        # thing that could move the per-turn total is the Taunt tick.
        state = BattleState(ours=_honchkrow(), target=_target("uxie", pp=(20, 0, 0, 0)),
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_1, config)          # Taunt lands
        rolled = state.target.taunted_turns + 1
        self.assertIn(rolled, (3, 4, 5))
        costs = []
        for _ in range(rolled):
            before = state.rng_offset
            state = simulate_turn(state, Action.ITEM, config, item_code="xsd")
            costs.append(state.rng_offset - before)
        self.assertEqual(state.target.taunted_turns, 0)
        self.assertEqual(len(set(costs)), 1, costs)   # the wear-off turn costs what the rest do

    def test_it_is_listed_as_modelled_for_our_side(self):
        self.assertIn(EFFECT_TAUNT, MODELLED_OUR_EFFECTS)
        self.assertIsNone(unselectable_reason(TAUNT))

    def test_it_is_not_a_sound_move(self):
        """Easy to assume, since Uproar and Screech are. `sSoundMoves` is twelve moves by name and
        Taunt is not one, so Soundproof does not block it."""
        self.assertNotIn("taunt", SOUND_MOVES)


class TestItNarrowsTheSelectionModulus(unittest.TestCase):
    """The load-bearing half, and the one a wrong reading of the ROM would have got backwards."""

    def test_a_taunted_uxie_picks_from_two_slots_rather_than_four(self):
        free = _target("uxie")
        taunted = _target("uxie", taunted_turns=3)
        self.assertEqual(free.usable_slots(), (0, 1, 2, 3))
        # Swift and Future Sight have power; Yawn and Amnesia do not.
        self.assertEqual(taunted.usable_slots(), (0, 2))

    def test_the_narrowing_is_by_POWER_not_by_category(self):
        """The ROM's own test is `moveTable[moveCur].power == 0`. The same set in practice for
        every configured moveset, so this pins the rule rather than the outcome."""
        for name, expected in (("uxie", (0, 2)),
                               ("azelf", (0, 1, 2)),        # only Nasty Plot is power 0
                               ("heatran", (1, 3)),         # Crunch and Lava Plume
                               ("suicune", (1, 2)),         # Gust and Aurora Beam
                               ("darkrai", (1,))):          # Faint Attack alone
            with self.subTest(name):
                self.assertEqual(_target(name, taunted_turns=3).usable_slots(), expected)
                for slot in expected:
                    self.assertTrue(_target(name).move(slot).power)

    def test_the_selection_roll_is_still_spent_even_at_a_modulus_of_one(self):
        """A taunted Darkrai has exactly one pickable move, and the ROM still rolls:
        `maxScoreMoveSlots[RandNext % numMaxScoreMoves]` spends its roll at a count of one."""
        rng = 0x12345678
        after, slot = select_target_move(rng, _target("darkrai", taunted_turns=3))
        self.assertEqual(slot, 1)
        self.assertNotEqual(after, rng)

    def test_a_taunted_target_with_no_damaging_move_left_would_struggle(self):
        """Taunt is the first thing that can put a target there, so the existing None path has a
        second way to be reached. Struggle is outside the model and the solver refuses to search
        into it, which is why this asserts the signal rather than a behaviour."""
        stuck = _target("darkrai", taunted_turns=3, pp=(20, 0, 20, 20))
        self.assertEqual(stuck.usable_slots(), ())
        _, slot = select_target_move(0x12345678, stuck)
        self.assertIsNone(slot)

    def test_the_modulus_really_changes_which_move_comes_out(self):
        """End to end: over a seed sweep a free Uxie uses all four slots and a taunted one uses
        only the two it may."""
        config = _config()
        for taunted, expected in ((False, {"E1", "E2", "E3", "E4"}), (True, {"E1", "E3"})):
            seen = set()
            for seed in SEEDS:
                target = _target("uxie", taunted_turns=20 if taunted else 0)
                state = BattleState(ours=_honchkrow(), target=target,
                                    rng=opening_rng(seed, config))
                for _ in range(4):
                    state = simulate_turn(state, Action.ITEM, config, item_code="xsd")
                    seen.update(p[:2] for p in state.log[-1] if p.startswith("E"))
                    if state.over:
                        break
            with self.subTest(taunted=taunted):
                self.assertEqual(seen, expected)

    def test_a_still_narrower_modulus_is_blind_between_siblings_too(self):
        """%2 divides 256, so the narrowing adds nothing on the RTC-second axis -- worth pinning
        because "fewer options" reads like "more information" (notes/platinum.md 15.6).

        Asserted on the SELECTED SLOTS rather than on the whole rendered path, which is the
        claim: two seeds an RTC second apart pick the same move every turn. Their paths can still
        differ, and do -- a Future Sight's 90% check is the one non-blind roll either target
        makes, and it is what separates them when anything does.
        """
        config = _config()
        separated_only_by_the_hit_check = 0
        for base in range(0x0C0E0200, 0x0C0E0210):
            slots, paths = [], []
            for seed in (base, (base + (1 << 24)) & 0xFFFFFFFF):
                state = BattleState(ours=_honchkrow(), target=_target("uxie", taunted_turns=20),
                                    rng=opening_rng(seed, config))
                for _ in range(6):
                    state = simulate_turn(state, Action.ITEM, config, item_code="xsd")
                    if state.over:
                        break
                paths.append(tok.render_path(state.log))
                slots.append([p[:2] for turn in state.log for p in turn if p.startswith("E")])
            with self.subTest(f"{base:#x}"):
                self.assertEqual(slots[0], slots[1])
            if paths[0] != paths[1]:
                separated_only_by_the_hit_check += 1
        # And the control: if nothing ever separated, the slot equality above would be vacuous
        # agreement between two runs of a blind simulator rather than a statement about moduli.
        self.assertGreater(separated_only_by_the_hit_check, 0)


class TestTheInterviewCannotOfferAMoveTheTargetCannotPick(unittest.TestCase):
    """An answer the game could not have produced eliminates every candidate rather than
    contradicting one, which is the worst failure the interview has."""

    def test_move_info_reports_selectability(self):
        info = {m["name"]: m for m in move_info(_target("uxie", taunted_turns=3), _honchkrow())}
        self.assertTrue(info["Swift"]["selectable"])
        self.assertTrue(info["Future Sight"]["selectable"])
        self.assertFalse(info["Yawn"]["selectable"])
        self.assertFalse(info["Amnesia"]["selectable"])

    def test_an_untaunted_target_offers_everything(self):
        info = move_info(_target("uxie"), _honchkrow())
        self.assertTrue(all(m["selectable"] for m in info))

    def test_the_flag_covers_the_pre_existing_zero_pp_case_too(self):
        """It was already wrong in the same way: a 0-PP move was offered as an answer. One flag,
        read off `usable_slots`, fixes both."""
        info = {m["name"]: m for m in move_info(_target("uxie", pp=(0, 10, 15, 20)), _honchkrow())}
        self.assertFalse(info["Swift"]["selectable"])
        self.assertTrue(info["Yawn"]["selectable"])

    def test_an_empty_slot_carries_the_key_rather_than_omitting_it(self):
        """The page reads the flag unconditionally, and `undefined` would filter as falsey by
        luck rather than by design."""
        two_moves = replace(_target("uxie"), moves=("Swift", "Yawn"), pp=(20, 10))
        for entry in move_info(two_moves, _honchkrow()):
            self.assertIn("selectable", entry)

    def test_the_page_filters_on_it(self):
        from pathlib import Path

        html = Path("app/web/index.html").read_text()
        self.assertIn("m.known && m.selectable", html)


class TestTheStateItLivesIn(unittest.TestCase):

    def test_the_counter_is_reported_in_the_field_banner(self):
        state = BattleState(ours=_honchkrow(), target=_target("uxie", taunted_turns=4), rng=0)
        (taunt,) = field_conditions(state)
        self.assertEqual(taunt, {"name": "Taunt", "turns": 4, "whose": "target"})

    def test_a_send_out_clears_it(self):
        """`tauntedTurns` lives in `moveEffectsData`, which a fresh BattleMon zeroes -- the same
        family as the drowsy counter."""
        self.assertEqual(sent_out(_honchkrow(taunted_turns=3)).taunted_turns, 0)

    def test_a_faint_clears_it(self):
        fainted = _honchkrow(taunted_turns=3).with_hp(0)
        self.assertEqual(fainted.taunted_turns, 0)

    def test_our_own_side_can_hold_the_counter_for_symmetry(self):
        """Unreachable -- no configured target has Taunt -- but the two halves of a turn are meant
        to differ only in which side they read, and what it would mean is worth stating: our own
        status moves would stop being selectable, the paralyzer included."""
        us = _honchkrow(moves=("Taunt", "Thunder Wave"), pp=(20, 20), taunted_turns=3)
        self.assertEqual(us.usable_slots(), ())


class TestWhatItBuysPerTarget(unittest.TestCase):
    """One assertion per configured encounter, because the answer differs and the differences are
    what a player picks a party on."""

    def test_it_shuts_uxies_yawn_which_is_the_point_against_that_target(self):
        config = _config()
        state = BattleState(ours=_honchkrow(), target=_target("uxie"),
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertGreater(state.target.taunted_turns, 0)
        for _ in range(state.target.taunted_turns):
            state = simulate_turn(state, Action.ITEM, config, item_code="xsd")
            self.assertEqual(state.ours.drowsy_turns, 0)

    def test_it_shuts_azelfs_nasty_plot(self):
        taunted = _target("azelf", taunted_turns=3)
        self.assertNotIn(3, taunted.usable_slots())
        self.assertEqual(taunted.spatk_stage, 0)

    def test_it_shuts_both_of_heatrans_two_stage_drops(self):
        """The strongest single thing in the kit: Metal Sound and Scary Face are both power 0."""
        taunted = _target("heatran", taunted_turns=3)
        for slot, name in enumerate(moveset("heatran")):
            if resolve_move(name).power == 0:
                with self.subTest(name):
                    self.assertNotIn(slot, taunted.usable_slots())

    def test_against_darkrai_it_leaves_one_move(self):
        """Three of the four are power 0 -- Hypnosis, Nightmare and Double Team -- so a taunted
        Darkrai can only Faint Attack, which a Dark/Flying carrier takes at x0.5."""
        self.assertEqual(_target("darkrai", taunted_turns=3).usable_slots(), (1,))

    def test_against_giratina_it_buys_nothing(self):
        """All four of its moves have power, so the modulus does not move. Worth a test so the
        advice does not claim otherwise."""
        for key in ("giratina-altered", "giratina-origin"):
            with self.subTest(key):
                target = _target(key)
                self.assertEqual(target.usable_slots(),
                                 replace(target, taunted_turns=3).usable_slots())


class TestItRunsEndToEnd(unittest.TestCase):

    def test_a_taunted_sweep_of_every_target_stays_grammatical(self):
        config = _config()
        for name in ("uxie", "azelf", "heatran", "darkrai", "suicune"):
            for seed in SEEDS:
                state = BattleState(ours=_honchkrow(),
                                    target=_target(name, taunted_turns=20),
                                    rng=opening_rng(seed, config))
                for _ in range(5):
                    state = simulate_turn(state, Action.ITEM, config, item_code="xsd")
                    problems = tok.validate_turn(state.log[-1])
                    self.assertEqual(problems, [],
                                     f"{name} {seed:#x}: {tok.render_turn(state.log[-1])}")
                    if state.over:
                        break

    def test_taunting_and_then_re_taunting_across_a_run_never_raises(self):
        config = _config()
        for seed in SEEDS:
            state = BattleState(ours=_honchkrow(), target=_target("uxie"),
                                rng=opening_rng(seed, config))
            for _ in range(12):
                state = simulate_turn(state, Action.MOVE_1, config)
                if state.over:
                    break


if __name__ == "__main__":
    unittest.main()


class TestTheLandingTurnRefusesAnAlreadySelectedMove(unittest.TestCase):
    """clayton-6xu.7.6. The one turn the refusal path fires, and it is the commonest Taunt turn
    there is.

    Every turn here has the target PARALYZED, which is not a contrivance: a free Lv50 Uxie
    outspeeds Honchkrow (121 to 110) and so moves before the Taunt can land, and paralysis is the
    Phase 2 precondition anyway. Quartered to 30 it moves second, which is the only arrangement
    in which the refusal is reachable at all.
    """

    def test_the_predicate_is_the_roms_power_test(self):
        """``tauntedTurns && moveTable[moveCur].power == 0``, by POWER not by category."""
        taunted = _target("uxie", taunted_turns=3)
        self.assertTrue(taunt_refuses(resolve_move("Amnesia"), taunted))
        self.assertTrue(taunt_refuses(resolve_move("Yawn"), taunted))
        self.assertFalse(taunt_refuses(resolve_move("Swift"), taunted))
        self.assertFalse(taunt_refuses(resolve_move("Future Sight"), taunted))

    def test_an_untaunted_actor_is_never_refused(self):
        free = _target("uxie")
        self.assertFalse(any(taunt_refuses(resolve_move(m), free) for m in moveset("uxie")))

    def _landing_turns(self):
        """(seed, state-after) for every seed whose Taunt turn ends in a refusal."""
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0300):
            state = BattleState(ours=_honchkrow(),
                                target=_target("uxie", status=Status.PARALYSIS),
                                rng=opening_rng(seed, config))
            after = simulate_turn(state, Action.MOVE_1, config)   # Honchkrow's Taunt
            if any(p.endswith(tok.TAUNTED) for p in after.log[-1]):
                yield seed, after

    def test_the_landing_turn_renders_a_tnt_token_naming_the_slot(self):
        """Over a seed sweep, some Uxies had picked Yawn or Amnesia before the Taunt resolved;
        those turns must render the slot and the refusal, not a bare slot and not a prevention."""
        refusals = {p for _, after in self._landing_turns()
                    for p in after.log[-1] if p.endswith(tok.TAUNTED)}
        # Yawn is slot 2 and Amnesia slot 4 of the Uxie moveset, and nothing else can be refused.
        self.assertEqual(refusals, {"E2" + tok.TAUNTED, "E4" + tok.TAUNTED})
        self.assertNotIn("E" + tok.TAUNTED, refusals,
                         "the slot must be kept, unlike every other prevention")

    def test_a_refused_turn_is_a_well_formed_turn(self):
        for seed, after in self._landing_turns():
            with self.subTest(f"{seed:#x}"):
                self.assertEqual(tok.validate_turn(after.log[-1]), [])

    def test_the_refused_side_contributes_nothing_and_pays_no_paralysis_roll(self):
        """The exact advance count, which is the point of the whole issue.

        One selection roll, the four before-turn advances, our Taunt's accuracy and duration
        rolls plus its two post-successful-move advances, the two between-turn advances, NOTHING
        for the target, and the four end-of-turn advances.

        The paralysis roll is the part that has to be absent. The ROM's taunt test is state 6 of
        the before-move walk and the paralysis roll is state 11, and a refusal returns
        CHECK_STATUS_DISRUPT_MOVE -- so a taunted and paralyzed target never reaches it. One
        extra here would be that roll, and Uxie is paralyzed in every real run.
        """
        expected = (1                                          # the wild selection roll
                    + turn_costs.BEFORE_TURN_ADVANCES          # 4
                    + 2                                        # Taunt: accuracy + duration
                    + turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES  # 2
                    + turn_costs.BETWEEN_TURN_ADVANCES         # 2
                    + 0                                        # the refused target
                    + turn_costs.END_OF_TURN_ADVANCES)         # 4
        counted = 0
        for seed, after in self._landing_turns():
            counted += 1
            with self.subTest(f"{seed:#x}"):
                self.assertEqual(after.rng_offset, expected)
        self.assertGreater(counted, 5, "the sweep produced too few refusals to measure")

    def test_a_refused_turn_is_the_cheapest_taunt_turn_there_is(self):
        """Same action, same Honchkrow, same Taunt landing — so our half of the turn is identical
        and the only difference is what the target did with its own half.

        Compared against the Taunt turns of the same sweep where the target had picked a damaging
        move instead and so was not refused. Not compared against an EXECUTED status move,
        because that is not apples to apples here: Yawn against Honchkrow's Insomnia fails free,
        which makes it cheaper than Amnesia and muddies the number the test is about.
        """
        config = _config()
        refused, allowed = set(), set()
        for seed in range(0x0C0E0200, 0x0C0E0300):
            after = simulate_turn(
                BattleState(ours=_honchkrow(), target=_target("uxie", status=Status.PARALYSIS),
                            rng=opening_rng(seed, config)), Action.MOVE_1, config)
            theirs = [p for p in after.log[-1] if p.startswith("E")]
            if any(p.endswith(tok.TAUNTED) for p in theirs):
                refused.add(after.rng_offset)
            elif theirs and theirs[0][1:2] in "13":     # Swift or Future Sight: never refused
                allowed.add(after.rng_offset)
        self.assertTrue(refused and allowed, "the sweep did not produce both kinds of turn")
        self.assertLess(max(refused), min(allowed))

    def test_the_prose_names_the_move(self):
        """The whole reason the token keeps its slot: the game announced which move it was."""
        lines = " ".join(tok.explain_turn(
            ("M1", "E2" + tok.TAUNTED),
            ours="Honchkrow", ours_moves=("Taunt", "Haze"),
            target="Uxie", target_moves=("Swift", "Yawn", "Future Sight", "Amnesia")))
        self.assertIn("Yawn", lines)
        self.assertIn("taunt", lines.lower())
