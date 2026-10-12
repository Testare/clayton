# Ho-Oh Lv70 (SoulSilver): the party, and what the game actually does

Companion to `notes/battle_compass_next_targets.md` sec 2, which established the target. That file
answers *what Ho-Oh is*; this one answers *what we bring* and *what the simulator still has to
learn* before the run is sound.

Claims are tagged **[verified]** when read out of the decompilation at `~/arch/pokeheartgold` or
computed by `claytonlib.battle.damage` against it, **[derived]** when it follows from a verified
fact by arithmetic, and **[check]** when it is a real-world prerequisite nobody has confirmed yet.

Every damage figure below is `claytonlib.battle.damage.damage_range` — the ROM's own arithmetic
order, flooring where the C floors — against Ho-Oh Lv70 at 31 IVs and a neutral nature:
**250 / 208 / 152 / 180 / 242 / 152**. Moveset `targets.py`: **Sacred Fire / Punishment /
Ancient Power / Safeguard**, in that slot order.

---

## 1. Four mechanics that decide the whole plan

### 1.1 Two of Ho-Oh's three attacks are PHYSICAL [verified]

`moves.json`: Sacred Fire `category=0`, Punishment `category=0`, Ancient Power `category=1`.

This is the single most load-bearing fact in the file and it was nearly missed. It means
**Light Screen covers only Ancient Power**, which is Ho-Oh's *weakest* attack. The screen that
matters here is Reflect.

### 1.2 A critical hit discards screens AND the attacker's lowered Attack [verified]

`CalcMoveDamage`, `src/battle/overlay_12_0224E4FC.c`:

```c
if ((sideCondition & SIDE_CONDITION_REFLECT) && crit == 1 && ... ) { dmg /= 2; }
...
if ((sideCondition & SIDE_CONDITION_LIGHT_SCREEN) && crit == 1 && ... ) { dmg /= 2; }
```

`crit == 1` is the *no-crit* multiplier, so both screens are skipped on a crit. The same function
discards a negative Attack stage on a crit (`if (crit > 1) { if (statChangeAtk > 6) {stage} else
{raw} }`), which `battle/damage.py` already encodes.

**Consequence:** Reflect, Intimidate and Charm all change the common case and leave the crit floor
exactly where it was. Nothing in this document protects anything from a Sacred Fire crit.

### 1.3 Rain's halving of Fire has NO crit gate [verified]

Same function, ~40 lines later, inside the Cloud Nine / Air Lock guard:

```c
if (fieldCondition & FIELD_CONDITION_RAIN_ALL) {
    switch (moveType) { case TYPE_FIRE: dmg /= 2; break;
```

**Weather is the only damage reducer in the game that survives a critical hit.** That is why the
Rain Dance idea was right in principle even though it lost on logistics (sec 4.5).

