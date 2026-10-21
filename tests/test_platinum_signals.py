"""The two Platinum Seed A signals: coin flips (MT) and chatot pitch (LCRNG).

Both are transcribed from pokeplatinum and cross-checked against PokeFinder, so the tests are
written to be a *second* reading rather than a copy of the implementation:

* MT19937 is asserted against the published reference outputs for the standard seeds, which is
  the only check that proves we seeded it the ROM's way rather than Python's.
* The pitch formula and its bucket boundaries are asserted against independently written
  constants, and against the boundary values themselves — those are the numbers that have to
  agree with PokeFinder or a pitch read off one tool means something else in the other. Pitch is
  **display only**: nothing parses one, because the player is never asked to report one
  (clayton-6xu.5).
* The property that motivates using flips at all — that RTC-second siblings separate immediately,
  where the LCRNG hides them for ~19 turns — is asserted directly.
"""
import unittest

from claytonlib.chatot_pitch import (
    BUCKETS, PITCH_MODULUS, PITCH_SCALE, bucket_of, format_pitch, format_sequence,
    pitch_buckets, pitch_value, pitch_values,
)
from claytonlib.coin_flips import MT19937, clean_flips, flip_sequence, flips_match
from claytonlib.safari import advance_rng
from claytonlib.times import calculate_seed

#: One RTC second inside a minute moves `mdms`, which sits in the seed's top byte.
#: `notes/seed_separation.md`; the same `k * 2**24` the LCRNG hides for a median of ~19 turns.
SECOND = 1 << 24

#: A seed used elsewhere in the project's notes, so a human can compare by hand.
SEED = 0x0C0E02CA


class TestMT19937(unittest.TestCase):
    """Seeded the ROM's way (`init_genrand`, f = 1812433253), not Python's `init_by_array`."""

    #: The canonical first five outputs of MT19937 seeded with 5489 — the reference
    #: implementation's own default seed, and the value `MTRNG_Next` falls back to when it was
    #: never seeded (src/math_util.c:126).
    REFERENCE_5489 = (3499211612, 581869302, 3890346734, 3586334585, 545404204)
    #: And the first output for seed 1, the other widely published vector.
    REFERENCE_1_FIRST = 1791095845

    def test_matches_reference_vectors(self):
        rng = MT19937(5489)
        self.assertEqual(tuple(rng.next() for _ in range(5)), self.REFERENCE_5489)

    def test_matches_reference_vector_for_seed_one(self):
        self.assertEqual(MT19937(1).next(), self.REFERENCE_1_FIRST)

    def test_regenerates_rather_than_returning_raw_state(self):
        """The index starts at N, so the first output is twisted and tempered.

        An index of 0 would hand back the seeded words straight, which looks plausible and is
        wrong for every output.
        """
        self.assertNotEqual(MT19937(12345).next(), 12345)

    def test_outputs_are_32_bit(self):
        rng = MT19937(SEED)
        for _ in range(200):
            self.assertTrue(0 <= rng.next() <= 0xFFFFFFFF)

    def test_crosses_the_regeneration_boundary(self):
        """624 outputs exhaust one block; the 625th must come from a fresh twist, not an index
        error. Cheap to get wrong and invisible until a long flip sequence is asked for."""
        rng = MT19937(SEED)
        values = [rng.next() for _ in range(626)]
        self.assertEqual(len(set(values)), len(values))


class TestFlipSequence(unittest.TestCase):

    def test_odd_is_heads(self):
        """The ROM sets `isHeads = MTRNG_Next() % 2`, and PokeFinder emits T for an even word."""
        rng = MT19937(SEED)
        expected = "".join("H" if rng.next() & 1 else "T" for _ in range(16))
        self.assertEqual(flip_sequence(SEED, 16), expected)

    def test_starts_at_mt_output_one_with_no_offset(self):
        """No REL analogue and nothing consumes MT before the Poketch, so flip 1 is output 1.

        Asserted as "the sequence is a prefix of the raw generator" rather than against a frozen
        string, so the test states the property instead of a snapshot.
        """
        rng = MT19937(SEED)
        first = "H" if rng.next() & 1 else "T"
        self.assertEqual(flip_sequence(SEED, 8)[0], first)

    def test_length_and_alphabet(self):
        flips = flip_sequence(SEED, 20)
        self.assertEqual(len(flips), 20)
        self.assertEqual(set(flips) - {"H", "T"}, set())

    def test_zero_flips_is_empty_not_an_error(self):
        self.assertEqual(flip_sequence(SEED, 0), "")

    def test_negative_count_raises(self):
        with self.assertRaises(ValueError):
            flip_sequence(SEED, -1)

    def test_clean_flips_keeps_only_the_alphabet(self):
        self.assertEqual(clean_flips("h, t  H-T?"), "HTHT")


