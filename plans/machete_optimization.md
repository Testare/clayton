# Machete Optimization Ideas

This document catalogues potential optimizations for `machete_one` and `machete_all`
(and by extension `machete_jane`). **Nothing here is implemented yet.** Ideas are
grouped by theme; rough impact/effort notes are included.

---

## Background: how many RNG advances does each action consume?

Understanding advance counts informs several ideas below.

| Action | State | Advances |
|---|---|---|
| throw_bait | WATCHING_WONT_FLEE | 4 pre-turn + 1 critical + 2 ability + 1 flee-check = **8** |
| throw_bait | WATCHING_WILL_FLEE | 4 + 1 + 2 + 0 (flee sets state, no advance) = **7** |
| throw_mud  | WATCHING_WONT_FLEE | 4 + 1 + 2 + 1 = **8** |
| throw_mud  | WATCHING_WILL_FLEE | 4 + 1 + 2 + 0 = **7** |
| throw_ball (captured) | any | 4 + 4 shakes = **8** |
| throw_ball (miss, balls>0, WONT_FLEE) | — | 4 + (shakes+1) + 2 + 1 = **8+shakes** (8–12) |
| throw_ball (miss, balls>0, WILL_FLEE) | — | 4 + (shakes+1) + 2 + 0 = **7+shakes** (7–11) |
| throw_ball (miss, balls=0) | — | 4 + (shakes+1) = **5+shakes** (5–9) |

So **bait and mud consume identical advance counts** for any given flee state (they
differ only in which stages they mutate). Ball consumes a variable count due to the
early-break shake loop.

---

## 1. State Deduplication (visited set)

### Idea
Two BFS branches that arrive at the same `(rng_state, flee_rate_stages,
capture_rate_stages, balls_remaining, watch_state)` tuple will produce identical
subtrees. We can skip re-exploring such states.

### Compact encoding
Pack the entire mutable state into a single `int` (47 bits total):

| Field | Bits | Range |
|---|---|---|
| rng_state | 32 | 0–0xFFFFFFFF |
| flee_rate_stages_idx | 4 | 0–12 (maps to −6…+6) |
| capture_rate_stages_idx | 4 | 0–12 |
| balls_remaining | 5 | 0–30 |
| watch_state | 2 | WONT/WILL/FLED/CAPTURED |

```python
def encode_state(ctx) -> int:
    return (ctx.rng_state
            | ((ctx.flee_rate_stages + 6) << 32)
            | ((ctx.capture_rate_stages + 6) << 36)
            | (ctx.balls_remaining << 40)
            | (ctx.state.value << 45))
```

For **machete_one** this is straightforward: add a `visited: set[int]` and skip
any state already in it. Since we want the *shortest* path, the first time we visit
a state is by definition the optimal path to it.

For **machete_all** it is trickier because two different paths to the same state are
considered distinct results. Deduplication is only safe if we enumerate paths, not
states. However, we can still prune states that are provably futile (no captures
reachable from them) using a `futile: set[int]` cache populated as the BFS unwinds.

### Why stage saturation amplifies this
When `flee_rate_stages` is already at −6, a non-critical bait throw does not change
it. When `capture_rate_stages` is already at +6, a mud throw still increments it
(capped). These saturations increase the likelihood that two different action
sequences reach the same compact state, making the visited set more effective.

**Impact: high for machete_one. Medium for machete_all.**
**Effort: low.**

---

## 2. WATCHING_WILL_FLEE Branch Pruning

### Idea
When `state == WATCHING_WILL_FLEE`, the very next flee check will transition to
`FLED`. Both `throw_bait` and `throw_mud` run a flee check before returning, so
they always result in `FLED` from this state. Only a `throw_ball` that *captures*
produces a non-fled outcome.

Therefore: **when the current state is WATCHING_WILL_FLEE, skip bait and mud
entirely; only explore the ball branch, and only if it leads to CAPTURED.**

```python
if curr.will_flee():
    # only the ball can save us
    ctx2 = copy.copy(curr)
    result = ctx2.throw_ball()
    if result == SafariStep.CAPTURED:
        return new_path  # machete_one
    continue  # machete_all: prune this whole subtree
```

This cuts up to 2/3 of the branching from every WATCHING_WILL_FLEE node, which
can appear at any depth.

**Impact: high on deep searches. Low overhead.**
**Effort: very low.**

