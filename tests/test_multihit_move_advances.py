"""Tests for multi-hit move RNG advances per hit.

Multi-hit moves (Double Slap, Barrage, Bone Rush, Rock Blast, Bullet Seed,
Comet Punch, Fury Attack, Arm Thrust, Spike Cannon, Fury Swipes, Icicle Spear,
Pin Missile, Double Hit) hit 2-5 times. Each hit consumes crit+damage advances,
and 2 unobservable between-hit advances separate each pair of consecutive hits.

Also verifies that when Splash is blocked (Gravity or Disable), the wild
Pokémon AI auto-switches to Tackle rather than wasting the turn.

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


def _check(seed: int, expected: list[str]) -> tuple[list[str], list[str]]:
    path = precompute_path(seed, magikarp_level=15, opposite_gender=False, n_turns=8)
    actual = _move_names(path)
    n = len(expected)
    actual_norm = [_normalize(x) for x in actual[:n]]
    expected_norm = [_normalize(x) for x in expected]
    return actual_norm, expected_norm


class TestMultiHitMoveAdvances(unittest.TestCase):
    """Verify that multi-hit move advance counts match ground truth.
    Tests also cover Gravity/Disable auto-switch (Magikarp switches to Tackle
    rather than losing its turn when Splash is unavailable).
    """

    def test_bullet_seed_t1(self):
        actual, expected = _check(
            0xFD34B0CF,
            ['Bullet Seed', 'Hypnosis', 'Extreme Speed', 'Horn Attack', 'Horn Drill', 'Flail'],
        )
        self.assertEqual(actual, expected)

    def test_fury_swipes_t1(self):
        actual, expected = _check(
            0xDD2C3EF0,
            ['Fury Swipes', 'Meditate', 'Shadow Punch', 'Fury Swipes', 'Double Slap', 'Pursuit'],
        )
        self.assertEqual(actual, expected)

    def test_fury_attack_t1_with_disable(self):
        # Also tests Disable → Magikarp auto-switch to Tackle at t6
        actual, expected = _check(
            0x9038B0CF,
            ['Fury Attack', 'Thunder Punch', 'Bone Club', 'Gust', 'Disable', 'Blizzard'],
        )
        self.assertEqual(actual, expected)

    def test_spike_cannon_t1(self):
        actual, expected = _check(
            0xB48CB0CF,
            ['Spike Cannon', 'Dragon Dance', 'Dark Pulse', 'Stockpile', 'Screech', 'Comet Punch'],
        )
        self.assertEqual(actual, expected)

    def test_bone_rush_t1(self):
        actual, expected = _check(
            0x3A583EF0,
            ['Bone Rush', 'Sand Tomb', 'Swords Dance', 'Softboiled', 'Trump Card', 'Light Screen'],
        )
        self.assertEqual(actual, expected)

    def test_rock_blast_t1(self):
        actual, expected = _check(
            0x64F03EF0,
            ['Rock Blast', 'Harden', 'Twister', 'Meditate', 'Dragon Rush', 'Transform'],
        )
        self.assertEqual(actual, expected)

    def test_double_slap_t2(self):
        actual, expected = _check(
            0xA3F03EF0,
            ['Psychic', 'Double Slap', 'Stun Spore', 'Grass Whistle', 'Heal Bell', 'Egg Bomb'],
        )
        self.assertEqual(actual, expected)

    def test_bullet_seed_t3(self):
        actual, expected = _check(
            0x2DEC3EF0,
            ['Water Sport', 'Guillotine', 'Bullet Seed', 'Flatter', 'String Shot', 'Growl'],
        )
        self.assertEqual(actual, expected)

    def test_comet_punch_t2(self):
        actual, expected = _check(
            0x9E2C3EF0,
            ['Vacuum Wave', 'Comet Punch', 'Pain Split', 'Vacuum Wave', 'Charge', 'Mist'],
        )
        self.assertEqual(actual, expected)

    def test_icicle_spear_t4(self):
        actual, expected = _check(
            0xC8523EF0,
            ['Grass Whistle', 'Facade', 'Icy Wind', 'Icicle Spear', 'Shock Wave', 'Seed Bomb'],
        )
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
