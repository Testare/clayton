"""The pure half of utils/gdb-platinum-battle-reader.py.

Everything in that file that does not need a live emulator:

* the stat arithmetic it duplicates from claytonlib.battle.stats -- the duplication is deliberate
  (GDB's interpreter may not be able to import the repo) so the point is that the copy cannot
  drift;
* the charmap and the control-code grammar, which are Platinum's and not HG/SS's, and which are
  checked against pokeplatinum's own tables when a clone is present;
* the BattleMon field names, which are the single most mechanical difference from the HG/SS
  reader and the easiest place for an HG/SS spelling to survive a copy-paste;
* the phase vocabulary, which is the reason the file exists.
"""
import importlib.util
import os
import pathlib
import sys
import unittest

from claytonlib.battle.stats import derive_stats as lib_derive_stats
from claytonlib.battle.stats import NATURES as LIB_NATURES

_PATH = pathlib.Path(__file__).resolve().parent.parent / "utils" / "gdb-platinum-battle-reader.py"

#: A clone of pret/pokeplatinum, which is where every symbol and table in the reader came from.
#: It is not part of this repo, so the tests that consult it skip when it is absent.
DECOMP = pathlib.Path(os.environ.get("CLAYTON_POKEPLATINUM",
                                     pathlib.Path.home() / "w" / "pokeplatinum"))


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
        spec = importlib.util.spec_from_file_location("gdb_platinum_battle_reader", _PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if previous is sentinel:
            del sys.modules["gdb"]
        else:
            sys.modules["gdb"] = previous
    return module


pbr = _load()
assert not pbr._IN_GDB, "the recorder must load in its no-GDB mode for these tests"

UXIE = 480
#: A _read_mon snapshot of a Lv50 Uxie with an uncontrolled spread, as a save state holds. Note
#: the keys are the project's (`hp`/`maxHp`, `atk`/`spa`) even though the reader fills them from
#: Platinum's field names -- that translation is the reader's job and is asserted separately.
SNAPSHOT = {
    "battler": 1, "species": UXIE, "level": 50, "hp": 155, "maxHp": 155,
    "stats": {"atk": 88, "def": 141, "spa": 83, "spd": 148, "spe": 103},
    "ivs": {"hp": 5, "atk": 9, "def": 12, "spa": 3, "spd": 30, "spe": 1},
    "ability": 26, "personality": 0x12345678, "types": [14, 14],
    "moves": [129, 281, 248, 133], "pp": [20, 10, 15, 20],
}
#: The override config these tests plan against, pinned HERE rather than read off the reader's
#: live `TARGET_OVERRIDE`. That module global is a KNOB -- it is how you point the recorder at a
#: different encounter, and it gets edited between runs -- so tests that read it went red the
#: moment somebody retargeted the recorder from Uxie to Azelf, which is a working session doing
#: exactly what the knob is for. What these tests are about is the arithmetic and the species
#: guard, neither of which has anything to say about which encounter is currently being hunted.
CONFIG = {
    "battler": 1,
    "species": UXIE,
    "nature": "Serious",
    "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
    "evs": 0,
    "preview_levels": (50,),
}


class TestStatArithmeticMatchesClaytonlib(unittest.TestCase):
    """The copy in the reader and the library must agree, because the reader's copy is what the
    emulator's numbers get compared against."""

    def test_nature_table_matches_and_is_in_rom_index_order(self):
        self.assertEqual(len(pbr.NATURES), 25)
        for index, (name, effect) in enumerate(pbr.NATURES):
            self.assertIn(name, LIB_NATURES, name)
            self.assertEqual(effect, LIB_NATURES[name], name)
            self.assertEqual(pbr.nature_index(name), index, name)

    def test_bold_is_the_roms_index_five(self):
        """include/constants/pokemon.h: NATURE_BOLD 5."""
        self.assertEqual(pbr.nature_index("Bold"), 5)
        self.assertEqual(pbr.NATURES[5][0], "Bold")

    def test_serious_is_the_neutral_nature(self):
        """`CONFIG` leans on nature being 1.0 everywhere, and this is what makes that true.

        It used to assert the same thing about the reader's live `TARGET_OVERRIDE` -- which is a
        knob, so the assertion failed the first time a session pointed the recorder at an Azelf
        with a real rolled nature. Naming the nature directly says what the fixture depends on
        without telling a working session what it may hunt.
        """
        self.assertIsNone(pbr.NATURES[pbr.nature_index("Serious")][1])
        self.assertIsNone(pbr.NATURES[pbr.nature_index(CONFIG["nature"])][1])

    def test_nature_multipliers_match(self):
        from claytonlib.battle.stats import nature_multiplier as lib_mult
        for name, _ in pbr.NATURES:
            for stat in pbr._STAT_KEYS:
                self.assertAlmostEqual(pbr.nature_multiplier(name, stat),
                                       lib_mult(name, stat), msg=f"{name}/{stat}")

    def test_derived_spreads_match_across_natures_levels_and_ivs(self):
        base = pbr.base_stats_for(UXIE)
        for level in (5, 50, 100):
            for nature in ("Serious", "Bold", "Timid", "Sassy"):
                for ivs in (0, 31, {"hp": 31, "atk": 0, "def": 17, "spa": 9, "spd": 31,
                                    "spe": 4}):
                    self.assertEqual(pbr.derive_stats(base, level, nature, ivs),
                                     lib_derive_stats(base, level, nature, ivs),
                                     f"Lv{level} {nature} {ivs}")


class TestCharmap(unittest.TestCase):
    """Platinum's charmap, which is the HG/SS one extended over the Latin block."""

    def test_the_runs_cover_the_whole_english_block_once(self):
        codes = set()
        for base, run in pbr._CHARMAP_RUNS:
            for offset in range(len(run)):
                self.assertNotIn(base + offset, codes, f"{base + offset:#05x} appears twice")
                codes.add(base + offset)
        self.assertEqual(min(codes), 0x121)
        self.assertEqual(max(codes), 0x1EA)

    def test_the_anchors_are_where_the_rom_puts_them(self):
        for code, expected in ((0x121, "0"), (0x12B, "A"), (0x145, "a"), (0x188, "é"),
                               (0x1AB, "!"), (0x1C4, ":"), (0x1DE, " "), (0x1EA, "＿")):
            self.assertEqual(pbr._POKE_CHARMAP[code], expected, f"{code:#05x}")

    def test_the_ligature_codes_decode_to_two_letters(self):
        """CHAR_PK / CHAR_MN are one glyph each and two letters of text, which is how "PkMn"
        comes out of a one-code-per-character table."""
        self.assertEqual(pbr._POKE_CHARMAP[0x1E0], "Pk")
        self.assertEqual(pbr._POKE_CHARMAP[0x1E1], "Mn")
        self.assertEqual(pbr.decode_poke_string([0x1E0, 0x1E1, 0xFFFF]), "PkMn")

    def test_the_kerning_codes_read_as_spaces(self):
        """CHAR_NUM_SPACE and CHAR_SPACE_1px..16px are width, not characters. A transcript wants
        a space rather than a [483]."""
        for code in range(0x1E2, 0x1E8):
            self.assertEqual(pbr._POKE_CHARMAP[code], " ", f"{code:#05x}")

    @unittest.skipUnless((DECOMP / "tools" / "msgenc" / "charmap.txt").exists(),
                         "no pokeplatinum clone")
    def test_every_code_agrees_with_the_decomps_own_table(self):
        """The table the ROM was built from. The reader's copy is generated from it, so this is
        the check that it was not then edited by hand."""
        authoritative = {}
        path = DECOMP / "tools" / "msgenc" / "charmap.txt"
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("//")[0]
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if len(key) == 4 and all(c in "0123456789ABCDEFabcdef" for c in key):
                authoritative[int(key, 16)] = value
        # The deliberate re-renderings: a ligature is two letters, kerning is a space.
        rendered = {0x1E0: "Pk", 0x1E1: "Mn"}
        rendered.update({code: " " for code in range(0x1E2, 0x1E8)})
        for code, char in pbr._POKE_CHARMAP.items():
            self.assertEqual(char, rendered.get(code, authoritative.get(code)),
                             f"{code:#05x}")
        # And nothing in the block was skipped.
        for code in range(0x121, 0x1EB):
            if code in authoritative:
                self.assertIn(code, pbr._POKE_CHARMAP, f"{code:#05x} missing")


class TestStringDecoder(unittest.TestCase):
    """The control-code grammar, from include/constants/charcode.h and src/render_text.c. This is
    where HG/SS and Platinum genuinely differ: the format-arg TYPES are not the same set."""

    def _encode(self, text):
        reverse = {char: code for code, char in pbr._POKE_CHARMAP.items() if len(char) == 1}
        return [reverse[c] for c in text]

    def test_plain_text_round_trips(self):
        self.assertEqual(pbr.decode_poke_string(self._encode("Uxie") + [0xFFFF]), "Uxie")

    def test_eos_ends_the_string(self):
        self.assertEqual(
            pbr.decode_poke_string(self._encode("ab") + [0xFFFF] + self._encode("cd")), "ab")

    def test_a_missing_eos_is_not_an_error(self):
        """`size` already bounds the read, so running out of words is an ordinary end."""
        self.assertEqual(pbr.decode_poke_string(self._encode("ab")), "ab")

    def test_char_cr_is_a_newline(self):
        self.assertEqual(pbr.decode_poke_string([0xE000, 0xFFFF]), "\n")

    def test_clear_and_scroll_break_the_line(self):
        """CHAR_CONTROL_CLEAR / CHAR_CONTROL_SCROLL are the page breaks a long message is split
        on, and reading them as one run of text would join two sentences."""
        self.assertEqual(pbr.decode_poke_string([0x25BC, 0x25BD, 0xFFFF]), "\n\n")

    def test_a_placeholder_marker_consumes_its_following_word(self):
        self.assertEqual(
            pbr.decode_poke_string([0xF0FD, 0x0003] + self._encode("x") + [0xFFFF]), "x")

    def test_a_control_format_arg_is_skipped_with_its_fields(self):
        """0xFF00 is CHAR_CONTROL_SET_COLOR: renderer steering, not text."""
        words = [0xFFFE, 0xFF00, 0x0002, 0x0001, 0x0002] + self._encode("hi") + [0xFFFF]
        self.assertEqual(pbr.decode_poke_string(words), "hi")

    def test_an_unresolved_placeholder_is_reported_not_skipped(self):
        """A message read before StringTemplate_Format would still have its arguments in it. That
        is a bug in when the buffer was read, so it has to be visible in the log."""
        words = [0xFFFE, 0x0104, 0x0001, 0x0000] + self._encode("!") + [0xFFFF]
        self.assertEqual(pbr.decode_poke_string(words), "[VAR:0x0104]!")

    def test_a_platinum_control_type_is_not_treated_as_a_variable(self):
        """0x0201 is CHAR_CONTROL_PAUSE here. HG/SS's table would not recognise it, which is
        exactly the drift this file exists to avoid."""
        self.assertNotIn("VAR", pbr.decode_poke_string([0xFFFE, 0x0201, 0x0001, 0x001E, 0xFFFF]))

    def test_an_unknown_code_keeps_its_number(self):
        self.assertEqual(pbr.decode_poke_string([0x0003, 0xFFFF]), "[3]")

    def test_a_runaway_buffer_is_capped(self):
        """A stale msgBuffer pointer should cost a truncated line, not a hung GDB."""
        text = pbr.decode_poke_string(self._encode("a") * 5000)
        self.assertEqual(len(text), pbr._MAX_MESSAGE_CHARS)


class TestBattleMonFieldNames(unittest.TestCase):
    """Platinum spells BattleMon's fields differently from HG/SS, and an HG/SS spelling would be
    written by GDB without complaint -- `hp` exists in both games and means different things."""

    def test_the_stat_fields_are_platinums(self):
        self.assertEqual({key: field for key, (field, _) in pbr._BATTLE_MON_FIELDS.items()},
                         {"hp": "maxHP", "atk": "attack", "def": "defense",
                          "spa": "spAttack", "spd": "spDefense", "spe": "speed"})

    def test_the_iv_fields_are_platinums(self):
        self.assertEqual({key: field for key, (_, field) in pbr._BATTLE_MON_FIELDS.items()},
                         {"hp": "hpIV", "atk": "attackIV", "def": "defenseIV",
                          "spa": "spAttackIV", "spd": "spDefenseIV", "spe": "speedIV"})

    def test_current_hp_is_curhp(self):
        self.assertEqual(pbr._CUR_HP_FIELD, "curHP")

    def test_no_hgss_spelling_survives_in_the_write_set(self):
        plan = pbr.plan_override(SNAPSHOT)
        for hgss_only in ("atk", "spAtk", "spDef", "maxHp", "hp", "movePPCur"):
            self.assertNotIn(hgss_only, plan["writes"])


class TestPlanOverride(unittest.TestCase):
    def test_it_records_what_the_save_state_held(self):
        before = pbr.plan_override(SNAPSHOT, config=CONFIG)["before"]
        self.assertEqual(before["ivs"], SNAPSHOT["ivs"])
        self.assertEqual(before["stats"]["spe"], SNAPSHOT["stats"]["spe"])
        self.assertEqual(before["stats"]["hp"], SNAPSHOT["maxHp"])
        self.assertEqual(before["nature"],
                         pbr.NATURES[SNAPSHOT["personality"] % 25][0])

    def test_it_writes_every_stat_and_the_personality(self):
        writes = pbr.plan_override(SNAPSHOT, config=CONFIG)["writes"]
        self.assertEqual(set(writes),
                         {"personality", "curHP", "maxHP", "attack", "defense",
                          "spAttack", "spDefense", "speed"})

    def test_the_written_stats_are_the_configured_spread_at_the_snapshots_level(self):
        plan = pbr.plan_override(SNAPSHOT, config=CONFIG)
        expected = pbr.derive_stats(pbr.base_stats_for(UXIE), SNAPSHOT["level"],
                                    CONFIG["nature"], CONFIG["ivs"], CONFIG["evs"])
        self.assertEqual(plan["after"]["stats"], expected)
        self.assertEqual(plan["writes"]["speed"], expected["spe"])
        self.assertEqual(plan["writes"]["maxHP"], expected["hp"])

    def test_the_level_comes_from_the_snapshot_not_the_config(self):
        """The ROM decides the level (StartLegendaryBattle's second argument); the config only
        says how it is previewed."""
        plan = pbr.plan_override(dict(SNAPSHOT, level=5), config=CONFIG)
        self.assertEqual(plan["after"]["stats"],
                         pbr.derive_stats(pbr.base_stats_for(UXIE), 5,
                                          CONFIG["nature"], CONFIG["ivs"]))

    def test_speed_is_not_confused_with_special_attack(self):
        """The IV bitfield puts speed third and spAttack fifth; the display order puts speed
        last. A spread that differs only in those two is the test for it."""
        config = dict(CONFIG,
                      ivs={"hp": 0, "atk": 0, "def": 0, "spa": 31, "spd": 0, "spe": 1})
        word = pbr.pack_iv_word(config["ivs"])
        self.assertEqual((word >> 15) & 0x1F, 1, "speed is not at bit 15")
        self.assertEqual((word >> 20) & 0x1F, 31, "spAttack is not at bit 20")

    def test_a_full_hp_target_stays_full(self):
        plan = pbr.plan_override(SNAPSHOT, config=CONFIG)
        self.assertEqual(plan["writes"]["curHP"], plan["writes"]["maxHP"])

    def test_a_damaged_target_keeps_its_absolute_hp(self):
        plan = pbr.plan_override(dict(SNAPSHOT, hp=40), config=CONFIG)
        self.assertEqual(plan["writes"]["curHP"], 40)

    def test_hp_is_clamped_to_a_smaller_new_maximum(self):
        plan = pbr.plan_override(dict(SNAPSHOT, hp=900, maxHp=1000), config=CONFIG)
        self.assertEqual(plan["writes"]["curHP"], plan["writes"]["maxHP"])

    def test_the_wrong_species_is_refused(self):
        plan = pbr.plan_override(dict(SNAPSHOT, species=482), config=CONFIG)
        self.assertIsNone(plan["after"])
        self.assertEqual(plan["writes"], {})
        self.assertIn("482", plan["skipped"])

    def test_a_refusal_still_logs_what_was_there(self):
        plan = pbr.plan_override(dict(SNAPSHOT, species=482), config=CONFIG)
        self.assertEqual(plan["before"]["ivs"], SNAPSHOT["ivs"])

    def test_an_unknown_species_is_refused_rather_than_guessed(self):
        config = dict(CONFIG, species=9999)
        plan = pbr.plan_override(dict(SNAPSHOT, species=9999), config=config)
        self.assertIsNone(plan["after"])
        self.assertIn("base stats", plan["skipped"])

    def test_the_nature_write_is_a_personality(self):
        plan = pbr.plan_override(SNAPSHOT, config=CONFIG)
        self.assertEqual(plan["writes"]["personality"] % 25, plan["after"]["nature_index"])


class TestPersonalityRewrite(unittest.TestCase):
    def test_the_result_has_the_requested_nature(self):
        for index in range(25):
            self.assertEqual(pbr.pid_with_nature(0x12345678, index) % 25, index)

    def test_it_accepts_a_nature_name(self):
        self.assertEqual(pbr.pid_with_nature(0x12345678, "Serious") % 25,
                         pbr.nature_index("Serious"))

    def test_the_high_bits_move_as_little_as_possible(self):
        self.assertLess(abs(pbr.pid_with_nature(0x12345678, "Serious") - 0x12345678), 50)

    def test_a_pid_near_the_u32_ceiling_steps_down_instead_of_wrapping(self):
        pid = pbr.pid_with_nature(0xFFFFFFFF, 24)
        self.assertLessEqual(pid, 0xFFFFFFFF)
        self.assertEqual(pid % 25, 24)


class TestIvWord(unittest.TestCase):
    def test_the_layout_puts_speed_third(self):
        self.assertEqual(pbr._IV_BITS, {"hp": 0, "atk": 5, "def": 10, "spe": 15,
                                        "spa": 20, "spd": 25})

    def test_every_iv_survives_the_round_trip(self):
        ivs = {"hp": 1, "atk": 2, "def": 3, "spa": 4, "spd": 5, "spe": 6}
        self.assertEqual(pbr.unpack_iv_word(pbr.pack_iv_word(ivs)), ivs)

    def test_the_two_flag_bits_are_preserved(self):
        existing = 0b11 << 30
        self.assertEqual(pbr.pack_iv_word(0, existing) & (0b11 << 30), existing)

    def test_an_out_of_range_iv_is_refused(self):
        with self.assertRaises(ValueError):
            pbr.pack_iv_word({"hp": 32, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0})

    def test_the_word_sits_eight_bytes_past_the_moves_array(self):
        """BattleMon is species + five u16 stats + four u16 moves, then the packed word, so the
        offset from &moves[0] is the four moves (include/battle/battle_mon.h:56)."""
        self.assertEqual(pbr._IV_WORD_OFFSET_FROM_MOVES, 8)


class TestPhaseVocabulary(unittest.TestCase):
    """The enums the phase records carry. All three condition-check tables are file-local enums
    in src/battle/battle_controller_player.c, so there is nothing to import even in C -- they are
    copied here, and their load-bearing entries are what these tests pin."""

    def test_yawn_and_thrash_are_where_platinums_enum_puts_them(self):
        """clayton-6xu.7.1 quotes these as YAWN 24 and THRASH 15. Platinum's own enum
        (src/battle/battle_controller_player.c:1256) numbers them 23 and 14 -- the issue's
        figures are one higher throughout, so they are not Platinum's.

        It does not change the issue's argument, which is about ORDER: THRASH still comes first,
        so sim._END_OF_TURN_RESIDUAL_ANCHOR's anchor is still before YAWN, and YAWN is still
        before the side-condition walk that holds Future Sight. But a recording labels its phases
        with these numbers, so they have to be Platinum's and not HG/SS's."""
        self.assertEqual(pbr.MON_COND_CHECK_NAMES.index("YAWN"), 23)
        self.assertEqual(pbr.MON_COND_CHECK_NAMES.index("THRASH"), 14)
        self.assertLess(pbr.MON_COND_CHECK_NAMES.index("THRASH"),
                        pbr.MON_COND_CHECK_NAMES.index("YAWN"))

    def test_future_sight_is_the_first_side_condition(self):
        self.assertEqual(pbr.SIDE_COND_CHECK_NAMES.index("FUTURE_SIGHT"), 0)

    def test_the_end_of_turn_commands_are_where_the_rom_puts_them(self):
        for name, index in (("CHECK_FIELD_CONDITIONS", 9), ("CHECK_MON_CONDITIONS", 10),
                            ("CHECK_SIDE_CONDITIONS", 11), ("TURN_END", 12)):
            self.assertEqual(pbr.BATTLE_CONTROL_NAMES.index(name), index, name)

    def test_exec_script_is_named_because_a_subscripts_rolls_report_it(self):
        self.assertIn("EXEC_SCRIPT", pbr.BATTLE_CONTROL_NAMES)

    def test_an_out_of_range_index_degrades_to_the_number(self):
        self.assertEqual(pbr._name_of(pbr.SIDE_COND_CHECK_NAMES, 99), "99")

    def test_phase_names_resolves_every_enum_field(self):
        fields = {"command": 21, "commandNext": 10, "fieldConditionCheckState": 13,
                  "monConditionCheckState": 23, "sideConditionCheckState": 0,
                  "scriptNarc": 1, "scriptFile": 18}
        names = pbr.phase_names(fields, tables={"sub_seq": [], "waza_seq": {}})
        self.assertEqual(names["command"], "EXEC_SCRIPT")
        self.assertEqual(names["commandNext"], "CHECK_MON_CONDITIONS")
        self.assertEqual(names["monConditionCheckState"], "YAWN")
        self.assertEqual(names["sideConditionCheckState"], "FUTURE_SIGHT")
        self.assertEqual(names["fieldConditionCheckState"], "END")


class TestScriptNames(unittest.TestCase):
    TABLES = {"sub_seq": ["subscript_start_encounter"] + ["filler"] * 17
                         + ["subscript_fall_asleep"],
              "waza_seq": {281: "Yawn", 248: "Future Sight"}}

    def test_a_subscript_resolves_by_index(self):
        self.assertEqual(pbr.resolve_script(pbr.NARC_SUB_SEQ, 18, self.TABLES),
                         "sub_seq:subscript_fall_asleep")

    def test_a_move_script_resolves_by_move_id(self):
        """waza_seq is indexed by move, not by script number (src/battle/battle_script.c:2130)."""
        self.assertEqual(pbr.resolve_script(pbr.NARC_WAZA_SEQ, 248, self.TABLES),
                         "waza_seq:Future Sight")

    def test_a_missing_name_degrades_to_the_number(self):
        self.assertEqual(pbr.resolve_script(pbr.NARC_SUB_SEQ, 999, self.TABLES),
                         "sub_seq:999")

    def test_an_unexpected_narc_is_named_by_number(self):
        self.assertEqual(pbr.resolve_script(7, 3, self.TABLES), "narc7:3")

    def test_the_narc_ids_are_the_roms(self):
        self.assertEqual((pbr.NARC_WAZA_SEQ, pbr.NARC_SUB_SEQ), (0, 1))

    def test_move_names_load_from_this_repos_own_data(self):
        moves = pbr.load_move_names()
        self.assertEqual(moves[281], "Yawn")
        self.assertEqual(moves[248], "Future Sight")

    def test_a_missing_subseq_order_is_empty_rather_than_an_exception(self):
        self.assertEqual(pbr.load_subseq_order("/nonexistent/sub_seq.order"), [])

    @unittest.skipUnless(
        (DECOMP / "res" / "battle" / "scripts" / "subscripts" / "sub_seq.order").exists(),
        "no pokeplatinum clone")
    def test_the_decomps_order_file_puts_the_two_subscripts_where_we_say(self):
        order = pbr.load_subseq_order(
            DECOMP / "res" / "battle" / "scripts" / "subscripts" / "sub_seq.order")
        self.assertEqual(order.index("subscript_fall_asleep"), 18)
        self.assertIn("subscript_future_sight_damage", order)


class TestPhaseSanity(unittest.TestCase):
    """The first rolls of a battle happen before ``battleSys->battleCtx`` points anywhere, so a
    phase read there is noise. data/battle_logs/uxie1.jsonl opens with exactly that:
    ``command=-494088671``, four rolls of BattleContext_InitCounters before the context exists."""

    SANE = {"command": 10, "commandNext": 12, "fieldConditionCheckState": 13,
            "fieldConditionCheckTemp": 0, "monConditionCheckState": 24,
            "monConditionCheckTemp": 0, "sideConditionCheckState": 0,
            "sideConditionCheckTemp": 1, "attacker": 1, "defender": 0,
            "scriptNarc": 1, "scriptFile": 18, "scriptCursor": 155, "moveCur": 281}

    def test_a_real_phase_passes(self):
        self.assertTrue(pbr.phase_is_sane(self.SANE))

    def test_the_uninitialised_read_is_rejected(self):
        """The literal values from uxie1.jsonl's first phase record."""
        self.assertFalse(pbr.phase_is_sane(dict(
            self.SANE, command=-494088671, commandNext=-451145720,
            monConditionCheckState=-369098752, monConditionCheckTemp=-390234112)))

    def test_a_single_out_of_range_field_is_enough(self):
        for name, bad in (("command", len(pbr.BATTLE_CONTROL_NAMES)),
                          ("monConditionCheckState", len(pbr.MON_COND_CHECK_NAMES)),
                          ("sideConditionCheckState", -1),
                          ("attacker", 4), ("scriptCursor", -1)):
            self.assertFalse(pbr.phase_is_sane(dict(self.SANE, **{name: bad})), name)

    def test_a_missing_field_is_rejected(self):
        self.assertFalse(pbr.phase_is_sane({k: v for k, v in self.SANE.items()
                                            if k != "moveCur"}))

    def test_every_phase_field_is_bounded(self):
        """A field with no bound would let garbage through on that field alone."""
        self.assertEqual(set(pbr.PHASE_FIELDS), set(pbr._PHASE_BOUNDS))

    def test_the_end_states_are_inside_the_bounds(self):
        """Each walk parks at its END value between turns, so END must not be rejected."""
        self.assertTrue(pbr.phase_is_sane(dict(
            self.SANE, monConditionCheckState=len(pbr.MON_COND_CHECK_NAMES) - 1,
            sideConditionCheckState=len(pbr.SIDE_COND_CHECK_NAMES) - 1,
            fieldConditionCheckState=len(pbr.FIELD_COND_CHECK_NAMES) - 1)))


class TestEffectScriptNames(unittest.TestCase):
    """be_seq, the narc most of a turn's rolls happen under. The first recording showed every
    move execution as a bare ``narc30:<n>`` because this case was missing."""

    TABLES = {"sub_seq": [], "waza_seq": {248: "Future Sight", 129: "Swift", 86: "Thunder Wave"}}

    def test_it_is_narc_thirty(self):
        """include/constants/narc.h: NARC_INDEX_BATTLE__SKILL__BE_SEQ, counted from
        WAZA_SEQ = 0."""
        self.assertEqual(pbr.NARC_BE_SEQ, 30)

    def test_the_index_is_the_effect_not_the_move(self):
        """battle_script.c:2084 jumps with CURRENT_MOVE_DATA.effect. Future Sight is move 248
        and effect 148, and the log's phase records carry 148."""
        self.assertIn("effect_148", pbr.resolve_script(pbr.NARC_BE_SEQ, 148, self.TABLES))

    def test_the_move_names_the_script(self):
        """Many moves share an effect, so the effect number alone does not say which move was
        executing; moveCur does."""
        self.assertEqual(pbr.resolve_script(pbr.NARC_BE_SEQ, 148, self.TABLES, move=248),
                         "be_seq:effect_148(Future Sight)")

    def test_an_unknown_move_leaves_the_effect_alone(self):
        self.assertEqual(pbr.resolve_script(pbr.NARC_BE_SEQ, 148, self.TABLES, move=9999),
                         "be_seq:effect_148")

    def test_effect_ids_match_this_repos_move_data(self):
        """The effect numbers seen in data/battle_logs/uxie1.jsonl, against moves.json."""
        from claytonlib.moves import _moves_by_number
        moves = _moves_by_number()
        for move, effect in ((86, 67), (103, 59), (248, 148), (129, 17), (269, 175), (206, 101)):
            self.assertEqual(moves[move].effect, effect, moves[move].name)


class TestRecording(unittest.TestCase):
    FIELDS = {name: 0 for name in pbr.PHASE_FIELDS}

    def test_the_game_is_written_into_the_output(self):
        import json
        doc = json.loads(pbr.Recording(label="uxie").to_json())
        self.assertEqual(doc["game"], "platinum")
        self.assertEqual(doc["forced_seed"], None)

    def test_a_forced_seed_is_written_as_hex(self):
        import json
        doc = json.loads(pbr.Recording(forced_seed=0xEC1504DC).to_json())
        self.assertEqual(doc["forced_seed"], "0xec1504dc")

    def test_a_phase_is_recorded_once_until_it_changes(self):
        rec = pbr.Recording()
        self.assertIsNotNone(rec.note_phase(self.FIELDS))
        self.assertIsNone(rec.note_phase(self.FIELDS))
        self.assertIsNotNone(rec.note_phase(dict(self.FIELDS, scriptCursor=1)))

    def test_a_phase_entry_keeps_the_raw_fields_and_the_names_apart(self):
        rec = pbr.Recording()
        entry = rec.note_phase(self.FIELDS, {"command": "GET_BATTLE_MON"})
        self.assertEqual(entry["phase"]["fields"]["command"], 0)
        self.assertEqual(entry["phase"]["names"]["command"], "GET_BATTLE_MON")

    def test_the_phase_cache_is_per_battle(self):
        """FieldBattleDTO_New clears it; otherwise a second battle that opened in the same phase
        would have no phase record at all."""
        rec = pbr.Recording()
        rec.note_phase(self.FIELDS)
        rec.phase_seen = None
        self.assertIsNotNone(rec.note_phase(self.FIELDS))

    def test_hp_is_recorded_only_when_it_changes(self):
        rec = pbr.Recording()
        readings = [{"battler": 0, "hp": 100, "max": 100}]
        self.assertIsNotNone(rec.note_hp(readings))
        self.assertIsNone(rec.note_hp(readings))
        self.assertIsNotNone(rec.note_hp([{"battler": 0, "hp": 99, "max": 100}]))

    def test_the_seed_entry_is_logged_once(self):
        rec = pbr.Recording()
        rec.add_seed({"seedRandNext": "0x1"})
        self.assertTrue(rec.seed_seen)
        self.assertEqual(len(rec.records), 1)

    def test_format_phase_names_the_condition_and_the_script(self):
        fields = dict(self.FIELDS, command=10, monConditionCheckState=23, scriptNarc=1,
                      scriptFile=18, scriptCursor=3)
        line = pbr.format_phase({"fields": fields,
                                 "names": pbr.phase_names(fields, TestScriptNames.TABLES)})
        self.assertIn("CHECK_MON_CONDITIONS", line)
        self.assertIn("mon=YAWN", line)
        self.assertIn("subscript_fall_asleep@3", line)

    def test_the_output_path_is_sanitised_and_defaulted(self):
        self.assertTrue(pbr.output_path("uxie yawn").endswith("uxie_yawn.jsonl"))
        self.assertTrue(pbr.output_path("").endswith("platinum.jsonl"))


class TestBreakpointSymbolsExistInTheDecomp(unittest.TestCase):
    """The HG/SS reader once broke on two symbols that were not in that build; GDB turned them
    into *pending* breakpoints, which print an error and then silently never fire, so the failure
    looked like a warning rather than a missing feature. There is no Platinum .elf in this tree
    to check against, so the decomp source is the next best thing -- and it is where every one of
    these names came from."""

    def setUp(self):
        if not (DECOMP / "src" / "battle").is_dir():
            self.skipTest(f"{DECOMP} is not a pokeplatinum clone "
                          f"(set CLAYTON_POKEPLATINUM)")

    def _decomp_text(self):
        parts = []
        for pattern in ("include/**/*.h", "src/**/*.c"):
            for path in DECOMP.glob(pattern):
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(parts)

    def test_every_symbol_the_script_breaks_on_is_defined_in_the_decomp(self):
        text = self._decomp_text()
        self.assertGreater(len(pbr.BREAKPOINT_SYMBOLS), 4)
        for symbol in pbr.BREAKPOINT_SYMBOLS:
            self.assertIn(symbol, text, f"{symbol} is not in pokeplatinum")

    def test_the_hgss_names_are_not_used_here(self):
        """Pinning the port: these are the HG/SS reader's symbols, and none of them exists in
        Platinum. The docstring's symbol map names them, so this checks the breakpoints."""
        for symbol in ("BattleSystem_Random", "BattleSetup_New",
                       "BattleSystem_GetBattleMon", "BattleSystem_PrintBattleMessage",
                       "ov12_0223C4E8"):
            self.assertNotIn(symbol, pbr.BREAKPOINT_SYMBOLS)

    def test_a_message_hook_symbol_is_among_them(self):
        """Messages are how a recording says which action each turn was, so losing every message
        hook is not a degraded recording, it is an unusable one."""
        self.assertTrue(set(pbr.SYM_MESSAGES) & set(pbr.BREAKPOINT_SYMBOLS))


if __name__ == "__main__":
    unittest.main()
