"""Generalized GetShakeCount, cross-checked against safari.py's emulator-verified Safari path
and against the worked figures in notes/battle_compass.md sec 2.2.
"""
import unittest

from claytonlib.battle.catch import (
    BALL_GREAT, BALL_POKE, BALL_SAFARI, BALL_ULTRA, GUARANTEED_CATCH_VALUE,
    ROLL_CEILING, STATUS_NONE, STATUS_PARALYSIS, STATUS_SLEEP,
    apricorn_catch_rate, capture_chance, capture_windows, captures, catch_value,
    fast_ball_catch_rate, is_guaranteed, rolls_consumed, shake_threshold,
    shakes_for_rolls,
)
from claytonlib.safari import STAGE_MULTIPLIERS, safari_pokemon_by_name

SUICUNE_CATCH_RATE = 3
SUICUNE_MAX_HP = 142


class TestAgreesWithSafari(unittest.TestCase):
    """safari.py is emulator-verified, so it is the reference for the case it covers: a Safari
    Ball (x1.5) against a full-HP target with no status.

    One documented exception. safari.py has no equivalent of the ROM's
    ``if (modifiedCatchRate >= 255) shakeCount = BALL_SHAKE_MAX;`` short-circuit, so above that
    value it keeps evaluating the shake formula and produces thresholds *above* the 16-bit roll
    ceiling -- and therefore capture probabilities greater than 1 (Pidgey reaches 2.29 at a
    boosted bait/mud stage). This module follows the ROM instead. The divergence has never
    mattered because Metang's catch rate is 3 and never approaches 255, but it is real, so the
    comparison below is restricted to the range where safari.py is sound.
    """

    def _staged_rate(self, base_catch_rate, stage):
        import math
        return max(math.floor(STAGE_MULTIPLIERS[stage] * base_catch_rate), 1)

    def test_matches_safari_thresholds_below_the_guarantee(self):
        from claytonlib._resources import basedata_json
        compared = 0
        for name, entry in basedata_json("safari_pokemon.json").items():
            mon = safari_pokemon_by_name(name)
            for stage in range(len(STAGE_MULTIPLIERS)):
                staged = self._staged_rate(entry["catch_rate"], stage)
                a = catch_value(staged, ball_multiplier=BALL_SAFARI, cur_hp=100, max_hp=100)
                if is_guaranteed(a):
                    continue
                self.assertEqual(shake_threshold(a), mon.adjusted_catch_rates_b[stage],
                                 f"{name} stage {stage}")
                compared += 1
        self.assertGreater(compared, 100, "the comparison covered almost nothing")

    def test_matches_safari_capture_chance_for_the_real_target(self):
        mon = safari_pokemon_by_name("metang")
        for stage in range(len(STAGE_MULTIPLIERS)):
            staged = self._staged_rate(mon.base_catch_rate, stage)
            ours = capture_chance(catch_value(staged, ball_multiplier=BALL_SAFARI,
                                              cur_hp=100, max_hp=100))
            self.assertAlmostEqual(ours, mon.capture_chance(stage), places=12, msg=stage)

    def test_we_never_report_a_probability_above_one(self):
        """The property safari.py loses above a=255."""
        for a in range(1, 2000):
            self.assertLessEqual(capture_chance(a), 1.0, a)


