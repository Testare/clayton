# Lugia Lv45 in a Love Ball — the plan, and what it needed

SoulSilver, Whirl Islands, targeting **Serious 31/31/31/17/31/31** (hp/atk/def/spa/spd/spe, the
project's order — `battle/stats.py`), caught in a **Love Ball**.

Claims are tagged: **[rom]** read out of `~/arch/pokeheartgold`, **[measured]** computed or
simulated here with the figures given, **[derived]** follows from a tagged claim, **[design]** a
proposal nothing has confirmed. `notes/battle_compass_next_targets.md` §1 and §3 are the parent
document; this one supersedes its §5 ordering for Lugia specifically, because the ball changed.

---

## 1. The ball is ×1, and that is the whole economics

**[rom]** `src/battle/battle_command.c:7295-7300`:

```c
case ITEM_LOVE_BALL: {
    if (ctx->battleMons[attacker].species == ctx->battleMons[target].species
        && ctx->battleMons[attacker].gender != ctx->battleMons[target].gender) {
        catchRate *= 8;
    }
    break;
}
```

A proper `break` — the famous missing one is Fast falling into Moon, two cases up. Lugia is
genderless, so the gender test fails even Lugia-against-Lugia. **×1.**

**[measured]** Lugia's max HP at 31 HP IV is 164; catch rate 3:

| state | `a` | `b` | P(catch)/throw |
|---|---|---|---|
| 1 HP, paralyzed | 3 | **21845** | **1.234%** |
| 1 HP, asleep | 4 | 23301 | 1.598% |
| 1 HP, no status | 2 | 19784 | 0.830% |
| full HP, any status | 1 | 16643 | 0.416% |

**1.234% is Suicune's number exactly** — same `a`, same `b`. So this is not an easier Suicune, it
is the same problem, which is the case Battle Compass was built for. For contrast, the Fast Ball's
×4 is real (base Speed 110 clears the ≥100 threshold **[rom]**) and would give b=33824 / 7.095%;
it is simply not what a Love Ball does. `clayton-957.3` carried those Fast Ball figures for ten
days and they were wrong for this run.

**Two consequences that change how the run is played.**

`standard_ball_matches_capture_ball()` is **True**, so a Poke Ball probe is *exactly* as likely to
catch as the Love Ball. Probe early, at full HP, where the risk is 0.416% a throw rather than
1.234%.

And **with a ×1 ball the status bonus is wasted at full HP** — the HP term floors `a` to 1 before
the status multiplies it, so paralysis buys literally nothing until the target is at 1 HP.

No code was needed for the ball itself: `app/facade.py:750` special-cases only `"fast ball"` and
everything else falls through to ×1, which is correct here. It is correct *by fall-through*
rather than by a rule, which is why `tests/test_battle_compass_lugia.py` pins it.

## 2. The target

**[measured]** Serious (neutral), 0 EVs, Lv45:

```
HP 164   Atk 99   Def 135   SpA 93   SpD 157   Spe 117
```

**The 17 is in the one stat that matters, and it is load-bearing.** All three of Lugia's damaging
moves are **special** **[rom: moves.json categories]**, so SpA is its only offensive stat. At
SpA 99 an Aeroblast crit does 156 against the Lv58 Smeargle's 153 HP; at SpA 93 it does 147.
The spread is the difference between "survives every clear-weather crit" and "doesn't".

A corollary worth stating because it differs from Ho-Oh: **our Defence is never read.** Reflect
does nothing against this target and `choose_item`'s X Defend is a pure no-op; X Sp. Def and
Light Screen are the only two that touch anything, and only on non-crits.

**Speed 117 against Smeargle's 160, and the Lv45 set has no Safeguard** — so unlike Ho-Oh Lv70
there is no Thunder Wave race at all. Lugia's ceiling is 128 with a boosting nature.

## 3. What it needed, and what was done

| | state |
|---|---|
| `clayton-957.27` — the accuracy stage table | **fixed** (§3.1) |
| `clayton-957.2` — the crit stage | **fixed** (§3.2) |
| `clayton-957.3` — the `STATIC_ENCOUNTERS` row | **added** (§3.3) |
| `clayton-957.10.15` — warn on unmodelled held items | open |
| `clayton-957.28` — Brightpowder | open |

### 3.1 The accuracy stage is a table, not the fraction it looks like

Found while reading the ROM for Brightpowder, and the most consequential of the three.

**[rom]** `sHitChanceTable[13][2]`, `src/battle/battle_controller_player.c:2399-2413`, applied as
`hitChance = hitChance * n / d` at :2490-2491, indexed by `clamp(6 + net, 0, 12)`:

```
net   -6      -5      -4      -3      -2      -1     0   +1       +2       +3  +4       +5      +6
     33/100  36/100  43/100  50/100  60/100  75/100 1/1 133/100  166/100  2/1 233/100  133/50  3/1
```

`_effective_accuracy` computed `accuracy * 3 // (3 - net)` below zero. **Two entries are not the
fraction**: 3/7 is 42.86 and the table says **43**; 3/8 is 37.5 and the table says **36**. So the
stages either side of -5 were both wrong, in opposite directions:

| net | move | ROM | the old form |
|---|---|---|---|
| -5 | Extrasensory | 36 | 37 |
| -5 | Aeroblast | 34 | 35 |
| -5 | Hydro Pump | 28 | **30** |
| -5 | Sing | 19 | 20 |
| -4 | Extrasensory | 43 | 42 |

Every other stage agreed. +2 and +5 differ by one (157/158, 252/253) but cannot change a verdict,
since anything at or above 100 always hits — fixed anyway, so that the table is the table.

**This was unsound, not imprecise.** A flipped verdict renders `h` where the game printed a miss,
the turn contradicts, and the true seed is eliminated. And it is squarely in this plan's path: the
Flash ×6 sequence passes through -4 and -5 on consecutive turns with Lugia attacking on each.

`metronome_compass.context.effective_accuracy` had the identical bug, which is worse there —
Metronome reaches Sand Attack, Flash, Kinesis and Double Team, so both directions are live, and
that module is the project's RNG-verified reference.

**A second, separate ordering difference in the same metronome function.** **[rom]** The ROM
applies, in order: the stage table → weather and ability terms → Compound Eyes → **Hustle** →
Tangled Feet → the defender's accuracy-reducing item → the attacker's accuracy-up item → Micle
Berry → **Gravity last** (`* 10 / 6`). Gravity was being applied *before* Hustle. Every step
truncates, so the position is a different number: at a base of 41, Hustle-then-gravity is 53 and
gravity-then-Hustle is 54.

Fixed by transcribing the table once into `battle.damage.apply_accuracy_stage`, with both callers
delegating. `tests/test_battle_accuracy_stage.py` asserts all thirteen entries against an
independent reading of the ROM, pins the two regression stages by the exact figures the old form
gave, and asserts the Hustle/gravity order by the truncation that separates them.

### 3.2 The crit stage

**[rom]** Effect 43 is the high-crit-ratio group, so it rolls at `CRIT_MODIFIERS[1]` — a crit on
`roll % 8 == 0`, not `% 16`. `execute_move` read slot 0 unconditionally.

**[measured]** The wrong model disagrees with the game on `roll % 8 == 0 and roll % 16 != 0`:
1/16 of Aeroblast turns against a 1/4 move choice, so **1.56% of turns — a ~47% chance of
eliminating the true seed over a 40-turn run**, with the damage doubly wrong on the same turn.

The effect ids are `{43, 200, 209}`, cross-validated against `metronome_compass.effects` rather
than inferred — `_eff_high_crit`, `_eff_burn_highcrit` and `_eff_poison_highcrit` all pass
`crit_stage=1`. The test asserts that correspondence, so the two modules cannot drift apart
silently.

**This moved no verified advance count.** `hit_crit_or_miss`'s docstring records that the group
spends the same rolls, and the test asserts `move_roll_cost` and `MoveOutcome.rolls` are unchanged.
Outcome-only.

`crit_stage_of(move, attacker)` reads an attacker crit stage defensively. Nothing in any
configured party has a Focus Energy, a Dire Hit or a Scope Lens, so `Battler` carries no such
field — the signature exists so that adding one is a field rather than a re-reading of the call
site.

### 3.3 The row

```python
"lugia": (45, ("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast")),
```

**[rom]** `scr_seq_0104_D40R0107.s:75-85` — `GetGameVersion`, then
`Compare VAR_SPECIAL_RESULT, 7` / `GoToIfNe` sends HeartGold to Lv70 and the fall-through gives
SoulSilver **Lv45**. That is the **opposite direction from Ho-Oh**, which is the trap: "SoulSilver
gets the Lv70 bird" is true of Ho-Oh and false of Lugia. `VERSION_SPLIT_LEVELS` carries the other
side of both.

`targets.unsupported_moves("lugia")` is clean once §3.2 lands; Aeroblast was the only blocker.

### 3.4 Still open

**`clayton-957.10.15`** — warn on the hunt page for every team held item the simulator does not
model, advisory and never blocking. A misconfigured item *should* desync the run; what is missing
is being told before the encounter. The allowlist is 33 names; the four that fail in the Choice
Scarf's *kind* rather than its degree, because the roll count or turn order changes, are **Quick
Claw** (random priority, and it spends a roll), **Brightpowder / Lax Incense** (every accuracy
verdict wrong), **King's Rock / Razor Fang** (a flinch roll per hit) and **Scope Lens / Razor
Claw** (wrong crit modulus).

**`clayton-957.28`** — model Brightpowder. **[rom]**
`battle_controller_player.c:2520-2524`: `HOLD_EFFECT_ACC_REDUCE` on the *defender* does
`hitChance = hitChance * (100 - itemMod) / 100`. It is a multiplier, not an evasion stage, so
Simple does not double it and Unaware does not zero it. `itemMod` is 10 but lives in a NARC, so it
carries the same "not read from source" caveat as `TYPE_ITEM_MODIFIER_PERCENT`. The ordering is
load-bearing: under Flash ×6 against Extrasensory it is `floor(floor(100·33/100)·90/100)` = 29,
not 30. Depends on §3.1.

## 4. Identification: Flash is the engine, not the mitigation

This is the part the design had backwards, and it is the most useful thing in this note.

**[measured]** Sibling separation per accuracy check, over 300 strict RTC-second sibling pairs
(seeds differing by `k·2²⁴`) × 40 advances:

| | Extrasensory | Hydro Pump | Aeroblast | per turn |
|---|---|---|---|---|
| no Flash | acc 100 → **0.0%** | 80 → 31.2% | 95 → 9.8% | **~10%** |
| Flash ×1 | 75 → 37.2% | 60 → 47.1% | 71 → 41.9% | **~32%** |
| Flash ×2 | 60 → 47.4% | 48 → 49.9% | 57 → 48.9% | **~37%** |
| Flash ×6 | 33 → 43.8% | 26 → 37.3% | 31 → 42.4% | ~31% |

**Extrasensory is 30 of Lugia's 45 PP, and at accuracy 100 its verdict is constant across
siblings — so two turns in three told us nothing.** One Flash converts it into a coin flip and
triples the per-turn separation. The peak is around ×2-3; ×4-6 are defensive.

**And the information Flash costs was never usable for this problem.** An HP reading is the
richest general signal (~2.5 bits), but the damage roll is `% 16` and 16 divides 256, so
**[measured]** it separates RTC-second siblings 0.0% of the time. Flash trades signal that cannot
separate siblings for signal that can.

### 4.1 The %3 move-selection cliff

`select_target_move` is `roll % len(usable)`. **[measured]** `%4` and `%2` both divide 256 and
separate **0.0%**; **`%3` does not and separates 66.5%**. So the moment any one of Lugia's three
5-PP moves runs dry, the move choice itself becomes the sharpest separator in the battle.

**[measured]** P(the modulus has dropped below 4), simulating uniform selection with 25% full
paralysis: **38% by turn 15, 75% by turn 20, 94% by turn 25.** A long setup *buys* identification.

### 4.2 Chatot's Sing is a free probe, and it already simulates correctly

**[rom + verified]** `execute_move` spends the accuracy roll **before** `will_fail`
(`sim.py:756-763`, pinned to `test1.jsonl` turn 3). So a Sing against an already-paralyzed Lugia
rolls its 55-accuracy check and *then* fails — **[measured]** 49.7% sibling separation, the
sharpest single probe available, with no catch risk and no status conflict. 15 PP under Pressure
is 7 per Chatot, 14 across the two.

Order matters twice: the probes must come **after** Thunder Wave (or Sing would land sleep and
displace the plan), and **after** the Flashes (Lv45 Chatot has 56 SpD, takes 85-102 from a plain
Aeroblast and dies to any crit).

## 5. The run

Party: Natu (Synchronize lead, must be **Serious** for the target nature) / Magneton / Ampharos /
Smeargle (Technician, **Silk Scarf**) / Chatot / Chatot.

**[design]** Switch → Magneton, Thunder Wave, → Ampharos, Flash ×6, → Magneton, Screech ×3,
→ Smeargle, False Swipe ×2, hand to the solver. ~15 turns.

### 5.1 Screech is a risk transfer, not a time saving

**[measured]** Smeargle Lv58, Technician **+ Silk Scarf** (base power 40 → 60 → 72, in that ROM
order — `effective_power`), against 164 HP / Def 135:

| banked | Lugia Def | False Swipe | hits to 1 HP | total turns | P(Magneton faints) | P(Smeargle faints) |
|---|---|---|---|---|---|---|
| 0 | 135 | 24-28 | 6-7 | 15.4 | 0.24% | **8.79%** |
| 1 (-2) | 67 | 45-54 | **4 exactly** | 15.2 | 0.27% | 7.07% |
| 2 (-4) | 45 | 67-81 | **3 exactly** | 15.3 | 0.69% | 4.17% |
| **3 (-6)** | 33 | 91-108 | **2 exactly** | 15.5 | 1.31% | **2.07%** |

Total turns are flat. What changes is *who* is exposed — and Magneton has finished its job by
then while Smeargle must be standing for Phase 2. **So three Screeches**, which is the opposite of
what the unscarfed numbers said (there the third bought nothing).

Note the **hit count becomes exact** at every tier: three hits cap at 162 against the 163 needed,
so -2 is always 4 and -4 is always 3. One False Swipe is impossible — 163 needed, 108 ceiling.

**[rom]** **Banked Screeches survive Magneton fainting.** `sent_out` resets the stat stages of the
Pokemon *arriving* (`BattleSystem_GetBattleMon`, `overlay_12_0224E4FC.c:75`), so Lugia's Def drop
is untouched by our switches and faints. Reviving to chase a third Screech buys ~2.1 points of
Smeargle risk for two turns of Magneton exposure: not worth it from -4, arguably worth it from
-2 or 0.

### 5.2 The one lethal hit, and why it is tolerable

**[measured]** Worst single hit is a **rain-boosted Hydro Pump crit at 172** against Smeargle's
153. `worst_incoming_hit` already enumerates reachable weathers and its docstring names this
exact case, so the danger floor is right.

* **In clear weather Smeargle survives everything** — Aeroblast crit is 147.
* **In rain**, 12 of the 16 rolls OHKO from full. Per-turn: ¼ × 0.80 × 1/16 × 12/16 = **0.94%**
  bare, and ¼ × 0.26 × 1/16 × 12/16 ≈ **0.30%** through Flash ×6.
* **[measured]** Over the whole setup: **P(Smeargle OHKO'd from full) ≈ 0.31%**, against
  P(faints at all) ≈ 2.07% — so the OHKO is a seventh of the risk and the rest is chip across two
  turns, which a Hyper Potion covers.

**[measured]** Rain is up on **~45% of turns** regardless of plan ordering. Rain Dance's 5 PP does
drain, but 5 × 5 turns is 25 turns of coverage against a 15-turn setup, so the drain shows up as
rain fading by Phase 2 rather than as dry weather during setup.

**Magneton resists both STAB moves and not the dangerous one.** Electric/Steel takes Extrasensory
and Aeroblast at 0.5× — **[rom: type chart]** — but **Water is neutral on both halves**; Steel
does not resist Water. With 50 base HP that makes Magneton the most exposed member to the only
move that threatens anyone: at Lv55 (137 HP) a rain Hydro Pump crit does 117-138 and KOs on the
top rolls. Right switch-in against two of three attacks, wrong one against the third.

## 6. Training

Real-world prerequisites, not work items.

**Magneton → Lv54, or Lv55 if Lv54 does not read 118.** **[measured]** Lugia is Speed 117.
Magneton's 107 at Lv49 pins `2·70 + IV + EV//4` to either 209 or 210, and they diverge exactly
here: 209 gives **117 at Lv54 — an exact tie** and 119 at Lv55; 210 gives 118 at Lv54. Lv55 clears
both.

A tie is worse than losing the race: `_we_move_first` compares with strict `>` and spends no
tie-break roll, so a tie is simulated as "Lugia moves first" with the wrong advance count — a
silent desync on the Thunder Wave turn. The race itself is optional (no Safeguard), so losing it
costs one Lugia attack; **tying costs the run.** Read the summary screen at Lv54 before relying
on it.

**Smeargle — optional.** **[measured]** Against SpA 93, using the worst end of the spread implied
by the fixture's 153 HP / 79 SpD at Lv58 (neutral nature; the Lv64 margin is 6 HP, so confirm it):

| Lv | HP | SpD | Extrasensory | crit | 3×Ex | Ex+crit | rain HP crit | |
|---|---|---|---|---|---|---|---|---|
| 58 | 153 | 79 | 58 | 117 | 174 | 175 | 172 | OHKO'd from full |
| **62** | 163 | 84 | 55 | 111 | 165 | 166 | 162 | no longer OHKO'd |
| **64** | 168 | 86 | 54 | 108 | **162** | **162** | 156 | survives 3 Extrasensories; out of crit range after one |

Both Lv64 conditions flip on the same level, which is why they felt close: "survive three
Extrasensories" and "not in crit range after taking one" are the same inequality to within 1 HP,
because a crit is almost exactly twice a normal hit. Lv62 is the cheaper milestone and closes the
only genuinely lethal hit. Neither is required — at three Screeches Smeargle takes exactly two
False Swipe turns — so this buys comfort and fewer heals, not feasibility.

## 7. Start advances: 6, and no longer in question

`notes/battle_compass_next_targets.md` §2 argued 6 was general rather than venue-specific. The
three `data/battle_logs/hooh*.jsonl` logs make it **four venues and four encounter kinds**:
Suicune (Bell Tower static), Metang (Safari Zone), Magikarp (Blackthorn) and Ho-Oh.

Lugia's script runs `PlayCry` / `NPCMsg` / `WaitCry` before `WildBattle` **[rom]**, which is a
different preamble from Suicune's — but it is text and audio and makes no RNG call. Treat 6 as
settled; a forced-seed Whirl Islands log is still `clayton-957.3`'s acceptance criterion, as a
confirmation to collect rather than a risk to retire first.
