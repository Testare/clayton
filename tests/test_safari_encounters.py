"""In-house Safari-Zone encounter resolution (claytonlib.safari_encounters, clayton-ctd.8).

Ground truth: notes/pokefinder_spread.md — a Pokefinder dump for seed 0x0D0E02D0, Safari Mountain,
Morning, Peak block score 56.  The strong test replays all of it.
"""
import re
import unittest
from pathlib import Path

from claytonlib.safari import advance_rng
from claytonlib.safari_encounters import (
    METHODS, ROD_METHODS, WATER_METHODS, resolve_safari_slots, frame_slot,
    advance_frame_species, find_encounter_frame, iter_encounter_frames, safari_areas,
    safari_methods, has_water, hook_rate, rod_hooks, locations_for_species,
    methods_for_species, normalize_method, time_of_day, areas_for_species,
    block_requirement_for,
)

SEED = 0x0D0E02D0
MOUNTAIN_MORNING_PEAK56 = [
    ("larvitar", 42), ("lunatone", 46), ("metang", 44), ("raticate", 16), ("lickitung", 16),
    ("rattata", 16), ("raticate", 17), ("lickitung", 17), ("magneton", 17), ("larvitar", 17),
]
_SPREAD = Path(__file__).resolve().parent.parent / "notes" / "pokefinder_spread.md"


class TestTimeOfDay(unittest.TestCase):
    """clayton-b42.7.1's boundaries: morning 4:00-9:59, day 10:00-19:59, night 20:00-3:59."""

    def test_boundary_hours(self):
        cases = {0: "night", 3: "night", 4: "morning", 9: "morning",
                 10: "day", 19: "day", 20: "night", 23: "night"}
        for hour, expected in cases.items():
            self.assertEqual(time_of_day(hour), expected, f"hour {hour}")

    def test_accepts_a_datetime(self):
        import datetime as dt
        self.assertEqual(time_of_day(dt.datetime(2025, 1, 1, 14, 30)), "day")
        self.assertEqual(time_of_day(dt.datetime(2025, 1, 1, 2, 0)), "night")

    def test_covers_all_24_hours_with_no_gaps(self):
        buckets = {time_of_day(h) for h in range(24)}
        self.assertEqual(buckets, {"morning", "day", "night"})


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


class TestAreasForSpecies(unittest.TestCase):
    """clayton-b42.10.3: filters the Safari-area picker to areas where the chosen species
    can actually appear."""

    def test_metang_is_mountain_only(self):
        self.assertEqual(areas_for_species("metang"), ["Mountain"])

    def test_case_insensitive(self):
        self.assertEqual(areas_for_species("Metang"), areas_for_species("METANG"))

    def test_unknown_species_returns_no_areas(self):
        self.assertEqual(areas_for_species("not-a-real-species"), [])

    def test_a_species_present_unconditionally_somewhere_is_included(self):
        # raticate appears in Mountain's own unconditioned "normal" table (see
        # MOUNTAIN_MORNING_PEAK56 above) -- no block score needed at all.
        self.assertIn("Mountain", areas_for_species("raticate"))


class TestBlockRequirementFor(unittest.TestCase):
    """clayton-b42.10.3: the block score actually needed for a species to appear."""

    def test_metang_needs_peak_56_in_mountain(self):
        self.assertEqual(block_requirement_for("Mountain", "metang"),
                         {"block_type": "peak", "quantity": 56})

    def test_unreachable_species_in_area_returns_none(self):
        self.assertIsNone(block_requirement_for("Plains", "metang"))

    def test_unconditionally_present_species_returns_none(self):
        # raticate needs no block score in Mountain -- it's in the area's own normal table.
        self.assertIsNone(block_requirement_for("Mountain", "raticate"))

    def test_case_insensitive(self):
        self.assertEqual(block_requirement_for("mountain", "Metang"),
                         block_requirement_for("Mountain", "metang"))

    def test_specific_tod_matches_the_all_tods_answer_when_consistent(self):
        # Metang's condition is the same slot/threshold in every time of day.
        for tod in ("morning", "day", "night"):
            self.assertEqual(block_requirement_for("Mountain", "metang", tod=tod),
                             block_requirement_for("Mountain", "metang"))


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


