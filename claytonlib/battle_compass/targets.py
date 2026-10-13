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

from dataclasses import dataclass

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


@dataclass(frozen=True)
class EncounterAccess:
    """What a party needs in order to **reach** an encounter, as opposed to beat it.

    A different kind of requirement from everything else in this module, and the reason it needs
    saying at all: the party you arrive with is the party you fight with. There is no PC in the
    Whirl Islands, so a Surf/Whirlpool carrier is not a travelling companion you leave at the
    door -- it occupies one of the six slots, and noticing that after a two-hour seed-targeting
    setup is the expensive way to find out.

    `field_moves` are checked against the party's movesets, and that is the whole of it.
    **Non-move prerequisites are deliberately NOT here** -- the Silver Wing, Ho-Oh's Rainbow Wing,
    Latias's Enigma Stone. A field move is worth checking because a party can be assembled
    wrongly and the mistake is invisible until you are standing at the water's edge; a key item
    you either have or cannot reach the encounter at all to begin with, so warning about it is
    noise on every single readiness check. They live in notes/lugia_love_ball.md, where a reader
    looks once, instead of in a warning a player reads forever.
    """
    #: Where the encounter is, for a message that tells the player why the moves are wanted.
    where: str
    #: Field moves some party member must know. Names as `resolve_move` spells them.
    field_moves: tuple[str, ...] = ()


#: species key -> what reaching that encounter requires.
#:
#: Only Lugia has field-move requirements on this profile, which is why this reads as a table
#: with one real entry: the Bell Tower and the Pewter museum are both walk-in, and a roamer is
#: wherever it happens to be. Absent means "nothing to check", not "unknown" -- a target with no
#: row produces no warnings rather than an empty one.
#: Slots in a Pokemon party. Named because the access warning does arithmetic with it, and a
#: hardcoded "one of your six" was wrong for every hunt configured with fewer -- it told a player
#: with four to drop somebody when they had two slots spare.
PARTY_SIZE = 6

ENCOUNTER_ACCESS: dict[str, EncounterAccess] = {
    "lugia": EncounterAccess(
        where="the Whirl Islands",
        # HM03 and HM05. Needed to get in and then to cross the whirlpools down to the chamber.
        #
        # Flash is NOT here. It lights the caves and the party happens to be carrying one for the
        # accuracy drops, but the Whirl Islands are navigable without it -- so requiring it would
        # warn falsely. The Silver Wing is not here either; see `EncounterAccess`.
        field_moves=("Surf", "Whirlpool")),
    # Ho-Oh needs the Rainbow Wing and Suicune the Clear Bell chain, both story flags rather than
    # moves, and the Bell Tower itself is walk-in. Latias needs the Enigma Stone, which was a
    # Mystery Gift distribution -- whether it is reachable at all on a given cartridge is a
    # real-world question (notes/battle_compass_next_targets.md sec 4F). None of those is a field
    # move, so none of them gets a row until something actually checks them.
}


def access_warnings(species: str, movesets: dict[str, list[str]],
                    party_species: dict[str, str] | None = None) -> list[str]:
    """Warnings about reaching `species`, given ``{pokemon name: move names}``.

    Advisory, never blocking, and deliberately so: the player may be carrying an HM mule the
    hunt's party list does not mention, or may simply already be standing in front of the
    encounter with a save ready to reload. A tool that refused to start on this would be wrong
    more often than it was right.

    Only field moves. A key item like the Silver Wing is not warned about: you either have it or
    you cannot reach the encounter to try, so the warning would fire forever and tell nobody
    anything. See `EncounterAccess`.

    `party_species` (``{pokemon name: species}``) is optional and turns the warning into
    something actionable: with it, the message can say which party members *could* learn a
    missing field move -- and, when the answer is none of them, say that instead of leaving the
    player to check six move pools by hand. For the Lugia party the answer really is none, which
    is the whole reason it is worth saying.

    Unknown target, or no row for it -> no warnings. The absence of a requirement and the absence
    of knowledge are not distinguished here on purpose, because every encounter this project
    supports is one or the other and conflating them costs nothing.
    """
    access = ENCOUNTER_ACCESS.get(species.strip().lower().replace(" ", "-"))
    if access is None:
        return []
    known = {move.strip().lower() for moves in movesets.values() for move in moves if move}
    out = []
    missing = [name for name in access.field_moves if name.lower() not in known]
    if missing:
        out.append(
            f"Nothing knows {_join(missing)}, which {access.where} needs. The carrier has to "
            f"travel with you \u2014 there is no PC down there.")
        carrier = _carrier_note(missing, party_species)
        # The room note only matters when a NEW Pokemon is needed. If somebody already in the
        # party can learn the move, the fix is to teach it -- "room for one more" would be
        # answering a question nobody asked.
        room = "" if (carrier.startswith("Can learn")) else _room_note(len(movesets))
        note = (carrier + room).strip()
        if note:
            out.append(note)
    return out


