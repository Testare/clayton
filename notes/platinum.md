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

## 14. As built — Heatran (clayton-6xu.6)

`StartLegendaryBattle SPECIES_HEATRAN, 50`
(`res/field/scripts/scripts_stark_mountain_room_3.s:83`) [verified]. Catch rate 3, Fire/Steel,
**Flash Fire**, base 91/90/106/77/130/106 — and a gender, 50/50, which makes it the first
configured target that has one at all. Nothing reads that: the Love Ball is the only mechanic
that would, and Platinum has no apricorn balls.

Moveset at Lv50 from its own `learnset.by_level`: **Metal Sound(25) / Crunch(33) / Scary Face(41)
/ Lava Plume(49)** [verified]. The level window is kind twice over — Fire Fang(17) is effect 273
and unmodelled, so it would have refused the target outright, and Ancient Power(1) is the
all-stats boost that makes Ho-Oh's Speed a problem. Both are learned *before* the four it keeps,
so both are pushed out.

### 14.1 Two stages at a time, and one of them is Speed

Every earlier target's drops were a single stage. Metal Sound is **−2 Sp. Def** and Scary Face
**−2 Speed** (`PRIMARY_STAT_DROPS` already had both; they only needed listing as modelled for a
target, and `act_target` already applied a primary drop to our side — Heatran is simply the first
target that has one).

Scary Face is the one that changes the shape of the fight: our lead outspeeds Heatran about 2:1,
and **two Scary Faces put it in front**. The no-speed-tie guarantee is what keeps ties out of the
solver's search, and who moves first decides what our move can still reach. The drops are also
permanent — a wild target never switches out and neither do we on a one-Pokémon plan, so the ROM's
stat reset never runs.

Both are also **missable** (85 and 90), which makes this target self-separating on the
RTC-second axis the way Lugia is and Suicune cannot be (`notes/seed_separation.md`).

### 14.2 The secondary drops became a table

Crunch is effect 69, a 20% Defence drop riding on damage. It would have been the **fourth**
hand-written `if outcome.secondary and move.effect == ...` branch in `simulate_turn`, and two of
the existing three lived only on the target's half of the turn — so a secondary drop from one of
*our* moves was applied nowhere at all. `SECONDARY_STAT_DROPS` replaces all four with one lookup
used on both sides.

> **Crunch drops DEFENCE in Gen 4.** It dropped Sp. Def in Gen 3, and that is exactly the class of
> fact a modern reference gets wrong for this project. From `effect_script_0069.s`, whose
> subscript is `MOVE_SUBSCRIPT_PTR_DEFENSE_DOWN_1_STAGE` [verified].

Effect 70 (Rock Tomb, Icy Wind) comes along for free: the same shape, read off
`effect_script_0070.s`, so a future target with one needs no edit.

### 14.3 The danger floor was blind to our own stages — a pre-existing bug

`worst_incoming_hit` built its `Defender` with **no stat stages at all**, so the figure was
computed at stage 0 whatever had been done to us. That figure *is* the solver's heal threshold, so
under-predicting it is how a run faints at a number the plan called safe.

Not new, and not Platinum's: **Latios's Luster Purge** has been able to drop our Sp. Def for as
long as it has been a configured target, and `act_target` was fixed to apply that drop
(clayton-957.26.1) while the floor went on ignoring it. Heatran is what made it acute — Metal Sound
is two stages at once, and at −2 its Lava Plume **one-shots a full-HP Smeargle** where at 0 it does
not. Measured: 210 at stage 0, 420 at −2.

Two fixes:

* the stages are passed to the `Defender`, and added to the memo key — a key without them served
  the stage-0 answer for the rest of the run once the first call had cached it. A crit ignores
  stages that would *reduce* its damage and respects those that raise it, which is the asymmetry
  wanted here, and `damage` already enforces it.
* `any_reachable_stage` now means what it says. It enumerated only the target's *offensive*
  stages, which is half the question; `reachable_defensive_drops` is the other half, read off the
  target's moveset. Only the extreme is priced, because damage is monotone in each stage, and only
  downward, for the same reason the offensive side only goes upward.

The second tier of advice is therefore reworded from "once the target has boosted" to "once the
target has **worked on you**", and it stays selective: a Blissey that survives 178 now and 700
after is warned, while Suicune — which cannot touch our defences — produces no warning at all.

### 14.4 Flash Fire is about our party, not about the fight

`BattleSystem_TriggerImmunityAbility` (`src/battle/battle_lib.c:3488-3545`) [verified] runs at
`TRY_MOVE_STATE_TRIGGER_IMMUNITY_ABILITIES` — after the accuracy roll and after the type chart, so
the rolls are spent either way. Six abilities absorb a whole move type, and **every one of them
does something extra on top of the immunity**: Volt Absorb, Water Absorb and Dry Skin heal a
quarter of max HP, Motor Drive raises Speed, and Flash Fire raises the holder's own Fire power by
half. So a Flamethrower thrown at Heatran would not merely fail — it would make the **Lava Plume
afterwards hit harder than anything predicted**. Unsound, not imprecise.

`ABSORBED_MOVE_TYPES` therefore *refuses* the move rather than approximating it, and the refusal is
about the **pairing**: `unselectable_reason` now takes the defender, so the same Flamethrower is
fine against Darkrai. The solver will not plan it, the interview will not offer it, and
`hunt_readiness` reports it before the run from a two-field probe of the target — so the advice is
available from the moment a species is typed, before a spread exists.

Lightning Rod is deliberately absent: in Gen 4 it redirects in doubles and grants no immunity at
all. Levitate is absent for the opposite reason — it *is* modelled (§13.4).

### 14.5 And the mirror: Soundproof blocks Metal Sound

`sSoundMoves` (`src/battle/battle_lib.c:3473-3486`) is a list of **twelve moves by name**, not a
type, and Metal Sound is on it [verified]. So an Electrode or a Whismur in the party blocks Metal
Sound outright — and without modelling it the simulator would apply two Sp. Def stages the game
never applied and mis-predict every special hit afterwards. Handled as a `will_fail` case, which
lands on the same no-more-work flag as the other defender-side refusals, so it costs what those
cost.

## 15. As built — Uxie and Azelf (clayton-6xu.7)

`StartLegendaryBattle SPECIES_UXIE, 50` (`res/field/scripts/scripts_acuity_cavern.s:33`) and
`SPECIES_AZELF, 50` (`scripts_valor_cavern.s:47`) [verified]. Both pure Psychic, **Levitate**,
catch rate 3 and genderless — so Phase 2's catch maths is Suicune's and Giratina's unchanged.

**Mesprit has no row and cannot have one.** Platinum makes it a *roamer*
(`RoamingPokemon_...` / `field_roamer`), so it is never met through a legendary-battle script;
`scripts_verity_cavern.s` only plays its cry and starts the roam. Two thirds of the lake trio is
all Battle Compass's static-encounter model can cover.

They share a stat line's *shape* and nothing else about it: Uxie is **75/75/130/75/130/95** and
Azelf **75/125/70/125/70/115**. Uxie is the gentlest target on the list and Azelf one of the
nastiest, and the plan for one is not the plan for the other.

Movesets are the last four learnable at 50 from each one's own `learnset.by_level`, in learn
order [verified]:

| | Uxie | Azelf |
|---|---|---|
| E1 | Swift (21) | Swift (21) |
| E2 | **Yawn** (31) | **Uproar** (31) |
| E3 | **Future Sight** (36) | **Future Sight** (36) |
| E4 | Amnesia (46) | Nasty Plot (46) |

The level window is kind twice over again, and in both directions this time. **Rest(1)** and
Confusion(1) are pushed out from below — Rest would heal off every False Swipe and make the chip
phase unwinnable — and **Explosion(76)**, Last Resort(61), Flail(61) and Extrasensory(51) from
above. An Explosion against a 1 HP target we are trying to catch ends the run.

Swift is effect 17, which Darkrai's Faint Attack already modelled: accuracy 0, so it never misses
and spends no accuracy roll. Note it is **special** in Gen 4, which is what makes Nasty Plot
matter to it.

### 15.1 Yawn — the first delayed status on either side

Accuracy 0 and **no roll of its own**: `subscript_yawn.s` only calls `BtlCmd_TryYawn`
(`battle_script.c:6580`), which sets `moveEffectsMask |= 1 << (YAWN_SHIFT + 1)`, i.e. 2
[verified]. `MON_COND_CHECK_STATE_YAWN` (state 24 of the end-of-turn condition walk) decrements
first and runs `subscript_fall_asleep` on reaching zero — so **a Yawn on turn T puts its victim
to sleep at the end of turn T+1**, and the first turn it costs is T+2.

The duration roll (`Random 3, 2` → 2–5 turns) is spent **then**, not at use, and only when the
sleep actually lands: the script re-checks Insomnia, Vital Spirit, an Uproar and any existing
status and bails *before* the `Random`. So a drowse that expires onto an already-paralyzed
Pokémon costs nothing at all, while the counter is consumed either way.

`will_fail` gained the whole of `subscript_yawn.s`'s own order: Insomnia and Vital Spirit first
(they print an ability message instead), then an Uproar, then any existing status, then a second
Yawn. Our side's Safeguard would block it too and is deliberately absent — `safeguard_turns` is
the *target's* side condition and nothing in any party can set one, so a row for it could never
fire.

Switching **does** shake a drowse off (`moveEffectsMask` is zeroed by the fresh `BattleMon` a
send-out builds), which is the opposite of a pending Future Sight. `sent_out` now says so.

### 15.2 Future Sight — the first move whose damage is banked

`effect_script_0148.s` runs `TryFutureSight` and then sets `SYSCTL_NONSTANDARD_ACC_CHECK` and
`SYSCTL_IGNORE_IMMUNITIES`. The ordering that makes all of this work is that **the effect script
runs before `TRY_MOVE`**: `BEFORE_MOVE` ends with `BattleSystem_LoadScript(..., moveCur)` and
`commandNext = BATTLE_CONTROL_TRY_MOVE` (`battle_controller_player.c:3215-3220`) [verified].

So the turn it is used spends **exactly one roll** — `BtlCmd_TryFutureSight`'s
`CalcMoveDamage` → `CalcDamageVariance` (`battle_script.c:6066-6096`) — and nothing else. No crit
roll (the script never reaches `CalcCrit`, and it passes a critical multiplier of 1) and no
accuracy roll (`CheckMoveHitAccuracy` returns 0 under the nonstandard flag). The token is the
bare slot: it neither hits nor misses nor crits.

Three consequences, all of them load-bearing:

