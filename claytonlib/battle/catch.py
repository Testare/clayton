"""Gen 4 capture maths, ported from the ROM.

Transcribed from ``BattleSystem_CalculateBallShakes`` in pokeheartgold
(``src/battle/battle_command.c``), which is the authority rather than a formula written from
memory.  ``safari.py`` independently encodes the Safari specialization and is emulator-verified;
``tests/test_battle_catch.py`` asserts this module agrees with it across every Safari pokemon and
bait/mud stage, and separately reproduces the ROM's own arithmetic order.

**The arithmetic order matters and is easy to get wrong.**  The ROM's own comment says so:

    This is written like ballMultiplier * (catch rate fraction) * (health fraction), but the CPU
    actually does the operations from left to right, causing weird rounding issues.

So it floors *twice* — once after dividing by 10, once after the HP fraction — and collapsing
that into a single division gives a different answer for any ball whose multiplier is not a
multiple of 10.  An earlier version of this module did exactly that.

Two mechanisms, not one.  Standard balls set ``ball_multiplier``; **apricorn balls scale the catch
rate itself** and are then clamped to 1..255, so they see diminishing returns on high-catch-rate
species where a multiplier would not.

The shape that matters for Battle Compass: a capture needs **four consecutive** rolls whose high
16 bits fall under ``b``.  That makes captures a property of a *position in the RNG stream* rather
than a per-throw gamble, which is what the solver steers towards (notes/battle_compass.md sec 6.1).
"""
from __future__ import annotations

import math

# Standard-ball multipliers, in tenths.  sStandardBallCatchRates = [20, 15, 10, 15] for item IDs
# 2..5, i.e. Ultra, Great, Poke, Safari.
BALL_POKE = 10
BALL_GREAT = 15
BALL_ULTRA = 20
BALL_SAFARI = 15
BALL_SPORT = 15
# Conditional non-apricorn balls, at the value they take when their condition holds.
BALL_NET_MATCHED = 30       # Water or Bug target
BALL_DIVE_MATCHED = 35      # surfing / fishing / underwater
BALL_NEST_MATCHED = 40      # scales with the target's level; 40 is its ceiling
BALL_REPEAT_MATCHED = 30    # species already registered in the Pokedex
BALL_TIMER_MATCHED = 40     # grows with turn count, capped at x4
BALL_DUSK_MATCHED = 35      # night, or in a cave
BALL_QUICK_MATCHED = 40     # first turn only

# Status bonuses, in tenths.  The ROM applies sleep/freeze as a plain *= 2 and the others as
# (x * 15) / 10; both are expressible in tenths because (a * 20) // 10 == a * 2.
STATUS_NONE = 10
STATUS_PARALYSIS = 15
STATUS_POISON = 15
STATUS_BURN = 15
STATUS_SLEEP = 20
STATUS_FREEZE = 20

# A shake roll uses the RNG's high 16 bits.
ROLL_CEILING = 0x10000
SHAKES_TO_CAPTURE = 4
# At or above this, the ROM skips the shake rolls entirely and the catch is guaranteed.
GUARANTEED_CATCH_VALUE = 255


def apricorn_catch_rate(base_catch_rate: int, *, multiplier: int = 1, bonus: int = 0) -> int:
    """A catch rate after an apricorn ball's own scaling, clamped the way the ROM clamps it.

    Apricorn balls (Fast, Level, Lure, Heavy, Love, Moon) multiply or offset the *catch rate*
    rather than setting a ball multiplier, and the result is capped at 255 — so a species with a
    high base rate gains far less from one than a naive multiplier would suggest.

    Two ROM quirks worth knowing, neither of which affects Suicune:

    * **Fast Ball falls through into the Moon Ball case** (a missing ``break``), so a Fast Ball
      thrown at a Moon Ball species gets both multipliers.
    * **Heavy Ball tests the catch rate where it meant to test the weight**, so every species
      light enough not to benefit is instead penalised by 20.
    """
    rate = base_catch_rate * multiplier + bonus
    if rate > 0xFF:
        return 0xFF
    if rate < 0:
        return 1
    return rate


