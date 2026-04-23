# Machete Jane Plan

## Overview

`machete_jane` takes a list of candidate seeds (each with a `SafariContext` already
reflecting the current encounter state, e.g. from compass) and returns an optimal
decision tree: at each step, which action maximises the probability of capture across
all candidate seeds, branching on the observed outcome.

The internal recursive function `jane_tree` does the heavy lifting.


## Tree node structure

```python
from fractions import Fraction
from dataclasses import dataclass, field

@dataclass
class JaneNode:
    action:      str                          # "BALL", "BAIT", "MUD", "CAPTURED", "FUTILE"
    probability: Fraction
    branches:    dict[str, "JaneNode"] | None # None only for terminal nodes
```

Terminal constants (defined once, reused everywhere):

```python
CAPTURED_NODE = JaneNode(action="CAPTURED", probability=Fraction(1), branches=None)
FUTILE_NODE   = JaneNode(action="FUTILE",   probability=Fraction(0), branches=None)
```

`branches` is `None` **only** for terminal nodes (CAPTURED, FUTILE). Non-terminal
nodes always have a `branches` dict, even if their probability happens to be 1.


## External API: machete_jane

```python
def machete_jane(
    candidates: list[tuple[SafariContext, int]],  # (ctx, seed) — e.g. from compass
    max_turns: int | None = ...,                  # overrides machete_config().max_turns
) -> JaneNode | None:
```

1. For each `(ctx, seed)` in candidates:
   - `ctx2 = copy.copy(ctx)` — never mutate the caller's context
   - Call `machete_all(ctx2, max_turns=max_turns)` to get the list of all viable paths
2. Build `items: list[tuple[SafariContext, list[str]]]` — each copy paired with its paths
3. Return `jane_tree(items)`

Note: `machete_jane` does not accept a `path` input. Callers are expected to pass
`SafariContext` objects that already reflect any actions already observed (e.g. as
filtered by compass). Seed values are retained in the input tuple for potential future
display use but are not used by the algorithm.


## Internal: jane_tree

```python
def jane_tree(
    candidates: list[tuple[SafariContext, list[str]]]
) -> JaneNode | None:
```

Each entry is `(ctx, paths)` where `paths` is the list of viable capture paths from
that context's current state.


### Base cases

1. If `candidates` is empty → return `None`
2. If every seed's path list is empty → return `FUTILE_NODE`


### Build one candidate tree per action type

Repeat the following for each action in `[BALL, MUD, BAIT]`:

#### Step 1 — Simulate the action on every candidate

For each `(ctx, paths)`:
- If `ctx.has_fled()`: skip simulation entirely. The seed is truly terminal and the
  player would already know — it cannot produce a new outcome. It still counts in
  `total_seeds`. (`ctx.captured()` is theoretically impossible here but treated the
  same way if encountered.)
- Otherwise: `ctx2 = copy.copy(ctx)`, call the action's throw method, record
  `result: SafariStep`, map to outcome character. This applies even if `paths` is
  empty — an active-context seed with no viable paths is still a real candidate the
  player might be on, and must be assigned to an outcome bucket so the denominator
  stays correct at every level of the recursion.

#### Step 2 — Group candidates by outcome character

Each seed lands in exactly one outcome bucket based on its deterministic RNG result.

Outcome characters per action:
- BAIT: `"b"` (BAIT), `"B"` (BAIT_CRITICAL)
- MUD:  `"m"` (MUD),  `"M"` (MUD_CRITICAL)
- BALL: `"0"` (BALL_0), `"1"` (BALL_1), `"2"` (BALL_2), `"3"` (BALL_3), `"C"` (CAPTURED)

#### Step 3 — Recurse per outcome bucket

For each outcome character `c` with at least one seed:

- **Filter paths**: for each seed in this bucket, keep only paths that start with `c`.
  Paths that don't start with `c` are silently dropped — we have committed to this
  action/outcome, so paths requiring a different first step are no longer viable.
- **Strip prefix**: slice each surviving path to remove the leading `c`.
- **Special case — BALL outcome `"C"`**: do not recurse. The subtree for this bucket
  is always `CAPTURED_NODE`. (Remaining path after stripping `"C"` would be `""`;
  returning CAPTURED_NODE handles this cleanly without recursing.)
- **Otherwise**: call `jane_tree([(ctx2, stripped_paths), ...])` for all seeds in
  this bucket. If the result is `None` or `FUTILE_NODE`, skip this bucket entirely
  (do not add a branch).

#### Step 4 — Compute the probability for this action tree

```
probability = sum(len(bucket) * bucket_node.probability
                  for each non-skipped bucket) / total_seeds
```

Where `total_seeds = len(candidates)`. Seeds in skipped buckets contribute 0 to
the numerator (their probability is 0) but still count in the denominator.

Using `fractions.Fraction` throughout avoids floating-point drift.

#### Step 5 — Assemble the node

```python
JaneNode(
    action     = "BALL" | "BAIT" | "MUD",
    probability= computed_probability,
    branches   = {c: subtree for non-skipped buckets},
)
```


### Select the best tree

- Compare the three action trees by probability
- Tie-break order: **ball > mud > bait** (balls have 5 outcome branches vs 2 for
  bait/mud, so they eliminate ambiguity fastest)
- If the winning probability is `Fraction(0)` → return `FUTILE_NODE` instead
- Otherwise → return the winning tree


### Recursion termination

`jane_tree` does not track turn count. Termination is guaranteed because:
- Each recursion strips at least one character from every path
- Once all paths are empty (or were already empty), the base case fires and returns
  `FUTILE_NODE`
- Maximum recursion depth equals the length of the longest path returned by
  `machete_all`, which is bounded by `max_turns`


## Probability semantics

The probability at any node represents the fraction of input seeds (at that point in
the tree) for which following this tree's recommendations leads to capture.

Seeds with no viable paths are intentionally retained in the denominator — they
represent seeds that are truly lost causes, and excluding them would give an
over-optimistic probability that doesn't reflect real-world uncertainty about which
seed was actually hit.


## Performance note

Path filtering at each recursion level is O(seeds × paths × path_length). For many
seeds or long paths this may be slow. A natural future optimisation is to represent
paths as a trie, making each level's filtering O(seeds × branching_factor). This
is deferred until the minimal viable implementation is validated.
