#!/usr/bin/env python
"""
gdb-battle-reader.py — sourced inside GDB to record ONE hand-played battle, with the battle
seed optionally forced, as ground truth for Battle Compass.

Sibling to utils/gdb-seed-reader.py, and deliberately simpler in one way and richer in another.

  Simpler: no batch loop and no F-key auto-pressing.  The metronome slurper replays a seed
  FILE, reloading a save state between seeds, because that battle plays itself.  A Battle
  Compass battle is played by hand over dozens of turns, so this records a single battle while
  you play it and the battle messages are enough to deduce what action you took.

  Richer: it logs **your Pokemon's HP**.  That is the one thing messages cannot tell you, and
  it is what R10 needs -- an observed HP change identifies which of the sixteen Gen 4 damage
  rolls (85..100%) landed, which is the strongest identification signal Battle Compass has
  (notes/battle_compass.md sec 3.1).

The shared helpers (charmap, string decoder, seed hijack) are COPIED from gdb-seed-reader.py
rather than imported, following the same convention as that file: each of these is standalone
so a change to one cannot break the other mid-session.

Usage (inside GDB, AFTER attaching to the emulator):

    (gdb) source utils/gdb-battle-reader.py
    (gdb) battlelog 0xEC1504DC      # force this battle seed and start recording
    (gdb) battlelog                 # record without forcing a seed
    ... play the battle ...
    (gdb) battleoverride            # show the target IV/nature override (on by default)
    (gdb) battlemark phase2         # optional: drop a labelled marker into the log
    (gdb) battlestatus              # what has been captured so far
    (gdb) battlesave                # flush to data/battle_logs/<name>.jsonl and stop

The target's IVs and nature are **overwritten** at every send-out, and its actual stats
recomputed to match, so that every recording measures the same Suicune -- see the
TARGET_OVERRIDE block below, which is the one thing in this file meant to be edited.  The
original IVs, nature and stats are logged first, so a recording always says what the save
state really held.

Sourcing only registers the commands and installs breakpoints; it records nothing until
`battlelog`.  Output is one JSON line per recorded battle, so repeated battles append.

On sourcing, every hook reports whether it resolved.  Take the FAIL lines seriously: a missing
message hook leaves a recording that looks complete and has no way to say which action each turn
was, which is the one thing the messages are for.

Analyse the result with `claytonlib.battle.logcheck`, which is pure Python and tested --
everything in this file needs a live emulator, so as little logic as possible lives here.

Symbols this file breaks on, all verified present in utils/main.elf:
BattleSetup_New, BattleSystem_Random, BattleSystem_GetBattleMon,
BattleSystem_PrintBattleMessage and ov12_0223C4E8.
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
# Copied from gdb-seed-reader.py: HG/SS English charmap + string decoder.
# ---------------------------------------------------------------------------

_POKE_CHARMAP = {}
for _i in range(10):
    _POKE_CHARMAP[289 + _i] = str(_i)
for _i in range(26):
    _POKE_CHARMAP[299 + _i] = chr(65 + _i)
    _POKE_CHARMAP[325 + _i] = chr(97 + _i)
_POKE_CHARMAP.update({
    427: '!',  428: '?',  429: ',',  430: '.',  431: '…',
    433: '/',  434: "'",  435: "'",  436: '"',  437: '"',
    441: '(',  442: ')',  443: '♂',  444: '♀',  445: '+',
    446: '-',  447: '*',  448: '#',  449: '=',  450: '&',
    451: '~',  452: ':',  453: ';',  458: '★',  464: '@',
    465: '♪',  466: '%',  478: ' ',  480: 'Pk', 481: 'Mn', 482: ' ',
})
del _i


def _decode_poke_string(ptr):
    """Read a String* at `ptr` and decode it with the HG/SS English charmap."""
    inferior = gdb.inferiors()[0]
    chars = []
    offset = 8  # String.data[] starts at byte 8
    while True:
        code = int.from_bytes(bytes(inferior.read_memory(ptr + offset, 2)), 'little')
        if code == 0xFFFF:       # EOS
            break
        if code == 0xE000:       # newline
            chars.append('\n')
            offset += 2
            continue
        if code == 0xFFFE:       # control code: 0xFFFE, type, field_count, [fields]
            hdr = bytes(inferior.read_memory(ptr + offset + 2, 4))
            ctrl_type = int.from_bytes(hdr[0:2], 'little')
            field_cnt = int.from_bytes(hdr[2:4], 'little')
            if ctrl_type == 0x207:
                chars.append('\n')
            elif ctrl_type & 0xFF00 in (0x100, 0x300, 0x400, 0x3400):
                chars.append(f'[VAR:{ctrl_type:#06x}]')
            offset += 6 + field_cnt * 2
            continue
        chars.append(_POKE_CHARMAP.get(code, f'[{code}]'))
        offset += 2
    return ''.join(chars)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MULT, _INC = 1103515245, 24691
# PC just past `ldr r3, [r0, r2]` in BattleSystem_Random — see gdb-seed-reader.py.
_HIJACK_POST_LOAD_OFF = 8
_OUTPUT_DIR = os.path.join(os.getcwd(), "data", "battle_logs")
# A hand-played battle is long, but not unbounded; this only guards a runaway loop.
_MAX_RECORDS = 200_000


def advance_rng(state):
    return (state * _MULT + _INC) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Target stat override -- EDIT THIS BLOCK
# ---------------------------------------------------------------------------
#
# In a real attempt the target's IVs and nature are controlled by the RNG manipulation itself.
# In the emulator they are whatever the save state happens to hold, and re-rolling them by hand
# is impractical -- so the recorder overwrites them to a fixed spread, and recomputes the actual
# stats to match, the moment the battler is built.  Every recording then measures the SAME
# Suicune, which is what makes damage rolls comparable between runs.
#
# `ivs` is keyed by name on purpose.  The ROM's BattleMon lays its IV bitfields out in the order
# hp/atk/def/SPEED/spa/spd -- speed third, not last -- while every display in this project and
# in the games uses hp/atk/def/spa/spd/spe.  A bare six-tuple would silently mean two different
# spreads depending on which order the reader had in mind, so there is no bare six-tuple.

OVERRIDE_TARGET = True          # master switch; set False to record the save state as-is

TARGET_OVERRIDE = {
    #: Which battler to rewrite. 1 is the opponent in a single wild battle.
    "battler": 1,
    #: Refuse to write unless the battler really is this species, so a mistimed breakpoint
    #: cannot silently rewrite our own Pokemon. None disables the guard.
    "species": 245,             # SPECIES_SUICUNE
    "nature": "Bold",
    "ivs": {"hp": 29, "atk": 15, "def": 31, "spa": 31, "spd": 31, "spe": 28},
    #: Wild Pokemon have none; here for completeness.
    "evs": 0,
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

#: project stat key -> BattleMon field names (stat, IV). Note `speed` sits third in the IV
#: bitfield order but that does not matter here, because these are named writes.
_BATTLE_MON_FIELDS = {
    "hp":  ("maxHp", "hpIV"),
    "atk": ("atk",   "atkIV"),
    "def": ("def",   "defIV"),
    "spa": ("spAtk", "spAtkIV"),
    "spd": ("spDef", "spDefIV"),
    "spe": ("speed", "speedIV"),
}

_STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")


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
    of arithmetic.  ``tests/test_gdb_battle_reader.py`` asserts the two agree, so the copy
    cannot drift.
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
    They can still change -- ability is ``pid & 1`` -- which is harmless for Suicune, whose only
    ability is Pressure and which is genderless, but would not be for an arbitrary species.

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

    Read as plain JSON off disk rather than through ``claytonlib``, so this works whether or not
    the repo is importable from GDB's interpreter.  Returns None when the species is absent,
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
    `snapshot` is a ``_read_mon`` result. `base` overrides the on-disk base-stat lookup.
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
    for key, (stat_field, iv_field) in _BATTLE_MON_FIELDS.items():
        writes[stat_field] = stats[key]
        writes[iv_field] = ivs[key]
    # A wild target is sent out at full HP, so full stays full. Otherwise keep the absolute
    # value and clamp -- scaling it would invent a damage figure that never happened.
    writes["hp"] = (stats["hp"] if before["hp"] == before["maxHp"]
                    else min(before["hp"], stats["hp"]))
    after = {
        "nature": NATURES[nature_index(config["nature"])][0],
        "nature_index": nature_index(config["nature"]),
        "personality": personality,
        "ivs": ivs,
        "stats": stats,
        "hp": writes["hp"],
        "maxHp": stats["hp"],
    }
    return {"before": before, "after": after, "writes": writes, "skipped": None}


# ---------------------------------------------------------------------------
# Recording state (pure enough to reason about; no gdb needed to construct)
# ---------------------------------------------------------------------------

class Recording:
    """One battle's interleaved record.

    `records` is ordered and heterogeneous, exactly like gdb-seed-reader's `results`, so the
    analyser can reconstruct what happened between any two rolls:

        {"roll": {"addr","func","val"}}   every BattleSystem_Random return
        {"msg": "..."}                    a battle message
        {"hp": [{"battler","hp","max"}]}  emitted only when an HP value CHANGES
        {"mon": {...}}                    a full battler snapshot, at battle start
        {"override": {...}}               the target's IVs/nature/stats, before and after
        {"mark": "label"}                 a manual marker you typed
    """

    def __init__(self, forced_seed=None, label=""):
        self.forced_seed = forced_seed
        self.label = label
        self.records = []
        self.started_at = time.time()
        self.hp_seen = {}       # battler id -> last logged (hp, max)
        self.stopped = False

    # -- accumulation ---------------------------------------------------

    def add_roll(self, addr, func, val):
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

        `readings` is [{"battler","hp","max"}].  Returns the entry appended, or None.
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

    # -- summary / output ------------------------------------------------

    @property
    def roll_count(self):
        return sum(1 for r in self.records if "roll" in r)

    def to_json(self):
        doc = {
            "label": self.label,
            "forced_seed": None if self.forced_seed is None else f"{self.forced_seed:#010x}",
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.started_at)),
            "records": self.records,
        }
        return json.dumps(doc, separators=(",", ":"))


def output_path(label):
    """data/battle_logs/<label>.jsonl, sanitised. Appends, so repeats accumulate."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "battle"))
    return os.path.join(_OUTPUT_DIR, f"{safe or 'battle'}.jsonl")


