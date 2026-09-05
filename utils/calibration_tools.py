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
        out["time"] = row["time"].isoformat()
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


def _prompt_yes_no(prompt):
    """Loop until the user answers yes/no/y/n (case-insensitive); returns a bool."""
    while True:
        raw = input(prompt).strip().lower()
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  please answer y/n.")


def save_compass_run(a_seed, b_seed, path=COMPASS_RUNS_PATH):
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
    """
    install_input_fixup()  # ipykernel resets builtins.input per cell; re-apply here
    prev = _last_run(path)

    tag = _prompt_default("Run tag", prev.get("tag"))
    target_timer_delay = _prompt_default(
        "Target timer delay", prev.get("target_timer_delay"), int)
    target_timer_calibration = _prompt_default(
        "Target timer calibration", prev.get("target_timer_calibration"), int)
    notes = input("Notes: ").strip()

    record = {
        "saved_at": dt.datetime.now().isoformat(timespec="seconds"),
        "tag": tag,
        "target_timer_delay": target_timer_delay,
        "target_timer_calibration": target_timer_calibration,
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
    m = {"tag": rec.get("tag"), "M": M, "Fa": Fa, "Fb": Fb, "dF": Fb - Fa, "dt": dt_s}
    if dt_s > 0:
        m["rate"] = m["dF"] / dt_s
        m["rate_lo"] = m["dF"] / (dt_s + 1)                       # time really longer
        m["rate_hi"] = m["dF"] / (dt_s - 1) if dt_s > 1 else float("inf")  # really shorter
    return m


def _norm_cdf(z):
    """Standard-normal CDF via math.erf (stdlib; avoids a scipy dependency)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


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


def calibrate_timer(path=COMPASS_RUNS_PATH, verbose=True):
    """Fit F_b = beta*M + alpha from the collected runs and return a calibration model.

    The returned dict carries the fitted params plus two closures:
      * predict(delay, calibration, k=2.0) -> {expected, lo, hi, jitter, rate_band}
          min/expected/max seed_b frame for a commanded (delay, calibration).  `lo`/`hi`
          fold together the reducible calibration/rate uncertainty (grows linearly with M,
          driven by the +/-1 s rate interval) and the irreducible physical jitter
          (grows ~sqrt(M)); k is how many jitter sigmas to include.
      * solve(target_fb, delay=None, calibration=None) -> {M, delay, calibration}
          the commanded countdown (and the missing one of delay/calibration) to land on
          target_fb.

    Degrades gracefully: 1 usable run still yields a rate + intercept (no jitter/regression
    until there are residuals to measure).
    """
    runs = [m for m in (_run_metrics(r) for r in load_compass_runs(path)) if m]
    timed = [m for m in runs if "rate" in m]
    if not runs:
        raise ValueError(f"no usable runs in {path} (need both a_seed and b_seed identified)")

    Ms = [m["M"] for m in runs]
    Fbs = [m["Fb"] for m in runs]
    M_bar = statistics.mean(Ms)
    Fb_bar = statistics.mean(Fbs)

    # --- slope (beta) --------------------------------------------------------
    # Primary: pooled within-run rate = total frames / total seconds (its +/-1 s error
    # averages down across runs).  Its band uses the realistic ~0.41 s per-run sigma.
    within = None
    if timed:
        tot_dF = sum(m["dF"] for m in timed)
        tot_dt = sum(m["dt"] for m in timed)
        rate = tot_dF / tot_dt
        rate_sigma = rate * (_TIMING_SIGMA * math.sqrt(len(timed))) / tot_dt
        within = {"rate": rate, "rate_sigma": rate_sigma,
                  "rate_lo": rate - rate_sigma, "rate_hi": rate + rate_sigma,
                  "n": len(timed)}

    # Cross-check / alternative: regress F_b on M (needs M to vary).
    regression = None
    ts = _theil_sen(Ms, Fbs)
    if ts is not None:
        regression = {"beta": ts[0], "alpha": ts[1], "rate": ts[0] * 1000.0}

    if within is not None:
        beta = within["rate"] / 1000.0
        beta_lo = within["rate_lo"] / 1000.0
        beta_hi = within["rate_hi"] / 1000.0
        slope_source = "within-run rate"
    elif regression is not None:
        beta = regression["beta"]
        beta_lo = beta_hi = beta            # no separate band without timed runs
        slope_source = "F_b-vs-M regression"
    else:
        beta = _NOMINAL_RATE / 1000.0       # last resort: nominal DS rate
        beta_lo = beta_hi = beta
        slope_source = f"nominal {_NOMINAL_RATE} Hz (no rate data)"

    # --- intercept (alpha) ---------------------------------------------------
    # Pivot the line about the data centroid so beta-uncertainty rotates about the runs
    # you actually measured (not about M=0): F_b = Fb_bar + beta*(M - M_bar).
    alpha = Fb_bar - beta * M_bar

    # --- jitter (irreducible spread of F_b about the line, vs M) --------------
    # Residuals here don't involve the timestamps, so the +/-1 s never enters them; they
    # are physical jitter + human reaction + model misfit -- the real spread you'll face.
    resid = [(m["M"], m["Fb"] - (Fb_bar + beta * (m["M"] - M_bar))) for m in runs]
    jitter_c = None          # diffusive: sigma(M) = c*sqrt(M)   (random-walk jitter)
    jitter_rms = None
    if len(runs) >= 2:
        jitter_rms = math.sqrt(statistics.mean(e * e for _, e in resid))
        pos = [(e * e) / M for M, e in resid if M > 0]
        if pos:
            jitter_c = math.sqrt(statistics.mean(pos))

    def jitter_sigma(M):
        if jitter_c is not None and M > 0:
            return jitter_c * math.sqrt(M)
        return jitter_rms or 0.0

    model = {
        "n_runs": len(runs), "n_timed": len(timed),
        "beta": beta, "beta_lo": beta_lo, "beta_hi": beta_hi,
        "rate": beta * 1000.0, "slope_source": slope_source,
        "alpha": alpha, "M_bar": M_bar, "Fb_bar": Fb_bar,
        "within": within, "regression": regression,
        "jitter_c": jitter_c, "jitter_rms": jitter_rms,
        "runs": runs,
    }

    def predict(delay, calibration, k=2.0):
        M = delay + calibration
        expected = Fb_bar + beta * (M - M_bar)
        # Reducible: rate/calibration uncertainty, pivoting about the centroid.
        rate_band = abs(M - M_bar) * (beta_hi - beta_lo) / 2.0
        j = jitter_sigma(M)
        half = rate_band + k * j
        return {"expected": expected, "lo": expected - half, "hi": expected + half,
                "jitter": j, "rate_band": rate_band, "M": M}

    def solve(target_fb, delay=None, calibration=None):
        M = M_bar + (target_fb - Fb_bar) / beta
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
        """Probability that commanding (delay, calibration) lands within `tolerance`
        frames of target_fb (M = delay + calibration).

        F_b is treated as Normal(expected, sigma):
          * expected = the predicted frame at M.
          * sigma combines the irreducible physical jitter with -- unless
            perfect_calibration=True -- the reducible uncertainty in the predicted mean
            (rate + intercept error).  perfect_calibration=True gives the best case you'd
            approach with unlimited calibration data.
        tolerance is the half-window in frames: a hit is |F_b - target_fb| <= tolerance
        (default 0.5 = exactly the integer frame target_fb).  Returns p plus the pieces.
        """
        M = delay + calibration
        expected = Fb_bar + beta * (M - M_bar)
        sj = jitter_sigma(M)
        # Uncertainty in the predicted MEAN (reducible): slope error grows as you
        # extrapolate from the centroid; centroid height error shrinks as 1/sqrt(n).
        sigma_beta = (beta_hi - beta_lo) / 2.0
        sc_slope = abs(M - M_bar) * sigma_beta
        sc_center = (jitter_rms / math.sqrt(len(runs))) if jitter_rms else 0.0
        sc = math.hypot(sc_slope, sc_center)
        sigma = sj if perfect_calibration else math.hypot(sj, sc)
        if sigma <= 0:
            p = 1.0 if abs(target_fb - expected) <= tolerance else 0.0
        else:
            p = (_norm_cdf((target_fb + tolerance - expected) / sigma)
                 - _norm_cdf((target_fb - tolerance - expected) / sigma))
        return {"p": p, "expected": expected, "delta": target_fb - expected,
                "sigma_jitter": sj, "sigma_calib": sc, "sigma_total": sigma,
                "tolerance": tolerance, "M": M}

    model["predict"] = predict
    model["solve"] = solve
    model["hit_probability"] = hit_probability
    if verbose:
        print_calibration_report(model)
    return model