* **No STAB and no type effectiveness.** Both live in `BattleSystem_ApplyTypeChart`
  (`battle_lib.c:2560`), called from `CheckTypeChart` during `TRY_MOVE` — which
  `SYSCTL_IGNORE_IMMUNITIES` skips outright, and the damage is already banked by then. So a
  Future Sight is **neither resisted nor super-effective nor blocked by an immunity**: a Dark
  type, which an ordinary Psychic move cannot touch at all, still takes it in full. It also loses
  its own ×1.5, which makes it weaker than its 80 base power reads against a neutral defender.
  `battle.damage.damage` gained a `type_chart` argument for exactly this one family, and the
  danger floor had been pricing it as an ordinary crit — **3× too high**, which is not a
  conservative error in the solver's heal threshold but a floor above every party member's max HP
  (the shape of clayton-957.10.1's collapse).
* **A switch does not dodge it.** `fieldConditions.futureSightTurns[defender]` is indexed by
  battler *position*, not by the Pokémon standing there, so the hit lands on whoever is out two
  turns later for the damage computed against whoever was out when it was used. It lives on
  `BattleState`, not on `Battler`.
* **Its accuracy check is a real 90% roll at end of turn.** `subscript_future_sight_damage.s`
  opens with `CheckMoveHit` [verified], and the nonstandard flag does not survive the turn it was
  set on. That verdict is observable, so it needed a token of its own: **`F`** — `Fh` hit, `F-`
  missed. It belongs to no actor's move (the turn that chose it is two turns gone), so attaching
  it to `E` would have claimed the target spent its turn on it.

The ROM's guard `--futureSightTurns[battler] == FALSE && battleMons[battler].curHP` is why the
HP-residual block in `simulate_turn` now runs *before* the end-of-turn advances: a burn tick that
faints us stops the Future Sight firing at all, so no roll is spent and no token is emitted. Which
is also why **a faint turn never carries an `F` token, whatever put us down**.

### 15.3 Uproar — a lock that attacks on every turn of it

`subscript_uproar.s` is `Random 3, 3`, and `BtlCmd_Random` reads that as `(rand % (3+1)) + 3`
(`battle_script.c:3201-3208`) — so the counter is **3 to 6, and the move is used on that many
turns in total** [verified]. `metronome_compass` rolls the same distribution counted as 2–5
*extra* turns, which is where the commonly quoted "Uproar lasts 2–5 turns" comes from;
corroboration, not coincidence.

While it runs, `Battler_CanPickCommand` is FALSE (`battle_lib.c:6224-6236`, where the Uproar
volatile sits beside `THRASH` and `MOVE_LOCKED` in one condition), so Azelf spends **no
move-selection roll and no PP** — the same two savings a Shadow Force charge turn gets, and the
reason `uproar_turns`/`uproar_slot` are their own fields rather than `charging_slot`: an Uproar
turn deals damage every turn, and `execute_move`'s `ends_charge` would clear a shared field on the
first of them.

It also **forbids sleep outright** while it runs. `subscript_fall_asleep`'s `_292`/`_311` branches
refuse the status ("But {0} can't sleep in an uproar!") and `MON_COND_CHECK_STATE_UPROAR` wakes
anything already asleep — looping every battler and *breaking out before the countdown*, so an
Uproar that woke somebody lasts one turn longer than its rolled length. The duration roll sits
past the refusal, so blocking it in `will_fail` is also what keeps the roll count right.

> **Uproar is the first *damaging* sound move any target has had**, and that needed code rather
> than a table row. `will_fail` is consulted only on the status branch, so Heatran's Metal Sound
> got Soundproof for free while Uproar would have dealt damage and started its lock against an
> Electrode. The check now sits in the damaging branch at the ROM's own position —
> `BattleSystem_TriggerImmunityAbility` runs after the effect script's CalcCrit/CalcDamage and
> after the accuracy check, so all three rolls are spent and then nothing happens; and
> `subscript_blocked_by_soundproof` *replaces* `USE_MOVE`, where the on-hit side effect would have
> run, so the duration roll is not spent and no lock is set. A Soundproof party member blanks the
> move whole — damage, lock and sleep ban together.

#### 15.3.1 It ends early when its user's move is prevented [verified]

**An Uproar whose user failed to move is over, whatever the counter says.** The order inside
`MON_COND_CHECK_STATE_UPROAR` is the whole content of the rule
(`src/battle/battle_controller_player.c:1505-1545`):

1. wake a sleeper and **break out before the countdown** (above);
2. otherwise decrement;
3. **then ask `BattleContext_MoveFailed(battleCtx, battler)` *before* reading what the counter now
   holds** — and if it answers TRUE, clear `VOLATILE_CONDITION_UPROAR` and the
   `FIELD_CONDITION_UPROAR` bit outright and run `subscript_uproar_end`;
4. only otherwise does a nonzero counter mean `subscript_uproar_continues`.

`BattleContext_MoveFailed` (`battle_lib.c:2808-2821`) reads **nine** flags — `paralyzed`,
`noEffect`, `imprisoned`, `infatuated`, `disabled`, `taunted`, `flinched`, `gravity`, `confused`.
What is *absent* matters as much: **sleep, freeze, truant, recharge, Heal Block and a plain miss
are not failures**, so a missed Uproar keeps its lock. `BattleSystem_SetupNextTurn` clears the
flags each turn (`battle_lib.c:2228-2234`), so this is strictly "did this turn's move fail".

Measured in `data/battle_logs/azelf_failure.jsonl` (forced seed `0x49023160`, read back and
confirmed). Azelf's second Uproar rolled **duration 3** — roll 47036 at `subscript_uproar`,
`47036 % 4 == 0` — and ran for **two** turns: used on turn 9, continued once, and then on turn 10
Azelf was fully paralyzed and *"The wild AZELF calmed down."* printed with a turn still on the
counter. The recording's other two Uproars, durations 3 and 6, both ran their full length.

**Why this is a desync and not a cosmetic error.** A locked target spends no move-selection roll,
so a lock carried one turn too long withholds a roll the game spent. On turn 11 the game rolled
21272 at `COMMAND_SELECTION_INPUT`, `21272 % 4 == 0` → **Swift**, while Clayton predicted a locked
Uproar — and every roll after that was off by one. This is the failure the recording was made for.

`MON_COND_CHECK_STATE_THRASH`, immediately after (same file, 1547-1570), carries the identical
rule for Thrash and Petal Dance. No configured battler has either move.

> **A second bug fell out of the same replay.** `simulate_turn` charged `rng_offset` from
> `select_target_move` returning a slot rather than from the stream having moved — and a locked
> target returns a slot while spending nothing, so the offset gained one per locked turn while the
> stream stayed right. It is `solver._state_key`'s stand-in for the stream position and the key
> its visited set dedupes on, so an inflated offset lets two genuinely different stream positions
> share a key. Now charged off `rng != rng_before`, which is exact: an LCRNG step here has no
> fixed point (it needs `state * (A-1) == -C mod 2**32`, and `A-1` is even while `C` is odd).

The whole 15-turn recording now replays exactly — roll counts, both sides' HP and the target's
chosen move slot — in `tests/test_battle_compass_ground_truth_azelf.py`.

### 15.4 Nasty Plot and Amnesia — one table, not two branches

Both are +2 self-raises whose effect script is a single `MOVE_SIDE_EFFECT_TO_ATTACKER` subscript
pointer, so neither spends a roll, and both have accuracy 0. They would have been a branch each in
`execute_move`; `PRIMARY_SELF_RAISES` replaces Double Team's hardcoded `("evasion_stage", 1)` with
a lookup, and `will_fail`'s +6 ceiling check reads the same table — so an Azelf that has already
Nasty Plotted three times spends two fewer advances on the fourth, which nobody had to notice.

**Amnesia is nearly harmless** against a physical chipper: it raises Sp. Def, and False Swipe is
physical, so Uxie spends roughly one turn in four on a move that does not slow the chip phase at
all. **Nasty Plot doubles Azelf's special attack**, and off base 125 that is the difference between
a party member surviving the chip phase and not — a critical Swift is 100 against a Lv58 Smeargle's
153 HP at +0 and 390 once it has stacked. `reachable_attack_stages` asked only about Ancient
Power's all-stats secondary and so could not see it; it now reads `PRIMARY_SELF_RAISES` for the
two *offensive* stages as well.

The table has since taken a third row from the same family, on our own side — see §18.

### 15.5 The one derived advance position (clayton-6xu.7.1)

Two of the end-of-turn condition states can now spend a roll: Yawn's sleep duration (state 24) and
a Future Sight's hit check (the first state of the side-condition walk that follows). Where they
sit inside the measured four end-of-turn advances is **derived, not measured**, and it is the only
such figure in `battle_compass/sim.py`.

What is known: `END_OF_TURN_ADVANCES = 4` is measured on turns where neither fires;
`metronome_compass` measured a rampage-end confusion-duration roll landing *after two of those
four* ("between END[1] and END[2]"), and that roll is `MON_COND_CHECK_STATE_THRASH` — **state 15**;
Yawn is state 24 and Future Sight is a whole phase later. So both are at or after the anchor and
Yawn is before Future Sight. `_END_OF_TURN_RESIDUAL_ANCHOR = 2` places them there.

What is not known is where the remaining two advances sit relative to states 15–24 and the
side-condition walk. **It matters because both verdicts are observable**: a wrong roll means a
wrong sleep length or a wrong Future Sight hit, which eliminates the true seed rather than merely
mispredicting a number. Uxie is the target that makes it load-bearing — both rolls are in its own
moveset and the target picks its own moves, so a run cannot route around them. [needs gdb]

**The capture tool now exists**: `utils/gdb-platinum-battle-reader.py`, the Platinum port of
`utils/gdb-battle-reader.py`. Beyond the port it logs the ROM's **battle phase** next to every
roll — `command`, all three condition-check state machines, and the battle script and cursor —
so the position of a roll inside the end of turn is read off the log rather than argued about.
`claytonlib.battle.logcheck`'s `end_of_turn_sequences` prints each turn's end-of-turn rolls in
order with the condition each one belongs to, which is the shape of the answer this section wants:

```
end-of-turn rolls, in order (which advance each condition's roll is):
  sequence 1: 4 roll(s)
    1. mon:THRASH[b0]          sub_seq:subscript_fall_asleep@0           val 40000
    2. mon:YAWN[b0]            sub_seq:subscript_fall_asleep@3           val 21000
    3. side:FUTURE_SIGHT[b0]   sub_seq:subscript_future_sight_damage@0   val 5000
    4. turn_end                ...                                      val 9
```

The recipe is the issue's: force a seed, Yawn on turn 1, read the end of turn 2; then the same
with a Future Sight banked on turn 1. Both rolls happen inside a subscript, so they report
`command` as `EXEC_SCRIPT` — `commandNext` is what says they are still the end of turn, and
`logcheck` attributes on that.

#### MEASURED (data/battle_logs/uxie1.jsonl, forced seed 0x9876543a)

The framing above is wrong in a way that makes the answer simpler. **None of the four
end-of-turn commands spends a roll of its own.** `CheckFieldConditions`, `CheckMonConditions`,
`CheckSideConditions` and `TurnEnd` contain zero `BattleSystem_RandNext` calls between them, and
in 362 recorded rolls not one has `command` set to any of the four [verified]. Every end-of-turn
roll happens inside a *subscript* the walk loads, and so reports `command = EXEC_SCRIPT` with
`commandNext` naming the walk it will return to.

The per-turn skeleton is rigidly regular across all 23 turns of the recording:

| rolls | phase | notes |
|---|---|---|
| 4 | `CHECK_PRE_MOVE_ACTIONS` | invariant — the pre-move speed rolls |
| — | *first mover's move* | `TRY_MOVE` = accuracy, `EXEC_SCRIPT→TRY_MOVE` = crit + damage variance |
| 2 | `AFTER_MOVE_EFFECT` | per **executed** move — the post-successful-move advances |
| 2 | `MOVE_END` | invariant |
| 1 | `BEFORE_MOVE` | **the paralysis check** — see below |
| — | *second mover's move* | |
| 2 | `MOVE_END` | invariant |
| 0–1 | `EXEC_SCRIPT→CHECK_MON_CONDITIONS` | **Yawn's sleep-duration roll** |
| 0–1 | `EXEC_SCRIPT→CHECK_SIDE_CONDITIONS` | **Future Sight's hit check** |
| 2 | `SHOW_BATTLE_MON` | invariant |
| 1 | `COMMAND_SELECTION_INPUT` | invariant |

Turn 4 is the turn both fired, verbatim:

```
PRE PRE PRE PRE  TRY AME AME  MEND MEND  BMV  TRY  MEND MEND  ES>MON ES>SIDE  SHOW SHOW CSEL
```

Both land after `MEND MEND` and before `SHOW SHOW`, **Yawn first**, one roll each.

**`BEFORE_MOVE` is the paralysis check, not a Quick Claw check.** Its phase records name
`sub_seq:subscript_check_quick_claw`, which is a trap: `scriptFile` is the last script *loaded*,
so it goes stale and says nothing about what the current phase is doing. The roll is
`CHECK_STATUS_STATE_PARALYSIS`, which `BattleControllerPlayer_BeforeMove` reaches through
`BEFORE_MOVE_STATE_STATUS_DISRUPTION`. Measured: it appears on 22 of the 23 turns — Uxie is
paralyzed from turn 1 on — and the one turn it is missing is the Taunt turn, where the refusal at
state 6 ends the walk before the paralysis roll at state 11. That absence is the
cleanest confirmation of the cost model below [verified].

It also closes the mapping, with nothing left over:

| `battle/turn.py` | ROM phase |
|---|---|
| `BEFORE_TURN_ADVANCES = 4` | `CHECK_PRE_MOVE_ACTIONS` ×4 |
| `SELECTION_ADVANCES = 1` | `COMMAND_SELECTION_INPUT` ×1 |
| the paralysis check (1, listed as an R7 residual) | `BEFORE_MOVE` ×1 |
| `POST_SUCCESSFUL_MOVE_ADVANCES = 2` | `AFTER_MOVE_EFFECT` ×2, per **executed** move |
| `BETWEEN_TURN_ADVANCES = 2` | the **first** `MOVE_END` pair |
| `END_OF_TURN_ADVANCES = 4` | the **second** `MOVE_END` pair + `SHOW_BATTLE_MON` ×2 |

which is what makes `_END_OF_TURN_RESIDUAL_ANCHOR = 2` exact rather than merely consistent: the
condition-walk rolls land between the two halves of that block [derived — every constant maps,
but the split of the four MOVE_END rolls into two pairs is read off the ordering rather than
measured directly].

**`_END_OF_TURN_RESIDUAL_ANCHOR = 2` is correct**, on one named identification: that the modelled
`END_OF_TURN_ADVANCES = 4` are the four trailing invariant rolls `MEND MEND SHOW SHOW`. On that
reading the anchor is exact, and it agrees with metronome_compass's rampage-end confusion
measurement ("between END[1] and END[2]", 0-based = after two) — `THRASH` is a mon-walk subscript
like Yawn, so it lands in the same place. The identification is the one thing still [derived];
`BEFORE_MOVE` and `COMMAND_SELECTION_INPUT` are the two per-turn invariant rolls `battle/turn.py`
already lists as unmodelled R7 residuals, which is consistent with it.

Every value matched the model [verified]:

| roll | site | value | model | observed |
|---|---|---|---|---|
| Yawn duration | `0x02242c90` `subscript_fall_asleep@155` | 63348 | `%4=0` → 2 | an Awakening was used |
| Yawn duration | same | 30480 | `%4=0` → 2 | 1 × "fast asleep", then woke |
| Yawn duration | same | 346 | `%4=2` → 4 | 3 × "fast asleep", then woke |
| Future Sight hit | `0x0224f230` `subscript_future_sight_damage@9` | 17334 | `%100=34 < 90` hit | "took the Future Sight attack", 133→99 |
| Future Sight hit | same | 62125 | `%100=25 < 90` hit | "took the Future Sight attack", 138→102 |
| Future Sight hit | same | 15792 | `%100=92 ≥ 90` miss | "took the Future Sight attack" **+ "But it failed!"**, no HP change |
| Taunt duration | `0x02242c90` `subscript_taunt_start@16` | 24559 | `%3=1` → 4 | wore off at the end of the 4th turn |

`0x02242c90` is the battle-script `Random` **opcode** — it fires only inside `subscript_fall_asleep`
and `subscript_taunt_start` in this log. And `BtlCmd_Random` is
`(rand % (range + 1)) + offset` (`src/battle/battle_script.c:3200-3210`), so `Random 3, 2` is
`% 4` and `Random 2, 3` is `% 3`: `SLEEP_DURATION_SPAN = 4` and `TAUNT_TURNS_SPAN = 3` are both
right, and any future reading of a script `Random` must add the 1.

#### Two bugs the same recording surfaced, both now fixed

**A pending Future Sight's re-use spends an accuracy roll** (clayton-6xu.7.5). It was modelled as
the only zero-roll failure in `execute_move`. `effect_script_0148.s` sets
`SYSCTL_NONSTANDARD_ACC_CHECK` — the flag that suppresses the accuracy check, and the reason
`accuracy_for` answers 0 on a use turn — on the **success** path only; `TryFutureSight` jumps over
it to `_010`, so the ordinary TRY_MOVE phase afterwards runs CheckMoveHit against the real 90.
Measured at turn 4: roll 60087 at the accuracy PC with no damage-variance roll on the turn. One
roll either way it goes, so `move_roll_cost`'s bound of 1 was right even while the branch was not.
The verdict is unobservable — the script prints "But it failed!" before the roll — so the turn
still renders the bare slot [verified].

**Taunt's landing turn refuses the target's already-selected move** (clayton-6xu.7.6), which
`Battler.usable_slots` argued could not happen. The narrowing it models happens at *selection*
time; on the turn the Taunt lands with the taunter moving first the target had already chosen, so
`CHECK_STATUS_STATE_TAUNT` (`tauntedTurns && power == 0`) refuses the move it is holding. Both
halves are now modelled — the narrowing in `usable_slots` for every later turn, the refusal in
`sim.taunt_refuses` for the landing turn.

The refusal costs the refused side **three advances**: the taunt test is state 6 of the
before-move walk and the paralysis roll is state 11, and `CHECK_STATUS_DISRUPT_MOVE` ends the walk
there — so a taunted *and paralyzed* target, which is every target in a real run, spends neither
its paralysis roll nor its two post-successful-move advances. Measured:

```
taunt-refused (turn 14)  PRE x4  TRY ES>MOVE_FAILED AME AME  MEND MEND       MEND MEND  SHOW SHOW CSEL
par-prevented (turn 17)  PRE x4  AME AME             MEND MEND  BMV           MEND MEND  SHOW SHOW CSEL
executed      (turn 19)  PRE x4                      MEND MEND  BMV  AME AME  MEND MEND  SHOW SHOW CSEL
```

`BMV` there is the paralysis roll, which is exactly the point: the refused turn is the only one
of the 23 without it.

And it gets a token of its own, `tokens.TAUNTED` — `E2tnt`, the **one move-prevention that keeps
its slot**, because the game announces the move by name where a paralysis or a flinch announces
nothing. On the landing turn that is a free read of the target's selection roll, which no other
prevented turn gives.

**Correction while porting — the state numbers above are one too high.** Platinum's enum opens
`MON_COND_CHECK_STATE_INGRAIN = MON_COND_CHECK_START`, which is an alias and not a state of its
own, so counting `MON_COND_CHECK_START` as a slot shifts everything after it by one. The decomp's
values are **Uproar 13, Thrash 14, Taunt 19, Yawn 23** (`src/battle/battle_controller_player.c`,
enum `MonCondCheckState`) against the 14 / 15 / 20 / 24 used in this document, in
`battle_compass/sim.py` and in clayton-6xu.7.1. Nothing about the *order* changes, so no
conclusion drawn from the old numbers is wrong — but a phase record carries the number, so the
reader and `tests/test_gdb_platinum_battle_reader.py` use the ROM's. [verified]

### 15.6 Strategy — and the finding that is the opposite of the natural guess

**Neither target separates two seeds one RTC second apart.** Both have exactly one sub-100 check,
Future Sight's 90, and it fires on about one turn in four and lands two turns after it is chosen.
Everything else either of them rolls is *permanently* blind between siblings, by
`notes/seed_separation.md`'s rule that a check is blind iff its modulus divides 256:

| check | modulus | verdict flips between siblings |
|---|---|---|
| move choice, paralysis | `% 4` | **0%** |
| crit, damage | `% 16` | **0%** |
| **Uproar length, sleep length** | `% 4` | **0%** |
| Future Sight hit | `% 100` at 90 | 17.9% |
| *our* Sing, for comparison | `% 100` at 55 | 49.5% |
| *a ball's shake check* | threshold | 44.5% |

(Computed by the same method as the memory note, which it reproduces to the decimal: 49.45% for
accuracy 55 and 44.45% for the shake check.) So **Uproar gives the run no information at all** —
the natural guess is that a 3–6 turn length is a rich signal, and it is the same length for both
siblings every time. What it does instead is take information *away*: no selection roll for 3–6
turns, and no sleep move to probe with.

Both of these are therefore **Suicune's case, not Lugia's**: the second axis has to come from our
own side — an early standard-ball probe, or a sub-100 move of ours.

Four concrete planning notes, all now surfaced by `hunt_readiness`:

1. **Azelf: paralysis, not sleep.** Uproar refuses sleep for 3–6 turns at a time and re-picks
   itself roughly one turn in four, so sleep is not a holding status this target reliably allows.
   A **Soundproof** party member (Electrode, Whismur line, Mr. Mime) removes the problem entirely.
2. **Azelf: the Nasty Plot clock.** It is permanent and +2 at a time. A Lv58 Smeargle survives an
   unboosted critical Swift and nothing after two stacks, so either reach the capture window early
   or bring something bulkier than the chipper to stand in front.
3. **Uxie: Yawn costs turns, not HP.** There is no Nightmare and no Bad Dreams, so the sleep-clock
   warning is silent and correctly so — but 2–5 turns asleep is 2–5 turns of a precomputed path
   re-solved. **Insomnia or Vital Spirit** refuses it (Noctowl, Hypno, Honchkrow, Ariados) and
   **Early Bird** halves the counter, so a rolled 2 costs no turn at all.
4. **A failing sleep move is still a probe.** `execute_move` spends the accuracy roll *before*
   `will_fail` decides, which is the ROM's order — so a Sing thrown at an uproaring Azelf or an
   already-paralyzed Uxie still rolls its 55, and the miss-versus-failed distinction is still the
   sharpest separator in the run (`notes/seed_separation.md`). Do not stop throwing it.

## 16. As built — Taunt, and the ROM read that nearly went the wrong way (clayton-4wr.1.2)

Our side's first move that changes what the TARGET's turn *costs* rather than only what it does.
Everything before it hurt the target, statused it, or degraded it; Taunt takes moves away.

`subscript_taunt_start.s` fails free if the defender is already taunted or the move missed, and
otherwise rolls `Random 2, 3` → `(rand % 3) + 3`, so **3 to 5 turns** [verified]. Accuracy is 100,
so the accuracy roll is spent too: **two rolls when it lands, one when it fails**. The wear-off is
`MON_COND_CHECK_STATE_TAUNT`, state 20 of the end-of-turn condition walk — between Uproar at 14
and Yawn at 24 — and it spends nothing, so unlike §15.5's two rolls it needs no position inside
the measured four end-of-turn advances.

### 16.1 The mechanism is a narrowed MODULUS, not a refused move

This is the part that nearly went in backwards, and it is worth recording how.

The ROM has a `subscript_move_fail_taunted` whose message — "{0} can't use {1} after the taunt!" —
reads exactly like the wild side picking a status move and being refused for it. It is reached
from `CHECK_STATUS_STATE_TAUNT` in the before-move status check, on the test
`tauntedTurns && moveTable[moveCur].power == 0` (`battle_controller_player.c:2559`). Modelled that
way, Taunt would leave `select_target_move`'s modulus alone and refuse the move afterwards.

That is wrong. The wild side's move choice is a max-score tie broken randomly, and
`TrainerAI_Init` zeroes the score of every move flagged by
`BattleSystem_CheckInvalidMoves(..., CHECK_INVALID_ALL)` (`trainer_ai.c:234-237`, then the pick at
`:317-338`). `CHECK_INVALID_ALL` is `~0` (`include/constants/battle.h:132`), so it carries
`CHECK_INVALID_TAUNTED` **and** `CHECK_INVALID_NO_PP`. A taunted power-0 move therefore drops out
of the tie list and the modulus shrinks with it.

Modelled as a refusal, every taunted turn would have spent two post-successful-move advances the
game does not spend, **and** picked the wrong move besides. The subscript is reached only when
something *forces* a taunted Pokémon into a status move — Encore, Sleep Talk, a locked move — none
of which any configured target can do, which is why it exists at all and why it is not the wild
path.

So the whole of the implementation is `Battler.usable_slots` growing one clause. Two things fall
out of that:

* **The same code path is the source behind the PP rule we already model.**
  `CHECK_INVALID_NO_PP` zeroes a 0-PP move's score by the identical route, which is why
  `select_target_move`'s `% usable_slots()` is right. That was verified by measurement; this is
  the code behind it.
* **A likely identification of `turn.BEFORE_TURN_ADVANCES`** [derived, not asserted]. The loop
  that zeroes those scores also does `moveDamageRolls[i] = 100 - (BattleSystem_RandNext % 16)`
  once per slot, `LEARNED_MOVES_MAX` is 4, and it runs for the AI-controlled side only. That is
  four advances at the top of the turn for the side that is not the player, which is exactly what
  `turn.py` has as measured-but-unexplained. Exact match, right position; confirm before writing
  it down as fact, and note the rolls are spent whether or not the AI ever reads them.

### 16.2 What it is worth, per target

By POWER, which is the ROM's own test rather than by category:

| | taunted slots | what is shut |
|---|---|---|
| Uxie | 2 of 4 | **Yawn and Amnesia** |
| Azelf | 3 of 4 | Nasty Plot |
| Heatran | 2 of 4 | **Metal Sound and Scary Face** — both two-stage drops |
| Darkrai | 1 of 4 | Hypnosis, Nightmare, Double Team |
| Suicune | 2 of 4 | Rain Dance, Mist |
| Giratina | 4 of 4 | nothing — all four of its moves have power |

Heatran is the best of them: both of the drops that make it dangerous (§14.1, §14.3) are power 0.
Darkrai is the most dramatic — one move left, and a Dark/Flying carrier takes it at ×0.5 — though
Insomnia already answers that target more cheaply (§15.6 note 1).

A target reduced to a single pickable move **still spends the selection roll**:
`maxScoreMoveSlots[RandNext % numMaxScoreMoves]` rolls at a count of one. And a taunted target
whose last damaging move runs out of PP would Struggle, which is outside the model — Taunt is the
first thing that can put a target there, so `select_target_move`'s existing `None` path has a
second way to be reached.

### 16.3 It does not help identification

`% 2` divides 256, so the narrowed modulus is as blind between RTC-second siblings as `% 4` was
(§15.6's table). Worth stating because "fewer options" reads like "more information": a taunted
Uxie picks the same move as its sibling every turn, and when the two separate at all it is still
Future Sight's 90% check doing it.

### 16.4 Fixed in passing

* **The interview offered moves the target could not pick.** `move_info` gained `selectable`, read
  straight off `usable_slots`, and the page filters on it — so the simulator's modulus and the
  list of answers cannot disagree. An answer the game could not have produced is worse than a
  contradiction: it eliminates every candidate. The pre-existing half of the same bug was 0-PP
  moves, which were offered as answers too, and one flag fixes both.
* **The readiness panel dropped every party member's ABILITY.**
  `facade._survivability_warnings` built its Battlers without `ability=`, so the whole party was
  judged ability-less: an Insomnia holder was told a target could sleep it, an Early Bird holder
  got the unhalved sleep clock, and the sentence naming the carrier could never fire. The run path
  has always passed it, so the simulation was right and only the advice was wrong — found by
  pointing the Honchkrow kit at it.

## 17. As built — Haze, and the move range nobody had read (clayton-4wr.1.1)

`effect_script_0025.s` is one line — `MOVE_SIDE_EFFECT_ON_HIT|MOVE_SUBSCRIPT_PTR_RESET_ALL_STAT_STAGES`
— and `subscript_reset_all_stat_stages.s` is `ResetAllStatChanges` plus "All stat changes were
eliminated!". No Random anywhere, and Haze's accuracy is 0, so **the move spends no rolls at all**
[verified].

That is not a free turn. Haze succeeds, so the turn still spends the two post-successful-move
advances, which puts it at **2** against Flash's 3 and Taunt's 4: the cheapest *move* in the
alphabet, and dearer than a bag action's nothing. Worth stating precisely because the first draft
of this work called it "level with an item" in three places, and a test caught it.

`BtlCmd_ResetAllStatChanges` (`battle_script.c:3535-3549`) loops **every battler** and sets every
one of its `statBoosts` to neutral, then clears Focus Energy. It touches nothing else: not status,
not the other volatiles, not field conditions. And there is no "already hazed" check, so a second
Haze succeeds and costs the same — unlike Mist, Safeguard, Water Sport and both screens, all of
which fail when re-used.

### 17.1 It undoes our own work, so the solver is kept off it

Both sides, which is the whole difficulty. The same move that wipes a Giratina at +6 from Ancient
Power also wipes:

* **the target's lowered accuracy** — six Flashes, the biggest accuracy investment a run makes,
  and permanent because a wild target never switches out;
* **our own X Sp. Def stacks** — `choose_item`'s preferred filler, so nonzero from the first
  filler turn of most plans.

At 2 advances it is Dijkstra's favourite action, so left unchecked the solver plans it as filler
and silently throws away what earlier turns of its own plan spent to get. `solver.undoes_our_own_work`
refuses it, and three things about that refusal are deliberate:

* **It is a solver refusal, not a `sim.unselectable_reason` one.** `unselectable_reason` is for
  moves the simulator would MIS-PREDICT; it also disables the move in the interview and reports it
  as a coverage gap. Haze is modelled exactly — it is merely self-defeating as *filler*, and
  whether to spend it is the player's call on the turn.
* **It is state-dependent, not a blanket ban.** From a state with no stages in play Haze genuinely
  is harmless cheap filler. In practice the X Sp. Def stack means the refusal bites from turn two.
* **The direction is spelled out per stage** (`_STAGES_IN_OUR_FAVOUR`) rather than inferred. The
  target's lowered *accuracy* helps us and its raised *evasion* hurts us, and those are adjacent
  fields on the same object; getting one backwards would refuse Haze exactly when it is wanted.

`STAGE_FIELD_NAMES` names the seven stage fields once, so a Haze and a send-out cannot clear
different sets — a field added to `Battler` and forgotten in one of them would be a stage that
survives a switch, silently. A test pins it against the dataclass and against
`hunt_session.STAGE_FIELDS`, which is the same seven paired with UI labels.

### 17.2 And a pre-existing bug: self-aimed moves were missing a vanished target

Haze is `range: 64` = **RANGE_FIELD**, and the ROM points a field-, side- or self-range move back
at its own user:

```c
} else if (range == RANGE_USER                 // e.g., Swords Dance
    || range == RANGE_USER_SIDE                // e.g., Light Screen, Reflect
    || range == RANGE_SINGLE_TARGET_SPECIAL    // e.g., Counter, Mirror Coat
    || range == RANGE_FIELD) {                 // e.g., Sunny Day
    defender = attacker;
```
`BattleSystem_GetDefender`, `battle_lib.c:1664-1683` [verified].

So there is nothing out of reach while Giratina is away mid-Shadow Force — and `execute_move` was
gating the semi-invulnerability check on nothing but the defender's state, so **every self-aimed
move of ours rendered as a MISS and set nothing**. A Light Screen used on the charge turn put no
screen up *and* cost the turn its two post-successful-move advances: a desync, not a mispredicted
number. Reachable, because Magneton carries Light Screen in the configured party, and Shadow Force
is in the same moveset as the Ancient Power boosts Haze is carried for.

`Move` now exposes `range_id` with a `reaches_opponent` property, and both branches of
`execute_move` gate on it. The flag values were decoded by running all 467 rows of moves.json
against the decomp's `generated/move_ranges.txt` — they land on exactly twelve named values and
nothing else, with Surf as ALL_ADJACENT, Spikes as OPPONENT_SIDE, Mist and Light Screen as
USER_SIDE, Haze and Rain Dance as FIELD, Helping Hand as ALLY and Acupressure as USER_OR_ALLY. It
fixes Light Screen, Reflect, Mist, Safeguard, Rain Dance, Refresh, Double Team, Nasty Plot and
Amnesia at a stroke; Flash and every damaging move still miss, which is the control.

### 17.3 Where the kit stands

With Haze and Taunt both modelled, the Honchkrow kit is fully simulable: **Insomnia** blanks
Darkrai's Hypnosis → Nightmare → Bad Dreams chain and Uxie's Yawn, **Taunt** shuts Uxie's Yawn and
Amnesia, Azelf's Nasty Plot and both of Heatran's two-stage drops, and **Haze** answers the one
thing neither of those can — a Giratina that has already boosted. Against Giratina specifically,
note §15.6's caution still stands: Ancient Power is Rock vs Dark/Flying = ×2 into base Sp. Def 52,
so Haze undoes the boosts but not the hit that applied them.

---

## 18. As built — Swords Dance, and a table that had already done the work (clayton-4wr.1.6)

`effect_script_0050.s` is one line:

```
UpdateVar OPCODE_SET, BTLVAR_SIDE_EFFECT_FLAGS_DIRECT, MOVE_SIDE_EFFECT_TO_ATTACKER|MOVE_SUBSCRIPT_PTR_ATTACK_UP_2_STAGES
End
```

Put `0053` (Nasty Plot) and `0054` (Amnesia) beside it and the three files differ **only** in the
subscript pointer; all three resolve to `subscript_update_stat_stage`
(`include/data/move_side_effect_subscripts.h:46-50`) [verified]. All three have accuracy 0 and no
`Random` anywhere, so the move spends **zero rolls** and the turn costs 2 — the post-successful-move
pair, the same as Haze. Cross-checked independently against
`metronome_compass.effects._eff_swords_dance`, which is `atk+2` and nothing else [verified].

So the whole change is one row in `PRIMARY_SELF_RAISES` and one in `MODELLED_OUR_EFFECTS`. Five
behaviours follow from the table already being the single point of truth, and none of them needed
code: `will_fail` refuses it at +6 (two fewer advances on the wasted turn), `execute_move` carries
it as `self_stat_raise`, both act halves apply it, `battle.damage` reads `attack_stage`, and
`reachable_attack_stages` counts any `atk_stage` self-raise as a booster — so a *target* that ever
has the move raises the danger floor with no further work. §15.4 is where that table was argued
for; this is the first time the argument paid.

**Why it is worth carrying, not merely supported.** It raises the physical damage *we* deal, and
False Swipe cannot take the target below 1 HP (effect 101) — so it is strictly fewer turns to the
Phase 2 precondition with no risk of overshooting it. Measured against a Lv50 Azelf (138 HP) with
the Lv64 Smeargle fixture:

| our Attack | False Swipes to reach 1 HP | turns including the dances |
|---|---|---|
| +0 | 5 | **5** |
| +2 | 3 | **4** |
| +4 | 2 | **4** |
| +6 | 2 | 5 |

So **one dance pays for itself and a third is thrown away** — the count cannot go below 2, because
a clamped hit still only takes the target to 1. A ceiling-first opening is not the fast line, which
is the solver's problem rather than the move's.

Two existing rules the boost leans on, both already right:

* **A critical hit keeps a raised stage.** `battle.damage` discards the attacker's stage on a crit
  only when it is *negative* (`if not (critical and attack_stage < 0)`, lines 499-502) — the Gen 4
  rule. Had it discarded raises too, the move would be worth nothing on exactly the turns it
  matters most.
* **A burn still halves the boosted Attack.** Two independent multipliers, which is why a boosted
  chipper is not automatically a faster one.

**What was deliberately left out.** Barrier (51) and Agility (52) have the identical script shape,
and Agility is *not* a free table row: Speed decides turn order, and a stage that lands the two
sides on equal effective Speed creates a speed tie, which spends extra rolls
(`notes/ss_rng/speed.md` — the reason Lagging Tail is mandated). Adding it would claim coverage for
the one self-raise in the family that can change a turn's cost. Barrier is genuinely free and is
simply not wanted yet.

No configured encounter has Swords Dance, so it is listed for our side only — the same standing as
Haze.

---

## 19. As built — the whole pure stat-stage family, and the ceiling that was modelled backwards (clayton-4wr.1.7)

§18 added one row to `PRIMARY_SELF_RAISES`. This adds the rest of the family, and in doing so
found that one of its rules had the wrong sign.

### 19.1 The ROM makes it a family, so the code does too

Scan `res/battle/scripts/effects` for a script that is exactly one `UpdateVar ...
MOVE_SIDE_EFFECT_{TO_ATTACKER,TO_DEFENDER}|MOVE_SUBSCRIPT_PTR_<stat>_<UP|DOWN>_<n>_STAGE(S)`
followed by `End`, and **23 effect ids** come back covering **33 moves** [verified]. Every one
resolves to `subscript_update_stat_stage` (`include/data/move_side_effect_subscripts.h:22-57`),
none contains a `Random`, and every self-raise has accuracy 0.

| | one stat, +1 | one stat, +2 | two stats, +1 each |
|---|---|---|---|
| **ours** | 10 Meditate/Sharpen/Howl, 11 Harden/Withdraw, 13 Growth, 16 Double Team | 50 Swords Dance, 51 Barrier/Acid Armor/Iron Defense, **52 Agility/Rock Polish**, 53 Tail Glow/Nasty Plot, 54 Amnesia | 206 Cosmic Power/Defend Order, 208 Bulk Up, 211 Calm Mind, **212 Dragon Dance** |
| **the target's** | 18 Growl, 19 Tail Whip/Leer, **20 String Shot**, 23 Sand Attack/Smoke Screen/Kinesis/Flash, 24 Sweet Scent | 58 Charm/Feather Dance, 59 Screech, **60 Cotton Spore/Scary Face**, 62 Fake Tears/Metal Sound | 205 Tickle |

The nine single-stat drops were already modelled. What this adds is the five single-stat raises,
the two remaining +2 raises, and the five two-stat moves — and the two tables' values became
**tuples of pairs** so that one code path covers a move that moves two stats. The bold entries
move SPEED; see §20.

### 19.2 "It cannot go higher" is not a failure — measured

`BtlCmd_ChangeStatStage` (`battle_script.c:2804-2975`) takes `jumpNoChange` when the stat is
already at the limit **for a DIRECT side effect**, and `jumpNoChange` is
`subscript_update_stat_stage`'s `_041`: print *"{0}'s {1} won't go higher/lower!"*, `End`, **no
status flag**. Only `jumpBlockedBySubstitute` sets `MOVE_STATUS_FAILED` [verified].

So a stat change that cannot happen is still a **successful** move and still spends the two
post-successful-move advances.

That is measured on the drop half. **`data/battle_logs/hooh1.jsonl` turns 34-37** are four Sweet
Scents against an evasion already at -6 — *"The wild HO-OH's evasiveness won't go lower!"* — and
each spends the full **15 rolls**. Modelling them as failures costs turn 34 two advances and
desynchronises every turn after it; the 57-turn replay only matches with them successful.

**`will_fail` had the mirror case backwards.** It returned True for a self-raise at +6, with
§15.4's claim that *"an Azelf that has already Nasty Plotted three times spends two fewer advances
on the fourth"*. That claim was derived, never measured, and the identical ROM instruction with
the sign flipped says otherwise. It is corrected: a single-stat raise at the ceiling wastes the
turn and costs the full price. Reachable, and not rarely — Azelf picks Nasty Plot roughly one turn
in four, so a long run hits the ceiling and then keeps picking it.

### 19.3 The two-stat moves really do fail, by a different route

Each has a subscript of its own — `subscript_user_atk_and_def_up_1_stage.s` and its four
siblings — which tests **every** stat before calling `ChangeStatStage` at all:

```
CompareMonDataToValue OPCODE_NEQ, ..., BATTLEMON_ATTACK_STAGE, 12, _011   // one free? do it
CompareMonDataToValue OPCODE_EQU, ..., BATTLEMON_DEFENSE_STAGE, 12, _046  // both maxed? fail
```

`_046` sets `MOVE_STATUS_NO_MORE_WORK`, which `BattleControllerPlayer_CheckMoveFailure` routes to
`LOOP_SPREAD_MOVES`, skipping `USE_MOVE` whole — so the post-move pair is not spent [verified in
the ROM; **derived** as an advance count, since nothing in a configured moveset can reach it: it
needs a two-stat move with *every* one of its stats at the limit]. `MULTI_STAT_EFFECTS` is the set
that distinguishes the two rules, and Tickle is the mirror of it at the floor.

One stat free is enough for the move to run, and the maxed stat then clamps silently inside its
own `ChangeStatStage` call — which is why `apply_stat_raise` and `apply_stat_drop` clamp each pair
independently rather than refusing the lot.

---

## 20. As built — speed ties your own moves can create (clayton-4wr.1.8)

`readiness.speed_checks` asks *"could these two Pokemon tie as they stand"*, and enumerates every
Speed stage the **target** can reach because Ancient Power is in two configured movesets. It holds
our own Speed constant. §19 is what made that insufficient: six of the 33 moves move Speed.

* **ours, upward**: Agility and Rock Polish (+2), Dragon Dance (+1)
* **the target's, downward**: String Shot (-1), Cotton Spore and Scary Face (-2)

Either direction can land the two sides on exactly equal effective Speed, and a tie spends rolls
this simulator does not model (`notes/ss_rng/speed.md`) — so every turn after it is unmatchable.
It is worse than a standing tie in one respect: it appears **mid-run, on a turn the player chose**,
long after the configuration screen said the party was fine.

`readiness.speed_move_ties` is the validation, and it is a **warning rather than a refusal**:
only some stage combinations tie, and the move may be exactly the right play — a Cotton Spore is
how a slow chipper gets to move first. What the player needs is to be told which stages to avoid.

Four decisions worth writing down:

* **Stages are enumerated by repetition and mixture**, not just the single step. Two Agilities is
  +4; an Agility and a Dragon Dance is +3, which no single move reaches and which is exactly where
  a tie hides.
* **Our drops compose on top of the target's own boosts.** Cotton Spore moves two stages, so from
  0 it can only reach -2/-4/-6 — the odd negative stages exist *only* if the target boosted itself
  first, and the facade passes `target_own_speed_stages` for that reason.
* **A target Speed drop is attributed to the whole party, not to its holder.** A wild target never
  switches out, so the drop is permanent: the Pokemon that used Cotton Spore may be back on the
  bench by the time the tie matters. The warning reads *"Cotton Spore (Smeargle's) can tie Krow"*.
* **The paralyzed-target rows are gated on the party being able to paralyze**, the mirror of
  `_target_can_paralyze_us`. Asked as "any party member" rather than "another": a Pokemon holding
  both Agility and Thunder Wave reaches the same tie over two turns, and reading it strictly would
  hide a real one.

Ties nobody's move caused are **not** reported here — our stage 0 against a target stage the target
reaches alone is `speed_checks`'s row, and crediting it to a String Shot that had nothing to do
with it would be worse than silence.

> **And an omission it exposed.** `can_inflict` treats an unrecognised ability as capable, which is
> the right direction; `_INERT_ABILITIES` is what stops that swallowing everything, and
> **Insomnia was not in it** — the headline ability of the wall this whole support kit is built
> around. So any party containing a Honchkrow answered "yes, we can paralyze" on its ability
> alone, and the gate above would have been ungated in practice. Insomnia and fifteen other
> purely defensive abilities are now listed. No configured target has any of them, which is why
> nothing else moved.

---

## 21. As built — Shaymin, and the two moves that are inert exactly when it matters (clayton-6xu.9.7, clayton-6xu.9.9, clayton-6xu.9.11)

The Flower Paradise Shaymin is in: `ENCOUNTERS["shaymin"]`, Lv30, `(Growth, Magical Leaf, Leech
Seed, Synthesis)`, `games=("platinum",)`. All four effects are modelled, so
`unsupported_moves("shaymin", "platinum")` is clean and the row is live rather than aspirational.

It is the proof case `notes/battle_compass_dialga_palkia_shaymin.md` §4C argued for, and the
argument survives contact: **both of its recovery moves are inert at full HP, and that is now
modelled rather than assumed.** Synthesis fails outright; Leech Seed's heal clamps to nothing. So
a full-HP Shaymin cannot move its own HP, and `b` stays where the window search put it. At 1 HP
the two interact and move `b` out from under the precomputed window, which is the thing to avoid.

### 21.1 Two ROM readings the design doc had slightly wrong

Both would have shipped as bugs, and both came out of reading the subscripts rather than the
move descriptions.

**Leech Seed's heal is the damage *actually dealt*, not the figure it computed.**
`subscript_leech_seed_effect.s` takes `maxHP / 8` of the seeded Pokemon, negates it, applies it —
and then reloads `BTLVAR_HIT_DAMAGE` before handing anything to the seeder. So a drain clamped by
our remaining HP heals the target by the *clamped* amount. The implementation measures the HP it
removed across `with_hp` rather than predicting the divisor, the same way the residual block
already measures Leftovers instead of predicting it. Predicting `maxHP / 8` would over-heal the
target on exactly the turn the drain faints us — a wrong prediction, not a conservative one.

**Synthesis does not set `MOVE_STATUS_FAILED` and never says "But it failed!"** The full-HP test
is the *first line* of `subscript_recover_hp.s`, which branches to `_036`, prints "{0}'s HP is
full!" and sets `MOVE_STATUS_NO_MORE_WORK` (`1 << 31`). That is a different flag and a different
route through `BattleControllerPlayer_CheckMoveFailure` (battle_controller_player.c:3312-3331):

| flag | route |
| --- | --- |
| `NO_MORE_WORK` | → `BATTLE_CONTROL_LOOP_SPREAD_MOVES` |
| `DID_NOT_HIT` (incl. `FAILED`, `INEFFECTIVE`) | → `subscript_missed` → `LOOP_FAINTED` |
| success | → `BATTLE_CONTROL_USE_MOVE` |

Both failure routes skip `BATTLE_CONTROL_USE_MOVE`, which is *why* giving them the same
two-advance discount should be right. But I could not find two unconditional `RandNext` calls on
the `USE_MOVE` path by static read, and `POST_SUCCESSFUL_MOVE_ADVANCES = 2` is an
emulator-measured figure fitted against families that all set `FAILED`. **So the equivalence is
an inference and is owed a capture** — filed, and cheap to reach, since a full-HP Shaymin picks
Synthesis one turn in four and the first turn of any Shaymin run is at full HP. Leech Seed's two
failure branches cover one flag of each kind (`INEFFECTIVE` for a Grass defender,
`NO_MORE_WORK` for an already-seeded one), so the same capture answers for both.

### 21.2 What got built

* `Battler.seeded` — `moveEffectsMask`'s Leech Seed bit. A flag with no counter, like
  `identified`. Shed by `sent_out` (so switching really is the answer to a Leech Seed) and by
  `with_hp(0)`.
* `sim.leech_seed_tick` — `max(1, maxHP / 8)`, floored but never zero because
  `DivideVarByValue` is `BattleSystem_Divide` (battle_lib.c:3599-3618), which clamps a zero
  quotient to 1 — the same rule as the burn tick and Leftovers. Applied **between Leftovers and
  the burn tick**, which is the ROM's own order (`MON_COND_CHECK_STATE_LEFTOVERS` 1263,
  `_LEECH_SEED` 1264, `_POISON` 1265, `_BURN` 1267). Order matters even with no rolls involved,
  because each is clamped at 0 and whichever reaches it first is the one that faints us.
* `sim.synthesis_heal` — the three weather branches of `BtlCmd_WeatherHPRecovery`
  (battle_script.c:5966-5979). For a Lv30 Shaymin at 109 max: 54 with no weather, 72 in sun, 27
  in rain/sand/hail. **Rain is reachable and works for us**: Suicune's and Lugia's Rain Dance
  halve the recovery from 54 to 27. Sun has no setter and is modelled anyway, because
  `weather_of` already reads weather and the branch costs nothing.
* `MoveOutcome.seeds` and `MoveOutcome.self_heal` — the first self-heal on either side.
  `self_heal` is a figure rather than a flag because the amount depends on the field.
* Four new `will_fail` families (ten total now), and the placement is the part worth recording:
  **they had to go above the `if field is None: return False` guard**, next to Refresh. Put below
  it with the screens they were unreachable whenever no field was passed, and the tests caught
  it, not a reading.
* `hunt_session.BATTLER_FLAGS` gained a Leech Seed row. It is the only condition in that banner
  that takes HP off one side and gives it to the other, so a player should not have to infer it
  from their HP dropping.

### 21.3 Three things deliberately not modelled, and said so in the code

**Big Root** would raise the heal by its `HOLD_EFFECT_LEECH_BOOST` param and **Liquid Ooze**
would reverse it into damage; no wild Pokemon holds the first and nothing in any configured party
has the second. **Heal Block** refuses Synthesis (`subscript_present_heal.s` `_015`) and refuses
the Leech Seed heal (`subscript_leech_seed_effect.s` `_083`, keyed on the *seeder*), and no party
can inflict it. Each is a comment rather than a branch, so that adding one later is a line.

**Magic Guard is modelled**, and is the one of this family that is a real party answer: the ROM
skips the whole Leech Seed state for a holder (battle_controller_player.c:1381), and Clefable is
an ordinary lead. Because the heal is the damage dealt, a Magic Guard holder starves the target
as well as itself — the drain is zero on both sides.

**A Grass lead cannot be seeded at all.** `subscript_leech_seed_start.s` `_065` checks both type
slots before anything else. That is the other genuine party answer here, and it is a test rather
than a comment.

### 21.3b The Lum Berry — found by Testare, and it changes the plan

**Shaymin holds a Lum Berry, guaranteed**, and it is the only target on the whole table that
holds anything at all. §21 shipped without it, which made the row claim a sleep the game cures.

`wildHeldItems` is Lum Berry in **both** the common and rare slots
(`res/pokemon/shaymin/data.json`), and that is exactly the case `Pokemon_GiveHeldItem`
(`src/pokemon.c:4675-4701`) short-circuits:

```c
u32 rand = LCRNG_Next() % 100;                         // unconditional, before the lookup
...
if (monItem1 == monItem2 && monItem1 != ITEM_NONE) {   // Shaymin takes this branch
    Pokemon_SetValue(mon, MON_DATA_HELD_ITEM, &monItem1);
    return;                                            // always held, not 45/50/5
}
```

Two things fall out of that read, and both matter:

* **It is guaranteed, not probabilistic**, so it is storable as a field (`Encounter.held_item`)
  rather than needing a branch in the simulation.
* **The roll is spent either way**, before the species lookup, so an encounter that holds
  something costs no more advances than one that does not — which is what keeps
  `BATTLE_START_ADVANCES` and the generation path shared across the table. §21's claim that
  Shaymin's generation path is identical to every other static's survives intact.

A scripted static really does reach that function: `StartFatefulEncounter` →
`CreateWildMon_Scripted` → `CreateWildMon` → `AddWildMonToParty` → `Pokemon_GiveHeldItem`
(`overlay006/wild_encounters.c:1227, 1047, 1085, 1462`).

**What the berry does.** `HOLD_EFFECT_STATUS_RESTORE`, and `lum_berry.json`'s `itemUseParams`
sets every one of `healSleep`, `healPoison`, `healBurn`, `healFreeze`, `healParalysis` and
`healConfusion` — so it cures whatever it finds. It fires through
`BattleSystem_TriggerHeldItemOnStatus` (`battle_lib.c:4967`, the case at `:5052`), which is the
**immediate** trigger rather than the end-of-turn one, reached from the site right after a move
applies a status (`battle_controller_player.c:3745`). It costs **zero advances** — no restore
subscript contains a `Random` — and it is **consumed**: `subscript_pluck_check.s` falls through
to `RemoveItem` whenever the Pluck self-turn flag is not set, that flag's only job being to stop
a second removal after Pluck already ate the berry.

**So Phase 2 against Shaymin needs two sleeps.** The first Spore burns the berry and the second
is the one that holds. That is the planning consequence, and it is the reason this was a wrong
prediction rather than a missing nicety: the simulator had the target asleep on a turn the game
had already woken it, which desynchronises everything after.

> **And it is observable, which is the better half.** The berry fires before the target's half of
> the turn, so a woken Shaymin goes on to use a move: the turn reads `M1 E1` where a sleeping one
> reads `M1 Eslp`. The player can see it happen, and the turn that spent the target's selection
> and move rolls is a different turn to match against — so this is an identification signal, not
> only a tax.

Modelled side-agnostically (`sim.cure_with_held_item`), because the ROM's trigger is per battler
and a party member may carry one. Hooked at all **eight** status-infliction sites rather than
only the reachable one, since missing a site is the failure mode. The item names live in
`battle.readiness.STATUS_RESTORE_ITEMS` for the same reason `LEFTOVERS` does — the
modelled-items allowlist is *assembled* from the tables that read the items, and
`test_battle_held_items` is what caught a hand-written entry when the first attempt put the row
inline.

### 21.4 And an omission it exposed, in the same place §20's was

`can_inflict` treats an unrecognised ability as capable — the right direction — and
`_INERT_ABILITIES` is what stops that swallowing everything. **Natural Cure was not in it**, so
Shaymin answered "yes, it can paralyze us" on the strength of an ability that does nothing to
anybody, and filled the speed table with rows for a state the player cannot reach. Caught by
`test_no_configured_target_can_paralyze_us`, which exists precisely to make a new target that
*can* a visible change. It is doubly inert here: Natural Cure cures its holder's status on
switching **out**, which a wild target never does.

That is twice now that this set has been the thing a new target broke (§20 was Insomnia). The
pattern is worth naming: the conservative default is correct, and the cost of it is that every
new ability on the table owes a row in one of the two sets.

---

## 22. As built — the three legendary titans, and a block that was half-missing (clayton-6xu.10.1, .2, .3, .7)

Regirock, Regice and Registeel are in: all Lv30, all Clear Body, all catch rate 3, all
platinum-only, and `unsupported_moves` is clean for all three.

| | slot 1 | slot 2 | slot 3 | slot 4 |
| --- | --- | --- | --- | --- |
| Regirock | Stomp | **Rock Throw** (90) | Curse | Superpower |
| Regice | Stomp | **Icy Wind** (95) | Curse | Superpower |
| Registeel | Stomp | **Metal Claw** (95) | Curse | Superpower |

**Explosion is shifted out of all three**, and that is asserted rather than assumed because it is
the first thing to fear about a Lv30 legendary. Five entries are learnable at 30 — Explosion(1),
Stomp(1), the type move(9), Curse(17), Superpower(25) — and `BoxPokemon_ReplaceMove` bubbles the
oldest off the front, so Explosion is exactly the one that goes.

They differ in **exactly one slot**, and that slot is where all the identification value lives:
the rest of the kit is accuracy 100 or 0, and two of its four moves spend no roll at all.

### 22.1 Half their kit is free, which makes them quiet rather than easy

| move | rolls beyond a move of its class | why |
| --- | --- | --- |
| Curse (109) | **0** | accuracy 0, and a DIRECT side effect — `TriggerPrimaryEffect`'s second branch applies it with no chance roll |
| Superpower (182) | **0** | `MOVE_SIDE_EFFECT_ON_HIT`, so it returns from the FIRST branch of `TriggerSecondaryEffect`, before any `% 100` |
| Stomp (150) | 1 | indirect without ON_HIT → the probabilistic branch, 30% |
| Metal Claw (139) | 1 | same branch, 10% |

So a Curse turn is **blind** to RTC-second siblings: the selection roll, the post-move advances,
and nothing else. Separation on this target comes from Stomp's and Metal Claw's `% 100` procs
(100 does not divide 256) and from the one sub-100 accuracy slot.

Superpower's `effect_chance` is 0, which is a free cross-check on the flag reading:
`GF_ASSERT(effectChance != 0)` guards both probabilistic branches, so the move provably never
reaches one. The ON_HIT / probabilistic split is kept as **two tables**
(`ON_HIT_SELF_CHANGES` and `SECONDARY_SELF_CHANGES`) precisely because it is an advance
difference and not a flavour of the same thing.

Stomp needed almost nothing: effect 150 was **already** in `FLINCH_EFFECTS`, so every flinch site
already handled it and it was missing only from `MODELLED_TARGET_EFFECTS` — the same one-row shape
Growth's addition had for Shaymin. Its `POWER_MULTI` 10/20-against-Minimize is ×1 always, since no
party move is Minimize: effect 149's situation, modelled by being inapplicable.

### 22.2 Clear Body is the Mist block with a second way in

`battle_script.c:2876-2886` checks `mistTurns` and then Clear Body / White Smoke in **consecutive
branches of the same `else`**, both setting `result = 1`. So this was never new machinery, and
`stat_drop_blocked_by` is now one test for both. White Smoke comes along for free because the ROM
tests the two in one condition. Keen Eye and Hyper Cutter are three lines further down and go
through `AbilityBlocksSpecificStatReduction`, which guards one stat each — a different shape, and
nothing in play has either.

What it does **not** do is the part that makes these targets awkward. The ROM's guard is
`attacker != sideEffectMon`, so Clear Body says nothing about a titan's own stat changes:

* **Curse stacks +1 Atk and +1 Def a turn, for zero rolls, and we cannot answer it.** Screech,
  Metal Sound, Charm and Flash are all modelled and all do precisely nothing here. Defence climbs,
  False Swipe gets worse, Superpower gets stronger. **Haze is the only answer** and §17 currently
  keeps the solver off it — filed as clayton-6xu.10.10, and this is the first target where that
  refusal is wrong rather than right.
* **Superpower softens the titan for us**, −1 Atk and −1 Def every time it lands, partly undoing
  the Curse. It is the one thing in their kit working in our favour.

### 22.3 And the block was half-missing, on both sides

Secondary stat drops were blocked by **nothing at all** — not Mist, not an ability, on either
half of the turn. The ROM's guard sits in the shared stat-stage handler and does not care which
effect asked, so the target's Mist refused our Screech and waved our Crunch through. That was a
latent gap before Clear Body; **with** Clear Body it is a wrong prediction, since all three titans
would have taken a secondary drop their ability refuses.

The reachable half of the fix is better than symmetry. **Metang and Metagross have Clear Body**,
and a Metang is this project's whole reason for existing — so a party member holding it refuses
Icy Wind's 100%-chance Speed drop and Crunch's Defence drop outright. Tested with a control run
at Pressure, so the assertion is about the ability and not about the seed.

Mist's **side** is kept straight in the process: `mist_turns` is the target's, so it is consulted
only for a drop we aim at the target. Passing the field unconditionally would have credited the
target's Mist with blocking the target's own Icy Wind against us.

> **A field whose name stopped being true.** `MoveOutcome.blocked_by_mist` was a bool, accurate
> while Mist was the only blocker, and would have read `True` for an ability that is not Mist. It
> is now `drop_blocked_by: str` carrying the reason — `"Mist"`, `"Clear Body"`, `"White Smoke"`
> — which is also what any future message would be built from. One test asserted the old field.

### 22.4 Signed stage changes, and why the two old helpers were left alone

Curse is the first move on either side whose self-package moves stats in **both directions at
once**, so `apply_stat_changes` is new rather than a change to `apply_stat_drop` or
`apply_stat_raise`. Those two carry every emulator-verified path, and a drop expressed as a
positive number — `apply_stat_drop`'s convention — is simply not the same shape as a signed
change, so merging them would have rewritten callers instead of adding a case.

Clamped per pair and in order, which is what the ROM does: each stat is its own
`UPDATE_STAT_STAGE` call taking its own no-change branch. A titan at −6 Speed keeps Cursing for
the Attack and Defence at exactly the same cost, because none of the three calls spends a roll —
so this is **not** a `will_fail` case, for the same reason §19 found the stage ceiling was
modelled backwards.

### 22.5 Checked in passing: the `effect_chance > 0` gate is right for the whole family

`execute_move` spends a proc roll whenever `effect_chance > 0`, and Icy Wind's chance is 100 —
which looked like it might be an ON_HIT move paying a roll it should not. It is not: effects 70,
69 and 31 all set INDIRECT **without** ON_HIT, so each really does pay a `% 100` roll, Icy Wind
included. That roll is spent and always lands (`roll % 100 < 100`), so it is blind but real. No
pre-existing bug, which was worth confirming rather than assuming given how many of these
readings have gone the other way.

### 22.6 Still owed for Regigigas

The Lv1 king is a different fight and is not in yet. It is blocked on three things, each filed:
**Slow Start** (clayton-6xu.10.5 — it is in `UNMODELLED_ATTACKER_ABILITIES`, so Regigigas is
refused outright today), **confusion aimed at us** (clayton-6xu.10.4, the only structurally new
mechanic in the whole set), and **Knock Off** (clayton-6xu.10.6, which takes our held item).

> **Corrected:** an earlier version of this said Knock Off threatens "our Lagging Tail" and so
> flips turn order. That was a mis-transplant from `metronome_compass`, which is the thing that
> mandates a Lagging Tail (`metronome_abilities.py`, and `app/models.py` validates it on the
> Metronome user). **Battle Compass never asks for one**, and `sim` deliberately keeps Lagging
> Tail out of the speed-item handling because it sets a lowered-priority flag rather than
> touching Speed. Knock Off still matters — Leftovers stops ticking, an accuracy item stops
> applying, a Silk Scarf's 20% comes off our chip damage — but turn order is at stake only if the
> party chose a Speed-affecting item, which is a decision rather than a mandate.

---

## 23. As built — Regigigas in pieces: Slow Start and Knock Off (clayton-6xu.10.5, .6)

Two of the three Regigigas blockers are down. Confusion (clayton-6xu.10.4) is the remaining one,
and until it lands there is deliberately **no `ENCOUNTERS` row** — `unsupported_moves` would
refuse it, which is the check doing its job.

### 23.1 The design decision that shrank Knock Off: no held items

**Testare's call: bring nothing to the Regigigas fight.** That converts the hardest-looking piece
of this target into a configuration rule, and the ROM says the trade is clean —
`BtlCmd_TryKnockOff` (`battle_script.c:6608-6634`) takes its `else` branch when the defender
holds nothing: no message, no state change, no `Random` on any path. Combined with the `ON_HIT`
flag (no proc roll), **Knock Off against an item-less lead is plain 20 BP damage.**

Checked rather than assumed, because "we probably don't need items" is the kind of claim worth
verifying:

* **Survivability.** A Lv1 Regigigas' Attack is about 4 once Slow Start halves it, firing a 70 BP
  Dizzy Punch and a 20 BP Knock Off. Measured here at ≤5 damage against an ordinary Lv50 lead.
  Leftovers would be answering a threat that does not exist.
* **Chip.** False Swipe reaches 1 HP on a 13 HP target in **one hit**, so a type-enhancing item
  buys nothing — the chip phase is one turn long.
* **Accuracy.** An accuracy-raising item would make our own sub-100 move *less* useful as a
  second-sibling separator — and that move is the only separation this target offers, since
  everything in its own kit is accuracy 100 or 0 and its confusion, duration and damage-variance
  checks all have moduli that divide 256. So an item here is actively counterproductive.
* The one real candidate was a **Lum Berry against Confuse Ray**, and **Own Tempo dominates it**:
  permanent, not consumed, and it refuses both of `subscript_confuse`'s paths.

The removal is modelled anyway — it is two lines, and a player who carries an item regardless
should get a correct simulation rather than a silently wrong one. Tested that the roll count is
**identical** with and without an item, which is the statement that matters: carrying nothing
removes a consequence, not a cost.

> **And it answered the bead's open question.** `TryKnockOff` tests **Sticky Hold** in the same
> function that reads the item, *before* reading it. So Sticky Hold is a second way out — and a
> worse one than carrying nothing.

### 23.2 Slow Start, and a Gen-4 trap that turned out not to be one

`slow start` was in `UNMODELLED_ATTACKER_ABILITIES`, so `unsupported_attacker_reason` refused
Regigigas outright at `sim.py` and `solver.py` — which made this the **gate** on the target
rather than a refinement.

Two integer halvings on one condition, `totalTurns - slowStartTurnNumber < 5`. `slowStartTurnNumber`
is stamped when the holder enters and a wild target is out from the start, so it is 0 for every
reachable case and the condition reduces to `turn < 5`. `BattleState.turn` is the ROM's
`totalTurns` — the same figure the Timer Ball already reads.

**The trap that wasn't.** `battle_lib.c:6713` halves `attackStat`, and Huge Power sits three
lines above doing `attackStat * 2` — a pairing that is a known Gen-4 quirk area, so it looked
like Slow Start might halve Sp. Atk for a special move. It does not: `attackStat` is assigned
from `BATTLEMON_ATTACK` at `:6635` and **`spAttackStat` is a separate `u16`** declared three
lines earlier. Physical Attack only, exactly as documented. Moot for Regigigas — both its attacks
are physical — and pinned with a test because the next reader will wonder the same thing.

**Order: after paralysis, not before.** Quick Feet and paralysis are one if/else at `:1257-1261`
and the Slow Start halving is the next statement at `:1263`. Each step truncates, so this is
recorded even though `spe / 4 / 2` and `spe / 2 / 4` agree on these figures — the next ability
added to that chain will depend on it.

`turn=None` means "do not apply", a documented escape hatch for an advisory caller asking about a
Pokemon outside any turn. Every call site inside a simulated turn passes the turn.

> **What it buys us is a guarantee, not a cost.** A Lv1 Regigigas at 3 effective Speed cannot tie
> anything we would bring, so the no-speed-tie contract (§4.2) holds for **free** here — no
> paralysis needed to buy it — and ties stay out of the search entirely.

### 23.3 Measured in passing: the max HP is pinned

`(2 * 110 + IV) * 1 / 100` floors to 2 for every IV 0–31, so **Regigigas' max HP is exactly 13,
whatever its spread**. That is stronger than `catch_value`'s usual note that a catch-rate-3
target lands on `a = 2` at 1 HP for any max HP ≥ 2: here there is no HP-IV uncertainty at *any*
HP, so the ball-and-HP readout (clayton-6xu.9.4) is exact for this target rather than a range.

### 23.4 Still owed

**Confusion aimed at us** (clayton-6xu.10.4) is the last blocker, and the only structurally new
mechanic in the whole regi set: a counter, a per-turn `& 1` check costing one advance, and a
self-hit costing a second for its damage variance. `Battler.confused` already exists as a field
documented as never set by anything — that is what it is for. Once it lands, the row
(clayton-6xu.10.7) and the no-held-items advice both have somewhere to attach.

---

## 24. As built — confusion, and the regis are complete (clayton-6xu.10.4, .7, .12)

All four regis are supported: Regirock, Regice and Registeel at Lv30 and **Regigigas at Lv1**,
every move modelled, every row live.

### 24.1 The token grammar was already waiting for it

Confusion looked like the biggest piece in the set and turned out to be the smallest surprise,
because `tokens.py` had already been built for it: `cfz` for a self-hit, `scfz<slot>` for
snapping out and then moving, and `RESOLUTION_DETAIL` existing with confusion as its sole member
and an explicit justification — *sleep and freeze need no wear-off marker because the move
happening at all proves the status ended, while a confused Pokemon attacks perfectly normally.*
Only the simulation was missing. The arc now renders exactly as that grammar anticipated:

```
turn 1  M1 h E3          Confuse Ray lands, 4 turns rolled
turn 2  Mcfz E3 HP182    hurt itself, move lost
turn 3  M1 h E3          passed the check, attacked normally
turn 5  Mscfz1 h E3      snapped out, then used move 1
```

### 24.2 The two routes differ in what a refusal COSTS

This is the part a flag-shaped model would have got wrong, and it is why Confuse Ray and Dizzy
Punch are modelled apart rather than as one "may confuse" case.

Every branch of `subscript_confuse.s` that refuses a **direct** confusion sets
`MOVE_STATUS_NO_MORE_WORK` (``_128`` already confused, ``_141`` Own Tempo, ``_167`` Safeguard,
all via ``_178``) — so Confuse Ray is a `will_fail` family and costs the turn what every other
family costs. Reached **indirectly**, those same branches each test
`SIDE_EFFECT_TYPE_INDIRECT` first and jump straight to ``_185``: the move still dealt its
damage, and nothing extra was spent. So a refused Dizzy Punch is *cheaper*, not a failure.

`confusion_lands_on` is one predicate shared by both routes, because three refusals written
twice is three chances to drift.

| | Confuse Ray (direct) | Dizzy Punch (secondary) |
| --- | --- | --- |
| lands | accuracy + duration = **2** | accuracy, crit, damage, proc, duration = **5** |
| refused | `will_fail`, accuracy only | accuracy, crit, damage, proc = **4** |
| Shield Dust | cannot refuse it | refuses it |

### 24.3 Three things the ROM settled about the self-hit

`CALC_SELF_HIT(MOVE_STRUGGLE, 40)` then `BattleSystem_CalcDamageVariance`, and all three of
these are easy to assume wrongly:

* **It is our Attack against our own Defence**, with our own stages on both ends — the macro
  passes the attacker as its own defender. A +2 Attack of ours makes confusion hurt *more*.
* **It is typeless with no STAB**, and the reason is mechanical rather than folklore:
  `BattleSystem_ApplyTypeChart` is never called, and STAB lives *inside* that function at
  `battle_lib.c:2593`. Pinned by asserting a Ghost lead takes the same self-hit as a Normal one.
* **Weather never touches it.** The macro passes `sideConditions = 0` *and*
  `fieldConditions = 0`, so neither Reflect nor rain applies — a self-hit in the rain is the same
  number as one in the clear. Pinned by asserting the function has no field parameter at all.

Burn halves it **inside** the formula (`:6977`), a different truncation point from
`_attacker_side`'s burn halving, so it is done the ROM's way here rather than by reusing that path.

And the duration is `(rand % 4) + 2` = **2 to 5**, not 2 to 4 — `BtlCmd_Random` does
`range += 1`. Verified by sweeping seeds and asserting the observed set is exactly {2,3,4,5}.
Decrement-before-check means a duration of N gives N−1 rolled turns.

> **A flag became a counter, and the flag became derived.** `Battler.confused` was honest while
> nothing inflicted confusion. It is now a read-only property over `confusion_turns`, so the two
> cannot drift — and `replace(..., confused=True)` raises, which is the loud failure the rename
> wanted. Both existing readers (the interview and the snapshot) needed no change.

### 24.4 And the bug it fixed on our own side

`MODELLED_OUR_EFFECTS[76]` said *"the proc roll only; confusion ON THE TARGET is inert here"*.
That was a live desync: `subscript_confuse.s` reaches ``_076`` on the indirect route too, and
``_076`` rolls `Random 3, 2` — so a procced Signal Beam of ours spent a duration advance the
simulator did not, and every turn after it read the wrong rolls. A procced Signal Beam now spends
five advances where it spent four, and four against Own Tempo, where the ROM jumps past the roll.

Nothing about that bug was Regigigas-specific; it was found by reading the regi effects and fixed
by the same machinery pointed the other way. That is now the fourth target in this file whose
reading turned up a defect in shipped behaviour.

### 24.5 Separation: Regigigas is the worst case on the table

Worth stating because the natural guess is the opposite — a target that confuses you sounds like
it offers plenty to observe. By `notes/seed_separation.md`'s rule, a check is permanently blind to
RTC-second siblings iff its modulus divides 256:

| check | modulus | separates? |
| --- | --- | --- |
| move selection | `% 4` | no |
| confusion check | `& 1` | no |
| confusion duration | `% 4` | no |
| self-hit variance | `% 16` | no |
| accuracy | every move is 100 or 0 | no |
| **Dizzy Punch proc** | `% 100` | **yes** |

So **nothing in Regigigas' own kit separates siblings except one roll it makes a quarter of the
time.** Identification against it has to come from our side — a sub-100 move of ours, or an early
standard-ball probe — which is also the reason an accuracy-raising item would make this target
*harder* rather than easier, and the last argument for the no-held-items rule in §23.1.

### 24.6 Still owed

Four children remain, none blocking: **Haze against Curse stacking** (clayton-6xu.10.10, the
first target where §17's refusal is wrong), the **Own Tempo advisory** (clayton-6xu.10.11, now
that confusion exists to advise about), the **cave-terrain gdb question** for all four venues
(clayton-6xu.10.9), and the **Lv1 ball-and-HP readout** (clayton-6xu.10.8). The access gating —
the ruins needing an event Regigigas and Snowpoint needing the trio — is recorded on the epic but
not yet expressed as `ENCOUNTER_ACCESS`; it belongs with clayton-6xu.9.12.
