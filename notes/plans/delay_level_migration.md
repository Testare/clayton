# Delay-Level Migration Plan

Move chain/compass evaluation from frame-level (step 2, 29/30 per second) to
delay-level (step 1, 59/60 per second). After this migration "frames" and
"delays" are synonyms in the codebase.

---

## evaluation.py

- `FPS = DPS / 2` → `FPS = DPS`
- `FPS_CEIL = 30` → `FPS_CEIL = 60`
- (OFPS, SPF, `_FPS_FRAC` derive from those — no code change)
- `MAX_FRAMES_PER_LINK = 30` → `= 60`
- `_WIDTH_BIT = 62` → `= 120`
- `_link_n_frames`: return values `29`/`30` → `59`/`60`
- `delay_at_second` line 46: drop `* 2` → `return base_delay + cumulative_frames(s)`
- `_build_frame_info` line 191: `base_delay + 2 * (cum + link_cum + j)` → `base_delay + (cum + link_cum + j)`

## chain.py

- Remove `struct` import and `_LINK_STRUCT = struct.Struct('<Q')`; add `_LINK_SIZE = 16`
- `_WIDTH_BIT = 62` → `= 120`
- `LocalChainStore.read_all/read_tail/append`: rewrite using `int.from_bytes`/`to_bytes` with `_LINK_SIZE`
- `chain_at_time` line 131: `delay + n * 2` → `delay + n`
- `link_at_time` line 143: `delay + n * 2` → `delay + n`
- `evaluate_chain_link`: `if n == 29:` → `if n == 59:`

## chart/__init__.py

- Line 190: `* 8` → `* 16`
- Line 217: `(min_size // 8) * 8` → `(min_size // 16) * 16`
- Line 408: `// 8` → `// 16`

## compass.py

- `_delay_offset_to_second_frame` lines 197/199: `cum + n * 2 > offset` → `cum + n > offset`; `cum += n * 2` → `cum += n`
- `_seed_reachable` lines 213/216–217: `seed_a_base + 2 * frame_j` → `+ frame_j`; `to_seed - 2 * (n - frame_j)` → `(to_seed - n) + frame_j`
- `_generate_candidates` lines 229–232: remove parity alignment block entirely; loop step `2` → `1`
- `_generate_candidates` lines 241/248: same seed arithmetic as `_seed_reachable`

## expedition.py

- Lines 1062–1064: same parity block removal and step change as compass
- Lines 1077/1081: same seed arithmetic changes as compass

## tests/test_evaluation.py

- `test_frames_in_second_returns_30_for_early_seconds`: check `== 60`, `range(5)` (first 59-delay second is s=5)
- `test_frames_in_second_returns_29_at_s11`: update to `frames_in_second(5) == 59`
- `test_frame29_bit1_full_weight` line 98: comment update only; SPF import picks up new value automatically
- `test_29_frame_link_output_length` line 103: `1 << 62` → `1 << 120`; assert length == 59
- `test_30_frame_link_output_length` line 108: `1 << 62` → `1 << 120`; MAX_FRAMES_PER_LINK auto-updates
- `test_scores_in_range` line 113: `mask = 0xBFFF_FFFF_FFFF_FFFF` → `mask = (1 << 120) - 1`
- `test_29_frame_link_shorter` line 150: `1 << 62` → `1 << 120`; assert length == 59
- `test_delay_formula` line 293: `_BASE_DELAY + 2 * (cumulative_frames(_SETUP) + 3)` → drop `* 2`
