"""moves.py — Centralized move data loading and lookup for Metronome tools.

Single source of truth for Move objects parsed from basedata/moves.json.
Used by compass_premetronome and metronome_compass.
"""
from __future__ import annotations

import json
from claytonlib._resources import basedata_json


# ---------------------------------------------------------------------------
# Move data type
# ---------------------------------------------------------------------------

TYPE_NAMES: dict[int, str] = {
    0: 'Normal',   1: 'Fighting', 2: 'Flying',   3: 'Poison',
    4: 'Ground',   5: 'Rock',     6: 'Bug',       7: 'Ghost',
    8: 'Steel',    9: '???',      10: 'Fire',     11: 'Water',
    12: 'Grass',   13: 'Electric', 14: 'Psychic', 15: 'Ice',
    16: 'Dragon',  17: 'Dark',
}


# Damage category, as moves.json stores it.
CATEGORY_PHYSICAL, CATEGORY_SPECIAL, CATEGORY_STATUS = 0, 1, 2


class Move:
    """Move metadata loaded from moves.json."""
    __slots__ = ('number', 'name', 'metronome_usable', 'effect', 'effect_chance', 'accuracy',
                 'type_id', 'category', 'power', 'priority', 'pp', 'flags')

    def __init__(self, number: int, name: str, metronome_usable: bool,
                 effect: int = 0, effect_chance: int = 0, accuracy: int = 0,
                 type_id: int = 0, category: int = CATEGORY_STATUS,
                 power: int = 0, priority: int = 0, pp: int = 0, flags: int = 0):
        self.number = number
        self.name = name
        self.metronome_usable = metronome_usable
        self.effect = effect
        self.effect_chance = effect_chance
        self.accuracy = accuracy  # 0 = always hits (bypasses accuracy check)
        self.type_id = type_id
        # 0 physical / 1 special / 2 status, as moves.json carries it. Defaults to status,
        # the inert choice: a Move built without one gains no physical-move behaviour.
        self.category = category
        # Battle Compass needs these three; the Metronome tools never did, which is why they
        # sat unread in moves.json until now (notes/battle_compass.md sec 17.3).
        self.power = power        # base power; 0 for status moves, 1 for fixed-damage moves
        self.priority = priority  # move-order bracket (Protect is +3, Roar -6)
        self.pp = pp              # base PP, before PP Ups/Maxes
        # The ROM's move flag byte (`unkB` in the decomp, `unk_b` in moves.json). Only bit 0
        # is read so far -- see `makes_contact`.
        self.flags = flags

    @property
    def makes_contact(self) -> bool:
        """Whether this move makes contact -- bit 0 of the ROM's move flag byte.

        `CheckAbilityEffectOnHit` gates the contact abilities on
        ``moveData[moveNoCur].unkB & 1`` (src/battle/overlay_12_0224E4FC.c), so this is the flag
        that decides whether Static, Rough Skin, Flame Body and friends get to roll at all. Read
        off the table rather than kept as a move-name list, because a list is wrong the first time
        a new target brings a move nobody thought of.

        Worth knowing which way round it falls for the configured targets: Punishment and False
        Swipe make contact; Sacred Fire, Ancient Power, Air Slash and Discharge do not.
        """
        return bool(self.flags & 1)

    @property
    def is_physical(self) -> bool:
        """Whether this is a physical move — what Hustle's accuracy cut applies to."""
        return self.category == CATEGORY_PHYSICAL

    @property
    def type_name(self) -> str:
        return TYPE_NAMES.get(self.type_id, '???')

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
        data = basedata_json("moves.json")
        _moves_cache = [
            Move(
                number=m["number"],
                name=m["name"],
                metronome_usable=m["metronome_usable"],
                effect=m["effect"],
                effect_chance=m["effect_chance"],
                accuracy=m["accuracy"],
                type_id=m["type"],
                category=m["category"],
                power=m["power"],
                priority=m["priority"],
                pp=m["pp"],
                flags=m.get("unk_b", 0),
            )
            for m in data
        ]
    return _moves_cache


#: Built once. `_load_moves` already caches the Move objects, but these two indexes were
#: REBUILT on every lookup -- and `resolve_move` is on the hottest path in the project.
#:
#: Measured: one reported turn against a 6,000-candidate window spent 59,675 `resolve_move`
#: calls and 28 MILLION `str.lower()` calls rebuilding this dict, ~3s of a ~6s turn. Nothing
#: about the move table changes at runtime, so the dict is built on first use and kept.
_by_number_cache: dict[int, Move] | None = None
_by_name_cache: dict[str, Move] | None = None


def _moves_by_number() -> dict[int, Move]:
    global _by_number_cache
    if _by_number_cache is None:
        _by_number_cache = {m.number: m for m in _load_moves()}
    return _by_number_cache


def _moves_by_name() -> dict[str, Move]:
    """Lowercase-normalised name → Move.

    Keyed on `m.name.lower()` while `resolve_move` looks up `_normalise(text)`, which also maps
    hyphens and underscores to spaces. That asymmetry is pre-existing and load-bearing: the table
    spells names with spaces, so normalising the QUERY is what lets "thunder-wave" resolve, and
    normalising the keys as well would change nothing. Left exactly as it was -- caching is the
    only change here.
    """
    global _by_name_cache
    if _by_name_cache is None:
        _by_name_cache = {m.name.lower(): m for m in _load_moves()}
    return _by_name_cache


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
