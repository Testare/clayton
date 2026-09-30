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

# Stat-stage multipliers, indexed -6..+6.  A critical hit ignores **every stat change that
# would reduce its damage** [verified]: the target's raised defences AND the attacker's lowered
# offences.  Changes that would *increase* the damage still apply.  That is why X Sp. Def does
# not lower the danger floor (sec 12.3) -- and, symmetrically, why lowering the opponent's
# offence does not protect against its crits either.
_STAGE_NUM = (2, 2, 2, 2, 2, 2, 2, 3, 4, 5, 6, 7, 8)
_STAGE_DEN = (8, 7, 6, 5, 4, 3, 2, 2, 2, 2, 2, 2, 2)


def stage_multiplier(stage: int) -> float:
    if not -6 <= stage <= 6:
        raise ValueError(f"stat stage out of range: {stage}")
    return _STAGE_NUM[stage + 6] / _STAGE_DEN[stage + 6]


#: Type-enhancing held items -> the type they boost, from the ROM's `sTypeEnhancingItems`
#: (src/battle/overlay_12_0224E4FC.c). All the Gen 4 classics; plates and incenses behave the
#: same way and can be added here as needed.
TYPE_ENHANCING_ITEMS: dict[str, str] = {
    "silk scarf": "Normal",      "charcoal": "Fire",         "mystic water": "Water",
    "magnet": "Electric",        "miracle seed": "Grass",    "never-melt ice": "Ice",
    "nevermeltice": "Ice",       "black belt": "Fighting",   "poison barb": "Poison",
    "soft sand": "Ground",       "sharp beak": "Flying",     "twisted spoon": "Psychic",
    "silver powder": "Bug",      "hard stone": "Rock",       "spell tag": "Ghost",
    "dragon fang": "Dragon",     "black glasses": "Dark",    "metal coat": "Steel",
}
#: Percent added by a matching type-enhancing item. The ROM reads this from the item's own
#: ITEM_VAR_MODIFIER, which lives in a binary NARC -- 20 is the documented Gen 4 value for every
#: item above, but unlike the ORDERING below it was not read out of the source.
TYPE_ITEM_MODIFIER_PERCENT = 20

#: Technician raises base power by half when the power is 60 or less (ABILITY_TECHNICIAN, and the
#: ROM checks the power *after* earlier power modifiers, not the raw base power).
TECHNICIAN_POWER_CAP = 60

#: Abilities that change damage and are NOT modelled here. Listed so an unmodelled one is
#: reported rather than silently ignored -- the same discipline `unsupported_reason` applies to
#: moves, and for incoming damage an unnoticed modifier is unsound, not merely imprecise.
UNMODELLED_DAMAGE_ABILITIES = frozenset({
    "huge power", "pure power", "hustle", "guts", "blaze", "torrent", "overgrow", "swarm",
    "flash fire", "thick fat", "heatproof", "levitate", "solid rock", "filter", "sniper",
    "tinted lens", "rivalry", "slow start", "iron fist", "reckless", "sheer force",
    "adaptability", "dry skin", "water absorb", "volt absorb", "flash fire", "wonder guard",
    "marvel scale", "mold breaker",
})


@dataclass(frozen=True)
class Attacker:
    """The opponent, as the damage formula sees it."""
    level: int
    attack: int          # Atk for a physical move, SpA for a special one
    special_attack: int
    types: tuple[str, ...]
    attack_stage: int = 0
    special_attack_stage: int = 0
    #: Lowercase-insensitive; only Technician is modelled, and anything in
    #: UNMODELLED_DAMAGE_ABILITIES is reported by `unsupported_attacker_reason`.
    ability: str = ""
    #: A type-enhancing item raises base power by TYPE_ITEM_MODIFIER_PERCENT.
    held_item: str = ""


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


def effective_power(move: Move, attacker: Attacker) -> int:
    """Base power after the attacker's ability and held item.

    Order and arithmetic transcribed from the ROM (src/battle/overlay_12_0224E4FC.c): Technician
    first as ``power * 15 / 10``, then a matching type-enhancing item as
    ``power * (100 + mod) / 100``, both integer division. The order is not cosmetic -- for a
    Technician user holding Silk Scarf, False Swipe goes 40 -> 60 -> 72, where applying the item
    first would give 40 -> 48 -> 72 by luck here but differ elsewhere.
    """
    power = move.power
    ability = attacker.ability.strip().lower()
    if ability == "technician" and power <= TECHNICIAN_POWER_CAP:
        power = power * 15 // 10
    boosted = TYPE_ENHANCING_ITEMS.get(attacker.held_item.strip().lower())
    if boosted is not None and boosted == move.type_name:
        power = power * (100 + TYPE_ITEM_MODIFIER_PERCENT) // 100
    return power


def unsupported_attacker_reason(attacker: Attacker) -> str | None:
    """Why this attacker's damage cannot be modelled, or None.

    Mirrors `unsupported_reason` for moves: an ability we do not implement must be *reported*,
    never assumed inert. For incoming damage an unnoticed multiplier eliminates the true seed.
    """
    ability = attacker.ability.strip().lower()
    if ability in UNMODELLED_DAMAGE_ABILITIES:
        return f"{attacker.ability} changes damage and is not modelled"
    return None


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
    defence_stage = defender.defence_stage if physical else defender.special_defence_stage
    attack_stage = attacker.attack_stage if physical else attacker.special_attack_stage
    # A crit ignores any stage that would REDUCE its damage -- the defender's raised defences and
    # the attacker's lowered offences -- while keeping those that would raise it.
    if not (critical and defence_stage > 0):
        defence = max(1, math.floor(defence * stage_multiplier(defence_stage)))
    if not (critical and attack_stage < 0):
        attack = max(1, math.floor(attack * stage_multiplier(attack_stage)))

    # The ROM's level term is INTEGER division -- `((level * 2 / 5) + 2)` in C -- so it differs
    # from a float form at any level where 2*level is not a multiple of 5 (63, 67, 71, 78...).
    # Level 40 and 60 are exact, which is why the fixture never showed it.
    level_term = (attacker.level * 2) // 5 + 2
    power = effective_power(move, attacker)
    base = math.floor(
        math.floor(math.floor(level_term * power * attack / defence) / 50)
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
