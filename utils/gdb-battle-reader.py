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
    (gdb) battlemark phase2         # optional: drop a labelled marker into the log
    (gdb) battlestatus              # what has been captured so far
    (gdb) battlesave                # flush to data/battle_logs/<name>.jsonl and stop

Sourcing only registers the commands and installs breakpoints; it records nothing until
`battlelog`.  Output is one JSON line per recorded battle, so repeated battles append.

Analyse the result with `claytonlib.battle.logcheck`, which is pure Python and tested --
everything in this file needs a live emulator, so as little logic as possible lives here.
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
                msgbuf = _eval_int(f"*(unsigned int *)({self.battle_system_ptr:#x} + 0x18)")
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

    BattleSetupNewBreakpoint()
    _RandomBreakpoint()
    for _symbol in ("BattleSystem_SetCurrentMessage", "BattleMessage_Print"):
        try:
            _MsgBreakpoint(_symbol)
        except Exception:
            # Message symbols vary by build; a missing one is not fatal, rolls still record.
            pass
    BattleLogCommand()
    BattleMarkCommand()
    BattleStatusCommand()
    BattleSaveCommand()
    print("[battlelog] ready. Commands: battlelog [seed] [label], battlemark, "
          "battlestatus, battlesave")
