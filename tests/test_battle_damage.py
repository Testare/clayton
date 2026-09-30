"""Incoming damage, checked against notes/battle_compass.md's fixture tables."""
import math
import unittest

from claytonlib.battle.damage import (
    DAMAGE_ROLLS, Attacker, Defender, damage, damage_range, damage_spread,
    rolls_for_damage, stage_multiplier, unsupported_reason,
    TECHNICIAN_POWER_CAP, TYPE_ITEM_MODIFIER_PERCENT, effective_power,
    unsupported_attacker_reason,
)
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.moves import resolve_move

AURORA_BEAM = resolve_move("Aurora Beam")
GUST = resolve_move("Gust")
MIST = resolve_move("Mist")


def _suicune() -> Attacker:
    stats = derive_species_stats("suicune", 40, "Bold")
    return Attacker(level=40, attack=stats["atk"], special_attack=stats["spa"],
                    types=tuple(species("suicune")["types"]))


def _party(name: str, level: int) -> Defender:
    stats = derive_species_stats(name, level, "Hardy")
    return Defender(defence=stats["def"], special_defence=stats["spd"],
                    types=tuple(species(name)["types"]))


class TestFixtureTables(unittest.TestCase):
    """The ranges printed in sec 3.1 and sec 11.2, asserted so the doc and the code cannot drift.

    **This is a consistency check, not a verification.** The values are the model's own output.
    Only one row has ever been measured: Aurora Beam on Smeargle, which
    tests/test_battle_compass_ground_truth.py checks against three real hits from
    data/battle_logs/test1.jsonl. Nothing has been recorded against Magneton or Mamoswine, so
    those rows are predictions and a change in them proves only that the model changed.
    """

    EXPECTED = {
        # (party member, level): {move: (normal range, crit range)}
        ("magneton", 30): {"Aurora Beam": ((16, 19), (33, 39)), "Gust": ((5, 6), (10, 12))},
        ("smeargle", 60): {"Aurora Beam": ((24, 29), (49, 58)), "Gust": ((15, 18), (30, 36))},
        # Mamoswine is Ice/Ground, so Aurora Beam is x0.5 then x2. The ROM truncates BETWEEN
        # the two -- `DamageDivide(damage * tenths, 10)` once per defender type -- which loses up
        # to half a point that a single combined x1.0 keeps. Was (13, 16)/(27, 32) when the two
        # matchups were multiplied together first.
        ("mamoswine", 90): {"Aurora Beam": ((12, 16), (26, 32)), "Gust": ((9, 11), (18, 22))},
    }

    def test_incoming_damage_ranges(self):
        attacker = _suicune()
        for (name, level), moves in self.EXPECTED.items():
            defender = _party(name, level)
            for move_name, (normal, crit) in moves.items():
                move = resolve_move(move_name)
                self.assertEqual(damage_range(move, attacker, defender), normal,
                                 f"{name} {move_name}")
                self.assertEqual(damage_range(move, attacker, defender, critical=True), crit,
                                 f"{name} {move_name} crit")

    def test_gust_on_magneton_is_quartered_not_halved(self):
        """Electric resists Flying as well as Steel — an error the doc originally had."""
        attacker, defender = _suicune(), _party("magneton", 30)
        self.assertEqual(damage_range(GUST, attacker, defender), (5, 6))

    def test_magneton_survives_a_critical_aurora_beam(self):
        """The reason the fixture uses a Lv30 Magneton rather than a Lv17 Magnemite."""
        attacker = _suicune()
        for ivs in (0, 31):
            stats = derive_species_stats("magneton", 30, "Hardy", ivs=ivs)
            defender = Defender(defence=stats["def"], special_defence=stats["spd"],
                                types=tuple(species("magneton")["types"]))
            worst = damage_range(AURORA_BEAM, attacker, defender, critical=True)[1]
            self.assertLess(worst, stats["hp"], f"IVs {ivs}")

    def test_suicune_gets_no_stab_on_either_attack(self):
        """It is pure Water; Ice and Flying are both off-type, which the ranges assume."""
        self.assertNotIn(AURORA_BEAM.type_name, species("suicune")["types"])
        self.assertNotIn(GUST.type_name, species("suicune")["types"])