---

## 3. Pure-Function Simulation on Compact State

### Idea
Replace `copy.copy(SafariContext)` + method call with a pure function that takes the
compact int from Idea 1 and returns `(new_compact_state, outcome_char)`. No object
allocation or attribute lookup in the hot path.

```python
def sim_bait(state: int) -> tuple[int, str]: ...
def sim_mud(state: int)  -> tuple[int, str]: ...
def sim_ball(state: int) -> tuple[int, str]: ...
```

The BFS queue then holds `(compact_int, path_str, turns)` instead of
`(SafariContext, path_str, turns)`. Copying is a single integer assignment.
Hashing for the visited set is O(1).

Profiling needed to confirm whether `copy.copy` or the simulation arithmetic
dominates, but in Python, object allocation is expensive.

**Impact: medium–high.**
**Effort: medium** (requires rewriting the simulation without the class, or wrapping it).

---

## 4. Precomputed RNG Sequence

### Idea
The LCG formula is `rng = (rng * 1103515245 + 24691) & 0xFFFFFFFF`.
From a starting `rng_state`, we can precompute the next N values into a list once
up front, then index into it rather than recomputing per step.

```python
def precompute_rng(seed: int, n: int) -> list[int]:
    vals = []
    for _ in range(n):
        seed = (seed * 1103515245 + 24691) & 0xFFFF_FFFF
        vals.append(seed >> 16)
    return vals
```

This turns repeated multiplications into list indexing, but the saving is modest
in CPython because the multiplication is already cheap. More useful if combined
with numpy (see below).

One subtlety: when two paths from the same starting state diverge, their RNG
offsets differ. Precomputing only works if we know the offset in advance or index
by offset. This interacts well with the compact state encoding (the rng_state tells
us exactly where we are in the LCG sequence).

**Impact: low in pure Python. Higher with numpy.**
**Effort: medium.**

---

## 5. numpy Vectorised Simulation (batch across candidates, machete_jane)

### Idea
In `machete_jane`, each candidate seed is evaluated independently with `machete_all`.
These are embarrassingly parallel, but also potentially vectorisable: we can simulate
the same sequence of actions across many seeds simultaneously using numpy uint32
arrays.

The LCG maps directly to numpy:
```python
import numpy as np
rng = np.array(seeds, dtype=np.uint32)
rng = rng * np.uint32(1103515245) + np.uint32(24691)   # one advance, all seeds at once
top16 = (rng >> 16).astype(np.int32)
```

For a fixed action sequence (e.g. "mud, mud, ball"), we can check whether that
sequence is a capture path for all seeds simultaneously in a few numpy operations,
rather than looping over each seed separately.

This is most powerful if we enumerate candidate paths first and then verify them
across all seeds via batched simulation. For example:
1. Use `machete_all` on the first candidate to generate all capture paths.
2. For each such path, simulate it across all remaining candidates in numpy.
3. Only fall back to full BFS for candidates that share no paths with candidate 0.

**Impact: potentially very high for machete_jane with many candidates (compass "J" path).**
**Effort: high** (significant restructuring).

---

## 6. numba JIT Compilation

### Idea
`numba.jit(nopython=True)` compiles a Python function to native machine code.
The BFS inner loop is ideal: tight arithmetic, no I/O, no Python objects if we
use the compact int encoding.

```python
import numba

@numba.jit(nopython=True)
def _bfs_core(rng_state, flee_idx, capture_idx, balls, watch_state, max_turns,
              adjusted_flee_rates, adjusted_catch_rates_b):
    # pure integer BFS returning first capture path as an array of action codes
    ...
```

Numba can JIT arrays and integer arithmetic to near-C speed. The first call
incurs compilation overhead (~seconds), but subsequent calls are fast. This is
suitable for a session that runs many machete calls.

Limitations: numba does not support Python dicts or complex data structures in
nopython mode; the compact-int encoding (Idea 3) is a prerequisite.

**Impact: potentially 20–100x on the BFS core.**
**Effort: high** (requires pure-integer BFS core as prerequisite).

---

## 7. Multiprocessing for machete_jane

### Idea
`machete_jane` evaluates each candidate independently. The GIL prevents thread-level
parallelism, but `concurrent.futures.ProcessPoolExecutor` sidesteps it:

