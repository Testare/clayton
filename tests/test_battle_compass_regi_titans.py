"""The three legendary titans — Clear Body, and a kit that costs almost nothing.

Rock Peak / Iceberg / Iron Ruins, all Lv30, all Clear Body, all catch rate 3.
`StartLegendaryBattle SPECIES_REGIROCK/REGICE/REGISTEEL, 30`
(res/field/scripts/scripts_{rock_peak,iceberg,iron}_ruins.s:47).

Each has FIVE learnable moves at 30, so one is shifted out — and the one shifted out is
**Explosion**. That is the first thing to fear about a Lv30 legendary and it does not happen,
so it is asserted rather than assumed.

Two things make these targets different in kind from everything before them:

**Clear Body refuses every stat drop we aim at them**, and it reaches the *same ROM branch* as
Mist (`battle_script.c:2876-2886`) — so it is the existing block with a second way in, not new
machinery. It does **not** touch a titan's own Curse or Superpower, because the ROM's guard is
`attacker != sideEffectMon`.

**Half their kit is free.** Curse spends nothing at all (accuracy 0, DIRECT side effect) and
Superpower spends no proc roll (`MOVE_SIDE_EFFECT_ON_HIT` returns from the first branch of
`BattleSystem_TriggerSecondaryEffect`, before any `% 100`). So a Curse turn is blind, and the
identification value on this target lives entirely in Stomp's and Metal Claw's `% 100` procs and
in the one slot that differs between the three — Rock Throw 90, Icy Wind 95, Metal Claw 95.

(clayton-6xu.10.1, clayton-6xu.10.2, clayton-6xu.10.3, clayton-6xu.10.7)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.sim import (
    MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, ON_HIT_SELF_CHANGES, PRIMARY_SELF_CHANGES,
    SECONDARY_SELF_CHANGES, STAT_DROP_BLOCKING_ABILITIES, STAT_STAGE_CEILING, STAT_STAGE_FLOOR,
    FLINCH_EFFECTS, HuntConfig, apply_stat_changes, execute_move, opening_rng, simulate_turn,
    stat_drop_blocked_by,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, encounter_level, moveset, resolve, supported, unsupported_moves,
)
from claytonlib.moves import resolve_move

STOMP, TYPE_MOVE, CURSE, SUPERPOWER = 0, 1, 2, 3

TITAN_TYPES = {"regirock": ("Rock",), "regice": ("Ice",), "registeel": ("Steel",)}
TITANS = ("regirock", "regice", "registeel")


def _titan(species: str = "regirock", slot: int = CURSE, **kwargs) -> Battler:
    """A titan with one usable slot, so the selection roll cannot pick away from it."""
    pp = [0, 0, 0, 0]
    pp[slot] = 10
    return replace(Battler(
        name=species, level=30, types=TITAN_TYPES[species],
        stats=derive_species_stats(species, 30, "Timid", ivs=31),
        moves=moveset(species), pp=tuple(pp), ability="Clear Body"), **kwargs)


def _wall(**kwargs) -> Battler:
    """A fat Normal lead carrying the two drops Clear Body is about."""
    return replace(Battler(
        name="Wall", level=100, types=("Normal",),
        stats={"hp": 400, "atk": 100, "def": 150, "spa": 100, "spd": 150, "spe": 200},
        moves=("Screech", "Flash"), pp=(40, 20)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3)


class TestTheEncounterRows(unittest.TestCase):
    def test_all_three_are_lv30_platinum_only(self):
        for species in TITANS:
            with self.subTest(species):
                key, enc = resolve(species, "platinum")
                self.assertEqual(key, species)
                self.assertEqual(enc.level, 30)
                self.assertEqual(encounter_level(species, "platinum"), 30)
                self.assertEqual(enc.games, ("platinum",))
                self.assertIn(species, supported("platinum"))
                self.assertNotIn(species, supported("heartgold"))

    def test_the_movesets_are_the_last_four_in_learn_order(self):
        self.assertEqual(moveset("regirock"),
                         ("Stomp", "Rock Throw", "Curse", "Superpower"))
        self.assertEqual(moveset("regice"),
                         ("Stomp", "Icy Wind", "Curse", "Superpower"))
        self.assertEqual(moveset("registeel"),
                         ("Stomp", "Metal Claw", "Curse", "Superpower"))

    def test_EXPLOSION_IS_SHIFTED_OUT(self):
        """The one that would end a run. Explosion(1) is first in the learnset and five entries
        are learnable at 30, so `BoxPokemon_ReplaceMove` bubbles it off the front."""
        for species in TITANS:
            with self.subTest(species):
                self.assertNotIn("Explosion", moveset(species))

    def test_they_differ_in_exactly_one_slot_and_it_is_the_sub_100_one(self):
        """That slot is where all the identification value lives: the rest of the kit is
        accuracy 100 or 0, and a sub-100 move from the target separates RTC-second siblings."""
        sets = [moveset(s) for s in TITANS]
        for i in (STOMP, CURSE, SUPERPOWER):
            with self.subTest(slot=i):
                self.assertEqual(len({m[i] for m in sets}), 1)
        self.assertEqual(len({m[TYPE_MOVE] for m in sets}), 3)
        for species, acc in (("regirock", 90), ("regice", 95), ("registeel", 95)):
            with self.subTest(species):
                self.assertEqual(resolve_move(moveset(species)[TYPE_MOVE]).accuracy, acc)

    def test_every_move_is_modelled(self):
        for species in TITANS:
            with self.subTest(species):
                self.assertEqual(unsupported_moves(species, "platinum"), ((), None))

    def test_the_ability_defaults_to_clear_body(self):
        """Slot 0 of each species row, so the row leaves `ability` empty."""
        from claytonlib.battle.stats import abilities
        for species in TITANS:
            with self.subTest(species):
                self.assertEqual(ENCOUNTERS[species].ability, "")
                self.assertEqual(abilities(species)[0], "Clear Body")


class TestClearBodyIsTheMistBlock(unittest.TestCase):
    """Same `else` branch, one condition after `mistTurns`, same `result = 1`."""

    def test_it_is_recognised_and_names_itself(self):
        self.assertEqual(stat_drop_blocked_by(_titan()), "Clear Body")
        self.assertIsNone(stat_drop_blocked_by(_wall()))

    def test_white_smoke_is_the_same_mechanic(self):
        """The ROM tests the two in one condition, so the table holds both."""
        self.assertEqual(set(STAT_DROP_BLOCKING_ABILITIES), {"clear body", "white smoke"})
        self.assertEqual(stat_drop_blocked_by(_wall(ability="White Smoke")), "White Smoke")

    def test_mist_still_wins_when_both_could_apply(self):
        """Read off the field first, exactly as the ROM orders them."""
        class _Misted:
            mist_turns = 5
        self.assertEqual(stat_drop_blocked_by(_titan(), _Misted()), "Mist")

    def test_our_screech_is_refused_but_still_succeeds(self):
        """The move executed, so it stays SUCCESSFUL and still spends its post-move advances --
        the rule verified for Mist on turn 15 of test1.jsonl."""
        rng = 0x0C0E_02CA
        _, outcome = execute_move(rng, resolve_move("Screech"), _wall(), _titan(),
                                  actor="M", slot=0)
        self.assertTrue(outcome.successful)
        self.assertEqual(outcome.drop_blocked_by, "Clear Body")
        self.assertIsNone(outcome.stat_drop)

    def test_the_whole_stat_drop_support_kit_is_inert_against_them(self):
        """Screech, Flash, Charm and Metal Sound are all modelled and all do nothing here. That
        is the planning fact, and it is why Haze is the only answer to Curse."""
        for name in ("Screech", "Flash", "Charm", "Metal Sound"):
            with self.subTest(name):
                move = resolve_move(name)
                self.assertIn(move.effect, MODELLED_OUR_EFFECTS)
                _, outcome = execute_move(0x0C0E_02CA, move, _wall(), _titan(),
                                          actor="M", slot=0)
                self.assertEqual(outcome.drop_blocked_by, "Clear Body")
                self.assertIsNone(outcome.stat_drop)

    def test_a_titans_stages_really_do_not_move_over_a_turn_of_ours(self):
        config = _config()
        ours = replace(_wall(), moves=("Screech",), pp=(40,))
        state = BattleState(ours=ours, target=_titan(slot=CURSE),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        # Curse moved three of its own stages; our Screech moved none of them.
        self.assertEqual(after.target.def_stage, 1)

    def test_it_does_NOT_block_a_drop_the_titan_puts_on_itself(self):
        """`attacker != sideEffectMon` is the ROM's guard, so Clear Body says nothing about
        Curse's own -1 Speed or Superpower's own -1/-1."""
        rng = 0x0C0E_02CA
        _, curse = execute_move(rng, resolve_move("Curse"), _titan(slot=CURSE), _wall(),
                                actor="E", slot=CURSE)
        self.assertIn(("speed_stage", -1), curse.self_stat_change)
        _, sp = execute_move(rng, resolve_move("Superpower"), _titan(slot=SUPERPOWER), _wall(),
                             actor="E", slot=SUPERPOWER)
        self.assertEqual(sp.self_stat_change, (("atk_stage", -1), ("def_stage", -1)))


class TestOurSecondaryDropsAreBlockedToo(unittest.TestCase):
    """The gap this work closed: the block lives in the shared stat-stage handler and does not
    care whether a PRIMARY or a SECONDARY effect asked."""

    def _crunch_run(self, ability: str, turns: int = 8) -> list[int]:
        """The titan's Defence stage after each of `turns` Crunches of ours.

        A weak attacker on purpose: Crunch's 20% Defence drop is the thing under test, and a
        realistic one would knock a 97 HP titan out before the proc ever fired. The titan is on
        Stomp rather than Curse so that nothing but our own move touches its Defence.
        """
        config = _config()
        ours = replace(_wall(), moves=("Crunch",), pp=(40,),
                       stats={**_wall().stats, "atk": 10})
        state = BattleState(ours=ours, target=_titan(slot=STOMP, ability=ability),
                            rng=opening_rng(0x0C0E02CA, config))
        out = []
        for _ in range(turns):
            state = simulate_turn(state, Action.MOVE_1, config)
            out.append(state.target.def_stage)
        return out

    def test_a_crunch_of_ours_cannot_drop_a_titans_defence(self):
        """Eight turns of a 20% drop, and not one of them lands."""
        self.assertEqual(set(self._crunch_run("Clear Body")), {0})

    def test_and_without_clear_body_those_same_turns_do_drop_it(self):
        """The control, so the test above is about the ability rather than about the seed."""
        self.assertLess(min(self._crunch_run("Pressure")), 0)

    def test_our_own_clear_body_refuses_the_targets_secondary_drop(self):
        """Reachable rather than symmetric: **Metang and Metagross have Clear Body**, and a
        Metang is this project's whole reason for existing. Regice's Icy Wind is a 100%-chance
        Speed drop, so without the block it would land every single time."""
        config = _config()
        ours = replace(_wall(), ability="Clear Body")
        state = BattleState(ours=ours, target=_titan("regice", slot=TYPE_MOVE),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.ours.speed_stage, 0)

    def test_and_without_it_the_drop_lands(self):
        """The control, so the test above is about the ability and not about the seed."""
        config = _config()
        state = BattleState(ours=_wall(), target=_titan("regice", slot=TYPE_MOVE),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.ours.speed_stage, -1)


class TestCurseCostsNothing(unittest.TestCase):
    def test_zero_rolls_and_a_bare_slot_token(self):
        """Accuracy 0 so no accuracy roll, status so no crit or damage, and a DIRECT side effect
        so no proc roll. A Curse turn is BLIND to RTC-second siblings."""
        rng = 0x0C0E_02CA
        after, outcome = execute_move(rng, resolve_move("Curse"), _titan(slot=CURSE), _wall(),
                                      actor="E", slot=CURSE)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertTrue(outcome.successful)
        self.assertEqual(outcome.tokens, ("E3",))

    def test_the_package_is_speed_down_attack_up_defence_up_in_that_order(self):
        """`subscript_curse_normal.s` calls UPDATE_STAT_STAGE three times, in this order."""
        self.assertEqual(PRIMARY_SELF_CHANGES[109],
                         (("speed_stage", -1), ("atk_stage", 1), ("def_stage", 1)))

    def test_it_stacks_over_turns_with_nothing_we_can_do_about_it(self):
        config = _config()
        ours = replace(_wall(), moves=("Screech",), pp=(40,))
        state = BattleState(ours=ours, target=_titan(slot=CURSE),
                            rng=opening_rng(0x0C0E02CA, config))
        for expected in (1, 2, 3):
            state = simulate_turn(state, Action.MOVE_1, config)
            self.assertEqual(state.target.def_stage, expected)
            self.assertEqual(state.target.atk_stage, expected)
            self.assertEqual(state.target.speed_stage, -expected)

    def test_a_non_ghost_user_is_the_only_branch_modelled(self):
        """All three titans are Rock, Ice or Steel. The Ghost branch pays half its HP to curse
        the DEFENDER instead, and nothing on this table can reach it."""
        for species in TITANS:
            with self.subTest(species):
                self.assertNotIn("Ghost", TITAN_TYPES[species])


class TestSuperpowerIsFreeAndHelpsUs(unittest.TestCase):
    def test_it_spends_no_proc_roll(self):
        """`MOVE_SIDE_EFFECT_ON_HIT` returns from the first branch of
        `BattleSystem_TriggerSecondaryEffect`, before any `% 100`. Three rolls: accuracy, crit,
        damage — and no fourth."""
        rng = 0x0C0E_02CA
        _, outcome = execute_move(rng, resolve_move("Superpower"), _titan(slot=SUPERPOWER),
                                  _wall(), actor="E", slot=SUPERPOWER)
        self.assertEqual(outcome.rolls, 3)
        self.assertFalse(outcome.secondary)

    def test_its_effect_chance_is_zero_which_cross_checks_the_flag(self):
        """`GF_ASSERT(effectChance != 0)` guards both probabilistic branches, so a chance of 0
        proves the move never reaches one."""
        self.assertEqual(resolve_move("Superpower").effect_chance, 0)

    def test_the_drop_is_guaranteed_on_hit(self):
        self.assertEqual(ON_HIT_SELF_CHANGES[182],
                         (("atk_stage", -1), ("def_stage", -1)))

    def test_it_softens_the_titan_for_us_turn_after_turn(self):
        """The one thing in their kit working in our favour: it partly undoes Curse."""
        config = _config()
        state = BattleState(ours=_wall(), target=_titan(slot=SUPERPOWER),
                            rng=opening_rng(0x0C0E02CA, config))
        for expected in (-1, -2, -3):
            state = simulate_turn(state, Action.MOVE_1, config)
            self.assertEqual(state.target.def_stage, expected)
            self.assertEqual(state.target.atk_stage, expected)


class TestStompReducesToTheModelledFlinch(unittest.TestCase):
    def test_150_was_already_in_FLINCH_EFFECTS(self):
        """Which is why this was a one-row addition rather than new machinery — the same shape
        Growth's row had for Shaymin."""
        self.assertIn(150, FLINCH_EFFECTS)
        self.assertIn(150, MODELLED_TARGET_EFFECTS)
        self.assertEqual(resolve_move("Stomp").effect, 150)

    def test_it_spends_one_proc_roll_at_30_percent(self):
        rng = 0x0C0E_02CA
        _, outcome = execute_move(rng, resolve_move("Stomp"), _titan(slot=STOMP), _wall(),
                                  actor="E", slot=STOMP)
        self.assertEqual(outcome.rolls, 4)
        self.assertEqual(resolve_move("Stomp").effect_chance, 30)

    def test_the_power_multiplier_is_x1_because_nothing_of_ours_minimizes(self):
        """`BTLVAR_POWER_MULTI` is 10 unless the defender has `MOVE_EFFECT_MINIMIZE`, when it is
        20. No party move is Minimize, so this is effect 149's situation: modelled by being
        inapplicable."""
        self.assertNotIn(16, [resolve_move(m).effect for m in _wall().moves])


