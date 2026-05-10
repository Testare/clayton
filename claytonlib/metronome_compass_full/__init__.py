"""metronome_compass_full — Multi-turn seed identification via Metronome battle observation.

Phase 1: Filters candidates by the Metronome move selected each turn.
         Post-move RNG tracking (hit/crit/miss, Magikarp turn) is infrastructure-ready
         but not yet used for filtering (pending GDB verification in Phase 2).
"""
from __future__ import annotations
import datetime as dt
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from claytonlib.safari import advance_rng
from claytonlib.times import get_times, calculate_seed
from claytonlib.compass_premetronome import MetronomeOpponent

from .path import (
    Path as BattlePath, Turn, render_path,
    PathToken, MetronomeMove, MagikarpMove, MultiHit,
    Hit, Miss, Crit, EffectProc,
    PAR, FRZ, CFZ, SCFZ, SLP, FLN, LV, Struggle, PathEnd, Unsupported,
)
from .context import BattleContext, RngContext, InteractiveContext
from .effects import Move, move_effect, EFFECT_HANDLERS, simulate_metronome_roll, _METRONOME_POOL


# ---------------------------------------------------------------------------
# Move data loading
# ---------------------------------------------------------------------------

_moves_cache: list[Move] | None = None


def _load_moves() -> list[Move]:
    global _moves_cache
    if _moves_cache is None:
        path = Path(__file__).parent.parent / "basedata" / "moves.json"
        with open(path) as f:
            data = json.load(f)
        _moves_cache = [
            Move(
                number=m["number"],
                name=m["name"],
                metronome_usable=m["metronome_usable"],
                effect=m["effect"],
                effect_chance=m["effect_chance"],
                accuracy=m["accuracy"],
            )
            for m in data
        ]
    return _moves_cache


def _moves_by_number() -> dict[int, Move]:
    return {m.number: m for m in _load_moves()}


# ---------------------------------------------------------------------------
# Magikarp gender
# ---------------------------------------------------------------------------

class MagikarpGender(Enum):
    MALE   = "male"
    FEMALE = "female"


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class CompassMetronomeFullInput:
    opponent:       MetronomeOpponent
    key_seed:       int
    target_delay:   int
    initial_time:   dt.datetime
    window:         int
    magikarp_level: int              # determines move pool (< 15: Splash only)
    known_moves:    tuple[int, ...] = field(default_factory=tuple)  # move numbers already known
    second_window:  int = 0


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _generate_candidates(inputs: CompassMetronomeFullInput) -> list[tuple[int, int]]:
    """Return sorted (seed, delay) pairs for the search window."""
    from claytonlib.compass import _delay_offset_to_second_frame
    base_delay, _ = get_times(inputs.key_seed)
    seen: set[int] = set()
    results: list[tuple[int, int]] = []

    for d in range(inputs.target_delay - inputs.window,
                   inputs.target_delay + inputs.window + 1):
        offset = d - base_delay
        if offset < 0:
            continue
        second_idx, _ = _delay_offset_to_second_frame(offset)
        for s in range(second_idx - inputs.second_window,
                       second_idx + inputs.second_window + 2):
            if s < 0:
                continue
            seed = calculate_seed(inputs.initial_time + dt.timedelta(seconds=s), d)
            if seed not in seen:
                seen.add(seed)
                results.append((seed, d))

    results.sort(key=lambda x: (x[1], x[0]))
    return results


# ---------------------------------------------------------------------------
# Path pre-computation
# ---------------------------------------------------------------------------

_BATTLE_START_ADVANCES = 7   # 4 bellShimmer + 2 ability + 1 flee
_BEFORE_TURN_ADVANCES  = 4   # quick claw checks

# End-of-turn advance counts (all approximate — needs GDB verification for Phase 2)
_EOT_SCRIPT_RAND    = 1
_EOT_ABILITY_SPLASH = 3   # "x4 (x3 if Splash)"
_EOT_ABILITY_TACKLE = 4
_EOT_ABILITY_BLOCK2 = 6
_EOT_FLEE_CHECK     = 1


