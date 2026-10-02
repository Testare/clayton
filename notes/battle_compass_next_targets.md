# Next targets: Lugia, Ho-Oh, Latias/Latios

Planning only — nothing here is implemented. Every number in section 1 is read out of the
decompilation at `~/arch/pokeheartgold`, with the file and line that produced it, because an
encounter's level and moveset are not derivable from anything in this repo and a guessed moveset
would silently mis-simulate every turn (`battle_compass/targets.py`).

**This profile is SoulSilver** (`SS - DSi`), which decides which variant of each target you
actually face. The version differences are not cosmetic — they change the level by 25 and the
moveset entirely.

---

## 1. What the ROM says

### The two tower birds — `WildBattle <species>, <level>, 0`

Both read the level from a `GetGameVersion` branch; `VERSION_HEARTGOLD = 7`,
`VERSION_SOULSILVER = 8` (`include/config.h:9`).

| | HeartGold | SoulSilver | script |
|---|---|---|---|
| **Ho-Oh** (Bell Tower) | **Lv45** | **Lv70** | `scr_seq_0021_D17R0110.s:63-73` |
| **Lugia** (Whirl Islands) | **Lv70** | **Lv45** | `scr_seq_0104_D40R0107.s:75-85` |

Suicune is `WildBattle SPECIES_SUICUNE, 40, 0` with **no** version branch
(`scr_seq_0024_D18R0102.s:247`) — which confirms the existing fixture's Lv40 for both versions.

### Latias / Latios — one roams, one is a static battle

* **Roamer, Lv35.** `field_roamer.c:180-204`, same table that gives Raikou and Entei Lv40.
* **Pewter City event, Lv40.** `scr_seq_0750_T03.s:364-381`: version 7 → `SPECIES_LATIOS`,
  else → `SPECIES_LATIAS`, then `WildBattle VAR_TEMP_x400A, 40, 0`.

So on **SoulSilver**: **Latios roams at Lv35**, **Latias is the Pewter static at Lv40**.
(The event one *is* a battle — the Enigma Stone triggers an encounter, not a gift.)

### Movesets, derived from `wotbl.narc`

Learnset entries are `u16` = `(level << 9) | moveId`, terminated `0xFFFF`
(`include/pokemon.h:17-25`). `InitBoxMonMoveset` (`src/pokemon.c:3035-3059`) walks them in order,
appending every move learnable at ≤ level and, when full, **deleting the first and appending** —
so the result is the last four learned, **in learn order**, which is exactly the slot order the
`E1`-`E4` tokens and the wild selection roll depend on.

| target | level | slot 1 | slot 2 | slot 3 | slot 4 |
|---|---|---|---|---|---|
| Suicune *(done)* | 40 | Rain Dance | Gust | Aurora Beam | Mist |
| **Lugia** | **45** | Extrasensory | Rain Dance | Hydro Pump | Aeroblast |
| Lugia | 70 | Aeroblast | Punishment | Ancient Power | Safeguard |
| Ho-Oh | 45 | Extrasensory | Sunny Day | Fire Blast | Sacred Fire |
| **Ho-Oh** | **70** | Sacred Fire | Punishment | Ancient Power | Safeguard |
| **Latios** *(roamer)* | **35** | Dragon Breath | Protect | Refresh | Luster Purge |
| **Latias** *(Pewter)* | **40** | Water Sport | Refresh | Mist Ball | Zen Headbutt |
| Latias *(roamer)* | 35 | Dragon Breath | Water Sport | Refresh | Mist Ball |
| Latios *(Pewter)* | 40 | Protect | Refresh | Luster Purge | Zen Headbutt |

**Recover is L71 on the birds and L45 on the Lati twins**, so *no relevant moveset has a healing
move.* That was the single biggest risk going in — a target that can heal off 1 HP would
invalidate §2.2's frozen-target model and the solver's whole dominance key — and it is not a
problem for any of these.

---

## 2. Start advances: 6, and now believed GENERAL rather than venue-specific

