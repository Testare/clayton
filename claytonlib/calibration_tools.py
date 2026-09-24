"""Metronome-compass calibration tools.

A Python port of RNGReporter's HGSS "Seed to Time" verification panel plus the
interactive seed-identification flow used by the Metronome Compass Calibration
notebook.  Given a target datetime + delay and a search window it enumerates the
nearby candidate seeds, each annotated with:

  * roamer relocation -- where Raikou / Entei / Latios(Latias) move to on reload
    (given where they are now), and
  * the Elm phone-call sequence (P / E / K) you can read off in-game.

Both come from walking the LCRNG stream advance_rng seeds, exactly as RNGReporter
does (HgSsRoamers.cs / Responses.cs).  identify_seed() drives the interactive
narrowing: observed roamer routes first, then Elm calls, with a manual fallback.
"""
import datetime as dt
import json
import math
import os
import statistics

from claytonlib.safari import advance_rng
from claytonlib.calibration import CalibrationModel, DEFAULT_MODEL_PATH

# Tokens accepted in a roamer readout to leave a roamer unconstrained.
_REL_WILDCARDS = (".", "-", "*", "?")
# The Elm responses we can read in-game (M is the "pick manually" escape).
_ELM_CHARS = ("P", "E", "K")

# Keyboard fixup: some keys on the dev's keyboard are flaky, so at every input() prompt
# these sequences are substituted in whatever is typed -- \T -> 2, \V -> w.  ipykernel
# resets builtins.input before EACH cell, so a one-off patch cell does not survive to the
# interactive cells; instead every interactive entry point below re-applies this at call
# time.  Edit INPUT_SUBS (or mutate it from the notebook) to add pairs.
INPUT_SUBS = {r"\T": "2", r"\V": "w"}


def install_input_fixup(subs=None):
    """Patch builtins.input to substitute each key in `subs` (default INPUT_SUBS) with its
    value in whatever the user types.  Idempotent (never double-wraps); returns the subs."""
    import builtins
    active = INPUT_SUBS if subs is None else subs
    original = getattr(builtins.input, "_original", builtins.input)
    def patched(prompt=""):
        s = original(prompt)
        for bad, good in active.items():
            s = s.replace(bad, good)
        return s
    patched._original = original
    builtins.input = patched
    return active


# --------------------------------------------------------------------------- #
# Seed + roamer + Elm math (pure)                                             #
# --------------------------------------------------------------------------- #
def seed_for(time: dt.datetime, delay: int) -> int:
    """Gen-4 HGSS initial seed for a *real* datetime + delay.

    times.calculate_seed assumes year 2000 (all its dates are 2000-..), so it drops
    the year term.  RNGReporter folds (year - 2000) into the low 16 bits, so we do too
    (Pandora.cs: "[CCCC] includes Year/Delay", CCCC = (Year - 2000) + Delay):
      AA   = (month*day + minute + second) & 0xFF   -> bits 24..31
      BB   = hour                                    -> bits 16..23
      CCCC = (delay + year - 2000) & 0xFFFF          -> bits 0..15
    """
    aa = (time.month * time.day + time.minute + time.second) & 0xFF
    cccc = (delay + time.year - 2000) & 0xFFFF
    return (aa << 24) | (time.hour << 16) | cccc


def route_from_rng_j(rng16: int) -> int:
    """Raikou / Entei route from a 16-bit RNG value (RNGReporter RouteFromRngJ)."""
    m = rng16 & 15
    return m + 29 if m < 11 else m + 31   # routes {29..39, 42..46}


def route_from_rng_k(rng16: int) -> int:
    """Latios / Latias route from a 16-bit RNG value (RNGReporter RouteFromRngK)."""
    m = rng16 % 25
    if m < 22:
        return m + 1                      # routes 1..22
    return {22: 24, 23: 26, 24: 28}[m]    # routes {24, 26, 28}


# roamer key -> route mapper, in the fixed relocation order.
_ROAMER_ORDER = ("r", "e", "l")
_ROAMER_MAPPERS = {"r": route_from_rng_j, "e": route_from_rng_j, "l": route_from_rng_k}


def _present_from_prev(prev_routes) -> dict:
    """Which roamers are still roaming, inferred from prev_routes: a roamer roams iff it has an
    entry there.  (prev_routes already carries this, so no separate `present` map is needed.)"""
    return {k: (k in prev_routes) for k in _ROAMER_ORDER}


def _present_from_rows(candidates) -> dict:
    """Which roamers are roaming, inferred from candidate rows (route is None when not roaming)."""
    return {k: any(c.get(f"{k}_route") is not None for c in candidates) for k in _ROAMER_ORDER}


def roamer_positions(seed, prev_routes, present=None):
    """Walk the roamer relocation rolls from `seed`.

    prev_routes: dict like {"r": 31, "e": 30, "l": 0} of each roamer's CURRENT route
                 (0 / anything not on its route table forces the first roll to stick).
                 A roamer roams iff it appears here.

    Returns (routes, rng_calls, state) where routes maps r/e/l -> new route (or None if
    that roamer isn't roaming) and state is the LCRNG state after the roamer rolls, ready
    for the Elm calls.
    """
    if present is None:
        present = _present_from_prev(prev_routes)
    state = seed
    calls = 0
    routes = {"r": None, "e": None, "l": None}
    for key in _ROAMER_ORDER:
        if not present.get(key):
            continue
        mapper = _ROAMER_MAPPERS[key]
        prev = prev_routes.get(key, 0)
        while True:
            state = advance_rng(state)
            calls += 1
            route = mapper(state >> 16)
            if route != prev:
                routes[key] = route
                break
    return routes, calls, state


def elm_calls(state, count):
    """`count` Elm responses continuing from LCRNG `state`.  0=E, 1=K, 2=P."""
    out = []
    for _ in range(count):
        state = advance_rng(state)
        out.append("EKP"[(state >> 16) % 3])
    return out


def generate_roamer_candidates_near(
    target_time: dt.datetime,
    target_delay: int,
    seconds_window: int,
    delay_window: int,
    prev_routes: dict,
    elm_count: int = 15,
    match_parity: bool = False,
):
    """Every seed within +/-seconds_window seconds and +/-delay_window delays of
    (target_time, target_delay), annotated with its roamer relocation and Elm calls.

    Returns a list of dicts (one per unique seed) with keys:
      seed, time, delay, sec_delta, delay_delta,
      r_route, e_route, l_route, rng_calls, elm (str), elm_list
    Rows are grouped by time (chronological) then delay ascending.
    match_parity=True keeps only delays with the same even/odd parity as
    target_delay (a real hardware hit lands on one parity).
    """
    by_seed: dict[int, tuple] = {}
    for sec in range(-seconds_window, seconds_window + 1):
        t = target_time + dt.timedelta(seconds=sec)
        for delay in range(target_delay - delay_window, target_delay + delay_window + 1):
            if delay < 0:
                continue
            if match_parity and (delay % 2) != (target_delay % 2):
                continue
            seed = seed_for(t, delay)
            key = (abs(delay - target_delay), abs(sec), seed)
            if seed in by_seed and by_seed[seed][0] <= key:
                continue
            routes, calls, state = roamer_positions(seed, prev_routes)
            elm = elm_calls(state, elm_count)
            by_seed[seed] = (key, {
                "seed": seed,
                "time": t,
                "delay": delay,
                "sec_delta": sec,
                "delay_delta": delay - target_delay,
                "r_route": routes["r"],
                "e_route": routes["e"],
                "l_route": routes["l"],
                "rng_calls": calls,
                "elm": "".join(elm),
                "elm_list": elm,
            })
    rows = [entry for _, entry in by_seed.values()]
    rows.sort(key=lambda c: (c["time"], c["delay"]))
    return rows


def print_roamer_candidates(rows, limit=20):
    print(f"{len(rows)} candidate seed(s)\n")
    if limit is None:
        limit = len(rows)
    print(f"  {'Seed':>10}  {'Time':>19}  {'Delay':>6}  {'dD':>4}  {'ds':>3}  "
          f"{'R':>3} {'E':>3} {'L':>3}  {'#':>2}  Elm")
    for c in rows[:limit]:
        fmt = lambda v: f"{v:>3}" if v is not None else "  ."
        print(f"  0x{c['seed']:08X}  {c['time'].strftime('%Y-%m-%d %H:%M:%S')}  "
              f"{c['delay']:>6}  {c['delay_delta']:>+4}  {c['sec_delta']:>+3}  "
              f"{fmt(c['r_route'])} {fmt(c['e_route'])} {fmt(c['l_route'])}  "
              f"{c['rng_calls']:>2}  {c['elm']}")
    if len(rows) > limit:
        print(f"  ... and {len(rows) - limit} more")


# --------------------------------------------------------------------------- #
# Filtering (pure cores)                                                       #
# --------------------------------------------------------------------------- #
def filter_rel(candidates, observed, present=None):
    """Keep candidates matching an observed roamer readout string.

    observed: one route per roaming legendary in R E L order, space-separated
              (e.g. "38 42 11"); a wildcard token (. - * ?) leaves one free.
    present:  which roamers roam (default: inferred from the candidate rows).
    Returns (matched, keys, tokens).
    """
    if present is None:
        present = _present_from_rows(candidates)
    keys = [k for k in _ROAMER_ORDER if present.get(k)]
    tokens = observed.split()
    if len(tokens) != len(keys):
        raise ValueError(f"expected {len(keys)} value(s) "
                         f"({' '.join(k.upper() for k in keys)}), got {len(tokens)}: {observed!r}")
    wanted = {k: int(tok) for k, tok in zip(keys, tokens) if tok not in _REL_WILDCARDS}
    matched = [c for c in candidates
               if all(c[f"{k}_route"] == v for k, v in wanted.items())]
    return matched, keys, tokens


def filter_elm(candidates, observed):
    """Candidates whose Elm sequence CONTAINS `observed` (the calls heard so far).

    Substring, not prefix: the RNG may advance a few times before the Elm calls we
    actually observe, so the heard sequence can begin partway through the precomputed
    Elm string -- e.g. "EE" matches both "EEPKEK" and "PKPEEE".
    """
    if not observed:
        return list(candidates)
    return [c for c in candidates if observed in c["elm"]]


