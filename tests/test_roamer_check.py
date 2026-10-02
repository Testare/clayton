"""Does one bit of one roll predict a roamer encounter?

`getRandomActiveRoamerInCurrMap` gates a roamer encounter solely on `LCRandRange(2)`, so the
decompilation says the answer is yes and the rate is 50%. A believed figure from play experience
is 1-in-4, which would make the predicate wrong. These tests pin the prediction and the recorder
logic so that a real capture can settle it; they cannot settle it themselves.
"""
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest

from claytonlib.roamer_check import (
    CheckEvent, Verdict, load, predict_from_roll, predict_from_state, roamer_frames, verify,
)
from claytonlib.safari import advance_rng
from claytonlib.safari_encounters import frame_slot

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _reader():
    """The gdb script, loaded in its no-GDB mode.

    Same shim as tests/test_gdb_battle_reader.py, for the same reason and with the same
    subtlety: the script decides whether it is inside GDB by whether ``import gdb`` succeeds,
    and under test discovery that is not reliable. Sibling test modules put ``utils/`` on
    ``sys.path``, and ``utils/gdb.py`` is itself a GDB-sourced script whose own top-level
    ``import gdb`` then resolves to itself -- so the import raises AttributeError from a
    circular import rather than ImportError, which the script does not catch. Binding the name
    to None in ``sys.modules`` forces the ImportError the script is written against.
    """
    sentinel = object()
    previous = sys.modules.get("gdb", sentinel)
    sys.modules["gdb"] = None
    try:
        spec = importlib.util.spec_from_file_location(
            "gdb_overworld_reader", ROOT / "utils" / "gdb-overworld-reader.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if previous is sentinel:
            del sys.modules["gdb"]
        else:
            sys.modules["gdb"] = previous
    return mod


class TestThePrediction(unittest.TestCase):
    def test_odd_rolls_mean_roamer(self):
        """`LCRandRange(2) == 0` returns FALSE (no roamer), so the roamer wins on odd."""
        self.assertTrue(predict_from_roll(1))
        self.assertFalse(predict_from_roll(0))
        self.assertTrue(predict_from_roll(65535))
        self.assertFalse(predict_from_roll(65534))

    def test_it_reads_the_roll_one_advance_past_the_frame(self):
        """The flip is the FIRST roll of a Sweet Scent check -- that path has no encounter-rate
        roll -- so it sits exactly where the encounter slot would otherwise be drawn."""
        seed = 0x0C0E02CA
        for frame in range(40):
            state = seed
            for _ in range(frame + 1):
                state = advance_rng(state)
            self.assertEqual(predict_from_state(seed, frame), (state >> 16) % 2 == 1)

    def test_it_is_the_same_roll_frame_slot_already_reads(self):
        """So the existing machinery covers this; only the modulus differs. If these two ever
        disagree, one of them has drifted off the encounter path."""
        seed = 0x0C0E02CA
        for frame in range(60):
            state = seed
            for _ in range(frame + 1):
                state = advance_rng(state)
            roll = state >> 16
            self.assertEqual(frame_slot(seed, frame), roll % 10)
            self.assertEqual(predict_from_state(seed, frame), roll % 2 == 1)

    def test_a_negative_frame_is_refused(self):
        with self.assertRaises(ValueError):
            predict_from_state(1, -1)

    def test_roamer_frames_agrees_with_the_per_frame_predicate(self):
        seed = 0x0C0E02CA
        frames = roamer_frames(seed, 200)
        self.assertEqual(frames, [f for f in range(200) if predict_from_state(seed, f)])

    def test_about_half_of_frames_qualify(self):
        """If the real rate turns out to be 1-in-4 this is the test that should have been
        failing -- it pins the decompilation's 50%, not an observation."""
        for seed in (0x0C0E02CA, 0x2D005C61, 0xEC1504DC):
            frames = roamer_frames(seed, 2000)
            self.assertAlmostEqual(len(frames) / 2000, 0.5, delta=0.04, msg=hex(seed))

    def test_roamer_frames_are_never_far_apart(self):
        """What makes this targetable: the worst gap is small, so a frame guide barely has to
        work. Asserted loosely because it is a property of the stream, not of the code."""
        frames = roamer_frames(0x0C0E02CA, 2000)
        gaps = [b - a for a, b in zip(frames, frames[1:])]
        self.assertLessEqual(max(gaps), 25)


class TestVerdict(unittest.TestCase):
    def test_a_check_that_spent_no_roll_is_not_counted_as_evidence(self):
        """nRoamers == 0 -- no roamer was on the map, so there was nothing to predict. Counting
        it would dilute the rate towards zero."""
        v = verify([{"rolls": [], "roamer": False}])
        self.assertEqual(v.testable, [])
        self.assertIsNone(v.roamer_rate)
        self.assertFalse(v.ok, "no evidence is not the same as agreement")

    def test_agreement(self):
        v = verify([{"rolls": [41], "roamer": True}, {"rolls": [40], "roamer": False}])
        self.assertEqual(v.agreed, 2)
        self.assertEqual(v.disagreed, [])
        self.assertEqual(v.roamer_rate, 0.5)
        self.assertTrue(v.ok)

    def test_a_mismatch_is_reported_with_the_roll_that_caused_it(self):
        v = verify([{"rolls": [40], "roamer": True, "first_roll_index": 7}])
        self.assertEqual(len(v.disagreed), 1)
        self.assertFalse(v.ok)
        self.assertIn("MISMATCH at roll 7", v.summary())
        self.assertIn("even", v.summary())

    def test_the_observed_rate_is_measured_over_flips_not_over_checks(self):
        """The right denominator: a check that found no roamer never flipped."""
        v = verify([{"rolls": [], "roamer": False},
                    {"rolls": [1], "roamer": True},
                    {"rolls": [3], "roamer": True}])
        self.assertEqual(v.roamer_rate, 1.0)

    def test_a_quarter_rate_would_show_up_as_such(self):
        """What a 1-in-4 recording would look like -- the bit can still predict every outcome
        while the RATE disagrees, and those are separate findings."""
        events = [{"rolls": [1], "roamer": True}] + [{"rolls": [0], "roamer": False}] * 3
        v = verify(events)
        self.assertTrue(v.ok, "the bit agreed on every event")
        self.assertEqual(v.roamer_rate, 0.25)
        self.assertIn("25.0%", v.summary())

    def test_a_tiebreak_is_called_out_as_impossible(self):
        """Two rolls means two roamers on one map, which RoamerLocationSetRandom forbids by
        confining the beasts to Johto indices and the Lati twin to Kanto."""
        v = verify([{"rolls": [1, 0], "roamer": True, "first_roll_index": 3}])
        self.assertEqual(len(v.tiebreaks), 1)
        self.assertIn("TIEBREAK", v.summary())

    def test_a_disagreeing_witness_is_a_recorder_problem_not_a_finding(self):
        """initRoamingWildmon runs only on a roamer battle. If it contradicts the return value
        then the hooks are wrong, and no conclusion above it is safe."""
        v = verify([{"rolls": [1], "roamer": True, "confirmed_roamer": False,
                     "first_roll_index": 2}])
        self.assertEqual(len(v.inconsistent_witnesses), 1)
        self.assertFalse(v.ok)
        self.assertIn("RECORDER PROBLEM", v.summary())

    def test_an_agreeing_witness_is_fine(self):
        v = verify([{"rolls": [1], "roamer": True, "confirmed_roamer": True}])
        self.assertEqual(v.inconsistent_witnesses, [])
        self.assertTrue(v.ok)

    def test_an_empty_recording_says_so_rather_than_passing(self):
        v = verify([])
        self.assertFalse(v.ok)
        self.assertIn("No roamer checks recorded", v.summary())

    def test_check_events_can_be_passed_directly(self):
        v = verify([CheckEvent(rolls=(1,), roamer=True)])
        self.assertTrue(v.ok)

    def test_load_reads_the_recorders_own_shape(self):
        doc = {"label": "t", "roamer_checks": [{"rolls": [1], "roamer": True,
                                                "confirmed_roamer": True,
                                                "first_roll_index": 0}]}
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
            fh.write(json.dumps(doc) + "\n")
            path = fh.name
        verdicts = load(path)
        self.assertEqual(len(verdicts), 1)
        self.assertTrue(verdicts[0].ok)


class TestTheRecorder(unittest.TestCase):
    """The gdb script's bracketing, exercised without an emulator."""

    def setUp(self):
        self.mod = _reader()

    def test_it_imports_outside_gdb(self):
        self.assertFalse(self.mod._IN_GDB)

    def test_its_rng_matches_the_librarys(self):
        """The script carries its own copy, as the other gdb readers do, so this is the check
        that the copy has not drifted."""
        state = 0x0C0E02CA
        for _ in range(500):
            self.assertEqual(self.mod.advance(state), advance_rng(state))
            state = advance_rng(state)

    def test_roll_of_matches_what_lcrandom_returns(self):
        self.assertEqual(self.mod.roll_of(0x0C0E02CA), advance_rng(0x0C0E02CA) >> 16)

    def test_its_prediction_matches_the_librarys(self):
        for roll in (0, 1, 2, 3, 40, 41, 65534, 65535):
            self.assertEqual(self.mod.predicted_roamer(roll), predict_from_roll(roll))

    def test_bracketing_captures_exactly_the_rolls_spent_inside_the_check(self):
        """The core of the design. Rolls before and after the check must not be attributed to
        it -- which is the whole reason this brackets instead of symbolising callers."""
        rec = self.mod.Recording("t", start_state=0x1234)
        rec.add_roll(100)                 # unrelated overworld noise
        rec.open_check()
        rec.add_roll(41)                  # the flip
        entry = rec.close_check(True)
        rec.add_roll(200)                 # the encounter that followed
        self.assertEqual(entry["rolls"], [41])
        self.assertEqual(entry["first_roll_index"], 1)
        self.assertEqual(rec.rolls, [100, 41, 200])

    def test_a_check_that_spends_nothing_records_an_empty_roll_list(self):
        rec = self.mod.Recording("t")
        rec.open_check()
        entry = rec.close_check(False)
        self.assertEqual(entry["rolls"], [])
        self.assertIsNone(entry["first_roll_index"])

    def test_a_tiebreak_is_captured_as_two_rolls(self):
        rec = self.mod.Recording("t")
        rec.open_check()
        rec.add_roll(1)
        rec.add_roll(0)
        self.assertEqual(rec.close_check(True)["rolls"], [1, 0])

    def test_closing_without_opening_is_ignored_rather_than_crashing(self):
        """A return hook can fire for a call whose entry was missed when recording starts
        mid-function; inventing a check from it would be worse than dropping it."""
        rec = self.mod.Recording("t")
        self.assertIsNone(rec.close_check(True))
        self.assertEqual(rec.checks, [])

    def test_the_witness_back_fills_the_most_recent_check(self):
        """initRoamingWildmon runs in the CALLER's roamer branch, after the check returns."""
        rec = self.mod.Recording("t")
        rec.open_check()
        rec.add_roll(41)
        rec.close_check(True)
        rec.note_roaming_init()
        self.assertTrue(rec.checks[-1]["confirmed_roamer"])

    def test_the_verdict_can_be_built_from_the_recorders_output(self):
        """End to end on the shape the script actually writes, so the two cannot drift."""
        rec = self.mod.Recording("t", start_state=0x0C0E02CA)
        rec.open_check(); rec.add_roll(41); rec.close_check(True); rec.note_roaming_init()
        rec.open_check(); rec.add_roll(40); rec.close_check(False)
        v = verify(rec.to_doc()["roamer_checks"])
        self.assertEqual(v.agreed, 2)
        self.assertTrue(v.ok)

    def test_the_doc_records_whether_the_seed_was_forced(self):
        forced = self.mod.Recording("t", forced_seed=0x0C0E02CA, start_state=0x0C0E02CA)
        self.assertEqual(forced.to_doc()["forced_seed"], "0x0c0e02ca")
        plain = self.mod.Recording("t", start_state=0x0C0E02CA)
        self.assertIsNone(plain.to_doc()["forced_seed"])
        self.assertEqual(plain.to_doc()["start_state"], "0x0c0e02ca")

    def test_the_roll_cap_stops_rather_than_growing_without_bound(self):
        rec = self.mod.Recording("t")
        for _ in range(self.mod.MAX_ROLLS + 10):
            rec.add_roll(1)
        self.assertEqual(len(rec.rolls), self.mod.MAX_ROLLS)
        self.assertTrue(rec.stopped)

    def test_output_path_sanitises_a_label(self):
        self.assertTrue(self.mod.output_path("a b/c").endswith("a_b_c.jsonl"))


class TestTheSymbolsItBreaksOn(unittest.TestCase):
    """Every symbol named in the docstring, checked against the ELF -- because gdb's default for
    an unknown symbol is a PENDING breakpoint that silently never fires, and this project has
    already lost a session to exactly that (notes/battle_compass.md sec 16.2)."""

    ELF = ROOT / "utils" / "main.elf"
    WANTED = ("LCRandom", "getRandomActiveRoamerInCurrMap", "initRoamingWildmon",
              "FieldSystem_PerformSweetScentEncounterCheck", "sLCRNG_State")

    def test_all_of_them_are_present(self):
        if not self.ELF.exists():
            self.skipTest("utils/main.elf not present")
        import struct
        b = self.ELF.read_bytes()
        (e_shoff,) = struct.unpack_from("<I", b, 0x20)
        e_shentsize, e_shnum = struct.unpack_from("<HH", b, 0x2E)
        secs = [struct.unpack_from("<10I", b, e_shoff + i * e_shentsize)
                for i in range(e_shnum)]
        names = set()
        for name, typ, flags, addr, off, size, link, info, align, entsize in secs:
            if typ != 2:                                  # SHT_SYMTAB
                continue
            stroff = secs[link][4]
            for i in range(size // (entsize or 16)):
                st_name = struct.unpack_from("<I", b, off + i * entsize)[0]
                end = b.index(b"\0", stroff + st_name)
                names.add(b[stroff + st_name:end].decode("ascii", "replace"))
        missing = [s for s in self.WANTED if s not in names]
        self.assertEqual(missing, [], f"not in utils/main.elf: {missing}")

    def test_the_docstring_lists_them(self):
        doc = (ROOT / "utils" / "gdb-overworld-reader.py").read_text()
        for sym in self.WANTED:
            self.assertIn(sym, doc, f"{sym} is hooked but not documented")
