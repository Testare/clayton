"""Swords Dance — the first move of OURS that makes our own damage bigger.

`effect_script_0050.s` is a single
`MOVE_SIDE_EFFECT_TO_ATTACKER|MOVE_SUBSCRIPT_PTR_ATTACK_UP_2_STAGES` and nothing else. Compare
`0053` (Nasty Plot) and `0054` (Amnesia): the three files differ only in the subscript pointer,
and all three resolve to `subscript_update_stat_stage`
(include/data/move_side_effect_subscripts.h:46-50). So this is one row in `PRIMARY_SELF_RAISES`,
accuracy 0, and **zero rolls** — cross-checked independently against
`metronome_compass.effects._eff_swords_dance`, which is atk+2 and nothing else.

What makes it worth having rather than merely supported: it raises the physical damage we deal,
and **False Swipe cannot take the target below 1 HP** (effect 101), so it is strictly fewer turns
to the Phase 2 precondition with no risk of overshooting it. That combination is the thing this
file is really here to pin — at +6 a Smeargle's False Swipe deals four times what it did, and
still stops at 1.

Two Gen 4 rules the boost depends on and that were already in place:

* a critical hit discards the attacker's stage only when it is **negative**
  (`battle.damage`, lines 499-502), so the +2 survives the turn it matters most on;
* Haze clears it, on both sides, for no rolls — which is why the solver must not plan one.

(clayton-4wr.1.6)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import move_info, reachable_attack_stages
from claytonlib.battle_compass.sim import (
    MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, PRIMARY_SELF_RAISES, STAT_STAGE_CEILING,
    HuntConfig, apply_stat_raise, execute_move, move_roll_cost, opening_rng, reset_stages,
    simulate_turn, unselectable_reason, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import ENCOUNTERS, moveset, stats_key, target_ability
from claytonlib.moves import resolve_move

SWORDS_DANCE = resolve_move("Swords Dance")
FALSE_SWIPE = resolve_move("False Swipe")
#: `MOVE_EFFECT_ATTACK_UP_2` — the index of effect_script_0050.s in the be_seq NARC.
EFFECT_SWORDS_DANCE = 50


def _target(name: str = "azelf", level: int = 50, **kwargs) -> Battler:
    key = stats_key(name)
    moves = moveset(name)
    return replace(Battler(
        name=name, level=level, types=tuple(species(key)["types"]),
        stats=derive_species_stats(key, level, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability(name)), **kwargs)


def _ours(**kwargs) -> Battler:
    """A chipper carrying both halves of the plan: the booster and the move it boosts."""
    return replace(Battler(
        name="Smeargle", level=64, types=("Normal",),
        stats={"hp": 168, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
        moves=("False Swipe", "Swords Dance"), pp=(40, 30), ability="Technician"), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestWhatItIs(unittest.TestCase):

    def test_it_is_a_primary_self_raise_of_two_attack_stages(self):
        self.assertEqual(SWORDS_DANCE.effect, EFFECT_SWORDS_DANCE)
        self.assertEqual(PRIMARY_SELF_RAISES[EFFECT_SWORDS_DANCE], (("atk_stage", 2),))

    def test_it_sits_in_the_same_table_as_nasty_plot_and_amnesia(self):
        """The three effect scripts differ only in the subscript pointer, so three table rows is
        the whole of the difference between them in this simulator too."""
        self.assertEqual(PRIMARY_SELF_RAISES[53], (("spatk_stage", 2),))
        self.assertEqual(PRIMARY_SELF_RAISES[54], (("spdef_stage", 2),))

    def test_agility_is_in_the_table_too_now_with_a_warning_beside_it(self):
        """Effect 52 was held back when this file was written, on the grounds that Speed decides
        turn order and a stage landing the sides on equal effective Speed makes a speed tie.

        That reasoning was right about the hazard and wrong about the remedy: the move is the
        same zero-roll table row as the rest, and refusing to model it did not stop a player
        bringing one -- it only stopped the simulator knowing. It is modelled now, and
        `readiness.speed_move_ties` is what warns before a tie is walked into.
        """
        self.assertEqual(PRIMARY_SELF_RAISES[52], (("speed_stage", 2),))
        self.assertIn(52, MODELLED_OUR_EFFECTS)

    def test_it_is_modelled_for_our_side_only(self):
        """No configured encounter has it, so the target half is wired for symmetry — the same
        standing as Haze."""
        self.assertIn(EFFECT_SWORDS_DANCE, MODELLED_OUR_EFFECTS)
        self.assertNotIn(EFFECT_SWORDS_DANCE, MODELLED_TARGET_EFFECTS)
        self.assertIsNone(unselectable_reason(SWORDS_DANCE))
        for key, encounter in ENCOUNTERS.items():
            with self.subTest(key):
                self.assertNotIn("Swords Dance", encounter.moves)


class TestWhatItCosts(unittest.TestCase):

    def test_the_move_itself_spends_no_rolls(self):
        """Accuracy 0 so no accuracy roll, and the subscript has no Random — the same nothing
        Haze, Nasty Plot and Amnesia cost."""
        self.assertEqual(SWORDS_DANCE.accuracy, 0)
        self.assertEqual(move_roll_cost(SWORDS_DANCE), 0)
        rng = 0x0C0E02CA
        after, outcome = execute_move(rng, SWORDS_DANCE, _ours(), _target(),
                                      actor="M", slot=1)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng, "the stream moved on a move that rolls nothing")
        self.assertTrue(outcome.successful)
        self.assertEqual(outcome.self_stat_raise, (("atk_stage", 2),))

    def test_it_renders_as_the_bare_slot(self):
        """A status move that lands has no hit marker, so the interview must not ask whether it
        crit."""
        _, outcome = execute_move(0x0C0E02CA, SWORDS_DANCE, _ours(), _target(),
                                  actor="M", slot=1)
        self.assertEqual(outcome.tokens, ("M2",))

    def test_at_the_ceiling_it_does_nothing_and_still_costs_a_full_turn(self):
        """**This file asserted the opposite when it was written, and the opposite was wrong.**

        `BtlCmd_ChangeStatStage` takes `jumpNoChange` for a DIRECT side effect whose stat is
        already at `MAX_STAT_STAGE`, and that branch prints "won't go higher!" and ends without
        setting a status flag -- so the move still counts as successful and still spends the
        post-successful-move pair. Measured on the mirror instruction: data/battle_logs/
        hooh1.jsonl turns 34-37 are four Sweet Scents against an evasion already at -6, each
        spending the full 15 rolls.
        """
        self.assertFalse(will_fail(SWORDS_DANCE, _target(), actor=_ours(atk_stage=6)))
        self.assertFalse(will_fail(SWORDS_DANCE, _target(), actor=_ours(atk_stage=4)))
        config = _config()
        base = BattleState(ours=_ours(atk_stage=4), target=_target(),
                           rng=opening_rng(0x0C0E02CA, config))
        at_ceiling = BattleState(ours=_ours(atk_stage=6), target=_target(),
                                 rng=opening_rng(0x0C0E02CA, config))
        lands = simulate_turn(base, Action.MOVE_2, config)
        wasted = simulate_turn(at_ceiling, Action.MOVE_2, config)
        self.assertEqual(lands.rng_offset, wasted.rng_offset)
        self.assertEqual(wasted.ours.atk_stage, 6, "the clamp let it overflow")

    def test_a_taunt_refuses_it_because_it_has_no_power(self):
        """By POWER, which is the ROM's own test — so our booster is exactly what a Taunt aimed
        at us would take away."""
        self.assertEqual(SWORDS_DANCE.power, 0)
        info = {m["name"]: m for m in move_info(_ours(), _target())}
        self.assertTrue(info["Swords Dance"]["taunt_refusable"])
        self.assertFalse(info["False Swipe"]["taunt_refusable"])


class TestTheBoostItself(unittest.TestCase):

    def test_each_use_is_two_stages(self):
        config = _config()
        state = BattleState(ours=_ours(), target=_target(),
                            rng=opening_rng(0x0C0E02CA, config))
        for expected in (2, 4, 6):
            state = simulate_turn(state, Action.MOVE_2, config)
            self.assertEqual(state.ours.atk_stage, expected)

    def test_it_clamps_at_the_ceiling_rather_than_overflowing(self):
        self.assertEqual(apply_stat_raise(_ours(atk_stage=5), (("atk_stage", 2),)).atk_stage,
                         STAT_STAGE_CEILING)

    def test_haze_takes_it_straight_back_off(self):
        """Which is the whole reason `solver.undoes_our_own_work` exists: Haze is the cheapest
        move in the alphabet and it would be planned as filler."""
        self.assertEqual(reset_stages(_ours(atk_stage=6)).atk_stage, 0)

    def test_it_lands_on_the_user_rather_than_the_target(self):
        config = _config()
        state = BattleState(ours=_ours(), target=_target(),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_2, config)
        self.assertEqual(after.ours.atk_stage, 2)
        self.assertEqual(after.target.atk_stage, 0)


class TestItReachesTheDamageWeDeal(unittest.TestCase):
    """The point of the move. Measured against a target whose Defence does not move, so the only
    thing changing between rows is our own stage."""

    def _damage(self, stage: int, move=FALSE_SWIPE) -> int:
        _, outcome = execute_move(0x0C0E02CA, move, _ours(atk_stage=stage),
                                  _target(), actor="M", slot=0)
        return outcome.damage

    def test_two_stages_doubles_it_and_six_quadruples_it(self):
        """The Gen 4 stage table: +2 is x2 and +6 is x4."""
        plain = self._damage(0)
        self.assertGreater(plain, 0)
        self.assertAlmostEqual(self._damage(2) / plain, 2.0, delta=0.08)
        self.assertAlmostEqual(self._damage(6) / plain, 4.0, delta=0.08)

    def test_it_rises_monotonically(self):
        values = [self._damage(stage) for stage in range(0, 7)]
        self.assertEqual(values, sorted(values))
        self.assertLess(values[0], values[-1])

    def test_a_critical_hit_keeps_a_raised_stage(self):
        """`battle.damage` discards the attacker's stage on a crit only when it is NEGATIVE
        (lines 499-502), which is the Gen 4 rule. If it discarded a raise as well, the move would
        be worth nothing on exactly the turns it matters most."""
        from claytonlib.battle.damage import Attacker, Defender, damage
        target, ours = _target(), _ours()
        attacker = Attacker(level=ours.level, attack=ours.stats["atk"],
                            special_attack=ours.stats["spa"], types=ours.types)
        defender = Defender(defence=target.stats["def"], special_defence=target.stats["spd"],
                            types=target.types)
        plain = damage(FALSE_SWIPE, attacker, defender, critical=True)
        boosted = damage(FALSE_SWIPE, replace(attacker, attack_stage=2), defender,
                         critical=True)
        self.assertGreater(boosted, plain)
        # And a LOWERED stage really is discarded, which is the other half of the same rule.
        lowered = damage(FALSE_SWIPE, replace(attacker, attack_stage=-2), defender,
                         critical=True)
        self.assertEqual(lowered, plain)

    def test_a_burn_still_halves_the_boosted_attack(self):
        """Two independent multipliers, and the burn is the reason a boosted chipper is not
        automatically a faster one."""
        healthy = self._damage(2)
        _, burned = execute_move(0x0C0E02CA, FALSE_SWIPE,
                                 _ours(atk_stage=2, status=Status.BURN), _target(),
                                 actor="M", slot=0)
        self.assertLess(burned.damage, healthy)


class TestFalseSwipeIsStillSafeAtPlusSix(unittest.TestCase):
    """The property that makes boosting worth doing at all.

    If a boosted False Swipe could kill, Swords Dance would be a trap rather than a shortcut --
    the run ends the moment the target faints. Effect 101 clamps at 1 HP, and the clamp is on the
    damage rather than on the plan, so it holds at any stage.
    """

    def test_it_cannot_take_the_target_below_one_hp(self):
        target = _target()
        for stage in range(0, 7):
            with self.subTest(stage=stage):
                _, outcome = execute_move(0x0C0E02CA, FALSE_SWIPE, _ours(atk_stage=stage),
                                          target, actor="M", slot=0)
                self.assertLess(outcome.damage, target.hp)

    def test_it_reaches_one_hp_in_fewer_hits(self):
        """The actual benefit, counted rather than argued, and isolated from the turn skeleton so
        only the stage differs between the two figures.

        Note what the numbers say about how much to invest: against this 138 HP target ONE dance
        pays for itself (5 hits down to 3, so 4 turns against 5) and a second does not get the
        count below 2, so the third would be thrown away. A ceiling-first opening is not
        automatically the fast line -- which is the solver's problem, not the move's.
        """
        def hits_to_one(stage: int) -> int:
            target, count = _target(), 0
            while target.hp > 1 and count < 40:
                _, outcome = execute_move(0x0C0E02CA, FALSE_SWIPE, _ours(atk_stage=stage),
                                          target, actor="M", slot=0)
                target = target.with_hp(target.hp - outcome.damage)
                count += 1
            return count

        plain, boosted = hits_to_one(0), hits_to_one(2)
        self.assertLess(boosted, plain)
        self.assertLess(boosted + 1, plain, "one dance has to pay for its own turn")

    def test_the_clamped_turn_still_renders_a_hit(self):
        """It connected, so the marker is `h` -- the clamp is not a miss and not a failure."""
        _, outcome = execute_move(0x0C0E02CA, FALSE_SWIPE, _ours(atk_stage=6), _target(),
                                  actor="M", slot=0)
        self.assertEqual(outcome.tokens, ("M1", tok.HIT))


class TestATargetWithItWouldRaiseTheDangerFloor(unittest.TestCase):
    """Unreachable today and wired anyway, because the table is the single point of change.

    `reachable_attack_stages` asks whether any of the target's moves self-raises an OFFENSIVE
    stage, so the row added here is all it takes for a Swords Dancing target to be priced at
    every stage up to +6 rather than at the one it currently holds.
    """

    def test_a_target_carrying_it_is_priced_at_every_stage(self):
        dancer = replace(_target(), moves=("Swift", "Swords Dance"), pp=(20, 30))
        self.assertEqual(reachable_attack_stages(dancer),
                         tuple(range(0, STAT_STAGE_CEILING + 1)))

    def test_a_target_without_a_booster_is_priced_where_it_stands(self):
        plain = replace(_target(), moves=("Swift",), pp=(20,))
        self.assertEqual(reachable_attack_stages(plain), (0,))


if __name__ == "__main__":
    unittest.main()
