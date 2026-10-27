"""Gen 4 damage, in both directions.

**Damage we take** is the richest identification signal available — we know both sides' exact
stats, so an observed HP change reads back the damage roll, worth ~2.5 bits per hit against ~2.8
for everything else in a turn combined (notes/battle_compass.md sec 3.1 and sec 5).

**Damage we deal is modelled too**, and this file claimed for a long time that it was not. The
claim came from sec 2.2's framing -- the target's HP is a player-declared binary, "at 1 HP or
not" -- but the simulator does compute our damage and does subtract it from the target
(`sim.act_ours`), and that is how the run knows whether enough False Swipes have landed to let
the solver start (`identify.solver_blockers`). So anything that changes the damage WE deal
changes when Phase 2 can begin: a burn halving our physical Attack means more False Swipes, and
an Attack drop from the target means the same.

Scope is narrow on purpose, and scales per opponent.  For Suicune the entire surface is Aurora
Beam and Gust, and no damage modifiers apply at all: its own Rain Dance does not touch Ice or
Flying, Mist guards its own side, Aurora Beam's Attack drop affects damage we *deal*, it has no
screens, and nothing in its kit touches our defensive stat stages.  That is what made weather
easy to leave out for v1 and impossible to leave out past it: Lugia's Hydro Pump under its own
Rain Dance is a 1.5x on the biggest hit in any configured moveset, and the move that made
fainting worth modelling.  Burn's halving and damage-absorbing abilities remain
unimplemented here rather than assumed absent — `unsupported_reason` says so, and the caller is
expected to refuse to filter rather than filter wrongly.

An error here is **unsound, not imprecise**: it eliminates the true seed.  Every opponent's
moves must be validated against emulator ground truth before the filter is enabled for it.
"""
from __future__ import annotations

from dataclasses import dataclass

from claytonlib.battle.types import effectiveness, type_multiplier
from claytonlib.moves import CATEGORY_PHYSICAL, CATEGORY_SPECIAL, CATEGORY_STATUS, Move

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
    """The stage's multiplier as a float, for reporting a margin.

    `apply_stage` is what the damage and speed paths use, because the ROM does the arithmetic in
    integers and a float detour is only safe by luck. Kept for callers that want the ratio
    itself -- `readiness`'s speed margins, which are advisory.
    """
    if not -6 <= stage <= 6:
        raise ValueError(f"stat stage out of range: {stage}")
    return _STAGE_NUM[stage + 6] / _STAGE_DEN[stage + 6]


def apply_stage(value: int, stage: int) -> int:
    """`value` after a stat stage, the way the ROM does it: integer, numerator then denominator.

    `sStatChangeTable` is written in tenths (``10/40`` at -6 through ``40/10`` at +6) and the ROM
    multiplies then divides in integers. Our table holds the same ratios reduced, which floors
    identically -- ``floor(15x/10) == floor(3x/2)`` -- so only the float detour was ever in
    question.

    It was not actually wrong: checked exhaustively over every stage and every stat value 1..800,
    ``floor(value * (num/den))`` agrees with the integer form everywhere. But four of the
    thirteen ratios (2/7, 1/3, 2/5, 2/3) have no exact binary representation, so the agreement
    held because a double has mantissa to spare rather than because the arithmetic was right.
    Doing it in integers makes it exact by construction instead.
    """
    if not -6 <= stage <= 6:
        raise ValueError(f"stat stage out of range: {stage}")
    return value * _STAGE_NUM[stage + 6] // _STAGE_DEN[stage + 6]


#: Accuracy-stage multipliers, indexed by ``clamp(6 + net, 0, 12)`` where ``net`` is the
#: attacker's accuracy stage minus the defender's evasion stage.
#:
#: **This is a TABLE, not the fraction, and that is the whole point of transcribing it.** The
#: accuracy stages do not share the stat-stage ratios above: the ROM reads
#: ``sHitChanceTable[13][2]`` (src/battle/battle_controller_player.c:2399-2413) and applies it as
#: ``hitChance = hitChance * n / d`` (:2490-2491), and two entries are not what the fraction
#: would give -- 3/7 is 42.86 but the table says **43**, and 3/8 is 37.5 but the table says
#: **36**. So the two stages either side of -5 are both wrong if computed, in opposite
#: directions.
#:
#: That was a live soundness bug, not a rounding nicety (clayton-957.27). A flipped accuracy
#: verdict predicts a hit where the game printed a miss, the turn contradicts, and the true seed
#: is eliminated -- and the Lugia plan's Flash x6 passes through -4 and -5 on consecutive turns
#: with the target attacking on each. Measured disagreement against the computed form: 1 roll in
#: 100 at -4 and at -5 for a 100-accuracy move, **2 in 100 at -5 for an 80-accuracy move**.
#:
#: The pairs are written the way the C writes them -- ``(1, 1)``, ``(2, 1)``, ``(133, 50)`` --
#: rather than normalised onto a common denominator, the same convention `_WEATHER_MULTIPLIERS`
#: follows, so a reader can diff this against the ROM line by line. The +2 and +5 rows are where
#: that matters least and is kept anyway: they differ from the fraction by one (157 vs 158, 252
#: vs 253) but cannot change a verdict, because anything at or above 100 always hits.
_ACCURACY_STAGE_TABLE: tuple[tuple[int, int], ...] = (
    (33, 100),      # -6
    (36, 100),      # -5
    (43, 100),      # -4
    (50, 100),      # -3
    (60, 100),      # -2
    (75, 100),      # -1
    (1, 1),         #  0
    (133, 100),     # +1
    (166, 100),     # +2
    (2, 1),         # +3
    (233, 100),     # +4
    (133, 50),      # +5
    (3, 1),         # +6
)


