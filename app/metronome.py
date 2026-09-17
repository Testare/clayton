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
    filter_rel,
    generate_candidates_near,
    generate_roamer_candidates_near,
    narrow_candidates,
    roamer_positions,
)

_TIME_FMT = "%Y-%m-%dT%H:%M:%S"
_ELM_DISPLAY = 15  # how many Elm calls to precompute/show


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

    params: target_time (ISO), target_delay, prev_routes {r,e,l}, seconds_window,
            delay_window, match_parity, and optionally rel_observed / elm_observed.
    """
    prev = _clean_prev_routes(params.get("prev_routes"))
    rows = generate_roamer_candidates_near(
        _parse_time(params["target_time"]),
        int(params["target_delay"]),
        int(params.get("seconds_window", 2)),
        int(params.get("delay_window", 10)),
        prev,
        elm_count=_ELM_DISPLAY,
        match_parity=bool(params.get("match_parity", False)),
    )
    rel = (params.get("rel_observed") or "").strip()
    if rel:
        rows, _keys, _tokens = filter_rel(rows, rel)
    elm = (params.get("elm_observed") or "").strip().upper()
    if elm:
        rows = filter_elm(rows, elm)
    return {
        "candidates": [_row_a_json(r) for r in rows],
        "count": len(rows),
        "roamers": [k for k in ("r", "e", "l") if k in prev],
    }


def key_seed_info(key_seed: int, prev_routes: dict | None) -> dict:
    """The key seed's own roamer routes + Elm sequence (Seed-to-Time style readout)."""
    prev = _clean_prev_routes(prev_routes)
    routes, calls, state = roamer_positions(int(key_seed), prev)
    return {
        "r_route": routes["r"], "e_route": routes["e"], "l_route": routes["l"],
        "rng_calls": calls, "elm": "".join(elm_calls(state, _ELM_DISPLAY)),
    }


# --- Seed B (battle seed: Metronome paths) --------------------------------

def _row_b_json(r: dict) -> dict:
    return {
        "seed": r["seed"], "seed_hex": f"0x{r['seed']:08X}",
        "time": r["time"].strftime(_TIME_FMT), "delay": r["delay"],
        "sec_delta": r["sec_delta"], "delay_delta": r["delay_delta"],
        "path_str": r["path_str"],
    }


def seed_b(params: dict) -> dict:
    """Candidate battle seeds around a target, each with its precomputed Metronome path.

    params: target_time (ISO), target_delay, magikarp_level, opposite_gender,
            seconds_window, delay_window, metronome_only, limit.
    """
    rows = generate_candidates_near(
        _parse_time(params["target_time"]),
        int(params["target_delay"]),
        int(params.get("seconds_window", 2)),
        int(params.get("delay_window", 10)),
        magikarp_level=int(params["magikarp_level"]),
        opposite_gender=bool(params["opposite_gender"]),
        metronome_only=bool(params.get("metronome_only", False)),
    )
    limit = int(params.get("limit", 15))
    return {"candidates": [_row_b_json(r) for r in rows[:limit]], "count": len(rows)}


def seed_b_runner(params: dict):
    """Build a ``runner(input_fn, output_fn) -> candidate|None`` for a narrowing session.

    Generates the full candidate set (with precomputed battle paths) once, then hands
    back a closure the session thread runs: it drives ``narrow_candidates`` with the
    injected callbacks so the UI can answer the battle questions one at a time.
    """
    level = int(params["magikarp_level"])
    opp = bool(params["opposite_gender"])
    metronome_only = bool(params.get("metronome_only", False))
    candidates = generate_candidates_near(
        _parse_time(params["target_time"]),
        int(params["target_delay"]),
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
