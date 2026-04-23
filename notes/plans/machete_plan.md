# Machete Plan

## Overview

`machete` finds capture paths for a known seed (or mid-encounter `SafariContext`)
by searching over possible action sequences (bait, mud, ball).

Three public functions:
- `machete_one` — BFS; returns the first (shortest) capture path found, or `None`
- `machete_all` — BFS; returns a list of all capture paths
- `machete_jane` — multi-seed optimal decision tree (see `machete_jane_plan.md`)

Success criterion is always `CRITERIA_CAPTURE` (not configurable).


## File layout

```
claytonlib/
  machete.py         — MacheteConfig, machete_config(), machete_one, machete_all, machete_jane
notes/plans/
  machete_plan.md
  machete_jane_plan.md
```


## Configuration: MacheteConfig

Singleton (accessed via `machete_config()`, same pattern as `chart_config`/`compass_config`):

```python
@dataclass
class MacheteConfig:
    max_turns: int | None = 50
```


## Input signature (machete_one and machete_all)

```python
def machete_one(
    pokemon_or_ctx: SafariPokemon | SafariContext,
    seed: int | None = None,       # required if SafariPokemon passed
    path: str = "",                # compass-syntax path to apply before search
    max_turns: int | None = ...,   # None = inherit machete_config().max_turns
) -> str | None:

def machete_all(
    pokemon_or_ctx: SafariPokemon | SafariContext,
    seed: int | None = None,
    path: str = "",
    max_turns: int | None = ...,
) -> list[str]:
```

### Dispatch rules
- If `SafariContext` passed: copy it immediately; ignore `path` and `seed`
- If `SafariPokemon` passed: `seed` is required; construct
  `SafariContext.start_encounter(seed, pokemon)`, then apply `path`


## Path application: `_apply_path`

```python
def _apply_path(ctx: SafariContext, path: str) -> SafariContext:
```

Applied only when starting from a seed+pokemon. Raises `ValueError` if:
- `u` (undo) appears — not supported in machete
- Unknown characters appear
- Actual RNG outcome does not match the character in the path string

Character → (action, expected SafariStep) mapping (same as compass, no uncertain):

| Char | Action | Expected step |
|------|--------|---------------|
| `b`  | throw_bait | BAIT |
| `B`  | throw_bait | BAIT_CRITICAL |
| `m`  | throw_mud  | MUD |
| `M`  | throw_mud  | MUD_CRITICAL |
| `0`  | throw_ball | BALL_0 |
| `1`  | throw_ball | BALL_1 |
| `2`  | throw_ball | BALL_2 |
| `3`  | throw_ball | BALL_3 |
| `C`  | throw_ball | CAPTURED |
| `F`  | throw_ball | FLED — raise ValueError (fled, no point searching) |

Spaces and commas are ignored (same as compass). Aliases `a`/`e` are NOT supported
(machete paths come from machete output, which always uses canonical characters).


## BFS search

BFS state: `(ctx: SafariContext, path_so_far: str, turns_taken: int)`

Action iteration order: **mud → ball → bait**

This order is used for both `machete_one` and `machete_all`. It is chosen so that
decisive actions (mud and ball) are explored before bait, preventing the BFS from
being flooded with long bait-only prefixes.

For each action in order:
1. `ctx2 = copy.copy(ctx)`
2. Call the appropriate throw method; get `result: SafariStep`
3. Append `SafariStep.value` (the canonical character) to `path_so_far`
4. If `result == CAPTURED`: yield/record path — **do not enqueue**
5. If `result == FLED`: discard — **do not enqueue**
6. If `turns_taken + 1 >= max_turns` (and not captured/fled): increment `truncated`
   counter, discard — **do not enqueue**
7. Otherwise: enqueue `(ctx2, new_path, turns_taken + 1)`

`max_turns=None` disables the turn limit.

### Output
- `machete_one`: return the first path dequeued that ends in capture, or `None` if
  the queue empties with no capture found
- `machete_all`: return a 2-tuple `(paths, truncated)` where `paths` is the list of
  all capture paths found (may be empty) and `truncated` is the count of BFS branches
  that were discarded solely because they reached `max_turns` without terminating
  (i.e. neither captured nor fled). A non-zero `truncated` count indicates that
  raising `max_turns` may reveal additional successful paths.


## Path format

Same encoding as compass output — canonical characters only, no spaces:

```
b012M3C
```
= bait (no crit), ball 0-shake fail, ball 1-shake fail, ball 2-shake fail,
  mud (crit), ball 3-shake fail, ball capture.

`F` (fled) never appears in a path returned by machete (fled paths are discarded).
