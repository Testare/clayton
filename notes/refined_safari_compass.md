# Refined safari-compass — design notes

Adapting `claytonlib/compass` (safari seed identification) to the calibrated charting model
(see `notes/refined_chart.md`).  Kept separate from the metronome compass.

Status: **design / brainstorm.** Tracked under the compass-safari rework epic (`clayton-b70`).

**Implementation progress:**
- ✅ **b70.1** — calibrated `(second, frame)` candidate generator (`_generate_candidates_calibrated`
  in `compass/_core.py`).  `_generate_candidates` now dispatches: calibrated when `frame_center`
  is set, legacy delay-window + seed_a/seed_b otherwise (kept for un-migrated callers).  The old
  seed_a is exactly the canonical scorer seed; seed_b is dropped (the RTC second is now the δ axis).
- ✅ **b70.3** — `CompassSafariInput.from_expedition_target(model, M, …)` (new explicit fields
  `frame_center`/`sigma`/`target_second`/`second_offsets`/`k`); `expedition.compass_safari()` prefers
  it, falling back to the legacy path when no model / commanded M is available.
- ✅ **b70.2** — ±K second axis: `second_offsets` covers δ∈{−1,0,+1} (configurable via
  `expedition.compass_safari(second_offsets=…)`), each δ using the SAME frame window; the
  identified seed reports which δ was hit ("timer on time / +1s late / −1s early").
- ✅ **b70.4** — landing prior `P(δ)·Normal(frame; F*, σ)` per candidate (`calibrated_candidates`
  returns `meta[seed]={frame,delta,prior}`); survivors ranked by posterior = prior_i /
  Σ prior_survivors and shown with P%; a `confidence_threshold` (default 95%) flags "likely
  identified".  Capture-success is NOT a prior.  Prior model: discrete-Gaussian over δ
  (`second_offset_sd`, default 0.6 ⇒ P(±1)≈17%) × the frame Normal.
- ✅ **b70.6** — graceful widen: on no-match (or `w` on request) prompt to widen the frame
  window (`k`) and/or the second window (`±K`), regenerate, and re-apply the observed path via
  `_replay_path` — no narrowing progress lost.
- ✅ **b70.7** — loop-back: `save_safari_run` is calibrated-aware — it recovers the identified
  seed's `(frame, RTC second, δ)` from the candidate meta, reports the inferred timer offset
  (e.g. "+1s late"), and records `frame`/`second`/`second_offset` (M via the timer fields) to
  `data/safari_runs.jsonl` — no capture required.  `expedition.save_safari_run()` wires it in.
- ✅ **b70.5** — candidate-set bounding: `CompassOptions.mass_cap` trims the sweep to the
  highest-prior seeds covering that share of the landing mass (`expedition.compass_safari`
  defaults 0.999; e.g. 1698→890 at 0.95 on the real model); the Jane offload now triggers on
  the prior-weighted `_effective_count` (seeds carrying `jane_mass` of the posterior), not raw
  count, so it fires once observations concentrate the mass — not on the wide pre-observation set.
- 🔮 b70.8 (FUTURE: safari-compass calibration runs, P4) — unblocked by b70.7, intentionally
  deferred until compass-safari has field use.

---

## 1. The shift

Today `compass_safari` generates candidates as a **delay window around one `target_delay`,
with two seeds per delay** (seed_a = current RTC second, seed_b = next second), then narrows
by observed safari steps (mud / bait / shakes / flee / capture).

The new charting reframes a target as **(boot `initial_time`, commanded countdown `M`)** →
a mean battle frame `F* = model.mean(M)` with a Gaussian spread `σ(M)` at a fixed RTC second
`T*`.  Identification must therefore search a much larger, differently-shaped candidate set —
but we now have a **probabilistic landing model** to prioritize it.

A candidate seed is `calculate_seed(initial_time + second, frame)`.

---

## 2. Necessary changes (the new model forces these)

1. **New candidate generator — `(second, frame)` sweep, not `delay ± window`.** Sweep
   `frame ∈ [F* − kσ, F* + kσ]` at second `T*`; one concrete seed per `(second, frame)`.
   Replaces `_generate_candidates`'s delay loop.
2. **Drop the seed_a/seed_b duality.** The RTC second is now an explicit axis, so the
   "did the second tick" pair is subsumed. `_seed_reachable` / `_delay_offset_to_second_frame`
   get rewritten around `(second, frame)`.