class TestDamageRollEntropy(unittest.TestCase):
    """The sec 3.1 identification signal: sixteen rolls collapsing onto six damage values."""

    def test_aurora_beam_on_smeargle_spreads_over_six_values(self):
        spread = damage_spread(AURORA_BEAM, _suicune(), _party("smeargle", 60))
        self.assertEqual(len(spread), 16)
        counts = {}
        for value in spread.values():
            counts[value] = counts.get(value, 0) + 1
        self.assertEqual(counts, {24: 2, 25: 3, 26: 4, 27: 3, 28: 3, 29: 1})

    def test_an_observed_value_narrows_the_roll(self):
        attacker, defender = _suicune(), _party("smeargle", 60)
        self.assertEqual(rolls_for_damage(29, AURORA_BEAM, attacker, defender), (100,))
        self.assertEqual(rolls_for_damage(26, AURORA_BEAM, attacker, defender),
                         (90, 91, 92, 93))

    def test_an_impossible_observation_yields_no_rolls(self):
        """Callers must surface this rather than emptying the candidate set (sec 3.1)."""
        attacker, defender = _suicune(), _party("smeargle", 60)
        self.assertEqual(rolls_for_damage(99, AURORA_BEAM, attacker, defender), ())


class TestStatStages(unittest.TestCase):
    def test_multipliers(self):
        self.assertEqual(stage_multiplier(0), 1.0)
        self.assertEqual(stage_multiplier(2), 2.0)
        self.assertEqual(stage_multiplier(6), 4.0)
        self.assertEqual(stage_multiplier(-6), 0.25)

    def test_out_of_range_stage_raises(self):
        for stage in (-7, 7):
            with self.assertRaises(ValueError):
                stage_multiplier(stage)

    def test_x_sp_def_cuts_chip_damage_but_not_crits(self):
        """Gen 4 crits ignore the defender's positive stages, so the danger floor is invariant
        under X Sp. Def — the finding behind sec 12.3's item tiering."""
        attacker = _suicune()
        base = _party("smeargle", 60)
        boosted = Defender(defence=base.defence, special_defence=base.special_defence,
                           types=base.types, special_defence_stage=6)
        self.assertEqual(damage_range(AURORA_BEAM, attacker, base), (24, 29))
        self.assertEqual(damage_range(AURORA_BEAM, attacker, boosted), (6, 8))
        # ...but the crit range does not move at all.
        self.assertEqual(damage_range(AURORA_BEAM, attacker, base, critical=True),
                         damage_range(AURORA_BEAM, attacker, boosted, critical=True))

    def test_negative_stages_still_apply_on_a_crit(self):
        attacker = _suicune()
        base = _party("smeargle", 60)
        lowered = Defender(defence=base.defence, special_defence=base.special_defence,
                           types=base.types, special_defence_stage=-2)
        self.assertGreater(damage_range(AURORA_BEAM, attacker, lowered, critical=True)[1],
                           damage_range(AURORA_BEAM, attacker, base, critical=True)[1])


class TestScopeGuards(unittest.TestCase):
    def test_status_moves_are_unsupported_and_raise(self):
        self.assertIsNotNone(unsupported_reason(MIST))
        with self.assertRaises(ValueError):
            damage(MIST, _suicune(), _party("smeargle", 60))

    def test_fixed_and_variable_power_moves_are_unsupported(self):
        for name in ("Seismic Toss", "Psywave", "Low Kick", "Flail"):
            self.assertIsNotNone(unsupported_reason(resolve_move(name)), name)

    def test_supported_moves_report_no_reason(self):
        self.assertIsNone(unsupported_reason(AURORA_BEAM))
        self.assertIsNone(unsupported_reason(GUST))

    def test_invalid_roll_raises(self):
        with self.assertRaises(ValueError):
            damage(AURORA_BEAM, _suicune(), _party("smeargle", 60), roll=84)

    def test_immunity_deals_zero_not_one(self):
        attacker = _suicune()
        ghost = Defender(defence=100, special_defence=100, types=("Ghost",))
        self.assertEqual(damage(resolve_move("Body Slam"), attacker, ghost), 0)

    def test_rolls_are_the_sixteen_gen4_values(self):
        self.assertEqual(DAMAGE_ROLLS, tuple(range(85, 101)))


