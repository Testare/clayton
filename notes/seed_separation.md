# Breaking apart similar seeds

How to tell two candidate battle seeds apart when the battle itself refuses to.

Status: the **mechanism** is verified against `data/battle_logs/test2.jsonl` and the ROM; the
**measurements** are from the simulator over the section 11 fixture and are tagged as such. The
proposals in section 5 are design, not implemented.

---

## 1. The problem, stated precisely

`candidates.generate` builds a grid over two axes — the **frame** (absolute delay counter) and the
**RTC second**. The two are not equally identifiable, and the asymmetry is structural rather than
bad luck.

`calculate_seed` builds a seed as `((mdms << 24) | (hour << 16)) + delay`. The frame lands in the
**low 16 bits**; the second enters through `mdms` in the **top 8 bits**. So two seeds one RTC
second apart (inside the same minute) differ by exactly `k · 2²⁴`, and that invariant survives the
LCRNG forever:

```
(2²⁴ · c) · A  mod 2³²  ==  2²⁴ · (c · A mod 2⁸)
```

A roll is `state >> 16`, so sibling rolls differ by **`256 · c`**. Which means:

**And `c` is not small.** It changes every advance: `c_{n+1} = c_n · (A mod 256) = c_n · 109
mod 256`. Since 109 is odd, `c` is always odd — the difference never vanishes — and it cycles
through **64 distinct values**, so the roll difference `256 · c` ranges over most of the 16-bit
space rather than sitting at a fixed 256. The first eight values of `c` are
`1, 109, 105, 181, 17, 61, 249, 5`.

That detail is load-bearing, and getting it wrong is how this analysis first went astray: computed
at `c = 1` the shake check looks almost blind (0.78%), and the measurements flatly contradicted
that. Averaged over the `c` the stream actually visits:

| check | form | 256 divisible by the modulus? | P(siblings disagree) |
|---|---|---|---|
| wild move selection | `% 4` | yes | **0.00%** |
| full paralysis | `% 4` | yes | **0.00%** |
| critical hit | `% 16 == 0` | yes | **0.00%** |
| damage range | `% 16` | yes | **0.00%** |
| accuracy 100 | `% 100 < 100` | — (always true) | **0.00%** |
| secondary effect, 10% | `% 100 < 10` | no | 17.9% |
| **shake check** | `roll < b` (magnitude) | — | **44.5%** |
| **accuracy 60** | `% 100 < 60` | no | **48.0%** |
| **accuracy 55** | `% 100 < 55` | no | **49.5%** |

So the split is not "modulus vs magnitude" but something sharper:

> A check is **permanently blind** iff its modulus divides 256, or its verdict is constant.
> Everything else sees a difference that averages close to a coin flip.

`% 4` and `% 16` are blind *for every value of c*, exactly 0% — not merely usually. That is why
almost everything the target *does* can never separate siblings, no matter how long you wait.

> **Not** "the low bits are discarded". Every bit feeds the next state; the point is narrower —
> a *specific* difference of `k · 2²⁴` is preserved as `256 · c` in the roll, and `256 · c` is
> invisible to a modulus that divides 256 whatever `c` happens to be.

Frame-siblings have no such problem: adjacent frames differ in the low bits, every modulus sees
it, and move choices alone separate them quickly.

### Why this surfaced now

`second_window` defaults to 0, so a normal run only ever holds frame-siblings. The RTC second is
pinned by `rtc_offset_seconds` instead. Second-siblings appear when the window is **widened**
mid-run — the recovery path for "the reported turn matched nothing". So this is specifically the
cost of widening, and the fix belongs next to it.

---

## 2. The sharpest tool: a move that can miss

The accuracy check is the only `% 100` roll we control the timing of. And here is the part that
makes it a free win rather than a trade:

> **A 100%-accuracy move still spends the accuracy roll.** `move_roll_cost` charges one roll
> whenever `accuracy > 0`, and the verdict is always "hit". The information is **destroyed, not
> absent** — identical RNG cost, zero signal.

