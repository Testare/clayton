"""
compass.py — Seed identification tool.

Helps the player determine which seed they actually hit during an
attempt. Takes observed in-game events (early safari turn outcomes)
as input and narrows down the candidate seed list to identify the
current RNG state.
"""
import copy
import datetime as dt
import os
from dataclasses import dataclass, field

from claytonlib.safari import SafariContext, SafariPokemon, SafariStep
from claytonlib.times import get_times, calculate_seed
from claytonlib.chart import Strategy, SuccessCriteria, CRITERIA_CAPTURE


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

@dataclass
class CompassAction:
    step: SafariStep
    uncertain: bool = False


class UndoAction:
    pass


class JaneAction:
    pass


@dataclass
class ParseError:
    unknown_chars: set[str]

    def __str__(self) -> str:
        chars = ', '.join(repr(c) for c in sorted(self.unknown_chars))
        return f"Unrecognised input character(s): {chars}"


_CHAR_TO_STEP: dict[str, SafariStep] = {
    'm': SafariStep.MUD,
    'M': SafariStep.MUD_CRITICAL,
    'a': SafariStep.MUD_CRITICAL,
    'b': SafariStep.BAIT,
    'B': SafariStep.BAIT_CRITICAL,
    'e': SafariStep.BAIT_CRITICAL,
    '0': SafariStep.BALL_0,
    '1': SafariStep.BALL_1,
    '2': SafariStep.BALL_2,
    '3': SafariStep.BALL_3,
    'F': SafariStep.FLED,
    'C': SafariStep.CAPTURED,
}

_UNCERTAIN_CANONICAL: dict[str, SafariStep] = {
    'b': SafariStep.BAIT,   'B': SafariStep.BAIT,   'e': SafariStep.BAIT,
    'm': SafariStep.MUD,    'M': SafariStep.MUD,    'a': SafariStep.MUD,
    '0': SafariStep.BALL_0, '1': SafariStep.BALL_0,
    '2': SafariStep.BALL_0, '3': SafariStep.BALL_0,
}


def parse_input(text: str) -> list | ParseError:
    """Parse one line of compass input into a list of CompassAction/UndoAction."""
    actions: list = []
    unknown: set[str] = set()
    chars = [c for c in text if c not in (' ', ',')]
    i = 0
    while i < len(chars):
        ch = chars[i]
        if ch == 'u':
            actions.append(UndoAction())
            i += 1
        elif ch == 'J':
            actions.append(JaneAction())
            i += 1
        elif ch == '?':
            i += 1
            if i < len(chars) and chars[i] in _UNCERTAIN_CANONICAL:
                actions.append(CompassAction(step=_UNCERTAIN_CANONICAL[chars[i]], uncertain=True))
                i += 1
            else:
                unknown.add('?')
        elif ch in _CHAR_TO_STEP:
            actions.append(CompassAction(step=_CHAR_TO_STEP[ch]))
            i += 1
        else:
            unknown.add(ch)
            i += 1
    if unknown:
        return ParseError(unknown)
    return actions


def _action_to_str(action: CompassAction) -> str:
    if action.uncertain:
        if action.step in (SafariStep.BAIT, SafariStep.BAIT_CRITICAL):
            return '?b'
        if action.step in (SafariStep.MUD, SafariStep.MUD_CRITICAL):
            return '?m'
        return '?0'
    return action.step.value


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class CompassConfig:
    starting_ball_count:  int = 30
    seeds_displayed:      int = 5
    evaluation_threshold: int = 10
    suggest_jane:         bool = True  # suggest Jane when seeds < cpu_count (once per run)


_config = CompassConfig()


def compass_config() -> CompassConfig:
    return _config


# ---------------------------------------------------------------------------
# CompassSafariInput
# ---------------------------------------------------------------------------

