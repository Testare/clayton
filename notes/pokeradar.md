## Attempt 1
Seed hit: 0xEE0203F1

Did 2 journal flips and used pokeradar, matched utility, including hard shake at -(1, -1). Utility says 9 rolls were consumed.

Utility says slot 5 at 18 advances, so I did 3 journal flips (3*4+2 => 14), then turned, walked, turned, walked.

4+9+14 => 27 advances total

I encountered machoke 48 M.
* Machoke, Lvl 48 (Slot 0)
* Male
* Timid Nature
* "Often scatters things"
* stats 147/90/78/61/63/58
* No Guard

Except for the characteristic (Which I might've messed up for pokefinder might have messed up), this matches the machoke at advance 33. Given we are off by my party count, it's possible I hit the counter RNG advance, so I'll take a couple steps then resave.

Then I missed recording the follow-up.

## Attempt 2

(I took a couple steps and resaved and reloaded before hitting the seed so that the party count issue would not recur)
Seed hit: 0xEE0203EF

18 advances to find hard shaking grass, 9 pages. Everything matches utility. Utility claims 11 rolls consumed, bringing us to 29.

Slot 4 in 2 advances, so I just turned and walked into the grass (2 advances, turn and step). Got Graveler 49 M, still not primeape.

Graveler
* 49 M (Slot 1)
* Impish
* Sturdy Body
* 119 108 145 54 60 40
* Rock Head


Clip shows shaking grass at (+1, +1) (soft), (-2, +2) (hard), (-2, +3) (hard), and 4th ring not visible (But might be near trees at bottom left)

This matches Advance 99 in the utility, excep that patch 1 (-2, +3) is shaking hard in mine but soft in the utility (And I can't see the patch at (-3, +4), so I don't know how hard it was shaking). I have chain set to 1, and it is "hard after a capture", so it should match.

I walked into the hard shaking patch 2, at (-2, -2) (2 steps right, turn, 2 steps up). The utility says this should continue the chain, but I encountered a Primeape 49 M, and the chain definitely broke.

Primeape
* 49 M (Encounter Slot 4)
* CarefulG
* Mischievous
* 126 109 68 70 94 110
* Vital Spirit

### Post analysis

Graveler matches advance 33. This means the turn and step must've taken more than 2 advances, which we have confirmed is a possibility. Might need to add some sort of mode to this thing to calculate actual advances for pathing to the encounter.
(This graveler matches advance 33 in pokefinder)

Pokefinder says battle advances go to advance frame 100, which is close to the advance frame that matched the placement of the follow-up tiles (99), if not whether they shook or if they continued the chain.

The utility claims 12 advances for this calculation, bringing us to either 111 or 112 depending on whether we use the advance from pokefinder or the utility. We took 5 steps (4 and turned), which should bring us to at least 116, or 119 on average if the 1.5 advances per step average is to be believed.

Primeape matches advance 119 in pokefinder, so that maths out okay.

Interestingly, if I don't lock in pokefinder mode, primeape matches advance 118 in pokefinder (except for it being obvously wingull and not primeape in slot 4) and graveler matches advance 32. So pokefinder encounters take one less roll it seems? This is probably more to do with how pokefinder is implemented than anything, but since I'm using pokefinder to find a shiny frame, I'll need to keep this in mind.
## Attempt 3
0xEC0203ED 

Pokeradar at advance 0, Matches utility. says 11 rolls consumed, 9 more to hit encounter slot 4, though 10 or 11 also works.
Turned to the right, steped, turned to face down, then up, which should have been 5 advances. Did 2 journal pages to get to 9 advances, then stepped up. This should be 20 advances total, plus however many it took to step into the grass

Got encounter slot 4! Primeape 49 M

Spore worked, so it is anger point, which matches primeape at 21, 22, and 25. The post battle advances are 44, 65, and 106.

The shakes match 64, leading me to believe they'll consistently match battle advances - 1 and we hit frame 22.

I'm going to try and catch a primeape with a payapa berry, the next one is at advance 109. Utility says "12 rolls plus roamer" after 64, so I'm saying we're on advance 77, meaning 22 advances? I'm going to turn left, then down, and then I'll be facing a patch and 2 advances ahead (79). 20 advances, I think walking into the patch will take 2, so I'll do 18 advances with my journal.

Ack, I screwed up and did the steps AFTER the 18 advances, and I didn't turn to the left first. The primeape is female (109 was male), so I definitely didn't do it right.

I also forgot that I could get information from the chain by recording the patch locations, oops. I saw them though, so I have a vague idea of where they were.

First Primeape does indeed match the one at advance 22. The second one matches advances 67, 93, 97, and 133. It occurs to me now that I did my math wrong earlier - 77 then 22 advances is 99, not 109. so my 18 advances, then turn and step probably brought me to 97.

All of them advance to frame 200 in pokefinder, and indeed if I set advances to 199 it looks like my vague memory of where the patches were after I caught primeape.


---

## What the two attempts actually showed [Note from R2D2]

Claims are tagged [verified] (read out of `pret/pokeplatinum`, or reproduced from the
runs recorded in `notes/pokeradar_attempts.md`), [derived] (follows from a verified fact) or [needs gdb].

### The mismatched wave: one missing advance, and it is the roamer check

Both waves that the **radar item** set up matched the utility exactly — attempt 1 at
advance 4 (9 rolls, hard shake at (-1,-1)) and attempt 2's first wave at advance 18
(11 rolls). Only the wave set up **by a battle** disagreed, and it disagreed in the
shake/continue flags while its four positions were right. That asymmetry is the tell.

A post-battle wave rolls its positions *before* the battle — `RadarSpawnPatches` at
`src/overlay006/wild_encounters.c:714-717`, immediately after the encountered mon is
created — and its flags *after* it, `SetupGrassPatches` at `src/encounter.c:428`
[verified]. Between those two, `src/encounter.c:421` runs
`RoamerAfterBattle_UpdateRoamers`, whose `roamer == NULL` branch — taken whenever the
thing you battled was not itself a roamer, i.e. every radar battle — draws one
**unconditional** `LCRNG_RandMod(100)`: the 30% "roamers leave anyway" check at
`src/overlay006/roamer_after_battle.c:55` [verified].

So a battle-driven wave's two halves are **1 advance apart**, and an item-driven wave's
are contiguous (`RefreshRadarChain` does both in one field task, `src/pokeradar.c:432-438`)
[derived]. The utility assumed contiguity everywhere; `ROAMER_CHECK_ADVANCES = 1` now
models it, and `r` cycles faint / capture / **radar use** so the two paths are distinct.

With the gap inserted, advance 99 / chain 1 / hard / after a capture reproduces the clip
on all four rings [verified]:

| ring | tile | was | now | clip |
| --- | --- | --- | --- | --- |
| 0 | (-3,+4) | hard, continues | hard, continues | unseen, bottom-left by the trees |
| 1 | (-2,+3) | **soft** | **hard**, continues | hard |
| 2 | (+2,-2) | hard, **continues** | hard, **BREAKS** | hard, and it broke |
| 3 | (+1,+1) | soft, breaks | soft, breaks | soft |

Gaps 0-399 were swept against the three visible rings; 1 is the smallest fit and is the
one the code predicts.

If a roamer is actually sitting on the route it costs more — `MoveRoamersOffMap` ->
`RoamingPokemon_MoveToRandomMap` has a rejection loop (`src/roaming_pokemon.c:339-352`) —
and a roamer on the map also adds a `RandMod(2)` to every step whose encounter check
passes (`wild_encounters.c:1441`). Keep both roamers off the route [derived].

### Why the chain broke

It follows from the table above: ring 2 was a **break** patch, so stepping in took the
`CreateWildMon_FromRadarNoChain` path and drew a slot roll; the patch shook hard, so
slots 4/5/10/11 held Primeape/Primeape/Mankey/Mankey; the roll gave slot 4; Primeape is
not Graveler, so `RadarChain_Clear` (`wild_encounters.c:1189`) [verified].

The Primeape arriving **from encounter slot 4 is itself the proof** that the patch was a
break patch — a chain-continuing patch copies the chain's species and level with no slot
roll at all (`CreateWildMon_FromRadarKeepChain`), so any slotted species means the chain
was already lost before the species was picked [derived].

General lesson: when the chain shakes hard, a hard patch is **ambiguous**. Continuing
patches copy the chain's type, and a break patch rolls 50/50 and can show that same type.
Only the *opposite* type is diagnostic — ring 3 above, shaking soft against a hard chain,
was a guaranteed break. "Walk into the hard one" excludes the soft patches and nothing
more [derived].

### The walk, and what the slot table should have meant

The old table searched for the advance at which a slot *roll value* occurred. That is not
what you need: the final step into the patch draws its own encounter-check rolls first —
the flat roll always, the rate roll when the flat one passes — and only then the slot
roll. Standing on a patch tile forces the encounter regardless of those verdicts
(`wild_encounters.c:279-285`), so they only shift the slot roll's position [verified].
That is exactly attempt 2's 2-advance miss: "slot 4 at 2 advances" meant the slot roll sat
at advance 3; the turn spent 2 advances and the step added its own. The table now reads as
advances to perform *before* stepping in, by forward simulation, and X=2 gives slot 1 —
the Graveler [verified].

The step model is pinned by all five recorded encounters -- slot, nature and every IV:

| run | route | model | result |
| --- | --- | --- | --- |
| a1 Machoke | 14 journal + 3 inputs, break patch | X=17 | slot 0, Timid, PID `0x6718E8B5`, slot roll at 33 |
| a2 Graveler | 1 turn, break patch | X=1 | slot 1, Impish, PID `0x940A25D0`, slot roll at 33 |
| a2 Primeape | 4 inputs, break patch | X=4 | slot 4, Careful, slot roll at 119 |
| a3 Primeape 1 | 4 inputs + 2 journal pages, break patch | X=8 | slot 4, Mild, IVs 6/21/12/21/9/24, slot roll at 22 |
| a3 Primeape 2 | 18 journal + 1 turn, **continuing** patch | X=19 | Naive, IVs 20/26/22/9/1/18 |

Both Primeapes match on nature plus all six IVs, which is unique to one frame, and the
Machoke and Graveler match on nature plus all six stats [verified]. PokeFinder's advance N
is the frame of the encounter-slot roll, so `wave end + X + step cost` reproduces it --
a direct cross-check on the overlay's X and its +/++ marker [verified].

Two corrections that this set forced, both of which had been compensating for each other:

**A lead with Static (or Magnet Pull) costs one extra advance before the slot roll.**
`TryGetSlotForTypeMatchAbility` rolls a `RandMod(2)` whenever the lead's ability matches
(`wild_encounters.c:1319`); on a table with no Electric or Steel type -- Route 226 has
neither, radar slots included -- `ForceMatchingTypeEncounterSlot` then returns at `:1308`
without rolling, so the cost is exactly one advance and the slot is unaffected [verified].
`CreateWildMon_FromRadarKeepChain` never reaches it, so a **continuing** patch pays
nothing [verified]. Attempt 3's lead was a Raichu; without this roll no advance count in
0-219 reproduces its Primeape, and with it exactly one does.

**The grace period is fresh on a load, and all five encounters are inside it.** Every
input in all five logged routes cost exactly 1 advance, which is the in-grace signature
(the grace roll ends the check 95% of the time); past-grace inputs average 1.52. The
earlier "past grace" reading of attempts 1 and 2 was an artifact of the missing Static
roll -- the two errors cancelled to the same slot-roll frame, 33, which is why it looked
right [verified].

A turn counts as an input: `Field_CheckWildEncounter` hangs off
`input->endMovement` (`src/overlay005/field_control.c:227`), which a completed turn sets
just like a step (`src/player_move.c:386-396`); only `Field_ProcessStep` is gated on real
movement, so turning burns rolls without spending Repel steps or radar charge [verified].

### The grace period: fresh on a load, and when it re-arms

`encounterAttempts` gates a cheap 1-roll path at the top of `ShouldGetRandomEncounter`.
Its life cycle, which took three passes to get right:

* Zeroed on field entry, `src/field_map_change.c:301` -- so a save load starts **in** the
  grace period, and all five recorded encounters sit inside it [verified].
* Incremented only inside the grace branch (`wild_encounters.c:756`), so an input past the
  threshold never touches it [verified].
* Zeroed again at **`wild_encounters.c:375`**, which is **outside** the
  `if (!gettingEncounter)` above it -- so every input that falls through to the bottom of
  `WildEncounters_TryWildEncounter` re-arms the grace period, *including a Repel-blocked
  encounter*, because Repel only makes `encounterSuccess` false [verified]. (The
  `else { encounterAttempts = 0; }` at `:681` is `WildEncounters_TryMudEncounter`, a
  different entry point -- do not read it as the grass path.)
* An input whose check failed never gets there: it returns early at `:287-289` and the
  counter keeps its value [verified].

So the counter is re-armed only by an input that reached the slot roll -- both check rolls
passing, 12% of inputs at rate 30 -- or by an actual encounter. The shape of a Repel walk
is therefore: 5 cheap 1-roll inputs after a load or a reset, then full 1-3 roll inputs
until one passes both rolls and hands you 5 more cheap ones [derived]. The utility
defaults to a fresh counter; `--attempts N` sets it explicitly.

Repel is orthogonal to all of this: it blocks the battle, not the reset [verified]. It
does *not* disable the grace period.

The walk model re-arms accordingly, which changes the 12-input step table for 61% of
states and drops the cost of 12 inputs from 17.3 to 16.1 advances on average [verified].

### Grass encounter rates are not always 30

`land_rate` across `res/field/encounters/*.json` takes five values, and the rate drives
both the rate roll and the grace threshold `8 - ((rate << 8) / 10 >> 8)` [verified]:

| land_rate | grace steps | where |
| --- | --- | --- |
| 5 | 8 | Snowpoint Temple |
| 10 | 7 | caves, and **Routes 227 and 228** |
| 15 | 7 | Mt Coronet, Turnback Cave |
| 30 | 5 | almost every route, Eterna Forest, the lakefronts |
| 35 | 5 | Great Marsh |

So a radar hunt on Route 228 runs at rate 10: 7 grace steps, and a step costs 1 roll 60%,
2 rolls 36%, 3 rolls 4% (mean 1.44 vs 1.52 at rate 30) [derived]. On top of the map value,
the *effective* rate is scaled before the check — x2 for Arena Trap / No Guard /
Illuminate, /2 for White Smoke / Quick Feet / Stench (and Sand Veil / Snow Cloak in their
weather), x1.5 or /2 for a White or Black Flute, x2/3 for a Cleanse Tag or Pure Incense
(`wild_encounters.c:921-939`, `:1326-1357`) — and the scaled value is what feeds the grace
threshold too, so an Illuminate lead both doubles the rate roll and shortens the grace
period to 2 steps [verified]. Pass the effective value as `--rate`.



