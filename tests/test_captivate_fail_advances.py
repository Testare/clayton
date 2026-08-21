"""Tests for Captivate fail-path RNG advances.

In a same-gender matchup (Chansey female vs Magikarp female), Captivate always
fails. The game still consumes one hit-check advance on the fail path, so
subsequent Metronome rolls must account for it.

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
    actual_norm = [_normalize(n) for n in actual[:len(expected)]]
    expected_norm = [_normalize(n) for n in expected]
    return actual_norm, expected_norm


class TestCaptivateFailAdvances(unittest.TestCase):
    """Captivate (effect 265) fails vs same-gender target.
    The game still rolls one unobservable hit-check advance on the fail path.
    These tests verify that subsequent Metronome rolls stay in sync.
    """

    def test_captivate_t1(self):
        # Captivate at t1; verify moves through t4 (t5+ diverges due to Morning Sun recovery bug)
        actual, expected = _check(
            0x269EB0CF,
            ['Captivate', 'Hi Jump Kick', 'Metal Sound', 'Morning Sun'],
        )
        self.assertEqual(actual, expected)

    def test_captivate_t2_zap_cannon(self):
        actual, expected = _check(
            0xE7D23EF0,
            ['Zap Cannon', 'Captivate', 'Rollout', 'Dark Pulse'],
        )
        self.assertEqual(actual, expected)

    def test_captivate_t2_wake_up_slap(self):
        # Captivate at t2; verify moves through t5 (t6 diverges due to separate bug)
        actual, expected = _check(
            0xD2F83EF0,
            ['Wake-Up Slap', 'Captivate', 'Cosmic Power', 'Foresight', 'Taunt'],
        )
        self.assertEqual(actual, expected)

    def test_captivate_t4_rock_throw(self):
        actual, expected = _check(
            0x516A3EF0,
            ['Rock Throw', 'Supersonic', 'Screech', 'Captivate', 'Teeter Dance', 'Healing Wish'],
        )
        self.assertEqual(actual, expected)

    def test_captivate_t4_stun_spore(self):
        actual, expected = _check(
            0xC7E03EF0,
            ['Stun Spore', 'Gust', 'Thunder', 'Captivate', 'Knock Off', 'Recover'],
        )
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
