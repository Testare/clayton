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
import dataclasses
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
    _second_of_frame,
    _seed_reachable,
    _generate_candidates,
    _generate_candidates_calibrated,
    calibrated_candidates,
    posteriors,
    _effective_count,
    _offset_weight,
    _frame_weight,
    _apply_action,
    _evaluate_context,
    _BAIT_STEPS,
    _MUD_STEPS,
    _BALL_STEPS,
)
from claytonlib.compass._display import (
    _print_cheatsheet,
    _delta_str,
    _sec_offset_str,
    _print_status,
    _print_status_calibrated,
    _print_success,
)


# ---------------------------------------------------------------------------
# Path replay + widen (calibrated mode: b70.6)
# ---------------------------------------------------------------------------

def _replay_path(candidates: list, path_actions: list) -> tuple:
    """Re-apply an observed path to a fresh candidate set, reproducing (cache, pending).

    Mirrors the main loop's per-action filtering exactly (a regular action resolves the
    pending set as no-flee then filters; FLED/CAPTURED resolve as fled/captured and stop),
    so a widened candidate set can pick up right where narrowing left off.
    """
    cache: list = [('', candidates)]
    pending = None
    for action in path_actions:
        step = action.step
        if step == SafariStep.FLED:
            if pending is not None:
                astr, cands = pending
                cache.append((astr, [t for t in cands if t[0].has_fled()]))
                pending = None
            break
        if step == SafariStep.CAPTURED:
            if pending is not None:
                astr, cands = pending
                cache.append((astr, [t for t in cands if t[0].captured()]))
                pending = None
            break
        if pending is not None:
            astr, cands = pending
            cache.append((astr, [t for t in cands if not t[0].has_fled()]))
            pending = None
        new_cands = _apply_action(cache[-1][1], action, filter_fled=False)
        pending = (_action_to_str(action), new_cands)
    return cache, pending


def _prompt_widen(inputs: CompassSafariInput) -> CompassSafariInput | None:
    """Prompt to widen the frame and/or second window; return a widened input, or None.

    The frame window is ``±k·σ`` (widen by raising k); the second window is ``±K`` offsets
    (widen by raising K).  Neither changes F* or σ, so the observed path stays valid and is
    re-applied to the expanded set by the caller.
    """
    cur_maxoff = max((abs(d) for d in inputs.second_offsets), default=0)
    while True:
        try:
            choice = input("Widen & re-apply your path?  "
                           "[f]rame  [s]econd  [b]oth  [n]o: ").strip().lower()
        except EOFError:
            return None
        if choice in ('n', ''):
            return None
        if choice in ('f', 's', 'b'):
            break
        print("  enter f, s, b, or n.")

    new_k, new_offsets = inputs.k, inputs.second_offsets
    if choice in ('f', 'b'):
        raw = input(f"  Frame half-width in σ (current {inputs.k:g}): ").strip()
        if raw:
            try:
                new_k = float(raw)
            except ValueError:
                print("  invalid; keeping current frame width.")
    if choice in ('s', 'b'):
        raw = input(f"  Max second offset ±K (current {cur_maxoff}): ").strip()
        if raw:
            try:
                K = abs(int(raw))
                new_offsets = tuple(range(-K, K + 1))
            except ValueError:
                print("  invalid; keeping current second offsets.")

    if new_k == inputs.k and tuple(new_offsets) == tuple(inputs.second_offsets):
        print("  No change made.")
        return None
    # Widening exists to consider seeds the prior-mass cap trimmed, so drop mass_cap -- otherwise
    # calibrated_candidates re-trims to the central mass_cap of the mass and the wider window
    # surfaces nothing new (the sought seed lives in the trimmed tail).
    opts = dataclasses.replace(inputs.options, mass_cap=None)
    return dataclasses.replace(inputs, k=new_k, second_offsets=tuple(new_offsets), options=opts)


