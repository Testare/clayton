"""StopwatchVector: the candidate centre for an encounter nobody could time.

A roamer encounter is observed, not commanded, so its battle-seed centre comes from a stopwatch
reading rather than from a fitted countdown. These tests pin the two things that make it a
different object from `calibration.CalibrationModel` rather than a configuration of one:

* the mean is **only** the elapsed time times the VBlank rate -- no fitted intercept, because the
  intercept a calibration carries describes a timer workflow this encounter does not have;
* the spread is wide enough to matter, and the suggested second window is **never zero**, which is
  the opposite of a static hunt's default.

(clayton-957.35.14, notes/roamers.md sec 6)
"""
import datetime as dt
import unittest

from claytonlib.battle_compass import candidates
from claytonlib.calibration import CalibrationModel
from claytonlib.stopwatch import (
    DEFAULT_DRIFT_FRACTION, DELAYS_PER_SECOND, StopwatchVector,
)

KEY_SEED = 0x64018903                        # mesprit.jsonl's forced seed
INITIAL = dt.datetime(2026, 10, 27, 12, 0, 0)


class TestTheMeanIsJustElapsedTime(unittest.TestCase):

    def test_frames_in_is_the_vblank_rate_and_nothing_else(self):
        sw = StopwatchVector()
        self.assertAlmostEqual(sw.frames_in(1000), DELAYS_PER_SECOND)
        self.assertAlmostEqual(sw.frames_in(60_000), 60 * DELAYS_PER_SECOND)

    def test_it_is_not_sixty_per_second(self):
        """The project's whole frame-rate migration, in one assertion."""
        self.assertNotEqual(StopwatchVector().frames_in(600_000), 36_000)
        self.assertAlmostEqual(StopwatchVector().frames_in(600_000), 35_895.66, places=1)

    def test_frame_returns_the_difference_on_top_of_base_low16(self):
        """The ``target="dF"`` contract `candidates.centre` relies on."""
        sw = StopwatchVector()
        base = KEY_SEED & 0xFFFF
        self.assertAlmostEqual(sw.frame(60_000, base) - base, sw.frames_in(60_000))

    def test_there_is_no_fitted_intercept(self):
        """Zero elapsed time is zero frames, which is exactly what a calibration cannot say."""
        sw = StopwatchVector()
        self.assertEqual(sw.frame(0, 0), 0)

    def test_it_carries_none_of_a_calibration_models_surface(self):
        """Not a model: asking it for a countdown to run is a bug, so it cannot answer."""
        sw = StopwatchVector()
        self.assertFalse(hasattr(sw, "solve_frame"))
        self.assertFalse(hasattr(sw, "mean"))
        self.assertFalse(hasattr(sw, "with_safari_offset"))

    def test_the_rtc_second_comes_from_real_time(self):
        sw = StopwatchVector()
        self.assertEqual(sw.battle_second_offset(120_000), 120)
        self.assertEqual(sw.battle_second_offset(120_400), 120)
        self.assertEqual(sw.battle_second_offset(120_600), 121)

    def test_the_rtc_offset_shifts_the_second_as_a_calibration_models_does(self):
        sw = StopwatchVector(rtc_offset_seconds=2.0)
        self.assertEqual(sw.battle_second_offset(120_000), 122)
        model = CalibrationModel(target="dF", rtc_offset_seconds=2.0)
        self.assertEqual(sw.battle_second_offset(120_000),
                         model.battle_second_offset(120_000))


class TestTheSpread(unittest.TestCase):

    def test_reaction_dominates_a_short_hunt_and_drift_a_long_one(self):
        sw = StopwatchVector()
        short, long = sw.frame_sigma(30_000), sw.frame_sigma(1_800_000)
        self.assertLess(short, long)
        # Half an hour of 0.1% drift is ~1.8 s, which is ~108 frames all by itself.
        self.assertGreater(long, 100)

    def test_the_load_press_jitter_is_carried_rather_than_guessed(self):
        """It stays in the budget because a roamer run never identifies Seed A."""
        without = StopwatchVector().frame_sigma(60_000)
        with_it = StopwatchVector(load_sigma_frames=40.0).frame_sigma(60_000)
        self.assertGreater(with_it, without)
        # In quadrature, so 40 frames of load jitter does not simply add 40.
        self.assertLess(with_it, without + 40)

    def test_the_second_sigma_excludes_the_load_jitter(self):
        """A load that landed late was still PRESSED when it was pressed."""
        sw = StopwatchVector(load_sigma_frames=200.0)
        self.assertAlmostEqual(sw.second_sigma(60_000),
                               StopwatchVector().second_sigma(60_000))

    def test_drift_scales_with_the_elapsed_time(self):
        sw = StopwatchVector(reaction_std_ms=0.0)
        self.assertAlmostEqual(sw.second_sigma(600_000), 600 * DEFAULT_DRIFT_FRACTION)


