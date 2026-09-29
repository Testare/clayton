"""Gen 4 capture maths — the general GetShakeCount, of which the Safari path is a special case.

``safari.py`` already encodes the Safari specialization and is emulator-verified (a /2-vs-/3 bug
was fixed in clayton-ctd.15).  It hardcodes two things this module parameterises: the Safari
Ball's x1.5 and the full-HP case.  Generalising needs curHP/maxHP, a ball bonus and a status
bonus; nothing else changes, and ``tests/test_battle_catch.py`` asserts the two agree across
every Safari input.

The shape that matters for Battle Compass: a capture needs **four consecutive** RNG rolls whose
high 16 bits fall under ``b``.  That makes captures a property of a *position in the RNG stream*
rather than a per-throw gamble, which is what the solver steers towards
(notes/battle_compass.md sec 6.1).
"""
from __future__ import annotations

import math

# Ball bonuses, as tenths.  Conditional balls are listed at the value they take when their
# condition holds; the caller decides whether it does.
BALL_POKE = 10
BALL_GREAT = 15
BALL_SAFARI = 15
BALL_ULTRA = 20
BALL_FAST_MATCHED = 40      # x4, only when the target's BASE Speed >= 100
BALL_FAST_UNMATCHED = 10    # otherwise a plain x1 -- Suicune (85) and Groudon (90) land here

# Status bonuses, as tenths.  Gen 4 values; Gen 5 raised the sleep/freeze figure.
STATUS_NONE = 10
STATUS_PARALYSIS = 15
STATUS_POISON = 15
STATUS_BURN = 15
STATUS_SLEEP = 20
STATUS_FREEZE = 20

# A shake roll uses the RNG's high 16 bits.
ROLL_CEILING = 0x10000
SHAKES_TO_CAPTURE = 4


def catch_value(catch_rate: int, *, ball_bonus: int = BALL_POKE,
                cur_hp: int = 1, max_hp: int = 1,
                status_bonus: int = STATUS_NONE) -> int:
    """``a`` — the modified catch rate.

    ``a = ((3*maxHP - 2*curHP) * catchRate * ballBonus) / (3*maxHP)``, then the status bonus,
    floored at each division and never below 1.

    Note how little the HP term resolves to in practice: at ``cur_hp == 1`` the factor is
    ``(3M-2)/M``, which floors to 2 for *any* max HP >= 2 — so a target at 1 HP has an
    IV-independent catch value, and knowing its exact max HP is unnecessary (sec 14.1).
    """
    if catch_rate < 1:
        raise ValueError(f"catch rate out of range: {catch_rate}")
    if max_hp < 1 or not 1 <= cur_hp <= max_hp:
        raise ValueError(f"HP out of range: {cur_hp}/{max_hp}")
    a = ((3 * max_hp - 2 * cur_hp) * catch_rate * ball_bonus) // (3 * max_hp * 10)
    a = (a * status_bonus) // 10
    return max(a, 1)


def shake_threshold(a: int) -> int:
    """``b`` — the value each of the four shake rolls must come in under.

    Mirrors ``safari.py``'s float-sqrt formulation step for step, including where it floors;
    an integer-sqrt version differs on some inputs.
    """
    if a < 1:
        raise ValueError(f"catch value must be >= 1, got {a}")
    divisor = math.floor(math.sqrt(math.floor(math.sqrt(0xFF0000 / a))))
    if divisor < 1:
        return ROLL_CEILING          # a so large that any roll captures
    return math.floor(0xFFFF0 / divisor)


def capture_chance(a: int) -> float:
    """Chance a single throw captures: all four rolls under ``b``.

    Named to match ``SafariPokemon.capture_chance``, and deliberately *not*
    ``capture_probability`` — ``chart.scorer`` already uses that for something quite different
    (a landing-weighted probability integrated over a distribution of frames), and
    ``claytonlib/__init__``'s auto-export would have silently shadowed one with the other.
    """
    return min(shake_threshold(a) / ROLL_CEILING, 1.0) ** SHAKES_TO_CAPTURE


def shakes_for_rolls(rolls: tuple[int, ...] | list[int], b: int) -> int:
    """Shake count 0-4 from the (high-16) rolls of one throw; 4 means captured.

    The game stops rolling at the first failure, so it consumes 1-4 rolls, not always 4 — which
    is why a ball is a *variable*-cost action for the solver (sec 12.5).
    """
    shakes = 0
    for roll in rolls[:SHAKES_TO_CAPTURE]:
        if roll >= b:
            return shakes
        shakes += 1
    return shakes


def rolls_consumed(shakes: int) -> int:
    """How many RNG rolls a throw spent, given its shake count."""
    if not 0 <= shakes <= SHAKES_TO_CAPTURE:
        raise ValueError(f"shake count out of range: {shakes}")
    # A capture checks all four; anything less stops on the failing roll.
    return SHAKES_TO_CAPTURE if shakes == SHAKES_TO_CAPTURE else shakes + 1


def captures(rolls: tuple[int, ...] | list[int], b: int) -> bool:
    return shakes_for_rolls(rolls, b) == SHAKES_TO_CAPTURE


def capture_windows(high16: list[int] | tuple[int, ...], b: int) -> list[int]:
    """Offsets where four consecutive rolls are all under ``b`` — the solver's goal positions.

    Dense in practice: at ``b = 21845`` (a target at 1 HP, paralyzed, x1 ball) roughly one
    offset in 79 starts a window (sec 1).
    """
    limit = len(high16) - SHAKES_TO_CAPTURE + 1
    return [i for i in range(max(0, limit))
            if all(high16[i + j] < b for j in range(SHAKES_TO_CAPTURE))]