def parse_elm_input(s):
    """Parse a raw Elm-input string.

    Reads left to right: P/E/K are collected (case-insensitive); every other
    character is ignored (spaces, commas, ...).  An 'M' is the "pick manually"
    escape -- on hitting one we stop and report manual=True.
    Returns (added_calls, manual).
    """
    add = []
    for ch in s.upper():
        if ch in _ELM_CHARS:
            add.append(ch)
        elif ch == "M":
            return "".join(add), True
    return "".join(add), False


# --------------------------------------------------------------------------- #
# Interactive drivers (prompt / print)                                         #
# --------------------------------------------------------------------------- #
def filter_by_observed_rel(candidates, observed=None, limit=20, present=None):
    """Prompt for (or take) an observed roamer readout and print the matches."""
    if present is None:
        present = _present_from_rows(candidates)
    keys = [k for k in _ROAMER_ORDER if present.get(k)]
    if observed is None:
        labels = " ".join(k.upper() for k in keys)
        observed = input(f"Observed roamer routes ({labels}, space-separated, . = any): ")
    matched, keys, tokens = filter_rel(candidates, observed, present)
    shown = " ".join(f"{k.upper()}={t}" for k, t in zip(keys, tokens))
    print(f"\nObserved {shown}  ->  {len(matched)} / {len(candidates)} candidate(s) match\n")
    print_roamer_candidates(matched, limit=limit)
    return matched


def manual_select(candidates):
    """Number the candidates and prompt for a choice.  Returns the chosen dict."""
    if not candidates:
        print("\nNo candidates to choose from.")
        return None
    print("\nManual selection -- remaining candidates:")
    for i, c in enumerate(candidates, 1):
        rel = "/".join(str(c[f"{k}_route"]) if c[f"{k}_route"] is not None else "."
                       for k in _ROAMER_ORDER)
        print(f"  [{i:>2}] 0x{c['seed']:08X}  {c['time'].strftime('%Y-%m-%d %H:%M:%S')}  "
              f"delay={c['delay']:>6}  R/E/L={rel}  Elm={c['elm']}")
    while True:
        raw = input(f"Choose a candidate [1-{len(candidates)}]: ")
        try:
            idx = int(raw)
        except ValueError:
            print("  enter a number.")
            continue
        if 1 <= idx <= len(candidates):
            return candidates[idx - 1]
        print(f"  out of range (1-{len(candidates)}).")


def narrow_by_elm(candidates, limit=20):
    """Narrow >1 candidates by the Elm calls heard, looping until one remains.

    Type P/E/K as you hear each Elm call (across as many inputs as you like);
    non-P/E/K characters are ignored.  Type M at any point to switch to picking
    a candidate manually.

    Returns ``(candidate_or_None, elm_so_far)``: the single surviving candidate dict
    (or None if the calls stopped matching / the user aborted), and the P/E/K calls
    actually entered.  Those calls advance the same Seed A stream the frame-ID step
    walks, so the caller can hand them straight to ``identify_frame(..., observed=...)``
    to avoid re-typing them (clayton-pwy).
    """
    elm_so_far = ""
    remaining = list(candidates)
    while len(remaining) > 1:
        raw = input("Elm calls (type P/E/K as heard; M = pick manually): ")
        add, manual = parse_elm_input(raw)
        elm_so_far += add
        if manual:
            return manual_select(filter_elm(candidates, elm_so_far)), elm_so_far
        print(f"Elm calls so far: {elm_so_far}")
        remaining = filter_elm(candidates, elm_so_far)
        print_roamer_candidates(remaining, limit=limit)
    if len(remaining) == 1:
        return remaining[0], elm_so_far
    print("\nNo candidates match those Elm calls -- check your input.")
    return None, elm_so_far


def identify_seed(candidates, observed_rel=None, display_limit=20, present=None):
    """Interactively pin down the seed you actually hit.

    1. Filter by the observed roamer routes (R E L) -- which roamers roam is inferred from
       the candidate rows, so no separate `present` map is needed.
    2. If more than one remains, narrow by the Elm call sequence (or M to pick).
    3. Print the single result and return the whole candidate row (dict), for use
       as `a_seed` -- its integer seed is `a_seed["seed"]`.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    matched = filter_by_observed_rel(candidates, observed=observed_rel,
                                     limit=display_limit, present=present)
    if not matched:
        print("\nNo candidates match -- check the observed routes or widen the window.")
        return None
    # A single roamer-route match needs no Elm calls to disambiguate, so the carried-over
    # progress must be EMPTY (A.2 starts fresh); otherwise it's whatever the user typed while
    # narrowing.  Recorded on the row as `elm_observed` so Section A.2's identify_frame can
    # pre-fill its `observed` and the user doesn't re-enter the same calls (clayton-pwy).
    if len(matched) == 1:
        result, elm_observed = matched[0], ""
    else:
        result, elm_observed = narrow_by_elm(matched, limit=display_limit)
    if result is None:
        return None
    result["elm_observed"] = elm_observed
    # The winning row was just printed by the step above; confirm it on one line rather
    # than re-printing the whole table.
    c = result
    rel = "/".join(str(c[f"{k}_route"]) if c[f"{k}_route"] is not None else "."
                   for k in _ROAMER_ORDER)
    print(f"\n=== Seed identified: 0x{c['seed']:08X}  "
          f"{c['time'].strftime('%Y-%m-%d %H:%M:%S')}  delay={c['delay']}  "
          f"R/E/L={rel}  Elm={c['elm']} ===")
    return result


# --------------------------------------------------------------------------- #
# Metronome-compass seed identification (ported from the Testing notebook)      #
# --------------------------------------------------------------------------- #
# The Metronome user's movepool BESIDES Metronome (which is always known). These
# extra moves are excluded from Metronome's roll and feed Conversion / Conversion 2
# typing, so they must match between path generation (generate_candidates_near) and
# interactive narrowing (narrow_candidates).  Edit here to change the user's movepool.
DEFAULT_EXTRA_MOVES = ("Fling", "Healing Wish", "Solar Beam")


def resolve_moveset(metronome_only=False):
    """Move numbers for the user's non-Metronome movepool (empty if metronome_only)."""
    if metronome_only:
        return ()
    from claytonlib.moves import resolve_move
    return tuple(resolve_move(name).number for name in DEFAULT_EXTRA_MOVES)


def generate_candidates_near(target_time, target_delay, seconds_window, delay_window,
                             magikarp_level, opposite_gender,
                             metronome_only=False, n_turns=10, user_ability=None):
    """Every seed within +/-seconds_window seconds and +/-delay_window delays of
    (target_time, target_delay), each annotated with its precomputed Metronome battle
    path.  The Metronome user is level 7 and, unless metronome_only=True, knows
    Metronome + DEFAULT_EXTRA_MOVES.

    NOTE: unlike the Testing notebook (which used times.calculate_seed), this uses the
    year-correct seed_for, so 2025+ dates produce the seed the hardware actually hits
    -- consistent with the roamer/Elm section's a_seed.

    Returns a list of dicts (one per unique seed) with keys:
      seed, time, delay, sec_delta, delay_delta, path, path_str
    sorted by (|delay_delta|, |sec_delta|, seed) so the target sits on top.
    """
    from claytonlib.metronome_compass import precompute_path, render_path
    moveset = resolve_moveset(metronome_only)
    by_seed = {}
    for sec in range(-seconds_window, seconds_window + 1):
        t = target_time + dt.timedelta(seconds=sec)
        for delay in range(target_delay - delay_window, target_delay + delay_window + 1):
            if delay < 0:
                continue
            seed = seed_for(t, delay)
            # A seed can be reachable from several (time, delay) pairs; keep the
            # representative closest to the target.
            key = (abs(delay - target_delay), abs(sec), seed)
            if seed in by_seed and by_seed[seed][0] <= key:
                continue
            path = precompute_path(seed, magikarp_level=magikarp_level,
                                   opposite_gender=opposite_gender,
                                   moveset=moveset, n_turns=n_turns,
                                   user_ability=user_ability)
            by_seed[seed] = (key, {
                "seed": seed,
                "time": t,
                "delay": delay,
                "sec_delta": sec,
                "delay_delta": delay - target_delay,
                "path": path,
                "path_str": render_path(path),
            })
    candidates = [entry for _, entry in by_seed.values()]
    candidates.sort(key=lambda c: (abs(c["delay_delta"]), abs(c["sec_delta"]), c["seed"]))
    return candidates


def print_candidates(candidates, limit=20):
    print(f"{len(candidates)} candidate seed(s)\n")
    if limit is None:
        limit = len(candidates)
    print(f"  {'Seed':>10}  {'Time':>19}  {'Delay':>6}  {'dD':>4}  {'ds':>3}  Path")
    for c in candidates[:limit]:
        print(f"  0x{c['seed']:08X}  {c['time'].strftime('%Y-%m-%d %H:%M:%S')}  "
              f"{c['delay']:>6}  {c['delay_delta']:>+4}  {c['sec_delta']:>+3}  {c['path_str']}")
    if len(candidates) > limit:
        print(f"  ... and {len(candidates) - limit} more")


class _AbortRun(Exception):
    """Raised when the user types ABORT at any prompt during narrow_candidates."""


def _abort_on_keyword(orig_input):
    """Wrap input() so typing ABORT (any case) at ANY prompt raises _AbortRun."""
    def wrapped(prompt=""):
        s = orig_input(prompt)
        if s.strip().upper() == "ABORT":
            raise _AbortRun()
        return s
    return wrapped