Burn's halving is likewise ungated (`if ((calcAttacker.status & STATUS_BURN) && ability !=
ABILITY_GUTS) dmg /= 2;`) — irrelevant here, since Ho-Oh is Fire-typed and cannot be burned, but
it is live in the other direction: a burned Smeargle deals half False Swipe damage.

### 1.4 Reflect is a SIDE condition, so it survives our switches [verified]

`ctx->fieldSideConditionFlags[side]` (`src/battle/battle_command.c:2577`, `:4010`) — indexed by
side, not by battler. Whoever sets it, it stays up when we switch. A second Reflect while one is
active takes the fail branch at `:2577`.

---

## 2. Incoming damage, by party member

Max rolls. "rain" is Ho-Oh's Fire halved per sec 1.3. Types are in: Fire→Steel 2.0, Fire→Water 0.5,
**Dark→Steel 0.5**, **Rock→Steel 0.5**, Rock→Flying 2.0 — which is why Punishment and Ancient
Power barely scratch Magneton and why Ancient Power is what threatens Gyarados.

| | HP | Sacred Fire | SF crit | SF crit, rain | Punishment | Pun crit | Ancient Power | AP crit |
|---|---|---|---|---|---|---|---|---|
| Smeargle Lv58 | 153 | 286 **KO** | 573 | 288 **KO** | 115 | 230 **KO** | 94 | 188 **KO** |
| Magneton Lv70 | 171 | 240 **KO** | 480 | 246 **KO** | 24 | 49 | 30 | 60 |
| Ampharos Lv93 | 311 | 105 | **210** | 108 | 43 | 86 | 32 | 64 |
| Togekiss Lv92 | 290 | 79 | 159 | 81 | 32 | 64 | 56 | 112 |
| Suicune Lv40 | 141 | 79 | 159 **KO** | 81 | 64 | 128 | 61 | 122 |

Ho-Oh's whole-battle budget against Ampharos is **900** (5 PP each × max roll, no crits) across 15
attacking turns, then 25 Safeguards and Struggle. With the solver's zero-advance Hyper Potion,
Ampharos outlasts the fight.

---

## 3. Availability: what each Pokemon can actually be taught

From `files/poketool/personal/personal.json` (`tms`) and `files/poketool/personal/wotbl.narc`
(level-up, entries `(level << 9) | moveId`, terminated `0xFFFF`). [verified]

| | Reflect (TM33) | Rain Dance (TM18) | Thunder Wave (TM73) | Light Screen (TM16) | Flash (TM70) |
|---|---|---|---|---|---|
| **Ampharos** | **NO** | yes | yes | yes | yes |
| Magneton | yes | yes | yes | yes | yes |
| Togekiss | yes | yes | **yes** | yes | yes |
| Suicune | yes | yes *(and knows it natively)* | no | no | no |
| Smeargle | — (Sketch) | — | — | — | — |

Level-up finds worth recording:

* **Granbull / Snubbull learn Charm at L1.** Their whole L1 block is Ice Fang, Fire Fang,
  Thunder Fang, Tackle, Scary Face, Tail Whip, **Charm**. Intimidate is ability slot 1, Quick Feet
  slot 2, so a wild one is a coin flip — see "Sourcing a Snubbull" below.
* **Gyarados learns Rain Dance at L38** and Leer at L26. So rain needs neither the TM nor Suicune.
* Suicune's own encounter moveset already contains Rain Dance in slot 1, so the single TM18 in the
  game is uncommitted either way.

### 3.1 Sourcing a Snubbull [verified]

**Route 38 is the only place in SoulSilver**, in all three time-of-day tables
(`files/fielddata/encountdata/s_enc_data.c`, `MAP_R38`), and it is the **last** of the twelve land
slots. `EncounterSlot_WildMonSlotRoll_Land` (`src/field/encounter_check.c:632`) gives slot 11 the
`rnd == 99` branch, so that is **1%**, at **level 13**.

Two things make the trip much cheaper:

* **Snubbull is Route 38's swarm species** (`.landSwarm = SPECIES_SNUBBULL`), and
  `EncSlots_Update_LandSwarm` overwrites `encSlots[0]` and `encSlots[1]` — the two 20% slots. So
  during a Snubbull outbreak it is **40% instead of 1%**, a 40x difference. Worth waiting for.
* **The ability is readable before you throw a ball.** `sendOutState` case 3 loops over
  `ctx->turnOrder` across *every* battler, so a wild Intimidate holder fires on battle start too —
  a Snubbull with Intimidate drops your lead's Attack as the encounter opens, and one with Quick
  Feet does nothing. Flee and re-roll rather than catching and checking.

**Tauros is slot 10 on the same route** (level 13, 4%) and is also an Intimidate user, but its
learnset has Tail Whip and no Charm, so it is only a substitute for the Intimidate half.

Levelling is cheaper than it looks: with 252 HP / 252 Def it only needs **Lv 36** to survive any
single non-crit hit, and **Lv 45-50** is comfortable (sec 4.3). The evolution at L23 is on the way,
and L13 → L36 is a shorter climb than taking a Gyarados from L40 to the L58-60 it needs.

Items:

* **Light Clay is obtainable** — an item ball on Kanto Route 9
  (`files/fielddata/eventdata/zone_event/014_R09.json`, `FLAG_HIDE_ITEMBALL_R09_LIGHT_CLAY`).
  Screens 5 → 8 turns. [verified]
* **Damp Rock is not reachable on this cartridge.** `HOLD_EFFECT_EXTEND_RAIN` exists in
  `item_data.csv` but has no field-event or script reference anywhere in the decomp, so it is a
  shop item — and without DPPt it is out. Rain stays 5 turns.
* **A Choice Scarf and a Light Clay cannot both be held.** Magneton is the only member that can
  carry either; the scarf wins (sec 4.4), so Reflect is a reaction rather than a pre-set.

---

## 4. The party, member by member

### 4.1 Ampharos Lv93 — the setup tank. One level short.

`311 137 182 336 210 143`. Reverse-engineered: Modest (+SpA/−Atk), max SpA investment, HP
IV+EV/4 = 44. Static is its only ability (`['ABILITY_STATIC', 'ABILITY_NONE']`).

Worst single hit is a **Sacred Fire crit at 210 of 311** — comfortable. The one hole is Ho-Oh at
+1 Atk from an Ancient Power proc:

| Ho-Oh Atk | Sacred Fire crit | vs Ampharos |
|---|---|---|
| +0 | 178-210 | safe |
| **+1** | **264-312** | **the 100-roll kills, 1 of 16** |
| +2 | 354-417 | dead |

**Lv 94 closes it**: 314 HP against 262-309, because its Defence grows as its HP does. Lv93 with
~4 more HP EVs (312 HP) does the same. Nothing fixes +2 except rain.

**Ampharos must never attack.** Ho-Oh is Fire/**Flying**, so Electric is 2× off 336 SpA:

| move | damage | vs Ho-Oh's 250 HP |
|---|---|---|
| **Discharge** | 222-264 (crit 446-528) | **KOs on the top rolls** |
| Discharge + Magnet | 266-314 | **always KOs** |
| Thunderbolt | 264-312 | always KOs |
| Signal Beam (Bug, 0.25×) | 17-20 | safe, and worse than a Screeched False Swipe |

The **Magnet is actively dangerous** — it exists only to make the move that kills the target kill
it harder. Hold Leftovers (+19/turn against a 900 budget).

#### Leftovers, and the one ordering detail that matters [verified]

Not implemented at all until clayton-957.10.12 — the word appeared in these notes and in a test
fixture's `item=` string, and nowhere in the code. With Magneton and Ampharos both holding one,
the predicted HP would have been low by max HP / 16 **every turn**, and the predicted HP is
compared exactly: the true seed dies on turn two of the run.

| fact | figure | source |
|---|---|---|
| recovery | `max(1, maxHP / 16)` = **19** on a 311 HP Ampharos | `CheckItemGradualHPRestore`, `src/battle/overlay_12_0224E4FC.c:4136` |
| only while below maximum | at full HP the item does **nothing**, which is not the same as healing zero | the same function's `hp < maxHp` gate |
| floors, never to zero | a 10 HP Pokemon still gets 1 | `DamageDivide`, `overlay_12_0224E4FC.c:3110` — the same function the burn tick uses |
| RNG cost | **zero**, so it carries no token of its own | deterministic, like the burn tick |
| **order** | **recovery lands BEFORE the burn tick** | `UpdateMonConditionState`, `src/battle/battle_controller_player.c:1143` — `UMC_STATE_LEFTOVERS_RECOVERY` precedes `UMC_STATE_BURN` |

The ordering has a consequence the player will see, and it is the player's own observation: **a
burned holder can never *end* a turn on full HP.** The recovery is gated on being below maximum,
so at full HP it is skipped and the tick takes 1/8 anyway. But every turn after that nets 1/16
instead of 1/8 — `200 + 19 - 38 = 181`, so **-19/turn against -38** — which roughly doubles how
long a burned Ampharos lasts. Keep the item on after Sacred Fire burns it.

One implementation note worth keeping: the residual is **measured, not predicted**. Both figures
are clamped by `with_hp`, so a recovery that tops us off restores less than 19, and a predicted
total would have demanded an HP token on a turn where nothing random happened at all.

### 4.2 Smeargle Lv58 — the Phase 2 body

`153 HP / 66 Def / 160 Spe`, Technician, +Spe nature with Speed maxed; HP IV+EV/4 = 37, Def = 36.

It solves because **False Swipe is the only damaging move in the party that cannot KO** — an
unlimited 3-roll filler action that is safe at 1 HP by construction, 40 PP = 20 uses under
Pressure.

False Swipe at 60 effective power (Technician on 40) against Ho-Oh's 152 Defence:

| | damage | hits to reach 1 HP |
|---|---|---|
| no Screech | 22-27 | 10-12 |
| 1 Screech (−2) | 42-51 | 5-6 |
| 2 Screeches (−4) | 64-76 | 4 |
| **3 Screeches (−6)** | **84-99** | **3** |

Survival, against a **non-crit** Sacred Fire, by Ho-Oh's Attack stage:

| Ho-Oh Atk | SF max | Lv58 as it stands | min Lv, current EVs | min Lv, +252 HP EVs |
|---|---|---|---|---|
| +0 | 286 | KO | Lv 82 | Lv 74 |
| −1 | 190 | KO | Lv 66 | Lv 59 |
| **−2** | **144** | **survives** | Lv 58 | Lv 58 |
| −5 | 82 | survives | Lv 58 | Lv 58 |

Three caveats, in order of how much they matter:

1. **No level survives a Sacred Fire crit.** 573 against a Lv100 max-HP Smeargle's 314.
2. At −1 the binding threat becomes a **Punishment crit at 230**, lethal through Lv61 even with
   max HP EVs; Lv66 survives it (206 vs 210).
3. **Ancient Power is special**, so Intimidate and Charm never touch it — 79-94, crit 159-188.

### 4.3 Granbull — Charm, and exactly how much of it is worth having

Base 90/120/75/60/60/45, pure Normal, so all three of Ho-Oh's attacks are neutral on it and its
base-60 Sp. Def is the hole. Charm is effect 58, accuracy 100, 20 PP, **−2 Atk per use**, and
stacks on its own Intimidate.

| route | Atk reached | field turns |
|---|---|---|
| Gyarados, 1 switch-in | −1 | 1 |
| Gyarados, 2 switch-ins | −2 | 2 |
| **Granbull, entry + 1 Charm** | **−3** | **2** |
| **Granbull, entry + 2 Charms** | **−5** | **3** |
| Granbull, entry + 3 Charms | −6 | 4 |

**−5 is the correct dose, and the reason is sec 4.2's third caveat.** Ancient Power is special and
fixed at 94. Sacred Fire crosses below it at −4:

| Ho-Oh Atk | −2 | −3 | **−4** | −5 | −6 |
|---|---|---|---|---|---|
| Sacred Fire max | 144 | 115 | **96** | 82 | 73 |
| Ancient Power max | 94 | 94 | **94** | 94 | 94 |

Past −4, Ancient Power *is* the largest non-crit hit Ho-Oh has and no amount of Attack reduction
moves it. Charming to −6 buys one thing only — Smeargle surviving two non-crit Sacred Fires
(73 + 73 < 153) — and Ancient Power spoils even that in any mixed pair.

#### Its own survival, and why HP / Def is the right spread

**Its Intimidate lands on its own switch-in turn**, because a switch resolves before any move. So
the strictest bar is the entry turn with Ho-Oh at **−1**; each Charm then makes the next turn
easier. Minimum level to survive any single non-crit hit at full HP, 31 IVs:

| spread | at −1 (entry) | at −3 | at −5 |
|---|---|---|---|
| **252 HP / 252 Def** | **Lv 36** | Lv 32 | Lv 32 |
| 252 HP / 252 Def, +Def nature | **Lv 34** | Lv 32 | Lv 32 |
| 252 HP / 128 Def / 128 SpD | Lv 38 | Lv 29 | Lv 29 |
| 252 HP only | Lv 41 | Lv 32 | Lv 32 |
| 252 HP / 252 SpD | Lv 41 | Lv 31 | Lv 27 |
| 31 IV, no EVs | Lv 45 | — | — |

**252 HP / 252 Def is correct, and the reason is the entry turn specifically.** At −1 the binding
move is still Sacred Fire (138 at Lv36), so Defence is what pays. Ancient Power only takes over as
the largest hit from −3 onwards — which is why the SpD spread wins every column except the one
that actually gates the plan. Def EVs buy the turn you cannot avoid; SpD EVs buy turns that are
already safe.

With 252 HP / 252 Def, by level:

| | HP | Sacred Fire (−1) | Punishment (−1) | Ancient Power |
|---|---|---|---|---|
| Lv 36 | 144 | **138** | 56 | 113 |
| Lv 40 | 159 | 124 | 50 | 101 |
| Lv 45 | 178 | 111 | 45 | 92 |
| Lv 50 | 197 | 100 | 41 | 83 |

Three bars, so pick by how much grinding you want:

* **Lv 36** — survives any single non-crit hit. The answer to the question as asked.
* **Lv 50** — survives two consecutive hits (197 vs 100 + 83).
* **Lv 59** — survives all three of its turns even if **every** attack connects (230 vs
  85 + 70 + 70).

Lv59 is pessimism though: its three turns come *after* the six Flashes, so Ho-Oh is hitting at
31-33% and all three connecting is roughly a 3% branch. **Lv 36 is sufficient and Lv 45-50 is
comfortable** — either is a far shorter climb from L13 than taking a Gyarados from L40 to L58-60,
and the evolution at L23 is on the way.

Surviving a *crit* is a different question and not worth chasing: Lv 73-84 depending on spread, and
sec 1.2 means no Defence investment touches it anyway. Granbull is expendable once its Charms land.

### 4.4 Magneton Lv70 — one guaranteed turn, then a liability

Scarfed it is 186 against Ho-Oh's 152 (`readiness.speed_after_item`: `spe * 15 / 10`). On turn 1
it moves first, Thunder Wave is accuracy 100, and Ho-Oh cannot have raised Safeguard because it
has not acted. **Turn-1 paralysis is a certainty, not a gamble.** [derived]

After that it is fragile: **any Sacred Fire kills it from full HP** (240 vs 171), and rain only
saves the non-crit (122 vs 171; crit 246 still kills).

Its second job is Screech, and it is reachable: **the Choice lock is cleared on switching out**
(`state.py:147` — the ROM refuses every other move "until it leaves the field"). So Magneton can
Thunder Wave, leave, and return locked into Screech. One move per visit, which is also why Reflect
would cost a dedicated third visit.

### 4.5 Suicune Lv40 — the EV answer, and why it stays benched

Reverse-engineered from `141 63 119 89 109 84`: Bold (+Def/−Atk), HP IV 28-29, Def/SpA/SpD 31,
Spe 28-29, Atk IV ~13-17.

Minimum level to survive **every** crit Ho-Oh can land:

| | Ho-Oh +0 Atk | Ho-Oh +1 Atk |
|---|---|---|
| **252 HP EVs** | **Lv 40 — already there** (166 vs 159) | Lv 49 (202 vs 196) |
| no EVs | Lv 43 (151 vs 148) | Lv 53 (184 vs 181) |

So the answer to "how much levelling" is **none** — 252 HP EVs on the Lv40 Suicune clears every
crit at +0, and Lv49 covers the one-Ancient-Power case. Worth doing as an emergency body.

It still stays off the field:

* Rain is **5 turns** with no Damp Rock, and the phase that needs protection — the solve — is
  twenty. Reflect is 8 turns with Light Clay, survives switching, and halves Punishment too.
* **Its Pressure doubles Ho-Oh's PP consumption**, and `struggle_deadline` is computed from that
  PP because Struggle is unmodelled. `sim.act_target` spends a flat `spend_pp(target_slot, 1)`, so
  our own Pressure is **not modelled at all** and the solver would plan against PP Ho-Oh no longer
  has.

### 4.6 Togekiss Lv92 — the paralyzer we are not using

`290 121 244 278 249 238`. It has **TM73 and 238 Speed against 152**, so it wins the paralysis
race bare — no Choice Scarf, no move lock — from a body whose worst incoming hit is a 159 Sacred
Fire crit. That would retire the scarfed-Magneton act entirely. Not taken only because its moves
are already set.

Air Slash is accuracy 95 and four rolls, which per `notes/seed_separation.md` makes it the richest
separating action in the party. But at 84-100 (crit 169-201) against 250 HP it is a **two-use
maximum**, and it needs Serene Grace modelled (sec 6.2) before it is sound at all.

### 4.7 Gyarados — the Intimidate shuttle

Water/Flying, so Sacred Fire is 0.5× — and its worst incoming move is **Ancient Power** (Rock 2× on
Flying), not Sacred Fire. At Lv60/31IV the crits are AP 158-188, SF 135-160, Punishment 110-130.

Minimum level to survive **every** crit:

| spread | min level |
|---|---|
| 31 IV, 0 EV, neutral | **Lv 58** (196 vs 192) |
| 0 IV, 0 EV, neutral | Lv 66 |
| 0 IV, 0 EV, −Def nature | Lv 66 |
| 0 IV, 0 EV, −SpD nature | Lv 69 |

EVs close the gap faster than levels: at Lv60 from 0 IVs, 252 HP alone flips it from 184-vs-212
(KO) to 221-vs-212 (safe), and 252 HP / 128 Def / 128 SpD gives 221 vs 188.

**Any Gyarados at Lv60 with 252 HP EVs is a crit-proof Intimidate shuttle regardless of IVs.**

### 4.8 Rejected

* **Leer.** −1 Def where Screech is −2, and the floor is −6 either way, so three Screeches already
  reach the cap. Strictly dominated; it buys nothing.
* **Discharge / Thunderbolt / the Magnet.** They kill the target (sec 4.1).
* **Light Screen.** Wrong category (sec 1.1), and Ampharos cannot learn Reflect instead (sec 3).
* **Damp Rock.** Not on this cartridge (sec 3).
* **Charm past −5.** Ancient Power is special (sec 4.3).

---

## 5. The two abilities that change the RNG, and one that does not

### 5.1 Static — no roll once Ho-Oh has a status [verified]

`CheckAbilityEffectOnHit`, `overlay_12_0224E4FC.c:3589`, in source order:

```c
battleMons[attacker].hp && !battleMons[attacker].status && !(moveStatusFlag & MOVE_STATUS_FAIL)
  && !(battleStatus & CHARGE_TURN) && !(battleStatus2 & UTURN)
  && (selfTurnData[target].physicalDamage || specialDamage)
  && (moveData[moveNoCur].unkB & 1)                     // contact
  && (BattleSystem_Random(battleSystem) % 10 < 3)       // 30%, and LAST
