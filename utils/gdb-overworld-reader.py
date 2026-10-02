#!/usr/bin/env python
"""
gdb-overworld-reader.py — sourced inside GDB to record the OVERWORLD (Seed A) RNG stream and
every roamer encounter check, to settle whether one bit of one roll predicts a roamer encounter.

Sibling to gdb-battle-reader.py. That one records the BATTLE stream (`BattleSystem_Random`, a
per-battle seed on the battle struct); this one records the overworld stream
(`LCRandom`, the global `sLCRNG_State`) — which is the stream that decides encounters, Elm
calls, roamer relocation and PID/IVs.

What it is for
--------------
`getRandomActiveRoamerInCurrMap` (src/field/encounter_check.c) is the only gate on meeting a
roamer:

    if (nRoamers == 0)       return FALSE;
    if (LCRandRange(2) == 0) return FALSE;      # a 50/50 coin flip
    if (nRoamers > 1) chosen = LCRandRange(nRoamers);
    return TRUE;

so the prediction *ought* to be one bit of one roll. A believed figure from play experience is
1-in-4, which would make that wrong. This records what actually happens.

How it avoids the trap it would otherwise fall into
---------------------------------------------------
`LCRandRange` is `static inline`: it has no symbol, so the flip cannot be hooked directly. The
obvious alternative — hook `LCRandom` and symbolise the caller — is exactly what misled this
project before: gdb resolves a caller address to the nearest symbol, and that attributed six
verified battle-start advances to a function which makes no RNG call at all
(notes/battle_compass.md sec 16.2).

So this file **brackets** instead. It breaks on the entry and the return of
`getRandomActiveRoamerInCurrMap`, and every roll in between belongs to that call. No
symbolisation, nothing a neighbouring function can spoof. The number of rolls bracketed is
itself a measurement: 0 means no roamer was on the map, 1 means the flip alone decided it, and
2 would mean two roamers shared a map — which `RoamerLocationSetRandom` says is impossible,
since Raikou and Entei draw locations only from the Johto range and the Lati twin only from
Kanto.

`initRoamingWildmon` is hooked as an independent witness: it runs only on a roamer battle, so if
it ever disagrees with the check's return value then the recorder is wrong and nothing else in
the log can be trusted.

Usage (inside GDB, AFTER attaching to the emulator):

    (gdb) source utils/gdb-overworld-reader.py
    (gdb) owlog                     # start recording; reads the current seed
    (gdb) owlog 0x0C0E02CA          # ...and force that seed first
    ... walk onto the roamer's route and Sweet Scent / take steps ...
    (gdb) owpredict                 # frames from the recorded seed that should give a roamer
    (gdb) owstatus                  # what has been captured, and the verdict so far
    (gdb) owsave                    # flush to data/overworld_logs/<name>.jsonl and stop

A note on forcing the seed
--------------------------
gdb-seed-reader.py records that **memory writes are corrupted by this emulator's GDB stub** —
writing 0x082A8651 left memory holding 0x0A7D8651 — which is why the battle reader forces its
seed by overwriting a register mid-instruction instead. `sLCRNG_State` is plain memory, so the
same hazard applies here, and this file does NOT assume the write landed: it writes, reads back,
retries, and refuses to record under a seed it could not verify. Recording without forcing is
fully supported and is all the roamer test actually needs — forcing only buys reproducible frame
numbers across runs.

Analyse the result with `claytonlib.roamer_check`, which is pure Python and tested. Everything
here needs a live emulator, so as little logic as possible lives in this file.

Symbols this file breaks on, all verified present in utils/main.elf:
    LCRandom                        0x0201fd44
    getRandomActiveRoamerInCurrMap  0x02248360   (static, but in the symbol table)
    initRoamingWildmon              0x022482bc   (static)
    FieldSystem_PerformSweetScentEncounterCheck  0x02247170
and the object `sLCRNG_State` at 0x021d15a8.
"""

import json
import os
import sys
import time

try:
    import gdb
    _IN_GDB = True
except ImportError:                                     # importable for tests
    gdb = None
    _IN_GDB = False

OUTPUT_DIR = os.path.join("data", "overworld_logs")

#: A session can be long, but not unbounded; this only guards a runaway loop.
MAX_ROLLS = 200000

#: How many times to re-attempt a corrupted seed write before giving up.
SEED_WRITE_ATTEMPTS = 8


# ---------------------------------------------------------------------------
# Pure helpers (no gdb) -- kept here only because the recorder needs them inline.
# ---------------------------------------------------------------------------

_MULT = 1103515245
_INC = 24691


def advance(state):
    return (state * _MULT + _INC) & 0xFFFFFFFF


