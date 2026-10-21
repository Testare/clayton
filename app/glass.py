"""glass.py — Glass's own small shaping: the delay readout, and a history entry.

Glass is deliberately the thinnest tool in the app: every RNG call it makes already exists and
is already called from two other places (``app.metronome.seed_a`` for Seed A candidates,
``app.safari_compass.identify_seed_a_frame`` / ``plan_frame_route`` for the advance frame). The
only thing it needs that nothing else does is the **absolute delay** — the number to dial into
the timer — and the year that decides it. That lives here, with the one validity check the other
tools never have to make. See ``notes/glass.md``.
"""
from __future__ import annotations

import datetime as dt

from app.metronome import target_delay_for_key_seed

# A DS clock reads 0-23. The hour is a whole byte of the seed (bits 16-23), so a hand-typed key
# seed can easily carry an hour no clock could ever show -- which makes the seed unreachable,
# and makes claytonlib.times.generate_times emit unparseable times like "2000-01-01 255:00:00"
# (get_times then raises on strptime). Checking it here is what keeps the picker off that path.
_MAX_HOUR = 23

#: The fields a history entry is allowed to carry, in display order. Anything else the page
#: sends is dropped rather than stored: the history is a scratchpad, and an open-ended dict
#: would quietly become a second, undocumented place where run data lives.
#:
#: `elm_heard` is HGSS-only, and there is no Platinum sibling: a Platinum frame is counted rather
#: than heard, so there is nothing the player reported to record. What a Platinum entry carries
#: instead is `frame` and `routed_to` — where they started and where they went (clayton-6xu.5).
_HISTORY_FIELDS = ("seed", "seed_hex", "time", "delay", "delay_delta", "sec_delta",
                   "elm_heard", "frame", "routed_to")


def _parse_time(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat((value or "").strip())
    except (TypeError, ValueError):
        return None


def readout(key_seed: int | None, initial_time: str = "") -> dict:
    """What Glass can say about a key seed on its own: hour, time-of-day bucket, delay.

    Returns ``{key_seed, key_seed_hex, hour, time_of_day, year, delay, problem}``, where every
    value it cannot derive is ``None`` and ``problem`` says why in a sentence the page can print
    as-is.

    The delay is ``(key_seed & 0xFFFF) - (year - 2000)`` — see ``target_delay_for_key_seed`` for
    why the year is in there at all. Two things can stop it:

    * an hour byte above 23, which means no DS clock can produce this seed at all;
    * a year beyond ``2000 + (key_seed & 0xFFFF)``, which would need a negative delay (and
      ``generate_roamer_candidates_near`` skips negative delays outright, so the candidate
      search would silently come back empty rather than complain).
    """
    out = {"key_seed": None, "key_seed_hex": "", "hour": None, "time_of_day": None,
           "year": None, "delay": None, "problem": ""}
    if key_seed is None or key_seed == "":
        out["problem"] = "no key seed yet"
        return out

    key_seed = int(key_seed)
    out["key_seed"] = key_seed
    out["key_seed_hex"] = f"0x{key_seed:08X}"

    hour = (key_seed >> 16) & 0xFF
    if hour > _MAX_HOUR:
        out["problem"] = (f"no DS clock can produce this seed — its hour byte is {hour}, "
                          f"and a clock only reaches {_MAX_HOUR}")
        return out
    out["hour"] = hour
    from claytonlib.safari_encounters import time_of_day
    out["time_of_day"] = time_of_day(hour)

    when = _parse_time(initial_time)
    if when is None:
        out["problem"] = "pick an initial time to see the delay"
        return out
    out["year"] = when.year

    delay = target_delay_for_key_seed(key_seed, when)
    if delay < 0:
        last = 2000 + (key_seed & 0xFFFF)
        out["problem"] = (f"year {when.year} cannot reach this seed — the delay would be "
                          f"{delay}. The last year that can is {last}.")
        return out
    out["delay"] = delay
    return out


def history_entry(payload: dict | None) -> dict:
    """One identification, stamped and trimmed to the fields the history displays."""
    payload = payload or {}
    entry = {"saved_at": dt.datetime.now().isoformat(timespec="seconds")}
    for key in _HISTORY_FIELDS:
        value = payload.get(key)
        if value not in (None, ""):
            entry[key] = value
    return entry
