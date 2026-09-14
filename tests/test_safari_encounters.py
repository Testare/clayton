"""In-house Safari-Zone encounter resolution (claytonlib.safari_encounters, clayton-ctd.8).

Ground truth: notes/pokefinder_spread.md — a Pokefinder dump for seed 0x0D0E02D0, Safari Mountain,
Morning, Peak block score 56.  The strong test replays all of it.
"""
import re
import unittest
from pathlib import Path

from claytonlib.safari_encounters import (
    resolve_safari_slots, frame_slot, advance_frame_species, find_encounter_frame, safari_areas,
)

SEED = 0x0D0E02D0
MOUNTAIN_MORNING_PEAK56 = [
    ("larvitar", 42), ("lunatone", 46), ("metang", 44), ("raticate", 16), ("lickitung", 16),
    ("rattata", 16), ("raticate", 17), ("lickitung", 17), ("magneton", 17), ("larvitar", 17),
]
_SPREAD = Path(__file__).resolve().parent.parent / "notes" / "pokefinder_spread.md"


class TestResolveSlots(unittest.TestCase):
    def test_mountain_morning_peak56_matches_pokefinder(self):
        self.assertEqual(resolve_safari_slots("Mountain", "morning", {"peak": 56}),
                         MOUNTAIN_MORNING_PEAK56)

    def test_block_input_forms_equivalent(self):
        dict_form = resolve_safari_slots("Mountain", "morning", {"peak": 56})
        list_form = resolve_safari_slots("Mountain", "morning", [0, 0, 0, 56, 0])  # idx3 = peak
        self.assertEqual(dict_form, list_form)

    def test_area_case_insensitive_and_tod_int(self):
        self.assertEqual(resolve_safari_slots("mountain", 0, {"peak": 56}),
                         resolve_safari_slots("Mountain", "morning", {"peak": 56}))

    def test_metang_absent_without_peak(self):
        slots = resolve_safari_slots("Mountain", "morning", {"peak": 0})
        self.assertNotIn("metang", [s for s, _ in slots])

    def test_unknown_area_and_block_type_raise(self):
        with self.assertRaises(ValueError):
            resolve_safari_slots("Atlantis", "morning", {"peak": 56})
        with self.assertRaises(ValueError):
            resolve_safari_slots("Mountain", "morning", {"mountains": 56})

    def test_all_twelve_areas_present(self):
        self.assertEqual(len(safari_areas()), 12)
        self.assertIn("Mountain", safari_areas())


class TestFrameScan(unittest.TestCase):
    def test_slot_formula_and_species(self):
        blocks = {"peak": 56}
        # advance 1 -> Metang, 5 -> Larvitar, 81 -> Metang (notes ground truth)
        self.assertEqual(advance_frame_species(SEED, 1, "Mountain", "morning", blocks)[0], "metang")
        self.assertEqual(advance_frame_species(SEED, 5, "Mountain", "morning", blocks)[0], "larvitar")
        self.assertEqual(advance_frame_species(SEED, 81, "Mountain", "morning", blocks)[0], "metang")

    def test_find_nearest_metang(self):
        # nearest Metang from frame 12 is frame 13 (spread row 13 -> slot 2 Metang)
        self.assertEqual(find_encounter_frame(SEED, "Mountain", "morning", {"peak": 56}, "metang",
                                              min_frame=12), (13, 44))

    def test_find_returns_none_when_absent(self):
        self.assertIsNone(find_encounter_frame(SEED, "Mountain", "morning", {"peak": 0}, "metang"))

    def test_full_pokefinder_spread(self):
        """Replay every row of notes/pokefinder_spread.md (slot AND species)."""
        slots = resolve_safari_slots("Mountain", "morning", {"peak": 56})
        names = [s for s, _ in slots]
        rows = 0
        for line in _SPREAD.read_text().splitlines():
            m = re.match(r"^(\d+)\t.*\t(\d+):\s*(.+?)\s*$", line)
            if not m:
                continue
            n, slot, sp = int(m.group(1)), int(m.group(2)), m.group(3).strip().lower()
            self.assertEqual(frame_slot(SEED, n), slot, f"slot mismatch at advance {n}")
            self.assertEqual(names[slot], sp, f"species mismatch at advance {n}")
            rows += 1
        self.assertGreater(rows, 100)


if __name__ == "__main__":
    unittest.main()