§16.2 and §16.1 explain the verified `BATTLE_START_ADVANCES = 6` as "4
`bellShimmerReplaceGraphics` (the Bell Tower's Suicune shimmer) + 2 Pressure", and call the 4
venue-specific. **The count stands; the breakdown and the venue claim do not.**

`bellShimmerReplaceGraphics` (`src/field/legend_cutscene_camera.c`) only loads and swaps model
animations — it makes no RNG call — and it is reached only through
`ScrCmd_LegendCutsceneClearBellShimmer`, which the Suicune encounter script **never calls**. The
gdb reader resolves a caller address to the nearest symbol, so `0x02251056` was attributed to a
neighbouring function in the same overlay rather than to the real consumer.

**And 6 has held across every encounter this project has measured** — Suicune (Bell Tower static),
Metang (Safari Zone), Magikarp (Blackthorn) — which is three different venues and three different
encounter *kinds*. That is much better evidence than the attribution was: whatever spends those
four rolls is generic wild-battle setup, not a venue cutscene.

So: **treat 6 as general and do not re-derive it per target.** The number is not in doubt; only the
story about its composition was, and that story is now simply deleted rather than replaced. If a
future encounter ever disagrees, that disagreement is the evidence that reopens it — per CLAUDE.md,
a ground-truth capture is what changes a verified count, and nothing short of one should.

## 3. The ball decides the multiplier, and the plan is to catch all of them

The planned balls are a **Love Ball for Lugia** and probably a **Luxury Ball for Ho-Oh**. Both are
**×1**, verified in `src/battle/battle_command.c`:

* `ballMultiplier = 10; // All ball multipliers are /10, so this is x1.` is the default, and
  **Luxury Ball has no case in the switch at all** — so it stays ×1. It only affects friendship.
* **Love Ball** takes `catchRate *= 8` only when
  `attacker.species == target.species && attacker.gender != target.gender`. Lugia is
  **genderless**, so even Lugia-against-Lugia fails the gender test. **×1.**

So every remaining target is catch rate 3 at ×1 — `b = 21845 / 65536`, **1.23% per throw** at 1 HP
and paralyzed. **Identical to Suicune.** That is the case Battle Compass was built for, and no
target here is a softer version of it.

> An earlier draft of this section ranked the targets by ease and led with Lugia on the strength
> of a ×4 Fast Ball. Two things wrong with that. The ×4 is real — `ITEM_FAST_BALL` does
> `catchRate *= 4` when base Speed ≥ 100, and Lugia's 110 clears it — but it is a property of
> **throwing a Fast Ball**, not of Lugia, whose catch rate is 3 like every other legendary here.
> And ranking by ease answers a question nobody asked: the goal is all of them, so the useful
> ordering is by **how much new machinery each one needs**, which is what §5 now does.

What *does* make Lugia Lv45 the easiest one to *build* is its moveset:

| move | status | note |
|---|---|---|
| Rain Dance | **implemented** | `EFFECT_RAIN_DANCE`, including its `will_fail` when already raining |
| Hydro Pump | **generic** | fixed power, acc 80 — `execute_move` handles it as-is |
| Extrasensory | **mostly** | generic damaging; 10% flinch, and effect 31 is already in `FLINCH_EFFECTS` with a `fln` token and `can_flinch()` |
| Aeroblast | **one gap** | generic damaging, acc 95 — but effect 43 is the high-crit group (Karate Chop, Slash, Crabhammer, Stone Edge…), and `execute_move` hardcodes `CRIT_MODIFIERS[0]`, so it would crit 1/16 instead of 1/8 |

**And accuracy 80 on Hydro Pump is a gift.** Per `notes/seed_separation.md`, a sub-100 accuracy
check is the sharpest seed separator there is — ~49% disagreement per roll between RTC-second
siblings, against 0% for every 100%-accuracy move. Suicune's moveset could not miss at all, which
is why its siblings took a median of 13 turns to separate. Lugia misses on its own, for free,
whenever it picks Hydro Pump or Aeroblast.

## 4. What each other target needs

Ranked by how many targets share the mechanic.

| mechanic | needed by | why it is not already there |
|---|---|---|
| **Crit stage** | Aeroblast (both Lugia sets) | `execute_move` uses `CRIT_MODIFIERS[0]` unconditionally, so a high-crit move crits 1/16 instead of 1/8 — wrong outcome *and* wrong damage |
| **Burn** | Fire Blast, Sacred Fire (both Ho-Oh sets) | status + 1/8 max HP per turn + halved physical Attack. The residual tick means **an HP token on every subsequent turn**, which `turn_requires_hp` must know about or every turn becomes ungrammatical |
| **Sun** | Sunny Day (Ho-Oh Lv45) | a second field condition, plus a weather term in `damage.py`, which has none — sun is ×1.5 on Fire and would make Sacred Fire far worse |
| **Safeguard** | both Lv70 sets | **blocks our Thunder Wave.** §2.2's precondition is a *permanently paralyzed* target, so a Safeguard up before we paralyze is a hard obstacle: paralyze first, or wait out its 5 turns |
| **Punishment** | both Lv70 sets | power 1 in `moves.json` marks variable power, which `unsupported_reason` refuses. Real power is 60 + 20 × our positive stat boosts — so it **interacts with `choose_item`**, whose X Sp. Def tier would be feeding the attack that hits us |
| **Ancient Power** | both Lv70 sets | 10% +1 to all of the *target's* stats. Mostly harmless against a frozen target, except Speed: §4.2's no-speed-tie guarantee is what keeps the roll count predictable, and a stack of boosts could reach a tie |
| **Refresh** | **all four Lati@s sets** | the target **cures its own status**. This breaks the frozen-target model at its root — a target that can shed paralysis is not a Phase 2 target in the current design at all |
| **Protect** | both Latios sets | priority +3, blocks our move outright. Does *not* block a ball, since a ball is not a move |
| **Paralysis on us** | Dragon Breath (30%) | a paralyzed Smeargle may stop outspeeding, losing the speed-tie guarantee |
| **Roamer fleeing** | the roaming twin | a roamer flees at end of turn unless trapped, so Mean Look becomes mandatory on turn 1 and a flee is a terminal outcome the state machine has no concept of |

### Safeguard, and winning the Thunder Wave race

Safeguard is slot 4 in **both** Lv70 sets, so on this profile Ho-Oh will raise it roughly one turn
in four. §2.2's Phase 2 precondition is a *permanently paralyzed* target, so a Safeguard up before
we land Thunder Wave is a hard block — wait out its five turns and try again, or get in first.

Getting in first is the part worth planning, and it has a catch: **the speed guarantee we normally
rely on comes FROM paralysis**, so it does not exist on the turn we are trying to apply paralysis.
That turn is the one race in the whole run we have to win on raw Speed.

**The spread being targeted is 31 Speed IV with a non-boosting nature**, which puts Ho-Oh Lv70 at
**Speed 152**. So the bar is:

* **153+** bare, or
* **102+** with a Choice Scarf (×1.5, floored).

It has to be *strictly* greater. A tie is not neutral — a speed tie consumes an extra roll
(`notes/ss_rng/speed.md`), which is exactly the unpredictability §4.2 exists to eliminate. Pikachu
is the illustration: at Lv70 with 31 IVs and a neutral nature it lands on **exactly 152** and ties.

Every species that learns Thunder Wave **by level-up** in HGSS, by base Speed (22 of them;
Thunder Wave is also TM73, which opens the list up enormously, so treat this as a floor not a
menu):

| species | base Spe | learns TW | Lv50 | Lv70 | clears 152? |
|---|---|---|---|---|---|
| Jolteon | 130 | L57 | 150 | 208 | Lv50 scarfed · **Lv70 bare** |
| Manectric | 105 | L1 | 125 | 173 | Lv50 scarfed · **Lv70 bare** |
| Zapdos | 100 | L8 | 120 | 166 | Lv50 scarfed · **Lv70 bare** |
| Rotom | 91 | L1 | 111 | 154 | Lv50 scarfed · **Lv70 bare** |
| Pikachu | 90 | L10 | 110 | 152 | Lv50 scarfed · Lv70 **ties — avoid** |
| **Magneton** | 70 | L17 | 90 | 124 | Lv70 scarfed (186) |

Two things worth drawing out:

* **The Magneton already in the party gets there** — at Lv70 it is 124 bare, 186 scarfed, clear of
  152. At its current Lv31 (Speed 50) it is 75 scarfed and nowhere near, so this is a levelling
  job rather than a new Pokemon.
* **A Lv70 Jolteon needs no scarf at all** (208 bare), which sidesteps the Choice lock entirely.

Two small pieces of machinery this needs: `effective_speed()` reads `battler.stats["spe"]` and
knows nothing about held items, and the in-game summary screen does not include a Choice Scarf's
boost either — so a Speed-modifying held item has to be modelled rather than entered. And a Choice
item **locks the holder into its first move**, which is fine for a dedicated paralyzer that
switches out afterwards, but the solver must not be allowed to pick a second move for it.

---

## 4a. How the game picks the roamer over the normal encounter

Answered exactly, in `src/field/encounter_check.c`.

Both the walking and Sweet Scent paths call the same helper, `getRandomActiveRoamerInCurrMap`:

```c
for (u8 i = 0; i < ROAMER_MAX; ++i) {
    u32 mapId = GetRoamMapByLocationIdx(Roamer_GetLocation(saveRoamers, i));
    if (GetRoamerIsActiveByIndex(saveRoamers, i) && mapId == fieldSystem->location->mapId) {
        foundRoamers[nRoamers] = ...; ++nRoamers;
    }
}
if (nRoamers == 0)      return FALSE;
if (LCRandRange(2) == 0) return FALSE;          // <-- a 50/50 coin flip
if (nRoamers > 1) {
    u16 chosenRoamer = LCRandRange(nRoamers);   // <-- which one, if several
    *pRoamer = foundRoamers[chosenRoamer];
}
return TRUE;
```

So, in order:

1. Collect every **active** roamer whose current location maps to the map you are standing on.
2. None → normal encounter.
3. **`LCRandRange(2) == 0` → normal encounter anyway.** Standing on the right route is a coin flip,
   not a guarantee.
4. More than one roamer on the map (Raikou, Entei and a Lati twin can overlap) → a second roll
   `LCRandRange(nRoamers)` picks which.
5. Otherwise: `BATTLE_TYPE_ROAMER`, `initRoamingWildmon` reads species/level/IVs/PID straight out of
   the save, and a forced wild battle starts.

**The consequence that matters for this project:** `LCRandRange(n)` is
`LCRandom() % n` (`include/math_util.h:30`), so that coin flip **spends one advance of the overworld
(Seed A) stream** — and it is spent *before* the normal encounter generation. Two things follow:

* On a route with an active roamer, an encounter check costs **one extra Seed A advance** compared
  to a roamer-free route (**two** if two roamers are on the map). Every advance-frame calculation
  in `safari_advance` and the frame guide is off by that much on such a route.
* But the outcome is therefore **deterministic and steerable**. At a known Seed A frame you know
  which way the coin falls, so "stand on the route and hope" becomes "land on a frame where the
  flip gives the roamer". That is the same kind of problem the frame guide already solves.

Two asymmetries between the paths, both worth knowing:

* **Walking** runs `FieldSystem_EncounterRateRoll` *first*; if that fails there is no encounter and
  the coin flip is never spent. Sweet Scent has no rate roll, so the flip happens every time.
* **Repel**: on the walking path, a roamer that wins the flip can still be suppressed by Repel —
  and when it is, the function returns `FALSE` outright, so the encounter is *lost* rather than
  falling through to a normal one. The Sweet Scent path has no Repel check on the roamer branch at
  all.

(`followerFlag` gates both, but the decomp comment notes it is always FALSE in HGSS.)

### Predicting which advance frames give the roamer — one bit, no generation

**You do not have to simulate Pokemon generation at all.** For a Sweet Scent with exactly one
active roamer on the map:

```python
roamer_on_frame = (advance_rng_n_times(seed, frame + 1) >> 16) & 1 == 1
```

That is *the same roll* `safari_encounters.frame_slot` already computes — one advance past the
frame — taken `% 2` instead of `% 10`. The machinery exists; only the modulus changes.

Two facts make generation irrelevant:

1. **The flip precedes all generation.** On the Sweet Scent path it is the *first* roll: there is
   no encounter-rate roll, and `getRandomActiveRoamerInCurrMap` runs before
   `FieldSystem_CreateBattleSetupForWildBattle`.
2. **A winning flip generates nothing.** `initRoamingWildmon` calls
   `CreateMonWithFixedIVs(species, level, ivs, pid)` → `CreateMon(..., fixedIV=0,
   hasFixedPersonality=1, otIdType=0, ...)`, and in `CreateBoxMon` every one of those arguments
   takes the branch that skips the RNG: `hasFixedPersonality == 1` skips the two personality
   rolls, `otIdType == 0` is neither 2 nor 1 so the OT-ID rolls are skipped, and `fixedIV < 0x20`
   takes the no-roll IV branch (then `MON_DATA_COMBINED_IVS` overwrites it with the saved word).
   **Zero generation rolls.** Species, level, IVs, PID, status and HP all come out of the save.

So a roamer encounter is *cheaper* to predict than a normal one: a normal Sweet Scent needs the
slot draw plus the species/level table, the roamer needs one bit and nothing else.

> **The 50% is what the code says, and it is worth a measurement.** The only probability gate on
> the roamer path is that single `LCRandRange(2)`. I searched for another: there are exactly two
> call sites, both unguarded beyond `followerFlag`, and the only other roamer RNG anywhere is
> relocation (`field_roamer.c`'s `LCRandom() % 16` teleport-vs-adjacent choice, and the location
> draws themselves). Nothing multiplies the rate down. But a believed figure of **1 in 4** is on
> the record from play experience, and if that is right then this predicate is wrong — it would
> be two bits, not one, and the frame density would quarter. Settle it before relying on it:
> the flip is a single identifiable roll, so one forced-seed capture on the roamer's route shows
> directly whether the first roll's low bit predicted the outcome.

Measured over 2000 frames of a real seed (`0x0C0E02CA`), **assuming the 50% above**:

| | |
|---|---|
| frames that give the roamer | **999 / 2000 = 50.0%** |
| gap to the next roamer frame | min 1, **max 11**, mean 2.00 |
| half the time | the very next frame works |

The bit is also well behaved, which was worth checking because `% 2` on an LCRNG is exactly where
weak low-order bits show up: 49.7% ones over 4000 rolls, and agreement at lags 1, 2, 3, 4, 8 and
16 all sit within a point of 0.5. No short period, no bias. Roamer frames are *abundant* — hitting
one is a far easier targeting problem than finding a shiny frame.

**Three caveats.**

* **Two roamers cannot share a map, so the tiebreak roll never fires.** An earlier draft here
  claimed Raikou, Entei and a Lati twin could overlap and cost a second bit. They cannot:
  `RoamerLocationSetRandom` confines Raikou and Entei to `ROAMER_LOC_JOHTO_*` indices and the
  Lati twin to `ROAMER_LOC_KANTO_*`, so `nRoamers` is always 1 in practice and
  `LCRandRange(nRoamers)` is effectively dead code. (The location *table* is shared, which is
  what made the overlap look possible — but the index range each roamer draws from is not.)
* **Walking is messier than Sweet Scent.** `FieldSystem_EncounterRateRoll` spends one
  `LCRandRange(100)`, and a *second* one via `FieldSystem_SecondEncounterRoll` only if the first
  passes — so the number of rolls before the flip is outcome-dependent (1 or 2), against a rate
  that depends on the tile, the lead's ability, a flute and a held item. Predictable, but fragile.
  Sweet Scent is the clean way to frame-target a roamer.
* **Multi-attempt is the one place generation would matter.** A *failed* flip runs the full normal
  encounter generation, so predicting a second attempt from the same starting point needs that
  roll cost. In practice you re-pin the frame from Elm calls between attempts — which the frame
  guide already does — so it does not come up.

### Two structural notes on the roamer

**Its IVs are fixed in your save, not by the encounter.** `CreateRoamer`
(`field_roamer.c:204-215`) calls `CreateMon` and stores `ROAMER_DATA_IVS` / `ROAMER_DATA_PERSONALITY`
at *setup* time — a one-off story event. So unlike the birds there is nothing to steer: the spread
is already decided, and you read it off once rather than targeting an advance frame. What Seed A is
still good for is the roamer's **location** — a seed that puts it on a chosen route is what lets
you go and wait there — and for centring Seed B, which is unchanged.

**Seed B's provenance differs.** Seed B is verified for Sweet-Scent and static A-press encounters
(CLAUDE.md). A roamer is a route encounter, closest to the Sweet-Scent case.

## 4b. Latias Lv40 (SoulSilver Pewter event): put it to SLEEP, not to sleep-adjacent

Moveset confirmed from `wotbl.narc`: **Water Sport / Refresh / Mist Ball / Zen Headbutt**. Two
things about it pull in opposite directions, and the resolution is cleaner than either.

**The Fast Ball really does apply.** Latias's base Speed is 110, clearing the ×4 threshold
(`catchRate *= 4` when base Speed ≥ 100), so catch rate 3 becomes 12. Unlike Lugia-in-a-Love-Ball
this one is not academic.

**Refresh really does shed paralysis** — and it is the only move in any planned target's set that
breaks §2.2's frozen-target precondition at the root.

### The resolution: Refresh is self-targeting, so a sleeping Latias cannot use it

Use **sleep** as the status instead of paralysis, and Refresh stops being a problem in three
separate ways:

1. **It cannot be used at all while the target is asleep**, because sleep prevents the move.
2. **Awake and unstatused, Refresh cures nothing**, so it fails — a wasted turn for Latias on
   roughly one turn in four. Refresh goes from a threat to a gift.
3. **Sleep is the better catch status anyway**: ×2 against paralysis's ×1.5
   (`STATUS_SLEEP = 20`, `STATUS_PARALYSIS = 15`, in tenths).

Latias Lv40 at 1 HP, 31 HP IV (max HP 126):

| ball | status | `b` | P(catch) per throw |
|---|---|---|---|
| ×1 | paralyzed | 21845 | 1.23% |
| Fast (×4) | none | 29958 | 4.37% |
| Fast (×4) | paralyzed | 33824 | 7.10% |
| **Fast (×4)** | **asleep** | **36157** | **9.27%** |

For scale, Suicune and Ho-Oh are both 1.23% — so a sleeping Latias in a Fast Ball is **7.5×
easier per throw** than either.

### And sleep costs nothing on turn order, which is the only reason paralysis was mandated

§4.2 requires paralysis because quartering the target's Speed guarantees we move first, and a
speed tie costs an extra roll. Here that guarantee survives without it: Smeargle at Lv58 has
Speed 160, and a Lv40 Latias tops out at **115** even with 31 IVs and a boosting nature. We
outspeed every possible spread, awake or not.

| Latias Lv40 spread | Speed | Smeargle (160) first? |
|---|---|---|
| 0 IV, hindering | 83 | yes |
| neutral, 31 IV | 105 | yes |
| max | 115 | yes |

### What it actually costs, and what needs building

**Sleep expires.** The duration is `2 + RAND % 4`, so 2-5 turns, rolled when it is applied (the
simulator already spends that roll — `SLEEP_DURATION_MIN/SPAN`). So this is a *window*, not the
permanent state §2.2's model is built on, and Phase 2 would have to carry the sleep counter and
the wake-up. That is `clayton-hdo.1`, already open: *"sleep on the target is unmodelled beyond its
duration roll."* It is the one genuine prerequisite.

**It cannot be topped up.** A status move against an already-statused target fails, so you wait
for the wake and re-Spore — you do not refresh the counter early. Budget is comfortable though:
**Latias's ability is Levitate, not Pressure** (`personal.json`), so our PP consumption is *not*
doubled and Spore's 15 PP is 15 applications rather than 7. (Levitate itself is irrelevant to
False Swipe and Spore.)

