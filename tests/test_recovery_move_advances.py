"""Tests for recovery/healing move RNG advances.

HP-recovery moves (Recover, Softboiled, Slack Off, Roost, Heal Order,
Morning Sun, Moonlight, Synthesis, Milk Drink) succeed only when
Chansey is not at full HP. Magikarp's Tackle hit sets user_is_full_hp=False,
allowing recovery to succeed and consume 2 POST_METRONOME_SUCCESS advances.

Ground truth: seedslurper actuals from Metroman2_test_7_vs_15f.jsonl.
Expected sequences derived directly from seedslurper BtlCmd_Metronome rolls.
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


class TestRecoveryMoveAdvances(unittest.TestCase):
    """Each test uses a seed where a recovery move appears at turn t_n.
    After recovery succeeds (Tackle → HP drops → Recover heals it),
    subsequent rolls must stay in sync: 2 POST_METRONOME_SUCCESS consumed.
    """

    # ------------------------------------------------------------------ Recover
    def test_recover_t1(self):
        # Recover, Last Resort (hit-then-fail), Secret Power, Fire Fang, Double-Edge, Flash
        actual, expected = _check(
            0xAB1AB0CF,
            ['Recover', 'Last Resort', 'Secret Power', 'Fire Fang', 'Double Edge', 'Flash'],
        )
        self.assertEqual(actual, expected)

    def test_recover_t2(self):
        # Assurance, Recover, Hidden Power, Water Pulse, Dragon Rage
        actual, expected = _check(
            0x93863EF0,
            ['Assurance', 'Recover', 'Hidden Power', 'Water Pulse', 'Dragon Rage'],
        )
        self.assertEqual(actual, expected)

    def test_recover_t4(self):
        actual, expected = _check(
            0x7A3C3EF0,
            ['Mud Bomb', 'Thunder Fang', 'String Shot', 'Recover', 'Bug Bite', 'Fire Punch'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Softboiled
    def test_softboiled_t2_air_slash(self):
        # Ice Ball (effect 117) locks for 4 continuations; Leaf Blade appears after t7.
        # Verify only through Ice Ball here (Leaf Blade requires n_turns=10).
        actual, expected = _check(
            0x175CB0CF,
            ['Air Slash', 'Softboiled', 'Ice Ball'],
        )
        self.assertEqual(actual, expected)

    def test_softboiled_t3(self):
        actual, expected = _check(
            0xBA5CB0CF,
            ['Spore', 'Spider Web', 'Sweet Scent', 'Softboiled', 'Steel Wing', 'Twineedle'],
        )
        self.assertEqual(actual, expected)

    def test_softboiled_t4(self):
        actual, expected = _check(
            0xA034B0CF,
            ['Razor Leaf', 'Return', 'Nasty Plot', 'Slack Off', 'Kinesis', 'Magic Coat'],
        )
        self.assertEqual(actual, expected)

    def test_softboiled_t2_zap_cannon(self):
        actual, expected = _check(
            0x0478B0CF,
            ['Shock Wave', 'Vacuum Wave', 'Horn Drill', 'Milk Drink', 'Safeguard', 'Aqua Ring'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Slack Off
    def test_slack_off_t3(self):
        actual, expected = _check(
            0x2D28B0CF,
            ['Magma Storm', 'Slack Off', 'Poison Powder', 'Double Kick', 'Howl', 'Hyper Beam'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Roost
    def test_roost_t1(self):
        actual, expected = _check(
            0x05ECB0CF,
            ['Roost', 'Crabhammer', 'Hyper Fang', 'Foresight', 'Perish Song', 'Leech Seed'],
        )
        self.assertEqual(actual, expected)

    def test_roost_t2(self):
        actual, expected = _check(
            0xDDF6B0CF,
            ['Extreme Speed', 'Roost', 'Thunder Fang', 'Amnesia', 'Poison Powder', 'Rock Slide'],
        )
        self.assertEqual(actual, expected)

    def test_roost_t4(self):
        actual, expected = _check(
            0xD826B0CF,
            ['Rapid Spin', 'Powder Snow', 'Giga Drain', 'Roost', 'Earthquake', 'Aqua Jet'],
        )
        self.assertEqual(actual, expected)

    def test_roost_t5(self):
        actual, expected = _check(
            0xFB06B0CF,
            ['Shadow Punch', 'Ice Beam', 'Dragon Dance', 'Mud Shot', 'Roost', 'Meditate'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Heal Order
    def test_heal_order_t2(self):
        actual, expected = _check(
            0x9F7AB0CF,
            ['Leech Seed', 'Heal Order', 'Water Gun', 'Cosmic Power', 'Mean Look', 'Substitute'],
        )
        self.assertEqual(actual, expected)

    def test_heal_order_t4(self):
        actual, expected = _check(
            0x03C63EF0,
            ['Lava Plume', 'Stun Spore', 'Quick Attack', 'Heal Order', 'Slash', 'Moonlight'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Milk Drink
    def test_milk_drink_t3(self):
        actual, expected = _check(
            0x8AA63EF0,
            ['Flash', 'Nasty Plot', 'Milk Drink', 'Waterfall', 'Baton Pass'],
        )
        self.assertEqual(actual, expected)

    def test_milk_drink_t4_shock_wave(self):
        actual, expected = _check(
            0x9D4CB0CF,
            ['Low Kick', 'Swift', 'Milk Drink', 'Heal Block', 'Defend Order', 'Smelling Salt'],
        )
        self.assertEqual(actual, expected)

    def test_milk_drink_t3_leaf_blade(self):
        actual, expected = _check(
            0x496E3EF0,
            ['Leaf Blade', 'Slam', 'Milk Drink', 'Water Spout', 'Reversal', 'Frenzy Plant'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Moonlight
    def test_moonlight_t2(self):
        actual, expected = _check(
            0xDBC8B0CF,
            ['Twister', 'Moonlight', 'Mud Bomb', 'Pain Split', 'Aurora Beam', 'Seed Bomb'],
        )
        self.assertEqual(actual, expected)

    def test_moonlight_t3(self):
        actual, expected = _check(
            0x27B63EF0,
            ['Ice Shard', 'Zen Headbutt', 'Moonlight', 'Aqua Ring', 'Weather Ball', 'Mean Look'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Synthesis
    def test_synthesis_t4(self):
        actual, expected = _check(
            0xDF643EF0,
            ['Fury Cutter', 'Rain Dance', 'Recycle', 'Synthesis', 'Harden', 'Super Fang'],
        )
        self.assertEqual(actual, expected)

    def test_synthesis_t5(self):
        actual, expected = _check(
            0x44FE3EF0,
            ['Moonlight', 'Vacuum Wave', 'Zap Cannon', 'Frustration', 'Synthesis', 'Zen Headbutt'],
        )
        self.assertEqual(actual, expected)

    # ------------------------------------------------------------------ Morning Sun
    def test_morning_sun_t2(self):
        actual, expected = _check(
            0xCA58B0CF,
            ['Spikes', 'Morning Sun', 'Brick Break', 'Thunder Wave', 'Razor Wind', 'Twister'],
        )
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