```

The RNG call is the final term, so C short-circuits before it. Three things follow:

* **Once Ho-Oh is paralyzed, Static spends no roll at all.** The turn-1 Thunder Wave therefore
  makes Ampharos's Static permanently dormant.
* It needs the contact flag, and **Punishment is Ho-Oh's only contact move** — `unk_b & 1` in
  `moves.json`: Punishment and False Swipe yes; Sacred Fire, Ancient Power, Air Slash, Discharge no.
* Unmodelled it is still a correctness hole on the one path that re-arms it: Ampharos entering
  while Ho-Oh is unstatused, i.e. only if the Magneton opening is skipped or fails.

### 5.2 Serene Grace — same roll, moved threshold [verified]

`BtlCmd_CheckEffectActivation` (`battle_command.c:5091`) and the two sites at
`overlay_12_0224E4FC.c:1308`/`:1329`:

```c
effectChance = moveData[moveNoCur].effectChance * (ability == ABILITY_SERENE_GRACE ? 2 : 1);
if ((BattleSystem_Random(battleSystem) % 100) < effectChance) { ... }
```

One roll either way; only the comparison changes. Omitting it predicts 30% where the game uses
60% — **same advance, wrong verdict**, which eliminates the true seed. It is entirely inert for a
Togekiss carrying no secondary-effect move.

### 5.3 Intimidate — deterministic, and it re-triggers [verified]

`sendOutState` case 3, `overlay_12_0224E4FC.c:3253`: it sets `BATTLE_SUBSCRIPT_INTIMIDATE` with
**no `BattleSystem_Random` anywhere in the branch**. And `intimidateFlag = 0` sits at
`overlay_12_0224E4FC.c:82`, inside the battler-initialisation function that reads IVs and the
nickname off the mon — so it runs on **every send-out**, not once per battle.

* The same Intimidate user switched out and back in **fires again**, stacking to −6.
* Nothing blocks it: Ho-Oh's ability is Pressure, not Clear Body or Hyper Cutter; it has no Mist;
  and Safeguard does not touch stat drops.
* **The drop is permanent**, because Ho-Oh never switches out. The `statChanges[i] = 6` reset two
  lines above line 82 applies only to the Pokemon being sent out — ours.

The same permanence argument is what makes Flash the best action in the plan: six Flashes put
Ho-Oh at −6 accuracy **for the rest of the battle**, where rain is 5 turns and Reflect is 8.

| Ho-Oh's accuracy after N Flashes | −0 | −1 | −2 | −3 | −4 | −5 | −6 |
|---|---|---|---|---|---|---|---|
| Sacred Fire (95) | 95 | 71 | 57 | 47 | 40 | 35 | **31** |
| Punishment / Ancient Power (100) | 100 | 75 | 60 | 50 | 42 | 37 | **33** |

Flash is 20 PP = 10 uses under Pressure. At −6 it fails, and **[player report]** that failure does
not change the turn's roll count — so unlike Light Screen's self-failure (sec 9 item 9) it needs no
`will_fail` case and Flash stays a usable filler indefinitely. Worth a ground-truth capture if it
ever becomes load-bearing.

### 5.4 Safeguard blocks a status MOVE but not Static [believed, not verified]

The asymmetry the Safeguard contingency rests on, and the one claim in this file that the
decompilation cannot settle.

`SIDE_CONDITION_SAFEGUARD` appears in exactly **four** places in the whole of `src/`: the move
setting it, the move failing against itself (`battle_command.c:3523`), and its expiry
(`battle_controller_player.c:914`). **There is no Safeguard term in any status-application path.**
The blocking lives entirely in the battle scripts inside `NARC_a_0_0_1`, where
`BATTLE_SUBSCRIPT_PARALYZE` cannot be read. `CheckAbilityEffectOnHit` has no Safeguard check of
its own, which is *consistent* with the Gen 4 behaviour but is not proof, because the subscript it
dispatches to might carry one.

What is on the record: in Gen 4 the ability-induced statuses — Static, Poison Point, Flame Body,
Effect Spore — bypass Safeguard, and Gen 5 closes the hole. The simulator already encodes exactly
that split, and it fell out of modelling Static as an ability rather than as a move: `will_fail`
refuses a status move while Safeguard is up (clayton-957.7) and `_contact_ability` never consults
it. Pinned by `TestSafeguardDoesNotStopStaticInGenFour` so it is not "fixed" into blocking later.

It matters because it is the only paralysis route a Safeguard cannot wall off: a Punishment into
Ampharos is 1-in-4 of Ho-Oh's move choices and 30% to paralyze, and it works through the five
turns that would otherwise stall the whole plan.

### 5.5 Losing the Speed race costs 0.12 percentage points, not the plan

An earlier reading of this section had an Ancient Power Speed proc *ending* the scarfed-Magneton
plan, on the grounds that +1 Spe is 228 against Magneton's 186. **That was wrong, and the error is
worth keeping.** Magneton does not need to move first to paralyze — it needs to survive the turn,
after which Thunder Wave resolves as normal. Moving first buys one turn's worth of the 25%
full-paralysis skip and nothing else, because the damage per hit is identical either way:

| Magneton's Thunder Wave turn, Ho-Oh at −1 from Intimidate | P(death) |
|---|---|
| moves first (Thunder Wave lands, then a paralyzed Ho-Oh attacks) | 0.36% |
| moves second (Ho-Oh attacks unparalyzed, Thunder Wave lands if Magneton lives) | 0.48% |

**What an Ancient Power proc actually costs is the Attack**, because it raises every stat by one
stage and Intimidate is also one stage — so a single proc cancels Granbull's work exactly:

| Ho-Oh's Attack stage | Sacred Fire vs Magneton (171 HP) | P(death) |
|---|---|---|
| −1, Intimidate only | 134-162 — survives | 0.48% |
| **0, Intimidate + one proc** | **204-240 — one-shot** | **7.75%** |
| −2, plus a Charm | 102-122 — survives | 0.48% |

So the rule is **check Ho-Oh's Attack stage before sending Magneton in**, not *count turns since
Granbull* — which is precisely what the stage display in `hrStages` exists to make possible. A
proc that nets the stage to zero shows as *no Attack chip at all*, and that disappearance is the
warning.

And the guarantee Phase 2 depends on is safe at every reachable stage, which removes the worry
entirely — a **paralyzed** Ho-Oh never outspeeds Smeargle:

| Ho-Oh Spe, paralyzed | vs Smeargle's 160 |
|---|---|
| +0 → 38 | Smeargle first |
| +1 → 57 | Smeargle first |
| +6 → 152 | Smeargle first, by 8 — and not a tie, so no unmodelled extra roll |

At +6 the stage multiplier cancels the quartering exactly and Ho-Oh is back to its full 152, and
Smeargle still clears it. (The 228 figure in sec 7 is the *unparalyzed* speed, which is why it
rules out the sleep route specifically: sleep leaves the Speed unquartered.)

---

---

## 6. The X-item trade, which is not free against this target

`punishment_power` sums **our** positive stat stages: 60 + 20 each, capped at 200. So every X item
we use feeds the physical attack hitting us. Ampharos Lv94 (314 HP, Def 184, SpD 211):

| item | Sacred Fire max | Punishment max | Ancient Power max |
|---|---|---|---|
| none | 103 | 42 (60 BP) | 32 |
| **X Defend +1** | **70** | **38** (80 BP) | 32 |
| X Sp. Def +1 | 103 | **56** (80 BP) | 22 |
| X Defend +2 | 52 | 35 (100 BP) | 32 |
| X Sp. Def +2 | 103 | **69** (100 BP) | 17 |

**X Defend is the better buy and X Sp. Def is net-negative** against Ho-Oh: the ×1.5 Defence beats
the ×1.33 power it feeds, while X Sp. Def trades 10 points off Ancient Power for 14 *onto*
Punishment. "Whichever defence the incoming move uses" is the right rule, but the tiebreak has to
recompute Punishment's power at the post-item stage, which `choose_item` does not do.

Note the negative stages we inflict on **Ho-Oh** — Flash, Screech, Intimidate, Charm — do not feed
Punishment at all, since only positive stages on its target count.

---

## 7. Capture odds: the Luxury Ball is the goal, not a variable

**The whole point of this project is catching hard targets in fancy balls whose multiplier is
×1.** The Luxury Ball is not a preference to be traded away for throughput — it is the deliverable.
Everything else in this document exists to make a ×1 ball work.

Ho-Oh is catch rate 3; at 1 HP with a ×1 ball the HP term resolves to the same `a` for any max HP,
so its HP IVs never need to be known. `claytonlib.battle.catch`:

| status | ball | `a` | `b` | P(catch)/throw |
|---|---|---|---|---|
| **paralyzed** | **×1 (Luxury)** | **3** | **21845** | **1.23% ← the target case** |
| asleep | ×1 | 4 | 23301 | 1.60% |
| none | ×1 | 2 | 19784 | 0.83% |
| *(paralyzed)* | *Ultra ×2, for scale only* | *7* | *26886* | *2.83%* |

1.23% is **identical to Suicune** (`battle_compass_next_targets.md` sec 3), which is to say it is
exactly the case Battle Compass was built for. A capture is not a per-throw gamble: it needs **four
consecutive rolls** under `b`, which makes it a property of a *position in the RNG stream* that the
solver steers onto. The low figure is why the tool has to exist, not an argument against the ball.

Three consequences for everything above:

* **All the leverage is in window-steering, none of it in the ball.** The action alphabet, the
  distinct per-turn RNG costs, and the turn budget are the only knobs. That is what makes sec 8's
  struggle-deadline arithmetic the binding resource rather than a footnote.
* **The only remaining lever on `b` itself is the status bonus** — paralysis ×1.5 to sleep ×2.0, a
  21845 → 23301 move, and the solver already copes with a `b` that varies along a path
  (`max_reachable_threshold`, added for Latias). **Here that door is closed**: paralysis is
  load-bearing for turn order, a status move against an already-paralyzed target fails, and
  Smeargle's 160 Speed only outruns Ho-Oh's 152 until a single Ancient Power proc puts it at 228.
  Sleep was the right answer for Latias because Smeargle outsped every possible spread; it is the
  wrong answer here. Recorded so nobody re-derives it.
* **A wrong ball is a lost run, not a cheaper one.** `sim` already distinguishes
  `captured_in_wrong_ball` as a terminal outcome; with the fancy ball *being* the objective, a
  standard-ball probe (`allow_standard_balls`) spends not just a turn but the goal if it succeeds.
  `notes/seed_separation.md` prices that risk at 0.35%/throw at full HP and 1.25% at 1 HP
  paralyzed — probe early, before the target is at 1 HP, or not at all.

---

## 8. The run

| turn | action | why |
|---|---|---|
| 1 | Magneton (Choice Scarf): **Thunder Wave** | 186 vs 152, accuracy 100, no Safeguard possible yet — a certainty. Static is dead from here (sec 5.1) |
| 2 | switch → **Ampharos** | worst incoming hit 210 of 314; it does not need the Intimidate yet |
| 3-8 | **6 × Flash** | Ho-Oh to −6 accuracy, permanent. X Defend over a potion while healthy (sec 6) |
| 9 | switch → **Granbull** | Intimidate, −1 Atk. Arrives into 31-33% accuracy, so its three turns are cheap |
| 10-11 | **2 × Charm** | −5 Atk, the dose sec 4.3 says is exactly right |
| 12 | switch → **Magneton** | the Choice lock cleared on switch-out, so this visit locks into Screech |
| 13-16 | **3 × Screech** (85 acc, ~3.5 attempts) | Ho-Oh Defence to −6 |
| 17 | switch → **Smeargle** | |
| 18-20 | **3 × False Swipe** | 84-99 each against 250 HP |
| 21+ | **solve on Smeargle** | False Swipe is the only damaging move in the party that cannot KO |

Roughly 20 turns of Phase 1 against Ho-Oh's 40 PP, leaving ~20 for the solve. It self-protects at
the back end: Ho-Oh has only 15 attacking PP and spends it whether its attacks hit or miss, so the
late turns increasingly land on Safeguard, which is harmless against an already-paralyzed target.

Residual risk during the solve, per turn: 75% Ho-Oh acts × 25% move choice × 31-33% hit × 1/16
crit, summed over three attacks ≈ **1.1% chance of a lethal hit**, so about **3% across the three
False Swipes** and more across a long solve. [derived]

**Party, settled:** **Magneton / Ampharos / Granbull / Smeargle**, with **Gyarados** as the
alternative or second Intimidate body and **Chatot** filling the remaining slots.

* **Natu leads, for Synchronize.** Verified that it applies to this encounter:
  `ScrCmd_WildBattle` → `SetupAndStartWildBattle` → `FieldSystem_GenerateSingleWildPokemon`,
  which takes `Party_GetMonByIndex(..., 0)` as the lead and passes it to `getWildMonNature`
  (`src/field/encounter_check.c:734`). In battle it is inert: `TrySyncronizeStatus` makes no RNG
  call, and the only status Ho-Oh can inflict is burn, which a Fire-type cannot receive. Early
  Bird is inert too. **Synchronize is ability slot 1 but Early Bird is slot 2, and unlike
  Intimidate it is invisible in battle** — so it must be read off the summary screen rather than
  the encounter.
* **The shuffle gets Magneton in free.** `_send_out` runs at the very end of the turn, after both
  sides have acted, so a replacement skips that turn's attack entirely and then moves first at
  186 against 152. Since Magneton dies to any Sacred Fire from full HP (240 against 171), letting
  Natu or Chatot faint is the difference between a guaranteed Thunder Wave and a coin flip on
  Ho-Oh's move choice. **The cost is that every shuffle turn is a free turn for an unparalyzed
  Ho-Oh at full accuracy** — and Safeguard is one move in four and blocks Thunder Wave for five
  turns, which Magneton cannot survive. With the seed known that is steerable, but it is the one
  thing to plan rather than improvise.
* **Chatot carries Growl and Sing**, both already modelled. Growl (effect 18) is −1 Atk, stacking
  with Intimidate and Charm toward the same −6. **Sing is the more valuable of the two**: at
  accuracy 55 it is the sharpest sibling separator available (`notes/seed_separation.md` prices a
  55-accuracy check at ~49.5% disagreement against 0% for a 100-accuracy one), and against an
  already-paralyzed Ho-Oh it **fails yet still spends its accuracy roll** — a free information
  probe, every turn, on a move we choose. Ho-Oh's own set offers nothing comparable, since Sacred
  Fire's 95 comes up only one turn in four. Chatot also learns **Feather Dance at L41**, which is
  Charm's effect id exactly — a levelled Chatot could do Granbull's whole job from a slot the
  party already spends.
* **Two of its level-up moves would end the run**, and both are on required party members:
  Natu's Teleport (L9) flees, and Granbull's Roar (L27) forces the target out, which against a
  wild Pokemon ends the battle. `solver.ends_the_run` refuses both — a KO costs the Pokemon, a
  flee costs the encounter.
* **Chatot never uses a move** by default, so its abilities are irrelevant — Keen Eye (blocks accuracy
  reduction) and Tangled Feet (evasion while confused) are both inert against this moveset anyway.
  It is there to reach the target advance frame, to be the body a Revive is used from, and as a
  **free-switch token**: a Pokemon that faints brings its replacement in at the end of the turn at
  no turn cost. The simulator needs nothing for this — `Battler.move` returns None for an empty
  slot and `usable_slots` skips it, which `state.py:194` notes makes "a Pokemon with no moves must
  Struggle" structural rather than special-cased.
* **Suicune is out** (sec 4.5), which also retires the unmodelled-own-Pressure concern: no member
  of this party has Pressure.
* **All six species are in `base_stats.json` now, from the ROM.** Our stats are entered off the
  summary screen but our *types* are not — `facade._battlers_for` resolves them through
  `battle.stats.species()`, which RAISES for an unknown species, so Natu, Chatot, Granbull,
  Gyarados, Ampharos and Togekiss each made starting a run fail outright. Taken from the
  decompilation's `personal.json` rather than PokeAPI, and that is not a convenience:
  `populate_base_stats.py`'s own `KNOWN_POST_GEN4_CHANGES` flags **Granbull** (became Fairy in
  Gen 6) and **Ampharos** (base stats revised in Gen 6 — Defence 75 → 85), so a fetched entry
  would have been quietly wrong for two of them. ROM-sourced entries carry `"source": "rom"` and
  `--check` no longer re-raises the verification for them.
* **Togekiss is out**, which retires Serene Grace. Both would come back if its moves were ever
  re-taught (sec 4.6).

Standing decisions:

* **Reflect is a reaction, not a pre-set** — it costs Magneton a dedicated third visit (one move
  per Choice-locked visit), and the scarf beats the Light Clay on the same held-item slot.
* **Do not solve on Ampharos.** At 1 HP every damaging move is lethal, Signal Beam's 17-20
  included, so its alphabet collapses to Light Screen and Flash — and Light Screen's self-failure
  while one is up is unmodelled.
* **Suicune stays benched** (sec 4.5).

---

## 8b. Five things a live test found, and the one that was dangerous

Found by playing the tool against the real encounter rather than by reading it, which is why they
are grouped: four were *reporting* bugs, where the simulator already modelled the mechanic
correctly and the interview gave the player no way to say what happened. The fifth was the model
lying.

### 8b.1 Static's paralysis had no token at all [fixed, clayton-957.10.13]

The player watched "Ho-Oh is paralyzed!" after a Punishment into Ampharos and the interview never
asked about it. Static is **the one event in a turn that no move announces** -- the message arrives
with nothing attached to it -- so unlike a secondary effect it cannot ride on the move's own
question or its `~` marker.

The reporting gap was the visible half. The dangerous half: two candidate seeds differing *only* in
that 30% roll rendered **identical turns**, so both survived, and the tool carried a split belief
about the one status the entire run is built on reaching. It resolves eventually -- a paralyzed
Ho-Oh spends a paralysis check, so the streams diverge a turn or two later -- through an
observation the player cannot attribute to anything.

Now `*`, after the move's own detail and after any `~`, because that is the roll order: `E2h*`, or
`E1h~*` for a contact move that also procced. A marker of its own rather than reuse of `~`,
because both can happen on one token.

It also had to work on a **switch** turn, which is the turn the plan actually uses: a switch
resolves before any move, so Ho-Oh's Punishment lands on the newcomer and it is the newcomer's
Static that fires (`S2E2h*HP289`). The snapshot's bench rows carried no `ability` field, so the
question was being skipped on precisely that turn.

### 8b.2 An invisible proc was being tokenized [fixed, clayton-957.10.10]

**This is the one that was dangerous**, and it had nothing to do with the interview. Non-volatile
statuses are mutually exclusive, so a Sacred Fire proc against an **already-burned** Ampharos sets
nothing and *says* nothing -- and the simulator emitted `E1h~` for it anyway.

Sacred Fire procs at 50% and has 8 PP, and the plan has it hitting a burned Ampharos for most of
them. So a player correctly reporting silence eliminated **every candidate that procced**, the true
seed included. The same applies to a Discharge proc against an already-paralyzed Ho-Oh, which is
the state the whole run is built on.

Only the marker is suppressed; the roll is still spent, so the stream is untouched (verified: the
rendered HP is identical with and without the burn). The *Safeguard* corner of this stays
`[believed, not verified]` -- whether a Safeguard-blocked secondary prints a protection message is
decided in the battle scripts in `NARC_a_0_0_1`, which is not in the decompilation. Suppressed on
the same reasoning as the rest of `_visible_tokens`: losing an observation costs information,
inventing one costs the run.

While fixing it: **effect 6 ("may paralyze") was listed in `MODELLED_OUR_EFFECTS` and applied
nowhere.** Ampharos's Discharge rolled its 30% and dropped the result on the floor. Same class as
957.10.2 -- a move the tool claimed to support, silently changing nothing -- and on the single most
valuable outcome available.

### 8b.3 A miss our own Flash made possible was unreportable [fixed, clayton-957.10.8]

Flash, then Punishment, then a miss, and no "Missed" chip. The simulator was right all along:
`act_ours` drops the stage before `act_target` recomputes the net accuracy, so the candidates
*did* predict `M2E2-`. The page's `can_miss` is read off the state the turn **opened** in, where
Punishment was still 100% and unmissable.

Same family as the sleep case `hrStatusWeJustApplied` already handled: half a turn happens before
the other half. A move that bypasses the accuracy check entirely keeps an effective accuracy of 0
at every stage, so Safeguard stays unmissable no matter how many Flashes have landed.

### 8b.4 The secondary question described Suicune's effects, on every move [fixed, 957.10.9]

The Yes chip was hardcoded as "<ours>'s stat fell" -- true of Aurora Beam, Mist Ball and Luster
Purge, and wrong twice over here: **Ancient Power raises Ho-Oh's five stats** and **Sacred Fire
burns us**. The player was being asked to confirm something the game never said, and the two
outcomes it conflated are the two the plan most needs distinguished.

The description now comes from the table next to the effect constants, as `(side, clause)` -- an
undescribed effect gets a bare "Yes" rather than a guess.

### 8b.5 The advice sweep outlived the position it described [fixed, 957.10.11]

Ranking is the only slow call in the tool (~8s at 6,000 candidates). The page already dropped a
stale *reply*; nothing stopped the *computation*, so reporting a turn left a sweep ranking actions
for a turn that had been played, holding the interpreter against the report the player was waiting
on. It now polls a position counter and abandons itself.

Found while fixing it: `advice()` **swept the candidate set twice per action** -- once through
`rank_actions` for the score and again through `partition` for the group count, for the same
partition. That was half the wait.

---

## 9. What the simulator still has to learn

**All of it is now implemented** (`tests/test_ho_oh_party.py`, plus
`tests/test_app_hunt_interview.py` and `tests/test_hunt_advice_abort.py` for the round the live
test produced). Kept as a record of what was wrong and why, because every one of these failed
*silently* -- `execute_move` has no notion of an unrecognised effect, so an unmodelled status move
reported success and changed nothing.

The one that mattered most was the smallest change: **957.10.1 was fixed by deleting a guard.**
A danger floor is the right instrument for the *readiness* question ("can this party do this at
all?") and the wrong one for a per-turn gate, because Phase 2 knows the stream. Smeargle solves
with a floor of 573 against 153 HP, and always could have.

One thing deliberately left unverified: **where Static's roll sits relative to a damaging move's
secondary proc.** The count is right either way, but the order decides which roll is which, and
per CLAUDE.md an advance count changes only with a ground-truth capture. It costs nothing in the
planned run -- turn-1 paralysis means no real turn ever contains both rolls -- and `_contact_ability`
says so at the call site.

| bead | gap | detail |
|---|---|---|
| **957.10.2** · done | **Our-side stat changes are silently inert** | `execute_move`'s status branch returns no stat payload and `act_ours` applies none, so **Flash, Screech and Charm all read as "it worked and changed nothing"**. Flash is the unsound one: `_effective_accuracy` already reads `accuracy_stage`, so the stage simply never gets set and every later hit/miss is computed at the wrong threshold. One table covers effects 23 (Flash), 58 (Charm), 59 (Screech), 19 (Tail Whip). |
| **957.10.3** · done | **Intimidate** | Deterministic, no rolls, applied in `_send_out` to the target's `atk_stage`, re-firing on each entry (sec 5.3). Unmodelled it mispredicts every physical hit by a third and eliminates the true seed. |
| **957.10.4** · done | **No no-KO guard on `allowed_moves`** | `SolverConfig.allowed_moves` defaults to `(0,1,2,3)` and `_legal_actions` never asks whether a move would faint the target. Against an Ampharos holding Discharge the solver will plan the move that kills Ho-Oh. |
| **957.10.5** · done | **The danger floor was frozen at entry** | Now computed per state, so Intimidate and Charm lower it and an Ancient Power proc raises it. The fix is NOT enumerating upward to +6 in the gate: that returns 828 against Ampharos's 311 and makes `in_danger` permanently true — 957.10.1's collapse, deepened. Enumeration moved to `survivability_warnings`, which is advice the player can act on rather than a gate they cannot. Memoised, or the per-node recompute cost the suite 3x. |
| **957.10.1** · done | **The item-only collapse** | Fixed by **deleting** the collapse, not by adding a risk toggle. `_legal_actions`'s `in_danger → item-only` early return was redundant: `solve` already discards every successor with `nxt.faints > current.faints`, which is an **exact per-action test against the known stream** — in Phase 2 the seed is identified, so whether an action faints us *this turn* is computed, not estimated. The floor is a bound on what the target COULD do; the simulator knows what it WILL do. Measured on seed `0xEC1504DC` with an 11/153 Smeargle: item-only reports **Unreachable**, the full alphabet finds a **150-distance capture**. So the guard was not choosing a dearer path, it was choosing none. The floor keeps its one good job — `choose_item` reads it to reach for a full heal rather than cheap filler. |
| *not filed* · n/a | **Our own Pressure is unmodelled** | `act_target` spends a flat `spend_pp(target_slot, 1)`, so a Suicune on the field would burn Ho-Oh's PP twice as fast as the simulator believes and `struggle_deadline` would be wrong. Moot while Suicune stays benched. |
| **957.10.7** · done | **Screens** | Not implemented. `damage.py` already carries the correct insertion point in a comment ("Burn's halving and the screens would sit here, in that order") and it matches the C exactly — burn, then Reflect, then weather. Only needed if Reflect is actually played. |
| *not filed* · n/a | **Serene Grace** | sec 5.2. Only if Togekiss comes in. |
| **957.10.13** · done | **Static's paralysis had no token** | sec 8b.1. The reporting gap was the visible half; the dangerous half is that two candidates differing only in the 30% rendered identical turns and both survived. `*`, after the move detail and after any `~`. Needed the bench rows to publish `ability`, or the question was skipped on the switch turn the plan uses. |
| **957.10.10** · done | **An invisible proc was tokenized, and effect 6 was inert** | sec 8b.2. The dangerous one. A secondary status that cannot land says nothing, and the simulator claimed it did -- live for Sacred Fire against an already-burned Ampharos, at 50% x 8 PP. Separately, effect 6 ("may paralyze") was listed as modelled and applied nowhere, so Discharge rolled its 30% and discarded the result. |
| **957.10.8** · done | **A miss our own Flash made possible was unreportable** | sec 8b.3. A page-only fix: the simulator predicted `M2E2-` all along, and `move_info` is read off the turn's opening state. Gated on `effective_accuracy` so a bypassing move (Safeguard) stays unmissable at every stage. |
| **957.10.9** · done | **The secondary question asserted Suicune's effect for every move** | sec 8b.4. Ancient Power raises *Ho-Oh's* stats and Sacred Fire burns *us*; the page said "our stat fell" for both. Description moved next to the effect constants, with a bare "Yes" as the fallback rather than a guess. |
| **957.10.12** · done | **Leftovers did not exist** | sec 4.1. `max(1, maxHP/16)`, only below maximum, zero RNG, and **before** the burn tick. Two party members hold one, so the predicted HP was low by 19 every turn. |
| **957.10.11** · done | **The advice sweep outlived its position** | sec 8b.5. It now polls a position counter and raises `AdviceAborted`; the facade reports that as an outcome rather than an error. Also halved the sweep: `advice()` was partitioning the candidate set twice per action for the same answer. |
| **957.10.6** · done | **Static's conditional roll** | The RNG call is the LAST term in the `&&` chain, so an already-statused attacker spends nothing and the turn-1 Thunder Wave makes it permanently dormant. Contact-only, read off `Move.makes_contact`. A second screen's `will_fail` landed with 957.10.7. |

**No open [check] items.** The Granbull will be sourced with Intimidate deliberately (sec 3.1), and
the ball is not a parameter at all — **the Luxury Ball is the objective** (sec 7), so it is a fixed
premise of every figure above.
