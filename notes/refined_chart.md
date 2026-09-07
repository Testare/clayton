# Refined chart — design notes

Working notes for reshaping the `chart/` tool around the probabilistic timer
calibration (Section C/D of the Metronome Compass notebook,
`utils/calibration_tools.py`, data in `data/compass_runs.jsonl`).

Status: **ideas / brainstorm.** Nothing here is implemented yet. We are still
collecting calibration runs (sweep 3→10 min).

---

## 1. The core mismatch with today's chart

The chain-generation half of the tool is fine and stays: for each candidate
datetime it simulates capture success per seed and packs the result into a
per-second bitmask (`chart/chain.py`). The problem is the **scoring layer**
(`SlidingWindowSum`, `NormalWindow` in `chart/evaluation.py`):

- Those kernels model the player's timing error as a **fixed-width** window —
  the *same* spread whether you aim at a 60 s target or a 600 s target.
- Calibration says that's wrong in the way that matters: physical jitter grows,
  roughly `σ(M) ≈ c·√M`. A fixed window is **too wide early** (understates
  achievable probability, blurs good short targets) and **too narrow late**
  (overconfident probabilities for far-out targets — exactly where we've been
  collecting 300–600 s runs).

## 2. The conceptual shift: rank control inputs, not clock times

Today the chart is indexed by `(initial_time, delay)` and hands you "aim for
HH:MM:SS at delay D." But what you actually *control* is the commanded countdown

```
M = target_timer_delay + target_timer_calibration   (ms, calibration signed)
```

and calibration already gives the map `M → distribution over F_b`. Compose the two:

```
P(capture | commanded M) = Σ_F  P(land on frame F | M) · capture_success(F)
```

- `capture_success(F)` — the straightened per-frame success mask the chart
  already produces (keep the seed_a / seed_b RTC-phase blend).
- `P(land on F | M)` — `Normal(mean = β·M + α, sd = σ(M))` straight from
  `calibrate_timer`.

The chart output then becomes **"set your timer to X"** with an honest capture
probability — which is the actionable thing, and it's already what Section D
computes for a single target. Reshaping = generalizing that convolution across
the whole success mask and ranking achievable M values.

## 3. Concrete mechanics

1. **New `EvaluationStrategy`: `CalibratedLandingWindow`.** Same interface as
   `NormalWindow`, but the Gaussian sigma at each frame is `σ(M(delay))` instead
   of a constant. Drop-in via the existing `score()` contract; the rest of
   `evaluate_chart` is untouched. This alone fixes the heteroscedasticity.
2. **Rank by expected capture, not opaque score.** Replace/augment top10/best10
   with a table of commanded countdowns: M (+ the actual timer setting to dial),
   expected F_b with 95 % landing range, `P(capture)`, and the clock time/delay
   for cross-reference.
3. **Report robustness separately.** We already split reducible (calibration/rate
   band) from irreducible (physical jitter). Surface both per target: `P(capture)`
   at best-estimate calibration, plus sensitivity to calibration error
   (`dP/dcalibration`, or P under ±1 calibration-σ). Tells you whether a target is
   a safe plateau or a knife's edge.
4. **Favor plateaus over spikes automatically.** Because σ grows with M, the
   convolution down-weights a narrow spike of success frames far out and rewards
   a contiguous success region at least ~σ(M) wide. Falls out for free.
5. **Don't inflate by the ±1 s granularity.** That's an estimator artifact for
   *measuring* rate, not a spread you face at play time. Use physical jitter σ(M)
   only.

## 4. Open decisions (change the design — user's call)

- **Single fixed rig — one global fit.** There is one DS console and (for now)
  one consistently-used timer computer, so β, σ(M), *and* α are all fit **once
  from the pooled data** — no per-machine bookkeeping. Tags are just run labels.
  If a real systematic session-to-session drift ever shows up (see 5.2), α can be
  re-pinned with a short calibration run; until then treat it as a single
  constant.
- **Timer quantization** *(RESOLVED — not needed).* M is **continuous**: the
  user types an arbitrary millisecond value, and although the app beeps at a fixed
  interval, the beeps are phased so the **last beep lands exactly on the typed
  value**. So there is no aim grid — treat M as a continuous control variable. The
  only residual is the human reaction at that final beep, which is ordinary
  trigger-timing jitter (the roughly-constant, non-M-growing term seen
  within-session, ~0.4–0.65 s) already absorbed by the fit. No grid modeling, no
  ±half-step term. (The `notes/compass_runs.md` "one beep too early" note was a
  one-off misfire, not evidence of a grid.)
