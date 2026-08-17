"""Unit tests for metronome_compass module."""
import unittest
from unittest.mock import patch
import datetime as dt

from claytonlib.metronome_compass import (
    _parse_turn_tokens,
    precompute_path,
    simulate_turn,
    metronome_compass,
    CompassMetronomeInput,
    RngContext,
    InteractiveContext,
    MetronomeMove,
    MagikarpMove,
    Hit,
    Miss,
    Crit,
    EffectProc,
    MetronomeBattleState,
)
from claytonlib.moves import _moves_by_number

class TestParseTurnTokens(unittest.TestCase):
    def setUp(self):
        self.moves = _moves_by_number()

    def test_parse_move_and_outcomes(self):
        tokens = _parse_turn_tokens("Flamethrower h sp", self.moves)
        self.assertEqual(len(tokens), 3)
        self.assertIsInstance(tokens[0], MetronomeMove)
        self.assertEqual(tokens[0].move_num, 53)
        self.assertIsInstance(tokens[1], Hit)
        self.assertIsInstance(tokens[2], MagikarpMove)
        self.assertEqual(tokens[2].move, 'sp')

    def test_parse_m_notation(self):
        tokens = _parse_turn_tokens("M053 ! ~ tk", self.moves)
        self.assertEqual(len(tokens), 4)
        self.assertEqual(tokens[0].move_num, 53)
        self.assertIsInstance(tokens[1], Crit)
        self.assertIsInstance(tokens[2], EffectProc)
        self.assertEqual(tokens[3].move, 'tk')

    def test_parse_miss(self):
        tokens = _parse_turn_tokens("Tackle - sp", self.moves)
        self.assertEqual(len(tokens), 3)
        self.assertIsInstance(tokens[1], Miss)

    def test_unknown_token_raises(self):
        with self.assertRaises(ValueError):
            _parse_turn_tokens("Flamethrower invalid sp", self.moves)

class TestPrecomputePath(unittest.TestCase):
    def test_deterministic(self):
        # Using seeds that are known to not hit unsupported moves for at least 2 turns.
        seed = 0xDEADEAD
        path1 = precompute_path(seed, magikarp_level=2, opposite_gender=False, n_turns=2)
        path2 = precompute_path(seed, magikarp_level=2, opposite_gender=False, n_turns=2)
        self.assertEqual(path1, path2)
        self.assertEqual(len(path1), 2)

    def test_different_seeds_different_paths(self):
        # This might fail by chance but very unlikely for 2 turns
        seed1 = 0xDEADEAD
        seed2 = 0x87654321
        path1 = precompute_path(seed1, magikarp_level=15, opposite_gender=False, n_turns=2)
        path2 = precompute_path(seed2, magikarp_level=15, opposite_gender=False, n_turns=2)
        self.assertNotEqual(path1, path2)

class TestSimulateTurn(unittest.TestCase):
    def setUp(self):
        self.moves = _moves_by_number()

    def test_rng_context_advances(self):
        seed = 0x12345678
        ctx = RngContext(seed)
        state = MetronomeBattleState()
        ctx.battle_state['state'] = state
        turn = simulate_turn(ctx, state, self.moves, frozenset(), magikarp_level=2)
        self.assertNotEqual(ctx.rng, seed)
        self.assertGreater(len(turn), 0)

    @patch('builtins.input')
    def test_interactive_context_prompts(self, mock_input):
        # Magikarp moves first. Answers in order:
        # 1. Magikarp move selection (sp/tk)
        # 2. Metronome move
        # 3. hit/crit/miss
        # 4. effect proc (Flamethrower has 10% burn)
        mock_input.side_effect = ["sp", "Flamethrower", "h", "~"]

        ctx = InteractiveContext()
        state = MetronomeBattleState()
        ctx.battle_state['state'] = state
        turn = simulate_turn(ctx, state, self.moves, frozenset(), magikarp_level=15)

        self.assertEqual(len(turn), 4)
        self.assertIsInstance(turn[0], MagikarpMove)
        self.assertIsInstance(turn[1], MetronomeMove)
        self.assertEqual(turn[1].move_num, 53)
        self.assertIsInstance(turn[2], Hit)
        self.assertIsInstance(turn[3], EffectProc)

if __name__ == '__main__':
    unittest.main()
