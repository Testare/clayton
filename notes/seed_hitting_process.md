# Hitting seeds: the timing process (t0–t3) and what it means for the model

How a run is actually executed on hardware, and the timing-error decomposition that tells us
how the RTC-second and the frame/delay can miss independently. This is the physical grounding
for the calibration model and the (planned) second-marginalization in the chart.

## The rig: EonTimer, 3 timers

EonTimer plays beeps leading up to each timer's end so button presses land consistently, then
auto-rolls into the next timer (and has calibration helpers). This project uses **3 consecutive
timers**, giving four moments:

- **t0 — set the DS clock + start EonTimer.** Set the DS to a chosen time and try to press the
  DS "set" button at the exact instant EonTimer starts. Then restart the DS, ready for timer 1.
- **t1 — boot the game** (timer 1 elapses). The frame/delay counter starts here (boot = frame origin).
- **t2 — load the game → Seed A** (timer 2 elapses). Seed A is generated at t2.
- **t3 — Sweet Scent → Seed B** (timer 3 elapses). During timer 3 you get into position
  (metronome: stay put, pick Sweet Scent; safari: enter the zone, do the RNG advances, reach the
  menu), then press Sweet Scent; the encounter fires and Seed B is generated.

**`vector_delay` (a.k.a. `M`)** = the duration of timer 3, which is **exactly** `t3 − t2`. Must be
≥ ~3 min (safari setup time), which is why the sweep starts at 3 min.

