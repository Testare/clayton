"""Tests for claytonlib.flee_flags — the Safari Compass Seed B candidate-table flee-flag
lookahead (clayton-b42.10.8): per-candidate, since each remaining seed's own future is
fully deterministic once its seed and an action sequence are fixed.

Ground truth for the fixtures below was established by running the real (already-tested)
SafariContext.throw_ball/throw_bait/throw_mud directly and observing the outcome, not by
hand-deriving expected RNG results — see each test's comment for what was actually observed.
"""
import unittest

from claytonlib.safari import SafariContext, SafariPokemon
from claytonlib.flee_flags import FleeFlag, _flee_turn, _make_flag, compute_flee_flags

# A handful of real seeds already used elsewhere in this test suite (tests/test_machete.py).
_SEEDS = [0xCC16BF30, 0xCC16BF38, 0x0D0E02BA]

# flee_rate=255 -> the flee check ALWAYS trips. start_encounter() itself runs one flee
# check before any throw, so by the time the first throw() happens the context is already
# WATCHING_WILL_FLEE -- the very next throw's own flee check finalizes it to FLED. Net
# effect (observed): fled on turn 1 for every action, for every real seed tried, UNLESS
# that turn's ball throw happens to capture first (capture is resolved before the flee
# check inside throw_ball, so a low but nonzero catch_rate can occasionally intervene).
_ALWAYS_FLEES = SafariPokemon(name="fleey", base_catch_rate=1, base_flee_rate=255)

# catch_rate=255 (maxed) -> a ball throw's capture check succeeds first, before any flee
# check ever runs -- so a flee-via-ball flag should almost never appear when combined with
# a maxed catch rate, while bait/mud (which have no capture branch at all) still do.
_ALWAYS_FLEES_AND_CATCHES = SafariPokemon(name="fc", base_catch_rate=255, base_flee_rate=255)

# flee_rate=0 -> the flee check never trips; catch_rate=200 -> ball usually captures fast.
_NEVER_FLEES = SafariPokemon(name="easy", base_catch_rate=200, base_flee_rate=0)


def _ctx(pokemon, seed):
    return SafariContext.start_encounter(seed, pokemon)


class TestFleeTurn(unittest.TestCase):
    def test_guaranteed_flee_pokemon_flees_on_turn_1_via_every_action(self):
        for seed in _SEEDS:
            for method in ("throw_ball", "throw_bait", "throw_mud"):
                self.assertEqual(_flee_turn(_ctx(_ALWAYS_FLEES, seed), method, 3), 1,
                                 f"{method} seed={seed:#x}")

    def test_never_flees_pokemon_never_returns_a_flee_turn(self):
        for seed in _SEEDS:
            self.assertIsNone(_flee_turn(_ctx(_NEVER_FLEES, seed), "throw_bait", 3))
            self.assertIsNone(_flee_turn(_ctx(_NEVER_FLEES, seed), "throw_mud", 3))

    def test_a_capture_returns_none_not_a_flee_turn(self):
        # Observed: seed 0xCC16BF30 with catch_rate=255 captures on the very first ball
        # throw (before the flee check ever gets a chance to run).
        self.assertIsNone(_flee_turn(_ctx(_ALWAYS_FLEES_AND_CATCHES, 0xCC16BF30), "throw_ball", 3))

    def test_does_not_mutate_the_original_context(self):
        ctx = _ctx(_ALWAYS_FLEES, _SEEDS[0])
        original_state = ctx.rng_state
        _flee_turn(ctx, "throw_ball", 3)
        self.assertEqual(ctx.rng_state, original_state)
        self.assertTrue(ctx.is_watching())


