"""Regigigas, in pieces — Slow Start and Knock Off. Confusion is still owed.

Snowpoint Temple B5F, **Lv1**, Slow Start, catch rate 3.
`StartLegendaryBattle SPECIES_REGIGIGAS, 1` (res/field/scripts/scripts_snowpoint_temple_b5f.s:51).

There is no `ENCOUNTERS` row yet, and there should not be: two of its four moves (Confuse Ray 49
and Dizzy Punch 76) are not in `MODELLED_TARGET_EFFECTS`, so `unsupported_moves` would refuse
the row — which is exactly the check working. The target is built by hand here until
clayton-6xu.10.4 lands.

**The fight brings no held items** (Testare's call, clayton-6xu.10.6), which is what reduces
Knock Off to plain damage. Checked rather than assumed: a Lv1 Regigigas' Attack is about 4 once
Slow Start halves it, False Swipe reaches 1 HP on a 13 HP target in one hit, and an
accuracy-raising item would actively weaken the one separator this target offers.

(clayton-6xu.10.5, clayton-6xu.10.6)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.damage import (
    UNMODELLED_ATTACKER_ABILITIES, UNMODELLED_DEFENDER_ABILITIES, unsupported_attacker_reason,
)
from claytonlib.battle_compass.sim import (
    ABILITY_SLOW_START, ABILITY_STICKY_HOLD, EFFECT_KNOCK_OFF, MODELLED_OUR_EFFECTS,
    MODELLED_TARGET_EFFECTS, SLOW_START_TURNS, _attacker_side, effective_speed, execute_move,
    slow_started, unselectable_reason,
)
from claytonlib.battle_compass.state import Battler
from claytonlib.moves import resolve_move

#: Lv1, base HP 110: (2*110 + IV) * 1 / 100 floors to 2 for every IV, so max HP is 13 exactly.
REGIGIGAS_MAX_HP = 13


def _regigigas(**kwargs) -> Battler:
    """A Lv1 Regigigas. Stats are the Lv1 figures, which barely depend on IVs at all."""
    return replace(Battler(
        name="Regigigas", level=1, types=("Normal",),
        stats={"hp": REGIGIGAS_MAX_HP, "atk": 8, "def": 10, "spa": 8, "spd": 10, "spe": 6},
        moves=("Dizzy Punch", "Knock Off", "Confuse Ray", "Foresight"),
        pp=(10, 20, 10, 40), ability="Slow Start"), **kwargs)


def _lead(**kwargs) -> Battler:
    """A plain lead carrying NOTHING, which is the configuration this fight calls for."""
    return replace(Battler(
        name="Lead", level=50, types=("Normal",),
        stats={"hp": 200, "atk": 100, "def": 100, "spa": 100, "spd": 100, "spe": 150},
        moves=("False Swipe", "Spore"), pp=(40, 15)), **kwargs)


class TestItsMaxHPIsPinned(unittest.TestCase):
    def test_every_iv_gives_the_same_13(self):
        """Stronger than `catch_value`'s usual "a=2 at 1 HP for any maxHP >= 2": at Lv1 there is
        no HP-IV uncertainty at ANY HP, so the ball-and-HP readout is exact rather than a range."""
        self.assertEqual({(2 * 110 + iv) * 1 // 100 + 1 + 10 for iv in range(32)},
                         {REGIGIGAS_MAX_HP})

    def test_false_swipe_reaches_1_hp_in_one_hit(self):
        """Which is why no chip item is wanted: the chip phase is one turn long."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("False Swipe"), _lead(),
                                  _regigigas(), actor="M", slot=0)
        self.assertGreaterEqual(outcome.damage, REGIGIGAS_MAX_HP - 1)