class TestSuicuneFigures(unittest.TestCase):
    """The numbers the design doc's feasibility case is built on."""

    def _a(self, cur_hp, status=STATUS_NONE, catch_rate=SUICUNE_CATCH_RATE):
        """An unmatched Fast Ball leaves the catch rate alone and uses a x1 multiplier."""
        return catch_value(catch_rate, ball_multiplier=BALL_POKE,
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
        values = {catch_value(SUICUNE_CATCH_RATE, ball_multiplier=BALL_POKE, cur_hp=1, max_hp=m)
                  for m in (2, 50, 130, 142, 714)}
        self.assertEqual(values, {2})

    def test_a_matched_fast_ball_would_be_far_easier(self):
        """The contrast the tool exists for: Suicune just misses the x4.

        A matched Fast Ball would be a ~5.7x better throw (7.10% vs 1.23%), which is the whole
        reason a base Speed of 85 rather than 100 makes this a hard target."""
        matched = capture_chance(self._a(1, STATUS_PARALYSIS,
                                        catch_rate=fast_ball_catch_rate(3, 115)))
        unmatched = capture_chance(self._a(1, STATUS_PARALYSIS,
                                          catch_rate=fast_ball_catch_rate(3, 85)))
        self.assertAlmostEqual(matched * 100, 7.095, places=3)
        self.assertAlmostEqual(unmatched * 100, 1.234, places=3)
        self.assertGreater(matched, 5 * unmatched)

    def test_the_fast_ball_threshold_is_on_BASE_speed(self):
        self.assertEqual(fast_ball_catch_rate(3, 99), 3)
        self.assertEqual(fast_ball_catch_rate(3, 100), 12)

    def test_the_fast_ball_threshold_is_on_BASE_speed(self):
        self.assertEqual(fast_ball_catch_rate(3, 99), 3)
        self.assertEqual(fast_ball_catch_rate(3, 100), 12)


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


class TestRomArithmeticOrder(unittest.TestCase):
    """The ROM floors twice -- once after dividing by 10, once after the HP fraction -- and
    collapsing that into one division diverges for any ball multiplier that is not a multiple
    of 10.  An earlier version of catch.py did exactly that, and neither the Suicune fixture
    (a x1 ball) nor the Safari cross-check (full HP only) could see it.  These are the cases
    that would have."""

    def _rom(self, rate, ball, cur, max_hp):
        """A literal transcription of BattleSystem_CalculateBallShakes' arithmetic."""
        max_hp_times_3 = max_hp * 3
        lost_hp = max_hp_times_3 - cur * 2
        return max(((rate * ball) // 10 * lost_hp) // max_hp_times_3, 1)

    def test_matches_the_rom_across_balls_rates_and_hp(self):
        for ball in (BALL_POKE, BALL_GREAT, BALL_ULTRA, 30, 35, 40):
            for rate in (1, 3, 7, 25, 45, 90, 190, 255):
                for max_hp in (2, 100, 142, 300, 714):
                    for cur in {1, max_hp // 2 or 1, max_hp}:
                        self.assertEqual(
                            catch_value(rate, ball_multiplier=ball, cur_hp=cur, max_hp=max_hp),
                            self._rom(rate, ball, cur, max_hp),
                            f"ball={ball} rate={rate} hp={cur}/{max_hp}")

    def test_a_single_combined_division_would_have_been_wrong(self):
        """The specific divergence, pinned so the bug cannot come back."""
        combined = ((3 * 142 - 2 * 1) * 3 * BALL_GREAT) // (3 * 142 * 10)
        actual = catch_value(3, ball_multiplier=BALL_GREAT, cur_hp=1, max_hp=142)
        self.assertEqual(actual, 3)
        self.assertEqual(combined, 4, "the naive formulation gives 4")
        self.assertNotEqual(actual, combined)


class TestApricornBalls(unittest.TestCase):
    """Apricorn balls scale the catch RATE (capped at 255) rather than setting a multiplier, so
    high-catch-rate species see diminishing returns a multiplier would not produce."""

    def test_scaling_is_clamped_to_255(self):
        self.assertEqual(apricorn_catch_rate(90, multiplier=4), 255)
        self.assertEqual(apricorn_catch_rate(3, multiplier=4), 12)

    def test_a_negative_result_clamps_to_one(self):
        """Reachable via the Heavy Ball's -20 penalty on a low-catch-rate species."""
        self.assertEqual(apricorn_catch_rate(3, bonus=-20), 1)

    def test_the_cap_makes_an_apricorn_ball_weaker_than_an_equivalent_multiplier(self):
        capped = catch_value(apricorn_catch_rate(90, multiplier=4),
                             ball_multiplier=BALL_POKE, cur_hp=1, max_hp=100)
        uncapped = catch_value(90, ball_multiplier=40, cur_hp=1, max_hp=100)
        self.assertLess(capped, uncapped)


class TestGuaranteedCapture(unittest.TestCase):
    def test_at_or_above_255_the_rom_skips_the_rolls(self):
        self.assertTrue(is_guaranteed(GUARANTEED_CATCH_VALUE))
        self.assertFalse(is_guaranteed(GUARANTEED_CATCH_VALUE - 1))
        self.assertEqual(capture_chance(GUARANTEED_CATCH_VALUE), 1.0)
        self.assertEqual(shake_threshold(GUARANTEED_CATCH_VALUE), ROLL_CEILING)

    def test_capture_chance_is_monotonic_up_to_the_guarantee(self):
        chances = [capture_chance(a) for a in range(1, 260)]
        self.assertEqual(chances, sorted(chances))