def apply_accuracy_stage(accuracy: int, net_stage: int) -> int:
    """`accuracy` after the combined accuracy/evasion stage, from the ROM's own table.

    `net_stage` is the attacker's accuracy stage minus the defender's evasion stage -- not evasion
    alone, since an accuracy drop on the attacker makes a 100%-accuracy move missable just as a
    raised evasion does. The ROM builds the same figure and clamps it the same way::

        attackerAccuracy = statChanges[STAT_ACC] - 6;
        targetEvasion    = 6 - statChanges[STAT_EVASION];
        var = 6 + targetEvasion + attackerAccuracy;   // clamped to 0..12

    Out-of-range stages are clamped rather than rejected, because the ROM clamps: Simple doubles
    a stage before this point and can push `var` past either end.

    The one place in the project that knows this table. `battle_compass.sim._effective_accuracy`
    and `metronome_compass.BattleContext.effective_accuracy` both delegate here -- they had
    independently computed the fraction, so they were independently wrong at the same two stages.
    """
    num, den = _ACCURACY_STAGE_TABLE[max(0, min(12, 6 + net_stage))]
    return accuracy * num // den


def item_key(name: str) -> str:
    """A held item's name reduced to a lookup key: lowercase, letters and digits only.

    **Every item table in this project is keyed on this**, because the in-game names are spelled
    inconsistently and players type them from memory. "BrightPowder" is one word on the item
    screen and "Bright Powder" is what most people write; "King's Rock" has an apostrophe that is
    easy to drop. Matching on `strip().lower()` alone meant the first of each pair worked and the
    second silently did not -- and for a held item, silently not matching is the failure mode that
    desynchronises a whole run.

    Checked for collisions before adopting: across all eight item tables plus the hazardous list,
    the only two raw names that reduce to the same key are ``never-melt ice`` and ``nevermeltice``
    -- which were already there as deliberate spellings of the SAME item, and are exactly the
    kind of alias this removes the need for.
    """
    return "".join(ch for ch in name.lower() if ch.isalnum())


#: Held items that cut the **attacker's** hit chance when the DEFENDER holds one, as
#: ``{name: percent}``. `HOLD_EFFECT_ACC_REDUCE` in the ROM's check.
#:
#: A multiplier on the hit chance, **not an evasion stage** -- which is the distinction that
#: matters: it does not go into `var`, so Simple does not double it and Unaware does not zero it.
#:
#: The percentages are the item's own ITEM_VAR_MODIFIER and live in a binary NARC rather than in
#: the decompiled source, so 10 is the documented Gen 4 figure for both and was NOT read out of
#: the ROM -- the same caveat as `TYPE_ITEM_MODIFIER_PERCENT`. The *ordering* below was read out
#: of the source.
ACCURACY_REDUCING_ITEMS: dict[str, int] = {
    item_key("BrightPowder"): 10, item_key("Lax Incense"): 10}

#: The mirror, when the ATTACKER holds one: `HOLD_EFFECT_ACCURACY_UP`, ``* (100 + mod) / 100``.
#:
#: Wide Lens only. **Zoom Lens is deliberately absent**: it is conditional on the holder moving
#: second, so it is state-dependent rather than a flat modifier, and the decomp's own TODO at
#: battle_controller_player.c:2532 notes that the constant for it (`HOLD_EFFECT_CRITRATE_UP_SLOWER`)
#: is mislabeled. Nothing in any planned party holds either; Wide Lens is here because it is free
#: and because leaving it out would make the modelled-items allowlist lie by omission.
ACCURACY_RAISING_ITEMS: dict[str, int] = {item_key("Wide Lens"): 10}