```python
from concurrent.futures import ProcessPoolExecutor
with ProcessPoolExecutor() as ex:
    results = list(ex.map(_machete_all_worker, candidates))
```

Each worker process runs `machete_all` on one candidate and returns the path list.
With N physical cores this gives roughly N× speedup on the path-collection phase,
which dominates `machete_jane` runtime for large candidate sets.

Caveats:
- Startup overhead per process (~0.1s) means it only helps when candidates are slow.
- `SafariContext` objects must be picklable (they are, being dataclasses).
- The `_jane_tree` phase is sequential but usually much faster than path collection.

**Impact: near-linear scaling with core count for large candidate sets.**
**Effort: low** (5–10 lines to add to `machete_jane`).

---

## 8. Iterative Deepening DFS (IDDFS) for machete_one

### Idea
The current BFS uses O(3^depth) memory in the worst case. IDDFS achieves the same
optimal-depth guarantee as BFS with only O(depth) memory:

```
for depth_limit in range(1, max_turns+1):
    result = dfs(ctx, depth_limit)
    if result: return result
```

Each iteration re-expands nodes from shallower depths, which is wasteful if the
branching factor is high (3 here). In practice, if the answer is at depth d, the
total work is O(3^d) regardless (same as BFS), but memory drops from O(3^d) to
O(d). For max_turns=20, BFS queue can hold millions of entries; IDDFS stays at
depth-20 stack frames.

**Impact: memory usage. May be slower wall-clock due to re-expansion.**
**Effort: low.**

---

## 9. Futile-Subtree Memoization (machete_all)

### Idea
As `machete_all` explores the tree, if a subtree produces zero captures, record its
compact state in a `futile: set[int]` cache. Any later branch that reaches that same
compact state can be pruned immediately.

This is the dual of the visited set (Idea 1): instead of "we already found the best
path here", we record "we already proved there is no path here".

This is safe for `machete_all` even though full deduplication is not, because we
only skip states that are provably dead (no captures anywhere in their subtree).

**Impact: high when the search space has many repeated dead-end states.**
**Effort: low.**

---

## 10. Infeasibility Bound (Pruning by catch-rate floor)

### Idea
For a given `(capture_rate_stages, balls_remaining, turns_left)`, compute the
minimum number of mud throws needed before a ball can ever capture, and prune if
that exceeds `turns_left`.

Concretely: pre-build a lookup table `can_capture[stage_idx][balls][turns_left]`
(13 × 31 × max_turns entries) indicating whether any sequence of at most
`turns_left` turns can produce a capture from that stage/balls state. Build it via
backwards induction:
- Base: can capture with 0 turns left only if already captured.
- Induction: `can_capture[s][b][t] = True` if any action (ball/mud/bait) from
  that state can lead to capture in t steps (considering both outcomes of the
  critical-hit RNG, which is a 1-in-10 branch).

At each BFS node, look up the table before queuing children. This is a pure
pre-computation step that adds no per-turn overhead beyond a table lookup.

The tricky part: the flee state and rng_state also affect outcomes, so the table
is an approximation (optimistic bound: ignores fleeing). False positives (pruning
too aggressively) are a correctness risk, so the table must be built conservatively
(assuming no flee, which is the best-case scenario).

**Impact: can dramatically shrink the search tree for low-catch-rate Pokémon.**
**Effort: medium.**

---

## 11. Invertible LCG → Bidirectional BFS

### Idea
The LCG `f(x) = (x * 1103515245 + 24691) mod 2^32` is invertible modulo 2^32:
```
inverse_mult = pow(1103515245, -1, 2**32)   # = 2520285293
f_inv(x) = ((x - 24691) * 2520285293) & 0xFFFF_FFFF
```

This means we can run the simulation *backwards*: given a final RNG state, compute
what state preceded it. In principle, bidirectional BFS from both the start state
and the "captured" terminal states could meet in the middle, reducing the search
space from O(3^d) to O(3^(d/2)).

Practical challenges:
- The "captured" state is not a unique RNG value; capture depends on the ball-shake
  outcomes, which depend on many different RNG states.
- Stage modifiers are also hard to invert (they depend on critical-hit outcomes).
- This may be more theoretical than practical for our search depth (≤20 turns).

Worth keeping in mind if searches grow very deep.

**Impact: theoretical. Hard to implement correctly.**
**Effort: very high.**

---