WATER_AREAS = ["Meadow", "Rocky Beach", "Wetland", "Swamp", "Marshland"]


class TestMethods(unittest.TestCase):
    """clayton-858: surf and the three rods, alongside grass."""

    def test_only_five_areas_have_water(self):
        self.assertEqual([a for a in safari_areas() if has_water(a)], WATER_AREAS)

    def test_water_areas_offer_every_method_and_the_rest_only_grass(self):
        for area in safari_areas():
            expected = list(METHODS) if area in WATER_AREAS else ["grass"]
            self.assertEqual(safari_methods(area), expected, area)

    def test_method_aliases(self):
        cases = {"grass": "grass", "Land": "grass", "surf": "surf", "Surfing": "surf",
                 "old rod": "old_rod", "OLD_ROD": "old_rod", "good-rod": "good_rod",
                 "super": "super_rod", "SuperRod": "super_rod"}
        for given, expected in cases.items():
            self.assertEqual(normalize_method(given), expected, given)

    def test_unknown_method_raises(self):
        with self.assertRaises(ValueError):
            normalize_method("headbutt")

    def test_water_method_in_a_waterless_area_raises(self):
        for method in WATER_METHODS:
            with self.assertRaises(ValueError) as ctx:
                resolve_safari_slots("Mountain", "morning", {}, method)
            self.assertIn("no water", str(ctx.exception))

    def test_every_method_resolves_to_ten_slots(self):
        # Grass has 10 block-conditionals, surf 3, each rod 2 -- but the resolved table is
        # always the flat 10 slots the safari branch draws from.
        for area in WATER_AREAS:
            for method in METHODS:
                for tod in ("morning", "day", "night"):
                    slots = resolve_safari_slots(area, tod, {"water": 99}, method)
                    self.assertEqual(len(slots), 10, f"{area}/{method}/{tod}")


class TestWaterSlotResolution(unittest.TestCase):
    def test_rocky_beach_surf_lapras_needs_water_10(self):
        """Rocky Beach's surf conditionals are water 10/14/18, each a Lapras."""
        self.assertEqual(block_requirement_for("Rocky Beach", "lapras", method="surf"), None)
        # Lapras is already in the normal table (slots 8/9) -- so no requirement -- but the
        # conditionals still upgrade the top slots to the high-level ones.
        without = resolve_safari_slots("Rocky Beach", "day", {"water": 9}, "surf")
        with_one = resolve_safari_slots("Rocky Beach", "day", {"water": 10}, "surf")
        self.assertEqual(without[0], ("magikarp", 15))
        self.assertEqual(with_one[0], ("lapras", 37))
        self.assertEqual(with_one[1:], without[1:])

    def test_swamp_super_rod_dragonair_needs_water_15(self):
        req = block_requirement_for("Swamp", "dragonair", method="super_rod")
        self.assertEqual(req, {"block_type": "water", "quantity": 15})
        self.assertNotIn("dragonair",
                         [sp for sp, _ in resolve_safari_slots("Swamp", "day", {"water": 14},
                                                               "super_rod")])
        self.assertEqual(resolve_safari_slots("Swamp", "day", {"water": 15}, "super_rod")[0],
                         ("dragonair", 42))

    def test_a_rods_two_conditionals_fill_only_the_top_two_slots(self):
        slots = resolve_safari_slots("Swamp", "day", {"water": 99}, "super_rod")
        self.assertEqual(slots[:2], [("dragonair", 42), ("dragonair", 45)])
        # Slot 2 onwards is the untouched normal table (Swamp super rod morning/day/night are
        # the same), so only two slots can ever be replaced.
        self.assertEqual(slots[2], ("goldeen", 36))

    def test_locations_and_methods_for_species(self):
        self.assertEqual(locations_for_species("lapras"),
                         [{"area": "Rocky Beach", "method": "surf"}])
        self.assertEqual(locations_for_species("dratini"),
                         [{"area": "Swamp", "method": "good_rod"},
                          {"area": "Swamp", "method": "super_rod"}])
        self.assertEqual(methods_for_species("Swamp", "dragonair"), ["super_rod"])

    def test_areas_for_species_spans_methods_by_default(self):
        # Magikarp is a water-only species: no grass table anywhere carries it.
        self.assertEqual(areas_for_species("magikarp"), WATER_AREAS)
        self.assertEqual(areas_for_species("magikarp", method="grass"), [])
        self.assertEqual(areas_for_species("lapras", method="surf"), ["Rocky Beach"])


