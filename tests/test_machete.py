"""
Unit tests for machete.py — path solver and jane_tree decision tree.
"""
import copy
import unittest
from fractions import Fraction

from claytonlib.safari import SafariContext, SafariPokemon, SafariStep, SafariContextState
from claytonlib.machete import (
    MacheteConfig,
    machete_config,
    JaneNode,
    CAPTURED_NODE,
    FUTILE_NODE,
    _apply_path,
    _jane_tree,
    machete_one,
    machete_all,
    machete_jane,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# Metang seed from the notebook — known to immediately capture on the first ball
# with _EASY_POKEMON (catch_rate=200). Used to test the immediate-capture edge case.
_METANG_SEED = 0xCC16BF30

# A nearby seed chosen so the first ball with _EASY_POKEMON does NOT immediately
# capture, giving us a non-trivial prefix for the prefix-path test.
_PREFIX_SEED = 0xCC16BF38  # first ball gives BALL_0 (not CAPTURED) with _EASY_POKEMON

# A SafariPokemon with guaranteed-never-flee (flee_rate=0) and moderate catch rate.
# Created directly to avoid depending on safari_pokemon.json in all tests.
_EASY_POKEMON = SafariPokemon(name='easy', base_catch_rate=200, base_flee_rate=0)

# A pokemon that always flees immediately (flee_rate=255 guarantees flee on first check).
_FLEE_POKEMON = SafariPokemon(name='fleey', base_catch_rate=1, base_flee_rate=255)


def _make_ctx(pokemon: SafariPokemon, seed: int) -> SafariContext:
    return SafariContext.start_encounter(seed, pokemon)


def _replay_path(ctx: SafariContext, path: str) -> SafariStep:
    """Replay a machete path on a fresh copy of ctx, return the final step."""
    ctx2 = copy.copy(ctx)
    result = None
    for ch in path:
        if ch == 'b' or ch == 'B':
            result = ctx2.throw_bait()
        elif ch == 'm' or ch == 'M':
            result = ctx2.throw_mud()
        else:  # 0 1 2 3 C
            result = ctx2.throw_ball()
    return result


# ---------------------------------------------------------------------------
# TestApplyPath
# ---------------------------------------------------------------------------

class TestApplyPath(unittest.TestCase):

    def test_empty_path_is_noop(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        rng_before = ctx.rng_state
        _apply_path(ctx, '')
        self.assertEqual(ctx.rng_state, rng_before)

    def test_spaces_and_commas_ignored(self):
        ctx_a = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        ctx_b = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        # Simulate one ball on ctx_a manually
        result_a = ctx_a.throw_ball()
        # Apply same ball via path with spaces on ctx_b
        _apply_path(ctx_b, f' {result_a.value} ')
        self.assertEqual(ctx_a.rng_state, ctx_b.rng_state)

    def test_undo_raises(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        with self.assertRaises(ValueError):
            _apply_path(ctx, 'u')

    def test_flee_raises(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        with self.assertRaises(ValueError):
            _apply_path(ctx, 'F')

    def test_unknown_char_raises(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        with self.assertRaises(ValueError):
            _apply_path(ctx, 'x')

    def test_wrong_outcome_raises(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        ctx2 = copy.copy(ctx)
        actual = ctx2.throw_ball()
        # Find a ball character that is NOT the actual outcome
        wrong = next(
            c for c in ('0', '1', '2', '3', 'C')
            if c != actual.value
        )
        with self.assertRaises(ValueError):
            _apply_path(ctx, wrong)

    def test_correct_outcome_advances_state(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        ctx_ref = copy.copy(ctx)
        actual = ctx_ref.throw_ball()
        _apply_path(ctx, actual.value)
        self.assertEqual(ctx.rng_state, ctx_ref.rng_state)


# ---------------------------------------------------------------------------
# TestMacheteOne
# ---------------------------------------------------------------------------

class TestMacheteOne(unittest.TestCase):

    def test_returns_string_or_none(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = machete_one(ctx)
        self.assertTrue(result is None or isinstance(result, str))

    def test_path_ends_with_C_when_found(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = machete_one(ctx, max_turns=4)
        if result is not None:
            self.assertEqual(result[-1], 'C')

    def test_path_is_valid_when_replayed(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = machete_one(ctx, max_turns=4)
        if result is not None:
            final = _replay_path(_make_ctx(_EASY_POKEMON, _METANG_SEED), result)
            self.assertEqual(final, SafariStep.CAPTURED)

    def test_fled_context_returns_none(self):
        # A context already in FLED state has no viable paths.
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        ctx.state = SafariContextState.FLED
        result = machete_one(ctx)
        self.assertIsNone(result)

    def test_accepts_safaripokemon_with_seed(self):
        result = machete_one(_EASY_POKEMON, seed=_METANG_SEED, max_turns=4)
        self.assertTrue(result is None or isinstance(result, str))

    def test_requires_seed_when_pokemon_passed(self):
        with self.assertRaises(ValueError):
            machete_one(_EASY_POKEMON)

    def test_path_no_longer_than_machete_all_shortest(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        one = machete_one(ctx, max_turns=4)
        all_paths, _ = machete_all(_make_ctx(_EASY_POKEMON, _METANG_SEED), max_turns=4)
        if one is not None and all_paths:
            self.assertLessEqual(len(one), min(len(p) for p in all_paths))

    def test_max_turns_zero_returns_none(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = machete_one(ctx, max_turns=0)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# TestMacheteAll
# ---------------------------------------------------------------------------

class TestMacheteAll(unittest.TestCase):

    def _get_paths(self, seed=_METANG_SEED, max_turns=4):
        ctx = _make_ctx(_EASY_POKEMON, seed)
        return machete_all(ctx, max_turns=max_turns)

    def test_returns_tuple(self):
        result = self._get_paths()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_all_paths_end_with_C(self):
        paths, _ = self._get_paths()
        for p in paths:
            self.assertEqual(p[-1], 'C', f"Path {p!r} does not end with C")

    def test_all_paths_valid_when_replayed(self):
        paths, _ = self._get_paths()
        for p in paths:
            ctx0 = _make_ctx(_EASY_POKEMON, _METANG_SEED)
            final = _replay_path(ctx0, p)
            self.assertEqual(final, SafariStep.CAPTURED, f"Path {p!r} did not capture")

    def test_no_duplicate_paths(self):
        paths, _ = self._get_paths()
        self.assertEqual(len(paths), len(set(paths)))

    def test_bfs_order_non_decreasing_length(self):
        paths, _ = self._get_paths()
        lengths = [len(p) for p in paths]
        self.assertEqual(lengths, sorted(lengths))

    def test_truncated_nonzero_when_limit_tight(self):
        # With max_turns=1, almost nothing will capture but lots will truncate.
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        _, truncated = machete_all(ctx, max_turns=1)
        self.assertGreater(truncated, 0)

    def test_truncated_zero_when_all_paths_terminate_naturally(self):
        # A pokemon that flees after one action has no bait/mud infinite branches —
        # all paths terminate within 2 turns, so nothing should be truncated.
        ctx = _make_ctx(_FLEE_POKEMON, _METANG_SEED)
        _, truncated = machete_all(ctx, max_turns=5)
        self.assertEqual(truncated, 0)

    def test_fled_context_returns_empty(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        ctx.state = SafariContextState.FLED
        paths, truncated = machete_all(ctx)
        self.assertEqual(paths, [])
        self.assertEqual(truncated, 0)

    def test_path_prefix_respected(self):
        # Paths from machete_all with a prefix, when prepended with the prefix,
        # should all appear in machete_all without prefix (they are valid sub-paths).
        # Uses _PREFIX_SEED which is chosen so the first ball does not immediately capture.
        ctx_ref = _make_ctx(_EASY_POKEMON, _PREFIX_SEED)
        first_step = copy.copy(ctx_ref).throw_ball()
        self.assertNotEqual(first_step, SafariStep.CAPTURED,
                            "_PREFIX_SEED immediately captures — choose a different seed")
        prefix = first_step.value
        suffix_max = 4
        # No-prefix search needs extra budget equal to prefix length so it can
        # contain paths of the form prefix + suffix (up to suffix_max turns).
        paths_no_prefix, _ = machete_all(
            _EASY_POKEMON, seed=_PREFIX_SEED, max_turns=suffix_max + len(prefix)
        )
        paths_with_prefix, _ = machete_all(
            _EASY_POKEMON, seed=_PREFIX_SEED, path=prefix, max_turns=suffix_max
        )
        full_set = set(paths_no_prefix)
        for p in paths_with_prefix:
            self.assertIn(prefix + p, full_set)

    def test_immediate_capture_no_error(self):
        # _METANG_SEED with _EASY_POKEMON captures on the very first ball.
        # Verify machete handles this gracefully.
        ctx_ref = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        first_step = copy.copy(ctx_ref).throw_ball()
        self.assertEqual(first_step, SafariStep.CAPTURED,
                         "_METANG_SEED no longer immediately captures — update fixture")
        one = machete_one(_make_ctx(_EASY_POKEMON, _METANG_SEED))
        self.assertEqual(one, 'C')
        paths, _ = machete_all(_make_ctx(_EASY_POKEMON, _METANG_SEED), max_turns=4)
        self.assertIn('C', paths)


# ---------------------------------------------------------------------------
# TestJaneTree
# ---------------------------------------------------------------------------

class TestJaneTree(unittest.TestCase):

    def test_empty_candidates_returns_none(self):
        self.assertIsNone(_jane_tree([]))

    def test_all_empty_paths_returns_futile(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = _jane_tree([(ctx, []), (copy.copy(ctx), [])])
        self.assertIs(result, FUTILE_NODE)

    def test_returns_jane_node(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx, max_turns=4)
        if not paths:
            self.skipTest("No paths found for this seed")
        result = _jane_tree([(copy.copy(ctx), paths)])
        self.assertIsInstance(result, JaneNode)

    def test_probability_between_zero_and_one(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx, max_turns=4)
        if not paths:
            self.skipTest("No paths found")
        result = _jane_tree([(copy.copy(ctx), paths)])
        self.assertGreaterEqual(result.probability, Fraction(0))
        self.assertLessEqual(result.probability, Fraction(1))

    def test_single_seed_with_paths_has_positive_probability(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx, max_turns=4)
        if not paths:
            self.skipTest("No paths found")
        result = _jane_tree([(copy.copy(ctx), paths)])
        self.assertGreater(result.probability, Fraction(0))

    def test_empty_paths_seed_in_same_bucket_lowers_probability(self):
        # A fled (terminal) seed counts in the denominator but contributes 0 to
        # the numerator, so probability must be strictly less than with one good seed.
        ctx_good = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx_good, max_turns=4)
        if not paths:
            self.skipTest("No paths found")
        ctx_fled = copy.copy(ctx_good)
        ctx_fled.state = SafariContextState.FLED
        result_two = _jane_tree([
            (copy.copy(ctx_good), paths),
            (ctx_fled, []),
        ])
        result_one = _jane_tree([(copy.copy(ctx_good), paths)])
        self.assertLess(result_two.probability, result_one.probability)

    def test_terminated_seed_counted_in_denominator(self):
        # A fled seed should still lower probability vs. just one good seed.
        ctx_good = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx_good, max_turns=4)
        if not paths:
            self.skipTest("No paths found")
        ctx_fled = copy.copy(ctx_good)
        ctx_fled.state = SafariContextState.FLED
        result = _jane_tree([
            (copy.copy(ctx_good), paths),
            (ctx_fled, []),
        ])
        self.assertLess(result.probability, Fraction(1))

    def test_captured_node_is_terminal(self):
        self.assertIsNone(CAPTURED_NODE.branches)
        self.assertEqual(CAPTURED_NODE.probability, Fraction(1))

    def test_futile_node_is_terminal(self):
        self.assertIsNone(FUTILE_NODE.branches)
        self.assertEqual(FUTILE_NODE.probability, Fraction(0))

    def test_non_terminal_node_has_branches(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx, max_turns=4)
        if not paths:
            self.skipTest("No paths found")
        result = _jane_tree([(copy.copy(ctx), paths)])
        if result not in (CAPTURED_NODE, FUTILE_NODE):
            self.assertIsNotNone(result.branches)

    def test_action_is_valid_label(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        paths, _ = machete_all(ctx, max_turns=4)
        if not paths:
            self.skipTest("No paths found")
        result = _jane_tree([(copy.copy(ctx), paths)])
        self.assertIn(result.action, ('BALL', 'MUD', 'BAIT', 'CAPTURED', 'FUTILE'))


# ---------------------------------------------------------------------------
# TestMacheteJane
# ---------------------------------------------------------------------------

class TestMacheteJane(unittest.TestCase):

    def test_empty_candidates_returns_none(self):
        result = machete_jane([])
        self.assertIsNone(result)

    def test_single_candidate_returns_node(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = machete_jane([(ctx, _METANG_SEED)], max_turns=4)
        self.assertIsInstance(result, JaneNode)

    def test_does_not_mutate_input_contexts(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        rng_before = ctx.rng_state
        machete_jane([(ctx, _METANG_SEED)], max_turns=4)
        self.assertEqual(ctx.rng_state, rng_before)

    def test_probability_in_range(self):
        ctx = _make_ctx(_EASY_POKEMON, _METANG_SEED)
        result = machete_jane([(ctx, _METANG_SEED)], max_turns=4)
        if result is not None:
            self.assertGreaterEqual(result.probability, Fraction(0))
            self.assertLessEqual(result.probability, Fraction(1))

    def test_multiple_candidates(self):
        seed_a = _METANG_SEED
        seed_b = _METANG_SEED + 2
        ctx_a = _make_ctx(_EASY_POKEMON, seed_a)
        ctx_b = _make_ctx(_EASY_POKEMON, seed_b)
        result = machete_jane([(ctx_a, seed_a), (ctx_b, seed_b)], max_turns=4)
        self.assertIsInstance(result, JaneNode)


# ---------------------------------------------------------------------------
# TestMacheteConfig
# ---------------------------------------------------------------------------

class TestMacheteConfig(unittest.TestCase):

    def test_default_max_turns(self):
        cfg = MacheteConfig()
        self.assertEqual(cfg.max_turns, 50)

    def test_singleton_is_mutable(self):
        original = machete_config().max_turns
        machete_config().max_turns = 10
        self.assertEqual(machete_config().max_turns, 10)
        machete_config().max_turns = original  # restore


if __name__ == '__main__':
    unittest.main()