def narrow_candidates(candidates, magikarp_level, opposite_gender, metronome_only=False,
                      input_fn=None, output_fn=None, user_ability=None):
    """Interactively narrow `candidates` to a single seed.

    `input_fn(prompt) -> str` and `output_fn(*args) -> None` override the console I/O
    (default: builtins input/print), so a non-notebook caller — the app facade — can
    drive the same turn-by-turn narrowing by answering questions programmatically.

    Reuses the metronome_compass battle driver: an InteractiveContext walks the real
    battle turn by turn, asking what actually happened ("Magikarp used? (sp/tk)",
    "Metronome selected? (move name or M###)", "Hit, crit, or miss?", status prompts,
    ...).  After each turn, candidates whose precomputed path diverges from what you
    observed are dropped.  Returns the identified candidate dict (whole row) or None.

    Type ABORT at any prompt to stop and leave the seed unidentified (returns None); the
    run also aborts automatically once no remaining seed has a further turn to observe
    (e.g. the Metronome user Explodes and every path ends).
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    out = output_fn or print  # redirect this driver's own output when run headless
    from claytonlib.metronome_compass import (
        simulate_turn, InteractiveContext, MetronomeBattleState,
        MetronomeMove, _BATTLE_START_ADVANCES,
    )
    from claytonlib.moves import _moves_by_number

    moves_by_num = _moves_by_number()

    # Movepool must match the generation step so Metronome rerolls and
    # Conversion / Conversion 2 typing line up. Metronome (118) is always implicit.
    moveset = resolve_moveset(metronome_only)
    known = frozenset(moveset)

    # One battle context drives the whole session. You answer truthfully, so its
    # state (status / locks / confusion) tracks the real battle across turns.
    ctx = InteractiveContext()
    state = MetronomeBattleState()
    state.target_level = magikarp_level
    # Must match what generate_candidates_near handed precompute_path, for the same reason
    # the movepool must: the candidates' precomputed paths were built with it, so narrowing
    # against a differently-configured battle would compare predictions to a battle nobody ran.
    state.user_ability = user_ability
    ctx.battle_state["opposite_gender"] = opposite_gender
    ctx.battle_state["state"] = state
    user_move_types = [moves_by_num[118].type_name]
    for num in moveset:
        m = moves_by_num.get(num)
        if m is not None:
            user_move_types.append(m.type_name)
    ctx.battle_state["user_move_types"] = user_move_types
    ctx.advance_unobservable(_BATTLE_START_ADVANCES)  # no-op interactively; parity w/ precompute

    def show(remaining, turn_n):
        out(f"\n{len(remaining)} / {len(candidates)} seeds remain -- next is turn {turn_n}")
        out(f"  {'Seed':>10}  {'Delay':>6}  {'dD':>4}  predicted turn {turn_n}")
        for c in remaining[:15]:
            path = c["path"]
            turn_str, move_name = "", "?"
            if len(path) >= turn_n:
                turn = path[turn_n - 1]
                turn_str = "".join(t.render() for t in turn)
                for tok in turn:
                    if isinstance(tok, MetronomeMove):
                        move_name = moves_by_num[tok.move_num].name
                        break
            out(f"  0x{c['seed']:08X}  {c['delay']:>6}  {c['delay_delta']:>+4}  "
                  f"{turn_str:<18} ({move_name})")
        if len(remaining) > 15:
            out(f"  ... and {len(remaining) - 15} more")

    import builtins
    remaining = list(candidates)
    turn_n = 0
    orig_input = builtins.input
    base_input = input_fn or orig_input   # injected callback drives InteractiveContext's input()
    builtins.input = _abort_on_keyword(base_input)  # ABORT at any prompt stops the run
    try:
        while True:
            show(remaining, turn_n + 1)
            if len(remaining) == 1:
                c = remaining[0]
                out(f"\nSeed identified: 0x{c['seed']:08X}  "
                      f"time={c['time'].strftime('%Y-%m-%d %H:%M:%S')}  delay={c['delay']}  "
                      f"dD={c['delay_delta']:+d}")
                out(f"Full path: {c['path_str']}")
                # Metronome moves remaining in the identified seed's path (turns not yet observed).
                out(f"Remaining Metronome moves (turn {turn_n + 1}+):")
                for turn_idx in range(turn_n, len(c["path"])):
                    for tok in c["path"][turn_idx]:
                        if isinstance(tok, MetronomeMove):
                            out(f"  Turn {turn_idx + 1}: {moves_by_num[tok.move_num].name} (M{tok.move_num:03d})")
                return c
            if not remaining:
                out("\nNo seeds match -- check your answers or widen the window above.")
                return None
            # No remaining seed has a turn beyond this one -> nothing left to observe (e.g. the
            # Metronome user Exploded and every path ends).  Can't narrow further; abort.
            if not any(len(c["path"]) > turn_n for c in remaining):
                out(f"\nAll {len(remaining)} remaining seeds' paths end here -- no further turn "
                      f"to observe. Aborting; seed left unidentified.")
                return None

            turn_n += 1
            out(f"\n--- Turn {turn_n}: answer what happened in the battle "
                  f"(or type ABORT to stop) ---")
            simulate_turn(ctx, state, moves_by_num, known, magikarp_level)
            observed = ctx.path[turn_n - 1]
            remaining = [c for c in remaining
                         if len(c["path"]) >= turn_n and c["path"][turn_n - 1] == observed]
    except _AbortRun:
        out("\nRun aborted -- seed left unidentified (b_seed = None).")
        return None
    finally:
        builtins.input = orig_input


def _prompt_until(prompt, parse):
    """input() looped until `parse` returns without ValueError/KeyError."""
    while True:
        try:
            return parse(input(prompt))
        except (ValueError, KeyError) as e:
            print(f"  invalid input{f': {e}' if str(e) else ''} -- try again")


def prompt_magikarp(metronome_user_is_female):
    """Prompt for the wild Magikarp's level and gender (these change every run).

    Returns (magikarp_level, opposite_gender), where opposite_gender is whether the
    Magikarp is the opposite gender to the Metronome user -- what precompute/narrow
    actually need.  The Metronome user's own gender is the stable config
    (b_metronome_user_is_female).
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    level = _prompt_until("Magikarp level: ", lambda s: int(s.strip()))

    def parse_gender(s):
        try:
            return {"m": False, "male": False, "f": True, "female": True}[s.strip().lower()]
        except KeyError:
            raise ValueError("enter M or F")

    magikarp_is_female = _prompt_until("Magikarp gender (M/F): ", parse_gender)
    return level, (magikarp_is_female != metronome_user_is_female)


# --------------------------------------------------------------------------- #
# Persisting a calibration run                                                  #
# --------------------------------------------------------------------------- #
COMPASS_RUNS_PATH = os.path.join("data", "compass_runs.jsonl")

# Which keys of an identified seed row are worth persisting (the rest -- live path
# objects, redundant time-deltas -- are dropped).  `time` is handled separately.
_SEED_PERSIST_KEYS = (
    "delay", "sec_delta", "delay_delta",
    "r_route", "e_route", "l_route", "rng_calls", "elm", "path_str",
)


def _seed_summary(row):
    """A JSON-serializable summary of an identified seed row (or None)."""
    if row is None:
        return None
    out = {"seed": row["seed"], "seed_hex": f"0x{row['seed']:08X}"}
    if isinstance(row.get("time"), dt.datetime):
        # The seed depends only on whole seconds; M-based b_target_time carries millis we don't
        # actually know, so drop the sub-second part rather than record a spurious fraction.
        out["time"] = row["time"].replace(microsecond=0).isoformat()
    for k in _SEED_PERSIST_KEYS:
        if k in row:
            out[k] = row[k]
    return out


def _last_run(path):
    """The last saved run dict (for prompt defaults), or {} if the file is empty/absent."""
    if not os.path.exists(path):
        return {}
    last = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if last is None:
        return {}
    try:
        return json.loads(last)
    except json.JSONDecodeError:
        return {}


def _prompt_default(prompt, default, parse=lambda s: s):
    """Prompt, defaulting to `default` on blank input.

    If the input is blank and `default` is None, re-prompt (no default to fall back on).
    Otherwise parse the input, re-prompting on ValueError/KeyError.
    """
    hint = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{hint}: ").strip()
        if not raw:
            if default is not None:
                return default
            print("  no previous value -- please enter one.")
            continue
        try:
            return parse(raw)
        except (ValueError, KeyError) as e:
            print(f"  invalid input{f': {e}' if str(e) else ''} -- try again")


def _parse_bool(s):
    """Parse a y/n-style answer to a bool (for _prompt_default); raises ValueError otherwise."""
    v = s.strip().lower()
    if v in ("y", "yes", "true", "t", "1"):
        return True
    if v in ("n", "no", "false", "f", "0"):
        return False
    raise ValueError("enter y/n")


def _prompt_yes_no(prompt):
    """Loop until the user answers yes/no/y/n (case-insensitive); returns a bool."""
    while True:
        raw = input(prompt).strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  please answer y/n.")


