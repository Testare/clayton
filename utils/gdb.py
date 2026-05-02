import gdb
import json
import os

# Resolve the moves.json path at source time (before __file__ is needed,
# which GDB doesn't set for sourced scripts). Assumes GDB is run from the
# project root.
_MOVES_JSON_PATH = os.path.join(os.getcwd(), "claytonlib", "basedata", "moves.json")

# Maps frame name -> int (permanent) or list[int] (consumed queue).
# Use `rand_override NAME VALUE [VALUE ...]` to populate.
destined_rand_by_name = {}


class BattleSetupNewBreakpoint(gdb.Breakpoint):
    def __init__(self):
        super().__init__("BattleSetup_New")
        self.silent = True

    def stop(self):
        gdb.set_convenience_variable("new_seed", True)

        date = gdb.parse_and_eval("date")
        time = gdb.parse_and_eval("time")

        year   = int(date["year"])
        month  = int(date["month"])
        day    = int(date["day"])
        hour   = int(time["hour"])
        minute = int(time["minute"])
        second = int(time["second"])

        print(f"Battle Setup: {year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}")

        return False  # continue


class BattleSystemRandomFinish(gdb.FinishBreakpoint):
    """Fires when BattleSystem_Random returns; inspects caller and applies overrides."""

    def __init__(self, frame):
        super().__init__(frame, internal=True)
        self.silent = True

    def stop(self):
        frame = gdb.selected_frame()
        pc = frame.pc()
        func_name = frame.name() or "??"
        r0 = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
        print(f"0x{pc:08x} {func_name}: r0=0x{r0:08x}")

        if pc == 0x0225e46e:
            print("End of turn")

        # Apply rand override for this frame name, if any
        override = destined_rand_by_name.get(func_name)
        if isinstance(override, list):
            if override:
                new_r0 = override.pop(0) & 0xFFFFFFFF
                gdb.execute(f"set $r0 = {new_r0}")
                print(f"  [rand_override] r0 overridden to 0x{new_r0:08x} ({len(override)} remaining)")
        elif isinstance(override, int):
            new_r0 = override & 0xFFFFFFFF
            gdb.execute(f"set $r0 = {new_r0}")
            print(f"  [rand_override] r0 overridden to 0x{new_r0:08x} (permanent)")

        smooth_rand = gdb.convenience_variable("smooth_rand")
        if smooth_rand:
            return False  # continue

        return True  # stop


class BattleSystemRandomBreakpoint(gdb.Breakpoint):
    def __init__(self):
        super().__init__("BattleSystem_Random")

    def stop(self):
        new_seed = gdb.convenience_variable("new_seed")
        if new_seed:
            battle_system = gdb.parse_and_eval("battleSystem")
            rand_val = int(battle_system["rand"]) & 0xFFFFFFFF
            print(f"SEED: {rand_val:#010x}")
            gdb.set_convenience_variable("new_seed", False)

        BattleSystemRandomFinish(gdb.selected_frame())
        return False  # continue; finish breakpoint handles the rest