Lower the accuracy and the same roll becomes an observation. Measured over 120 strict
second-sibling pairs (same delay, difference exactly `2²⁴`), playing one filler move every turn
against the Phase 2 fixture, counting turns until the rendered token streams differ:

| filler | accuracy | separated | median turns | max |
|---|---|---|---|---|
| Mean Look | 0 (bypasses the check) | 84/120 | 13 | 30 |
| Sweet Scent | 100 | 66/120 | 14 | 28 |
| **Hypnosis** | **60** | **120/120** | **1** | **6** |
| **Sing** | **55** | **120/120** | **1** | **5** |

[measured, simulator]

A median of **1 turn against 13**, and no failures against roughly a third. The 100%-accuracy
fillers separate only when something else leaks — chiefly Aurora Beam's 10% Attack drop, chosen
one turn in four and straddling the threshold about a fifth of the time.

Note Sweet Scent does *worse* than Mean Look despite having an accuracy roll, which is the point
restated: a roll that always says "hit" is noise, not signal.

### The part that makes it genuinely free

Against an already-paralyzed target a sleep move **always fails** — non-volatile statuses are
mutually exclusive — **and still rolls accuracy first.** Verified in `test2.jsonl`:

```
roll ??                              <- wild move selection
roll BattleControllerPlayer_BeforeTurn  x4
roll BattleSystem_CheckMoveHit       <- the accuracy check happens anyway
MSG: SMEARGLE used Spore!
MSG: But it failed!
```

`BattleSystem_CheckMoveHit` fires *before* "But it failed!". So Sing against a paralyzed Suicune
is a **pure information probe**: guaranteed no state change, guaranteed to spend the roll,
guaranteed to tell us something. The two outcomes render as `M1-` (missed) and the bare `M1`
(went ahead, did nothing), and they cost the same advances.

Smeargle can Sketch one — or it can live on any other party member, since switching costs no
advances and Phase 1 allows it.

### Picking the accuracy

**Accuracy nearest 50 is the best separator** — 49.5% at 55, 48.0% at 60, 17.9% at 10, 0% at 100
(table above). The intuition is plain once `c` is understood to roam: the threshold splits the
range, and a split nearest the middle is likeliest to fall between two values that are far apart
in an unpredictable direction.

Sing (55) and Hypnosis (60) are therefore near ideal. Thunder (70) is worse, and is a damaging
move that would kill a 1-HP target anyway.

**Do not** reach for lowering our own accuracy or raising the target's evasion to make a
100%-accuracy move missable. It works in principle — `can_miss` is computed against
`accuracy_net_stage`, not assumed from the move — but it costs turns to set up and the stage
shifts the effective threshold away from 50.

---

## 2a. Ball throws are nearly as good — and that argues for allowing them in Phase 1

The shake check is `roll < b`, a **magnitude comparison**. It has no modulus to be blind to, so it
sees the sibling difference 44.5% of the time — within a few points of a 55%-accuracy move's
49.5%. Measured over the same 120 strict sibling pairs, throwing the capture ball every turn:

| probe | separated | median turns | max |
|---|---|---|---|
| Sing (accuracy 55) | 120/120 | 1 | 5 |
| **capture ball throw** | **120/120** | **2** | **8** |
| Mean Look / Sweet Scent (accuracy 0 / 100) | 66-84/120 | 13-14 | 30 |

[measured, simulator]

Attributing the *first* divergence: 97% of the time it is the shake count itself (`C2` vs `C1`,
`C0` vs `C1`), not the target's turn. So the throw is doing the work, not luck elsewhere.

This is a real argument for lifting the Phase 1 ball ban rather than a curiosity. But the two ball
kinds have opposite risk profiles, and conflating them is what the current blanket ban does:

**The capture ball is always safe to throw.** If it lands you have won; the only cost is the ball.
So there is no correctness reason to forbid it in Phase 1 — only an inventory one, and for an
Apricorn ball like the Fast Ball that inventory may be a handful. Worth confirming against the
real supply before leaning on it as a routine probe.

