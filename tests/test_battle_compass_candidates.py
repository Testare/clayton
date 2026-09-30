"""The candidate window: where to look for Seed B.

The centring is cross-checked against ``app.metronome.seed_b_center``, which has always done
this correctly. An earlier version of ``centre`` treated the model's output as an absolute frame
rather than a difference to add onto Seed A's delay, which put every window a couple of hundred
frames too early and produced no candidates at all.
"""
import datetime as dt
import tempfile
import unittest

from app.facade import Facade
from app.metronome import seed_b_center
from app.store import FileStore
from claytonlib.battle_compass.candidates import (
    centre, estimate_size, generate, seed_a_delay,
)

KEY_SEED = 0x2D005C61
WHEN = dt.datetime(2026, 1, 1, 12, 0, 0)


def _model():
    facade = Facade(FileStore(tempfile.mkdtemp()))
    profile_id = facade.create_profile({"name": "T"})["id"]
    return facade._resolve_calibration_models(profile_id)["linear"]


class TestVectorMsIsADifference(unittest.TestCase):
    """Vector ms is the gap between Seed A and Seed B, so the battle frame is Seed A's delay
    PLUS the predicted difference -- never the model's output on its own."""

    def setUp(self):
        self.model = _model()

    def test_the_centre_matches_the_metronome_path_exactly(self):
        """The same quantity computed two ways; they must not drift."""
        compared = 0
        for key_seed in (0x2D005C61, 0x1A2B3C4D, 0xEC1504DC, 0x0000FFFF):
            for year in (2000, 2024, 2026):
                when = dt.datetime(year, 3, 4, 12, 0, 0)
                for vector in (5000, 60000, 120000, 300000):
                    b_time, b_delay = seed_b_center(key_seed, when, vector, self.model)
                    frame, second = centre(self.model, key_seed, vector, when)
                    self.assertEqual(frame, b_delay,
                                     f"{key_seed:#x} {year} {vector}")
                    self.assertEqual(b_time, when + dt.timedelta(seconds=second),
                                     f"{key_seed:#x} {year} {vector}")
                    compared += 1
        self.assertGreater(compared, 40)

    def test_a_larger_vector_lands_later(self):
        frames = [centre(self.model, KEY_SEED, v, WHEN)[0]
                  for v in (5000, 60000, 120000, 300000)]
        self.assertEqual(frames, sorted(frames))
        self.assertEqual(len(set(frames)), len(frames))

    def test_the_frame_is_offset_from_seed_as_own_delay(self):
        """Not an absolute frame from the model. This is the bug that emptied every window."""
        a_delay = seed_a_delay(KEY_SEED, WHEN)
        frame, _ = centre(self.model, KEY_SEED, 120_000, WHEN)
        self.assertGreater(frame, a_delay)
        # ~2 minutes at ~59.83 frames/sec, within the model's slack.
        self.assertAlmostEqual(frame - a_delay, 120 * 59.8261, delta=400)

    def test_seed_a_delay_inverts_the_seed_low_bits_for_the_target_year(self):
        for year in (2000, 2024, 2026):
            when = dt.datetime(year, 6, 1)
            self.assertEqual(seed_a_delay(KEY_SEED, when),
                             (KEY_SEED & 0xFFFF) - (year - 2000))

    def test_the_second_comes_from_real_elapsed_time(self):
        """Never from the frame counter, which lags across loading screens."""
        _, second = centre(self.model, KEY_SEED, 120_000, WHEN)
        self.assertAlmostEqual(second, 120 + self.model.rtc_offset_seconds, delta=1)


class TestGenerating(unittest.TestCase):
    def setUp(self):
        self.model = _model()

    def test_a_realistic_vector_fills_the_window(self):
        window = generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                          vector_ms=120_000, frame_window=60, second_window=0)
        self.assertEqual(len(window), estimate_size(60, 0))
        self.assertIsNone(window.why_empty())
        self.assertEqual(window.skipped_below_base_delay, 0)

    def test_seeds_are_distinct_and_centre_first(self):
        window = generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                          vector_ms=120_000, frame_window=30, second_window=0)
        self.assertEqual(len(set(window.seeds)), len(window))
        deltas = [abs(c.frame - window.frame_centre) for c in window.candidates]
        self.assertEqual(deltas, sorted(deltas))

    def test_a_vector_in_seconds_rather_than_milliseconds_is_caught(self):
        """The mistake the units invite: 120 means 0.12s, which lands before Seed A."""
        window = generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                          vector_ms=120, frame_window=60, second_window=0)
        self.assertEqual(len(window), 0)
        self.assertIn("MILLISECONDS", window.why_empty())

    def test_the_base_delay_floor_is_the_target_years_delay(self):
        """Comparing against get_times()'s year-2000 delay instead differs by (year - 2000) and
        would reject legitimate frames."""
        window = generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                          vector_ms=120_000, frame_window=10, second_window=0)
        self.assertEqual(window.base_delay, seed_a_delay(KEY_SEED, WHEN))

    def test_a_window_is_year_independent_in_size(self):
        sizes = {len(generate(self.model, key_seed=KEY_SEED,
                              initial_time=dt.datetime(year, 1, 1, 12, 0, 0),
                              vector_ms=120_000, frame_window=20, second_window=0))
                 for year in (2000, 2024, 2026)}
        self.assertEqual(sizes, {estimate_size(20, 0)})

    def test_a_second_window_multiplies_the_set(self):
        one = generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                       vector_ms=120_000, frame_window=10, second_window=0)
        three = generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                         vector_ms=120_000, frame_window=10, second_window=1)
        self.assertEqual(len(three), 3 * len(one))

    def test_negative_windows_are_refused(self):
        for kwargs in ({"frame_window": -1}, {"second_window": -1}):
            with self.assertRaises(ValueError):
                generate(self.model, key_seed=KEY_SEED, initial_time=WHEN,
                         vector_ms=120_000, **kwargs)


if __name__ == "__main__":
    unittest.main()
