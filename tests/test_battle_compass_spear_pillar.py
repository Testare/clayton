"""Dialga and Palkia — Lv70, Pressure, catch rate 30, and one move that skips its own turn.

Spear Pillar, both at Lv70. `StartLegendaryBattle SPECIES_DIALGA/PALKIA, 70`
(res/field/scripts/scripts_spear_pillar_{dialga,palkia}.s:43).

Nine moves are learnable at 70, so five are shifted out and both sets land on the four at
40/50/60/70 in learn order. The pair differs in exactly one slot — the signature move at 40 —
and these two targets needed only ONE new effect between them, because Spacial Rend is effect 43
(the high-crit group Aeroblast opened), Heal Block is 236 and Earth Power 72.

**Catch rate 30** is what makes them matter: ten times Suicune's and the titans'. At full HP
asleep in a Dusk Ball they are a=70 against Suicune's a=18 at 1 HP in the same ball, so the chip
phase is a downgrade — and for Dialga it is not merely a downgrade but arithmetically out of
reach (Steel resists False Swipe, Defence 194, and Pressure halves our 40 PP to 20 uses).

(clayton-6xu.9.10, clayton-6xu.9.11)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.sim import (
    EFFECT_ROAR_OF_TIME, MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, HuntConfig,
    execute_move, opening_rng, select_target_move, sent_out, simulate_turn, unselectable_reason,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, encounter_level, moveset, resolve, supported, target_held_item,
    unsupported_moves,
)
from claytonlib.moves import resolve_move

SIGNATURE, HEAL_BLOCK, EARTH_POWER, SLASH = 0, 1, 2, 3

TYPES = {"dialga": ("Steel", "Dragon"), "palkia": ("Water", "Dragon")}


def _titan(species: str = "dialga", slot: int = SIGNATURE, **kwargs) -> Battler:
    """One usable slot, so the selection roll cannot pick away from it."""
    pp = [0, 0, 0, 0]
    pp[slot] = 40
    return replace(Battler(
        name=species, level=70, types=TYPES[species],
        stats=derive_species_stats(species, 70, "Timid", ivs=31),
        moves=moveset(species), pp=tuple(pp), ability="Pressure"), **kwargs)


def _wall(**kwargs) -> Battler:
    """A Flying wall — immune to Earth Power, neutral to Roar of Time, and faster, so our half of
    the turn always resolves first."""
    return replace(Battler(
        name="Wall", level=100, types=("Flying",),
        stats={"hp": 400, "atk": 100, "def": 150, "spa": 100, "spd": 150, "spe": 250},
        moves=("Sweet Scent",), pp=(20,)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=30, target_has_pressure=True)


class TestTheEncounterRows(unittest.TestCase):
    def test_both_are_lv70_platinum_only(self):
        for species in ("dialga", "palkia"):
            with self.subTest(species):
                key, enc = resolve(species, "platinum")
                self.assertEqual(key, species)
                self.assertEqual(enc.level, 70)
                self.assertEqual(encounter_level(species, "platinum"), 70)
                self.assertEqual(enc.games, ("platinum",))
                self.assertIn(species, supported("platinum"))
                self.assertNotIn(species, supported("heartgold"))

    def test_the_movesets_are_the_last_four_in_learn_order(self):
        self.assertEqual(moveset("dialga"),
                         ("Roar of Time", "Heal Block", "Earth Power", "Slash"))
        self.assertEqual(moveset("palkia"),
                         ("Spacial Rend", "Heal Block", "Earth Power", "Slash"))

    def test_they_differ_in_exactly_the_signature_slot(self):
        for i in (HEAL_BLOCK, EARTH_POWER, SLASH):
            with self.subTest(slot=i):
                self.assertEqual(moveset("dialga")[i], moveset("palkia")[i])
        self.assertNotEqual(moveset("dialga")[SIGNATURE], moveset("palkia")[SIGNATURE])

    def test_the_shifted_out_moves_include_the_dangerous_one(self):
        """Ancient Power(20) raises every stat at once including Speed, which is the one boost
        that threatens the no-speed-tie guarantee. Five moves are pushed out at 70 and that is
        one of them."""
        for species in ("dialga", "palkia"):
            with self.subTest(species):
                self.assertNotIn("Ancient Power", moveset(species))
                self.assertNotIn("Scary Face", moveset(species))

    def test_every_move_is_modelled(self):
        for species in ("dialga", "palkia"):
            with self.subTest(species):
                self.assertEqual(unsupported_moves(species, "platinum"), ((), None))

    def test_only_ONE_new_effect_was_needed_between_them(self):
        """Spacial Rend is effect 43, which Aeroblast already opened; Heal Block and Earth Power
        were already in. Roar of Time is the whole of the new work."""
        self.assertEqual(resolve_move("Spacial Rend").effect, 43)
        self.assertEqual(resolve_move("Slash").effect, 43)
        self.assertEqual(resolve_move("Heal Block").effect, 236)
        self.assertEqual(resolve_move("Earth Power").effect, 72)
        self.assertEqual(resolve_move("Roar of Time").effect, EFFECT_ROAR_OF_TIME)

    def test_the_ability_defaults_to_pressure_and_neither_holds_anything(self):
        from claytonlib.battle.stats import abilities
        for species in ("dialga", "palkia"):
            with self.subTest(species):
                self.assertEqual(ENCOUNTERS[species].ability, "")
                self.assertEqual(abilities(species)[0], "Pressure")
                self.assertEqual(target_held_item(species, "platinum"), "")

    def test_catch_rate_30_is_why_phase_2_runs_above_1_hp(self):
        """Ten times Suicune's. The figure lives in base_stats, and the point of asserting it is
        that the whole off-1-HP design rests on it."""
        from claytonlib.battle.stats import species as species_row
        for species in ("dialga", "palkia"):
            with self.subTest(species):
                self.assertEqual(species_row(species)["catch_rate"], 30)


class TestDialgaCannotBeBroughtTo1HP(unittest.TestCase):
    """The finding the design rests on, asserted so it cannot quietly stop being true."""

    def test_its_bulk_and_typing_are_what_the_arithmetic_says(self):
        dialga = _titan("dialga")
        self.assertEqual(dialga.max_hp, 241)
        self.assertEqual(dialga.stats["def"], 194)
        self.assertIn("Steel", dialga.types)       # resists False Swipe

    def test_false_swipe_needs_an_implausible_number_of_hits(self):
        """40 PP, halved to 20 by Pressure, against 240 HP of Steel. The solver must never plan
        a 1 HP route here -- see `solver.struggle_deadline` and clayton-6xu.9.3."""
        ours = replace(_wall(), moves=("False Swipe",), pp=(40,),
                       stats={**_wall().stats, "atk": 200})
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("False Swipe"), ours,
                                  _titan("dialga"), actor="M", slot=0)
        hits_needed = (_titan("dialga").max_hp - 1) / max(1, outcome.damage)
        self.assertGreater(hits_needed, 15)


class TestRoarOfTime(unittest.TestCase):
    def test_it_is_effect_80_and_modelled_target_side_only(self):
        self.assertIn(EFFECT_ROAR_OF_TIME, MODELLED_TARGET_EFFECTS)
        self.assertNotIn(EFFECT_ROAR_OF_TIME, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Roar of Time")))

    def test_the_recharge_costs_no_proc_roll(self):
        """`MOVE_SIDE_EFFECT_ON_HIT`, so it returns from the first branch of
        `BattleSystem_TriggerSecondaryEffect`. Three rolls: accuracy, crit, damage."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Roar of Time"), _titan("dialga"),
                                  _wall(), actor="E", slot=SIGNATURE)
        self.assertEqual(outcome.rolls, 3)
        self.assertFalse(outcome.secondary)
        self.assertTrue(outcome.starts_recharge)

    def test_A_MISS_IS_THE_ONE_WAY_TO_DODGE_IT(self):
        """90 accuracy, and the recharge is gated on the hit -- so a missed Roar of Time costs
        Dialga nothing and buys us nothing either. It is also the move's own sub-100 accuracy,
        which makes it this target's separator."""
        self.assertEqual(resolve_move("Roar of Time").accuracy, 90)
        missed = None
        for seed in range(0x0C0E_0200, 0x0C0E_0600):
            _, outcome = execute_move(seed, resolve_move("Roar of Time"), _titan("dialga"),
                                      _wall(evasion_stage=6), actor="E", slot=SIGNATURE)
            if not outcome.successful:
                missed = outcome
                break
        self.assertIsNotNone(missed, "no seed in range missed")
        self.assertFalse(missed.starts_recharge)