**`will_fail` needs a Refresh case.** It currently returns True for a status move against an
already-statused target and for the three field conditions, and knows nothing about a Refresh
with nothing to cure. Without it the simulator would spend Refresh's two post-successful-move
advances where the game skips them — precisely the bug that desynchronised test1 at turn 3.

**A bonus:** Zen Headbutt is 90 accuracy, so Latias self-separates for RTC-second siblings the
way Lugia does (§3) and Suicune never did. Mist Ball's 50% Sp. Atk drop lands on us and does not
matter; Water Sport is a no-op against anything we do.

## 4c. Itemised: what supporting Latias actually requires

Grounded in the code rather than estimated. Each item names the line that assumes otherwise.

### A. Lift the paralysis precondition — 4 places, all small

The contract "1 HP and **permanently paralyzed**" is asserted in two places and stated in several
more. Sleep satisfies the *purpose* (a frozen target, a constant `b`) but not the letter.

| # | where | what it does now |
|---|---|---|
| A1 | `identify.solver_blockers` (~L225) | `if state.target.status is not Status.PARALYSIS` → "the target is not paralyzed" |
| A2 | `solver.solve` (~L320) | same check again, returns `Unreachable` with `proven=False` |
| A3 | `battle_compass/__init__.py`, `state.py`, `solver.py` docstrings | state the contract as paralysis specifically |
| A4 | `app/web/index.html` (~L3922, L5160, L5466) | "Suicune is at 1 HP and paralyzed", and the force-solving confirm text |

