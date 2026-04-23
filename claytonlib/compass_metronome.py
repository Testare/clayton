"""
compass_metronome.py — Seed identification via Metronome observation.

Given a starting seed window and an observed Metronome move, narrows down
the candidate seed list by simulating which seeds would produce that move.
"""
import copy
import datetime as dt
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from claytonlib.safari import advance_rng
from claytonlib.times import get_times, calculate_seed


# ---------------------------------------------------------------------------
# Move data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Move:
    number: int
    name: str
    metronome_usable: bool


_moves: list[Move] | None = None


def _load_moves() -> list[Move]:
    global _moves
    if _moves is None:
        path = Path(__file__).parent / "basedata" / "moves.json"
        with open(path) as f:
            data = json.load(f)
        _moves = [Move(number=m["number"], name=m["name"],
                       metronome_usable=m["metronome_usable"]) for m in data]
    return _moves


def _moves_by_number() -> dict[int, Move]:
    return {m.number: m for m in _load_moves()}


def _moves_by_name() -> dict[str, Move]:
    """Lowercase-normalised name → Move."""
    return {m.name.lower(): m for m in _load_moves()}


def _normalise(s: str) -> str:
    return s.strip().lower().replace('-', ' ').replace('_', ' ')


def resolve_move(text: str) -> Move | None:
    """Return a Move for the given name string, or None if not found."""
    key = _normalise(text)
    return _moves_by_name().get(key)


def suggest_moves(text: str, n: int = 3) -> list[Move]:
    """Return up to n moves whose names contain the query as a substring."""
    key = _normalise(text)
    return [m for m in _load_moves() if key in m.name.lower()][:n]


# ---------------------------------------------------------------------------
# MetronomeOpponent
# ---------------------------------------------------------------------------

class MetronomeOpponent(Enum):
    MAGIKARP = "magikarp"


# ---------------------------------------------------------------------------
# CompassMetronomeInput
# ---------------------------------------------------------------------------

@dataclass
class CompassMetronomeInput:
    opponent:     MetronomeOpponent
    key_seed:     int
    target_delay: int
    initial_time: dt.datetime
    window:       int


# ---------------------------------------------------------------------------
# Seed generation (raw seeds, no SafariContext needed)
# ---------------------------------------------------------------------------

def _generate_metronome_candidates(inputs: CompassMetronomeInput) -> list[tuple[int, int]]:
    """Return sorted (seed, delay) pairs for the search window."""
    base_delay, _ = get_times(inputs.key_seed)
    results: list[tuple[int, int]] = []

    start = inputs.target_delay - inputs.window
    if (start - base_delay) % 2 != 0:
        start += 1

    for d in range(start, inputs.target_delay + inputs.window + 1, 2):
        offset = d - base_delay
        if offset < 0:
            continue
        second_idx = offset // 60
        frame_j = (offset % 60) // 2
        time_at = inputs.initial_time + dt.timedelta(seconds=second_idx)
        f = calculate_seed(time_at, base_delay + second_idx * 60)

        seed_a = f + 2 * frame_j
        results.append((seed_a, d))

        if frame_j > 0:
            t2 = calculate_seed(time_at + dt.timedelta(seconds=1),
                                base_delay + (second_idx + 1) * 60)
            seed_b = t2 - 2 * (30 - frame_j)
            results.append((seed_b, d))

    results.sort(key=lambda x: (x[1], x[0]))
    return results


# ---------------------------------------------------------------------------
# Metronome simulation
# ---------------------------------------------------------------------------

_METRONOME_POOL = 0x1d3  # 467 — total moves in the roll range


def _simulate_metronome(seed: int) -> int:
    """Return the move number Metronome would select for this raw seed.

    Advances: 7 (battle start, mirroring start_encounter) + 4 (before-turn),
    then rolls rand % 0x1d3 + 1, rerolling on disallowed moves.
    """
    state = seed
    by_number = _moves_by_number()

    # 7 battle-start advances (mirrors start_encounter: 4 graphics + 2 ability + 1 flee)
    for _ in range(7):
        state = advance_rng(state)

    # 4 before-turn advances (mirrors throw_bait/mud/ball pattern)
    for _ in range(4):
        state = advance_rng(state)

    # Roll metronome, rerolling on disallowed moves
    while True:
        state = advance_rng(state)
        move_num = (state >> 16) % _METRONOME_POOL + 1
        move = by_number.get(move_num)
        if move is not None and move.metronome_usable:
            return move_num


def _filter_by_move(candidates: list[tuple[int, int]],
                    move_number: int) -> list[tuple[int, int]]:
    return [(seed, delay) for seed, delay in candidates
            if _simulate_metronome(seed) == move_number]


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
# analyze_compass_metronome
# ---------------------------------------------------------------------------

def analyze_compass_metronome(inputs: CompassMetronomeInput) -> list[tuple[int, str]]:
    """Return (seed, move_name) for every candidate in the window.

    Does not filter — useful for inspecting the distribution of Metronome
    outcomes across all seeds in the search window.
    """
    by_number = _moves_by_number()
    return [
        (seed, by_number[_simulate_metronome(seed)].name)
        for seed, _delay in _generate_metronome_candidates(inputs)
    ]


# ---------------------------------------------------------------------------
# compass_metronome
# ---------------------------------------------------------------------------

def compass_metronome(inputs: CompassMetronomeInput) -> None:
    """Interactive seed identifier using Metronome move observations."""
    candidates = _generate_metronome_candidates(inputs)
    total = len(candidates)

    print("=== Compass: Metronome Seed Identifier ===")
    print(f"Opponent: {inputs.opponent.value.capitalize()}")
    print(f"Window:   ±{inputs.window} frames ({total} initial candidates)")
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

        candidates = _filter_by_move(candidates, move.number)

        # Only one loop iteration for now; loop structure in place for future observations.
        break

    print()
    _print_metronome_status(candidates, total, inputs.target_delay)
    if len(candidates) == 1:
        seed, delay = candidates[0]
        delta = delay - inputs.target_delay
        print()
        print(f"Seed identified: 0x{seed:08X}  delay={delay}  Δ={_delta_str(delta)}")
