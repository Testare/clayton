# Roamers — what catching one takes, and where it lives in Clayton

**Analysis document.** Claims are tagged [verified] (read out of a decomp or measured here),
[derived] (follows from a verified fact) or [design] (a decision to make).

Scope: roaming targets in Battle Compass, with **Platinum's Cresselia as the first one**. The
mechanism is shared with HGSS's roamers (Raikou, Entei, the roaming Lati twin), so everything in
sections 1–5 apply to both and `clayton-957.35`'s children are the HGSS half of the same work.

Sources: `pret/pokeplatinum` at `~/arch/pokeplatinum` and `pret/pokeheartgold` at
`~/arch/pokeheartgold`; unqualified file:line citations are the Platinum tree.

---

## 1. The shape of the problem

A roamer inverts the normal hunt. In a static hunt the player hits a Seed A, identifies it, routes
to an advance frame, fires the encounter and then identifies Seed B. A roamer gives none of that
back:

* **Nothing about the target is generated at the encounter.** `AddRoamerToEnemyParty`
  (`src/overlay006/wild_encounters.c:1402-1419`) reads species, level, **IVs**, **personality**,
  **status** and **current HP** out of the save and calls `Pokemon_InitAndCalcStats` — no RNG at
  all [verified]. The spread was fixed at `RoamingPokemon_ActivateSlot`
  (`src/roaming_pokemon.c:289`, `INIT_IVS_RANDOM`) the moment the roam started [verified]. So
  there is nothing to steer **at the encounter** — and no reason to hit any particular Seed A
  there. The spread is still steerable, one moment earlier: see section 7.
* **The encounter cannot be routed to.** Finding the roamer means walking between maps until it
  lands on yours, and every step on an encounter tile spends overworld rolls. Advance counting is
  hopeless by construction, not merely hard.
* **It leaves on turn one** unless trapped, and the trap has exactly four forms (section 2).

What a roamer gives back in exchange is unusual and worth saying up front: **HP and status persist
in the save between encounters** (section 3), and **a trapped roamer battle can run for as many
turns as we like** — which is exactly what identification wants.

---

## 2. The flee, and the four things that stop it

### 2.1 A roamer is driven by the trainer AI

`Task_TrainerShowMoveSelectMenu` (`src/battle/battle_display.c:3587-3590`) sends
`BATTLE_TYPE_TRAINER | BATTLE_TYPE_ROAMER` to `TrainerAI_Main`, where an ordinary wild Pokémon
takes the `else` branch and picks `validMoves[RandNext % validMovesCount]` [verified].
`BATTLE_TYPE_ROAMER` is `1 << 8` and is *not* `BATTLE_TYPE_TRAINER`
(`include/constants/battle.h:26,34`), so the roamer bit is what routes it — and
`TrainerAI_Init` then sets `thinkingMask = AI_FLAG_ROAMING_POKEMON` for it alone
(`src/battle/trainer_ai/trainer_ai.c:246`) [verified]. HGSS is the same code with the flag called
`AI_29` (`src/battle/trainer_ai.c:38-42`) [verified].

### 2.2 The trap list is exactly four things, and it is checked twice

`RoamingPokemon_Main` (`src/battle/trainer_ai/script.s:8073-8089`), verbatim in order:

1. our side's `VOLATILE_CONDITION_BIND` on the roamer → trapped
2. `VOLATILE_CONDITION_MEAN_LOOK` on the roamer → trapped
3. **our active battler's** `ABILITY_SHADOW_TAG` → trapped
4. the **roamer's** `ABILITY_LEVITATE` → *not* trapped (skips the next check)
5. our active battler's `ABILITY_ARENA_TRAP` → trapped

otherwise `Escape` [verified]. Two consequences for Cresselia specifically: **Levitate makes Arena
Trap useless** on it, and the Levitate check sits *after* Shadow Tag, so **Shadow Tag still works**
[verified].

The ability is read with `AICmd_LoadAbility` → `Battler_Ability` (`trainer_ai.c:2654-2662`), the
*true* ability rather than what the AI has observed [verified]. So a Shadow Tag lead traps the
roamer on turn 1 without having revealed anything.

**The trap must be in place at ACTION SELECTION, and only two of the four survive to
execution.** `BattleControllerPlayer_FleeCommand`
(`src/battle/battle_controller_player.c:1989-2001`) loads `subscript_enemy_escape_failed` when the
enemy has `BIND | MEAN_LOOK` — and **not** Shadow Tag or Arena Trap [verified]. Those two are
consulted *only* by the AI script, i.e. only at the top of the turn, so:

* **A Shadow Tag lead traps from turn 1 and the roamer never chooses to escape at all.** Measured
  over 7 turns with Wobbuffet active at selection: every one spent the move-choice roll and none
  chose Escape (section 2.6).
