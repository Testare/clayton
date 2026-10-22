"""Turn a recorded battle log into answers about the measurements that are still open.

Reads the jsonl written by ``utils/gdb-battle-reader.py``.  Everything here is pure Python and
tested, deliberately: the recorder itself needs a live emulator and cannot be tested at all, so
as little judgement as possible lives there and as much as possible lives here.

What it answers:

* **R2 — battle-start advance count.** Rolls spent before the first turn. Segmentation uses the
  markers you type (``battlemark``) rather than guesswork, because you are already sitting at
  the emulator and a marker is exact where a heuristic is a guess.
* **R7 residual — per-move and per-phase counts.** ``rolls_by_caller`` groups the stream by the
  function that requested each roll, which is how the ROM's 74 ``BattleSystem_Random`` call
  sites get mapped onto phases.
* **R10 — incoming damage.** ``damage_events`` pairs every HP drop with the rolls that preceded
  it, and ``check_damage_event`` asks ``battle.damage`` which of the sixteen Gen 4 rolls could
  have produced it. An event no roll explains is the signal that matters: it means the seed, the
  stats, or the damage model is wrong, and §3.1 requires that be loud rather than silent.
* **Where in the end of turn a roll landed.** Only for logs that carry ``phase`` records, which
  at present means ones taken by ``utils/gdb-platinum-battle-reader.py``.
  ``end_of_turn_sequences`` returns each turn's end-of-turn rolls in order, labelled with the
  ROM's own condition-check state, which is what clayton-6xu.7.1 asks for: which of the four
  end-of-turn advances is Yawn's sleep-duration roll, and which is Future Sight's hit check.
  ``rolls_by_phase`` is the same data aggregated, for the phases outside the end of turn.

Run it directly for a report::

    python -m claytonlib.battle.logcheck data/battle_logs/suicune.jsonl
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Our active Pokemon is battler 0; the wild target is battler 1.
PLAYER_BATTLER = 0
TARGET_BATTLER = 1

#: The BATTLE_CONTROL_* commands that make up the end of a turn, as
#: include/battle/battle_controller_player.h orders them. A roll under one of these is one of the
#: end-of-turn advances that turn_costs.END_OF_TURN_ADVANCES counts.
END_OF_TURN_COMMANDS = (
    "CHECK_FIELD_CONDITIONS", "CHECK_MON_CONDITIONS", "CHECK_SIDE_CONDITIONS", "TURN_END",
)

#: Which condition-check state machine each of those commands walks, so a label can name the
#: condition and not just the command. TURN_END walks none.
#:
#: The third element is how far the state has already MOVED ON by the time a subscript the walk
#: loaded is running, which is the only reason a label can be wrong:
#:
#: * ``mon`` — every one of the 26 cases in ``BattleControllerPlayer_CheckMonConditions`` ends
#:   ``monConditionCheckState++; break;``, *including* the ones that break out to a subscript. So
#:   a roll inside ``subscript_fall_asleep`` reads the state as ITEM_CONDITION (24) when Yawn
#:   (23) is what loaded it. Measured: data/battle_logs/uxie1.jsonl, every fall-asleep roll.
#: * ``side`` — ``CheckSideConditions`` loops ``sideConditionCheckTemp`` over the battlers inside
#:   each state and only advances the state when that loop finishes, so the state still names the
#:   condition. Measured in the same log: the Future Sight rolls read FUTURE_SIGHT (0).
#: * ``field`` — MIXED. The seven side-scoped cases (Reflect..Wish) do not increment on break-out
#:   and the six weather cases do, so there is no single adjustment; `None` means "do not guess",
#:   and :func:`phase_label` marks such a label with a trailing ``?``.
_CHECK_STATE_OF = {
    "CHECK_FIELD_CONDITIONS": ("field", "fieldConditionCheckState", "fieldConditionCheckTemp",
                               None),
    "CHECK_MON_CONDITIONS": ("mon", "monConditionCheckState", "monConditionCheckTemp", 1),
    "CHECK_SIDE_CONDITIONS": ("side", "sideConditionCheckState", "sideConditionCheckTemp", 0),
}


@dataclass
class HpChange:
    battler: int
    hp: int
    max_hp: int
    #: Index into the log's record list, so callers can look at what surrounded it.
    index: int


@dataclass
class DamageEvent:
    """One drop in a battler's HP, with the rolls that preceded it."""

    battler: int
    before: int
    after: int
    index: int
    #: Roll values (high 16 bits as recorded) between the previous HP reading and this one.
    preceding_rolls: list[int] = field(default_factory=list)
    #: Messages in the same span, which is how the move that did it is identified.
    preceding_messages: list[str] = field(default_factory=list)

    @property
    def damage(self) -> int:
        return self.before - self.after


