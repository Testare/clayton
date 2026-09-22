"""metronome.py — Metronome Compass seed identification, wrapped for the UI.

Thin, JSON-friendly wrappers over ``claytonlib.calibration_tools`` so the facade can
drive Seed A (roamer routes + Elm calls) and Seed B (Metronome battle paths) without
the notebook's interactive ``input()`` flow. The heavy lifting — the LCRNG walks —
stays in claytonlib; here we only shape inputs/outputs and apply the pure filters.

Seed A narrowing (REL + Elm) is done here because those filters are simple and pure.
Seed B is generated with each candidate's precomputed battle path; picking the seed
from what you observe is left to the caller for now (the notebook's turn-by-turn
narrowing is stateful and will be reconnected later).
"""
from __future__ import annotations

import datetime as dt

from claytonlib.calibration_tools import (
    elm_calls,
    filter_elm,
    generate_candidates_near,
    generate_roamer_candidates_near,
    narrow_candidates,
    roamer_positions,
)

_TIME_FMT = "%Y-%m-%dT%H:%M:%S"
_ELM_DISPLAY = 15  # how many Elm calls to precompute/show
_REL_WILDCARDS = (".", "-", "*", "?")


def _parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def _clean_prev_routes(prev: dict | None) -> dict:
    """Keep only roaming legendaries (a null/absent value means 'not roaming')."""
    out = {}
    for k in ("r", "e", "l"):
        v = (prev or {}).get(k)
        if v is not None and str(v).strip() != "":
            out[k] = int(v)
    return out


def _target_delay_for_key_seed(key_seed: int, target_time: dt.datetime) -> int:
    """The delay to search around, derived from the key seed and target_time alone.

    seed_for() masks (delay + year - 2000) & 0xFFFF into a seed's low 16 bits (see its
    docstring). The caller never supplies or sees a delay: given only the key seed
    (not whatever delay/year originally produced it) and target_time's year, we can
    still recover a delay that reconstructs the key seed's low-16 field for THIS
    year — so a fresh candidate generated at that delay lines up with the key seed
    regardless of what calendar year target_time happens to use. This only cancels
    correctly when the key seed's own low-16 also used this method's target year (the
    ordinary case: a key seed picked for this hunting session), but needs no input
    either way — the delay is never the user's concern.
    """
    key_low16 = key_seed & 0xFFFF
    return key_low16 - (target_time.year - 2000)


def _rel_predicate(observed: str, keys: list[str]):
    """A lenient REL match predicate from a live, possibly-partial observed string.

    - A missing token (not yet typed) or a wildcard (. - * ?) constrains nothing.
    - A single-digit token for R or E is a tens-place prefix: every real R/E route is
      two digits, so a lone digit can only be a still-being-typed tens place (e.g. "4"
      matches any actual route starting with "4" — since only routes 42-46 actually
      occur, this naturally narrows to exactly that, no range table needed).
    - L is always matched as an exact number — it has genuine single-digit routes.
    - Extra tokens beyond `keys` are ignored (still typing); a non-digit token makes
      the whole predicate unusable.

    Returns (predicate(candidate_row) -> bool, ok). ok=False means "can't parse this
    yet" — the caller shows no candidates without raising, so a lone keystroke never
    surfaces as an error.
    """
    tokens = observed.strip().split()[:len(keys)]
    wanted: dict[str, tuple[str, object]] = {}
    for key, tok in zip(keys, tokens):
        if tok in _REL_WILDCARDS:
            continue
        if not tok.isdigit():
            return None, False
        if key == "l" or len(tok) >= 2:
            wanted[key] = ("eq", int(tok))
        else:  # single digit, R or E -> tens-place prefix
            wanted[key] = ("prefix", tok)

    def predicate(c: dict) -> bool:
        for key, (kind, val) in wanted.items():
            route = c.get(f"{key}_route")
            if route is None:
                return False
            if kind == "eq" and route != val:
                return False
            if kind == "prefix" and not str(route).startswith(val):
                return False
        return True

    return predicate, True


# --- Seed A (initial seed: roamer routes + Elm) ---------------------------

def _row_a_json(r: dict) -> dict:
    return {
        "seed": r["seed"], "seed_hex": f"0x{r['seed']:08X}",
        "time": r["time"].strftime(_TIME_FMT), "delay": r["delay"],
        "sec_delta": r["sec_delta"], "delay_delta": r["delay_delta"],
        "r_route": r["r_route"], "e_route": r["e_route"], "l_route": r["l_route"],
        "rng_calls": r["rng_calls"], "elm": r["elm"],
    }