class TestTheRechargeTurn(unittest.TestCase):
    def _run(self, turns: int):
        config = _config()
        state = BattleState(ours=_wall(), target=_titan("dialga", SIGNATURE),
                            rng=opening_rng(0x0C0E02CA, config))
        rows = []
        for _ in range(turns):
            before = state.rng_offset
            state = simulate_turn(state, Action.MOVE_1, config)
            rows.append((state.log[-1], state.rng_offset - before, state.target.recharging))
        return state, rows

    def test_it_alternates_hit_then_recharge(self):
        _, rows = self._run(4)
        flat = ["".join(t) for t, _, _ in rows]
        self.assertIn("E1", flat[0])
        self.assertIn("Erch", flat[1])
        self.assertIn("E1", flat[2])
        self.assertIn("Erch", flat[3])

    def test_the_recharge_turn_costs_THE_TARGET_nothing(self):
        """No selection roll (`Battler_CanPickCommand` is FALSE), no status checks after state 4
        because the walk stops, and no post-move advances. Our own half still costs what it
        costs, so the saving is the difference between the two turns."""
        _, rows = self._run(2)
        hit_advances, recharge_advances = rows[0][1], rows[1][1]
        self.assertLess(recharge_advances, hit_advances)

    def test_it_spends_no_PP(self):
        """The ROM marks `ppDecremented` for a battler that cannot pick a command, which is the
        same reason Shadow Force's fire turn is free. Spending it twice would empty a 5 PP move
        in half the uses and shrink `usable_slots` early -- a desync, not a rounding error."""
        state, _ = self._run(2)
        self.assertEqual(state.target.pp[SIGNATURE], 39)

    def test_the_flag_clears_itself(self):
        state, rows = self._run(2)
        self.assertTrue(rows[0][2])
        self.assertFalse(rows[1][2])

    def test_no_selection_roll_is_spent_while_recharging(self):
        """Asked of the selector directly, because this is the half that is an advance
        difference rather than a verdict."""
        rng = 0x0C0E_02CA
        after_recharging, _ = select_target_move(rng, _titan("dialga", recharging=True))
        self.assertEqual(after_recharging, rng)
        after_normal, _ = select_target_move(rng, _titan("dialga", SIGNATURE))
        self.assertNotEqual(after_normal, rng)

    def test_it_is_state_4_so_it_short_circuits_paralysis(self):
        """Recharge is state 4 and paralysis state 12, and the recharge returns
        `CHECK_STATUS_DISRUPT_MOVE`, which stops the walk -- so a recharging AND paralyzed Dialga
        spends no paralysis roll. The same short-circuit the taunt refusal already models."""
        from claytonlib.battle_compass.state import Status
        config = _config()
        state = BattleState(
            ours=_wall(),
            target=_titan("dialga", SIGNATURE, recharging=True).with_status(Status.PARALYSIS),
            rng=opening_rng(0x0C0E02CA, config))
        before = state.rng_offset
        after = simulate_turn(state, Action.MOVE_1, config)
        paralyzed_recharge = after.rng_offset - before

        clean = BattleState(
            ours=_wall(),
            target=_titan("dialga", SIGNATURE, recharging=True),
            rng=opening_rng(0x0C0E02CA, config))
        before2 = clean.rng_offset
        after2 = simulate_turn(clean, Action.MOVE_1, config)
        self.assertEqual(paralyzed_recharge, after2.rng_offset - before2)
        self.assertIn("Erch", "".join(after.log[-1]))

    def test_the_recharging_target_is_NOT_semi_invulnerable(self):
        """The difference from a charge turn, and the reason this is the one free turn Dialga
        gives us: everything we throw at it connects."""
        from claytonlib.battle_compass.sim import is_semi_invulnerable
        self.assertFalse(is_semi_invulnerable(_titan("dialga", recharging=True)))

    def test_switching_out_would_clear_it(self):
        """`statusVolatile` is zeroed by the fresh BattleMon a send-out builds. Unreachable for a
        wild target, which never switches; asserted because the field must not be the one volatile
        that survives."""
        self.assertFalse(sent_out(_wall(recharging=True)).recharging)

    def test_fainting_clears_it(self):
        self.assertFalse(_wall(recharging=True).with_hp(0).recharging)


