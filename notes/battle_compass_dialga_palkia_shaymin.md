# Next targets: Dialga, Palkia, Shaymin

Planning only — nothing here is implemented. Every number in §1 is read out of the Platinum
decompilation at `/tmp/pokeplatinum` with the file and line that produced it, because an
encounter's level and moveset are not derivable from anything in this repo and a guessed moveset
silently mis-simulates every turn (`battle_compass/targets.py`).

All three are **Platinum only**, like Giratina and the lake trio.

---

## 0. The headline, before the detail

Three conclusions, in descending order of how much they change the plan.

1. **Dialga cannot be brought to 1 HP at all.** It needs 20–27 False Swipes and Pressure leaves
   us 20. That is arithmetic, not a tuning problem (§4A).
2. **So Phase 2 has to work at HP above 1.** The capture maths is already HP-general; the blocker
   is a single gate in `solver.solve` plus one missing field in the dominance key (§3).
3. **The move work is small**: four genuinely new effects across all three targets, and only one
   of them (Leech Seed) is structurally novel. Earth Power, Slash, Spacial Rend and Magical Leaf
   are already modelled (§2).

**Corrected since first writing.** This page originally argued the 1 HP phase was a *downgrade*
for these targets. That was wrong, and wrong because it compared the wrong things — see §4D. The
capture ball is a **requirement of the hunt, not a lever the solver pulls**: the point of Battle
Compass is a specific Pokemon in a specific ball, and most decorative balls are x1. At x1 the chip
phase is still worth 3x, so it is a lever the player chooses rather than one we can remove. What
survives is the weaker and still-decisive claim in (1) and (2): the design must span the whole HP
range, because Dialga cannot reach the bottom of it and a x3.5 ball does not need to.

The difficulty is *not* where it was for Suicune. Suicune was hard to catch (rate 3) and harmless.
Dialga and Palkia are **ten times easier to catch and lethal** — every damaging move they have
kills a Smeargle on a crit, and Roar of Time kills it without one.

---

## 1. What the ROM says

### The encounters

| target | level | script | command |
|---|---|---|---|
| **Dialga** | **70** | `scripts_spear_pillar_dialga.s:43` | `StartLegendaryBattle SPECIES_DIALGA, 70` |
| **Palkia** | **70** | `scripts_spear_pillar_palkia.s:43` | `StartLegendaryBattle SPECIES_PALKIA, 70` |
| **Shaymin** | **30** | `scripts_flower_paradise.s:46` | `StartFatefulEncounter SPECIES_SHAYMIN, 30` |

**Shaymin's command is a different one, and it does not matter** [verified].
`ScrCmd_StartFatefulEncounter` → `Encounter_NewFatefulVsSpeciesAtLevel` (`src/encounter.c:568`) is
byte-for-byte `Encounter_NewVsSpeciesAtLevel` (`:549`) plus **one data write** —
`Pokemon_SetValue(wildMon, MON_DATA_FATEFUL_ENCOUNTER, &tmp)` — placed *after*
`CreateWildMon_Scripted` and before `StartEncounter`. Same generation path, same battle start, no
RNG consumed by the flag. So Shaymin reuses `BATTLE_START_ADVANCES` unchanged and needs no new
capture. This was the one live risk in adding it and it is closed.

### Rows for `targets.ENCOUNTERS`

| | types | catch rate | ability | gender | base stats |
|---|---|---|---|---|---|
| Dialga | Steel/Dragon | **30** | Pressure | genderless | 100/120/120/150/100/90 |
| Palkia | Water/Dragon | **30** | Pressure | genderless | 90/120/100/150/120/100 |
| Shaymin | Grass | **45** | Natural Cure | genderless | 100/100/100/100/100/100 |

Catch rate is the number to notice. **Giratina is 3** — I had assumed 30 and the ROM table says
otherwise — so Giratina is a Suicune-class capture while Dialga and Palkia are ten times easier
and Shaymin fifteen times.

