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
    #: True for a ROAMER, which is a different kind of encounter rather than a harder one: it is
    #: driven by the trainer AI (5 selection rolls where a wild spends 1), it flees unless trapped
    #: at action-selection time, and its HP, status and spread come out of the save rather than
    #: being generated when the battle starts (notes/roamers.md sec 2). Every one of those
    #: changes the simulation, so the flag belongs on the encounter and not on the Hunt -- a
    #: player cannot configure Cresselia into being static.
    roamer: bool = False


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
    # Platinum, Stark Mountain's innermost room, after Buck takes the Magma Stone:
    # `StartLegendaryBattle SPECIES_HEATRAN, 50` (res/field/scripts/scripts_stark_mountain_room_3.s:83).
    #
    # Catch rate 3, Fire/Steel, Flash Fire, base 91/90/106/77/130/106 -- and a GENDER, 50/50,
    # which makes it the first configured target that has one at all. Nothing reads that yet:
    # the Love Ball is the only mechanic that would, and Platinum has no apricorn balls.
    #
    # Moveset at Lv50 from its own `learnset.by_level`: Metal Sound(25), Crunch(33), Scary
    # Face(41), Lava Plume(49). Three of its earlier moves are pushed out, and two of those are
    # strokes of luck -- Fire Fang(17) is effect 273 and unmodelled, and Ancient Power(1) would
    # have given it the all-stats boost that makes Ho-Oh's Speed a problem.
    #
    # Two things make this target different in kind from the others. **Its drops are two stages
    # at a time**: Scary Face takes two Speed stages off US, which can flip turn order outright,
    # and the no-speed-tie guarantee is what keeps ties out of the search. And **half its
    # moveset can miss** -- Metal Sound at 85 and Scary Face at 90 -- so it separates RTC-second
    # siblings on its own, the way Lugia does and Suicune cannot.
    #
    # Flash Fire is the hazard, and it is about OUR party rather than about the fight: a Fire
    # move thrown at it is absorbed AND raises its own Fire power by half, so the Lava Plume
    # afterwards hits harder than anything predicted. `sim.ABSORBED_MOVE_TYPES` refuses the move
    # rather than approximating it. The mirror is worth knowing too: Metal Sound is one of the
    # twelve SOUND moves, so a Soundproof party member (an Electrode, a Whismur) blocks it
    # outright -- `sim.SOUND_MOVES`.
    "heatran": Encounter(
        "heatran", 50, ("Metal Sound", "Crunch", "Scary Face", "Lava Plume"),
        games=("platinum",), where="Stark Mountain"),
    # Platinum's lake trio, two thirds of it: `StartLegendaryBattle SPECIES_UXIE, 50`
    # (res/field/scripts/scripts_acuity_cavern.s:33) and `SPECIES_AZELF, 50`
    # (scripts_valor_cavern.s:47). **Mesprit has no row and cannot have one** -- Platinum makes it
    # a ROAMER, so it is met through `field_roamer` and never through a legendary-battle script,
    # which is why only two of the three are here.
    #
    # Both are Lv50, pure Psychic, Levitate, catch rate 3 and genderless, so the Phase 2 catch
    # maths is Suicune's and Giratina's unchanged. They differ in exactly one way that matters,
    # and it is their stat spreads: Uxie is 75/75/130/75/130/95 and Azelf 75/125/70/125/70/115.
    # Uxie is the gentlest target on this list and Azelf one of the nastiest.
    #
    # The two movesets are the last four learnable at 50 from each one's own `learnset.by_level`,
    # in learn order. They share two slots:
    #
    #   Uxie   Swift(21), Yawn(31), Future Sight(36), Amnesia(46)
    #   Azelf  Swift(21), Uproar(31), Future Sight(36), Nasty Plot(46)
    #
    # Five effects had to be modelled before either row could exist, and three of them are firsts:
    #
    # * **Yawn (187)** is the first delayed status either way round -- it makes US drowsy and the
    #   sleep lands at the end of the turn AFTER it, with its duration roll spent then rather than
    #   at use (`sim._tick_drowsy`).
    # * **Future Sight (148)** is the first move whose damage is BANKED. One roll at use, nothing
    #   else -- no crit, no accuracy -- and the hit check comes two turns later at end of turn.
    #   Three consequences worth knowing: it is neither resisted nor super-effective nor blocked
    #   by an immunity and gets no STAB either (`battle.damage.damage`'s ``type_chart``); a switch
    #   does not dodge it, because the ROM keys it to the battler POSITION; and its 90 accuracy is
    #   the only sub-100 event in either moveset, which makes it the ONLY thing either target
    #   offers for separating RTC-second siblings -- and not much of one. Measured by
    #   notes/seed_separation.md's method, a 90-accuracy check flips its verdict between siblings
    #   17.9% of the time, against 49.5% for a Sing of ours and 44.5% for a ball's shake check;
    #   and it only fires on about one turn in four. So both of these targets are Suicune's case
    #   rather than Lugia's: the second axis has to come from our own side.
    # * **Uproar (159)** is the first multi-turn lock that attacks every turn. It runs 3-6 turns,
    #   and while it runs Azelf spends no move-selection roll at all. It **forbids sleep
    #   outright** for its duration and wakes anything already asleep, so a sleep-based plan
    #   against Azelf is not merely risky, it is refused by the game -- and a Soundproof party
    #   member (an Electrode, a Whismur) blanks the move whole, lock included, which takes that
    #   ban away with it.
    #
    #   It gives the RUN no information, which is worth stating because the opposite is the
    #   natural guess: its duration roll is ``% 4`` and 4 divides 256, so two seeds one RTC
    #   second apart roll the SAME length every time (notes/seed_separation.md's blindness rule).
    #   What it does instead is take information away -- no selection roll for 3-6 turns, and no
    #   sleep move to probe with.
    # * **Nasty Plot (53)** and **Amnesia (54)** are plain self-raises of +2, reached through
    #   `sim.PRIMARY_SELF_RAISES` alongside Double Team's evasion. Amnesia is close to harmless
    #   against a physical chipper; Nasty Plot DOUBLES Azelf's special attack, and off base 125
    #   that turns a 60-power Swift into a real threat.
    #
    # Swift is effect 17, which Darkrai's Faint Attack already modelled: accuracy 0, so it never
    # misses and spends no accuracy roll. Note it is SPECIAL in Gen 4.
    #
    # Two strokes of luck in the level window, both on the moves it pushes out: Extrasensory(51)
    # just misses on both, and so do Uxie's Flail(61) and Azelf's Last Resort(61) and
    # Explosion(76) -- an Explosion against a 1 HP target we are trying to catch would end the
    # run. Rest(1) and Confusion(1) are pushed out from below, and Rest is the one that matters:
    # it would heal off every False Swipe and make the chip phase unwinnable.
    "uxie": Encounter(
        "uxie", 50, ("Swift", "Yawn", "Future Sight", "Amnesia"),
        games=("platinum",), where="Acuity Cavern"),
    "azelf": Encounter(
        "azelf", 50, ("Swift", "Uproar", "Future Sight", "Nasty Plot"),
        games=("platinum",), where="Valor Cavern"),
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
    # Platinum's roaming Cresselia -- the FIRST ROAMER, and the gentlest target on this table
    # (notes/roamers.md sec 5). `ActivateRoamingPokemon ROAMING_SLOT_CRESSELIA`
    # (res/field/scripts/scripts_fullmoon_island_forest.s:28) starts the roam, and
    # `case ROAMING_SLOT_CRESSELIA: species = SPECIES_CRESSELIA; level = 50`
    # (src/roaming_pokemon.c:259-261) is where the level comes from -- so the level is a property
    # of the SLOT rather than of a battle script, which is why there is no `WildBattle` line to
    # cite for it.
    #
    # `where` is deliberately vague because a roamer has no venue: it is wherever the thing
    # currently is, which is what makes the encounter unroutable in the first place.
    #
    # Last four learnable at 50, in learn order, from res/pokemon/cresselia/data.json's
    # `learnset.by_level` (1 Confusion, 1 Double Team, 11 Safeguard, 20 Mist, 29 Aurora Beam,
    # 38 Future Sight, 47 Slash, 57 Moonlight):
    #
    #   Mist(46), Aurora Beam(68), Future Sight(148), Slash(43)
    #
    # **All four effects were already modelled** -- 46 and 68 are Suicune's, 148 is Uxie's and
    # Azelf's, 43 is Lugia's Aeroblast -- so this row needed no new target effects, which is most
    # of why it is the first roamer rather than Raikou (clayton-957.35.6 lists what those need).
    #
    # The level window is kind in both directions, and both edges matter:
    #
    # * **Safeguard(11) is pushed out from below**, so sleep lands. A target that could raise one
    #   would block the prep encounter's whole point.
    # * **Moonlight(57) and Psychic(93) are pushed out from above.** Moonlight is the Rest of this
    #   matchup: it would heal off every False Swipe and make the chip phase unwinnable.
    #
    # And there is no Roar, which is what keeps clayton-957.35.5 (Ingrain) and .7 (the
    # replacement-selection roll) off this target's path entirely.
    #
    # Future Sight's accuracy 90 is worth noting as an asset rather than a hazard: it is a real
    # sub-100 verdict, which is what separates RTC-second siblings (notes/seed_separation.md), and
    # a roamer hunt opens with a window far wider than a static hunt's.
    "cresselia": Encounter(
        "cresselia", 50, ("Mist", "Aurora Beam", "Future Sight", "Slash"),
        games=("platinum",), roamer=True, where="roaming Sinnoh"),
    # Platinum's roaming **Mesprit**, and the one target on this table whose row is confirmed by a
    # recording rather than only by a learnset: data/battle_logs/mesprit.jsonl reports
    # ``moves: [129, 381, 248, 204]`` for it, which is Swift / Lucky Chant / Future Sight / Charm
    # in that order -- an exact match for "the last four learnable at 50, in learn order", and the
    # first empirical confirmation of that rule for a ROAMER rather than a legendary-battle script.
    #
    # `ActivateRoamingPokemon ROAMING_SLOT_MESPRIT` is in scripts_verity_cavern.s; the level comes
    # from the slot (`case ROAMING_SLOT_MESPRIT: species = SPECIES_MESPRIT; level = 50`,
    # src/roaming_pokemon.c:254-257), which is why there is no `WildBattle` line to cite.
    #
    # **notes/platinum.md section 15 said Mesprit "has no row and cannot have one"**, and that was
    # true of a table that could only describe static encounters: Platinum makes it a roamer, so it
    # is never met through a legendary-battle script. With `roamer` on `Encounter` it can, and the
    # lake trio is complete.
    #
    # 80/105/105/105/105/80, pure Psychic, Levitate, catch rate 3 and genderless -- so the ball
    # maths is Cresselia's (Fast x1 off base Speed 80, Love x1 with no gender) and the Timer Ball
    # is again the answer.
    #
    # Last four learnable at 50, in learn order, from res/pokemon/mesprit/data.json (1 Rest,
    # 1 Confusion, 6 Imprison, 16 Protect, 21 Swift, 31 Lucky Chant, 36 Future Sight, 46 Charm,
    # 51 Extrasensory):
    #
    #   Swift(17), Lucky Chant(240), Future Sight(148), Charm(58)
    #
    # The level window is kind at both edges again, and this time the lower one is the one that
    # matters most: **Rest(1) is pushed out from below**, and a Rest would heal off every False
    # Swipe and make the chip phase unwinnable. **Extrasensory(51) is pushed out from above** by a
    # single level, which is the hardest-hitting move in the list.
    #
    # Two effects were new for this row and both were measured off the same recordings:
    # Lucky Chant (240, no crits against it for five turns, and the crit roll is STILL SPENT) and
    # Charm (58, two stages off our Attack, which is the chip phase slowing rather than failing).
    # Charm's accuracy 100 also makes it the only move here that can miss, which is worth having:
    # Swift is accuracy 0 and Lucky Chant has no roll of its own.
    "mesprit": Encounter(
        "mesprit", 50, ("Swift", "Lucky Chant", "Future Sight", "Charm"),
        games=("platinum",), roamer=True, where="roaming Sinnoh"),
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


