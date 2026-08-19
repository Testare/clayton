#!/usr/bin/env python
"""
gdb-seed-reader.py - Sourced inside GDB to collect ground-truth battle data for
verifying claytonlib/metronome_compass.

Based on utils/gdb.py, but standalone: the shared helpers (charmap +
_decode_poke_string) are COPIED here on purpose so this file is independent and
gdb.py is left untouched (see plan clayton-i32, gotcha G7).

Usage (inside GDB, AFTER attaching to the emulator, e.g. `target remote ...`):

    (gdb) source utils/gdb-seed-reader.py
    (gdb) seedslurper          # prompts for config, then runs the per-seed loop

Sourcing only REGISTERS the `seedslurper` and `wrap_up` commands and installs the
breakpoints; it does no prompting and starts no loop (the debugger must be
attached first).

For each hex seed in the seed file, the loop:
  * sets a seed override injected at BattleSetup_New (like gdb.py's seed_override),
  * curls the f3_presser to reload the battle save state (F-key),
  * continues while breakpoints silently ACCUMULATE rolls + battle messages,
  * stops on a battle-end condition,
  * appends one compact JSON line {"seed":..., "results":[...]} to a .jsonl file.

`results` is an ordered, interleaved list of roll objects
{"addr","func","val"} and message objects {"msg"} (plan gotcha G8).
"""

import json
import os
import sys
import time
import urllib.request

# GDB is only present when this file is actually sourced inside GDB. Guard the
# import so the pure helpers below remain importable/testable outside GDB.
try:
    import gdb
    _IN_GDB = True
except ImportError:  # pragma: no cover - only when run outside GDB
    gdb = None
    _IN_GDB = False


# ---------------------------------------------------------------------------
# Copied from gdb.py: Pokemon HeartGold English charmap + string decoder.
# ---------------------------------------------------------------------------
_MOVES_JSON_PATH = os.path.join(os.getcwd(), "claytonlib", "basedata", "moves.json")

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
    """Read a String* at ptr and decode to Python str using HG/SS English charmap.

    String layout (pm_string.h): u16 maxsize [+0], u16 size [+2], u32 magic [+4],
    u16 data[] [+8]. Control code format: 0xFFFE, <type u16>, <field_count u16>,
    [fields...].
    """
    inferior = gdb.inferiors()[0]
    chars = []
    offset = 8  # data[] starts at byte 8
    while True:
        raw = bytes(inferior.read_memory(ptr + offset, 2))
        code = int.from_bytes(raw, 'little')
        if code == 0xFFFF:   # EOS
            break
        if code == 0xE000:   # CHAR_LF — newline
            chars.append('\n')
            offset += 2
            continue
        if code == 0xFFFE:   # EXT_CTRL_CODE_BEGIN
            hdr = bytes(inferior.read_memory(ptr + offset + 2, 4))
            ctrl_type = int.from_bytes(hdr[0:2], 'little')
            field_cnt = int.from_bytes(hdr[2:4], 'little')
            if ctrl_type == 0x207:
                chars.append('\n[SCROLL]\n')
            elif ctrl_type == 0x208:
                chars.append('[WAIT]')
            elif ctrl_type & 0xFF00 in (0x100, 0x300, 0x400, 0x3400):
                chars.append(f'[VAR:{ctrl_type:#06x}]')
            # else: color/formatting codes — skip silently
            offset += (3 + field_cnt) * 2
            continue
        chars.append(_POKE_CHARMAP.get(code, f'[{code:#05x}]'))
        offset += 2
    return ''.join(chars)


# ---------------------------------------------------------------------------
# Pure helpers (testable outside GDB): config, filenames, seed parsing.
# ---------------------------------------------------------------------------
VALID_MOVESETS = ("test", "P0")
OUTPUT_DIR = "metronome_seeds"    # results live here, not the project root


