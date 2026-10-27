#!/usr/bin/env python
"""
gdb-platinum-battle-reader.py — the Platinum port of utils/gdb-battle-reader.py: record ONE
hand-played battle, with the battle seed optionally forced, as ground truth for Battle Compass.

Written for clayton-6xu.7.1, which needs to know where in the four end-of-turn advances Yawn's
sleep-duration roll and Future Sight's hit check land.  That is the one DERIVED advance position
in battle_compass/sim.py and it is load-bearing for Uxie, whose own moveset contains both.  So
this reader does something its HG/SS sibling does not: it logs the ROM's **battle phase** next to
every roll -- the control command, the three end-of-turn condition-check state machines, and the
battle script that asked for the roll.  With that, "which of the four advances is the Yawn roll"
is read off the log rather than argued about.

Everything was read against a clone of `pret/pokeplatinum` (complete decomp); file:line
citations below are that tree.  Nothing here was inferred from the HG/SS build.

Symbol map, HG/SS -> Platinum
-----------------------------
    BattleSetup_New                 -> FieldBattleDTO_New
                                       (include/field_battle_data_transfer.h:93; the battle seed
                                       is BORN here, src/field_battle_data_transfer.c:115)
    BattleSystem_Random             -> BattleSystem_RandNext
                                       (src/battle/battle_system.c:1308)
    BattleSystem_GetBattleMon       -> BattleSystem_InitBattleMon
                                       (src/battle/battle_lib.c:70; same ARM EABI arg order:
                                       r0 battleSys, r1 battleCtx, r2 battler, r3 partySlot)
    BattleSystem_PrintBattleMessage -> BattleMessage_Print
    ov12_0223C4E8                   -> BattleMessage_PrintToWindow
                                       (src/battle/battle_system.c:1652, 1665; both funnel
                                       through the static BattleMessage_Format, which is what
                                       fills battleSys->msgBuffer at battle_system.c:2286)
    battleSystem->ctx               -> battleSys->battleCtx
                                       (include/struct_defs/battle_system.h:55)

`BattleMessage_Print` is worth a note: it is one of the two names the HG/SS reader once broke on
and that tests/test_gdb_battle_reader.py pins as *absent* from that build.  It is absent from
HG/SS and present in Platinum.  Same name, different game — not a mistake coming back.

How the seed is forced, and why differently
-------------------------------------------
The HG/SS reader forces the seed by overwriting r3 at `BattleSystem_Random+8`, just past the
`ldr r3, [r0, r2]` that loads it.  That offset was established by disassembling a build.  There
is no Platinum build in this tree to disassemble, so repeating the trick would mean inventing an
instruction offset — and a hijack that lands on the wrong instruction clobbers a live register
and mislabels the whole recording.

Instead this reader writes `dto->seed` through the DWARF type, at the return of
FieldBattleDTO_New.  That is strictly more faithful than the register hijack:
`BattleSys_New` copies `dto->seed` into BOTH `battleSys->seedRandNext` and `battleSys->seedDTO`
(src/battle/battle_main.c:1034-1035), which is exactly what a real run has, where the register
hijack leaves seedDTO holding the clock-derived value.  Nothing between FieldBattleDTO_New and
BattleSys_New touches `dto->seed` (it is assigned in exactly one other place,
battle_main.c:684, which is the write-BACK at battle end).

The write is then confirmed from the other end: at the first BattleSystem_RandNext of the
battle, before the multiply, `battleSys->seedRandNext` is read and logged.  If a seed was forced
and that read disagrees, recording stops loudly rather than producing a log labelled with a seed
the game never used.  When no seed is forced the same read is still logged, which is how an
un-forced recording says what Seed B actually was.

The cost: forcing needs DWARF types for FieldBattleDTO and BattleSystem.  Without them this
reader will NOT claim to have forced anything.  Load the .elf with symbols.

Usage (inside GDB, AFTER attaching to the emulator):

    (gdb) source utils/gdb-platinum-battle-reader.py
    (gdb) plbattlelog 0xEC1504DC uxie   # force this battle seed and start recording
    (gdb) plbattlelog                   # record without forcing a seed
    ... play the battle ...
    (gdb) plbattleoverride              # show the target IV/nature override (on by default)
    (gdb) plbattlephase verbose         # also print each phase change as you play
    (gdb) plbattlemark turn2            # drop a labelled marker into the log
    (gdb) plbattlestatus                # what has been captured so far
    (gdb) plbattlesave                  # flush to data/battle_logs/<name>.jsonl and stop

The commands are `pl`-prefixed so that sourcing this file cannot silently take over the HG/SS
reader's `battlelog`, or be taken over by it.

Analyse the result with `claytonlib.battle.logcheck`, which is pure Python and tested --
everything in this file needs a live emulator, so as little logic as possible lives here.

On sourcing, every hook reports whether it resolved.  Take the FAIL lines seriously: a missing
message hook leaves a recording that looks complete and has no way to say which action each turn
was, which is the one thing the messages are for.
"""

import json
import os
import time

try:
    import gdb
    _IN_GDB = True
except ImportError:  # pragma: no cover — only when read outside GDB
    gdb = None
    _IN_GDB = False


# ---------------------------------------------------------------------------
# Platinum English charmap.
#
# Built from runs rather than an entry-per-line dict, because the table IS runs: generated from
# pokeplatinum's tools/msgenc/charmap.txt (version 2023.07.28) and spot-checked back against it.
# Every code in these runs agrees with the HG/SS table the sibling reader carries -- the two
# games share the character set -- but this one is complete over the Latin block instead of
# stopping at the ASCII punctuation, so an accented nickname and the 'é' in "Pokémon" decode
# instead of coming out as [392].
#
# Copied rather than imported, following the same convention as the sibling reader: each of
# these files is standalone so a change to one cannot break the other mid-session.
# ---------------------------------------------------------------------------