def chip_warnings(species: str, movesets: "dict[str, list]",
                  our_abilities: "dict[str, str] | None" = None,
                  game: str = "") -> list[str]:
    """Warnings about being able to DAMAGE `species`, given ``{pokemon name: Moves}``.

    The sibling of `access_warnings`, and the same shape for the same reason: both answer a
    question about the party that is only worth answering *before* the encounter. That one asks
    whether the party can reach the fight; this one asks whether it can win the half of it that
    comes before a ball.

    **Why it exists.** Phase 1 needs the target on 1 HP and False Swipe is the only move that can
    safely put it there (effect 101's floor). False Swipe is Normal, so against a Ghost target it
    does *nothing* — and the player found that out after hitting the seed, in an interview that
    showed a hit marker and an unmoved HP bar. The immunity is removable (a Foresight, an Odor
    Sleuth, or a Scrappy attacker), which is exactly why the warning is worth giving: it names a
    fix that costs one party slot, decided before the run rather than during it.

    **Advisory, never blocking**, like every other warning in this module. Two reasons, and the
    second is the one that matters: the hunt's party list is not necessarily the game party, and a
    player may knowingly intend to chip with something this cannot price (a fixed-damage move, a
    Pokemon the hunt does not list). A tool that refused to start on this would be wrong more
    often than right.

    `our_abilities` (``{pokemon name: ability}``) is optional and is read for Scrappy alone — the
    attacker-side route to the same removal (`battle.damage.ignores_ghost_immunity`). Without it a
    Scrappy Kangaskhan would be warned about when it is in fact the answer.

    **The Foresight does NOT have to be on the False Swipe user.** [verified in game, by Testare]
    The identified status is a volatile on the TARGET, not on whoever applied it
    (`subscript_foresight.s` sets it on ``BTLSCR_DEFENDER``), so one Pokemon can Odor Sleuth and
    another can come in and chip — and a wild target never leaves the field, so it is bought once
    and lasts the battle.

    This is called out because the opposite is the natural assumption, and acting on it costs a
    party slot: it is what makes "``use Odor Sleuth (Stantler) first``" a legitimate suggestion
    even when Stantler is not the chipper, so this function names ANY carrier in the party rather
    than only the one holding the False Swipe. It was briefly believed to work the other way and
    an in-game test settled it — Foresight with one Pokemon, switch, False Swipe with another,
    damage dealt. The two departure paths in the ROM agree: `BattleSystem_UpdateAfterSwitch` and
    `BattleSystem_CleanupFaintedMon` (battle_lib.c:2040, 2155) clear, from *other* battlers, only
    Mean Look, Lock On, Attract and Bind — the four that record a source — and the volatile
    stores none, so there is nothing for the game to match on (clayton-957.26.5).

    Unknown target, or no row for it -> no warnings, as `access_warnings` has it.
    """
    from claytonlib.battle.damage import is_type_immune
    from claytonlib.battle_compass.sim import EFFECT_FORESIGHT, FALSE_SWIPE_EFFECT
    from claytonlib.moves import CATEGORY_STATUS
    from claytonlib.species_names import display_species_name

    try:
        _, row = resolve(species, game)
        types = target_types(species, game)
        ability = target_ability(species, game)
    except (KeyError, ValueError):
        # KeyError is the documented "no row for it". ValueError is the narrower case of a
        # profile holding a game string this build does not know -- `resolve` raises it while
        # BUILDING its own KeyError message, through `game_name`. Either way the honest answer is
        # no advice: a misconfigured game must not take the whole readiness panel down with it.
        return []

    abilities = our_abilities or {}
    #: The Pokedex name, taken off the row rather than off the encounter key -- which for a
    #: forme-split target is the difference between "Giratina" and "Giratina-Origin" in the middle
    #: of a sentence. The forme is not worth naming here anyway: both share a typing, and this
    #: warning is about typing.
    named = display_species_name(row.species) or row.species

    def blocked(move, holder: str, *, identified: bool) -> bool:
        return is_type_immune(move, types, defender_ability=ability, identified=identified,
                              attacker_ability=abilities.get(holder, ""))

    #: Who could lift a Ghost immunity, as ``(holder, move name)``. A list because naming the
    #: holder is what makes the advice actionable -- "use Odor Sleuth" is a move, "use Odor Sleuth
    #: (Smeargle)" is a turn.
    identifiers = [(holder, move.name)
                   for holder, moves in movesets.items() for move in moves
                   if move is not None and move.effect == EFFECT_FORESIGHT]
    fix = (f"use {identifiers[0][1]} ({identifiers[0][0]}) first"
           if identifiers else
           "add Foresight or Odor Sleuth to the party, or bring a Scrappy attacker")

    out: list[str] = []
    for holder, moves in movesets.items():
        attacks = [m for m in moves if m is not None and m.category != CATEGORY_STATUS]
        swipes = [m for m in attacks if m.effect == FALSE_SWIPE_EFFECT]

        # The specific case first, because it is the one with a one-turn fix and the one the whole
        # chip phase rests on.
        for move in swipes:
            if not blocked(move, holder, identified=False):
                continue
            if blocked(move, holder, identified=True):
                # Not the Ghost immunity, so no Foresight would help. Unreachable with a
                # Normal-typed False Swipe -- Normal is zeroed by nothing but Ghost -- and said
                # plainly anyway rather than assumed, since the test is free and a Sketched
                # effect-101 move of another type would land here.
                out.append(
                    f"{holder}'s {move.name} cannot touch {named} at all — its typing blocks it "
                    f"and identifying it would not change that.")
            else:
                out.append(
                    f"{holder}'s {move.name} does nothing to {named} until it is identified "
                    f"({'/'.join(types)} blocks Normal and Fighting) — {fix}.")

        # ...then the general one, for a Pokemon whose whole attacking half is blocked. Skipped
        # where a False Swipe above has already spoken for it, so one problem is not reported
        # twice. A Pokemon with no attacks at all is not reported either: a dedicated paralyzer or
        # a Flash mule is a legitimate party member, not a coverage gap.
        if swipes or not attacks:
            continue
        if any(not blocked(move, holder, identified=False) for move in attacks):
            continue
        if any(not blocked(move, holder, identified=True) for move in attacks):
            out.append(
                f"Nothing {holder} carries can damage {named} until it is identified — {fix}.")
        else:
            out.append(f"Nothing {holder} carries can damage {named}: every attack it has is "
                       f"blocked by {named}'s typing"
                       + (f" or {ability}." if ability else "."))
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