def apply_accuracy_items(accuracy: int, *, defender_item: str = "",
                         attacker_item: str = "") -> int:
    """`accuracy` after both held-item terms, in the ROM's order and arithmetic.

    Transcribed from `BattleSystem_CheckMoveHit`
    (src/battle/battle_controller_player.c:2520-2531)::

        item    = GetBattlerHeldItemEffect(ctx, battlerIdTarget);
        itemMod = GetHeldItemModifier(ctx, battlerIdTarget, 0);
        if (item == HOLD_EFFECT_ACC_REDUCE) hitChance = hitChance * (100 - itemMod) / 100;

        item    = GetBattlerHeldItemEffect(ctx, battlerIdAttacker);
        itemMod = GetHeldItemModifier(ctx, battlerIdAttacker, 0);
        if (item == HOLD_EFFECT_ACCURACY_UP) hitChance = hitChance * (100 + itemMod) / 100;

    **Applied AFTER the stage table, and the order is load-bearing**, because every step
    truncates. It disagrees with folding the item in first on 467 of the 1300 (base accuracy,
    stage) pairs -- including, for the moves this project actually rolls: Aeroblast at -6 (27 vs
    28), Screech at -1 (56 vs 57), Sing at -4 (20 vs 21). Defender's reduction before attacker's
    boost, for the same reason.

    (The obvious example does *not* diverge -- a 100-accuracy move under six Flashes is 29 either
    way -- which is exactly why the ordering is worth a test rather than an eyeball.)
    """
    reduce_pct = ACCURACY_REDUCING_ITEMS.get(item_key(defender_item))
    if reduce_pct is not None:
        accuracy = accuracy * (100 - reduce_pct) // 100
    raise_pct = ACCURACY_RAISING_ITEMS.get(item_key(attacker_item))
    if raise_pct is not None:
        accuracy = accuracy * (100 + raise_pct) // 100
    return accuracy


#: Gravity multiplies the final hit chance by ``10 / 6``, and it is applied **last** -- after the
#: stage table, after every weather and ability term, after both held-item terms and after the
#: Micle Berry (battle_controller_player.c:2544-2546). Every step truncates, so the position is
#: observable and not just tidiness. Written as the C writes it; it reduces exactly to 5/3.
GRAVITY_ACCURACY_NUM, GRAVITY_ACCURACY_DEN = 10, 6

#: Hustle cuts the accuracy of PHYSICAL moves to 80%, applied after the stage table and before
#: the held-item terms (battle_controller_player.c:2511-2513).
HUSTLE_ACCURACY_PERCENT = 80


#: Type-enhancing held items -> the type they boost, from the ROM's `sTypeEnhancingItems`
#: (src/battle/overlay_12_0224E4FC.c). All the Gen 4 classics; plates and incenses behave the
#: same way and can be added here as needed.
TYPE_ENHANCING_ITEMS: dict[str, str] = {item_key(k): v for k, v in {
    "Silk Scarf": "Normal",      "Charcoal": "Fire",         "Mystic Water": "Water",
    "Magnet": "Electric",        "Miracle Seed": "Grass",    "NeverMeltIce": "Ice",
    "Black Belt": "Fighting",    "Poison Barb": "Poison",    "Soft Sand": "Ground",
    "Sharp Beak": "Flying",      "TwistedSpoon": "Psychic",  "SilverPowder": "Bug",
    "Hard Stone": "Rock",        "Spell Tag": "Ghost",       "Dragon Fang": "Dragon",
    "BlackGlasses": "Dark",      "Metal Coat": "Steel",
}.items()}
#: Percent added by a matching type-enhancing item. The ROM reads this from the item's own
#: ITEM_VAR_MODIFIER, which lives in a binary NARC -- 20 is the documented Gen 4 value for every
#: item above, but unlike the ORDERING below it was not read out of the source.
TYPE_ITEM_MODIFIER_PERCENT = 20

#: Technician raises base power by half when the power is 60 or less (ABILITY_TECHNICIAN, and the
#: ROM checks the power *after* earlier power modifiers, not the raw base power).
TECHNICIAN_POWER_CAP = 60