- **Closing the loop with `expedition`** *(accepted — promote to work).* Each run
  yields `(M, F_b)`; feed it back into calibration to tighten the model live.
  **Safari caveat:** metronome-compass pins one seed reliably, but compass-*safari*
  often leaves a small candidate set — only loop a run back when it has narrowed
  to a **single** seed; always *save* the run regardless.
- **Safari vs metronome are different transition profiles.** The safari path has a
  **loading screen entering the Safari Zone** that the metronome path lacks. Like
  the ~800-frames-per-battle effect (§5.5), a fixed load likely adds a systematic
  α offset, so the two calibrations may **not** be interchangeable. Save safari
  runs (path + timer delay + suspected single seed) alongside metronome runs so
  the offset can be *measured* later rather than assumed zero.

---

## 5. The "≤2 seeds per hit frame" concern

**Concern (user):** the chain's structure — "if you hit frame b, it's one of at
most 2 seeds, depending on whether the RTC has crossed the second boundary" —
secretly relies on a *constant* frame rate to know which second a given absolute
delay lands in. With an irregular rate, the same delay could land in different
seconds across runs → more than 2 candidate seeds.

This is legitimate. The `≤2 seeds` count presupposes you know the delay↔second
alignment, and today that comes from the constant-rate `cumulative_frames()`
table. If the real rate drifts from 59.8261, that table is wrong, and the error
**accumulates over the countdown**.

### 5.1 What the data says

Same-commanded-M repeat runs are the direct test. From
`data/compass_runs.jsonl` (all "Smeagol", cal = −5000):

**Within one session, same M — run-to-run spread is small (≤ ~1 s):**

| M (ms) | F_b values | excess spread beyond F_a offset |
|--------|------------|---------------------------------|
| 210000 | 12615, 12690 | ~0.65 s |
| 540000 | 32585, 32615 | ~0 s |
| 600000 | 36165, 36178 | ~0.4 s |

Note it does **not** grow with √M here (0.4 s at 600 s < 0.65 s at 210 s) —
consistent with the residual being dominated by **human trigger timing + the RTC
±1 s granularity**, not runaway frame-rate randomness.

**Between sessions, same M = 300000 — spread is large (~seconds):**

- "Sweep" session:      F_b ≈ 18017
- "300k delay" session: F_b ≈ 18257, 18262   (+ one misfire at 18052)
- → ~240 frames ≈ **4 seconds** apart at *nominally identical* input.

### 5.2 Interpretation

The effect splits into two very different pieces:

1. **Systematic session offset (large, ~seconds).** With a single console and
   timer computer, this ~4 s gap is **not** a hardware frame-rate difference —
   it's session setup / technique (the "300k delay" runs likely used a slightly
   different trigger convention than the "Sweep" runs). The whole delay↔second
   map shifts several seconds. This *does* break a naive global constant-rate
   chain — but it is a **bias** that lives in α. In practice it's small enough to
   fold into the global α fit as scatter, and can be re-pinned with a short
   calibration run at the start of a session if it ever proves systematic.
2. **Random run-to-run jitter (small, ~1 s).** Within a session at fixed M, runs
   agree to ≤ ~1 second and don't clearly grow with √M. A hit frame therefore
   maps to a *few* candidate seconds, not dozens.

**Bottom line:** the "≤2 seeds" idea is not catastrophically wrong from
frame-rate *randomness* — that residual is only ~1 s (a few seconds). What is
genuinely broken is assuming **one global constant-rate alignment** across
sessions; the alignment drifts multiple seconds and must be re-derived per
session/console. A calibration-driven chart does exactly this: it stops treating
the delay↔second map as a fixed constant-rate table and instead derives its mean
(β, α) and spread (σ(M)) from that session's calibration.

### 5.3 Consequence for the redesign

- The landing distribution is really **2-D**: over *which second* (driven by the
  accurate RTC crystal — stable, ~±1 s, predictable from M) and *which
  sub-second delay* (driven by the jittery VBlank rate). Today's tool collapses
  both onto one constant-rate delay axis. The reshaped scorer should convolve the
  success mask against the joint distribution instead of a 1-D window.
- Because the RTC second is the *stable* axis and the delay counter is the
  *jittery* one, most predictive uncertainty in the seed comes through the delay
  counter, while the second index is comparatively pinned — a useful asymmetry to
  exploit when enumerating candidate seeds.
- With one fixed rig, β, σ(M), and α are all fit **once from all runs pooled**.
  A short per-session re-pin of α is available as a safety net if session drift
  ever proves systematic, but is not required by the current data.

### 5.4 Data we still need to nail this down

The current same-M repeats conflate different F_a offsets, possibly unrecorded
timer differences, and one likely misfire (18052) — and there are only 2–4
repeats per M. To cleanly separate the random run-to-run component (piece 2) from
session drift (piece 1):

