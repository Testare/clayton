"""Tests for locking/rampage-move RNG advance counts.

Two sub-groups:
- Encore/Torment: status moves restricting the target's move choices.
- Rampage (Thrash, Outrage, Petal Dance): lock user 2-3 turns then confuse.

After the locking move at turn t_n, subsequent Metronome rolls must match
ground truth — verifying the locking move (and any continuation/confusion
turns) consume the correct number of advances.

Ground truth: seedslurper actuals.
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


def _check(seed: int, expected: list[str]):
    # 16 turns: two stacked rampages (Thrash + Uproar) push later selections
    # past the usual 8-turn budget.
    path = precompute_path(seed, magikarp_level=15, opposite_gender=False, n_turns=16)
    actual = _move_names(path)
    actual_norm = [_normalize(n) for n in actual[:len(expected)]]
    expected_norm = [_normalize(n) for n in expected]
    return actual_norm, expected_norm


class TestLockingMoveMoveSequences(unittest.TestCase):

    # ----------------------------------------------------- Encore / Torment
    def test_torment_t1(self):
        actual, expected = _check(
            0xE30CB0CF,
            ['Torment', 'Drill Peck', 'Air Slash', 'False Swipe', 'Cross Poison', 'Psywave'],
        )
        self.assertEqual(actual, expected)

    def test_encore_t1(self):
        actual, expected = _check(
            0xD76CB0CF,
            ['Encore', 'Sky Uppercut', 'Aqua Tail', 'Cross Chop', 'Twineedle', 'Hyper Voice'],
        )
        self.assertEqual(actual, expected)

    def test_torment_t4(self):
        actual, expected = _check(
            0x14303EF0,
            ['Hyper Fang', 'Dream Eater', 'Dragon Dance', 'Torment', 'Aerial Ace', 'Acid'],
        )
        self.assertEqual(actual, expected)

    def test_encore_t3(self):
        actual, expected = _check(
            0x3C1E3EF0,
            ['Guillotine', 'Magical Leaf', 'Encore', 'Tailwind', 'Aqua Ring', 'Dynamic Punch'],
        )
        self.assertEqual(actual, expected)

    def test_encore_t5(self):
        actual, expected = _check(
            0x03BEB0CF,
            ['Dragon Dance', 'Poison Jab', 'Vine Whip', 'Iron Defense', 'Encore', 'Spit Up'],
        )
        self.assertEqual(actual, expected)

    # ----------------------------------------------------- Rampage
    def test_thrash_t1(self):
        actual, expected = _check(
            0x9266B0CF,
            ['Thrash', 'Uproar', 'Cosmic Power', 'Earth Power', 'Zen Headbutt'],
        )
        self.assertEqual(actual, expected)

    def test_petal_dance_t1(self):
        actual, expected = _check(
            0xE3623EF0,
            ['Petal Dance', 'Low Kick', 'Swallow', 'Safeguard'],
        )
        self.assertEqual(actual, expected)

    def test_outrage_t1(self):
        actual, expected = _check(
            0x55DA3EF0,
            ['Outrage', 'Healing Wish'],
        )
        self.assertEqual(actual, expected)

    def test_petal_dance_t2(self):
        actual, expected = _check(
            0xBD44B0CF,
            ['Bonemerang', 'Petal Dance', 'Mud-Slap', 'Attack Order'],
        )
        self.assertEqual(actual, expected)

    def test_outrage_t3(self):
        actual, expected = _check(
            0xA3D6B0CF,
            ['Thunderbolt', 'Pluck', 'Outrage', 'Psych Up', 'Double Hit', 'Snore'],
        )
        self.assertEqual(actual, expected)


if __name__ == '__main__':
    unittest.main()