* **A Shadow Tag Pokémon switching IN cannot stop an escape already chosen.** The decision was
  taken while the departing Pokémon was out; our switch resolves first (`PARTY` before `FIGHT` in
  `CalcTurnOrder`), Shadow Tag is on the field when `FleeCommand` runs — and it leaves anyway,
  because that check does not look at abilities [verified: `mesprit1.jsonl` T2].
* **A Mean Look landing the same turn DOES rescue it**, because Mean Look is a volatile on the
  roamer and `FleeCommand` does look for that: "can no longer escape" then "can’t escape!", and the
  roamer's turn is spent on nothing [verified 3×: `mesprit.jsonl` T3, `mesprit2.jsonl` T2 and T7].

So Shadow Tag is a **lead-only** trap and Mean Look is the only one that can be applied *reactively*
— which inverts the obvious reading of the trap list, where Shadow Tag looks strictly stronger.

### 2.3 The flee is speed-ordered, and that is why a fast Mean Look works

The AI's `AI_ENEMY_ESCAPE` (index 4) is emitted as 5 and recognised in
`COMMAND_SELECTION_MOVE_SELECT` as `(ioBuffer - 1) == 4` → `PICK_COMMAND = BATTLE_CONTROL_RUN`
(`battle_controller_player.c:772-776`) — it sets **PICK_COMMAND, leaving SELECTED_COMMAND as
`PLAYER_INPUT_FIGHT`** [verified]. `BattleControllerPlayer_CalcTurnOrder` (`:707-790`) hoists a
*run* ahead of everything only for `BATTLER_PLAYER_1`/`_2`, i.e. our own slots, and then orders the
"fight" group by `BattleSystem_CompareBattlerSpeed` with `skipPriority = FALSE` whenever both sides
chose the same command — which they did [verified].

**So the roamer's escape competes with our action on speed and priority, exactly like a move.**
That settles `clayton-957.35.10`: a trapper that outspeeds the roamer lands Mean Look first, the
escape then fails at execution, and the roamer's turn is consumed doing nothing. A slower trapper
never gets the chance.

**Sleep is not a trap.** An asleep roamer still runs the whole selection path and still escapes: the
sleep check belongs to move execution, and an escape is an action rather than a move [verified:
`mesprit2.jsonl` T9 and T10 select a move while "fast asleep", and T11 chooses Escape and leaves,
asleep throughout]. So the prep encounter's sleep buys catch rate and nothing else — it never
substitutes for the trap.

### 2.4 Leaving the field releases the trap

`BattleSystem_UpdateAfterSwitch` and `BattleSystem_CleanupFaintedMon` (`battle_lib.c:2040,2155`)
clear Mean Look, Lock On, Attract and Bind from *other* battlers when a battler departs
[verified — this is the same pair of functions `targets.foresight_warnings` already cites].

This answers the "Mean Look then swap?" question outright, and the answer is no:

* **Switch out → the trap is gone.** The roamer's action for that turn was already chosen as a
  move, so it attacks; on the *next* turn it chooses Escape, and our switch-in cannot Mean Look
  first unless it outspeeds — and even then we have spent a turn for nothing.
* **The trapper fainting releases the trap, and the replacement gets exactly one chance.** The
  roamer's next selection sees an untrapped field and chooses Escape, so the Pokémon sent out must
  re-trap *and* outspeed it — Mean Look only, since a switched-in Shadow Tag cannot stop a chosen
  escape (section 2.2). Measured both ways: a replacement Smeargle at Speed 177 re-trapped
  successfully (`mesprit2.jsonl` T6 faint → T7 Mean Look), and a Honchkrow at Speed 94 against the
  roamer's 100 did not (`mesprit.jsonl` T7, `mesprit2.jsonl` T11 — both "The wild MESPRIT fled!").
  So `danger_floor` and the survivability warnings are not advice on a roamer hunt; they are the
  run's hard constraint [design].
* **A partial-trapping move (Bind, Whirlpool, Fire Spin…) cannot be the trap we catch under**: its
  residual is 1/16 per turn, which kills a 1 HP target. It is a prep-phase tool at most [derived].

### 2.5 What a roamer's turn costs in rolls

`TrainerAI_Init` spends **four** battle-RNG rolls unconditionally — `moveDamageRolls[i] = 100 -
(BattleSystem_RandNext % 16)` over `LEARNED_MOVES_MAX`, outside any branch
(`trainer_ai.c:234-241`) [verified]. `BattleSystem_RandomOpponent` spends none in singles
(`battle_lib.c`, the `else chosen = attacker ^ 1` branch) [verified].
`BattleSystem_CheckInvalidMoves` spends none [verified]. The roaming script makes no `Random` call
[verified]. `AI_INIT_SCORE_ALL_MOVES` starts all four scores at 100 and the script changes none of
them, so the tie list is every slot holding a move and the pick is
`maxScoreMoveSlots[RandNext % numMaxScoreMoves]` (`trainer_ai.c:339`) [verified].