#: The condition-check enums, needed only to re-name a state after undoing the mon walk's
#: increment (``_CHECK_STATE_OF``). Duplicated from the recorder's own copies -- which are
#: themselves copies of file-local enums in src/battle/battle_controller_player.c -- and
#: tests/test_battle_logcheck.py asserts the two agree, so neither can drift.
_CONDITION_NAMES = {
    "mon": (
        "INGRAIN", "AQUA_RING", "ABILITY", "USE_ITEM", "LEFTOVERS", "LEECH_SEED", "POISON",
        "TOXIC", "BURN", "NIGHTMARE", "CURSE", "BIND", "BAD_DREAMS", "UPROAR", "THRASH",
        "DISABLE", "ENCORE", "LOCK_ON", "CHARGE", "TAUNT", "MAGNET_RISE", "HEAL_BLOCK",
        "EMBARGO", "YAWN", "ITEM_CONDITION", "ITEM_DETRIMENTAL_EFFECT", "END",
    ),
    "side": ("FUTURE_SIGHT", "PERISH_SONG", "TRICK_ROOM", "END"),
    "field": (
        "REFLECT", "LIGHT_SCREEN", "MIST", "SAFEGUARD", "TAILWIND", "LUCKY_CHANT", "WISH",
        "RAINING", "SANDSTORM", "SUNNY", "HAILING", "DEEP_FOG", "GRAVITY", "END",
    ),
}


@dataclass
class PhaseRoll:
    """One roll, with the battle phase the ROM was in when it asked for it."""

    #: Index into the log's record list.
    index: int
    #: Which roll this is within its end-of-turn sequence, counting from 1. This is the number
    #: clayton-6xu.7.1 is after: "the second of the four end-of-turn advances" is ordinal 2.
    ordinal: int
    #: e.g. ``mon:YAWN[b0]``, ``side:FUTURE_SIGHT[b1]``, ``turn_end``.
    label: str
    #: e.g. ``sub_seq:subscript_fall_asleep@3``.
    script: str
    value: int


def phase_label(phase: dict) -> str | None:
    """A readable label for an END-OF-TURN phase, or None if it is not one.

    A roll inside a subscript reports ``command`` as EXEC_SCRIPT, with ``commandNext`` holding
    the command that will resume once the script finishes — so that is what says whether a
    script's roll belongs to the end of turn. Both of 6xu.7.1's rolls are of that shape:
    subscript_fall_asleep and subscript_future_sight_damage are both loaded by the
    condition-check walk and both return to it.
    """
    fields, names = phase.get("fields", {}), phase.get("names", {})
    command = names.get("command")
    in_script = command == "EXEC_SCRIPT"
    host = names.get("commandNext") if in_script else command
    if host not in END_OF_TURN_COMMANDS:
        return None
    walk = _CHECK_STATE_OF.get(host)
    if walk is None:
        return "turn_end"
    kind, state_key, temp_key, lag = walk
    state = fields.get(state_key)
    label = names.get(state_key, state)
    uncertain = ""
    if in_script:
        if lag is None:
            uncertain = "?"
        elif lag and isinstance(state, int):
            label = _CONDITION_NAMES.get(kind, ())[state - lag] \
                if 0 <= state - lag < len(_CONDITION_NAMES.get(kind, ())) else str(state - lag)
    return f"{kind}:{label}[b{fields.get(temp_key)}]{uncertain}"