class TestPalkiaNeededNothingNew(unittest.TestCase):
    def test_spacial_rend_is_the_high_crit_group(self):
        """Effect 43, which Lugia's Aeroblast opened -- one crit stage up, so `% 8` rather than
        `% 16`. 95 accuracy, so it is Palkia's separator the way Roar of Time's 90 is Dialga's."""
        self.assertEqual(resolve_move("Spacial Rend").effect, 43)
        self.assertEqual(resolve_move("Spacial Rend").accuracy, 95)
        self.assertIn(43, MODELLED_TARGET_EFFECTS)

    def test_it_spends_no_recharge_and_no_proc(self):
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Spacial Rend"), _titan("palkia"),
                                  _wall(), actor="E", slot=SIGNATURE)
        self.assertFalse(outcome.starts_recharge)
        self.assertEqual(outcome.rolls, 3)

    def test_palkia_never_loses_a_turn(self):
        config = _config()
        state = BattleState(ours=_wall(), target=_titan("palkia", SIGNATURE),
                            rng=opening_rng(0x0C0E02CA, config))
        for _ in range(4):
            state = simulate_turn(state, Action.MOVE_1, config)
            self.assertFalse(state.target.recharging)
            self.assertNotIn("Erch", "".join(state.log[-1]))


if __name__ == "__main__":
    unittest.main()
