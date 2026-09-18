"""safari_compass.py — Safari Compass Seed B identification, wrapped for the UI.

Reuses claytonlib.compass's calibrated candidate generation (calibrated_candidates) and
per-action filtering (_apply_action) directly, rather than the full interactive
compass_safari() driver in claytonlib/compass/__init__.py — that driver is input()-driven
with UX (undo/widen/expand/Jane-offload/machete-preview prompts) well beyond what's needed
here. Like Metronome Seed A, this is STATELESS: given the target and the full observed path
string so far, it regenerates candidates and replays the whole path from scratch each call —
so live narrowing (re-run on every keystroke) is trivial and there's no session to manage.

The pending/cache "did it flee?" replay below exactly mirrors compass_safari's own loop: a
flee is only known once the NEXT observed action reveals it (or F/C is typed explicitly) —
see claytonlib/compass/__init__.py for the reference implementation this matches.

Seed A (roamer routes + Elm calls) is shared with Metronome Compass verbatim — see
app/metronome.py's seed_a/key_seed_info; nothing Safari-specific is needed there.
"""
from __future__ import annotations

import datetime as dt

from claytonlib.compass import CompassSafariInput, calibrated_candidates, posteriors
from claytonlib.compass._core import _apply_action
from claytonlib.compass._types import CompassAction, ParseError, UndoAction, parse_input
from claytonlib.safari import SafariStep, safari_pokemon_by_name

# CompassSafariInput requires strategy/criteria, but calibrated_candidates only ever touches
# inputs.pokemon/options — strategy/criteria solely feed the interactive driver's optional
# live "P(capture) so far" column, which this stateless API doesn't build. A neutral, always-
# available pair keeps the dataclass happy without asking the UI to supply meaningless input.
def _neutral_strategy_criteria():
    from claytonlib.chart import CRITERIA_CAPTURE, STRATEGY_ONLY_BALLS
    return STRATEGY_ONLY_BALLS, CRITERIA_CAPTURE


def _build_input(exp: dict, model, params: dict) -> CompassSafariInput:
    strategy, criteria = _neutral_strategy_criteria()
    pokemon = safari_pokemon_by_name(exp["pokemon"])
    return CompassSafariInput.from_expedition_target(
        model=model, M=float(params["vector_ms"]),
        initial_time=dt.datetime.fromisoformat(params["initial_time"]),
        key_seed=int(exp["key_seed"]), max_target_seconds=int(params.get("max_target_seconds", 300)),
        pokemon=pokemon, strategy=strategy, criteria=criteria,
        second_offsets=tuple(params.get("second_offsets", (-1, 0, 1))),
        k=float(params.get("k", 3.5)), mass_cap=params.get("mass_cap", 0.999),
    )


def _apply_path(candidates: list, actions: list):
    """Replay `actions` against `candidates`, mirroring compass_safari's pending/cache
    flee-resolution state machine exactly. Returns (current_candidates, terminal|None),
    terminal being "captured"/"fled" once a run-ending action is reached."""
    cache = [candidates]
    pending = None
    terminal = None
    for action in actions:
        if isinstance(action, UndoAction):
            if pending is not None:
                pending = None
            elif len(cache) > 1:
                cache.pop()
            continue
        step = action.step
        if step == SafariStep.FLED:
            if pending is not None:
                cache.append([c for c in pending if c[0].has_fled()])
                pending = None
            terminal = "fled"
            break
        if step == SafariStep.CAPTURED:
            if pending is not None:
                cache.append([c for c in pending if not c[0].has_fled()])
                pending = None
            cache.append(_apply_action(cache[-1], action, filter_fled=False))
            terminal = "captured"
            break
        # Regular action: resolve the pending step as no-flee, then apply this one.
        if pending is not None:
            cache.append([c for c in pending if not c[0].has_fled()])
            pending = None
        pending = _apply_action(cache[-1], action, filter_fled=False)
    current = pending if pending is not None else cache[-1]
    return current, terminal


def _row_json(seed: int, frame: int, meta: dict, post: dict) -> dict:
    m = meta.get(seed, {}) if meta else {}
    return {
        "seed": seed, "seed_hex": f"0x{seed:08X}", "frame": frame,
        "delta": m.get("delta"), "posterior": post.get(seed, 0.0),
    }