class TestAbilityAndItemPowerModifiers(unittest.TestCase):
    """Order and arithmetic transcribed from src/battle/overlay_12_0224E4FC.c: Technician as
    `power * 15 / 10` when power <= 60, THEN a matching type-enhancing item as
    `power * (100 + mod) / 100`, both integer division.

    Neither was modelled, so Smeargle's False Swipe was computed at base power 40 instead of 72 --
    under-damaging by roughly 1.7x, which is what made the run's target HP bar wrong.
    """

    def _smeargle(self, ability="", item=""):
        return Attacker(level=60, attack=65, special_attack=60, types=("Normal",),
                        ability=ability, held_item=item)

    def _suicune(self):
        stats = derive_species_stats("suicune", 40, "Bold")
        return Defender(defence=stats["def"], special_defence=stats["spd"], types=("Water",))

    def test_technician_raises_a_weak_move_by_half(self):
        move = resolve_move("False Swipe")
        self.assertEqual(move.power, 40)
        self.assertEqual(effective_power(move, self._smeargle("Technician")), 60)

    def test_technician_stops_above_sixty(self):
        self.assertEqual(TECHNICIAN_POWER_CAP, 60)
        strong = resolve_move("Surf")          # power 90
        self.assertEqual(effective_power(strong, self._smeargle("Technician")), strong.power)

    def test_technician_applies_at_exactly_sixty(self):
        """The ROM's condition is `movePower <= 60`, inclusive."""
        move = resolve_move("Aurora Beam")     # power 65 -- just above
        self.assertEqual(effective_power(move, self._smeargle("Technician")), 65)

    def test_a_type_item_raises_a_matching_move(self):
        move = resolve_move("False Swipe")
        self.assertEqual(effective_power(move, self._smeargle(item="Silk Scarf")), 48)

    def test_a_type_item_ignores_a_mismatched_move(self):
        water = resolve_move("Surf")
        self.assertEqual(effective_power(water, self._smeargle(item="Silk Scarf")), water.power)

    def test_technician_applies_before_the_item(self):
        """Not cosmetic: the ROM orders them this way and both floor."""
        move = resolve_move("False Swipe")
        self.assertEqual(effective_power(move, self._smeargle("Technician", "Silk Scarf")), 72)
        # 40 -> x15/10 = 60 -> x120/100 = 72
        self.assertEqual(40 * 15 // 10 * (100 + TYPE_ITEM_MODIFIER_PERCENT) // 100, 72)

    def test_item_names_are_matched_case_and_space_insensitively(self):
        move = resolve_move("False Swipe")
        for spelling in ("Silk Scarf", "silk scarf", "  SILK SCARF  "):
            self.assertEqual(effective_power(move, self._smeargle(item=spelling)), 48)

    def test_the_damage_actually_changes(self):
        """The upper figure moved from (28, 33) to (27, 33) when the damage range was corrected
        to apply BEFORE STAB, as the ROM does. False Swipe is Normal on a Normal Smeargle, so
        STAB applies and the order is visible; Suicune's own Ice moves get no STAB, which is why
        incoming damage was unaffected by the same change."""
        move = resolve_move("False Swipe")
        bare = damage_range(move, self._smeargle(), self._suicune())
        full = damage_range(move, self._smeargle("Technician", "Silk Scarf"), self._suicune())
        self.assertEqual(bare, (16, 19))
        self.assertEqual(full, (27, 33))

    def test_an_unmodelled_ability_is_reported_not_ignored(self):
        """Same discipline as unsupported_reason: for INCOMING damage an unnoticed multiplier
        eliminates the true seed, so it must be refused rather than silently skipped."""
        self.assertIsNone(unsupported_attacker_reason(self._smeargle("Technician")))
        self.assertIsNone(unsupported_attacker_reason(self._smeargle("Pressure")))
        for ability in ("Huge Power", "Guts", "Blaze", "Sniper", "Adaptability"):
            self.assertIsNotNone(unsupported_attacker_reason(self._smeargle(ability)),
                                 f"{ability} changes damage and must be flagged")

    def test_no_ability_and_no_item_is_unchanged(self):
        move = resolve_move("False Swipe")
        self.assertEqual(effective_power(move, self._smeargle()), move.power)


class TestTheLevelTermIsIntegerDivision(unittest.TestCase):
    """The ROM computes `((level * 2 / 5) + 2)` in C -- integer division. A float form differs at
    any level where 2*level is not a multiple of 5. Level 40 and 60 are exact, which is why the
    section 11 fixture never revealed it."""

    def test_it_matches_the_rom_at_every_level(self):
        move = resolve_move("Gust")
        defender = Defender(defence=80, special_defence=80, types=("Normal",))
        for level in range(1, 101):
            attacker = Attacker(level=level, attack=100, special_attack=100, types=("Flying",))
            rom_term = (level * 2) // 5 + 2
            expected = math.floor(math.floor(math.floor(
                rom_term * move.power * 100 / 80) / 50)) + 2
            expected = math.floor(expected * 1.5)          # STAB
            expected = math.floor(expected * 1.0)          # Flying vs Normal
            self.assertEqual(damage(move, attacker, defender, roll=100), max(1, expected),
                             f"level {level}")

    def test_the_two_forms_really_do_diverge(self):
        """So the test above is not vacuous."""
        differing = [L for L in range(1, 101) if (L * 2) // 5 + 2 != 2 * L / 5 + 2]
        self.assertTrue(differing)
        self.assertIn(63, differing)
        self.assertNotIn(60, differing)
        self.assertNotIn(40, differing)


class TestTheRomsModifierOrder(unittest.TestCase):
    """The order is not a matter of taste -- each step truncates, so a different order is a
    different number. Transcribed from src/battle/overlay_12_0224E4FC.c and battle_command.c:

        CalcMoveDamage:      atk * power * ((level*2/5)+2) / def / 50, then + 2
        DamageCalcDefault:   damage *= criticalMultiplier
        BtlCmd_CalcDamage:   damage = ApplyDamageRange(damage)       <- the roll
        (separate command):  damage = damage * 15 / 10               <- STAB
                             damage = DamageDivide(damage * tenths, 10) per defender type

    An earlier version applied STAB and type effectiveness BEFORE the roll, which disagreed with
    the emulator on the third of five recorded False Swipe hits.
    """

    def _setup(self):
        stats = derive_species_stats("suicune", 40, "Bold")
        return (Attacker(level=60, attack=65, special_attack=60, types=("Normal",),
                         ability="Technician", held_item="Silk Scarf"),
                Defender(defence=stats["def"], special_defence=stats["spd"], types=("Water",)))

    def test_the_range_comes_before_stab(self):
        """Explicitly: applying STAB first gives a different answer for at least one roll."""
        move = resolve_move("False Swipe")
        attacker, defender = self._setup()
        level_term = (60 * 2) // 5 + 2
        base = 65 * effective_power(move, attacker) * level_term // defender.defence // 50 + 2
        for roll in range(85, 101):
            rom_order = base * roll // 100 * 15 // 10
            other_order = base * 15 // 10 * roll // 100
            if rom_order != other_order:
                self.assertEqual(damage(move, attacker, defender, roll=roll), rom_order,
                                 f"roll {roll}: the ROM order gives {rom_order}, the other "
                                 f"gives {other_order}")
                return
        self.fail("no roll distinguishes the two orders, so this test proves nothing")

    def test_the_level_term_truncates(self):
        """`((level * 2 / 5) + 2)` in C."""
        for level, expected in ((60, 26), (63, 27), (67, 28), (40, 18)):
            self.assertEqual((level * 2) // 5 + 2, expected)

    def test_the_base_divides_by_def_then_by_fifty(self):
        """Two truncations, not one combined divide by (def * 50)."""
        move = resolve_move("False Swipe")
        attacker, defender = self._setup()
        level_term = 26
        power = effective_power(move, attacker)
        stepwise = attacker.attack * power * level_term // defender.defence // 50
        combined = attacker.attack * power * level_term // (defender.defence * 50)
        # They agree here, but the ROM's form is the one implemented; assert the implemented one.
        self.assertEqual(damage(move, attacker, defender, roll=100),
                         (stepwise + 2) * 15 // 10)
        self.assertIsInstance(combined, int)

    def test_a_dual_type_truncates_once_per_type(self):
        """x0.5 then x2 is not x1 when each step truncates."""
        move = resolve_move("Aurora Beam")
        stats = derive_species_stats("suicune", 40, "Bold")
        attacker = Attacker(level=40, attack=stats["atk"],
                            special_attack=stats["spa"], types=("Water",))
        ice_ground = Defender(defence=100, special_defence=110, types=("Ice", "Ground"))
        neutral = Defender(defence=100, special_defence=110, types=("Normal",))
        halved_then_doubled = damage(move, attacker, ice_ground, roll=100)
        untouched = damage(move, attacker, neutral, roll=100)
        self.assertLessEqual(halved_then_doubled, untouched)

    def test_a_zero_result_floors_to_one(self):
        """ApplyDamageRange and DamageDivide both refuse to return 0 for a nonzero input."""
        move = resolve_move("Gust")
        weak = Attacker(level=1, attack=1, special_attack=1, types=("Flying",))
        tanky = Defender(defence=999, special_defence=999, types=("Normal",))
        self.assertGreaterEqual(damage(move, weak, tanky, roll=85), 1)


if __name__ == "__main__":
    unittest.main()


class TestCritIgnoresDamageReducingStages(unittest.TestCase):
    """A crit ignores every stat change that would reduce its damage: the target's raised
    defences and the attacker's lowered offences. Changes that would raise the damage still
    apply, in both directions."""

    def setUp(self):
        self.base_defender = _party("smeargle", 60)
        self.plain = damage_range(AURORA_BEAM, _suicune(), self.base_defender, critical=True)

    def _attacker(self, spa_stage=0):
        a = _suicune()
        return Attacker(level=a.level, attack=a.attack, special_attack=a.special_attack,
                        types=a.types, special_attack_stage=spa_stage)

    def _defender(self, spd_stage=0):
        d = self.base_defender
        return Defender(defence=d.defence, special_defence=d.special_defence, types=d.types,
                        special_defence_stage=spd_stage)

    def test_a_crit_ignores_the_targets_raised_special_defence(self):
        self.assertEqual(damage_range(AURORA_BEAM, self._attacker(), self._defender(6),
                                      critical=True), self.plain)

    def test_a_crit_ignores_the_attackers_lowered_special_attack(self):
        """So lowering the opponent's offence does not protect against its crits."""
        self.assertEqual(damage_range(AURORA_BEAM, self._attacker(-6), self._defender(),
                                      critical=True), self.plain)

    def test_a_crit_still_honours_the_targets_lowered_defence(self):
        lowered = damage_range(AURORA_BEAM, self._attacker(), self._defender(-2), critical=True)
        self.assertGreater(lowered[1], self.plain[1])

    def test_a_crit_still_honours_the_attackers_raised_offence(self):
        raised = damage_range(AURORA_BEAM, self._attacker(2), self._defender(), critical=True)
        self.assertGreater(raised[1], self.plain[1])

    def test_a_non_crit_honours_every_stage_in_both_directions(self):
        plain = damage_range(AURORA_BEAM, self._attacker(), self._defender())
        self.assertLess(damage_range(AURORA_BEAM, self._attacker(-2), self._defender())[1],
                        plain[1])
        self.assertLess(damage_range(AURORA_BEAM, self._attacker(), self._defender(2))[1],
                        plain[1])
        self.assertGreater(damage_range(AURORA_BEAM, self._attacker(2), self._defender())[1],
                           plain[1])