def seed_a(params: dict) -> dict:
    """Candidate initial seeds around a target, narrowed by observed REL and Elm.

    params: target_time (ISO), key_seed, prev_routes {r,e,l}, seconds_window,
            delay_window, match_parity, and optionally rel_observed / elm_observed.
    The search delay is derived from key_seed + target_time — never a caller input.
    """
    prev = _clean_prev_routes(params.get("prev_routes"))
    target_time = _parse_time(params["target_time"])
    target_delay = _target_delay_for_key_seed(int(params["key_seed"]), target_time)
    rows = generate_roamer_candidates_near(
        target_time,
        target_delay,
        int(params.get("seconds_window", 2)),
        int(params.get("delay_window", 10)),
        prev,
        elm_count=_ELM_DISPLAY,
        match_parity=bool(params.get("match_parity", False)),
    )
    roamers = [k for k in ("r", "e", "l") if k in prev]

    rel_valid = True
    rel = (params.get("rel_observed") or "").strip()
    if rel:
        predicate, rel_valid = _rel_predicate(rel, roamers)
        rows = [r for r in rows if predicate(r)] if rel_valid else []

    elm = (params.get("elm_observed") or "").strip().upper()
    if elm:
        rows = filter_elm(rows, elm)

    return {
        "candidates": [_row_a_json(r) for r in rows],
        "count": len(rows),
        "roamers": roamers,
        "rel_valid": rel_valid,
    }


def key_seed_info(key_seed: int, prev_routes: dict | None) -> dict:
    """The key seed's own roamer routes + Elm sequence (Seed-to-Time style readout)."""
    prev = _clean_prev_routes(prev_routes)
    routes, calls, state = roamer_positions(int(key_seed), prev)
    return {
        "r_route": routes["r"], "e_route": routes["e"], "l_route": routes["l"],
        "rng_calls": calls, "elm": "".join(elm_calls(state, _ELM_DISPLAY)),
    }


def times_on_date(key_seed: int, month: int | None = None, day: int | None = None,
                  second: int | None = None) -> list[str]:
    """Every valid initial time for `key_seed` (from claytonlib.times.get_times, which is
    itself cached per key seed), optionally filtered to a month (1-12), a day-of-month
    (1-31), and/or a second-of-minute (0-59) — any combination, all independent and
    optional. With none set, every valid time is returned. Powers the "pick from a
    calendar" flow for Initial-time fields — the set of times you could ever load this key
    seed at is fixed and small enough to just enumerate and let the user click one.

    generate_times() stamps every time with a nominal placeholder year (calculate_seed
    never reads the year — only month/day/hour/minute/second matter to the RNG). When
    month and/or day narrows the result, matches are re-stamped with the CURRENT real
    year purely for a friendlier display (the game itself doesn't care what year you load
    it — the picker says so) — a Feb 29 match is dropped silently if the current year
    isn't a leap year (not a real date to load on this year). With neither set, the
    placeholder year is left as-is.
    """
    from claytonlib.times import get_times
    restamp_year = dt.date.today().year if (month is not None or day is not None) else None
    _delay, times = get_times(int(key_seed))
    out = []
    for t in times:
        if second is not None and t.second != second:
            continue
        if month is not None and t.month != month:
            continue
        if day is not None and t.day != day:
            continue
        if restamp_year is not None:
            try:
                t = t.replace(year=restamp_year)
            except ValueError:
                continue
        out.append(t.strftime(_TIME_FMT))
    return sorted(out)


# --- Seed B (battle seed: Metronome paths) --------------------------------

def _metronome_moves(path) -> list[dict]:
    """The Metronome moves in a precomputed battle path, one entry per turn that used one
    (matches the notebook's narrow_candidates() readout) — lets the New Run summary show
    the whole move sequence for the identified seed, not just the raw path_str token
    string, so the user can visually confirm they hit the seed they expected."""
    from claytonlib.metronome_compass.path import MetronomeMove
    from claytonlib.moves import _moves_by_number
    moves_by_num = _moves_by_number()
    out = []
    for turn_idx, turn in enumerate(path):
        for tok in turn:
            if isinstance(tok, MetronomeMove):
                m = moves_by_num.get(tok.move_num)
                out.append({"turn": turn_idx + 1, "move_num": tok.move_num,
                            "move_name": m.name if m else f"M{tok.move_num:03d}"})
                break
    return out


