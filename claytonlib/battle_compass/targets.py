"""Known movesets for the static encounters Battle Compass can hunt.

Not derivable from anything already in the repo. Base stats are a property of the species, but a
moveset belongs to the *encounter*: the Bell Tower Suicune is Lv40 with these four moves in this
order, and a Suicune met any other way would differ. Slot order matters as much as membership --
it is what the ``E1``-``E4`` tokens refer to and what the wild move-selection roll indexes into
(sec 5.2 R4), so a reordered list would silently mis-simulate every turn.

One entry for now. v1 targets Suicune (sec 8); adding a target means adding its row here, its
base stats via ``one-offs/populate_base_stats.py``, and confirming its moves are among the nine
``sim`` implements.
"""
from __future__ import annotations

#: species key -> (level, moves in slot order). Levels are the encounter's, not a range.
STATIC_ENCOUNTERS: dict[str, tuple[int, tuple[str, ...]]] = {
    # HGSS Bell Tower, after the Burned Tower release. Roaming Suicune is the same set.
    "suicune": (40, ("Rain Dance", "Gust", "Aurora Beam", "Mist")),
}


def moveset(species: str) -> tuple[str, ...]:
    """The encounter moveset, in slot order. Raises for an unknown target.

    Raises rather than returning empty: the simulator needs the target's moves to advance a turn
    at all, so a missing moveset is a hard stop, not a degraded mode.
    """
    key = species.strip().lower().replace(" ", "-")
    entry = STATIC_ENCOUNTERS.get(key)
    if entry is None:
        raise KeyError(
            f"no known moveset for {species!r}. Battle Compass simulates the target's turns, so "
            f"its moves and their slot order are required; add it to "
            f"battle_compass.targets.STATIC_ENCOUNTERS.")
    return entry[1]


def encounter_level(species: str) -> int:
    """The level this target is met at, for cross-checking the configured one."""
    key = species.strip().lower().replace(" ", "-")
    entry = STATIC_ENCOUNTERS.get(key)
    if entry is None:
        raise KeyError(f"no known encounter for {species!r}")
    return entry[0]


def supported() -> tuple[str, ...]:
    return tuple(sorted(STATIC_ENCOUNTERS))