class TestMakeFlag(unittest.TestCase):
    def test_ball_turn_1_omits_the_digit(self):
        self.assertEqual(_make_flag("ball", 1).code, "F0")

    def test_ball_turn_3_includes_the_digit(self):
        self.assertEqual(_make_flag("ball", 3).code, "F03")

    def test_bait_and_mud_letters(self):
        self.assertEqual(_make_flag("bait", 2).code, "Fb2")
        self.assertEqual(_make_flag("mud", 2).code, "Fm2")

    def test_any_omits_the_letter(self):
        self.assertEqual(_make_flag("any", 2).code, "F2")

    def test_any_turn_1_is_bare_f(self):
        self.assertEqual(_make_flag("any", 1).code, "F")

    def test_tooltip_mentions_the_action_and_timing(self):
        f = _make_flag("bait", 2)
        self.assertIn("bait", f.tooltip)
        self.assertIn("2 turns", f.tooltip)
        f1 = _make_flag("ball", 1)
        self.assertIn("this turn", f1.tooltip)

    def test_tooltip_uses_the_given_pokemon_name(self):
        f = _make_flag("mud", 2, pokemon_name="Metang")
        self.assertTrue(f.tooltip.startswith("Metang"))


class TestComputeFleeFlags(unittest.TestCase):
    def test_an_already_fled_context_returns_no_flags_instead_of_raising(self):
        # Real bug report: app.safari_compass._apply_path's "pending" candidates can
        # legitimately have ctx.has_fled()==True already (the flee is still AMBIGUOUS from
        # the observed-path's point of view -- filter_fled=False keeps them until the next
        # observation resolves it -- but the context itself has already transitioned).
        # Calling throw_ball/bait/mud on a non-watching context raises "Cannot throw X,
        # pokemon has fled or been captured" -- compute_flee_flags must not do that.
        ctx = _ctx(_ALWAYS_FLEES, _SEEDS[0])
        ctx.throw_ball()  # -> FLED on the very first throw (see _ALWAYS_FLEES' docstring)
        self.assertTrue(ctx.has_fled())
        self.assertEqual(compute_flee_flags(ctx, max_turns=3), [])

    def test_an_already_captured_context_returns_no_flags_instead_of_raising(self):
        ctx = _ctx(_ALWAYS_FLEES_AND_CATCHES, 0xCC16BF30)  # observed: captures on turn 1
        ctx.throw_ball()
        self.assertTrue(ctx.captured())
        self.assertEqual(compute_flee_flags(ctx, max_turns=3), [])

    def test_all_three_actions_flee_collapses_to_one_any_flag(self):
        flags = compute_flee_flags(_ctx(_ALWAYS_FLEES, _SEEDS[0]), max_turns=3)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].action, "any")
        self.assertEqual(flags[0].code, "F")

    def test_never_flees_pokemon_produces_no_flags(self):
        self.assertEqual(compute_flee_flags(_ctx(_NEVER_FLEES, _SEEDS[0]), max_turns=3), [])

    def test_a_capture_excludes_ball_but_not_bait_or_mud(self):
        # Observed: seed 0xCC16BF30 captures via ball, so ball is excluded -- but bait/mud
        # have no capture branch, so both still flee at turn 1. Only 2 of 3 actions qualify,
        # so this does NOT collapse to "any".
        flags = compute_flee_flags(_ctx(_ALWAYS_FLEES_AND_CATCHES, 0xCC16BF30), max_turns=3)
        actions = {f.action for f in flags}
        self.assertEqual(actions, {"bait", "mud"})

    def test_a_seed_where_ball_also_flees_collapses_to_any(self):
        # Observed: seed 0xCC16BF38 flees via ball too (no capture intervenes) -- all three
        # actions qualify here, so it collapses to a single "any" flag.
        flags = compute_flee_flags(_ctx(_ALWAYS_FLEES_AND_CATCHES, 0xCC16BF38), max_turns=3)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].action, "any")

    def test_pokemon_name_is_used_in_the_tooltip_when_given(self):
        flags = compute_flee_flags(_ctx(_ALWAYS_FLEES, _SEEDS[0]), max_turns=3, pokemon_name="Metang")
        self.assertIn("Metang", flags[0].tooltip)

    def test_returns_flee_flag_instances(self):
        flags = compute_flee_flags(_ctx(_ALWAYS_FLEES, _SEEDS[0]))
        self.assertTrue(all(isinstance(f, FleeFlag) for f in flags))


if __name__ == "__main__":
    unittest.main()
