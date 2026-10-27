"""Foresight and Odor Sleuth — the move that makes a Ghost target catchable at all.

Giratina is **Ghost/Dragon** and False Swipe is **Normal**, so the chip phase against it is not
merely slow, it is impossible: the one damaging move that cannot knock the target out does
nothing whatsoever. Both formes have the problem and nothing in a party sidesteps it, because
False Swipe's 1 HP floor (effect 101) is what makes Phase 1 safe in the first place.

Foresight and Odor Sleuth are the answer, and they are the same answer — effect 113, byte-for-byte
identical rows in `moves.json`. What the ROM says they do:

* `effect_script_0113.s` — `MOVE_SIDE_EFFECT_ON_HIT|MOVE_SUBSCRIPT_PTR_FORESIGHT`, then
  `SYSCTL_IGNORE_IMMUNITIES` so the Normal-type move itself can land on a Ghost. No `Random`, and
  accuracy 0, so the whole move costs **zero rolls**.
* `subscript_foresight.s` — one `UpdateMonData OPCODE_FLAG_ON, BTLSCR_DEFENDER, ...
  VOLATILE_CONDITION_FORESIGHT` and a message. No test before the flag is set, so a **second use
  succeeds**; this is not a `will_fail` entry.
* `BattleSystem_ApplyTypeChart` (battle_lib.c:2612-2621) — the table walk **breaks** at the 0xFE
  sentinel when the defender carries that volatile *or the attacker has Scrappy*, skipping
  precisely the two rows after it. Levitate is tested in the branch *before* the walk, so it
  survives.
* `BattleControllerPlayer_CheckMoveHitAccuracy` (battle_controller_player.c:2888) —
  ``if (MON_IS_IDENTIFIED(defender) && evaStages < 0) evaStages = 0``, and `evaStages` is held
  negated, so only evasion the defender *gained* is discarded.

(clayton-957.26.3)
"""
import re
import unittest
from dataclasses import replace
from pathlib import Path

