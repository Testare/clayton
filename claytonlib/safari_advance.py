"""safari_advance.py — Seed A advance-frame identification and route planning.

Ported from utils/safari_advance.py's pure functions (the notebook-interactive pieces —
input()-driven prompting and the Pokefinder-handoff prompt itself — stay in utils/, since
that's UI, not math). Given Seed A and the Elm calls heard so far, this pins its current
advance frame, then plans a route (chatot flips + a verifiable Elm-call margin) to a target
encounter frame — chosen either externally (Pokefinder) or in-house via
find_in_house_frame (claytonlib.safari_encounters' block-config search).

Terminology (see notes/safari_calibration_notebook.md):
  * Seed A is the initial RNG state for the overworld stream (encounters, roamer relocation,
    Elm phone calls).
  * An *advance frame* is the number of times Seed A's state has been advanced via
    advance_rng since the seed was generated — driven by player actions, not the clock.
  * Roamer relocation (REL) consumes a fixed number of advances (`rng_calls`); after that,
    each Elm phone call is exactly one advance, so the P/E/K calls heard pin the current frame.
"""
from __future__ import annotations

from dataclasses import dataclass

from claytonlib.calibration_tools import _ELM_CHARS, elm_calls, roamer_positions

DEFAULT_ELM_MARGIN = 3


def clean_elm(observed: str) -> str:
    """Keep only the P/E/K characters (upper-cased) from a raw Elm-input string."""
    return "".join(ch for ch in observed.upper() if ch in _ELM_CHARS)


def _all_start_positions(haystack: str, needle: str) -> list[int]:
    """Every start index where haystack[p:p+len(needle)] == needle (overlaps included)."""
    if needle == "":
        return list(range(len(haystack) + 1))
    positions = []
    start = haystack.find(needle)
    while start != -1:
        positions.append(start)
        start = haystack.find(needle, start + 1)
    return positions


def frame_candidates(rng_calls: int, elm: str, observed: str,
                     max_offset: int | None = None) -> list[int]:
    """The advance frame(s) consistent with hearing `observed` in `elm`.

    `elm[i]` is the call heard on the advance from frame `rng_calls + i` to `rng_calls + i + 1`
    (generate it with `advance_context`). `observed` is cleaned via `clean_elm`. Returns a
    sorted list of candidate CURRENT advance frames: one => pinned; more than one => keep
    listening; empty => the calls don't occur in the sequence (bad input, or too short).
    """
    obs = clean_elm(observed)
    positions = _all_start_positions(elm, obs)
    if max_offset is not None:
        positions = [p for p in positions if p <= max_offset]
    return sorted(rng_calls + p + len(obs) for p in positions)


def advance_context(seed: int, prev_routes: dict, count: int = 128,
                    present: dict | None = None) -> tuple[int, str]:
    """(rng_calls, elm) for `seed` — REL advances plus its Elm-call string.

    `count` should be generated long enough to cover the whole approach to a target frame
    (planning), not just identification — the caller picks it based on how far out the
    target encounter frame is expected to be.
    """
    _routes, rng, state = roamer_positions(seed, prev_routes, present=present)
    elm = "".join(elm_calls(state, count))
    return rng, elm


@dataclass
class AdvancePlan:
    """A recipe to reach `encounter_frame` from `current_frame`.

    You Sweet Scent while standing on `scent_frame` (= `encounter_frame`). The bulk of the
    distance is covered by `chatot_flips` (two advances each; a trailing half-flip = one
    advance is fine), landing on `land_frame`; from there `elm_before_scent` Elm calls — the
    verifiable margin — carry you to `scent_frame`.
    """
    current_frame: int
    encounter_frame: int
    scent_frame: int
    total_advances: int
    chatot_flips: float
    chatot_advances: int
    elm_before_scent: int
    land_frame: int
    margin: int


def plan_advances(current_frame: int, encounter_frame: int,
                  margin: int = DEFAULT_ELM_MARGIN) -> AdvancePlan:
    """Plan the advances from `current_frame` to `encounter_frame`.

    You Sweet Scent while standing ON the encounter frame (pressing a frame early misses by
    one). Raises ValueError if `encounter_frame` is already behind `current_frame` (overshot
    — you'd need to reset). When more than `margin` advances remain, chatot flips close the
    gap to `margin` Elm calls short of the scent frame; otherwise the whole (short) distance
    is Elm calls and no chatot flips are used.
    """
    scent_frame = encounter_frame
    total = scent_frame - current_frame
    if total < 0:
        raise ValueError(
            f"already past the target: on frame {current_frame}, but Sweet Scent "
            f"for encounter frame {encounter_frame} must fire on frame {scent_frame}")
    elm_before = min(total, margin)
    chatot_advances = total - elm_before
    # A single (or half) chatot flip isn't worth the unverifiable flip — just do those as
    # extra Elm calls (a 4- or 5-call margin), mirroring the short-distance case.
    if 0 < chatot_advances <= 2:
        elm_before = total
        chatot_advances = 0
    return AdvancePlan(
        current_frame=current_frame,
        encounter_frame=encounter_frame,
        scent_frame=scent_frame,
        total_advances=total,
        chatot_flips=chatot_advances / 2,
        chatot_advances=chatot_advances,
        elm_before_scent=elm_before,
        land_frame=current_frame + chatot_advances,
        margin=margin,
    )


