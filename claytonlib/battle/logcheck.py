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


class BattleLog:
    """One recorded battle."""

    def __init__(self, doc: dict):
        self.label: str = doc.get("label", "")
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

    def rolls_by_caller(self) -> Counter:
        """How many rolls each calling function requested.

        The first thing to look at in a new log: it tells you which of the ROM's call sites this
        matchup actually exercises, and how often.
        """
        return Counter(roll["func"] for roll in self.rolls)

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
        f"battle: {log.label or '(unlabelled)'}   recorded {log.recorded_at or '?'}",
        f"forced seed: {log.forced_seed or 'none'}",
        f"records: {len(log.records)}  rolls: {len(log.rolls)}  "
        f"messages: {len(log.messages)}  marks: {len(log.marks)}",
    ]
    if log.mons:
        lines.append("")
        lines.append("battlers at start:")
        for mon in log.mons:
            lines.append(f"  battler {mon.get('battler')}: species {mon.get('species')} "
                         f"Lv {mon.get('level')}  {mon.get('hp')}/{mon.get('maxHp')} HP  "
                         f"stats {mon.get('stats')}")
            lines.append(f"      IVs {mon.get('ivs')}  ability {mon.get('ability')}  "
                         f"moves {mon.get('moves')}  PP {mon.get('pp')}")
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
