"""compass/_core.py — Seed generation, filtering, and evaluation."""
from __future__ import annotations

import copy
import datetime as dt
import math

from claytonlib.safari import SafariContext, SafariStep
from claytonlib.times import get_times, calculate_seed
from claytonlib.chart import Strategy, SuccessCriteria
from claytonlib.compass._types import CompassAction, CompassSafariInput


# ---------------------------------------------------------------------------
# Step groups used by filtering
# ---------------------------------------------------------------------------

_BAIT_STEPS = (SafariStep.BAIT, SafariStep.BAIT_CRITICAL)
_MUD_STEPS  = (SafariStep.MUD,  SafariStep.MUD_CRITICAL)
_BALL_STEPS = (SafariStep.BALL_0, SafariStep.BALL_1, SafariStep.BALL_2, SafariStep.BALL_3)


# ---------------------------------------------------------------------------
# Seed generation
# ---------------------------------------------------------------------------

def _delay_offset_to_second_frame(offset: int) -> tuple[int, int]:
    """Return (second_idx, frame_j) for a delay offset from base_delay.

    Iterates the variable-width second table to find which second the
    given delay offset falls in and the frame index within that second.
    """
    from claytonlib.chart.evaluation import frames_in_second
    s = 0
    cum = 0
    while True:
        n = frames_in_second(s)
        if cum + n > offset:
            return s, offset - cum
        cum += n
        s += 1


def _seed_reachable(target_seed: int, target_delay: int, base_delay: int,
                    initial_time: dt.datetime) -> bool:
    offset = target_delay - base_delay
    if offset < 0:
        return False
    from claytonlib.chart.evaluation import frames_in_second, delay_at_second
    second_idx, frame_j = _delay_offset_to_second_frame(offset)
    n = frames_in_second(second_idx)
    time_at = initial_time + dt.timedelta(seconds=second_idx)
    seed_a_base = calculate_seed(time_at, delay_at_second(base_delay, second_idx))
    if seed_a_base + frame_j == target_seed:
        return True
    to_seed = calculate_seed(time_at + dt.timedelta(seconds=1),
                             delay_at_second(base_delay, second_idx + 1))
    if (to_seed - n) + frame_j == target_seed:
        return True
    return False


def _second_of_frame(base_delay: int, frame: int) -> int:
    """The RTC-second offset from boot whose variable-width delay band contains `frame`."""
    second_idx, _ = _delay_offset_to_second_frame(frame - base_delay)
    return second_idx


def _offset_weight(delta: int, sd: float) -> float:
    """Discrete-Gaussian prior weight for a second-offset δ (P(δ) before normalization)."""
    sd = max(sd, 1e-9)
    return math.exp(-0.5 * (delta / sd) ** 2)


def _frame_weight(frame: int, f_center: float, sigma: float) -> float:
    """Landing-likelihood weight for a battle frame (Normal(frame; F*, σ), unnormalized)."""
    sigma = max(sigma, 1e-9)
    return math.exp(-0.5 * ((frame - f_center) / sigma) ** 2)


def calibrated_candidates(inputs: CompassSafariInput) -> tuple[list[tuple], dict[int, dict]]:
    """The calibrated (second, frame) sweep with a landing prior per candidate.

    Returns ``(results, meta)`` where results is a sorted list of ``(SafariContext, seed,
    frame)`` triples and meta maps ``seed -> {"frame", "delta", "prior"}``.

    A candidate is ``seed_for_mdmsh(mdmsh_of(initial_time + (s+δ)), frame)`` — equivalently
    ``calculate_seed(initial_time + (s+δ), frame)`` — over ``frame ∈ [F* ± k·σ]`` and each δ
    in ``second_offsets`` (s = the RTC second whose band contains `frame`).  The frame is the
    absolute delay counter; the RTC second is its own axis (δ), so there is no seed_a/seed_b
    duality.  The frame window is the SAME at every δ (the second-offset is decoupled from the
    frame value; see refined_safari_compass §2.3/§5) — δ shifts the RTC second, not the frame.

    The prior is ``P(δ) · Normal(frame; F*, σ)`` (unnormalized here; the caller renormalizes
    over survivors).  Capture-success is deliberately NOT part of the prior — it bears on
    catching, not on which seed was hit.  When two δ collide on one seed (same mdms/hour) the
    prior accumulates their weights and the higher-weight δ is the reported representative.
    """
    from claytonlib.chart.canon import mdmsh_of, seed_for_mdmsh
    base_delay, _ = get_times(inputs.key_seed)

    sigma = max(float(inputs.sigma), 1e-9)
    sd = inputs.options.second_offset_sd
    lo = max(base_delay, int(math.floor(inputs.frame_center - inputs.k * sigma)))
    hi = int(math.ceil(inputs.frame_center + inputs.k * sigma))

    # The base battle RTC second is FIXED at the model-derived target_second for the whole frame
    # window -- it does NOT slide with the frame.  Frame and second miss near-independently
    # (notes/seed_hitting_process.md §3-4): the frame center is held across seconds and the second
    # comes from the model (μ=M/1000+rtc_offset), exactly as the chart scorer's marginal_capture
    # does.  Deriving s0 from the frame (the old _second_of_frame here) coupled the two axes and
    # produced a candidate set disjoint from chart_check_target_landing.
    s0 = inputs.target_second
    results: list[tuple] = []
    meta: dict[int, dict] = {}
    for frame in range(lo, hi + 1):
        fw = _frame_weight(frame, inputs.frame_center, sigma)
        for delta in inputs.second_offsets:
            s = s0 + delta
            if s < 0:
                continue
            seed = seed_for_mdmsh(mdmsh_of(inputs.initial_time + dt.timedelta(seconds=s)), frame)
            w = _offset_weight(delta, sd) * fw
            if seed in meta:  # distinct δ collided on mdms/hour → one shared seed/state
                m = meta[seed]
                m["prior"] += w
                if w > m["_w"]:
                    m.update(frame=frame, delta=delta, _w=w)
                continue
            meta[seed] = {"frame": frame, "delta": delta, "prior": w, "_w": w}
            ctx = SafariContext.start_encounter(seed, inputs.pokemon)
            ctx.balls_remaining = inputs.options.starting_ball_count
            results.append((ctx, seed, frame))

    for m in meta.values():
        m.pop("_w", None)

    # Probability-mass window (b70.5): keep the smallest set of highest-prior candidates that
    # covers `mass_cap` of the total landing mass, trimming the far Gaussian×δ tails.
    cap = inputs.options.mass_cap
    if cap is not None and 0 < cap < 1 and meta:
        total = sum(m["prior"] for m in meta.values())
        if total > 0:
            keep: set[int] = set()
            acc = 0.0
            for seed, m in sorted(meta.items(), key=lambda kv: -kv[1]["prior"]):
                keep.add(seed)
                acc += m["prior"]
                if acc >= cap * total:
                    break
            results = [t for t in results if t[1] in keep]
            meta = {s: m for s, m in meta.items() if s in keep}

    results.sort(key=lambda x: (x[2], x[1]))
    return results, meta