def phase_script(phase: dict) -> str:
    names, fields = phase.get("names", {}), phase.get("fields", {})
    return f"{names.get('script', fields.get('scriptFile'))}@{fields.get('scriptCursor')}"


class BattleLog:
    """One recorded battle."""

    def __init__(self, doc: dict):
        self.label: str = doc.get("label", "")
        #: "platinum" for a log from the Platinum reader; absent (so None) for the HG/SS
        #: reader's own logs, which predate the field.
        self.game: str | None = doc.get("game")
        self.forced_seed: str | None = doc.get("forced_seed")
        self.recorded_at: str = doc.get("recorded_at", "")
        self.records: list[dict] = list(doc.get("records", []))

    # -- views ----------------------------------------------------------

    @property
    def rolls(self) -> list[dict]:
        return [r["roll"] for r in self.records if "roll" in r]

    @property
    def messages(self) -> list[str]:
        return [r["msg"] for r in self.records if "msg" in r]

    @property
    def marks(self) -> list[str]:
        return [r["mark"] for r in self.records if "mark" in r]

    @property
    def mons(self) -> list[dict]:
        return [r["mon"] for r in self.records if "mon" in r]

    @property
    def phases(self) -> list[dict]:
        return [r["phase"] for r in self.records if "phase" in r]

    @property
    def seeds(self) -> list[dict]:
        """The ``seed`` entries: what the game's two streams actually held at each battle's
        first roll. One per battle recorded, so normally one."""
        return [r["seed"] for r in self.records if "seed" in r]

    def rolls_by_caller(self) -> Counter:
        """How many rolls each calling function requested.

        **Unreliable for Platinum logs** — see :meth:`rolls_by_site`, which is the same question
        asked of the program counter instead of a symbol name.
        """
        return Counter(roll["func"] for roll in self.rolls)

    def rolls_by_site(self) -> Counter:
        """How many rolls each PROGRAM COUNTER requested, most common first.

        The first thing to look at in a new log. ``rolls_by_caller`` asks the same question of
        GDB's symbol name for the frame, and in an overlay that name can be another overlay's
        function at the same address: in data/battle_logs/uxie1.jsonl the 192 most common rolls
        came back as ``ChooseTraceTarget`` in a battle containing no Trace, while
        ``BattleSystem_CalcDamageVariance`` and ``BattleSystem_CalcCriticalMulti`` on other
        addresses were correct. The PC is unambiguous, so this is the grouping to trust and the
        names are a hint to check against the phases around each roll.
        """
        return Counter(roll["addr"] for roll in self.rolls)

    def sites(self) -> dict[str, Counter]:
        """Address -> how often each battle PHASE was seen at it, for logs carrying phases.

        This is how a roll site gets identified when its symbol name cannot be trusted: a PC
        that fires only under ``TRY_MOVE`` and inside ``subscript_future_sight_damage`` is the
        accuracy check, whatever GDB calls it. Keyed on ``command|script`` so the two halves of
        that argument are both visible.
        """
        out: dict[str, Counter] = {}
        phase: dict | None = None
        for record in self.records:
            if "phase" in record:
                phase = record["phase"]
                continue
            if "roll" not in record:
                continue
            if phase is None:
                where = "<before any phase>"
            else:
                where = f"{phase['names'].get('command')}|{phase['names'].get('script')}"
            out.setdefault(record["roll"]["addr"], Counter())[where] += 1
        return out

    def hp_changes(self, battler: int | None = None) -> list[HpChange]:
        out = []
        for index, record in enumerate(self.records):
            for reading in record.get("hp", []):
                if battler is None or reading["battler"] == battler:
                    out.append(HpChange(battler=reading["battler"], hp=reading["hp"],
                                        max_hp=reading["max"], index=index))
        return out

    # -- R2: advances before a point ------------------------------------

    def rolls_before_mark(self, label: str) -> int | None:
        """Rolls spent before the marker `label`, or None if it is not in the log.

        With a ``battlemark turn1`` typed before your first action, this is R2 directly: the
        battle-start advance count for this encounter.
        """
        count = 0
        for record in self.records:
            if record.get("mark") == label:
                return count
            if "roll" in record:
                count += 1
        return None

    def segments(self) -> list[tuple[str, int]]:
        """(marker, rolls since the previous marker), in order.

        Mark each turn and this is the per-turn advance count, straight out — which is what
        ``battle.turn``'s skeleton gets checked against.
        """
        out: list[tuple[str, int]] = []
        count = 0
        for record in self.records:
            if "mark" in record:
                out.append((record["mark"], count))
                count = 0
            elif "roll" in record:
                count += 1
        if count:
            out.append(("<end>", count))
        return out

    # -- phases: where in the turn a roll landed -------------------------

    def end_of_turn_sequences(self) -> list[list[PhaseRoll]]:
        """Each end-of-turn run of rolls, in order, labelled with the condition being walked.

        One list per time the battle entered the end-of-turn commands and spent at least one
        roll there; the list is empty for a log without ``phase`` records, which is how an HG/SS
        log reports that it cannot answer this.

        Read it against ``turn_costs.END_OF_TURN_ADVANCES``: a quiet turn gives one sequence of
        four, and the ordinals of the labels that mention YAWN or FUTURE_SIGHT are where those
        rolls sit among them.
        """
        out: list[list[PhaseRoll]] = []
        current: list[PhaseRoll] = []
        label: str | None = None
        script = ""
        for index, record in enumerate(self.records):
            if "phase" in record:
                label = phase_label(record["phase"])
                script = phase_script(record["phase"])
                if label is None and current:
                    out.append(current)
                    current = []
                continue
            if "roll" not in record or label is None:
                continue
            current.append(PhaseRoll(index=index, ordinal=len(current) + 1, label=label,
                                     script=script, value=record["roll"]["val"]))
        if current:
            out.append(current)
        return out

    def rolls_by_phase(self) -> Counter:
        """How many rolls each end-of-turn label accounted for, across the whole battle."""
        return Counter(roll.label
                       for sequence in self.end_of_turn_sequences() for roll in sequence)

    # -- R10: damage attribution ----------------------------------------

    def damage_events(self, battler: int = PLAYER_BATTLER) -> list[DamageEvent]:
        """Every drop in `battler`'s HP, with the rolls and messages that preceded it."""
        events: list[DamageEvent] = []
        last_hp: int | None = None
        rolls: list[int] = []
        messages: list[str] = []
        for index, record in enumerate(self.records):
            if "roll" in record:
                rolls.append(record["roll"]["val"])
                continue
            if "msg" in record:
                messages.append(record["msg"])
                continue
            for reading in record.get("hp", []):
                if reading["battler"] != battler:
                    continue
                if last_hp is not None and reading["hp"] < last_hp:
                    events.append(DamageEvent(
                        battler=battler, before=last_hp, after=reading["hp"], index=index,
                        preceding_rolls=list(rolls), preceding_messages=list(messages)))
                last_hp = reading["hp"]
                rolls, messages = [], []
        return events


