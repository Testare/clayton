"""metronome_species.py — Pokemon species eligible as a Metronome Compass user.

HGSS species data (gender category, abilities, learnable movepool) for the species that
can learn Metronome in HeartGold/SoulSilver — sourced from Serebii via
``one-offs/scrape_metronome_species.py`` (see that script's docstring for exact provenance:
which page sections count as "learnable through normal HGSS play", how pre-evolution moves
are folded in, and how Serebii's move spellings are matched against
``claytonlib/basedata/moves.json``'s canonical names). Gender/ability values were
cross-checked against https://www.serebii.net/pokedex-dp/<dex_no>.shtml for each species
(see notes/flagged_for_review.md's "Feedback 7" entry) — worth a spot check since this is
real game data driving what the app will and won't let a user save.

Metronome Compass itself is built and verified specifically for Natural Cure Chansey; other
species here are real, legitimate alternatives (not a hedge or a guess) but the app layer
still flags non-Chansey choices with a warning rather than treating them as fully
equivalent — see ``app/models.py``'s ``MetronomeUser.suitability_warnings``.
"""
from __future__ import annotations

from dataclasses import dataclass

from claytonlib._resources import basedata_json

# Display order for the Species dropdown — by evolutionary line, matching how these were
# specified (draft2 feedback round 7).
_DISPLAY_ORDER = [
    "Happiny", "Chansey", "Blissey",
    "Cleffa", "Clefairy", "Clefable",
    "Mew",
    "Togepi", "Togetic", "Togekiss",
    "Munchlax", "Snorlax",
    "Snubbull", "Granbull",
]


@dataclass(frozen=True)
class MetronomeSpecies:
    """One species' HGSS gender/ability/movepool data.

    ``gender`` is a coarse category — "female_only" / "male_only" / "genderless" / "both" —
    not the exact real-world ratio: that's all a gender-option dropdown actually needs (a
    "both" species just leaves male/female open to the user, since either is legitimately
    possible and only the real cartridge knows which).
    """
    name: str
    dex_no: int
    gender: str
    abilities: tuple[str, ...]
    moves: tuple[str, ...]


_cache: dict[str, MetronomeSpecies] | None = None


def _load() -> dict[str, MetronomeSpecies]:
    global _cache
    if _cache is None:
        data = basedata_json("metronome_species.json")
        _cache = {
            name: MetronomeSpecies(
                name=name, dex_no=info["dex_no"], gender=info["gender"],
                abilities=tuple(info["abilities"]), moves=tuple(info["moves"]))
            for name, info in data.items()
        }
    return _cache


def list_metronome_species() -> list[MetronomeSpecies]:
    """Every species offerable in the Metronome-user Species dropdown, in display order."""
    species = _load()
    return [species[name] for name in _DISPLAY_ORDER if name in species]


def metronome_species_by_name(name: str) -> MetronomeSpecies | None:
    return _load().get(name)