Natural Cure is inert on a wild target: it cures status on switch-out and a wild Pokemon never
switches out.

### Movesets

Derived the same way as every other row: `learnset.by_level` from `res/pokemon/<name>/data.json`,
walked in order, keeping the last four learnable at ≤ level **in learn order**, which is the slot
order the `E1`–`E4` tokens and the wild selection roll depend on.

| target | level | slot 1 | slot 2 | slot 3 | slot 4 |
|---|---|---|---|---|---|
| **Dialga** | 70 | Roar of Time | Heal Block | Earth Power | Slash |
| **Palkia** | 70 | Spacial Rend | Heal Block | Earth Power | Slash |
| **Shaymin** | 30 | Growth | Magical Leaf | Leech Seed | Synthesis |

Shaymin at 30 has **exactly four** learnable moves (Growth 1, Magical Leaf 10, Leech Seed 19,
Synthesis 28), so nothing is evicted — the first target where the window is not a coincidence.

Three strokes of luck in the Lv70 window worth recording, because each would have been a problem:
**Ancient Power (20) is pushed out** by four later moves, so no all-stats self-boost and no threat
to the no-speed-tie guarantee from that direction; **Dragon Breath (1) is pushed out**, so no
incoming paralysis; and **Aura Sphere (90) and Flash Cannon (80) are out of reach**, so Dialga's
only special coverage is Earth Power and Roar of Time.

### Derived stats at the encounter level (31 IVs, Timid)

| | HP | Atk | Def | SpA | SpD | Spe |
|---|---|---|---|---|---|---|
| Dialga Lv70 | 241 | 174 | 194 | 236 | 166 | **167** |
| Palkia Lv70 | 227 | 174 | 166 | 236 | 194 | **182** |
| Shaymin Lv30 | 109 | 66 | 74 | 74 | 74 | 81 |

---

## 2. Move coverage: four new effects, one of them real work

**Already modelled, free:**

* **Earth Power** (72) — in `SECONDARY_STAT_DROPS` and `MODELLED_TARGET_EFFECTS`; its 10% Sp. Def
  drop on us arrives through the same table Luster Purge's does.
* **Slash** and **Spacial Rend** (43) — `HIGH_CRIT_EFFECTS`, modelled for Aeroblast.
* **Magical Leaf** (17) — accuracy 0, never misses, spends no accuracy roll. Modelled for Swift
  and Faint Attack.
* **Growth** (13) — already in `PRIMARY_SELF_RAISES`; it is **absent from
  `MODELLED_TARGET_EFFECTS` only because nothing had it**, so this is a one-line table entry, the
  same shape as Haze's mirror.

**New.** All four are from the project's own effect notes (`notes/ss_rng/effects.md`), confirmed
against the scripts.

### Roar of Time — effect 80, the recharge turn

150 power Dragon, **90 accuracy**, 5 PP. On a hit the user gains
`VOLATILE_CONDITION_RECHARGING` and loses its next turn.

Three facts, and all three already have machinery in this repo:

* **No move-selection roll on the recharge turn.** `Battler_CanPickCommand`
  (`battle_lib.c:6225-6236`) returns FALSE for `RECHARGING`, exactly as it does for `MOVE_LOCKED`
  (Shadow Force) and `UPROAR`. `select_target_move` already handles both of those.
* **The recharge turn spends nothing else either.** `CHECK_STATUS_STATE_RECHARGING`
  (`battle_controller_player.c:2514-2526`) clears the flag, loads `subscript_recharging` and
  returns `CHECK_STATUS_DISRUPT_MOVE`, which stops the before-move walk there.
