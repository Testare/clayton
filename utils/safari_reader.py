"""safari_reader.py -- pure helpers for the Safari-Zone GDB ground-truth reader.

Split out from the GDB-sourced ``gdb-safari-reader.py`` so the parsing / action /
message-to-path logic is importable and unit-testable OFF the emulator (the GDB
script does only the debugger + presser I/O and imports this).

Three pieces:
  * seed-file parsing with an action script (``0x080E2B7C 6B6C1M`` = 6 Bait, 6
    Ball, 1 Mud, then Ball forever);
  * the presser key sequence for each action (Ball = s,space / Mud = s,d,space /
    Bait = s,a,space);
  * reverse-engineering the safari battle MESSAGES into a compass-safari path
    string (b/B bait, m/M mud, 0-3 ball shakes, F fled, C captured).

The message SUBSTRINGS are unknown until the emulator spike (clayton-ctd.14), so
they live in ``MsgMap`` with TODO placeholders; ``messages_to_path`` takes a
MsgMap, so the assembly ALGORITHM is tested now with a synthetic map and only the
real strings need filling in later.
"""
import re
from dataclasses import dataclass, field


# Battle messages decode with real newlines and control markers ([WAIT]/[SCROLL]/[VAR:..], the
# last standing in for the pokemon name), so a substring like "What will Ethan throw?" can arrive
# split as "What will Ethan\nthrow?".  We match against a sanitized copy but LOG the raw text.
_MSG_MARKER_RE = re.compile(r"\[(?:WAIT|SCROLL|VAR:[^\]]*)\]")
_MSG_WS_RE = re.compile(r"\s+")


def sanitize_message(text):
    """Normalize a decoded battle message for substring matching: drop the control markers and
    collapse every run of whitespace (newlines included) to a single space."""
    return _MSG_WS_RE.sub(" ", _MSG_MARKER_RE.sub(" ", text)).strip()


# --------------------------------------------------------------------------- #
# Seed file: "<seed> <action-script>"                                          #
# --------------------------------------------------------------------------- #
# Action-script tokens (in the seed file) and the compass path/action they mean.
BAIT, MUD, BALL = "B", "M", "C"      # C = "Capture" attempt = throw a Safari Ball
_ACTION_CHARS = (BAIT, MUD, BALL)


def expand_action_script(spec):
    """Expand a run-length action script like '6B6C1M' -> ['B']*6 + ['C']*6 + ['M'].

    Each group is a count (>=1) followed by one of B/M/C (case-insensitive).  An empty
    spec expands to [] (meaning: throw balls from the start).  Raises ValueError on a
    malformed group (a count with no action, an unknown action letter, or a stray letter
    with no count).
    """
    out = []
    num = ""
    for ch in spec.strip().upper():
        if ch.isdigit():
            num += ch
            continue
        if ch in _ACTION_CHARS:
            if num == "":
                raise ValueError(f"action {ch!r} has no count in {spec!r}")
            out.extend([ch] * int(num))
            num = ""
            continue
        raise ValueError(f"unexpected character {ch!r} in action script {spec!r}")
    if num != "":
        raise ValueError(f"trailing count {num!r} with no action in {spec!r}")
    return out


def parse_safari_seed_line(line):
    """Parse one seed-file line into ``(seed:int, actions:list[str])`` or None to skip.

    Format: a hex seed (with/without 0x) optionally followed by an action script on the
    same line, e.g. ``0x080E2B7C 6B6C1M``.  A bare seed yields an empty action list (throw
    balls throughout).  Blank lines and ``#`` comments return None.
    """
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    parts = s.split(None, 1)
    seed = int(parts[0], 16) & 0xFFFFFFFF
    actions = expand_action_script(parts[1]) if len(parts) > 1 else []
    return seed, actions


