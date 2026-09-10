# Refined chart — design notes

Working notes for reshaping the `chart/` tool around the probabilistic timer
calibration (Section C/D of the Metronome Compass notebook,
`utils/calibration_tools.py`, data in `data/compass_runs.jsonl`).

Status: **partially implemented** (epic `clayton-abf`). Done so far:
- **§2–3 model API** — `claytonlib/calibration.py::CalibrationModel` (mean F_b, σ_jitter(M),
  σ_band(M), predict/solve/hit_probability, save/load); `utils/calibration_tools` fits it
  (`build_calibration_model`, `export_calibration_model`).
- **§3 kernel** — `claytonlib/chart/evaluation.py::CalibratedLandingWindow` (σ(M)-width
  Gaussian; drop-in EvaluationStrategy).
- **§5.5 provenance** — `save_compass_run` records fresh_boot + prior_battles;
  `calibrate_timer(fresh_only=True)` excludes battle-contaminated runs from the fit.
- **§4 safari save** — `save_safari_run` / `load_safari_runs` → `data/safari_runs.jsonl`.
- **§4 loop-back** — each saved run refreshes `data/calibration_model.json`;
  `Expedition.calibration_model()` reads it.

Still open: **§6 chain ±K coverage** (on-disk chain-format change; gates the ranking/report
work), the ranking/report itself, the uncertainty-reporting layer, and the data-gated pieces
(reboot-fresh σ(M) sweep; safari-vs-metronome offset). Real fit today (34 runs):
σ_jitter ≈ 0.128·√M.

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

### 6.5 DECIDED design — "swap the axes" (second → wide frame band)

Supersedes the "±K seconds per frame" framing of 6.2. Instead of indexing by
frame and storing N seeds per frame, **index by RTC second and give each second a
wide band of frames**:

- A "link" is still **one row per RTC second** (append-one-per-second → still
  resumable), but each row is now a **1-bit-per-frame** bitmask of
  `capture(calculate_seed(T, D))` over a band
  `D ∈ [center(T)−W(T), center(T)+W(T)]` — dropping the old 2-bit seed_a/seed_b
  duality.
- **Multi-seed-per-frame is free via row overlap**: since `W(T) ≫ 60`, consecutive
  seconds' bands overlap, so a given absolute frame is covered by many rows
  (= many candidate seconds/seeds) without any per-frame variable structure.
- **Query-aligned**: the scorer, given commanded M, fixes the RTC second `T*(M)`
  (RTC crystal is stable) and integrates capture over the frame band with the σ(M)
  kernel — exactly one row's contents.

**Why this shape (measured on the real metang config):** the success mask is
**~21.7% dense** (not sparse → a bitmask beats a sparse list) and costs
**~13 ms/seed** (machete criterion → **compute, not storage, is the bottleneck**).

**Decoupling (critical):** the stored capture grid is **calibration-independent**
— band `W(T) = ⌈k·c_ceiling·√M(T)⌉` uses a fixed conservative ceiling, not the
live σ. The live σ(M) kernel is applied **at scoring time** (cheap), fitting
inside the stored band by construction. So loop-back σ updates do **not**
invalidate the expensive chains; only raising the ceiling does (an explicit,
versioned re-precompute).

