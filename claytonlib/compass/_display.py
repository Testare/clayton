"""compass/_display.py — Display and formatting helpers for the safari compass."""
from __future__ import annotations

from claytonlib.safari import SafariStep
from claytonlib.chart import Strategy, SuccessCriteria
from claytonlib.compass._types import CompassAction, CompassOptions, CompassSafariInput
from claytonlib.compass._core import _evaluate_context, posteriors
from claytonlib.compass._types import _action_to_str


def cheatsheet_rows(pokemon_name: str, calibrated: bool = False) -> list[tuple[str, str, str]]:
    """The (key, action, in-game message) legend rows for a Safari Compass path, e.g. what
    a mud-crit actually says on screen for this species. Pulled out of _print_cheatsheet so
    the app can reuse the same data as a guide UI, not just a printed notebook cheatsheet."""
    pname = pokemon_name.capitalize()
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
    if calibrated:
        rows.append(('w', 'Widen window & re-apply path', '—'))
    return rows


def _print_cheatsheet(inputs: CompassSafariInput) -> None:
    rows = cheatsheet_rows(inputs.pokemon.name, calibrated=getattr(inputs, 'calibrated', False))
    key_w = max(len(r[0]) for r in rows)
    act_w = max(len(r[1]) for r in rows)
    print("=== Compass: Safari Zone Seed Identifier ===")
    for key, action, message in rows:
        print(f"  {key:<{key_w}}  {action:<{act_w}}  {message}")
    print("  Spaces and commas in input are ignored.")
    print()


# Ball-consuming outcomes -- each throws one ball (0-3 shakes, or a capture).
_BALL_OUTCOME_STEPS = frozenset((SafariStep.BALL_0, SafariStep.BALL_1, SafariStep.BALL_2,
                                 SafariStep.BALL_3, SafariStep.CAPTURED))


def _balls_remaining(candidates: list, path_actions: list, starting: int) -> int:
    """Balls left.  Read a surviving candidate's context when one exists; otherwise derive it
    from the observed throws (each 0-3/C consumed a ball; bait/mud don't) so the count stays
    correct even after the last observed step eliminated every candidate (empty set)."""
    if candidates:
        return candidates[0][0].balls_remaining
    thrown = sum(1 for a in path_actions if getattr(a, "step", None) in _BALL_OUTCOME_STEPS)
    return starting - thrown


def _delta_str(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def _print_status(candidates: list[tuple], total: int, target_delay: int,
                  path_actions: list, eval_strategy: Strategy | None,
                  eval_criteria: SuccessCriteria,
                  options: CompassOptions | None = None) -> None:
    cfg = options or CompassOptions()
    path_str = ''.join(_action_to_str(a) for a in path_actions) or '(none)'
    balls = _balls_remaining(candidates, path_actions, cfg.starting_ball_count)

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


def _sec_offset_str(delta: int) -> str:
    if delta == 0:
        return "on time"
    return f"{_delta_str(delta)}s ({'late' if delta > 0 else 'early'})"


def _print_status_calibrated(candidates: list[tuple], total: int, ref_frame: int,
                             meta: dict, path_actions: list,
                             eval_strategy: Strategy | None,
                             eval_criteria: SuccessCriteria,
                             options: CompassOptions | None = None) -> list[tuple]:
    """Calibrated status: survivors ranked by posterior landing probability with P%.

    Returns the ranked list of (seed, posterior, meta_dict) so the caller can honor an
    early-stop confidence threshold.
    """
    cfg = options or CompassOptions()
    path_str = ''.join(_action_to_str(a) for a in path_actions) or '(none)'
    balls = _balls_remaining(candidates, path_actions, cfg.starting_ball_count)

    ctx_by_seed = {seed: ctx for ctx, seed, _ in candidates}
    post = posteriors(list(ctx_by_seed), meta)
    ranked = sorted(post.items(), key=lambda kv: (-kv[1], meta[kv[0]]["frame"]))

    print(f"Seeds: {len(candidates)} / {total} remaining")
    print(f"Path:  {path_str}")
    print(f"Balls: {balls}")

    show_eval = eval_strategy is not None and len(candidates) <= cfg.evaluation_threshold
    header = f"  {'#':>2}  {'Seed':>10}  {'Frame':>7}  {'\u0394':>6}  {'\u03b4sec':>5}  {'P(land)':>8}"
    print(header + ("  Success" if show_eval else ""))

    for i, (seed, p) in enumerate(ranked[:cfg.seeds_displayed], 1):
        m = meta[seed]
        row = (f"  {i:>2}. 0x{seed:08X}  {m['frame']:>7}  "
               f"{_delta_str(m['frame'] - ref_frame):>6}  {_delta_str(m['delta']):>5}  "
               f"{p * 100:>7.2f}%")
        if show_eval:
            ok = _evaluate_context(ctx_by_seed[seed], eval_strategy, eval_criteria)
            row += f"  {'yes' if ok else 'no'}"
        print(row)

    if ranked:
        top_seed, top_p = ranked[0]
        tm = meta[top_seed]
        note = "  \u2190 likely identified" if (len(ranked) > 1 and top_p >= cfg.confidence_threshold) else ""
        print(f"  Most likely: 0x{top_seed:08X}  P={top_p * 100:.2f}%  "
              f"(timer {_sec_offset_str(tm['delta'])}){note}")
    return [(s, p, meta[s]) for s, p in ranked]


def _print_success(seed: int, delay: int, target_delay: int,
                   path_actions: list, second_offset: int | None = None) -> None:
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
    if second_offset is not None:
        lines.append(f"timer = {_sec_offset_str(second_offset)}")
    width = max(len(l) for l in lines) + 2
    border = '\u2550' * width
    print(f"\u2554{border}\u2557")
    for line in lines:
        print(f"\u2551  {line:<{width - 2}}\u2551")
    print(f"\u255a{border}\u255d")
