"""Defog, and the Life Orb — one move and one item, both of them two things at once.

They are tested together because that is the shape they share: each has a half that is obvious
and a half that is easy to leave out, and in both cases the half left out was the dangerous one.

**Defog** is the first move of ours that REMOVES a condition the target put up, which makes it
the answer to the only two things that block a Phase 2 precondition outright: the target's
Safeguard refuses every status move, and its Mist refuses every stat drop. Three configured
encounters carry one — Suicune and Cresselia have Mist, Ho-Oh has Safeguard. Its evasion drop is
the obvious half; the clearing is the half that earns it.

**The Life Orb** is ×1.3 damage and a tenth of the holder's max HP per hit. The multiplier is the
obvious half and produces a visible contradiction when it is missing; the recoil is the half that
does not — it takes HP off OUR side every attacking turn, nothing in the stream disagrees, and the
solver's healing budget is quietly computed against a Pokemon healthier than the one on screen.

(clayton-0tt.)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.damage import (
    LIFE_ORB, LIFE_ORB_MODIFIER_PERCENT, damage, item_key,
)
from claytonlib.battle.readiness import MODELLED_HELD_ITEMS, unmodelled_held_items
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.sim import (
    EFFECT_DEFOG, LIFE_ORB_RECOIL_DIVISOR, MIST_TURNS, MODELLED_OUR_EFFECTS,
    PRIMARY_STAT_DROPS, SAFEGUARD_TURNS, HuntConfig, _attacker_side, _defender_side,
    execute_move, move_roll_cost, opening_rng, simulate_turn, unselectable_reason,
    unsupported_our_moves, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.battle_compass import tokens as tok
from claytonlib.moves import resolve_move

DEFOG, SURF, FLASH, SWEET_SCENT = 0, 1, 2, 3


def _mule(**kwargs) -> Battler:
    """A Defog carrier. Pelipper because it is the ordinary answer: a Water/Flying HM mule that
    can hold Surf and Defog at once, which is the pair a Platinum party wants anyway."""
    return replace(Battler(
        name="Pelipper", level=40, types=("Water", "Flying"),
        stats=derive_species_stats("pelipper", 40, "Bold", ivs=31),
        moves=("Defog", "Surf", "Flash", "Sweet Scent"), pp=(15, 15, 20, 20)), **kwargs)


def _suicune(**kwargs) -> Battler:
    """The v1 target, and a Mist carrier."""
    return replace(Battler(
        name="Suicune", level=40, types=tuple(species("suicune")["types"]),
        stats=derive_species_stats("suicune", 40, "Bold", ivs=31),
        moves=moveset("suicune"),
        pp=tuple(resolve_move(m).pp for m in moveset("suicune"))), **kwargs)


def _titan(**kwargs) -> Battler:
    """Clear Body, which is the one thing Defog cannot clear."""
    return replace(Battler(
        name="Regirock", level=30, types=("Rock",),
        stats=derive_species_stats("regirock", 30, "Timid", ivs=31),
        moves=moveset("regirock"),
        pp=tuple(resolve_move(m).pp for m in moveset("regirock")),
        ability="Clear Body"), **kwargs)


def _smeargle(item: str = "", **kwargs) -> Battler:
    """The canonical chipper: False Swipe and nothing that can kill."""
    return replace(Battler(
        name="Smeargle", level=58, types=("Normal",),
        stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
        moves=("False Swipe", "Flash", "Sweet Scent", "Mean Look"), pp=(40, 20, 20, 5),
        held_item=item), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3)


def _rendered(state: BattleState) -> str:
    return tok.render_turn(tok.normalise(state.log[-1]))


class TestDefogIsWorthCarrying(unittest.TestCase):
    def test_it_is_modelled_and_selectable(self):
        self.assertIn(EFFECT_DEFOG, MODELLED_OUR_EFFECTS)
        self.assertIsNone(unselectable_reason(resolve_move("Defog"), _suicune()))
        self.assertEqual(unsupported_our_moves(["Defog"]), ())

    def test_the_three_encounters_it_answers(self):
        """Not a hypothetical. Suicune and Cresselia raise Mist, which refuses every stat drop we
        aim at them; Ho-Oh raises Safeguard, which refuses every status move -- and the Ho-Oh plan
        is built on landing paralysis."""
        carriers = {}
        for name in ("suicune", "cresselia", "ho-oh"):
            for move in moveset(name):
                effect = resolve_move(move).effect
                if effect in (46, 124):                       # Mist, Safeguard
                    carriers[name] = move
        self.assertEqual(carriers, {"suicune": "Mist", "cresselia": "Mist",
                                    "ho-oh": "Safeguard"})

    def test_it_spends_no_rolls_at_all(self):
        """Accuracy 0, and `subscript_defog.s` has no `Random` on any path -- so it is Haze's
        cost: two advances for the turn and nothing of its own."""
        move = resolve_move("Defog")
        self.assertEqual(move.accuracy, 0)
        self.assertEqual(move_roll_cost(move), 0)
        _, outcome = execute_move(0x12345678, move, _mule(), _suicune(),
                                  actor="M", slot=DEFOG, field=None)
        self.assertEqual(outcome.rolls, 0)
        self.assertTrue(outcome.successful)

    def test_it_never_fails(self):
        """The subscript checks the side conditions only to decide whether to print its
        animation; `_043` runs either way. So there is no `will_fail` family for it -- not even at
        the evasion floor, which for a single-stat drop is not a failure."""
        for label, target in (("nothing up", _suicune()),
                              ("evasion already floored", _suicune(evasion_stage=-6)),
                              ("Clear Body", _titan())):
            with self.subTest(label):
                self.assertFalse(will_fail(resolve_move("Defog"), target))


class TestWhatDefogClears(unittest.TestCase):
    def test_it_takes_the_targets_mist_and_safeguard_away(self):
        state = BattleState(rng=opening_rng(0x12345678, _config()), ours=_mule(),
                            target=_suicune(), mist_turns=MIST_TURNS,
                            safeguard_turns=SAFEGUARD_TURNS)
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertEqual((state.mist_turns, state.safeguard_turns), (0, 0))

    def test_it_leaves_our_own_side_and_the_weather_alone(self):
        """`MOVE_SIDE_EFFECT_TO_DEFENDER`, so a Defog of OURS reads the target's side. Rain is a
        FIELD condition rather than a side one and is not in the subscript's list at all; nor is
        Lucky Chant, which the subscript simply does not check."""
        state = BattleState(rng=opening_rng(0x12345678, _config()), ours=_mule(),
                            target=_suicune(), rain_turns=4, our_safeguard_turns=5,
                            reflect_turns=3, light_screen_turns=3,
                            target_lucky_chant_turns=4)
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertEqual(state.our_safeguard_turns, 4)         # ticked, not cleared
        self.assertEqual((state.reflect_turns, state.light_screen_turns), (2, 2))
        self.assertEqual(state.rain_turns, 3)
        self.assertEqual(state.target_lucky_chant_turns, 3)

    def test_clearing_the_safeguard_is_what_lets_a_status_move_land_afterwards(self):
        """The whole point of carrying it. `will_fail` refuses a status move through a standing
        Safeguard, so this is the before-and-after of that refusal."""
        thunder_wave = resolve_move("Thunder Wave")
        guarded = BattleState(rng=0, ours=_mule(), target=_suicune(),
                              safeguard_turns=SAFEGUARD_TURNS)
        self.assertTrue(will_fail(thunder_wave, _suicune(), guarded, actor_side="ours"))
        state = BattleState(rng=opening_rng(0x12345678, _config()), ours=_mule(),
                            target=_suicune(), safeguard_turns=SAFEGUARD_TURNS)
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertFalse(will_fail(thunder_wave, state.target, state, actor_side="ours"))


class TestDefogsEvasionDrop(unittest.TestCase):
    def test_it_is_the_same_single_row_sweet_scent_gets(self):
        """`subscript_defog.s` reaches it through `MOVE_SUBSCRIPT_PTR_EVASION_DOWN_1_STAGE`, the
        identical subscript pointer."""
        self.assertEqual(PRIMARY_STAT_DROPS[EFFECT_DEFOG], (("evasion_stage", 1),))
        self.assertEqual(PRIMARY_STAT_DROPS[EFFECT_DEFOG], PRIMARY_STAT_DROPS[24])

    def test_a_standing_mist_blocks_the_drop_and_is_then_removed(self):
        """**The one surprising thing about the move.** The drop is attempted at ``_043`` and the
        Mist is cleared at ``_081``, so the first Defog into a misted target drops nothing and the
        second one drops a stage. Not a special case here -- `execute_move` prices the drop against
        the field as it stands and `apply_field` clears afterwards -- but it is what a
        reimplementation would get backwards."""
        state = BattleState(rng=opening_rng(0x12345678, _config()), ours=_mule(),
                            target=_suicune(), mist_turns=MIST_TURNS)
        first = simulate_turn(state, Action.MOVE_1, _config())
        self.assertEqual(first.target.evasion_stage, 0)        # refused by the Mist
        self.assertEqual(first.mist_turns, 0)                  # ...which is now gone
        second = simulate_turn(first, Action.MOVE_1, _config())
        self.assertEqual(second.target.evasion_stage, -1)      # and now it lands

    def test_the_block_is_reported_rather_than_silent(self):
        _, outcome = execute_move(
            0x12345678, resolve_move("Defog"), _mule(), _suicune(), actor="M", slot=DEFOG,
            field=BattleState(rng=0, ours=_mule(), target=_suicune(), mist_turns=MIST_TURNS))
        self.assertIsNone(outcome.stat_drop)
        self.assertEqual(outcome.drop_blocked_by, "Mist")
        self.assertTrue(outcome.clears_side_conditions)        # the other half still happens

    def test_clear_body_refuses_the_drop_and_defog_cannot_clear_an_ability(self):
        """So against the titans Defog's evasion half is simply unavailable -- there is no second
        Defog that gets through, unlike the Mist case above."""
        _, outcome = execute_move(
            0x12345678, resolve_move("Defog"), _mule(), _titan(), actor="M", slot=DEFOG,
            field=BattleState(rng=0, ours=_mule(), target=_titan()))
        self.assertIsNone(outcome.stat_drop)
        self.assertEqual(outcome.drop_blocked_by, "Clear Body")

    def test_the_solver_will_not_haze_a_defog_away(self):
        """A lowered target evasion is an investment like a lowered accuracy, and
        `_STAGES_IN_OUR_FAVOUR` had a row for one and not the other. Defog is what makes that
        ordinary: a Platinum party can teach HM05 to anything."""
        from claytonlib.battle_compass.solver import _STAGES_IN_OUR_FAVOUR, undoes_our_own_work

        self.assertIn(("target", "evasion_stage", -1), _STAGES_IN_OUR_FAVOUR)
        worked_for = BattleState(rng=0, ours=_mule(), target=_suicune(evasion_stage=-1))
        self.assertIsNotNone(undoes_our_own_work(resolve_move("Haze"), worked_for))

    def test_the_dominance_key_separates_states_that_disagree_about_it(self):
        """It decides whether OUR move hits, and a miss returns unsuccessful -- which costs the
        turn its two post-successful-move advances."""
        from claytonlib.battle_compass.solver import _dominance_key

        plain = BattleState(rng=0, ours=_mule(), target=_suicune())
        dropped = BattleState(rng=0, ours=_mule(), target=_suicune(evasion_stage=-1))
        self.assertNotEqual(_dominance_key(plain), _dominance_key(dropped))


class TestTheLifeOrbsMultiplier(unittest.TestCase):
    def test_it_is_thirty_percent_of_the_damage_not_of_the_power(self):
        """The distinction that decides where it goes: every other damage item in Gen 4 is a
        `movePower` multiplier, and this one multiplies `battleCtx->damage` after the critical
        multiplier (battle_script.c:1346)."""
        self.assertEqual(LIFE_ORB_MODIFIER_PERCENT, 30)
        move = resolve_move("False Swipe")
        for crit in (False, True):
            for roll in (85, 100):
                with self.subTest(crit=crit, roll=roll):
                    plain = damage(move, _attacker_side(_smeargle()),
                                   _defender_side(_suicune()), roll=roll, critical=crit)
                    orbed = damage(move, _attacker_side(_smeargle(LIFE_ORB)),
                                   _defender_side(_suicune()), roll=roll, critical=crit)
                    self.assertGreater(orbed, plain)
                    # Between 1.20 and 1.30 rather than exactly 1.30, and that is the ASSERTION:
                    # the step truncates and the variance truncates after it, so a float x1.3
                    # applied at the end would agree on some of these four and not all.
                    self.assertLessEqual(orbed, plain * 13 // 10 + 1)

    def test_it_lands_after_the_crit_and_before_the_damage_range(self):
        """Pinned by the arithmetic rather than by comparison with itself, because the position is
        the only thing about this item that is easy to get wrong -- and an earlier draft of this
        test got it wrong in the obvious direction, assuming the step came after STAB.

        ``type_chart=False`` stops the chain exactly where the ROM's `CalcMoveDamage` returns, so
        it is the probe: the Life Orb step has to be visible INSIDE that prefix (it is applied
        before STAB and the type chart) and it has to be applied to an already-doubled figure on a
        crit.

        Against this Suicune, at roll 100: an uncritical False Swipe is 12 before the type chart,
        ``12 * 130 // 100 = 15`` with the orb, and STAB then takes it to ``15 * 15 // 10 = 22``.
        A crit doubles the 12 to 24 first, so the orb reads ``24 * 130 // 100 = 31`` rather than
        doubling the orbed 15 to 30 -- which is the one figure that separates "after the crit"
        from "before it".
        """
        move = resolve_move("False Swipe")
        defender = _defender_side(_suicune())
        bare = _attacker_side(_smeargle())
        orbed = _attacker_side(_smeargle(LIFE_ORB))
        pct = 100 + LIFE_ORB_MODIFIER_PERCENT

        for crit, expected_bare in ((False, 12), (True, 24)):
            with self.subTest(crit=crit):
                pre = damage(move, bare, defender, roll=100, critical=crit, type_chart=False)
                self.assertEqual(pre, expected_bare)
                # Inside the type_chart=False prefix: so it is before STAB.
                self.assertEqual(
                    damage(move, orbed, defender, roll=100, critical=crit, type_chart=False),
                    pre * pct // 100)
        # ...and the crit figure is the orb applied to the DOUBLED damage, not double the orbed
        # damage. 31, not 30.
        self.assertEqual(
            damage(move, orbed, defender, roll=100, critical=True, type_chart=False), 31)
        # STAB after it, which is where the familiar 22 and 46 come from.
        self.assertEqual(damage(move, orbed, defender, roll=100), 22)
        self.assertEqual(damage(move, orbed, defender, roll=100, critical=True), 46)

    def test_a_life_orb_chipper_can_newly_be_lethal_and_the_solver_sees_it(self):
        """`can_faint_target` builds its `Attacker` with the held item, so the 30% reaches the
        KO-safety check for free. False Swipe is floored and so stays safe either way, which is
        the case that matters -- it is Phase 2's unlimited filler."""
        from claytonlib.battle_compass.solver import can_faint_target

        for item in ("", LIFE_ORB):
            with self.subTest(item or "no item"):
                self.assertFalse(can_faint_target(
                    resolve_move("False Swipe"), _smeargle(item), _suicune(hp=1)))