def target_types(name: str, game: str = "") -> tuple[str, ...]:
    """This encounter's types, from the same row its stats come from.

    The sibling of `target_ability`, and keyed the same way -- through `stats_key`, so a
    forme-split target answers for the forme it is actually met as. That matters here for the
    same reason it matters for stats: Giratina Origin and Altered happen to share a typing, but
    nothing about the lookup should depend on that holding.
    """
    from claytonlib.battle.stats import species as species_row

    return tuple(species_row(stats_key(name, game))["types"])


def stats_key(name: str, game: str = "") -> str:
    """Which `base_stats.json` row to take this encounter's stats and types from.

    The species' own row for everything met once, and the forme's row where the encounter names
    one. Separate from `Encounter.species` because the species is still what the player typed and
    what the Pokedex calls it -- only the STATS come from somewhere else.
    """
    _, row = resolve(name, game)
    return row.forme or row.species


#: Effect 106 -- Mean Look, Block and Spider Web. The **pure** traps: no damage, no duration, and
#: the only ones `FleeCommand` honours that we can apply on purpose. Keyed by effect rather than by
#: name so all three count, and so a fourth would count for free.
PURE_TRAP_EFFECT = 106

#: Effect 42 (Bind, Wrap, Fire Spin, Clamp, Sand Tomb, Magma Storm) and 261 (Whirlpool) -- the
#: partial traps. They set the same ``VOLATILE_CONDITION_BIND`` the roamer AI and `FleeCommand`
#: both accept, so they really do hold it... and they are useless to us twice over: the residual
#: is 1/16 per turn, which kills the 1 HP target the whole run exists to catch, and neither effect
#: is in `sim.MODELLED_OUR_EFFECTS`, so a party carrying one is refused before it gets this far.
#: Named so the warning can say that instead of staying silent about a move that looks like the
#: answer.
PARTIAL_TRAP_EFFECTS = frozenset({42, 261})