**A standard Poké Ball is cheap, plentiful, and can lose the run** (sec 2.3: a plain ball is also
×1 on Suicune, so one that lands catches it in the wrong ball). The risk is small, quantifiable,
and already computed per-candidate by `hunt_session.standard_ball_risk`:

| target state | shake threshold `b` | P(catch) per throw |
|---|---|---|
| **full HP, no status** | 16643 | **0.35%** |
| full HP, paralyzed | 16643 | 0.35% |
| 1 HP, no status | 19784 | 0.80% |
| 1 HP, paralyzed | 21845 | 1.25% |

[measured, 4000 seeds each]

Which inverts the obvious instinct:

> **Probe with standard balls EARLY, at full HP, not late.** A throw costs 0.35% of the run before
> any chip damage and 1.25% once the target is at 1 HP and paralyzed — 3.6× worse. And a throw at
> full HP separates just as well, because `b` barely moves (25.4% vs 33.3% per roll) and the
> separation comes from the magnitude comparison, not from `b` being large.

At a median of 2 probe throws, early probing costs roughly **0.7%** of the run to resolve an
ambiguity that 100%-accuracy filler would spend 13+ turns on and fail to resolve a third of the
time. That is a good trade, but it is a trade, and it is the player's to make — so the tool should
show the live figure (it does) rather than decide.

**Why paralysis does not change the full-HP figure**: the status bonus and `b` are computed from
HP and status together, and at full HP the HP term dominates; `b` is identical with and without
paralysis there. So there is no "paralyze first, then probe" ordering benefit.

### What this means for the phase rules — **implemented**

Both balls are now legal in every phase. `Phase.balls_allowed` is deleted rather than pinned to
True, so the gate cannot quietly grow back, and what replaces it is disclosure:

* `HuntSession.standard_ball_risk` is reported in **every** phase, including Phase 1 and including
  a pinned seed — where it stops being a percentage and becomes a verdict, which is the most
  actionable it ever gets.
* `HuntConfig.standard_ball_matches_capture_ball` says whether this matchup is the dangerous one,
  so the warning states the player's actual case rather than always the harsher one.
* `Session.rank_actions` ranks balls alongside moves, on information alone. A standard ball's
  chance of ending the run is priced nowhere in that score, which is exactly why the risk sits
  beside the ranking instead of being folded into it.

It also makes Phase 1.5 less of a distinct phase: "throw the capture ball to pin the seed" is
simply the best information-gain action, which is what Phase 1.5 already ranks for.

## 3. Why we cannot simply solve for all of them at once

The tempting alternative is a **conformant** plan: one action sequence that captures every
candidate, so identification never matters. Measured, it barely exists.

For Suicune at 1 HP and paralyzed in a ×1 ball the shake threshold is `b = 21845 / 65536` (≈ 1/3),
so a capture window — four consecutive rolls under `b` — occurs about once per **125 advances**.
Not rare. But:

> Only **2%** of a seed's capture windows fall at the same offset in its one-second sibling.
> [measured, simulator]

So a path threads a window that the sibling almost certainly does not share. Replaying each seed's
own minimum-distance path against its sibling:

* **0 of 80** pairs captured both.
* **0 of 60** five-seed sibling sets captured all five.
* First *observable* divergence: median turn 6.

The solver isn't at fault — it minimises distance, so it threads the earliest cheap window, with
no reason to prefer a shared one. A search that deliberately looked for a shared window would do
better than 0%, but with ~0.3 expected shared windows per 2000-advance horizon for a *pair*, it
would still fail most of the time and essentially never for five.

**Conclusion: separate first. Do not plan around not knowing.**

---

## 4. What the tool must not do

Two bugs here were the same mistake, and both destroyed separating information rather than merely
being inconvenient:

1. **`guaranteed_fail` read as "nothing to ask".** It only means that when the move *also* cannot
   miss. A doomed missable move has two distinguishable outcomes, and suppressing both made Sing
   unreportable — throwing away the best separator we have. Fixed; the rule is now "ask whenever
   `can_miss`, and separately offer the failure only when it is doomed".

