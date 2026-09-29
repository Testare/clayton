"""Stat derivation, checked against the reference fixture in notes/battle_compass.md."""
import unittest

from claytonlib.battle.stats import (
    NATURES, calc_hp, calc_stat, derive_stats, nature_multiplier,
)

# Base stats for everything in the section 11 fixture.
SUICUNE = {"hp": 100, "atk": 75, "def": 115, "spa": 90, "spd": 115, "spe": 85}
MAGNETON = {"hp": 50, "atk": 60, "def": 95, "spa": 120, "spd": 70, "spe": 70}
SMEARGLE = {"hp": 55, "atk": 20, "def": 35, "spa": 20, "spd": 45, "spe": 75}
MAMOSWINE = {"hp": 110, "atk": 130, "def": 80, "spa": 70, "spd": 60, "spe": 80}


class TestNatures(unittest.TestCase):
    def test_twenty_five_natures_five_of_them_neutral(self):
        self.assertEqual(len(NATURES), 25)
        self.assertEqual(sum(1 for v in NATURES.values() if v is None), 5)

    def test_every_nature_raises_and_lowers_different_stats(self):
        for name, effect in NATURES.items():
            if effect is not None:
                self.assertNotEqual(effect[0], effect[1], name)

    def test_bold_raises_defence_and_lowers_attack(self):
        self.assertEqual(nature_multiplier("Bold", "def"), 1.1)
        self.assertEqual(nature_multiplier("Bold", "atk"), 0.9)
        self.assertEqual(nature_multiplier("Bold", "spe"), 1.0)

    def test_hp_is_never_affected_by_nature(self):
        for name in NATURES:
            self.assertEqual(nature_multiplier(name, "hp"), 1.0, name)

    def test_unknown_nature_raises(self):
        with self.assertRaises(ValueError):
            nature_multiplier("Sparkly", "atk")


class TestFixtureStats(unittest.TestCase):
    """Every number here is quoted in notes/battle_compass.md; a mismatch means one of the
    two is wrong, which is the point of asserting them."""

    def test_suicune_lv40_bold_perfect_ivs(self):
        self.assertEqual(
            derive_stats(SUICUNE, 40, "Bold"),
            {"hp": 142, "atk": 69, "def": 119, "spa": 89, "spd": 109, "spe": 85},
        )

    def test_suicune_max_hp_spans_130_to_142_across_hp_ivs(self):
        self.assertEqual(calc_hp(100, 0, 0, 40), 130)
        self.assertEqual(calc_hp(100, 31, 0, 40), 142)

    def test_suicune_speed_range_clears_smeargles_160_even_unparalyzed(self):
        speeds = [
            calc_stat(85, iv, 0, 40, mult)
            for iv in (0, 31) for mult in (0.9, 1.0, 1.1)
        ]
        self.assertEqual((min(speeds), max(speeds)), (65, 93))
        self.assertLess(max(speeds), 160)

    def test_suicune_spa_range_is_wide_enough_to_require_exact_ivs(self):
        """Why the damage filter needs the target's IVs entered (sec 14.1)."""
        spa = [calc_stat(90, iv, 0, 40, m) for iv in (0, 31) for m in (0.9, 1.0, 1.1)]
        self.assertEqual((min(spa), max(spa)), (69, 97))

    def test_party_hp_and_special_defence(self):
        for base, level, hp, spd in (
            (MAGNETON, 30, 79, 56),
            (SMEARGLE, 60, 154, 77),
            (MAMOSWINE, 90, 325, 140),
        ):
            stats = derive_stats(base, level, "Hardy")
            self.assertEqual((stats["hp"], stats["spd"]), (hp, spd), base)


class TestCalcEdges(unittest.TestCase):
    def test_nature_is_applied_after_flooring_not_before(self):
        """Folding the nature into one expression rounds differently for some spreads."""
        self.assertEqual(calc_stat(115, 31, 0, 40, 1.1), 119)  # floor(109 * 1.1), not floor(119.9..)

    def test_ev_quarters_are_floored(self):
        self.assertEqual(calc_stat(100, 31, 3, 50), calc_stat(100, 31, 0, 50))
        self.assertGreater(calc_stat(100, 31, 4, 50), calc_stat(100, 31, 0, 50))

    def test_out_of_range_inputs_raise(self):
        for kwargs in ({"iv": 32}, {"iv": -1}, {"ev": 253}, {"level": 0}, {"level": 101}):
            args = {"base": 100, "iv": 31, "ev": 0, "level": 50, **kwargs}
            with self.assertRaises(ValueError, msg=kwargs):
                calc_stat(**args)

    def test_derive_stats_rejects_incomplete_base_stats(self):
        with self.assertRaises(ValueError):
            derive_stats({"hp": 100}, 40)

    def test_derive_stats_accepts_per_stat_iv_and_ev_maps(self):
        stats = derive_stats(SMEARGLE, 60, "Jolly", ivs={"spe": 31, "atk": 0},
                             evs={"spe": 252})
        self.assertEqual(stats["spe"], calc_stat(75, 31, 252, 60, 1.1))


if __name__ == "__main__":
    unittest.main()