def _simulate_turn_rng(
    ctx: RngContext,
    moves_by_num: dict[int, Move],
    known_moves: frozenset[int],
    magikarp_level: int,
) -> 'Turn':
    """Simulate one full battle turn and return its token tuple.

    Advances RNG through: before-turn checks, metronome roll, move execution,
    Magikarp's turn, and end-of-turn processing. Calls ctx.end_turn().

    NOTE: Move execution and Magikarp tackle use placeholder advance counts
    (Phase 1). Phase 2 replaces these with GDB-verified effect scripts.
    """
    from .effects import simulate_move_execution

    ctx.advance_unobservable(_BEFORE_TURN_ADVANCES)

    move = simulate_metronome_roll(ctx, moves_by_num, known_moves)
    simulate_move_execution(ctx, move)  # Phase 1: placeholder advances only

    if ctx.battle_state.get('unsupported'):
        return ctx.end_turn()  # path ends here; caller stops the loop

    mk_move = ctx.magikarp_move_select(magikarp_level)

    # Magikarp tackle execution (approximate — Phase 2 will verify)
    if mk_move.move == 'tk':
        ctx.advance_unobservable(3)  # accuracy + crit + damage TODO: verify

    # End of turn (approximate — Phase 2 will verify)
    splashed = (mk_move.move == 'sp')
    ctx.advance_unobservable(_EOT_SCRIPT_RAND)
    ctx.advance_unobservable(_EOT_ABILITY_SPLASH if splashed else _EOT_ABILITY_TACKLE)
    ctx.advance_unobservable(_EOT_ABILITY_BLOCK2)
    ctx.advance_unobservable(_EOT_FLEE_CHECK)

    return ctx.end_turn()


def _precompute_first_move(
    seed: int,
    moves_by_num: dict[int, Move],
    known_moves: frozenset[int],
) -> int | None:
    """Return the move number Metronome would select on turn 1 for this seed.

    Returns None if something went wrong (should not happen in practice).
    """
    ctx = RngContext(seed)
    ctx.advance_unobservable(_BATTLE_START_ADVANCES)
    ctx.advance_unobservable(_BEFORE_TURN_ADVANCES)
    move = simulate_metronome_roll(ctx, moves_by_num, known_moves)
    return move.number