# --- screens ---------------------------------------------------------------------------------
#
# Reflect halves PHYSICAL damage and Light Screen halves SPECIAL damage, and against a mixed
# attacker that asymmetry decides which one is worth bringing: Ho-Oh's Sacred Fire and Punishment
# are physical while only Ancient Power is special, so Reflect covers two of its three attacks and
# Light Screen covers the weakest one (notes/ho_oh_party.md sec 1.1).
#
# **A critical hit bypasses both** [verified]. Both branches in `CalcMoveDamage` are gated on
# ``crit == 1`` -- the no-crit multiplier:
#
#     if ((sideCondition & SIDE_CONDITION_REFLECT) && crit == 1 && ...) { dmg /= 2; }
#     if ((sideCondition & SIDE_CONDITION_LIGHT_SCREEN) && crit == 1 && ...) { dmg /= 2; }
#
# So a screen changes the common case and leaves the danger floor exactly where it was. That is
# the opposite of weather, whose Fire halving has no crit gate at all -- which makes rain the one
# reducer that can lower a floor and a screen one that never can.
#
# Position: the ROM halves for burn, then for the screen, then applies weather, all before the
# closing ``+ 2``. Every step truncates, so this is the one correct place for it.
SCREEN_DIVISOR = 2
#: Light Clay extends a screen from five turns to eight (`HOLD_EFFECT_EXTEND_SCREENS`). Lives here
#: beside the halving because the two are the whole of what a screen is.
SCREEN_TURNS = 5
SCREEN_TURNS_LIGHT_CLAY = 8
LIGHT_CLAY = "light clay"


def screen_turns(held_item: str) -> int:
    """How many turns a screen set by the holder of `held_item` lasts."""
    return (SCREEN_TURNS_LIGHT_CLAY if item_key(held_item) == item_key(LIGHT_CLAY)
            else SCREEN_TURNS)


# --- weather ---------------------------------------------------------------------------------
#
# Field weather, as the damage formula sees it. Rain halves Fire and multiplies Water by 1.5; sun
# does the reverse. Transcribed from `CalcMoveDamage` (src/battle/overlay_12_0224E4FC.c), which
# also halves Solar Beam in any weather that is not sun -- unmodelled here because no configured
# moveset has it.
WEATHER_NONE = ""
WEATHER_RAIN = "rain"
WEATHER_SUN = "sun"
WEATHERS = (WEATHER_NONE, WEATHER_RAIN, WEATHER_SUN)

#: ``weather -> {move type: (numerator, denominator)}``, in the ROM's own tenths-style arithmetic.
#: A halving is ``/ 2`` in the source rather than ``* 5 / 10``, and the two differ by truncation,
#: so the pairs are written the way the C is.
_WEATHER_MODIFIERS: dict[str, dict[str, tuple[int, int]]] = {
    WEATHER_RAIN: {"Fire": (1, 2), "Water": (15, 10)},
    WEATHER_SUN: {"Fire": (15, 10), "Water": (1, 2)},
}

#: Abilities that change the damage their holder **DEALS** and are NOT modelled here.
#:
#: Listed so an unmodelled one is reported rather than silently ignored -- the same discipline
#: `unsupported_reason` applies to moves, and for incoming damage an unnoticed modifier is
#: unsound, not merely imprecise.
UNMODELLED_ATTACKER_ABILITIES = frozenset({
    "huge power", "pure power", "hustle", "guts", "blaze", "torrent", "overgrow", "swarm",
    "sniper", "tinted lens", "rivalry", "slow start", "iron fist", "reckless", "sheer force",
    "adaptability", "mold breaker",
})

#: Abilities that change the damage their holder **TAKES** and are not modelled here.
#:
#: Separated from the attacker set because `unsupported_attacker_reason` is asked of the
#: ATTACKER, and a defensive ability there changes nothing. Conflating the two had a real cost:
#: once the facade started setting the target's ability from its encounter row, every Levitate
#: holder -- both Lati twins and Giratina Origin -- was reported as an unmodelled ATTACKER and
#: so dealt zero damage, which is not a conservative error but a wrong prediction
#: (clayton-6xu.3.4).
#:
#: Nothing reads this yet. It is the list a defender-side check would use, and it is here so the
#: split above is a statement about which side each ability acts on rather than a deletion.
UNMODELLED_DEFENDER_ABILITIES = frozenset({
    "flash fire", "thick fat", "heatproof", "solid rock", "filter", "dry skin", "water absorb",
    "volt absorb", "wonder guard", "marvel scale",
})

#: Both, for a caller that wants "any ability that touches damage".
UNMODELLED_DAMAGE_ABILITIES = UNMODELLED_ATTACKER_ABILITIES | UNMODELLED_DEFENDER_ABILITIES

#: Levitate is in NEITHER set, because it is fully modelled: in Gen 4 it grants immunity to
#: Ground moves and does nothing else whatsoever. So it is a type rule, not an unknown
#: multiplier -- see `_levitates`. Treating it as unmodelled was the bug above.
ABILITY_LEVITATE = "levitate"
TYPE_GROUND = "Ground"