def write_recording(recording, path=None):
    path = path or output_path(recording.label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(recording.to_json() + "\n")
    return path


# ---------------------------------------------------------------------------
# GDB wiring
# ---------------------------------------------------------------------------

_HOOKS = {}          # what -> "live" or why not; reported at load and by battlestatus
_rec = None          # the active Recording, or None
_hijack_bp = None
_hp_available = None  # None = not probed yet; False = symbolic reads unavailable


def _battle_random_base():
    return int(gdb.parse_and_eval("(unsigned)&BattleSystem_Random")) & ~1 & 0xFFFFFFFF


def _eval_int(expr):
    return int(gdb.parse_and_eval(expr)) & 0xFFFFFFFF


def _read_hp(battle_system_ptr):
    """[{"battler","hp","max"}] for both battlers, or [] if symbolic access is unavailable.

    Reached as battleSystem->ctx->battleMons[i], which is how BattleSystem_GetBattleContext
    does it (battle_system.c) — read as a member rather than by calling the function, so we
    never have to run code in the inferior from inside a breakpoint.

    Requires DWARF types for BattleSystem/BattleContext. If they are missing we say so once
    and carry on WITHOUT HP rather than guessing at struct offsets: a wrong offset would log
    plausible-looking nonsense, which is worse than logging nothing.
    """
    global _hp_available
    if _hp_available is False:
        return []
    try:
        ctx = _eval_int(f"((BattleSystem *){battle_system_ptr:#x})->ctx")
        readings = []
        for battler in (0, 1):
            hp = int(gdb.parse_and_eval(
                f"((BattleContext *){ctx:#x})->battleMons[{battler}].hp"))
            mx = int(gdb.parse_and_eval(
                f"((BattleContext *){ctx:#x})->battleMons[{battler}].maxHp"))
            readings.append({"battler": battler, "hp": hp, "max": mx})
        if _hp_available is None:
            _hp_available = True
            print("[battlelog] HP tracking active (symbolic struct access works).")
        return readings
    except Exception as exc:
        if _hp_available is None:
            _hp_available = False
            print(f"[battlelog] HP tracking DISABLED: {exc}\n"
                  f"            Rolls and messages will still be recorded. HP needs DWARF "
                  f"types for BattleSystem/BattleContext — load the .elf with symbols.")
        return []


def _read_mon(ctx, battler):
    """A one-off snapshot of a battler, so the log is self-describing.

    Worth having beyond curiosity: it lets claytonlib.battle.stats be checked against the
    game's own numbers rather than against my arithmetic.
    """
    def field(name):
        return int(gdb.parse_and_eval(f"((BattleContext *){ctx:#x})->battleMons[{battler}].{name}"))
    snapshot = {
        "battler": battler,
        "species": field("species"),
        "level": field("level"),
        "hp": field("hp"),
        "maxHp": field("maxHp"),
        "stats": {k: field(src) for k, src in
                  (("atk", "atk"), ("def", "def"), ("spa", "spAtk"),
                   ("spd", "spDef"), ("spe", "speed"))},
        "ivs": {k: field(src) for k, src in
                (("hp", "hpIV"), ("atk", "atkIV"), ("def", "defIV"),
                 ("spa", "spAtkIV"), ("spd", "spDefIV"), ("spe", "speedIV"))},
        "ability": field("ability"),
        "personality": field("personality"),
        "types": [field("type1"), field("type2")],
        "moves": [int(gdb.parse_and_eval(
            f"((BattleContext *){ctx:#x})->battleMons[{battler}].moves[{i}]")) for i in range(4)],
        "pp": [int(gdb.parse_and_eval(
            f"((BattleContext *){ctx:#x})->battleMons[{battler}].movePPCur[{i}]")) for i in range(4)],
    }
    return snapshot


if _IN_GDB:

    class _SeedHijackBreakpoint(gdb.Breakpoint):
        """At BattleSystem_Random+8, just after the seed load, overwrite r3 with the forced
        seed so the game's own store writes advance_rng(seed) coherently — no corruptible
        memory write. Armed for the first random call of a battle, then disarms itself.

        Lifted from gdb-seed-reader.py, including its sanity check: if r3 does not match the
        value just loaded we are not where we think we are, and silently clobbering a register
        would mislabel the whole recording.
        """

        def __init__(self, addr):
            super().__init__(f"*{addr}", internal=True)
            self.silent = True
            self.enabled = False

        def stop(self):
            if _rec is None or _rec.stopped or _rec.forced_seed is None:
                self.enabled = False
                return False
            if not gdb.convenience_variable("bl_new_seed"):
                return False
            gdb.set_convenience_variable("bl_new_seed", False)
            self.enabled = False
            r0, r2 = _eval_int("$r0"), _eval_int("$r2")
            loaded = _eval_int("$r3")
            mem = int.from_bytes(
                bytes(gdb.inferiors()[0].read_memory((r0 + r2) & 0xFFFFFFFF, 4)), "little")
            if loaded != mem:
                print(f"[battlelog] ABORT: seed-hijack sanity check failed at "
                      f"BattleSystem_Random+{_HIJACK_POST_LOAD_OFF} "
                      f"(r3={loaded:#010x} != rand={mem:#010x}). The seed was NOT forced; "
                      f"stopping so nothing is recorded under a false seed.")
                _rec.stopped = True
                return True
            gdb.execute(f"set $r3 = {_rec.forced_seed & 0xFFFFFFFF}")
            print(f"[battlelog] forced battle seed {_rec.forced_seed:#010x}")
            return False

    def _ensure_hijack_bp():
        global _hijack_bp
        if _hijack_bp is None:
            _hijack_bp = _SeedHijackBreakpoint(_battle_random_base() + _HIJACK_POST_LOAD_OFF)
        return _hijack_bp

    class BattleSetupNewBreakpoint(gdb.Breakpoint):
        """Battle start: arm the seed hijack and reset the per-battle HP cache."""

        def __init__(self):
            super().__init__("BattleSetup_New")
            self.silent = True

        def stop(self):
            gdb.set_convenience_variable("bl_new_seed", True)
            if _rec is not None and not _rec.stopped:
                _rec.hp_seen.clear()
                if _rec.forced_seed is not None:
                    _ensure_hijack_bp().enabled = True
            return False

    class _RandomFinish(gdb.FinishBreakpoint):
        """On BattleSystem_Random's return, record the caller and the value, then the HP."""

        def __init__(self, frame, battle_system_ptr):
            super().__init__(frame, internal=True)
            self.silent = True
            self.battle_system_ptr = battle_system_ptr

        def stop(self):
            rec = _rec
            if rec is None or rec.stopped:
                return False
            frame = gdb.selected_frame()
            rec.add_roll(f"0x{frame.pc():08x}", frame.name() or "??", _eval_int("$r0"))
            # HP after the roll, so a damage roll and its effect sit adjacent in the log.
            readings = _read_hp(self.battle_system_ptr)
            if readings:
                rec.note_hp(readings)
            if len(rec.records) > _MAX_RECORDS:
                print(f"[battlelog] stopping: over {_MAX_RECORDS} records. "
                      f"Run battlesave to keep what was captured.")
                rec.stopped = True
            return False

    class _RandomBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("BattleSystem_Random")
            self.silent = True

        def stop(self):
            if _rec is None or _rec.stopped:
                return False
            _RandomFinish(gdb.selected_frame(), _eval_int("$r0"))
            return False

    def _read_msg_buffer(battle_system_ptr):
        """``battleSystem->msgBuffer``, the String the expanded message text lands in.

        Read as a member where DWARF allows, because the raw offset is only correct for one
        struct layout. It happens to be 0x18 in this build -- unk0, bgConfig, window, msgData,
        unk10, msgFormat, then msgBuffer -- which is the fallback when the type is unavailable.
        """
        try:
            return _eval_int(f"((BattleSystem *){battle_system_ptr:#x})->msgBuffer")
        except Exception:
            return _eval_int(f"*(unsigned int *)({battle_system_ptr:#x} + 0x18)")


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
                    text = _decode_poke_string(msgbuf)
                    rec.add_message(text)
                    print(f"[msg] {text}")
            except Exception as exc:
                print(f"[battlelog] msg decode error: {exc}")
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

        Called just after ``BattleSystem_GetBattleMon`` returns, which is where the ROM copies
        every one of these fields out of the Pokemon struct -- so this is the first moment the
        values exist and the last moment before anything reads them.  It runs on every send-out,
        which is what keeps a switch from quietly restoring the save state's own spread.
        """
        try:
            snapshot = _read_mon(ctx, battler)
        except Exception as exc:
            print(f"[battlelog] override SKIPPED: cannot read battler {battler}: {exc}")
            return None
        plan = plan_override(snapshot)
        if plan["skipped"]:
            print(f"[battlelog] override skipped for battler {battler}: {plan['skipped']}")
            if _rec is not None:
                _rec.add_override(plan)
            return plan

        for field_name, value in plan["writes"].items():
            gdb.execute(f"set ((BattleContext *){ctx:#x})->battleMons[{battler}]."
                        f"{field_name} = {value}", to_string=True)

        # Read the fields back rather than trusting the writes: a bitfield that silently
        # truncated would otherwise look applied, and every damage figure in the log would be
        # measured against a spread that was never in memory.
        readback = _read_mon(ctx, battler)
        actual = dict(readback["stats"], hp=readback["maxHp"])
        mismatched = {k: (plan["after"]["stats"][k], actual[k])
                      for k in plan["after"]["stats"] if plan["after"]["stats"][k] != actual[k]}
        bad_ivs = {k: (plan["after"]["ivs"][k], readback["ivs"][k])
                   for k in plan["after"]["ivs"] if plan["after"]["ivs"][k] != readback["ivs"][k]}
        plan["verified"] = not mismatched and not bad_ivs
        plan["readback"] = {"ivs": readback["ivs"], "stats": actual,
                            "personality": readback["personality"]}
        if _rec is not None:
            _rec.add_override(plan)

        before, after = plan["before"], plan["after"]
        print(f"[battlelog] battler {battler} (species {snapshot['species']}, "
              f"Lv{snapshot['level']}) overridden")
        print(f"            nature {before['nature']} -> {after['nature']}")
        print(f"            IVs    {_fmt_spread(before['ivs'])} -> {_fmt_spread(after['ivs'])}")
        print(f"            stats  {_fmt_spread(before['stats'])} -> "
              f"{_fmt_spread(after['stats'])}")
        if not plan["verified"]:
            print(f"[battlelog] WARNING: readback disagrees with the plan. "
                  f"stats {mismatched} ivs {bad_ivs}. Do NOT trust this recording.")
        return plan

    class _GetBattleMonFinish(gdb.FinishBreakpoint):
        """Apply the override after the ROM has finished populating the battler."""

        def __init__(self, frame, ctx, battler):
            super().__init__(frame, internal=True)
            self.silent = True
            self.ctx = ctx
            self.battler = battler

        def stop(self):
            if OVERRIDE_TARGET and self.battler == TARGET_OVERRIDE.get("battler", 1):
                _apply_override(self.ctx, self.battler)
            return False

    class _GetBattleMonBreakpoint(gdb.Breakpoint):
        """Entry to BattleSystem_GetBattleMon, to capture its arguments.

        ARM EABI: r0 battleSystem, r1 ctx, r2 battlerId, r3 selectedMon. Read from registers
        rather than frame arguments so a build without full DWARF still works.
        """

        def __init__(self):
            super().__init__("BattleSystem_GetBattleMon")
            self.silent = True

        def stop(self):
            if not OVERRIDE_TARGET:
                return False
            try:
                _GetBattleMonFinish(gdb.selected_frame(), _eval_int("$r1"), _eval_int("$r2"))
            except Exception as exc:
                print(f"[battlelog] override hook failed: {exc}")
            return False

    # -- commands -------------------------------------------------------

    class BattleLogCommand(gdb.Command):
        """battlelog [seed] [label] — start recording the next battle.

        With a hex seed, that seed is forced at battle start. Without one, the battle is
        recorded as it happens. `label` names the output file (default "battle")."""

        def __init__(self):
            super().__init__("battlelog", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global _rec
            parts = arg.split()
            seed = None
            label = "battle"
            if parts:
                try:
                    seed = int(parts[0], 16)
                except ValueError:
                    label = parts[0]
                else:
                    if len(parts) > 1:
                        label = parts[1]
            _rec = Recording(forced_seed=seed, label=label)
            where = output_path(label)
            print(f"[battlelog] recording -> {where}")
            if seed is None:
                print("[battlelog] no seed forced; the battle's own seed will be used.")
            else:
                print(f"[battlelog] will force {seed:#010x} at the next BattleSetup_New. "
                      f"Start the battle now.")

    class BattleOverrideCommand(gdb.Command):
        """battleoverride [on|off|show] — control the target stat override.

        With no argument, shows the configured spread. `on`/`off` flip the master switch for
        the rest of the session; edit TARGET_OVERRIDE at the top of this file to change the
        spread itself. The override applies automatically at every send-out, so there is
        normally nothing to run by hand."""

        def __init__(self):
            super().__init__("battleoverride", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global OVERRIDE_TARGET
            word = arg.strip().lower()
            if word in ("on", "off"):
                OVERRIDE_TARGET = word == "on"
            elif word not in ("", "show"):
                print(f"[battlelog] unknown argument {arg!r}; expected on, off or show.")
                return
            config = TARGET_OVERRIDE
            print(f"[battlelog] override {'ON' if OVERRIDE_TARGET else 'OFF'} "
                  f"for battler {config.get('battler', 1)}"
                  + (f", species {config['species']} only" if config.get("species") else ""))
            print(f"            nature {config['nature']}  "
                  f"IVs {_fmt_spread(config['ivs'])}  (hp/atk/def/spa/spd/spe)")
            base = base_stats_for(config.get("species")) if config.get("species") else None
            if base is None:
                print("            stats will be computed at send-out, once the level is known.")
            else:
                for level in (40,):
                    spread = derive_stats(base, level, config["nature"], config["ivs"],
                                          config.get("evs", 0))
                    print(f"            at Lv{level}: {_fmt_spread(spread)}")

    class BattleMarkCommand(gdb.Command):
        """battlemark <label> — drop a labelled marker into the log at this point."""

        def __init__(self):
            super().__init__("battlemark", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None:
                print("[battlelog] not recording — run battlelog first.")
                return
            label = arg.strip() or "mark"
            _rec.add_mark(label)
            print(f"[battlelog] marked {label!r} at record {len(_rec.records)}")

    class BattleStatusCommand(gdb.Command):
        """battlestatus — what has been captured so far."""

        def __init__(self):
            super().__init__("battlestatus", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None:
                print("[battlelog] not recording.")
                return
            kinds = {}
            for record in _rec.records:
                key = next(iter(record))
                kinds[key] = kinds.get(key, 0) + 1
            seed = "none" if _rec.forced_seed is None else f"{_rec.forced_seed:#010x}"
            print(f"[battlelog] label={_rec.label} forced_seed={seed} "
                  f"stopped={_rec.stopped}")
            print(f"            {kinds or 'nothing captured yet'}")
            hp = ", ".join(f"battler {b}: {v[0]}/{v[1]}" for b, v in sorted(_rec.hp_seen.items()))
            print(f"            HP: {hp or 'not tracked'}")
            dead = [k for k, v in _HOOKS.items() if v != "live"]
            if dead:
                print(f"            NOT HOOKED: {', '.join(dead)}")

    class BattleSaveCommand(gdb.Command):
        """battlesave [path] — flush the recording to jsonl and stop recording."""

        def __init__(self):
            super().__init__("battlesave", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global _rec
            if _rec is None:
                print("[battlelog] nothing to save.")
                return
            path = write_recording(_rec, arg.strip() or None)
            print(f"[battlelog] wrote {_rec.roll_count} rolls / {len(_rec.records)} records "
                  f"to {path}")
            print("[battlelog] analyse with: "
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

    _install("battle start", BattleSetupNewBreakpoint)
    _install("RNG rolls", _RandomBreakpoint)
    _install("target override", _GetBattleMonBreakpoint)
    # Both public entry points that expand a BattleMessage into battleSystem->msgBuffer; the
    # expansion itself is static, so it is not a reliable symbol to break on.
    _messages = [_install(f"messages ({sym})", lambda s=sym: _MsgBreakpoint(s))
                 for sym in ("BattleSystem_PrintBattleMessage", "ov12_0223C4E8")]

    BattleLogCommand()
    BattleOverrideCommand()
    BattleMarkCommand()
    BattleStatusCommand()
    BattleSaveCommand()
    for _what, _state in _HOOKS.items():
        print(f"[battlelog] {'  ok' if _state == 'live' else 'FAIL'}  {_what}: {_state}")
    if not any(v == "live" for k, v in _HOOKS.items() if k.startswith("messages")):
        print("[battlelog] WARNING: no message hook resolved, so the log will record rolls and "
              "HP but NOT battle messages -- and the messages are how you tell which action "
              "each turn was. Check the symbol names against this build before recording.")
    if _HOOKS.get("target override") != "live":
        print("[battlelog] WARNING: the target override is not installed; IVs and nature will "
              "be whatever the save state holds. If BattleSystem_GetBattleMon lives in an "
              "overlay, re-source this file once the battle overlay is loaded.")
    print("[battlelog] ready. Commands: battlelog [seed] [label], battleoverride, "
          "battlemark, battlestatus, battlesave")
    if OVERRIDE_TARGET:
        print(f"[battlelog] target override ON: {TARGET_OVERRIDE['nature']}, IVs "
              f"{_fmt_spread(TARGET_OVERRIDE['ivs'])} (hp/atk/def/spa/spd/spe). "
              f"battleoverride off to disable.")