@dataclass
class CompassSafariInput:
    pokemon:             SafariPokemon
    strategy:            Strategy
    criteria:            SuccessCriteria
    window:              int
    initial_time:        dt.datetime
    key_seed:            int | None = None
    target_delay:        int | None = None
    target_seed:         int | None = None
    evaluation_strategy: Strategy | None = None
    evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE

    def __post_init__(self):
        if self.target_delay is None:
            raise ValueError("target_delay is required")
        if self.key_seed is None:
            raise ValueError("key_seed is required")
        if self.target_seed is not None:
            base_delay, _ = get_times(self.key_seed)
            if not _seed_reachable(self.target_seed, self.target_delay,
                                   base_delay, self.initial_time):
                raise ValueError(
                    f"target_seed 0x{self.target_seed:08X} does not match any candidate "
                    f"at target_delay={self.target_delay} for the given initial_time"
                )

    @classmethod
    def from_chart(cls, chart_input, *, window: int, initial_time: dt.datetime,
                   target_seed: int | None = None, target_delay: int | None = None,
                   pokemon: SafariPokemon | None = None, strategy: Strategy | None = None,
                   criteria: SuccessCriteria | None = None,
                   evaluation_strategy: Strategy | None = None,
                   evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE) -> 'CompassSafariInput':
        return cls(
            pokemon=pokemon or chart_input.pokemon,
            strategy=strategy or chart_input.strategy,
            criteria=criteria or chart_input.criteria,
            window=window,
            initial_time=initial_time,
            key_seed=chart_input.key_seed,
            target_delay=target_delay,
            target_seed=target_seed,
            evaluation_strategy=evaluation_strategy,
            evaluation_criteria=evaluation_criteria,
        )


# ---------------------------------------------------------------------------
# Seed generation helpers
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
        ctx.balls_remaining = _config.starting_ball_count
        results.append((ctx, seed_a, d))

        to_seed = calculate_seed(time_at + dt.timedelta(seconds=1),
                                 delay_at_second(base_delay, second_idx + 1))
        seed_b = (to_seed - n) + frame_j
        ctx = SafariContext.start_encounter(seed_b, inputs.pokemon)
        ctx.balls_remaining = _config.starting_ball_count
        results.append((ctx, seed_b, d))

    results.sort(key=lambda x: (x[2], x[1]))
    return results


# ---------------------------------------------------------------------------
# Filtering and evaluation
# ---------------------------------------------------------------------------

