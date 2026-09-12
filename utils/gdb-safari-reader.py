#!/usr/bin/env python
"""
gdb-safari-reader.py - Sourced inside GDB to collect ground-truth SAFARI ZONE
battle data for verifying claytonlib/compass (safari path generation).

The Safari analog of utils/gdb-seed-reader.py, sharing its PROVEN, game-wide
machinery verbatim -- register-hijack seed injection at BattleSystem_Random+8,
RNG-roll capture, and battle-message decoding -- because safari encounters are
ordinary battles (BattleSetup_New / BattleSystem_Random / the message printer).
Only three things are safari-specific:

  1. Each seed line carries an action script (Bait / Mud / Ball); at the "What
     will <name> throw?" prompt we send the matching key sequence to the presser
     (Ball=s,space  Mud=s,d,space  Bait=s,a,space).  Safari dialog auto-advances,
     so there is NO auto-space.
  2. The end is pokemon fled / captured / out of Safari Balls.
  3. The compass path is reverse-engineered straight from the messages
     (safari_reader.messages_to_path), using the strings in compass/_display.py.

The pure, unit-tested logic lives in utils/safari_reader.py; this file is the
GDB + presser I/O shell.

Usage (inside GDB, AFTER `target remote ...`):
    (gdb) source utils/gdb-safari-reader.py
    (gdb) safarislurper          # prompts for config, then runs the per-seed loop
Ctrl+C returns to the prompt with run state intact: `wrap_up` then `continue` to
stop after the current seed, or just `continue` to resume.

SPIKE: the breakpoint symbols/offsets are copied from the metronome reader (same
ROM).  If a symbol name or the msgbuf offset differs for your build, adjust here.
"""
import json
import os
import sys
import time
import urllib.request

# GDB is only present when sourced inside GDB; guard so the shell stays importable.
# (Running standalone from utils/, a bare `import gdb` can grab the project's utils/gdb.py by
# name; the real GDB module exposes `Command`, so we test for that rather than trust the import.)
try:
    import gdb
    _IN_GDB = hasattr(gdb, "Command")
except Exception:
    _IN_GDB = False
if not _IN_GDB:
    gdb = None

# Import the pure, tested helpers (this script lives in utils/, next to them).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir()
                else "utils")
import safari_reader as sr  # noqa: E402

OUTPUT_DIR = "safari_seeds"            # results live here, not the project root
DEFAULT_PRESSER_PORT = 62628           # matches utils/f3_presser.py PORT
MAX_ROLLS_PER_SEED = 5000              # stuck-battle guard
PRESSER_FAIL_LIMIT = 3                 # abort after N consecutive presser failures


# Safari battle messages -- single source of truth in safari_reader (shared with the validator).
SAFARI_MSGS = sr.SAFARI_MESSAGES


# ---------------------------------------------------------------------------
# Copied from gdb.py / gdb-seed-reader.py: HG/SS English charmap + string decoder.
# ---------------------------------------------------------------------------
_POKE_CHARMAP = {}
for _i in range(10):
    _POKE_CHARMAP[289 + _i] = str(_i)       # '0'-'9'
for _i in range(26):
    _POKE_CHARMAP[299 + _i] = chr(65 + _i)  # 'A'-'Z'
    _POKE_CHARMAP[325 + _i] = chr(97 + _i)  # 'a'-'z'
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
    """Read a String* at ptr and decode to Python str using the HG/SS English charmap."""
    inferior = gdb.inferiors()[0]
    chars = []
    offset = 8  # data[] starts at byte 8
    while True:
        code = int.from_bytes(bytes(inferior.read_memory(ptr + offset, 2)), 'little')
        if code == 0xFFFF:        # EOS
            break
        if code == 0xE000:        # CHAR_LF
            chars.append('\n')
            offset += 2
            continue
        if code == 0xFFFE:        # EXT_CTRL_CODE_BEGIN
            hdr = bytes(inferior.read_memory(ptr + offset + 2, 4))
            ctrl_type = int.from_bytes(hdr[0:2], 'little')
            field_cnt = int.from_bytes(hdr[2:4], 'little')
            if ctrl_type == 0x207:
                chars.append('\n[SCROLL]\n')
            elif ctrl_type == 0x208:
                chars.append('[WAIT]')
            elif ctrl_type & 0xFF00 in (0x100, 0x300, 0x400, 0x3400):
                chars.append(f'[VAR:{ctrl_type:#06x}]')
            offset += (3 + field_cnt) * 2
            continue
        chars.append(_POKE_CHARMAP.get(code, f'[{code:#05x}]'))
        offset += 2
    return ''.join(chars)