class TestMetalClawRaisesItsOwnAttack(unittest.TestCase):
    def test_it_is_a_secondary_self_raise_at_10_percent(self):
        self.assertEqual(SECONDARY_SELF_CHANGES[139], (("atk_stage", 1),))
        self.assertEqual(resolve_move("Metal Claw").effect_chance, 10)

    def test_the_proc_roll_is_spent_either_way(self):
        """Already handled by the `effect_chance > 0` gate, so only the EFFECT was missing."""
        rng = 0x0C0E_02CA
        _, outcome = execute_move(rng, resolve_move("Metal Claw"),
                                  _titan("registeel", slot=TYPE_MOVE), _wall(),
                                  actor="E", slot=TYPE_MOVE)
        self.assertEqual(outcome.rolls, 4)

    def test_it_lands_on_the_titan_itself_not_on_us(self):
        """The raise is self-aimed, which is the half that could have gone to the wrong side --
        `SECONDARY_STAT_DROPS` next to it goes to the defender."""
        self.assertEqual(
            apply_stat_changes(_titan("registeel"), SECONDARY_SELF_CHANGES[139]).atk_stage, 1)

    def test_over_a_run_its_attack_climbs_and_ours_does_not(self):
        config = _config()
        state = BattleState(ours=_wall(), target=_titan("registeel", slot=TYPE_MOVE),
                            rng=opening_rng(0x0C0E02CA, config))
        for _ in range(12):
            state = simulate_turn(state, Action.MOVE_1, config)
        self.assertGreater(state.target.atk_stage, 0)
        self.assertEqual(state.ours.atk_stage, 0)

    def test_only_registeel_has_it(self):
        self.assertIn("Metal Claw", moveset("registeel"))
        self.assertNotIn("Metal Claw", moveset("regirock"))
        self.assertNotIn("Metal Claw", moveset("regice"))


