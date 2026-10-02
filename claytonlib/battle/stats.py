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


# ---------------------------------------------------------------------------
# Species base stats
# ---------------------------------------------------------------------------

_species_cache: dict[str, dict] | None = None


def _load_species() -> dict[str, dict]:
    global _species_cache
    if _species_cache is None:
        from claytonlib._resources import basedata_json
        _species_cache = basedata_json("base_stats.json")
    return _species_cache


def species(name: str) -> dict:
    """Base stats, types and weight for one species, from basedata/base_stats.json.

    Only ever needed for *targets*: our own party's stats are entered directly (sec 15.4.1).
    Regenerate or extend the file with `one-offs/populate_base_stats.py`.
    """
    key = name.strip().lower().replace(" ", "-")
    data = _load_species()
    if key in data:
        return data[key]
    # Forms are stored under their suffixed name (e.g. giratina-altered); accept the bare one.
    matches = [k for k in data if k.split("-")[0] == key]
    if len(matches) == 1:
        return data[matches[0]]
    raise KeyError(
        f"no base stats for {name!r}"
        + (f" (did you mean one of {matches}?)" if matches else
           "; add it with one-offs/populate_base_stats.py")
    )


def derive_species_stats(name: str, level: int, nature: str = "Hardy",
                         ivs: dict[str, int] | int = 31,
                         evs: dict[str, int] | int = 0) -> dict[str, int]:
    """`derive_stats` looked up by species name."""
    return derive_stats(species(name)["base_stats"], level, nature, ivs, evs)


def abilities(name: str) -> tuple[str, ...]:
    """The species' possible abilities, in slot order.

    Gen 4 values, taken from the ROM's own `personal.json` rather than from PokeAPI's Gen 9 view
    -- several species gained or swapped abilities after Gen 4, and the one the simulator reads
    changes how a battle is scored.
    """
    return tuple(species(name).get("abilities", ()))


def has_pressure(name: str) -> bool:
    """Whether this species has Pressure, which **doubles OUR PP consumption** (sec 4.4).

    Worth its own function because the cost of guessing is asymmetric and invisible: assuming
    Pressure where there is none halves every PP budget the solver plans against, and the run
    simply runs out of moves earlier than the plan said it would. All three tower birds have it;
    both Lati twins have Levitate instead.

    A species with Pressure in *either* slot counts: a wild Pokemon's ability is drawn from its
    slots, and none of the targets here has Pressure in only one.
    """
    return any(a.strip().lower() == "pressure" for a in abilities(name))


def has_fast_ball_bonus(name: str) -> bool:
    """Whether the Fast Ball's x4 applies: base Speed >= 100.

    Suicune is 85 and Groudon 90, so both get a flat x1 — the case Battle Compass exists for
    (notes/battle_compass.md sec 4.1).
    """
    return species(name)["base_stats"]["spe"] >= 100


#: The stat order a spread is written and read in, everywhere in this project: hp/atk/def/spa/
#: spd/spe. Public because the run page, the facade and the gdb override all have to agree about
#: which number is which -- a spread read in the wrong order is still six valid IVs, so nothing
#: downstream would object to it.
STAT_KEYS: tuple[StatKey, ...] = _STAT_KEYS

#: Highest legal IV. Gen 4 stores five bits per IV.
MAX_IV = 31


def nature_names() -> tuple[str, ...]:
    """Every nature, alphabetically — the order a picker should offer them in."""
    return tuple(sorted(NATURES))


def parse_iv_spread(text: str) -> dict[StatKey, int]:
    """Six IVs from one whitespace-separated string, in :data:`STAT_KEYS` order.

    For the run page, where the player types a spread they derived themselves after
    identifying a Seed A that was not the key seed. One parser rather than a regex in the page
    and a loop in the facade, because the failure is silent in the worst way: a spread short by
    one value shifts every later stat by a position, and five plausible IVs plus a missing
    Speed is indistinguishable from a typo until the simulation desynchronises mid-battle.

    Raises ValueError naming what is actually wrong -- how many values were found, or which
    ones are not integers in 0..31 -- since "invalid IVs" sends the player back to count on
    their fingers.
    """
    tokens = (text or "").replace(",", " ").split()
    if len(tokens) != len(STAT_KEYS):
        raise ValueError(
            f"expected {len(STAT_KEYS)} IVs in {'/'.join(STAT_KEYS)} order, got "
            f"{len(tokens)}: {' '.join(tokens) if tokens else '(nothing)'}")
    values: list[int] = []
    bad: list[str] = []
    for key, token in zip(STAT_KEYS, tokens):
        try:
            value = int(token)
        except ValueError:
            bad.append(f"{key}={token!r} is not a number")
            continue
        if not 0 <= value <= MAX_IV:
            bad.append(f"{key}={value} is outside 0-{MAX_IV}")
            continue
        values.append(value)
    if bad:
        raise ValueError("; ".join(bad))
    return dict(zip(STAT_KEYS, values))


def format_iv_spread(ivs: dict[str, int]) -> str:
    """The inverse of :func:`parse_iv_spread`, for prefilling the field."""
    missing = [k for k in STAT_KEYS if not isinstance(ivs.get(k), int)]
    if missing:
        raise ValueError("spread is missing " + ", ".join(missing))
    return " ".join(str(ivs[k]) for k in STAT_KEYS)
