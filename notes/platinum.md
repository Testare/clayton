# Platinum — what supporting it in Glass and Hunts actually takes

**Analysis document.** Claims are tagged [verified] (read out of the pokeplatinum decomp or
measured here), [derived] (follows from a verified fact) or [design] (a decision to make).

Scope: **Glass and Hunts only.** Expeditions (chart / Safari Compass / Metronome Compass) stay
HGSS-only, and Diamond/Pearl stay unsupported everywhere. Darkrai is worked through in §5.1-5.5
and Giratina in §5.6 — as examples of what the target side has to handle, not as a shortlist.
Every legendary is in scope eventually, so §5 is organised by *what each one exercises* (a forme
split, a conditional ball, a two-turn move) rather than by any order of attack.

Sources. Everything below was read against a clone of `pret/pokeplatinum` (complete decomp) at
`/tmp/pokeplatinum`; unqualified file:line citations are that tree. Citations under `Core/`,
`Form/` or `Model/` are `Admiral-Fish/PokeFinder` at `/tmp/pokefinder`, an independent check on
the two mechanics it already implements (coin flips and chatot pitch). Quoted prose is
[Smogon's DPPt/HGSS RNG guide part 2](https://www.smogon.com/ingame/rng/dpphgss_rng_part2), which
is the established player-facing procedure and the source for the frame costs of actions the
decomp does not make obvious.

---

## 1. The good news: most of the RNG stack is the *same code*

| Thing | Platinum | Verdict |
| --- | --- | --- |
| LCRNG | `include/math_util.h:8` `1103515245`, `:9` `24691`; `src/math_util.c:80` returns `state >> 16` | identical [verified] |
| Initial seed from the RTC | `src/main.c:306-316` | identical formula [verified] |
| When the seed is made | `src/game_start.c:113` — `InitRNG()` in `GameStartLoadSave_Init` | same point in the load [verified] |
| Battle seed ("Seed B") | `src/field_battle_data_transfer.c:115-119` — *same formula again*, evaluated in `FieldBattleDTO_New` | identical mechanism [verified] |
| Two RNG streams | `src/battle/battle_main.c:1033-1034` saves the overworld LCRNG and seeds `seedRandNext` from `dto->seed`; `:774` restores it after | identical [verified] |
| Battle RNG | `src/battle/battle_system.c:1308-1311` — same multiplier/increment, same `>> 16` | identical [verified] |
| Capture maths | `src/battle/battle_script.c:10904-11013` | identical, incl. the double floor and the `isqrt(isqrt(0xFF0000/a))` threshold [verified] |
| Accuracy stage table | `include/data/hit_rate_stages.h:4-18` | byte-identical to `battle/damage.py:100-114` [verified] |
| Accuracy 0 ⇒ no roll | `src/battle/battle_controller_player.c:2899-2902` returns before the roll at `:2976` | same as we model [verified] |
| 4 pre-move speed rolls per turn | `src/battle/battle_controller_player.c:858-861` loops `MAX_BATTLERS` | matches `battle/turn.py` `BEFORE_TURN_ADVANCES = 4` [verified] |

The seed formula deserves spelling out, because it is the foundation of Glass's delay arithmetic
and of the Hunts candidate grid:

```c
// src/main.c:312 and src/field_battle_data_transfer.c:115, verbatim
u32 seed = date.year + date.month * 0x100 * date.day * 0x10000
         + time.hour * 0x10000 + (time.minute + time.second) * 0x1000000
         + gSystem.vblankCounter;
```

`month * 0x100 * day * 0x10000` is `month*day << 24`, so this is exactly
`((month*day + minute + second) & 0xFF) << 24 | hour << 16 | (delay + year-2000)` —
`times.calculate_seed` and `calibration_tools.seed_for` unchanged [verified]. Therefore:

* **Glass's `delay = (key_seed & 0xFFFF) - (year - 2000)` holds in Platinum unchanged** [derived].
* **`times.generate_times` / `mdMap.json` work unchanged**, and one key seed still means one hour.
* **Two candidate seeds per delay** (RTC second not-yet-ticked / ticked) still holds, and so does
  `match_parity`.
* **The Hunts (delay × second) candidate grid in `battle_compass/candidates.py` carries over with
  no change at all** [derived]. The sibling-separation argument in `notes/seed_separation.md`
  (differences of `k*2^24`, `c` multiplying by 109 per advance) is a property of the LCRNG and the
  formula, both identical, so it applies verbatim.

### Measured: the data files need no Platinum variant

Two cross-checks run here against the decomp's own JSON:

* **All 467 moves** — power, accuracy, PP, priority, effect id and effect chance — are
  **identical** between `basedata/moves.json` (HGSS-derived) and `res/moves/*/data.json`
  (effect names resolved through `generated/move_battle_effects.txt`). Zero mismatches [verified].
* **All 493 species** — base stats, catch rate, types, genderless — are **identical** between
  `basedata/base_stats.json` and `res/pokemon/*/data.json`. The only diffs the comparison printed
  were my own normalisation artifacts (`COMPOUNDEYES` vs `COMPOUND_EYES`, and the ROM listing a
  single-ability species twice) [verified].

So `moves.json`, `base_stats.json` and the whole `claytonlib/battle/` damage/catch/stats layer are
game-agnostic as they stand. One gap: **Platinum's new formes are not in `base_stats.json`** —
Giratina Origin, Shaymin Sky, the Rotom formes. `base_stats.json` is keyed by species slug with a
single row each (`giratina-altered` is the Giratina row), so a forme is not merely missing, it has
nowhere to live. Irrelevant to Darkrai; blocking for a Distortion World Giratina (§5.6).

The decomp makes filling it easy when the time comes: forme data is right there at
`res/pokemon/<species>/forms/<forme>/data.json`, and `Pokemon_GetFormNarcIndex`
(`src/pokemon.c:4943-4946`) gives the personal-table index each forme occupies — Giratina form 1
is index 501 — so `one-offs/populate_base_stats_from_rom.py` can be extended rather than
hand-maintained [verified].

---

## 2. What is actually gone

**No Elm calls.** There is no phone-call analogue that spends one advance and reports a letter.

**No load-time roamer relocation.** `RoamingPokemon_RandomizeAllLocations` is called only from
`FieldSystem_SetFlyFlags` and `FieldSystem_SetTeleportFlags` (`src/field_map_change_flags.c:106`,
`:112`) — Fly and Teleport, never game load [verified]. So the whole REL half of
`calibration_tools.roamer_positions` has nothing to observe, and
`safari_advance.advance_context`'s `(rng_calls, elm)` pair has no Platinum counterpart.

Two related facts worth knowing before designing around them:

* **Platinum has six roamer slots** — Mesprit, Cresselia, Darkrai(!), Moltres, Zapdos, Articuno
  (`src/roaming_pokemon.c:252-275`) [verified]. The Darkrai slot is unused by the retail scripts;
  the real Darkrai is static (§5).
* **Every non-temporary map change burns LCRNG calls per active roamer** — a `1/16` relocation
  check plus at least one route roll (`src/roaming_pokemon.c:199-213`, called from
  `src/field_map_change_flags.c:48-52`) [verified]. With the birds roaming that is up to five
  roamers' worth of advances per door you walk through. **Count advances without changing maps**,
  or expect the count to be wrong [derived].

---

## 3. What replaces it: coin flips (MT) and chatot pitch (LCRNG)

### 3.1 Coin flips are a *different generator*, which is better than it sounds

`src/applications/poketch/coin_toss/main.c:158`: `appData->coin.isHeads = MTRNG_Next() % 2` —
the Poketch coin toss reads **MT19937**, not the LCRNG [verified]. `InitRNG` seeds *both*
generators with the same u32 (`src/main.c:314-315`) [verified], and `src/math_util.c:113-152` is
textbook MT19937 (`init_genrand` with `f = 1812433253`, the standard tempering).

What that buys, and it is a lot:

* **A flip costs zero LCRNG advances.** You can identify the seed without spending the frame you
  are trying to land on — strictly better than Elm calls, which are the thing being counted
  [derived].
* **Flips separate RTC-second siblings instantly.** Two seeds differing by `k*2^24` produce
  completely unrelated MT streams, where in the LCRNG they are nearly invisible for ~19 turns
  (`candidates.py`). The axis Battle Compass currently defaults to `second_window = 0` to avoid
  becomes cheap to search [derived].
* **One bit per flip.** `% 2` of a tempered word. A ±2s × ±60-delay window is a few hundred
  candidates, so ~10-12 flips [derived]. Cheap, but not free, and the bits are *order-sensitive*
  — a miscounted flip is a silent wrong answer, so the UI wants undo (`u`, like Safari Compass).
* **Nothing else in the field touches MT before you can open the app.** `MTRNG_Next` consumers are
  new-save init (`src/game_start.c:158,162`, `src/special_encounter.c:22-23` — both save-entry
  init funcs, so new game only), TV segments, the Underground, and other Poketch apps (friendship
  checker, roulette) [verified]. **PokeFinder agrees and assumes zero**:
  `Utilities4::coinFlips` is `MTFast rng(seed, 0, 20)` — seed, **advances = 0**, 20 flips
  (`Core/Util/Utilities.cpp:144-159`, signature at `Core/RNG/MT.hpp:123`) [verified]. So the flip
  sequence starts at MT output 0, with no leading offset to search.
* Parity check against the ROM: PokeFinder emits `(rng.next() & 1) == 0 ? "T" : "H"`, and the ROM
  sets `isHeads = MTRNG_Next() % 2` — odd is heads in both [verified].

**New code:** an MT19937 module in `claytonlib/` (~40 lines) plus a `flip_sequence(seed, n)`
helper, the moral equivalent of `elm_calls`.

### 3.2 A chatot cry is one LCRNG advance, and its pitch is readable

`src/sound_chatot.c:60-98`, in `Sound_Impl_PlayChatotCry`:

```c
u16 speedVariance = LCRNG_Next() % CHATOT_CRY_SPEED_VARIANCE;   // 8192
...
param.speed = WAVE_OUT_SPEED(1.0) + speedVariance;              // 32768 + variance
```

[verified]. So:

* **One cry = exactly one LCRNG advance** — which confirms the project's existing "a chatot flip
  is two advances" accounting (two summary screens = two cries) [verified].
* **The pitch is `(state >> 16) % 8192`** — 13 bits of the roll, i.e. playback speed from ×1.000
  to ×1.250, a shade under four semitones (`include/sound.h:23`) [verified].
* **Scaled to 0-99 the way everyone quotes it**, which PokeFinder states outright:
  `chatot(((prng % 8192) * 100) >> 13)` where `prng` is the roll `state >> 16`
  (`Core/Gen4/States/State4.hpp:49`) [verified]. Our ROM reading and PokeFinder's implementation
  were derived independently and agree exactly, which is about as settled as this gets.
* **It only fires when a recorded cry is actually playable.** `Sound_IsRecordedChatotCryPlayable`
  (`src/sound_chatot.c:39-57`) gates it, and the recording is **one per save file**
  (`SaveData_GetChatotCry`), not per Pokemon. No valid recording ⇒ the default cry plays and
  **no advance happens at all** [verified]. That is a real trap: the player must confirm they are
  hearing their own recording, or they are flipping and standing still at the same time.

Community practice agrees exactly, and adds the operational detail: *"accessing Chatot's summary
window like the one below will advance the frame by 1"*, and *"you can have two Chatot next to each
other in your party and just keep flipping between their summaries"* for speed
([Smogon part 2](https://www.smogon.com/ingame/rng/dpphgss_rng_part2)) [verified].

**A pitch is an output, not an input** [design, round 2]. It is tempting to treat it as HGSS
treats an Elm call — something the player reports, from which the frame is deduced — and an
earlier version of this note and of the implementation did exactly that. It is the wrong shape.
The player already knows their advance frame: they load on a known starting frame and every action
has a known cost (a Journal flip 2, a cry 1). So the pitch is how the *planned margin* gets
checked — they hear it and know whether they landed where the plan said. Asking them to type
pitches in is asking them to measure a number they already have, and it imports an error source
(a misheard bucket) into a count that was exact.

What follows from that, and it simplifies several things:

* there is no pitch parsing, no tolerance band, and no pitch search — `frame_candidates` stays
  HGSS-only;
* the per-venue starting frame stops being optional. §3.4 said identification did not need it
  because the search found the observation wherever it sat; with no search, the starting frame is
  the only anchor the count has;
* **ambiguity matters more, not less**: the margin is now the *only* error detection a route has,
  so a bracket that repeats 1-2 positions away is a miscount made invisible.

### 3.3 The Journal is the blind bulk method, and it is 2 advances

**This is the piece that makes the port structural rather than a redesign.** From the same guide:

> *"Whenever your Journal is on a page that displays (insert Pokemon's name) was caught (Time)
> like the one below, frames are advanced by 2. Flipping your Journal to another page with a
> similar entry will also advance it by 2."*

[verified]. So Platinum has **both** halves of the HGSS route, in the same sizes:

| | HGSS | Platinum |
| --- | --- | --- |
| Bulk, blind | chatot flip — **2** advances | **Journal flip — 2 advances** |
| Margin, readable | Elm call — 1 advance, 3-way letter | **chatot summary — 1 advance, 5-way pitch** |

An earlier draft of this note argued the two-phase split was obsolete because every advance is now
readable in principle. That was wrong twice over: pitch is too hard to read in bulk (§9.2), and
there is a purpose-built blind method with exactly the arithmetic `plan_advances` already does.

**So `plan_advances` is correct as written** — `chatot_flips` (2 advances each, including the
trailing half-flip) becomes journal flips, `elm_before_scent` becomes chatot summaries, and the
`margin`, `land_frame` and `total_advances` arithmetic is untouched [derived]. `margin_guide` and
`margin_ambiguous` need only the symbol alphabet swapped, and ambiguity gets *less* likely with
5 buckets than with 3 letters [derived].

One more happy coincidence: **the Journal is reached from the in-game menu, and opening that menu
is also what freezes the NPCs** that would otherwise steal advances (§9.1). The bulk-advance
action and the stream-hygiene action are the same action.

### 3.4 What replaces REL is a constant, not a calculation

`advance_context` returns `(rng_calls, elm)` where `rng_calls` is the REL cost — a *seed-dependent*
number of advances consumed before the first observable one. Platinum has no REL, but it does not
have zero leading offset either, and an earlier draft of this note said it did. Evidence:

> *"If you're doing advances through the Journal or Chatter your starting frame will be 23 (It will
> be 12 if you're advancing the frame through the Journal without accessing it from the menu)"*,
> and *"Every time the Distortion World is loaded the frame advances by 11"*

[verified, for the Distortion World Giratina]. So the starting advance frame after a game load is
a **per-venue, per-procedure constant** — a thing to measure and configure, not to compute from
the seed [derived]. That is structurally *easier* than REL (no roamer walk to simulate) but it
needs a number per target that nothing in the repo can derive.

**Mind the off-by-one between the guides and this project.** Clayton and PokeFinder count advances
from the seed itself — advance 0 is the raw state, before anything is spent
(`Core/Gen4/Generators/StaticGenerator4.cpp:57` counts from 0 on top of an `initialAdvances` that
defaults to 0) [verified]. RNG Reporter, which the Smogon guide is written against, calls the first
frame 1. So the guide's *"starting frame will be 23"* is advance **22** here, and its 12 is our 11
[derived — the PokeFinder half is verified, the RNG Reporter half is the convention those tools use
and is worth one empirical check before a venue constant is trusted].

Glass needs none of this: a Seed has no venue, so it is loaded on advance 0 and routed from there,
which is why `PLATINUM_START_FRAME` is 0 and the page does not ask. The constant is a Hunts
concern.

Caveat worth carrying: it is only constant while **no roamer is active**. `MoveRoamerRandom`
retries its route roll until the route differs from the previous one
(`src/roaming_pokemon.c:303-345`), so a map load's cost is seed-dependent when roamers are up
[verified] — a third reason (after §2 and §9.1) to clear Mesprit/Cresselia/the birds before
counting anything.

### 3.5 PokeFinder already draws this fork, in one line

Worth knowing before designing ours, because it is the same decision made by the tool players
already use (`/tmp/pokefinder`, `Admiral-Fish/PokeFinder`):

```cpp
// Core/Gen4/SeedTime4.cpp:77
return roamer ? Utilities4::getCalls(seed, roamer->getSkips()) : Utilities4::coinFlips(seed);
```

HGSS gets Elm calls offset by the roamer skips; everything else gets coin flips from the raw seed
[verified]. The Seed-to-Time form splits the same way — `labelHGSSElmCalls` + `labelHGSSRoamers`
against `labelDPPtCoinFlips` (`Form/Gen4/Tools/SeedToTime4.cpp:188`, `:240-242`) [verified].

So the shape proposed here — one game field choosing between two Seed-A signals, with the rest of
the pipeline shared — is not an invention; it is what the established tool does, which is also a
good sign the player-facing workflow will feel familiar rather than novel.

---

## 4. The decisions

1. **Pitch syntax: buckets, with the exact number in parentheses** [design, round 1]. The guide
   prints each margin cry as `M (41)`, so the label is what you listen for and the number is there
   when you want to be precise or to compare two cries that landed in the same bucket:

   ```
   Route: 26 cries -> frame 142
     1. 22 cries (don't listen)
     2. margin: [ M (41)  H (88)  ML (18)  L (7) ]  ! A-press on frame 142
   ```

   Buckets are `L ML M MH H`, with the number beside each one. **Display only** — there is no
   input to parse (§3.2).

   **The bucket boundaries are PokeFinder's, not invented here**: `L` < 20, `ML` < 40, `M` < 60,
   `MH` < 80, `H` >= 80, on the 0-99 scale above (`Core/Util/Utilities.cpp:72-96`) [verified].
   Five equal 20-wide bands. PokeFinder renders the same pair as `M 41`; parentheses are the only
   difference, and matching its buckets exactly means a pitch read off one tool means the same
   thing in the other.
2. **The margin is what gets confirmed**: the bulk of the route is journal flips (2 advances
   each, nothing to listen to) and the last few advances are chatot summaries whose pitches are
   printed for you to check against (§3.3). `margin_ambiguous` applies and fires less often with
   five buckets than with three letters — and it is load-bearing here in a way it is not in HGSS,
   because it is the only thing standing between a miscount and a silently wrong frame.
3. **Time of day: three buckets, bordered at 04:00, 10:00 and 20:00** [design, round 1] — the
   same three Glass shows for HGSS, rather than the ROM's five.

   The ROM table is `src/rtc.c:153-179`: late night 0-3, morning 4-9, day 10-16,
   **twilight 17-19**, night 20-23 [verified]. Collapsing it to night 20-3 / morning 4-9 /
   day 10-19 keeps the two borders the ROM already has (morning at 4, day at 10) and folds
   twilight into day and late night into night.

   **That collapse happens to be exactly the Dusk Ball's own boundary**, which is the one place
   the buckets are load-bearing rather than cosmetic: the Dusk Ball takes ×3.5 at `TIMEOFDAY_NIGHT`
   or `TIMEOFDAY_LATE_NIGHT` and **not** at twilight (`src/battle/battle_script.c:10961-10967`)
   [verified], so `night` in the three-bucket reading is precisely the set of hours where the Dusk
   Ball is ×3.5, and `day` (twilight included) is precisely where it is ×1 [derived]. So the Hunts
   side can use the same function Glass displays, with no five-bucket variant anywhere.

---

## 5. Hunts: the target side

### 5.1 The encounter

`res/field/scripts/scripts_newmoon_island_forest.s:44` — `StartLegendaryBattle SPECIES_DARKRAI, 50`
[verified]. Lv **50**, not the 40 the unused roamer slot says. The script is
`PlaySE`/`WaitSE`/`Message`/`CloseMessage` then the battle, with no `WaitButton`, so the gap
between the player's A-press and `FieldBattleDTO_New` is fixed-duration — it fits the existing
vector model like any other target, with its own offset [derived].

`res/pokemon/darkrai/data.json`: catch rate **3**, genderless, ability **Bad Dreams**, base Speed
125, Dark/Dark [verified]. Catch rate 3 is the Suicune case the whole solver was built for.

**Moveset at Lv50.** `BoxPokemon_SetDefaultMoves` (`src/pokemon.c:3819-3843`) fills slots in learn
order and then `BoxPokemon_ReplaceMove` (`:3881-3907`) bubbles slots 2-4 up and appends — the same
"last four learnable, in learn order" rule `targets.py` already documents [verified]. Learnset
≤50 is Ominous Wind(1), Disable(1), Quick Attack(11), Hypnosis(20), Faint Attack(29),
Nightmare(38), Double Team(47), so:

> **E1 Hypnosis · E2 Faint Attack · E3 Nightmare · E4 Double Team** [derived]

### 5.2 What that moveset costs us

**None of the four effects is in `sim.MODELLED_TARGET_EFFECTS`** — ids 1 (sleep), 17 (never-miss),
107 (Nightmare), 16 (evasion +1) against the modelled set `{0,4,31,43,46,68,71,72,124,125,136,
140,149,193,210,245}` [verified]. All four exist in `metronome_compass/effects.py`, so they port
and cross-validate the same way the first nine did. Specifics:

* **Hypnosis, accuracy 60** — can sleep *us*, and per `notes/seed_separation.md` a sub-100
  accuracy move on the target's side separates RTC-second siblings fast: an accuracy-60 verdict
  flips on 48% of sibling pairs, so the second axis resolves from the target's own moves without
  a probe of ours [derived].
* **Double Team** — raises Darkrai's evasion. `state.py:136-137` already tracks evasion stages and
  `apply_accuracy_stage` already reads the ROM table, so the plumbing exists; what is new is that
  a long run degrades our own accuracy, up to +6 [derived].
* **Nightmare + Bad Dreams** — Nightmare is 1/4 max HP per turn on a sleeping target, and **Bad
  Dreams is 1/8 max HP to sleeping foes, and is not modelled anywhere** (`battle/stats.py` knows
  only Pressure). Our Pokemon falling asleep is 37.5% max HP per turn [derived].
* **Faint Attack** — accuracy 0, so no accuracy roll (`:2899-2902`), and unmissable incoming
  damage.

### 5.3 The ball story is where Platinum really diverges

Platinum has **no apricorn balls**, and `BattleScript_CalcCatchShakes`
(`src/battle/battle_script.c:10922-10974`) instead gives the conditional balls their multiplier
directly [verified]: Net ×3 (Water/Bug), Dive ×3.5 (water terrain), Nest `40 - level` floored at
×1, Repeat ×3 (registered), **Timer `10 + totalTurns` capped ×4**, **Dusk ×3.5 (night, late night
or cave — *not* twilight)**, **Quick ×4 (turn 1 only)**. Everything unlisted stays ×1.

Two problems, both ours rather than the ROM's:

1. **Nothing maps a ball name to a multiplier today.** `app/facade.py:781` sets only
   `fast_ball_matched`; `HuntConfig.capture_ball_multiplier` is never assigned, so every ball is
   simulated as ×1 [verified]. That was harmless because every HGSS target/ball pairing so far
   really is ×1 (`notes/battle_compass_next_targets.md` §3). On Platinum it is wrong on the
   obvious choices.
2. **Quick and Timer make the multiplier turn-dependent**, and Dusk makes it depend on the key
   seed's own hour. `solver.target_threshold` is already "`b` at one moment" and takes the state,
   and `sim.py:1469` reads the config at throw time, so the change is localised — the multiplier
   becomes a function of the state rather than a constant [derived]. But the solver's goal set and
   dominance key are built on a threshold that does not improve with time, and a Timer Ball's does.

And note the interaction worth exploiting: **a Dusk Ball's ×3.5 depends on the hour, which is
encoded in the key seed itself** (bits 16-23). Glass already derives a time-of-day emoji from the
seed; for a Platinum hunt that same byte decides whether the ball is ×3.5 or ×1 [derived].
Concretely, for a catch-rate-3 target at 1 HP with max HP 150, computed through
`battle.catch.catch_value` / `shake_threshold`:

| Ball | Status | `a` | `b` | per throw |
| --- | --- | --- | --- | --- |
| ×1 | none | 2 | 19784 | 0.83% |
| ×1 | paralyzed | 3 | 21845 | 1.23% |
| Dusk ×3.5 | none | 9 | 29126 | 3.90% |
| Dusk ×3.5 | paralyzed | 13 | 31774 | 5.53% |

`b = 21845` is the figure every HGSS target so far has shared, so a Platinum run on a conditional
ball sits at a genuinely different `b` — which changes the density of four-roll capture windows the
solver steers towards, and therefore how far ahead it has to look. That is a number the solver
needs, not a reason to prefer one target.

**Terrain is the other half of that, and it comes from the tile you are standing on.**
`CalcTerrain` (`src/field_battle_data_transfer.c:467-494`) tests the tile behaviour first — ice,
tall grass, sand, snow, mud, **cave floor**, surfable — and only falls back to the map's battle
background [verified]. So the cave branch of the Dusk Ball check makes it **×3.5 in any cave at
any hour**, and Dive Ball ×3.5 on any surfable tile. For a target in a cave the hour stops
mattering (§5.6), which means terrain belongs next to time-of-day as a per-encounter property of
a target row, not as something derived at throw time.

### 5.4 `BATTLE_START_ADVANCES` — assume 6, with a lead on why

**Decision: carry the verified 6 over to Platinum unchanged for now, and reach for gdb only if a
run disagrees** [design, round 1]. A disagreement is cheap to spot and unmistakable — the true
seed gets eliminated on turn 1 while unrelated candidates survive, which is exactly the failure
`opening_rng`'s docstring describes — so the cost of being wrong is one wasted run, not a silent
error. The rest of this section is the reasoning that makes 6 the right guess, and the thing to
re-read if a run does disagree.

`notes/battle_compass_next_targets.md` §2 deleted the "4 bellShimmer + 2 Pressure" story and kept
6 as a general figure. Platinum offers a candidate explanation for the 4:
`BattleContext_InitCounters` rolls `speedRand[i]` for **`MAX_BATTLERS` = 4** battlers
(`src/battle/battle_lib.c:2019-2025`), called exactly once at battle init
(`src/battle/battle_controller_player.c:185`) [verified]. The per-turn block does the same four
(`:858-861`), which is where our verified `BEFORE_TURN_ADVANCES = 4` comes from.

That makes **4 + 2-for-an-announced-entry-ability** a plausible reading of the HGSS 6 [derived].
It is also the one concrete reason the Platinum figure might differ: **Bad Dreams is not announced
on entry**, so if the 2 really are an announcement, Darkrai would be 4 rather than 6. That is a
hypothesis, not a finding — per CLAUDE.md a verified count changes only on a ground-truth capture,
and nothing here is one. Hence the decision above: assume 6, and if the first Darkrai run cannot
match any candidate, this paragraph names the first thing to try (4) and the capture that would
settle it.

### 5.5 Access

Newmoon Island needs the **Member Card**, which is event-distribution only. That belongs in
`targets.EncounterAccess`-adjacent prose, not in a warning — same call the Silver Wing got.

### 5.6 Giratina is two different fights, and `STATIC_ENCOUNTERS` cannot hold both

Giratina can be fought in the **Distortion World** during the story, or at **Turnback Cave** later
if you knock it out or run. Both at Lv47 [verified]:

```
res/field/scripts/scripts_distortion_world_giratina_room.s:69
    StartGiratinaOriginBattle SPECIES_GIRATINA, 47
res/field/scripts/scripts_turnback_cave_giratina_room.s:35
    StartLegendaryBattle SPECIES_GIRATINA, 47
```

They are **not the same encounter**, and the differences are all load-bearing:

| | Distortion World | Turnback Cave |
| --- | --- | --- |
| Forme | **Origin** — `Encounter_NewVsGiratinaOrigin` calls `Pokemon_SetGiratinaOriginForm` (`src/encounter.c:982`) | Altered |
| Base stats | 150/**120**/**100**/90/**120**/**100** | 150/**100**/**120**/90/**100**/**120** |
| Ability | **Levitate** | **Pressure** |
| Terrain | forced `TERRAIN_GIRATINA` (`src/encounter.c:989`) | `TERRAIN_CAVE` — `CalcTerrain` returns it for a cave-floor tile (`src/field_battle_data_transfer.c:481`) |
| Dusk Ball | ×3.5 **only at night** | **×3.5 always** (the cave branch) |
| Starting advance frame | 12 / 23, with an 11-advance map load (§3.4) | its own constant, unmeasured |

Stats and ability from `res/pokemon/giratina/forms/origin/data.json` vs `.../giratina/data.json`
[verified]. Catch rate is 3 and types Ghost/Dragon in both.

Three consequences:

1. **`targets.STATIC_ENCOUNTERS` is keyed by species slug**, and this is the first target where one
   species means two encounters with *different stats and a different ability*. The version-split
   rows (Ho-Oh, Lugia) at least differ only in level, so `encounter_level` could tell them apart;
   here the level is **the same 47** and nothing distinguishable is left. The key has to become
   something like `(species, venue)` [design].
2. **`has_pressure(species)` is actively wrong for the Distortion World fight.** It reads the
   species row, so it returns True for Giratina — and the Origin forme has Levitate. That is
   precisely the failure `app/facade.py:783-788` warns about in its own comment: assuming Pressure
   where there is none halves every PP budget the solver plans against, and the run quietly runs
   out of moves earlier than the plan said. Ability has to come from the *encounter*, not the
   species, as soon as a forme target exists [derived].
3. **Levitate is not inert**, unlike Pressure-vs-nothing: it makes Ground moves miss outright. Any
   party move of that type is a dead slot against the Origin forme.

**The moveset is the cheap part.** The learnsets are identical through Lv47, so both fights have
the same four slots — last four learnable in learn order: **Ominous Wind, Ancient Power, Dragon
Claw, Shadow Force** [derived]. Of those, effects 140 (Ominous Wind *and* Ancient Power both),
and 0 (Dragon Claw) are already in `sim.MODELLED_TARGET_EFFECTS`; only **Shadow Force (effect 272)
is missing — and it is already implemented** in `metronome_compass/effects.py:2828` as
`_eff_charge_fire`, Group A "turn 1 sets lock, no rolls" [verified].

What Giratina needs, then, is structural rather than per-move: the `(species, venue)` key, the
encounter-level ability, and somewhere for a forme to live in `base_stats.json` (§1). Those three
are shared infrastructure — every later forme target wants them — so they are worth building
properly rather than around.

Access: the Distortion World fight is story-gated and unmissable; the Turnback Cave one needs the
three-pillar room navigation. Neither is a field-move requirement, so neither belongs in
`EncounterAccess`.

---

## 6. Calibration is the real blocker, not the RNG

`app/calibration.py:47` and `:67` are the only two fit paths, and they take `kind == "metronome"`
and `kind == "safari"` runs. **Both tools are HGSS-only.** Battle Compass runs are saved as
`kind="battle"` and are explicitly *"Diagnostic only -- no fit consumes these"*
(`app/facade.py:1732-1740`) [verified].

So a Platinum profile can never improve its own timer model: it is stuck on the bundled
"Standard" model forever, and the Hunts window has to be wide enough to contain the truth on
every run. That is survivable (nothing needs to *hit* a seed — only to contain it), but it is a
standing tax, and it will show up as "why is my delay window 60".

A `kind="battle"` run already carries `a_seed`, `b_seed` and `vector_ms` — exactly what
`calibrate_timer` wants [verified]. **Making battle runs fittable is the single highest-leverage
piece of this whole effort**, it is the only way Platinum calibrates at all, and it helps HGSS
too. Worth doing before, not after, the first Platinum hunt.

Separately: Platinum's power-on-to-`InitRNG` path is a different intro, so the *achievable* delay
range differs from HGSS — the guide puts it at *"For DPPt minimum delay should be around 650"*
[verified]. Nothing in code assumes a range, and models live on the profile (= one cartridge), so
this separates itself — but a Platinum profile's first runs will look like wild outliers against a
HGSS-fitted Standard model [derived].

**Parity, and a cross-confirmation of `notes/glass.md`.** The guide's fix for landing on the wrong
delay parity is to *"insert either a FRLG or RSE cart into your DS"* or to *"change the year in
your DS clock... by 1"* [verified]. The second one only works because the year is folded into the
seed's low 16 bits alongside the delay — exactly the `delay = (key_seed & 0xFFFF) - (year - 2000)`
relation Glass derives and is the only tool to surface. So the year field Glass already asks for
is also the parity lever, which is worth saying in the UI copy [derived].

---

## 7. Glass is the small one

Per `notes/glass.md`, Glass is four steps, and only two of them change:

| Step | Platinum |
| --- | --- |
| Configure (label, key seed, initial time, default frame, notes) | **unchanged** — delay arithmetic and the time picker's year stamping are formula-identical |
| Seed A candidates (roamer starts + R/E/L + Elm) | **replaced** — coin-flip narrowing; `seed_a_defaults`' roamer positions become meaningless, `match_parity` and the two windows stay |
| Seed A advances (Elm to pin the frame, chatot+Elm route) | **same shape, new symbols** — pitches to pin, journal flips + a pitch margin to route (§3.3); plus a per-venue starting frame instead of REL (§3.4) |
| History | `elm_heard` wants a game-neutral sibling (flips heard / cries made) |

Time-of-day emoji: **unchanged** — `safari_encounters.time_of_day`'s three buckets with their
existing 04:00 / 10:00 / 20:00 borders are what Platinum shows too (§4.3), so this is not even a
game-dependent call.

Glass still never touches Seed B, so none of §5 or §6 applies to it. **Glass is shippable for
Platinum without any battle-side work at all** — it needs MT19937, the pitch model, the input
syntax, and the game field. That is the natural first milestone [design].

---

## 8. The game field, and the gating it finally forces

`Profile.version` is a free-text `"HeartGold" or "SoulSilver"` (`app/models.py:286`) that
**nothing ever branches on** — stored, round-tripped, rendered, and never read
(`app/facade.py:171`, `index.html:7587-7590`) [verified]. Meanwhile `targets.py:14-16` says
outright *"This profile is SoulSilver"* and ships SoulSilver's rows for the two version-split
encounters, with `encounter_level` as a tripwire for a HeartGold player [verified].

So adding a `game` enum (HeartGold / SoulSilver / Platinum, with Diamond and Pearl selectable but
refused everywhere) is both the Platinum prerequisite *and* the fix for a latent HeartGold bug.
What it then has to gate:

* **Expeditions** — HGSS only (chart, Safari Compass, Metronome Compass, metronome users).
* **Seed A identification** — HGSS: roamers + Elm. Platinum: flips + pitch. This is the fork, and
  it is reached from Glass *and* Hunts, through `facade.metronome_seed_a`,
  `metronome_key_seed_info`, `safari_compass_identify_frame` and `safari_compass_plan_frame` —
  four facade methods currently named after the HGSS tools they came from.
* **Balls** — the UI's `BALLS` list (`index.html:3883`) offers apricorns to everyone; Platinum
  gets the Park/Heal/Cherish side instead, and `battle/catch.py`'s apricorn helpers become
  HGSS-only paths rather than shared ones.
* **Targets** — Platinum rows, and the version-split rows become genuinely version-keyed.

Time of day is deliberately *not* on that list: §4.3 settles it as the same three buckets in both
games, so it stays one shared function.

`app/portability.py` carries neither Hunts nor Seeds today, so export needs nothing [verified].

---

## 9. Verification list

Three items that were on this list are now closed:

* ~~`BATTLE_START_ADVANCES` on a Platinum legendary~~ — **assumed 6, deferred** (§5.4). Not
  blocking; a wrong guess costs one run and announces itself.
* ~~Does a save-continue consume MT calls before the Poketch is reachable?~~ — **no**.
  PokeFinder's `coinFlips` seeds MT with `advances = 0` (§3.1), and the decomp's only
  save-continue-reachable MT consumers are new-save init funcs. Treated as settled.
* ~~Does anything advance the LCRNG while standing still?~~ — **yes, and there is a known fix.**
  The guide confirms it as a first-class hazard: *"Any NPC that randomly moves will advance frames
  by 1 for each random movement... it is advisable to attempt your captures in areas with little or
  no NPCs"*, and for the rest: *"you must press X to bring up the menu the moment you enter the
  in-game world. This freezes all NPCs in place and stops them from making any unnecessary
  advancements"* [verified]. That matches the decomp exactly —
  `src/overlay005/ov5_021EB1A0.c:640-644` is a billboard sprite animation spending
  `LCRNG_Next() % 16` roughly every 32 frames, and Darkrai's own overworld sprite *is* a billboard
  (`src/overlay005/object_event_gfx_data.c:1716`) [verified]. So **the route guide must tell the
  player to open the menu on entry**, before the first journal flip — which costs nothing extra,
  since the Journal lives in that menu anyway (§3.3).

What is left, none of it blocking the Glass milestone:

1. **The starting advance frame for each Platinum venue** (§3.4) — a constant per *venue* and
   procedure, measured rather than derived. One per target, and **two for Giratina**, since the
   Distortion World and Turnback Cave fights are different encounters (§5.6). Needed before the
   first hunt at a given venue, cheap to get from one run, and the published Distortion World
   figures (12 / 23, with an 11-advance map load) show the shape of the answer.
2. **Whether five pitch buckets are distinguishable by ear in practice** — the whole 0-99 range is
   under four semitones, so each band is ~77 cents. The *boundaries* are settled (§4.1, they are
   PokeFinder's); the error rate is not, and the guide is candid that there is one: *"It may take
   multiple tries until you can match the pitches with their categories, and even then there's
   room for error"*, with the advice to record a distinctive custom Chatter and to practise *"in an
   area with no NPCs"* [verified]. Since the pitch is a confirmation rather than an input, a
   misread costs a false alarm rather than a wrong answer — but a margin that cries wolf gets
   ignored, so the consequence is still: **keep the margin short**.
3. **Does HGSS have the same chatot pitch call?** PokeFinder computes `call(prng % 3)` and
   `chatot(((prng % 8192) * 100) >> 13)` from the *same* roll for every Gen 4 state
   (`Core/Gen4/States/State4.hpp:49`), i.e. it treats pitch and Elm letter as two readings of one
   advance and offers both columns regardless of game [verified of PokeFinder; not of the HGSS
   ROM]. If `pokeheartgold`'s `Sound_Impl_PlayChatotCry` really does roll the same way, then
   **HGSS's blind bulk flips become verifiable too** — a free win for the existing tools out of
   work done for Platinum.

---

## 10. As built — the Glass milestone (clayton-6xu.1, clayton-6xu.2)

Six beads closed; Glass works end to end on a Platinum profile. Differences from the design
above, all small, plus the two places reality was better than the plan.

**The route structure needed no redesign at all**, which §3.3 predicted and the code confirms:
`plan_advances` is called unchanged by both games, with `chatot_flips` counting Journal flips and
`elm_before_scent` counting chatot cries. The one piece of Platinum-specific arithmetic is a
function with a seven-line docstring: **the bulk must come out even**, because there is no half
Journal flip (HGSS tolerates an odd bulk only because half a chatot flip is one cry, which is a
real action). The leftover advance becomes one more cry, lengthening the readable margin — the
better place for it anyway.

**`safari_advance` was parameterised, not forked.** `_all_start_positions` now works over any
sequence with an optional `match` hook, `frame_candidates` takes a signal plus a matcher,
`margin_guide` takes `render`/`render_bracket`, and `margin_ambiguous` takes a confusability
predicate. A `str` observation is still raw Elm input and is still cleaned, so all four HGSS
facade callers are untouched — asserted by its own test class rather than assumed.

New in `claytonlib/`: `coin_flips.py` (MT19937 seeded the ROM's way, `flip_sequence`,
`flips_match` as a prefix test), `chatot_pitch.py` (the pitch value, PokeFinder's buckets, the
`M (41)` form and the parser), `games.py` (the registry), `platinum_advance.py` (`pitch_context`,
`identify_frame`, `plan_route`, `generate_flip_candidates_near`, `filter_flips`).

Decisions made during the build, none of them in the design above:

* **Pitch is output only, and the frame is never "found"** [design, round 2 — and the one real
  design error of the build]. The first implementation mirrored HGSS: a text box for the pitches
  heard, `identify_frame` searching for them in the seed's sequence, a ±10 tolerance so a numeric
  reading could be matched. All of it answered a question nobody had. The player is not trying to
  discover their advance frame — they know it, because they loaded on a known frame and counted
  what they did. The pitch is the receipt, not the measurement.

  Removed as a result: `PitchObservation`, `parse_observations`, `observations_match`,
  `DEFAULT_TOLERANCE`, `platinum_advance.identify_frame`, the `platinum_identify_frame` facade
  method, the `match` hook that had been added to `frame_candidates` (no caller left — so
  `safari_advance`'s search went back to the string form it had), and the pitch text box. The
  Glass frame panel for Platinum now has exactly one input: where you want to go.

  The tolerance deserves its own epitaph, because it was a well-argued answer to the wrong
  question. ±10 was chosen to be a bucket's width so that a number carried the same information
  but *centred* on the reading rather than snapped to an inaudible edge — a true 39 heard as "about
  40" is eliminated by the bucket `M` and accepted by `40`. That reasoning is sound and it does not
  matter, because nobody should have been typing either one.
* **Ambiguity is judged in buckets**, and it got *more* important rather than less: with the frame
  counted instead of measured, the margin is the only error detection the route has. "Would a 1-2
  frame miscount be invisible?" is a question about what the player would *hear*, and they hear a
  bucket.
* **The guide puts numbers only in the margin.** `M (41)` for the bracketed cries, bare buckets
  for the surrounding context — which is what "include the numeric in parenthesis for the margin"
  asks for, and it keeps the line readable at a 30-advance route.
* **An unset `game` is permissive, not refused.** Every profile that predates the field has one
  and they are all HGSS, so refusing them would lock existing players out of tools they were
  already using to enforce a field they never filled in. `tool_refusal` returns `""` for unset,
  the signal defaults to the Elm shape (`LEGACY_DEFAULT_SIGNAL`), and the page shows
  `UNSET_HINT` so the default is visible rather than silent. Diamond and Pearl *are* refused, at
  the facade rather than in the page, so the gate holds however a seed is created.
* **`Profile.version` became `Profile.game`, migrating at read time.** `canonical_game_key`
  accepts the key, the display name and `"Heart Gold"`-style spellings, so no stored profile
  needed rewriting; `to_dict` still writes the display name under `version` so an export read by
  an older build still names the game.
* **`elm_heard` has no Platinum sibling.** A Platinum frame is counted rather than heard, so
  there is nothing the player reported to record; the entry carries `frame` and `routed_to` —
  where they started and where they went — and `elm_heard` stays HGSS-only.
* **There is no flips-to-frame handoff.** In HGSS the Elm calls typed to narrow Seed A *are* the
  calls heard since it loaded, so they prefill the frame step. Coin flips say nothing about the
  advance frame — the same property that makes them free to use cuts both ways — so
  `glassPickSeedA` hands over nothing on Platinum.
* **The hygiene note is in the UI, not just here.** The facade's `seed_a_signal` descriptor
  carries it and the frame panel prints it: open the menu on entry to freeze the NPCs, and check
  the Chatot has a recorded cry or the cry spends no advance at all. Both are invisible when
  forgotten, which is exactly why they cannot live only in a notes file.

Tests: `tests/test_platinum_signals.py` (28 — MT against published reference vectors, the pitch
formula, PokeFinder's bucket boundaries), `tests/test_platinum_advance.py` (37 — the Elm
primitives' unchanged behaviour, the route, the candidate table), `tests/test_games.py` (35),
`tests/test_app_glass_platinum.py` (29), plus seven Glass guards in `tests/test_app_web_ui.py` —
two of which now assert the *absence* of a pitch input, since that is the thing worth preventing
from coming back. Full suite green at **3094**.

Still open for Glass, and deliberately: the real-world pitch error rate (§9.2), which wants a run
rather than a test. The per-venue starting frame is plumbed (`start_frame` on `plan_route` and the
facade) and unused, because Glass has no venue — see §3.4 for the 1-based/0-based conversion to
apply when a guide's figure is adopted.

---

## 11. As built — the Hunts milestone, minus the legendaries (clayton-6xu.3)

Four beads closed. A Platinum hunt now configures, identifies its seed, routes to a frame, throws
the right ball and feeds its own calibration. What is deliberately **not** here is any specific
legendary: Darkrai's four target effects plus Bad Dreams (clayton-6xu.3.3) and Giratina's formes
plus Shadow Force (clayton-6xu.3.4) remain open.

### The balls

`claytonlib/battle/balls.py` is new: a registry carrying per-game availability and, per ball,
`ball_effect(name, rate, ThrowContext) -> BallEffect`. One call covers both ROM mechanisms, so no
caller has to know which kind of ball it is holding.

`HuntConfig` takes the ball **by name** plus a `ThrowContext` and exposes `ball_effect_at(turn)` /
`ball_multiplier_at(turn)`; `solver.target_threshold` and the simulator's throw both ask per turn.
`state.turn` turns out to be the ROM's `totalTurns` exactly — it is incremented at the *end* of a
turn — so the Quick Ball's "first turn" and the Timer Ball's climb line up with no adjustment.
The old explicit `capture_ball_multiplier` / `fast_ball_matched` pair still wins when no name is
set, which is how every existing fixture keeps meaning what it meant.

**Time of day is derived, not configured.** The in-game hour is bits 16-23 of the key seed, so a
hunt that knows which seed it aims at already knows whether the Dusk Ball's night applies; asking
would be asking the player to restate it and to get it wrong independently. Terrain *is*
configured (`Hunt.terrain`), because it comes from the tile you stand on and nothing in the seed
says which tile that is. Registration (`Hunt.target_registered`) likewise, for the Repeat Ball.

Two things fixed in passing, both pre-existing:

* **`ball_key` has to NFKD-normalise.** `"é".isalnum()` is True in Python, so stripping
  non-alphanumerics leaves the accent in place and `"poke ball"` — what anyone types — missed
  `"Poké Ball"`. `damage.item_key` has the same shape and no accented item to trip on it.
* **`catch.py` called 40 the Nest Ball's ceiling.** It is the constant the level is subtracted
  *from*; the real ceiling is 39, at level 1.

### Seed A, and the frame

Both pages now fork on one `seed_a_signal` descriptor, so neither branches on a game's *name*.
`hunt_run_setup` carries the descriptor, the venue's `start_frame` and the game's refusal;
`create_hunt` refuses Diamond/Pearl at the facade exactly as `create_seed` does.

A Platinum hunt has **no frame-finding step**: `pinnedFrame` is set from `start_frame` when the
run page opens, and the route renders Journal flips + Chatot cries through the same renderer that
draws the HGSS plan — the two payloads differ in nouns, not in shape. The run record keeps its
`elm_calls` / `chatot_flips` column names, because the two advance units really are the same sizes
in both games (§3.3), so the numbers mean the same thing.

Fixed in passing: an earlier bulk rename in this work had renamed the `frameObserved` /
`framePrefill` **declarations** in the Safari-compass and Hunts page state without their uses.
Neither was visibly broken — JavaScript simply created the key on first write — but each object
had a dead field and a shadow one. The Safari compass went back to its old names and the Hunts
page's uses came forward.

### Calibration — the piece that was actually blocking

`_record_for_battle_run` + `preview_battle_fit`, reached through
`facade.preview_battle_calibration`. A battle run already carried everything the fit wants, so the
gap was a missing record builder — except that `hunt_session._candidate_row` wrote only
`frame`/`second`, and now also writes `delay` and `time`. That is literally the expression
`candidates.generate` used to build the seed, read back; carrying it on the row keeps a saved run
self-describing, so the fit never depends on the hunt's configuration still saying what it said
during the run.

**It is a separate fit, not pooled with the metronome runs** [design]. A metronome run loads and
walks to a Chansey; a battle run loads and presses A on a static encounter. Whether those two load
paths share an offset is **unmeasured**, and pooling them would average over a difference instead
of measuring it — which is the mistake `fit_safari_offset` exists to avoid for the Safari path. So
one fit per observed path. When a profile has enough runs of both kinds, comparing the two fits
*is* the measurement of whether they could have been pooled.

`save_hunt_run`'s "Diagnostic only -- no fit consumes these" docstring is corrected, and this is a
free gain on HGSS too: a Suicune or Lugia run used to be thrown away.

### One dependency dropped

`clayton-6xu.3.1` was filed as depending on `clayton-957.35.4` (the encounter-keyed target table).
It did not need it: terrain and registration went on the **Hunt** rather than the target row,
which is where per-visit configuration already lives. When 957.35.4 lands, moving terrain onto the
row is a simplification rather than a prerequisite. The two are linked instead, and 957.35.4's
notes carry the Giratina escalation that makes encounter-keying mandatory rather than merely tidy.

Tests: `tests/test_battle_balls.py` (29 — availability, the ROM's conditional table transcribed
independently, the two turn-dependent balls moving in opposite directions, unmodelled rules
declaring themselves) and `tests/test_app_hunt_platinum.py` (39 — the gate, the game-scoped
picker, the derived time of day, the multiplier reaching the solver per turn, the Seed A fork, and
a class asserting the HGSS path is untouched including Lugia's Fast Ball ×4). Full suite green at
**3162**.

## 12. As built — Darkrai (clayton-6xu.3.3)

The first Platinum target, and the first one whose danger is not a hit. Everything in §5.1-5.2 held
up; what follows is what the implementation had to add, and the three things the ROM said that the
design doc had guessed at.

### 12.1 The table is keyed by encounter now (clayton-957.35.4, structurally)

`battle_compass/targets.py` went from `STATIC_ENCOUNTERS: dict[str, (level, moves)]` to
`ENCOUNTERS: dict[str, Encounter]`, where the key is an **encounter** key and the row carries
`species, level, moves, games, ability, forme, where`. For every target met once the key simply *is*
the species slug, so `moveset("suicune")` keeps working; `resolve(name, game)` accepts either and
raises for a species met twice (which is Giratina, clayton-6xu.3.4, and nothing else yet).

Two things fall out of `games` that were latent bugs rather than new features:

* **The HeartGold hole this module's own docstring admitted to is closed.** It said "This profile is
  SoulSilver" and shipped SoulSilver's rows; a HeartGold player entering Lv45 for Ho-Oh passed the
  level cross-check and would have been simulated against four moves their bird does not have. The
  row now exists only in `soulsilver`, so the refusal is by cartridge, not by level.
* **"Not a configured target" stopped being a lie.** A Platinum profile asking for Lugia is told it
  is SoulSilver's and shown what Platinum does have. The two mistakes — a typo and the wrong
  cartridge — need different fixes, and one message could not serve both.

An unset game filters nothing, the same choice `games.tool_refusal` makes and for the same reason:
every profile written before the field existed has none.

`target_ability(name, game)` is the row's ability falling back to the species' slot 0, and both
`HuntConfig.target_has_pressure` and the target `Battler`'s own `ability` now come from it. The
target Battler carried **no ability at all** before, which was invisible for as long as the only
abilities in play affected damage.

### 12.2 The four effects

| Effect | Move | What it needed |
| --- | --- | --- |
| 1 | Hypnosis | `act_target` applying `applied_status` **at all** |
| 107 | Nightmare | a volatile that coexists with sleep, plus a residual |
| 16 | Double Team | `self_stat_raise` on the outcome, and `apply_stat_raise` |
| 17 | Faint Attack | nothing — accuracy 0 already skips the roll |

**Effect 1 is the find.** `act_target` applied damage, stat drops, secondary statuses and Static's
paralysis — and threw `applied_status` on the floor. Nothing fired it because no configured target
had a status move, so the gap was invisible: the duration roll would have been spent and the sleep
discarded, leaving the simulator attacking through turns the game had us asleep for. Every
prediction after the first Hypnosis wrong, with no contradiction raised — exactly the failure
`MODELLED_TARGET_EFFECTS` exists to prevent, sitting in the code that reads the table.

Effect 17 is in the table with no code behind it, which is worth saying out loud: its script is
`CalcCrit` then `CalcDamage` with no accuracy check (`effect_script_0017.s`), which is what
`execute_move` already does for an accuracy-0 damaging move. Two rolls, not three.

### 12.3 The residuals, in the ROM's order

`MON_COND_CHECK_STATE_*` (`src/battle/battle_controller_player.c:1259-1272`) orders them
**Leftovers → Leech Seed → poison → toxic → burn → Nightmare → Curse → Bind → Bad Dreams**
[verified], so the end-of-turn block applies leftovers, burn, Nightmare, Bad Dreams. None of the
four spends a roll, so the order decides only *which one faints us* — which is enough to matter,
because each is clamped at zero.

* Nightmare is `maxHP / 4`, Bad Dreams `maxHP / 8`, both through `BattleSystem_Divide`, which never
  returns 0 — so the floor is 1, like every other residual here [verified].
* **Nightmare is gated on being asleep, not on carrying the flag.** The ROM's `else` branch clears
  the volatile with no damage the moment the holder is awake, so waking up is the cure and the
  rolled sleep duration is what decides the total.
* **Magic Guard skips burn, Nightmare and Bad Dreams alike** — each case opens by checking it — and
  **Heatproof halves the burn tick**. Neither is in a planned party; both were read off the same
  scripts while this was being wired, and a residual that is wrong by one is wrong forever, because
  every HP comparison is exact.

### 12.4 Three things the ROM settled that §5 had not asked

**Sleep duration is `Random 3, 2`**, and `BtlCmd_Random` adds 1 to the range
(`src/battle/battle_script.c:3200-3207`), so it is `2 + rand % 4` — byte-identical to the HGSS
figures `SLEEP_DURATION_MIN`/`SLEEP_DURATION_SPAN` already hold [verified]. One roll.

**Early Bird decrements the counter by two** (`:2442-2452`), so a rolled duration of 2 costs its
holder no turn at all — and halves what the residuals take. Noctowl and Xatu are ordinary things to
bring, so this is modelled rather than noted.

**Insomnia and Vital Spirit refuse sleep outright**, checked at the very top of
`subscript_fall_asleep` and landing on the same `MOVE_STATUS_NO_MORE_WORK` flag as "is already
asleep" — the failure whose advance cost is verified (test1.jsonl), so the cost follows. Leaf Guard
is deliberately *not* modelled: it blocks sleep only in sunshine and nothing in any configured
moveset can set sun.

### 12.5 The clock, and why it gets its own warning

`survivability_warnings` priced hits, which is the only question a target without sleep can pose.
Darkrai poses another: Hypnosis costs no HP, and then 37.5% of max HP a turn for as long as the
sleep lasts. A measured consequence, not a design choice:

> **Nothing survives a maximal sleep against the full moveset.** Four ticks at three eighths is
> 150% of *any* Pokemon's max HP. Levelling cannot fix it — the figures are fractions of max HP.

So `_sleep_clock_warning` fires for every party member against a complete Darkrai, and the gate is
still real: Bad Dreams *alone* is an eighth a turn, which over at most four turns is half of max HP,
so a Darkrai under Lv38 (no Nightmare yet) cannot kill through sleep at all and warns nobody.

And the trap worth knowing before the run: **a bag action does not tick the sleep counter.** The
decrement lives in `BattleControllerPlayer_BeforeMove`'s status-disruption state
(`:3145-3149`), which is reached only when the battler's action is a move [verified]. So throwing
balls while asleep keeps us asleep and keeps the residual running; only *trying to move* spends the
sleep down. The solver gets this right for free — `simulate_turn` applies the residuals and the
solver already prunes any path that spends a Pokemon — and a spot check of a sleeping, nightmared
Smeargle at 1-HP-Darkrai had it plan a heal mid-sequence rather than a third throw.

### 12.6 The mid-turn status mirror (a live HGSS gap, found here)

The run page added "is asleep" to the *target's* options when a Spore of ours landed earlier in the
same turn, because the snapshot's option lists describe the state the turn **opened** in. The mirror
— a status the TARGET landed on **us** — did not exist, which left two turns unreportable:

* Darkrai's Hypnosis landing first, after which our move simply does not happen;
* **Latios's Dragon Breath paralysis**, which has been a configured target all along. Its 30% proc
  resolves before our half of the turn, and "was fully paralyzed" was not on offer.

`hrStatusTargetJustApplied` is the mirror of `hrStatusWeJustApplied`, with the same asymmetry
between the two statuses: sleep *replaces* our half of the turn (one line, nothing to report) while
paralysis only *might* stop it, so it joins the options.

## 13. As built — Giratina, both of it (clayton-6xu.3.4)

The target the encounter-keyed table exists for, and the first two-turn move on either side.

### 13.1 The two fights

```
res/field/scripts/scripts_distortion_world_giratina_room.s:69   StartGiratinaOriginBattle SPECIES_GIRATINA, 47
res/field/scripts/scripts_turnback_cave_giratina_room.s:35      StartLegendaryBattle      SPECIES_GIRATINA, 47
```

[verified] **Both Lv47**, so `encounter_level`'s cross-check — the thing that catches a HeartGold
player reaching for SoulSilver's Ho-Oh — cannot separate them at all. And the moveset cannot
either: the form's own `learnset.by_level` is identical to the species' through 47 (they diverge at
Heal Block, 50), so both are Ominous Wind(10) / Ancient Power(20) / Dragon Claw(30) / Shadow
Force(40) [verified].

What separates them is forme data:

| | base stats | ability |
| --- | --- | --- |
| Altered (Turnback Cave) | 150/100/120/90/100/120 | **Pressure** |
| Origin (Distortion World) | 150/120/100/90/120/100 | **Levitate** |

Keyed **by forme** rather than by venue — `giratina-origin`, `giratina-altered` — for three
reasons that line up: the forme is what distinguishes the fights mechanically, it is how players
name them, and the key is then also the `base_stats.json` row the stats come from, so the one
thing the player types resolves everywhere. `resolve("giratina")` raises and names both keys with
their venues, which is the right answer for a free-text field.

### 13.2 The forme rows

`one-offs/populate_base_stats_from_rom.py` now emits **all twelve** form rows, not just Giratina's:
the personal table holds them past dex 493 (slots 496-507) and `Pokemon_GetFormNarcIndex` confirms
the mapping (Giratina form 1 = 501). HGSS's table and Platinum's forme JSON agree byte for byte on
Origin, so the existing decomp source needed no change.

A form row carries `forme_of` and **shares its base species' dex number**, because that is what a
dex number is. So the file's invariant moved: "one row per dex number" is now a statement about
rows *without* `forme_of`, and `tests/test_base_stats_rom.py` partitions on exactly that.

One consequence worth stating, because it is a behaviour change: `species("giratina")` used to
resolve to `giratina-altered` through the bare-name suffix fallback, since that was the only
match. With both formes present it raises and names them. That is the honest answer — the two
differ in ability and stat line, so picking one silently would mis-simulate whichever fight the
player meant.

### 13.3 Shadow Force (effect 272) costs three separate things

`res/battle/scripts/effects/effect_script_0272.s` [verified]:

1. **The charge turn spends nothing.** Its branch sets the vanish and `End`s without reaching
   CalcCrit/CalcDamage, and `CheckMoveHitAccuracy` returns before its roll because "charge-up
   moves don't consider accuracy on their first turn"
   (`battle_controller_player.c:2905-2907`). Zero rolls — cross-validated against
   `metronome_compass.effects._eff_charge_fire`, which also spends none and was fit to the
   Blackthorn ground truth.
2. **The fire turn spends no SELECTION roll.** A locked battler's `Battler_CanPickCommand` is
   FALSE, and command selection is skipped entirely (`:334-338`) — the ROM relocks it into
   `moveLockedInto` without consulting PP (`:1885-1888`). One advance fewer, and getting it wrong
   would desynchronise every turn after a Shadow Force. It also means **PP is spent on the charge
   turn only** (`ppDecremented` is set TRUE on the skipped selection): charging twice for a 5-PP
   move would empty it in two uses, shrink `usable_slots` early and change the selection modulus.
3. **While it is away, everything of ours misses — after spending its rolls.**
   `BattleSystem_CheckMoveHit` calls `CheckMoveHitAccuracy` *then* `CheckMoveHitOverrides`
   (`:219-220`), so the accuracy roll is spent and the semi-invulnerable verdict is layered on
   afterwards. A turn against a vanished target therefore costs exactly what an ordinary miss
   costs. An accuracy-0 move is not exempt: Faint Attack spends no accuracy roll and still cannot
   reach something that is not there.

**And a ball still works.** The catch path has no invulnerability check anywhere in it, so Shadow
Force costs us two turns of *moves* and nothing of the capture. Verified by reading the whole
`SEQ_CATCH_MON_*` sequence: no `moveEffectsMask` test appears in it.

The one derived figure: the charge turn is **successful**, so the turn keeps its two
post-successful-move advances. The move went off and printed a message, which is every other
successful move's situation — but nothing has watched a charge turn in the emulator, so this is
the line to check first if a Giratina run cannot match any candidate.

Which turn of ours is lost depends on **speed**, and the answer is counter-intuitive: a Smeargle
lead outspeeds Giratina, so on the charge turn our move resolves *before* it vanishes and lands
normally. It is the **fire** turn we lose — the vanish is still up when we move, and the flag comes
off only once the move goes off (`_055`).

### 13.4 Levitate was a live bug, not a Giratina detail

`unsupported_attacker_reason` refused **Levitate** as "changes damage and is not modelled", because
`UNMODELLED_DAMAGE_ABILITIES` mixed attacker-side and defender-side abilities in one set. It was
harmless only because the target's `Battler` carried no ability at all. The moment the facade
started setting it from the encounter row, every Levitate holder — **both Lati twins** as well as
Giratina Origin — was reported as an unmodelled *attacker* and dealt **zero damage**. That is not a
conservative error; it is a wrong prediction that would have contradicted the true seed on the
first hit.

Two fixes, and the second is the real one:

* the set is split into `UNMODELLED_ATTACKER_ABILITIES` (Huge Power, Guts, Sniper, Adaptability…)
  and `UNMODELLED_DEFENDER_ABILITIES` (Thick Fat, Filter, Wonder Guard…), and the attacker check
  reads only the first;
* **Levitate is in neither, because it is fully modelled.** In Gen 4 it grants immunity to Ground
  moves and does nothing else whatsoever, so it is a type rule rather than an unknown multiplier.
  `Defender.ability` exists for that one reading.

### 13.5 Measured in passing: half its moveset cannot touch a Normal lead

Ominous Wind and Shadow Force are both **Ghost**, which does nothing at all to a Normal type. So
against a Smeargle lead, Giratina has two live moves rather than four, and two of its four turns
are free. The immunity is the type chart's, so it was already modelled — it is recorded here
because it changes how the fight reads: the danger is Ancient Power and Dragon Claw, and Ancient
Power is also the one that can raise every stat it has.