def seed_b(exp: dict, model, params: dict) -> dict:
    """Candidate battle seeds for Safari Compass, narrowed by the observed path so far.

    params: initial_time (ISO), vector_ms, path (the full observed-action string, e.g.
            "bbbBbb0321"), and optionally second_offsets/k/mass_cap/limit.
    """
    inputs = _build_input(exp, model, params)
    candidates, meta = calibrated_candidates(inputs)
    total = len(candidates)

    path = (params.get("path") or "").strip()
    parsed = parse_input(path) if path else []
    if isinstance(parsed, ParseError):
        return {"path_valid": False, "count": 0, "total": total, "candidates": [], "terminal": None}

    actions = [a for a in parsed if isinstance(a, (CompassAction, UndoAction))]
    # Jane offload isn't wired up here (draft2: "Jane might not be an immediate priority") --
    # a JaneAction in the input is simply not an CompassAction/UndoAction, so it's dropped above.

    current, terminal = _apply_path(candidates, actions)
    post = posteriors([s for _, s, _ in current], meta) if meta else {}
    ranked = sorted(current, key=lambda x: (-post.get(x[1], 0.0), x[2]))
    limit = int(params.get("limit", 15))

    result = {
        "path_valid": True, "count": len(current), "total": total, "terminal": terminal,
        "candidates": [_row_json(seed, frame, meta, post) for _ctx, seed, frame in ranked[:limit]],
    }

    if len(current) == 1 and terminal is None:
        # Provisionally identified but the run isn't over — offer the Machete-predicted
        # continuation so the UI can bold the next expected action (bead uj7.1).
        ctx, seed, frame = current[0]
        from claytonlib.machete import machete_one
        mpath = machete_one(ctx)
        result["identified_seed"] = f"0x{seed:08X}"
        result["machete_path"] = mpath

    return result


# ---------------------------------------------------------------------------
# Seed A advance-frame identification + route planning (clayton-b42.5.11)
#
# This is a SEPARATE concern from Seed B (the battle seed) above: it's about Seed A's own
# advance frame -- how many Elm calls have been heard since Seed A was generated -- so the
# player can be told exactly how to reach a chosen encounter frame (e.g. one Pokefinder says
# holds the target Pokemon). See claytonlib.safari_advance for the underlying math (ported
# from utils/safari_advance.py, the notebook's Section A/ctd.2).
# ---------------------------------------------------------------------------

# Matches app.metronome._ELM_DISPLAY -- the same short Elm sequence already generated (and
# shown to the user) for Seed A candidate rows. Identification only ever needs a handful of
# calls to disambiguate (frame_candidates' worked examples resolve within ~4); looking much
# further out than this just wastes computation and, per notebook convention, isn't how the
# reference workflow does it.
from app.metronome import _ELM_DISPLAY as DEFAULT_FRAME_LOOKAHEAD


def identify_seed_a_frame(seed: int, prev_routes: dict, observed_elm: str,
                          count: int = DEFAULT_FRAME_LOOKAHEAD,
                          max_offset: int | None = None) -> dict:
    """Pin Seed A's current advance frame from the Elm calls heard since it was generated.

    Returns {"rng_calls", "frames" (all consistent candidates), "pinned" (bool),
    "frame" (int, only when pinned)}. Call again with more `observed_elm` (the full string
    heard so far, not just the new calls) when `frames` has more than one entry.
    """
    from claytonlib.safari_advance import advance_context, frame_candidates
    rng_calls, elm = advance_context(seed, prev_routes, count=count)
    frames = frame_candidates(rng_calls, elm, observed_elm, max_offset=max_offset)
    return {
        "rng_calls": rng_calls, "frames": frames,
        "pinned": len(frames) == 1, "frame": frames[0] if len(frames) == 1 else None,
    }


def find_target_frame(seed: int, prev_routes: dict, current_frame: int, area: str, tod,
                      block_config: dict, pokemon: str, margin: int = 3,
                      max_frame: int = 300, aim_advance: int | None = None) -> dict:
    """In-house target-encounter-frame search (vs. a Pokefinder handoff) — an alternative way
    to pick `encounter_frame` for plan_frame_route below, using the expedition's own Safari
    block scores. See claytonlib.safari_advance.find_in_house_frame for the algorithm."""
    from claytonlib.safari_advance import find_in_house_frame
    return find_in_house_frame(seed, prev_routes, current_frame, area, tod, block_config,
                              target=pokemon, search_margin=margin, max_frame=max_frame,
                              aim_advance=aim_advance)


def plan_frame_route(seed: int, prev_routes: dict, current_frame: int, encounter_frame: int,
                     margin: int = 3) -> dict:
    """A chatot-flip + Elm-call route from `current_frame` to `encounter_frame`, however that
    was chosen (Pokefinder, or the in-house search above)."""
    from claytonlib.safari_advance import (
        advance_context, describe_plan, margin_ambiguous, margin_guide, plan_advances,
    )
    plan = plan_advances(current_frame, encounter_frame, margin=margin)
    # Generous enough to cover the whole approach regardless of REL cost.
    rng_calls, elm = advance_context(seed, prev_routes, count=encounter_frame + 20)
    guide, truncated = margin_guide(rng_calls, elm, plan)
    return {
        "current_frame": plan.current_frame, "encounter_frame": plan.encounter_frame,
        "scent_frame": plan.scent_frame, "total_advances": plan.total_advances,
        "chatot_flips": plan.chatot_flips, "chatot_advances": plan.chatot_advances,
        "elm_before_scent": plan.elm_before_scent, "land_frame": plan.land_frame,
        "guide": guide, "truncated": truncated,
        "ambiguous": margin_ambiguous(rng_calls, elm, plan),
        "description": describe_plan(plan, guide),
    }
