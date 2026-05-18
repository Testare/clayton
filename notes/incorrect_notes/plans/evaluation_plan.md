# Chart Evaluation Plan

## Statistical justification for normal distribution

If we model the player's timing error as normally distributed — i.e. when they
aim for frame j their actual frame is j + ε where ε ~ N(0, σ²) — then the
expected probability of success when targeting frame j is:

    E[success | target=j] = Σ_k P(actual = j+k | target = j) · score(j+k)
                           = Σ_k N(k; 0, σ) · score(j+k)

This is the exact definition of a Gaussian-weighted average of scores centred
on j. Truncating at ±2σ retains ~95.4 % of the probability mass, so the error
from the cutoff is small. This is a proper expected-value calculation — the
result is the probability of success given an optimally aimed but imperfectly
executed button press with standard deviation σ frames.

The uniform sliding-window strategy is the special case where timing errors are
assumed to be uniformly distributed within the window, which is simpler but
less realistic.


## Step 1 — Straightening a link

`straighten_link(link: int) -> list[float]`  (30 values, one per frame)

Each 64-bit link bitmask has 60 meaningful bits: bits 2j and 2j+1 belong to
frame j (0 ≤ j ≤ 29).

- Bit 2j   → seed evaluated as "still on first second"  → weight (30−j)/30
- Bit 2j+1 → seed evaluated as "already on next second" → weight j/30

At frame 0 both seeds are identical (expand_chain_link emits `f, f`), so the
weight degeneracy doesn't matter; the formula still gives score = bit(0) · 1.

    score[j] = ((link >> 2j) & 1) · (30−j)/30
             + ((link >> (2j+1)) & 1) · j/30

Scores are floats in [0, 1]. Dividing by 30 keeps them in that range and makes
the subsequent windowed averages directly interpretable as probabilities.

`straighten_chain(links: list[int]) -> list[float]`

Concatenates the output of straighten_link for each link in order. Length =
30 · len(links). Frame index f in the flat list corresponds to:
    link  = f // 30
    frame = f %  30

Both functions live in evaluation.py as module-level helpers shared by both
strategies.


## Step 2 — Sliding window scoring

Two strategies are defined. Both receive the flat per-frame scores from
straighten_chain. Both set edge frames (those without a full window on one
side) to 0 rather than computing a partial score, so the output list length
equals the input length and frame → delay mapping stays trivial.

### Strategy A — SlidingWindowSum(window: int)