#: What a Choice Scarf multiplies Speed by, as the ROM's integer pair (`* 15 / 10`). Here rather
#: than imported from `battle.readiness` because this module only ever asks the hypothetical --
#: "would a scarf make this one fast enough" -- and never applies one.
SCARF_NUMERATOR, SCARF_DENOMINATOR = 15, 10


@dataclass(frozen=True)
class TrapCandidate:
    """One party member, as the trap check needs to see it."""
    name: str
    ability: str = ""
    #: Move names, as `resolve_move` spells them.
    moves: tuple[str, ...] = ()
    #: Effective Speed INCLUDING whatever it is holding -- the caller has already applied
    #: `readiness.speed_after_item`, because that is what it does for the speed checks anyway.
    speed: int = 0
    held_item: str = ""


@dataclass(frozen=True)
class TrapCheck:
    """Whether this member could hold a roamer, and if not, what is missing."""
    name: str
    traps: bool
    #: What would do it -- an ability name or a move name. Empty when nothing would.
    how: str = ""
    #: What is wrong, in a sentence. Empty when nothing is.
    problem: str = ""
    #: True when a Choice Scarf is the whole difference. Separated from `problem` because it is
    #: the one failure with a one-item fix, and the fix has no downside here: a scarfed trapper
    #: locks into its trapping move, and locking into Mean Look costs nothing once the trap is up
    #: -- balls, revives and items are bag actions, so the run continues normally.
    scarf_would_fix: bool = False
    #: True when the verdict could not be reached rather than coming back negative -- a Speed
    #: that is not configured on either side. Distinguished because the two call for opposite
    #: messages: a negative verdict says to change the party, and this says to finish entering it.
    unknown: bool = False