#: Scrappy, and it is in neither UNMODELLED set for the same reason Levitate is in neither: it is
#: a type rule with no second half. `BattleSystem_ApplyTypeChart` tests
#: ``Battler_Ability(attacker) == ABILITY_SCRAPPY`` in the **same condition** as the defender's
#: Foresight volatile (battle_lib.c:2612-2616), so the two are one mechanic reached from opposite
#: sides, and modelling one without the other would be an asymmetry rather than a smaller scope.
#:
#: It mattered before anything was typed here: a Scrappy Kangaskhan is an ordinary thing to bring
#: and False Swipe is its obvious job, so the simulator predicted 0 damage against Giratina on a
#: turn the game dealt some -- a wrong prediction, which eliminates the true seed rather than
#: merely under-promising.
#:
#: Tested with `Battler_Ability` rather than `Battler_IgnorableAbility`, so unlike Levitate it is
#: **not** suppressed by Mold Breaker. Nothing models Mold Breaker anyway; noted because the two
#: lines sit three apart in the ROM and differ.
ABILITY_SCRAPPY = "scrappy"


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
    #: The defender's ability. Only Levitate is read, and only as a Ground immunity -- which is
    #: all Levitate is in Gen 4. Last, so every positional construction keeps working.
    ability: str = ""
    #: Whether a Foresight or Odor Sleuth has landed on this defender -- the ROM's
    #: `VOLATILE_CONDITION_FORESIGHT`. It removes the two Ghost immunities and nothing else
    #: (`types.FORESIGHT_REMOVABLE`); Levitate is checked before the table walk and survives it.
    #:
    #: On the DEFENDER because that is where the ROM keeps it, even though the move is used by the
    #: attacker: `battleMons[defender].statusVolatile`. The attacker-side route to the same
    #: removal is Scrappy -- see `ignores_ghost_immunity`.
    identified: bool = False


def _levitate_blocks(ability: str, move: Move) -> bool:
    """Levitate's whole rule, from an ability NAME rather than from a `Defender`.

    Split out so `is_type_immune` can ask the same question without a damage-calculation object:
    whether a move is blocked is about types and abilities, and nothing about it needs a stat
    spread.
    """
    return (ability or "").strip().lower() == ABILITY_LEVITATE \
        and move.type_name == TYPE_GROUND


def _levitates(defender: Defender, move: Move) -> bool:
    """Whether Levitate makes this move do nothing at all.

    A type rule rather than an unmodelled multiplier: Gen 4 Levitate grants immunity to Ground
    moves and has no other effect, so a Normal move against a Levitate holder is simply a normal
    move. Both Lati twins and Giratina Origin have it, and the Distortion World fight is the one
    where it matters -- its sibling in Turnback Cave has Pressure instead.
    """
    return _levitate_blocks(defender.ability, move)


def ignores_ghost_immunity(*, identified: bool = False, attacker_ability: str = "") -> bool:
    """Whether the Normal/Fighting-vs-Ghost rows do not apply to this pairing.

    Two routes to one answer, which is how the ROM has it -- both halves of a single condition at
    battle_lib.c:2612-2616: a Foresight or Odor Sleuth landed on the DEFENDER, or the ATTACKER has
    Scrappy.

    **Takes the two facts rather than the two battlers**, which is why the keywords are named
    after sides. The question is about one volatile flag and one ability, and demanding a
    `Defender` and an `Attacker` for it meant a caller that only wanted to know whether a move
    could do anything had to invent a stat spread to ask.
    """
    if identified:
        return True
    return (attacker_ability or "").strip().lower() == ABILITY_SCRAPPY


def is_type_immune(move: Move, types: tuple[str, ...] | list[str] | str, *,
                   defender_ability: str = "", identified: bool = False,
                   attacker_ability: str = "") -> bool:
    """Whether this pairing zeroes the move outright, so it deals nothing whatever it rolls.

    Both routes to zero in one answer, because a caller asking "will this move do anything" does
    not care which: the type chart (a 0.0 matchup against either of the defender's types) and
    Levitate, which the ROM keeps inside the same function as the chart. Foresight and Scrappy are
    folded in too, so this flips to False the moment one of them lands.

    Takes the defender's TYPES and the two relevant ability/flag facts rather than a `Defender`
    and an `Attacker`, for the reason `ignores_ghost_immunity` gives: none of this reads a stat.

    **A zeroed move is not a failed move**, and the distinction is the reason this is published
    rather than inferred from a damage figure of 0. It spends every roll, prints a hit, renders a
    ``h``/``!`` token and counts as successful -- so the turn is identical to a connecting one
    except that no HP moved. What the UI needs it for is saying *why* nothing happened, which is
    otherwise indistinguishable from a bug: against Giratina half of a Smeargle's moveset reads as
    broken until someone explains that Normal does not touch Ghost.

    Status moves are never immune -- they do not reach the type chart at all -- so they answer
    False rather than raising.
    """
    if move.category == CATEGORY_STATUS:
        return False
    if _levitate_blocks(defender_ability, move):
        return True
    return effectiveness(
        move.type_name, types,
        foresight=ignores_ghost_immunity(identified=identified,
                                         attacker_ability=attacker_ability)) == 0.0