def load_safari_seeds(path):
    """Read a safari seed file into a list of ``(seed, actions)`` tuples."""
    rows = []
    with open(path) as f:
        for line in f:
            parsed = parse_safari_seed_line(line)
            if parsed is not None:
                rows.append(parsed)
    return rows


def action_at(actions, turn_index):
    """The action to take on ``turn_index`` (0-based): the scripted one, else BALL forever."""
    return actions[turn_index] if turn_index < len(actions) else BALL


# --------------------------------------------------------------------------- #
# Action -> presser key sequence (the throw cursor is STATEFUL)               #
# --------------------------------------------------------------------------- #
# The game remembers the action selected last turn and pre-selects it, so the keys to reach the
# target depend on where the cursor already is.  Layout (confirmed in-game): the battle starts
# with NOTHING selected, and 's' selects Ball; from Ball, 'a' -> Bait and 'd' -> Mud; from Bait
# or Mud, 'w' -> Ball (so Bait->Mud is 'w','d' and Mud->Bait is 'w','a').  After the first turn
# the cursor persists on the last action, so no 's' is needed.
_NAV = {
    BALL: {BALL: [],    BAIT: ["a"],      MUD:  ["d"]},
    BAIT: {BAIT: [],    BALL: ["w"],      MUD:  ["w", "d"]},
    MUD:  {MUD:  [],    BALL: ["w"],      BAIT: ["w", "a"]},
}


def action_keys(action, last=None):
    """The presser key sequence that performs ``action`` (B/M/C) given the previously selected
    action ``last`` (None on the first turn).

    First turn (``last is None``): nothing is selected, so 's' selects Ball, then navigate to
    ``action``, then 'space'.  Later turns: navigate from ``last`` (the remembered cursor) to
    ``action``, then 'space' -- no 's'.
    """
    action = action.upper()
    if action not in _ACTION_CHARS:
        raise ValueError(f"unknown action {action!r} (use B, M, or C)")
    if last is None:
        return ["s"] + _NAV[BALL][action] + ["space"]
    last = last.upper()
    if last not in _ACTION_CHARS:
        raise ValueError(f"unknown last action {last!r} (use B, M, or C)")
    return _NAV[last][action] + ["space"]


# --------------------------------------------------------------------------- #
# Messages -> compass-safari path                                             #
# --------------------------------------------------------------------------- #
@dataclass
class MsgMap:
    """Substrings that identify each safari battle message (source: compass/_display.py).

    Filled in from the emulator message inventory (clayton-ctd.14 spike).  Crit variants are
    checked before their non-crit counterparts, so if a crit message is a superset of the
    normal one it still resolves to the crit token.  Any field left "" is simply never matched.

    Note: the safari has NO per-shake message.  Each ball throw produces exactly one outcome
    message that already encodes the shake count -- ``ball_0``..``ball_3`` -- or the capture.
    """
    prompt: str = ""       # "What will <name> throw?" -- the per-turn action prompt
    bait: str = ""         # 'b'  "<name> is eating!"
    bait_crit: str = ""    # 'B'  "<name> is busy eating!"
    mud: str = ""          # 'm'  "<name> is angry!"
    mud_crit: str = ""     # 'M'  "<name> is beside itself with anger!"
    ball_0: str = ""       # '0'  "Oh, no! The Pokémon broke free!"
    ball_1: str = ""       # '1'  "Aww! It appeared to be caught!"
    ball_2: str = ""       # '2'  "Aargh! Almost had it!"
    ball_3: str = ""       # '3'  "Shoot! It was so close, too!"
    capture: str = ""      # 'C'  "Gotcha! <name> was caught!" (terminal)
    flee: str = ""         # 'F'  "<name> fled!" (terminal)
    out_of_balls: str = "" # terminal, no token (contains "Announcer:")


def _msg_text(item):
    """The message string of a results item ({'msg': ...}), or None for a roll item."""
    if isinstance(item, dict):
        return item.get("msg")
    return item if isinstance(item, str) else None


