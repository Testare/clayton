# Battle Compass — design document

Extending the compass/machete idea from the Safari Zone to **ordinary battles**: identify the
battle seed from what we observe in the fight, then steer the RNG until a specific ball
captures.

**v1 target: Suicune at the Bell Tower, caught in a Fast Ball.** Suicune's base Speed is 85,
under the Fast Ball's >=100 threshold, so the ball is a flat **x1** — the hardest multiplier
case, which is the point of the tool.

**Status:** design only, nothing implemented. Every claim below is tagged as one of:
**[verified]** (checked in this codebase or confirmed by the user), **[derived]** (computed
here from verified formulas), **[illustrative]** (a model whose shape matters but whose
constants need ground truth), or **[needs gdb]**.

---

## 1. Why this is tractable: we steer, we don't gamble

Two facts change the problem shape versus the Safari Zone.

**A static legendary cannot flee** [verified — user confirmed the static A-press encounter
generates Seed B]. In the Safari every turn carries a flee check, so the encounter is a race
and `chart` has to pre-target a capture-friendly seed before the run starts. Against Suicune
we have as many turns as our PP allows, so **we never need to hit a target seed** — we take
whatever seed we land on, identify it, and work from there. Battle Compass v1 therefore needs
no `chart` and no timer calibration.

**Capture windows are dense, and we can walk to them.** A capture needs four consecutive
shake rolls under a threshold `b`. At `b = 21845` (Suicune at 1 HP, paralyzed, x1 ball) each
stream position has a 1.234% chance of starting a valid four-roll window — so windows are
**roughly 1 per 79 RNG advances**, ~48 of them in a 4000-advance horizon [derived]:

| | windows per 4000 advances | first window offset | gap between windows |
|---|---|---|---|
| | mean 48.5 (min 24, max 87) | median 81 | median 36, mean 79 |

Because each turn advances the RNG by an amount that depends on **which action we choose**,
the action sequence is a steering wheel. The question is not *"will a capturing turn come
up?"* but *"can we arrange to arrive at a known-good window?"*

### 1.1 The single most important number in this document

Simulating BFS over RNG offsets against real LCRNG streams, varying only how many distinct
per-turn advance costs the player has available [illustrative cost model, robust conclusion]:

| Player's filler actions | Capture reachable within 40 turns | Median turns |
|---|---|---|
| **1 action** (one cost) | **36%** | 19 |
| **2 actions, costs differ by 1** | **95%** | 11 |
| 2 actions, costs differ by 2 | 97% | 11 |
| **3 actions** | **99%** | 8 |
| 4 actions | 98% | 8-9 |

**Going from one filler action to two nearly triples the success rate.** Three is
effectively a solved problem. The specific cost values barely matter; what matters is having
**at least two, preferably three, actions with distinct per-turn RNG costs.**

This retires most of the pessimism in earlier drafts of this note. A single-filler-action
player is doing a ~36% blind stall; a player with three filler actions captures in a median
of **8 turns**. At 8 turns, PP is not a constraint, survival is not a constraint, and
Suicune's Struggle deadline (§4.4) is not a constraint. **The RNG-manipulation vocabulary is
the whole game**, which is why §7's configuration model treats it as a hard requirement
rather than a nicety.

### 1.2 What this means for the pitch

Not "a known seed makes capture deterministic" (too strong — reachability can fail) and not
"~78% of encounters are winnable" (that was the one-filler-action case). The honest version:

> With an adequate action set, a Fast Ball Suicune is a **~98% proposition in under 40 turns,
> typically 8**, and in the rare unreachable case we find out *before throwing* and soft
> reset having spent nothing.

---

## 2. The two-phase workflow

Phase boundaries are load-bearing: they determine when balls may be thrown and when the
solver may run.

### Phase 1 — Setup: get Suicune to 1 HP and paralyzed

- Chip with False Swipe (or another non-KO damage source) until **exactly 1 HP**.
- Apply paralysis (Thunder Wave, 100% acc; Stun Spore at 75% for Ground types; or a Static
  contact ability) [verified: HGSS has no Electric-type paralysis immunity].
- **No ball throws in Phase 1.** See §2.3.
- Throughout, record observations and narrow the candidate seed set, exactly as
  `metronome_compass` does.

Phase 1 is also the identification phase, and it gets that for free: chipping ~142 HP down
to 1 takes several turns, and every one of those turns yields observables (§3). By the time
setup is complete the seed is usually already pinned.

### Phase 1.5 — Pin the seed (§15.3)

Sits between the two, at 1 HP and paralyzed, and exists because the seed is not guaranteed to be
pinned by the end of setup. The tool advises and the player acts; the objective is **maximum
information gain**, not minimum distance — a different policy from the solver's, over the same
simulator. This is also where accidental-capture risk peaks (§2.3), so §2.4's disclosure governs
any ball throw here.

### Phase 2 — Solve: steer the RNG to a capture window

- Preconditions the solver **asserts** (declared by the player, not inferred):
  1. target at exactly **1 HP**,
  2. target **paralyzed**,
  3. target's **max HP known**,
  4. **the active Pokémon is the one we intend to finish with.**

  The opponent's HP is never tracked beyond the binary in (1) — see §2.2. Criterion (4) is what
  lets the solver drop `SWITCH` from its action set entirely (§12.5): getting the right Pokémon
  in front is Phase 1's job, so the solver never has to weigh switching against using an item.
- If the seed is identified -> run the solver (§6), execute the returned action sequence,
  throw the Fast Ball on the indicated turn.
- If the seed is **not** identified -> §2.4's risk disclosure, then the player decides.
- **Reporting continues through Phase 2**, now in a *verification* role: every action is still
  reported, and whenever we take damage the resulting HP is checked against the prediction. A
  mismatch means either the damage model or the identified seed is wrong — see §2.5.

### 2.1 Two vocabularies: what the player reports vs what the solver chooses

These are deliberately different sizes, and conflating them would over-complicate both.

| | **Reporting alphabet** | **Solver action set** |
|---|---|---|
| Used in | Phase 1 **and** Phase 2 | Phase 2 only |
| Purpose | record what happened, narrow candidates, verify | choose what to do next |
| Switching | **yes**, with *which Pokémon* was switched to | **no** — excluded by precondition (4) |
| Items | **yes**, with *which item* was used | one `USE_ITEM`, resolved by tiering (§12.2) |
| Moves | any move the active Pokémon has | the same, as `USE_MOVE_1..4` |

In Phase 1 the player does whatever they judge best — any item, any switch, any legal move —
so the reporting grammar has to be **fully expressive**. The solver's vocabulary is deliberately
much narrower (§12.5), because every extra distinction multiplies the search for no gain.

None of §12.5's availability criteria apply to Phase 1. They constrain what the *solver* may
propose, not what the player may do.

### 2.2 Why 1 HP, precisely

Worth being exact here, because the obvious reason is wrong for this target.

For Suicune with a x1 ball, `a` is **2 for every curHP from 1 to 71**, and 1 above that
[derived]:

| Suicune's HP | base `a` | paralyzed (x1.5) | `b` | P/ball |
|---|---|---|---|---|
| 72-142 | 1 | 1 | 16643 | 0.416% |
| **1-71** | **2** | **3** | **21845** | **1.234%** |

So going below half HP buys **no additional catch rate at all** for this target — the catch
rate is identical at 71 HP and at 1 HP. But 1 HP is still the right requirement, for two
better reasons:

1. **1 HP is a fixed point, which keeps the action alphabet wide.** False Swipe cannot KO, so
   from 1 HP it leaves HP unchanged while still consuming its crit/damage/accuracy rolls.
   That makes damaging moves **usable as Phase 2 filler actions without perturbing `a`**. At
   71 HP every chip would shift HP and, in the general case, shift `b` — so Phase 2 would be
   restricted to non-damaging fillers. Given §1.1, protecting the size of the action set is
   worth more than anything else here.
2. **A known-exact HP is required for ball-shake filtering to be sound.** A shake count of 2
   means "rolls 1-2 were `< b`, roll 3 was `>= b`". Using that to eliminate candidate seeds is
   only valid if `b` is known exactly, and `b` depends on curHP. An HP *range* would make
   shake-based filtering **unsound**, not merely imprecise.

   Note what this does *not* require: **we never track the opponent's HP.** "At 1 HP" is a
   binary precondition the player declares at the phase boundary (§11.6), and from then on `b`
   is a single constant (21845). The solver does not run until that is true, so it never needs
   an opponent HP model — only the assertion. This is why §5's damage-dealt problem never
   reaches the critical path.

Additional benefit: at 1 HP with permanent paralysis the *target's* state is frozen — no HP
changes, no status changes, no weather that matters. The solver's state collapses to
`(RNG offset, our PP, our HP)`, which is why §6's search is cheap. Our HP is in there only
because of the heal policy (§11.2 item 4); the target contributes nothing.

Cost: at 1 HP, Suicune's first Struggle KOs it (§4.4). Accepted — a median of 8 turns means
the deadline is never approached.

### 2.3 Why no balls in Phase 1

A plain Poke Ball is **also x1 on Suicune**, exactly like the Fast Ball. So a practice throw
that succeeds catches Suicune *in the wrong ball* and the run is lost [derived]:

| State | per throw | over 20 throws |
|---|---|---|
| Full HP, no status | 0.416% | **8.0%** |
| 1 HP, paralyzed | 1.234% | **22.0%** |

Phase 1 ends with the target at its **most catchable** state, so throwing balls during setup
means accepting rising risk for information we mostly get free from moves. Hence the rule:
**no throws until setup is complete and the decision in §2.4 has been made explicitly.**

**This worry disappears once the seed is identified.** Capture requires all four rolls `< b`,
and the capture ball's `b` is never smaller than a plain Poké Ball's, so *the capture ball
failing implies the standard ball fails*. In Phase 2 with a known seed the solver can therefore
throw standard balls on turns it knows will fail — **zero risk, free observation and filler**
(§12.5). The risk is confined to throws made while the seed is still ambiguous.

### 2.4 Phase 2 with an unidentified seed: informed risk

If the candidate set is still ambiguous entering Phase 2, a ball throw is the most
information-dense observation available (it reads up to four rolls at once). The tool must
surface the trade rather than make it:

- **Risk**: the exact percentage of surviving candidates for which a thrown standard ball
  **captures**. Computed, not estimated — each candidate is a concrete seed.