def _row_b_json(r: dict) -> dict:
    return {
        "seed": r["seed"], "seed_hex": f"0x{r['seed']:08X}",
        "time": r["time"].strftime(_TIME_FMT), "delay": r["delay"],
        "sec_delta": r["sec_delta"], "delay_delta": r["delay_delta"],
        "path_str": r["path_str"],
        "metronome_moves": _metronome_moves(r["path"]),
    }


def seed_b_center(key_seed: int, target_time: dt.datetime, vector_ms, model):
    """The (time, delay) Seed B is PREDICTED to land on — what a Seed B search centers on.

    Seed B is the battle seed generated `vector_ms` after Seed A, so it is neither at Seed A's
    delay nor at Seed A's RTC second, and searching around Seed A (which this used to do) can
    only ever find it by brute-forcing a delay window thousands wide. Both coordinates come
    from the calibration model, exactly as Safari Compass's own Seed B search already did
    (CompassSafariInput.from_expedition_target):

    * delay — Seed A's search delay plus the predicted dF. `model.frame(M, base_low16)` is the
      battle seed's low16 field; subtracting base_low16 leaves the pure frame difference, which
      is year-independent and so adds cleanly onto Seed A's own year-adjusted search delay.
    * time — the RTC clock runs during the countdown, so Seed B's second is Seed A's plus
      `M/1000 + rtc_offset_seconds` (rounded). Derived from REAL time, never from the frame
      counter, which lags across loads (see notes/seed_hitting_process.md).
    """
    a_delay = _target_delay_for_key_seed(key_seed, target_time)
    if model is None or vector_ms in (None, ""):
        raise ValueError(
            "Seed B needs the Vector ms and a calibration model to know where to look — "
            "set a target (Initial time + Vector ms) before starting Seed B.")
    M = float(vector_ms)
    base_low16 = key_seed & 0xFFFF
    dF = model.frame(M, base_low16) - base_low16
    b_delay = a_delay + round(dF)
    b_time = target_time + dt.timedelta(
        seconds=round(M / 1000.0 + model.rtc_offset_seconds))
    return b_time, b_delay


def seed_b(params: dict, model=None) -> dict:
    """Candidate battle seeds around the PREDICTED Seed B, each with its Metronome path.

    params: target_time (ISO — Seed A's target), key_seed, vector_ms, magikarp_level,
            opposite_gender, seconds_window, delay_window, metronome_only, limit.
    `model` is the profile's active calibration model; see seed_b_center for why both the
    search delay and the search time have to come from it.
    """
    target_time = _parse_time(params["target_time"])
    b_time, b_delay = seed_b_center(
        int(params["key_seed"]), target_time, params.get("vector_ms"), model)
    rows = generate_candidates_near(
        b_time,
        b_delay,
        int(params.get("seconds_window", 2)),
        int(params.get("delay_window", 10)),
        magikarp_level=int(params["magikarp_level"]),
        opposite_gender=bool(params["opposite_gender"]),
        metronome_only=bool(params.get("metronome_only", False)),
    )
    limit = int(params.get("limit", 15))
    return {"candidates": [_row_b_json(r) for r in rows[:limit]], "count": len(rows)}


def seed_b_runner(params: dict, model=None):
    """Build a ``runner(input_fn, output_fn) -> candidate|None`` for a narrowing session.

    Generates the full candidate set (with precomputed battle paths) once, then hands
    back a closure the session thread runs: it drives ``narrow_candidates`` with the
    injected callbacks so the UI can answer the battle questions one at a time.
    """
    level = int(params["magikarp_level"])
    opp = bool(params["opposite_gender"])
    metronome_only = bool(params.get("metronome_only", False))
    target_time = _parse_time(params["target_time"])
    b_time, b_delay = seed_b_center(
        int(params["key_seed"]), target_time, params.get("vector_ms"), model)
    candidates = generate_candidates_near(
        b_time,
        b_delay,
        int(params.get("seconds_window", 2)),
        int(params.get("delay_window", 10)),
        magikarp_level=level,
        opposite_gender=opp,
        metronome_only=metronome_only,
    )

    def runner(input_fn, output_fn):
        return narrow_candidates(
            candidates, level, opp, metronome_only=metronome_only,
            input_fn=input_fn, output_fn=output_fn,
        )

    return runner
