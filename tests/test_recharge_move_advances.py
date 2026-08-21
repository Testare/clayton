"""Tests for recharge-move RNG advance counts (Hyper Beam family).

Verifies that the recharge turn correctly consumes no Metronome roll
(move_success=False) so subsequent turns stay in sync with ground truth.

Ground truth: seedslurper actuals from Metroman2_test_7_vs_15f.jsonl.
"""
import unittest
from claytonlib.metronome_compass import precompute_path
from claytonlib.metronome_compass.path import MetronomeMove
from claytonlib.moves import _moves_by_number


def _normalize(name: str) -> str:
    return name.lower().replace('-', ' ').replace('_', ' ')


def _move_names(path) -> list[str]:
    moves = _moves_by_number()
    return [moves[t.move_num].name
            for turn in path
            for t in turn
            if isinstance(t, MetronomeMove)]


def _check(seed: int, expected: list[str]) -> list[str]:
    path = precompute_path(seed, magikarp_level=15, opposite_gender=False, n_turns=8)
    actual = _move_names(path)
    actual_norm = [_normalize(n) for n in actual[:len(expected)]]
    expected_norm = [_normalize(n) for n in expected]
    return actual_norm, expected_norm


class TestRechargeMoveMoveSequences(unittest.TestCase):
    """Each test uses a seed where a recharge move appears at turn t_n.
    After the forced recharge turn, the subsequent Metronome rolls must match
    the ground truth — verifying the recharge turn consumes the correct
    number of advances (no Metronome roll, move_success=False).
    """

    # ------------------------------------------------------------------ t1
    def test_blast_burn_t1(self):
        actual, expected = _check(
            0xF47CB0CF,
            ['Blast Burn', 'Acid', 'Tail Whip', 'Metal Claw', 'Cut', 'Thrash'],
        )
        self.assertEqual(actual, expected)

    def test_hyper_beam_t1(self):
        actual, expected = _check(
            0x9BD8B0CF,
            ['Hyper Beam', 'Seed Bomb', 'Power Gem', 'Heal Block', 'Superpower', 'Ice Shard'],
        )
        self.assertEqual(actual, expected)

    def test_hydro_cannon_t1(self):
        actual, expected = _check(
            0x23463EF0,
            ['Hydro Cannon', 'Doom Desire', 'Shadow Claw', 'Discharge', 'Tickle', 'Peck'],
        )
        self.assertEqual(actual, expected)

    def test_frenzy_plant_t1(self):
        # Path ends early (Rest at t4 → Chansey sleeps)
        actual, expected = _check(
            0xBFE43EF0,
            ['Frenzy Plant', 'Shadow Sneak', 'Ice Punch', 'Rest'],
        )
        self.assertEqual(actual, expected)

    def test_rock_wrecker_t1(self):
        actual, expected = _check(
            0x2470B0CF,
            ['Rock Wrecker', 'Glare', 'Flatter', 'Sandstorm', 'Psywave', 'Dragon Rage'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ t2
    def test_blast_burn_t2_milk_drink(self):
        actual, expected = _check(
            0xC3E23EF0,
            ['Milk Drink', 'Blast Burn', 'Mist', 'Hyper Fang', 'Superpower', 'Light Screen'],
        )
        self.assertEqual(actual, expected)

    def test_blast_burn_t2_acupressure(self):
        actual, expected = _check(
            0x0A48B0CF,
            ['Acupressure', 'Blast Burn', 'Bubble', 'Thunder', 'Volt Tackle', 'Doom Desire'],
        )
        self.assertEqual(actual, expected)

    def test_hyper_beam_t2_gyro_ball(self):
        actual, expected = _check(
            0xEE7A3EF0,
            ['Gyro Ball', 'Hyper Beam', 'Crabhammer', 'Roar of Time', 'Vacuum Wave', 'Rock Wrecker'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ t3
    def test_frenzy_plant_t2_rock_climb(self):
        actual, expected = _check(
            0x2188B0CF,
            ['Rock Climb', 'Frenzy Plant', 'Super Fang', 'Iron Tail', 'Mud-Slap', 'Magic Coat'],
        )
        self.assertEqual(actual, expected)

    def test_blast_burn_t2_defog(self):
        actual, expected = _check(
            0xCCC23EF0,
            ['Defog', 'Blast Burn', 'Rock Tomb', 'Wake-Up Slap', 'Mud Sport', 'Splash'],
        )
        self.assertEqual(actual, expected)

    def test_blast_burn_t3_worry_seed(self):
        actual, expected = _check(
            0x6F963EF0,
            ['Worry Seed', 'Pursuit', 'Blast Burn', 'Swift', 'False Swipe', 'Iron Tail'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ t4
    def test_blast_burn_t4_wring_out(self):
        actual, expected = _check(
            0xE60C3EF0,
            ['Wring Out', 'Supersonic', 'Mirror Shot', 'Blast Burn', 'Flamethrower', 'Fake Tears'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ t5
    def test_hydro_cannon_t5_fire_blast(self):
        actual, expected = _check(
            0x5C103EF0,
            ['Fire Blast', 'Hyper Voice', 'Ice Shard', 'Flatter', 'Hydro Cannon', 'Tail Glow'],
        )
        self.assertEqual(actual, expected)

    def test_giga_impact_t3_aerial_ace(self):
        actual, expected = _check(
            0x6D5E3EF0,
            ['Aerial Ace', 'Flail', 'Giga Impact', 'Mirror Shot', 'Body Slam', 'Perish Song'],
        )
        self.assertEqual(actual, expected)

    def test_giga_impact_t4_zen_headbutt(self):
        actual, expected = _check(
            0x95BE3EF0,
            ['Zen Headbutt', 'Doom Desire', 'Bite', 'Giga Impact', 'Needle Arm', 'Sing'],
        )
        self.assertEqual(actual, expected)

    def test_frenzy_plant_t4_guard_swap(self):
        actual, expected = _check(
            0x10D2B0CF,
            ['Guard Swap', 'Water Spout', 'Shadow Ball', 'Frenzy Plant', 'Imprison', 'Disable'],
        )
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
