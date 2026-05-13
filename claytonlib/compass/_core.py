"""compass/_core.py — Seed generation, filtering, and evaluation."""
from __future__ import annotations

import copy
import datetime as dt

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


def _generate_candidates(inputs: CompassSafariInput) -> list[tuple]:
    """Return sorted (SafariContext, seed, delay) triples for the search window."""
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