class ActionDriver:
    """Decides WHEN to send the next safari action and WHICH keys, purely from the messages.

    It recognizes ONLY the terminal messages (capture / flee / out-of-balls) and the action
    prompt ("What will <name> throw?").  Every other message is opaque -- we never parse action
    outcomes or count RNG rolls, so gathering data does not depend on our understanding of the
    mechanics (a mismatched outcome string only affects the reconstructed path afterward, which
    is the divergence we are hunting).

    A one-shot ``_armed`` flag guards against a prompt redrawn within the same turn: it is
    cleared when we act and re-armed by ANY non-prompt message (an action always produces at
    least one), so exactly one action is sent per turn without knowing what that message says.

    Feed ``on_message(text)`` per battle message; it returns one of:
      * ``("end", reason)``   -- a terminal message,
      * ``("keys", [...])``   -- perform this key sequence (the next scripted action),
      * ``None``              -- nothing to do.
    """

    def __init__(self, actions, msgmap):
        self.actions = actions
        self.msgmap = msgmap
        self.turn = 0
        self.last_action = None
        self._armed = True

    def on_message(self, text):
        text = sanitize_message(text)
        m = self.msgmap
        for field, reason in ((m.capture, "captured"), (m.flee, "fled"),
                              (m.out_of_balls, "out_of_balls")):
            if field and field in text:
                return ("end", reason)
        if m.prompt and m.prompt in text:
            if not self._armed:
                return None                  # a redraw of the same turn's prompt
            self._armed = False
            action = action_at(self.actions, self.turn)
            self.turn += 1
            keys = action_keys(action, self.last_action)
            self.last_action = action
            return ("keys", keys)
        self._armed = True                   # any non-prompt message => the turn advanced
        return None


def messages_to_path(results, msgmap):
    """Reverse-engineer an ordered results/message stream into a compass-safari path.

    ``results`` is the interleaved roll/message list (or a plain list of message strings);
    only messages are consulted.  Returns ``(path, ended)`` where path is the token string
    (``b/B`` bait, ``m/M`` mud, ``0-3`` ball shakes, ``F`` fled, ``C`` captured) and ``ended``
    is True once a terminal message (capture / flee / out-of-balls) is seen.

    Each ball throw's shake count comes from a single distinct outcome message
    (``ball_0``..``ball_3``); a capture ends the path with ``C`` instead of a digit.
    """
    path = []
    ended = False

    def has(field, text):
        return bool(field) and field in text

    for item in results:
        raw = _msg_text(item)
        if not raw:
            continue
        text = sanitize_message(raw)
        if has(msgmap.flee, text):
            path.append("F")
            ended = True
            break
        if has(msgmap.capture, text):
            path.append("C")
            ended = True
            break
        if has(msgmap.out_of_balls, text):
            ended = True
            break
        if has(msgmap.bait_crit, text):
            path.append("B")
        elif has(msgmap.bait, text):
            path.append("b")
        elif has(msgmap.mud_crit, text):
            path.append("M")
        elif has(msgmap.mud, text):
            path.append("m")
        elif has(msgmap.ball_3, text):
            path.append("3")
        elif has(msgmap.ball_2, text):
            path.append("2")
        elif has(msgmap.ball_1, text):
            path.append("1")
        elif has(msgmap.ball_0, text):
            path.append("0")
    return "".join(path), ended


# The real HG/SS safari messages (name-agnostic substrings; source: compass/_display.py).
# Shared by the GDB reader and the validator so there is a single source of truth.
SAFARI_MESSAGES = MsgMap(
    prompt="What will Ethan throw?",
    bait="is eating!", bait_crit="is busy eating!",
    mud="is angry!", mud_crit="is beside itself with anger!",
    ball_0="broke free!", ball_1="appeared to be caught!",
    ball_2="Almost had it!", ball_3="so close, too!",
    capture="was caught!", flee="fled!", out_of_balls="Announcer:",
)