def parse_seed_line(line):
    """Parse one line of the seed file into an int, or return None to skip.

    Accepts hex with or without a 0x prefix. Blank lines and lines starting
    with '#' are skipped (return None).
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    return int(s, 16) & 0xFFFFFFFF


def load_seeds(path):
    """Read a seed file (one hex seed per line) into a list of ints."""
    seeds = []
    with open(path) as f:
        for line in f:
            seed = parse_seed_line(line)
            if seed is not None:
                seeds.append(seed)
    return seeds


def build_output_filename(name, moveset, level, magikarp_level, gender):
    """metronome_seeds_<name>_<moveset>_<level>_vs_<mklvl>_<g>.jsonl"""
    g = gender.strip().lower()[:1]  # 'm' or 'f'
    return (f"metronome_seeds_{name}_{moveset}_{level}"
            f"_vs_{magikarp_level}_{g}.jsonl")


class Config:
    """Run configuration gathered from prompts when `seedslurper` is invoked."""

    def __init__(self, magikarp_level, magikarp_gender, user_name, moveset,
                 user_level, presser_url, reload_fkey, seed_file,
                 prompt_limit=7):
        self.magikarp_level = magikarp_level
        self.magikarp_gender = magikarp_gender
        self.user_name = user_name
        self.moveset = moveset
        self.user_level = user_level
        self.presser_url = presser_url.rstrip("/")
        self.reload_fkey = reload_fkey            # e.g. 3 for F3
        self.seed_file = seed_file
        self.prompt_limit = prompt_limit          # 7 prompts => 6 completed turns

    def output_filename(self):
        return os.path.join(OUTPUT_DIR, build_output_filename(
            self.user_name, self.moveset, self.user_level,
            self.magikarp_level, self.magikarp_gender))


def _prompt(label, default=None, required=False, choices=None, cast=str):
    """Prompt until a valid value is entered. `default` used on empty input."""
    while True:
        suffix = f" [{default}]" if default is not None else ""
        choice_str = f" ({'/'.join(choices)})" if choices else ""
        raw = input(f"{label}{choice_str}{suffix}: ").strip()
        if not raw:
            if default is not None:
                raw = str(default)
            elif required:
                print("  A value is required.")
                continue
        if choices and raw not in choices:
            print(f"  Must be one of: {', '.join(choices)}")
            continue
        try:
            return cast(raw)
        except ValueError:
            print(f"  Invalid value: {raw!r}")


def _prompt_gender():
    while True:
        raw = input("Magikarp gender (m/f): ").strip().lower()
        if raw in ("m", "male"):
            return "m"
        if raw in ("f", "female"):
            return "f"
        print("  Enter m or f.")


def _prompt_fkey():
    while True:
        raw = input("Which F-key reloads the save state? (1-8): ").strip().lower()
        if raw.startswith("f"):
            raw = raw[1:]
        if raw.isdigit() and 1 <= int(raw) <= 8:
            return int(raw)
        print("  Enter a number 1-8 (or f1..f8).")


def gather_config():
    """Interactively gather run config (invoked from the seedslurper command)."""
    magikarp_level = _prompt("Magikarp level", required=True, cast=int)
    magikarp_gender = _prompt_gender()
    user_name = _prompt("Metronome user name", default="Metroman2")
    moveset = _prompt("Metronome user moveset", default="test",
                      choices=VALID_MOVESETS)
    user_level = _prompt("Metronome user level", default=7, cast=int)
    presser_url = _prompt("f3_presser URL (e.g. http://192.168.1.50:62628)",
                          required=True)
    reload_fkey = _prompt_fkey()
    seed_file = _prompt("Seed file path", required=True)
    return Config(magikarp_level, magikarp_gender, user_name, moveset,
                  user_level, presser_url, reload_fkey, seed_file)


# ---------------------------------------------------------------------------
# f3_presser client
# ---------------------------------------------------------------------------
class PresserError(Exception):
    pass


def presser_get(url, timeout=5):
    """GET a presser endpoint, returning parsed JSON. Raises PresserError."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # urllib/timeout/json
        raise PresserError(f"{url}: {e}")


def presser_ping(base_url):
    data = presser_get(f"{base_url}/ping")
    if data.get("status") != "ok":
        raise PresserError(f"unexpected /ping response: {data!r}")