The replacement is not "accept any status": it is **accept paralysis, or sleep with a known
remaining duration**. Burn and poison would also satisfy the catch bonus and fail the frozen-state
requirement, because they tick HP every turn.

### B. Model sleep properly — the real prerequisite (`clayton-hdo.1`)

This is the bulk of the work, and it is worse than "unmodelled": it is currently **wrong**.

| # | gap | detail |
|---|---|---|
| B1 | **A sleeping target acts normally** | `sim.act_target` (~L592) checks only `Status.PARALYSIS`. A sleeping target falls through and attacks. Not an omission — a wrong simulation. |
| B2 | The duration is rolled and **discarded** | `MoveOutcome.sleep_turns` is computed (~L243) and never stored. `BattleState`/`Battler` have no sleep counter, so the target never wakes. |
| B3 | Wake-up roll accounting | whether the per-turn sleep check costs a roll is an R7-style question. Cross-validate against `metronome_compass.effects._eff_sleep` first, which the project already does for Spore's application roll. |
| B4 | `_dominance_key` must include it | exactly the argument the field conditions already won (~L292): two states at the same offset with different remaining sleep are not interchangeable, because one wakes sooner and spends different advances. |
| B5 | The solver gains a **second clock** | `struggle_deadline` caps the horizon by the target's PP. A sleep window caps it again, and much sooner: a path must land its throw before the target wakes, or plan the re-Spore. |
| B6 | Re-application is a sequence, not a top-up | a status move against a statused target fails, so "wait for the wake, then Spore" has to be a legal plan. Spore's 15 PP is 15 applications here (see E2). |