def margin_guide(rng_calls: int, elm: str, plan: AdvancePlan,
                 n_before: int = 5, n_after: int = 3) -> str:
    """The Elm-call guide string around the approach, e.g. "PEEEP[KPE]!KEP".

    `n_before` calls precede the bracket (in case you land early), the bracket holds the
    `elm_before_scent` calls you should hear approaching the target, "!" marks where to Sweet
    Scent (on `scent_frame`), and `n_after` trailing calls follow (in case you overshoot).
    """
    j_land = plan.land_frame - rng_calls
    j_scent = j_land + plan.elm_before_scent
    if j_land < 0:
        raise ValueError(
            f"land_frame {plan.land_frame} precedes REL end (frame {rng_calls})")
    truncated = len(elm) < j_scent
    before = elm[max(0, j_land - n_before):j_land]
    bracket = elm[j_land:j_scent]
    after = elm[j_scent:j_scent + n_after]
    return f"{before}[{bracket}]!{after}", truncated


def margin_ambiguous(rng_calls: int, elm: str, plan: AdvancePlan) -> bool:
    """Whether the plan's Elm-call margin can't reliably confirm the Sweet-Scent frame.

    The margin confirms the frame only if it reads uniquely — flagged when a full copy of the
    bracket sits 1 or 2 positions before or after it (a landing/count error that size would be
    invisible). See utils/safari_advance.py's docstring for the full rationale.
    """
    m = plan.elm_before_scent
    lo = plan.land_frame - rng_calls
    hi = lo + m
    if m < 1 or lo < 0 or hi > len(elm):
        return False
    bracket = elm[lo:hi]
    for p in range(1, min(m, 2) + 1):
        if lo - p >= 0 and elm[lo - p:hi - p] == bracket:
            return True
        if hi + p <= len(elm) and elm[lo + p:hi + p] == bracket:
            return True
    return False


def describe_plan(plan: AdvancePlan, guide: str | None = None) -> str:
    """A multi-line, human-readable instruction block."""
    lines = [
        f"On advance frame {plan.current_frame}; want an encounter on frame "
        f"{plan.encounter_frame} (Sweet Scent while on frame {plan.scent_frame}).",
        f"  Advances to go: {plan.total_advances}",
    ]
    if plan.chatot_advances > 0:
        flips = (f"{plan.chatot_flips:.1f}" if plan.chatot_flips % 1
                 else f"{int(plan.chatot_flips)}")
        lines.append(
            f"  1. {flips} chatot flips ({plan.chatot_advances} advances) "
            f"-> land on frame {plan.land_frame}")
    else:
        lines.append("  1. (no chatot flips needed)")
    lines.append(
        f"  2. {plan.elm_before_scent} Elm calls "
        f"-> frame {plan.scent_frame}, then Sweet Scent.")
    if guide is not None:
        lines.append(f"  Guide: {guide}   (]! = Sweet Scent here)")
    return "\n".join(lines)


def find_in_house_frame(seed: int, prev_routes: dict, current_frame: int, area: str, tod,
                        blocks, target: str = "metang", search_margin: int = DEFAULT_ELM_MARGIN,
                        max_frame: int = 300, aim_advance: int | None = None) -> dict:
    """Pick a target-species encounter frame in-house (claytonlib.safari_encounters), instead
    of a Pokefinder handoff — mirrors utils/safari_advance.py's choose_target_frame in-house
    branch (minus its exact-key-seed-hit special case and the Pokefinder prompt itself, which
    are the caller's own concerns, not this pure function's).

    Frames whose Elm-call approach margin can't be read reliably (margin_ambiguous) are
    skipped when a strictly-better unambiguous candidate exists. `aim_advance`, when given,
    picks the candidate CLOSEST to that advance (for calibration data-gathering runs that want
    a specific advance count, not just "as soon as possible") instead of the nearest one to
    `current_frame`.

    Returns {"frame", "level", "skipped_ambiguous" (count), "all_ambiguous" (bool — every
    candidate was ambiguous, so `frame` is just the closest one anyway, use with care)}.
    `skipped_ambiguous` counts ONLY candidates that were both (a) genuinely NEARER to the aim
    than the chosen `frame` and (b) ambiguous — i.e. candidates actually passed over in favor
    of `frame` (clayton-b42.10.6: an earlier version counted every ambiguous candidate in the
    whole search window regardless of distance, so it could report frames "skipped" that were
    farther from the aim than the one chosen, or even report a nonzero count when `frame` was
    already the closest possible candidate — neither makes sense under the word "skipped").
    Raises ValueError if no candidate frame exists in range at all.
    """
    from claytonlib.safari_encounters import iter_encounter_frames

    lo = current_frame + search_margin
    hi = max_frame if aim_advance is None else max(max_frame, aim_advance + search_margin)
    candidates = list(iter_encounter_frames(seed, area, tod, blocks, target,
                                            min_frame=lo, max_frame=hi))
    if not candidates:
        raise ValueError(
            f"no {target} frame in [{lo}, {hi}] for {area}/{tod} blocks={blocks} — "
            f"check the block scores, area, and time of day.")

    aim = current_frame if aim_advance is None else aim_advance
    def _distance(frame_level):
        frame = frame_level[0]
        return (abs(frame - aim), frame)  # nearest to aim, lower frame breaks ties

    rng_calls, elm = advance_context(seed, prev_routes, count=hi + 20)

    def _ambiguous(frame_level):
        return margin_ambiguous(rng_calls, elm,
                                plan_advances(current_frame, frame_level[0], margin=search_margin))

    scored = [(fl, _ambiguous(fl)) for fl in candidates]
    unambiguous = [fl for fl, amb in scored if not amb]
    if unambiguous:
        chosen = min(unambiguous, key=_distance)
        all_ambiguous = False
    else:
        chosen = min(candidates, key=_distance)
        all_ambiguous = True

    chosen_dist = _distance(chosen)
    skipped = sum(1 for fl, amb in scored
                  if amb and fl != chosen and _distance(fl) < chosen_dist)
    frame, level = chosen
    return {"frame": frame, "level": level, "skipped_ambiguous": skipped,
            "all_ambiguous": all_ambiguous}