def presser_autospace(base_url, on):
    presser_get(f"{base_url}/autospace/{'on' if on else 'off'}")


def presser_press_fkey(base_url, n):
    presser_get(f"{base_url}/press/f{n}")


# ---------------------------------------------------------------------------
# Collection state + end-condition detection
#
# The exact message substrings and the U-turn/Baton-Pass switch trigger are
# unknown until the message-inventory spike (clayton-i32.6) and the end-to-end
# spike (clayton-i32.10) are run on the emulator. They are collected here as
# tunable constants so they can be corrected once observed.
# ---------------------------------------------------------------------------
# Confirmed on the emulator (spike clayton-i32.6). Decoded messages contain real
# newlines (CHAR_LF -> '\n'), so substrings spanning a line break include '\n'.
INPUT_PROMPT_SUBSTR = "What will"            # 'What will Metroman2 do?'
FAINT_SUBSTR = "fainted"                     # 'Metroman2 fainted!' / 'The wild MAGIKARP fainted!'
# U-turn shows '... went back\nto <trainer>!'. Baton Pass emits no 'went back'
# message, so match 'Baton Pass!' directly; it has no accuracy check and can't
# fail, so its use always switches the metronome user out.
SWITCH_OUT_SUBSTRS = ("went back\nto", "Baton Pass!")
# Metronome user rolled Whirlwind/Roar -> wild Magikarp forced out. 100% accuracy
# and no evasion supported, so the 'used' message reliably marks the end.
FORCE_OUT_SUBSTRS = ("Whirlwind!", "Roar!")


class Collector:
    """Accumulates rolls + messages for the current seed and detects end."""

    def __init__(self, config):
        self.config = config
        self.results = []          # ordered, interleaved roll/message dicts
        self.prompt_count = 0
        self.activity_since_prompt = False  # a roll seen since last counted prompt
        self.battle_over = False
        self.end_reason = None

    def reset(self):
        self.results = []
        self.prompt_count = 0
        self.activity_since_prompt = False
        self.battle_over = False
        self.end_reason = None

    def add_roll(self, addr, func, val):
        self.results.append({"addr": addr, "func": func, "val": val})
        self.activity_since_prompt = True

    def add_message(self, msg):
        self.results.append({"msg": msg})
        self._check_end_message(msg)

    def _end(self, reason):
        self.battle_over = True
        self.end_reason = reason

    def _check_end_message(self, msg):
        user = self.config.user_name
        # (1) input prompt: N prompts => (N-1) completed turns. The prompt is
        # drawn twice per turn, so only count it once by requiring a roll to
        # have occurred since the last counted prompt.
        if INPUT_PROMPT_SUBSTR in msg and "?" in msg:
            if self.prompt_count == 0 or self.activity_since_prompt:
                self.prompt_count += 1
                self.activity_since_prompt = False
                if self.prompt_count >= self.config.prompt_limit:
                    self._end("prompt_limit")
            return
        # (2)/(3) faints — user vs Magikarp distinguished by the user's name
        if FAINT_SUBSTR in msg:
            self._end("user_fainted" if user in msg else "magikarp_fainted")
            return
        # (4) user switched out (U-turn / Baton Pass)
        if any(s in msg for s in SWITCH_OUT_SUBSTRS):
            self._end("user_switched_out")
            return
        # (5) Magikarp forced out (Whirlwind / Roar)
        if any(s in msg for s in FORCE_OUT_SUBSTRS):
            self._end("magikarp_forced_out")


# ---------------------------------------------------------------------------
# Run state + driver.
#
# There is NO Python continue-loop. Like utils/gdb.py, the engine is gdb's own
# `continue` plus breakpoint reactions: when a battle ends, the breakpoint
# handler writes the result, points the override at the next seed, and curls the
# reload — then returns False to continue straight into the next battle (or True
# to stop when the run is finished). _run persists across Ctrl+C, so after an
# interrupt a plain `continue` (optionally preceded by `wrap_up`) resumes.
# ---------------------------------------------------------------------------
MAX_ROLLS_PER_SEED = 5000    # stuck-battle guard: force-end a runaway battle
PRESSER_FAIL_LIMIT = 3       # abort after N consecutive presser failures