def _prompt_expand(inputs: CompassSafariInput) -> CompassSafariInput | None:
    """Expand the calibrated search by a number of FRAMES and SECONDS, in intuitive units.

    Used when the observed path has eliminated every candidate: widen the ±kσ frame window by
    `frames` (converted via σ) and the ±K second-offset range by `seconds`, so the search looks
    for the seed further out.  Blank/0 keeps a value; returns a widened input, or None if nothing
    changed / declined.  (``_prompt_widen`` remains the σ-unit widen behind the `w` command.)
    """
    sigma = max(float(inputs.sigma or 1.0), 1e-9)
    cur_frames = int(round(inputs.k * sigma))
    cur_maxoff = max((abs(d) for d in inputs.second_offsets), default=0)
    print(f"  Current window: ±{cur_frames} frames (k={inputs.k:g}σ, σ≈{sigma:.1f}), "
          f"±{cur_maxoff}s.")
    try:
        raw_f = input("  Expand frames by how many (each side)? [0] ").strip()
        raw_s = input("  Expand seconds by how many (each side)? [0] ").strip()
    except EOFError:
        return None

    def _int(raw, label):
        if not raw:
            return 0
        try:
            return max(0, int(raw))
        except ValueError:
            print(f"  invalid {label}; using 0.")
            return 0

    add_frames = _int(raw_f, "frames")
    add_secs = _int(raw_s, "seconds")
    if add_frames == 0 and add_secs == 0:
        print("  No expansion.")
        return None
    new_k = inputs.k + add_frames / sigma
    new_K = cur_maxoff + add_secs
    # Expanding is a deliberate search into the tail the initial mass_cap excluded, so lift the
    # cap -- otherwise calibrated_candidates re-trims to the central mass and the expansion is a
    # no-op past a point (the eliminated-everything case means the truth IS in that tail).
    opts = dataclasses.replace(inputs.options, mass_cap=None)
    return dataclasses.replace(inputs, k=new_k,
                               second_offsets=tuple(range(-new_K, new_K + 1)), options=opts)