**The +0.2 s bias lives on the FIRST timer.** It shifts t1, t2, and t3 all later by 0.2 s
*together*, so it changes none of the differences (`t2 − t1`, `t3 − t2 = M`). Its point is to make
t2 land at `target_second + 0.2 s` — 0.2 s PAST the boundary — so being slightly early doesn't drop
you onto the previous second's seed (targeting :55 but hitting :54.95 gives the :54 seed even though
only 50 ms early). Because it shifts t2 and t3 equally, it cancels in the frame (`dF`) but not
necessarily in the RTC second (it can nudge Seed B's whole-second across a boundary — see below).

**Worked example (real target).** `M = 327591 ms` (5 min 27.591 s), targeting second **55** for
Seed A. With no error the whole run is `M + 55 + 0.2 = 382.791 s` (6 min 22.791 s) — that's t3.
Then t2 = 55.2 s (reads second 55), and `t3 − t2 = 327.591 s = M` exactly.

## Two clocks set the two coordinates of a seed

- **RTC second** (the DS wall clock) sets the `mds` byte via `(month·day + minute + second)`.
- **Frame/delay counter** starts at boot (t1) and advances at ~59.83 Hz.

So, in absolute terms:

| seed   | RTC second      | frame/delay     |
|--------|-----------------|-----------------|
| Seed A | `t2 − t0`       | `t2 − t1`       |
| Seed B | `t3 − t0`       | `t3 − t1`       |

Because we **identify Seed A exactly**, what matters for predicting Seed B is the A→B *relative*
pair:

- `dF = frame_B − frame_A = rate·(t3 − t2) = rate·M`   ← the calibrated `dF` model.
- `dS = second_B − second_A` = the whole RTC seconds in `[t2, t3]`.

## Error sources

- **δ0 — t0 misalignment:** the fixed offset between EonTimer's clock and the DS RTC, set once at
  t0 and constant for the whole run (DS clock-update lag, EonTimer start lag, not pressing both at
  once). Affects only the *RTC second*, never the frame.
- **ε1, ε2, ε3 — press lag at t1/t2/t3:** how late/early each actual press is vs the beep
  (audio + reaction lag).
- **φ2 — sub-second phase at t2:** where within its RTC second the t2 press fell (≈ uniform,
  uncontrolled). Determines whether the *next* boundary is crossed.

## The key decomposition (why frame ≠ second precision)

- **`dF` (frame) error ≈ `rate·(ε3 − ε2)`.** Both presses are on the SAME EonTimer clock, so
  *common-mode lag cancels*, and δ0 cancels entirely. The frame is therefore usually quite precise.
- **`dS` (second) ≈ `floor(M_actual/1000 + φ2)`, plus δ0.** It carries the frame's information
  (via `M_actual`) PLUS an independent phase term `φ2` (and δ0). The phase term is an extra degree
  of freedom the frame doesn't have.

Consequences, all consistent with what's seen in practice:

1. **The second is intrinsically noisier and more off-by-one-prone than the frame** (it doesn't get
   the common-mode cancellation, and it has the extra `φ2`/δ0 spread).
2. **A wrong second with a good frame is usually a δ0 / φ2 problem, NOT a frame problem** — you
   landed on the frame you intended, but a phase boundary or a mis-started timer shifted the
   second. You routinely see both "frame a touch late, second good" and "frame perfect, second one
   late."
3. **Therefore, when marginalizing capture probability over the RTC second, KEEP THE SAME FRAME
   CENTER across candidate seconds — do NOT recenter per second.** Conditioning on a different
   second barely moves `E[M_actual]` (the second's spread is dominated by the independent `φ2`/δ0,
   not by frame-length variation), so the intended frame is still the best center. [Empirically
   confirmed by the user; overturns an earlier "frame center per second" idea.]
4. **Frame jitter and second jitter are near-independent, so no jitter "decomposition" is needed.**
   The frame jitter `σ_jitter` (fit from `dF` residuals) reflects `ε3 − ε2`; the second spread
   `σ_S` is dominated by `φ2` + δ0, which are separate from the frame. They share only the weak
   `M_actual` coupling, so the second-marginalization can use the full `σ_jitter` for the
   within-`mdmsh` frame kernel and a separate `σ_S` for `P(second)` without meaningful
   double-counting.

## Model design that follows (for the planned second-marginalization)

- `P(capture | M) = Σ_s P(S=s | M) · P_capture(mdmsh(boot + s), frame kernel)` — marginalize the
  second instead of committing to the modal one.
- `P(S=s | M) = Φ((s+0.5−μ)/σ_S) − Φ((s−0.5−μ)/σ_S)`, `μ = M/1000 + rtc_offset_seconds`. `σ_S = 0`
  reproduces today's deterministic behavior.
- **Same frame center** `model.frame(M, base)` at every candidate second (per point 3 above).
- `σ_S` mean is absorbed by `rtc_offset_seconds`; its spread ≈ `rtc_offset_std`. Note the cross-run
  `rtc_offset_std` (~0.5 s) likely OVERstates the within-session second spread, since it also mixes
  in session-to-session δ0 drift — a smaller within-session `σ_S` matches the "5200 ms almost
  always lands on the same second" intuition better.
- **What `rtc_offset_seconds` (~5.26 s) actually absorbs:** Seed B locks a fixed ~5 s AFTER the
  Sweet-Scent press at t3 (encounter/battle-start; the frame counter keeps running through it, so
  that lead is baked into the `dF` intercept too). On top of that, the +0.2 s first-timer bias
  delays Seed B's absolute time without changing Seed A's whole second, adding ~0.2 s. So
  `~5 (encounter) + 0.2 (bias) + rounding ≈ 5.26` — all self-corrected by the fitted offset; the
  model never has to decompose it.
- Canon: a given frame can co-occur with second `s` or `s±1` (δ0/φ2), so each second's frame band
  should cover ~±1 s of frames (~±60). Current wide `BandPolicy` bands already cover ±1 s; worth
  making explicit on the next precompute.

## Resolved / still open

- **+0.2 s bias — resolved:** it's on the first timer, shifting t1/t2/t3 together; it doesn't
  change `M = t3 − t2`. It cancels in the frame but contributes ~0.2 s to `rtc_offset_seconds`.
- **`vector_delay` definition — resolved:** exactly timer 3's duration, `t3 − t2`.
- **δ0 direction — open:** may lean late more often than early; the data will tell. Any systematic
  component is self-corrected into `rtc_offset_seconds` (by design), so only its *spread* needs a
  model.
- **Sub-second data — open:** capturing the actual phase at t0/t2/t3 would separate δ0 from `ε3`
  and pin the within-session `σ_S` — the missing piece for a precise second model.