_run = None
_seed_override = None
_last_pc = None


def _write_result(fh, seed, results):
    """Append one compact JSON line and return it (so callers can echo it)."""
    line = json.dumps({"seed": f"{seed:#010x}", "results": results},
                      separators=(",", ":"))
    fh.write(line + "\n")
    fh.flush()
    return line


def _wait_ready(seconds=5):
    """Give the operator time to focus the emulator before the first reload."""
    try:
        input("Focus the emulator window, then press Enter to begin...")
    except EOFError:
        pass
    for r in range(seconds, 0, -1):
        print(f"  starting in {r}...")
        time.sleep(1)


class RunState:
    """Persistent state for a seedslurper run; survives Ctrl+C so a plain
    `continue` (after `wrap_up`) resumes exactly where we left off."""

    def __init__(self, config, seeds, fh):
        self.config = config
        self.seeds = seeds
        self.fh = fh
        self.idx = 0
        self.completed = 0
        self.presser_fails = 0
        self.wrap_up = False
        self.done = False
        self.collector = Collector(config)


def _start_seed(run):
    """Point state at seeds[run.idx]: set override, reset collector, curl reload.
    Returns True on success; on presser failure returns False (fails counted)."""
    global _seed_override
    _seed_override = run.seeds[run.idx]
    run.collector.reset()
    try:
        presser_press_fkey(run.config.presser_url, run.config.reload_fkey)
        run.presser_fails = 0
        return True
    except PresserError as e:
        run.presser_fails += 1
        print(f"[seedslurper] presser failure "
              f"{run.presser_fails}/{PRESSER_FAIL_LIMIT}: {e}")
        return False


def _advance_to_next_seed(run):
    """Move to and start the next runnable seed. Returns True if one started
    (continue into it), False if the run should finish."""
    while True:
        run.idx += 1
        if run.idx >= len(run.seeds):
            return False
        if _start_seed(run):
            return True
        if run.presser_fails >= PRESSER_FAIL_LIMIT:
            return False  # caller finishes with presser_abort


def _finish_run(run, reason):
    global _seed_override
    run.done = True
    _seed_override = None
    try:
        presser_autospace(run.config.presser_url, False)
    except PresserError:
        pass
    try:
        run.fh.close()
    except Exception:
        pass
    print(f"[seedslurper] finished ({reason}). "
          f"{run.completed}/{len(run.seeds)} seeds recorded.")


def _handle_battle_end(run):
    """Called from a breakpoint once collector.battle_over is set. Records the
    current seed, then advances or finishes. Returns True if gdb should STOP
    (run finished), False to continue straight into the next battle."""
    seed = run.seeds[run.idx]
    line = _write_result(run.fh, seed, run.collector.results)
    run.completed += 1
    print(f"[seedslurper] {seed:#010x}: {run.collector.end_reason} "
          f"({len(run.collector.results)} entries) "
          f"[{run.completed}/{len(run.seeds)}]")
    print(line)  # echo the JSON so progress history is visible

    if run.wrap_up:
        _finish_run(run, "wrap_up")
        return True
    if not _advance_to_next_seed(run):
        _finish_run(run, "presser_abort"
                    if run.presser_fails >= PRESSER_FAIL_LIMIT else "complete")
        return True
    return False  # next seed reloaded; keep going


def _maybe_end(run):
    """Tail for breakpoint stop() handlers: returns the bool to return from
    stop() (True stops gdb, False keeps continuing)."""
    if run is None or run.done or not run.collector.battle_over:
        return False
    return _handle_battle_end(run)


