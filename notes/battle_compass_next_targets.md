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

## 2. A correction to §16.2 that this turned up

§16.2 explains the verified `BATTLE_START_ADVANCES = 6` as "4 `bellShimmerReplaceGraphics` (the
Bell Tower's Suicune shimmer) + 2 Pressure", and calls the 4 venue-specific.

**The attribution is wrong.** `bellShimmerReplaceGraphics`
(`src/field/legend_cutscene_camera.c`) only loads and swaps model animations — it makes no RNG
call — and it is reached only through `ScrCmd_LegendCutsceneClearBellShimmer`, which the Suicune
script **never calls**. The gdb reader resolves a caller address to the nearest symbol, so
`0x02251056` was attributed to a neighbouring function in the same overlay rather than to the
actual consumer.

What survives is the measurement: **6 advances, verified in two independent logs** (test1 and
test2). What does not survive is the story about where 4 of them come from, and therefore the
claim that they are venue-specific. The honest status:

> The count is ground truth for the Bell Tower Suicune. Whether it holds for Whirl Islands Lugia
> or Bell Tower Ho-Oh is **unknown** and must be measured, not inferred — CLAUDE.md's rule about
> verified advance counts exists for exactly this.

Encouragingly, both bird scripts *do* call `LegendCutsceneClearBellShimmer` while Suicune's does
not, so if the 4 were that cutscene the count would have been *lower* for Suicune, not equal.
That points at a generic wild-battle setup cost, which would carry over. It is still a hypothesis.

**This is the first thing to measure for any new target, and it is cheap:** force a seed, start
the encounter, count the rolls before the first move-selection roll. `utils/gdb-battle-reader.py`
already prints exactly that, and `test_battle_compass_ground_truth_2.py` already asserts it.

---

## 3. Why Lugia Lv45 is the right next target

On SoulSilver it is the early bird, and it is *easier than Suicune in the way that matters most*.

**The Fast Ball actually works on it.** Lugia's base Speed is 110, clearing the Fast Ball's 100
threshold, so the catch rate is ×4 instead of ×1:

| target | base Spe | Fast Ball | catch rate | `b` at 1 HP + paralyzed | P(catch) per throw |
|---|---|---|---|---|---|
| Suicune Lv40 | 85 | ×1 | 3 | 21845 | 1.23% |
| **Lugia Lv45** | **110** | **×4** | **12** | **33824** | **7.10%** |
| Ho-Oh Lv70 | 90 | ×1 | 3 | 21845 | 1.23% |

Nearly six times the per-throw chance, which means capture windows are far denser and Phase 2
paths get much shorter. `has_fast_ball_bonus` already returns True for it and `HuntConfig`
already threads `fast_ball_matched` through, so none of that needs writing.

**Its moveset is almost entirely covered already:**

| move | status | note |
|---|---|---|
| Rain Dance | **implemented** | `EFFECT_RAIN_DANCE`, including its `will_fail` when already raining |
| Hydro Pump | **generic** | fixed power, acc 80 — `execute_move` handles it as-is |
| Extrasensory | **mostly** | generic damaging; 10% flinch, and effect 31 is already in `FLINCH_EFFECTS` with a `fln` token and `can_flinch()` |
| Aeroblast | **one gap** | generic damaging, acc 95 — but effect 43 is the high-crit group (Karate Chop, Slash, Crabhammer, Stone Edge…), and `execute_move` hardcodes `CRIT_MODIFIERS[0]` |

**And accuracy 80 on Hydro Pump is a gift.** Per `notes/seed_separation.md`, a sub-100 accuracy
check is the sharpest seed separator there is — ~49% disagreement per roll between RTC-second
siblings, against 0% for every 100%-accuracy move. Suicune's moveset could not miss at all, which
is why its siblings took a median of 13 turns to separate. Lugia misses on its own, for free, on
any turn it picks Hydro Pump or Aeroblast.

So Lugia Lv45 needs **one real mechanic** (crit stage) plus a check that the flinch *consequence*
is applied, not just tokenised.

---

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

### Two structural notes on the roamer

**Its IVs are fixed in your save, not by the encounter.** `CreateRoamer`
(`field_roamer.c:204-215`) calls `CreateMon` and stores `ROAMER_DATA_IVS` / `ROAMER_DATA_PERSONALITY`
at *setup* time — a one-off story event. So unlike the birds, there is nothing to steer: the
spread is already decided, you read it off once rather than targeting an advance frame. The Seed A
advances step is irrelevant for it, and the spread entry becomes a one-time profile fact.

**Seed B's provenance differs.** Seed B is verified for Sweet-Scent and static A-press encounters
(CLAUDE.md). A roamer is a route encounter, closer to the Sweet-Scent case, but the battle-start
advances will not be the Bell Tower's and need their own capture.

---

## 5. Suggested order

1. **Lugia Lv45** — crit stage, confirm the flinch consequence, measure its start advances. Gets a
   ×4 ball and a self-separating moveset. By far the best value.
2. **Ho-Oh Lv70** — the other half of this profile. Needs burn, Punishment, Ancient Power and
   Safeguard; no sun, since Sunny Day is only in the Lv45 set. The hardest of the birds.
3. **Latias Lv40 (Pewter)** — static, so no fleeing, but Refresh still breaks the frozen-target
   model. Worth doing before the roamer because it isolates that one problem.
4. **Latios Lv35 (roamer)** — Refresh *and* fleeing *and* a different Seed B provenance. Treat as
   a separate project, not a new row in `STATIC_ENCOUNTERS`.

Steps 1 and 2 are "add a target". Steps 3 and 4 are "extend the model", and step 4 arguably wants
its own compass.
