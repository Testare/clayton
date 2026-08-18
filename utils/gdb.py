import gdb
import json
import os

# Resolve the moves.json path at source time (before __file__ is needed,
# which GDB doesn't set for sourced scripts). Assumes GDB is run from the
# project root.
_MOVES_JSON_PATH = os.path.join(os.getcwd(), "claytonlib", "basedata", "moves.json")

# Pokemon HeartGold English character code -> Python str mapping.
# Codes from include/constants/charcode.h.
_POKE_CHARMAP = {}
for _i in range(10):
    _POKE_CHARMAP[289 + _i] = str(_i)      # '0'-'9'
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

    String layout (pm_string.h):
        u16 maxsize [+0], u16 size [+2], u32 magic [+4], u16 data[] [+8]

    Control code format (string_control_code.c):
        0xFFFE, <type u16>, <field_count u16>, [fields...]
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
            # format: 0xFFFE, type, field_count, [fields]
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

# Maps frame name -> int (permanent) or list[int] (consumed queue).
# Use `rand_override NAME VALUE [VALUE ...]` to populate.
destined_rand_by_name = {}

# Consecutive-hit counter for BattleSystem_Random calls at the same PC.
_last_pc = None
_last_func_name = None
_consecutive_count = 0

# PCs that should auto-continue (not stop) in BattleSystemRandomFinish.
_skip_pcs = set()

# skip_turn counter: when > 0, all BattleSystem_Random calls auto-continue
# until a '??' frame is hit, at which point the counter is decremented.
# Stops when the counter reaches 0.
_skip_turn_count = 0

# Maps frame name -> int modulus for mod_report.
_mod_report_by_name = {}

# Persistent seed to inject into battleSystem->rand before the first
# BattleSystem_Random call each battle.  None = no override.
_seed_override = None

# Whether to print each battle message to GDB as it is displayed.
_battle_msg_enabled = False


class GfRtcCopyDateTimeFinish(gdb.FinishBreakpoint):
    """Fires when GF_RTC_CopyDateTime returns; at that point we're back in
    BattleSetup_New's frame so 'date' and 'time' resolve to the correct
    (now-populated) locals."""

    def __init__(self, frame):
        super().__init__(frame, internal=True)
        self.silent = True

    def stop(self):
        date = gdb.parse_and_eval("date")
        time = gdb.parse_and_eval("time")

        year   = 2000 + int(date["year"])
        month  = int(date["month"])
        day    = int(date["day"])
        hour   = int(time["hour"])
        minute = int(time["minute"])
        second = int(time["second"])

        print(f"Battle Setup: {year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}")
        return False  # continue


# Flag set by BattleSetupNewBreakpoint so GfRtcCopyDateTimeBreakpoint only
# installs the finish breakpoint when called from BattleSetup_New.
_in_battle_setup = False


class BattleSetupNewFinish(gdb.FinishBreakpoint):
    """Fires when BattleSetup_New returns; prints unk_19C for diagnostic confirmation."""

    def __init__(self, frame):
        super().__init__(frame, internal=True)
        self.silent = True

    def stop(self):
        try:
            val = int(gdb.parse_and_eval("*($r0 + 0x19C)")) & 0xFFFFFFFF
            print(f"BattleSetup_New: unk_19C = {val:#010x}")
        except gdb.error as e:
            print(f"BattleSetup_New: could not read unk_19C ({e})")
        return False  # continue


class BattleSetupNewBreakpoint(gdb.Breakpoint):
    def __init__(self):
        super().__init__("BattleSetup_New")
        self.silent = True

    def stop(self):
        global _in_battle_setup
        _in_battle_setup = True
        gdb.set_convenience_variable("new_seed", True)
        BattleSetupNewFinish(gdb.selected_frame())
        return False  # continue


class GfRtcCopyDateTimeBreakpoint(gdb.Breakpoint):
    def __init__(self):
        super().__init__("GF_RTC_CopyDateTime")
        self.silent = True

    def stop(self):
        global _in_battle_setup
        if _in_battle_setup:
            _in_battle_setup = False
            GfRtcCopyDateTimeFinish(gdb.selected_frame())
        return False  # continue