- Log **several reboot-fresh runs at one fixed M** (e.g. 5–10 runs at 300 s and
  again at 600 s, **rebooting between each**). That isolates the true frame-rate
  random walk (the console's σ(M)) and tells us whether it really grows as √M —
  the single most useful measurement for the reshaped scorer. **Do not** collect
  these as consecutive battles in one boot — see 5.5.

### 5.5 Battle transitions suppress the frame rate (measured)

Attempted to collect same-session repeats as **consecutive battles in a single
boot** (tag "Consecutive Run 1": one `a_seed`, delay 689, battles at total-elapsed
M = 175 / 355 / 535 s). Against the sweep-fit line (`Fb ≈ 60.36·M/1000 + 256`):

| battles traversed before this one | net M | F_b | residual vs sweep |
|-----------------------------------|-------|-----|-------------------|
| 0 (fresh boot → first battle)     | 175 s | 10896 | **+77** (on trend) |
| 1                                 | 355 s | 20829 | **−856** |
| 2                                 | 535 s | 31075 | **−1475** |

The first battle from a fresh boot lands on the sweep line; each subsequent battle
falls ~**800 frames** (~13 s of frames) further behind. So **initiating/exiting a
battle costs ~800 frames** the overworld-waiting model doesn't account for — a
real physical effect, not a calc error. The consecutive-only slope is ~55–56 Hz
vs the sweep's ~60. The M-aware outlier detector **correctly** rejects runs 2–3.

Implications:

- **Consecutive-in-one-boot runs cannot calibrate the single-battle workflow.**
  Every battle after the first carries the accumulated transition deficit. Repeat-
  same-M jitter data must be **reboot-fresh** (one battle per boot).
- **The sweep protocol matches real play** (boot → one target battle), so the
  sweep-based model is valid for actual capture — *assuming the real route has no
  battle before the target encounter* (confirm this).
- **Record provenance per run**: fresh-boot flag + count of prior battles, so
  contaminated points are excluded by construction, not just by the outlier
  detector. (Feeds the save step in §4 / `save_compass_run`.)

---

## 6. Chain adjustments — the concrete chain-level change

Sections 1–5 are mostly about the *scoring* layer. This section is what changes
in the **chain** itself (`chart/chain.py`, `expand_chain_link`).

### 6.1 What actually breaks

A chain link enumerates each delay paired with only **two** adjacent seconds:

```
seed_a(j) = calculate_seed(T,   D + j)   # this second
seed_b(j) = calculate_seed(T+1, D + j)   # next second
```

That tolerates **±1 second** of misalignment between the delay counter and the
RTC. The true seed is always `calculate_seed(T_actual, D_actual)` — and if
frame-rate drift pushes the delay↔second alignment off by **more than 1 second**,
that pair is off by ≥2 seconds and its seed **isn't in the chain at all**.

The data (rig held fixed) puts the residual *random* drift at ~1 s, so today's
2-seed structure is *marginally* adequate now — but it's hardcoded at ±1 s and
will under-cover long countdowns where σ(M) grows.

### 6.2 The adjustment

**Generalize the 2-seed pairing to an M-dependent ±K.** Instead of pairing each
delay with `{T, T+1}`, pair it with `{T, T+1, … T+K}` — equivalently, widen each
second's delay band so neighboring links **overlap by K seconds' worth of
frames**. Then whatever `(T_actual, D_actual)` you land on,
`calculate_seed(T_actual, D_actual)` is guaranteed present.

- **K is driven by σ(M):** K≈1 for short targets (matches the current
  structure), growing to ~2–3 for ≥600 s countdowns. Set by plausible drift, not
  a constant.
- Two equivalent implementations: **(i)** more seed columns per delay
  (seed_a, seed_b, seed_c…), or **(ii)** widen each second's enumerated delay
  range to overlap its neighbors. Same coverage either way. (Note the packed
  bitmask in `evaluation.py` currently allots 2 bits/delay + a width bit; option
  (i) would need a wider packing or a different representation.)

### 6.3 What stays

- Link = one RTC second over its 59/60 delays; per-seed capture evaluation —
  unchanged.
- Constant-rate `cumulative_frames()` stays as the **mean/backbone and index** —
  still the best point estimate of the alignment. We just stop treating it as
  *exact* and add overlap around it.

### 6.4 Where the variance is actually handled

The chain's only new job is **guaranteeing coverage** (the right seed is present
to score). The variance itself lives in the scoring layer (sections 2–3):
convolve the success mask against the landing distribution over `(second,
delay)`, where the RTC second is nearly pinned by M and the delay carries the
σ(M) spread. Probability weight concentrates near the predicted `(T*, D*)`; K
just guards the tails.