def is_grounded(name: str, game: str = "") -> bool:
    """Whether this encounter is on the ground, which is Arena Trap's whole condition.

    Levitate or a Flying type lifts it. Gravity, an Iron Ball and Ingrain would put it back down
    and are deliberately absent: none is reachable here, since nothing in `MODELLED_OUR_EFFECTS`
    sets Gravity and a wild target holds no item.
    """
    from claytonlib.battle.damage import ABILITY_LEVITATE

    if target_ability(name, game).strip().lower() == ABILITY_LEVITATE:
        return False
    return "flying" not in {t.strip().lower() for t in target_types(name, game)}


def _already_scarfed(member: "TrapCandidate") -> bool:
    """Whether this member's Speed already has a Choice Scarf in it.

    Checked because `TrapCandidate.speed` is item-adjusted: suggesting a scarf to somebody
    already holding one produced "105 does not outspeed 105 - a Choice Scarf would (157)", which
    is advice to do the thing they had done and a number no Pokemon in the battle would have.
    """
    from claytonlib.battle.damage import item_key
    from claytonlib.battle.readiness import CHOICE_SPEED_ITEMS

    return item_key(member.held_item or "") in CHOICE_SPEED_ITEMS


def trap_checks(species: str, party: "list[TrapCandidate] | tuple[TrapCandidate, ...]", *,
                target_speed: int | None, game: str = "") -> list[TrapCheck]:
    """Which party members could hold a roamer in the battle, one row each.

    **Every member is checked, not just the lead**, because any of them can end up active: the
    trap is released when our side leaves the field, so the Pokemon that replaces a fainted
    trapper has to be able to re-establish it (notes/roamers.md sec 2.4). The rule is the same for
    both -- a replacement is on the field before the next action selection, so an ability traps
    from that selection just as a lead's does.

    The three ways, in the order `RoamingPokemon_Main` tests them:

    * **Shadow Tag** -- always, and from the first selection. No Speed requirement at all.
    * **Arena Trap** -- the same, but only if the target `is_grounded`. Cresselia has Levitate, so
      on that target it does nothing.
    * **A pure trapping move** -- Mean Look, Block or Spider Web, and it must **outspeed the
      target**: the roamer has already chosen Escape by then, and the move only refuses it by
      landing first (sec 2.3). A Choice Scarf counts, and `scarf_would_fix` says when it is the
      whole difference.

    What this does NOT check is our own voluntary switching, which no party composition can fix:
    a Shadow Tag Pokemon switched IN behind an already-chosen escape does not stop it, so on a
    roamer hunt a mid-battle switch is a lost run whoever is on the bench. That belongs in the run
    page's advice, not in a readiness row.

    Returns ``[]`` for a target that is not a roamer: a static encounter cannot leave, so a party
    that cannot trap is a perfectly good party.
    """
    from claytonlib.battle_compass.sim import ARENA_TRAP, SHADOW_TAG
    from claytonlib.moves import resolve_move
    from claytonlib.species_names import display_species_name

    try:
        if not is_roamer(species, game):
            return []
        grounded = is_grounded(species, game)
        display = display_species_name(resolve(species, game)[1].species)
    except (KeyError, ValueError):
        return []

    def effects(member: TrapCandidate) -> dict[int, str]:
        found: dict[int, str] = {}
        for name in member.moves:
            if not name:
                continue
            try:
                move = resolve_move(name)
            except (KeyError, ValueError):
                continue
            found.setdefault(move.effect, name)
        return found

    checks: list[TrapCheck] = []
    for member in party:
        ability = (member.ability or "").strip().lower()
        known = effects(member)
        if ability == SHADOW_TAG:
            checks.append(TrapCheck(member.name, True, how="Shadow Tag"))
            continue
        if ability == ARENA_TRAP:
            if grounded:
                checks.append(TrapCheck(member.name, True, how="Arena Trap"))
            else:
                checks.append(TrapCheck(
                    member.name, False, problem=(
                        f"Arena Trap does not reach {display}, which is not grounded — it is "
                        f"skipped before the Arena Trap check, so the roamer flees anyway")))
            continue
        trap_move = known.get(PURE_TRAP_EFFECT)
        if trap_move:
            if not target_speed or not member.speed:
                # A verdict needs both Speeds, and the one that is usually missing is the
                # target's: a roamer's spread cannot be looked up from the key seed, so a hunt
                # can be fully configured in every other respect and still not know it
                # (notes/roamers.md sec 7).
                missing = ("the target's Speed is not known yet" if not target_speed
                           else f"{member.name}'s Speed is not configured")
                checks.append(TrapCheck(
                    member.name, False, how=trap_move, unknown=True,
                    problem=(f"{trap_move} would hold it, but only by outspeeding, and "
                             f"{missing}")))
            elif member.speed > target_speed:
                checks.append(TrapCheck(member.name, True, how=trap_move))
            elif member.speed == target_speed:
                # A TIE, which is worse than being slower rather than marginally better: the ROM
                # breaks it with a roll (notes/ss_rng/speed.md), so the trap lands half the time
                # AND the turn costs an advance the simulation does not predict. Either side of
                # the tie is fine and the tie itself is not.
                checks.append(TrapCheck(
                    member.name, False, how=trap_move,
                    problem=(
                        f"{trap_move} ties {display}'s Speed at {target_speed}, and the game "
                        f"breaks a tie with a roll — so the trap is a coin flip and the turn "
                        f"spends an advance the simulation does not predict")))
            elif _already_scarfed(member):
                checks.append(TrapCheck(
                    member.name, False, how=trap_move,
                    problem=(
                        f"{trap_move} needs to land before the escape, and {member.speed} does "
                        f"not outspeed {display}'s {target_speed} even with the "
                        f"{member.held_item}")))
            elif member.speed * SCARF_NUMERATOR // SCARF_DENOMINATOR > target_speed:
                scarfed = member.speed * SCARF_NUMERATOR // SCARF_DENOMINATOR
                checks.append(TrapCheck(
                    member.name, False, how=trap_move, scarf_would_fix=True,
                    problem=(
                        f"{trap_move} needs to land before the escape, and {member.speed} does "
                        f"not outspeed {display}'s {target_speed} — a Choice Scarf would "
                        f"({scarfed})")))
            else:
                checks.append(TrapCheck(
                    member.name, False, how=trap_move,
                    problem=(
                        f"{trap_move} needs to land before the escape, and {member.speed} does "
                        f"not outspeed {display}'s {target_speed} — not even with a Choice "
                        f"Scarf")))
            continue
        partial = next((known[e] for e in sorted(known) if e in PARTIAL_TRAP_EFFECTS), None)
        if partial:
            checks.append(TrapCheck(
                member.name, False, problem=(
                    f"{partial} does trap, but its residual takes 1/16 of the target's HP every "
                    f"turn and the run needs it alive on 1 — it cannot be the trap")))
            continue
        checks.append(TrapCheck(
            member.name, False, problem=(
                "cannot trap: no Shadow Tag, no Arena Trap and no Mean Look, Block or "
                "Spider Web")))
    return checks


