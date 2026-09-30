"""Candidate battle seeds for a Battle Compass run (notes/battle_compass.md sec 17.1).

A **uniform (delay x second) grid** around a centre seed, with deliberately **no posterior
weighting**.  That is the opposite choice from Safari Compass, which ranks candidates by landing
probability (``compass/_core.py:calibrated_candidates``) — and the difference is principled:
nothing here needs to *hit* a seed, only to contain the true one, so ranking buys nothing.  It
follows ``metronome_compass._generate_candidates``'s superset approach instead.

**The two axes are not equally identifiable, and the defaults reflect that.**  The frame window
can be generous — move observations pin it easily, and 1201 frame candidates narrow to one in
three turns.  The *second* window cannot: candidates differing only in the RTC second are
invisible to every modulo-based observable, so a second window of 2 stalls at five survivors and
never resolves.  See ``identify.Session.ambiguity``, which explains why.

The reason is structural.  ``calculate_seed`` is ``((mdms << 24) | (hour << 16)) + delay``, so the
second enters through ``mdms`` in the **top 8 bits**, and an LCRNG difference of ``k * 2**24``
stays in the top 8 bits forever.  Every modulus the game takes — ``% 4`` for move choice, ``% 16``
for crits and damage, ``% 100`` for accuracy and secondary procs — reads the *low* bits of the
roll, which are identical across those candidates.  Only a magnitude comparison distinguishes
them, and the shake check ``roll < b`` is the only one in the game.

So ``second_window`` defaults to 0: the model derives the second from real elapsed time and no
amount of play will correct it, which makes widening it a way to become permanently unsure rather
than a safety margin.

Two axes, kept independent:

* the **frame** (the absolute delay counter) comes from ``model.frame(M, base_low16)``;
* the **RTC second** comes from ``model.battle_second_offset(M)`` — that is, from *real time*,
  ``round(M/1000 + rtc_offset_seconds)`` — and is held **fixed** across the whole frame window.

Deriving the second from the frame instead couples two axes that miss near-independently, and
doing exactly that once produced a Safari candidate set disjoint from the chart scorer's
(notes/seed_hitting_process.md sec 3-4).  The same mistake is available here, so the second is a
separate offset rather than a function of the frame.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from claytonlib.times import calculate_seed, get_times

#: A window costs about this many candidates per second of slack (two seeds per delay).
CANDIDATES_PER_SECOND = 120


@dataclass(frozen=True)
class Candidate:
    """One possible battle seed, with where in the grid it came from."""
    seed: int
    frame: int
    second: int

    @property
    def frame_delta(self) -> int:
        """Set by :func:`generate`; kept here so a candidate can be sorted by proximity."""
        return 0


@dataclass(frozen=True)
class CandidateWindow:
    """The grid to search, and what centred it."""
    key_seed: int
    initial_time: dt.datetime
    vector_ms: float
    frame_centre: int
    second_centre: int
    frame_window: int
    second_window: int
    candidates: tuple[Candidate, ...]

    def __len__(self) -> int:
        return len(self.candidates)

    @property
    def seeds(self) -> tuple[int, ...]:
        return tuple(c.seed for c in self.candidates)

    def by_seed(self) -> dict[int, Candidate]:
        return {c.seed: c for c in self.candidates}


def centre(model, key_seed: int, vector_ms: float) -> tuple[int, int]:
    """(frame, second) the window is built around.

    The frame comes from the fitted model; the second from real elapsed time. Kept separate on
    purpose — see the module docstring.
    """
    frame = round(model.frame(vector_ms, key_seed & 0xFFFF))
    return frame, model.battle_second_offset(vector_ms)


def generate(model, *, key_seed: int, initial_time: dt.datetime, vector_ms: float,
             frame_window: int = 60, second_window: int = 0) -> CandidateWindow:
    """Every seed in the (frame x second) grid around the model's centre.

    Frames below the key seed's own base delay are skipped: the battle seed cannot precede the
    initial seed it was generated after.

    ``second_window`` defaults to 0 deliberately — see the module docstring. Widening it adds
    candidates that observation cannot separate, so it trades a pinned seed for a permanently
    ambiguous one.
    """
    if frame_window < 0 or second_window < 0:
        raise ValueError("windows cannot be negative")
    frame_centre, second_centre = centre(model, key_seed, vector_ms)
    base_delay, _ = get_times(key_seed)

    seen: set[int] = set()
    found: list[Candidate] = []
    for frame in range(frame_centre - frame_window, frame_centre + frame_window + 1):
        if frame < base_delay:
            continue
        for second in range(second_centre - second_window, second_centre + second_window + 1):
            if second < 0:
                continue
            seed = calculate_seed(initial_time + dt.timedelta(seconds=second), frame)
            if seed in seen:
                continue
            seen.add(seed)
            found.append(Candidate(seed=seed, frame=frame, second=second))

    # Nearest the centre first, so a truncated display shows the likeliest rows even though the
    # set itself is unweighted.
    found.sort(key=lambda c: (abs(c.frame - frame_centre), abs(c.second - second_centre), c.seed))
    return CandidateWindow(
        key_seed=key_seed, initial_time=initial_time, vector_ms=vector_ms,
        frame_centre=frame_centre, second_centre=second_centre,
        frame_window=frame_window, second_window=second_window,
        candidates=tuple(found))


def estimate_size(frame_window: int, second_window: int) -> int:
    """How many candidates a window will hold, before generating it.

    Worth having because the UI can warn about an unaffordable window rather than hanging on
    one: the practical limit is compute on the first turn's sweep, not information.
    """
    return (2 * frame_window + 1) * (2 * second_window + 1)