def unsupported_reason(move: Move, *, power_known: bool = False) -> str | None:
    """Why this move's damage cannot be modelled yet, or None if it can.

    Callers must treat a reason as "do not filter on damage", never as "assume zero".

    `power_known` is for the variable-power moves. Power 1 in the table marks "work this out from
    state" rather than "unknown forever" -- Punishment is 60 + 20 per positive stage of its target
    -- so a caller that can supply the figure is not blocked by the absence of a fixed one.
    """
    if move.category == CATEGORY_PHYSICAL or move.category == CATEGORY_SPECIAL:
        if move.power <= 1 and not power_known:
            # power 1 marks fixed-damage and variable-power moves (Seismic Toss, Psywave,
            # Low Kick, Flail...), each of which needs its own rule.
            return f"{move.name} has no fixed base power"
        return None
    return f"{move.name} is a status move and deals no damage"


def effective_power(move: Move, attacker: Attacker, *, base: int | None = None) -> int:
    """Base power after the attacker's ability and held item.

    Order and arithmetic transcribed from the ROM (src/battle/overlay_12_0224E4FC.c): Technician
    first as ``power * 15 / 10``, then a matching type-enhancing item as
    ``power * (100 + mod) / 100``, both integer division. The order is not cosmetic -- for a
    Technician user holding Silk Scarf, False Swipe goes 40 -> 60 -> 72, where applying the item
    first would give 40 -> 48 -> 72 by luck here but differ elsewhere.
    """
    power = move.power if base is None else base
    ability = attacker.ability.strip().lower()
    if ability == "technician" and power <= TECHNICIAN_POWER_CAP:
        power = power * 15 // 10
    boosted = TYPE_ENHANCING_ITEMS.get(item_key(attacker.held_item))
    if boosted is not None and boosted == move.type_name:
        power = power * (100 + TYPE_ITEM_MODIFIER_PERCENT) // 100
    return power


def unsupported_attacker_reason(attacker: Attacker) -> str | None:
    """Why this attacker's damage cannot be modelled, or None.

    Mirrors `unsupported_reason` for moves: an ability we do not implement must be *reported*,
    never assumed inert. For incoming damage an unnoticed multiplier eliminates the true seed.
    """
    ability = attacker.ability.strip().lower()
    if ability in UNMODELLED_ATTACKER_ABILITIES:
        return f"{attacker.ability} changes damage and is not modelled"
    return None


def _apply_weather(value: int, move: Move, weather: str) -> int:
    """Rain's and sun's type multipliers, at the point `CalcMoveDamage` applies them.

    **Position is the whole point of this function.** The ROM applies weather near the END of
    `CalcMoveDamage` but still *before* its closing ``return dmg + 2`` -- so it lands before the
    ``+ 2``, before the critical multiplier (`DamageCalcDefault` applies that after the call
    returns), and before `ApplyDamageRange`, STAB and type effectiveness. Every one of those
    truncates, so "x1.5 somewhere in the chain" is not one modifier: moving it changes the
    number. A Hydro Pump that comes to 139 before the ``+ 2`` is 208 under rain and 211 if the
    boost is applied one step later, and that is a predicted HP that matches no candidate.

    Not modelled, and absent from every configured moveset: Solar Beam's halving outside sun, and
    the Cloud Nine / Air Lock abilities that switch weather off entirely.
    """
    modifiers = _WEATHER_MODIFIERS.get(weather)
    if not modifiers:
        return value
    pair = modifiers.get(move.type_name)
    if pair is None:
        return value
    numerator, denominator = pair
    return value * numerator // denominator