* **It is state 4 of that walk**, before FLINCH (5) and far before PARALYSIS (12) — full order is
  SLEEP, FREEZE, TRUANT, **RECHARGING**, FLINCH, DISABLE, TAUNT, IMPRISON, GRAVITY, HEAL_BLOCK,
  CONFUSION, PARALYSIS, ATTRACT, BIDE, SELF_THAW. So **a recharging *and* paralyzed Dialga spends
  no paralysis roll**, the same way the taunt refusal already short-circuits it.

It is also **not** a "move failed" for `BattleContext_MoveFailed` — recharge is absent from that
function's nine flags, so it must not set `move_failed` (it would end an Uproar early, if
anything ever had one).

Shape to copy: `charging_slot`. A `recharging` flag plus a `tokens` marker for the lost turn.

### Heal Block — effect 236, and it is almost entirely inert

100 accuracy, 15 PP, 5 turns, fails if already applied. The surprise is how little it does to us:
`Move_HealBlocked` (`battle_lib.c:3427-3440`) tests a **hardcoded list of 14 moves** —

> Recover, Softboiled, Rest, Milk Drink, Morning Sun, Synthesis, Moonlight, Swallow, Heal Order,
> Slack Off, Roost, Lunar Dance, Healing Wish, Wish

— plus the Ingrain and Aqua Ring residuals (`battle_controller_player.c:1315, 1336`). **It does
not touch items and it does not touch Leftovers** [verified: `healBlockTurns` appears at exactly
those four sites plus its own countdown]. So Hyper Potions, Full Restores and Revives work
straight through a Heal Block, and the solver's healing plan is untouched.

What it still has to be modelled for is **cost**, not effect: an accuracy roll, five turns on a
counter, and a second one *failing* — which is two advances cheaper than a successful move, the
same trap Rain Dance set on turn 3 of test1.jsonl. Shape to copy: Safeguard / Taunt.

The one party it bites is a **Rest or Roost wall** — and `notes/battle_compass_next_targets.md`
already floats a Roost-carrying Noctowl/Xatu as the sleep answer, so this is a real interaction to
warn about rather than a hypothetical.

### Leech Seed — effect 84, the structurally new one

90 accuracy, 10 PP. `subscript_leech_seed_start.s` reads, in order: Substitute check, **Grass-type
check on both type slots**, already-seeded check, miss check, then set the flag on the defender.

* **Grass types are immune** — so the one case where it does nothing is a Grass lead of ours.
* The drain is in the end-of-turn walk at `MON_COND_CHECK_STATE_LEECH_SEED`, **immediately after
  LEFTOVERS** (`battle_controller_player.c:1370-1391`), skipped for a Magic Guard holder.
* `subscript_leech_seed_effect.s`: `maxHP / 8` of the **seeded** Pokemon, negated and applied to
  it, then **that same figure is handed to the seeder** (modified by a Big Root's
  `HOLD_EFFECT_LEECH_BOOST`). Against a 154 HP Smeargle that is 19 a turn.