class TestFlipsMatch(unittest.TestCase):

    def test_a_seed_matches_its_own_prefix(self):
        for n in (1, 5, 12, 20):
            self.assertTrue(flips_match(SEED, flip_sequence(SEED, n)))

    def test_empty_observation_matches_everything(self):
        self.assertTrue(flips_match(SEED, ""))
        self.assertTrue(flips_match(SEED + 1, "   "))

    def test_anchors_at_the_start(self):
        """Unlike Elm calls, the observation is a prefix, not a substring: the app is opened
        fresh. A sequence that occurs later but not at the start must NOT match."""
        flips = flip_sequence(SEED, 20)
        later = flips[3:9]
        if later != flips[:6]:          # vanishingly unlikely, but do not assert on luck
            self.assertFalse(flips_match(SEED, later))

    def test_rtc_second_siblings_separate_immediately(self):
        """The whole reason flips beat Elm calls on the second axis.

        Over a spread of real seeds, a sibling one RTC second away is ruled out by a handful of
        flips — where in the LCRNG the same pair stays invisible for a median of 19 battle turns.
        """
        worst = 0
        for delay in range(600, 700):
            seed = calculate_seed(_a_time(), delay)
            sibling = seed + SECOND
            needed = _flips_to_separate(seed, sibling)
            self.assertIsNotNone(needed, f"sibling of {seed:#010x} never separated in 20 flips")
            worst = max(worst, needed)
        self.assertLessEqual(worst, 12, f"worst sibling needed {worst} flips")

    def test_ten_flips_separate_a_realistic_window(self):
        """~10 bits against a few-hundred-candidate window: at most one survivor expected.

        Asserted as "the true seed survives and almost nothing else does", which is the claim the
        UI makes to the player.
        """
        target = calculate_seed(_a_time(), 650)
        window = [calculate_seed(_a_time(), d) for d in range(620, 681)]
        window += [s + SECOND for s in window] + [s - SECOND for s in window]
        observed = flip_sequence(target, 10)
        survivors = [s for s in set(window) if flips_match(s, observed)]
        self.assertIn(target, survivors)
        self.assertLessEqual(len(survivors), 2, f"{len(survivors)} survivors after 10 flips")


class TestPitchValue(unittest.TestCase):

    def test_formula_is_the_rom_formula(self):
        """``((roll % 8192) * 100) >> 13``, written here from the ROM rather than from the code."""
        for roll in (0, 1, 1234, 4095, 4096, 8191, 8192, 12345, 0xFFFF):
            self.assertEqual(pitch_value(roll), ((roll % 8192) * 100) // 8192)

    def test_range_is_zero_to_ninety_nine(self):
        values = {pitch_value(roll) for roll in range(0, 0x10000, 7)}
        self.assertEqual(min(values), 0)
        self.assertEqual(max(values), PITCH_SCALE - 1)

    def test_modulus_discards_the_top_three_bits(self):
        """8192 is 2**13, so rolls differing only above bit 12 give the same pitch — which is why
        a pitch is 13 bits of information and not 16."""
        self.assertEqual(pitch_value(0x0123), pitch_value(0x0123 + PITCH_MODULUS))
        self.assertEqual(pitch_value(0x0123), pitch_value(0x0123 + 3 * PITCH_MODULUS))


class TestBuckets(unittest.TestCase):

    #: Transcribed from PokeFinder's `getPitch` (Core/Util/Utilities.cpp:72-96): < 20, < 40,
    #: < 60, < 80, else. Written out as (value, label) pairs independently of BUCKET_BOUNDS.
    POKEFINDER_BOUNDARIES = (
        (0, "L"), (19, "L"), (20, "ML"), (39, "ML"), (40, "M"), (59, "M"),
        (60, "MH"), (79, "MH"), (80, "H"), (99, "H"),
    )

    def test_boundaries_match_pokefinder(self):
        for value, label in self.POKEFINDER_BOUNDARIES:
            self.assertEqual(bucket_of(value), label, f"pitch {value}")

    def test_five_equal_bands_cover_the_scale(self):
        counts = {label: 0 for label in BUCKETS}
        for value in range(PITCH_SCALE):
            counts[bucket_of(value)] += 1
        self.assertEqual(set(counts.values()), {20})

    def test_out_of_range_raises(self):
        for bad in (-1, PITCH_SCALE, 1000):
            with self.assertRaises(ValueError):
                bucket_of(bad)

    def test_format_is_bucket_then_number_in_parentheses(self):
        self.assertEqual(format_pitch(41), "M (41)")
        self.assertEqual(format_pitch(0), "L (0)")
        self.assertEqual(format_pitch(99), "H (99)")


class TestPitchSequence(unittest.TestCase):

    def test_advances_before_reading_like_elm_calls(self):
        """`pitch_values(seed, n)[i]` is the pitch on the advance from frame i to i+1.

        Same convention as `calibration_tools.elm_calls`, and getting it wrong by one is the
        classic way a route guide points at the wrong frame.
        """
        state = SEED
        expected = []
        for _ in range(6):
            state = advance_rng(state)
            expected.append(pitch_value(state >> 16))
        self.assertEqual(pitch_values(SEED, 6), tuple(expected))

    def test_first_pitch_is_not_the_seeds_own_roll(self):
        self.assertNotEqual(pitch_values(SEED, 1)[0], pitch_value(SEED >> 16))

    def test_buckets_agree_with_values(self):
        values = pitch_values(SEED, 32)
        self.assertEqual(pitch_buckets(SEED, 32), tuple(bucket_of(v) for v in values))

    def test_format_sequence_renders_one_token_per_pitch(self):
        values = pitch_values(SEED, 10)
        rendered = format_sequence(values)
        self.assertEqual(rendered.count("("), len(values))
        self.assertEqual(rendered, " ".join(format_pitch(v) for v in values))

    def test_negative_count_raises(self):
        with self.assertRaises(ValueError):
            pitch_values(SEED, -1)


def _a_time():
    import datetime as dt
    # A time whose second is mid-minute, so +/- one second stays inside the minute and the
    # sibling really is the `k * 2**24` neighbour the separation argument is about.
    return dt.datetime(2026, 6, 15, 21, 30, 30)


def _flips_to_separate(seed: int, sibling: int, limit: int = 20) -> int | None:
    """How many flips it takes before `sibling` is ruled out by `seed`'s own flips."""
    truth = flip_sequence(seed, limit)
    for n in range(1, limit + 1):
        if not flips_match(sibling, truth[:n]):
            return n
    return None


if __name__ == "__main__":
    unittest.main()