def damage(move: Move, attacker: Attacker, defender: Defender, *,
           roll: int = 100, critical: bool = False,
           weather: str = WEATHER_NONE, base_power: int | None = None,
           reflect: bool = False, light_screen: bool = False,
           type_chart: bool = True) -> int:
    """Damage for one hit, in HP.

    `roll` is the 85..100 damage roll.  Flooring happens at each step exactly as the game does;
    collapsing them changes the result for some inputs.

    `weather` is WEATHER_NONE / WEATHER_RAIN / WEATHER_SUN. It matters here far more than its
    size suggests: Rain Dance is in Suicune's and Lugia's movesets, and rain turns Hydro Pump
    into a move that can faint a Pokemon at full HP -- which is the whole reason fainting needed
    modelling at all.

    `reflect` and `light_screen` are the DEFENDER's side conditions. Each halves its own category
    and **both are ignored on a critical hit** -- see the screens section above. Callers pass them
    unconditionally; the crit gate is applied here so no caller has to remember it.

    `type_chart=False` stops after the damage range: **no STAB, no type effectiveness and no
    Levitate immunity.** It exists for exactly one move family and is not a tuning knob. STAB,
    effectiveness and Levitate all live in one ROM function, `BattleSystem_ApplyTypeChart`
    (battle_lib.c:2560 -- "Levitate is included in the type-effectiveness chart as a functional
    immunity to Ground-type attacks"), which is called from `CheckTypeChart` during TRY_MOVE.
    Future Sight's effect script sets `SYSCTL_IGNORE_IMMUNITIES` *before* TRY_MOVE runs, which
    skips that call outright -- and it has already banked its damage by then
    (`BtlCmd_TryFutureSight`, battle_script.c:6066, which calls `CalcMoveDamage` then
    `CalcDamageVariance` and stores the result). The fire turn two turns later applies the stored
    number directly. So a Future Sight is neither resisted nor super-effective nor blocked by an
    immunity, and it loses its own STAB as well -- which makes it weaker than its 80 base power
    reads against a neutral target and stronger than it reads against a Dark type.
    """
    reason = unsupported_reason(move, power_known=base_power is not None)
    if reason:
        raise ValueError(reason)
    if roll not in DAMAGE_ROLLS:
        raise ValueError(f"damage roll must be 85..100, got {roll}")
    if weather not in WEATHERS:
        raise ValueError(f"unknown weather {weather!r}; expected one of {WEATHERS}")
    if type_chart and _levitates(defender, move):
        # Immune, which is a real answer rather than a refusal: Levitate's whole effect in Gen 4
        # is "Ground moves do not hit me". Returned here rather than folded into the type chart
        # because the chart is about types and this is about an ability.
        return 0

    physical = move.category == CATEGORY_PHYSICAL
    attack = attacker.attack if physical else attacker.special_attack
    defence = defender.defence if physical else defender.special_defence
    defence_stage = defender.defence_stage if physical else defender.special_defence_stage
    attack_stage = attacker.attack_stage if physical else attacker.special_attack_stage
    # A crit ignores any stage that would REDUCE its damage -- the defender's raised defences and
    # the attacker's lowered offences -- while keeping those that would raise it.
    if not (critical and defence_stage > 0):
        defence = max(1, apply_stage(defence, defence_stage))
    if not (critical and attack_stage < 0):
        attack = max(1, apply_stage(attack, attack_stage))

    # The ROM's level term is INTEGER division -- `((level * 2 / 5) + 2)` in C -- so it differs
    # from a float form at any level where 2*level is not a multiple of 5 (63, 67, 71, 78...).
    level_term = (attacker.level * 2) // 5 + 2
    power = effective_power(move, attacker, base=base_power)

    # CalcMoveDamage, transcribed from src/battle/overlay_12_0224E4FC.c. Integer division at each
    # step, in this order -- `atk * power * levelterm`, then `/ def`, then `/ 50`:
    #
    #     dmg  = monAtk; dmg *= movePower; dmg *= ((level * 2 / 5) + 2);
    #     dmg /= monDef; dmg /= 50;  ...  return dmg + 2;
    #
    # The `+ 2` is split off from the expression above because the weather multiplier goes
    # BETWEEN them -- see `_apply_weather`. Collapsing them, as this did while there was no
    # weather term to fit in, left nowhere correct to put it.
    value = attack * power * level_term // defence // 50
    # Burn's halving sits here too, when it lands -- `battle_compass.sim` currently applies it to
    # the Attack stat before this call instead, which is where `CalcMoveDamage` reads it.
    if not critical:
        if physical and reflect:
            value //= SCREEN_DIVISOR
        elif not physical and light_screen:
            value //= SCREEN_DIVISOR
    value = _apply_weather(value, move, weather)
    value += 2

    # DamageCalcDefault applies the crit multiplier straight after CalcMoveDamage returns.
    if critical:
        value *= 2

    # ApplyDamageRange, then STAB, then type effectiveness -- IN THAT ORDER. This is the part an
    # earlier version had backwards: it applied STAB and type first and the roll last. The set of
    # results is not the same, because each step truncates -- verified against
    # data/battle_logs/test1.jsonl, where the two orders disagree on the third of five hits.
    value = _apply_damage_range(value, roll)
    if not type_chart:
        # Future Sight banks its damage before the type-chart stage runs at all. Stopping here
        # rather than multiplying by 1.0 twice: the two steps truncate, so "a multiplier of one"
        # and "the step did not happen" are the same number only by luck.
        return value
    value = _apply_stab(value, move, attacker)
    value = _apply_effectiveness(value, move, defender, attacker=attacker)
    return value