def fast_ball_catch_rate(base_catch_rate: int, base_speed: int) -> int:
    """Fast Ball: x4 on the catch rate, but only if the target's *base* Speed is >= 100.

    Suicune is 85 and Groudon 90, so both get nothing — which is the case Battle Compass exists
    for (notes/battle_compass.md sec 4.1).
    """
    return apricorn_catch_rate(base_catch_rate, multiplier=4 if base_speed >= 100 else 1)


def catch_value(catch_rate: int, *, ball_multiplier: int = BALL_POKE,
                cur_hp: int = 1, max_hp: int = 1,
                status_bonus: int = STATUS_NONE) -> int:
    """``modifiedCatchRate`` — the ROM's ``a``, in the ROM's arithmetic order.

    Note how little the HP term resolves to in practice: at ``cur_hp == 1`` the factor is
    ``(3M-2)/(3M)``, so with a x1 ball a catch-rate-3 target lands on 2 for *any* max HP >= 2 —
    its HP IVs never need to be known (sec 14.1).

    Deviation from the ROM, deliberately: the result is floored at 1.  The ROM has no such clamp
    and would divide by zero on a value of 0, which is reachable (catch rate 1, x1 ball, full HP).
    """
    if catch_rate < 1:
        raise ValueError(f"catch rate out of range: {catch_rate}")
    if max_hp < 1 or not 1 <= cur_hp <= max_hp:
        raise ValueError(f"HP out of range: {cur_hp}/{max_hp}")
    max_hp_times_3 = max_hp * 3
    lost_hp = max_hp_times_3 - cur_hp * 2
    # Left to right, flooring at each division -- see the module docstring.
    a = (catch_rate * ball_multiplier) // 10
    a = (a * lost_hp) // max_hp_times_3
    a = (a * status_bonus) // 10
    return max(a, 1)


def is_guaranteed(a: int) -> bool:
    """Whether the ROM skips the shake rolls and captures outright."""
    return a >= GUARANTEED_CATCH_VALUE


def shake_threshold(a: int) -> int:
    """``shakeProbability`` — the value each of the four rolls must come in under.

    ``0xFFFF0 / isqrt(isqrt(0xFF0000 / a))``, using the DS's integer square root.  Only
    meaningful below :data:`GUARANTEED_CATCH_VALUE`; at or above it the ROM never gets here, so
    this returns :data:`ROLL_CEILING` to keep callers monotonic.
    """
    if a < 1:
        raise ValueError(f"catch value must be >= 1, got {a}")
    if is_guaranteed(a):
        return ROLL_CEILING
    return 0xFFFF0 // math.isqrt(math.isqrt(0xFF0000 // a))


def capture_chance(a: int) -> float:
    """Chance a single throw captures: all four rolls under ``b``.

    Named to match ``SafariPokemon.capture_chance``, and deliberately *not*
    ``capture_probability`` — ``chart.scorer`` uses that for a landing-weighted probability over a
    distribution of frames, and ``claytonlib/__init__``'s auto-export would shadow one with the
    other.
    """
    if is_guaranteed(a):
        return 1.0
    return min(shake_threshold(a) / ROLL_CEILING, 1.0) ** SHAKES_TO_CAPTURE


def shakes_for_rolls(rolls: tuple[int, ...] | list[int], b: int) -> int:
    """Shake count 0-4 from one throw's (high-16) rolls; 4 means captured.

    The ROM breaks out of its loop on the first roll at or above ``b``, so a throw consumes 1-4
    rolls rather than always 4 — which is why a ball is a *variable*-cost action for the solver
    (sec 12.5).
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
    return SHAKES_TO_CAPTURE if shakes == SHAKES_TO_CAPTURE else shakes + 1


def captures(rolls: tuple[int, ...] | list[int], b: int) -> bool:
    return shakes_for_rolls(rolls, b) == SHAKES_TO_CAPTURE


def capture_windows(high16: list[int] | tuple[int, ...], b: int) -> list[int]:
    """Offsets where four consecutive rolls are all under ``b`` — the solver's goal positions.

    Dense in practice: at ``b = 21845`` (a target at 1 HP, paralyzed, x1 ball) roughly one offset
    in 79 starts a window (sec 1).
    """
    limit = len(high16) - SHAKES_TO_CAPTURE + 1
    return [i for i in range(max(0, limit))
            if all(high16[i + j] < b for j in range(SHAKES_TO_CAPTURE))]