def roll_of(state):
    """What LCRandom() returns from `state`: advance, then the high 16 bits."""
    return advance(state) >> 16


def predicted_roamer(roll):
    """The claim under test: the roamer wins on an odd roll."""
    return (roll % 2) != 0


def output_path(label):
    name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (label or "run"))
    return os.path.join(OUTPUT_DIR, f"{name}.jsonl")


class Recording:
    """Rolls, roamer checks and markers for one session."""

    def __init__(self, label, forced_seed=None, start_state=None):
        self.label = label or "run"
        self.forced_seed = forced_seed
        self.start_state = start_state
        self.rolls = []            # every LCRandom() return value, in order
        self.checks = []           # one dict per roamer check
        self.markers = []
        self.stopped = False
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        #: Index into `rolls` where the currently-open roamer check began, or None.
        self._open_check = None
        #: Set by the initRoamingWildmon hook, consumed by the check's return hook.
        self._saw_roaming_init = False

    # -- rolls ----------------------------------------------------------

    def add_roll(self, value):
        if len(self.rolls) >= MAX_ROLLS:
            self.stopped = True
            return
        self.rolls.append(value & 0xFFFF)

    # -- roamer checks --------------------------------------------------

    def open_check(self):
        """Entry to getRandomActiveRoamerInCurrMap: remember where its rolls start."""
        self._open_check = len(self.rolls)
        self._saw_roaming_init = False

    def close_check(self, roamer):
        """Return from the check: everything rolled since entry belonged to it.

        `initRoamingWildmon` runs INSIDE the caller's roamer branch, after this returns, so the
        witness is recorded against the next close rather than this one -- see
        `note_roaming_init`, which back-fills the most recent check.
        """
        if self._open_check is None:
            return None
        rolls = self.rolls[self._open_check:]
        entry = {
            "first_roll_index": self._open_check if rolls else None,
            "rolls": list(rolls),
            "roamer": bool(roamer),
            "confirmed_roamer": None,
        }
        self._open_check = None
        self.checks.append(entry)
        return entry

    def note_roaming_init(self):
        """initRoamingWildmon fired, which only happens on a roamer battle."""
        if self.checks:
            self.checks[-1]["confirmed_roamer"] = True

    def note_normal_encounter(self):
        """The caller fell through to a normal encounter, so no roamer battle followed."""
        if self.checks and self.checks[-1]["confirmed_roamer"] is None:
            self.checks[-1]["confirmed_roamer"] = False

    def add_marker(self, text):
        self.markers.append({"at_roll": len(self.rolls), "text": text})

    # -- output ---------------------------------------------------------

    def to_doc(self):
        return {
            "label": self.label,
            "recorded_at": self.started_at,
            "forced_seed": None if self.forced_seed is None else f"{self.forced_seed:#010x}",
            "start_state": None if self.start_state is None else f"{self.start_state:#010x}",
            "rolls": list(self.rolls),
            "roamer_checks": list(self.checks),
            "markers": list(self.markers),
        }


_rec = None
_HOOKS = {}