Therefore, and **now measured** (section 2.6):

| | rolls at action selection | the move-choice roll |
| --- | --- | --- |
| ordinary wild | 1 | `% validMovesCount`, the 1st roll |
| roamer, trapped | **5** | `% 4` (all four slots tie), the **5th** roll |
| roamer, fleeing | **4** | none — the escape branch skips the tie-break |

Three notes. The modulus is `% 4` either way, so by `notes/seed_separation.md`'s argument the move
choice stays blind to RTC-second siblings on a roamer exactly as it is on a static target. The four
damage rolls are **not** conditional on anything we can see, which makes them a clean constant to
pin. And the roll count *is* the decision: a fifth roll means it chose a move, its absence means it
chose Escape — so a recording says what the roamer decided before it acts, which is how section 2.6
reads the trap state off a log rather than inferring it.

Ordering, from the same recordings: selection comes **before** the four BeforeTurn speed rolls
(`battle/turn.py`'s `BEFORE_TURN_ADVANCES`), so the roamer change is to replace
`turn.SELECTION_ADVANCES = 1` with 5 or 4 **in place**, not to add a block anywhere else.

### 2.6 The three recordings, and what they measured

`data/battle_logs/mesprit.jsonl`, `mesprit1.jsonl` (seed `0x64018903`) and `mesprit2.jsonl`
(`0x78017333`) — forced-seed Platinum captures against the roaming **Mesprit** Lv50, with a
Wobbuffet (Shadow Tag, Lv25, Speed 21), a Smeargle (Lv64, Speed 177) and a Honchkrow (Lv52, Speed
94) against the roamer's Speed 100. 20 turns total.

**Every turn's AI roll count matched the trap state at selection, with no exceptions:**

| turns | trapped at selection by | AI rolls | what it did |
| --- | --- | --- | --- |
| 7 | Shadow Tag (Wobbuffet active) | 5 | chose a move |
| 7 | Mean Look standing | 5 | chose a move |
| 6 | nothing | 4 | chose Escape |

Of those six escapes, three were rescued by a faster Mean Look landing the same turn and three ran:
one with Shadow Tag switching in behind the decision (`mesprit1` T2), and two with a Honchkrow that
the roamer outsped (`mesprit` T7, `mesprit2` T11 — the latter asleep).

**The escape itself spends no rolls.** On a fleeing turn the log shows the 4 AI rolls, the 4
BeforeTurn rolls, and then "The wild MESPRIT fled!" with nothing between — there is no
escape-chance roll, because `Battler_CanEscape` is only on *our* branch of `FleeCommand`. The
failed-escape path spends none either.

**One caveat on these three recordings:** the harness's target override reported
`stats_verified: false`. The IV word took (`ivs_verified: true`) but `defense` and `spDefense` read
back as `23933` (`0x5D7D`) where `125` (`0x007D`) was written, with the low byte right and a `0x5D`
high byte from somewhere — cause not determined. So **nothing about the roamer's defensive side in
these logs is usable**, while the roll counts, the move choices, the turn order and the flee
behaviour — everything section 2 draws on — are untouched by it.

And the deeper reason the IV write could not have helped anyway, which is the roamer case in one
sentence: **the roamer's stats were already derived in the field**, by
`AddRoamerToEnemyParty` → `Pokemon_InitAndCalcStats`, long before `BattleSystem_InitBattleMon` runs,
and nothing re-derives them mid-battle. For a roamer the override has to go into the **save's roamer
block** (`ROAMER_DATA_IVS`, `_PERSONALITY`, and `_CURRENT_HP`/`_STATUS` for the prep state) so the
game computes the spread the way it would in a real run.

---

## 3. HP and status persist — the prep encounter is real

`RoamerAfterBattle_UpdateRoamers` (`src/overlay006/roamer_after_battle.c:25-60`), called from
`src/encounter.c:421` after every battle [verified]:

* result `WIN` with the roamer at 0 HP → the slot is zeroed, `ROAMER_STATE_DEFEATED`;
* result `CAPTURED_MON` → zeroed, `ROAMER_STATE_CAPTURED`;
* **anything else → `ROAMER_DATA_CURRENT_HP` and `ROAMER_DATA_STATUS` are written back from the
  battle mon.** Our run, its flee, a loss: all persist [verified].

`roamerStatus` is a `u8` cast of `MON_DATA_STATUS`, which in Gen 4 is the whole status byte —
sleep's remaining-turn counter included [verified: the Gen 4 status word keeps sleep turns in the
low bits, and nothing above that byte is used].

