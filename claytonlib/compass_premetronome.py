"""
compass_premetronome.py — Seed identification via Metronome observation.

Given a starting seed window and an observed Metronome move, narrows down
the candidate seed list by simulating which seeds would produce that move.
"""
import copy
import datetime as dt
from dataclasses import dataclass
from enum import Enum

from claytonlib.safari import advance_rng
from claytonlib.times import get_times, calculate_seed
from claytonlib.moves import (
    Move, _load_moves, _moves_by_number, _moves_by_name,
    resolve_move, suggest_moves,
)


# ---------------------------------------------------------------------------
# MetronomeOpponent
# ---------------------------------------------------------------------------

class MetronomeOpponent(Enum):
    MAGIKARP = "magikarp"


# ---------------------------------------------------------------------------
# CompassPremetronomeInput
# ---------------------------------------------------------------------------

@dataclass
class CompassPremetronomeInput:
    opponent:      MetronomeOpponent
    key_seed:      int
    target_delay:  int
    initial_time:  dt.datetime
    window:        int
    second_window: int = 0
    magikarp_level: int = 0


# ---------------------------------------------------------------------------
# Seed generation (raw seeds, no SafariContext needed)
# ---------------------------------------------------------------------------

def _generate_metronome_candidates(inputs: CompassPremetronomeInput) -> list[tuple[int, int]]:
    """Return sorted (seed, delay) pairs for the search window.

    For each delay d, the two canonical seeds come from the two RTC seconds that
    straddle that delay (second_idx and second_idx+1).  With second_window > 0,
    additional seeds from second_idx ± second_window are included, which handles
    cases where the observed time differs from the calculated one.
    """
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
# Metronome simulation
# ---------------------------------------------------------------------------

_METRONOME_POOL = 0x1d3  # 467 — total moves in the roll range


def _simulate_turn_start(seed: int, magikarp_level: int) -> tuple[int, int]:
    """Return (metronome_move_number, magikarp_move_idx) for the first battle turn.

    Sequence before Metronome rolls:
      6 battle-start advances (graphics + ability checks)
      1 Magikarp move selection: idx = (rng >> 16) % num_moves
        num_moves = 2 (Splash/Tackle) if magikarp_level >= 15, else 1 (Splash only)
        This advance was previously misidentified as a 7th battle-start advance.
      4 BeforeTurn advances (BattleControllerPlayer_BeforeTurn, purpose unknown)

    magikarp_move_idx: 0 = Splash, 1 = Tackle.
    """
    state = seed
    by_number = _moves_by_number()

    # 6 battle-start advances
    for _ in range(6):
        state = advance_rng(state)

    # Magikarp move selection (advance 7)
    state = advance_rng(state)
    num_moves = 2 if magikarp_level >= 15 else 1
    magikarp_move_idx = (state >> 16) % num_moves

    # 4 BeforeTurn advances (BattleControllerPlayer_BeforeTurn)
    for _ in range(4):
        state = advance_rng(state)

    # Roll Metronome, rerolling on disallowed moves
    while True:
        state = advance_rng(state)
        move_num = (state >> 16) % _METRONOME_POOL + 1
        move = by_number.get(move_num)
        if move is not None and move.metronome_usable:
            return move_num, magikarp_move_idx


def _simulate_metronome(seed: int) -> int:
    """Return the move number Metronome would select for this raw seed."""
    move_num, _ = _simulate_turn_start(seed, magikarp_level=0)
    return move_num


def _filter_by_turn_start(candidates: list[tuple[int, int]],
                           move_number: int,
                           magikarp_move_idx: int | None,
                           magikarp_level: int) -> list[tuple[int, int]]:
    results = []
    for seed, delay in candidates:
        m_num, m_idx = _simulate_turn_start(seed, magikarp_level)
        if m_num != move_number:
            continue
        if magikarp_move_idx is not None and m_idx != magikarp_move_idx:
            continue
        results.append((seed, delay))
    return results