class BattleSystemRandomFinish(gdb.FinishBreakpoint):
    """Fires when BattleSystem_Random returns; inspects caller and applies overrides."""

    def __init__(self, frame):
        super().__init__(frame, internal=True)
        self.silent = True

    def stop(self):
        global _last_pc, _last_func_name, _consecutive_count, _skip_turn_count
        frame = gdb.selected_frame()
        pc = frame.pc()
        func_name = frame.name() or "??"
        _last_func_name = func_name
        r0 = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF

        if pc == _last_pc:
            _consecutive_count += 1
        else:
            _consecutive_count = 1
            _last_pc = pc

        mod = _mod_report_by_name.get(func_name)
        mod_suffix = f" % {mod} = {r0 % mod}" if mod is not None else ""
        print(f"{_consecutive_count}. 0x{pc:08x} {func_name}: {r0:5} (0x{r0:04x}){mod_suffix}")

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

        if _skip_turn_count > 0:
            if func_name == "??":
                _skip_turn_count -= 1
                if _skip_turn_count == 0:
                    print("skip_turn: reached '??' frame, stopping.")
                    return True  # stop
            return False  # continue

        if pc in _skip_pcs:
            return False  # continue

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
            if _seed_override is not None:
                gdb.execute(f"set battleSystem->rand = {_seed_override}")
                print(f"SEED: {rand_val:#010x} -> [seed_override] {_seed_override:#010x}")
            else:
                print(f"SEED: {rand_val:#010x}")
            gdb.set_convenience_variable("new_seed", False)

        BattleSystemRandomFinish(gdb.selected_frame())
        return False # continue; finish breakpoint handles the rest


class RandOverrideCommand(gdb.Command):
    """Set or clear a rand override for a named frame.

Usage:
  rand_override VALUE              -- permanent override for last-hit frame
  rand_override NAME VALUE         -- permanent: r0 is always forced to VALUE
  rand_override NAME V1 V2 ...     -- queue: values consumed one per call
  rand_override NAME clear         -- remove any override for NAME
  rand_override list               -- show all current overrides

VALUE may be decimal or hex (0x...).
If the first argument is a number, the last-hit frame name is used."""

    def __init__(self):
        super().__init__("rand_override", gdb.COMMAND_USER)

    @staticmethod
    def _try_int(s):
        try:
            return int(s, 0)
        except ValueError:
            return None

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

        # If the first arg is a number, use the last-hit frame name.
        if self._try_int(args[0]) is not None:
            if _last_func_name is None:
                print("No BattleSystem_Random hit recorded yet.")
                return
            name = _last_func_name
            value_args = args
        else:
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
            value_args = args[1:]

        values = [int(v, 0) for v in value_args]
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


