# Compass Plan

## Overview

`compass_safari` is an interactive seed-identification tool. Given a window of candidate
seeds around a target, the user inputs observed safari zone outcomes turn by turn. The
seed set is filtered after each input until one (or zero) seeds remain, or the pokemon
flees/is captured.

`compass_metronome` is stubbed with `raise NotImplementedError`.


## File layout

```
claytonlib/
  compass/
    __init__.py     — CompassConfig, CompassSafariInput, compass_safari, compass_metronome
    actions.py      — CompassAction, parse_input()
```

No `filter.py` needed — filtering is done directly via `SafariContext` methods from
`safari.py` (`throw_bait`, `throw_mud`, `throw_ball`, `start_encounter`).


## Configuration: CompassConfig

Singleton (accessed via `compass_config()`, same pattern as `chart_config()`):

```python
@dataclass
class CompassConfig:
    starting_ball_count:  int = 30
    seeds_displayed:      int = 5
    evaluation_threshold: int = 10   # show success column when ≤ this many seeds remain
```


## Input: CompassSafariInput

```python
@dataclass
class CompassSafariInput:
    pokemon:              SafariPokemon
    strategy:             Strategy
    criteria:             SuccessCriteria
    window:               int                    # search ±window delay units around target
    initial_time:         dt.datetime            # starting datetime of the player's chain
    key_seed:             int | None = None
    target_delay:         int | None = None
    target_seed:          int | None = None      # optional: verified against initial_time + target_delay
    evaluation_strategy:  Strategy | None = None # None = skip success column
    evaluation_criteria:  SuccessCriteria = CRITERIA_CAPTURE
```

The evaluation column is shown when `evaluation_strategy` is set **and** the candidate
count is at or below `compass_config().evaluation_threshold`.

Validation in `__post_init__` (four cases):

| key_seed | target_delay | target_seed | Action |
|----------|-------------|-------------|--------|
| absent   | present     | any         | `ValueError`: need key_seed to derive target clock time |
| present  | present     | absent      | Resolve target clock time from key_seed + target_delay |
| any      | absent      | present     | `ValueError`: target_delay is required (target_seed alone is ambiguous — see Seed generation) |
| present  | present     | present     | Resolve target clock time, verify that target_seed appears among the candidates at target_delay; `ValueError` if not found |

`target_seed` is only used to verify the target_delay is correct. It does **not**
become the sole seed to track — see Seed generation below for why two seeds exist
per delay.

### Alternative constructor

```python
@classmethod
def from_chart(
    cls,
    chart_input: ChartSafariInput,
    *,
    window: int,
    target_seed: int | None = None,
    target_delay: int | None = None,
    pokemon: SafariPokemon | None = None,
    strategy: Strategy | None = None,
    criteria: SuccessCriteria | None = None,
) -> CompassSafariInput:
```

Copies `key_seed`, `pokemon`, `strategy`, `criteria` from `chart_input`.
Does **not** copy `target_seed` or `target_delay` — those must be supplied explicitly.
Optional keyword overrides for `pokemon`, `strategy`, `criteria`.


## Action encoding

| Character(s) | Meaning |
|---|---|
| `m` | Mud, no crit |
| `M` or `a` | Mud, crit (besides itself with **A**nger) |
| `b` | Bait, no crit |
| `B` or `e` | Bait, crit (busy **E**ating) |
| `0` | Ball, 0 shakes (broke free immediately) |
| `1` | Ball, 1 shake |
| `2` | Ball, 2 shakes |
| `3` | Ball, 3 shakes |
| `F` | Pokemon fled (terminal — ends session) |
| `C` | Pokemon captured (terminal — ends session) |
| `u` | Undo last action |
| `?x` | Uncertain prefix on any of `b B e m M a 0 1 2 3` |
| ` ` `,` | Ignored |
| anything else | Error — list offending characters, reprompt without applying |

