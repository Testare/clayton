"""Gen 4 stat derivation from base stats, IVs, EVs, level and nature.

Battle Compass derives the *target's* stats this way — its IVs and nature are known because
the encounter is RNG-manipulated and the player enters them as Hunt configuration.  Our own
party's stats are entered directly off the in-game summary screen instead, so nothing here is
needed for them (notes/battle_compass.md sec 15.4.1).
"""
from __future__ import annotations

import math
from typing import Literal

StatKey = Literal["hp", "atk", "def", "spa", "spd", "spe"]

_STAT_KEYS: tuple[StatKey, ...] = ("hp", "atk", "def", "spa", "spd", "spe")

# name -> (raised stat, lowered stat); None for the five neutral natures.
NATURES: dict[str, tuple[StatKey, StatKey] | None] = {
    "Hardy":   None,             "Lonely":  ("atk", "def"),
    "Brave":   ("atk", "spe"),   "Adamant": ("atk", "spa"),
    "Naughty": ("atk", "spd"),   "Bold":    ("def", "atk"),
    "Docile":  None,             "Relaxed": ("def", "spe"),
    "Impish":  ("def", "spa"),   "Lax":     ("def", "spd"),
    "Timid":   ("spe", "atk"),   "Hasty":   ("spe", "def"),
    "Serious": None,             "Jolly":   ("spe", "spa"),
    "Naive":   ("spe", "spd"),   "Modest":  ("spa", "atk"),
    "Mild":    ("spa", "def"),   "Quiet":   ("spa", "spe"),
    "Bashful": None,             "Rash":    ("spa", "spd"),
    "Calm":    ("spd", "atk"),   "Gentle":  ("spd", "def"),
    "Sassy":   ("spd", "spe"),   "Careful": ("spd", "spa"),
    "Quirky":  None,
}


def nature_multiplier(nature: str, stat: StatKey) -> float:
    """1.1 / 0.9 / 1.0 for `stat` under `nature`.  HP is never affected."""
    try:
        effect = NATURES[_canonical_nature(nature)]
    except KeyError:
        raise ValueError(f"unknown nature {nature!r}") from None
    if effect is None or stat == "hp":
        return 1.0
    raised, lowered = effect
    if stat == raised:
        return 1.1
    if stat == lowered:
        return 0.9
    return 1.0


def _canonical_nature(nature: str) -> str:
    return nature.strip().capitalize()


def calc_stat(base: int, iv: int, ev: int, level: int, nature_mult: float = 1.0) -> int:
    """A non-HP stat.  Floors twice, exactly as the game does.

    The nature multiplier is applied to the *floored* pre-nature value and floored again —
    doing it in one step would round differently for some spreads.
    """
    _validate(base, iv, ev, level)
    pre = math.floor((2 * base + iv + ev // 4) * level / 100) + 5
    return math.floor(pre * nature_mult)


def calc_hp(base: int, iv: int, ev: int, level: int) -> int:
    """The HP stat.  Natures never affect it.

    Shedinja (base HP 1) is a special case in-game and is not modelled; nothing in scope has it.
    """
    _validate(base, iv, ev, level)
    return math.floor((2 * base + iv + ev // 4) * level / 100) + level + 10


def derive_stats(base: dict[str, int], level: int, nature: str = "Hardy",
                 ivs: dict[str, int] | int = 31,
                 evs: dict[str, int] | int = 0) -> dict[str, int]:
    """Full stat spread.  `ivs`/`evs` may be a per-stat dict or one value for every stat.

    Wild Pokemon have no EVs, so the default suits a Hunt target directly.
    """
    iv_map = ivs if isinstance(ivs, dict) else dict.fromkeys(_STAT_KEYS, ivs)
    ev_map = evs if isinstance(evs, dict) else dict.fromkeys(_STAT_KEYS, evs)
    missing = [k for k in _STAT_KEYS if k not in base]
    if missing:
        raise ValueError(f"base stats missing {missing}")
    out: dict[str, int] = {}
    for key in _STAT_KEYS:
        iv, ev = iv_map.get(key, 31), ev_map.get(key, 0)
        if key == "hp":
            out[key] = calc_hp(base[key], iv, ev, level)
        else:
            out[key] = calc_stat(base[key], iv, ev, level, nature_multiplier(nature, key))
    return out


def _validate(base: int, iv: int, ev: int, level: int) -> None:
    if not 1 <= level <= 100:
        raise ValueError(f"level out of range: {level}")
    if not 0 <= iv <= 31:
        raise ValueError(f"IV out of range: {iv}")
    if not 0 <= ev <= 252:
        raise ValueError(f"EV out of range: {ev}")
    if base < 1:
        raise ValueError(f"base stat out of range: {base}")