### C. Flinch — `can_flinch` exists but nothing applies one

`sim.act_ours` checks only paralysis, and only effect **68** (Aurora Beam's Attack drop) is applied
from a secondary proc (~L609). So Zen Headbutt's 20% flinch is *reportable by the player and
unpredictable by the simulator* — a real flinch turn would match no candidate and read as a
contradiction. This is the one item that bites even without the sleep work.

### D. Two `will_fail` cases

`will_fail` knows status-against-a-statused-target and three field conditions, and neither of
these:

* **D1 — Refresh with nothing to cure.** With sleep as the status this is the *common* case: an
  awake unstatused Latias wastes ~1 turn in 4 on it.
* **D2 — Water Sport already active.** Needs a field flag alongside rain and mist. Without it a
  second Water Sport wrongly spends its two post-successful-move advances.

Both are the bug that desynchronised test1 at turn 3, in a new costume.

### E. Target configuration — small but easy to get wrong

* **E1** `targets.py`: `"latias": (40, ("Water Sport", "Refresh", "Mist Ball", "Zen Headbutt"))`.
  Base stats are already present for both twins.
* **E2 — `target_has_pressure` is hardcoded True in practice.** It is a `HuntConfig` field
  defaulting to `True`, and `app/facade.py` never sets it. Correct for all three birds
  (`ABILITY_PRESSURE`) and **wrong for both Lati twins** (`ABILITY_LEVITATE`), where it would
  double-count our PP and halve every budget the solver plans against. Should be derived from the
  species' ability, not defaulted.
* **E3** Mist Ball's 50% Sp. Atk drop is tokenised and not applied. Harmless — nothing we use is a
  special move — but it should be *documented* as ignorable rather than left looking like an
  oversight.

### F. Not code

The Enigma Stone was a Mystery Gift distribution. Whether this encounter is reachable at all on a
given cartridge is a real-world prerequisite, not a work item — worth settling before any of the
above is built.

### Status: A, C, D and E are implemented; B is implemented for the target's side

| item | state |
|---|---|
| A — lift the paralysis precondition | **done**. `Battler.frozen_for_phase2` accepts paralysis, sleep and freeze and refuses burn, poison and none; both assertion sites and the UI copy go through it. |
| B — sleep | **done for the target.** `Battler.sleep_turns` + `tick_sleep`, the rolled duration is stored instead of discarded, `_dominance_key` carries the status and the counter. The solver's *second clock* (B5) and the re-Spore sequence (B6) are not yet taught to the planner. |
| C — flinch | **done**, both sides. |
| D — `will_fail` | **done**, both cases, with `target_water_sport` on the state and in the dominance key. |
| E — configuration | **done**. Abilities are in `base_stats.json` from the ROM, `has_pressure` derives it, the facade passes it, and both twins have target rows. |

Two things the implementation settled that the plan had left open:

* **A sleeping turn and a flinched turn each spend no roll**, and the turn order is
  sleep → freeze → flinch → confusion → paralysis. Both come from `metronome_compass`, which is
  RNG-verified against Blackthorn ground truth and emits each prevention with `raw_emit` (no
  advance). §4c had flagged the flinch accounting as unverified and the ordering as a guess; it
  is neither — the project already had the answer in a module Battle Compass does not import.
* **The sleep counter read back after application is the number of turns the target will miss.**
  The application turn ticks it once itself, so a rolled 2..5 costs 1..4 turns and the visible
  counter is the honest "turns left asleep" rather than something needing an off-by-one in the
  reader's head.

### B5/B6 were the wrong shape, and the correction is worth recording

The plan said a Phase 2 path "must land its throw before the target wakes, or plan the re-Spore",
and treated the sleep window as a second deadline alongside `struggle_deadline`. That is not what
sleep is.

**The catch bonus is read at the throw and nowhere else** (`sim.throw_ball` takes
`status_bonus=_status_bonus(new.target.status)` at the moment of the throw). So sleep does not
need to be *maintained*; it needs to be true on one turn. Everything else sleep does — shielding
us, denying the target PP, changing the advance count of its turn — is state the search already
reasons about, not a constraint to add.

So there is no second clock and no backward reasoning. Ordinary Dijkstra over states handles it:
Spore is an action, waking is a transition, a re-Spore is the search taking Spore again, and a
path that lets the target wake and throws later is simply a path at the awake threshold, with
distance deciding between them. The user's reading was right and the plan's was not.

**One real bug fell out of it, in the other direction.** `b` is no longer constant across a path,
and the single threshold used to PRUNE the search was taken from the entry state:

* `target_threshold` was documented "constant for the whole of Phase 2" — true while the only
  permitted status was permanent paralysis, false the moment sleep was allowed.
* Against a **paralyzed** Latias the entry `b` is 33824 while Spore reaches 36157. Pruning at
  33824 can report *"no four consecutive rolls fall under b"* with **`proven=True`** while a
  Spore-then-throw path exists at 36157. And `proven=True` is the signal that justifies a soft
  reset (§6.3), so a false proof there does not lose a path — it costs the run.
* Real examples, in the test: seeds `0x10000023` and `0x1000004b` have **zero** windows in 60
  advances at 33824 and three and four respectively at 36157.

The fix is `max_reachable_threshold`, which maximises over the statuses the target can actually
reach — its current one, NONE (sleep and freeze wear off), and whatever our own permitted moves
with PP left can inflict. That keeps the precondition *necessary*, which is all a prune has to
be: a window that exists only at some other status is a harmless false positive, and every actual
throw is still settled by `simulate_turn`.

**And the forward search needs no assumption about Spore landing**, because Spore cannot miss
here: 100 accuracy, no Safeguard in Latias's set, and Gen 4 has no powder immunity. A sweep
asserts it over 300 seeds rather than arguing it — so "Spore now, throw next turn" is a certainty
the search can rely on, not a probability it has to hedge.

What remains genuinely open: `struggle_deadline` is computed from the target's PP at entry, and a
sleeping target spends none, so the real deadline is *later* than the horizon the solver uses.
That loses paths rather than inventing them, so it is conservative in the safe direction.

### What this means for ordering

**C and D are worth doing regardless** — C is a live correctness hole for any target with a
flinching move (Extrasensory is in both Lv45 bird sets), and D is the same class of bug the
simulator has already been caught by once. **A is half a day.** **B is the project**, and
`clayton-957.11` now depends on `clayton-hdo.1` for exactly that reason.

## 5. Suggested order — by machinery needed, not by difficulty

Every target is catch rate 3 at ×1, so none is easier to *catch*. They differ only in how much new
simulation each needs.

1. **Crit stage** (one task) — then **Lugia Lv45** is reachable, because the rest of its moveset is
   already covered or generic. Cheapest path to a second working target.
2. **Ho-Oh Lv70** — the other half of this profile, and the heaviest lift: burn with its residual
   tick, Punishment's variable power, Ancient Power's self-boost, Safeguard, plus a Speed-modifying
   held item for the Thunder Wave race. No sun needed, since Sunny Day is only in the Lv45 set this
   version never sees.
3. **Latias Lv40 (Pewter)** — static, so no fleeing, which makes it the right place to isolate the
   Refresh problem on its own.
4. **Latios Lv35 (roamer)** — Refresh *and* fleeing *and* the extra Seed A advance from §4a *and* a
   save-fixed spread. Treat as its own project rather than a new `STATIC_ENCOUNTERS` row.

Steps 1-2 are "add a target". Steps 3-4 are "extend the model".

---

## 6. The roamer-rate experiment

`utils/gdb-overworld-reader.py` records the **overworld** (Seed A) stream and every roamer
encounter check, to settle 1-in-2 against 1-in-4. Analysis lives in `claytonlib/roamer_check.py`
(pure Python, tested) because everything in the recorder needs a live emulator.

```
(gdb) source utils/gdb-overworld-reader.py
(gdb) owlog 0x0C0E02CA bluetest     # force a seed and start; or `owlog` to just record
(gdb) owpredict 40                  # frames this seed should give a roamer on
... walk onto the roamer's route and Sweet Scent ...
(gdb) owstatus                      # running verdict
(gdb) owsave                        # -> data/overworld_logs/<name>.jsonl
```

**It brackets rather than attributes, and that is the whole design.** `LCRandRange` is
`static inline`, so the flip has no symbol and cannot be hooked directly. The obvious
alternative — hook `LCRandom` and symbolise the caller — is exactly what misled this project in
§2: gdb resolves a caller to the nearest symbol, which credited six verified battle-start
advances to a function that makes no RNG call. So the recorder breaks on the **entry and return**
of `getRandomActiveRoamerInCurrMap` and treats every roll in between as that call's. No
symbolisation, nothing a neighbour can spoof.

The bracketed roll count is itself a measurement:

| rolls spent | means |
|---|---|
| 0 | no active roamer on that map — says nothing about the rate |
| 1 | the flip alone decided it, which the decompilation says is universal |
| 2+ | a tiebreak fired, so two roamers shared a map — which §4a says is impossible |

`initRoamingWildmon` is hooked as an **independent witness**: it runs only on a roamer battle, so
if it ever disagrees with the check's return value then the recorder is wrong and nothing else in
the log is safe. `claytonlib.roamer_check` reports that as a recorder problem rather than folding
it into the result.

Two findings are kept separate on purpose, because they can differ: whether **the bit predicts
the outcome**, and what the **observed rate** is. A 1-in-4 recording would show the bit agreeing
on every single event while the rate came out at 25% — which would mean the gate is not the
`LCRandRange(2)` this reading assumes, and the predicate needs more than one bit.

**On forcing the seed.** `gdb-seed-reader.py` records that this emulator's GDB stub corrupts
memory writes (writing `0x082A8651` left memory holding `0x0A7D8651`), which is why the battle
reader forces its seed through a register hijack instead. `sLCRNG_State` is plain memory, so
`owlog` writes it, reads it back, retries, and **refuses to record** under a seed it could not
verify — a silently-unforced seed would mislabel every frame number in the log. Recording without
forcing is fully supported and is all the rate test needs; forcing only buys frame numbers that
are reproducible across runs.

> Worth noting: that same stub hazard is the most likely explanation for the unresolved IV-word
> write in §16.x of the battle notes, where a single `u32` store came back with its low half
> correct and two fields in the high half wrong. A partially-landed memory write is exactly what
> the stub was already known to do.
