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


class TestInteractiveHiddenDuration(unittest.TestCase):
    """Interactive-mode handling of hidden-length locks and confusion."""

    def setUp(self):
        self.moves = _moves_by_number()

    def _locked_state(self, effect, move_num, turns):
        state = MetronomeBattleState()
        state.user_locked_effect = effect
        state.user_locked_move_num = move_num
        state.user_locked_turns = turns
        return state

    @patch('builtins.input')
    def test_interactive_rampage_ends_early_on_confirmation(self, mock_input):
        # Chansey locked into Outrage (effect 27). Interactive tracks the max lock
        # (2). Magikarp Splashes; Outrage continuation hits; the player confirms the
        # rampage ended this turn → lock clears and fatigue-confusion is applied.
        # Inputs: Magikarp move (sp), continuation hit (h), "did Rampage end?" (y).
        mock_input.side_effect = ["sp", "h", "y"]
        state = self._locked_state(effect=27, move_num=200, turns=2)
        ctx = InteractiveContext()
        ctx.battle_state['state'] = state
        simulate_turn(ctx, state, self.moves, frozenset(), magikarp_level=15)

        self.assertEqual(state.user_locked_turns, 0)
        self.assertIsNone(state.user_locked_move_num)
        # roll_hidden_duration returns the max (2-5 → 5) with no prompt.
        self.assertEqual(state.user_confusion_turns, 5)

    @patch('builtins.input')
    def test_interactive_rampage_continues_on_negative(self, mock_input):
        # Same setup, but the player says the rampage did NOT end → still locked,
        # no confusion yet. Inputs: Magikarp move (sp), continuation hit (h), (n).
        mock_input.side_effect = ["sp", "h", "n"]
        state = self._locked_state(effect=27, move_num=200, turns=2)
        ctx = InteractiveContext()
        ctx.battle_state['state'] = state
        simulate_turn(ctx, state, self.moves, frozenset(), magikarp_level=15)

        self.assertEqual(state.user_locked_turns, 1)          # decremented, still locked
        self.assertEqual(state.user_locked_move_num, 200)
        self.assertEqual(state.user_confusion_turns, 0)       # no fatigue yet

    @patch('builtins.input')
    def test_interactive_chansey_confusion_hit_self(self, mock_input):
        # Chansey confused (rampage fatigue). Magikarp Splashes; the player reports
        # Chansey hit itself → CFZ token, move fails, one confusion turn consumed.
        mock_input.side_effect = ["sp", "h"]  # magikarp sp, confusion "h"=hit itself
        state = MetronomeBattleState()
        state.user_confusion_turns = 2
        ctx = InteractiveContext()
        ctx.battle_state['state'] = state
        turn = simulate_turn(ctx, state, self.moves, frozenset(), magikarp_level=15)

        from claytonlib.metronome_compass.path import CFZ
        self.assertTrue(any(isinstance(t, CFZ) for t in turn))
        self.assertEqual(state.user_confusion_turns, 1)

    @patch('builtins.input')
    def test_interactive_chansey_confusion_attacks_through(self, mock_input):
        # Chansey confused but attacks through (no token); Metronome then resolves.
        # Inputs: magikarp sp, confusion "a"=attacked, metronome move, hit.
        mock_input.side_effect = ["sp", "a", "Tackle", "h"]
        state = MetronomeBattleState()
        state.user_confusion_turns = 2
        ctx = InteractiveContext()
        ctx.battle_state['state'] = state
        turn = simulate_turn(ctx, state, self.moves, frozenset(), magikarp_level=15)

        from claytonlib.metronome_compass.path import CFZ, SCFZ
        self.assertFalse(any(isinstance(t, (CFZ, SCFZ)) for t in turn))
        self.assertTrue(any(isinstance(t, MetronomeMove) for t in turn))
        self.assertEqual(state.user_confusion_turns, 1)


if __name__ == '__main__':
    unittest.main()
