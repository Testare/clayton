"""The pure half of utils/gdb-battle-reader.py.

Everything in that file that does not need a live emulator, and in particular the stat
arithmetic it duplicates from claytonlib.battle.stats -- the duplication is deliberate (GDB's
interpreter may not be able to import the repo) so the point of these tests is that the copy
cannot drift.
"""
import importlib.util
import pathlib
import sys
import unittest

from claytonlib.battle.stats import derive_species_stats, derive_stats as lib_derive_stats
from claytonlib.battle.stats import NATURES as LIB_NATURES

_PATH = pathlib.Path(__file__).resolve().parent.parent / "utils" / "gdb-battle-reader.py"


def _load():
    """The hyphens in the filename make it unimportable by name.

    The script decides whether it is running inside GDB by whether ``import gdb`` succeeds, and
    outside GDB it must fail. It does not reliably: several sibling test modules put ``utils/``
    on ``sys.path``, and ``utils/gdb.py`` is itself a GDB-sourced script -- so under discovery
    ``import gdb`` can pick that up and the recorder would try to install breakpoints. Binding
    the name to None in ``sys.modules`` makes the import raise ImportError, which is the
    outcome the script is written against.
    """
    sentinel = object()
    previous = sys.modules.get("gdb", sentinel)
    sys.modules["gdb"] = None
    try:
        spec = importlib.util.spec_from_file_location("gdb_battle_reader", _PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is sentinel:
            del sys.modules["gdb"]
        else:
            sys.modules["gdb"] = previous
    return module


gbr = _load()
assert not gbr._IN_GDB, "the recorder must load in its no-GDB mode for these tests"

SUICUNE = 245
#: A _read_mon snapshot of a Lv40 Suicune with an uncontrolled spread, as a save state holds.
SNAPSHOT = {
    "battler": 1, "species": SUICUNE, "level": 40, "hp": 138, "maxHp": 138,
    "stats": {"atk": 70, "def": 110, "spa": 85, "spd": 104, "spe": 80},
    "ivs": {"hp": 12, "atk": 20, "def": 8, "spa": 17, "spd": 3, "spe": 25},
    "ability": 46, "personality": 0x12345678, "types": [11, 11],
    "moves": [240, 16, 62, 54], "pp": [5, 35, 20, 30],
}


class TestStatArithmeticMatchesClaytonlib(unittest.TestCase):
    """The copy exists because GDB may not be able to import claytonlib. It stays honest only
    if something checks it, which is this."""

    def test_nature_table_matches_and_is_in_rom_index_order(self):
        self.assertEqual(len(gbr.NATURES), 25)
        for index, (name, effect) in enumerate(gbr.NATURES):
            self.assertIn(name, LIB_NATURES, name)
            self.assertEqual(effect, LIB_NATURES[name], name)
            self.assertEqual(gbr.nature_index(name), index, name)

    def test_bold_is_the_roms_index_five(self):
        """include/constants/pokemon.h: NATURE_BOLD 5."""
        self.assertEqual(gbr.nature_index("Bold"), 5)
        self.assertEqual(gbr.NATURES[5][0], "Bold")

    def test_nature_multipliers_match(self):
        from claytonlib.battle.stats import nature_multiplier as lib_mult
        for name, _ in gbr.NATURES:
            for stat in ("hp", "atk", "def", "spa", "spd", "spe"):
                self.assertAlmostEqual(gbr.nature_multiplier(name, stat),
                                       lib_mult(name, stat), msg=f"{name}/{stat}")

    def test_derived_spreads_match_across_natures_levels_and_ivs(self):
        base = gbr.base_stats_for(SUICUNE)
        checked = 0
        for name, _ in gbr.NATURES:
            for level in (5, 40, 50, 100):
                for ivs in ({"hp": 29, "atk": 15, "def": 31, "spa": 31, "spd": 31, "spe": 28},
                            0, 31, {"hp": 0, "atk": 1, "def": 2, "spa": 3, "spd": 4, "spe": 5}):
                    self.assertEqual(gbr.derive_stats(base, level, name, ivs),
                                     lib_derive_stats(base, level, name, ivs=ivs),
                                     f"{name} Lv{level} {ivs}")
                    checked += 1
        self.assertGreater(checked, 300)

    def test_the_configured_override_is_the_documented_spread(self):
        base = gbr.base_stats_for(SUICUNE)
        spread = gbr.derive_stats(base, 40, gbr.TARGET_OVERRIDE["nature"],
                                  gbr.TARGET_OVERRIDE["ivs"])
        self.assertEqual(spread, {"hp": 141, "atk": 63, "def": 119,
                                  "spa": 89, "spd": 109, "spe": 84})

    def test_it_differs_from_the_perfect_iv_fixture(self):
        """Otherwise the override would be untestable against a real recording."""
        base = gbr.base_stats_for(SUICUNE)
        spread = gbr.derive_stats(base, 40, "Bold", gbr.TARGET_OVERRIDE["ivs"])
        self.assertNotEqual(spread, derive_species_stats("suicune", 40, "Bold"))


class TestBaseStatLookup(unittest.TestCase):
    def test_looks_up_by_national_dex_number(self):
        self.assertEqual(gbr.base_stats_for(SUICUNE),
                         {"hp": 100, "atk": 75, "def": 115, "spa": 90, "spd": 115, "spe": 85})

    def test_an_unknown_species_is_none_rather_than_a_guess(self):
        self.assertIsNone(gbr.base_stats_for(1))

    def test_a_missing_file_is_none_rather_than_an_exception(self):
        """It runs inside GDB; a raising lookup would take the recorder down mid-battle."""
        self.assertIsNone(gbr.base_stats_for(SUICUNE, path="/nonexistent/base_stats.json"))


class TestPersonalityRewrite(unittest.TestCase):
    """Nature lives in the personality value as ``pid % 25``, so setting it means rewriting the
    PID -- the game's own idiom, src/pokemon.c: ``pid += nature - (pid % 25)``."""

    def test_the_result_has_the_requested_nature(self):
        for pid in (0, 1, 24, 25, 0x12345678, 0xFFFFFFFF, 0xFFFFFFF0):
            for index in range(25):
                self.assertEqual(gbr.pid_with_nature(pid, index) % 25, index, f"{pid:#x}/{index}")

    def test_it_accepts_a_nature_name(self):
        self.assertEqual(gbr.pid_with_nature(0x12345678, "Bold") % 25, 5)

    def test_the_result_stays_a_u32(self):
        for pid in (0xFFFFFFFF, 0xFFFFFFF0, 0xFFFFFFE7):
            for index in range(25):
                self.assertLessEqual(gbr.pid_with_nature(pid, index), 0xFFFFFFFF)
                self.assertGreaterEqual(gbr.pid_with_nature(pid, index), 0)

    def test_the_high_bits_move_as_little_as_possible(self):
        """Gender, shininess and ability slot ride on the PID, so a wholesale reroll would
        change more than the nature."""
        pid = 0x12345678
        self.assertLess(abs(gbr.pid_with_nature(pid, "Bold") - pid), 25)

    def test_a_pid_near_the_u32_ceiling_steps_down_instead_of_wrapping(self):
        """Rounding up would carry past 0xFFFFFFFF and land on the wrong nature. The ROM's own
        line has this hole; it never meets it because it clears the top byte first."""
        result = gbr.pid_with_nature(0xFFFFFFFF, 21)
        self.assertEqual(result % 25, 21)
        self.assertLessEqual(result, 0xFFFFFFFF)
        self.assertLess(0xFFFFFFFF - result, 50)


class TestPlanOverride(unittest.TestCase):
    def test_it_records_what_the_save_state_held(self):
        """The whole reason to log `before`: a recording is only comparable to another if you
        can see the spread it replaced."""
        plan = gbr.plan_override(SNAPSHOT)
        self.assertEqual(plan["before"]["ivs"], SNAPSHOT["ivs"])
        self.assertEqual(plan["before"]["stats"]["spe"], 80)
        self.assertEqual(plan["before"]["stats"]["hp"], 138)
        self.assertEqual(plan["before"]["personality"], 0x12345678)
        self.assertEqual(plan["before"]["nature"], gbr.NATURES[0x12345678 % 25][0])

    def test_it_writes_every_stat_and_iv_field(self):
        writes = gbr.plan_override(SNAPSHOT)["writes"]
        for stat_field, iv_field in gbr._BATTLE_MON_FIELDS.values():
            self.assertIn(stat_field, writes)
            self.assertIn(iv_field, writes)
        self.assertIn("personality", writes)
        self.assertIn("hp", writes)

    def test_the_written_stats_reflect_the_new_ivs_and_nature(self):
        """The requirement: stats must not be left describing the old spread."""
        writes = gbr.plan_override(SNAPSHOT)["writes"]
        self.assertEqual(writes["maxHp"], 141)
        self.assertEqual(writes["atk"], 63)
        self.assertEqual(writes["def"], 119)
        self.assertEqual(writes["spAtk"], 89)
        self.assertEqual(writes["spDef"], 109)
        self.assertEqual(writes["speed"], 84)

    def test_the_iv_writes_use_the_roms_field_names(self):
        writes = gbr.plan_override(SNAPSHOT)["writes"]
        self.assertEqual(writes["hpIV"], 29)
        self.assertEqual(writes["speedIV"], 28)
        self.assertEqual(writes["spAtkIV"], 31)

    def test_speed_is_not_confused_with_special_attack(self):
        """BattleMon orders its IV bitfields hp/atk/def/SPEED/spa/spd, so a positional reading
        would swap Speed and SpAtk. The configured 28 is Speed and the 31 is SpAtk."""
        writes = gbr.plan_override(SNAPSHOT)["writes"]
        self.assertEqual(writes["speedIV"], 28)
        self.assertNotEqual(writes["spAtkIV"], 28)

    def test_the_nature_write_is_a_personality(self):
        writes = gbr.plan_override(SNAPSHOT)["writes"]
        self.assertEqual(writes["personality"] % 25, 5)

    def test_a_full_hp_target_stays_full(self):
        plan = gbr.plan_override(SNAPSHOT)
        self.assertEqual(plan["writes"]["hp"], plan["writes"]["maxHp"])

    def test_a_damaged_target_keeps_its_absolute_hp(self):
        """Scaling it would invent a damage figure that never happened."""
        snapshot = dict(SNAPSHOT, hp=50)
        self.assertEqual(gbr.plan_override(snapshot)["writes"]["hp"], 50)

    def test_hp_is_clamped_to_a_smaller_new_maximum(self):
        snapshot = dict(SNAPSHOT, hp=200, maxHp=300)
        plan = gbr.plan_override(snapshot)
        self.assertEqual(plan["writes"]["hp"], plan["writes"]["maxHp"])

    def test_the_wrong_species_is_refused(self):
        """A mistimed breakpoint must not silently rewrite our own Pokemon."""
        plan = gbr.plan_override(dict(SNAPSHOT, species=235))  # Smeargle
        self.assertEqual(plan["writes"], {})
        self.assertIn("not the configured", plan["skipped"])

    def test_a_refusal_still_logs_what_was_there(self):
        plan = gbr.plan_override(dict(SNAPSHOT, species=235))
        self.assertEqual(plan["before"]["ivs"], SNAPSHOT["ivs"])

    def test_the_species_guard_can_be_disabled(self):
        config = dict(gbr.TARGET_OVERRIDE, species=None)
        plan = gbr.plan_override(dict(SNAPSHOT, species=235), config,
                                 base=gbr.base_stats_for(SUICUNE))
        self.assertIsNone(plan["skipped"])

    def test_an_unknown_species_is_refused_rather_than_guessed(self):
        config = dict(gbr.TARGET_OVERRIDE, species=None)
        plan = gbr.plan_override(dict(SNAPSHOT, species=1), config)
        self.assertEqual(plan["writes"], {})
        self.assertIn("no base stats", plan["skipped"])

    def test_the_level_comes_from_the_snapshot_not_the_config(self):
        """A Lv40 Bell Tower Suicune is the fixture, but the script must not assume it."""
        plan = gbr.plan_override(dict(SNAPSHOT, level=50))
        self.assertNotEqual(plan["writes"]["maxHp"], 141)
        self.assertEqual(plan["writes"]["maxHp"],
                         gbr.calc_hp(100, 29, 0, 50))

    def test_editing_the_config_changes_the_result(self):
        """The block is meant to be edited, so that has to actually work."""
        config = dict(gbr.TARGET_OVERRIDE, nature="Timid",
                      ivs={k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")})
        plan = gbr.plan_override(SNAPSHOT, config)
        self.assertEqual(plan["after"]["nature"], "Timid")
        self.assertEqual(plan["writes"]["hpIV"], 31)
        self.assertEqual(plan["writes"]["maxHp"], 142)
        self.assertGreater(plan["writes"]["speed"], 84)


class TestRecordingLogsTheOverride(unittest.TestCase):
    def test_the_override_lands_in_the_record_stream(self):
        rec = gbr.Recording(label="t")
        rec.add_override(gbr.plan_override(SNAPSHOT))
        self.assertEqual(len(rec.records), 1)
        self.assertIn("override", rec.records[0])

    def test_it_survives_serialisation(self):
        import json
        rec = gbr.Recording(label="t")
        rec.add_override(gbr.plan_override(SNAPSHOT))
        doc = json.loads(rec.to_json())
        entry = doc["records"][0]["override"]
        self.assertEqual(entry["before"]["ivs"]["spe"], 25)
        self.assertEqual(entry["after"]["ivs"]["spe"], 28)
        self.assertEqual(entry["after"]["stats"]["atk"], 63)


class TestFormatting(unittest.TestCase):
    def test_spreads_print_in_the_projects_display_order(self):
        self.assertEqual(gbr._fmt_spread(gbr.TARGET_OVERRIDE["ivs"]), "29/15/31/31/31/28")


if __name__ == "__main__":
    unittest.main()