class SkipTurnCommand(gdb.Command):
    """Auto-continue BattleSystem_Random until a '??' frame is hit.

Usage:
  skip_turn        -- set skip count to 1 (stop at next '??' frame)
  skip_turn N      -- set skip count to N (stop after N '??' frames; 0 to disable)

When active, all BattleSystem_Random breakpoints auto-continue. Each time a
'??' frame is encountered the count is decremented; execution stops when it
reaches zero."""

    def __init__(self):
        super().__init__("skip_turn", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        global _skip_turn_count
        args = arg.split()
        if not args:
            _skip_turn_count = 1
            print("skip_turn: will stop at next '??' frame.")
            return
        try:
            n = int(args[0], 0)
        except ValueError:
            print(f"skip_turn: invalid value '{args[0]}'.")
            return
        if n < 0:
            print("skip_turn: value must be >= 0.")
            return
        _skip_turn_count = n
        if n == 0:
            print("skip_turn: disabled.")
        else:
            print(f"skip_turn: will stop after {n} '??' frame(s).")


class RandSkipCommand(gdb.Command):
    """Auto-continue BattleSystem_Random hits at an address.

Usage:
  rand_skip           -- skip the last-seen address
  rand_skip ADDRESS   -- skip the specified address

Adds the address to the skip list so that future hits at that address
automatically continue without stopping."""

    def __init__(self):
        super().__init__("rand_skip", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        args = arg.split()
        if args:
            try:
                pc = int(args[0], 0)
            except ValueError:
                print(f"rand_skip: invalid address '{args[0]}'")
                return
        else:
            if _last_pc is None:
                print("No BattleSystem_Random hit recorded yet.")
                return
            pc = _last_pc

        _skip_pcs.add(pc)
        print(f"rand_skip: 0x{pc:08x} will now auto-continue ({len(_skip_pcs)} skipped total)")


class RandSkipClearCommand(gdb.Command):
    """Clear all rand_skip auto-continue addresses; break on all frames again.

Usage: rand_skip_clear"""

    def __init__(self):
        super().__init__("rand_skip_clear", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        count = len(_skip_pcs)
        _skip_pcs.clear()
        print(f"rand_skip_clear: cleared {count} address(es), breaking on all frames.")


class SeedOverrideCommand(gdb.Command):
    """Persistently override the initial battle seed each time a new battle starts.

Usage:
  seed_override VALUE   -- inject VALUE into battleSystem->rand before the first rand call
  seed_override clear   -- remove the override
  seed_override         -- show current override

VALUE may be decimal or hex (0x...).
The override applies every battle until cleared."""

    def __init__(self):
        super().__init__("seed_override", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        global _seed_override
        args = arg.split()
        if not args:
            if _seed_override is None:
                print("seed_override: not set.")
            else:
                print(f"seed_override: {_seed_override:#010x} (active)")
            return
        if args[0] == "clear":
            _seed_override = None
            print("seed_override: cleared.")
            return
        try:
            _seed_override = int(args[0], 0) & 0xFFFFFFFF
            print(f"seed_override: will inject {_seed_override:#010x} as initial seed each battle.")
        except ValueError:
            print(f"seed_override: invalid value '{args[0]}'.")


class ModReportCommand(gdb.Command):
    """Print r0 % N alongside the rand line for a named frame.

Usage:
  mod_report MOD              -- set mod for last-hit frame
  mod_report NAME MOD         -- set mod for named frame
  mod_report NAME clear       -- remove mod report for NAME
  mod_report clear all        -- remove all mod reports
  mod_report list             -- show all current mod reports

MOD must be a positive integer (decimal or hex)."""

    def __init__(self):
        super().__init__("mod_report", gdb.COMMAND_USER)

    @staticmethod
    def _try_int(s):
        try:
            return int(s, 0)
        except ValueError:
            return None

    def invoke(self, arg, from_tty):
        args = arg.split()
        if not args:
            print(self.__doc__)
            return

        if args[0] == "list":
            if not _mod_report_by_name:
                print("No mod reports set.")
            for name, mod in _mod_report_by_name.items():
                print(f"  {name}: % {mod}")
            return

        if args[0] == "clear" and len(args) >= 2 and args[1] == "all":
            count = len(_mod_report_by_name)
            _mod_report_by_name.clear()
            print(f"mod_report: cleared all {count} report(s).")
            return

        # If first arg is a number, use last-hit frame name.
        if self._try_int(args[0]) is not None:
            if _last_func_name is None:
                print("No BattleSystem_Random hit recorded yet.")
                return
            name = _last_func_name
            value_args = args
        else:
            name = args[0]
            if len(args) < 2:
                print("Usage: mod_report NAME MOD | NAME clear | clear all | list")
                return
            if args[1] == "clear":
                removed = _mod_report_by_name.pop(name, None)
                if removed is not None:
                    print(f"mod_report: cleared '{name}'.")
                else:
                    print(f"mod_report: no report was set for '{name}'.")
                return
            value_args = args[1:]

        if len(value_args) != 1:
            print("mod_report: expected exactly one MOD value.")
            return
        mod = self._try_int(value_args[0])
        if mod is None or mod <= 0:
            print(f"mod_report: MOD must be a positive integer, got '{value_args[0]}'.")
            return
        _mod_report_by_name[name] = mod
        print(f"mod_report '{name}': will show r0 % {mod}")


class BattlePrintMsgFinish(gdb.FinishBreakpoint):
    """Fires when BattleSystem_PrintBattleMessage (or ov12_0223C4E8) returns;
    at that point msgBuffer is populated with the fully-expanded message text."""

    def __init__(self, frame, battleSystem_ptr):
        super().__init__(frame, internal=True)
        self.silent = True
        self.battleSystem_ptr = battleSystem_ptr

    def stop(self):
        if not _battle_msg_enabled:
            return False
        try:
            # BattleSystem.msgBuffer is at offset 0x18 (7th field, all ptrs).
            msgbuf_ptr = int(gdb.parse_and_eval(
                f"*(unsigned int *)({self.battleSystem_ptr:#x} + 0x18)"
            )) & 0xFFFFFFFF
            if msgbuf_ptr == 0:
                return False
            text = _decode_poke_string(msgbuf_ptr)
            print(f"[BattleMsg] {text!r}")
        except Exception as e:
            print(f"[BattleMsg] error: {e}")
        return False


class BattlePrintMsgBreakpoint(gdb.Breakpoint):
    """Intercepts BattleSystem_PrintBattleMessage to log messages when battle_msg is on."""

    def __init__(self):
        super().__init__("BattleSystem_PrintBattleMessage")
        self.silent = True

    def stop(self):
        if not _battle_msg_enabled:
            return False
        battleSystem_ptr = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
        BattlePrintMsgFinish(gdb.selected_frame(), battleSystem_ptr)
        return False


class BattlePrintMsg2Breakpoint(gdb.Breakpoint):
    """Intercepts ov12_0223C4E8 (secondary message printer) similarly."""

    def __init__(self):
        super().__init__("ov12_0223C4E8")
        self.silent = True

    def stop(self):
        if not _battle_msg_enabled:
            return False
        battleSystem_ptr = int(gdb.parse_and_eval("$r0")) & 0xFFFFFFFF
        BattlePrintMsgFinish(gdb.selected_frame(), battleSystem_ptr)
        return False


class BattleMsgCommand(gdb.Command):
    """Print battle messages to GDB as they are displayed on screen.

Usage:
  battle_msg on   -- enable live message logging
  battle_msg off  -- disable
  battle_msg      -- show current state"""

    def __init__(self):
        super().__init__("battle_msg", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        global _battle_msg_enabled
        arg = arg.strip().lower()
        if not arg:
            state = "on" if _battle_msg_enabled else "off"
            print(f"battle_msg: {state}")
        elif arg == "on":
            _battle_msg_enabled = True
            print("battle_msg: on — will print battle messages to GDB")
        elif arg == "off":
            _battle_msg_enabled = False
            print("battle_msg: off")
        else:
            print("Usage: battle_msg [on|off]")


_HELP_LINES = [
    "  rand_override VALUE [VALUE ...]       -- override r0 for last-hit frame",
    "  rand_override NAME VALUE [VALUE ...]  -- override r0 for named frame",
    "  rand_override NAME clear              -- remove override for NAME",
    "  rand_override list                    -- show all current overrides",
    "  metronome MOVE [, MOVE ...]           -- override BtlCmd_Metronome by move name",
    "  seed_override VALUE                   -- inject seed into battleSystem->rand each battle",
    "  seed_override clear                   -- remove seed override",
    "  mod_report MOD                        -- show r0 % MOD for last-hit frame",
    "  mod_report NAME MOD                   -- show r0 % MOD for named frame",
    "  mod_report NAME clear                 -- remove mod report for NAME",
    "  mod_report clear all                  -- remove all mod reports",
    "  mod_report list                       -- show all mod reports",
    "  skip_turn [N]                         -- auto-continue until N '??' frames hit (default 1; 0 to disable)",
    "  rand_skip [ADDRESS]                   -- auto-continue last-hit (or ADDRESS) address",
    "  rand_skip_clear                       -- stop skipping, break on all frames",
    "  mod VALUE                             -- print $r0 % VALUE",
    "  r0 VALUE                              -- set $r0 = VALUE",
    "  zero                                  -- set $r0 = 0",
    "  battle_msg [on|off]                   -- print battle messages to GDB terminal",
    "  utilhelp                              -- show this help",
]


class UtilHelpCommand(gdb.Command):
    """Display all Clayton GDB utility commands."""

    def __init__(self):
        super().__init__("utilhelp", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        print("Clayton GDB utilities:")
        for line in _HELP_LINES:
            print(line)


BattleSetupNewBreakpoint()
GfRtcCopyDateTimeBreakpoint()
BattleSystemRandomBreakpoint()
BattlePrintMsgBreakpoint()
BattlePrintMsg2Breakpoint()
BattleMsgCommand()
RandOverrideCommand()
MetronomeCommand()
SkipTurnCommand()
RandSkipCommand()
RandSkipClearCommand()
SeedOverrideCommand()
ModReportCommand()
UtilHelpCommand()
gdb.execute("alias mod = p $r0 %")
gdb.execute("alias r0 = set $r0 =")
gdb.execute("alias zero = set $r0 = 0")
print("GDB defaults")
gdb.execute("rand_override TryCriticalHit 1")
gdb.execute("rand_override ApplyDamageRange 0")
gdb.execute("mod_report BattleSystem_CheckMoveHit 100")
gdb.execute("mod_report ov12_02250490 100")
gdb.execute("mod_report ?? 2")
gdb.execute("rand_skip 0x02251056")  # bellShimerReplaceGraphics
gdb.execute("rand_skip 0x02258606")  # ov12_022585B
gdb.execute("rand_skip 0x0224941c")  # BattleControllerPlayer_BeforeTurn
print("GDB utils loaded. Type 'utilhelp' for a command reference.")