def repel_warnings(species: str, lead_level: int | None, game: str = "") -> list[str]:
    """Whether the LEAD's level lets the Repel trick find this roamer at all.

    `RepelPreventsEncounter` is ``repelActive && firstBattlerLevel > wildLevel``
    (pokeplatinum src/overlay006/wild_encounters.c:1397-1400) read off the first *live* party
    member (`:264`) -- which is also the Pokemon that gets sent out, so the trapper and the Repel
    gate are the same Pokemon and cannot be tuned separately.

    A strict inequality, so **equal levels are fine**: a Lv50 lead against a Lv50 Cresselia passes.
    One level over and the roamer is suppressed -- and on the walking path that is worse than a
    normal encounter, because the suppressed check returns FALSE outright and the encounter is
    simply lost rather than falling through to a wild Pokemon [verified].

    The other half of the trick -- the lead being ABOVE every wild level on the route -- is
    deliberately not checked: it needs Platinum's route encounter tables, which this project does
    not carry (`safari_zones.json` is the HGSS Safari's). Warning about the half that is knowable
    beats warning about neither, and the message says which half it checked.

    Advisory, not blocking: a player may be finding the roamer some other way (walking without a
    Repel, or on a Seed A they are steering), and refusing the hunt for it would be wrong more
    often than right.
    """
    try:
        if not is_roamer(species, game):
            return []
        level = encounter_level(species, game)
    except (KeyError, ValueError):
        return []
    if lead_level is None or lead_level <= level:
        return []
    from claytonlib.species_names import display_species_name

    named = display_species_name(resolve(species, game)[1].species)
    return [
        f"The Repel trick needs your lead at level {level} or below — {named} is level {level}, "
        f"and a lead above it suppresses the encounter entirely rather than giving you a wild "
        f"Pokemon instead. Your lead is level {lead_level}. (It still has to be ABOVE the route's "
        f"wild levels, which this cannot check.)"
    ]