_BAIT_STEPS = (SafariStep.BAIT, SafariStep.BAIT_CRITICAL)
_MUD_STEPS  = (SafariStep.MUD,  SafariStep.MUD_CRITICAL)
_BALL_STEPS = (SafariStep.BALL_0, SafariStep.BALL_1, SafariStep.BALL_2, SafariStep.BALL_3)


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


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

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
                  path_actions: list, eval_strategy, eval_criteria) -> None:
    cfg = _config
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


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def compass_safari(inputs: CompassSafariInput) -> list[str]:
    """Interactive safari zone seed identifier.

    Returns a list of hex seed strings (e.g. ['0xABCD1234']) for all seeds
    that matched the observed path. Returns an empty list when no seeds
    matched or the session was quit.
    """
    candidates = _generate_candidates(inputs)
    total = len(candidates)

    cache: list[tuple[str, list]] = [('', candidates)]
    pending: tuple[str, list] | None = None
    path_actions: list[CompassAction] = []
    _jane_suggested = False

    _print_cheatsheet(inputs)

    while True:
        current = pending[1] if pending is not None else cache[-1][1]
        print()
        _print_status(current, total, inputs.target_delay, path_actions,
                      inputs.evaluation_strategy, inputs.evaluation_criteria)

        if (not _jane_suggested and _config.suggest_jane
                and 1 < len(current) < (os.cpu_count() or 1)):
            print("  (Tip: seed count is small enough that Jane could take over — type 'J' to switch)")
            _jane_suggested = True

        if len(current) == 0:
            print()
            print(f"No matching seed found in window \u00b1{inputs.window}.")
            print("Consider expanding the search window or checking for input errors.")
            return []

        if len(current) == 1:
            ctx, seed, delay = current[0]
            print()
            _print_success(seed, delay, inputs.target_delay, path_actions)
            while True:
                raw = input("\nRun Machete to find a capture path from this point? (y/n) ").strip().lower()
                if raw in ('y', 'yes'):
                    from claytonlib.machete import machete_one
                    path = machete_one(ctx)
                    if path is not None:
                        print(f"Machete found a path: {path}")
                    else:
                        print("Machete found no capture path from this state.")
                    return [f"0x{seed:08X}"]
                elif raw in ('n', 'no'):
                    return [f"0x{seed:08X}"]

        raw = input("\n>> ").strip()

        if raw.lower() == 'q':
            confirm = input("Quit compass? (y/n) ").strip().lower()
            if confirm in ('y', 'yes'):
                current = pending[1] if pending is not None else cache[-1][1]
                return [f"0x{seed:08X}" for _, seed, _ in current]
            continue

        result = parse_input(raw)

        if isinstance(result, ParseError):
            print(f"  {result}")
            continue

        if any(isinstance(a, JaneAction) for a in result):
            confirm = input("Switching to Jane can take significant time. Are you sure? (y/n) ").strip().lower()
            if confirm in ('y', 'yes'):
                from claytonlib.machete import machete_jane, machete_config
                default_turns = machete_config().max_turns_all
                default_label = str(default_turns) if default_turns is not None else "unlimited"
                raw_turns = input(
                    f"Max turn depth? (Enter for default: {default_label}) "
                ).strip()
                if raw_turns == '':
                    jane_max_turns = ...
                else:
                    try:
                        jane_max_turns = int(raw_turns)
                    except ValueError:
                        print("  Invalid number; using default.")
                        jane_max_turns = ...
                jane_candidates = [(ctx, seed) for ctx, seed, delay in current]
                machete_jane(jane_candidates, pokemon=inputs.pokemon, interactive=True,
                             max_turns=jane_max_turns)
                return [f"0x{seed:08X}" for _, seed, _ in current]
            continue

        terminal = False
        for action in result:
            if isinstance(action, UndoAction):
                if pending is not None:
                    pending = None
                    if path_actions:
                        path_actions.pop()
                elif len(cache) > 1:
                    cache.pop()
                    if path_actions:
                        path_actions.pop()
                continue

            step = action.step

            if step == SafariStep.FLED:
                if pending is not None:
                    astr, cands = pending
                    filtered = [(c, s, d) for c, s, d in cands if c.has_fled()]
                    cache.append((astr, filtered))
                    pending = None
                path_actions.append(action)
                terminal = True
                break

            if step == SafariStep.CAPTURED:
                if pending is not None:
                    astr, cands = pending
                    filtered = [(c, s, d) for c, s, d in cands if c.captured()]
                    cache.append((astr, filtered))
                    pending = None
                path_actions.append(action)
                terminal = True
                break

            # Regular action: resolve pending as no-flee, then apply new action
            if pending is not None:
                astr, cands = pending
                filtered = [(c, s, d) for c, s, d in cands if not c.has_fled()]
                cache.append((astr, filtered))
                pending = None

            new_cands = _apply_action(cache[-1][1], action, filter_fled=False)
            pending = (_action_to_str(action), new_cands)
            path_actions.append(action)

        if terminal:
            final = cache[-1][1]
            event = "captured" if path_actions[-1].step == SafariStep.CAPTURED else "fled"
            print()
            print(f"Pokémon {event}. {len(final)} seed(s) matched this path:")
            nearest_final = sorted(final, key=lambda x: (abs(x[2] - inputs.target_delay), x[1]))[:_config.seeds_displayed]
            by_prox = sorted(nearest_final, key=lambda x: (x[2] - inputs.target_delay, x[1]))
            for i, (_, seed, delay) in enumerate(by_prox, 1):
                print(f"  {i}. seed=0x{seed:08X}  delay={delay}  \u0394={_delta_str(delay - inputs.target_delay)}")
            return [f"0x{seed:08X}" for _, seed, _ in by_prox]


from claytonlib.compass_metronome import (  # noqa: E402, F401
    compass_metronome as compass_metronome,
    CompassMetronomeInput as CompassMetronomeInput,
    MetronomeOpponent as MetronomeOpponent,
)