def _apply_damage_range(value: int, roll: int) -> int:
    """`ApplyDamageRange`: ``damage * roll / 100``, with a floor of 1.

    `roll` is the 85..100 multiplier. Note that the ROM derives it by SUBTRACTING the RNG value
    (``100 - rand % 16``), so a raw roll of 0 is 100% and 15 is 85%; callers that map an RNG
    value to a multiplier must do it that way round (see ``battle_compass.sim``).
    """
    if not value:
        return 0
    value = value * roll // 100
    return value or 1


def _apply_stab(value: int, move: Move, attacker: Attacker) -> int:
    """``damage * 15 / 10`` when the move matches one of the attacker's types.

    Integer, and applied AFTER the damage range (overlay_12_0224E4FC.c, the STAB block).
    """
    if move.type_name in attacker.types:
        return value * 15 // 10
    return value


def _apply_effectiveness(value: int, move: Move, defender: Defender, *,
                         attacker: Attacker | None = None) -> int:
    """Type effectiveness, applied once PER DEFENDER TYPE in tenths.

    The ROM does ``damage = DamageDivide(damage * typeEffectiveness, 10)`` for each of the
    defender's types in turn, where `typeEffectiveness` is a tenths figure (5, 10, 20) and
    `DamageDivide` truncates but never returns 0 for a nonzero input. Multiplying the two
    matchups together and dividing once is not the same thing: ``x * 5 / 10 * 5 / 10`` truncates
    twice, which is what the game does against a dual type resisting twice over.

    A Foresighted defender or a Scrappy attacker drops the two Ghost immunities before the walk
    starts (`ignores_ghost_immunity`). Nothing else about the walk changes -- in particular the
    per-type truncation is unaffected, because a removed row contributes no multiplier at all
    rather than a multiplier of one.
    """
    foresight = ignores_ghost_immunity(
        identified=defender.identified,
        attacker_ability="" if attacker is None else attacker.ability)
    for defending in defender.types:
        tenths = round(type_multiplier(move.type_name, defending, foresight=foresight) * 10)
        if tenths == 0:
            return 0                     # an immunity zeroes it outright
        if value == 0:
            return 0
        value = (value * tenths) // 10 or 1
    return value


def damage_spread(move: Move, attacker: Attacker, defender: Defender, *,
                  critical: bool = False, weather: str = WEATHER_NONE,
                  base_power: int | None = None,
                  reflect: bool = False, light_screen: bool = False,
                  type_chart: bool = True) -> dict[int, int]:
    """`roll` -> damage, for all sixteen rolls.

    This is what makes the sec 3.1 filter work: an observed HP change identifies the set of
    rolls consistent with it, and therefore constrains the RNG state.

    `type_chart` is passed straight through; see `damage`. Future Sight is the move that needs
    it, and it needs it here too -- a danger floor that priced a Future Sight with STAB and a
    crit it cannot have reported three times the real number.
    """
    return {roll: damage(move, attacker, defender, roll=roll, critical=critical,
                         weather=weather, base_power=base_power,
                         reflect=reflect, light_screen=light_screen,
                         type_chart=type_chart)
            for roll in DAMAGE_ROLLS}


def rolls_for_damage(observed: int, move: Move, attacker: Attacker, defender: Defender, *,
                     critical: bool = False, weather: str = WEATHER_NONE,
                     reflect: bool = False,
                     light_screen: bool = False) -> tuple[int, ...]:
    """Which damage rolls could have produced `observed`.

    Empty means no roll can — the seed, the stats, or this model is wrong.  Callers must
    surface that rather than silently discarding candidates (sec 3.1).
    """
    spread = damage_spread(move, attacker, defender, critical=critical, weather=weather,
                           reflect=reflect, light_screen=light_screen)
    return tuple(roll for roll, value in spread.items() if value == observed)


def damage_range(move: Move, attacker: Attacker, defender: Defender, *,
                 critical: bool = False, weather: str = WEATHER_NONE,
                 base_power: int | None = None,
                 reflect: bool = False, light_screen: bool = False,
                 type_chart: bool = True) -> tuple[int, int]:
    """(minimum, maximum) over the sixteen rolls."""
    values = damage_spread(move, attacker, defender, critical=critical,
                           weather=weather, base_power=base_power,
                           reflect=reflect, light_screen=light_screen,
                           type_chart=type_chart).values()
    return min(values), max(values)