def save_compass_run(a_seed, b_seed, path=COMPASS_RUNS_PATH, update_model=False,
                     model_path=DEFAULT_MODEL_PATH):
    """Prompt for run metadata, preview the record, and append it to compass_runs.jsonl.

    Persists one JSON line combining the two identified seeds (`a_seed` from the
    roamer/Elm section, `b_seed` from the Metronome section) with:
      * tag                       -- e.g. "300s Samwise" / "11000d Work"
      * target_timer_delay        -- the timer delay you were aiming for (int)
      * target_timer_calibration  -- the timer calibration you were aiming for (int)
      * notes                     -- free-form (never defaulted)
    The first three default to the previous run's values on blank input.  The record is
    pretty-printed and confirmed (y/n, re-prompting) before it is written.  Returns the
    saved record dict, or None if the user declined.

    Saving does NOT touch the shared calibration model by default: changing it would
    invalidate a precomputed chart (an hour to rebuild), and you often save test runs while
    charting a target from the current model.  Review and apply model changes deliberately
    with ``update_calibration_model()`` (its own notebook cell).  ``update_model=True`` opts
    back into the old auto-refresh.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    prev = _last_run(path)

    tag = _prompt_default("Run tag", prev.get("tag"))
    target_timer_delay = _prompt_default(
        "Target timer delay", prev.get("target_timer_delay"), int)
    target_timer_calibration = _prompt_default(
        "Target timer calibration", prev.get("target_timer_calibration"), int)
    notes = input("Notes: ").strip()

    # The calibration protocol is always a fresh boot straight to one battle, so provenance is
    # fixed (fresh_boot=True, prior_battles=0).  The fields are still recorded so the fit's
    # contamination screen keeps working over older, mixed-provenance runs.
    record = {
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "tag": tag,
        "target_timer_delay": target_timer_delay,
        "target_timer_calibration": target_timer_calibration,
        "fresh_boot": True,
        "prior_battles": 0,
        "notes": notes,
        "a_seed": _seed_summary(a_seed),
        "b_seed": _seed_summary(b_seed),
    }

    print("\n" + json.dumps(record, indent=2))
    if not _prompt_yes_no("\nSave this run? (y/n): "):
        print("Not saved.")
        return None

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Saved to {path}")

    # By default the shared calibration model is left untouched -- refitting it here would
    # silently change what the chart/expedition use (invalidating a precomputed chart).  Opt
    # in with update_model=True, or review + apply deliberately via update_calibration_model().
    if update_model:
        try:
            models = export_calibration_model(runs_path=path, out_path=model_path)
            cm = models.get("linear") or next(iter(models.values()))
            print(f"Updated calibration modelset {sorted(models)} "
                  f"({cm.n_runs} run(s), {cm.n_fit} in fit) -> {model_path}")
        except Exception as e:  # noqa: BLE001 - advisory only
            print(f"  (calibration model not updated: {e})")
    else:
        print("Calibration model NOT updated (run update_calibration_model() to review "
              "+ apply changes).")
    return record


# --------------------------------------------------------------------------- #
# Persisting a SAFARI compass run                                               #
# --------------------------------------------------------------------------- #
# The safari path has a Safari-Zone loading screen the metronome path lacks, so its runs
# are collected separately (data/safari_runs.jsonl) -- keeping them apart lets the load
# offset between the two be measured later rather than assumed zero (notes/refined_chart.md).
# Unlike metronome-compass, safari-compass often can't pin a single seed, so the seed is
# recorded only when the candidate set narrowed to exactly one.
SAFARI_RUNS_PATH = os.path.join("data", "safari_runs.jsonl")


def load_safari_runs(path=SAFARI_RUNS_PATH):
    """Every saved safari run record (list of dicts) from safari_runs.jsonl (or [])."""
    return load_compass_runs(path)  # identical JSONL reader


def _safari_seed_delay(inputs, seed_int):
    """Recover the delay of `seed_int` from a CompassSafariInput's candidate window (or None).

    compass_safari returns only hex seeds; the delay lives on the (ctx, seed, delay) triples
    _generate_candidates produces, so we re-derive it here without changing compass_safari.
    """
    if inputs is None:
        return None
    try:
        from claytonlib.compass._core import _generate_candidates
        for _ctx, s, d in _generate_candidates(inputs):
            if s == seed_int:
                return d
    except Exception:
        return None
    return None


def _safari_calibrated_meta(inputs, seed_int):
    """Recover (frame, second, delta) for `seed_int` directly from a calibrated CompassSafariInput.

    Everything is decoded from the identified seed itself -- no need to regenerate the sweep:
      * ``frame``  = the battle-seed low16 (``seed & 0xFFFF``; seed_for_mdmsh stores the frame there),
      * ``second`` = the RTC second offset from boot whose ``mdmsh`` matches the seed's high bytes.
        ``mdmsh_of`` is locally injective, so exactly one offset around the model's target_second
        matches -- that IS the landing second (frame ⊥ second; notes/seed_hitting_process.md §3-4),
      * ``delta``  = ``second - target_second`` = the timing miss vs the model's target second.

    Returns a dict or None (legacy inputs, or the seed's mdms/hour matches no swept second).
    """
    if inputs is None or not getattr(inputs, "calibrated", False) or seed_int is None:
        return None
    try:
        from claytonlib.chart.canon import mdmsh_of
        want = ((seed_int >> 24) & 0xFF, (seed_int >> 16) & 0xFF)   # the seed's (mds, hour)
        # Prefer the smallest |δ| on a match (same representative the sweep keeps on an mdms tie).
        for delta in sorted(inputs.second_offsets, key=abs):
            s = inputs.target_second + delta
            if s >= 0 and mdmsh_of(inputs.initial_time + dt.timedelta(seconds=s)) == want:
                return {"frame": seed_int & 0xFFFF, "delta": delta, "second": s}
        return None
    except Exception:
        return None


def _offset_phrase(delta):
    if delta == 0:
        return "on time (δ=0)"
    return f"{delta:+d}s {'late' if delta > 0 else 'early'} (δ={delta:+d})"


def save_safari_run(matched, inputs=None, path=None, save_path=SAFARI_RUNS_PATH,
                    a_seed=None, target_timer_delay=None, elm_calls=None, chatot_flips=None,
                    advance_frame=None):
    """Prompt for run metadata, preview the record, and append it to safari_runs.jsonl.

    Parameters
    ----------
    matched:
        The return of compass_safari(...) -- a list of hex seed strings (e.g. ['0x0C0E02CA'])
        that matched the observed path.  The identified seed is recorded ONLY when exactly one
        matched; otherwise the ambiguous candidate set is still saved (as matched_seeds) but
        `seed` is null, so it can be excluded from any fit that needs a confident seed.
    a_seed:
        The Section-A initial-seed row (from identify_seed), if known.  Stored as `a_seed` so
        the safari offset fit has F_a (= a_seed low16, carries the year) to reconstruct the dF
        prediction -- exactly like the metronome run's a_seed.  Optional (older runs omit it).
    inputs:
        Optional CompassSafariInput -- when given and the seed is unique, its delay (the F_b
        analog) is recovered from the candidate window for the later safari-vs-metronome
        offset analysis.
    path:
        Optional observed-safari-path string; prompted for if omitted.
    target_timer_delay:
        The commanded countdown M (ms) -- pass the notebook's ``b_target_timer_delay`` directly;
        it is recorded as-is with no prompt.  Falls back to the previous run's value if omitted.
        Safari runs use no separate timer calibration (M = target_timer_delay).
    advance_frame:
        The Section-A Seed-A advance frame Sweet Scent was actually pressed on -- i.e. the
        ``AdvancePlan.encounter_frame`` (pass the notebook's ``a_plan.encounter_frame`` or
        ``a_target_frame``).  Unlike ``elm_calls``/``chatot_flips`` (the recipe's raw counts),
        this is the landing frame itself, and is the more directly compensable signal for a
        safari-chart target: it's the frame the encounter (species/IVs/nature) actually rolled
        on, independent of how the approach was split between chatot flips and Elm calls.
    save_path:
        Destination JSONL (default data/safari_runs.jsonl).

    The only interactive prompts are the run tag, the notes, and the final save confirmation.
    The record captures the landing -- ``frame`` (battle frame hit), ``target_frame`` (the model's
    F*), and ``frame_delta`` (the signed miss) -- plus the RTC second / offset; it carries no
    fresh_boot / prior_battles / timer-calibration fields (safari runs are always a fresh boot with
    M = target_timer_delay).  The record is pretty-printed and confirmed (y/n) before it is
    written.  Returns the saved record dict, or None if the user declined.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    prev = _last_run(save_path)

    matched = list(matched or [])
    seed_int = int(matched[0], 16) if len(matched) == 1 else None

    # Calibrated flow: recover (frame, second, δ) from the candidate meta; the frame is the
    # F_b analog (delay).  Legacy flow: recover the delay from the legacy candidate window.
    cal = _safari_calibrated_meta(inputs, seed_int)
    if cal is not None:
        delay = cal["frame"]
        print(f"Inferred timer offset: {_offset_phrase(cal['delta'])}  "
              f"(frame {cal['frame']}, RTC second {cal['second']}).")
    else:
        delay = _safari_seed_delay(inputs, seed_int) if seed_int is not None else None

    if target_timer_delay is None:
        target_timer_delay = prev.get("target_timer_delay")

    # Reference battle frame (F* in calibrated mode, the commanded delay in legacy) and the signed
    # frame miss (hit - target) -- the core calibration signal shown as Δ in the compass.
    if inputs is not None and getattr(inputs, "calibrated", False):
        target_frame = round(inputs.frame_center)
    else:
        target_frame = getattr(inputs, "target_delay", None) if inputs is not None else None
    frame_delta = (delay - target_frame) if (delay is not None and target_frame is not None) else None

    tag = _prompt_default("Run tag", prev.get("tag"))
    if path is None:
        path = input("Safari path (observed): ").strip()
    notes = input("Notes: ").strip()

    record = {
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "tag": tag,
        "target_timer_delay": target_timer_delay,
        "path": path,
        "n_matched": len(matched),
        "matched_seeds": matched,
        # Populated only when the candidate set narrowed to exactly one seed.
        "seed": seed_int,
        "seed_hex": f"0x{seed_int:08X}" if seed_int is not None else None,
        "delay": delay,
        # Landing: the battle frame hit, the model's target frame F*, and the signed miss.
        "frame": cal["frame"] if cal else None,
        "target_frame": target_frame,
        "frame_delta": frame_delta,
        "second": cal["second"] if cal else None,
        "second_offset": cal["delta"] if cal else None,
        # Section-A.2 advance recipe (Seed A): how many Elm calls and chatot flips reached the
        # encounter frame -- recorded to test whether they correlate with frame_delta (Seed B miss).
        "elm_calls": elm_calls,
        "chatot_flips": chatot_flips,
        # The Seed-A advance frame Sweet Scent was actually pressed on (AdvancePlan.encounter_frame).
        # More directly useful than elm_calls/chatot_flips for compensating a safari-chart target.
        "advance_frame": advance_frame,
        # Section-A initial seed (for F_a in the safari offset fit); null on older runs.
        "a_seed": _seed_summary(a_seed),
        "notes": notes,
    }

    print("\n" + json.dumps(record, indent=2))
    if len(matched) != 1:
        print(f"\nNote: {len(matched)} seeds matched -- seed left null (not a confident single seed).")
    if not _prompt_yes_no("\nSave this run? (y/n): "):
        print("Not saved.")
        return None

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "a") as f:
        f.write(json.dumps(record) + "\n")
    print(f"Saved to {save_path}")
    return record


# --------------------------------------------------------------------------- #
# Timer calibration: map a commanded countdown to the seed_b frame             #
# --------------------------------------------------------------------------- #
# Model (see the notebook's Section D writeup):
#
#     F_b = beta * M + alpha          M = target_timer_delay + target_timer_calibration  (ms)
#
#   * beta  = frames per ms = rate/1000, rate ~= 59.8261 Hz.  The SLOPE.
#   * alpha = INTERCEPT.  Absorbs every fixed offset at once -- the ~5 s between timer
#             expiry and battle-seed generation AND the "load advances the clock but not
#             the frame counter" y-intercept.  The two are degenerate: only their sum is
#             identifiable, and alpha (hence the calibration) is exactly that sum.
#
# Two independent slope estimators:
#   * within-run:  rate = (F_b - F_a) / (T_b - T_a).  Works from ONE run off a long lever
#                  arm.  Only this one is hurt by the +/-1 s timestamp granularity.
#   * between-run: regress F_b on M.  Immune to the +/-1 s issue but needs M to vary.
#
# A run's two timestamps are each truncated to the second, so the true elapsed time is
# within (dt-1, dt+1).  The 1-sigma of that difference-of-two-truncations is ~0.41 s;
# +/-1 s is the hard worst case.
_TIMING_SIGMA = 1.0 / math.sqrt(6.0)   # ~0.408 s, std of a difference of two U(0,1) truncations
_NOMINAL_RATE = 59.8261                # DS VBlank Hz, for reference / priors
_OUTLIER_K = 3.5                       # a run is an outlier past k robust-sigmas (MAD-based)


def load_compass_runs(path=COMPASS_RUNS_PATH):
    """Every saved run record (list of dicts) from compass_runs.jsonl (or [])."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _run_metrics(rec):
    """Per-run derived quantities, or None if the record lacks both identified seeds.

    Returns a dict with: tag, M (commanded ms), Fa, Fb, dF, dt (s), and -- when dt > 0 --
    rate and its +/-1 s worst-case bounds (rate_lo/rate_hi).
    """
    a, b = rec.get("a_seed"), rec.get("b_seed")
    if not a or not b or "time" not in a or "time" not in b:
        return None
    Fa, Fb = a["delay"], b["delay"]
    Ta = dt.datetime.fromisoformat(a["time"])
    Tb = dt.datetime.fromisoformat(b["time"])
    dt_s = (Tb - Ta).total_seconds()
    M = rec["target_timer_delay"] + rec["target_timer_calibration"]
    m = {"tag": rec.get("tag"), "M": M, "Fa": Fa, "Fb": Fb, "dF": Fb - Fa, "dt": dt_s,
         # Provenance (older records predate these fields -> treated as a clean fresh boot).
         "prior_battles": rec.get("prior_battles", 0),
         "fresh_boot": rec.get("fresh_boot", True),
         # Opaque passthrough (e.g. an app-side run id) so a caller that fits from an
         # in-memory `runs` list (see calibrate_timer) can map outlier/contaminated flags
         # back onto its own records. None (and ignored) for the plain JSONL path.
         "_run_id": rec.get("_run_id")}
    if dt_s > 0:
        m["rate"] = m["dF"] / dt_s
        m["rate_lo"] = m["dF"] / (dt_s + 1)                       # time really longer
        m["rate_hi"] = m["dF"] / (dt_s - 1) if dt_s > 1 else float("inf")  # really shorter
    return m


def _norm_cdf(z):
    """Standard-normal CDF via math.erf (stdlib; avoids a scipy dependency)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _robust_flags(values, k, floor=0.0):
    """Bool list: True where a value is a robust (MAD-based) outlier.

    Flags |v - median| > k * scale, where scale = max(1.4826*MAD, floor).  The `floor`
    keeps tightly-clustered data (tiny MAD) from producing a hair-trigger threshold that
    flags runs sitting within the real measurement noise -- pass the physical noise level.
    Returns all-False if there are fewer than 4 finite values or the scale is zero.  NaNs
    are never flagged, so a metric missing for some runs (e.g. rate on an untimed run) is
    simply skipped.
    """
    finite = [v for v in values if v == v]
    if len(finite) < 4:
        return [False] * len(values)
    med = statistics.median(finite)
    mad = statistics.median([abs(v - med) for v in finite])
    scale = max(1.4826 * mad, floor)
    if scale <= 0:
        return [False] * len(values)
    return [(v == v) and abs(v - med) > k * scale for v in values]


def _theil_sen(xs, ys):
    """Robust (slope, intercept): median pairwise slope, median residual intercept.

    Needs >= 2 points with distinct x; returns None if x never varies.
    """
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs))
              if xs[j] != xs[i]]
    if not slopes:
        return None
    slope = statistics.median(slopes)
    intercept = statistics.median([y - slope * x for x, y in zip(xs, ys)])
    return slope, intercept


