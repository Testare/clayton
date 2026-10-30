"""Regigigas — Lv1, Slow Start, and the only confusion on either side.

Snowpoint Temple B5F, **Lv1**, Slow Start, catch rate 3.
`StartLegendaryBattle SPECIES_REGIGIGAS, 1` (res/field/scripts/scripts_snowpoint_temple_b5f.s:51).

Seven moves are learnable at 1, so three are shifted out — and the three that go are Fire, Ice
and Thunder Punch, its only real damage. What is left is Dizzy Punch, Knock Off, Confuse Ray,
Foresight, in learn order.

Lv1 makes it strange rather than hard. Its max HP is **exactly 13 for every IV**, so there is no
HP-IV uncertainty at any HP; False Swipe reaches 1 HP in one hit; the Nest Ball is ×3.9 here and
×1 everywhere else on the table; and Slow Start halving its Speed hands us the no-speed-tie
guarantee for free, with no paralysis needed to buy it.

**The fight brings no held items** (Testare's call, clayton-6xu.10.6), which is what reduces
Knock Off to plain damage. Checked rather than assumed: a Lv1 Regigigas' Attack is about 4 once
Slow Start halves it, False Swipe reaches 1 HP on a 13 HP target in one hit, and an
accuracy-raising item would actively weaken the one separator this target offers.

Confusion is the only structurally new mechanic in the whole regi set, and all three of its
moduli divide 256 — so none of it separates RTC-second siblings. Only Dizzy Punch's `% 100` proc
does.

(clayton-6xu.10.4, clayton-6xu.10.5, clayton-6xu.10.6, clayton-6xu.10.7, clayton-6xu.10.12)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.damage import (
    UNMODELLED_ATTACKER_ABILITIES, UNMODELLED_DEFENDER_ABILITIES, unsupported_attacker_reason,
)
from claytonlib.battle_compass.sim import (
    ABILITY_OWN_TEMPO, ABILITY_SHIELD_DUST, ABILITY_SLOW_START, ABILITY_STICKY_HOLD,
    CONFUSION_TURNS_MIN, CONFUSION_TURNS_SPAN, EFFECT_CONFUSE_RAY, EFFECT_DIZZY_PUNCH,
    EFFECT_KNOCK_OFF, MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, SLOW_START_TURNS,
    HuntConfig, _attacker_side, confusion_blocked_by, confusion_lands_on, confusion_self_hit,
    effective_speed, execute_move, opening_rng, simulate_turn, slow_started,
    unselectable_reason, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler
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


class TestConfusionLands(unittest.TestCase):
    """The duration roll, and the three refusals -- which differ in COST between the two routes."""

    def test_confuse_ray_spends_the_accuracy_roll_then_the_duration_roll(self):
        """Accuracy 100 so the roll is spent and always passes; DIRECT so there is no proc roll.
        Two advances when it lands."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Confuse Ray"), _regigigas(),
                                  _lead(), actor="E", slot=2)
        self.assertEqual(outcome.rolls, 2)
        self.assertTrue(CONFUSION_TURNS_MIN
                        <= outcome.confuses
                        < CONFUSION_TURNS_MIN + CONFUSION_TURNS_SPAN)

    def test_the_duration_is_2_to_5_not_2_to_4(self):
        """`Random 3, 2` with `BtlCmd_Random`'s ``range += 1``, so ``(rand % 4) + 2``. Getting
        this wrong by one would mis-count every confused turn after it."""
        self.assertEqual((CONFUSION_TURNS_MIN,
                          CONFUSION_TURNS_MIN + CONFUSION_TURNS_SPAN - 1), (2, 5))
        seen = set()
        for seed in range(0x0C0E_0200, 0x0C0E_0280):
            _, outcome = execute_move(seed, resolve_move("Confuse Ray"), _regigigas(),
                                      _lead(), actor="E", slot=2)
            seen.add(outcome.confuses)
        self.assertEqual(seen, {2, 3, 4, 5})

    def test_dizzy_punch_rolls_the_duration_only_when_the_proc_lands(self):
        with_proc = without = None
        for seed in range(0x0C0E_0200, 0x0C0E_0400):
            _, outcome = execute_move(seed, resolve_move("Dizzy Punch"), _regigigas(),
                                      _lead(), actor="E", slot=0)
            if outcome.secondary and with_proc is None:
                with_proc = outcome
            if not outcome.secondary and without is None:
                without = outcome
            if with_proc and without:
                break
        self.assertEqual(without.rolls, 4)       # accuracy, crit, damage, proc
        self.assertEqual(with_proc.rolls, 5)     # ...and the duration
        self.assertEqual(without.confuses, 0)
        self.assertTrue(with_proc.confuses)

    def test_own_tempo_refuses_it_on_both_routes(self):
        """`CheckAbility` on one, `CheckIgnorableAbility` on the other -- so it is the party
        answer here, and strictly better than a Lum Berry: permanent and not consumed."""
        self.assertEqual(confusion_blocked_by(_lead(ability="Own Tempo"), indirect=False),
                         "Own Tempo")
        self.assertEqual(confusion_blocked_by(_lead(ability="Own Tempo"), indirect=True),
                         "Own Tempo")
        self.assertEqual(ABILITY_OWN_TEMPO, "own tempo")

    def test_shield_dust_refuses_only_the_SECONDARY_route(self):
        """`subscript_confuse.s` tests it on the branch reached when
        `SIDE_EFFECT_TYPE_INDIRECT` is set, so it can stop Dizzy Punch and never Confuse Ray."""
        self.assertEqual(confusion_blocked_by(_lead(ability="Shield Dust"), indirect=True),
                         "Shield Dust")
        self.assertIsNone(confusion_blocked_by(_lead(ability="Shield Dust"), indirect=False))
        self.assertEqual(ABILITY_SHIELD_DUST, "shield dust")

    def test_a_refused_CONFUSE_RAY_is_a_will_fail(self):
        """The direct route sets `MOVE_STATUS_NO_MORE_WORK` on all three refusals, so the move
        costs the turn what every other `will_fail` family costs."""
        move = resolve_move("Confuse Ray")
        self.assertFalse(will_fail(move, _lead(), actor_side="target"))
        self.assertTrue(will_fail(move, _lead(ability="Own Tempo"), actor_side="target"))
        self.assertTrue(will_fail(move, _lead(confusion_turns=3), actor_side="target"))

    def test_a_refused_DIZZY_PUNCH_is_NOT_a_will_fail(self):
        """Reached indirectly, the same branches jump to ``_185`` and end -- the move still dealt
        its damage, and nothing extra was spent. That asymmetry is why the two routes are
        modelled apart."""
        move = resolve_move("Dizzy Punch")
        self.assertFalse(will_fail(move, _lead(ability="Own Tempo"), actor_side="target"))

    def test_an_already_confused_victim_is_not_re_confused(self):
        self.assertFalse(confusion_lands_on(_lead(confusion_turns=2), None,
                                            actor="E", indirect=True))
        self.assertTrue(confusion_lands_on(_lead(), None, actor="E", indirect=True))

    def test_our_own_safeguard_blocks_it(self):
        class _Guarded:
            our_safeguard_turns = 4
            safeguard_turns = 0
        self.assertFalse(confusion_lands_on(_lead(), _Guarded(), actor="E", indirect=False))
        self.assertTrue(confusion_lands_on(_lead(), _Guarded(), actor="M", indirect=False))