# ---------------------------------------------------------------------------
# f3_presser client (adds queued key sequences for safari actions)
# ---------------------------------------------------------------------------
class PresserError(Exception):
    pass


def presser_get(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise PresserError(f"{url}: {e}")


def presser_ping(base_url):
    if presser_get(f"{base_url}/ping").get("status") != "ok":
        raise PresserError("unexpected /ping response")


def presser_press_fkey(base_url, n):
    presser_get(f"{base_url}/press/f{n}")


def presser_keys(base_url, names):
    """Enqueue a key sequence (e.g. ['s','a','space']) via /keys/<s+a+space>."""
    presser_get(f"{base_url}/keys/{'+'.join(names)}")


# ---------------------------------------------------------------------------
# Config + collection
# ---------------------------------------------------------------------------
class Config:
    def __init__(self, seed_file, presser_url, reload_fkey, target_name,
                 msgmap=SAFARI_MSGS):
        self.seed_file = seed_file
        self.presser_url = presser_url.rstrip("/")
        self.reload_fkey = reload_fkey       # e.g. 3 for F3
        self.target_name = target_name       # the safari pokemon, for the filename
        self.msgmap = msgmap

    def output_filename(self):
        return os.path.join(OUTPUT_DIR, f"safari_{self.target_name}.jsonl")


class Collector:
    """Accumulates rolls + messages for one seed and drives the safari actions.

    The action decisions live in the (unit-tested) safari_reader.ActionDriver: it fires the
    next scripted action at each "What will ... throw?" prompt and ends on a terminal message
    (capture / flee / out-of-balls) -- recognizing ONLY those, never parsing action outcomes or
    counting rolls, so a mismatched outcome message can't deadlock the run.  The path is parsed
    afterward, from the gathered messages.  This Collector is just the GDB<->presser wiring.
    """

    def __init__(self, config):
        self.config = config
        self.reset([])

    def reset(self, actions):
        self.results = []
        self.driver = sr.ActionDriver(actions, self.config.msgmap)
        self.battle_over = False
        self.end_reason = None

    def _end(self, reason):
        self.battle_over = True
        self.end_reason = reason

    def add_roll(self, addr, func, val):
        self.results.append({"addr": addr, "func": func, "val": val})
        if not self.battle_over and len(self.results) > MAX_ROLLS_PER_SEED:
            self._end("stuck")

    def add_message(self, text):
        self.results.append({"msg": text})
        outcome = self.driver.on_message(text)
        if outcome is None:
            return
        kind, payload = outcome
        if kind == "end":
            self._end(payload)
        elif kind == "keys":
            presser_keys(self.config.presser_url, payload)

    def path(self):
        return sr.messages_to_path(self.results, self.config.msgmap)[0]


def _write_result(fh, seed, actions, collector):
    line = json.dumps({"seed": f"{seed:#010x}",
                       "actions": "".join(actions),
                       "end_reason": collector.end_reason,
                       "path": collector.path(),
                       "results": collector.results}, separators=(",", ":"))
    fh.write(line + "\n")
    fh.flush()
    return line


# ---------------------------------------------------------------------------
# Live console feedback
# ---------------------------------------------------------------------------
_mid_roll_line = False


def _echo_roll():
    global _mid_roll_line
    sys.stdout.write("<roll>")
    sys.stdout.flush()
    _mid_roll_line = True


def _close_roll_line():
    global _mid_roll_line
    if _mid_roll_line:
        sys.stdout.write("\n")
        sys.stdout.flush()
        _mid_roll_line = False


def _echo_message(msg):
    _close_roll_line()
    literal = msg.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    print(f"> {literal}")


def _wait_ready(seconds=5):
    try:
        input(f"Press Enter, then focus the emulator window within {seconds}s...")
    except EOFError:
        pass
    for r in range(seconds, 0, -1):
        print(f"  starting in {r}...")
        time.sleep(1)


# ---------------------------------------------------------------------------
# Run state + driver (GDB `continue` + breakpoint reactions; no Python loop)
# ---------------------------------------------------------------------------
_run = None
_seed_override = None

_MULT = 1103515245
_INC = 24691
_HIJACK_POST_LOAD_OFF = 8   # PC just after `ldr r3, [r0, r2]` in BattleSystem_Random
_hijack_bp = None


def _advance_rng(state):
    return (state * _MULT + _INC) & 0xFFFFFFFF


def _battle_random_base():
    """Entry address of BattleSystem_Random (Thumb bit cleared)."""
    return int(gdb.parse_and_eval("(unsigned)&BattleSystem_Random")) & ~1 & 0xFFFFFFFF


class RunState:
    """Persistent state for a safarislurper run; survives Ctrl+C so `continue`
    (after `wrap_up`) resumes exactly where we left off.  `rows` = [(seed, actions), ...]."""

    def __init__(self, config, rows, fh):
        self.config = config
        self.rows = rows
        self.fh = fh
        self.idx = 0
        self.completed = 0
        self.presser_fails = 0
        self.wrap_up = False
        self.done = False
        self.collector = Collector(config)


def _start_seed(run):
    """Point state at rows[idx]: set override, reset collector w/ its actions, reload."""
    global _seed_override
    seed, actions = run.rows[run.idx]
    _seed_override = seed
    run.collector.reset(actions)
    try:
        presser_press_fkey(run.config.presser_url, run.config.reload_fkey)
        run.presser_fails = 0
        return True
    except PresserError as e:
        run.presser_fails += 1
        print(f"[safarislurper] presser failure "
              f"{run.presser_fails}/{PRESSER_FAIL_LIMIT}: {e}")
        return False


def _advance_to_next_seed(run):
    while True:
        run.idx += 1
        if run.idx >= len(run.rows):
            return False
        if _start_seed(run):
            return True
        if run.presser_fails >= PRESSER_FAIL_LIMIT:
            return False


def _finish_run(run, reason):
    global _seed_override
    run.done = True
    _seed_override = None
    try:
        run.fh.close()
    except Exception:
        pass
    _close_roll_line()
    print(f"[safarislurper] finished ({reason}). "
          f"{run.completed}/{len(run.rows)} seeds recorded.")


def _handle_battle_end(run):
    _close_roll_line()
    seed, actions = run.rows[run.idx]
    _write_result(run.fh, seed, actions, run.collector)
    run.completed += 1
    print(f"[safarislurper] {seed:#010x}: {run.collector.end_reason} "
          f"-> {run.collector.path()} "
          f"[{run.completed}/{len(run.rows)}]")
    if run.wrap_up:
        _finish_run(run, "wrap_up")
        return True
    if not _advance_to_next_seed(run):
        _finish_run(run, "presser_abort"
                    if run.presser_fails >= PRESSER_FAIL_LIMIT else "complete")
        return True
    return False


def _maybe_end(run):
    if run is None or run.done or not run.collector.battle_over:
        return False
    return _handle_battle_end(run)


def run_safarislurper(host=None):
    global _run
    seed_file = input("Seed file (seed + action script per line): ").strip()
    if host is None:
        host = input("f3_presser host/IP: ").strip()
    port = input(f"f3_presser port [{DEFAULT_PRESSER_PORT}]: ").strip() or str(DEFAULT_PRESSER_PORT)
    fkey = int(input("Reload F-key number [3]: ").strip() or "3")
    name = input("Safari pokemon name (for the output file) [metang]: ").strip() or "metang"
    config = Config(seed_file, f"http://{host}:{port}", fkey, name)

    rows = sr.load_safari_seeds(config.seed_file)
    out_path = config.output_filename()
    print(f"[safarislurper] {len(rows)} seed(s); output -> {out_path}")
    try:
        presser_ping(config.presser_url)
    except PresserError as e:
        print(f"[safarislurper] ABORT: f3_presser unreachable ({e}). 0 seeds done.")
        return
    if not rows:
        print("[safarislurper] no seeds to run.")
        return

    _wait_ready()
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    _run = RunState(config, rows, open(out_path, "a"))

    while not _start_seed(_run):
        if _run.presser_fails >= PRESSER_FAIL_LIMIT:
            _finish_run(_run, "presser_abort")
            return
        _run.idx += 1
        if _run.idx >= len(rows):
            _finish_run(_run, "complete")
            return

    gdb.execute("continue")   # breakpoints drive seed-to-seed and stop when finished


if _IN_GDB:

    class _SeedHijackBreakpoint(gdb.Breakpoint):
        """At BattleSystem_Random+8 (just after the seed load) overwrite r3 with the override
        seed, so the game's own store writes advance_rng(seed) coherently (the emulator's stub
        corrupts direct memory writes).  Armed for a battle's first random call; self-disables."""

        def __init__(self, addr):
            super().__init__(f"*{addr}", internal=True)
            self.silent = True
            self.enabled = False

        def stop(self):
            if _run is None or _run.done or _seed_override is None:
                self.enabled = False
                return False
            if not gdb.convenience_variable("new_seed"):
                return False
            gdb.set_convenience_variable("new_seed", False)
            self.enabled = False
            seed = _seed_override & 0xFFFFFFFF
            r0 = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
            r2 = int(gdb.parse_and_eval("$r2")) & 0xFFFFFFFF
            loaded = int(gdb.parse_and_eval("$r3")) & 0xFFFFFFFF
            mem = int.from_bytes(
                bytes(gdb.inferiors()[0].read_memory((r0 + r2) & 0xFFFFFFFF, 4)), "little")
            if loaded != mem:
                _close_roll_line()
                print(f"[safarislurper] ABORT: seed-hijack sanity check failed at "
                      f"BattleSystem_Random+{_HIJACK_POST_LOAD_OFF} "
                      f"(r3={loaded:#010x} != rand={mem:#010x}). Wrong ROM/layout.")
                _finish_run(_run, "hijack_layout_error")
                return True
            gdb.execute(f"set $r3 = {seed}")
            return False

    def _ensure_hijack_bp():
        global _hijack_bp
        if _hijack_bp is None:
            _hijack_bp = _SeedHijackBreakpoint(
                _battle_random_base() + _HIJACK_POST_LOAD_OFF)
        return _hijack_bp

    class BattleSetupNewBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("BattleSetup_New")
            self.silent = True

        def stop(self):
            gdb.set_convenience_variable("new_seed", True)
            if _seed_override is not None:
                _ensure_hijack_bp().enabled = True
            return False

    class RandomFinish(gdb.FinishBreakpoint):
        """On BattleSystem_Random return: record caller addr/func and the r0 roll value."""

        def __init__(self, frame):
            super().__init__(frame, internal=True)
            self.silent = True

        def stop(self):
            run = _run
            if run is None or run.done:
                return False
            frame = gdb.selected_frame()
            pc = frame.pc()
            func_name = frame.name() or "??"
            r0 = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
            run.collector.add_roll(f"0x{pc:08x}", func_name, r0)
            _echo_roll()
            return _maybe_end(run)

    class RandomBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("BattleSystem_Random")
            self.silent = True

        def stop(self):
            if _run is None or _run.done:
                return False
            RandomFinish(gdb.selected_frame())   # +8 hijack handles seed injection
            return False

    class MsgFinish(gdb.FinishBreakpoint):
        def __init__(self, frame, battleSystem_ptr):
            super().__init__(frame, internal=True)
            self.silent = True
            self.battleSystem_ptr = battleSystem_ptr

        def stop(self):
            run = _run
            if run is None or run.done:
                return False
            try:
                msgbuf_ptr = int(gdb.parse_and_eval(
                    f"*(unsigned int *)({self.battleSystem_ptr:#x} + 0x18)")) & 0xFFFFFFFF
                if msgbuf_ptr:
                    text = _decode_poke_string(msgbuf_ptr)
                    run.collector.add_message(text)
                    _echo_message(text)
            except Exception as e:
                print(f"[safarislurper] msg decode error: {e}")
                return False
            return _maybe_end(run)

    class _MsgBreakpoint(gdb.Breakpoint):
        def __init__(self, symbol):
            super().__init__(symbol)
            self.silent = True

        def stop(self):
            if _run is None or _run.done:
                return False
            battleSystem_ptr = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
            MsgFinish(gdb.selected_frame(), battleSystem_ptr)
            return False

    class SafariSlurperCommand(gdb.Command):
        """`safarislurper [HOST]` -- prompt for config, then replay each seed and record.

Run AFTER attaching to the emulator (target remote ...).  Ctrl+C returns here with run state
intact: `wrap_up` then `continue` to stop after the current seed, or `continue` to resume."""

        def __init__(self):
            super().__init__("safarislurper", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            host = arg.strip() or None
            try:
                run_safarislurper(host)
            except KeyboardInterrupt:
                print("\n[safarislurper] interrupted. 'wrap_up' to stop after the "
                      "current seed, or 'continue' to resume.")

    class WrapUpCommand(gdb.Command):
        """Finish the current seed, then stop (don't advance to remaining seeds)."""

        def __init__(self):
            super().__init__("wrap_up", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _run is None or _run.done:
                print("[safarislurper] no active run to wrap up.")
                return
            _run.wrap_up = True
            print("[safarislurper] wrap_up set; will stop after the current seed. "
                  "Type 'continue'.")

    BattleSetupNewBreakpoint()
    RandomBreakpoint()
    _MsgBreakpoint("BattleSystem_PrintBattleMessage")
    _MsgBreakpoint("ov12_0223C4E8")
    SafariSlurperCommand()
    WrapUpCommand()
    print("gdb-safari-reader loaded. Attach the emulator, then run 'safarislurper'.")
