"""compass/_display.py — Display and formatting helpers for the safari compass."""
from __future__ import annotations

from claytonlib.safari import SafariStep
from claytonlib.chart import Strategy, SuccessCriteria
from claytonlib.compass._types import CompassAction, CompassOptions, CompassSafariInput
from claytonlib.compass._core import _evaluate_context
from claytonlib.compass._types import _action_to_str


def _print_cheatsheet(inputs: CompassSafariInput) -> None:
    pname = inputs.pokemon.name.capitalize()
    rows = [
        ('m',     'Mud, no crit',        f'{pname} is angry!'),
        ('M / a', 'Mud, crit (Anger)',   f'{pname} is beside itself with anger!'),
        ('b',     'Bait, no crit',       f'{pname} is eating!'),
        ('B / e', 'Bait, crit (Eating)', f'{pname} is busy eating!'),
        ('0',     'Ball, 0 shakes',      'Oh, no! The Pokémon broke free!'),
        ('1',     'Ball, 1 shake',       'Aww! It appeared to be caught!'),
        ('2',     'Ball, 2 shakes',      'Aargh! Almost had it!'),
        ('3',     'Ball, 3 shakes',      'Shoot! It was so close, too!'),
        ('C',     'Captured (ends)',     f'Gotcha! {pname} was caught!'),
        ('F',     'Fled (ends)',         f'{pname} fled!'),
        ('u',     'Undo last action',    '—'),
        ('?x',    'Uncertain result',    '—'),
        ('J',     'Switch to Jane',      '—'),
    ]
    key_w = max(len(r[0]) for r in rows)
    act_w = max(len(r[1]) for r in rows)
    print("=== Compass: Safari Zone Seed Identifier ===")
    for key, action, message in rows:
        print(f"  {key:<{key_w}}  {action:<{act_w}}  {message}")
    print("  Spaces and commas in input are ignored.")
    print()


def _delta_str(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def _print_status(candidates: list[tuple], total: int, target_delay: int,
                  path_actions: list, eval_strategy: Strategy | None,
                  eval_criteria: SuccessCriteria,
                  options: CompassOptions | None = None) -> None:
    cfg = options or CompassOptions()
    path_str = ''.join(_action_to_str(a) for a in path_actions) or '(none)'
    balls = candidates[0][0].balls_remaining if candidates else cfg.starting_ball_count

    print(f"Seeds: {len(candidates)} / {total} remaining")
    print(f"Path:  {path_str}")
    print(f"Balls: {balls}")

    nearest = sorted(candidates, key=lambda x: (abs(x[2] - target_delay), x[1]))[:cfg.seeds_displayed]
    display = sorted(nearest, key=lambda x: (x[2] - target_delay, x[1]))
    show_eval = eval_strategy is not None and len(candidates) <= cfg.evaluation_threshold

    if show_eval:
        print(f"  {'#':>2}  {'Seed':>10}  {'Delay':>7}  {'Δ':>5}  Success")
    else:
        print(f"  {'#':>2}  {'Seed':>10}  {'Delay':>7}  {'Δ':>5}")

    for i, (ctx, seed, delay) in enumerate(display, 1):
        delta = delay - target_delay
        marker = "  ← target" if delta == 0 else ""
        if show_eval:
            success = "yes" if _evaluate_context(ctx, eval_strategy, eval_criteria) else "no"
            print(f"  {i:>2}. 0x{seed:08X}  {delay:>7}  {_delta_str(delta):>5}  {success}{marker}")
        else:
            print(f"  {i:>2}. 0x{seed:08X}  {delay:>7}  {_delta_str(delta):>5}{marker}")


def _print_success(seed: int, delay: int, target_delay: int,
                   path_actions: list) -> None:
    path_str = ''.join(_action_to_str(a) for a in path_actions)
    delta = delay - target_delay
    delta_label = f"{_delta_str(delta)} (exact target)" if delta == 0 else _delta_str(delta)
    lines = [
        "Seed identified!",
        f"seed  = 0x{seed:08X}",
        f"delay = {delay}",
        f"\u0394     = {delta_label}",
        f"path  = {path_str or '(none)'}",
    ]
    width = max(len(l) for l in lines) + 2
    border = '\u2550' * width
    print(f"\u2554{border}\u2557")
    for line in lines:
        print(f"\u2551  {line:<{width - 2}}\u2551")
    print(f"\u255a{border}\u255d")