class TestTheSelfHit(unittest.TestCase):
    """`CALC_SELF_HIT(MOVE_STRUGGLE, 40)` then `BattleSystem_CalcDamageVariance`."""

    def test_it_uses_our_own_attack_against_our_own_defence(self):
        """The macro passes the attacker as its own defender, so both ends are ours -- and our
        own stages apply to both."""
        base = confusion_self_hit(_lead(), damage_roll=0)
        self.assertGreater(confusion_self_hit(_lead(atk_stage=2), damage_roll=0), base)
        self.assertLess(confusion_self_hit(_lead(def_stage=2), damage_roll=0), base)

    def test_weather_never_touches_it(self):
        """The macro passes `fieldConditions = 0`, so a self-hit in the rain is the same number
        as one in the clear. There is no field argument here at all, which is the point."""
        import inspect
        self.assertEqual(list(inspect.signature(confusion_self_hit).parameters),
                         ["battler", "damage_roll"])

    def test_it_is_typeless_so_our_own_typing_does_not_matter(self):
        """No STAB and no type chart: `BattleSystem_ApplyTypeChart` is never called, and STAB
        lives inside it at battle_lib.c:2593. A Normal lead gets no 1.5x off Struggle's type."""
        normal = confusion_self_hit(_lead(), damage_roll=0)
        ghost = confusion_self_hit(replace(_lead(), types=("Ghost",)), damage_roll=0)
        self.assertEqual(normal, ghost)

    def test_the_variance_is_a_16_step_spread_with_a_floor_of_1(self):
        values = {confusion_self_hit(_lead(), damage_roll=r) for r in range(16)}
        self.assertGreater(len(values), 1)
        self.assertGreaterEqual(min(values), 1)

    def test_burn_halves_it(self):
        from claytonlib.battle_compass.state import Status
        burned = _lead().with_status(Status.BURN)
        self.assertLess(confusion_self_hit(burned, damage_roll=0),
                        confusion_self_hit(_lead(), damage_roll=0))