`window` is the total number of frames included. Enforced to be odd (ValueError
if even) so there is a clear centre frame.

    score(j) = sum(flat[j - window//2 : j + window//2 + 1])   if both ends in bounds
             = 0                                                 otherwise

Filename base: `sliding_window_{window}`  →  file `sliding_window_{window}.json`


### Strategy B — NormalWindow(sigma_frames: float)

`sigma_frames` is the standard deviation in **frames** (not delay units — recall
each frame is 2 delay units, so sigma_frames=8 corresponds to a timing spread of
±16 delay). Minimum value: 1.0 frame (enforced with ValueError); below this the
window degenerates toward single-frame evaluation and the weight normalisation
becomes awkward. The window half-width is `hw = floor(2 * sigma_frames)` (2σ cutoff).

Weights are the un-normalised Gaussian values evaluated at integer frame offsets:
    w(k) = exp(−k² / (2 · sigma_frames²))   for k in [−hw, hw]

Then normalise so they sum to 1 (accounts for truncation at ±2σ):
    w_norm(k) = w(k) / Σ_i w(i)

    score(j) = Σ_{k=−hw}^{hw} w_norm(k) · flat[j+k]   if both ends in bounds
             = 0                                          otherwise

Filename base: `normal_{sigma_frames}`  →  file `normal_{sigma_frames}.json`

For `sigma_frames` that is a whole number, format without decimal (e.g. `normal_12`);
otherwise include it (e.g. `normal_8.5`). Use Python's `g` format spec.


## Step 3 — Building TopResult entries

After computing the windowed score list, find the top 5 frames by score.

For a flat frame index f with base_delay B and setup_delay_seconds S:
    link  = f // 30
    frame = f %  30
    delay = B + (S + link) * 60 + frame * 2
    time  = (initial_time + timedelta(seconds = S + link)).strftime("%H:%M:%S")

`TopResult(score=..., delay=delay, time=time)`

Sort descending by score. If scores are tied, sort ascending by delay (earlier
is easier to hit).


## Step 4 — EvaluationStrategy.evaluate signature

    def evaluate(
        self,
        links: list[int],
        base_delay: int,
        setup_delay_seconds: int,
        initial_time: dt.datetime,
    ) -> list[TopResult]:

The method owns the full pipeline: straighten → window → top-5. Both
strategies implement this on their own.


## Step 5 — CrossChainResult and updated EvaluationData

The top-level JSON gains a `top10` field: the 10 best results across all chains,
deduplicating entries that share the same (delay, score) pair.

    @dataclass
    class CrossChainResult:
        score: int | float
        delay: int
        time: str
        chain: str   # path.name of the chain file (e.g. "2024-01-01_12-00-00+300.chain")

    @dataclass
    class EvaluationData:
        results: dict[str, ChainEvaluationResult]
        top10: list[CrossChainResult]

JSON shape:
    {
      "top10": [
        {"score": 0.9, "delay": 1234, "time": "12:05:42",
         "chain": "2024-01-01_12-00-00+300.chain"},
        ...
      ],
      "results": {
        "2024-01-01_12-00-00+300.chain": {
          "max_links_checked": 61,
          "top5": [...]
        }
      }
    }

Deduplication: when gathering candidates from all per-chain top5 lists, drop any
entry whose (delay, score) pair has already been seen. Sort descending by score,
ascending by delay on ties, then take the first 10.


## Step 6 — evaluate_chart implementation

    def evaluate_chart(inputs: ChartSafariInput, strategy, store=None) -> None:

1. If store is None, use LocalChainStore().
2. chart_dir = _output_dir(inputs).
3. base_delay, times = get_times(inputs.key_seed).
4. chain_paths = [p for p in store.list_chain_files(chart_dir)
                  if _chain_setup_delay(p) == inputs.setup_delay_seconds]
   where _chain_setup_delay(path) parses the integer between '+' and '.chain'
   in the filename stem (e.g. "2024-01-01_12-00-00+300.chain" → 300).
5. Load existing EvaluationData via read_evaluation, or start with empty dicts.
6. t_total_start = now()
7. For each (path, time) in zip(chain_paths, times):
   a. links = store.read_all(path)
   b. max_links_checked = len(links)
   c. Skip if existing result has same max_links_checked (already up to date).
   d. t0 = now()
   e. flat = straighten_chain(links)                    # flatten step
   f. t1 = now()
   g. scored = strategy.score(flat)                     # windowed scoring step
   h. t2 = now()
   i. top5 = gather_top5(scored, base_delay,
                          inputs.setup_delay_seconds, time)
   j. t3 = now()
   k. Store ChainEvaluationResult(max_links_checked, top5) keyed by path.name.
   l. logger.info("chain %s: flatten=%.3fs score=%.3fs top5=%.3fs",
                   path.name, t1-t0, t2-t1, t3-t2)
8. t_chains_done = now()
9. Gather cross-chain top10 from all results[*].top5 (deduplicate by (delay, score)).
10. t_top10_done = now()
11. logger.info("top10 across %d chain(s): %.3fs  total: %.3fs",
                len(chain_paths), t_top10_done-t_chains_done,
                t_top10_done-t_total_start)
12. data.top10 = top10
13. write_evaluation(chart_dir, strategy, data).

Note: `strategy.score(flat)` is an internal helper (not part of the Protocol) —
the Protocol's `evaluate` method may call straighten_chain + score + gather_top5
internally, or evaluate_chart can call them directly if the strategy exposes them.
Decide at implementation time which is cleaner; leaning toward evaluate_chart
owning steps e–j and strategy exposing `score(flat: list[float]) -> list[float]`
alongside `filename`, making `evaluate` on the Protocol just a convenience wrapper.


## Open questions

- Should `strategy.evaluate` remain a convenience wrapper (straighten + score +
  top5 in one call) or be removed in favour of evaluate_chart driving each step?
  Leaning toward keeping it as a wrapper so strategies can also be used standalone.
