"""
compass — Seed identification tool.

Helps the player determine which seed they actually hit during an
attempt. Takes observed in-game events (early safari turn outcomes)
as input and narrows down the candidate seed list to identify the
current RNG state.

Public API re-exported from submodules:
  _types.py   — action types, parsing, options, input dataclass
  _core.py    — seed generation, filtering, evaluation
  _display.py — display helpers
"""
import os

from claytonlib.safari import SafariStep

# Re-export all public + internal names used by callers
from claytonlib.compass._types import (
    CompassAction,
    UndoAction,
    JaneAction,
    ParseError,
    CompassOptions,
    CompassSafariInput,
    parse_input,
    _action_to_str,
    _CHAR_TO_STEP,
    _UNCERTAIN_CANONICAL,
)
from claytonlib.compass._core import (
    _delay_offset_to_second_frame,
    _seed_reachable,
    _generate_candidates,
    _apply_action,
    _evaluate_context,
    _BAIT_STEPS,
    _MUD_STEPS,
    _BALL_STEPS,
)
from claytonlib.compass._display import (
    _print_cheatsheet,
    _delta_str,
    _print_status,
    _print_success,
)


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
                      inputs.evaluation_strategy, inputs.evaluation_criteria,
                      inputs.options)

        if (not _jane_suggested and inputs.options.suggest_jane
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
                from claytonlib.machete import machete_jane, MacheteOptions
                default_turns = MacheteOptions().max_turns_all
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
            nearest_final = sorted(final, key=lambda x: (abs(x[2] - inputs.target_delay), x[1]))[:inputs.options.seeds_displayed]
            by_prox = sorted(nearest_final, key=lambda x: (x[2] - inputs.target_delay, x[1]))
            for i, (_, seed, delay) in enumerate(by_prox, 1):
                print(f"  {i}. seed=0x{seed:08X}  delay={delay}  \u0394={_delta_str(delay - inputs.target_delay)}")
            return [f"0x{seed:08X}" for _, seed, _ in by_prox]


from claytonlib.compass_premetronome import (  # noqa: E402, F401
    compass_premetronome as compass_premetronome,
    CompassPremetronomeInput as CompassPremetronomeInput,
    MetronomeOpponent as MetronomeOpponent,
)
from claytonlib.metronome_compass import (  # noqa: E402, F401
    metronome_compass as metronome_compass,
    CompassMetronomeInput as CompassMetronomeInput,
)