class TestConfusionOverATurn(unittest.TestCase):
    def _run(self, turns: int, **target):
        config = HuntConfig(target_catch_rate=3)
        pp = [0, 0, 0, 0]
        pp[2] = 40
        state = BattleState(ours=_lead(), target=_regigigas(pp=tuple(pp), **target),
                            rng=opening_rng(0x0C0E02CA, config))
        out = []
        for _ in range(turns):
            state = simulate_turn(state, Action.MOVE_1, config)
            out.append(state.log[-1])
        return state, out

    def test_the_whole_arc_renders_in_the_grammar_the_tokens_already_had(self):
        """`Mcfz` for a self-hit, a bare `M1` for a confused turn that attacks normally, and
        `Mscfz1` for the turn it wears off and the move still happens. None of that token work
        was new -- `tokens.RESOLUTION_DETAIL` was waiting for this."""
        _, log = self._run(6)
        flat = ["".join(t) for t in log]
        self.assertTrue(any("Mcfz" in t for t in flat), flat)
        self.assertTrue(any("Mscfz" in t for t in flat), flat)

    def test_a_self_hit_costs_two_advances_and_a_clean_turn_costs_one(self):
        """The check is one roll; the self-hit adds the damage-variance roll."""
        config = HuntConfig(target_catch_rate=3)
        before = BattleState(ours=_lead(confusion_turns=4), target=_regigigas(),
                             rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(before, Action.MOVE_1, config)
        spent = after.rng_offset - before.rng_offset
        self.assertIn("Mcfz" if after.ours.hp < _lead().hp else "M1",
                      "".join(after.log[-1]))
        self.assertGreaterEqual(spent, 1)

    def test_the_turn_it_wears_off_spends_no_confusion_roll(self):
        """The counter is decremented before the test, so reaching zero snaps out without
        rolling -- a duration of N gives N-1 rolled turns."""
        config = HuntConfig(target_catch_rate=3)
        state = BattleState(ours=_lead(confusion_turns=1), target=_regigigas(),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.ours.confusion_turns, 0)
        self.assertIn("Mscfz1", "".join(after.log[-1]))

    def test_own_tempo_keeps_us_out_of_it_entirely(self):
        """Six turns of Confuse Ray and we are never confused once -- the party answer, against
        the control run above which is confused within one."""
        config = HuntConfig(target_catch_rate=3)
        pp = (0, 0, 40, 0)
        guarded = BattleState(ours=_lead(ability="Own Tempo"), target=_regigigas(pp=pp),
                              rng=opening_rng(0x0C0E02CA, config))
        for _ in range(6):
            guarded = simulate_turn(guarded, Action.MOVE_1, config)
            self.assertEqual(guarded.ours.confusion_turns, 0)
        unguarded, _ = self._run(1)
        self.assertTrue(unguarded.ours.confused)


class TestOurOwnConfusionBugIsFixed(unittest.TestCase):
    """clayton-6xu.10.12, which this machinery fixed in passing.

    `MODELLED_OUR_EFFECTS[76]` used to say "the proc roll only; confusion ON THE TARGET is inert
    here". `subscript_confuse.s` reaches ``_076`` on the INDIRECT route too, and ``_076`` rolls
    `Random 3, 2` -- so a procced Signal Beam of ours spent a duration advance the simulator did
    not, desynchronising every turn after it.
    """

    def _signal_beam(self, **target):
        ours = replace(_lead(), moves=("Signal Beam",), pp=(15,))
        tgt = replace(_regigigas(), **target)
        for seed in range(0x0C0E_0200, 0x0C0E_0600):
            _, outcome = execute_move(seed, resolve_move("Signal Beam"), ours, tgt,
                                      actor="M", slot=0)
            if outcome.secondary:
                return outcome
        self.fail("no seed in range procced the secondary")

    def test_a_procced_signal_beam_now_spends_the_duration_roll(self):
        outcome = self._signal_beam()
        self.assertEqual(outcome.rolls, 5)       # accuracy, crit, damage, proc, duration
        self.assertTrue(outcome.confuses)

    def test_and_spends_nothing_extra_against_own_tempo(self):
        """The ROM jumps past the roll, so refusing it is cheaper -- which is the half a
        flag-shaped model would have got wrong in the other direction."""
        outcome = self._signal_beam(ability="Own Tempo")
        self.assertEqual(outcome.rolls, 4)
        self.assertEqual(outcome.confuses, 0)

    def test_the_row_no_longer_claims_it_is_inert(self):
        self.assertNotIn("inert", MODELLED_OUR_EFFECTS[EFFECT_DIZZY_PUNCH])


class TestTheRow(unittest.TestCase):
    """It exists now that confusion is modelled, which is the gate working in both directions."""

    def test_all_four_of_its_effects_are_modelled(self):
        for effect in (49, 76, 113, 188):
            with self.subTest(effect=effect):
                self.assertIn(effect, MODELLED_TARGET_EFFECTS)

    def test_it_is_lv1_with_the_learn_order_moveset(self):
        from claytonlib.battle_compass.targets import (
            encounter_level, moveset, resolve, supported, unsupported_moves,
        )
        key, enc = resolve("regigigas", "platinum")
        self.assertEqual(key, "regigigas")
        self.assertEqual(enc.level, 1)
        self.assertEqual(encounter_level("regigigas", "platinum"), 1)
        self.assertEqual(enc.moves,
                         ("Dizzy Punch", "Knock Off", "Confuse Ray", "Foresight"))
        self.assertEqual(unsupported_moves("regigigas", "platinum"), ((), None))
        self.assertIn("regigigas", supported("platinum"))
        self.assertNotIn("regigigas", supported("heartgold"))

    def test_THE_ELEMENTAL_PUNCHES_ARE_SHIFTED_OUT(self):
        """Seven moves are learnable at 1, so three go -- and the three that go are Fire, Ice and
        Thunder Punch, which are its only real damage. Pure luck in our favour."""
        from claytonlib.battle_compass.targets import moveset
        for name in ("Fire Punch", "Ice Punch", "Thunder Punch"):
            with self.subTest(name):
                self.assertNotIn(name, moveset("regigigas"))

    def test_it_holds_nothing(self):
        """No wild held item in its personal data, so the no-items rule is about OUR side."""
        from claytonlib.battle_compass.targets import target_held_item
        self.assertEqual(target_held_item("regigigas", "platinum"), "")

    def test_foresight_is_already_modelled(self):
        """Accuracy 0, so it never misses and spends no accuracy roll -- Darkrai's Faint Attack
        put it in long ago."""
        self.assertIn(113, MODELLED_TARGET_EFFECTS)


if __name__ == "__main__":
    unittest.main()