class TestRodNibbleCheck(unittest.TestCase):
    """The nibble check is the encounter's FIRST draw, so a rod's slot sits one advance
    further on than grass/surf's (PokeFinder WildGenerator4::generateMethodK)."""

    def test_base_rates(self):
        self.assertEqual([hook_rate(m) for m in ROD_METHODS], [25, 50, 75])

    def test_happiness_and_suction_cups(self):
        self.assertEqual(hook_rate("good_rod", 20), 70)
        self.assertEqual(hook_rate("good_rod", 0, True), 100)
        self.assertEqual(hook_rate("good_rod", 20, True), 140)   # may exceed 100: always bites

    def test_non_rod_has_no_nibble_check(self):
        for method in ("grass", "surf"):
            with self.assertRaises(ValueError):
                hook_rate(method)

    def test_slot_draw_offset_by_method(self):
        for method in ("grass", "surf"):
            self.assertEqual(frame_slot(SEED, 7, method), frame_slot(SEED, 7, "grass"))
        for method in ROD_METHODS:
            # One further on: a rod's slot at frame N is grass's slot at frame N+1.
            self.assertEqual(frame_slot(SEED, 7, method), frame_slot(SEED, 8, "grass"))

    def test_rod_hooks_matches_the_first_draw(self):
        for frame in range(20):
            state = SEED
            for _ in range(frame + 1):
                state = advance_rng(state)
            roll = (state >> 16) % 100
            for method in ROD_METHODS:
                self.assertEqual(rod_hooks(SEED, frame, method), roll < hook_rate(method),
                                 f"{method} frame {frame}")

    def test_no_hook_means_no_encounter(self):
        frames = [f for f in range(60) if not rod_hooks(SEED, f, "old_rod")]
        self.assertTrue(frames, "expected at least one failed old-rod cast in 60 frames")
        for frame in frames:
            self.assertIsNone(advance_frame_species(SEED, frame, "Swamp", "day", {"water": 99},
                                                    "old_rod"))

    def test_candidate_frames_exclude_failed_casts(self):
        args = (SEED, "Swamp", "day", {"water": 99}, "goldeen")
        candidates = list(iter_encounter_frames(*args, 0, 200, method="old_rod"))
        self.assertTrue(candidates)
        for frame, _level in candidates:
            self.assertTrue(rod_hooks(SEED, frame, "old_rod"), f"frame {frame} doesn't hook")
            self.assertEqual(advance_frame_species(SEED, frame, "Swamp", "day", {"water": 99},
                                                   "old_rod")[0], "goldeen")

    def test_a_higher_hook_rate_only_adds_candidates(self):
        args = (SEED, "Swamp", "day", {"water": 99}, "goldeen")
        lean = {f for f, _ in iter_encounter_frames(*args, 0, 300, method="old_rod")}
        rich = {f for f, _ in iter_encounter_frames(*args, 0, 300, method="old_rod",
                                                    happiness_bonus=50)}
        self.assertTrue(lean < rich, "a +50 happiness bonus should strictly widen the set")

    def test_iter_agrees_with_per_frame_lookup_for_every_method(self):
        for area in ("Swamp", "Marshland"):
            for method in METHODS:
                blocks = {"water": 99, "peak": 99, "plains": 99, "forest": 99}
                slots = resolve_safari_slots(area, "day", blocks, method)
                target = slots[0][0]
                found = {f for f, _ in iter_encounter_frames(SEED, area, "day", blocks, target,
                                                             0, 120, method=method)}
                brute = {f for f in range(121)
                         if (advance_frame_species(SEED, f, area, "day", blocks, method) or
                             (None,))[0] == target}
                self.assertEqual(found, brute, f"{area}/{method}")


if __name__ == "__main__":
    unittest.main()
