"""Known movesets for the static encounters Battle Compass can hunt.

Not derivable from anything already in the repo. Base stats are a property of the species, but a
moveset belongs to the *encounter*: the Bell Tower Suicune is Lv40 with these four moves in this
order, and a Suicune met any other way would differ. Slot order matters as much as membership --
it is what the ``E1``-``E4`` tokens refer to and what the wild move-selection roll indexes into
(sec 5.2 R4), so a reordered list would silently mis-simulate every turn.

**Keyed by ENCOUNTER, not by species** (clayton-957.35.4). For every single-venue target the two
coincide and the key simply is the species slug, which is why `resolve` takes either. They come
apart where the same species is met twice: Platinum's Giratina is Lv47 in the Distortion World
and Lv47 in Turnback Cave with a different forme, ability and base stats, so a species key could
not hold both and the level cross-check could not tell them apart.

Adding a target means adding its row here, its base stats via
``one-offs/populate_base_stats_from_rom.py``, and confirming every one of its moves is in
``sim.MODELLED_TARGET_EFFECTS`` -- which `unsupported_moves` checks for you rather than leaving
to a reading of a list.

**Rows carry the GAMES they exist in**, and that is what finally fixes the bug this module's old
docstring admitted to: it said outright "This profile is SoulSilver" and shipped SoulSilver's
rows, so a HeartGold player was offered them too. Ho-Oh and Lugia are version-split in OPPOSITE
directions, and only the SoulSilver side of each is on file; `VERSION_SPLIT_LEVELS` holds the
other so a player on HeartGold is told what they are actually facing instead of being simulated
against the wrong four moves. A profile with no game set is filtered by nothing -- see
`supported`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Encounter:
    """One encounter: where it is, what it is, and what it knows.

    The moveset and the level are the parts the simulator cannot do without. `ability` and
    `forme` exist because a species row cannot answer them for a forme-split target: Giratina is
    Pressure with one stat line in Turnback Cave and Levitate with another in the Distortion
    World, and `battle.stats.has_pressure` reading the species would be confidently wrong for
    one of the two -- which halves every PP budget the solver plans against.

    Terrain is deliberately NOT here. It is a property of the tile you stand on rather than of
    the encounter (`CalcTerrain`, pokeplatinum src/field_battle_data_transfer.c:467-494), so it
    lives on the Hunt where the player can say which tile they will be on.
    """
    #: Species slug, as `species_names.canonical_species_name` spells it.
    species: str
    #: The encounter's level. Not a range: a static encounter has one.
    level: int
    #: Moves in slot order -- the order E1-E4 and the selection roll depend on.
    moves: tuple[str, ...]
    #: Game keys this encounter exists in, as `claytonlib.games` spells them. Empty means every
    #: game, which is what a target met identically in all of them wants.
    games: tuple[str, ...] = ()
    #: The ability to simulate it with, or "" to take the species' slot-0 ability.
    ability: str = ""
    #: The `base_stats.json` key to take stats from, or "" for the species' own row. Set only
    #: for a forme whose stats differ from the species row.
    forme: str = ""
    #: Where the encounter is, for a message that can say which one it means.
    where: str = ""


#: encounter key -> `Encounter`. For a single-venue target the key IS the species slug, so
#: ``moveset("suicune")`` keeps working; a species met twice gets one venue-qualified key apiece.
ENCOUNTERS: dict[str, Encounter] = {
    # HGSS Bell Tower, after the Burned Tower release. Roaming Suicune is the same set.
    # `WildBattle SPECIES_SUICUNE, 40, 0` with no version branch, so Lv40 in both versions
    # (files/fielddata/script/scr_seq/scr_seq_0024_D18R0102.s:247).
    "suicune": Encounter(
        "suicune", 40, ("Rain Dance", "Gust", "Aurora Beam", "Mist"),
        games=("heartgold", "soulsilver"), where="the Bell Tower"),
    # HGSS Pewter City museum, the Enigma Stone event. `WildBattle <species>, 40, 0` with the
    # species version-gated (scr_seq_0750_T03.s:364-381): HeartGold gets Latios here and
    # SoulSilver gets Latias, with the OTHER twin roaming at Lv35. So these two rows are
    # version-split by SPECIES rather than by level, and the `games` tuple is what says so.
    #
    # Derived from wotbl.narc rather than transcribed: entries are `(level << 9) | moveId` and
    # `InitBoxMonMoveset` keeps the last four learnable moves IN LEARN ORDER, which is exactly
    # the slot order E1-E4 and the wild selection roll depend on.
    #
    # Refresh is the reason this target wants SLEEP rather than paralysis: it sheds paralysis,
    # but it is self-targeting, so a sleeping Latias cannot use it -- and awake and unstatused it
    # cures nothing and simply fails (notes/battle_compass_next_targets.md sec 4b).
    "latias": Encounter(
        "latias", 40, ("Water Sport", "Refresh", "Mist Ball", "Zen Headbutt"),
        games=("soulsilver",), where="the Pewter City museum"),
    "latios": Encounter(
        "latios", 40, ("Protect", "Refresh", "Luster Purge", "Zen Headbutt"),
        games=("heartgold",), where="the Pewter City museum"),
    # HGSS Bell Tower. The level is VERSION-SPLIT, and this row is **SoulSilver's**:
    # `GetGameVersion` then `Compare VAR_SPECIAL_RESULT, 7` / `GoToIfNe` picks Lv45, and the
    # fall-through picks Lv70 (scr_seq_0021_D17R0110.s:63-73). HeartGold's Lv45 Ho-Oh is a
    # DIFFERENT set -- Extrasensory / Sunny Day / Fire Blast / Sacred Fire -- so a HeartGold hunt
    # must not use this row. TWO things now catch that: `games` refuses the row outright on a
    # HeartGold profile, and `encounter_level` still cross-checks the configured level for a
    # profile with no game set at all.
    #
    # Derived from wotbl.narc the same way as the Lati twins: `InitBoxMonMoveset` keeps the last
    # four learnable moves in LEARN order, which is the slot order E1-E4 depends on.
    "ho-oh": Encounter(
        "ho-oh", 70, ("Sacred Fire", "Punishment", "Ancient Power", "Safeguard"),
        games=("soulsilver",), where="the Bell Tower"),
    # HGSS Whirl Islands. Version-split the OPPOSITE way round from Ho-Oh, which is the trap:
    # `GetGameVersion` then `Compare VAR_SPECIAL_RESULT, 7` / `GoToIfNe` sends HeartGold (7) to
    # Lv70 and the fall-through gives SoulSilver Lv45 (scr_seq_0104_D40R0107.s:75-85). So this
    # row is **SoulSilver's**, and HeartGold's Lv70 Lugia is a different set entirely --
    # Aeroblast / Punishment / Ancient Power / Safeguard, none of which this row can stand in
    # for.
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
    "lugia": Encounter(
        "lugia", 45, ("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast"),
        games=("soulsilver",), where="the Whirl Islands"),
    # Platinum, Newmoon Island, reached by the Member Card event: `StartLegendaryBattle
    # SPECIES_DARKRAI, 50` (res/field/scripts/scripts_newmoon_island_forest.s:44). Lv50, NOT the
    # 40 the unused roamer slot in field_roamer.c says -- the roamer never activates.
    #
    # Moveset from res/pokemon/darkrai/data.json's own `learnset.by_level`, which the complete
    # Platinum decomp exposes as JSON rather than as the packed wotbl.narc the HGSS rows had to
    # be unpacked from: Hypnosis (20), Faint Attack (29), Nightmare (38), Double Team (47) are
    # the last four learnable at 50, in learn order. Haze is 57, so it just misses.
    #
    # All four effects had to be modelled before this row could exist, the same bar Lugia's
    # Aeroblast had to clear: Hypnosis is the first STATUS move any target has had (effect 1),
    # Nightmare the first volatile residual (107), Double Team the first thing to degrade our own
    # accuracy from the target's side (16), and Faint Attack the first never-miss move (17).
    # Bad Dreams is modelled alongside them -- 1/8 of our max HP every turn we spend asleep,
    # which with Nightmare's quarter is 37.5% a turn (`sim.bad_dreams_tick`).
    "darkrai": Encounter(
        "darkrai", 50, ("Hypnosis", "Faint Attack", "Nightmare", "Double Team"),
        games=("platinum",), where="Newmoon Island"),
    # Platinum's Giratina, met TWICE, which is the case this table's key exists for. Both at
    # **Lv47**, so the level cross-check cannot tell them apart at all -- and they differ in
    # forme, ability and base stats, not merely in moveset:
    #
    #   `StartGiratinaOriginBattle SPECIES_GIRATINA, 47`  (scripts_distortion_world_giratina_room.s:69)
    #   `StartLegendaryBattle SPECIES_GIRATINA, 47`       (scripts_turnback_cave_giratina_room.s:35)
    #
    # Keyed by FORME rather than by venue, because the forme is both what distinguishes the two
    # fights mechanically and what a player types: "Origin Giratina" names the Distortion World
    # one unambiguously, and the key is then also the `base_stats.json` row its stats come from.
    # `resolve("giratina")` raises and names both, with their venues.
    #
    # The moveset is the SAME in both, because the learnsets agree through 47 -- the form's
    # `learnset.by_level` in res/pokemon/giratina/forms/origin/data.json is identical to the
    # species' up to Heal Block at 50. Last four learnable at 47, in learn order: Ominous
    # Wind(10), Ancient Power(20), Dragon Claw(30), Shadow Force(40).
    #
    # Two of the four were already modelled (140 twice, 0); Shadow Force is effect 272 and is the
    # first two-turn move on either side -- see `sim.EFFECT_SHADOW_FORCE` for the three things it
    # costs. The player also meets Giratina in the Distortion World during the story and can
    # *leave* it there; the Turnback Cave fight is the same Pokemon met again, which is why both
    # rows exist rather than one being the "real" one.
    "giratina-origin": Encounter(
        "giratina", 47, ("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force"),
        games=("platinum",), ability="Levitate", forme="giratina-origin",
        where="the Distortion World"),
    "giratina-altered": Encounter(
        "giratina", 47, ("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force"),
        games=("platinum",), ability="Pressure", forme="giratina-altered",
        where="Turnback Cave"),
}

#: The other side of each version-split encounter, for the cross-check's error message. Not in
#: `ENCOUNTERS` because nothing can simulate it yet either -- it is here so a player on the wrong
#: version is told what they are actually facing rather than just refused. Keyed by encounter key.
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


def encounter_key(name: str) -> str:
    """Normalise anything a caller might hold into an encounter key.

    Shared by every lookup here so that ``"Ho-Oh"``, ``"ho-oh"`` and ``" ho oh "`` cannot resolve
    differently depending on which function was asked.
    """
    return name.strip().lower().replace(" ", "-")


def resolve(name: str, game: str = "") -> tuple[str, Encounter]:
    """``(encounter key, row)`` for `name`, which may be an encounter key or a species slug.

    `game` is a game key (`claytonlib.games`). Its job is to keep a player from being simulated
    against another version's encounter: a HeartGold profile asking for Lugia must not silently
    get SoulSilver's Lv45 row. **An empty `game` filters nothing**, deliberately -- every profile
    written before the field existed has none, and refusing those would lock out every hunt that
    already works (the same choice `games.tool_refusal` makes).

    Raises `KeyError` for an unknown target, and for a species whose name is AMBIGUOUS in this
    game -- two venues, as Giratina has. Ambiguity is an error rather than a silent first-match
    because the two rows differ in the things the whole simulation rests on: ability, base stats
    and moveset.
    """
    key = encounter_key(name)
    rows = {k: row for k, row in ENCOUNTERS.items() if _in_game(row, game)}
    if key in rows:
        return key, rows[key]
    by_species = {k: row for k, row in rows.items() if row.species == key}
    if len(by_species) == 1:
        return next(iter(by_species.items()))
    if len(by_species) > 1:
        where = ", ".join(f"{k} ({row.where})" for k, row in sorted(by_species.items()))
        raise KeyError(
            f"{name!r} is met more than once and the two differ in more than their moveset; "
            f"say which: {where}")
    # Present but filtered out by the game: say that, rather than "no such target". The two
    # mistakes need different fixes -- one is a typo, the other is the wrong cartridge.
    elsewhere = [k for k, row in ENCOUNTERS.items() if k == key or row.species == key]
    if elsewhere and game:
        from claytonlib.games import game_name
        rowgames = sorted({g for k in elsewhere for g in ENCOUNTERS[k].games})
        listed = ", ".join(game_name(g) or g for g in rowgames)
        raise KeyError(
            f"{name!r} is not an encounter in {game_name(game) or game} -- it is "
            f"{listed}'s. Battle Compass simulates the target's turns, so the row it uses has "
            f"to be the one from the cartridge being played.")
    raise KeyError(
        f"no known encounter for {name!r}. Battle Compass simulates the target's turns, so its "
        f"moves and their slot order are required; add it to "
        f"battle_compass.targets.ENCOUNTERS.")


def _in_game(row: Encounter, game: str) -> bool:
    """Whether `row` exists in `game`. No game, or a row with no games, matches everything."""
    return not game or not row.games or game in row.games


def unsupported_moves(name: str, game: str = "") -> tuple[tuple[str, str], str | None]:
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
    for move_name in moveset(name, game):
        move = resolve_move(move_name)
        if move is None:
            problems.append((move_name, "is not in the move table at all"))
            continue
        if move.effect not in MODELLED_TARGET_EFFECTS:
            problems.append((move_name, f"effect {move.effect} is not modelled"))
            continue
        # `power_known` for a move whose power is computed from state: Punishment's power 1 in
        # the table means "work it out", not "we have no rule".
        reason = unsupported_reason(
            move, power_known=move.effect in VARIABLE_POWER_EFFECTS)
        # A status move "deals no damage" is the expected answer, not a gap.
        if reason is not None and "status move" not in reason:
            problems.append((move_name, reason))
    if not problems:
        return (), None
    listed = "; ".join(f"{move_name} ({why})" for move_name, why in problems)
    return tuple(problems), (
        f"{name} cannot be simulated yet -- {listed}. The simulator treats an unmodelled "
        f"effect as inert rather than refusing it, so running this would mis-predict every turn "
        f"it fires on and eliminate the true seed.")


def moveset(name: str, game: str = "") -> tuple[str, ...]:
    """The encounter moveset, in slot order. Raises for an unknown target.

    Raises rather than returning empty: the simulator needs the target's moves to advance a turn
    at all, so a missing moveset is a hard stop, not a degraded mode.
    """
    return resolve(name, game)[1].moves


def encounter_level(name: str, game: str = "") -> int:
    """The level this target is met at, for cross-checking the configured one."""
    return resolve(name, game)[1].level


def target_ability(name: str, game: str = "") -> str:
    """The ability to simulate this encounter with.

    Off the ROW, falling back to the species' slot-0 ability. The fallback is right for every
    target met once and wrong for exactly the case the row exists for: Giratina is Pressure in
    Turnback Cave and Levitate in the Distortion World, and `battle.stats.has_pressure` asked
    about the species would answer Pressure for both -- which halves every PP budget the solver
    plans against for the fight where it does not apply.
    """
    _, row = resolve(name, game)
    if row.ability:
        return row.ability
    from claytonlib.battle.stats import abilities
    return (abilities(row.species) or ("",))[0]


def stats_key(name: str, game: str = "") -> str:
    """Which `base_stats.json` row to take this encounter's stats and types from.

    The species' own row for everything met once, and the forme's row where the encounter names
    one. Separate from `Encounter.species` because the species is still what the player typed and
    what the Pokedex calls it -- only the STATS come from somewhere else.
    """
    _, row = resolve(name, game)
    return row.forme or row.species


def supported(game: str = "") -> tuple[str, ...]:
    """Encounter keys this game can hunt, sorted.

    An empty `game` returns everything, which is what a profile with no game set gets. See
    `resolve` for why that is permissive rather than refused.
    """
    return tuple(sorted(k for k, row in ENCOUNTERS.items() if _in_game(row, game)))