class TestApplyStatChanges(unittest.TestCase):
    """Signed, and clamped at BOTH bounds — which is why it is not `apply_stat_raise`."""

    def test_it_moves_stats_in_both_directions_at_once(self):
        after = apply_stat_changes(_titan(), PRIMARY_SELF_CHANGES[109])
        self.assertEqual((after.speed_stage, after.atk_stage, after.def_stage), (-1, 1, 1))

    def test_it_clamps_at_the_floor_and_the_ceiling(self):
        at_floor = apply_stat_changes(_titan(speed_stage=STAT_STAGE_FLOOR),
                                      PRIMARY_SELF_CHANGES[109])
        self.assertEqual(at_floor.speed_stage, STAT_STAGE_FLOOR)
        # ...and the other two stats in the same package still move.
        self.assertEqual(at_floor.atk_stage, 1)
        at_ceiling = apply_stat_changes(_titan(def_stage=STAT_STAGE_CEILING),
                                        PRIMARY_SELF_CHANGES[109])
        self.assertEqual(at_ceiling.def_stage, STAT_STAGE_CEILING)

    def test_a_clamped_change_does_not_make_the_move_fail(self):
        """None of Curse's three calls spends a roll, so a titan at -6 Speed keeps Cursing for
        the Attack and Defence at exactly the same cost."""
        rng = 0x0C0E_02CA
        _, outcome = execute_move(rng, resolve_move("Curse"),
                                  _titan(slot=CURSE, speed_stage=STAT_STAGE_FLOOR), _wall(),
                                  actor="E", slot=CURSE)
        self.assertTrue(outcome.successful)
        self.assertEqual(outcome.rolls, 0)


if __name__ == "__main__":
    unittest.main()