class TestSlowStart(unittest.TestCase):
    """Two integer halvings on one turn counter, and the gate on this target existing at all."""

    def test_it_is_no_longer_an_unmodelled_ability(self):
        """It was in `UNMODELLED_ATTACKER_ABILITIES`, so Regigigas was refused outright --
        `unsupported_attacker_reason` is consulted by both `sim` and `solver`."""
        self.assertNotIn(ABILITY_SLOW_START, UNMODELLED_ATTACKER_ABILITIES)
        self.assertNotIn(ABILITY_SLOW_START, UNMODELLED_DEFENDER_ABILITIES)
        self.assertIsNone(unsupported_attacker_reason(_attacker_side(_regigigas(), 0)))

    def test_it_is_active_for_exactly_five_turns(self):
        """``totalTurns - slowStartTurnNumber < 5``, and a wild target is out from the start so
        the stamp is 0 -- the condition reduces to ``turn < 5``."""
        for turn in range(SLOW_START_TURNS):
            with self.subTest(turn=turn):
                self.assertTrue(slow_started(_regigigas(), turn))
        for turn in (SLOW_START_TURNS, SLOW_START_TURNS + 1, 20):
            with self.subTest(turn=turn):
                self.assertFalse(slow_started(_regigigas(), turn))

    def test_it_halves_speed_and_physical_attack(self):
        self.assertEqual(effective_speed(_regigigas(), 0), 3)
        self.assertEqual(effective_speed(_regigigas(), SLOW_START_TURNS), 6)
        self.assertEqual(_attacker_side(_regigigas(), 0).attack, 4)
        self.assertEqual(_attacker_side(_regigigas(), SLOW_START_TURNS).attack, 8)

    def test_it_leaves_special_attack_alone(self):
        """`attackStat` is `BATTLEMON_ATTACK` and `spAttackStat` is a SEPARATE variable in the
        ROM, so special damage is untouched. Moot for Regigigas, whose two attacks are both
        physical, and pinned because Huge Power sits three lines away with the same shape."""
        self.assertEqual(_attacker_side(_regigigas(), 0).special_attack,
                         _regigigas().stats["spa"])

    def test_a_missing_turn_means_do_not_apply_it(self):
        """The documented escape hatch for a caller asking outside any turn."""
        self.assertFalse(slow_started(_regigigas(), None))
        self.assertEqual(effective_speed(_regigigas(), None), 6)

    def test_nothing_else_has_it(self):
        self.assertFalse(slow_started(_lead(), 0))
        self.assertEqual(effective_speed(_lead(), 0), _lead().stats["spe"])

    def test_it_guarantees_we_move_first_which_keeps_ties_out_of_the_search(self):
        """The thing it buys us. A Lv1 Regigigas at 3 effective Speed cannot tie anything we
        would bring, so the no-speed-tie contract holds for free."""
        self.assertGreater(effective_speed(_lead(), 0), effective_speed(_regigigas(), 0))
        self.assertNotEqual(effective_speed(_lead(), 0), effective_speed(_regigigas(), 0))


class TestKnockOff(unittest.TestCase):
    def test_it_is_effect_188_and_modelled_target_side_only(self):
        self.assertEqual(resolve_move("Knock Off").effect, EFFECT_KNOCK_OFF)
        self.assertIn(EFFECT_KNOCK_OFF, MODELLED_TARGET_EFFECTS)
        self.assertNotIn(EFFECT_KNOCK_OFF, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Knock Off")))

    def test_it_spends_no_proc_roll(self):
        """`MOVE_SIDE_EFFECT_ON_HIT`, so it returns from the first branch of
        `BattleSystem_TriggerSecondaryEffect` before any `% 100`. Three rolls: accuracy, crit,
        damage."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Knock Off"), _regigigas(),
                                  _lead(), actor="E", slot=1)
        self.assertEqual(outcome.rolls, 3)
        self.assertFalse(outcome.secondary)

    def test_AGAINST_AN_ITEMLESS_LEAD_IT_IS_PLAIN_DAMAGE(self):
        """The whole point of bringing nothing. `BtlCmd_TryKnockOff` takes its `else` branch when
        the defender holds nothing: no message, no state change, and no `Random` on any path."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Knock Off"), _regigigas(),
                                  _lead(), actor="E", slot=1)
        self.assertFalse(outcome.knocks_off_item)
        self.assertEqual(outcome.rolls, 3)

    def test_and_it_costs_the_same_whether_there_is_an_item_or_not(self):
        """So carrying nothing is not a roll-count trade -- it removes a CONSEQUENCE, not a
        cost."""
        rng = 0x0C0E_02CA
        _, without = execute_move(rng, resolve_move("Knock Off"), _regigigas(), _lead(),
                                  actor="E", slot=1)
        _, with_item = execute_move(rng, resolve_move("Knock Off"), _regigigas(),
                                    _lead(held_item="Leftovers"), actor="E", slot=1)
        self.assertEqual(without.rolls, with_item.rolls)
        self.assertTrue(with_item.knocks_off_item)

    def test_sticky_hold_refuses_it(self):
        """The ROM tests Sticky Hold in the same function that reads the item, before reading it
        -- so it is a second way out, and a worse one than carrying nothing."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Knock Off"), _regigigas(),
                                  _lead(held_item="Leftovers", ability="Sticky Hold"),
                                  actor="E", slot=1)
        self.assertFalse(outcome.knocks_off_item)
        self.assertEqual(ABILITY_STICKY_HOLD, "sticky hold")

    def test_a_lv1_regigigas_knock_off_barely_scratches_us(self):
        """20 BP from an Attack of about 4. The reason no defensive item is wanted either."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Knock Off"), _regigigas(),
                                  _lead(), actor="E", slot=1)
        self.assertLessEqual(outcome.damage, 5)


class TestTheRowIsStillRefused(unittest.TestCase):
    """And should be, until confusion is modelled."""

    def test_confusion_is_what_is_missing(self):
        for effect in (49, 76):
            with self.subTest(effect=effect):
                self.assertNotIn(effect, MODELLED_TARGET_EFFECTS)

    def test_foresight_is_already_modelled(self):
        """Accuracy 0, so it never misses and spends no accuracy roll -- Darkrai's Faint Attack
        put it in long ago."""
        self.assertIn(113, MODELLED_TARGET_EFFECTS)

    def test_there_is_no_encounter_row_yet(self):
        from claytonlib.battle_compass.targets import ENCOUNTERS
        self.assertNotIn("regigigas", ENCOUNTERS)


if __name__ == "__main__":
    unittest.main()