def _gauss_solve(A, b):
    """Solve A x = b for a small dense system (partial pivoting).  None if singular."""
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for c in range(n):
        p = max(range(c, n), key=lambda i: abs(M[i][c]))
        if abs(M[p][c]) < 1e-15:
            return None
        M[c], M[p] = M[p], M[c]
        for i in range(n):
            if i != c:
                f = M[i][c] / M[c][c]
                for j in range(c, n + 1):
                    M[i][j] -= f * M[c][j]
    return [M[i][n] / M[i][i] for i in range(n)]


def _poly_fit(us, ys, degree):
    """Least-squares polynomial coefficients [c0..c_degree] over basis u**j (u is expected
    pre-centered/scaled to O(1) so the normal equations stay well-conditioned)."""
    n = degree + 1
    S = [[0.0] * n for _ in range(n)]
    rhs = [0.0] * n
    for u, y in zip(us, ys):
        pw = [u ** j for j in range(n)]
        for j in range(n):
            rhs[j] += pw[j] * y
            for k in range(n):
                S[j][k] += pw[j] * pw[k]
    return _gauss_solve(S, rhs)


def _jitter_from_resid(resid):
    """(jitter_c, jitter_rms) from [(M, residual), ...].

    jitter_rms is the plain RMS; jitter_c is the coefficient of a diffusive sigma(M) =
    c*sqrt(M) (random-walk frame jitter).  (None, None) if fewer than 2 residuals.
    """
    if len(resid) < 2:
        return None, None
    rms = math.sqrt(statistics.mean(e * e for _, e in resid))
    pos = [(e * e) / M for M, e in resid if M > 0]
    c = math.sqrt(statistics.mean(pos)) if pos else None
    return c, rms


def _make_predictors(fit, n_fit, Sxx, M_bar, jitter_c, jitter_rms):
    """Build (predict, solve, hit_probability, model) over a fitted mean function.

    The math lives in the reusable claytonlib.calibration.CalibrationModel (so the chart
    and this notebook share one implementation); these closures just adapt its M-based API
    to the notebook's (delay, calibration) call convention.  `model` is the CalibrationModel
    itself, for the chart to consume directly.
    """
    cm = CalibrationModel.from_fit(fit, n_fit, Sxx, M_bar, jitter_c, jitter_rms)

    def predict(delay, calibration, k=2.0):
        return cm.predict(delay + calibration, k)

    def solve(target_fb, delay=None, calibration=None):
        M = cm.solve(target_fb)
        out = {"M": M}
        if delay is not None:
            out["calibration"] = M - delay
            out["delay"] = delay
        elif calibration is not None:
            out["delay"] = M - calibration
            out["calibration"] = calibration
        return out

    def hit_probability(delay, calibration, target_fb, tolerance=0.5,
                        perfect_calibration=False):
        return cm.hit_probability(delay + calibration, target_fb, tolerance,
                                  include_calibration=not perfect_calibration)

    return predict, solve, hit_probability, cm


def _line_fit(slope, intercept, Ms, Fbs):
    """Fit dict for a fixed straight line F_b = intercept + slope*M."""
    f = lambda M: intercept + slope * M
    solve_M = (lambda t: (t - intercept) / slope) if slope else (lambda t: 0.0)
    return {"kind": "line", "beta": slope, "alpha": intercept,
            "f_of_M": f, "dfdM": (lambda M: slope), "solve_M": solve_M,
            "resid": [(M, F - f(M)) for M, F in zip(Ms, Fbs)]}


def _poly_model(Ms, Fbs, degree, M_bar, M_scale):
    """Fit dict for a degree-`degree` polynomial of the centered/scaled u=(M-M_bar)/M_scale.
    None if the fit is singular (e.g. too few distinct M)."""
    us = [(M - M_bar) / M_scale for M in Ms]
    coeffs = _poly_fit(us, Fbs, degree)
    if coeffs is None:
        return None

    def f_of_M(M):
        u = (M - M_bar) / M_scale
        return sum(c * u ** j for j, c in enumerate(coeffs))

    def dfdM(M):
        u = (M - M_bar) / M_scale
        return sum(j * c * u ** (j - 1) for j, c in enumerate(coeffs) if j >= 1) / M_scale

    def solve_M(target):
        M = M_bar  # Newton from the centroid; f is monotonic over the data range
        for _ in range(80):
            slope = dfdM(M)
            if slope == 0:
                break
            step = (f_of_M(M) - target) / slope
            M -= step
            if abs(step) < 1e-4:
                break
        return M

    return {"kind": "quad", "coeffs": coeffs, "m_center": M_bar, "m_scale": M_scale,
            "f_of_M": f_of_M, "dfdM": dfdM, "solve_M": solve_M,
            "resid": [(M, F - f_of_M(M)) for M, F in zip(Ms, Fbs)]}