from claytonlib.battle.damage import (
    UNMODELLED_ATTACKER_ABILITIES, UNMODELLED_DEFENDER_ABILITIES, Attacker, Defender, damage,
    ignores_ghost_immunity, is_type_immune,
)
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle.types import (
    FORESIGHT_REMOVABLE, TYPE_CHART, effectiveness, type_multiplier,
)
from claytonlib.battle_compass.hunt_session import field_conditions, move_info
from claytonlib.battle_compass.sim import (
    EFFECT_FORESIGHT, MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, HuntConfig,
    accuracy_net_stage, deals_nothing, execute_move, opening_rng, sent_out, simulate_turn,
    unselectable_reason, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass.targets import moveset, stats_key, target_ability
from claytonlib.moves import resolve_move

#: Both spellings of the same effect. Every behavioural test runs over the pair, because the whole
#: argument for supporting them together is that the ROM makes no distinction — and a player's
#: party decides which one they have (Smeargle Sketches either; Stantler learns Odor Sleuth).
BOTH = ("Foresight", "Odor Sleuth")

_NOTES = Path(__file__).resolve().parent.parent / "notes" / "ss_rng" / "effectiveness_chart.md"


def _giratina(key="giratina-origin", **kwargs) -> Battler:
    moves = moveset(key)
    row = species(stats_key(key))
    return replace(Battler(
        name=key, level=47, types=tuple(row["types"]),
        stats=derive_species_stats(stats_key(key), 47, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(name).pp for name in moves),
        ability=target_ability(key)), **kwargs)


def _ours(sleuth="Odor Sleuth", **kwargs) -> Battler:
    """Smeargle with False Swipe in slot 0 and the identifier in slot 1.

    Sketch is why this is a realistic party rather than a contrivance: Smeargle is already the
    planned Phase 2 Pokemon for every target, and it can hold both moves.
    """
    return replace(Battler(
        name="Smeargle", level=73, types=("Normal",),
        stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
        moves=("False Swipe", sleuth), pp=(40, 40)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestTheMoveData(unittest.TestCase):

    def test_both_moves_are_effect_113(self):
        for name in BOTH:
            with self.subTest(name):
                self.assertEqual(resolve_move(name).effect, EFFECT_FORESIGHT)

    def test_the_two_rows_are_identical_everywhere_that_matters(self):
        """Which is the justification for treating them as one move throughout. Compared field by
        field rather than asserted in prose, so a corrected `moves.json` row would surface here
        instead of silently making one of them behave differently."""
        foresight, sleuth = (resolve_move(name) for name in BOTH)
        for field in ("effect", "category", "power", "accuracy", "pp", "effect_chance",
                      "priority"):
            with self.subTest(field):
                self.assertEqual(getattr(foresight, field), getattr(sleuth, field))

    def test_accuracy_is_zero_so_there_is_no_accuracy_roll_to_spend(self):
        for name in BOTH:
            with self.subTest(name):
                self.assertEqual(resolve_move(name).accuracy, 0)

    def test_it_is_aimed_at_the_opponent(self):
        """RANGE_SINGLE_TARGET, so unlike Light Screen or Haze it really does miss a Giratina that
        is away mid-Shadow Force — which is the one way this move can fail to land."""
        for name in BOTH:
            with self.subTest(name):
                self.assertTrue(resolve_move(name).reaches_opponent)


class TestTheTypeChart(unittest.TestCase):
    """The sentinel, and the claim that a break and a two-row deletion are the same thing."""

    def test_foresight_removable_is_exactly_what_follows_the_sentinel(self):
        """The ROM BREAKS at the 0xFE marker rather than skipping named rows, so "what Foresight
        removes" is "whatever is listed after it". This asserts that reading of the notes table
        directly, which is what licenses `FORESIGHT_REMOVABLE` being a hand-written pair.
        """
        rows, after, seen = [], [], False
        for line in _NOTES.read_text().splitlines():
            m = re.match(r"\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|", line)
            if m:
                rows.append((m.group(2), m.group(3)))
        for attacking, defending in rows:
            if attacking == "FORESIGHT":
                seen = True
                continue
            if attacking == "ENDTABLE":
                break
            if seen:
                after.append((attacking.capitalize(), defending.capitalize()))
        self.assertEqual(set(after), set(FORESIGHT_REMOVABLE))
        self.assertEqual(len(after), 2)

    def test_the_two_rows_are_still_in_the_default_chart(self):
        """`foresight=False` is the ordinary case and must not have changed: an unidentified Ghost
        is immune to Normal exactly as it was."""
        for pair in FORESIGHT_REMOVABLE:
            with self.subTest(pair):
                self.assertEqual(TYPE_CHART[pair], 0.0)

    def test_the_immunity_is_deleted_rather_than_inverted(self):
        """Neutral, not super-effective. A Foresight makes Normal *work*; it does not make it
        good."""
        self.assertEqual(type_multiplier("Normal", "Ghost", foresight=True), 1.0)
        self.assertEqual(type_multiplier("Fighting", "Ghost", foresight=True), 1.0)

    def test_nothing_else_in_the_chart_moves(self):
        """Every row but those two is untouched, asserted exhaustively rather than by sampling."""
        for (attacking, defending), expected in TYPE_CHART.items():
            if (attacking, defending) in FORESIGHT_REMOVABLE:
                continue
            with self.subTest(f"{attacking}->{defending}"):
                self.assertEqual(
                    type_multiplier(attacking, defending, foresight=True), expected)

    def test_the_dark_immunity_to_psychic_is_not_removed(self):
        """The natural wrong guess, and the ROM is explicit: Psychic->Dark sits at index 72, well
        before the sentinel, so the break never reaches it. Removing *that* one is Miracle Eye's
        job (effect 216), which is **not** the same mechanism despite sharing
        `MON_IS_IDENTIFIED`'s evasion half: `BasicTypeMulApplies` (battle_lib.c:2551-2555) vetoes
        any immunity row whose DEFENDING type is Dark, entry by entry, rather than breaking out of
        the walk. So the two cannot be folded into one flag, and effect 216 stays unmodelled.
        """
        self.assertEqual(type_multiplier("Psychic", "Dark", foresight=True), 0.0)

    def test_giratinas_pairing_is_the_point(self):
        """Ghost/Dragon: 0x on the Ghost half and 1x on the Dragon half, so deleting one row
        takes the whole combination from immune to neutral."""
        self.assertEqual(effectiveness("Normal", ("Ghost", "Dragon")), 0.0)
        self.assertEqual(effectiveness("Normal", ("Ghost", "Dragon"), foresight=True), 1.0)

    def test_a_surviving_resistance_still_applies(self):
        """Fighting against Ghost/Steel: the Ghost row goes, the Steel row stays — and Fighting is
        super-effective on Steel, so the answer is 2x rather than 1x. Pins that the removal is per
        row, not a blanket "ignore the defender's typing"."""
        self.assertEqual(effectiveness("Fighting", ("Ghost", "Steel"), foresight=True), 2.0)


class TestTheTwoRoutesToTheSameRemoval(unittest.TestCase):
    """Foresight on the defender, Scrappy on the attacker — one ROM condition."""

    def test_the_defender_flag_removes_it(self):
        self.assertTrue(ignores_ghost_immunity(identified=True))

    def test_the_attacker_ability_removes_it(self):
        self.assertTrue(ignores_ghost_immunity(attacker_ability="Scrappy"))

    def test_the_ability_name_is_matched_loosely(self):
        """Abilities arrive from encounter rows and from hand-typed party configuration, so the
        comparison has to survive both."""
        for spelling in ("scrappy", "SCRAPPY", " Scrappy "):
            with self.subTest(spelling):
                self.assertTrue(ignores_ghost_immunity(attacker_ability=spelling))

    def test_neither_means_neither(self):
        self.assertFalse(ignores_ghost_immunity())
        self.assertFalse(ignores_ghost_immunity(attacker_ability="Technician"))

    def test_scrappy_is_in_neither_unmodelled_ability_set(self):
        """For the same reason Levitate is in neither: it is a type rule with no second half, so
        it is modelled rather than refused. Leaving it out was unsound in the dangerous direction
        — a Kangaskhan's False Swipe against Giratina really does damage, and the simulator
        predicted zero, which eliminates the true seed rather than under-promising.
        """
        self.assertNotIn("scrappy", UNMODELLED_ATTACKER_ABILITIES)
        self.assertNotIn("scrappy", UNMODELLED_DEFENDER_ABILITIES)

    def test_a_scrappy_false_swipe_damages_a_ghost(self):
        false_swipe = resolve_move("False Swipe")
        plain = Attacker(level=73, attack=65, special_attack=40, types=("Normal",))
        scrappy = replace(plain, ability="Scrappy")
        ghost = Defender(defence=100, special_defence=120, types=("Ghost", "Dragon"))
        self.assertEqual(damage(false_swipe, plain, ghost, roll=100), 0)
        self.assertGreater(damage(false_swipe, scrappy, ghost, roll=100), 0)

    def test_the_two_routes_agree_on_the_number(self):
        """Same ROM condition, so the same damage — not merely both nonzero."""
        false_swipe = resolve_move("False Swipe")
        plain = Attacker(level=73, attack=65, special_attack=40, types=("Normal",))
        scrappy = replace(plain, ability="Scrappy")
        ghost = Defender(defence=100, special_defence=120, types=("Ghost", "Dragon"))
        identified = replace(ghost, identified=True)
        self.assertEqual(damage(false_swipe, scrappy, ghost, roll=100),
                         damage(false_swipe, plain, identified, roll=100))


class TestLevitateSurvivesIt(unittest.TestCase):
    """The asymmetry that makes Giratina Origin interesting: one immunity goes, the other does
    not. The ROM tests Levitate in the branch BEFORE the table walk the sentinel lives in."""

    def test_a_ground_move_is_still_blocked(self):
        earthquake = resolve_move("Earthquake")
        attacker = Attacker(level=50, attack=200, special_attack=200, types=("Ground",))
        floating = Defender(defence=100, special_defence=100, types=("Ghost", "Dragon"),
                            ability="Levitate", identified=True)
        self.assertEqual(damage(earthquake, attacker, floating, roll=100), 0)

    def test_but_the_normal_move_gets_through_to_the_same_pokemon(self):
        false_swipe = resolve_move("False Swipe")
        attacker = Attacker(level=73, attack=65, special_attack=40, types=("Normal",))
        floating = Defender(defence=100, special_defence=100, types=("Ghost", "Dragon"),
                            ability="Levitate", identified=True)
        self.assertGreater(damage(false_swipe, attacker, floating, roll=100), 0)

    def test_the_battler_level_predicate_says_the_same(self):
        self.assertTrue(deals_nothing(resolve_move("Earthquake"),
                                      _giratina(identified=True), _ours()))
        self.assertFalse(deals_nothing(resolve_move("False Swipe"),
                                       _giratina(identified=True), _ours()))


class TestWhatItCosts(unittest.TestCase):

    def test_it_spends_no_rolls_and_leaves_the_stream_untouched(self):
        rng = 0x1234_5678
        for name in BOTH:
            with self.subTest(name):
                after, outcome = execute_move(rng, resolve_move(name), _ours(sleuth=name),
                                              _giratina(), actor="M", slot=1)
                self.assertEqual(outcome.rolls, 0)
                self.assertEqual(after, rng)
                self.assertTrue(outcome.successful)

    def test_it_renders_the_bare_slot(self):
        """A successful status move, so no hit marker and nothing to ask the player about."""
        _, outcome = execute_move(0x1234_5678, resolve_move("Odor Sleuth"), _ours(),
                                  _giratina(), actor="M", slot=1)
        self.assertEqual(outcome.tokens, ("M2",))

    def test_it_is_three_advances_cheaper_than_the_false_swipe_it_enables(self):
        """Worth pinning as a figure rather than as "fewer": the immune False Swipe still spends
        crit, damage and accuracy, so the identifying turn is the cheapest turn in the run."""
        config = _config()
        state = BattleState(ours=_ours(), target=_giratina(),
                            rng=opening_rng(0x0C0E02CA, config))
        swiped = simulate_turn(state, Action.MOVE_1, config)
        sleuthed = simulate_turn(state, Action.MOVE_2, config)
        self.assertEqual(swiped.rng_offset - sleuthed.rng_offset, 3)


class TestItCannotFail(unittest.TestCase):

    def test_a_second_use_is_not_a_failure(self):
        """`subscript_foresight.s` tests nothing before setting the bit, which is what keeps this
        out of `will_fail` — and a `will_fail` entry would cost the turn two advances it spends.
        """
        for name in BOTH:
            with self.subTest(name):
                self.assertFalse(will_fail(resolve_move(name), _giratina(identified=True)))

    def test_a_second_use_costs_exactly_what_the_first_did(self):
        rng = 0x1234_5678
        first = execute_move(rng, resolve_move("Odor Sleuth"), _ours(), _giratina(),
                             actor="M", slot=1)[1]
        again = execute_move(rng, resolve_move("Odor Sleuth"), _ours(),
                             _giratina(identified=True), actor="M", slot=1)[1]
        self.assertEqual((first.rolls, first.successful, first.identifies),
                         (again.rolls, again.successful, again.identifies))

    def test_mean_look_by_contrast_does_fail_on_a_second_use(self):
        """The contrast that makes this move useful as filler. Mean Look also sets a permanent
        flag on a wild target, but a second one FAILS — and a failing move is two advances cheaper
        than a successful one, so its turn cost depends on whether it has been used before.
        Foresight's does not, which is what a constant-cost filler needs.
        """
        config = _config()
        fresh = BattleState(ours=_ours(), target=_giratina(),
                            rng=opening_rng(0x0C0E02CA, config))
        trapped = replace(fresh.copy(), target_trapped=True)
        mean_look = resolve_move("Mean Look")
        self.assertFalse(will_fail(mean_look, fresh.target, fresh))
        self.assertTrue(will_fail(mean_look, trapped.target, trapped))


class TestTheFlagLandsOnTheDefender(unittest.TestCase):
    """`BTLSCR_DEFENDER`, even though the attacker is the one using the move — which is the half
    of this that is easy to get backwards, and the notes in `notes/ss_rng/effects.md` do describe
    it as the user's status."""

    def test_our_move_identifies_the_target_and_not_us(self):
        config = _config()
        state = BattleState(ours=_ours(), target=_giratina(),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_2, config)
        self.assertTrue(after.target.identified)
        self.assertFalse(after.ours.identified)

    def test_it_persists_across_turns(self):
        """A wild Pokemon never switches out and the ROM clears `statusVolatile` only on the way
        in, so one use lasts the battle. Paid once, which is what makes it affordable."""
        config = _config()
        state = BattleState(ours=_ours(), target=_giratina(),
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_2, config)
        for _ in range(4):
            state = simulate_turn(state, Action.MOVE_1, config)
            self.assertTrue(state.target.identified)

    def test_fainting_clears_it(self):
        """It is a `statusVolatile` bit, and those go when a Pokemon leaves the field — the same
        rule that stops a Revive bringing back something still mid-nightmare."""
        self.assertFalse(_giratina(identified=True).with_hp(0).identified)

    def test_a_switch_clears_it(self):
        """Reachable only in the direction the target cannot use: a Foresight aimed at US is shed
        by switching, while the target has no way out of ours."""
        self.assertFalse(sent_out(_ours(identified=True)).identified)

    def test_it_survives_the_APPLIER_switching_out(self):
        """[verified in game, by Testare.] One Pokemon identifies the target, switches out, and
        another chips it -- **the Foresight does not have to be on the False Swipe user.**

        The flag is a volatile on the target, so whoever applied it is irrelevant from then on.
        The ROM could not do it the other way even if it wanted to: the four effects it DOES clear
        when their applier leaves (Mean Look, Lock On, Attract, Bind) each record a source in
        `MoveEffectsData`, and this one records none, so there is nothing to match on
        (battle_lib.c:2040 and 2155; include/battle/battle_mon.h:23-26).

        A regression test rather than a derivation, because this was briefly believed to work the
        other way round and "fixing" it would make the simulator predict 0 damage on a turn the
        game deals real damage -- which eliminates the true seed rather than under-promising
        (clayton-957.26.5).
        """
        config = _config()
        stantler = replace(_ours(name="Stantler", moves=("Odor Sleuth", "Take Down"),
                                 pp=(40, 20)), party_slot=1)
        smeargle = replace(_ours(), party_slot=2)
        state = BattleState(ours=stantler, target=_giratina(), bench=(smeargle,),
                            rng=opening_rng(0x0C0E02CA, config))

        state = simulate_turn(state, Action.MOVE_1, config)          # Stantler: Odor Sleuth
        self.assertTrue(state.target.identified)

        state = simulate_turn(state, Action.SWITCH, config, bench_slot=0)
        self.assertEqual(state.ours.name, "Smeargle")
        self.assertTrue(state.target.identified, "the switch must not shed the target's flag")

        before = state.target.hp
        state = simulate_turn(state, Action.MOVE_1, config)           # Smeargle: False Swipe
        self.assertLess(state.target.hp, before)


class TestTheEvasionHalf(unittest.TestCase):
    """``if (MON_IS_IDENTIFIED(defender) && evaStages < 0) evaStages = 0``, and `evaStages` is held
    negated — so only evasion the defender GAINED is thrown away."""

    def test_a_raised_evasion_stops_counting(self):
        self.assertEqual(accuracy_net_stage(_ours(), _giratina(evasion_stage=3)), -3)
        self.assertEqual(
            accuracy_net_stage(_ours(), _giratina(evasion_stage=3, identified=True)), 0)

    def test_an_evasion_DROP_still_counts(self):
        """The asymmetry, and it is worth a test of its own: a run spends real turns on Flash and
        Sweet Scent, and reading the ROM as "evasion is neutralised" would hand that work back.
        """
        self.assertEqual(
            accuracy_net_stage(_ours(), _giratina(evasion_stage=-3, identified=True)), 3)

    def test_our_own_accuracy_drop_is_untouched(self):
        """Foresight zeroes the defender's term only. An accuracy drop on us is the attacker's
        side of the sum and survives."""
        self.assertEqual(
            accuracy_net_stage(_ours(accuracy_stage=-2), _giratina(identified=True)), -2)

    def test_the_clamp_still_applies(self):
        """The ROM bounds ``6 + evaStages + accStages`` to 0..12."""
        self.assertEqual(
            accuracy_net_stage(_ours(accuracy_stage=6),
                               _giratina(evasion_stage=-6, identified=True)), 6)


class TestCoverageAndSelectability(unittest.TestCase):

    def test_it_is_modelled_on_both_sides(self):
        self.assertIn(EFFECT_FORESIGHT, MODELLED_OUR_EFFECTS)
        self.assertIn(EFFECT_FORESIGHT, MODELLED_TARGET_EFFECTS)

    def test_the_interview_will_now_offer_it(self):
        """It was refused before this existed — an unmodelled status move, which
        `unselectable_reason` correctly reported as simulating as "doing nothing". That report was
        right: the flag went nowhere and every later False Swipe still predicted zero.
        """
        for name in BOTH:
            with self.subTest(name):
                self.assertIsNone(unselectable_reason(resolve_move(name), _giratina()))

    def test_move_info_publishes_which_move_identifies(self):
        rows = {row["name"]: row for row in move_info(_ours(), _giratina())}
        self.assertTrue(rows["Odor Sleuth"]["applies_foresight"])
        self.assertFalse(rows["False Swipe"]["applies_foresight"])

    def test_move_info_says_false_swipe_does_nothing_until_it_lands(self):
        """The player-facing half. Half a chipper's moveset reads like a bug against a Ghost, and
        `deals_nothing` is what lets the page say why — and why a Foresight is worth a turn."""
        before = {row["name"]: row for row in move_info(_ours(), _giratina())}
        after = {row["name"]: row
                 for row in move_info(_ours(), _giratina(identified=True))}
        self.assertTrue(before["False Swipe"]["deals_nothing"])
        self.assertFalse(after["False Swipe"]["deals_nothing"])

    def test_a_status_move_is_never_reported_as_dealing_nothing(self):
        """It does not reach the type chart at all, so False is the answer rather than a
        technicality — asking "is Odor Sleuth type-immune" must not read as "it will do nothing".
        """
        rows = {row["name"]: row for row in move_info(_ours(), _giratina())}
        self.assertFalse(rows["Odor Sleuth"]["deals_nothing"])
        self.assertFalse(is_type_immune(resolve_move("Odor Sleuth"), ("Ghost", "Dragon")))

    def test_every_move_info_row_carries_the_new_keys(self):
        """Including the empty-slot row, which has to publish the full key set or the page reads
        `undefined` for a blank slot."""
        for row in move_info(_ours(), _giratina()) + move_info(
                _ours(moves=("False Swipe",), pp=(40,)), _giratina()):
            with self.subTest(row["slot"]):
                self.assertIn("deals_nothing", row)
                self.assertIn("applies_foresight", row)


class TestTheBanner(unittest.TestCase):
    """It is announced once and then never mentioned again, while every turn afterwards depends on
    it — so it has to be visible rather than remembered."""

    def test_identified_shows_up_once_it_lands(self):
        config = _config()
        state = BattleState(ours=_ours(), target=_giratina(),
                            rng=opening_rng(0x0C0E02CA, config))
        self.assertNotIn("Identified", [row["name"] for row in field_conditions(state)])
        after = simulate_turn(state, Action.MOVE_2, config)
        rows = [row for row in field_conditions(after) if row["name"] == "Identified"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["whose"], "target")
        self.assertIsNone(rows[0]["turns"])


class TestTheRunItEnables(unittest.TestCase):

    def test_the_chip_phase_is_impossible_without_it(self):
        """The problem, stated as a test. Five False Swipes against a fresh Giratina leave it at
        full HP — and False Swipe is the only damaging move Phase 1 can safely use.
        """
        config = _config()
        state = BattleState(ours=_ours(), target=_giratina(),
                            rng=opening_rng(0x0C0E02CA, config))
        for _ in range(5):
            state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.target.hp, state.target.max_hp)

    def test_one_use_then_false_swipe_chips_it(self):
        for name in BOTH:
            with self.subTest(name):
                config = _config()
                state = BattleState(ours=_ours(sleuth=name), target=_giratina(),
                                    rng=opening_rng(0x0C0E02CA, config))
                state = simulate_turn(state, Action.MOVE_2, config)
                before = state.target.hp
                state = simulate_turn(state, Action.MOVE_1, config)
                self.assertLess(state.target.hp, before)

    def test_false_swipe_still_floors_at_one_hp(self):
        """The two mechanics have to compose, and this is the one that makes Phase 1 safe: having
        made the move work, it must still not be able to knock the target out. Driven with a
        target one HP above the floor so the clamp is what is being tested.
        """
        config = _config()
        state = BattleState(ours=_ours(), target=_giratina(identified=True, hp=2),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.target.hp, 1)
        self.assertFalse(after.target.fainted)

    def test_both_formes_are_chippable(self):
        """Origin has Levitate and Altered has Pressure, and neither ability touches this: the
        immunity was the type chart's all along."""
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                config = _config()
                state = BattleState(ours=_ours(), target=_giratina(key),
                                    rng=opening_rng(0x0C0E02CA, config))
                state = simulate_turn(state, Action.MOVE_2, config)
                self.assertTrue(state.target.identified)
                before = state.target.hp
                state = simulate_turn(state, Action.MOVE_1, config)
                self.assertLess(state.target.hp, before)

    def test_it_cannot_reach_a_vanished_giratina(self):
        """Shadow Force's charge turn. It is aimed at the opponent, so unlike Light Screen it
        misses — and misses for free, since it had no accuracy roll to spend either way.
        """
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Odor Sleuth"), _ours(),
                                  _giratina(charging_slot=3), actor="M", slot=1)
        self.assertFalse(outcome.successful)
        self.assertFalse(outcome.identifies)
        self.assertIn("-", outcome.tokens)
        self.assertEqual(outcome.rolls, 0)


if __name__ == "__main__":
    unittest.main()