def trap_warnings(species: str, party: "list[TrapCandidate] | tuple[TrapCandidate, ...]", *,
                  target_speed: int | None, game: str = "") -> list[str]:
    """`trap_checks` as sentences, worst first, for a readiness panel.

    Advisory in shape and fatal in fact, which is the one place this differs from
    `access_warnings`: a lead that cannot trap does not make the simulation wrong, it makes the
    run end on turn 1. So the lead's row comes first and says so, and the bench's rows explain
    what a faint would cost rather than reading as nitpicking.
    """
    checks = trap_checks(species, party, target_speed=target_speed, game=game)
    if not checks:
        return []
    out: list[str] = []
    lead, bench = checks[0], checks[1:]
    if lead.unknown:
        out.append(f"{lead.name} leads and {lead.problem} — so whether this party can hold the "
                   f"roamer at all is still unknown.")
    elif not lead.traps:
        out.append(f"{lead.name} leads and {lead.problem}. The roamer flees on turn 1 and the "
                   f"run is over before it starts.")
    if lead.traps and lead.how not in ("Shadow Tag", "Arena Trap"):
        out.append(f"{lead.name} holds it with {lead.how}, which only works because it outspeeds "
                   f"— the roamer chooses Escape on turn 1 either way and {lead.how} refuses it "
                   f"by landing first.")
    for check in bench:
        if check.unknown:
            out.append(f"{check.name}: {check.problem}.")
        elif not check.traps:
            out.append(f"{check.name} {check.problem} — so if {lead.name} faints, the roamer "
                       f"leaves.")
    if any(c.unknown for c in checks):
        return out
    if any(c.traps for c in checks) and not all(c.traps for c in checks):
        out.append("A roamer hunt wants EVERY member able to trap, not just the lead: the trap is "
                   "released when our side leaves the field, so a faint hands the roamer a free "
                   "turn to escape on.")
    if all(c.traps for c in checks) and len(checks) > 1:
        out.append("Do not switch voluntarily: a Shadow Tag Pokemon switched in behind an "
                   "already-chosen escape does not stop it, so only a faint's replacement gets a "
                   "second chance at the trap.")
    return out


def is_roamer(name: str, game: str = "") -> bool:
    """Whether this encounter is a roamer, which changes the simulation rather than its difficulty.

    Read off the row for the same reason `target_ability` is: it is a property of the ENCOUNTER.
    The same species can be both in principle -- HeartGold's Latios roams at Lv35 and is static
    at Lv40 in the Pewter museum -- so asking the species would be wrong for exactly the case
    this table's encounter keys exist for.
    """
    return resolve(name, game)[1].roamer


def supported(game: str = "") -> tuple[str, ...]:
    """Encounter keys this game can hunt, sorted.

    An empty `game` returns everything, which is what a profile with no game set gets. See
    `resolve` for why that is permissive rather than refused.
    """
    return tuple(sorted(k for k, row in ENCOUNTERS.items() if _in_game(row, game)))
