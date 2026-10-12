"""Known movesets for the static encounters Battle Compass can hunt.

Not derivable from anything already in the repo. Base stats are a property of the species, but a
moveset belongs to the *encounter*: the Bell Tower Suicune is Lv40 with these four moves in this
order, and a Suicune met any other way would differ. Slot order matters as much as membership --
it is what the ``E1``-``E4`` tokens refer to and what the wild move-selection roll indexes into
(sec 5.2 R4), so a reordered list would silently mis-simulate every turn.

Adding a target means adding its row here, its base stats via
``one-offs/populate_base_stats.py``, and confirming every one of its moves is in
``sim.MODELLED_TARGET_EFFECTS`` -- which `unsupported_moves` checks for you rather than leaving
to a reading of a list.

**Two of these encounters are version-split, and they split in OPPOSITE directions.** This
profile is SoulSilver, so Ho-Oh's row is the Lv70 one and Lugia's is the Lv45 one;
`VERSION_SPLIT_LEVELS` holds the other side of each so a player on HeartGold is told what they
are actually facing instead of being silently simulated against the wrong four moves.
"""
from __future__ import annotations

#: species key -> (level, moves in slot order). Levels are the encounter's, not a range.
STATIC_ENCOUNTERS: dict[str, tuple[int, tuple[str, ...]]] = {
    # HGSS Bell Tower, after the Burned Tower release. Roaming Suicune is the same set.
    # `WildBattle SPECIES_SUICUNE, 40, 0` with no version branch, so Lv40 in both versions
    # (files/fielddata/script/scr_seq/scr_seq_0024_D18R0102.s:247).
    "suicune": (40, ("Rain Dance", "Gust", "Aurora Beam", "Mist")),
    # HGSS Pewter City museum, the Enigma Stone event. `WildBattle <species>, 40, 0` with the
    # species version-gated (scr_seq_0750_T03.s:364-381): HeartGold gets Latios here and
    # SoulSilver gets Latias, with the OTHER twin roaming at Lv35.
    #
    # Derived from wotbl.narc rather than transcribed: entries are `(level << 9) | moveId` and
    # `InitBoxMonMoveset` keeps the last four learnable moves IN LEARN ORDER, which is exactly
    # the slot order E1-E4 and the wild selection roll depend on.
    #
    # Refresh is the reason this target wants SLEEP rather than paralysis: it sheds paralysis,
    # but it is self-targeting, so a sleeping Latias cannot use it -- and awake and unstatused it
    # cures nothing and simply fails (notes/battle_compass_next_targets.md sec 4b).
    "latias": (40, ("Water Sport", "Refresh", "Mist Ball", "Zen Headbutt")),
    "latios": (40, ("Protect", "Refresh", "Luster Purge", "Zen Headbutt")),
    # HGSS Bell Tower. The level is VERSION-SPLIT, and this row is **SoulSilver's**:
    # `GetGameVersion` then `Compare VAR_SPECIAL_RESULT, 7` / `GoToIfNe` picks Lv45, and the
    # fall-through picks Lv70 (scr_seq_0021_D17R0110.s:63-73). HeartGold's Lv45 Ho-Oh is a
    # DIFFERENT set -- Extrasensory / Sunny Day / Fire Blast / Sacred Fire -- so a HeartGold hunt
    # must not use this row. `encounter_level` is what catches that: the configured level is
    # cross-checked against it, so entering 45 here is reported rather than silently simulated
    # with the wrong four moves.
    #
    # Derived from wotbl.narc the same way as the Lati twins: `InitBoxMonMoveset` keeps the last
    # four learnable moves in LEARN order, which is the slot order E1-E4 depends on.
    "ho-oh": (70, ("Sacred Fire", "Punishment", "Ancient Power", "Safeguard")),
    # HGSS Whirl Islands. Version-split the OPPOSITE way round from Ho-Oh, which is the trap:
    # `GetGameVersion` then `Compare VAR_SPECIAL_RESULT, 7` / `GoToIfNe` sends HeartGold (7) to
    # Lv70 and the fall-through gives SoulSilver Lv45 (scr_seq_0104_D40R0107.s:75-85). So this
    # row is **SoulSilver's**, and HeartGold's Lv70 Lugia is a different set entirely --
    # Aeroblast / Punishment / Ancient Power / Safeguard, none of which this row can stand in
    # for. `encounter_level` is the cross-check that catches a player on the wrong version.
    #
    # Derived from wotbl.narc like the rows above: `InitBoxMonMoveset` keeps the last four
    # learnable moves in LEARN order, which is the slot order E1-E4 depends on.
    #
    # Aeroblast is why this row could not exist until clayton-957.2: it is effect 43, the
    # high-crit group, and `execute_move` read `CRIT_MODIFIERS[0]` unconditionally -- so the
    # simulator crit it at 1/16 against the game's 1/8 and was wrong about both the token and
    # the damage on 1.56% of turns. Inert rather than refused, which is exactly what
    # `unsupported_moves` exists to stop.
    #
    # Two things make this target *easier* than Suicune to identify, both from the moveset
    # rather than from the catch rate: Hydro Pump's accuracy 80 and Aeroblast's 95 mean it
    # separates RTC-second siblings on its own, where Suicune's set could not miss at all.
    "lugia": (45, ("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast")),
}