`?` semantics:
- `?b` / `?B` / `?e` — bait thrown, crit unknown
- `?m` / `?M` / `?a` — mud thrown, crit unknown
- `?0`–`?3` — ball thrown, not captured, shake count unknown

`F` and `C` are terminal: the session ends even if multiple seeds remain.


## Parsing: `parse_input(text: str) -> list[CompassAction] | ParseError`

Located in `actions.py`.

`SafariStep` (from `safari.py`) already represents precise outcomes and has
`from_char()` for `b/B/m/M/0-3/C/F`. Aliases `a` and `e` are normalised to
`MUD_CRITICAL` and `BAIT_CRITICAL` respectively at parse time.

```python
@dataclass
class CompassAction:
    step: SafariStep        # the specific step (or the "representative" step for uncertain ball)
    uncertain: bool = False # True if preceded by ?

# Sentinel values for uncertain throws:
# uncertain bait  → step=BAIT,   uncertain=True  (could be BAIT or BAIT_CRITICAL)
# uncertain mud   → step=MUD,    uncertain=True  (could be MUD or MUD_CRITICAL)
# uncertain ball  → step=BALL_0, uncertain=True  (any BALL_x, not CAPTURED)

class UndoAction: pass   # singleton sentinel, not a CompassAction
```

Algorithm:
1. Strip spaces and commas.
2. Scan left to right; collect unknown characters into a set.
3. Normalise aliases: `a` → `M` (MUD_CRITICAL), `e` → `B` (BAIT_CRITICAL).
4. On `?`: consume next character (error if EOF or not in `bBemMa0123`); mark as
   uncertain; normalise the aliased chars; set `step` to the canonical form of the
   throw type (BAIT for ?bBe, MUD for ?mMa, BALL_0 for ?0123).
5. On `u`: emit `UndoAction`.
6. If any unknown characters found: return `ParseError(unknown_chars)` — do not apply
   any of the input.
7. Return `list[CompassAction | UndoAction]`.


## Flee / capture resolution

Flee is **not** implicit — it is always an explicit `F` character. Capture is always
an explicit `C`. However, the flee outcome for any action is only known when the *next*
character is observed:

- An action that is **not last** in the current input: if the next character is not `F`,
  the pokemon did not flee on that turn → filter out fled seeds.
- An action that **is last** in the current input: flee status is pending. Do not filter
  for flee until the next prompt.
- When the next prompt arrives, the first non-undo character resolves the pending action:
  `F` → fled, anything else → did not flee. Apply the flee filter retroactively before
  processing the new characters.

This means `u` applied to a `?b` (pending) simply discards the pending state; the
cache is restored to the previous fully-resolved state.


## Seed generation

`generate_seed_window(inputs: CompassSafariInput) -> list[tuple[SafariContext, int, int]]`
  → list of `(context, seed, delay)` triples for all delays in
  `[target_delay - window, target_delay + window]`.

### Two seeds per delay

Within any given second (link), a 30-frame window has two candidate seeds per frame
because we don't know exactly when the second boundary advances:

- **Seed A** ("current second still active"): `f + 2j`
  where `f = calculate_seed(time_i, base_link_delay)` and `j` is the frame index.
- **Seed B** ("second has already advanced"): `t - 2*(30 - j)`
  where `t = calculate_seed(time_i + 1s, base_link_delay + 60)`.

At frame j=0, Seed A and Seed B are identical (`f` and `f`) — only one entry is
generated. For j > 0, they are distinct — two entries are generated for that delay.

### Algorithm

Use `get_times(key_seed)` to get `base_delay` and per-second datetimes.
For each delay `d` in `[target_delay - window, target_delay + window]`:
1. `second_idx = (d - base_delay) // 60`
2. `frame_j    = ((d - base_delay) % 60) // 2`
3. `time_i     = datetimes[second_idx]`
4. `f          = calculate_seed(time_i, base_delay + second_idx * 60)`
5. `seed_a     = f + 2 * frame_j`
6. Emit `(SafariContext.start_encounter(seed_a, pokemon), seed_a, d)`.
7. If `frame_j > 0`:
   - `t      = calculate_seed(time_i + 1s, base_delay + (second_idx + 1) * 60)`
   - `seed_b = t - 2 * (30 - frame_j)`
   - Emit `(SafariContext.start_encounter(seed_b, pokemon), seed_b, d)`.