def check_damage_event(event: DamageEvent, move, attacker, defender, *,
                       critical: bool = False) -> dict:
    """Which damage rolls could have produced `event`, per ``battle.damage``.

    ``rolls`` empty is the interesting outcome: no roll explains the damage, so the seed, the
    entered stats, or the damage model is wrong. §3.1 requires that surface rather than quietly
    eliminating candidates, which is why this returns a verdict instead of a bool.
    """
    from claytonlib.battle.damage import damage_range, rolls_for_damage
    consistent = rolls_for_damage(event.damage, move, attacker, defender, critical=critical)
    lo, hi = damage_range(move, attacker, defender, critical=critical)
    return {
        "observed": event.damage,
        "expected_range": (lo, hi),
        "rolls": consistent,
        "explained": bool(consistent),
        "critical_assumed": critical,
    }


def load(path: str | Path) -> list[BattleLog]:
    """Every battle recorded in a jsonl file, in order."""
    logs = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            logs.append(BattleLog(json.loads(line)))
    return logs


def report(log: BattleLog) -> str:
    """A human-readable summary — what to look at first in a fresh recording."""
    lines = [
        f"battle: {log.label or '(unlabelled)'}   recorded {log.recorded_at or '?'}"
        + (f"   game: {log.game}" if log.game else ""),
        f"forced seed: {log.forced_seed or 'none'}",
        f"records: {len(log.records)}  rolls: {len(log.rolls)}  "
        f"messages: {len(log.messages)}  marks: {len(log.marks)}  phases: {len(log.phases)}",
    ]
    for seed in log.seeds:
        confirmed = seed.get("confirmed")
        lines.append(
            f"seeds at the first roll: Seed B (seedRandNext) {seed.get('seedRandNext')}  "
            f"Seed A (seedLCRNG) {seed.get('seedLCRNG')}"
            + ("" if confirmed is None else
               "   [forced seed CONFIRMED]" if confirmed else
               "   [FORCED SEED DID NOT TAKE]"))
    if log.mons:
        lines.append("")
        lines.append("battlers at start:")
        for mon in log.mons:
            lines.append(f"  battler {mon.get('battler')}: species {mon.get('species')} "
                         f"Lv {mon.get('level')}  {mon.get('hp')}/{mon.get('maxHp')} HP  "
                         f"stats {mon.get('stats')}")
            lines.append(f"      IVs {mon.get('ivs')}  ability {mon.get('ability')}  "
                         f"moves {mon.get('moves')}  PP {mon.get('pp')}")
    by_site = log.rolls_by_site()
    if by_site and log.phases:
        # With phases in the log the PC is the identity and the symbol name is a hint, so group
        # by address and show what each one was doing. Without phases there is nothing to show
        # but the name, which is the HG/SS reader's case below.
        lines.append("")
        lines.append("rolls by site (R7: the PC is the identity -- `func` can be another "
                     "overlay's symbol):")
        sites = log.sites()
        for addr, count in by_site.most_common():
            names = ", ".join(sorted({r["func"] for r in log.rolls if r["addr"] == addr}))
            lines.append(f"  {count:5}  {addr}  [gdb says: {names}]")
            for where, seen in sites.get(addr, Counter()).most_common(4):
                lines.append(f"            {seen:5}  {where}")
    else:
        by_caller = log.rolls_by_caller()
        if by_caller:
            lines.append("")
            lines.append("rolls by calling function (R7: maps call sites onto phases):")
            for func, count in by_caller.most_common():
                lines.append(f"  {count:5}  {func}")
    if log.marks:
        lines.append("")
        lines.append("rolls between markers (R2 / per-turn counts):")
        for label, count in log.segments():
            lines.append(f"  {count:5}  up to {label!r}")
    sequences = log.end_of_turn_sequences()
    if sequences:
        lines.append("")
        lines.append("end-of-turn rolls, in order (which advance each condition's roll is):")
        for number, sequence in enumerate(sequences, start=1):
            lines.append(f"  sequence {number}: {len(sequence)} roll(s)")
            for roll in sequence:
                lines.append(f"    {roll.ordinal}. {roll.label:<28} {roll.script:<44} "
                             f"val {roll.value}")
    elif log.phases:
        lines.append("")
        lines.append("no end-of-turn rolls: the battle spent none under "
                     + ", ".join(END_OF_TURN_COMMANDS) + ".")
    events = log.damage_events()
    if events:
        lines.append("")
        lines.append("damage taken (R10: each drop and the rolls before it):")
        for event in events:
            moves = "; ".join(m.replace("\n", " ") for m in event.preceding_messages[-2:])
            lines.append(f"  {event.before:4} -> {event.after:4}  "
                         f"({event.damage:3} damage, {len(event.preceding_rolls)} rolls before)"
                         + (f"   [{moves}]" if moves else ""))
    elif not log.hp_changes():
        lines.append("")
        lines.append("no HP readings: the recorder could not do symbolic struct access, so "
                     "R10 cannot be answered from this log (load the .elf with DWARF types).")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print(__doc__)
        print("usage: python -m claytonlib.battle.logcheck <log.jsonl> [...]")
        return 2
    for path in args:
        for index, log in enumerate(load(path)):
            print(f"=== {path} [{index}] " + "=" * 40)
            print(report(log))
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