def _effective_count(seeds, meta: dict[int, dict], mass: float = 0.99) -> int:
    """The number of top-posterior candidates that together carry `mass` of the probability.

    A prior-weighted alternative to the raw survivor count: when the posterior concentrates on
    a few seeds, the effective count is small even if many long-shot candidates linger — the
    signal for a Jane offload (b70.5).
    """
    seeds = [s for s in seeds if s in meta]
    if not seeds:
        return 0
    post = posteriors(seeds, meta)
    acc = 0.0
    n = 0
    for _, p in sorted(post.items(), key=lambda kv: -kv[1]):
        acc += p
        n += 1
        if acc >= mass:
            break
    return n


def _generate_candidates_calibrated(inputs: CompassSafariInput) -> list[tuple]:
    """The calibrated candidate triples alone (see `calibrated_candidates` for the prior meta)."""
    return calibrated_candidates(inputs)[0]


def posteriors(seeds, meta: dict[int, dict]) -> dict[int, float]:
    """Posterior landing probability over a subset of `seeds`: prior_i / Σ prior_survivors."""
    total = sum(meta[s]["prior"] for s in seeds if s in meta)
    if total <= 0:
        return {s: 0.0 for s in seeds}
    return {s: meta[s]["prior"] / total for s in seeds if s in meta}


def _generate_candidates(inputs: CompassSafariInput) -> list[tuple]:
    """Return sorted (SafariContext, seed, delay/frame) triples for the search window.

    Dispatches on mode: the calibrated (second, frame) sweep when `frame_center` is set,
    else the legacy delay-window + seed_a/seed_b sweep.
    """
    if inputs.calibrated:
        return _generate_candidates_calibrated(inputs)
    from claytonlib.chart.evaluation import frames_in_second, delay_at_second
    base_delay, _ = get_times(inputs.key_seed)
    results: list[tuple] = []
    start = inputs.target_delay - inputs.window

    for d in range(start, inputs.target_delay + inputs.window + 1):
        offset = d - base_delay
        if offset < 0:
            continue
        second_idx, frame_j = _delay_offset_to_second_frame(offset)
        n = frames_in_second(second_idx)
        time_at = inputs.initial_time + dt.timedelta(seconds=second_idx)
        seed_a_base = calculate_seed(time_at, delay_at_second(base_delay, second_idx))

        seed_a = seed_a_base + frame_j
        ctx = SafariContext.start_encounter(seed_a, inputs.pokemon)
        ctx.balls_remaining = inputs.options.starting_ball_count
        results.append((ctx, seed_a, d))

        to_seed = calculate_seed(time_at + dt.timedelta(seconds=1),
                                 delay_at_second(base_delay, second_idx + 1))
        seed_b = (to_seed - n) + frame_j
        ctx = SafariContext.start_encounter(seed_b, inputs.pokemon)
        ctx.balls_remaining = inputs.options.starting_ball_count
        results.append((ctx, seed_b, d))

    results.sort(key=lambda x: (x[2], x[1]))
    return results


# ---------------------------------------------------------------------------
# Filtering and evaluation
# ---------------------------------------------------------------------------

def _apply_action(candidates: list[tuple], action: CompassAction,
                  filter_fled: bool) -> list[tuple]:
    results = []
    step = action.step
    for ctx, seed, delay in candidates:
        ctx2 = copy.copy(ctx)
        if step in _BAIT_STEPS:
            result = ctx2.throw_bait()
            ok = (result in _BAIT_STEPS) if action.uncertain else (result == step)
        elif step in _MUD_STEPS:
            result = ctx2.throw_mud()
            ok = (result in _MUD_STEPS) if action.uncertain else (result == step)
        else:  # ball
            result = ctx2.throw_ball()
            ok = (result in _BALL_STEPS) if action.uncertain else (result == step)
        if not ok:
            continue
        if filter_fled and ctx2.has_fled():
            continue
        results.append((ctx2, seed, delay))
    return results


def _evaluate_context(ctx: SafariContext, strategy: Strategy,
                      criteria: SuccessCriteria) -> bool:
    ctx2 = copy.copy(ctx)
    while ctx2.is_watching():
        strategy.take_action(ctx2)
        if criteria.met(ctx2):
            return True
    return False