def calibrate_timer(path=COMPASS_RUNS_PATH, verbose=True, fresh_only=True, runs=None):
    """Fit F_b as a function of the commanded countdown M and return a calibration model.

    Builds several candidate models (in `model["models"]`), each carrying predict / solve /
    hit_probability closures:
      * "within_rate" (PREVIOUS) -- a line whose slope is the within-run *average* frame
        rate.  Kept only for comparison; it uses the wrong slope for F_b-vs-M (the average
        rate is dragged down by the slow post-boot frames), so its residuals grow with |M|.
      * "linear_m" (NEW, recommended) -- fits F_b directly against M (robust Theil-Sen).
        Slope = the instantaneous rate at battle time (~near the 60 Hz ceiling by 3-7 min).
      * "quad_m" (NEW, experimental) -- adds an M^2 term to test whether the rising
        instantaneous rate curves F_b(M) measurably yet.

    `model["recommended"]` names the default, and model["predict"/"solve"/"hit_probability"]
    point at it.  Each closure:
      * predict(delay, calibration, k=2.0) -> {expected, lo, hi, jitter, rate_band}
          expected seed_b frame with lo/hi = expected +/- (reducible mean-uncertainty band
          + k*jitter); jitter is the irreducible spread (grows ~sqrt(M)).
      * solve(target_fb, delay=None, calibration=None) -> {M, delay, calibration}
          the commanded countdown to land on target_fb.
      * hit_probability(delay, calibration, target_fb, tolerance=0.5) -> {p, ...}
          probability of landing within tolerance frames of target_fb.

    Runs that are robust outliers off the F_b-vs-M trend are shown in the report but
    EXCLUDED from the fit, so one mis-identified seed can't poison the model.

    `runs`, if given, is used INSTEAD of reading `path` — a list of run records already in
    memory (JSONL-record shape: tag/target_timer_delay/target_timer_calibration/a_seed/
    b_seed/...), e.g. already curated by a caller's own manual/tag exclusion pass. `path` is
    then unused for reading (only ever relevant to the default file-based call).
    """
    raw = runs if runs is not None else load_compass_runs(path)
    all_runs = [m for m in (_run_metrics(r) for r in raw) if m]
    if not all_runs:
        raise ValueError(f"no usable runs in {path} (need both a_seed and b_seed identified)")

    # --- contamination screening (provenance) --------------------------------
    # A run that traversed prior battles this boot sits ~800 frames/battle off the fresh-boot
    # F_b-vs-M trend (notes/refined_chart.md 5.5).  With fresh_only (default) these are marked
    # and excluded from the fit up front -- by construction, not by the statistical detector.
    for m in all_runs:
        m["contaminated"] = fresh_only and m.get("prior_battles", 0) > 0

    # --- outlier screening (robust, M-aware) ---------------------------------
    # Flag a run whose F_b is a robust outlier off the F_b-vs-M trend.  We fit that trend
    # with Theil-Sen (which tolerates the very outliers we're hunting), then flag any run
    # whose residual exceeds k robust-sigmas.  Because the trend line absorbs the
    # legitimate rise of frame rate with M, a run that is anomalous *for its M* is still
    # caught -- unlike flagging the raw within-run rate, which that rising trend now masks
    # (a genuinely low-rate run no longer looks extreme once long runs reach ~59 Hz).
    # A mis-identified seed or a mis-entered delay both push F_b off the line, so this one
    # test covers what the old rate/offset pair did.  The scale is floored at ~1 s of
    # countdown (slope*1000 frames) so a tight clean cluster isn't a hair-trigger.
    for m in all_runs:
        m["outlier"] = False
        m["outlier_reason"] = ""
    # Detect off-trend outliers on the non-contaminated subset so the ~800-frame battle
    # offset can't distort the trend line used to catch them.
    screen = [m for m in all_runs if not m["contaminated"]]
    ts_all = _theil_sen([m["M"] for m in screen], [m["Fb"] for m in screen]) if len(screen) >= 2 else None
    if ts_all is not None:
        slope0, intercept0 = ts_all
        resids = [m["Fb"] - (intercept0 + slope0 * m["M"]) for m in screen]
        for m, rf in zip(screen, _robust_flags(resids, _OUTLIER_K, slope0 * 1000.0)):
            m["outlier"] = bool(rf)
            m["outlier_reason"] = "off-trend" if rf else ""

    # Fit on the clean subset: neither contaminated nor a statistical outlier
    # (falling back to everything if that somehow leaves nothing).
    runs = [m for m in all_runs if not m["outlier"] and not m["contaminated"]] or list(all_runs)
    timed = [m for m in runs if "rate" in m]

    Ms = [m["M"] for m in runs]
    Fbs = [m["Fb"] for m in runs]
    dFs = [m["dF"] for m in runs]          # F_b - F_a, per run (option-2 target)
    M_bar = statistics.mean(Ms)
    Fb_bar = statistics.mean(Fbs)
    dF_bar = statistics.mean(dFs)

    # RTC-second offset: the battle RTC second is M/1000 s past the initial seed plus a fixed
    # real-time setup lead.  Both seeds carry their boot RTC datetime (mds/hour), so the actual
    # elapsed RTC seconds is dt = Tb - Ta, and the lead is dt - M/1000 (independent of the frame
    # counter).  Averaged over the clean runs; the +/-1 s spread is the timestamp truncation,
    # which compass-safari's delta axis absorbs.  A Safari-Zone-entry lead would add on top.
    rtc_offs = [m["dt"] - m["M"] / 1000.0 for m in runs if m.get("dt") is not None]
    rtc_offset_seconds = statistics.mean(rtc_offs) if rtc_offs else 0.0
    # Spread of that offset = σ_S, the battle-second wander (used to marginalize capture over the
    # RTC second).  NOTE: this cross-run spread likely OVERstates the within-session σ_S (it also
    # absorbs session-to-session δ0 drift); refine as sub-second data is gathered.
    rtc_offset_std = statistics.pstdev(rtc_offs) if len(rtc_offs) > 1 else 0.0

    # Within-run rate: pooled total frames / total seconds (its +/-1 s error averages down).
    within = None
    if timed:
        tot_dF = sum(m["dF"] for m in timed)
        tot_dt = sum(m["dt"] for m in timed)
        rate = tot_dF / tot_dt
        rate_sigma = rate * (_TIMING_SIGMA * math.sqrt(len(timed))) / tot_dt
        within = {"rate": rate, "rate_sigma": rate_sigma, "n": len(timed)}

    # Direct F_b-vs-M slope (robust), the correct slope for predicting F_b from M.
    ts = _theil_sen(Ms, Fbs)
    regression = {"beta": ts[0], "alpha": ts[1], "rate": ts[0] * 1000.0} if ts else None

    # Option-2 target: dF = F_b - F_a vs M.  Same slope family, but the intercept now absorbs
    # only the fixed ~5 s A-to-A lever -- NOT F_a (the initial-seed frame) and NOT the year
    # term.  Reconstruction re-adds the run's ACTUAL F_a (= low16 of the initial seed, which
    # already carries year), so this is year-agnostic and reuses data across target years.
    # Its RMS residual is directly comparable to the F_b fit's: it IS option 2's F_b error.
    ts_df = _theil_sen(Ms, dFs)
    regression_df = {"beta": ts_df[0], "alpha": ts_df[1], "rate": ts_df[0] * 1000.0} if ts_df else None

    # Geometry shared by every model's uncertainty band.
    M_scale = statistics.pstdev(Ms) if len(Ms) > 1 else 1.0
    Sxx = sum((M - M_bar) ** 2 for M in Ms)

    # ---- build the candidate models (each: mean fn + jitter + closures) ------
    # Deployed: the dF fits (linear default, quad optional) -- fit dF = F_b - F_a vs M and
    # reconstruct F_b = dF + F_a.  Also fit F_b directly and the within-run average rate as
    # diagnostic baselines (their RMS lets you sanity-check the dF fit and see the rate).
    models = {}

    def add_model(key, label, kind, fit, target="Fb"):
        if fit is None:
            return
        jc, jr = _jitter_from_resid(fit["resid"])
        pred, solv, hp, cm = _make_predictors(fit, len(runs), Sxx, M_bar, jc, jr)
        cm.label = label
        cm.n_runs = len(all_runs)
        cm.m_lo, cm.m_hi = (min(Ms), max(Ms)) if Ms else (None, None)
        cm.rtc_offset_seconds = rtc_offset_seconds
        cm.rtc_offset_std = rtc_offset_std     # σ_S: battle-second spread (marginalization)
        cm.target = target          # "Fb" (mean=F_b) or "dF" (mean=dF; frame()=dF+F_a)
        models[key] = {"label": label, "kind": kind, "fit": fit, "target": target,
                       "f_of_M": fit["f_of_M"], "dfdM": fit.get("dfdM"),
                       "solve_M": fit["solve_M"], "coeffs": fit.get("coeffs"),
                       "jitter_c": jc, "jitter_rms": jr, "model": cm,
                       "predict": pred, "solve": solv, "hit_probability": hp}

    if within is not None:
        add_model("within_rate", "within-run-rate slope", "line",
                  _line_fit(within["rate"] / 1000.0,
                            Fb_bar - (within["rate"] / 1000.0) * M_bar, Ms, Fbs))
    if regression is not None:
        add_model("linear_m", "F_b line", "line",
                  _line_fit(regression["beta"], regression["alpha"], Ms, Fbs))
    if len(runs) >= 3 and M_scale > 0:
        add_model("quad_m", "F_b quadratic", "quad",
                  _poly_model(Ms, Fbs, 2, M_bar, M_scale))
    # dF models (deployed): fit dF = F_b - F_a vs M; reconstruct F_b by re-adding actual F_a.
    if regression_df is not None:
        add_model("linear_df", "dF line (deployed)", "line",
                  _line_fit(regression_df["beta"], regression_df["alpha"], Ms, dFs),
                  target="dF")
    if len(runs) >= 3 and M_scale > 0:
        add_model("quad_df", "dF quadratic (deployed, fps_model=quad)", "quad",
                  _poly_model(Ms, dFs, 2, M_bar, M_scale), target="dF")

    # Deployed default = the dF line (year-agnostic; reconstruct F_b = dF + F_a); fall back to the
    # F_b line, then whatever we have.  The chart/expedition consume this via the exported artifact
    # and call model.frame(M, base_delay) to get the actual seed frame.
    recommended = ("linear_df" if "linear_df" in models
                   else "linear_m" if "linear_m" in models
                   else "within_rate" if "within_rate" in models
                   else next(iter(models), None))

    model = {
        "n_runs": len(all_runs), "n_timed": sum(1 for m in all_runs if "rate" in m),
        "n_fit": len(runs), "n_outliers": sum(1 for m in all_runs if m["outlier"]),
        "n_contaminated": sum(1 for m in all_runs if m["contaminated"]),
        "M_bar": M_bar, "Fb_bar": Fb_bar, "M_scale": M_scale, "Sxx": Sxx,
        "rtc_offset_seconds": rtc_offset_seconds,
        "rtc_offset_std": (statistics.pstdev(rtc_offs) if len(rtc_offs) > 1 else 0.0),
        "within": within, "regression": regression,
        "models": models, "recommended": recommended, "runs": all_runs,
    }
    if recommended is not None:
        rec = models[recommended]
        model["predict"] = rec["predict"]
        model["solve"] = rec["solve"]
        model["hit_probability"] = rec["hit_probability"]
        model["calibration_model"] = rec["model"]  # reusable CalibrationModel for the chart
    if verbose:
        print_calibration_report(model)
    return model


def build_calibration_model_set(path=COMPASS_RUNS_PATH):
    """Fit the runs and return BOTH deployable models as {"linear": cm, "quad": cm}.

    linear = the year-agnostic dF line (default, physically-sane slope); quad = the dF quadratic
    (fits 3-10 min slightly tighter in-range, but its slope runs past the ~59.83 Hz ceiling, so
    do not extrapolate).  The chart selects one via the expedition's fps_model; precompute_chart
    covers the UNION of both, so fps_model can be flipped without a re-precompute.  Falls back to
    the recommended model under "linear" if the dF variants aren't available (e.g. too few runs).
    """
    m = calibrate_timer(path=path, verbose=False)
    models = m["models"]
    out = {}
    if "linear_df" in models:
        out["linear"] = models["linear_df"]["model"]
    if "quad_df" in models:
        out["quad"] = models["quad_df"]["model"]
    if not out:
        rec = m.get("recommended")
        if rec:
            out["linear"] = models[rec]["model"]
    return out