3. **±K second axis, with the SAME frame window at each second (independent axes).** Cover
   `δ ∈ {−1, 0, +1}` (configurable) for off-by-one timing.  **Do NOT shift the frame center by
   `δ·rate`** — measured on the calibration data, the second-offset is *decoupled* from the
   frame value (`corr(resid_Fb, resid_elapsed) ≈ 0.19`, slope ≈ 39 fr/s vs the ~60 a coupling
   would give).  The offset is driven by **timer-start timing**, not the countdown duration, so
   the frame distribution is the same `[F* − kσ, F* + kσ]` at every δ.
4. **Window sized from `σ(M)`, not a fixed delay window** — half-width `kσ` (or a probability
   mass target); `window` becomes `k`/mass, not a raw delay count.
5. **Input plumbing from the chosen target.** A `CompassSafariInput.from_expedition_target(...)`
   that pulls `initial_time`, `M`, `F*`, `σ`, `T*` from the expedition + calibration model,
   instead of a hand-set `target_delay`/`window`.  Prefer **new explicit fields**
   (`target_second`, `frame_center`, `sigma`, `second_offsets`) over repurposing `target_delay`.
6. **Handle the much larger candidate set** (~K seconds × ~2kσ frames ≈ 1.4k–2.1k+ seeds,
   growing with M): don't dump the whole list to the terminal; keep narrowing incremental;
   retune the `Jane` auto-offload threshold (§3.9).

---

## 3. Probabilistic enhancements (the payoff)

7. **Prior per candidate:** `P(δ) · Normal(frame; F*, σ)` — the landing likelihood of each seed
   (same frame window at each δ per §3).  Capture-success is **irrelevant** to *which* seed you
   hit and is not used as a prior; machete/Jane handles turning a hit into a capture.
8. **Rank survivors by posterior; show most-likely first with P%.** Posterior over survivors is
   `prior_i / Σ prior_survivors` (replaces sorting by delta).
9. **Report the most-probable seed when several remain** — "most likely `0x… (63%)`, then
   `0x… (24%)`" — and allow accepting the top one, instead of just "N seeds match".
10. **Confidence-threshold early stop.** If the top survivor's posterior exceeds a threshold
    (e.g. 95%), suggest you're done without full narrowing.
11. **Prioritized / lazy simulation + probability-mass window.** Simulate high-prior candidates
    first and trim the Gaussian tails to a mass cap (e.g. 99.5%), bounding the ~2k-seed cost so
    the likely answer surfaces fast.
12. **Graceful widen prompt (keeps path progress).** When nothing matches (or on request),
    prompt to **widen the frame window OR the second window**, regenerate the expanded candidate
    set, and **re-apply the observed path so far** so no narrowing progress is lost.  The prompt
    controls how much to widen each axis.
13. **Second-offset inference as feedback.** Once identified, report which δ you actually hit
    ("you were 1 second late") — timing feedback and a check for systematic bias.
14. **Loop-back into a SEPARATE safari dataset.** Save the identified seed + the **observed path
    (as entered)** + `(M, frame, second, δ)` to `data/safari_runs.jsonl` (already distinct from
    the metronome `compass_runs.jsonl`), **without requiring a capture**.  Retuning the model
    from this data is future work.

*(Dropped: a "best next observation" optimizer — Jane already covers deep search when the
candidate set is small enough.)*

---

## 4. Open decisions (recommended defaults)

- **`P(δ = ±1)`** — a fixed parameter to start (e.g. ~15 % each); later estimate it empirically
  from §3.13's inferred offsets.
- **Window bound** — trim to a probability-mass target (bounded, prior-aware) rather than a
  fixed `kσ`.
- **Field design** — explicit `target_second` / `frame_center` / `sigma` / `second_offsets`
  with a from-target constructor, not repurposed `target_delay`/`window`.
- **Capture-success is not a prior** — only the landing distribution is.

---

## 5. Data note — second/frame decoupling

Measured on `data/compass_runs.jsonl` (34 fresh-boot runs): after removing the `F_b`-vs-`M`
trend, the frame residual (σ ≈ 89 frames) is essentially uncorrelated with the elapsed-second
residual (`corr ≈ 0.19`; slope ≈ 39 fr/s, not the ~60 a tight coupling implies).  Hence §2.3:
the ±1-second offset is its own axis and does not shift the frame center.  (n=34, elapsed is
±1 s-granular — worth revisiting as more data arrives.)

---

## 6. Future — safari-compass calibration runs

An analog of the Metronome Compass Calibration, but using the **safari** compass: do actual
runs **without requiring hitting the intended seed first**, purely to collect data on which
seeds we actually land on (M → observed seed/frame/second).  Builds the safari-side landing
dataset for retuning σ/β and the `P(δ)` prior.  **To be done AFTER compass-safari is in good
shape** — tracked as its own (deferred) bead.
