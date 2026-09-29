"""Incoming damage, checked against notes/battle_compass.md's fixture tables."""
import unittest

from claytonlib.battle.damage import (
    DAMAGE_ROLLS, Attacker, Defender, damage, damage_range, damage_spread,
    rolls_for_damage, stage_multiplier, unsupported_reason,
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
    """These exact ranges appear in sec 3.1 and sec 11.2; the doc and the code must agree."""

    EXPECTED = {
        # (party member, level): {move: (normal range, crit range)}
        ("magneton", 30): {"Aurora Beam": ((16, 19), (33, 39)), "Gust": ((5, 6), (10, 12))},
        ("smeargle", 60): {"Aurora Beam": ((24, 29), (49, 58)), "Gust": ((15, 18), (30, 36))},
        ("mamoswine", 90): {"Aurora Beam": ((13, 16), (27, 32)), "Gust": ((9, 11), (18, 22))},
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


if __name__ == "__main__":
    unittest.main()
