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
import os

from claytonlib.safari import advance_rng

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


def roamer_positions(seed, prev_routes, present):
    """Walk the roamer relocation rolls from `seed`.

    prev_routes: dict like {"r": 31, "e": 30, "l": 0} of each roamer's CURRENT route
                 (0 / anything not on its route table forces the first roll to stick).
    present:     dict like {"r": True, "e": True, "l": False} of which roamers still roam.

    Returns (routes, rng_calls, state) where routes maps r/e/l -> new route (or None if
    that roamer isn't roaming) and state is the LCRNG state after the roamer rolls, ready
    for the Elm calls.
    """
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
    present: dict,
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
            routes, calls, state = roamer_positions(seed, prev_routes, present)
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
def filter_rel(candidates, present, observed):
    """Keep candidates matching an observed roamer readout string.

    observed: one route per roaming legendary in R E L order, space-separated
              (e.g. "38 42 11"); a wildcard token (. - * ?) leaves one free.
    Returns (matched, keys, tokens).
    """
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
def filter_by_observed_rel(candidates, present, observed=None, limit=20):
    """Prompt for (or take) an observed roamer readout and print the matches."""
    keys = [k for k in _ROAMER_ORDER if present.get(k)]
    if observed is None:
        labels = " ".join(k.upper() for k in keys)
        observed = input(f"Observed roamer routes ({labels}, space-separated, . = any): ")
    matched, keys, tokens = filter_rel(candidates, present, observed)
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
    a candidate manually.  Returns the single surviving candidate dict (or None).
    """
    elm_so_far = ""
    remaining = list(candidates)
    while len(remaining) > 1:
        raw = input("Elm calls (type P/E/K as heard; M = pick manually): ")
        add, manual = parse_elm_input(raw)
        elm_so_far += add
        if manual:
            return manual_select(filter_elm(candidates, elm_so_far))
        print(f"Elm calls so far: {elm_so_far}")
        remaining = filter_elm(candidates, elm_so_far)
        print_roamer_candidates(remaining, limit=limit)
    if len(remaining) == 1:
        return remaining[0]
    print("\nNo candidates match those Elm calls -- check your input.")
    return None


def identify_seed(candidates, present, observed_rel=None, display_limit=20):
    """Interactively pin down the seed you actually hit.

    1. Filter by the observed roamer routes (R E L).
    2. If more than one remains, narrow by the Elm call sequence (or M to pick).
    3. Print the single result and return the whole candidate row (dict), for use
       as `a_seed` -- its integer seed is `a_seed["seed"]`.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    matched = filter_by_observed_rel(candidates, present,
                                     observed=observed_rel, limit=display_limit)
    if not matched:
        print("\nNo candidates match -- check the observed routes or widen the window.")
        return None
    result = matched[0] if len(matched) == 1 else narrow_by_elm(matched, limit=display_limit)
    if result is None:
        return None
    print("\n=== Seed identified ===")
    print_roamer_candidates([result], limit=1)
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
                             metronome_only=False, n_turns=10):
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
                                   moveset=moveset, n_turns=n_turns)
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


def narrow_candidates(candidates, magikarp_level, opposite_gender, metronome_only=False):
    """Interactively narrow `candidates` to a single seed.

    Reuses the metronome_compass battle driver: an InteractiveContext walks the real
    battle turn by turn, asking what actually happened ("Magikarp used? (sp/tk)",
    "Metronome selected? (move name or M###)", "Hit, crit, or miss?", status prompts,
    ...).  After each turn, candidates whose precomputed path diverges from what you
    observed are dropped.  Returns the identified candidate dict (whole row) or None.
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
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
        print(f"\n{len(remaining)} / {len(candidates)} seeds remain -- next is turn {turn_n}")
        print(f"  {'Seed':>10}  {'Delay':>6}  {'dD':>4}  predicted turn {turn_n}")
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
            print(f"  0x{c['seed']:08X}  {c['delay']:>6}  {c['delay_delta']:>+4}  "
                  f"{turn_str:<18} ({move_name})")
        if len(remaining) > 15:
            print(f"  ... and {len(remaining) - 15} more")

    remaining = list(candidates)
    turn_n = 0
    while True:
        show(remaining, turn_n + 1)
        if len(remaining) == 1:
            c = remaining[0]
            print(f"\nSeed identified: 0x{c['seed']:08X}  "
                  f"time={c['time'].strftime('%Y-%m-%d %H:%M:%S')}  delay={c['delay']}  "
                  f"dD={c['delay_delta']:+d}")
            print(f"Full path: {c['path_str']}")
            # Metronome moves remaining in the identified seed's path (turns not yet observed).
            print(f"Remaining Metronome moves (turn {turn_n + 1}+):")
            for turn_idx in range(turn_n, len(c["path"])):
                for tok in c["path"][turn_idx]:
                    if isinstance(tok, MetronomeMove):
                        print(f"  Turn {turn_idx + 1}: {moves_by_num[tok.move_num].name} (M{tok.move_num:03d})")
            return c
        if not remaining:
            print("\nNo seeds match -- check your answers or widen the window above.")
            return None

        turn_n += 1
        print(f"\n--- Turn {turn_n}: answer what happened in the battle ---")
        simulate_turn(ctx, state, moves_by_num, known, magikarp_level)
        observed = ctx.path[turn_n - 1]
        remaining = [c for c in remaining
                     if len(c["path"]) >= turn_n and c["path"][turn_n - 1] == observed]


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