#: (first code, the characters at that code onwards). Contiguous by construction.
_CHARMAP_RUNS = (
    (0x121, "0123456789"),
    (0x12B, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    (0x145, "abcdefghijklmnopqrstuvwxyz"),
    (0x15F, "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß"),
    (0x17F, "àáâãäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ"),
    (0x19F, "ŒœŞşªº¹²³$¡¿"),
    (0x1AB, "!?,.…·/‘’“”„《》()♂♀+-*#=&~:;"),
    (0x1C6, "♠♣♥♦★◉●■▲◆@♪%☀☁☂☃☺♚♛☹↗↘☽ ⁴₧₦ "),
    (0x1E8, "°_＿"),
)

_POKE_CHARMAP = {}
for _base, _run in _CHARMAP_RUNS:
    for _offset, _char in enumerate(_run):
        _POKE_CHARMAP[_base + _offset] = _char
#: The glyphs that are not one character of text. CHAR_PK/CHAR_MN are the "PkMn" ligature pair;
#: CHAR_NUM_SPACE and CHAR_SPACE_1px..16px are kerning, which reads as a space in a transcript.
_POKE_CHARMAP.update({0x1E0: "Pk", 0x1E1: "Mn", 0x1E2: " "})
for _code in range(0x1E3, 0x1E8):
    _POKE_CHARMAP[_code] = " "
del _base, _run, _offset, _char, _code


# Control codes, from include/constants/charcode.h and the renderer that consumes them
# (src/render_text.c:70-195). Identical values to HG/SS for EOS / newline / format-arg, which is
# why the sibling reader's decoder very nearly works -- but its *format-arg type* table is HG/SS's
# and wrong here, so the grammar below is Platinum's own.
_CHAR_CR = 0xE000                 #: newline
_CHAR_PLACEHOLDER_BEGIN = 0xF0FD  #: followed by one more word, both skipped
_CHAR_COMPRESSED_MARK = 0xF100
_CHAR_CONTROL_CLEAR = 0x25BC      #: page break
_CHAR_CONTROL_SCROLL = 0x25BD
_CHAR_FORMAT_ARG = 0xFFFE         #: 0xFFFE, type, field_count, [fields]
_CHAR_EOS = 0xFFFF

#: Format-arg types that steer the renderer rather than standing in for text. Anything else is a
#: placeholder -- CharCode_IsFormatArg (src/charcode.c:28) accepts type & 0xFF00 in
#: {0x100, 0x500, 0x600} -- and should not appear in a message that has been through
#: StringTemplate_Format, so seeing one in a log means the message was read too early.
_FORMAT_ARG_CONTROLS = {
    0x0200: "screen-indicator", 0x0201: "pause", 0x0202: "callback",
    0x0203: "cursor-x", 0x0204: "cursor-y",
    0xFE06: "move", 0xFF00: "set-color", 0xFF01: "set-size",
}

#: A message is a few dozen characters. The cap is here so a stale msgBuffer pointer costs a
#: truncated line rather than a hung GDB.
_MAX_MESSAGE_CHARS = 1024


def decode_poke_string(words):
    """Decode a sequence of charcodes with the Platinum English charmap.

    Pure, so the grammar is testable without an emulator -- which matters more here than in the
    sibling reader, because this decoder follows Platinum's control codes rather than HG/SS's.
    `words` is any iterable of 16-bit ints; decoding stops at CHAR_EOS or when `words` runs out.
    """
    words = list(words)
    out = []
    index = 0
    while index < len(words) and len(out) < _MAX_MESSAGE_CHARS:
        code = words[index]
        if code == _CHAR_EOS:
            break
        if code == _CHAR_CR:
            out.append("\n")
            index += 1
            continue
        if code in (_CHAR_CONTROL_CLEAR, _CHAR_CONTROL_SCROLL):
            out.append("\n")
            index += 1
            continue
        if code == _CHAR_PLACEHOLDER_BEGIN:
            index += 2
            continue
        if code == _CHAR_COMPRESSED_MARK:
            # The ROM asserts against this reaching the renderer (render_text.c:73), so if it is
            # here the buffer is not a formatted message. Say so rather than decode noise.
            out.append("[COMPRESSED]")
            index += 1
            continue
        if code == _CHAR_FORMAT_ARG:
            arg_type = words[index + 1] if index + 1 < len(words) else 0
            field_count = words[index + 2] if index + 2 < len(words) else 0
            control = _FORMAT_ARG_CONTROLS.get(arg_type)
            if control is None:
                out.append(f"[VAR:{arg_type:#06x}]")
            index += 3 + field_count
            continue
        out.append(_POKE_CHARMAP.get(code, f"[{code}]"))
        index += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Battle phase vocabulary — the enums whose values the phase records carry.
#
# Names, not just numbers, because the whole point of a phase record is to be read. All three
# condition-check state machines are declared inside src/battle/battle_controller_player.c (they
# are file-local enums, so they are not in a header to import even in C).
# ---------------------------------------------------------------------------

#: enum BattleControlSequence, include/battle/battle_controller_player.h:10.
#: The BATTLE_CONTROL_ prefix is dropped; it is on every entry and adds nothing to a log line.
BATTLE_CONTROL_NAMES = (
    "GET_BATTLE_MON", "START_ENCOUNTER", "TRAINER_MESSAGE", "SHOW_BATTLE_MON",
    "INIT_COMMAND_SELECTION", "COMMAND_SELECTION_INPUT", "CALC_TURN_ORDER",
    "CHECK_PRE_MOVE_ACTIONS", "BRANCH_ACTIONS", "CHECK_FIELD_CONDITIONS",
    "CHECK_MON_CONDITIONS", "CHECK_SIDE_CONDITIONS", "TURN_END",
    "FIGHT", "ITEM", "PARTY", "RUN",
    "SAFARI_BALL", "SAFARI_BAIT", "SAFARI_ROCK", "SAFARI_WAIT",
    "EXEC_SCRIPT", "BEFORE_MOVE", "TRY_MOVE", "PRIMARY_EFFECT", "MOVE_FAILED", "USE_MOVE",
    "UPDATE_HP", "AFTER_MOVE_MESSAGE", "UNUSED_29", "AFTER_MOVE_EFFECT", "LOOP_MULTI_HIT",
    "UNUSED_32", "LOOP_FAINTED", "LOOP_SPREAD_MOVES", "FAINT_AFTER_SELFDESTRUCT",
    "TRIGGER_AFTER_HIT_EFFECTS", "UNUSED_37", "UPDATE_MOVE_BUFFERS", "MOVE_END",
    "CHECK_ANY_FAINTED", "RESULT", "SCREEN_WIPE", "FIGHT_END", "END_WAIT",
)

#: enum MonCondCheckState, src/battle/battle_controller_player.c:1256. THRASH (14) is the state
#: metronome_compass measured the rampage-end confusion roll in, which is what anchors
#: sim._END_OF_TURN_RESIDUAL_ANCHOR; YAWN (23) is the one clayton-6xu.7.1 is about.
#:
#: Those two numbers are ONE LOWER than notes/platinum.md, sim.py and clayton-6xu.7.1 all give
#: (15 and 24, and Taunt 20 against the 19 here). The enum opens
#: ``MON_COND_CHECK_STATE_INGRAIN = MON_COND_CHECK_START``, an alias and not a state of its own,
#: so counting MON_COND_CHECK_START as a slot shifts everything after it by one; these are the
#: decomp's values. Nothing about the ORDER changes, so no conclusion drawn from the old numbers
#: is wrong -- but a phase record carries the number, so it has to be the ROM's.
MON_COND_CHECK_NAMES = (
    "INGRAIN", "AQUA_RING", "ABILITY", "USE_ITEM", "LEFTOVERS", "LEECH_SEED", "POISON",
    "TOXIC", "BURN", "NIGHTMARE", "CURSE", "BIND", "BAD_DREAMS", "UPROAR", "THRASH",
    "DISABLE", "ENCORE", "LOCK_ON", "CHARGE", "TAUNT", "MAGNET_RISE", "HEAL_BLOCK",
    "EMBARGO", "YAWN", "ITEM_CONDITION", "ITEM_DETRIMENTAL_EFFECT", "END",
)

#: enum SideCondCheckState, src/battle/battle_controller_player.c:1735. FUTURE_SIGHT is state 0,
#: so it is the first thing the side-condition walk does -- the other half of 6xu.7.1.
SIDE_COND_CHECK_NAMES = ("FUTURE_SIGHT", "PERISH_SONG", "TRICK_ROOM", "END")

#: enum FieldCondCheckState, src/battle/battle_controller_player.c:897.
FIELD_COND_CHECK_NAMES = (
    "REFLECT", "LIGHT_SCREEN", "MIST", "SAFEGUARD", "TAILWIND", "LUCKY_CHANT", "WISH",
    "RAINING", "SANDSTORM", "SUNNY", "HAILING", "DEEP_FOG", "GRAVITY", "END",
)

#: enum NarcID, include/constants/narc.h:5. Only the two the battle script engine loads from.
NARC_WAZA_SEQ = 0    #: battle/skill/waza_seq.narc — indexed by MOVE ID (battle_script.c:2130)
NARC_SUB_SEQ = 1     #: battle/skill/sub_seq.narc  — indexed by subscript (common.h:27)
#: battle/skill/be_seq.narc — indexed by the move's EFFECT, not by the move
#: (``BattleScript_Jump(battleCtx, NARC_INDEX_BATTLE__SKILL__BE_SEQ, CURRENT_MOVE_DATA.effect)``,
#: battle_script.c:2084). This is the narc most of a turn's rolls happen under, and the first
#: recording was unreadable without it: every move execution showed as a bare ``narc30:<n>``.
NARC_BE_SEQ = 30


def _name_of(table, index):
    """`table[index]`, or the bare number when it is out of range.

    Out of range is not necessarily corruption: the check-state fields sit at their END value
    between turns, and END is the last entry of each table, so this mostly guards a build whose
    enum grew.
    """
    if isinstance(index, int) and 0 <= index < len(table):
        return table[index]
    return str(index)


# ---------------------------------------------------------------------------
# Script names.
#
# `battleCtx->scriptFile` is an index into whichever NARC `battleCtx->scriptNarc` names, so the
# number alone is not readable: 18 is subscript_fall_asleep in sub_seq and Sand-Attack in
# waza_seq. Both tables can be resolved off disk:
#
#   sub_seq -> pokeplatinum's res/battle/scripts/subscripts/sub_seq.order, one name per line, in
#              index order. That file lives in the decomp, not in this repo, so the path is an
#              env var with the usual clone location as the default and silence as the fallback.
#   waza_seq -> this repo's own claytonlib/basedata/moves.json, which already has every move's
#              number and name.
#
# A missing table costs the name, never the record: the raw narc/file/cursor numbers are logged
# either way, so a log taken on a machine without the decomp is still analysable.
# ---------------------------------------------------------------------------

_SUBSEQ_ORDER_ENV = "CLAYTON_PL_SUBSEQ_ORDER"
_SUBSEQ_ORDER_DEFAULT = os.path.expanduser(
    "~/w/pokeplatinum/res/battle/scripts/subscripts/sub_seq.order")

_script_tables = None     # None = not loaded yet; then {"sub_seq": [...], "waza_seq": {id: name}}


def load_subseq_order(path=None):
    """The subscript names in index order, or [] when the file is not there."""
    path = path or os.environ.get(_SUBSEQ_ORDER_ENV) or _SUBSEQ_ORDER_DEFAULT
    try:
        with open(path) as fh:
            return [line.strip() for line in fh if line.strip()]
    except Exception:
        return []


def load_move_names(path=None):
    """{move id: name} from claytonlib/basedata/moves.json, or {} when unreadable.

    Read as plain JSON rather than through ``claytonlib``, so this works whether or not the repo
    is importable from GDB's interpreter.
    """
    path = path or os.path.join(os.getcwd(), "claytonlib", "basedata", "moves.json")
    try:
        with open(path) as fh:
            return {entry["number"]: entry["name"] for entry in json.load(fh)}
    except Exception:
        return {}


def script_tables():
    """Both name tables, loaded once."""
    global _script_tables
    if _script_tables is None:
        _script_tables = {"sub_seq": load_subseq_order(), "waza_seq": load_move_names()}
    return _script_tables


def resolve_script(narc, index, tables=None, move=None):
    """A readable name for (`narc`, `index`), e.g. ``sub_seq:subscript_fall_asleep``.

    `move` is ``battleCtx->moveCur``, used only to name a be_seq script: that narc is indexed by
    the move's *effect*, which many moves share, so ``be_seq:effect_17`` alone does not say
    whether the roll belonged to Swift or to Tri Attack.

    Falls back to ``sub_seq:18`` when the table is missing and ``narc7:18`` when the NARC is not
    one the battle script engine loads from.
    """
    tables = script_tables() if tables is None else tables
    if narc == NARC_SUB_SEQ:
        order = tables.get("sub_seq") or []
        name = order[index] if 0 <= index < len(order) else str(index)
        return f"sub_seq:{name}"
    if narc == NARC_WAZA_SEQ:
        moves = tables.get("waza_seq") or {}
        return f"waza_seq:{moves.get(index, index)}"
    if narc == NARC_BE_SEQ:
        moves = tables.get("waza_seq") or {}
        named = moves.get(move)
        return f"be_seq:effect_{index}" + (f"({named})" if named else "")
    return f"narc{narc}:{index}"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: LCRNG_MULTIPLIER / LCRNG_INCREMENT, include/constants/battle/battle.h via
#: src/battle/battle_system.c:1310 -- the same constants HG/SS uses, as notes/platinum.md records.
_MULT, _INC = 1103515245, 24691

#: Every ROM symbol this file breaks on, named once so that the breakpoints and
#: tests/test_gdb_platinum_battle_reader.py (which checks them against the decomp) cannot
#: disagree. That test exists because the HG/SS reader once broke on two symbols that were not
#: in the build, and GDB turned them into *pending* breakpoints -- an error printed, then silence.
SYM_BATTLE_START = "FieldBattleDTO_New"
SYM_RANDOM = "BattleSystem_RandNext"
SYM_INIT_BATTLE_MON = "BattleSystem_InitBattleMon"
SYM_MESSAGES = ("BattleMessage_Print", "BattleMessage_PrintToWindow")
BREAKPOINT_SYMBOLS = (SYM_BATTLE_START, SYM_RANDOM, SYM_INIT_BATTLE_MON) + SYM_MESSAGES

_OUTPUT_DIR = os.path.join(os.getcwd(), "data", "battle_logs")
#: A hand-played battle is long, but not unbounded; this only guards a runaway loop.
_MAX_RECORDS = 200_000


def advance_rng(state):
    return (state * _MULT + _INC) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Target stat override -- EDIT THIS BLOCK
# ---------------------------------------------------------------------------
#
# In a real attempt the target's IVs and nature are controlled by the RNG manipulation itself.
# In the emulator they are whatever CreateWildMon_Scripted happened to roll off the save state's
# Seed A, and re-rolling them by hand is impractical -- so the recorder overwrites them to a
# fixed spread, and recomputes the actual stats to match, the moment the battler is built. Every
# recording then measures the SAME target, which is what makes damage rolls comparable between
# runs.
#
# The default is the Uxie of clayton-6xu.7, with a NEUTRAL nature and perfect IVs. Neutral on
# purpose: nature is a second place a stat mismatch can hide, and with a 1.0 multiplier a stat
# that does not match the model is a wrong base stat or a wrong IV, which is a shorter list.
#
# `ivs` is keyed by name on purpose. The ROM's BattleMon lays its IV bitfields out in the order
# hp/atk/def/SPEED/spa/spd -- speed third, not last (include/battle/battle_mon.h:64) -- while
# every display in this project and in the games uses hp/atk/def/spa/spd/spe. A bare six-tuple
# would silently mean two different spreads depending on which order the reader had in mind, so
# there is no bare six-tuple.

OVERRIDE_TARGET = True          # master switch; set False to record the save state as-is

TARGET_OVERRIDE = {
    #: Which battler to rewrite. 1 is the opponent in a single wild battle.
    "battler": 1,
    #: Refuse to write unless the battler really is this species, so a mistimed breakpoint
    #: cannot silently rewrite our own Pokemon. None disables the guard.
    "species": 487,
    "nature": "Modest",        # +Sp. Atk, -Atk
    "ivs": {"hp": 31, "atk": 31, "def": 31, "spa": 31, "spd": 31, "spe": 31},
    #: Wild Pokemon have none; here for completeness.
    "evs": 0,
    #: Levels the preview prints. The battler's real level always comes from the snapshot.
    "preview_levels": (47,),
}

# Nature by index, in the ROM's order (include/constants/pokemon.h: NATURE_HARDY 0 .. QUIRKY 24)
# -> (raised stat, lowered stat), None for the five neutral natures.
NATURES = (
    ("Hardy",   None),            ("Lonely",  ("atk", "def")),
    ("Brave",   ("atk", "spe")),  ("Adamant", ("atk", "spa")),
    ("Naughty", ("atk", "spd")),  ("Bold",    ("def", "atk")),
    ("Docile",  None),            ("Relaxed", ("def", "spe")),
    ("Impish",  ("def", "spa")),  ("Lax",     ("def", "spd")),
    ("Timid",   ("spe", "atk")),  ("Hasty",   ("spe", "def")),
    ("Serious", None),            ("Jolly",   ("spe", "spa")),
    ("Naive",   ("spe", "spd")),  ("Modest",  ("spa", "atk")),
    ("Mild",    ("spa", "def")),  ("Quiet",   ("spa", "spe")),
    ("Bashful", None),            ("Rash",    ("spa", "spd")),
    ("Calm",    ("spd", "atk")),  ("Gentle",  ("spd", "def")),
    ("Sassy",   ("spd", "spe")),  ("Careful", ("spd", "spa")),
    ("Quirky",  None),
)

#: project stat key -> BattleMon field names (stat, IV), as Platinum spells them
#: (include/battle/battle_mon.h:56). Platinum writes them out in full -- `attack`, not `atk`;
#: `spAttack`, not `spAtk` -- and keeps HP in `curHP`/`maxHP` rather than `hp`/`maxHp`, which is
#: the single most mechanical difference between this file and its HG/SS sibling.
_BATTLE_MON_FIELDS = {
    "hp":  ("maxHP",     "hpIV"),
    "atk": ("attack",    "attackIV"),
    "def": ("defense",   "defenseIV"),
    "spa": ("spAttack",  "spAttackIV"),
    "spd": ("spDefense", "spDefenseIV"),
    "spe": ("speed",     "speedIV"),
}

#: BattleMon's current-HP field. Named once, because it is the field whose HG/SS spelling (`hp`)
#: is a *different* field here and so would be written without complaint.
_CUR_HP_FIELD = "curHP"

_STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")

#: Bit position of each IV inside BattleMon's packed u32, in the ROM's own field order --
#: hp, attack, defense, SPEED, spAttack, spDefense -- followed by isEgg (30) and hasNickname (31).
#: Note speed is third, not last. Identical to HG/SS.
_IV_BITS = {"hp": 0, "atk": 5, "def": 10, "spe": 15, "spa": 20, "spd": 25}
#: The two flags sharing that word, which a write must preserve.
_IV_WORD_FLAG_MASK = 0b11 << 30
#: Byte offset of the word from the start of ``moves[0]``: four u16 moves.
_IV_WORD_OFFSET_FROM_MOVES = 8


def pack_iv_word(ivs, existing=0):
    """The 32-bit word BattleMon stores its six IVs in, preserving the two flag bits.

    Written as one word rather than six bitfield assignments, for the reason the HG/SS reader
    records: GDB's per-bitfield writes did not take reliably there (four of six landed), and
    there is no reason to depend on how a debugger implements a read-modify-write when the whole
    word can be assembled here.
    """
    word = existing & _IV_WORD_FLAG_MASK
    for key, shift in _IV_BITS.items():
        value = ivs[key] if isinstance(ivs, dict) else ivs
        if not 0 <= value <= 31:
            raise ValueError(f"IV out of range for {key}: {value}")
        word |= (value & 0x1F) << shift
    return word


def unpack_iv_word(word):
    """The inverse, for checking a readback."""
    return {key: (word >> shift) & 0x1F for key, shift in _IV_BITS.items()}


def _fmt_spread(spread):
    """A spread in the project's display order, hp/atk/def/spa/spd/spe."""
    return "/".join(str(spread[k]) for k in _STAT_KEYS)


def nature_index(name):
    """The ROM's nature index for `name`. Raises for an unknown nature."""
    wanted = name.strip().capitalize()
    for i, (nature, _) in enumerate(NATURES):
        if nature == wanted:
            return i
    raise ValueError(f"unknown nature {name!r}")


def nature_multiplier(name, stat):
    """1.1 / 0.9 / 1.0. HP is never affected by nature."""
    effect = NATURES[nature_index(name)][1]
    if effect is None or stat == "hp":
        return 1.0
    raised, lowered = effect
    return 1.1 if stat == raised else 0.9 if stat == lowered else 1.0


def calc_stat(base, iv, ev, level, mult):
    """A non-HP stat. Floors twice, as the game does."""
    pre = (2 * base + iv + ev // 4) * level // 100 + 5
    return int(pre * mult)


def calc_hp(base, iv, ev, level):
    return (2 * base + iv + ev // 4) * level // 100 + level + 10


def derive_stats(base, level, nature, ivs, evs=0):
    """Full spread from base stats, level, nature and IVs.

    Duplicated from ``claytonlib.battle.stats`` rather than imported, for the same reason the
    charmap above is duplicated: this file is sourced into GDB's own interpreter, where the
    repo may not be importable, and a recorder that dies on an import is worse than six lines
    of arithmetic. ``tests/test_gdb_platinum_battle_reader.py`` asserts the two agree, so the
    copy cannot drift.
    """
    ev_of = (lambda k: evs) if isinstance(evs, int) else evs.get
    iv_of = (lambda k: ivs) if isinstance(ivs, int) else ivs.get
    out = {}
    for key in _STAT_KEYS:
        iv, ev = iv_of(key) or 0, ev_of(key) or 0
        out[key] = (calc_hp(base[key], iv, ev, level) if key == "hp"
                    else calc_stat(base[key], iv, ev, level,
                                   nature_multiplier(nature, key)))
    return out


def pid_with_nature(personality, nature):
    """`personality` adjusted so ``pid % 25`` is `nature`, the game's own idiom
    (src/pokemon.c: ``pid += nature - (pid % 25)``).

    Keeping the high bits means gender, shininess and ability slot move as little as possible.
    They can still change -- ability is ``pid & 1`` -- which is harmless for the lake trio, all
    of which are genderless and have Levitate as their only ability, but would not be for an
    arbitrary species.

    One deviation from the ROM's line: rounding *up* to the requested nature can carry past
    0xFFFFFFFF, and a wrapped PID has the wrong nature. The game never meets that case because
    it clears the top byte first; here the PID comes from a save state, so it can. We step down
    by 25 instead, which lands on the right nature and still moves the PID by under 50.
    """
    index = nature if isinstance(nature, int) else nature_index(nature)
    candidate = personality - personality % 25 + index
    if candidate > 0xFFFFFFFF:
        candidate -= 25
    return candidate


def base_stats_for(species_id, path=None):
    """Base stats by National Dex number, from claytonlib/basedata/base_stats.json.

    Gen 4 species IDs are the National Dex numbers for all 493, so the ROM's `species` field
    indexes this table directly.

    Read as plain JSON off disk rather than through ``claytonlib``, so this works whether or not
    the repo is importable from GDB's interpreter. Returns None when the species is absent,
    which the caller reports rather than guessing.
    """
    path = path or os.path.join(os.getcwd(), "claytonlib", "basedata", "base_stats.json")
    try:
        with open(path) as fh:
            table = json.load(fh)
    except Exception:
        return None
    for entry in table.values():
        if entry.get("dex_no") == species_id:
            return entry["base_stats"]
    return None


def plan_override(snapshot, config=None, base=None):
    """What to write, and what was there before. Pure, so it is testable without an emulator.

    Returns ``{"before": ..., "after": ..., "writes": {field: value}, "skipped": reason|None}``.
    The keys of `writes` are BattleMon field names as PLATINUM spells them, because they are
    handed straight to GDB. `snapshot` is a ``_read_mon`` result, whose keys stay in this
    project's vocabulary. `base` overrides the on-disk base-stat lookup.
    """
    config = config or TARGET_OVERRIDE
    species_id = snapshot["species"]
    expected = config.get("species")
    before = {
        "species": species_id,
        "level": snapshot["level"],
        "nature": NATURES[snapshot["personality"] % 25][0],
        "nature_index": snapshot["personality"] % 25,
        "personality": snapshot["personality"],
        "ivs": dict(snapshot["ivs"]),
        "stats": dict(snapshot["stats"], hp=snapshot["maxHp"]),
        "hp": snapshot["hp"],
        "maxHp": snapshot["maxHp"],
    }
    if expected is not None and species_id != expected:
        return {"before": before, "after": None, "writes": {},
                "skipped": f"battler is species {species_id}, not the configured {expected}"}
    base = base or base_stats_for(species_id)
    if base is None:
        return {"before": before, "after": None, "writes": {},
                "skipped": f"no base stats on file for species {species_id}"}

    level = snapshot["level"]
    ivs = dict(config["ivs"])
    stats = derive_stats(base, level, config["nature"], ivs, config.get("evs", 0))
    personality = pid_with_nature(snapshot["personality"], config["nature"])

    writes = {"personality": personality}
    for key, (stat_field, _iv_field) in _BATTLE_MON_FIELDS.items():
        writes[stat_field] = stats[key]
    # A wild target is sent out at full HP, so full stays full. Otherwise keep the absolute
    # value and clamp -- scaling it would invent a damage figure that never happened.
    writes[_CUR_HP_FIELD] = (stats["hp"] if before["hp"] == before["maxHp"]
                             else min(before["hp"], stats["hp"]))
    after = {
        "iv_word": pack_iv_word(ivs),
        "nature": NATURES[nature_index(config["nature"])][0],
        "nature_index": nature_index(config["nature"]),
        "personality": personality,
        "ivs": ivs,
        "stats": stats,
        "hp": writes[_CUR_HP_FIELD],
        "maxHp": stats["hp"],
    }
    return {"before": before, "after": after, "writes": writes, "skipped": None}


# ---------------------------------------------------------------------------
# Phase records
# ---------------------------------------------------------------------------

#: The BattleContext fields a phase record carries, spelled as the decomp spells them so a log
#: line can be grepped straight against include/battle/battle_context.h:128.
#:
#: The three ...CheckState/...CheckTemp pairs are the end-of-turn state machines: State is which
#: condition is being walked, Temp is which battler within it. Together with `command` they say
#: exactly where in the end-of-turn sequence a roll happened, which is what clayton-6xu.7.1
#: needs. `scriptNarc`/`scriptFile`/`scriptCursor` say which script instruction asked.
PHASE_FIELDS = (
    "command", "commandNext",
    "fieldConditionCheckState", "fieldConditionCheckTemp",
    "monConditionCheckState", "monConditionCheckTemp",
    "sideConditionCheckState", "sideConditionCheckTemp",
    "attacker", "defender",
    "scriptNarc", "scriptFile", "scriptCursor",
    #: Which move is executing. `scriptFile` under be_seq is the move's EFFECT, which many moves
    #: share, so without this a be_seq script cannot be named. It lives far from the rest in
    #: BattleContext (past battleScript[] and battleMons[]), which is why _PhaseProbe reads in
    #: clusters rather than one span.
    "moveCur",
)

#: Plausible ranges for the fields a bad read would corrupt, used by :func:`phase_is_sane`.
#: Needed because the FIRST rolls of a battle happen before `battleSys->battleCtx` points
#: anywhere -- data/battle_logs/uxie1.jsonl opens with a phase record of
#: ``command=-494088671`` read off an uninitialised pointer, which is noise in a log whose whole
#: purpose is to say where a roll happened.
_PHASE_BOUNDS = {
    "command": (0, len(BATTLE_CONTROL_NAMES) - 1),
    "commandNext": (0, len(BATTLE_CONTROL_NAMES) - 1),
    "fieldConditionCheckState": (0, len(FIELD_COND_CHECK_NAMES) - 1),
    "monConditionCheckState": (0, len(MON_COND_CHECK_NAMES) - 1),
    "sideConditionCheckState": (0, len(SIDE_COND_CHECK_NAMES) - 1),
    "fieldConditionCheckTemp": (0, 3),
    "monConditionCheckTemp": (0, 3),
    "sideConditionCheckTemp": (0, 3),
    "attacker": (0, 3),
    "defender": (0, 3),
    "scriptNarc": (0, 255),
    "scriptFile": (0, 0xFFFF),
    "scriptCursor": (0, 0xFFFF),
    "moveCur": (0, 0xFFFF),
}


def phase_is_sane(fields):
    """Whether `fields` can be a real BattleContext, rather than a read off a stale pointer.

    Pure, so it is testable. Every bound is a range the ROM's own enums and array sizes make
    inescapable, so this rejects garbage without ever rejecting a legitimate state.
    """
    for name, (low, high) in _PHASE_BOUNDS.items():
        value = fields.get(name)
        if not isinstance(value, int) or not low <= value <= high:
            return False
    return True


def phase_names(fields, tables=None):
    """The readable half of a phase record: {enum field: name}.

    Separate from the raw values rather than replacing them. The numbers are what match the
    decomp; the names are what make a log readable, and a name is only ever a lookup away from
    being wrong if a build's enum grew.
    """
    return {
        "command": _name_of(BATTLE_CONTROL_NAMES, fields.get("command")),
        "commandNext": _name_of(BATTLE_CONTROL_NAMES, fields.get("commandNext")),
        "fieldConditionCheckState": _name_of(FIELD_COND_CHECK_NAMES,
                                             fields.get("fieldConditionCheckState")),
        "monConditionCheckState": _name_of(MON_COND_CHECK_NAMES,
                                           fields.get("monConditionCheckState")),
        "sideConditionCheckState": _name_of(SIDE_COND_CHECK_NAMES,
                                            fields.get("sideConditionCheckState")),
        "script": resolve_script(fields.get("scriptNarc"), fields.get("scriptFile"), tables,
                                 move=fields.get("moveCur")),
        "moveCur": (tables or script_tables()).get("waza_seq", {}).get(
            fields.get("moveCur"), str(fields.get("moveCur"))),
    }


def format_phase(phase):
    """One line describing a phase record, for the live print and for logcheck's report."""
    fields, names = phase.get("fields", {}), phase.get("names", {})
    return (f"{names.get('command', fields.get('command'))}"
            f"  field={names.get('fieldConditionCheckState')}/{fields.get('fieldConditionCheckTemp')}"
            f"  mon={names.get('monConditionCheckState')}/{fields.get('monConditionCheckTemp')}"
            f"  side={names.get('sideConditionCheckState')}/{fields.get('sideConditionCheckTemp')}"
            f"  {names.get('script')}@{fields.get('scriptCursor')}"
            f"  atk={fields.get('attacker')} def={fields.get('defender')}")


# ---------------------------------------------------------------------------
# Recording state (pure enough to reason about; no gdb needed to construct)
# ---------------------------------------------------------------------------

class Recording:
    """One battle's interleaved record.

    `records` is ordered and heterogeneous, exactly like the HG/SS reader's, so the analyser can
    reconstruct what happened between any two rolls:

        {"roll": {"addr","func","val"}}   every BattleSystem_RandNext return
        {"msg": "..."}                    a battle message
        {"hp": [{"battler","hp","max"}]}  emitted only when an HP value CHANGES
        {"phase": {"fields","names"}}     emitted only when the battle phase CHANGES
        {"mon": {...}}                    a full battler snapshot, at send-out
        {"override": {...}}               the target's IVs/nature/stats, before and after
        {"seed": {...}}                   the battle's seeds, read at its first roll
        {"mark": "label"}                 a manual marker you typed

    The "phase" entry is this reader's addition over its HG/SS sibling, and the reason the file
    exists: see PHASE_FIELDS.
    """

    #: Written into the output so an analyser never has to guess which game a log came from --
    #: the two readers write to the same directory.
    game = "platinum"

    def __init__(self, forced_seed=None, label=""):
        self.forced_seed = forced_seed
        self.label = label
        self.records = []
        self.started_at = time.time()
        self.hp_seen = {}        # battler id -> last logged (hp, max)
        self.phase_seen = None   # last logged tuple of PHASE_FIELDS values
        self.seed_seen = False   # whether this battle's seeds have been logged
        self.stopped = False

    # -- accumulation ---------------------------------------------------

    def add_roll(self, addr, func, val):
        """One roll. **`addr` is the identity; `func` is a hint and often a wrong one.**

        `func` is GDB's name for the frame the roll came from, and the battle code lives in an
        overlay: other overlays are linked at the same addresses, so a PC inside overlay 12
        resolves to whichever symbol the loaded ELF happens to have there. In
        data/battle_logs/uxie1.jsonl the 192 most common rolls came back as `ChooseTraceTarget`
        in a battle with no Trace in it, while `BattleSystem_CalcDamageVariance` and
        `BattleSystem_CalcCriticalMulti` on other addresses were right. The PC is unambiguous, so
        group by `addr` (``logcheck.rolls_by_site``) and treat `func` as a label to check.
        """
        obj = {"roll": {"addr": addr, "func": func, "val": val}}
        self.records.append(obj)
        return obj

    def add_message(self, msg):
        obj = {"msg": msg}
        self.records.append(obj)
        return obj

    def add_mark(self, label):
        obj = {"mark": label}
        self.records.append(obj)
        return obj

    def add_mon(self, snapshot):
        obj = {"mon": snapshot}
        self.records.append(obj)
        return obj

    def add_seed(self, seed):
        """The battle's seeds as the game holds them, at the first roll.

        Logged whether or not a seed was forced: for a forced battle it is the confirmation, and
        for an un-forced one it is the only record of what Seed B was.
        """
        obj = {"seed": seed}
        self.records.append(obj)
        self.seed_seen = True
        return obj

    def add_dto_seed(self, detail):
        """The dto->seed write: what was there, what went in, what read back."""
        obj = {"dto_seed": detail}
        self.records.append(obj)
        return obj

    def add_override(self, plan):
        """The stat override, both sides of it.

        The `before` half is the point: a recording is only comparable to another if you can
        see what the save state actually held, so the original IVs, nature and stats are logged
        whether or not the write succeeded.
        """
        obj = {"override": plan}
        self.records.append(obj)
        return obj

    def note_hp(self, readings):
        """Record HP only when it changed, so the log stays readable.

        `readings` is [{"battler","hp","max"}]. Returns the entry appended, or None.
        """
        changed = [r for r in readings
                   if self.hp_seen.get(r["battler"]) != (r["hp"], r["max"])]
        if not changed:
            return None
        for r in changed:
            self.hp_seen[r["battler"]] = (r["hp"], r["max"])
        obj = {"hp": changed}
        self.records.append(obj)
        return obj

    def note_phase(self, fields, names=None):
        """Record the phase only when it changed.

        The dedup key includes `scriptCursor`, so consecutive rolls from different instructions
        of one script are separate entries. That is deliberate: "which instruction asked for
        this roll" is the question, and collapsing it would answer a weaker one.
        """
        key = tuple(fields.get(name) for name in PHASE_FIELDS)
        if key == self.phase_seen:
            return None
        self.phase_seen = key
        obj = {"phase": {"fields": dict(fields), "names": dict(names or {})}}
        self.records.append(obj)
        return obj

    # -- summary / output ------------------------------------------------

    @property
    def roll_count(self):
        return sum(1 for r in self.records if "roll" in r)

    def to_json(self):
        doc = {
            "game": self.game,
            "label": self.label,
            "forced_seed": None if self.forced_seed is None else f"{self.forced_seed:#010x}",
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_at)),
            "records": self.records,
        }
        return json.dumps(doc, separators=(",", ":"))


def output_path(label):
    """data/battle_logs/<label>.jsonl, sanitised. Appends, so repeats accumulate."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "platinum"))
    return os.path.join(_OUTPUT_DIR, f"{safe or 'platinum'}.jsonl")


def write_recording(recording, path=None):
    path = path or output_path(recording.label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(recording.to_json() + "\n")
    return path


# ---------------------------------------------------------------------------
# GDB wiring
# ---------------------------------------------------------------------------

_HOOKS = {}            # what -> "live" or why not; reported at load and by plbattlestatus
_rec = None            # the active Recording, or None
_force_armed = False   # whether the next FieldBattleDTO_New should have its seed rewritten
_hp_available = None   # None = not probed yet; False = symbolic reads unavailable
_phase_mode = "on"     # "on" (record), "verbose" (record and print), "off"
_phase_probe = None    # a _PhaseProbe bound to the current BattleContext
_phase_insane = 0      # phase reads rejected by phase_is_sane, reported by plbattlestatus


def _eval_int(expr):
    return int(gdb.parse_and_eval(expr)) & 0xFFFFFFFF


def _read_u32(addr):
    return int.from_bytes(bytes(gdb.inferiors()[0].read_memory(addr, 4)), "little")


def _battle_ctx(battle_system_ptr):
    """``battleSys->battleCtx``, which is how BattleSystem_GetBattleContext reaches it
    (src/battle/battle_system.c) -- read as a member rather than by calling the function, so we
    never have to run code in the inferior from inside a breakpoint."""
    return _eval_int(f"((BattleSystem *){battle_system_ptr:#x})->battleCtx")


def _read_hp(battle_system_ptr):
    """[{"battler","hp","max"}] for both battlers, or [] if symbolic access is unavailable.

    Platinum keeps these in `curHP` (s32) and `maxHP` (u32), not HG/SS's `hp`/`maxHp`
    (include/battle/battle_mon.h:103).

    Requires DWARF types for BattleSystem/BattleContext. If they are missing we say so once and
    carry on WITHOUT HP rather than guessing at struct offsets: a wrong offset would log
    plausible-looking nonsense, which is worse than logging nothing.
    """
    global _hp_available
    if _hp_available is False:
        return []
    try:
        ctx = _battle_ctx(battle_system_ptr)
        readings = []
        for battler in (0, 1):
            mon = f"((BattleContext *){ctx:#x})->battleMons[{battler}]"
            readings.append({"battler": battler,
                             "hp": int(gdb.parse_and_eval(f"{mon}.curHP")),
                             "max": int(gdb.parse_and_eval(f"{mon}.maxHP"))})
        if _hp_available is None:
            _hp_available = True
            print("[plbattlelog] HP tracking active (symbolic struct access works).")
        return readings
    except Exception as exc:
        if _hp_available is None:
            _hp_available = False
            print(f"[plbattlelog] HP tracking DISABLED: {exc}\n"
                  f"              Rolls and messages will still be recorded. HP needs DWARF "
                  f"types for BattleSystem/BattleContext — load the .elf with symbols.")
        return []


def _read_mon(ctx, battler):
    """A one-off snapshot of a battler, so the log is self-describing.

    Worth having beyond curiosity: it lets claytonlib.battle.stats be checked against the game's
    own numbers rather than against my arithmetic. The keys stay in this project's vocabulary
    (`hp`/`maxHp`, `atk`/`spa`) even though the fields they come from are Platinum's, so a log
    from either reader reads the same way.
    """
    def field(name):
        return int(gdb.parse_and_eval(
            f"((BattleContext *){ctx:#x})->battleMons[{battler}].{name}"))

    def array(name, count):
        return [int(gdb.parse_and_eval(
            f"((BattleContext *){ctx:#x})->battleMons[{battler}].{name}[{i}]"))
            for i in range(count)]

    return {
        "battler": battler,
        "species": field("species"),
        "level": field("level"),
        "hp": field(_CUR_HP_FIELD),
        "maxHp": field("maxHP"),
        "stats": {k: field(src) for k, src in
                  (("atk", "attack"), ("def", "defense"), ("spa", "spAttack"),
                   ("spd", "spDefense"), ("spe", "speed"))},
        "ivs": {k: field(src) for k, src in
                (("hp", "hpIV"), ("atk", "attackIV"), ("def", "defenseIV"),
                 ("spa", "spAttackIV"), ("spd", "spDefenseIV"), ("spe", "speedIV"))},
        "ability": field("ability"),
        "personality": field("personality"),
        "types": [field("type1"), field("type2")],
        "moves": array("moves", 4),
        "pp": array("ppCur", 4),
    }


if _IN_GDB:

    class _PhaseProbe:
        """Reads PHASE_FIELDS out of one BattleContext, cheaply.

        Every field's address is resolved from DWARF once, when the context is first seen, and
        after that each read is raw memory. That matters: a phase read happens on every roll, and
        a roll happens hundreds of times a turn, so fourteen `parse_and_eval` calls per roll
        would be fourteen expression parses and fourteen round trips to the emulator each time.

        The addresses are then grouped into CLUSTERS of nearby fields and each cluster read in
        one go. Clusters rather than one span because `moveCur` sits past ``battleScript[]`` and
        ``battleMons[4]`` -- tens of kilobytes away from `command` -- so a single span would read
        the whole of BattleContext on every roll.
        """

        #: Fields closer together than this share a read. One cluster is then at most this much
        #: slack plus four bytes of real field, so a cluster never reads much it does not need.
        CLUSTER_GAP = 64

        def __init__(self, ctx):
            self.ctx = ctx
            self.addrs = {
                name: _eval_int(f"(unsigned)&((BattleContext *){ctx:#x})->{name}")
                for name in PHASE_FIELDS
            }
            self.clusters = []       # [(lo, length, [(name, offset), ...])]
            for name, addr in sorted(self.addrs.items(), key=lambda kv: kv[1]):
                if self.clusters and addr - (self.clusters[-1][0] + self.clusters[-1][1]) \
                        <= self.CLUSTER_GAP:
                    lo, length, members = self.clusters[-1]
                    self.clusters[-1] = (lo, addr + 4 - lo, members + [(name, addr - lo)])
                else:
                    self.clusters.append((addr, 4, [(name, 0)]))

        def read(self):
            inferior = gdb.inferiors()[0]
            out = {}
            for lo, length, members in self.clusters:
                blob = bytes(inferior.read_memory(lo, length))
                for name, offset in members:
                    out[name] = int.from_bytes(blob[offset:offset + 4], "little", signed=True)
            return out

    def _phase_probe_for(battle_system_ptr):
        """The probe for the live BattleContext, rebuilt if the context moved.

        BattleContext is heap-allocated per battle, so its address changes between battles and
        the cached field addresses have to go with it.
        """
        global _phase_probe
        if _phase_mode == "off":
            return None
        try:
            ctx = _battle_ctx(battle_system_ptr)
            if _phase_probe is None or _phase_probe.ctx != ctx:
                _phase_probe = _PhaseProbe(ctx)
                print(f"[plbattlelog] phase: {len(PHASE_FIELDS)} fields in "
                      f"{len(_phase_probe.clusters)} read(s) per roll.")
            return _phase_probe
        except Exception as exc:
            print(f"[plbattlelog] phase tracking DISABLED: {exc}\n"
                  f"              Needs DWARF types for BattleSystem/BattleContext. Rolls, "
                  f"messages and HP are unaffected, but clayton-6xu.7.1 cannot be answered "
                  f"from a log without phases.")
            _set_phase_mode("off")
            return None

    def _note_phase(battle_system_ptr):
        probe = _phase_probe_for(battle_system_ptr)
        if probe is None or _rec is None or _rec.stopped:
            return
        try:
            fields = probe.read()
        except Exception as exc:
            print(f"[plbattlelog] phase read failed: {exc}")
            return
        if not phase_is_sane(fields):
            # The battle's very first rolls (BattleContext_InitCounters) happen before
            # battleSys->battleCtx points at anything, so this is expected once per battle
            # rather than a fault. Recording it would put noise in the one place the log is
            # supposed to be precise.
            global _phase_insane
            _phase_insane += 1
            return
        entry = _rec.note_phase(fields, phase_names(fields))
        if entry is not None and _phase_mode == "verbose":
            print(f"[phase] {format_phase(entry['phase'])}")

    def _set_phase_mode(mode):
        global _phase_mode
        _phase_mode = mode

    # -- seed forcing ---------------------------------------------------

    class _DtoNewFinish(gdb.FinishBreakpoint):
        """On FieldBattleDTO_New's return, rewrite `dto->seed`.

        r0 holds the returned FieldBattleDTO*. The write is read back immediately, because a
        write that did not take would otherwise leave a log labelled with a seed the game never
        saw -- and unlike a wrong stat, a wrong seed label invalidates every conclusion in the
        log rather than one number in it.
        """

        def __init__(self, frame):
            super().__init__(frame, internal=True)
            self.silent = True

        def stop(self):
            global _force_armed
            if _rec is None or _rec.stopped or _rec.forced_seed is None or not _force_armed:
                return False
            _force_armed = False
            try:
                dto = _eval_int("$r0")
                addr = _eval_int(f"(unsigned)&((FieldBattleDTO *){dto:#x})->seed")
                natural = _read_u32(addr)
                gdb.execute(f"set *(unsigned int *){addr:#x} = {_rec.forced_seed:#x}",
                            to_string=True)
                readback = _read_u32(addr)
            except Exception as exc:
                print(f"[plbattlelog] ABORT: could not force the seed: {exc}\n"
                      f"              This needs DWARF types for FieldBattleDTO. Stopping so "
                      f"nothing is recorded under a seed that was not applied.")
                _rec.stopped = True
                return True
            _rec.add_dto_seed({"addr": f"0x{addr:08x}",
                               "natural": f"0x{natural:08x}",
                               "written": f"0x{_rec.forced_seed:08x}",
                               "readback": f"0x{readback:08x}"})
            if readback != (_rec.forced_seed & 0xFFFFFFFF):
                print(f"[plbattlelog] ABORT: dto->seed reads back {readback:#010x} after "
                      f"writing {_rec.forced_seed:#010x}. The seed was NOT forced; stopping so "
                      f"nothing is recorded under a false seed.")
                _rec.stopped = True
                return True
            print(f"[plbattlelog] forced battle seed {_rec.forced_seed:#010x} "
                  f"(was {natural:#010x})")
            return False

    class DtoNewBreakpoint(gdb.Breakpoint):
        """Battle start: the DTO is allocated and its seed computed from the clock here
        (src/field_battle_data_transfer.c:115), which makes it both the battle-start signal and
        the one place the battle seed can be set without touching a live register."""

        def __init__(self):
            super().__init__(SYM_BATTLE_START)
            self.silent = True

        def stop(self):
            global _phase_probe
            _phase_probe = None
            if _rec is not None and not _rec.stopped:
                _rec.hp_seen.clear()
                _rec.phase_seen = None
                _rec.seed_seen = False
                try:
                    _DtoNewFinish(gdb.selected_frame())
                except Exception as exc:
                    print(f"[plbattlelog] seed hook failed: {exc}")
            return False

    # -- rolls ----------------------------------------------------------

    def _note_seed(battle_system_ptr):
        """The battle's seeds, read at its first roll -- before the multiply, so seedRandNext is
        still the seed the battle started from."""
        if _rec is None or _rec.stopped or _rec.seed_seen:
            return
        try:
            sys_expr = f"((BattleSystem *){battle_system_ptr:#x})"
            seed = {name: _eval_int(f"{sys_expr}->{name}")
                    for name in ("seedRandNext", "seedDTO", "seedLCRNG")}
        except Exception:
            # Without DWARF there is nothing to read; the roll stream is still recorded.
            _rec.seed_seen = True
            return
        entry = {"seedRandNext": f"0x{seed['seedRandNext']:08x}",
                 "seedDTO": f"0x{seed['seedDTO']:08x}",
                 "seedLCRNG": f"0x{seed['seedLCRNG']:08x}",
                 "forced": None if _rec.forced_seed is None else f"0x{_rec.forced_seed:08x}"}
        if _rec.forced_seed is not None:
            entry["confirmed"] = seed["seedRandNext"] == (_rec.forced_seed & 0xFFFFFFFF)
        _rec.add_seed(entry)
        if entry.get("confirmed") is False:
            print(f"[plbattlelog] ABORT: the battle started from "
                  f"{seed['seedRandNext']:#010x}, not the forced {_rec.forced_seed:#010x}. "
                  f"Stopping so nothing is recorded under a false seed.")
            _rec.stopped = True
            return
        print(f"[plbattlelog] battle seed (seedRandNext) {seed['seedRandNext']:#010x}"
              + ("  [forced, confirmed]" if entry.get("confirmed") else "")
              + f"   Seed A (seedLCRNG) {seed['seedLCRNG']:#010x}")

    class _RandomFinish(gdb.FinishBreakpoint):
        """On BattleSystem_RandNext's return, record the caller and the value, then the phase and
        the HP."""

        def __init__(self, frame, battle_system_ptr):
            super().__init__(frame, internal=True)
            self.silent = True
            self.battle_system_ptr = battle_system_ptr

        def stop(self):
            rec = _rec
            if rec is None or rec.stopped:
                return False
            frame = gdb.selected_frame()
            # THE PHASE RECORD GOES IN BEFORE THE ROLL. Both are read at the same instant --
            # BattleSystem_RandNext has just returned and nothing has run since -- so the phase
            # describes THIS roll either way. But a phase entry is only written when the phase
            # CHANGED, so whichever side of the roll it lands on is the side an analyser has to
            # read it from, and "the phase record preceding a roll describes it" is the only
            # order that also works for the rolls where no entry was written.
            #
            # The first recording (data/battle_logs/uxie1.jsonl) was taken with these two the
            # other way round, which attributed every roll to the phase of the NEXT one: the
            # Yawn duration roll came out labelled SHOW_BATTLE_MON and the roll after it got
            # subscript_fall_asleep. claytonlib.battle.logcheck reads the order below.
            _note_phase(self.battle_system_ptr)
            rec.add_roll(f"0x{frame.pc():08x}", frame.name() or "??", _eval_int("$r0"))
            # HP last: the phase is what the roll was FOR and the HP is what it did, so this
            # order reads forwards.
            readings = _read_hp(self.battle_system_ptr)
            if readings:
                rec.note_hp(readings)
            if len(rec.records) > _MAX_RECORDS:
                print(f"[plbattlelog] stopping: over {_MAX_RECORDS} records. "
                      f"Run plbattlesave to keep what was captured.")
                rec.stopped = True
            return False

    class _RandomBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__(SYM_RANDOM)
            self.silent = True

        def stop(self):
            if _rec is None or _rec.stopped:
                return False
            battle_system_ptr = _eval_int("$r0")
            _note_seed(battle_system_ptr)
            if _rec.stopped:
                return False
            _RandomFinish(gdb.selected_frame(), battle_system_ptr)
            return False

    # -- messages -------------------------------------------------------

    def _read_msg_buffer(battle_system_ptr):
        """``battleSys->msgBuffer``, the String the formatted message text lands in
        (include/struct_defs/battle_system.h:49, filled at battle_system.c:2286).

        Read as a member: unlike HG/SS, where the sibling reader carries a fallback raw offset,
        there is no disassembled Platinum build here to take an offset from, so a missing DWARF
        type means no messages rather than a guessed offset's worth of nonsense.
        """
        return _eval_int(f"((BattleSystem *){battle_system_ptr:#x})->msgBuffer")

    def _decode_msg_string(ptr):
        """Read a String* and decode it.

        `size` bounds the read (include/string_gf.h:11: maxSize, size, integrity, then data at
        byte 8), so a buffer that is not NUL-terminated costs nothing. The decoder stops at
        CHAR_EOS regardless.
        """
        inferior = gdb.inferiors()[0]
        header = bytes(inferior.read_memory(ptr, 4))
        size = int.from_bytes(header[2:4], "little")
        count = max(1, min(size + 1, _MAX_MESSAGE_CHARS))
        blob = bytes(inferior.read_memory(ptr + 8, count * 2))
        words = [int.from_bytes(blob[i:i + 2], "little") for i in range(0, len(blob), 2)]
        return decode_poke_string(words)

    class _MsgFinish(gdb.FinishBreakpoint):
        def __init__(self, frame, battle_system_ptr):
            super().__init__(frame, internal=True)
            self.silent = True
            self.battle_system_ptr = battle_system_ptr

        def stop(self):
            rec = _rec
            if rec is None or rec.stopped:
                return False
            try:
                msgbuf = _read_msg_buffer(self.battle_system_ptr)
                if msgbuf:
                    text = _decode_msg_string(msgbuf)
                    rec.add_message(text)
                    print(f"[msg] {text}")
            except Exception as exc:
                print(f"[plbattlelog] msg decode error: {exc}")
            return False

    class _MsgBreakpoint(gdb.Breakpoint):
        def __init__(self, symbol):
            super().__init__(symbol)
            self.silent = True

        def stop(self):
            if _rec is None or _rec.stopped:
                return False
            _MsgFinish(gdb.selected_frame(), _eval_int("$r0"))
            return False

    # -- target stat override -------------------------------------------

    def _apply_override(ctx, battler):
        """Rewrite the target's IVs, nature and stats, and log both sides.

        Called just after ``BattleSystem_InitBattleMon`` returns, which is where the ROM copies
        every one of these fields out of the Pokemon struct (src/battle/battle_lib.c:70-167) --
        so this is the first moment the values exist and the last moment before anything reads
        them. It runs on every send-out, which is what keeps a switch from quietly restoring the
        save state's own spread.

        One thing it does NOT cover: ``BattleSystem_ReloadPokemon`` (battle_lib.c:169) rewrites
        the five stats from the party Pokemon again after a level-up or a form change. Neither
        happens to a wild target in a capture attempt, so it is not hooked -- but a recording
        where the target levels up would quietly revert.
        """
        try:
            snapshot = _read_mon(ctx, battler)
        except Exception as exc:
            print(f"[plbattlelog] override SKIPPED: cannot read battler {battler}: {exc}")
            return None
        plan = plan_override(snapshot)
        if plan["skipped"]:
            print(f"[plbattlelog] override skipped for battler {battler}: {plan['skipped']}")
            if _rec is not None:
                _rec.add_override(plan)
            return plan

        mon = f"((BattleContext *){ctx:#x})->battleMons[{battler}]"
        for field_name, value in plan["writes"].items():
            gdb.execute(f"set {mon}.{field_name} = {value}", to_string=True)

        # The six IVs share one u32 with isEgg and hasNickname. Written as ONE word, for the
        # reason pack_iv_word records. Addressed from moves[0], which is an ordinary array and so
        # has a taker-of-address.
        iv_addr = _eval_int(f"(unsigned)&{mon}.moves[0]") + _IV_WORD_OFFSET_FROM_MOVES
        current = _read_u32(iv_addr)
        intended = pack_iv_word(plan["after"]["ivs"], current)
        # Hex, not decimal: the word carries the two flag bits, so a preserved `hasNickname`
        # makes it exceed INT_MAX and a decimal literal that large is at the mercy of how GDB
        # types it.
        gdb.execute(f"set *(unsigned int *){iv_addr:#x} = {intended:#x}", to_string=True)
        # Re-read the word IMMEDIATELY, before anything else touches the struct. On HG/SS this
        # same write came back with two of six fields wrong, twice, and these three fields are
        # what separate the explanations -- the store not taking, something else rewriting the
        # word, or an unaligned u32 store that ARM rotates rather than faults.
        plan["iv_word_write"] = {"addr": iv_addr, "aligned": iv_addr % 4 == 0,
                                 "before": current, "intended": intended,
                                 "immediate": _read_u32(iv_addr)}

        # Read back rather than trusting any of it: a truncated write would otherwise look
        # applied and every damage figure in the log would be measured against a spread never in
        # memory.
        readback = _read_mon(ctx, battler)
        actual = dict(readback["stats"], hp=readback["maxHp"])
        mismatched = {k: (plan["after"]["stats"][k], actual[k])
                      for k in plan["after"]["stats"] if plan["after"]["stats"][k] != actual[k]}
        bad_ivs = {k: (plan["after"]["ivs"][k], readback["ivs"][k])
                   for k in plan["after"]["ivs"] if plan["after"]["ivs"][k] != readback["ivs"][k]}
        # Severity is not the same for the two. The SIMULATION consumes the stats; the IVs only
        # ever derived them, and the game will not re-derive mid-battle. So wrong stats
        # invalidate the recording and wrong IVs are a note.
        plan["stats_verified"] = not mismatched
        plan["ivs_verified"] = not bad_ivs
        plan["verified"] = not mismatched and not bad_ivs
        plan["readback"] = {"ivs": readback["ivs"], "stats": actual,
                            "personality": readback["personality"],
                            "iv_word": _read_u32(iv_addr)}
        if _rec is not None:
            _rec.add_override(plan)

        before, after = plan["before"], plan["after"]
        print(f"[plbattlelog] battler {battler} (species {snapshot['species']}, "
              f"Lv{snapshot['level']}) overridden")
        print(f"              nature {before['nature']} -> {after['nature']}")
        print(f"              IVs    {_fmt_spread(before['ivs'])} -> {_fmt_spread(after['ivs'])}")
        print(f"              stats  {_fmt_spread(before['stats'])} -> "
              f"{_fmt_spread(after['stats'])}")
        if mismatched:
            print(f"[plbattlelog] WARNING: the STATS did not take: {mismatched}. "
                  f"Do NOT trust this recording -- every damage figure in it would be measured "
                  f"against a spread that was never in memory.")
        elif bad_ivs:
            write = plan["iv_word_write"]
            print(f"[plbattlelog] note: the stats are correct but these IVs read back "
                  f"differently: {bad_ivs}. Harmless for the simulation, which consumes the "
                  f"stats, but worth knowing.")
            print(f"              IV word @ {write['addr']:#x} "
                  f"(aligned: {write['aligned']}): was {write['before']:#010x}, "
                  f"wrote {write['intended']:#010x}, reads {write['immediate']:#010x}")
            print("              -- the store took, so something after it is rewriting the word."
                  if write["immediate"] == write["intended"]
                  else "              -- the store itself did not take.")
        return plan

    class _InitBattleMonFinish(gdb.FinishBreakpoint):
        """Snapshot the battler, and override it if it is the configured target."""

        def __init__(self, frame, ctx, battler):
            super().__init__(frame, internal=True)
            self.silent = True
            self.ctx = ctx
            self.battler = battler

        def stop(self):
            if OVERRIDE_TARGET and self.battler == TARGET_OVERRIDE.get("battler", 1):
                _apply_override(self.ctx, self.battler)
            # Snapshot AFTER the override, so `mon` entries are what the battle actually ran
            # with. Every battler gets one: our own Pokemon is never overridden and nothing else
            # in the log records its stats, which is half of what a damage check needs.
            if _rec is not None and not _rec.stopped:
                try:
                    _rec.add_mon(_read_mon(self.ctx, self.battler))
                except Exception as exc:
                    print(f"[plbattlelog] could not snapshot battler {self.battler}: {exc}")
            return False

    class _InitBattleMonBreakpoint(gdb.Breakpoint):
        """Entry to BattleSystem_InitBattleMon, to capture its arguments.

        ARM EABI: r0 battleSys, r1 battleCtx, r2 battler, r3 partySlot (battle_lib.c:70). Read
        from registers rather than frame arguments so a build without full DWARF still works.
        """

        def __init__(self):
            super().__init__(SYM_INIT_BATTLE_MON)
            self.silent = True

        def stop(self):
            if _rec is None or _rec.stopped:
                return False
            try:
                _InitBattleMonFinish(gdb.selected_frame(), _eval_int("$r1"), _eval_int("$r2"))
            except Exception as exc:
                print(f"[plbattlelog] send-out hook failed: {exc}")
            return False

    # -- commands -------------------------------------------------------

    class PlBattleLogCommand(gdb.Command):
        """plbattlelog [seed] [label] — start recording the next battle.

        With a hex seed, that seed is forced at battle start. Without one, the battle is
        recorded as it happens and its own seed is logged. `label` names the output file
        (default "platinum")."""

        def __init__(self):
            super().__init__("plbattlelog", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global _rec, _force_armed, _phase_probe
            parts = arg.split()
            seed = None
            label = "platinum"
            if parts:
                try:
                    seed = int(parts[0], 16)
                except ValueError:
                    label = parts[0]
                else:
                    if len(parts) > 1:
                        label = parts[1]
            _rec = Recording(forced_seed=seed, label=label)
            _force_armed = seed is not None
            _phase_probe = None
            print(f"[plbattlelog] recording -> {output_path(label)}")
            if seed is None:
                print("[plbattlelog] no seed forced; the battle's own seed will be logged.")
            else:
                print(f"[plbattlelog] will write {seed:#010x} into dto->seed at the next "
                      f"FieldBattleDTO_New, and confirm it at the battle's first roll. "
                      f"Start the battle now.")
            print(f"[plbattlelog] phase tracking {_phase_mode}")

    class PlBattleOverrideCommand(gdb.Command):
        """plbattleoverride [on|off|show] — control the target stat override.

        With no argument, shows the configured spread. `on`/`off` flip the master switch for
        the rest of the session; edit TARGET_OVERRIDE at the top of this file to change the
        spread itself. The override applies automatically at every send-out, so there is
        normally nothing to run by hand."""

        def __init__(self):
            super().__init__("plbattleoverride", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global OVERRIDE_TARGET
            word = arg.strip().lower()
            if word in ("on", "off"):
                OVERRIDE_TARGET = word == "on"
            elif word not in ("", "show"):
                print(f"[plbattlelog] unknown argument {arg!r}; expected on, off or show.")
                return
            config = TARGET_OVERRIDE
            print(f"[plbattlelog] override {'ON' if OVERRIDE_TARGET else 'OFF'} "
                  f"for battler {config.get('battler', 1)}"
                  + (f", species {config['species']} only" if config.get("species") else ""))
            print(f"              nature {config['nature']}  "
                  f"IVs {_fmt_spread(config['ivs'])}  (hp/atk/def/spa/spd/spe)")
            base = base_stats_for(config.get("species")) if config.get("species") else None
            if base is None:
                print("              stats will be computed at send-out, once the level is "
                      "known.")
            else:
                for level in config.get("preview_levels", (50,)):
                    spread = derive_stats(base, level, config["nature"], config["ivs"],
                                          config.get("evs", 0))
                    print(f"              at Lv{level}: {_fmt_spread(spread)}")

    class PlBattlePhaseCommand(gdb.Command):
        """plbattlephase [on|off|verbose] — control battle-phase recording.

        `on` (the default) records a phase entry whenever the ROM's control command, end-of-turn
        check states or battle script change. `verbose` also prints each one as you play, which
        is how you watch an end-of-turn sequence happen. `off` stops reading BattleContext on
        every roll, which is the only reason to turn it off."""

        def __init__(self):
            super().__init__("plbattlephase", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            word = arg.strip().lower()
            if word in ("on", "off", "verbose"):
                _set_phase_mode(word)
            elif word not in ("", "show"):
                print(f"[plbattlelog] unknown argument {arg!r}; expected on, off or verbose.")
                return
            tables = script_tables()
            print(f"[plbattlelog] phase tracking {_phase_mode}")
            print(f"              fields: {', '.join(PHASE_FIELDS)}")
            print(f"              sub_seq names: "
                  f"{len(tables['sub_seq']) or 'NONE — set ' + _SUBSEQ_ORDER_ENV}"
                  f"   move names: {len(tables['waza_seq']) or 'NONE'}")

    class PlBattleMarkCommand(gdb.Command):
        """plbattlemark <label> — drop a labelled marker into the log at this point."""

        def __init__(self):
            super().__init__("plbattlemark", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None:
                print("[plbattlelog] not recording — run plbattlelog first.")
                return
            label = arg.strip() or "mark"
            _rec.add_mark(label)
            print(f"[plbattlelog] marked {label!r} at record {len(_rec.records)}")

    class PlBattleStatusCommand(gdb.Command):
        """plbattlestatus — what has been captured so far."""

        def __init__(self):
            super().__init__("plbattlestatus", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None:
                print("[plbattlelog] not recording.")
                return
            kinds = {}
            for record in _rec.records:
                key = next(iter(record))
                kinds[key] = kinds.get(key, 0) + 1
            seed = "none" if _rec.forced_seed is None else f"{_rec.forced_seed:#010x}"
            print(f"[plbattlelog] label={_rec.label} forced_seed={seed} "
                  f"stopped={_rec.stopped}")
            print(f"              {kinds or 'nothing captured yet'}")
            hp = ", ".join(f"battler {b}: {v[0]}/{v[1]}" for b, v in sorted(_rec.hp_seen.items()))
            print(f"              HP: {hp or 'not tracked'}")
            if _phase_insane:
                print(f"              phase reads rejected as garbage: {_phase_insane} "
                      f"(expected a few per battle, before battleSys->battleCtx is set)")
            if _rec.phase_seen is not None:
                fields = dict(zip(PHASE_FIELDS, _rec.phase_seen))
                print(f"              phase: "
                      f"{format_phase({'fields': fields, 'names': phase_names(fields)})}")
            dead = [k for k, v in _HOOKS.items() if v != "live"]
            if dead:
                print(f"              NOT HOOKED: {', '.join(dead)}")

    class PlBattleSaveCommand(gdb.Command):
        """plbattlesave [path] — flush the recording to jsonl and stop recording."""

        def __init__(self):
            super().__init__("plbattlesave", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global _rec
            if _rec is None:
                print("[plbattlelog] nothing to save.")
                return
            path = write_recording(_rec, arg.strip() or None)
            print(f"[plbattlelog] wrote {_rec.roll_count} rolls / {len(_rec.records)} records "
                  f"to {path}")
            print("[plbattlelog] analyse with: "
                  "python -m claytonlib.battle.logcheck " + path)
            _rec.stopped = True
            _rec = None

    def _install(what, factory):
        """Create a breakpoint, or record why it could not be.

        GDB's default for an unknown symbol is a *pending* breakpoint: it prints an error and
        then silently never fires, which the constructor reports as success. That is the worst
        outcome here -- a recording that looks fine and is missing a whole class of event.
        `breakpoint pending off` makes the constructor raise instead, which we can act on.
        """
        try:
            gdb.execute("set breakpoint pending off", to_string=True)
            bp = factory()
        except Exception as exc:
            _HOOKS[what] = f"UNAVAILABLE ({str(exc).splitlines()[0]})"
            return None
        finally:
            gdb.execute("set breakpoint pending auto", to_string=True)
        if getattr(bp, "pending", False):
            bp.delete()
            _HOOKS[what] = "UNAVAILABLE (symbol did not resolve)"
            return None
        _HOOKS[what] = "live"
        return bp

    _install("battle start / seed", DtoNewBreakpoint)
    _install("RNG rolls", _RandomBreakpoint)
    _install("send-out + target override", _InitBattleMonBreakpoint)
    # Both public entry points that format a BattleMessage into battleSys->msgBuffer; the
    # formatting itself (BattleMessage_Format) is static, so it is not a symbol to break on.
    for _sym in SYM_MESSAGES:
        _install(f"messages ({_sym})", lambda s=_sym: _MsgBreakpoint(s))
    del _sym

    PlBattleLogCommand()
    PlBattleOverrideCommand()
    PlBattlePhaseCommand()
    PlBattleMarkCommand()
    PlBattleStatusCommand()
    PlBattleSaveCommand()
    for _what, _state in _HOOKS.items():
        print(f"[plbattlelog] {'  ok' if _state == 'live' else 'FAIL'}  {_what}: {_state}")
    if not any(v == "live" for k, v in _HOOKS.items() if k.startswith("messages")):
        print("[plbattlelog] WARNING: no message hook resolved, so the log will record rolls, "
              "phases and HP but NOT battle messages -- and the messages are how you tell which "
              "action each turn was. Check the symbol names against this build before recording.")
    if _HOOKS.get("battle start / seed") != "live":
        print("[plbattlelog] WARNING: FieldBattleDTO_New is not hooked, so a seed CANNOT be "
              "forced and the per-battle state will not reset. Recording is still possible "
              "without a forced seed.")
    if _HOOKS.get("send-out + target override") != "live":
        print("[plbattlelog] WARNING: the target override is not installed; IVs and nature will "
              "be whatever the save state holds. If BattleSystem_InitBattleMon lives in an "
              "overlay, re-source this file once the battle overlay is loaded.")
    if not script_tables()["sub_seq"]:
        print(f"[plbattlelog] note: no sub_seq.order found, so phase records will carry "
              f"subscript NUMBERS and not names. Set {_SUBSEQ_ORDER_ENV} to "
              f"pokeplatinum's res/battle/scripts/subscripts/sub_seq.order "
              f"(tried {_SUBSEQ_ORDER_DEFAULT}).")
    print("[plbattlelog] ready. Commands: plbattlelog [seed] [label], plbattleoverride, "
          "plbattlephase, plbattlemark, plbattlestatus, plbattlesave")
    if OVERRIDE_TARGET:
        print(f"[plbattlelog] target override ON: species {TARGET_OVERRIDE['species']}, "
              f"{TARGET_OVERRIDE['nature']}, IVs {_fmt_spread(TARGET_OVERRIDE['ivs'])} "
              f"(hp/atk/def/spa/spd/spe). plbattleoverride off to disable.")