The returned list is sorted by delay, then seed value. "Closest to target" display
sorts by `|delay - target_delay|` ascending.


## Seed filtering

No new simulation layer needed. Filtering uses `SafariContext` directly:

```python
import copy

def apply_action(
    candidates: list[tuple[SafariContext, int]],
    action: CompassAction,
    filter_fled: bool,
) -> list[tuple[SafariContext, int]]:
    results = []
    for ctx, delay in candidates:
        ctx2 = copy.copy(ctx)
        match action.step:
            case SafariStep.BAIT | SafariStep.BAIT_CRITICAL:
                result = ctx2.throw_bait()
                if action.uncertain:
                    ok = result in (SafariStep.BAIT, SafariStep.BAIT_CRITICAL)
                else:
                    ok = result == action.step
            case SafariStep.MUD | SafariStep.MUD_CRITICAL:
                result = ctx2.throw_mud()
                if action.uncertain:
                    ok = result in (SafariStep.MUD, SafariStep.MUD_CRITICAL)
                else:
                    ok = result == action.step
            case _:  # BALL_0..BALL_3
                result = ctx2.throw_ball()
                if action.uncertain:
                    ok = result in (SafariStep.BALL_0, SafariStep.BALL_1,
                                    SafariStep.BALL_2, SafariStep.BALL_3)
                else:
                    ok = result == action.step
        if not ok:
            continue
        if filter_fled and ctx2.has_fled():
            continue
        results.append((ctx2, delay))
    return results
```

`filter_fled=True` when the action is fully resolved (flee known to not have occurred).
`filter_fled=False` when flee status is still pending (last action in input batch).

For `FleeAction`: filter candidates where the pending action resulted in
`ctx.has_fled() == True`.
For `CaptureAction`: filter candidates where the pending ball action resulted in
`ctx.captured() == True`.

`SafariContext` is mutable, so `copy.copy()` is used to avoid mutating cached states.
A shallow copy suffices since all fields are ints/enums (no nested mutable objects).


## Caching

Stack-based to support undo:

```python
# Each entry: (action_repr: str, candidates_after: list[tuple[SafariContext, int, int]])
cache: list[tuple[str, list[tuple[SafariContext, int, int]]]]
```

- `cache[0]` = initial candidate set (pre-any-action), no action label.
- After each fully-resolved action: push `(action_str, filtered_candidates)`.
- Undo: pop the last entry. Pending (unresolved flee) actions are not pushed until
  resolved — the pending state is held separately.

```python
pending_action: ParsedAction | None = None
pending_seeds:  list[tuple[int, int]] | None = None  # filtered for action, not flee
```


## Display

### Cheatsheet (printed once at session start, reprinted with each prompt)

The cheatsheet maps each input character to the action taken and the in-game message
the player sees for that outcome.

| Key     | Action                        | In-game message                        |
| ------- | ----------------------------- | -------------------------------------- |
| `m`     | Mud, no crit                  | {pokemon} is angry!                    |
| `M`/`a` | Mud, crit (Anger)             | {pokemon} is beside itself with anger! |
| `b`     | Bait, no crit                 | {pokemon} is eating!                   |
| `B`/`e` | Bait, crit (Eating)           | {pokemon} is busy eating!              |
| `0`     | Ball, 0 shakes                | Oh, no! The Pokémon broke free!        |
| `1`     | Ball, 1 shake                 | Aww! It appeared to be caught!         |
| `2`     | Ball, 2 shakes                | Aargh! Almost had it!                  |
| `3`     | Ball, 3 shakes (broke free)   | Shoot! It was so close, too!           |
| `C`     | Captured (ends)               | Gotcha! {pokemon} was caught!          |
| `F`     | Fled (ends)                   | {pokemon} fled!                        |
| `u`     | Undo last action              | —                                      |
| `?x`    | Uncertain result for action x | —                                      |

