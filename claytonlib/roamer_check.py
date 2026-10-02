"""Does the low bit of one roll decide whether you meet the roamer?

`getRandomActiveRoamerInCurrMap` (src/field/encounter_check.c) is the only gate on a roamer
encounter.  Reading the decompilation, it is:

    if (nRoamers == 0)       return FALSE;      # no roamer on this map
    if (LCRandRange(2) == 0) return FALSE;      # a 50/50 coin flip
    if (nRoamers > 1) chosen = LCRandRange(nRoamers);
    return TRUE;

and `LCRandRange(n)` is `LCRandom() % n`, where `LCRandom()` returns `advance_rng(state) >> 16`.
So the prediction ought to be **one bit of one roll**: you meet the roamer iff that roll is odd.

That is a claim about the game, not about this file, and the figure disagrees with a believed
1-in-4 from play experience.  So this module exists to be *checked against a recording* rather
than trusted: `utils/gdb-overworld-reader.py` captures the rolls an encounter check actually
consumed and whether a roamer resulted, and :func:`verify` says whether the bit predicted it.

**Why the recorder brackets rather than attributes.** `LCRandRange` is `static inline`, so it
has no symbol of its own and the flip cannot be hooked directly.  The obvious alternative --
hook `LCRandom` and look at the caller -- is exactly what misled this project once before: gdb
resolves a caller address to the nearest symbol, which attributed six battle-start advances to a
function that makes no RNG call at all (notes/battle_compass.md sec 16.2).  So the recorder
breaks on the *entry and return* of `getRandomActiveRoamerInCurrMap` and treats every roll
in between as belonging to it.  That needs no symbolisation and cannot be fooled by a
neighbouring function.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from claytonlib.safari import advance_rng

#: What the decompilation says: the roamer wins when ``LCRandom() % 2`` is non-zero.
ROAMER_WINS_ON_ODD_ROLL = True


def predict_from_roll(roll: int) -> bool:
    """Whether this roll's value means "roamer", per the decompilation.

    `roll` is what `LCRandom()` returned — the high 16 bits of the advanced state.
    """
    return (roll % 2) != 0


def predict_from_state(seed: int, frame: int) -> bool:
    """Whether Sweet-Scenting on advance `frame` of `seed` meets the roamer.

    The flip is the FIRST roll of a Sweet Scent check (there is no encounter-rate roll on that
    path), so it is the roll one advance past the frame — the same roll
    ``safari_encounters.frame_slot`` reads for the encounter slot, taken ``% 2`` instead of
    ``% 10``.  Only meaningful where an active roamer is on the map; elsewhere the check spends
    no roll at all and this frame arithmetic does not apply.
    """
    if frame < 0:
        raise ValueError(f"frame cannot be negative: {frame}")
    state = seed
    for _ in range(frame + 1):
        state = advance_rng(state)
    return predict_from_roll(state >> 16)


def roamer_frames(seed: int, limit: int, start: int = 0) -> list[int]:
    """Every frame in ``[start, limit)`` that the prediction says gives a roamer."""
    return [f for f in range(start, limit) if predict_from_state(seed, f)]


@dataclass
class CheckEvent:
    """One recorded call to the roamer check.

    `rolls` is every roll consumed between the call's entry and its return, in order —
    whatever the game actually spent, not what we expected it to spend. Its LENGTH is itself a
    measurement:

    * **0** — the check returned without rolling, so no active roamer was on the map.
    * **1** — the flip alone decided it, either way. This is the case the decompilation says is
      universal once a roamer is present.
    * **2+** — a tiebreak roll fired, meaning two or more roamers were found on one map. Reading
      `RoamerLocationSetRandom`, that should be impossible: Raikou and Entei draw locations only
      from the Johto index range and the Lati twin only from Kanto. A 2 here would disprove that.
    """
    rolls: tuple[int, ...]
    #: What the function returned — True when a roamer battle followed.
    roamer: bool
    #: Set when `initRoamingWildmon` was seen, which only happens on a roamer battle. An
    #: independent witness to `roamer`, so a disagreement means the recorder is wrong.
    confirmed_roamer: bool | None = None
    #: Roll index within the whole recording, for locating this event in the stream.
    first_roll_index: int | None = None
    label: str = ""

    @property
    def spent(self) -> int:
        return len(self.rolls)

    @property
    def flip(self) -> int | None:
        """The coin-flip roll, or None if the check never got that far."""
        return self.rolls[0] if self.rolls else None

    @property
    def predicted(self) -> bool | None:
        """What the bit says should have happened. None when no flip was spent."""
        return None if self.flip is None else predict_from_roll(self.flip)

    @property
    def agrees(self) -> bool | None:
        """Whether the prediction matched reality. None when there was nothing to predict."""
        return None if self.predicted is None else self.predicted == self.roamer


@dataclass
class Verdict:
    """The answer, and enough detail to act on a wrong one."""
    events: list[CheckEvent] = field(default_factory=list)

    @property
    def testable(self) -> list[CheckEvent]:
        """Events that spent a flip, so there was something to predict."""
        return [e for e in self.events if e.flip is not None]

    @property
    def agreed(self) -> int:
        return sum(1 for e in self.testable if e.agrees)

    @property
    def disagreed(self) -> list[CheckEvent]:
        return [e for e in self.testable if e.agrees is False]

    @property
    def roamer_rate(self) -> float | None:
        """Observed fraction of flips that produced a roamer — the 1/2-versus-1/4 question.

        Measured over events that actually spent a flip, which is the right denominator: a check
        that found no roamer on the map never flipped and says nothing about the rate.
        """
        t = self.testable
        return (sum(1 for e in t if e.roamer) / len(t)) if t else None

    @property
    def inconsistent_witnesses(self) -> list[CheckEvent]:
        """Events where `initRoamingWildmon` disagreed with the return value.

        Not a statement about the game — a statement about the recording. Either hook being
        wrong invalidates the rest, so these are separated out rather than counted as failures.
        """
        return [e for e in self.events
                if e.confirmed_roamer is not None and e.confirmed_roamer != e.roamer]

    @property
    def tiebreaks(self) -> list[CheckEvent]:
        return [e for e in self.events if e.spent > 1]

    @property
    def ok(self) -> bool:
        return (bool(self.testable) and not self.disagreed
                and not self.inconsistent_witnesses)

    def summary(self) -> str:
        if not self.events:
            return "No roamer checks recorded. Was an active roamer on the map?"
        lines = [f"{len(self.events)} roamer check(s) recorded, "
                 f"{len(self.testable)} of which spent a coin flip."]
        no_roll = len(self.events) - len(self.testable)
        if no_roll:
            lines.append(f"  {no_roll} spent no roll at all -- no active roamer on that map.")
        if self.testable:
            lines.append(f"  the bit predicted the outcome {self.agreed}/{len(self.testable)} "
                         f"times.")
            rate = self.roamer_rate
            lines.append(f"  observed roamer rate: {rate:.1%} "
                         f"({sum(1 for e in self.testable if e.roamer)}/{len(self.testable)}) "
                         f"-- the decompilation says 50%.")
        for e in self.disagreed:
            lines.append(f"  MISMATCH at roll {e.first_roll_index}: flip {e.flip} is "
                         f"{'odd' if e.flip % 2 else 'even'} so the bit predicted "
                         f"{'roamer' if e.predicted else 'normal'}, but the game gave "
                         f"{'roamer' if e.roamer else 'normal'}.")
        for e in self.tiebreaks:
            lines.append(f"  TIEBREAK at roll {e.first_roll_index}: {e.spent} rolls spent, so "
                         f"two or more roamers were on one map -- which "
                         f"RoamerLocationSetRandom says cannot happen.")
        for e in self.inconsistent_witnesses:
            lines.append(f"  RECORDER PROBLEM at roll {e.first_roll_index}: the check returned "
                         f"{e.roamer} but initRoamingWildmon said {e.confirmed_roamer}. Fix the "
                         f"recording before believing anything above.")
        if self.ok:
            lines.append("  VERDICT: the low bit of the flip predicted every outcome.")
        return "\n".join(lines)


def verify(events) -> Verdict:
    """Check a list of :class:`CheckEvent` (or dicts shaped like one) against the prediction."""
    out = []
    for e in events:
        out.append(e if isinstance(e, CheckEvent) else CheckEvent(
            rolls=tuple(e["rolls"]), roamer=bool(e["roamer"]),
            confirmed_roamer=e.get("confirmed_roamer"),
            first_roll_index=e.get("first_roll_index"), label=e.get("label", "")))
    return Verdict(events=out)


def load(path: str | Path) -> list[Verdict]:
    """One Verdict per recorded session in a `.jsonl` written by the overworld reader."""
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        doc = json.loads(line)
        out.append(verify(doc.get("roamer_checks", [])))
    return out