def run_seedslurper():
    """Bootstrap invoked by the `seedslurper` command: gather config, start the
    first seed, then hand off to gdb's `continue` + breakpoint state machine."""
    global _run
    config = gather_config()
    seeds = load_seeds(config.seed_file)
    out_path = config.output_filename()
    print(f"[seedslurper] {len(seeds)} seed(s); output -> {out_path}")

    try:
        presser_ping(config.presser_url)
    except PresserError as e:
        print(f"[seedslurper] ABORT: f3_presser unreachable ({e}). 0 seeds done.")
        return
    if not seeds:
        print("[seedslurper] no seeds to run.")
        return

    _wait_ready()
    presser_autospace(config.presser_url, True)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    _run = RunState(config, seeds, open(out_path, "a"))

    # Start the first runnable seed (skipping any that fail to reload).
    while not _start_seed(_run):
        if _run.presser_fails >= PRESSER_FAIL_LIMIT:
            _finish_run(_run, "presser_abort")
            return
        _run.idx += 1
        if _run.idx >= len(seeds):
            _finish_run(_run, "complete")
            return

    # Single continue; breakpoints drive seed-to-seed and stop when finished.
    gdb.execute("continue")


if _IN_GDB:

    class BattleSetupNewBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("BattleSetup_New")
            self.silent = True

        def stop(self):
            gdb.set_convenience_variable("new_seed", True)
            return False

    class RandomFinish(gdb.FinishBreakpoint):
        """On BattleSystem_Random return: record caller addr/func and r0 value."""

        def __init__(self, frame):
            super().__init__(frame, internal=True)
            self.silent = True

        def stop(self):
            global _last_pc
            run = _run
            if run is None or run.done:
                return False
            frame = gdb.selected_frame()
            pc = frame.pc()
            func_name = frame.name() or "??"
            _last_pc = pc
            r0 = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
            c = run.collector
            c.add_roll(f"0x{pc:08x}", func_name, r0)
            if not c.battle_over and len(c.results) > MAX_ROLLS_PER_SEED:
                c._end("stuck")
            return _maybe_end(run)

    class RandomBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("BattleSystem_Random")
            self.silent = True

        def stop(self):
            if _run is None or _run.done:
                return False
            if gdb.convenience_variable("new_seed") and _seed_override is not None:
                gdb.execute(f"set battleSystem->rand = {_seed_override}")
                gdb.set_convenience_variable("new_seed", False)
            RandomFinish(gdb.selected_frame())
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
                    f"*(unsigned int *)({self.battleSystem_ptr:#x} + 0x18)"
                )) & 0xFFFFFFFF
                if msgbuf_ptr:
                    run.collector.add_message(_decode_poke_string(msgbuf_ptr))
            except Exception as e:
                print(f"[seedslurper] msg decode error: {e}")
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

    class SeedSlurperCommand(gdb.Command):
        """Prompt for config, then replay each seed and record rolls + messages.

Run this AFTER attaching to the emulator (target remote ...). Ctrl+C returns to
this prompt with run state intact: run `wrap_up` to stop after the current seed,
or just `continue` to resume."""

        def __init__(self):
            super().__init__("seedslurper", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            try:
                run_seedslurper()
            except KeyboardInterrupt:
                print("\n[seedslurper] interrupted. Run 'wrap_up' to stop after "
                      "the current seed, or 'continue' to resume.")

    class WrapUpCommand(gdb.Command):
        """Finish the current seed, then stop (don't advance to remaining seeds).

Interrupt the running seedslurper with Ctrl+C to reach this prompt, run
`wrap_up`, then `continue` to let it wrap up cleanly."""

        def __init__(self):
            super().__init__("wrap_up", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _run is None or _run.done:
                print("[seedslurper] no active run to wrap up.")
                return
            _run.wrap_up = True
            print("[seedslurper] wrap_up: will stop after the current seed. "
                  "Type 'continue' to resume.")

    BattleSetupNewBreakpoint()
    RandomBreakpoint()
    _MsgBreakpoint("BattleSystem_PrintBattleMessage")
    _MsgBreakpoint("ov12_0223C4E8")
    SeedSlurperCommand()
    WrapUpCommand()
    print("gdb-seed-reader loaded. Attach the emulator, then run 'seedslurper'.")