def export_calibration_model(runs_path=COMPASS_RUNS_PATH, out_path=DEFAULT_MODEL_PATH):
    """Fit the runs and write the reusable calibration MODELSET artifact to out_path.

    This is the expedition "loop-back": the chart / expedition read the artifact via
    CalibrationModel.load_default(which=fps_model) / load_set(), so re-exporting here after each
    saved run tightens the models they use without any manual batch re-fit.  Writes both the
    linear and quad dF models (default linear).  Returns the {"linear": cm, "quad": cm} dict.
    """
    models = build_calibration_model_set(path=runs_path)
    CalibrationModel.save_set(models, out_path, default="linear")
    return models


def build_calibration_model(path=COMPASS_RUNS_PATH, which=None):
    """Fit the runs non-interactively and return the reusable CalibrationModel for the chart.

    `which` selects a model key from calibrate_timer's `models` (default: the recommended
    one).  This is the entry point chart code should use -- it never prints the interactive
    report and hands back a plain claytonlib.calibration.CalibrationModel that maps a
    commanded countdown M to (mean F_b, sigma(M)).
    """
    m = calibrate_timer(path=path, verbose=False)
    key = which or m.get("recommended")
    if key is None or key not in m["models"]:
        raise ValueError(f"no calibration model available (which={which!r})")
    return m["models"][key]["model"]


def _model_fields(cm):
    """The math parameters of a CalibrationModel that the chart depends on, for comparison."""
    if cm is None:
        return {}
    return {
        "kind": cm.kind, "n_runs": cm.n_runs, "n_fit": cm.n_fit,
        "beta": cm.beta, "alpha": cm.alpha, "coeffs": tuple(cm.coeffs),
        "jitter_c": cm.jitter_c, "jitter_rms": cm.jitter_rms,
        "rtc_offset_seconds": cm.rtc_offset_seconds,
        "rtc_offset_std": cm.rtc_offset_std,
        "m_lo": cm.m_lo, "m_hi": cm.m_hi,
    }


def _fmt_val(v):
    if isinstance(v, float):
        return f"{v:.5g}"
    if isinstance(v, tuple):
        return "(" + ", ".join(f"{x:.5g}" if isinstance(x, float) else str(x) for x in v) + ")"
    return str(v)


def print_model_change(old, new):
    """Print an old -> new parameter table between two CalibrationModels (old may be None)."""
    of, nf = _model_fields(old), _model_fields(new)
    keys = ["kind", "n_runs", "n_fit", "beta", "alpha", "coeffs",
            "jitter_c", "jitter_rms", "rtc_offset_seconds", "rtc_offset_std", "m_lo", "m_hi"]
    if old is None:
        print("No existing model artifact -- this would CREATE one:")
    else:
        print("Proposed calibration-model change (old -> new):")
    for k in keys:
        ov, nv = of.get(k), nf.get(k)
        changed = old is not None and ov != nv
        mark = "  <-- changed" if changed else ""
        if old is None:
            print(f"  {k:<20} {_fmt_val(nv)}")
        else:
            print(f"  {k:<20} {_fmt_val(ov):>14} -> {_fmt_val(nv):<14}{mark}")