## 12. Path String Representation Overhead

### Idea
Currently the BFS accumulates `path_so_far` as a string via concatenation:
`new_path = path_so_far + result.value`. In Python, string concatenation is O(n)
per step because strings are immutable; at depth 20 this creates 20 new string
objects per node.

Alternatives:
- Carry the path as a `list[str]` and join only on capture.
- Carry the path as an integer bitmask (each action = 2 bits, 20 turns = 40 bits).
- For `machete_one` specifically, reconstruct the path from the BFS parent-pointer
  graph rather than carrying it in every queue entry.

This is a micro-optimisation but at high branching factor (millions of nodes) it
adds up.

**Impact: low–medium.**
**Effort: low.**

---

## 13. __slots__ on SafariContext

### Idea
Adding `__slots__` to `SafariContext` removes the per-instance `__dict__`, which
speeds up attribute access and reduces memory per object. Combined with the current
`copy.copy` approach, this is a low-effort improvement that applies to all callers
without restructuring.

```python
@dataclass
class SafariContext:
    __slots__ = ('pokemon', 'rng_state', 'flee_rate_stages', 'capture_rate_stages',
                 'turn_count', 'balls_remaining', 'state')
    ...
```

Note: `copy.copy` of a `__slots__` dataclass works correctly.

**Impact: modest (5–20% on copy-heavy workloads).**
**Effort: very low.**

---

## 14. Cython Extension Module

### Idea
Write `_machete_core.pyx` in Cython with typed variables (`cdef int rng_state`,
etc.) and compile it as a C extension. The BFS core (the while-queue loop, RNG
advances, shake computation) is ideal for Cython: tight arithmetic, no Python
objects needed.

Compared to numba, Cython is more portable (compiles to C, no LLVM dependency)
and more predictable, but requires a build step and a .pyx file. The calling
interface can remain pure Python; only the inner loop goes to Cython.

**Impact: similar to numba (10–100x on the core).**
**Effort: high** (build infrastructure, .pyx source, type annotations throughout).

---

## 15. Avoid Redundant logger.debug Calls

### Idea
The `throw_bait`, `throw_mud`, and `throw_ball` methods each end with a
`logger.debug(...)` call. Even when debug logging is disabled, Python still
evaluates the arguments to `logger.debug` (the f-string or format args) before
the logging module short-circuits. With millions of BFS node expansions, this is
measurable overhead.

Fix: guard with `if logger.isEnabledFor(logging.DEBUG)` or remove the calls from
the BFS hot path (they are most useful for compass/interactive use, not machete).

**Impact: small but free.**
**Effort: very low.**

---

## Summary Table

| # | Idea | Impact | Effort | Prerequisite |
|---|------|--------|--------|--------------|
| 1 | State deduplication (visited set) | High | Low | Compact encoding (3) |
| 2 | WATCHING_WILL_FLEE pruning | High | Very low | — |
| 3 | Pure-function + compact int state | Med–High | Medium | — |
| 4 | Precomputed RNG sequence | Low–Med | Medium | — |
| 5 | numpy batch sim (machete_jane) | Very high | High | — |
| 6 | numba JIT | Very high | High | Compact int state (3) |
| 7 | multiprocessing (machete_jane) | High | Low | — |
| 8 | IDDFS for machete_one | Memory only | Low | — |
| 9 | Futile-subtree memo (machete_all) | High | Low | Compact encoding (3) |
| 10 | Infeasibility bound table | High | Medium | — |
| 11 | Bidirectional BFS (LCG inverse) | Theoretical | Very high | — |
| 12 | Path as list/int not string concat | Low–Med | Low | — |
| 13 | `__slots__` on SafariContext | Small | Very low | — |
| 14 | Cython extension | Very high | High | Compact int state (3) |
| 15 | Guard logger.debug calls | Small | Very low | — |

### Recommended implementation order

1. **Ideas 2, 13, 15** — zero-risk micro-wins, implement together.
2. **Idea 3** (compact int state) — unlocks 1, 9, 6, 14.
3. **Ideas 1 + 9** — deduplication for machete_one and machete_all.
4. **Idea 7** — multiprocessing for machete_jane, independent of the above.
5. **Idea 12** — path representation.
6. **Idea 10** — infeasibility bound table.
7. **Ideas 5 or 6** — numpy/numba, highest ceiling, most work.