if _IN_GDB:

    def _eval_int(expr):
        return int(gdb.parse_and_eval(expr)) & 0xFFFFFFFF

    def _read_seed():
        return _eval_int("sLCRNG_State")

    def _force_seed(value):
        """Write sLCRNG_State and verify it, retrying a corrupted write.

        Deliberately not trusted: gdb-seed-reader.py records that this stub corrupts memory
        writes, and a seed that silently did not land would mislabel every frame number in the
        recording. Returns the value actually in memory, which the caller must compare.
        """
        for attempt in range(1, SEED_WRITE_ATTEMPTS + 1):
            gdb.execute(f"set sLCRNG_State = {value & 0xFFFFFFFF}", to_string=True)
            got = _read_seed()
            if got == (value & 0xFFFFFFFF):
                if attempt > 1:
                    print(f"[owlog] seed write took on attempt {attempt}")
                return got
            print(f"[owlog] seed write attempt {attempt} was corrupted: "
                  f"wrote {value:#010x}, memory holds {got:#010x}")
        return _read_seed()

    class _RandomFinish(gdb.FinishBreakpoint):
        """Records LCRandom's return value, which is the roll the game saw."""

        def __init__(self, frame):
            super().__init__(frame, internal=True)
            self.silent = True

        def stop(self):
            if _rec is not None and not _rec.stopped:
                try:
                    _rec.add_roll(int(self.return_value) & 0xFFFF)
                except Exception:
                    # No return value available (tail call, or the frame vanished). Recording a
                    # roll we cannot read would shift every later index, so stop instead.
                    _rec.stopped = True
                    print("[owlog] STOPPED: could not read an LCRandom return value, so the "
                          "roll stream would be misaligned from here on.")
            return False

    class _RandomBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("LCRandom", internal=True)
            self.silent = True

        def stop(self):
            if _rec is not None and not _rec.stopped:
                try:
                    _RandomFinish(gdb.newest_frame())
                except Exception:
                    pass
            return False

    class _RoamerCheckFinish(gdb.FinishBreakpoint):
        """The return of getRandomActiveRoamerInCurrMap: TRUE means a roamer battle follows."""

        def __init__(self, frame):
            super().__init__(frame, internal=True)
            self.silent = True

        def stop(self):
            if _rec is None or _rec.stopped:
                return False
            try:
                roamer = bool(int(self.return_value))
            except Exception:
                print("[owlog] WARNING: a roamer check's return value was unreadable; that "
                      "check is recorded with roamer=False and should be discarded.")
                roamer = False
            entry = _rec.close_check(roamer)
            if entry is not None:
                flip = entry["rolls"][0] if entry["rolls"] else None
                if flip is None:
                    print("[owlog] roamer check: no roll spent -> no active roamer on this map")
                else:
                    agree = predicted_roamer(flip) == roamer
                    print(f"[owlog] roamer check: flip {flip} "
                          f"({'odd' if flip % 2 else 'even'}) -> predicted "
                          f"{'ROAMER' if predicted_roamer(flip) else 'normal'}, got "
                          f"{'ROAMER' if roamer else 'normal'} "
                          f"{'[agrees]' if agree else '[*** MISMATCH ***]'}"
                          + (f"  ({len(entry['rolls'])} rolls spent -- TIEBREAK)"
                             if len(entry["rolls"]) > 1 else ""))
            return False

    class _RoamerCheckBreakpoint(gdb.Breakpoint):
        def __init__(self):
            super().__init__("getRandomActiveRoamerInCurrMap", internal=True)
            self.silent = True

        def stop(self):
            if _rec is not None and not _rec.stopped:
                _rec.open_check()
                try:
                    _RoamerCheckFinish(gdb.newest_frame())
                except Exception:
                    print("[owlog] WARNING: could not set the roamer-check return hook, so "
                          "this check's outcome is unknown.")
            return False

    class _RoamingInitBreakpoint(gdb.Breakpoint):
        """Independent witness: only ever runs on a roamer battle."""

        def __init__(self):
            super().__init__("initRoamingWildmon", internal=True)
            self.silent = True

        def stop(self):
            if _rec is not None and not _rec.stopped:
                _rec.note_roaming_init()
            return False

    class _SweetScentBreakpoint(gdb.Breakpoint):
        """Marks each Sweet Scent attempt, so the log says which rolls belong to which try."""

        def __init__(self):
            super().__init__("FieldSystem_PerformSweetScentEncounterCheck", internal=True)
            self.silent = True

        def stop(self):
            if _rec is not None and not _rec.stopped:
                _rec.add_marker("sweet scent")
            return False

    # -- commands -------------------------------------------------------

    class OwLogCommand(gdb.Command):
        """owlog [seed] [label] -- start recording the overworld stream."""

        def __init__(self):
            super().__init__("owlog", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global _rec
            parts = arg.split()
            forced = None
            label = "run"
            if parts and parts[0].lower().startswith(("0x", "0X")):
                forced = int(parts[0], 16)
                parts = parts[1:]
            elif parts and all(c in "0123456789abcdefABCDEF" for c in parts[0]) \
                    and len(parts[0]) >= 6:
                forced = int(parts[0], 16)
                parts = parts[1:]
            if parts:
                label = parts[0]

            before = _read_seed()
            start = before
            if forced is not None:
                got = _force_seed(forced)
                if got != (forced & 0xFFFFFFFF):
                    print(f"[owlog] ABORT: could not write the seed after "
                          f"{SEED_WRITE_ATTEMPTS} attempts (memory holds {got:#010x}). "
                          f"Nothing is being recorded -- a wrong seed would mislabel every "
                          f"frame number. Run `owlog` with no seed to record from whatever "
                          f"state the game is in; the roamer test does not need forcing.")
                    return
                start = got
            _rec = Recording(label, forced_seed=forced, start_state=start)
            print(f"[owlog] recording '{label}'. sLCRNG_State = {start:#010x}"
                  + (f" (forced; was {before:#010x})" if forced is not None else " (not forced)"))
            print("[owlog] walk onto the roamer's route and Sweet Scent. "
                  "owstatus / owpredict / owsave.")

    class OwPredictCommand(gdb.Command):
        """owpredict [n] -- frames from the recorded start state that should give a roamer."""

        def __init__(self):
            super().__init__("owpredict", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None or _rec.start_state is None:
                print("[owlog] nothing recorded yet; run owlog first.")
                return
            limit = int(arg) if arg.strip().isdigit() else 32
            state = _rec.start_state
            hits = []
            for frame in range(limit):
                state = advance(state)
                if predicted_roamer(state >> 16):
                    hits.append(frame)
            print(f"[owlog] from {_rec.start_state:#010x}, frames predicted to give a roamer "
                  f"(of 0..{limit - 1}):")
            print("        " + ", ".join(str(f) for f in hits))
            print(f"        {len(hits)}/{limit} = {len(hits) / limit:.0%}. "
                  f"Rolls consumed so far: {len(_rec.rolls)}.")

    class OwMarkCommand(gdb.Command):
        """owmark <text> -- drop a labelled marker into the log."""

        def __init__(self):
            super().__init__("owmark", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None:
                print("[owlog] nothing recorded yet; run owlog first.")
                return
            _rec.add_marker(arg.strip() or "mark")
            print(f"[owlog] marked at roll {len(_rec.rolls)}: {arg.strip()}")

    class OwStatusCommand(gdb.Command):
        """owstatus -- what has been captured, and the verdict so far."""

        def __init__(self):
            super().__init__("owstatus", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            if _rec is None:
                print("[owlog] nothing recorded yet; run owlog first.")
                return
            print(f"[owlog] '{_rec.label}': {len(_rec.rolls)} roll(s), "
                  f"{len(_rec.checks)} roamer check(s)"
                  + (" [STOPPED]" if _rec.stopped else ""))
            tested = [c for c in _rec.checks if c["rolls"]]
            if not tested:
                print("        no check has spent a flip yet -- is an active roamer on this map?")
                return
            agreed = sum(1 for c in tested
                         if predicted_roamer(c["rolls"][0]) == c["roamer"])
            got = sum(1 for c in tested if c["roamer"])
            print(f"        the bit predicted {agreed}/{len(tested)} outcomes")
            print(f"        observed roamer rate {got}/{len(tested)} = "
                  f"{got / len(tested):.0%} (the decompilation says 50%)")
            for c in tested:
                if len(c["rolls"]) > 1:
                    print(f"        TIEBREAK at roll {c['first_roll_index']}: "
                          f"{len(c['rolls'])} rolls spent")

    class OwSaveCommand(gdb.Command):
        """owsave [name] -- flush to data/overworld_logs/<name>.jsonl and stop recording."""

        def __init__(self):
            super().__init__("owsave", gdb.COMMAND_USER)

        def invoke(self, arg, from_tty):
            global _rec
            if _rec is None:
                print("[owlog] nothing to save.")
                return
            name = arg.strip() or _rec.label
            path = output_path(name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as fh:
                fh.write(json.dumps(_rec.to_doc(), separators=(",", ":")) + "\n")
            print(f"[owlog] saved {len(_rec.rolls)} roll(s) and {len(_rec.checks)} "
                  f"roamer check(s) to {path}")
            print("[owlog] analyse with: python -c \"from claytonlib.roamer_check import load; "
                  f"[print(v.summary()) for v in load('{path}')]\"")
            _rec.stopped = True
            _rec = None

    # -- installation ---------------------------------------------------

    def _install(what, factory):
        """Create a breakpoint, or record why it could not be.

        GDB's default for an unknown symbol is a *pending* breakpoint: it prints an error and
        then silently never fires, while the constructor reports success. That is the worst
        outcome here -- a recording that looks complete and is missing the very events it was
        made for. `breakpoint pending off` makes the constructor raise instead.
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

    _install("overworld rolls (LCRandom)", _RandomBreakpoint)
    _install("roamer check", _RoamerCheckBreakpoint)
    _install("roamer witness (initRoamingWildmon)", _RoamingInitBreakpoint)
    _install("sweet scent marker", _SweetScentBreakpoint)

    OwLogCommand()
    OwPredictCommand()
    OwMarkCommand()
    OwStatusCommand()
    OwSaveCommand()

    for _what, _state in _HOOKS.items():
        print(f"[owlog] {'  ok' if _state == 'live' else 'FAIL'}  {_what}: {_state}")
    if _HOOKS.get("roamer check") != "live":
        print("[owlog] WARNING: the roamer check did not resolve, so this records rolls and "
              "nothing else -- the whole point is that hook. getRandomActiveRoamerInCurrMap is "
              "static and lives in an overlay; if it is missing, re-source once the overworld "
              "is loaded.")
    if _HOOKS.get("overworld rolls (LCRandom)") != "live":
        print("[owlog] WARNING: LCRandom did not resolve, so no rolls will be recorded and "
              "every check will look like it spent none.")
    print("[owlog] ready. Commands: owlog [seed] [label], owpredict [n], owmark, owstatus, "
          "owsave [name]")