So it is two mechanisms at once: a residual on us (ordinary, the burn tick's shape) and **healing
for the target** (new, and the thing that breaks the frozen-target model). §4C is why solving at
full HP makes the second half disappear.

### Synthesis — effect 132, and it fails at full HP

Accuracy 0, 5 PP, no rolls of its own. `BtlCmd_WeatherHPRecovery` (`battle_script.c:5966-5979`):

| weather | heal | Shaymin (109 max) |
|---|---|---|
| none | `maxHP / 2` | 54 |
| sun | `BattleSystem_Divide(maxHP * 20, 30)` | 72 |
| rain / sand / hail | `BattleSystem_Divide(maxHP, 4)` | 27 |

**It fails outright at full HP**, which is the whole of §4C.

---

## 3. What the solver needs — less than it looks

`throw_ball` already reads `cur_hp=max(target.hp, 1), max_hp=target.max_hp` and already
short-circuits on `is_guaranteed`. `target_threshold` already computes `a` from the live HP. So
**the capture maths is HP-general today**; nothing in the arithmetic assumes 1.

What assumes it:

1. **`solver.solve`'s gate** — `if state.target.hp != 1: return Unreachable(...)`. One check.
2. **`_dominance_key` omits the target's HP.** Harmless while HP is constant, unsound the moment a
   plan can change it: two states at one RNG offset with different target HP have different `b`
   and are not interchangeable. Adding `state.target.hp` costs nothing when it is constant.
3. **`identify.solver_blockers`** (`identify.py:320-329`) gates the workflow on "declare the
   target at 1 HP", and `Phase` / `enter_pinning` are built around it.
4. `BattleState.phase`'s comment, `Battler.frozen_for_phase2`, and the `__init__` docstring all
   state the precondition in prose.

**This exact relaxation has already been done once.** `solve`'s own comment records it: the gate
used to require paralysis, then required *some* holding status, and both were dropped because "a
target we cannot status is not unreachable, only less likely per throw… the window search simply
runs at the smaller figure." The HP argument is that argument verbatim — and for these three the
figure is not even smaller (§4).

The honest form of the new precondition is **not** "any HP" but **"the target's HP is known and
the plan does not change it"**. At 1 HP that was free, because the floor made False Swipe inert and
every other move lethal. Above 1 HP it has to be enforced: either put HP in the dominance key and
let the search reason about it, or keep damaging moves out of Phase 2 filler. The first is
strictly better and is one tuple entry.

---

## 4. Per target

### A. Dialga — the PP wall, and why it decides the design

False Swipe is Normal; **Steel resists it**, and Dialga pairs that with 194 Def and 241 HP.
Pressure doubles our PP consumption, so 40 PP buys **20 uses**:

| chipper | damage | hits needed | PP budget | verdict |
|---|---|---|---|---|
| Smeargle, plain | 6–7 | 35–40 | 20 | **impossible** |
| + Technician | 8–10 | 24–30 | 20 | **impossible** |
| + Technician + Silk Scarf | 9–12 | 20–27 | 20 | **impossible** |

Even the best-equipped single chipper comes up short, and that is before asking whether it
survives 27 turns. Workarounds exist — a second False Swipe carrier, Ethers — but each spends a
party slot or an unmodelled item to buy a phase we do not need.

Against that: **Dialga at FULL HP, asleep, in a Dusk Ball is `a=70`, `b=47661`, 27.97% a throw** —
about one capture window every 3.6 stream positions, against **7.10%** for Suicune at 1 HP asleep
in the same ball. So a Dusk Ball hunt needs no chip phase at all. A **x1 ball hunt is a different
question** and is answered in §4D.

**Danger.** Against a 154 HP Smeargle, all three damaging moves are lethal on a crit, and Roar of
Time is lethal without one:

| move | damage range (to crit) |
|---|---|
| Roar of Time | 352–831 |
| Earth Power | 141–334 |
| Slash | 90–212 |

So the lead cannot be the chipper. Note the type pull in two directions: Roar of Time is Dragon
(**Steel resists it**) and Earth Power is Ground (**Flying is immune, Steel takes double**), so no
single typing walls both. A Flying type dodges Earth Power entirely and eats Roar of Time neutral;
there is no Fairy in Gen 4 to blank the Dragon half.

**Speed.** Dialga is 167 and the fixture Smeargle is 160, so **the target moves first** — the
reverse of every target so far, where paralysis guaranteed us the lead. Paralysis still fixes it
(167/4 = 41) and still pays its ×1.5, so Thunder Wave stays the opening move; it just stops being
optional. Thunder Wave lands: neither type resists Electric and neither is Ground.

### B. Palkia — Dialga without the wall

Same catch rate, same Heal Block / Earth Power / Slash, Spacial Rend instead of Roar of Time.
Water/Dragon is **neutral to Normal**, so the chip is affordable: 9–10 False Swipes with
Technician + Silk Scarf, inside the 20-use Pressure budget. So Palkia is the one of the three where
the existing 1 HP design still works.

It is still worse than throwing at full HP (27.97% a throw), and Spacial Rend at 235–555 is lethal
on a crit, so the same argument applies with less force.

Two small bonuses: **Spacial Rend is 95 accuracy and Roar of Time 90**, so both targets offer a
sub-100 event every time they pick slot 1 — which is exactly the RTC-second-sibling separation
`notes/seed_separation.md` says Suicune could not provide. Palkia is also the **fastest** target
yet at 182.

### C. Shaymin — and the case for solving at full HP

The user's instinct is right, and the reason is stronger than "we avoid modelling recovery":
**at full HP both of Shaymin's recovery moves are provably inert.**

* **Synthesis fails at full HP.** Not "heals nothing" — *fails*, with the two-advance discount a
  failing move carries. That is a `will_fail` row keyed on the **actor's** HP rather than the
  defender's, which is a new shape but a cheap one (`will_fail` already takes `actor`).
* **Leech Seed's heal is capped to nothing**, because the seeder is already full. The drain on
  *us* still happens (19 a turn off a Smeargle) and still has to be modelled — but that is our
  side, which is the burn tick's shape and already understood.

So full-HP solving does not merely dodge the hard case, it **deletes** it. At 1 HP the two moves
interact: Leech Seed tops Shaymin up, which lowers `b`, which invalidates the window the solver
precomputed — exactly the "different targets viable at different points" problem the user
described. Nothing about that arises at full HP.

And the numbers are good enough that nothing is being sacrificed:

| state | a | b | per throw |
|---|---|---|---|
| full HP, asleep, **Quick Ball** (turn 1) | 120 | 55187 | **50.28%** |
| full HP, asleep, Dusk Ball | 104 | 52428 | 40.96% |
| full HP, asleep, Ultra Ball | 60 | 47661 | 27.97% |
| full HP, no status, Ultra Ball | 30 | 38835 | 12.33% |
| **1 HP, asleep, Dusk Ball** | 312 | — | **GUARANTEED** |

Two things fall out. A **Quick Ball on turn 1 at full HP** beats every Suicune configuration by 7×,
with no setup at all. And at 1 HP asleep in a Dusk Ball `a` exceeds 255, so the ROM **skips the
shake rolls entirely** — a capture with no RNG condition to steer towards, which makes the
window search trivially satisfiable rather than hard. Either end of the HP range is easy; it is
the middle that is messy, and the middle is the part we can simply not visit.

**Shaymin is harmless.** Magical Leaf does 22–54 to a Smeargle and is its only attack. There is no
survivability problem and no speed problem (81 against 160).

**Spore works.** Grass types are not immune to powder moves until Gen 6 — `immune_to_status`
agrees — so sleep and its ×2 are available.

**Forme.** `base_stats.json` carries both `shaymin` (Grass, Land) and `shaymin-sky`
(Grass/Flying). Only Land is encounterable — Sky needs the Gracidea and daytime, after the catch —
so a single row keyed `shaymin` with no `forme` is right and `stats_key` lands on Land. Unlike
Giratina this needs no forme split, but it deserves the same test
(`test_a_forme_encounter_is_keyed_by_its_forme`), because the colliding row exists.

### D. The ball decides whether the chip phase is worth it

**The capture ball is a hunt requirement, not a solver choice.** The whole point is a specific
Pokemon in a specific ball, and most balls somebody *wants* a legendary in — Premier, Luxury,
Cherish, a plain Poke Ball — are **x1**. So the honest table is two-dimensional, and the figure
that matters is whichever cell the player's ball lands in. Asleep, at both HP extremes:

| target | x1 (Premier) full → 1 HP | x2 (Ultra) full → 1 HP | x3.5 (Dusk) full → 1 HP |
|---|---|---|---|
| Shaymin (45) | 12.33% → **40.96%** | 27.97% → 78.46% | 40.96% → **GUARANTEED** |
| Dialga / Palkia (30) | 8.09% → **23.42%** | 16.78% → 50.28% | 27.97% → 99.99% |
| Suicune (3), for scale | 0.83% → 1.60% | 1.60% → 4.37% | 2.56% → 7.10% |

Read down the x1 column: **the chip phase is worth about 3x**, which is the difference between a
window every 12 stream positions and every 4. That is not a rounding error, and it is why "solve
at full HP" is a *lever* rather than a replacement. Read across the Dusk row instead and the chip
phase buys almost nothing, because full HP is already 28%.

So the design requirement is **span**, not a new fixed point: support any HP, and tell the player
what their chosen ball costs them at each end so they can decide how much chipping to do. The
thing to build is the *readout*, not a second hard-coded precondition.

Two corollaries worth noting. **Shaymin at 1 HP asleep in a Dusk Ball exceeds `a=255`**, so the ROM
skips the shake rolls entirely — and `shake_threshold(255)` saturates at 65536, which
`capture_windows_in_horizon` already handles (every position is a window, verified). And **the
turn-1 Quick Ball x4 is only interesting if a Quick Ball is what you wanted**; as an argument for
full-HP solving it was misdirected, because it is not available to a hunt that specifies any other
ball.

### E. Making False Swipe feasible is a party problem, and it is solvable

Dialga's 20–27 hits assume a Smeargle. A prepped physical attacker changes the arithmetic
completely. Worked for a **Lv100 Adamant max-Atk/EV Gallade** (Atk 383) against Dialga's 194 Def,
with Screech stacking:

| | no Choice Band | with Choice Band (x1.5 Atk) |
|---|---|---|
| no Screech | 34 (14% of HP) | 50 (21%) |
| 1 Screech | 67 (28%) | 100 (42%) |
| 2 Screeches | 101 (42%) | 151 (63%) |
| **3 Screeches (−6 Def)** | 135 (56%) | **201 (83%)** |

So three Screeches and a Choice Band bring Dialga to 1 HP in **two False Swipes**, 4 PP under
Pressure. The PP wall disappears entirely.

Two things that has to respect:

* **A Choice Band locks its holder into False Swipe**, so the Screeches come from somebody else.
  `choice_locked_slot` already models the lock. Screech lowers the *target's* Defence, which is
  permanent on a wild Pokemon, so "Screech x3, switch, False Swipe x2" works — switching resets
  *our* stages, not theirs. Screech caps at −6 after exactly three uses [verified].
* **The Choice Band's x1.5 Attack is NOT MODELLED** (§5). Until it is, this plan is simulated at
  the left-hand column and every predicted HP after the first hit is wrong.

And **the premise may be worth questioning**: all that preparation buys a 3x better throw in a x1
ball. Given a catch rate of 30, the party slot might be better spent on something that survives
Roar of Time, since the binding constraint is turns alive, not HP removed.

---

## 5. Gotchas not yet mentioned

* **Dusk Ball depends on the venue, and the venue is not free.** `balls._dusk` already keys on
  `TERRAIN_CAVE` or the night bucket. Spear Pillar is inside Mt. Coronet and **may** be cave
  terrain — if so Dialga and Palkia get ×3.5 at any hour. Flower Paradise is outdoors, so Shaymin's
  Dusk Ball is **night only** — and the hour is not a free choice, because it is part of the
  datetime that hits the seed. *Needs checking in the map data; it is worth a real ×3.5.*
* **Access.** `ENCOUNTER_ACCESS` has no rows for these. Spear Pillar is behind a Mt. Coronet climb
  (Strength / Rock Climb / Surf / Defog) and Flower Paradise behind Surf on the Seabreak Path plus
  the Oak's Letter event. The event is a story flag, not a field move, so it gets no row for the
  same reason Latias's Enigma Stone gets none.
* **Struggle.** Dialga's PP totals 50 and Palkia's 50; Shaymin's 75. `struggle_deadline` already
  prices this. At full HP a Struggle's recoil no longer kills the prize, which is a quiet third
  argument for the same design.
* **Heal Block vs our own wall.** If the answer to Dialga's damage is a Rest or Roost wall, Heal
  Block shuts it off for five turns. That is a `survivability_warnings` interaction, not a
  simulator one.
* **`MODELLED_OUR_EFFECTS` is untouched.** Nothing here is a move our side would carry, so this is
  all target-side work.

---

## 6. The work list

Ordered so each item is useful on its own. Bead ids where filed.

### Tier 0 — correctness bugs, independent of these targets

| # | work | why now |
|---|---|---|
| 0.1 | **Choice Band / Choice Specs x1.5** in `battle.damage`. Modelled for the move LOCK only; the stat multiplier is inert [verified: identical damage with and without the item]. | Under-predicts OUR damage, so predicted target HP is wrong from the first hit and every candidate is eliminated. Same soundness class as the Scrappy hole. Blocks §4E outright. |
| 0.2 | **Our side's chip-move coverage.** Audited: Psycho Cut, Night Slash, Leaf Blade, Shadow Claw, X-Scissor, Zen Headbutt, Rock Slide, Body Slam, Screech, Swords Dance all pass. Refused: **Aerial Ace (17)**, **Earthquake (147)**, Brick Break (186), Close Combat (229), Superpower (182), Drain Punch (3), Return (121). | 17 and 147 are **one-line table rows** — both are already modelled target-side (Swift/Magical Leaf; Gust/Surf) and refused only on our half. The rest are what a real physical attacker carries. |

### Tier 1 — the architecture these targets need

| # | work | notes |
|---|---|---|
| 1.1 | **Generalise Phase 2 off `hp == 1`** — `solve`'s gate, `state.target.hp` into `_dominance_key`, `identify.solver_blockers` wording, and the prose in `__init__`/`state`. | `clayton-6xu.9.1`. Capture maths is already HP-general. Precondition becomes "HP known and the plan does not change it". |
| 1.2 | **Ball-and-HP readout**: what the configured capture ball is worth at full HP, at 1 HP, and at the current HP, per status. | The deliverable that replaces the deleted "always solve at full HP" rule (§4D). Turns a design question into a number the player reads. `_ball_readout` already exists to extend. |
| ~~1.3~~ | ~~Re-read the burn/poison gate above 1 HP.~~ **Withdrawn — the gate is correct as it stands.** | See the note below. |

### Tier 2 — advice, which is where the leverage now is

| # | work | notes |
|---|---|---|
| 2.1 | **`chip_warnings` learns arithmetic**: hits needed, PP available, and the Pressure doubling. "Your False Swipe needs 27 hits and Pressure leaves you 20" is the warning that would have produced §4A without this analysis. | Needs target Def/HP and our Atk — all available at configure time. Highest-value single item on this page. |
| 2.2 | **Survivability before chipping, for high-catch-rate targets.** The binding constraint is turns alive, not HP removed: at x1 full HP Dialga is ~12 stream positions, so the party has to last ~12+ turns against a move that one-shots a Smeargle. | Reorders what the readiness panel leads with, and should say *how many turns* each party member survives rather than only "dies to a Roar of Time". |
| 2.3 | **Speed warning is load-bearing now.** Dialga 167 and Palkia 182 both outspeed the fixture Smeargle (160) — the first targets to do so. `speed_checks` fires, but the advice ("paralyse first") is no longer optional. | |

**On the burn/poison gate, which this page briefly proposed re-opening.** The gate stays
[Testare]. My argument for revisiting it was that its stated *reason* weakens above 1 HP — the
tick no longer faints the target before a ball can land — and that is both true and beside the
point. The real argument against burn and poison never depended on 1 HP: they give the **same
x1.5 as paralysis** and arrive attached to a clock, so there is no HP at which they are the right
trade. Above 1 HP the clock is slower, not absent, and a target on a timer is strictly worse than
the same target not on one. `solver.solve` keeps refusing them — what is worth changing is the
comment, which should lead with "no benefit paralysis does not also give" rather than with the
faint, so the next reader does not mistake the reason for the rule.

### Tier 3 — the four target-side effects

| # | work | notes |
|---|---|---|
| 3.1 | **Growth** (13) | One `MODELLED_TARGET_EFFECTS` row; `PRIMARY_SELF_RAISES` already has it. |
| 3.2 | **Synthesis** (132) | Weather heal `maxHP/2` · `maxHP*20/30` · `maxHP/4`, and **fails at full HP** — a `will_fail` row keyed on the ACTOR's HP, which is a new shape. |
| 3.3 | **Heal Block** (236) | Cost only: accuracy roll, 5-turn counter, second use fails. Blocks 14 named moves + Ingrain/Aqua Ring; **not items, not Leftovers**. |
| 3.4 | **Leech Seed** (84) | Drain `maxHP/8` off us next to the Leftovers tick, same figure healing the target; Grass immune; already-seeded fails. The only structurally new one. |
| 3.5 | **Roar of Time** (80) | Recharge turn: no selection roll, no paralysis roll (state 4 vs 12), not a `move_failed`. Copy `charging_slot`. |

### Tier 4 — rows and data

| # | work |
|---|---|
| 4.1 | `ENCOUNTERS` rows for `dialga`, `palkia`, `shaymin` (§1), plus the forme test for the `shaymin-sky` row that exists but is not encounterable. |
| 4.2 | `ENCOUNTER_ACCESS` for Spear Pillar (Strength / Rock Climb / Surf / Defog) and Flower Paradise (Surf; Oak's Letter is a story flag, so no row). |
| 4.3 | **Spear Pillar's terrain** — if it is `TERRAIN_CAVE`, Dialga and Palkia get a x3.5 Dusk Ball at any hour, which per §4D removes their chip phase. Worth a real answer. |

### Tier 5 — owed a capture

| # | work |
|---|---|
| 5.1 | **The recharge turn's post-move advances.** A charge turn is `successful=True` and gets the two; a *disrupted* move looks more like the taunt refusal that spends nothing. Two advances a turn, and a run shows it immediately. |

---

## 7. Which target first

1. **Generalise Phase 2 off 1 HP** — the gate, the dominance key entry, and the workflow wording.
   Nothing else on this page is useful without it, and it is the smallest change of the three.
2. **Shaymin**, as the proof: Growth is a table row, Magical Leaf is free, and Synthesis-fails-at-
   full-HP plus the Leech Seed drain are the only new code. Harmless, fast to chip if we ever want
   to, and the one target where a mistake costs nothing.
3. **Palkia**: Heal Block, and Spacial Rend/Earth Power/Slash are free. Works under the old design
   too, so it is a clean A/B of full-HP against 1 HP.
4. **Dialga**: Roar of Time's recharge, plus whatever the survivability answer turns out to be.
   Last because it is the only one where the party, not the simulator, is the hard part.

## 8. Owed a capture

Nothing on this page needs one to *start*, which is worth saying because the last three mechanics
did. The recharge turn's zero-roll claim rests on `Battler_CanPickCommand` and
`CHECK_STATUS_DISRUPT_MOVE`, which is the same evidence the Shadow Force charge turn and the Uproar
lock already run on. The two worth confirming once a run exists:

* **The recharge turn's post-move advances.** A charge turn is `successful=True` and gets the two
  post-successful-move advances on the same derived reasoning (notes/platinum.md §13); a recharge
  turn is a *disrupted* move, which looks more like the taunt refusal that spends nothing. Those
  differ by two advances a turn and the run would show it immediately.
* **Spear Pillar's terrain**, for the Dusk Ball multiplier.