- **Reward**: the full predicted **shake-count distribution** across candidates (e.g. "48% of
  candidates -> 0 shakes, 27% -> 1, 14% -> 2, 6% -> 3, **5% -> capture**"), plus how much each
  outcome would narrow the set.
- **Alternatives**: the same information-gain figure for every *move* available, so the player
  can see when a zero-risk observation is nearly as informative.

Then the player decides whether the information is worth the chance of catching Suicune in the
wrong ball and restarting from scratch. The tool's job is to make that a numerically informed
decision, not to make it for them.

### 2.5 Phase 2 verification: the desync detector

Because Phase 2 runs to a precomputed path, it also gives us a free correctness check. Each turn
we know what the player should do, which move Suicune should use, whether it should crit, and —
via §3.1 — **exactly how much damage we should take**. So on every reported turn:

- the action taken should match the prescribed path, and
- if we took damage, the resulting HP should match the prediction exactly.

A mismatch is unambiguous and important: either the identified seed is wrong, or the damage
model is wrong (§3.1's soundness risk made operational). Either way the correct response is to
**halt, warn, and re-identify or re-solve** — never to continue executing a path that reality
has already diverged from. This is the practical safety net behind enabling the damage filter at
all.

---

## 3. Observables — what narrows the candidate set

Same mechanism as `metronome_compass`: each turn produces tokens, and candidates whose
simulated tokens disagree with what the player saw are eliminated.

| Observable | Entropy | Notes |
|---|---|---|
| Suicune's move choice | 2 bits/turn, **decaying** | `roll % (moves with PP)`, indexing the surviving list (R4). Falls to 1.58 bits once Rain Dance's 5 PP is gone, then 1.00, then 0 |
| Our move's hit / crit / miss | ~1-2 bits | existing `hit_crit_or_miss` |
| Secondary-effect procs | varies | e.g. Body Slam's 30% paralysis roll |
| **Aurora Beam's 10% Attack drop** | ~0.5 bits | a free observable on its best attack |
| **Enemy prevented from moving** (25% full paralysis) | ~0.8 bits/turn | permanent once paralyzed — a recurring signal; needs its own token (§13.5) |
| **Exact damage we take** | **1.8-3.3 bits/hit** | The damage roll is 1 of 16 (85-100%). Because we know both sides' exact stats, observed HP loss pins it. **The single richest observable available** — see §3.1 |
| Ball shake count | up to 4 rolls | Phase 2 only, and only after §2.4 |

Suicune is unusually legible because half its moveset is non-damaging and it spends ~25% of its
turns unable to act.

**A note on move failure, corrected.** An earlier draft listed "Mist / Rain Dance failing when
already active" as a high-entropy *observable*. That was wrong on both counts. Whether those
moves fail is **fully determined by battle state**, not by a roll, so the simulator predicts it
rather than observing it — and it therefore contributes **no identification entropy of its own**.
Listing it was double-counting: the entropy lives in the move *choices* that produced the state,
which the `E1`-`E4` tokens already capture. The RNG *consequence* (a failed move skips its
post-success advances) is still modelled, from state.

### 3.1 Exact damage taken — the richest signal we have

Gen 4 multiplies damage by one of **16 rolls (85-100%)**. `context.py:hit_crit_or_miss`
currently spends that roll as `advance_unobservable()  # damage roll is not observable` — true
for the Metronome setup, where nobody's HP is tracked. **For Battle Compass it is observable**,
because we know Suicune's exact stats (RNG-manipulated IVs + nature) *and* our own party's
exact stats, so the damage we take is a pure function of the roll.

Measured for this fixture [derived]:

| Incoming move | base | distinct damage values | entropy |
|---|---|---|---|
| Aurora Beam | 29 | 6 (24-29) | **2.48 bits** |
| Aurora Beam, crit | 58 | 10 (49-58) | **3.25 bits** |
| Gust | 18 | 4 (15-18) | 1.81 bits |
| Gust, crit | 36 | 7 (30-36) | 2.73 bits |

Against the rest of a turn's signal:

| Per-turn observable | bits |
|---|---|
| Suicune's move choice (`roll % 4`) | 2.00 |
| crit or not (1/16) | 0.34 |
| Aurora Beam's 10% Attack drop | 0.47 |
| **exact damage taken** | **2.48** |
| *total without damage tracking* | *2.81 -> ~7x narrowing/turn* |
| **total with damage tracking** | **5.29 -> ~39x narrowing/turn** |

From ~2000 candidates that is **3 damaging turns instead of 4**. In turn count the gain is
modest, but the *reliability* gain is the point: Phase 1 runs ~8 turns of which roughly half
deal damage, so with damage tracking identification finishes comfortably inside Phase 1, while
without it the margin is thin. **That directly reduces how often §2.4's risky ball throws are
needed**, which is the expensive failure mode.

**We model incoming damage only — and only the opponent's attacking moves.** This is what
keeps the model tractable and, crucially, *verifiable*. For Suicune the entire surface is two
moves, **Aurora Beam and Gust**. That is small enough to validate exhaustively against ground
truth, and the same discipline scales: each newly supported opponent adds only its own
attacking moves, each verified as it is added. There is no general Gen 4 damage engine to get
right up front.

For this matchup, **no damage modifiers apply at all** [derived]:

| Possible modifier | Effect here |
|---|---|
| Rain (from Suicune's own Rain Dance) | none — rain boosts Water and weakens Fire; Ice and Flying are unaffected |
| Mist | protects Suicune's side only; no damage effect |
| Aurora Beam's 10% Attack drop | lowers **our Attack** -> affects damage we *deal*, not damage we *take* |
| Reflect / Light Screen | not in Suicune's moveset |
| Def/SpD stat stages on our side | nothing in Suicune's kit touches them |
| Damage-absorbing abilities | none on this party |

So the model reduces to: base power x SpA/SpD x type effectiveness x crit x roll. Screens,
weather, absorbing abilities and stat stages are **deferred** — real work, but not on the
critical path for the first target.

Two errors in earlier drafts of this document were caught by implementing
`claytonlib/battle/types.py` and `stats.py` — exactly the check sec 17.3 predicted:

- **Gust vs Magneton is x0.25, not x0.5.** Electric resists Flying *as well as* Steel, so the
  two resistances stack. Magneton takes even less than documented, so its survive-a-crit
  conclusion holds with more margin.
- **Suicune's Attack is 69, not 80.** A scratch script used base 90 (its Sp. Atk) for Attack.
  Harmless — all four of its moves are status or special, so its Attack is never read — but the
  table was wrong.

Incoming damage per party member. **Only one row is verified** — the rest are the model's own
output, and are here for the doc and the code to agree on rather than as measurements:

| Party member | HP | SpD | Aurora Beam | crit | Gust | crit | provenance |
|---|---|---|---|---|---|---|---|
| Magneton Lv30 (Steel x0.5 Ice, x0.25 Flying) | 79 | 56 | 16-19 | 33-39 | **5-6** | **10-12** | derived |
| Smeargle Lv60 (Normal, x1.0) | 154 | 77 | 24-29 | 49-58 | 15-18 | 30-36 | **Aurora Beam verified** |
| Mamoswine Lv90 (Ice/Ground, x1.0) | 325 | 140 | 12-16 | 26-32 | 9-11 | 18-22 | derived |

**Verified:** three Aurora Beams landed on Smeargle in `data/battle_logs/test1.jsonl` for 27, 26
and 24, every one of them reproduced exactly (§16.1). Nothing has ever been measured against
Magneton or Mamoswine, so those rows are predictions.

Mamoswine's row moved from 13-16 to 12-16 when type effectiveness was corrected to apply once
**per defender type** as the ROM does — Ice/Ground is `x0.5` then `x2`, and `DamageDivide`
truncates between them, which a single combined `x1.0` does not. The mechanism is ROM-verified;
the resulting Mamoswine figure is not.

Two figures here disagree with the log and should be re-entered from the summary screen: it
recorded Smeargle at **153** HP, not 154, and solving its three Aurora Beams for Sp. Def gives
**78-80** rather than 77.

Mamoswine still needs roughly **11 critical Aurora Beams** to fall, confirming its role as an
untouchable wall — a conclusion robust to a point either way.

**The soundness caveat is serious.** A damage filter that is wrong anywhere — modifier order, a
rounding step, a missed ability — **eliminates the true seed** and silently breaks the run.
That is strictly worse than not filtering at all. So:

- Each opponent's attacking moves must be **validated against ground truth before being
  trusted** (R10), as part of adding support for that opponent.
- It must **fail loudly**: "observed damage matches no candidate" is a warning and an offer to
  disable the damage filter, never a silently emptied candidate set.
- It should be **opt-in** per opponent until that opponent's moves have been confirmed on real
  runs.

**Damage we *deal* is not modelled at all**, to this or any precision. We only ever see the
opponent's HP bar, so there is nothing to filter on, and the solver never needs the number
(§2.2). The asymmetry is deliberate and it is what makes the whole model verifiable: exact
modelling only where the result is observable.

---

## 4. Mechanics reference

### 4.1 The general catch formula

`safari.py:__adjusted_catch_rate_b` already encodes the **Safari specialization** of
`GetShakeCount`, emulator-verified (a `/2` vs `/3` bug was fixed in `clayton-ctd.15`)
[verified]. The general form:

```
a = ((3*maxHP - 2*curHP) * catchRate * ballBonus) / (3*maxHP)   # ballBonus in /10 fixed point
a = a * statusBonus                                             # sleep|freeze x2; par|psn|brn x1.5
a = max(a, 1)
b = 0xFFFF0 / isqrt(isqrt(0xFF0000 / a))
capture iff all four (rand >> 16) < b
```

Safari hardcodes `ballBonus = 15` (Safari Ball x1.5) and the full-HP case. Generalizing needs
**curHP/maxHP**, **ballBonus**, and **statusBonus** — the first two trivial, the third a small
table. No Gen 5 critical-capture mechanic exists in Gen 4, so there is no extra branch.

Ball bonuses needed for v1: **Fast Ball** (x4 iff base Speed >= 100 — Suicune's 85 fails, so
x1) and **plain Poke Ball** (x1). The conditional and turn-count-dependent balls (Timer,
Quick, Dusk, Level, Heavy + weight table, Love, Moon, Net, Dive, Nest, Repeat) are deferred.

### 4.2 Why paralysis, not sleep

`NonVolatileStatus` is single-valued and `effects.py:_status_applier` refuses to apply a
second one [verified], so **paralysis and sleep are mutually exclusive** — Thunder Wave and
Spore are alternatives, not a combo. The choice:

| Route | `a` at 1 HP | P/ball | Maintenance |
|---|---|---|---|
| Sleep (Spore, x2) | 4 | 1.598% | re-Spore every 2-5 turns, forever |
| **Paralysis (Thunder Wave, x1.5)** | 3 | 1.234% | **none — one move, permanent** |

Paralysis is ~30% worse per ball and wins anyway:

1. **Zero upkeep.** One move, permanent. No re-application schedule, no window to land the
   throw inside, nothing to lapse at the wrong moment.
2. **It solves turn order.** Gen 4 paralysis cuts speed to **x0.25** [needs confirmation],
   taking Lv 40 Suicune's ~85 Speed to ~21 — so essentially anything outspeeds it. That means
   **no speed-tie rolls anywhere in the search**, which retires most of R3 and removes any
   need for a Lagging Tail (which would be actively harmful, guaranteeing we move last).
3. **~25% of its turns it cannot move at all** — free turns, and a recurring observable.
4. **It is the only permanent status that does not damage the target.** Toxic, poison and burn
   are also x1.5 and permanent, but they chip Suicune every turn and **will eventually kill
   it** — the one unrecoverable outcome. Freeze is x2 but thaws (20%/turn) and cannot be
   applied reliably. Sleep is harmless but temporary. Paralysis is the unique viable point.

**Decision: paralysis for v1. The sleep-route solver is deferred**, and can be added later as
a second solver over the same core.

### 4.3 Suicune's data

Lv 40, catch rate 3, ability **Pressure**, base Speed 85. Max HP **130 (0 HP IV) to 142 (31 HP
IV)** [derived] — and since the encounter is RNG-manipulated, we know which exactly.

Moveset **in slot order** [user] — the order matters, because the `E1`-`E4` tokens (§13.3) and
R4's surviving-list indexing both reference slots. `moves.json` confirms full PP data is present
[verified]:

| Slot | Move | PP | Power | Acc | Type | Effect | Notes |
|---|---|---|---|---|---|---|---|
| **1** | Rain Dance | **5** | — | — | Water | 136 | Harmless; rain does nothing for this moveset. **Exhausts first** (R4) |
| **2** | Gust | 35 | 40 | 100 | Flying | 149 | Weak special |
| **3** | Aurora Beam | 20 | 65 | 100 | Ice | 68 | Its best hit; 10% Attack drop |
| **4** | Mist | 30 | — | — | Ice | 46 | Blocks stat *drops* only — **does not block paralysis** |

Only **55 of its 90 PP are damaging moves**, and both are weak — so "a mon that can take a hit
or two" is an easy bar, and no Smeargle/Sketch plan is required. Critically, **nothing in its
moveset can end the battle** (no Roar/Whirlwind).

### 4.4 The Struggle deadline

Pressure doubles *our* PP consumption but **does not touch Suicune's own PP** [verified by
user]. It has 90 PP. Paralysis costs it ~25% of its turns (spending no PP), so:

> Suicune can act ~90 times across **~120 battle turns**, then must **Struggle**. Gen 4
> Struggle recoil is 1/4 max HP ~= 35, so **from 1 HP it dies to its first Struggle** — and we
> lose the legendary.

This is a real lose condition and the solver must treat Suicune's PP as a countdown. In
practice it is not binding (§1.1's median is 8 turns), but it gives the search a natural,
intrinsic horizon — see §6.3.

---

## 5. What we already have, and what is missing

`metronome_compass/` is structurally ~85% of a general Gen 4 battle simulator that happens to
be wired for one matchup.

| Asset | Where | Reusable? |
|---|---|---|
| LCRNG + seed<->datetime mapping | `safari.py`, `times.py` | Yes |
| Dual-mode sim (RNG-driven *and* interactive over one effect script) | `metronome_compass/context.py` | Yes — the crown jewel |
| **235 of 257 move effect IDs**, with verified advance counts | `metronome_compass/effects.py` (2,899 lines) | Yes |
| Accuracy / crit / multi-hit / secondary-proc roll ordering | `context.py:hit_crit_or_miss` | Yes |
| Hidden-duration status machinery | `context.py:roll_hidden_duration` | Only if the sleep route returns |
| Path-token grammar + candidate filtering loop | `metronome_compass/path.py`, `__init__.py` | Yes |
| Catch math (`GetShakeCount`, Safari path) | `safari.py` | Generalize per §4.1 |
| Straight-line per-candidate lookahead | `flee_flags.py` | Yes — closest analogue to §6 |
| Supported-species gating with warnings/hard errors | `metronome_species.py`, `metronome_abilities.py` | Yes — the pattern for §7 |
| Battle-RNG reverse-engineering notes | `notes/ss_rng/` | Yes |
| 1,024 passing tests | `tests/` | **The refactor safety net** |

### 5.1 The move-coverage gap is well-aimed at us

The 22 unimplemented effect IDs are exactly the moves Metronome cannot call — i.e. exactly what
a player-driven battle wants. For v1 we need only two:

| Effect | Move | Why |
|---|---|---|
| **111** | **Protect / Detect** (priority +3) | Cheapest filler, and the damage answer |
| **254** | **Struggle** | Needed for *us* on PP-out, and for Suicune's §4.4 deadline |

Everything else (Sketch 95, Sleep Talk 97, Endure 116, Counter 89, Thief 105, Focus Punch 170,
Mirror Move, Mimic, Metronome, Destiny Bond, Follow Me, Helping Hand, Trick, Assist, Snatch,
Feint, Me First, Copycat, Chatter) is out of v1 scope.

Already implemented and useful, because all are Metronome-callable [verified]: Thunder Wave,
Stun Spore, False Swipe, Body Slam, Substitute, Recycle, Seismic Toss.

### 5.2 Open questions needing ground truth

**R1 — Static encounter reseeds Seed B. RESOLVED: yes** [verified by user]. The residual is
that `calibration.py`'s `rtc_offset_seconds ~= 5.26 s` is fitted to the Sweet-Scent path and a
legendary's intro differs — **irrelevant for v1**, since §1 never pre-targets a seed.

**R2 — Battle-start advance count** [needs gdb]. `_BATTLE_START_ADVANCES = 6` is "4
bellShimmer + 2 ability" for the Blackthorn encounter. Suicune's battle intro differs, and
**Pressure** is an entry ability. One capture needed.

**R3 — Turn order** [mostly retired by §4.2]. Paralysis makes us faster than Suicune in every
realistic configuration, so no tie rolls. Still needed: priority brackets (Protect is +3;
`moves.json` has `priority`, `Move` does not expose it) and the exact Speed comparison. Since
the encounter is RNG-manipulated we know Suicune's **exact** Speed — a real asymmetry versus
`metronome_compass`, which must reason about a *range* of Magikarp speeds.

**R4 — Wild move selection. CONFIRMED** [verified on emulator]. It is **not** rejection
sampling. The game rolls `RANDOM % (number of *possible* moves)` and indexes into the list of moves
**that have not been eliminated**. So if Rain Dance (slot 1) is out of PP, the surviving list is
`[Gust, Aurora Beam, Mist]` and `roll % 3 == 1` selects **Aurora Beam** — the second survivor.

Consequences:

- **Exactly one roll per selection, always.** No variable RNG cost, which is simpler than the
  rejection-sampling model this document previously assumed.
- **The modulus shrinks as moves are exhausted**, so the move choice carries progressively less
  information: 2.00 bits at `%4`, 1.58 at `%3`, 1.00 at `%2`, and none once a single move remains.
- **Rain Dance runs dry first, after only 5 uses** (§4.3), so the drop to `%3` happens early rather
  than as a late-battle edge case.
- The same roll maps to *different* moves for candidates with different PP histories, which is a
  genuine source of discrimination rather than a complication.

**R5 — General `GetShakeCount`. RESOLVED from the ROM decompilation**, no emulator needed.
`BattleSystem_CalculateBallShakes` in `~/arch/pokeheartgold/src/battle/battle_command.c` is the
authority, and `claytonlib/battle/catch.py` is now a transcription of it. What it settled:

- **The arithmetic order floors twice**, not once — `((catchRate * ballMultiplier) / 10 * lostHp)
  / (3 * maxHp)`. The ROM's own comment flags this ("the CPU actually does the operations from
  left to right, causing weird rounding issues"). An earlier version of `catch.py` collapsed it
  into one division, which diverges for any ball multiplier that is not a multiple of 10.
- **Apricorn balls scale the catch *rate*** (then clamp to 1..255) rather than setting a ball
  multiplier, so they see diminishing returns on high-catch-rate species. Fast Ball is
  `catchRate *= 4` when base Speed >= 100, not a x4 multiplier.
- **`modifiedCatchRate >= 255` skips the shake rolls entirely** — a guaranteed catch.
- Standard multipliers confirmed as Ultra 20, Great 15, Poke 10, Safari 15 (all tenths), and the
  status bonuses as sleep/freeze x2, burn/paralysis/poison x1.5.
- Two ROM quirks recorded in `catch.py`: Fast Ball falls through into the Moon Ball case (a
  missing `break`), and Heavy Ball tests the catch rate where it meant to test the weight.

**R6 — Bag-action turn order and advance structure. LARGELY RESOLVED** [verified by user on
emulator]. Bag actions resolve before any move, so a successful capture ends the battle before
the opponent attacks. **Items and switches cost zero advances**; a ball's shake rolls are just
that turn's action rolls, following the **4 BeforeTurn rolls every turn already spends** (so
there is no ball-specific offset); **between-turn rolls and the opponent's post-attack-success
rolls still occur**, including on item turns. See §12.1. Still open: intra-bracket ordering of
item/ball/switch when it could matter.

**R7 — Per-action advance costs. MOSTLY RESOLVED** [verified + already in the codebase].
Items and switches are zero (R6); per-move counts are the verified values already in
`effects.py`, and **every move in this fixture has an implemented handler** (§12.1). What
remains: the between-turn count in this context, and confirmation that the existing per-move
counts hold outside the Metronome matchup. §1.1's requirement is satisfied — the alphabet spans
zero-cost (item/switch) through to multi-roll moves and the 1-4 roll ball.

**R8 — Paralysis constants. CONFIRMED** [verified on emulator]. Speed is divided by 4 and the
catch rate multiplied by 1.5, as assumed throughout. So a Lv 40 Suicune's 85 Speed becomes 21.

**R9 — Switch-in RNG cost. RESOLVED: zero** [verified by user on emulator]. A switch consumes
no additional advances (§12.1). `notes/ss_rng/switching_out.md`'s speed-tie worry does not apply
to §11's party (§11.4), so switching is a narrow, solved feature rather than the open-ended
problem that note describes.

**R10 — Exact incoming-damage calculation, per opponent move** [needs emulator]. Required by
§3.1, and deliberately narrow: for Suicune it is **Aurora Beam and Gust only**, correct to the
last integer, with no modifiers needed (§3.1's table). Each newly supported opponent adds and
validates only its own attacking moves. Unlike most unknowns here, an error is **unsound rather
than imprecise** — it discards the true seed — so validate on real runs before enabling the
filter for that opponent.

**Crit stat-stage rule. CONFIRMED, and broader than assumed** [verified]. A critical hit ignores
**every stat change that would reduce its damage** — the target's raised defences *and* the
attacker's lowered offences — while changes that would raise the damage still apply. An earlier
version of `damage.py` only ignored the defender's positive stages. The consequence for §12.3
stands and now generalises: X Sp. Def does not lower the crit-defined danger floor, and neither
does lowering the opponent's offence.

**Turn structure. CONFIRMED** [verified]. Recorded in `claytonlib/battle/turn.py`: 4 BeforeTurn,
then the first actor's action (bag 0, ball 1-4 shakes, or a move), +2 if that was a successful
move, 2 between-turn, the second actor's move, +2 if successful, 4 end-of-turn. The counts match
the values `metronome_compass` verified independently for Blackthorn, and a test asserts they stay
in agreement.

---

## 6. The solver

### 6.1 Not brute force — target the windows

Forward-searching every action sequence is the wrong shape. The efficient formulation inverts
it:

1. **Precompute capture windows.** Walk the identified seed's stream over the horizon and
   collect every offset `i` where `(rand[i+j] >> 16) < b` for `j = 0..3`. Cheap, and there are
   only ~50 per 4000 advances (§1).
2. **Use the windows to prune, not to define goals.** ~~A turn beginning at RNG offset `x`
   spends its 4 BeforeTurn rolls on `x..x+3`, so a ball thrown that turn has its shake rolls at
   `x+4..x+7`, and the goal set is `{ w - 4 : w in windows }`.~~ **[corrected — implementation]**
   That formula is an oversimplification. The shake rolls do follow the 4 BeforeTurn advances
   directly (the 4 is what every turn pays, **not** a ball-specific offset — §12.1 stands), but
   they also follow the wild mon's **move-selection roll**, which is spent at the top of the turn
   whether or not that mon ends up moving. So the arrival offset is `w - 5` when the target has a
   move with PP left and `w - 4` when it does not — state-dependent, and for a full-PP Suicune it
   is `w - 5` on every turn of the hunt.

   Rather than case-split the goal set, the implementation treats the window set as a **necessary
   condition only**: it prunes (no window anywhere in the horizon ⇒ no capture, a real proof of
   unreachability), and every actual throw is settled by running the simulator. "Windows prune;
   the simulator decides." See `battle.turn.shake_roll_offset`, whose `target_can_act` argument
   deliberately has no default.
3. **Solve reachability.** BFS/Dijkstra over nodes `(rng_offset, pp_state, our_hp)`, where choosing
   action `A` costs `overhead + cost(A) + cost(Suicune's move)`. Suicune's move is itself
   determined by the roll at the current offset, so **edge weights are position-dependent** — a
   DAG rather than a uniform-cost lattice, but still a plain shortest-path problem.
4. Return the shortest action sequence reaching any goal offset.

This is the algorithm §1.1's table was produced with. It is fast because the state space is
small (§2.2: at 1 HP + paralyzed the battle is nearly stateless) and because the horizon is
intrinsically bounded (§6.3).

**The Struggle deadline is enforced, not just noted [implementation].** The simulator does not
model Struggle at all — `select_target_move` returns no slot, so the turn spends no roll and deals
no damage, which would be silently wrong rather than visibly unsupported. And at 1 HP the recoil
kills the target outright, losing the legendary.

There are two mechanisms, and only one of them is exact:

* **Exact, per path.** A state whose target has no usable move is never expanded, because the
  next turn would be Struggle. The simulator tracks the target's PP along each path and a
  fully-paralyzed turn spends none, so this needs no estimate at all. This is what actually
  enforces the deadline.
* **An estimate, for sizing.** `struggle_deadline()` = `2.5 ×` the target's **remaining** PP
  (remaining, not total: by Phase 2 the identification turns have already spent some). It bounds
  the turn budget and the RNG horizon the window scan covers. 2.5 rather than 1.0 because every
  full-paralysis turn is free — 4/3 on average at a 25% rate, and more in practice because the
  solver can prefer paths that proc it.

**There is no provable turn bound on the battle.** Paralysis can extend it indefinitely, so no
finite budget covers every branch. Consequently the *search* can never prove a seed hopeless; it
can only report "no capture within the budget searched", which is what `Unreachable.proven` and
`searched_turns` say together. The one real proof available is the **window scan**: if no four
consecutive rolls fall under `b` anywhere in the horizon, no throw captures however you arrive.

### 6.0.1 Vector ms is a difference, not a position [corrected — implementation]

`candidates.centre` originally used `model.frame(M, low16)` as an **absolute** frame. It is not:
Vector ms is the gap between Seed A (the key seed) and Seed B, so

```
dF    = round(model.frame(M, base_low16) - base_low16)   # the pure frame difference
frame = seed_a_delay(key_seed, initial_time) + dF        # added onto Seed A's own delay
```

The absolute reading put every window a couple of hundred frames *below* the key seed's own
delay, so the "Seed B cannot precede Seed A" guard skipped all of them and no window ever held a
candidate. `app.metronome.seed_b_center` had always done this correctly; `centre` is now
cross-checked against it across seeds, years and vectors.

Two related corrections fell out:

* The floor for that guard is Seed A's delay **for the target year**, not `get_times()`'s
  year-2000 delay — they differ by `year - 2000`, and comparing against the wrong one rejects
  legitimate frames.
* The model is fitted over realistic countdowns. Extrapolating to a sub-second `M` gives a
  *negative* frame difference, which is how a Vector ms entered in seconds rather than
  milliseconds shows up. `why_empty()` names that case, because "120" for "120 seconds" is the
  mistake the unit invites.

### 6.1.1 A capture window is a target, not a reachable one

The distinction §6.1 step 2 now turns on, worth stating on its own because it is easy to misread
in the other direction. A window says four consecutive rolls under `b` sit at some RNG offset. It
says nothing about whether any legal action sequence arrives there holding a ball, under the
sustainability constraints, before the target runs out of PP.

Windows are *dense* — roughly one offset in 79 at `b = 21845` — so "windows exist" is nearly free
information. The two seeds out of 200 the solver could not crack had **63 and 56** windows
respectively, and reached none of them. A high window count alongside no path is the ordinary
outcome, not a contradiction, and `Unreachable.capture_windows` is documented as a count of
*targets* for exactly that reason.

**Measured [implementation].** §1.1's reachability table was built from an illustrative cost
model before any simulator existed. Re-measured against the real solver over 200 random seeds:

| | §1.1 predicted | measured |
|---|---|---|
| seeds solved within 40 turns | ~98–99% | **99.0%** (198/200) |
| median turns | ~8 | **6–7** |
| mean turns | — | 8.1–8.8 |
| worst | — | 36–37 |

Cumulative: 31% within 4 turns, 62% within 8, 92% within 16. The deadline of §6.3 never binds at
these counts. A representative solution, on a seed needing 9 turns:

```
M1hE3!HP103 M1hE2hHP086 M1hEpar M1hE4 M1!Epar M1hE4 M3E4 M2E3hHP060 C
```

One implementation note on performance. A plain Dijkstra over
`(rng_offset, pp, hp, stages)` took 47s and 97,139 states. Since **whether a throw captures
depends only on the RNG offset**, visiting each offset once at its cheapest arrival cuts that to
0.16s and 642 states — a 300× reduction, verified to return identical distances on six seeds.
It is a heuristic, though: reaching a *future* offset depends on PP and HP as well, so collapsing
can in principle discard a state that would have led somewhere cheaper. `SolverConfig.
collapse_offsets=False` runs the complete search, and only that search's exhaustion sets
`Unreachable.proven` — the window-based pruning proof of step 2 is sound either way.

### 6.2 Sustainability as hard constraints, not warnings

A path is only returned if it is actually executable. Reject any path that:

- exhausts **our** PP (Pressure-doubled) before the throw,
- lets our active Pokemon **faint** with no revive/heal available,
- crosses **Suicune's Struggle deadline** (§4.4), which kills the legendary.

Same philosophy as never wasting the ball, one level up: it does not make the battle easier, it
makes failure **cheap and knowable in advance**.

### 6.3 No `max_turns` parameter needed

Machete needs a depth limit because the Safari search can run away. Here the horizon is
intrinsic:

- Suicune's 90 PP caps the battle at **~120 turns** (§4.4).
- At a per-turn cost on the order of 10 advances, that is **~1,200-2,400 RNG offsets** total.
- A BFS over a few thousand offsets x a handful of actions is trivially small.

So the search can be **exhaustive over the real horizon** rather than heuristically truncated.
If it reports no solution, that is a genuine proof of unreachability for this seed — exactly
the signal needed to justify a soft reset. This is a meaningful improvement over machete's
"none found within `max_turns`", which cannot distinguish the two.

### 6.4 Multi-candidate mode

When the seed has not been pinned, `machete_jane`'s decision-tree-over-candidates pattern
applies: choose the action that is best across all surviving candidates, and feed the observed
outcome back as a filter. This is also the machinery behind §2.4's risk/reward disclosure.

---

## 7. Pre-configuration

Unlike the Safari tools — where player state is just a ball count — this solver cannot run
without a real model of what the player brought. This is a substantial piece of work in its own
right, and the natural home for the `metronome_species.py` / `metronome_abilities.py` gating
pattern (supported species, warnings vs hard errors).

**Party** — per Pokemon: species, level, **exact Speed stat** (turn order), max/current HP,
ability, gender, held item, status.

**Movesets** — per Pokemon, four moves with **current PP tracked per move**. PP is a live
budget and Pressure doubles the drain, so per-mon totals are not sufficient.

**Items** — the Fast Ball (the prize), spare Poke Balls, healing items, revives, and battle
items (X Defend, X Sp. Def, Guard Spec., ...), with counts and prices, because the solver spends
them and prices drive the §12.7 distance function.

**No PP restoration.** Ethers are hard to obtain and deliberately out of scope, so **PP is a
hard, non-renewable budget** for the whole battle. That is affordable because battle items give
~47 zero-RNG-cost turns (§12.4) — the solver leans on items for filler and spends move PP only
where it needs a move's particular advance cost.

**Target** — species, level, and **exact IVs and nature**, since the encounter is
RNG-manipulated. This removes an entire class of branching that `metronome_compass` must live
with.

**The action alphabet is a first-class requirement, not a convenience.** Per §1.1, the
configuration step should *validate* that the party offers **at least two, preferably three,
filler actions with distinct per-turn RNG advance costs**, and warn loudly if it does not — a
single-cost party is a 36% proposition rather than a 99% one. This is the highest-leverage
validation in the entire tool.

### 7.1 Data we do not have

- **Base stats.** `basedata/` has no base-stat table [verified]; needed for Speed and max HP.
  **Source: PokeAPI**, via a `one-offs/populate_base_stats.py` script following the existing
  `populate_moves.py` / `scrape_metronome_species.py` pattern. Store as
  `basedata/base_stats.json`.
- **Species weights** — only for Heavy Ball, which is deferred. PokeAPI again when needed.
- **Target data** — Suicune's level, catch rate, ability and moveset are known (§4.3), and its
  four moves are already in `moves.json` with PP. A general per-legendary table can wait.

---

## 8. Scope

**In:**
- Suicune at the Bell Tower, Fast Ball, paralysis route, two-phase workflow.
- **Basic switching, as a Phase 1 capability** — required by §11's strategy (lead a paralyzer,
  switch to the chipper, switch in a wall if the chipper faints and needs reviving). Speed ties
  are avoidable by construction (§11.4) and a switch costs zero advances (R9), so this is a
  narrow feature, not `switching_out.md`'s open-ended problem. **The solver never switches**
  (§12.5).
- Exact-1-HP captures with permanent paralysis.
- Mechanics validation on **Snorlax or Sudowoodo**, never on a one-shot legendary.

**Assumed player capability** (per the user):
- A Pokemon that can take a hit or two — an easy bar against Suicune (§4.3).
- Moves **with and without secondary effects**, giving a spread of per-turn advance costs. Now
  understood to be the single most important requirement (§1.1).
- A reliable paralysis source (Thunder Wave; Stun Spore or Static for Ground types).
- Plenty of spare Poke Balls for observation — subject to §2.3 and §2.4.
- Plenty of healing items and revives, so fainting is recoverable rather than terminal.

**Out of v1:**
- **The sleep-route solver** (§4.2) — a later second solver over the same core.
- **Roamers** (Raikou, Entei, Latias/Latios) — they flee at the end of turn 1, so there is no
  observation window at all. They would need chart-style pre-targeting: a genuinely different
  tool, not a variant of this one.
- Full damage simulation (§2.2 makes it unnecessary here), double battles, trainer AI,
  conditional/turn-count ball bonuses, and every target other than Suicune.
- Switching *as a solver-chosen branch* beyond the scripted uses in §11.6 — the solver may use
  the configured switches, but need not search over switch timing in v1.

---

## 9. Work breakdown

### Phase 0 — Ground truth
Mostly closed. Per §16.3 the rest does **not** block starting: the forced-seed emulator loop needs
the tool to exist, so the order is build with best-guess constants, then calibrate. These gate
*trusting* output, not writing it.

1. ~~R1: static encounters reseed Seed B~~ — **done**.
2. ~~R6/R7/R9: bag-action ordering, item/switch/ball costs, switch cost~~ — **done**: items and
   switches cost zero, a ball's shakes are ordinary action rolls after the standard 4 BeforeTurn
   rolls, and between-turn rolls still occur.
3. ~~R4: wild move selection~~ — **done**: `RANDOM % (moves with PP)` indexing the surviving list.
4. ~~R8: paralysis constants~~ — **done**: Speed / 4, catch rate x1.5.
5. ~~R5: general `GetShakeCount`~~ — **done from the ROM decompilation**, no emulator needed.
6. ~~Turn structure~~ — **done**, in `claytonlib/battle/turn.py`.
7. ~~Crit stat-stage rule~~ — **done**, and broader than assumed: a crit ignores every change that
   would reduce its damage, on either side.
8. **The forced-seed logging utility** (§16.1) — gdb writes a chosen battle seed, and a reader
   modelled on `utils/gdb-seed-reader.py` / `utils/verify_paths.py` logs the emulator side for
   diffing against tool output. The instrument for everything below.
9. **R2: battle-start advance count** for Suicune (Pressure on entry) and for a throwaway test
   species. `metronome_compass`'s 6 is "4 bellShimmer + 2 ability" for Blackthorn and will differ.
10. **R7 residual**: confirm `effects.py`'s per-move counts hold outside the Metronome matchup.
11. **R10: incoming damage for Aurora Beam and Gust** — all 16 rolls, crit and non-crit, against
    each party member's exact stats. Gates the §3.1 filter.

### Phase 1 — Shared core, built alongside (§15.2)
**Superseded:** earlier drafts made this a symmetric refactor of `effects.py`. Per §15.2 Battle
Compass is its own tool, so that refactor is **off the critical path** — which removes the largest
risk in the plan.

11. **Wire `data/move_paths.tsv` up as a golden-file snapshot test** (§14.1 item 1). Cheap, and it
    protects `metronome_compass` against any shared-code extraction that follows.
12. Create `claytonlib/battle/` and **move the genuinely generic pieces there**: the dual
    RNG/interactive `BattleContext`, and the path-token base classes. `metronome_compass` keeps
    working against them; it does not have to migrate further.
13. New shared modules: `stats.py` (derive stats from base/IV/nature/level), `types.py`
    (type-effectiveness chart), `damage.py` (Gen 4 damage, **incoming only**, §3.1), `catch.py`
    (generalized `GetShakeCount`, §4.1).
14. `battle_compass/` with its **own handlers for the nine moves the fixture needs** — Suicune's
    four plus our five — each **cross-validated against `metronome_compass`'s verified handler**
    (§15.2 option i).
15. Turn order: priority brackets (expose `Move.priority`), exact Speed comparison, the paralysis
    speed factor. Paralysis, not Lagging Tail, as the tie-avoidance (§4.2).

### Phase 2 — Battle mechanics
16. Per-move PP tracking + **Pressure** doubling our drain; **Struggle** (effect 254) for us,
    and Suicune's §4.4 deadline as a lose condition.
17. **Protect/Detect** (effect 111).
18. Generalized `GetShakeCount` (§4.1) with the **Fast Ball** base-Speed>=100 test and the plain
    Poke Ball.
19. Item use and **ball throw** as turn actions.
20. **Pressure** as an entry ability; **switching** as a Phase 1 turn action (zero-cost, R9).
21. `basedata/base_stats.json` + `one-offs/populate_base_stats.py` (PokeAPI).
22. The pre-configuration model (§7), including the **action-alphabet validation**.

### Phase 3 — Battle Compass (identification)
23. `battle_compass/` front-end: candidate generation, path tokens for the new observables (§3),
    interactive narrowing loop. Mirrors `metronome_compass/__init__.py`.
24. The **Phase 1 / 1.5 / 2 state machine** (§15.3), with the no-balls-in-Phase-1 rule enforced
    (§2.3) and a **player-declared** transition into Phase 1.5 (§11.6 step 5) — never inferred
    from a hit count.
25. **Incoming-damage filter** (§3.1): make the damage roll observable in `hit_crit_or_miss`,
    filter candidates on exact HP loss, with fail-loud behaviour and a per-opponent opt-in.
    Scope is **the opponent's attacking moves only** — for Suicune, Aurora Beam and Gust — each
    validated as its opponent is added (R10). No general damage engine.
26. **Heal policy** (§11.2 item 4): the danger-floor rule in both modes (worst-case-crit when
    unidentified, exact when identified), the capture carve-out, and the dynamic item
    recommendation — smallest item that clears the floor for the most demanding candidate.
27. §2.4's risk/reward disclosure: per-candidate capture percentage, predicted shake
    distribution, and information gain per available action.
28. Supported-species gating and target data for Suicune.
29. **Phase 1.5 multi-candidate action selection** (§15.3, §6.4): choose the action maximising
    expected candidate reduction, subject to not accidentally capturing and not fainting. A
    *different objective function* from the solver's, over the same simulator.
30. **Hard interlocks** (§11.7 item 9), each unrepresentable rather than merely discouraged:
    no Mamoswine attack (structural, §12.5), no ball in Phase 1, no solver run without exact
    HP, and no action that would KO the target.

### Phase 4 — The solver
31. Capture-window precomputation (§6.1 steps 1-2).
32. The **7-action model** (8 while statused) and the deterministic `USE_ITEM` tiering
    (§12.2, §12.5, §13.7).
33. Position-dependent search over `(rng_offset, active_mon, our_hp, stat stages, pp)` (§6.1
    steps 3-4), **Dijkstra over the §12.7 distance function** rather than BFS over turns, with
    memoisation on `rng_offset` and dominance pruning (§12.8). Exhaustive over the intrinsic
    horizon (§6.3).
34. Sustainability as hard constraints (§6.2).
35. **Item-assignment post-optimisation** along a solved path (§12.6/§12.9) — provably
    capture-safe, since item choice moves no RNG offsets.
36. **The §11 fixture as the primary test harness** — single-seed replay, the seed-uniqueness
    study, and the speed-tie assertions.

### Phase 5 — Workflow and UI
37. **Move party Pokémon onto the Profile** (§15.4.1), following the inline `metronome_users`
    precedent: species, level, entered stats, ability, moveset, max PP.
38. A **"Hunt"** configuration type alongside `Expedition` (§15.4) — the party chosen for this
    hunt, their **held items**, the target and its **IVs/nature**, and the capture ball. Config
    only; live battle state stays in Battle Compass.
39. **Undo**, built in from the start (§15.4.2) — as *two* operations: rewind-a-misreport, and
    accept-a-misplay-and-re-solve.
40. **Run records** saved for replay and verification (diagnostic only, not model calibration),
    as a third `list_runs` kind alongside `"metronome"` and `"safari"`.
41. A **Hunts tab** in `app/` + `app/web/index.html`, with `hunt_session.py` mirroring
    `metronome_session.py`'s background-thread question/answer pattern.

### Deliberately deferred
Sleep-route solver, full damage simulation, roamers, doubles, trainer AI, conditional ball
bonuses, and every target other than Suicune.

---

## 10. Risks

- **~~Phase 1 is the whole ballgame.~~ Retired by §15.2.** Battle Compass is its own tool, so the
  2,900-line symmetric refactor of `effects.py` is no longer a prerequisite. This was the largest
  risk in the plan and it is now optional future work.
- **Two divergent simulators** is the risk that replaces it. `effects.py`'s value is its verified
  advance counts, and a second implementation can drift from them. Mitigated by keeping v1's
  duplication tiny (**nine** move handlers, §15.2) and cross-validating each against the existing
  one — but the mitigation weakens as targets are added, which is when option (ii) becomes
  attractive.
- **§1.1's conclusion is model-shaped, not measured.** The cost model behind that table is
  illustrative. The *structural* claim (cost diversity -> near-certain reachability, single-digit
  turn counts) is robust to the constants, but the real numbers come from R7 and could reveal
  that the available actions share a cost. **Do R7 first.**
- **Verified advance counts are sacred.** Every number like `_BATTLE_START_ADVANCES = 6` came
  from emulator ground truth, not reasoning. New ones must too — the failure mode is a solver
  that is confidently off by one and wastes a legendary.
- **One-shot encounters punish bugs.** Validate on Snorlax/Sudowoodo, which cost nothing to
  re-encounter.
- **Accidental capture in the wrong ball** is the most likely way to lose a run that the tool
  itself could have prevented (§2.3/§2.4). Treat the Phase 1 no-throw rule as a hard interlock,
  not advice.
- **This sits on top of an unfinished migration.** The 59.8261 Hz frame-rate rework is still in
  flight across chart, compass and machete. Battle Compass v1 sidesteps it by not needing chart
  at all (§1), so it is *less* blocked on that migration than the Metang hunt.

---

## 11. Worked test case — the reference fixture

A concrete end-to-end scenario to build against, validate against, and regression-test with.
All damage/stat figures below are **[derived]** from Gen 4 formulas; the RNG advance costs are
still **[needs gdb]** (R7).

### 11.1 The scenario

**Target:** Suicune, Lv 40, **Bold** nature, perfect IVs, 0 EVs (wild). Verified by `claytonlib/battle/stats.py` and `tests/test_battle_stats.py`.

| Stat | HP | Atk | Def | SpA | SpD | Spe |
|---|---|---|---|---|---|---|
| | **142** | 69 | 119 | 89 | 109 | **85** (-> **21** paralyzed) |

**Party:**

| # | Pokemon | Lv | Speed | Ability / Item | Moves |
|---|---|---|---|---|---|
| 1 | **Magneton** | 30 | 47-56 | Sturdy | Thunder Wave |
| 2 | Smeargle | 60 | 160 | **Technician** + **Silk Scarf**, Atk ~65 | False Swipe, Mean Look, Sweet Scent, Spore |
| 3 | Mamoswine | 90 | — | — | *no usable moves* — Phase 1 insurance only (§11.2 item 5) |

**Strategy:** Magneton leads -> Thunder Wave -> switch to Smeargle -> False Swipe to 1 HP ->
heal as needed -> Phase 2 (with Smeargle active).

Smeargle's moveset is **fixed** — it is the user's general-purpose catching Smeargle and
cannot be re-Sketched for this hunt. Treat its four moves as a hard constraint.

### 11.2 Findings

**(1) Sturdy does not do what it does in later generations — but Magneton settles it.** In
Gen 4, **Sturdy only blocks OHKO moves** (Fissure, Horn Drill, Guillotine, Sheer Cold); the
"survive one hit from full HP" behaviour is **Gen 5 onwards**. What actually protects the lead
is **Steel resisting both Ice (Aurora Beam) and Flying (Gust)**, plus raw bulk.

A Lv 17 Magnemite (35-40 HP) survives a normal Aurora Beam only with good IVs and **dies to
any crit**. Evolving to **Lv 30 Magneton fixes this outright** [derived]:

| Magneton | HP | Aurora Beam | **crit Aurora Beam** | Gust | crit Gust |
|---|---|---|---|---|---|
| perfect IVs | 79 | 16-19 | **33-39** | 5-6 | 10-12 |
| 0 IVs | 70 | 19-23 | **39-46** | 6-7 | 12-14 |

**Magneton survives a critical Aurora Beam with room to spare, even at 0 IVs.** Turn 1 is no
longer a failure mode, and no Focus Sash is needed. It also fixes the speed margin (§11.4).

**(2) False Swipe damage — RESOLVED: Technician.** Smeargle's ability boosts moves of base
power <=60 by x1.5, and False Swipe is 40 BP, so it qualifies. That was the factor this
document was missing (along with STAB — Smeargle is Normal-type, so False Swipe gets x1.5 there
too). With Technician (40 -> 60 BP), STAB and Silk Scarf [derived]:

| Smeargle Atk | Damage | Hits to reach 1 HP from 142 |
|---|---|---|
| 60 | 25-30 | 5 best case, **6 guaranteed** |
| **65** | **28-34** | 5 best case, **6 guaranteed** |
| 70 | 30-36 | 4 best case, 5 guaranteed |
| *user's calculator: 25-31* | | 5 best case, **6 guaranteed** |

**Both ranges agree on the conclusion: 5 False Swipes can reach 1 HP, 6 guarantees it.** The
fixture's assumption is correct.

Note how sensitive the count is to the exact Attack stat — at Atk 65 a five-hit minimum-roll
run leaves Suicune on exactly **2 HP**, while Atk 70 would finish in 4. That sensitivity is
precisely why §11.6 step 5 watches the HP bar instead of counting hits.

**(3) PP is not a constraint, so Seismic Toss is unnecessary.** An earlier draft of this
document recommended Sketching Seismic Toss to conserve PP. **Retracted** — that was based on
the STAB-less 15-18 hit estimate. With False Swipe's 40 PP halved to 20 uses by Pressure:

| False Swipes used | PP consumed | Uses left for Phase 2 filler |
|---|---|---|
| 6 | 12 / 40 | **14** |
| 8 | 16 / 40 | 12 |
| 10 | 20 / 40 | 10 |

Even the pessimistic estimate leaves ample filler PP. Smeargle's moveset stays as it is.

**(4) The heal policy: configured, advisory in Phase 1, doctrine in Phase 2.**

**Correction first:** an earlier draft of this document claimed the heal bound "only works
because Smeargle outspeeds." That is wrong. **Healing items have priority over all moves** —
bag actions resolve before any Pokemon attacks — so the heal always lands before the incoming
hit regardless of speed. The bound holds for that reason, not because of the speed margin. (See
R6: ball throws sit in the same pre-move bracket, which is why a capture turn is also safe.)

**The policy is part of the configuration**, and it applies in both phases with different
force:

| | Phase 1 | Phase 2 (seed identified) |
|---|---|---|
| Who drives | **The player** | The solver |
| The policy is | a **recommendation** | **doctrine** — the solver plans to it |
| Constraints on the player | use only configured moves/Pokemon, and **report every action** | follow the returned path |

How the player reaches Phase 2 and identifies the seed is left to their judgment. The tool
observes, narrows and advises; it does not direct. Only once the seed is identified and Phase 2
begins does the solver take over and treat the policy as binding.

**The policy itself — heal when the active Pokemon is in danger of fainting, unless it can be
captured this turn.** This supersedes the earlier "3 hits, a crit counting as 2" rule, which
was a proxy for exactly this and is only needed as a fallback when no damage model is available.
Two modes, matching the two information states:

- **Seed not identified** — guard against the worst possible single hit: a max-roll critical.
  Heal whenever current HP is at or below that number [derived]:

  | Party member | HP | Worst single hit (crit Aurora Beam) | Heal at or below |
  |---|---|---|---|
  | Magneton Lv30 | 79 | 39 | 39 |
  | **Smeargle Lv60** | **154** | **58** | **58** |
  | Mamoswine Lv90 | 325 | 32 | 32 |

- **Seed identified** — the solver knows the next hit's move, crit and damage roll exactly, so
  "in danger" becomes exact: heal iff current HP <= the *actual* incoming damage. Far tighter
  than the worst-case bound, and it wastes no turns.

The **capture carve-out is safe** rather than a gamble: bag actions resolve before moves, so a
successful Fast Ball ends the battle before Suicune ever attacks. With the seed identified the
solver *knows* the throw captures, so declining to heal on that turn risks nothing.

**The heal is a floor, not a schedule.** This is the important consequence. Healing is also a
**filler action** in the alphabet (§11.5), so the solver may choose to heal more often than
safety requires when it wants an item-cost turn. A fixed "every 3 hits" schedule would constrain
the action sequence and hurt reachability (§1.1); a safety floor leaves the solver free. Against
the old rule, Smeargle absorbs ~96 HP before hitting the floor — roughly **4-5 hits instead of
3** — so the floor binds less often as well.

**Item choice is computed, not fixed.** The heal must clear the floor, not merely top up
[derived]:

| Smeargle at | Smallest sufficient item |
|---|---|
| 58 HP | Potion (+20) -> 78 |
| 40 HP | Potion (+20) -> 60 |
| 20 HP | Super Potion (+50) -> 70 |
| 10 HP | Super Potion (+50) -> 60 |

Per candidate seed, compute the worst case to the next healing opportunity and pick the
smallest item that guarantees safety; with several candidates alive, **recommend the item that
satisfies the most demanding one**. That conserves inventory when the seed is benign and
escalates only when it is not.

To confirm in R7: whether different items cost the same number of RNG advances. If they do —
likely — **item choice is RNG-neutral** and the recommendation can optimise purely for safety
without perturbing a planned path. If they differ, item tier becomes another alphabet entry,
which is no bad thing.

**Magneton is exempt.** Its policy is simply *switch out once Thunder Wave has landed*, which
needs no modelling — the player knows it, and would rightly ignore a directive to heal a
Pokemon they are about to withdraw.

**(5) Mamoswine is Phase 1 insurance, and its empty moveset is handled structurally.** Its
role is narrow: if Smeargle somehow faints during Phase 1, Mamoswine holds the field while
Smeargle is revived and brought back. It is not a Phase 2 tank — Phase 2 begins with Smeargle
active and the solver never switches (§12.5).

The hazard is that a Pokémon with **no usable moves is forced to Struggle**, and a Lv 90
Struggle would annihilate a 1-HP Suicune. This needs no special-casing: §12.5's rule that *a
move slot the active Pokémon does not have is not an action* means the solver can never emit a
Mamoswine attack at all. The interlock falls out of the same rule that handles empty move slots.

### 11.3 Switching moves into v1 scope

This strategy **requires** switching — Magneton to Smeargle after Thunder Wave, and Smeargle
out to Mamoswine if Smeargle faints and needs reviving. §8 had deferred switching; that deferral
is superseded: **basic switching is in v1 scope, as a Phase 1 capability.** The solver itself
never switches (§12.5).

The good news is that `notes/ss_rng/switching_out.md`'s central worry — speed ties on
switch-in — does not apply to this party (§11.4). The RNG cost of a switch is still unmeasured;
see R9.

### 11.4 Speed margins

No speed ties are permitted; each one costs extra RNG rolls (`notes/ss_rng/speed.md`).

| Matchup | Margin | Verdict |
|---|---|---|
| Smeargle 160 vs Suicune 85 | +75 | safe |
| Smeargle 160 vs Suicune 21 (paralyzed) | +139 | safe |
| Magneton 47-56 vs Suicune 85 | -29 to -38 | always second — expected, and survivable per (1) |
| **Magneton 47-56 vs Suicune 21 (paralyzed)** | **+26 to +35** | safe |

The Lv 17 Magnemite this fixture originally specified had a **+1** margin against a paralyzed
Suicune (22 vs 21) — one point from a tie, and two from a reversal. Magneton removes that
entirely. The config validation in §7 should still assert non-tie for every (party mon x target
status) pair and flag margins of <=2 as fragile; this is exactly the class of bug that silently
desynchronises a solver.

### 11.5 The action alphabet — this party passes

Per §1.1 this is what decides success. Smeargle's fixed moveset yields an unusually good
spread, because three of its four moves **fail** in predictable circumstances — and a failed
move has a different RNG cost than a successful one:

| Action | Distinct costs | Note |
|---|---|---|
| False Swipe | 1 | crit + damage + accuracy; **HP-neutral at 1 HP** (§2.2), so usable throughout Phase 2 |
| Spore | 1 | **always fails** post-paralysis (statuses are exclusive, §4.2) — dead as a status move, alive as a filler |
| Sweet Scent | 2 | lowers evasion; **fails at -6** after 6 uses |
| Mean Look | 2 | succeeds once, fails thereafter (otherwise pointless — Suicune cannot flee) |
| Item (any) | **0 rolls** [verified] | the cheapest action in the alphabet; heal turns are **schedulable, not reactive**, and the safety floor is a minimum — the solver may add more as filler (§11.2 item 4) |
| Switch | **0 rolls** [verified] | **Phase 1 only** — the solver excludes it (§12.5). Part of the reporting alphabet, with the target Pokémon recorded (§2.1) |
| Poke Ball | 1-4 | variable by shake count, after the 4 start-of-turn rolls; **zero-risk in Phase 2** (§12.5) |

That is plausibly **4-6 distinct per-turn costs**, comfortably past §1.1's three-action
threshold (~99% reachable, median ~8 turns). **This party is well chosen for the job**, and for
a reason the strategy did not state: its value lies in the *failure modes* of its moves, not
their effects. The fixed moveset is not a limitation here.

One subtlety: **Sweet Scent erodes observability.** At -6 evasion, False Swipe's effective
accuracy is capped and the hit roll always passes — the roll is still consumed (so the RNG cost
is unchanged) but the hit/miss *observable* is lost. Good for determinism, mildly bad for
identification. Prefer Sweet Scent as a Phase 2 filler; avoid it during Phase 1.

### 11.6 Strategy as modelled

1. Lead **Magneton** (Lv 30). It moves second and survives whatever Suicune opens with,
   including a crit.
2. **Thunder Wave** -> paralysis, permanent (§4.2). Suicune's Speed drops to 21.
3. **Switch to Smeargle** (R9). It outspeeds by +139 from here on.
4. **False Swipe until Suicune is at 1 HP.** Nominally 6 (5 can suffice — §11.2 item 2), but
   see step 5: the count is a *testing* convenience, not the operational rule.
5. **The phase transition is player-declared, not computed.** In a real run the player simply
   says when Suicune has reached 1 HP, and Phase 2 begins. Hit counts exist only so the
   fixture can simulate a run end-to-end.

   This matters because a fixed count is genuinely unreliable: **Aurora Beam's 10% Attack drop
   lands on Smeargle**, reducing False Swipe damage, so some runs need more than 6. Rather than
   model that, the tool doesn't need to know — the player does, from the HP bar.
6. **Phase 2 begins** at exactly 1 HP + paralyzed. The seed should already be identified from
   steps 1-5 (~8 turns of observables, §3); if not, §2.4's risk disclosure governs whether to
   throw a spare ball.
7. Run the solver (§6) over Smeargle's filler alphabet and throw the Fast Ball on the indicated
   turn. No switching is involved — Phase 2 begins with Smeargle already active, and the solver
   never switches (§12.5).

**Standing rule, in force across both phases (§11.2 item 4):** heal the active Pokemon when it
is in danger of fainting — HP at or below the worst possible single hit (58 for Smeargle) while
the seed is unknown, or at or below the *exact* incoming damage once it is identified — **unless
Suicune can be captured this turn**, since the ball resolves first. It is a recommendation in
Phase 1 and doctrine in Phase 2, and it is a safety *floor*: the solver may heal more often when
it wants an item-cost filler turn.

### 11.7 What this fixture lets us test

The user's two, plus additions:

1. **Single-seed end-to-end replay.** Fix a battle seed, simulate the whole strategy, and
   assert the solver finds a capture. The core correctness test.
2. **Seed-uniqueness study.** Run the Phase 1 observation sequence across a range of candidate
   seeds and count how many remain indistinguishable at the Phase 1/2 boundary. Directly
   measures whether ~8 setup turns identify the seed, or whether we routinely enter Phase 2
   ambiguous — i.e. whether §2.4's risk disclosure is a hot path or a rare fallback.
3. **Action-alphabet measurement (highest value).** Once R7 lands, measure the *actual*
   distinct per-turn costs this party produces and re-run §1.1's table with real numbers
   instead of the illustrative model. The single test that confirms or refutes this document's
   headline claim.
4. **Solver success rate and turn count** across many seeds with this exact alphabet — the real
   version of §1.1.
5. **Incoming-damage validation for Aurora Beam and Gust** (R10) — the only two moves the
   damage model needs for this target. Exhaustive: all 16 damage rolls, crit and non-crit,
   against each party member's exact stats. This is the gating test for enabling the §3.1
   filter on Suicune.
6. **PP feasibility**: confirm False Swipe's Pressure-halved 20 uses comfortably cover Phase 1
   plus Phase 2 filler under both damage estimates.
7. **Heal-policy simulation (§11.2 item 4):** that the danger floor is never breached in
   either mode — worst-case-crit while the seed is unknown, exact incoming damage once it is
   identified; that the capture carve-out never costs a run; that heal turns are correctly
   *pre-scheduled* from the seed rather than reacted to; and that an off-script heal triggers a
   re-solve rather than silently invalidating the path.
8. **Speed-tie assertions:** encode §11.4's table as a test — including the superseded Lv 17
   Magnemite +1 case as a regression fixture, so a future config change that reintroduces a
   near-tie fails loudly.
9. **Hard-interlock tests** — each should be *impossible to express*, not merely unlikely: a
   Mamoswine Struggle, a ball thrown in Phase 1, the solver running without exact HP, and any
   action that would KO the target.
10. **Damage-filter soundness (§3.1).** The critical one: replay real runs and assert the true
    seed is *never* eliminated by the incoming-damage filter. Also assert the fail-loud path —
    a damage observation matching no candidate must warn and offer to disable the filter, not
    silently empty the set. And measure the real narrowing rate against §3.1's ~39x/turn.
11. **Dynamic heal recommendation:** that the recommended item always *clears the floor* rather
    than merely topping up, for every surviving candidate — and that it degrades to the
    worst-case-crit bound when the damage filter is disabled (§11.2 item 4).
12. **Regression corpus.** Record real attempts turn-by-turn and replay them as fixtures, as
    the project already does with `data/compass_runs.jsonl` and `metronome_seeds/`. A real run
    that desynchronises from the simulation is the highest-value bug report available.
13. **Struggle-deadline test:** an artificial seed where no capture window is reachable within
    Suicune's ~120-turn PP budget, asserting the solver reports *proven unreachable* (§6.3)
    rather than timing out.

---

## 12. Solver action model and item doctrine

Built on emulator findings **[verified by user]** that settle several previously open questions.

### 12.1 What the emulator confirmed

1. **Switching, potions and battle items consume no RNG advances of their own.**
2. **A ball's shake rolls are simply that turn's action rolls.** They follow the **4 BeforeTurn
   rolls that every turn already spends** — those are *not* extra rolls added for the ball.
   There is therefore **no ball-specific `PRE_BALL` constant**; the ball is just an action
   costing 1-4 rolls, early-exiting on failure. (`safari.py:throw_ball` has the same shape: 4
   BeforeTurn advances, then shakes.)
3. **Between-turn rolls still occur** on every turn, including item and ball turns — and so do
   **the opponent's post-attack-success rolls**, even on turns where we only use an item.

This makes the per-turn cost model concrete:

```
turn cost = 4 (before-turn/quick-claw)
          + our action's rolls      # item/switch 0; ball 1-4 (early exit); move varies
          + Suicune's move rolls    # determined by its move choice, which is itself a roll
          + between-turn rolls
```

**R7 is largely answered already.** Per-move advance counts live in `effects.py` with verified
values, and **every move in this fixture has an implemented effect handler** [verified]:

| Side | Move | Effect ID | |
|---|---|---|---|
| Suicune | Rain Dance / Mist / Gust / Aurora Beam | 136 / 46 / 149 / 68 | all implemented |
| Ours | False Swipe / Mean Look / Sweet Scent / Spore / Thunder Wave | 101 / 106 / 24 / 1 / 67 | all implemented |

What remains for R7 is the between-turn count in this context and confirmation that the
existing per-move counts hold outside the Metronome matchup. **R9 (switch cost) is answered:
zero.** R6 is answered except for intra-bracket ordering.

### 12.2 One `USE_ITEM` action, resolved deterministically

Since **all items cost zero RNG advances**, no two item choices differ in their effect on the
RNG trajectory. Branching on *which* item to use would multiply the search for no reachability
benefit — and, as the user notes, would be miserable to follow at the table. So the solver
exposes a single `USE_ITEM` action and a **deterministic priority tiering** decides what it
resolves to:

1. **Fully heal** if the active Pokémon would otherwise faint this turn. Expensive, but a full
   heal buys flexibility — a small potion often forces another heal next turn. *Skip this tier
   only if an X Defend / X Sp. Def would itself prevent the faint; then do that cheaper thing.*
   **Nothing mitigates a critical hit** (§12.3), so if the incoming hit is a crit that would KO,
   a fully-healing item is the only option.
2. **X Defend / X Sp. Def** against the most currently-dangerous move — compared on
   **non-crit damage**, since crits ignore these stages entirely. Only the relevant one if the
   opponent is purely physical or purely special; for Suicune, **X Sp. Def**. If that stat is
   already at +6, fall through.
3. **A plain potion** if not at full HP — the cheapest useful option.
4. **Remaining battle items, cheapest first** — Guard Spec. included, with no special treatment
   (§12.3).
5. **Everything else, cheapest first.**

### 12.3 Two corrections to the tiering

**Guard Spec. does not prevent critical hits.** In Gen 4 it prevents **stat reduction** for 5
turns — it is the item form of Mist. There is no crit-prevention item in Gen 4; the only crit
blocker is **Lucky Chant**, a move, which is not in this Smeargle's fixed moveset. Against
Suicune, Guard Spec's real effect is blocking **Aurora Beam's 10% Attack drop** — which matters
little in Phase 2, since Suicune is at 1 HP and False Swipe cannot KO, so our Attack is
irrelevant. So it takes **no special handling at all**: it sits in tier 4 with the other battle items,
ordered purely by cost.

**X Sp. Def does not lower the danger floor.** In Gen 4, **critical hits ignore the defender's
positive Defense/Sp. Def stages.** So boosting Sp. Def cuts chip damage substantially but
leaves the worst single hit untouched [derived]:

| Sp. Def stage | effective SpD | Aurora Beam | **crit** | Turns of chip before reaching the 58 floor |
|---|---|---|---|---|
| +0 | 77 | 24-29 | **49-58** | 3.3 |
| +2 | 154 | 12-15 | **49-58** | 6.4 |
| +4 | 231 | 9-11 | **49-58** | 8.7 |
| +6 | 308 | 6-8 | **49-58** | 12.0 |

So the user's core claim holds and is substantial — **chip damage falls ~3.6x and turns between
heals rise from ~3 to ~12** — but the crit-defined danger floor stays at 58 at every stage. With
the seed identified this matters less than it sounds: the solver knows whether the next hit is a
crit, so it can run Smeargle far below 58 on turns where no crit is coming, and only respects
the 58 bound while the seed is unknown.

### 12.4 Item supply is not a constraint

Six X items x 6 stages = 36 uses, plus Dire Hit once = **37**, with Guard Spec. reusable every 5
turns. The user's cycle (Guard Spec, then 4 X items, repeat) gives **~47 consecutive item
turns** — confirmed [derived]. Against a median solve of ~8 turns (§1.1), supply is a non-issue,
so the tiering can afford to be conservative.

### 12.5 The action set

**Seven** actions, and often far fewer. `SWITCH` is deliberately absent: Phase 2's precondition
(4) guarantees the right Pokémon is already active (§2 / §2.1), so the solver never weighs
switching against using an item.

| Action | Available when |
|---|---|
| `THROW_CAPTURE_BALL` | it would succeed |
| `USE_MOVE_1..4` | the active Pokémon **has** that move, it has PP, capture would fail, and we would not faint this turn |
| `THROW_STANDARD_BALL` | capture would fail, and we would not faint this turn |
| `USE_ITEM` | capture would fail, and the tiering yields an applicable item |

Notes:

- **A move slot the active Pokémon does not have is simply not an action.** Magneton with only
  Thunder Wave offers `USE_MOVE_1` alone; Mamoswine with no usable moves offers **none**. This
  is a solver criterion in Phase 2 and a plain limitation in Phase 1.
- **This makes the Mamoswine-Struggle interlock structural rather than special-cased.** If no
  move exists, no move action exists, so the solver can never emit one — §11.2 item 5's hazard
  is handled by the same rule that handles empty move slots, with no extra machinery.
- **The standard ball is provably safe here, and generally.** Capture requires all four rolls
  `< b`, and the capture ball's `b` is never smaller than a plain Poké Ball's, so *the capture
  ball failing implies the standard ball fails*. In Phase 2 with the seed identified, standard
  balls are **zero-risk** observation and filler — which retires §2.3's accidental-capture worry
  for Phase 2. It still applies while the seed is unknown (§2.4).
- **If the capture would succeed, it is the only action considered.** Bag actions resolve before
  moves, so the ball lands before Suicune can attack — the capture turn is never lost to
  fainting.
- **If we would faint and only an item prevents it, `USE_ITEM` is the only action** — the
  branching factor collapses to 1.

### 12.6 The ordering problem — and why it decomposes

The open question was: defensive boosts are worth more used early, so a depth-first search may
return a feasible-but-expensive path. There is a clean answer, and it falls out of §12.1's
first finding.

> **Because items and switches consume zero RNG advances, the RNG trajectory depends only on
> the sequence of action *types* — never on which item was used.**

So the problem separates:

1. **Solve for reachability** using the conservative (safest, most expensive) item doctrine,
   which maximises the set of feasible paths. Output: a capture path, with certain turns marked
   as item turns.
2. **Post-optimise the item assignment** along that now-fixed path — downgrade items wherever
   safety still holds.

**Step 2 cannot invalidate the capture.** Swapping a Hyper Potion for a Potion changes no RNG
offsets, so the capture turn stays exactly where it was; the only thing that can break is
fainting, which the optimiser checks by direct simulation. That makes the two-step approach
*provably* safe rather than merely heuristic — and it is exactly the "go over it afterwards and
replace item uses with cheaper ones" the user proposed.

Two refinements worth having:

- **If you want the cheapest path directly, use Dijkstra rather than BFS**, with edge weight =
  item cost instead of 1-per-turn. Early X Defends are then preferred automatically whenever
  they pay for themselves. This requires the search state to carry defensive stat stages and
  HP, so that a later heal's cost reflects boosts taken earlier: `(rng_offset, our_hp,
  def_stages, pp, active_mon)`. Stages are bounded (0-6) and the horizon is short, so this stays
  tractable.
- **The tiering already front-loads the defensive items** — X Defend / X Sp. Def rank above
  plain potions — so much of the ordering concern is handled by doctrine before the search ever
  sees it.

### 12.7 The distance function: trading turns against money

Plain BFS minimises **turns** and will happily burn a Full Restore to save one. Plain
cost-Dijkstra minimises **money** and will happily play 40 extra turns to save ₽200. Neither is
what a player wants. The fix is a single scalar that prices both:

```
distance(action) = BASE + floor(cost_in_pokedollars / DIVISOR)

BASE = 15, DIVISOR = 50        # both tunable; distance stays an integer
```

Every action costs at least `BASE`, so turns are never free; item cost is added on top. The
ratio sets the exchange rate: with these defaults, **one turn is worth up to ₽750**.

| Action | ₽ | distance | vs a free turn |
|---|---|---|---|
| Any free action (move, switch) | 0 | **15** | 1.0x |
| Poké Ball | 200 | 19 | 1.3x — marginally worse than free |
| Potion | 300 | 21 | 1.4x |
| X Defend / X Sp. Def | 350 | 22 | 1.5x |
| Guard Spec. | 700 | 29 | 1.9x |
| Hyper Potion | 1500 | 45 | **3.0x** |
| Full Restore | 3000 | 75 | 5.0x |

*(Prices are placeholders — fill the real HGSS table in with the base-stat data.)*

The behaviour this produces is exactly the intent:

- **2x X Defend = 44 beats 3 free turns = 45**, so the solver will spend on defensive boosts
  when they save even a little time — and they pay for themselves again later by deferring
  Hyper Potions.
- **A Poké Ball costs barely more than a free turn**, so standard balls stay attractive as
  filler (and in Phase 2 they are zero-risk, §12.5).
- **A Hyper Potion costs exactly 3 turns**, so the solver reaches for one only when it genuinely
  cannot spend three cheap turns instead.

Run **Dijkstra over this distance** rather than BFS over turn count. Edge weights are
state-dependent (the tiering decides which item `USE_ITEM` resolves to, and that depends on HP
and stat stages) — which Dijkstra handles fine, since weights need only be non-negative and
determined by `(state, action)`.

### 12.8 Keeping the search tractable

Cost-weighted search needs a richer state than pure reachability did:

```
(rng_offset, active_mon, our_hp, def_stage, spdef_stage, pp_per_move, items_used)
```

Most of that is bounded — stages are 0-6, the horizon is ~120 turns — but the product is large
enough that a naive search blows up on hard seeds (the median 8-turn solve is fine; a 40-turn
one is not). Two standard mitigations, both worth building in from the start:

- **Memoise on `rng_offset`.** It increases monotonically and is the dominant coordinate, so it
  makes a natural primary key.
- **Dominance pruning.** Among states sharing an `rng_offset`, discard any state that is
  dominated by another: no more HP, no better stat stages, no more PP, and no lower accumulated
  distance. This collapses the combinatorial fan-out dramatically, because most action orderings
  converge on comparable states.

### 12.9 How the three optimisation layers fit together

They are not redundant; each handles something the others cannot:

1. **The tiering (§12.2)** makes `USE_ITEM` a *single* action with a well-defined cost. Without
   it the branching factor would multiply by the item list for no reachability gain.
2. **Dijkstra over distance (§12.7)** chooses *when* to spend item turns, trading turns against
   money on one scale.
3. **Post-optimisation (§12.6)** relaxes the tiering after the fact — downgrading items wherever
   safety still holds. This remains valuable even with Dijkstra, because the tiering is fixed
   doctrine and can be locally over-conservative. And it is **provably capture-safe**: item
   choice moves no RNG offsets, so the capture turn cannot shift; only fainting needs
   re-checking, by direct simulation.

---

## 13. The reporting grammar

Design is the user's; this section records it with the fixes noted below. It follows
`metronome_compass`: a string of tokens, **spaces separating turns**, tokens concatenated with
no delimiter inside a turn.

### 12.10 The interview must offer exactly what the simulator can emit [implementation]

Stated as an invariant because three separate bugs were the same violation of it, and each looked
like a wrong model constant rather than a UI fault:

* Every prevention marker was offered regardless of state, so an unparalyzed Magneton could be
  reported as fully paralyzed.
* `M`-then-`E` was emitted unconditionally, so a turn a faster target opened rendered backwards.
* Spore against an already-paralyzed Suicune renders as the **bare** slot token — statuses are
  mutually exclusive, so it rolls accuracy and then fails — but "Missed / failed" was offered,
  and a truthful report produced `M4-`, matching nothing.

Offer a **superset** and the player can report something impossible; offer a **subset** and a real
turn becomes unreportable. Both are tested directly, by comparing the offered outcome set against
what the simulator emits over a few hundred seeds.

A related trap: `can_miss` is a property of the **situation**, not the move. Accuracy 0 bypasses
the check and accuracy 100 always passes it, so Spore and False Swipe cannot miss — *until* our
accuracy is dropped or the target's evasion is raised. The check uses the net of the attacker's
accuracy stage and the defender's evasion stage, and `accuracy_net_stage` exists so the simulator
and the interview cannot disagree about it.

### 12.11 Abilities and held items are part of the damage model [implementation]

`damage.py` originally declared itself one-directional — "damage we deal is never modelled" — but
`sim.execute_move` used it for both actors, so the target's HP was computed by a model that did
not claim to support the direction it was being used in. Smeargle's False Swipe came out at base
power 40 instead of 72, under-damaging by ~1.7×, which showed up as a wrong HP bar and would have
blocked Phase 2: `solver_blockers` gates on the *simulated* target HP reaching 1.

Order and arithmetic are transcribed from the ROM (`src/battle/overlay_12_0224E4FC.c`):

```
Technician:           power = power * 15 / 10     when power <= 60
type-enhancing item:  power = power * (100 + mod) / 100
```

both integer division, **Technician first**. For a Technician user holding Silk Scarf, False Swipe
is `40 -> 60 -> 72`. The ×1.2 magnitude is the documented Gen 4 value; unlike the ordering it was
not read out of the source, because item modifiers live in a binary NARC.

Reading that code also turned up a latent bug of its own: the ROM's level term is `((level * 2 /
5) + 2)` in **integer** division, and a float form diverges at any level where `2*level` is not a
multiple of 5 (63, 67, 71, 78…). Levels 40 and 60 are exact, which is why the §11 fixture never
showed it.

`unsupported_attacker_reason` extends the existing discipline to abilities: an ability that
changes damage and is not implemented is *reported*, never assumed inert. For incoming damage an
unnoticed multiplier eliminates the true seed.

### 12.12 Uncertainty is displayed, not collapsed [implementation]

The run page showed HP from whichever candidate came first out of the dict — one prediction
presented as fact, when candidates genuinely disagree about damage rolls and critical hits (after
one False Swipe, 61 candidates held six different HPs). Both HP bars now show a range: solid to
the value every candidate agrees on, a lighter band across the span they disagree over, and empty
for what is certainly gone. Danger is judged on the **low** end, since the best case would
under-warn exactly when it matters.

The same principle applies to the Phase 2 transition. When the preconditions hold the button is
emphasised; when they do not it stays **enabled** behind a confirmation, because `solver_blockers`
reports what the *simulation* believes and the player can see things it cannot — an unmodelled
damage modifier leaves the simulated target above 1 HP when the real one is at 1. Refusing outright
would lock the run out precisely when the model is the thing at fault.

### 12.9 Reporting is an interview, not a token string [implementation]

The grammar of §13 is how the tool *stores* and *compares* turns. It is not how a turn should be
entered. The run page asks the small factual questions — what did you do, what happened, what did
the target do, what is your HP — and assembles the tokens itself, because over dozens of turns a
typed string puts the grammar in the player's head, and a typo is then indistinguishable from a
wrong model constant. Telling those two apart is the one diagnosis §2.5 depends on.

Which questions apply is derived from the moveset, not hardcoded: a status move is never asked
whether it crit, a never-miss move is never offered "missed", and HP is asked only when something
must have changed it. `hunt_session.move_info` is the single source of those flags.

The completeness requirement this creates is worth stating: **every turn the simulator can
predict must be expressible in the interview**, or a run can reach a state it cannot report. That
is a test, not an aspiration — and its first run found 96 of 456 distinct renderings
unreportable, all of them the `~` secondary-effect marker (Aurora Beam's Attack drop), which had
no question.

### 13.1 The grammar's real job is canonical rendering, not parsing

Worth stating up front, because it reorders the priorities. Input will be collected the way
`metronome_compass` collects it — **interactive prompts and UI elements**, not the player typing
a path string. So the pipeline is:

1. Each candidate seed's simulated turn is rendered to a token sequence.
2. The player's observations are gathered through prompts.
3. Filtering is a **list compare** (or a string compare after stringification).

That means the grammar's essential property is that it be **canonical** — one and only one
rendering per battle state — not that it be parseable from arbitrary text. Round-tripping from a
typed string is a convenience for fixtures, notes and bug reports, not the primary path.

### 13.2 On token collisions: position resolves them

An earlier draft of this section argued that the existing uppercase status tokens (`PAR`, `SLP`,
`SCFZ`, `STR`, `CFZ`, `CVFire`, `Mag2`) collide with the action prefixes `P`, `S`, `C`, `M` and
must be lowercased. **That argument was wrong**, because it assumed a context-free tokeniser.
A parser that tracks grammar position has no ambiguity:

- Bag actions (`I`, `C`, `P`, `S`) resolve *before* any move (§12.1), so nothing after an `E` or
  `M` token can be a bag action. In `P0Epar`, the `p` cannot be a Poké Ball.
- `E` and `M` followed by a **digit** is a move slot; followed by a **letter** it is the
  prevented-from-moving form plus its status.
- No turn begins with a status token — a turn always opens with an action.
- Our action slot is consumed once filled, so a second actor-action cannot appear.

I could not construct a genuinely ambiguous string under those rules. **Lowercasing the detail
alphabet is therefore optional** — a readability choice, not a correctness requirement. (If it is
done, note that bare single letters `f`, `p` and `s` would then conflict with `frz`/`fln`,
`par`/`psn` and `slp`/`scfz`/`str`, so single-character markers should stay symbolic: `h`, `-`,
`!`, `~`.)

`HP###` is likewise fine as a two-character prefix: the action-prefix set `I C M P S E HP` is
prefix-free because **`H` alone is not an action**, so longest-match resolves it. Worth an
assertion in the tokeniser so a future bare `H` action cannot silently break it.

HP is `HP` + **exactly three zero-padded digits** — three is always enough, since the largest
possible Gen 4 HP stat is 714 (Lv 100 Blissey), and fixed width keeps `HP50M2` from being
ambiguous.

### 13.3 Actions

| Token | Meaning |
|---|---|
| `Ip` `Isp` `Ihp` `Imp` | Potion / Super / Hyper / Max Potion |
| `Ifh` `Ifr` | Full Heal / Full Restore (status cures — see §13.7) |
| `Ixa` `Ixd` `Ixs` `Ixsd` `Ixp` `Ixc` | X Attack / Defend / Special / Sp. Def / Speed / Accuracy |
| `Idh` `Igs` | Dire Hit / Guard Spec. |
| `C` | capture ball thrown and **succeeded** — terminal |
| `M1`-`M4` | our move, by slot in the active Pokémon's registered moveset |
| `M` | we selected a move but a status intervened — followed by the status detail; see §13.4 |
| `P0`-`P3` | standard ball, that many shakes |
| `Pc` | **accidental capture** in a standard ball — terminal, run lost |
| `S1`-`S6` | switch to that party slot |
| `E1`-`E4` | enemy used that move, by slot in its known moveset |
| `E` | enemy's move was intervened on by a status — followed by the status detail; see §13.4 |
| `HP###` | our active Pokémon's HP at end of turn, zero-padded to 3 digits |

### 13.4 Tokens are chronological, and a status can resolve *and* let the action through

The ordering rule inside a turn is simply that **tokens appear in the order the events occur** —
which is what `metronome_compass` already does. That explains a placement which would otherwise
look arbitrary: a status check happens *before* the move executes, so **the status marker precedes
the move slot.**

And crucially, a status intervening does not always mean the action is lost. But a
**status-end token is only needed when the status can persist while the action still completes** —
otherwise the end is implied by the action happening at all:

| Status | Prevented form | Action completed | End token needed? |
|---|---|---|---|
| Paralysis (25% full para) | `Mpar` | — (permanent; each turn is an independent check) | n/a |
| Sleep | `Mslp` | `M1h` | **no** — you cannot move while asleep, so waking is implied |
| Freeze | `Mfrz` | `M1h` | **no** — thawing is implied the same way |
| **Confusion** | `Mcfz` (hit self) | `Mscfz1h` *snapped out*, or `M1h` *attacked through, still confused* | **yes** |
| Flinch | `Mfln` | — | n/a |

**Confusion is the only case that needs one**, precisely because a Pokémon can stay confused and
still attack through it — so the move completing does not tell you whether the status ended. The
presence or absence of `scfz` is what distinguishes "snapped out" from "attacked through."

This also means no wake/thaw token is required, which drops two token types and shortens every
rendering. Note the RNG still differs between the two cases even though the observable does not
need a token: a **sleep** duration is rolled once when the status is applied, so its per-turn
resolution costs nothing extra, whereas **freeze** spends a 20%-thaw roll every turn. Both are
modelled; neither needs reporting, because whether the move executed already says which happened.

(Flinch is documented for generality only — nothing in Suicune's moveset causes it.)

So `ESCFZ2h` reads "the enemy snapped out of confusion, then used move 2, and hit" — the slot is
still there because the move happened. `scfz` already exists in `metronome_compass`; the generic
`StatusEnd` form `(label)` stays useful for durations whose end is *not* implied by an action
completing, such as Disable, Taunt and Encore.

**This also means a status that *might* prevent acting does not remove `USE_MOVE_N` from the
action set** (§12.5). You can select a move while frozen or asleep, and the thaw/wake roll decides
whether it executes — there is no reason not to click M1. An earlier draft of §13.7 said a frozen
Pokémon "can still use items and balls," which understated it: it can attempt moves too, and
`Mfrz` is simply one of the possible renderings of that turn.

### 13.5 The missing token the Suicune fixture will actually hit

**`E` + status — the enemy was prevented from moving.** Suicune is paralyzed for the whole of
Phase 2, so **~25% of its turns it cannot act** (§4.2). This is observable ("it can't move!"),
consumes a roll, and is one of the recurring identification signals in §3 — but the sketch has
no token for it. By symmetry with `M`, `Epar` is the natural form. **This is guaranteed to occur
in the fixture**, so it is not an edge case.

No token is needed for a **failed move**. Whether a move fails (Mist while Mist is up, Spore on
an already-statused target, an X item at +6) is determined by battle state rather than by a roll,
so the simulator derives it and the player never has to report it. The RNG consequence is still
modelled.

### 13.6 Detail tokens

Reused from `metronome_compass` directly — casing is a free choice (§13.2). Shown here
lowercased for readability:

| Token | Meaning |
|---|---|
| `h` `!` `-` | hit / critical hit / miss |
| `~` | a secondary effect proc'd |
| `xN` | multi-hit, N hits |
| `par` `slp` `frz` `brn` `psn` | non-volatile statuses |
| `cfz` `scfz` `fln` | confused / snapped out of confusion / flinched |
| `zz` `lv` `str` `bd` `bf` `magN` `cvType` | as in `metronome_compass` |

Moves with richer outcomes (Tri Attack's status choice, Acupressure's stat pick) reuse their
existing per-move tokens directly — a real benefit of building on the Metronome work.

### 13.7 Our Pokémon getting a status condition

The plan had not accounted for this. It does not arise against Suicune, which inflicts nothing,
but many opponents do, and the user's analysis of why it is special is right:

> Unlike healing items — which are interchangeable so long as the Pokémon does not faint —
> **curing a status condition massively changes the RNG.** A paralyzed or sleeping Pokémon's turn
> consumes different rolls than a healthy one's.

So this is **the one case where `USE_ITEM` splits into two distinct solver actions**:

| Action | Item | Considered when |
|---|---|---|
| `USE_ITEM` (no cure) | per the §12.2 tiering | always |
| `USE_ITEM_CURE` | **Full Heal**, or **Full Restore** if a Full Heal would still leave us fainting | only while the active Pokémon has a status condition |

Antidote, Burn Heal, Paralyze Heal and Awakening are equivalent to Full Heal for our purposes
(and cheaper — §12.6's post-optimisation can downgrade). Modelling only Full Heal / Full Restore
keeps the action set small while losing nothing.

**The action count is therefore 7 normally, 8 while statused.**

Three consequences worth recording:

- **Sleep needs the hidden-duration machinery on our side.** `context.py:roll_hidden_duration` /
  `hidden_status_ends` already do exactly this for Magikarp and Chansey, so it transfers.
- **No status gets special priority — the distance metric decides.** An earlier draft called
  freeze "the status most worth curing immediately." That is not how this solver works: being
  statused is simply a **different RNG cost profile**, and `USE_ITEM_CURE` competes against every
  other action on §12.7's distance like anything else. A frozen Pokémon keeps its whole action
  set — items, balls, **and moves** (§13.4) — and its 20%-per-turn thaw roll is predictable from
  the identified seed, so staying frozen may well be the cheapest route to the right offset.
- **Paralysis on *our* Pokémon can flip turn order.** It quarters our Speed, so §11.4's margins
  must be re-checked against our own possible statuses, not just the target's. Smeargle survives
  it comfortably (160 -> 40, still far above Suicune's 21), but the config validation should
  assert non-tie under our statuses too.

**Gen 4 Full Heal cures confusion** [verified by user], along with poison (regular and bad),
paralysis, sleep, burn and freeze — so one `USE_ITEM_CURE` action covers every case, and there is
no need to model per-status cure items.

### 13.8 Grammar invariants worth enforcing

Each of these is checkable against the simulator's own prediction, and each catches a class of
mis-reported turn. They matter most in Phase 2, where they are the desync detector (§2.5):

- **Bag actions precede the enemy's move.** `I`, `C`, `P` and `S` all resolve before any move
  (§12.1), so within a turn they must appear before `E`. `E2!~Ihp` is invalid; `IhpE2!~` is the
  only legal order.
- **`C` and `Pc` are terminal.** Nothing follows them.
- **An `HP###` token is present exactly when our HP changed, for any reason.** Not only damage
  taken — also a **healing item**, **burn or poison** ticking at end of turn, a **confusion
  self-hit**, recoil, Struggle, Leech Seed or weather. Since the simulator predicts whether HP
  changed, this is checkable in both directions: a missing token where a change was predicted, or
  a present one where none was, is a discrepancy worth surfacing. Given §2.5's verification role,
  that distinction matters.
- **`HP###` is exactly five characters.**
- **A `MN` token is only valid if the active Pokémon has move N** (§12.5), which requires the
  parser to track the active Pokémon across `S` tokens.

### 13.9 Worked example

```
E3hM2-HP050 IhpE2!~HP100 E4M2h
```

1. Enemy used move 3 and hit; we used move 2 and missed; we ended the turn on 50 HP.
2. We used a Hyper Potion (bag priority, so it resolves first); enemy used move 2, crit, and its
   secondary proc'd; we ended on 100 HP.
3. Enemy used move 4 with no hit check (a status move); we used move 2 and hit. No `HP` token, so
   our HP did not change.

A phase-boundary marker is worth adding for fixture strings — `|` between the Phase 1 and Phase 2
segments — since the two phases have different rules about what is legal (§2.1).

---

## 14. Open questions before implementation

### 14.1 Answer these two first — both cheap, both de-risking

**(1) ~~Build an `effects.py` regression corpus from `data/move_paths.tsv`.~~ RETRACTED.** That
file is generated data for `metronome_compass` and **is not accurate**, so it is not a golden file
and cannot serve as one [corrected by user].

The concern it was addressing has also largely dissolved: per §15.2, Battle Compass is built
alongside rather than by refactoring `effects.py`, so Phase 1 only *moves* generic code
(`BattleContext`, token base classes) without changing behaviour. The existing 1,024 tests are an
adequate net for a move-without-modify. And the real validation strategy is §16's emulator loop,
which is the only thing that can establish correctness in the first place.

**(2) Decide how the target's IVs and nature are obtained — or whether they are needed at all.**
The design assumes Suicune's exact stats are known because the encounter is RNG-manipulated, but
**there is no PID/IV generation code in `claytonlib`** [verified]: `safari_encounters.py` resolves
encounter slots and species only, and the project has historically handed IVs off to Pokefinder.
Static legendaries also use a different generation method than Sweet-Scent wild encounters.

The reassuring part is how little actually depends on it [derived]:

| Target stat | Needed? | Why |
|---|---|---|
| max HP | **No** | `a` = 2 at 1 HP for *any* max HP >= 2, so the catch threshold is IV-independent |
| Speed | **No** | paralyzed range is 16-23 across all IVs and natures; Smeargle's 160 clears all of it |
| Def / SpD | **No** | only affects damage we *deal*, which we never model (§5) |
| **SpA** | **Yes** | and *only* for §3.1's incoming-damage filter |

Across all IVs and natures Suicune's SpA spans **69-97**, which makes Aurora Beam anywhere from
18-22 to 26-31 — overlapping ranges, so an unknown SpA makes the damage filter **unsound**, not
merely vague (§3.1).

So the whole dependency on RNG-manipulating the target reduces to **one stat, for one optional
feature.** Three viable answers:

- **(a) Manipulate Seed A** (Pokefinder or new Method-1 code) -> exact SpA -> filter on, ~2.5
  extra bits/turn.
- **(b) Do not manipulate** -> filter off -> everything else in the design still works, at the
  cost of slower identification and a hotter §2.4 path.
- **(c) Jointly identify `(seed, SpA)`** from observed damage. SpA has only ~28 possible values,
  so this is tractable and needs no Seed A control — arguably the most elegant option, and worth
  costing before committing to (a).

**This is the one place where the document's "we know the opponent exactly" premise is not backed
by tooling**, so it deserves an explicit decision rather than an assumption.

### 14.2 Ground truth still needed (gdb)

None of these block Phase 1; they block the solver being *correct*.

| Item | What |
|---|---|
| R7 residual | between-turn advance count here; confirm `effects.py`'s per-move counts hold outside the Metronome matchup |
| R8 | paralysis constants — speed x0.25, catch x1.5 |
| R5 | general `GetShakeCount` — ball and status multipliers, HP-term flooring |
| R4 | wild move selection: `roll % 4`?, rejection sampling on unusable moves, move index order |
| R2 | battle-start advance count for Suicune (Pressure on entry) |
| R10 | incoming damage for **Aurora Beam and Gust** — all 16 rolls, crit and non-crit |
| — | Gen 4 crit rule: crits ignore the defender's positive Def/SpD stages (§12.3) |
| — | HGSS item price table, for §12.7's distance function |
| — | whether Gen 4 Full Heal cures confusion (only matters beyond Suicune) |

### 14.3 Design decisions that are not discoverable — they need a call

1. **Refactor `metronome_compass` in place, or build `claytonlib/battle/` alongside and migrate?**
   The doc assumes in-place (§9 items 8-10). In-place keeps one source of truth and lets the test
   suite guard every step; alongside is lower-risk for the working tool but risks two divergent
   simulators. This is the single largest scoping decision in the plan.
2. **Is multi-candidate solving (§6.4) in v1, or gated on measurement?** If Phase 1 reliably pins
   the seed (§11.7 test 2), it can be deferred. That is measurable *before* building it.
3. **Notebook-first, or app-integrated from the start?** Phase 5 assumes a `Hunt` persistence type
   and an app area; `metronome_compass` began as notebook-only.
4. **How is the player's party entered?** Asking for the **exact stats off the summary screen** is
   simpler and less error-prone than deriving them from species/level/IVs/EVs/nature — and it means
   base stats are needed **only for the target** (plus the Fast Ball's base-Speed test), which
   shrinks the PokéAPI job considerably.
5. **On a Phase 2 desync (§2.5): abort or re-solve from the divergence point?** And can the tool
   distinguish "seed was wrong" from "damage model is wrong"? They call for different responses.
6. ~~Does a player deviation from the returned path trigger an automatic re-solve?~~
   **Answered (§15.4.2): yes** — the action that actually happened is accepted and the solver
   re-runs from the real state.

### 14.4 Deliberately left open until measured

Not blocking, and cheaper to discover than to predict: whether dominance pruning keeps the search
tractable (§12.8), whether Phase 1 reliably pins the seed (§11.7 test 2), and what the real
action-alphabet cost diversity turns out to be (§1.1 vs R7).

---

## 15. Decisions (§14 answered)

### 15.1 Target IVs and nature: configured, filter on

Option (a). The user obtains the target's IVs and nature by RNG manipulation with external tools
(Pokefinder), and **enters them as part of the Hunt configuration**. The §3.1 incoming-damage
filter is therefore **on** by default, and no PID/IV generation needs building in `claytonlib`.

The target's stats are **derived** from base stats + IVs + nature + its fixed level (0 EVs, wild).
Our own party's stats are **entered directly** off the summary screen (§15.4), so base-stat data is
needed **only for target species** — plus the Fast Ball's base-Speed >= 100 test.

### 15.2 Battle Compass is its own tool, built alongside

Not an in-place refactor of `metronome_compass`. **This removes the single largest risk in the
plan** — §10's "Phase 1 is the whole ballgame" no longer applies, because the 2,900-line symmetric
refactor of `effects.py` is not on the critical path.

It introduces a different risk in its place: **two divergent simulators** of the same Gen 4
mechanics. Worth being deliberate about, because `effects.py`'s value is its hard-won verified
advance counts, and duplicating them badly would be the worst outcome here.

The tension is real and worth stating plainly: **`effects.py`'s handlers are written against
`MetronomeBattleState`'s `user_`/`mk_` field prefixes, so sharing them requires exactly the
symmetric refactor we just took off the table.** Three ways out, and the first is clearly right
for v1:

- **(i) Battle Compass implements only the handlers it needs.** For the §11 fixture that is **nine
  moves** — Suicune's four plus our five — against `effects.py`'s 235. Duplication at that scale is
  cheap, and it comes with a **free cross-check**: every one of those nine already has a verified
  handler in `metronome_compass`, so the new implementations can be validated against the old ones.
  The cost grows only as targets are added.
- (ii) Do the symmetric refactor anyway, so handlers can be shared. Deferred, not rejected — it
  becomes attractive once the ported handler count climbs.
- (iii) An adapter presenting a symmetric view over `MetronomeBattleState`. More indirection than
  it is worth at nine moves.

**Shared code** should go in a new `claytonlib/battle/` package — the genuinely matchup-agnostic
pieces, several of which do not exist yet:

| Module | Contents | Status |
|---|---|---|
| `context.py` | the dual RNG/interactive `BattleContext` | **exists** in `metronome_compass`, genuinely generic, move it |
| `tokens.py` | path-token base classes and rendering | exists, partly generic |
| `catch.py` | generalized `GetShakeCount` (§4.1) | generalize from `safari.py` |
| `damage.py` | Gen 4 damage, incoming only (§3.1) | **new** |
| `stats.py` | stat derivation from base/IV/nature/level | **new** |
| `types.py` | type-effectiveness chart | **new** (prose exists in `notes/ss_rng/effectiveness_chart.md`) |

`moves.py` and `advance_rng` are already shared. `metronome_compass` can migrate onto
`claytonlib/battle/` later; nothing forces it to move first.

### 15.3 Phase 1.5: pinning the seed at 1 HP

Multi-candidate handling is **required**, not optional — but it is better understood as its own
phase than as a mode of Phase 2:

| | Phase 1 | **Phase 1.5** | Phase 2 |
|---|---|---|---|
| State | working toward 1 HP + paralysis | **already at 1 HP + paralyzed** | seed pinned |
| Goal | set up | **pin the seed** | steer to a capture window |
| Driver | the player | the tool advises, the player acts | the solver |
| Objective function | — | **maximise information gain** | **minimise §12.7 distance** |

Naming it separately matters because **the two objectives are different**. Phase 2 minimises
distance; Phase 1.5 maximises expected candidate reduction, subject to not accidentally capturing
(§2.3) and not fainting. A distance-minimising solver is the wrong tool for Phase 1.5, and vice
versa — so they want separate action-selection policies over the same simulator.

Phase 1.5 is also where **accidental-capture risk peaks**: at 1 HP and paralyzed a standard ball
captures at 1.234%, three times the full-HP rate (§2.3). So §2.4's risk/reward disclosure is
squarely a Phase 1.5 feature, and the `machete_jane` decision-tree pattern (§6.4) is its natural
implementation.

### 15.4 App integration from the start

**UI is in prototype scope, not after it** [user]: build Battle Compass and Hunts directly in the
app, with no notebook or CLI interim layer. Every capability lands behind `app/facade.py` with UI.

A new **Hunts** tab alongside Expeditions and Profiles — the Battle Compass equivalent of an
Expedition. No chart equivalent; Metronome Compass remains available and unchanged. Runs are saved
for replay and verification, but **not** fed back into model calibration.

Good news on plumbing: **the patterns needed already exist** [verified].

- `app/metronome_session.py`'s `SeedBSession` is exactly the right shape — it drives a
  console-style `input()`-blocking narrowing loop from an async UI by running it on a background
  thread with question/answer queues, exposing only `{prompt, output, done, result}` snapshots. A
  `hunt_session.py` should mirror it rather than invent anything.
- `facade.py:list_runs(profile_id, kind)` already switches on kinds `"metronome"` and `"safari"`,
  so a third kind slots in naturally.
- `metronome_users` already live inline on the **profile** document, which is precedent for the
  party living there too.

**The split between configuration and live state mirrors the Safari side exactly** [verified]:
`Expedition` is a *"Persistent configuration and workflow manager"* holding chart and compass
inputs, while `compass_safari` runs the live interactive narrowing in memory, and finished runs are
recorded separately via `save_safari_run`. So:

| | Holds | Persisted? |
|---|---|---|
| **Hunt** | the party for this hunt, their held items, the target and its IVs/nature, the ball to capture with, and any other setup/planning config | **yes** — it is configuration |
| **Battle Compass** | the live encounter: current HP, per-move PP, stat stages, surviving candidates, RNG offset | **no** — in-memory for the duration of the battle |
| **Run records** | a finished (or abandoned) battle, turn by turn | yes, as a **diagnostic** — for replay and verifying the tool, not for calibrating models |

An earlier draft of this section claimed Hunt persistence had to carry mid-battle state. **It does
not** — that conflated the two, and the Expedition/Safari-Compass precedent already settles it.

### 15.4.1 Where each piece of configuration lives

- **Profile** — the durable facts about each party Pokémon: species, level, entered stats, ability,
  moveset (Smeargle's is fixed and reused across hunts, §11.1), and max PP. This follows
  `metronome_users`, which already live inline on the profile document [verified].
- **Hunt** — which of those profile Pokémon form this hunt's party, **their held items** (easy to
  change per hunt), the **target and its IVs/nature** (per-encounter), the capture ball, and the
  seed-targeting configuration from §17.1: `key_seed`, **advances**, `initial_time` (chosen from the
  seed's possible times), **Vector ms**, and the **active calibration model**.

One nuance worth settling: **starting PP**. Max PP is durable (PP Ups/Maxes) so it belongs on the
profile, but *current* PP at the start of a battle is per-run. Defaulting to full — you would heal
before a hunt — with a per-hunt override is probably right.

### 15.4.2 Undo is two different operations

Worth separating, because the two phases fail differently:

- **Phase 1 — "undo last turn."** Pure bookkeeping: a great deal of detail is being reported, so
  mis-entry is likely. Rewind the reported path by one turn and re-widen the candidate set
  accordingly.
- **Phase 2 — mostly verification, and the interesting case is not an undo at all.** Two distinct
  needs:
  1. *Misreport* — rewind, as in Phase 1.
  2. **Misplay** — the player took a different action in-game than the one prescribed. This
     **cannot be undone**, because the game has already advanced. The tool must accept the action
     that actually happened and **re-solve from the real state.**

Case (2) answers §14.3 item 6: **a player deviation is accepted, not rejected, and triggers a
re-solve.** It is also cheap to support — the solver is fast (§6.3) and item choice moves no RNG
offsets (§12.6), so re-solving mid-battle is routine rather than exceptional.

### 15.5 Desync recovery: widen the window first

On a Phase 2 mismatch (§2.5), **offer to widen the candidate-seed range** and re-search for a seed
consistent with the whole observed path; the player may abort instead.

This is better than the abort-or-re-solve framing it replaces, and it has a property worth noting:
**widening doubles as the diagnostic.** Once the damage model has been validated (R10), the likelier
cause of a mismatch is a too-narrow initial window, not a modelling bug. So if a *substantially*
wider range still yields no consistent seed, that is real evidence the damage model or an advance
count is wrong — which is exactly the discrimination §14.3 item 5 asked for, obtained for free.

---

## 16. Validation strategy: the forced-seed emulator loop

The primary way this tool gets validated, and the reason most of §14.2's ground-truth items are
**not** blockers to starting.

### 16.1 The loop

1. Generate a list of candidate seeds occurring in a range.
2. **Use gdb to overwrite the battle seed** in the emulator with one of them, chosen at random.
3. Run Battle Compass against that same candidate list and check it **identifies the right seed**.
4. Check that the path it returns **actually captures in the emulator**.
5. A logging utility records the emulator side so logs can be diffed against the tool's output.

Steps 2 and 5 are built:

**`utils/gdb-battle-reader.py`** — sourced inside gdb, records one hand-played battle with the
seed optionally forced. Sibling to `utils/gdb-seed-reader.py`, and different in two ways that
matter. It does **no auto-pressing and no batch loop**: the Metronome slurper replays a seed file
because that battle plays itself, whereas a Battle Compass battle is played by hand over dozens
of turns. And it logs **our Pokemon's HP**, which is the one thing battle messages cannot tell us
and exactly what R10 needs. The forced-seed technique is lifted wholesale from the proven reader
— overwrite `r3` at `BattleSystem_Random+8`, just past the seed load, so the game's own store
writes `advance_rng(seed)` coherently, with the same sanity check that aborts rather than
mislabelling a recording.

```
(gdb) source utils/gdb-battle-reader.py
(gdb) battlelog 0xEC1504DC suicune    # force this seed, record to data/battle_logs/suicune.jsonl
      ... play the battle, typing `battlemark turn1`, `turn2`, ... as you go ...
(gdb) battlesave
```

**`claytonlib/battle/logcheck.py`** — pure Python and tested, because the recorder needs a live
emulator and cannot be tested at all. As little judgement as possible lives in the recorder and
as much as possible lives here. `python -m claytonlib.battle.logcheck <log.jsonl>` reports:

| Section | Answers |
|---|---|
| rolls by calling function | **R7** — which of the ROM's 74 `BattleSystem_Random` call sites this matchup exercises, and how often |
| rolls between markers | **R2** — battle-start advances, and per-turn counts to check `battle/turn.py` against |
| damage taken | **R10** — each HP drop with the rolls before it; `check_damage_event` then asks `battle.damage` which of the sixteen rolls could have produced it |

Segmentation uses the markers you type rather than a heuristic, on the grounds that you are
already sitting at the emulator and a marker is exact where a guess is not. And a damage event
that **no** roll explains is the outcome that matters: it means the seed, the entered stats, or
the damage model is wrong, and §3.1 requires that be loud rather than quietly eliminating
candidates.

Both tolerate the case where gdb has no DWARF types for `BattleSystem`/`BattleContext`: the
recorder says so once and carries on logging rolls and messages without HP, and the report says
R10 cannot be answered from that log rather than looking complete.

### 16.2 Why this is the right shape

- **Forcing the seed removes timing from the test entirely.** No timer calibration, no seed-hitting
  — just write the value. So the test exercises the simulator and solver in isolation from
  everything §1 already said Battle Compass does not need.
- **Random selection from a known list makes it a blind test.** The tool has to find the seed, and
  we hold ground truth.
- **Both halves get exercised end to end**: identification (step 3) *and* solving (step 4). A path
  that captures in the emulator is the only real proof the advance counts are right.
- **Unit tests cannot substitute for this.** The failure mode we most fear is a wrong advance
  count, and a unit test written against our own implementation would simply encode the same wrong
  number. Only the emulator can establish correctness; unit tests then protect it from regression.
  Worth keeping that division of labour explicit.

### 16.3 What it implies for sequencing

The loop **requires the tool to exist** before it can run, so the order is **build with best-guess
constants, then calibrate against the emulator** — the same way the Metronome work proceeded
(`notes/gdb_logs/`, the calibration notebooks). None of §14.2's measurements block starting; they
block *trusting the output*, which is a different gate.

One partial exception: **R4 (wild move selection)** shapes the identification code rather than just
a constant — flat `roll % 4` versus rejection sampling on unusable moves are different control flow.
Worth making it one of the first things the loop answers.

---

## 16.1 Ground truth: the first real emulator run [verified]

`data/battle_logs/test1.jsonl` — a hand-played Bell Tower Suicune battle with the battle seed
forced to `0xC5011C6B`, 17 turns, captured by `utils/gdb-battle-reader.py`. It settles R2, R7 and
the identification half of R10, and it found three bugs that no amount of reasoning had.

**What it confirmed.** After the fixes below, the simulator reproduces all 17 turns exactly:
every advance count, every move Suicune chose, every ball's shake count, and **every one of our
HP values** (126, 146, 120, 96) — the last being the whole identification signal.

| Quantity | Value | Note |
|---|---|---|
| R2 battle-start advances | **6** | 4 `bellShimmerReplaceGraphics` + 2 for Pressure — the same figure `metronome_compass` verified for Blackthorn |
| Wild move-selection roll | **1 per turn** | caller unresolved (`??`), present on every turn |
| BeforeTurn | **4 per turn** | `BattleControllerPlayer_BeforeTurn` |
| Paralysis check | **1 per turn while paralyzed** | `ov12_0224B528`, absent on turn 1 before Thunder Wave landed |
| Post-successful-move | **2, per move that succeeded** | so the skeleton is 10 / 8 / 6 for two, one or no successes |
| Between-turn + end-of-turn | **2 + 4** | inside the same skeleton figure |
| Secondary-effect proc | **1** | `ov12_02250490`, on the three Aurora Beam turns only |
| Ball shakes | **`min(shakes+1, 4)`** | 3 shakes→4 rolls, 0→1, 1→2 |

**Bug 1 — moves that fail because their condition is already up.** This is what made the run
diverge at turn 3, after matching turns 1 and 2 exactly. Suicune re-used Rain Dance while it was
already raining, the game reported "But it failed!" and skipped the **two post-successful-move
advances**; the simulator spent them. 17 advances against a simulated 19, and every offset after
that was wrong. Same for Mist while misted (turns 6, 7, 8, 16) and Mean Look on an already-trapped
target (turn 12). `rain_turns`, `mist_turns` and `target_trapped` existed on `BattleState` and had
never been wired to anything.

Durations, both verified from the log: **rain 5 turns** (set turn 1, stopped turn 5), **mist 5
turns** (set turn 4, wore off turn 8).

A Mist-blocked stat drop is *different*: turn 15's Sweet Scent was reported "protected by Mist"
and the turn still spent 8 skeleton rolls, not 6 — so the move executed and paid its post-move
advances. Blocked effect, successful move.

**Bug 2 — the damage formula: two errors, both in how the multiplications are ordered.**

*The roll was inverted.* `ApplyDamageRange` *subtracts*:

```c
damage *= (100 - (BattleSystem_Random(battleSystem) % 16));
damage /= 100;
```

so `% 16 == 0` is 100% and `% 16 == 15` is 85%. This was implemented as `85 + roll % 16`, which
spans the **same sixteen multipliers** and therefore passes any range check while getting every
individual value wrong.

*And the roll was applied in the wrong place.* Tracing the call chain
(`battle_command.c:DamageCalcDefault` → `BtlCmd_CalcDamage`, and the STAB/type block in
`overlay_12_0224E4FC.c`) gives the real order, and every step truncates, so the order **is** the
result:

```
CalcMoveDamage:   atk * power * ((level*2/5)+2) / def / 50, then + 2
                  damage *= criticalMultiplier
BtlCmd_CalcDamage: damage = ApplyDamageRange(damage)              <- the roll
(later command):  damage = damage * 15 / 10                       <- STAB
                  damage = DamageDivide(damage * tenths, 10)      <- once PER defender type
```

This applied STAB and type effectiveness *before* the roll. Three consequences, all confirmed:

* Power modifiers are on **base power**, Technician first, then a type-enhancing item at
  `(100 + 20)/100` — the 20 read out of `files/itemtool/itemdata/item_data.narc`, where every
  type-enhancing item carries the same param. For a Technician user with Silk Scarf, False Swipe
  is `40 → 60 → 72`.
* Type effectiveness truncates **once per defender type**. Ice on Ice/Ground is `x0.5` then `x2`,
  which is not `x1`.
* The level term is integer division, `((level * 2 / 5) + 2)`.

*The inverted roll, in the data.* `ApplyDamageRange` *subtracts*:

```c
damage *= (100 - (BattleSystem_Random(battleSystem) % 16));
damage /= 100;
```

so `% 16 == 0` is 100% and `% 16 == 15` is 85%. This was implemented as `85 + roll % 16`, which
spans the **same sixteen multipliers** and therefore passes any range check while getting every
individual value wrong. The log is unambiguous: a roll of `% 16 == 13` dealt *less* than one of
`% 16 == 9`, which the ascending form cannot produce. Against the three Aurora Beam hits:

| | turn 5 | turn 13 | turn 17 |
|---|---|---|---|
| actual | 27 | 26 | 24 |
| corrected (`100 - r`) | **27** | **26** | **24** |
| as implemented (`85 + r`) | 24 | 25 | 27 |

All three wrong, from a single base damage of 28. This is the §3.1 signal — ~2.5 bits per hit, the
richest observable there is — so the effect was not imprecision but *eliminating the true seed on
the first damaging turn*. Solving the three hits for Smeargle's Sp. Def gives 78–80, which matches
the 80 assumed, so the formula itself was right and only the roll mapping was backwards.

**Bug 3 — our own fainting was not terminal.** `BattleState.over` ignored `ours.fainted`, so the
simulator kept taking turns at 0 HP and rendered hits that changed nothing — `E2h` with no `HP`
token, which `validate_turn` correctly rejects. Found while chasing something else; the solver had
always treated fainting as a hard constraint (§6.2), and the simulator now agrees.

**Still open.** Outgoing damage does not reconcile. False Swipe dealt 28, 28, 27, 27, 27 with
multipliers 91, 92, 87, 90, 90, and no single base damage fits — turn 5 needs 32 where the others
need 31. Outgoing damage is not in the token stream, so this does not affect identification; it
affects only the Phase 2 gate, and False Swipe's clamp reaches 1 HP regardless. The likeliest
cause is the assumed Smeargle attack stat (recorded only as "about 65") rather than the formula.
Needs the exact figure to settle.

**Also noted.** The `gdb-battle-reader` stat override wrote every *stat* correctly (141/63/119/
89/109/84 — exactly the configured Bold spread) but two of the six IV bitfields read back wrong
(`spa` 31→5, `spe` 28→26), so it reported `verified: false`. Since the stats are what the
simulation consumes and they were right, this run is sound; the IV write needs looking at, and
the verification should distinguish "stats wrong" from "IVs cosmetically off".

## 17. Remaining questions

### 17.1 Candidate generation — ANSWERED

A Hunt carries the same seed-targeting configuration an Expedition does, minus the optimisation:

| Hunt config | Role |
|---|---|
| `key_seed` | as in Expeditions |
| **advances** | the Seed A advance frame that produces the target's intended IVs/nature |
| `initial_time` | **chosen from the list of possible initial times for that seed** — not optimised |
| **Vector ms** (`M`) | simply however long the player needs to reach the target advance — not optimised |
| **active calibration model** | required, since the centre-seed calculation depends on it. Selected through the Metronome Compass "Review data" flow, exactly as for an Expedition |

Together these give the **centre target seed** and a suggested delay/second range, and then:

> **Every seed for every (delay, second) combination in range is included. No probability-density
> filter.**

That is deliberately *not* what Safari Compass does — it weights candidates by posterior landing
probability (`compass/_core.py:posteriors`, `_generate_candidates_calibrated`). Battle Compass
instead follows **`metronome_compass._generate_candidates`'s uniform seconds x delays grid**, which
is already written as a deliberate superset of the strictly reachable seeds. Since nothing here
needs to *hit* a seed, there is no reason to rank candidates — only to be sure the true one is in
the set.

**Seed A work that is still needed:** the Seed A / advance-frame deduction from Safari Compass —
roamer positions and Elm-call identification (`calibration_tools.py`, `safari_advance.py`) — because
the target's IVs come from hitting a Seed A advance frame.

**Seed A work that is *not* needed:** `safari_encounters.py`'s in-house block-config search for
frames that generate the target species. A static legendary's species is fixed, so there is nothing
to search for.

### 17.1a The two grid axes are not equally identifiable — measured, then **corrected**

Section 17.1 said the window "can be generous to the point of carelessness". That is comfortably
true of the **frame** and much less true of the **second**.

| Window | Candidates | Outcome |
|---|---|---|
| frame ±60, second ±0 | 121 | identified in 2 turns |
| frame ±600, second ±0 | 1,201 | identified in 3 turns |
| frame ±60, second ±2 | 605 | ~~stalls at 5 survivors, forever~~ **median 19 turns** |

> **Correction.** This section originally claimed the RTC second was *unidentifiable* — that no
> move could ever separate second-siblings and the only remedy was a narrower window. **That was
> wrong**, and it was wrong in the conclusion rather than the premise. Credit to the user for
> challenging it; the arithmetic below is what it should have said.

**What is true.** `calculate_seed` is `((mdms << 24) | (hour << 16)) + delay`, so the second
enters through `mdms` in the **top 8 bits**, and an LCRNG difference of `k · 2²⁴` stays a multiple
of `2²⁴` for every subsequent advance:

```
(2²⁴·c) · A  mod 2³²  =  2²⁴ · (c·A mod 2⁸)
```

**What does not follow.** A roll is `state >> 16`, so between second-siblings it differs by
`256·c`. A modulus is therefore blind to the second **only if it divides 256**:

| Modulus | Used for | 256 mod m | Sees the second? |
|---|---|---|---|
| `% 2` | move choice, 2 moves left | 0 | no |
| `% 4` | wild move choice, 4 moves left | 0 | no |
| `% 16` | crit, damage roll | 0 | no |
| `% 3` | wild move choice, **3 moves left** | 1 | **yes** — differs on ~70% of rolls |
| `% 100` | accuracy, secondary procs | 56 | **yes** — differs on almost every roll |
| `roll < b` | shake check | — | **yes** (a magnitude comparison) |

So the original claim held for the moduli that happen to be powers of two, and was generalised to
all of them without checking. Two observables do see the second:

* **Aurora Beam's 10% proc** (`% 100`). Its *verdict* differs on ~20% of rolls, and Aurora Beam
  is one move of four, so about 5% of turns.
* **The wild move choice, once the target is down to three usable moves.** Rain Dance has only 5
  PP, so `% 4` becomes `% 3` early in a long battle — and `% 3` differs on ~70% of rolls, which
  is far stronger than the proc.

**Measured.** 120 second-apart pairs, False Swipe every turn: **all 120 separated. Median 19
turns, mean 19.4, max 54.** Not one failed to separate.

**Consequences.**

- `candidates.generate` still defaults `second_window` to **0**, but for a plain cost reason: it
  multiplies the candidate set fivefold and costs ~19 extra turns. That is a poor trade, not a
  futile one, and a set stuck on seconds is waiting for turns rather than doomed.
- The frame window can stay generous, so imprecision in Vector ms really is close to free.
- `rtc_offset_seconds` matters less than 17.1a first claimed. Getting it wrong costs turns, not
  the run — though it is still the number worth measuring for a *static A-press* encounter, since
  §R1 fitted it to the Sweet-Scent path.
- Balls remain the strongest second-discriminator, but throwing them in Phase 1 is still barred
  for the unrelated reason in §2.3 (a standard ball that lands loses the run).
- `identify.Session.ambiguity()` reports this situation explicitly rather than letting a stuck set
  look like one that needs more turns.

**On the earlier arithmetic.** §17.1's entropy estimate was not wrong so much as measuring the
wrong thing: it counted bits per turn without asking *which* bits of the seed those observations
can see. They see the frame and never the second. Worth remembering as a general caution — an
entropy count says how much information an observation carries, not which unknowns it is capable
of addressing.

### 17.2 Smaller open items

- ~~Confirm Suicune's moveset and level~~ — **closed** [user]: Lv 40, slots in order **1 Rain
  Dance, 2 Gust, 3 Aurora Beam, 4 Mist** (§4.3).
- ~~One capture ball, or a fallback list?~~ — **closed** [user]: **no fallback.** One chosen
  capture ball, so the solver's goal set is a single `b` throughout.
- ~~Whether Gen 4 Full Heal cures confusion~~ — **closed** [user]: **yes**, and it also cures
  poison (regular and bad), paralysis, sleep, burn and freeze. So a single `USE_ITEM_CURE` action
  covers every non-volatile status plus confusion (§13.7).
- ~~Intra-bracket ordering of item / ball / switch~~ — **closed** [user]: you can only take one bag
  action per turn, so the ordering never arises.

### 17.3 Nothing is blocking — but three things to do in the first hour

No open questions remain (§17.2 is fully closed, and §16.3 establishes that ground truth gates
*trusting* output rather than writing it). These are not questions, just friction that is cheaper to
clear up front than to discover.

**(1) `Move` does not expose `power`, `priority` or `pp`** — all three are present in `moves.json`
and all three are needed immediately [verified]:

| Field | Needed by |
|---|---|
| `power` | the incoming-damage model (§3.1) |
| `priority` | turn order — Protect is +3 (§R3) |
| `pp` | the PP budget, which is non-renewable (§7) |

`Move.__slots__` is currently `(number, name, metronome_usable, effect, effect_chance, accuracy,
type_id, category)`. Adding the three is a one-line change but it blocks the first line of code in
three separate features.

**(2) `claytonlib/__init__.py`'s auto-export can silently shadow new shared types.** It walks every
top-level module and subpackage and does `globals().update(...)`, so **last module wins on a name
collision, in `pkgutil` iteration order** [verified]. Today that hoists **267 names from 20
modules** with only one collision (`logger`, benign).

The hazard is directional and unfavourable: **`battle` and `battle_compass` sort early**, so any
name they share with a later module (`metronome_compass`, `moves`, `safari`, `times`) resolves to the
*existing* one. Importing `claytonlib.BattleContext` would silently give you the Metronome version
rather than the shared one.

Given this project's "verified advance counts are sacred" posture, a silently shadowed simulator type
is exactly the class of bug that wastes a legendary. **Add a collision assertion** to the auto-export
(or a test that fails on any name bound to two different objects, whitelisting `logger`). Five lines,
and it protects every extraction that follows.

**(3) Suggested first slice**, chosen so each step is verifiable before the next:

1. The two fixes above, plus the collision test.
2. `claytonlib/battle/stats.py` and `types.py` — pure functions, trivially unit-testable, and they
   let §11's derived numbers be reproduced in code rather than in a scratch script.
3. `basedata/base_stats.json` via `one-offs/populate_base_stats.py` (PokéAPI), target species only.
4. `claytonlib/battle/damage.py` — incoming damage only, and immediately validated against §11.2's
   tables (Aurora Beam 24-29 / crit 49-58 vs Smeargle; 16-19 / 33-39 vs Magneton).
5. `claytonlib/battle/catch.py` — generalized `GetShakeCount`, validated against `safari.py`'s
   existing Safari-path results *and* §2.2's `a`/`b` table.
6. The forced-seed logging utility (§16.1), so everything after this is measured rather than guessed.

Steps 2, 4 and 5 are each independently checkable against numbers already in this document, which
makes them a good place to start: if any of them disagrees with §11, the disagreement is a finding
about the document rather than the code.