So the run splits in two:

* **Prep encounters** — chip to 1 HP, apply sleep, then leave. Needs a trapper that outspeeds
  (section 2.3) or, with no trap at all, accepts exactly one action per encounter before the flee.
* **The hunt encounter** — opens at 1 HP and already statused, so every turn is identification or
  a throw, and the active mon only needs to trap and survive.

**Each encounter also scatters the roamers.** `MoveRoamersOffMap` runs unconditionally after an
encountered roamer's battle, and after a battle with *no* roamer there is a `LCRNG_RandMod(100) <
30` check that may do it anyway — one overworld advance, every battle [verified]. So prep is not
free: every prep encounter costs another hunt for the roamer. Prefer **one** prep encounter that
does everything (trap → chip → sleep → run) over several cheap ones [design].

---

## 4. The encounter itself

`TryEncounterRoamer` (`wild_encounters.c:1423-1453`) [verified], identical in substance to HGSS's
`getRandomActiveRoamerInCurrMap`: no active roamer on this map → normal; `LCRNG_RandMod(2) == 0` →
normal anyway; more than one roamer co-located → a second `LCRNG_RandMod(nRoamers)`.

**Repel is the finding tool, and its rule is a strict inequality.**
`RepelPreventsEncounter` is `repelActive && firstBattlerLevel > wildLevel`
(`wild_encounters.c:1397-1400`), where `firstBattlerLevel` is the first *live* party mon's level
(`:264`) [verified]. Cresselia is Lv50, so with Repel up:

* lead level **≤ 50** or the roamer is suppressed — and on the walking path the suppressed
  encounter returns `FALSE` outright, so the encounter is simply lost [verified];
* lead level **> every wild level on the route**, which is the whole point of the trick.

The lead is also the battler, so the trapper *is* the Repel gate. That couples two requirements
onto one Pokémon and is the first thing a roamer readiness check should test [design].

---

## 5. Cresselia, specifically

`ActivateRoamingPokemon ROAMING_SLOT_CRESSELIA` (`res/field/scripts/scripts_fullmoon_island_forest.s:28`)
and `case ROAMING_SLOT_CRESSELIA: species = SPECIES_CRESSELIA; level = 50`
(`src/roaming_pokemon.c:259-261`) [verified].

**120/70/120/75/130/85, pure Psychic, Levitate, catch rate 3, female-only**
(`res/pokemon/cresselia/data.json`) [verified].

**Moveset at Lv50** — the last four learnable in learn order, which is the `E1`–`E4` slot order
`targets.Encounter` wants [verified from `learnset.by_level`: 1 Confusion, 1 Double Team,
11 Safeguard, 20 Mist, 29 Aurora Beam, 38 Future Sight, 47 Slash, 57 Moonlight]:

| | move | effect | why it matters |
| --- | --- | --- | --- |
| E1 | Mist | 46 | already modelled |
| E2 | Aurora Beam | 68 | already modelled — Suicune's |
| E3 | **Future Sight** | 148 | already modelled; **accuracy 90**, so it separates siblings |
| E4 | Slash | 43 | already modelled — the high-crit group, Aeroblast's |

**All four effects are already in `sim.MODELLED_TARGET_EFFECTS`** [verified by inspection], so
unlike the HGSS roamers (`clayton-957.35.6`) Cresselia needs no new target effects at all.

The level window is kind in both directions: **Safeguard (11) is pushed out from below**, so sleep
lands, and **Moonlight (57) from above**, so nothing heals off the chip. There is no Roar, so
`clayton-957.35.5` and `.7` (Ingrain, the replacement-selection roll) are not on Cresselia's path.

**Balls.** Base Speed 85 < 100 so the Fast Ball is ×1; Love Ball needs the same species, so ×1
[verified, `battle/balls.py` rules]. What is left is the ordinary conditional set — and one of them
fits a roamer hunt perfectly:

| ball, at 1 HP | awake | paralyzed | asleep |
| --- | --- | --- | --- |
| Poké ×1 | 0.83% | 1.23% | 1.60% |
| Ultra ×2 | 2.11% | 2.83% | 4.37% |
| Dusk ×3.5 (night) | 3.90% | 5.53% | 7.10% |
| **Timer ×4 (turn 30+)** | 4.37% | 7.10% | **9.27%** |

A Timer Ball is `min(10 + turn, 40)` tenths (`balls.py:164-168`), i.e. ×4 from turn 30 — and a
trapped-roamer battle *wants* to be dozens of turns long for identification anyway. The
identification phase pays for the ball [derived].

**The HP IV does not matter.** Cresselia's Lv50 max HP spans 180–195 over the IV range, and at
`cur_hp = 1` every row of that table is byte-identical at both ends: same `a`, same `b`, same
probability [verified by computation against `battle/catch.py`]. That is most of the spread problem
(section 7) dissolved.

---

## 6. What replaces Seed A: the stopwatch vector

The candidate grid needs two numbers: the **delay** at `FieldBattleDTO_New` and the **RTC second**
there. `candidates.generate` already builds the grid from `key_seed + initial_time + vector_ms`
alone, and `centre()` already treats vector ms as a *difference* from Seed A's own delay rather
than a position — so the grid machinery carries over untouched [verified by reading
`battle_compass/candidates.py`].

What does not carry over is **where the centre comes from**. `model.frame(M, base_low16)` maps a
*commanded* timer countdown through a fitted load path: the intercept is the timer-vs-load-press
misalignment of that workflow. A roamer encounter is not commanded, it is *measured*. So [design]:

* The player starts a stopwatch at the load press (the key seed anchors the delay there) and stops
  it at the moment the encounter fires. The elapsed reading is the vector.
* `frame_centre = seed_a_delay(key_seed, initial_time) + round(elapsed_ms * DELAYS_PER_MS)` with
  the project's 59.8261 Hz, and `second_centre = round(elapsed_ms / 1000 + rtc_offset_seconds)`.
* **This is a different model object, not a different argument.** Threading a flag into
  `CalibrationModel.frame` would mix a fitted intercept into a measured quantity; a small
  `StopwatchVector` with the same two-method surface (`frame`, `battle_second_offset`) keeps
  `candidates.generate` and `HuntSession` callers unchanged [design].

Error budget, and it is the thing to beware of:

| source | rough size |
| --- | --- |
| landing jitter on the load press (we never identify Seed A, so it stays) | the model's σ at the run's M |
| stopwatch start + stop reaction | ±0.2–0.5 s ⇒ ±12–30 frames |
| stopwatch vs DS clock drift over a long hunt | 0.1% of elapsed; 10 min ⇒ ~36 frames |

That argues for a **frame window in the low hundreds and a second window of ±1 or ±2** — order
1000 candidates, against the 121 a static hunt opens with. Two mitigations, both already in the
codebase: `HuntSession.rebase`/`widen` exist for exactly this, and a trapped roamer gives unbounded
turns to spend. The open question is compute on the first sweep, not information [design].

A cheaper variant worth testing: **stopwatch from console power-on**, since `gSystem.vblankCounter`
counts from boot, which removes the load-press jitter from the budget entirely and makes the key
seed unnecessary — only the DS clock's date/hour/minute at the encounter is then needed
[design, needs one real run to confirm the counter's origin in practice].

---

## 7. The spread: not from the key seed, but still knowable

`HuntTarget` takes nature and all six IVs by hand "from Pokefinder", and `hunt_run_setup` calls the
hunt's spread "the one the key seed produces". **The second of those is not true of a roamer**: the
spread was rolled when the roam was *activated*, not at the encounter.

**But that moment is manipulable like any other, so a roamer somebody created on purpose has a
spread they know exactly.** `RoamingPokemon_ActivateSlot` calls `Pokemon_InitWith(...,
INIT_IVS_RANDOM, ...)` off the overworld LCRNG at the instant the script runs
(`src/roaming_pokemon.c:289`) — so a player who targets the seed they talk to Cresselia on chooses
its IVs and nature there, and the hunt simply enters them. [Verified: Testare manipulated them
ahead of time, which is what this section originally got wrong.] `clayton-957.35.9` is the bead for
that moment; its old reading — "there is nothing to steer" — is exactly backwards, because the
thing to steer is the activation rather than the encounter.

So an *entered* spread is the normal path and an exact one. The fallback below is for the other
case: a roam that started before anyone was targeting it, where the numbers are simply gone.

What the sim actually needs it for, in descending order of harm:

1. **Speed** — turn order against the escape. **Removed entirely by a Shadow Tag lead**, which
   traps before speed is consulted (section 2.2) [derived].
2. **Attack / Sp. Atk** — survivability and the incoming-damage filter. Wanted, not load-bearing;
   `clayton-xaf` already has the filter opt-in per opponent.
3. **Defence / Sp. Def** — our chip damage, i.e. the prep phase only. False Swipe leaves 1 HP
   whatever the number is.
4. **HP** — the catch maths. **Provably irrelevant at 1 HP** (section 5).

So a roamer hunt **accepts a blank spread and says what that costs**, rather than refusing a run
over numbers that may genuinely be gone — while a *half*-entered spread stays an error, because a
nature without IVs is an unfinished form rather than a declaration of ignorance. The fallback is a
neutral nature and 31 across the board, which is conservative in every direction that matters:
maximum Attack and Sp. Atk over-state the incoming damage, maximum defences over-state the chip
phase, and at 1 HP the HP IV changes the catch maths not at all. The exception is **Speed**, where
a +Speed nature is faster still — so the trap check asks for the *fastest it could be* instead,
since a trapper that turns out slower loses the whole run while a needless warning costs a
sentence.

Readiness says so out loud when a run is on the fallback, and says why it is worth avoiding: a
roamer you RNG'd has a spread you know, and entering it turns every damage prediction from a bound
into a figure.

The forced-seed recordings make the same point from the other end: an IV write at
`BattleSystem_InitBattleMon` changes nothing, because the stats were already derived from the save
before the battle existed (section 2.6). The place to write them is the save's roamer block —
or, for a run rather than a fixture, the activation seed. Section 5's table is why that is affordable; a Shadow Tag lead is
why the remaining risk is survivability rather than correctness.

---

## 8. Where it lives: a Hunt mode, not a new tool

Recommendation: **a discriminator on `Hunt`** (`encounter_kind: "static" | "roamer"`), not a
separate tool.

What a roamer changes is the *acquisition* of the seed and the *opening state* of the battle. What
it does not change is everything downstream: `solver`, `tokens`, `items`, `sim`'s effect library,
`HuntSession`'s observe/undo/predict/replay loop, the candidate grid, run records, readiness, and
the whole Hunts UI. That is ~7,000 lines shared against maybe 400 forked. A separate tool would
duplicate the identification loop — the single most expensive and most tested thing in the repo —
to avoid four conditionals.

The conditionals it needs, concretely:

* `candidates`: centre from a `StopwatchVector` instead of the calibration model (section 6).
* `sim`: the roamer AI's roll cost, and `Action`/outcome for the flee (section 2.5).
* `hunt_session`: opening HP/status/sleep-turns as configuration; `fled` as a terminal outcome
  alongside `caught`/`wiped`; the trapper's faint as a *run-ending* event.
* `targets`: Cresselia's row, keyed by encounter, with the roamer flag on it.
* app: the run page skips the Seed A step entirely and asks for a stopwatch reading instead; the
  spread step becomes optional.

---

## 9. Herding — the investigation the user asked for, now with code to read

Steering a roamer onto a chosen route is **not** ruled out by anything above. The movement is pure
LCRNG and the route graph is a static table:

* `RoamingPokemon_MoveAllLocations` (`src/roaming_pokemon.c:198-212`), called from
  `src/field_map_change_flags.c:48-52` on every non-temporary map change: per *active* roamer,
  `LCRNG_RandMod(16) == 0` → `MoveRoamerRandom`, else `MoveRoamerNearby` [verified].
* `MoveRoamerRandom` (`:303-320`) is a **rejection loop**: `LCRNG_RandMod(RI_MAX)` until the route
  is neither the player's previous map nor the roamer's current one. `MoveRoamerNearby` (`:322-353`)
  is the same shape over `sNearbyRoutes[current].adjacentRouteIndexes` [verified].
* `RI_MAX` is **29** route slots (`include/roaming_pokemon.h:8-38`) [verified].
* Roamers cannot move to the map the player just left (`RoamingPokemon_UpdatePlayerRecentRoutes`,
  `:252-258`) [verified].

So the number of advances per map change is **variable and state-dependent** (the rejection loop,
times the number of active roamers), which is what `clayton-957.35.8` says for HGSS — but it is
*simulable* from a known frame, because every input is either a constant table or something we
track. The feasibility question is not the movement, it is **whether the frame survives the walk**:
steps on encounter tiles spend rolls, so a herding route would have to move between maps without
ever touching grass. Clearing the other roamers first (Platinum has six slots; the birds and
Mesprit multiply every map change's cost) is a prerequisite, and `notes/platinum.md` section 2
already flags that.

Worth an investigation bead, not a work bead, and strictly after the basic flow catches something.
Platinum and HGSS would need the route graph transcribed separately.

---

## 10. As built

What landed on 2026-10-27, and the three places the implementation says something the design above
did not.

**`claytonlib/battle_compass/targets.py`** — `Encounter.roamer`, the `cresselia` row, `is_roamer()`.

**`claytonlib/battle_compass/sim.py`** — `ROAMER_AI_ADVANCES = 4`, `traps_by_ability`,
`roamer_trapped_at_selection`, `escape_blocked_at_execution`, `RoamerChoice`,
`select_roamer_action`, and `HuntConfig.target_is_roamer` as the only door to any of it.
`simulate_turn` takes the roamer branch in place of `select_target_move`, and `act_target`
resolves the escape ahead of every move-prevention check.

**`claytonlib/battle_compass/state.py`** — `BattleState.target_fled`, which `over` reads.

**`claytonlib/battle_compass/tokens.py`** — `Eesc` (terminal) and `Etrp` (not), both E-only.

**`claytonlib/stopwatch.py`** — `StopwatchVector`, duck-compatible with `CalibrationModel` for the
two methods `candidates` calls and deliberately nothing else.

**`app/models.py` / `app/facade.py`** — `Hunt.encounter_kind` and `Hunt.stopwatch_ms`,
`Facade._sync_encounter_kind` (derived on every write, never configured) and
`Facade._centring_model` (the one place that decides which object centres the window).

### 10.1 The party rule: every member, not just the lead

`targets.trap_checks` / `trap_warnings`, surfaced as `hunt_readiness`'s `trap` key. The rule is
one sentence — **every party member must be able to hold the roamer** — and it is every member
rather than only the lead because the trap is released when our side leaves the field (sec 2.4),
so whoever replaces a fainted trapper has to re-establish it. A replacement is on the field before
the next action selection, so the rule is identical for a lead and a bench member.

The three ways, in the order `RoamingPokemon_Main` tests them:

| | Speed requirement | note |
| --- | --- | --- |
| Shadow Tag | none | works from the first selection |
| Arena Trap | none | **only against a grounded target** — `is_grounded`, so never Cresselia |
| Mean Look / Block / Spider Web (effect 106) | must **outspeed** | the roamer has already chosen Escape; the move refuses it by landing first |

Three details the implementation had to get right, two of which the first version did not:

* **A Choice Scarf counts, and holding one is not a problem.** It takes a 70-Speed Mean Look user
  past Cresselia's 105, and locking into Mean Look costs nothing once the trap is up: balls,
  revives and items are bag actions. `scarf_would_fix` says when the item is the whole difference.
  The check reads the item-adjusted Speed, so a scarf already equipped is *already counted* — and
  it must not then be suggested again, which the first version did ("105 does not outspeed 105 — a
  Choice Scarf would (157)", advising the item they were holding and naming a Speed nothing in the
  battle had).
* **A Speed TIE is worse than being slower, not marginally better.** The ROM breaks it with a roll
  (`notes/ss_rng/speed.md`), so the trap becomes a coin flip *and* the turn spends an advance the
  simulation does not predict. A scarf that lands exactly on the target's Speed is not a fix, and
  the check says so in its own branch.
* **An unknown target Speed is reported as unknown, not as a failure.** A roamer's spread cannot
  be looked up from the key seed (sec 7), so a hunt can be fully configured in every other respect
  and still not know it. `TrapCheck.unknown` keeps "finish entering it" apart from "change the
  party".

The partial-trapping family (effect 42 — Bind, Wrap, Fire Spin, Clamp, Sand Tomb, Magma Storm —
and 261, Whirlpool) really does set the volatile both the AI and `FleeCommand` accept, and is
refused with a reason rather than ignored: its residual takes 1/16 per turn and the run needs the
target alive on 1. Neither effect is in `MODELLED_OUR_EFFECTS` either.

What no party composition can fix, and so is advice rather than a check: **do not switch
voluntarily.** A Shadow Tag Pokémon switched in behind an already-chosen escape does not stop it
(sec 2.2), so only a faint's replacement gets a second chance at the trap.

### 10.2 Mesprit, and what three recordings settled

`mesprit`, `mesprit1` and `mesprit2` in `data/battle_logs/` are forced-seed captures of the
roaming Mesprit, 21 turns in all, and **every roll count, HP figure and rendered token in them is
reproduced** by `tests/test_battle_compass_ground_truth_mesprit.py`. What that pinned:

* **The AI cost, exactly.** 80 rolls at the four-damage-roll site over 20 turns — four every turn
  without exception, fleeing and asleep included — and 14 at the tie-break, so 14 chose a move and
  6 chose Escape. Section 2.5's table is measured now, not derived.
* **The wild selection call site never fires**, which is a cleaner confirmation of the trainer-AI
  branch than any count: not the same path at a different price, a different path.
* **`BATTLE_START_ADVANCES` is 6 for a roamer route encounter** — four in
  `BattleContext_InitCounters` plus two at the send-out, the same as every Platinum static and the
  same as HGSS's Bell Tower. No roamer variant needed (`clayton-957.35.2`).
* **Mesprit has a row after all.** `notes/platinum.md` section 15 said it "has no row and cannot
  have one", which was true of a table that could only describe static encounters. Its Lv50 set is
  Swift / Lucky Chant / Future Sight / Charm — and the log reports exactly those four move ids,
  which is the first empirical confirmation of the last-four-learnable-in-learn-order rule for a
  roamer rather than for a battle script.

Two effects came with it. **Lucky Chant (240)** suppresses crits against the target for five turns
and **the crit roll is still spent**: `BattleSystem_CalcCriticalMulti` puts `BattleSystem_RandNext`
first in its `&&` chain and tests the flag after it, so C's short-circuit never reaches the roll.
**Charm (58)** takes two stages off our Attack, which slows the chip phase rather than failing it.

### 10.3 Three things the design above got wrong or left out

**The stopwatch has a load-lag term, and it is a bias.** Section 6 said "the player starts a
stopwatch at the load press" and then centred on the reading — but the seed is generated part way
*through* the loading sequence, so a raw reading measures press-to-encounter where the grid needs
seed-to-encounter. At 59.8261 Hz, one second of error is **sixty frames**, which swamps the entire
spread budget that section was careful about. It is now `StopwatchVector.seed_lag_seconds`,
defaulted to zero and **explicitly not** inferred from `CalibrationModel.alpha` (−290 frames ≈ 4.8 s
on the deployed fit, which is the right size and the wrong quantity: that intercept was fitted for a
countdown that *ends* at the encounter press). `implied_seed_lag` reads it off a finished run, so
one deliberately-wide first hunt pins it to within a frame. `clayton-957.35.23`.

Which also corrects section 6's window arithmetic, in the direction of the windows Battle Compass
is actually run at. An unmeasured lag is a **bias of up to ten seconds**, and no multiple of sigma
reaches a bias — so `suggest_frame_window` adds `lag_allowance_frames` (~600) on top of the 3σ
spread until the lag is known, and the second window gains the same ten. That makes a first roamer
window ~830 frames × ~11 s ≈ 38,000 candidates, against the ±2000 frames and ±7 seconds Testare
reports static hunts working well at — so it is in the normal range rather than the alarming one.
Once the lag is measured the allowance disappears and the same hunt asks for ~230 × 1 ≈ 1,400,
which is the concrete payoff for doing the one wide run.

**Our own Safeguard blocked our own Spore**, and that bug predates roamers entirely.
`safeguard_turns` was a single counter documented as the target's — "nothing in any party can set
one" — which stopped being true the moment a Wobbuffet with Safeguard became the standard roamer
trapper. `mesprit2` T8 is the turn that caught it: the game slept the target and the simulator
refused to. Our side has its own counter now, and `will_fail` takes the acting side. The roll count
on that turn happened to agree anyway, so only the two turns *after* it diverged — which is why a
recording was the only thing that could have found it.

**Nothing released the target's trap when our side left the field** — a real bug, not a missing
feature, and it predates roamers. `BattleSystem_UpdateAfterSwitch` and
`BattleSystem_CleanupFaintedMon` clear Mean Look from other battlers on any departure (sec 2.4), and
the simulator did not. Harmless for a static target, where the trap only decides whether a second
Mean Look fails; run-ending for a roamer. Now `sim._release_trap`, called from both departure paths.
The full suite stayed green, so nothing had depended on the old behaviour.

**An unavoidable flee eliminates no candidates.** Nothing random decides it — the trap state and the
speed comparison are both deterministic — so every candidate in the window predicts `Eesc`
identically. A lost roamer run therefore teaches the *next* attempt nothing about the seed, which is
worth saying out loud in the UI: the cost of losing one is the whole hunt for the roamer again, with
no partial credit.

---

## 11. Open items that need ground truth

* ~~**The roamer turn's roll cost**~~ — **measured** over 20 turns in the three `mesprit*.jsonl`
  recordings (section 2.6): 5 trapped, 4 fleeing, with the selection block ahead of the BeforeTurn
  rolls. `clayton-957.35.1` is left open only for the one thing the logs do not cover: whether a
  roamer whose moves are not all usable (no PP, Torment, Imprison) narrows the `% 4` the way a
  wild's `% validMovesCount` would.
* **`BATTLE_START_ADVANCES` for a roamer route encounter** — the static figure is measured for
  Suicune and its documented breakdown is known-wrong (`notes/battle_compass_next_targets.md`
  sec 16.2). `clayton-957.35.2`.
* **The persisted sleep counter.** The byte carries remaining turns, so the hunt encounter opens
  mid-sleep with a count we did not observe. Either model it as uncertain over its range or re-apply
  sleep in the hunt encounter — which a Shadow Tag lead cannot do. Note this is about catch rate
  only: sleep does not stop the escape (section 2.3).
* **The forced-seed harness cannot set up a roamer.** Writing `battleMons[]` after
  `InitBattleMon` is the wrong seam for a target whose stats were derived in the field, and two of
  five stat writes read back wrong in all three recordings (section 2.6). A roamer fixture wants the
  save's roamer block patched instead — which is also the only way to record a 1-HP-and-asleep
  opening state.
* **The 50% encounter flip** — code says 1/2, play experience has said 1/4 (`clayton-957.16`).
  Unchanged by anything here, and Platinum's `TryEncounterRoamer` says 1/2 too.
