"""Candidate battle seeds for a Battle Compass run (notes/battle_compass.md sec 17.1).

A **uniform (delay x second) grid** around a centre seed, with deliberately **no posterior
weighting**.  That is the opposite choice from Safari Compass, which ranks candidates by landing
probability (``compass/_core.py:calibrated_candidates``) — and the difference is principled:
nothing here needs to *hit* a seed, only to contain the true one, so ranking buys nothing.  It
follows ``metronome_compass._generate_candidates``'s superset approach instead.

**The two axes are not equally identifiable, and the defaults reflect that.**  The frame window
can be generous -- move choices, crits and damage rolls all separate frames quickly.  The RTC
second is far slower, for a reason worth spelling out because an earlier version of this file got
the conclusion wrong.

``calculate_seed`` builds the seed as ``((mdms << 24) | (hour << 16)) + delay``, so the frame
lands in the low 16 bits while the second enters through ``mdms`` in the **top 8 bits**.  An
LCRNG difference of ``k * 2**24`` then stays a multiple of ``2**24`` forever, since
``(2**24 * c) * A mod 2**32 == 2**24 * (c * A mod 2**8)``.  That invariant is real.

**What does not follow -- and what this file previously claimed -- is that the game cannot see
it.**  A roll is ``state >> 16``, so it differs by ``256 * c``, and 256 is a multiple of 4 and 16
but not of 100.  So the ``% 4`` move choice and the ``% 16`` crit and damage rolls genuinely are
identical, but ``% 100`` accuracy checks and secondary-effect procs are not, and neither is the
shake check's magnitude comparison ``roll < b``.

Second-siblings therefore **do** separate.  Slowly, and slowly for a matchup-specific reason: no
move in the section 11 fixture can miss (every accuracy is 100 or 0), so the accuracy verdict is
invisible and it comes down to Aurora Beam's 10% Attack drop -- Aurora Beam chosen one turn in
four, and the two rolls straddling the threshold about a fifth of the time.  Measured over 120
second-apart pairs: all separated, **median 19 turns, max 54**.

``second_window`` still defaults to 0, but for the honest reason: five times the candidates and
~19 extra turns is a poor trade when ``rtc_offset_seconds`` normally pins the second already.  A
set stuck on seconds is waiting for turns, not doomed.

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

    def frame_delta(self, centre: int) -> int:
        """Signed miss in frames from the frame this window was centred on.

        Takes the centre rather than storing it. An earlier version was a no-argument property
        returning a hardcoded ``0``, documented as "set by :func:`generate`" -- which `generate`
        could not do, since this is a frozen dataclass and that was a property. It was never
        read, so the zero never surfaced; a stored delta would also have gone stale the moment
        ``HuntSession.rebase`` widened the window under it.

        Sign follows ``calibration_tools``: actual minus target, so positive is late.
        """
        return self.frame - centre

    def second_delta(self, centre: int) -> int:
        """Signed miss in RTC seconds. The two axes miss near-independently
        (notes/seed_hitting_process.md sec 3-4), which is why both are worth reporting."""
        return self.second - centre


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
    #: The key seed's own base delay. A battle seed cannot precede the initial seed it was
    #: generated after, so frames below this are skipped.
    base_delay: int = 0
    #: How many frames that rule removed. Nonzero with an empty result is the whole explanation:
    #: the window is centred before the run even started.
    skipped_below_base_delay: int = 0

    def __len__(self) -> int:
        return len(self.candidates)

    def why_empty(self) -> str | None:
        """Why there are no candidates, in terms the player can act on. None if there are some.

        Worth spelling out rather than reporting a bare zero, because the two causes need
        opposite fixes: a window centred below the base delay needs a *later* target, while a
        window that is merely too narrow needs a wider one.
        """
        if self.candidates:
            return None
        if self.skipped_below_base_delay:
            return (
                f"The window centres on frame {self.frame_centre}, before Seed A's own frame "
                f"{self.base_delay} — and Seed B cannot precede the seed it was generated "
                f"after, so all {self.skipped_below_base_delay} frames were skipped. Vector ms "
                f"is the gap between Seed A and Seed B, so a value this small leaves no room; "
                f"check it is in MILLISECONDS.")
        return ("The window generated no seeds at all. Check the key seed, initial time and "
                "vector ms — one of them is almost certainly not what you played.")

    @property
    def seeds(self) -> tuple[int, ...]:
        return tuple(c.seed for c in self.candidates)

    def by_seed(self) -> dict[int, Candidate]:
        return {c.seed: c for c in self.candidates}


def seed_a_delay(key_seed: int, initial_time: dt.datetime) -> int:
    """Seed A's own delay, recovered from the key seed and the target year.

    ``calculate_seed`` masks ``delay + year - 2000`` into the low 16 bits, so this inverts that
    for *this* year — which is what makes the frame difference below add on cleanly. Same
    derivation as ``app.metronome._target_delay_for_key_seed``.
    """
    return (key_seed & 0xFFFF) - (initial_time.year - 2000)


def centre(model, key_seed: int, vector_ms: float,
           initial_time: dt.datetime | None = None) -> tuple[int, int]:
    """(frame, second) the window is built around.

    **Vector ms is a difference, not a position.** It is the gap between Seed A (the key seed)
    and Seed B, so the battle frame is Seed A's delay *plus* the predicted frame difference. An
    earlier version of this function used ``model.frame(...)`` directly as an absolute frame,
    which put the centre a couple of hundred frames *below* the key seed's own delay and made
    every window empty — see ``app.metronome.seed_b_center``, which has always done it correctly
    and is what this now matches:

    * frame — ``model.frame(M, base_low16)`` is the battle seed's low16 field, so subtracting
      ``base_low16`` leaves the pure frame difference. That difference is year-independent, and
      so adds cleanly onto Seed A's own year-adjusted delay.
    * second — from REAL elapsed time, never from the frame counter, which lags across loads
      (notes/seed_hitting_process.md).

    `initial_time` is only needed for its year. It is optional for callers that predate this
    fix; without it the year is taken as 2000, which is the identity case.
    """
    base_low16 = key_seed & 0xFFFF
    a_delay = (seed_a_delay(key_seed, initial_time) if initial_time is not None
               else base_low16)
    frame_difference = round(model.frame(vector_ms, base_low16) - base_low16)
    return a_delay + frame_difference, model.battle_second_offset(vector_ms)


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
    frame_centre, second_centre = centre(model, key_seed, vector_ms, initial_time)
    # Seed B cannot precede Seed A. The floor is Seed A's own delay for this year, not
    # get_times()'s year-2000 delay -- those differ by (year - 2000) and comparing against the
    # wrong one rejects legitimate frames.
    base_delay = seed_a_delay(key_seed, initial_time)

    seen: set[int] = set()
    found: list[Candidate] = []
    skipped = 0
    for frame in range(frame_centre - frame_window, frame_centre + frame_window + 1):
        if frame < base_delay:
            skipped += 1
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
        candidates=tuple(found), base_delay=base_delay, skipped_below_base_delay=skipped)


def estimate_size(frame_window: int, second_window: int) -> int:
    """How many candidates a window will hold, before generating it.

    Worth having because the UI can warn about an unaffordable window rather than hanging on
    one: the practical limit is compute on the first turn's sweep, not information.
    """
    return (2 * frame_window + 1) * (2 * second_window + 1)
