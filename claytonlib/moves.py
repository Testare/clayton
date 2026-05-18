"""moves.py — Centralized move data loading and lookup for Metronome tools.

Single source of truth for Move objects parsed from basedata/moves.json.
Used by compass_premetronome and metronome_compass_full.
"""
from __future__ import annotations

import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Move data type
# ---------------------------------------------------------------------------

class Move:
    """Move metadata loaded from moves.json."""
    __slots__ = ('number', 'name', 'metronome_usable', 'effect', 'effect_chance', 'accuracy')

    def __init__(self, number: int, name: str, metronome_usable: bool,
                 effect: int = 0, effect_chance: int = 0, accuracy: int = 0):
        self.number = number
        self.name = name
        self.metronome_usable = metronome_usable
        self.effect = effect
        self.effect_chance = effect_chance
        self.accuracy = accuracy  # 0 = always hits (bypasses accuracy check)

    def is_gravity_blocked(self) -> bool:
        """Returns True if this move is blocked by Gravity (Gen IV list)."""
        # HGSS gravity-blocked moves
        return self.number in {
            19,   # Fly
            26,   # Jump Kick
            136,  # Hi Jump Kick
            150,  # Splash
            340,  # Bounce
            393,  # Magnet Rise
        }


# ---------------------------------------------------------------------------
# Loading and caching
# ---------------------------------------------------------------------------

_moves_cache: list[Move] | None = None


def _load_moves() -> list[Move]:
    global _moves_cache
    if _moves_cache is None:
        path = Path(__file__).parent / "basedata" / "moves.json"
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


def _moves_by_name() -> dict[str, Move]:
    """Lowercase-normalised name → Move."""
    return {m.name.lower(): m for m in _load_moves()}


# ---------------------------------------------------------------------------
# Public lookup helpers
# ---------------------------------------------------------------------------

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