Spaces and commas in input are ignored.

### Status block (printed before each prompt)

```
Seeds: 47 / 201 remaining
Path:  me2?b
Balls: 27
Closest seeds:
  1. seed=0x1A2B3C4D  delay=19234  Δ=+2
  2. seed=0x1A2B3C51  delay=19232  Δ=0  ← target
  3. ...
```

"Δ" = delay - target_delay (signed, so target is Δ=0). Path is printed with no spaces.

When `len(candidates) <= evaluation_threshold` and `evaluation_strategy` is set,
add a success column evaluated by running `evaluate_context` (see below) on each
candidate's current `SafariContext`:

```
Seeds: 8 / 201 remaining
Path:  me2?b
Balls: 27
Closest seeds:
  #   Seed        Delay   Δ    Success
  1.  0x1A2B3C4D  19234   +2   yes
  2.  0x1A2B3C51  19232    0   no   ← target
  3.  ...
```


## Terminal output

### 0 seeds remaining

```
No matching seed found in window ±{window}.
Consider expanding the search window or checking for input errors.
```

### 1 seed remaining

```
╔══════════════════════════════════╗
║  Seed identified!                ║
║  seed  = 0x1A2B3C51              ║
║  delay = 19232                   ║
║  Δ     = 0 (exact target)        ║
║  path  = me2?b                   ║
╚══════════════════════════════════╝
```

### F or C with multiple seeds remaining

Print the status block showing remaining seeds (not a success or failure), then exit.
Let the user know how many seeds matched and the full list up to `seeds_displayed`.

```
Pokemon fled. {N} seed(s) matched this path:
  1. seed=0x...  delay=...  Δ=...
  ...
```


## Main loop (compass_safari)

```
1.  Validate inputs (CompassSafariInput.__post_init__ handles this).
2.  seeds = generate_seed_window(inputs)   # list[(seed, delay)]
3.  cache = [(None, seeds)]
4.  pending_action, pending_seeds = None, None
5.  Print cheatsheet.
6.  Loop:
    a. current_seeds = pending_seeds if pending_action else cache[-1][1]
    b. Print status block.
    c. If len(current_seeds) == 0: print no-match message, return.
    d. If len(current_seeds) == 1: print success block, return.
    e. raw = input(">> ")
    f. result = parse_input(raw)
    g. If ParseError: print offending characters, continue (reprompt).
    h. For each action in result:
       - UndoAction: pop cache (if len > 1), clear pending; continue.
       - If pending_action exists and action is not UndoAction:
           If action is FleeAction: filter pending_seeds for fled=True → terminal.
           Else: filter pending_seeds for fled=False → push to cache. Clear pending.
       - If FleeAction or CaptureAction: apply, print terminal output, return.
       - If last action in result: apply action filter (no flee), set pending.
       - Else: apply action filter (fled=False included), push to cache.
```


## Evaluate from mid-encounter state

`evaluate_context(ctx: SafariContext, strategy: Strategy, criteria: SuccessCriteria) -> bool`

Simulates the strategy forward from the current `SafariContext` state (which already
has modified flee/capture stages, depleted balls, and current RNG position) and returns
whether the outcome meets `criteria`. This is analogous to the existing `evaluate_seed`
in `chart/__init__.py`, but starts from a mid-encounter context rather than a fresh seed.

Implementation: copy the context, apply the strategy's action sequence until terminal
state, evaluate against criteria. Defined in `compass/__init__.py` or factored into
`safari.py` if it proves generally useful.


## Open questions / deferred

- Future: `*` prefix for "uncertain if action was taken at all".
- `compass_metronome` — stubbed, not designed yet.