class TestTheSuggestedWindows(unittest.TestCase):

    def test_a_second_window_is_never_zero(self):
        """A static hunt defaults it to 0; here that would exclude the true seed silently."""
        for ms in (0, 1_000, 60_000, 600_000, 3_600_000):
            self.assertGreaterEqual(StopwatchVector().suggest_second_window(ms), 1, ms)

    def test_the_frame_window_never_falls_below_a_static_hunts_own_default(self):
        """With the lag measured there is nothing left but the spread, and 60 is the floor."""
        self.assertEqual(StopwatchVector(seed_lag_seconds=4.8).suggest_frame_window(0), 60)

    def test_an_unmeasured_lag_dominates_the_whole_spread_budget(self):
        """~600 frames of allowance against ~75 of spread -- which is why measuring it pays."""
        unmeasured = StopwatchVector(load_sigma_frames=73.3)
        measured = StopwatchVector(load_sigma_frames=73.3, seed_lag_seconds=4.8)
        self.assertGreater(unmeasured.suggest_frame_window(120_000),
                           3 * measured.suggest_frame_window(120_000))
        self.assertEqual(unmeasured.lag_allowance_frames(), 599)
        self.assertEqual(measured.lag_allowance_frames(), 0)

    def test_the_second_window_carries_the_same_allowance(self):
        self.assertGreaterEqual(StopwatchVector().suggest_second_window(120_000), 10)
        self.assertEqual(
            StopwatchVector(seed_lag_seconds=4.8).suggest_second_window(120_000), 1)

    def test_an_unmeasured_window_is_the_size_hunts_are_really_run_at(self):
        """Testare reports static hunts working at +-2000 frames and +-7 seconds, so ~800 x ~11
        is in the right neighbourhood rather than alarming -- and it is the price of not having
        measured the lag, not a property of roamers."""
        sw = StopwatchVector(load_sigma_frames=73.3)
        self.assertLess(sw.suggest_frame_window(120_000), 2_000)
        self.assertLess(sw.suggest_second_window(120_000), 15)

    def test_the_frame_window_grows_with_the_hunt(self):
        sw = StopwatchVector(load_sigma_frames=8.0)
        self.assertLess(sw.suggest_frame_window(30_000), sw.suggest_frame_window(900_000))

    def test_three_sigma_by_default_and_the_caller_may_widen(self):
        sw = StopwatchVector(load_sigma_frames=8.0)
        self.assertLessEqual(sw.suggest_frame_window(600_000, k_sigma=2.0),
                             sw.suggest_frame_window(600_000, k_sigma=4.0))

    def test_negative_elapsed_time_is_refused_rather_than_centred(self):
        with self.assertRaises(ValueError):
            StopwatchVector().suggest_frame_window(-1)
        with self.assertRaises(ValueError):
            StopwatchVector().suggest_second_window(-1)

    def test_it_can_price_the_window_before_generating_it(self):
        sw = StopwatchVector(load_sigma_frames=8.0)
        estimate = sw.estimated_candidates(600_000)
        window = candidates.generate(
            sw, key_seed=KEY_SEED, initial_time=INITIAL, vector_ms=600_000,
            frame_window=sw.suggest_frame_window(600_000),
            second_window=sw.suggest_second_window(600_000))
        self.assertEqual(len(window), estimate)
        # Roughly an order of magnitude more than a static hunt's 121, which is the trade a
        # roamer makes and pays for with unbounded turns.
        self.assertGreater(estimate, 1_000)

    def test_describe_says_the_centre_the_spread_and_the_cost(self):
        line = StopwatchVector(load_sigma_frames=8.0).describe(120_000)
        self.assertIn("120.0 s measured", line)
        self.assertIn("candidates", line)