def _room_note(configured: int) -> str:
    """Whether a carrier needs to displace anybody, given how many are CONFIGURED.

    Two things this gets right that a hardcoded "one of your six" did not.

    **The arithmetic.** A hunt configured with four has two slots spare, so nothing has to be
    dropped -- telling that player to drop somebody is advice that is simply false.

    **And the hunt party is not the game party.** This only ever sees what the hunt lists, and a
    player may well be walking in with a Lapras in a slot Battle Compass was never told about.
    So the wording says the carrier need not *displace* anything rather than claiming a slot is
    empty -- which would assert something this function cannot know. The caveat itself stays in
    `access_warnings`'s docstring instead of in the message: it is true of every warning here,
    and a sentence the player reads on every readiness check should not spend its length on it.
    """
    if configured == 0:
        return ""
    if configured < PARTY_SIZE:
        return f" Room for one: {configured} of {PARTY_SIZE} listed."
    return f" All {PARTY_SIZE} are listed, so one has to make room."


def _carrier_note(missing: list[str], party_species: dict[str, str] | None,
                  configured: int = PARTY_SIZE) -> str:
    """" Who could learn `missing`", appended to the field-move warning, or "" if unknown.

    Silent rather than speculative when the data is thin. `can_learn_hm` returns None for a
    species whose move pool nothing has recorded, and a Pokemon in that state is neither
    suggested nor ruled out -- saying "none of your party can carry this" on the strength of
    missing data would send a player to the Game Corner for a Pokemon they already own.
    """
    if not party_species:
        return ""
    from claytonlib.battle.stats import can_learn_hm

    able: dict[str, list[str]] = {}
    unknown = False
    for pokemon, species_name in party_species.items():
        if not species_name:
            unknown = True
            continue
        for move in missing:
            try:
                verdict = can_learn_hm(species_name, move)
            except KeyError:                 # a species base_stats.json has never heard of
                unknown = True
                continue
            if verdict is None:
                unknown = True
            elif verdict:
                able.setdefault(pokemon, []).append(move)

    if able:
        listed = "; ".join(f"{who} ({_join(moves, 'and')})" for who, moves in sorted(able.items()))
        return f"Can learn: {listed}."
    if unknown:
        return ""
    which = "either move" if len(missing) == 2 else (
        _join(missing) if len(missing) == 1 else "any of them")
    # No slot advice here: `_room_note` says whether anything has to make room, and saying it
    # twice got it wrong twice for a four-member hunt.
    return f"None of your party can learn {which}."


def _join(names: list[str], conjunction: str = "or") -> str:
    """``"Surf"`` / ``"Surf or Whirlpool"`` / ``"Surf, Whirlpool or Dive"``.

    The conjunction is a parameter because the two call sites mean opposite things: "nobody knows
    Surf OR Whirlpool" is a disjunction over what is missing, while "Gyarados can learn Surf AND
    Whirlpool" is a conjunction over what it covers. Reading the second as a choice would suggest
    a second carrier is still needed.
    """
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} {conjunction} {names[-1]}"


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