def print_calibration_report(model):
    print(f"=== Timer calibration  ({model['n_runs']} run(s), "
          f"{model['n_timed']} timed) ===\n")
    print(f"  F_b = beta*M + alpha,   M = delay + calibration (ms)")
    print(f"  slope  beta  = {model['beta']:.6f} frames/ms "
          f"(= {model['rate']:.4f} Hz)   [{model['slope_source']}]")
    if model["within"]:
        w = model["within"]
        print(f"         within-run rate {w['rate']:.4f} +/- {w['rate_sigma']:.4f} Hz "
              f"(1σ, from {w['n']} run(s))")
    if model["regression"]:
        r = model["regression"]
        print(f"         F_b-vs-M slope  {r['rate']:.4f} Hz  (Theil-Sen cross-check)")
    alpha_ms = model["alpha"] / model["beta"] if model["beta"] else float("nan")
    print(f"  intercept alpha = {model['alpha']:+.1f} frames "
          f"({alpha_ms:+.0f} ms)   (the ~5 s battle delay + load y-intercept, combined)")
    if model["jitter_c"] is not None:
        print(f"  jitter  ~ {model['jitter_c']:.3f}*sqrt(M) frames "
              f"(RMS residual {model['jitter_rms']:.1f})")
    elif model["jitter_rms"] is not None:
        print(f"  jitter  RMS residual {model['jitter_rms']:.1f} frames")
    else:
        print(f"  jitter  -- need >= 2 runs to estimate")
    print(f"\n  {'tag':<16} {'M':>8} {'Fa':>7} {'Fb':>7} {'dF':>7} {'dt':>5} {'rate':>8}")
    for m in model["runs"]:
        rate = f"{m['rate']:.3f}" if "rate" in m else "   --"
        print(f"  {(m['tag'] or ''):<16} {m['M']:>8} {m['Fa']:>7} {m['Fb']:>7} "
              f"{m['dF']:>7} {m['dt']:>5.0f} {rate:>8}")