def _filter_by_move(candidates: list[tuple[int, int]],
                    move_number: int) -> list[tuple[int, int]]:
    return _filter_by_turn_start(candidates, move_number, None, 0)


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def _delta_str(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def _print_metronome_status(candidates: list[tuple[int, int]],
                             total: int, target_delay: int) -> None:
    print(f"Seeds: {len(candidates)} / {total} remaining")
    by_proximity = sorted(candidates, key=lambda x: (x[1] - target_delay, x[0]))
    display = by_proximity[:10]
    print(f"  {'#':>2}  {'Seed':>10}  {'Delay':>7}  {'Δ':>5}")
    for i, (seed, delay) in enumerate(display, 1):
        delta = delay - target_delay
        marker = "  ← target" if delta == 0 else ""
        print(f"  {i:>2}. 0x{seed:08X}  {delay:>7}  {_delta_str(delta):>5}{marker}")


# ---------------------------------------------------------------------------
# analyze_compass_premetronome
# ---------------------------------------------------------------------------

_MAGIKARP_MOVE_NAMES = {0: "Splash", 1: "Tackle"}


def analyze_compass_premetronome(inputs: CompassPremetronomeInput) -> list[tuple[int, str, str]]:
    """Return (seed, move_name, magikarp_move) for every candidate in the window.

    Does not filter — useful for inspecting the distribution of Metronome
    outcomes across all seeds in the search window.
    magikarp_move is always "Splash" when magikarp_level < 15.
    """
    by_number = _moves_by_number()
    return [
        (seed,
         by_number[move_num].name,
         _MAGIKARP_MOVE_NAMES[m_idx])
        for seed, _delay in _generate_metronome_candidates(inputs)
        for move_num, m_idx in [_simulate_turn_start(seed, inputs.magikarp_level)]
    ]


# ---------------------------------------------------------------------------
# compass_premetronome
# ---------------------------------------------------------------------------

def compass_premetronome(inputs: CompassPremetronomeInput) -> list[str]:
    """Interactive metronome seed identifier.

    Narrows down the candidate seed list by observing the move Metronome
    selects on the FIRST turn of battle.
    """

    candidates = _generate_metronome_candidates(inputs)
    total = len(candidates)

    print("=== Compass: Metronome Seed Identifier ===")
    print(f"Opponent: {inputs.opponent.value.capitalize()}")
    sw = f"  second_window=±{inputs.second_window}" if inputs.second_window else ""
    print(f"Window:   ±{inputs.window} delays{sw}  ({total} initial candidates)")
    print()

    while True:
        print()
        _print_metronome_status(candidates, total, inputs.target_delay)

        if len(candidates) == 0:
            print()
            print(f"No matching seed found in window ±{inputs.window}.")
            print("Consider expanding the search window or checking for input errors.")
            return

        raw = input("\nEnter observed Metronome move (or 'q' to quit): ").strip()
        if raw.lower() in ('q', 'quit'):
            return

        move = resolve_move(raw)
        if move is None:
            suggestions = suggest_moves(raw)
            if suggestions:
                names = ', '.join(f'"{m.name}"' for m in suggestions)
                print(f"  Unknown move. Did you mean: {names}?")
            else:
                print(f"  Unknown move {raw!r}. Check spelling and try again.")
            continue

        if not move.metronome_usable:
            print(f"  {move.name} cannot be selected by Metronome.")
            continue

        magikarp_move_idx = None
        if inputs.magikarp_level >= 15:
            while True:
                raw_k = input("Magikarp used Splash (s) or Tackle (t)? ").strip().lower()
                if raw_k in ('s', 'splash'):
                    magikarp_move_idx = 0
                    break
                elif raw_k in ('t', 'tackle'):
                    magikarp_move_idx = 1
                    break
                else:
                    print("  Enter 's' for Splash or 't' for Tackle.")

        candidates = _filter_by_turn_start(candidates, move.number,
                                           magikarp_move_idx, inputs.magikarp_level)

        # Only one loop iteration for now; loop structure in place for future observations.
        break

    print()
    _print_metronome_status(candidates, total, inputs.target_delay)
    if len(candidates) == 1:
        seed, delay = candidates[0]
        delta = delay - inputs.target_delay
        print()
        print(f"Seed identified: 0x{seed:08X}  delay={delay}  Δ={_delta_str(delta)}")
    
    return [f"0x{seed:08X}" for seed, delay in candidates]