class RandOverrideCommand(gdb.Command):
    """Set or clear a rand override for a named frame.

Usage:
  rand_override NAME VALUE         -- permanent: r0 is always forced to VALUE
  rand_override NAME V1 V2 ...     -- queue: values consumed one per call
  rand_override NAME clear         -- remove any override for NAME
  rand_override list               -- show all current overrides

VALUE may be decimal or hex (0x...)."""

    def __init__(self):
        super().__init__("rand_override", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        args = arg.split()
        if not args:
            print(self.__doc__)
            return

        if args[0] == "list":
            if not destined_rand_by_name:
                print("No rand overrides set.")
            for name, val in destined_rand_by_name.items():
                if isinstance(val, list):
                    formatted = "[" + ", ".join(hex(v) for v in val) + "]"
                else:
                    formatted = f"{hex(val)} (permanent)"
                print(f"  {name}: {formatted}")
            return

        name = args[0]
        if len(args) < 2:
            print("Usage: rand_override NAME VALUE [VALUE ...] | clear | list")
            return

        if args[1] == "clear":
            removed = destined_rand_by_name.pop(name, None)
            if removed is not None:
                print(f"Cleared rand override for '{name}'.")
            else:
                print(f"No override was set for '{name}'.")
            return

        values = [int(v, 0) for v in args[1:]]
        if len(values) == 1:
            destined_rand_by_name[name] = values[0]
            print(f"rand_override '{name}' = {hex(values[0])} (permanent)")
        else:
            destined_rand_by_name[name] = values
            print(f"rand_override '{name}' = [{', '.join(hex(v) for v in values)}] (queue)")


class MetronomeCommand(gdb.Command):
    """Queue Metronome outcomes by move name.

Usage: metronome MOVE [, MOVE , ...]

Move names are comma-separated and case-insensitive; spaces within a name are fine.
  metronome Ice Beam
  metronome Surf, Thunder Punch, Earthquake

A single move sets a permanent override; multiple moves (or a trailing comma) set a consumed queue.
Sets rand_override for BtlCmd_Metronome using rand = move_number - 1."""

    FRAME_NAME = "BtlCmd_Metronome"
    _moves_cache = None  # dict: lowercase_name -> {"number": int, "metronome_usable": bool}

    def __init__(self):
        super().__init__("metronome", gdb.COMMAND_USER)

    @classmethod
    def _load_moves(cls):
        if cls._moves_cache is None:
            with open(_MOVES_JSON_PATH) as f:
                data = json.load(f)
            cls._moves_cache = {
                m["name"].lower(): {"number": m["number"], "usable": m.get("metronome_usable", False)}
                for m in data
            }
        return cls._moves_cache

    def _resolve(self, name):
        """Return (move_number, usable) for name, or raise ValueError."""
        moves = self._load_moves()
        key = name.lower().strip()
        entry = moves.get(key)
        if entry is None:
            # Partial match
            hits = [k for k in moves if key in k]
            if len(hits) == 1:
                entry = moves[hits[0]]
                print(f"  '{name}' matched '{hits[0]}' (#{entry['number']})")
            elif hits:
                print(f"  Ambiguous move '{name}': {[h for h in hits[:6]]}")
                raise ValueError(name)
            else:
                print(f"  Unknown move: '{name}'")
                raise ValueError(name)
        return entry["number"], entry["usable"]

    def invoke(self, arg, from_tty):
        if not arg.strip():
            print(self.__doc__)
            return

        force_list = arg.rstrip().endswith(",")
        names = [n.strip() for n in arg.split(",") if n.strip()]
        try:
            resolved = [self._resolve(n) for n in names]
        except ValueError:
            return

        for name, (num, usable) in zip(names, resolved):
            if not usable:
                print(f"  Warning: '{name}' (#{num}) is not metronome_usable")

        rand_values = [num - 1 for num, _ in resolved]

        if len(rand_values) == 1 and not force_list:
            destined_rand_by_name[self.FRAME_NAME] = rand_values[0]
            num, _ = resolved[0]
            print(f"metronome: '{names[0]}' (#{num}) -> rand={rand_values[0]} (permanent)")
        else:
            destined_rand_by_name[self.FRAME_NAME] = rand_values
            pairs = ", ".join(
                f"'{n}' (#{num}) -> {r}"
                for n, (num, _), r in zip(names, resolved, rand_values)
            )
            print(f"metronome: [{pairs}] queued")


BattleSetupNewBreakpoint()
BattleSystemRandomBreakpoint()
RandOverrideCommand()
MetronomeCommand()
print("GDB utils loaded.")
print("  rand_override NAME VALUE [VALUE ...]  -- override r0 after BattleSystem_Random")
print("  metronome MOVE [, MOVE ...]           -- override BtlCmd_Metronome by move name")