class TestItDrivesTheRealCandidateGrid(unittest.TestCase):
    """The duck-typing is the point: `candidates` must not know which model it has."""

    def test_the_centre_is_seed_as_own_delay_plus_the_measured_frames(self):
        sw = StopwatchVector()
        window = candidates.generate(sw, key_seed=KEY_SEED, initial_time=INITIAL,
                                     vector_ms=120_000, frame_window=5, second_window=0)
        expected = candidates.seed_a_delay(KEY_SEED, INITIAL) + round(sw.frames_in(120_000))
        self.assertEqual(window.frame_centre, expected)
        self.assertEqual(window.second_centre, 120)

    def test_the_grid_contains_the_seed_the_centre_names(self):
        from claytonlib.times import calculate_seed

        sw = StopwatchVector()
        window = candidates.generate(sw, key_seed=KEY_SEED, initial_time=INITIAL,
                                     vector_ms=120_000, frame_window=3, second_window=1)
        centre_seed = calculate_seed(INITIAL + dt.timedelta(seconds=window.second_centre),
                                     window.frame_centre)
        self.assertIn(centre_seed, window.seeds)

    def test_a_reading_before_seed_a_itself_is_explained_not_silently_empty(self):
        """`why_empty` must answer for a stopwatch exactly as it does for a countdown."""
        sw = StopwatchVector()
        window = candidates.generate(sw, key_seed=0x64010001, initial_time=INITIAL,
                                     vector_ms=0, frame_window=2, second_window=0)
        if not window.candidates:
            self.assertIn("Vector ms", window.why_empty())


class TestTheLoadLag(unittest.TestCase):
    """The one number here that is a BIAS rather than a spread, and must not be guessed."""

    def test_it_shifts_both_axes_together(self):
        """Applying it to one axis and not the other would describe two different encounters."""
        sw = StopwatchVector(seed_lag_seconds=5.0)
        plain = StopwatchVector()
        self.assertAlmostEqual(plain.frame(120_000, 0) - sw.frame(120_000, 0),
                               5.0 * DELAYS_PER_SECOND, places=3)
        self.assertEqual(plain.battle_second_offset(120_000)
                         - sw.battle_second_offset(120_000), 5)

    def test_one_second_of_error_is_sixty_frames(self):
        """Why it is worth a field, a docstring and a bead: it dwarfs the whole spread budget."""
        off_by_one = (StopwatchVector(seed_lag_seconds=4.0).frame(120_000, 0)
                      - StopwatchVector(seed_lag_seconds=5.0).frame(120_000, 0))
        self.assertAlmostEqual(off_by_one, DELAYS_PER_SECOND, places=3)
        self.assertGreater(off_by_one, StopwatchVector().frame_sigma(120_000) / 2)

    def test_a_finished_run_pins_it(self):
        """`implied_seed_lag` returns the value to STORE, not a correction to apply."""
        truth = StopwatchVector(seed_lag_seconds=4.8)
        landed = round(truth.frame(300_000, 0))
        # To within one frame, which is the precision a single run can offer: the frame it
        # landed on is an integer, so the lag it implies is quantised at 1/59.8261 s.
        self.assertAlmostEqual(StopwatchVector().implied_seed_lag(300_000, landed, 0), 4.8,
                               delta=1 / DELAYS_PER_SECOND)

    def test_it_round_trips_from_a_vector_that_already_assumed_one(self):
        """So a second run refines the stored value instead of double-counting it."""
        assumed = StopwatchVector(seed_lag_seconds=3.0)
        truth = StopwatchVector(seed_lag_seconds=4.8)
        landed = round(truth.frame(300_000, 0))
        self.assertAlmostEqual(assumed.implied_seed_lag(300_000, landed, 0), 4.8,
                               delta=1 / DELAYS_PER_SECOND)

    def test_from_calibration_takes_the_spread_and_refuses_the_intercept(self):
        model = CalibrationModel(target="dF", alpha=-289.88, beta=0.0599,
                                 jitter_rms=73.33, rtc_offset_seconds=5.25)
        sw = StopwatchVector.from_calibration(model)
        self.assertAlmostEqual(sw.load_sigma_frames, 73.33)
        # The three things it must NOT inherit, because they describe a commanded countdown.
        self.assertEqual(sw.seed_lag_seconds, 0.0)
        self.assertEqual(sw.rtc_offset_seconds, 0.0)
        self.assertAlmostEqual(sw.delays_per_second, DELAYS_PER_SECOND)

    def test_from_calibration_accepts_a_measured_lag(self):
        model = CalibrationModel(target="dF", jitter_rms=73.33)
        sw = StopwatchVector.from_calibration(model, seed_lag_seconds=4.8)
        self.assertAlmostEqual(sw.seed_lag_seconds, 4.8)