def _precompute_all(
    candidates: list[tuple[int, int]],
    inputs: CompassMetronomeFullInput,
    moves_by_num: dict[int, Move],
) -> dict[int, int]:
    """Return {seed: move_number} for all candidates."""
    known = frozenset(inputs.known_moves)
    return {seed: _precompute_first_move(seed, moves_by_num, known)
            for seed, _ in candidates}


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _delta_str(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def _print_candidates(
    candidates: list[tuple[int, int]],
    seed_to_move: dict[int, int],
    moves_by_num: dict[int, Move],
    target_delay: int,
    total: int,
) -> None:
    print(f"Seeds: {len(candidates)} / {total} remaining")
    by_proximity = sorted(candidates, key=lambda x: (abs(x[1] - target_delay), x[0]))
    display = by_proximity[:10]
    print(f"  {'#':>2}  {'Seed':>10}  {'Delay':>7}  {'Δ':>5}  Path")
    for i, (seed, delay) in enumerate(display, 1):
        delta = delay - target_delay
        marker = " ← target" if delta == 0 else ""
        move_num = seed_to_move.get(seed)
        move_name = moves_by_num[move_num].name if move_num else "?"
        path_str = f"M{move_num:03d}"
        print(f"  {i:>2}. 0x{seed:08X}  {delay:>7}  {_delta_str(delta):>5}  "
              f"{path_str}  ({move_name}){marker}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")


# ---------------------------------------------------------------------------
# Public path pre-computation
# ---------------------------------------------------------------------------

def precompute_path(
    seed: int,
    magikarp_level: int,
    opposite_gender: bool,
    known_moves: tuple[int, ...] = (),
    n_turns: int = 10,
) -> BattlePath:
    """Pre-compute the battle path for a single seed.

    Returns a Path (tuple of turns) representing the observable RNG events for
    this seed over n_turns turns. Each turn contains a MetronomeMove token and
    a MagikarpMove token (Ksp or Ktk depending on magikarp_level and the roll).

    opposite_gender: True if Magikarp is the opposite gender to the Metronome
    user (i.e. Attract can land). Stored in battle_state for effect scripts to
    read when Attract is selected (Phase 2/3). Derive this from the Metronome
    user's gender (expedition config) and Magikarp's gender (prompted per run).

    Phase 1: post-move and end-of-turn RNG uses placeholder advance counts
    (GDB-verified counts pending for Phase 2).
    """
    moves_by_num = _moves_by_number()
    known = frozenset(known_moves)
    ctx = RngContext(seed)
    ctx.battle_state['opposite_gender'] = opposite_gender
    ctx.advance_unobservable(_BATTLE_START_ADVANCES)
    for _ in range(n_turns):
        _simulate_turn_rng(ctx, moves_by_num, known, magikarp_level)
        if ctx.battle_state.get('unsupported'):
            break
    return ctx.path


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

def _resolve_move_input(raw: str, moves_by_num: dict[int, Move]) -> Move | None:
    """Parse user input as a move name or M### notation. Returns None if unresolved."""
    s = raw.strip()
    if s.upper().startswith('M') and s[1:].isdigit():
        num = int(s[1:])
        return moves_by_num.get(num)
    key = s.lower().replace('-', ' ').replace('_', ' ')
    for move in moves_by_num.values():
        if move.name.lower() == key:
            return move
    # Substring suggestions
    return None


def _suggest_moves(raw: str, moves_by_num: dict[int, Move], n: int = 3) -> list[Move]:
    key = raw.strip().lower().replace('-', ' ').replace('_', ' ')
    return [m for m in moves_by_num.values() if key in m.name.lower()][:n]


def metronome_compass_full(inputs: CompassMetronomeFullInput) -> None:
    """Interactive multi-turn seed identification via Metronome move observation.

    Phase 1: filters by Metronome move selection only. Each observation narrows
    the candidate set. 'Go again' re-runs a fresh session on the same window
    (useful for calibration across multiple battle attempts).
    """
    moves_by_num = _moves_by_number()
    initial_candidates = _generate_candidates(inputs)
    total = len(initial_candidates)
    moveset = "Splash only" if inputs.magikarp_level < 15 else "Splash + Tackle"

    print("=== Metronome Compass (Full) — Phase 1 ===")
    print(f"Opponent:       {inputs.opponent.value.capitalize()}")
    print(f"Magikarp level: {inputs.magikarp_level} ({moveset})")
    sw = f"  second_window=±{inputs.second_window}" if inputs.second_window else ""
    print(f"Window:         ±{inputs.window} delays{sw}  ({total} initial candidates)")
    if inputs.known_moves:
        names = ', '.join(moves_by_num[n].name for n in inputs.known_moves
                          if n in moves_by_num)
        print(f"Known moves:    {names}")
    print()

    while True:
        # Fresh session: reset candidates and pre-compute
        candidates = list(initial_candidates)
        seed_to_move = _precompute_all(candidates, inputs, moves_by_num)
        turn = 1

        print(f"--- Session ---")

        while True:
            print()
            _print_candidates(candidates, seed_to_move, moves_by_num,
                              inputs.target_delay, total)

            if not candidates:
                print()
                print("No matching seeds. Check for input errors or expand the window.")
                break

            if len(candidates) == 1:
                seed, delay = candidates[0]
                delta = delay - inputs.target_delay
                print()
                print(f"Seed identified: 0x{seed:08X}  delay={delay}  Δ={_delta_str(delta)}")
                break

            print()
            raw = input(f"Turn {turn} — Metronome move (or u=undo, q=quit): ").strip()

            if raw.lower() in ('q', 'quit'):
                return
            if raw.lower() == 'u':
                print("  (Undo not yet implemented for Phase 1)")
                continue

            move = _resolve_move_input(raw, moves_by_num)
            if move is None:
                suggestions = _suggest_moves(raw, moves_by_num)
                if suggestions:
                    names = ', '.join(f'"{m.name}"' for m in suggestions)
                    print(f"  Unknown move. Did you mean: {names}?")
                else:
                    print(f"  Unknown move {raw!r}. Check spelling and try again.")
                continue

            if not move.metronome_usable:
                print(f"  {move.name} cannot be selected by Metronome.")
                continue

            # Filter candidates by the observed move
            candidates = [(seed, delay) for seed, delay in candidates
                          if seed_to_move.get(seed) == move.number]
            turn += 1

            # NOTE (Phase 2): After filtering, advance RNG through this turn for each
            # remaining candidate to pre-compute turn 2's metronome move.
            # For now, the loop ends after one observation (single-turn Phase 1).
            print()
            _print_candidates(candidates, seed_to_move, moves_by_num,
                              inputs.target_delay, total)
            if len(candidates) == 1:
                seed, delay = candidates[0]
                delta = delay - inputs.target_delay
                print()
                print(f"Seed identified: 0x{seed:08X}  delay={delay}  Δ={_delta_str(delta)}")
            elif not candidates:
                print()
                print("No matching seeds. Check for input errors or expand the window.")
            break  # Phase 1: single observation per session

        print()
        again = input("Go again? (y/n): ").strip().lower()
        if again != 'y':
            break
        print()