def _observed_path_line(path_actions) -> str:
    """The full observed path as a copy-pasteable string (for recording the run)."""
    return "Observed path: " + ("".join(_action_to_str(a) for a in path_actions) or "(none)")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def compass_safari(inputs: CompassSafariInput) -> list[str]:
    """Interactive safari zone seed identifier.

    Returns a list of hex seed strings (e.g. ['0xABCD1234']) for all seeds
    that matched the observed path. Returns an empty list when no seeds
    matched or the session was quit.
    """
    if inputs.calibrated:
        candidates, meta = calibrated_candidates(inputs)
    else:
        candidates, meta = _generate_candidates(inputs), None
    total = len(candidates)

    # Reference frame for the Δ column / "← target" marker: the commanded target delay in
    # legacy mode, the model's mean battle frame F* in calibrated mode.
    ref = round(inputs.frame_center) if inputs.calibrated else inputs.target_delay

    cache: list[tuple[str, list]] = [('', candidates)]
    pending: tuple[str, list] | None = None
    path_actions: list[CompassAction] = []
    _jane_suggested = False
    _identified_seed: int | None = None   # the seed we last showed the Machete preview for

    def apply_new_inputs(new_inputs) -> bool:
        """Adopt a widened/expanded input, regenerate candidates, and re-apply the full
        observed path.  Returns True if it happened, False if `new_inputs` is None."""
        nonlocal inputs, candidates, meta, total, cache, pending
        if new_inputs is None:
            return False
        inputs = new_inputs
        candidates, meta = calibrated_candidates(inputs)
        total = len(candidates)
        cache, pending = _replay_path(candidates, path_actions)
        print(f"  Now ±{inputs.k:g}σ over offsets {list(inputs.second_offsets)}: "
              f"{total} candidates; re-applied {len(path_actions)} observed step(s).")
        return True

    def apply_widen() -> bool:
        """Prompt to widen the calibrated window (the `w` command) and re-apply the path."""
        return apply_new_inputs(_prompt_widen(inputs))

    _print_cheatsheet(inputs)

    while True:
        current = pending[1] if pending is not None else cache[-1][1]
        print()
        if meta is not None:
            _print_status_calibrated(current, total, ref, meta, path_actions,
                                     inputs.evaluation_strategy, inputs.evaluation_criteria,
                                     inputs.options)
        else:
            _print_status(current, total, ref, path_actions,
                          inputs.evaluation_strategy, inputs.evaluation_criteria,
                          inputs.options)

        # Jane offload signal: raw count in legacy mode; prior-weighted effective count in
        # calibrated mode (a few high-posterior seeds may dominate a long tail of long-shots).
        if meta is not None:
            offload_n = _effective_count([s for _, s, _ in current], meta,
                                         inputs.options.jane_mass)
        else:
            offload_n = len(current)
        if (not _jane_suggested and inputs.options.suggest_jane
                and 1 < offload_n < (os.cpu_count() or 1)):
            extra = (f" ({offload_n} candidates carry {inputs.options.jane_mass:.0%} of the "
                     f"probability)" if meta is not None else "")
            print(f"  (Tip: seed count is small enough that Jane could take over — "
                  f"type 'J' to switch{extra})")
            _jane_suggested = True

        if len(current) == 0:
            print()
            if inputs.calibrated:
                print(f"The observed path eliminated every candidate in the current window "
                      f"(\u00b1{inputs.k:g}\u03c3, \u03c3\u2248{inputs.sigma:.1f}, offsets "
                      f"{list(inputs.second_offsets)}).  Expand the search to look further out, "
                      f"or fix an input error.")
                # Expand by a prompted number of frames + seconds, then re-apply the path.
                if apply_new_inputs(_prompt_expand(inputs)):
                    _identified_seed = None   # a re-found seed should re-offer the Machete preview
                    continue
            else:
                print(f"No matching seed found in window \u00b1{inputs.window}.")
            print(_observed_path_line(path_actions))
            return []

        if len(current) == 1:
            ctx, seed, delay = current[0]
            # Show the identification + a one-time Machete preview, but KEEP going: the user
            # enters the ACTUAL observed steps so the whole path is recorded and a diverging
            # step can still eliminate this (provisional) seed and trigger an expansion.
            if seed != _identified_seed:
                print()
                sec_off = meta[seed]["delta"] if meta is not None and seed in meta else None
                _print_success(seed, delay, ref, path_actions, second_offset=sec_off)
                raw = input("\nRun Machete to preview the capture path from here? (y/n) ").strip().lower()
                if raw in ('y', 'yes'):
                    from claytonlib.machete import machete_one
                    mpath = machete_one(ctx)
                    print(f"Machete path (predicted): {mpath}" if mpath is not None
                          else "Machete found no capture path from this state.")
                print("\nThis seed is provisional -- keep entering the ACTUAL steps you observe. "
                      "If one diverges, the seed is eliminated and you can expand the search; "
                      "enter C/F when captured/fled, or q to stop here.")
                _identified_seed = seed
            # fall through to the input prompt (do NOT return here)

        raw = input("\n>> ").strip()

        if raw.lower() == 'w' and meta is not None:
            apply_widen()
            continue

        if raw.lower() == 'q':
            confirm = input("Quit compass? (y/n) ").strip().lower()
            if confirm in ('y', 'yes'):
                current = pending[1] if pending is not None else cache[-1][1]
                print(_observed_path_line(path_actions))
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
            print(_observed_path_line(path_actions))
            if meta is not None:
                post = posteriors([s for _, s, _ in final], meta)
                ranked = sorted(final, key=lambda x: (-post.get(x[1], 0.0), x[2]))
                for i, (_, seed, delay) in enumerate(ranked[:inputs.options.seeds_displayed], 1):
                    m = meta[seed]
                    print(f"  {i}. seed=0x{seed:08X}  frame={delay}  "
                          f"Δ={_delta_str(delay - ref)}  δ={_delta_str(m['delta'])}s  "
                          f"P={post.get(seed, 0.0) * 100:.2f}%")
                return [f"0x{seed:08X}" for _, seed, _ in ranked]
            nearest_final = sorted(final, key=lambda x: (abs(x[2] - ref), x[1]))[:inputs.options.seeds_displayed]
            by_prox = sorted(nearest_final, key=lambda x: (x[2] - ref, x[1]))
            for i, (_, seed, delay) in enumerate(by_prox, 1):
                print(f"  {i}. seed=0x{seed:08X}  delay={delay}  \u0394={_delta_str(delay - ref)}")
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