2. **Treating a 100%-accuracy move's roll as uninformative.** True, but the conclusion is to
   *change the move*, not to shrug. See section 2.

The general rule: **information costs rolls, and rolls cost turns.** There is no free separation —
a zero-advance action (an item, a switch) yields exactly zero bits. So turns are the currency, and
the only question is how many bits per turn.

---

## 5. Proposals, cheapest first

### 5.1 Readiness warning when nothing can miss [recommended, not implemented]

`battle.readiness` already warns about speed ties. Add: if no move on any party member can miss
against the target, and `second_window > 0`, warn that second-siblings will take a median of ~13
turns and may not separate at all — and name the fix ("a 50-60% accuracy status move on any
party member").

This is the highest value-to-effort item in this document. It converts a mid-run dead end into a
pre-run checklist line.

### 5.2 Rank Phase 1.5 actions by expected candidates eliminated [partly built]

The pinning phase already predicts what each action would emit per candidate. Score each by the
partition it induces (Gini or entropy over the predicted-token buckets, highest first) rather than
by anything else, and the "use the missable move" advice falls out automatically instead of being
a thing the player has to know.

### 5.3 Let Phase 2 be *configured* without a singleton [recommended]

Today Phase 2 wants one seed. It only truly needs one *before the throw*. Let it be entered with
k > 1, show the per-candidate paths, and gate only the throw on identification. Combined with 5.1
this dissolves the problem for the v1 fixture.

### 5.4 Conformant solve over a tuple of seeds [optional, low expected yield]

Lift the solver's state from one RNG to a *tuple* of RNGs advancing in lockstep under the same
action; goal = the ball captures in **every** component. Same Dijkstra, and `_dominance_key`
extends naturally. No branching for the player to read, and when it fires you capture without ever
identifying. Section 3 says expect it to work for maybe a fifth of pairs and never for five, so
this is a bonus, not a strategy.

### 5.5 Full contingent (AND/OR) policy [only if 5.1-5.3 prove insufficient]

The general answer, and worth stating correctly because the natural phrasing gets it backwards:

* **OR nodes are our actions.** One choice, shared by every candidate still in the set — we cannot
  condition on a hidden seed.
* **AND nodes are the observations.** We do not *choose* a branch; the game tells us which subset
  we are in, and we need a plan for every branch.

So the player is shown possible *outcomes*, not options. Precedent exists in this repo:
`machete_jane` builds exactly this shape for Safari, with `JaneNode` and `Fraction` probabilities.

Two things to decide before building it:

* **Greedy repair is not sufficient.** "Solve for seed A, then patch where B diverges" has no
  backtracking: because the first action must be shared, a path optimal for A alone can strand B
  (fainted, PP gone, window passed), and patching forward from the divergence cannot recover.
  The search has to be over belief states.
* **Cost metric.** The existing scalar distance (sec 12.7) prices turns against money for one
  seed. Over a belief set, prefer **worst-case (minimax)**: candidates are deliberately
  unweighted, and a run is one-shot with an irreversible failure mode.

---

## 6. Summary

* Second-siblings differ by `k · 2²⁴`, so their rolls differ by `256 · c`, invisible to every
  modulus dividing 256 — which is nearly everything the target does.
* A check is permanently blind iff its modulus divides 256 (`% 4`, `% 16`) or its verdict is
  constant (accuracy 100). Everything else — a sub-100 accuracy check, a secondary proc, the
  shake check's magnitude comparison — sees a near-coin-flip difference.
* A ~55% accuracy status move that is doomed to fail anyway separates them in a median of **1**
  turn instead of 13, with no state side effect and no extra advances.
* Ball throws separate almost as well (44.5% per shake check), so the Phase 1 ban should narrow
  to **standard** balls only — and standard-ball probing is 3.6x safer at full HP than at 1 HP,
  which inverts the instinct to probe late.
* Planning around *not* identifying does not work: only 2% of capture windows are shared, and a
  single path captured both members of a pair 0 times in 80.
* So: **make the seeds separate, rather than making the solver tolerate them.**