def update_calibration_model(runs_path=COMPASS_RUNS_PATH, out_path=DEFAULT_MODEL_PATH,
                             assume_yes=False):
    """Review a re-fit of the calibration MODELSET (linear + quad) and write it ONLY after you confirm.

    Fits fresh linear and quad dF models from the runs, shows how each parameter differs from the
    current artifact (per model), and (unless assume_yes) prompts before overwriting.  This is
    deliberately NOT automatic on save: the chart/expedition read this artifact, so changing it
    invalidates any precomputed chart -- you decide when to take the new models and re-run
    precompute_chart.  Returns the written {"linear": cm, "quad": cm} dict, or None if declined.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    new = build_calibration_model_set(path=runs_path)
    old = CalibrationModel.load_set(out_path) if os.path.exists(out_path) else {}

    print()
    changed = False
    for key in sorted(set(new) | set(old)):
        print(f"[{key}]")
        o, n = old.get(key), new.get(key)
        print_model_change(o, n)
        if o is None or n is None or _model_fields(o) != _model_fields(n):
            changed = True
        print()

    if old and not changed:
        print("No change -- the models are already up to date.")
        return None

    print("*** Applying this invalidates the current precomputed chart -- re-run "
          "precompute_chart afterward (a fast incremental extend; it covers linear+quad). ***")
    if not (assume_yes or _prompt_yes_no("Write these models? (y/n): ")):
        print("Models not updated.")
        return None
    CalibrationModel.save_set(new, out_path, default="linear")
    print(f"Updated calibration modelset ({sorted(new)}) -> {out_path}")
    return new


def _safari_run_point(rec, fresh_only=True):
    """(M, Fa, Fb, run_id, advances) for a safari run, or None if it can't feed the offset fit.

    Needs a confident single identified seed (trusted battle frame), the Section-A a_seed
    (for F_a), and a commanded countdown M.  With `fresh_only`, battle-contaminated runs
    (prior_battles > 0) are skipped, matching the metronome fit's provenance screen.
    `run_id` is `rec.get("_run_id")` (None on the plain JSONL path) -- an opaque passthrough
    so a caller fitting from its own in-memory records (see fit_safari_offset's `runs=`) can
    map each residual back onto its own run ids.

    `advances` is the run's Seed A advance frame (the frame Sweet Scent fired on), or None for
    a run saved before that was recorded.  It is NOT required here -- the flat-offset fit
    doesn't need it and older runs legitimately lack it; only the per-advance fit screens on it.
    """
    if rec.get("seed") is None:                       # ambiguous / unidentified
        return None
    if fresh_only and rec.get("prior_battles", 0) > 0:
        return None
    a = rec.get("a_seed")
    if not a or a.get("delay") is None:               # need F_a
        return None
    Fb = rec.get("frame")
    if Fb is None:
        Fb = rec.get("delay")
    if Fb is None:
        return None
    if rec.get("target_timer_delay") is None:
        return None
    # M = commanded countdown; calibration defaults to 0 (safari runs no longer record it).
    M = rec["target_timer_delay"] + (rec.get("target_timer_calibration") or 0)
    return M, a["delay"], Fb, rec.get("_run_id"), rec.get("advance_frame")


# The per-advance slope is REPORTED WITH ITS UNCERTAINTY rather than withheld until it looks
# good (clayton-6h2.3, revised).  An earlier version refused to adopt a slope below hand-picked
# run-count/spread thresholds; those turned out to be both arbitrary and far too permissive --
# simulated at the old thresholds (12 runs, spread 20, ~50-frame residual scatter) the 95% CI on
# the correction at ~80 advances was still around +/-500 frames, ten times the landing jitter it
# was correcting.  Run count and spread are only proxies: they cannot see the residual scatter,
# which is the third term setting the uncertainty.
#
# The honest quantity is the CI half-width itself, which callers scale by the advance count they
# will actually use to get "+/- N frames of correction uncertainty" -- directly comparable to the
# landing spread.  That subsumes run count, spread AND scatter with no magic constants, and a
# wide interval early is useful feedback (it shrinks visibly as runs accumulate) rather than
# something to hide.  So the only hard refusal left is the one case where no estimate EXISTS:
# fewer than two runs with distinct advance counts, where there is no line to fit.
SAFARI_PER_ADVANCE_MIN_POINTS = 2     # two distinct advance counts define a line; below that, none does
_BOOTSTRAP_MIN_POINTS = 3             # below this a resample is too degenerate to mean anything
_BOOTSTRAP_RESAMPLES = 2000
_BOOTSTRAP_SEED = 20260919           # fixed so a preview doesn't jitter between renders


def _theil_sen(xs, ys):
    """(slope, intercept) by Theil-Sen: median of pairwise slopes, then median of residuals.

    Used instead of least squares because a single misidentified run must not be able to drag
    the fit -- the same reason the flat-offset fit is a median.  Returns (0.0, median(ys)) when
    no two points have distinct x (nothing to estimate a slope from).
    """
    slopes = [(ys[j] - ys[i]) / (xs[j] - xs[i])
              for i in range(len(xs)) for j in range(i + 1, len(xs))
              if xs[j] != xs[i]]
    if not slopes:
        return 0.0, statistics.median(ys)
    slope = statistics.median(slopes)
    return slope, statistics.median([y - slope * x for x, y in zip(xs, ys)])


def _bootstrap_slope_ci(xs, ys, resamples=_BOOTSTRAP_RESAMPLES):
    """A 95% percentile-bootstrap CI for the Theil-Sen slope, as (lo, hi).

    Deliberately reported rather than a bare point estimate: with the small run counts this fit
    realistically runs on, the interval is the number that says whether the slope is worth
    believing.  Seeded, so re-previewing the same runs gives the same interval.
    """
    import random
    if len(xs) < _BOOTSTRAP_MIN_POINTS:
        return ()
    rng = random.Random(_BOOTSTRAP_SEED)
    n = len(xs)
    slopes = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        s, _b = _theil_sen([xs[i] for i in idx], [ys[i] for i in idx])
        slopes.append(s)
    slopes.sort()
    lo = slopes[int(0.025 * (len(slopes) - 1))]
    hi = slopes[int(math.ceil(0.975 * (len(slopes) - 1)))]
    return (lo, hi)


def fit_safari_offset(model, runs_path=SAFARI_RUNS_PATH, fresh_only=True, runs=None,
                      per_advance=False, jitter=False):
    """Fit the safari load-path offset Δα for `model`, holding its slope/shape fixed.

    Δα = median over usable safari runs of (actual battle frame − model.frame(M, F_a)): how
    many frames the extra Safari-Zone loading screen lands off this (metronome-fit) model
    (abf.10).  Median so one mis-identified run can't drag it.  Returns
    ``{"offset", "n", "std", "residuals", "residuals_by_run", "per_advance", "per_advance_n",
    "per_advance_ci", "quality", "jitter_c"}`` or None if there are no usable runs.
    ``residuals_by_run`` maps ``_run_id -> residual`` for every input record that had one
    (empty when reading plain JSONL, which carries no ids).

    ``per_advance=True`` additionally fits ``safari_offset_per_advance`` -- frames per Seed A
    advance -- jointly with the intercept by Theil-Sen, over the subset of runs that recorded an
    advance count.  Fitting BOTH on that subset (rather than taking the intercept from every run
    and the slope from the subset) matters: split across different sets, the two parameters
    mis-attribute the offset between them.  Runs without an advance count are reported in
    ``gate["n_missing_advances"]`` and otherwise ignored by this branch.

    A slope is fit from whatever is there and reported WITH its uncertainty, rather than
    withheld until it looks convincing -- a rough early estimate is useful, and watching its
    interval shrink is how you see the data accumulating.  ``quality`` carries what a caller
    needs to say how much to trust it: ``ci_halfwidth`` (frames per advance -- scale it by the
    advance count you will actually run at to get the correction's uncertainty in frames) and
    ``sigma_ref`` (the landing spread those same runs were fit against, so the two are directly
    comparable).  The ONE hard refusal is the case where no estimate exists at all: fewer than
    two DISTINCT advance counts, where slope and offset are the same parameter -- then
    ``estimable`` is False, ``per_advance`` is 0.0, and the flat median offset stands.
    ``ci_halfwidth`` is None below _BOOTSTRAP_MIN_POINTS runs (a slope, but no way to say how
    uncertain); ``reason`` explains either case.

    ``jitter=True`` additionally estimates ``jitter_c`` for the safari path from the spread of
    these residuals about the fit (``std / sqrt(mean M)``, keeping the model's sqrt(M) form)
    rather than inheriting the metronome fit's.

    `runs`, if given, is used INSTEAD of reading `runs_path` -- an in-memory list of run
    records already curated by a caller's own exclusion pass, exactly like calibrate_timer's
    `runs=` parameter.
    """
    raw = runs if runs is not None else load_safari_runs(runs_path)
    pts = [p for p in (_safari_run_point(r, fresh_only) for r in raw) if p]
    if not pts:
        return None
    resid = [Fb - model.frame(M, Fa) for (M, Fa, Fb, _rid, _adv) in pts]  # metronome-path prediction
    by_run = {rid: r for (_M, _Fa, _Fb, rid, _adv), r in zip(pts, resid) if rid is not None}

    offset = statistics.median(resid)
    slope = 0.0
    ci: tuple = ()
    quality = None
    fit_resid = resid          # residuals about whatever fit was actually adopted
    fit_Ms = [M for (M, _Fa, _Fb, _rid, _adv) in pts]

    if per_advance:
        with_adv = [(p, r) for p, r in zip(pts, resid) if p[4] is not None]
        xs = [float(p[4]) for p, _r in with_adv]
        ys = [r for _p, r in with_adv]
        spread = (max(xs) - min(xs)) if xs else 0.0
        quality = {"n_with_advances": len(xs), "n_missing_advances": len(pts) - len(xs),
                   "spread": spread, "estimable": False, "reason": None,
                   "ci_halfwidth": None, "sigma_ref": None}
        if len(set(xs)) < SAFARI_PER_ADVANCE_MIN_POINTS:
            # The ONLY hard refusal: with every run at the same advance count (or none at all)
            # the slope and the offset are the same parameter -- there is no estimate to make,
            # rough or otherwise. Falls back to the flat median offset over all runs.
            quality["reason"] = (
                "needs at least two runs with DIFFERENT advance counts — "
                f"{len(xs)} run(s) recorded one, at {len(set(xs))} distinct value(s)"
                if xs else "no run has recorded an advance count yet")
        else:
            slope, offset = _theil_sen(xs, ys)
            ci = _bootstrap_slope_ci(xs, ys)
            quality["estimable"] = True
            if ci:
                quality["ci_halfwidth"] = (ci[1] - ci[0]) / 2.0
            else:
                quality["reason"] = (
                    f"fit from only {len(xs)} run(s) — too few to estimate how uncertain "
                    f"the slope is, so treat it as a first guess")
            fit_resid = [y - (offset + slope * x) for x, y in zip(xs, ys)]
            fit_Ms = [p[0] for p, _r in with_adv]
            # The landing spread these same runs were fit against, so a caller can say how the
            # correction's uncertainty compares to the noise it is correcting. Reported here
            # (where M is known) rather than computed by callers, but deliberately NOT scaled by
            # any advance count -- the lever arm is an expedition concept the library never sees.
            if fit_Ms:
                quality["sigma_ref"] = model.jitter_sigma(statistics.mean(fit_Ms))

    jitter_c = None
    if jitter and len(fit_resid) > 1:
        m_bar = statistics.mean(fit_Ms)
        if m_bar > 0:
            jitter_c = statistics.pstdev(fit_resid) / math.sqrt(m_bar)

    return {"offset": offset, "n": len(resid),
            "std": statistics.pstdev(resid) if len(resid) > 1 else 0.0,
            "residuals": resid, "residuals_by_run": by_run,
            "per_advance": slope,
            "per_advance_n": quality["n_with_advances"] if quality else 0,
            "per_advance_ci": ci, "quality": quality, "jitter_c": jitter_c}


def update_safari_offset(model_path=DEFAULT_MODEL_PATH, runs_path=SAFARI_RUNS_PATH,
                         fresh_only=True, assume_yes=False):
    """Section E (safari): fit and write the safari offset into the deployed modelset on confirm.

    Holds each model's metronome alpha/beta and sets only ``safari_offset`` (+ n/std), so the
    pure metronome fit is untouched.  The expedition folds this offset into the frame center for
    ALL safari scoring (``use_safari_offset``, default True), so after changing it you must RE-RUN
    ``precompute_chart()`` -- the canon is keyed by frame and the offset shifts which frames the
    scorers ask for (a fast incremental extend, not a full rebuild) -- then ``chart_report()``.
    Returns the updated {key: CalibrationModel}, or None.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    models = CalibrationModel.load_set(model_path)
    if not models:
        print(f"No deployed model at {model_path}; run the metronome Section E first.")
        return None
    fits = {k: fit_safari_offset(m, runs_path, fresh_only) for k, m in models.items()}
    if not any(fits.values()):
        print(f"No usable safari runs in {runs_path} "
              f"(need a_seed + a confident single seed).")
        return None

    print()
    for k in sorted(models):
        old, fit = models[k].safari_offset, fits[k]
        old_s = f"{old:+.2f}" if old is not None else "None"
        if fit is None:
            print(f"[{k}] no usable runs -> unchanged (safari_offset={old_s})")
        else:
            print(f"[{k}] safari_offset {old_s} -> {fit['offset']:+.2f} frames  "
                  f"(n={fit['n']}, std={fit['std']:.2f})")
    print("\n*** This shifts the safari load-path frame center. The expedition applies it to ALL "
          "safari scoring (use_safari_offset, default True), so RE-RUN precompute_chart() to "
          "extend the canon to the shifted frames, then chart_report(). (Set "
          "expedition.use_safari_offset=False to score against the raw metronome fit instead.) ***")
    if not (assume_yes or _prompt_yes_no("Write the safari offset? (y/n): ")):
        print("Safari offset not updated.")
        return None

    for k, m in models.items():
        fit = fits[k]
        if fit is not None:
            m.safari_offset = fit["offset"]
            m.safari_offset_n = fit["n"]
            m.safari_offset_std = fit["std"]
    CalibrationModel.save_set(models, model_path, default="linear")
    print(f"Wrote safari offset into {sorted(models)} -> {model_path}")
    return models


def print_calibration_report(model):
    hdr = f"=== Timer calibration  ({model['n_runs']} run(s), {model['n_timed']} timed"
    if model.get("n_outliers"):
        hdr += f", {model['n_outliers']} excluded as outlier"
    if model.get("n_contaminated"):
        hdr += f", {model['n_contaminated']} excluded (battle-contaminated)"
    print(hdr + ") ===\n")
    print(f"  F_b as a function of M = delay + calibration (ms)\n")

    if model["within"]:
        w = model["within"]
        print(f"  within-run avg rate {w['rate']:.4f} +/- {w['rate_sigma']:.4f} Hz "
              f"(dF/dt; rises with M as the slow post-boot frames dilute out)\n")

    # Model comparison block: label, slope/rate, jitter RMS, marked recommended.
    _kept = [m for m in model["runs"] if not m.get("outlier") and not m.get("contaminated")]
    Mlo = min(m["M"] for m in _kept)
    Mhi = max(m["M"] for m in _kept)
    for key, sub in model["models"].items():
        star = " *" if key == model.get("recommended") else "  "
        rms = sub["jitter_rms"]
        rms_s = f"{rms:.1f}" if rms is not None else "n/a"
        rate_lo = sub["dfdM"](Mlo) * 1000.0 if sub["dfdM"] else float("nan")
        rate_hi = sub["dfdM"](Mhi) * 1000.0 if sub["dfdM"] else float("nan")
        if sub["kind"] == "quad":
            rate_desc = f"inst rate {rate_lo:.3f}->{rate_hi:.3f} Hz over M range"
        else:
            rate_desc = f"slope {rate_lo:.4f} Hz"
        tgt = f"[{sub.get('target', 'Fb')}]"
        print(f" {star}{sub['label']:<40} {tgt:<5}{rate_desc:<32} RMS residual {rms_s:>6} frames")
    if model.get("recommended"):
        print(f"\n  ( * = deployed default; predict/solve/hit_probability use it. "
              f"[dF] models reconstruct F_b = dF + F_a )")

    print(f"\n  RTC-second offset {model.get('rtc_offset_seconds', 0.0):.2f} +/- "
          f"{model.get('rtc_offset_std', 0.0):.2f} s  "
          f"(battle RTC second = round(M/1000 + this); +/-1 s is timestamp truncation)")

    print(f"\n  {'tag':<16} {'M':>8} {'Fa':>7} {'Fb':>7} {'dF':>7} {'dt':>5} {'rate':>8}")
    for m in model["runs"]:
        rate = f"{m['rate']:.3f}" if "rate" in m else "   --"
        if m.get("contaminated"):
            flag = f"   <- contaminated ({m.get('prior_battles', 0)} prior battles), excluded"
        elif m.get("outlier"):
            flag = f"   <- outlier ({m['outlier_reason']}), excluded"
        else:
            flag = ""
        print(f"  {(m['tag'] or ''):<16} {m['M']:>8} {m['Fa']:>7} {m['Fb']:>7} "
              f"{m['dF']:>7} {m['dt']:>5.0f} {rate:>8}{flag}")
