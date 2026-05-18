# Frame Rate Fix Plan

## Background

DS hardware VBlank rate is 59.8261 Hz, not 60. The delay counter increments once per VBlank. The codebase currently assumes 60 delays/second everywhere, causing seed predictions to drift ~0.174 delays/second — roughly 1 full delay unit every 5.75 seconds, and a full second's worth of drift after ~5.75 minutes.

**Chosen approach:** Option B — frame-first iteration. Iterate by frame index and compute the RTC second for each frame, rather than assuming 60 delays per second.

**Compass supplement:** Option C (widening compass windows) is deferred.

---

## Terminology

- **Delay**: increments once per hardware VBlank at ~59.8261 Hz
- **Frame**: game frame, every 2 delays (~29.913/sec)
- **Second**: RTC second (integer boundary in calculate_seed's time argument)

---

## Math

Constants:
```
DPS      = 59.8261          # delays per second
FPS      = DPS / 2          # frames per second (~29.91305)
FPS_CEIL = 30               # ceil(FPS)
OFPS     = FPS_CEIL - FPS   # ~0.08695  (fractional frames "missed" per second)
SPF      = 1.0 / FPS        # seconds per frame
```

Helpers:
```
offset_frames(s) = (s * OFPS) % 1.0
    → fractional frame drift accumulated by second s

frames_in_second(s) = 30 if offset_frames(s) < (FPS % 1) else 29
    → equivalently: ceil(FPS - offset_frames(s))
    → 29-frame seconds occur when offset_frames(s) >= ~0.91305
    → roughly 1 in every ~11.5 seconds is a 29-frame second

weight_b(s, j) = min(1.0, SPF * (j + offset_frames(s)))
weight_a(s, j) = 1.0 - weight_b(s, j)
    → where j = frame index within second s (0-based)
    → weight_b = P(RTC has advanced to second s+1 at frame j)

score(s, j) = eval_seed_a * weight_a(s, j) + eval_seed_b * weight_b(s, j)
```

The 64-bit chain link bitmask has 4 unused bits (bits 60-63). Use **bit 62** as a width flag:
- 0 → 30-frame link (60 seed bits used)
- 1 → 29-frame link (58 seed bits used)

---

## Phase 1 — Constants and helpers

**Location:** New section at top of `chart/chain.py` (or a shared `claytonlib/constants.py` if reuse across modules warrants it).

- Define `DPS`, `FPS`, `FPS_CEIL`, `OFPS`, `SPF` as module-level constants.
- Implement `offset_frames(s: int) -> float` and `frames_in_second(s: int) -> int`.
- Precompute a second table utility if needed for performance:
  `_build_second_table(n_seconds) -> list[tuple[int, int, int]]`
  returning `(first_global_frame, delay_offset, n_frames)` per second.

---

## Phase 2 — `chart/chain.py`: link generation

### `chain_at_time(time, delay)`
- Add second counter `s = 0`.
- Each iteration:
  - Compute `n = frames_in_second(s)`
  - Yield the link (with width bit set if `n == 29`)
  - Step `delay += n * 2` (58 or 60 instead of always 60)
  - Step `time += timedelta(seconds=1)` (unchanged)
  - Increment `s`

### `link_at_time(time, delay, s: int)`
- Add `s` parameter for width bit and consistency.

### `expand_chain_link(link)`
- Read width bit (bit 62) to determine `n_frames` (29 or 30).
- For 30-frame link: same as current (30 pairs, f to f+58, t-58 to t).
- For 29-frame link: stop at index 28 (28 pairs, f to f+56, t-56 to t).
  ```
  # 29-frame expansion stops here instead of continuing to f+58/t-2
  f+54, t-4,
  f+56, t-2,   ← last pair for 29-frame link (index 28)
  ```

### `evaluate_chain_link` / `evaluate_chain_link_cached`
- No signature change needed; the width bit is part of the link value so cache keys remain correct.

---

## Phase 3 — `chart/evaluation.py`: straightening and scoring

### `FRAMES_PER_LINK`
- Rename to `MAX_FRAMES_PER_LINK = 30`. Actual frame count per link is read from the width bit.

### `straighten_link(link, s: int)`
- Add `s` parameter.
- Replace fixed weights `(30-j)/30` / `j/30` with:
  ```python
  off = offset_frames(s)
  n_frames = 29 if (link >> 62) & 1 else 30
  for j in range(n_frames):
      wb = min(1.0, SPF * (j + off))
      wa = 1.0 - wb
      bit0 = (link >> (2 * j)) & 1
      bit1 = (link >> (2 * j + 1)) & 1
      scores.append(bit0 * wa + bit1 * wb)
  ```

### `straighten_chain(links, setup_delay_seconds: int)`
- Add `setup_delay_seconds` (or starting second index) so each link's `s` can be computed.
- Pass `s = setup_delay_seconds + i` to `straighten_link`.

### Delay formula
- Replace `base_delay + (setup_delay_seconds + i) * 60 + j * 2` with cumulative frame count:
  ```python
  cumulative_frames[i] = sum(frames_in_second(setup_delay_seconds + k) for k in range(i))
  delay = base_delay + 2 * (cumulative_frames[i] + j)
  ```
  Precompute `cumulative_frames` once per chain evaluation rather than recomputing per frame.

### `_fmt_time_diff` (in `chart/__init__.py`)
- Replace `delay_from_key / 60` with `delay_from_key / DPS`.

---

## Phase 4 — `chart/__init__.py`: chain initialization and resumption

### `_initialize_writers`
- Replace `delay + start_offset * 60` with cumulative delay using the second table.
- Writers need to know their starting second index `s` to resume correctly.
- Store starting `s` per writer (derived from `setup_delay_seconds + already_written`).

### `chart_safari` main loop
- Pass second index to `evaluate_chain_link_cached` calls, or embed it in the link value (the width bit already handles this for evaluation; `s` is only needed at straighten time).

### Resume validation (`_validate_resume`)
- Same logic, but delay calculation uses cumulative second table.

---

## Phase 5 — `compass.py`: seed candidate generation

### `_seed_reachable` and `_generate_candidates`
- Replace `offset // 60` / `(offset % 60) // 2` with a second-table lookup:
  ```python
  # Given delay offset from base_delay, find (second_idx, frame_j)
  def delay_offset_to_second_frame(offset: int) -> tuple[int, int]:
      # iterate second table until cumulative delays exceed offset
  ```

---

## Breaking changes

- **Existing `.chain` files are invalid** (generated with wrong delay step). Must be deleted and re-charted.
- Consider adding a 1-byte version header to chain files to detect stale data on load and emit a clear error rather than silently producing wrong results.
- `straighten_link` signature changes (adds `s` parameter) — update all call sites.
- `straighten_chain` signature changes — update call sites.

---

## Test updates

- `test_evaluation.py`: update `straighten_link` calls to pass `s`; verify weights at j=0 for s>0 are non-zero.
- `test_chart.py`: re-verify that known-good seed `0xF613_087B` still evaluates correctly under new delay arithmetic.
- Add a test that `frames_in_second` returns 29 for seconds where `offset_frames(s) >= FPS % 1` and 30 otherwise.
- Add a test that `sum(frames_in_second(s) for s in range(N)) ≈ N * FPS` (within 1 frame).
