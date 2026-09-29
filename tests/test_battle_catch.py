"""Generalized GetShakeCount, cross-checked against safari.py's emulator-verified Safari path
and against the worked figures in notes/battle_compass.md sec 2.2.
"""
import unittest

from claytonlib.battle.catch import (
    BALL_FAST_MATCHED, BALL_FAST_UNMATCHED, BALL_POKE, BALL_SAFARI,
    ROLL_CEILING, STATUS_NONE, STATUS_PARALYSIS, STATUS_SLEEP,
    capture_chance, capture_windows, captures, catch_value,
    rolls_consumed, shake_threshold, shakes_for_rolls,
)
from claytonlib.safari import STAGE_MULTIPLIERS, safari_pokemon_by_name

SUICUNE_CATCH_RATE = 3
SUICUNE_MAX_HP = 142


class TestAgreesWithSafari(unittest.TestCase):
    """safari.py is emulator-verified, so it is the reference for the case it covers:
    a Safari Ball (x1.5) against a full-HP target with no status."""

    def test_matches_safari_thresholds_for_every_pokemon_and_stage(self):
        import claytonlib.safari as safari
        import json
        from claytonlib._resources import basedata_json
        for name, entry in basedata_json("safari_pokemon.json").items():
            mon = safari_pokemon_by_name(name)
            for stage in range(len(STAGE_MULTIPLIERS)):
                # safari.py applies the bait/mud stage to the species rate before the ball.
                import math
                staged = math.floor(STAGE_MULTIPLIERS[stage] * entry["catch_rate"])
                ours = shake_threshold(catch_value(
                    max(staged, 1), ball_bonus=BALL_SAFARI,
                    cur_hp=100, max_hp=100, status_bonus=STATUS_NONE,
                ))
                self.assertEqual(ours, mon.adjusted_catch_rates_b[stage],
                                 f"{name} stage {stage}")

    def test_matches_safari_capture_chance(self):
        mon = safari_pokemon_by_name("metang")
        for stage in range(len(STAGE_MULTIPLIERS)):
            import math
            staged = max(math.floor(STAGE_MULTIPLIERS[stage] * mon.base_catch_rate), 1)
            ours = capture_chance(catch_value(
                staged, ball_bonus=BALL_SAFARI, cur_hp=100, max_hp=100,
            ))
            self.assertAlmostEqual(ours, mon.capture_chance(stage), places=12, msg=stage)


class TestSuicuneFigures(unittest.TestCase):
    """The numbers the design doc's feasibility case is built on."""

    def _a(self, cur_hp, status=STATUS_NONE, ball=BALL_FAST_UNMATCHED):
        return catch_value(SUICUNE_CATCH_RATE, ball_bonus=ball,
                           cur_hp=cur_hp, max_hp=SUICUNE_MAX_HP, status_bonus=status)

    def test_full_hp(self):
        self.assertEqual(self._a(142), 1)
        self.assertEqual(shake_threshold(1), 16643)
        self.assertAlmostEqual(capture_chance(1) * 100, 0.416, places=3)

    def test_paralysis_does_nothing_at_full_hp_because_of_flooring(self):
        self.assertEqual(self._a(142, STATUS_PARALYSIS), 1)

    def test_one_hp_paralyzed_is_the_route_the_doc_chooses(self):
        self.assertEqual(self._a(1, STATUS_PARALYSIS), 3)
        self.assertEqual(shake_threshold(3), 21845)
        self.assertAlmostEqual(capture_chance(3) * 100, 1.234, places=3)

    def test_sleep_beats_paralysis_by_one_step(self):
        self.assertEqual(self._a(1, STATUS_SLEEP), 4)
        self.assertAlmostEqual(capture_chance(4) * 100, 1.598, places=3)

    def test_catch_value_is_flat_from_1hp_to_half_hp(self):
        """Why chipping below half buys nothing for this target (sec 2.2)."""
        values = {self._a(hp, STATUS_PARALYSIS) for hp in range(1, 72)}
        self.assertEqual(values, {3})
        self.assertEqual(self._a(72, STATUS_PARALYSIS), 1)

    def test_catch_value_at_1hp_ignores_max_hp(self):
        """So the target's HP IVs never need to be known (sec 14.1)."""
        values = {catch_value(SUICUNE_CATCH_RATE, ball_bonus=BALL_POKE, cur_hp=1, max_hp=m)
                  for m in (2, 50, 130, 142, 714)}
        self.assertEqual(values, {2})

    def test_a_matched_fast_ball_would_be_far_easier(self):
        """The contrast the tool exists for: Suicune just misses the x4.

        A matched Fast Ball would be a ~5.7x better throw (7.10% vs 1.23%), which is the whole
        reason a base Speed of 85 rather than 100 makes this a hard target."""
        matched = capture_chance(self._a(1, STATUS_PARALYSIS, BALL_FAST_MATCHED))
        unmatched = capture_chance(self._a(1, STATUS_PARALYSIS))
        self.assertAlmostEqual(matched * 100, 7.095, places=3)
        self.assertAlmostEqual(unmatched * 100, 1.234, places=3)
        self.assertGreater(matched, 5 * unmatched)


class TestShakeMechanics(unittest.TestCase):
    def test_four_rolls_under_threshold_captures(self):
        self.assertTrue(captures([0, 0, 0, 0], 21845))
        self.assertEqual(shakes_for_rolls([0, 0, 0, 0], 21845), 4)

    def test_stops_at_the_first_failure(self):
        self.assertEqual(shakes_for_rolls([0, 0, 65535, 0], 21845), 2)
        self.assertEqual(shakes_for_rolls([65535, 0, 0, 0], 21845), 0)

    def test_rolls_consumed_is_variable_which_is_why_a_ball_is_a_cheap_filler(self):
        self.assertEqual([rolls_consumed(n) for n in range(5)], [1, 2, 3, 4, 4])

    def test_rolls_consumed_rejects_impossible_shake_counts(self):
        for n in (-1, 5):
            with self.assertRaises(ValueError):
                rolls_consumed(n)

    def test_capture_windows_finds_four_in_a_row(self):
        rolls = [0, 0, 0, 0, 65535, 0, 0, 0, 0, 0]
        self.assertEqual(capture_windows(rolls, 21845), [0, 5, 6])

    def test_capture_windows_on_too_short_a_stream_is_empty(self):
        self.assertEqual(capture_windows([0, 0, 0], 21845), [])

    def test_threshold_saturates_rather_than_exceeding_the_roll_space(self):
        self.assertLessEqual(shake_threshold(255), ROLL_CEILING)
        self.assertLessEqual(capture_chance(255), 1.0)


class TestValidation(unittest.TestCase):
    def test_rejects_impossible_inputs(self):
        for kwargs in ({"cur_hp": 0, "max_hp": 142}, {"cur_hp": 200, "max_hp": 142},
                       {"cur_hp": 1, "max_hp": 0}):
            with self.assertRaises(ValueError, msg=kwargs):
                catch_value(3, **kwargs)
        with self.assertRaises(ValueError):
            catch_value(0)
        with self.assertRaises(ValueError):
            shake_threshold(0)


if __name__ == "__main__":
    unittest.main()