#: The other side of each version-split encounter, for the cross-check's error message. Not in
#: `STATIC_ENCOUNTERS` because nothing can simulate it yet either -- it is here so a player on
#: the wrong version is told what they are actually facing rather than just refused.
VERSION_SPLIT_LEVELS: dict[str, tuple[int, str]] = {
    "ho-oh": (45, "HeartGold's Lv45 Ho-Oh, which has a different moveset"),
    # The inverse of the row above, and worth stating as its own entry rather than as a note on
    # it: the two birds split in OPPOSITE directions, so "SoulSilver gets the Lv70 one" is true
    # of Ho-Oh and false of Lugia.
    "lugia": (70, "HeartGold's Lv70 Lugia, which has a different moveset"),
}


def unsupported_moves(species: str) -> tuple[tuple[str, str], str | None]:
    """``((move name, why), ...)`` for every move in this encounter's set the simulator cannot
    model, plus the same as one sentence.

    The check that stops "configured" from meaning "silently mis-simulated". `execute_move` has
    no notion of an unknown effect: an unrecognised status move is treated as having worked and
    changed nothing, and an unrecognised damaging move as plain damage. So a missing secondary is
    inert rather than refused -- and for the target's moves that is unsound, not imprecise,
    because an unnoticed modifier eliminates the true seed (``battle.damage``'s own warning).

    Deliberately keyed on the EFFECT id rather than the move name, so a new target that happens
    to reuse a modelled effect passes without anyone editing a list.
    """
    from claytonlib.battle.damage import unsupported_reason
    from claytonlib.battle_compass.sim import (
        MODELLED_TARGET_EFFECTS, VARIABLE_POWER_EFFECTS,
    )
    from claytonlib.moves import resolve_move

    problems: list[tuple[str, str]] = []
    for name in moveset(species):
        move = resolve_move(name)
        if move is None:
            problems.append((name, "is not in the move table at all"))
            continue
        if move.effect not in MODELLED_TARGET_EFFECTS:
            problems.append((name, f"effect {move.effect} is not modelled"))
            continue
        # `power_known` for a move whose power is computed from state: Punishment's power 1 in
        # the table means "work it out", not "we have no rule".
        reason = unsupported_reason(
            move, power_known=move.effect in VARIABLE_POWER_EFFECTS)
        # A status move "deals no damage" is the expected answer, not a gap.
        if reason is not None and "status move" not in reason:
            problems.append((name, reason))
    if not problems:
        return (), None
    listed = "; ".join(f"{name} ({why})" for name, why in problems)
    return tuple(problems), (
        f"{species} cannot be simulated yet -- {listed}. The simulator treats an unmodelled "
        f"effect as inert rather than refusing it, so running this would mis-predict every turn "
        f"it fires on and eliminate the true seed.")


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
