"""Gen 4 damage, for damage the *opponent* deals to us.

Deliberately one-directional.  Damage we deal is never modelled: we only ever see the
opponent's HP bar, and Battle Compass never needs the number — the target's HP is a
player-declared binary ("at 1 HP or not").  Damage we *take* is the opposite case, because we
know both sides' exact stats and can therefore read the damage roll off an observed HP change.
That makes it the richest identification signal available, worth ~2.5 bits per hit against
~2.8 for everything else in a turn combined.  See notes/battle_compass.md sec 3.1 and sec 5.

Scope is narrow on purpose, and scales per opponent.  For Suicune the entire surface is Aurora
Beam and Gust, and no damage modifiers apply at all: rain does not touch Ice or Flying, Mist
guards its own side, Aurora Beam's Attack drop affects damage we *deal*, it has no screens, and
nothing in its kit touches our defensive stat stages.  Screens, weather and damage-absorbing
abilities are unimplemented rather than assumed absent — `unsupported_reason` says so, and the
caller is expected to refuse to filter rather than filter wrongly.

An error here is **unsound, not imprecise**: it eliminates the true seed.  Every opponent's
moves must be validated against emulator ground truth before the filter is enabled for it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from claytonlib.battle.types import effectiveness
from claytonlib.moves import CATEGORY_PHYSICAL, CATEGORY_SPECIAL, Move

# Gen 4 multiplies damage by one of sixteen values, 85..100 percent.
DAMAGE_ROLLS: tuple[int, ...] = tuple(range(85, 101))

# Stat-stage multipliers for Defence/Sp. Def, indexed -6..+6.  Critical hits ignore the
# defender's *positive* stages (Gen 3-5), which is why X Sp. Def does not lower the danger
# floor -- see sec 12.3.
_STAGE_NUM = (2, 2, 2, 2, 2, 2, 2, 3, 4, 5, 6, 7, 8)
_STAGE_DEN = (8, 7, 6, 5, 4, 3, 2, 2, 2, 2, 2, 2, 2)


def stage_multiplier(stage: int) -> float:
    if not -6 <= stage <= 6:
        raise ValueError(f"stat stage out of range: {stage}")
    return _STAGE_NUM[stage + 6] / _STAGE_DEN[stage + 6]


@dataclass(frozen=True)
class Attacker:
    """The opponent, as the damage formula sees it."""
    level: int
    attack: int          # Atk for a physical move, SpA for a special one
    special_attack: int
    types: tuple[str, ...]


@dataclass(frozen=True)
class Defender:
    """Our active Pokemon."""
    defence: int
    special_defence: int
    types: tuple[str, ...]
    defence_stage: int = 0
    special_defence_stage: int = 0


def unsupported_reason(move: Move) -> str | None:
    """Why this move's damage cannot be modelled yet, or None if it can.

    Callers must treat a reason as "do not filter on damage", never as "assume zero".
    """
    if move.category == CATEGORY_PHYSICAL or move.category == CATEGORY_SPECIAL:
        if move.power <= 1:
            # power 1 marks fixed-damage and variable-power moves (Seismic Toss, Psywave,
            # Low Kick, Flail...), each of which needs its own rule.
            return f"{move.name} has no fixed base power"
        return None
    return f"{move.name} is a status move and deals no damage"


def damage(move: Move, attacker: Attacker, defender: Defender, *,
           roll: int = 100, critical: bool = False) -> int:
    """Damage for one hit, in HP.

    `roll` is the 85..100 damage roll.  Flooring happens at each step exactly as the game does;
    collapsing them changes the result for some inputs.
    """
    reason = unsupported_reason(move)
    if reason:
        raise ValueError(reason)
    if roll not in DAMAGE_ROLLS:
        raise ValueError(f"damage roll must be 85..100, got {roll}")

    physical = move.category == CATEGORY_PHYSICAL
    attack = attacker.attack if physical else attacker.special_attack
    defence = defender.defence if physical else defender.special_defence
    stage = defender.defence_stage if physical else defender.special_defence_stage
    # A critical hit ignores the defender's positive stages but keeps negative ones.
    if not (critical and stage > 0):
        defence = max(1, math.floor(defence * stage_multiplier(stage)))

    base = math.floor(
        math.floor(math.floor((2 * attacker.level / 5 + 2) * move.power * attack / defence) / 50)
    ) + 2
    if critical:
        base *= 2
    if move.type_name in attacker.types:
        base = math.floor(base * 1.5)          # STAB
    base = math.floor(base * effectiveness(move.type_name, defender.types))
    if base == 0:
        return 0                                # immune, or scaled away entirely
    return max(1, math.floor(base * roll / 100))


def damage_spread(move: Move, attacker: Attacker, defender: Defender, *,
                  critical: bool = False) -> dict[int, int]:
    """`roll` -> damage, for all sixteen rolls.

    This is what makes the sec 3.1 filter work: an observed HP change identifies the set of
    rolls consistent with it, and therefore constrains the RNG state.
    """
    return {roll: damage(move, attacker, defender, roll=roll, critical=critical)
            for roll in DAMAGE_ROLLS}


def rolls_for_damage(observed: int, move: Move, attacker: Attacker, defender: Defender, *,
                     critical: bool = False) -> tuple[int, ...]:
    """Which damage rolls could have produced `observed`.

    Empty means no roll can — the seed, the stats, or this model is wrong.  Callers must
    surface that rather than silently discarding candidates (sec 3.1).
    """
    spread = damage_spread(move, attacker, defender, critical=critical)
    return tuple(roll for roll, value in spread.items() if value == observed)


def damage_range(move: Move, attacker: Attacker, defender: Defender, *,
                 critical: bool = False) -> tuple[int, int]:
    """(minimum, maximum) over the sixteen rolls."""
    values = damage_spread(move, attacker, defender, critical=critical).values()
    return min(values), max(values)