class TestTheLifeOrbsRecoil(unittest.TestCase):
    def test_it_is_a_tenth_of_the_holders_max_hp(self):
        _, outcome = execute_move(0x12345678, resolve_move("False Swipe"),
                                  _smeargle(LIFE_ORB), _suicune(), actor="M", slot=0, field=None)
        self.assertEqual(outcome.self_damage, 153 // LIFE_ORB_RECOIL_DIVISOR)
        self.assertEqual(outcome.self_damage, 15)

    def test_it_keys_on_the_HIT_and_not_on_damage_dealt(self):
        """**The rule that decides whether the chip phase is priced correctly.** A False Swipe
        into a 1 HP target deals exactly zero and still costs the tenth, because the ROM's
        condition is ``battleStatusMask & SYSCTL_MOVE_HIT``."""
        _, outcome = execute_move(0x12345678, resolve_move("False Swipe"),
                                  _smeargle(LIFE_ORB), _suicune(hp=1),
                                  actor="M", slot=0, field=None)
        self.assertEqual(outcome.damage, 0)
        self.assertEqual(outcome.self_damage, 15)

    def test_a_status_move_costs_nothing(self):
        """``CURRENT_MOVE_DATA.class != CLASS_STATUS``, so a Flash or Thunder Wave turn is free --
        which is most of what a Phase 2 plan actually plays."""
        _, outcome = execute_move(0x12345678, resolve_move("Flash"), _smeargle(LIFE_ORB),
                                  _suicune(), actor="M", slot=FLASH, field=None)
        self.assertEqual(outcome.self_damage, 0)

    def test_an_ineffective_hit_costs_nothing(self):
        """The ROM counts an immunity as not having hit at all -- `MOVE_STATUS_INEFFECTIVE` is a
        member of `MOVE_STATUS_DID_NOT_HIT` -- so a Normal move into a Ghost is free. Live against
        Giratina, where half a Normal chipper's moveset lands here."""
        giratina = Battler(
            name="Giratina", level=47, types=("Ghost", "Dragon"),
            stats=derive_species_stats("giratina-altered", 47, "Timid", ivs=31),
            moves=moveset("giratina-altered"),
            pp=tuple(resolve_move(m).pp for m in moveset("giratina-altered")))
        _, outcome = execute_move(0x12345678, resolve_move("False Swipe"),
                                  _smeargle(LIFE_ORB), giratina, actor="M", slot=0, field=None)
        self.assertFalse(outcome.successful)
        self.assertEqual(outcome.self_damage, 0)

    def test_magic_guard_is_spared(self):
        _, outcome = execute_move(0x12345678, resolve_move("False Swipe"),
                                  _smeargle(LIFE_ORB, ability="Magic Guard"), _suicune(),
                                  actor="M", slot=0, field=None)
        self.assertEqual(outcome.self_damage, 0)

    def test_it_spends_no_rolls(self):
        """`subscript_lose_hp_from_item` has no `Random`, which is exactly why leaving this
        unmodelled was dangerous rather than imprecise: nothing in the stream disagrees, so there
        is no contradiction to notice -- the predicted HP is simply wrong."""
        plain = execute_move(0x12345678, resolve_move("False Swipe"), _smeargle(),
                             _suicune(), actor="M", slot=0, field=None)[1]
        orbed = execute_move(0x12345678, resolve_move("False Swipe"), _smeargle(LIFE_ORB),
                             _suicune(), actor="M", slot=0, field=None)[1]
        self.assertEqual(plain.rolls, orbed.rolls)

    def test_a_whole_turn_reports_the_hp_it_cost_us(self):
        state = BattleState(rng=opening_rng(0x12345678, _config()),
                            ours=_smeargle(LIFE_ORB), target=_suicune())
        before = state.ours.hp
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertEqual(before - state.ours.hp, 15)
        self.assertIn("HP138", _rendered(state))

    def test_it_stacks_with_struggles_recoil(self):
        """Two blocks in two different walks, neither aware of the other: a quarter plus a tenth.
        Unreachable for our side (the model never chooses a Struggle for us) and asserted through
        `execute_move` directly, which is the layer that computes it."""
        from claytonlib.battle_compass.sim import STRUGGLE_RECOIL_DIVISOR, struggle_move

        _, outcome = execute_move(0x12345678, struggle_move(), _smeargle(LIFE_ORB), _suicune(),
                                  actor="M", slot=tok.STRUGGLE_SLOT, field=None)
        self.assertEqual(outcome.self_damage,
                         153 // STRUGGLE_RECOIL_DIVISOR + 153 // LIFE_ORB_RECOIL_DIVISOR)


class TestTheReadinessPanelStoppedWarningAboutIt(unittest.TestCase):
    def test_it_is_in_the_allowlist_with_both_halves_described(self):
        (why,) = [why for why, names in MODELLED_HELD_ITEMS.items()
                  if item_key(LIFE_ORB) in names]
        self.assertIn("30%", why)
        self.assertIn("tenth", why)

    def test_a_party_member_holding_one_draws_no_warning(self):
        self.assertEqual(unmodelled_held_items({"Smeargle": "Life Orb"}), [])
        for spelling in ("life orb", "  LIFE ORB ", "lifeorb"):
            with self.subTest(spelling):
                self.assertEqual(unmodelled_held_items({"Smeargle": spelling}), [])


if __name__ == "__main__":
    unittest.main()
