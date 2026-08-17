"""Utilities for generating test seeds in metronome compass development."""
from __future__ import annotations
from claytonlib.moves import resolve_move


def reverse_rng(state: int, n: int = 1) -> int:
    """Backtrack the LCRNG n steps using the multiplicative inverse."""
    inv_mult = 0xEEB9EB65
    for _ in range(n):
        state = ((state - 24691) * inv_mult) & 0xFFFFFFFF
    return state


def generate_seed_for_move(move_name: str, magikarp_level: int = 2, offset: int = 0) -> int:
    """Return a seed whose Turn 1 Metronome roll produces the named move.

    The Metronome pool has 467 entries, so multiple top-16-bit values map to
    the same move: top16 = (move_number - 1) + k * 467 for k = 0, 1, 2, ...
    offset selects k; offset=0 gives the smallest top-16 value.
    Raises ValueError if the move is not Metronome-usable or the offset
    pushes top16 above 0xFFFF.
    """
    move = resolve_move(move_name)
    if not move or not move.metronome_usable:
        raise ValueError(f"Move {move_name!r} is not Metronome-usable.")

    pool = 467
    top16 = (move.number - 1) + offset * pool
    if top16 > 0xFFFF:
        raise ValueError(
            f"offset={offset} puts top16=0x{top16:X} above 0xFFFF for move {move_name!r}"
        )

    state = top16 << 16

    # Advances consumed before the Turn 1 Metronome roll:
    # 6 (Battle Start) + optional 1 (Magikarp move select if level >= 15)
    # + 4 (BeforeTurn) + 1 (Metronome roll itself)
    advances = 6 + (1 if magikarp_level >= 15 else 0) + 4 + 1
    return reverse_rng(state, advances)