**Chosen parameters / format:**
- Band policy: **k = 3.5, c_ceiling = 0.16** (~25% margin over today's 0.128).
- Storage: **binary bitmask rows + a JSON sidecar header** (format version, band
  policy, setup/max seconds, row-width formula). Fixed-max-width padded rows keep
  O(1) seek/resume; the header makes it self-describing and re-tunable.

**Open worry — compute feasibility:** widening from 2 seeds/frame to a
hundreds-wide band multiplies an already-expensive precompute (~4–7× more
seeds/second on top of 13 ms/seed). Full-range charting may be infeasible by
brute force; likely need to limit the charted band to promising regions and/or a
cheaper coarse criterion. Tracked separately (abf.11) from the representation
work.

### 6.6 Canonicalize by mdmsh (the reuse the old chains had)

`capture` is a **pure function of the seed**, and in the chart's model
`seed = (mdms<<24 | hour<<16) + delay` with `mdms = (month·day+min+sec)&0xFF`
(no year term). key_seed **fixes the hour** and pins `mdms`, so — measured on the
real metang config — its **2858 candidate times share hour=21 and one mdms_base**;
at second-offset 0 they give **one identical seed**, and as the offset advances the
minute/second rollover phase splits them into only **~1–4 distinct seeds** per
(row, frame). The whole 2858-time chart is therefore **~2–4 grids' worth of
distinct seeds, not 2858** — the distinct-seed set is bounded and essentially
independent of the candidate-time count.

The **old** chart captured this (evaluate_chain_link_cached deduped identical
links across all concurrent chains per batch). A naive per-datetime
`GridFile.generate()` would **throw it away** (~2858× redundant work). So the
store is **keyed by `mdmsh = (mdms, hour)`**, not by datetime:

- **Phase 1 (generation, minimal):** `capture[mdmsh] → {frame-range bitmasks}`.
  Enumerate every (candidate time, second-offset) → its `mdmsh` and band
  `center±W`; accumulate per-mdmsh the *union* of frame ranges (disjoint, since a
  given mdmsh recurs ~every 256 s at a much higher frame); evaluate `capture` once
  per distinct `(mdmsh, frame)`. Irreducible minimum (~one grid, not 2858×).
- **Phase 2 (scoring/convolution):** candidate M → datetime → `(mdmsh, center
  frame)` → look up the map over `[center ± kσ(M)]` → convolve with the σ(M)
  kernel. More indirection than a flat row, but small and bounded per query.

Swap-axes primitives (`BandPolicy`, `pack_row`, bit math) carry over; only the
store's **keying** moves from per-datetime second-rows to mdmsh → frame-ranges.

**Prototype + measured (claytonlib/chart/canon.py, metang, setup 300 / max 900,
k=3.5 c_ceiling=0.16):** 2858 candidate times → **254 distinct mdmsh** →
**2,085,318 distinct seeds**, vs 1.5 B naive per-time-grid evaluations = **721×
reuse**. Enumeration (Phase 1a, no eval) 1.8 s. Precompute @13.2 ms/seed ≈ **7.65 h
canonical vs ~230 days naive** — feasible as a one-time offline run, amortized
further by the persistent `SeedCache`. `canon.py` provides `needed_ranges`
(enumerate), `SeedCache` (persistent memo), `build_canon` (evaluate →
`CanonMap.captured(mdmsh, frame)`). Remaining abf.11 levers: cheaper coarse
criterion, parallelism.

**Persistent offline precompute (landed):** `CanonStore` (append-one-JSONL-line-
per-mdmsh + a `.meta.json` config signature) + `precompute_canon` make the ~7.65 h
run **resumable** — a crash costs at most the one mdmsh in progress, and re-running
skips done mdmsh (config-signature-checked so resumes can't mix configs). `CanonMap.
save/load` round-trip the map. Demonstrated on a real metang 2-second slice: 3,822
seeds / 6 mdmsh / 953× reuse / 49.8 s cold, artifact ~1.2 KB, **resume 0.01 s** vs
49.8 s cold; full map projects to ~0.5 MB.

**Phase 2 scorer (landed) — `claytonlib/chart/scorer.py`:** resolves a commanded M
→ mean frame F* → its RTC second → mdmsh, then `capture_probability` integrates
the CanonMap's bits at that mdmsh against the σ(M) landing kernel (jitter, or
jitter+band via `include_calibration`); `rank_targets` sweeps target frames (each
with `M = model.solve(F)`), `distinct_targets` de-clusters, `print_target_report`
prints the best commanded countdowns. Because σ grows with M it auto-prefers wide
capture plateaus over lone spikes and reports honestly lower P far out. Demonstrated
end-to-end on real data (16 s slice, real fit): ranked M's with P(capture) and σ.

**Expedition orchestration (landed, additive):** `Expedition.precompute_chart()` drives
`precompute_canon` from the config (key_seed → base_delay + candidate times, setup/max,
pokemon/strategy/criteria) into a resumable `CanonStore` under the chart dir;
`Expedition.chart_report()` loads that map + `calibration_model()` and prints ranked
commanded countdowns. Real ETAs (machete criterion, ~13 ms/seed): **200–600 s ≈ 4.2 h**
(1.15 M seeds), **200–900 s ≈ 8.5 h** (2.32 M seeds), 721× reuse, resumable. Note:
calibration is well-fit to ~600 s (runs span M ≤ ~595 k); longer targets extrapolate
(σ_band widens) until longer runs are collected. **Retirement of the old packed-chain
path (chart_safari/evaluate_chart/choose_target + chain.py + old strategies) is staged** —
it's entangled with the interactive `choose_target` UX and the persisted `eval_strategy`
config, so it needs a small UX decision before deletion; the new path is additive and
primary in the meantime.

**Incremental extend (landed):** the store is now per-(mdmsh, frame-range) and its config
signature omits setup/max, so a precompute over a wider second range appends only the new
frame gaps on top of an existing store — no re-evaluation. `precompute_canon` computes
`needed_ranges` for the current [setup,max], subtracts the store's `done_coverage()` per
mdmsh (interval subtraction), evaluates only the gaps, and reports `evaluated_this_run`.
Verified on real data: [300,302]→6,378 seeds, extend→[300,305] evaluated only the 7,684
new (0 re-done), re-run 0 (idempotent). So **200–600 (4.2 h) then extend to 900 costs only
the incremental ~4.3 h**, not a fresh 8.5 h. (Same mechanism finer-grains crash-resume:
a crash now loses at most one frame-range, not a whole mdmsh.)

**Parallelism (landed):** `precompute_canon(..., workers=N)` evaluates each range's seeds
across a fork-based process pool (evaluate_seed is CPU-bound + GIL-blocked, so processes not
threads; fork inherits the unpicklable strategy/criteria closures without pickling). Results
still append per range in order, so resumability/idempotency are unchanged.
`Expedition.precompute_chart(workers=None)` defaults to all CPUs and prints timestamped
progress with a rolling ETA. Measured 4.6× on 12 cores for a machete-criterion slice
(sub-linear from per-range barriers on tiny ranges; larger runs scale better) → **200–600 s
≈ 55 min, 200–900 s ≈ 1.85 h** wall-clock. Further scaling (coarser batching across an
mdmsh's gaps) is a possible future tweak.

**initial_time is an OUTPUT of charting.** key_seed is chosen up front; the boot datetime is
what the chart *finds*.  So `Expedition.chart_report()` defaults to **mode A** — rank the
best **(boot time, commanded M) pairs** across all candidate boot times (`scorer.rank_over_times`
+ `print_pairs_report`); capture depends only on the target second's mdmsh (≈1–4 across the
2858 candidates), so this is cheap (~5 s).  Pass `initial_time=` for **mode B** — the best M
for a specific preferred boot time (`rank_targets`/`print_target_report`), which must be
RNG-consistent with key_seed (same hour) or it's rejected.  (Bug fixed: the parser now
accepts ISO 'T'; and mode A no longer needs a single fixed datetime, so the earlier
hour-mismatch fallback is gone.)

**Findings persistence + target selection.** `chart_report()` idempotently writes its ranked
rows to `chart_report.json` in the chart dir (overwrite, no append).  A **separate** step,
`Expedition.select_target()` (the new choose_target), reads that file and asks how to pick:
**[t]** from the top ranking (by rank number) or **[s]** a specific starting time (typed,
year ignored, looked up among the per-starting-time bests).  It records the choice:
`initial_time` = boot datetime, `target_timer_delay` = commanded M (calibration 0),
`target_delay` = expected F_b — then saves.  The Expedition Workflow notebook's "Choose
Target" cell calls `select_target()`.

A single `chart_report()` call (mode A) saves **two** sections to `chart_report.json`: `top`
= the top-N overall (boot time, M) pairs (also printed), and `per_initial_time` = the best
target for EVERY candidate starting time (one row each, ranked by its best P — ~2.5 k rows).
One `rank_over_times` sweep feeds both: `best_per_scenario` → overall, `rank_boot_from_scored`
→ per-starting-time.  Cheap (~5 s).  `select_target` reads the `top` section.

**Year handling (DECIDED — option 2, implemented):** the calibration model predicts
**dF = F_b − F_a** (year-agnostic), and the actual battle-seed low16 is reconstructed as
`frame = dF(M) + F_a`, where `F_a = key_seed & 0xFFFF` is the low16 of the *identified*
initial seed — which already carries `year−2000` in `CCCC`. So the chart's `(mdmsh, frame)`
space now uses the **actual** frames (year folded into `frame` via `base_delay`); `mdms`/`hour`
stay year-independent. This is year-correct in any year and lets one calibration data set be
reused across target years (only `key_seed` changes with the year, not the fit).

Mechanics: `CalibrationModel.target == "dF"`, and every place a prediction becomes a canon
frame calls `model.frame(M, base_delay)` / `model.solve_frame(F, base_delay)` (scorer, canon
`needed_ranges`, compass `from_expedition_target`, expedition `select_target`/`compass_safari`/
`chart_check_target_landing`). A legacy `target=="Fb"` model ignores `base_delay` (back-compat).

Why not option 1 (add `year−2000` at the boundary): equally accurate (LOO-CV: dF vs F_b within
noise, F_a only wobbles ~14 frames), but option 1 bakes in a fixed year; option 2 removes year
as a concept structurally. The canon is unaffected per-seed (capture is year-independent given
the actual seed), so the model left the CanonStore signature — switching to dF extends the store
incrementally (the ~25-frame shift is covered by the wide bands) instead of forcing a rebuild.
⚠️ **Never feed a raw `model.mean(M)` (a dF value) as a seed frame — always go through `frame()`.**
