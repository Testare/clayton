# Machete

**Module:** `claytonlib/machete.py`

Once the seed is known, machete asks: *is there a sequence of actions (bait, mud,
ball) that leads to a capture, and what is it?* It simulates turns into the future
over the deterministic RNG and searches for success. Three entry points cover
different needs, plus **Jane**, which builds an optimal decision tree across
several candidate seeds at once.

> Machete currently operates on a single fixed seed / fixed frame rate. Extending
> it to the variable frame rate is the final planned rework — see
> [APPROXIMATE_STATE_OF_THE_PROJECT.md](APPROXIMATE_STATE_OF_THE_PROJECT.md).

## Path syntax

Paths are strings of action characters (matching the compass convention):

| Char | Action / outcome |
|------|------------------|
| `b` / `B` | bait / critical bait |
| `m` / `M` | mud / critical mud |
| `0` `1` `2` `3` | ball, shook that many times (broke free) |
| `C` | ball captured (terminal) |

(`F` flee and `u` undo are **not** valid inside a machete path.)

## Performance model

Machete searches over `safari_compact.py`, which packs a `SafariContext` into a
single integer for O(1) copy and hashing. The compact action order is
**mud → ball → bait** (decisive actions first, to avoid flooding the BFS queue with
long bait-only prefixes). When the Pokémon is in the *will-flee* state, only a ball
can help, so bait and mud are skipped.

## `machete_one` — shortest path (BFS)

```python
machete_one(pokemon_or_ctx, seed=None, path='', max_turns=..., options=None) -> str | None
```

Returns the **shortest** capture path, or `None` if none exists within `max_turns`.
Pass either a `SafariPokemon` + `seed` (+ optional already-taken `path`) or a
mid-encounter `SafariContext`. `max_turns` defaults to
`MacheteOptions().max_turns_one` (50).

## `machete_all` — every path (DFS)

```python
machete_all(pokemon_or_ctx, seed=None, path='', max_turns=..., options=None) -> tuple[list[str], int]
```

Returns `(paths, truncated)` — every capture path found, and a count of branches
that were cut off only because of the depth limit. A non-zero `truncated` means
raising `max_turns` (default `max_turns_all`, 20) may reveal more paths.

## `machete_jane` — optimal decision tree

```python
machete_jane(candidates, pokemon=None, max_turns=..., interactive=False, options=None) -> JaneNode | None
```

When you've narrowed to a small set of candidate seeds but haven't uniquely
identified one, Jane computes the single action plan that maximises capture
probability across all of them, branching on the observable outcome of each throw.

- `candidates` — a list of `(SafariContext, seed)` tuples or plain seed ints
  (requires `pokemon` for plain ints).
- Returns the optimal `JaneNode` tree, `FUTILE_NODE` if no seed has a viable path,
  or `None` if `candidates` is empty.

```python
@dataclass
class JaneNode:
    action:              str        # "BALL" | "BAIT" | "MUD" | "CAPTURED" | "FUTILE"
    probability:         Fraction   # exact probability of reaching this node
    branches:            dict[str, 'JaneNode'] | None   # None ⇒ terminal
    direct_capture_prob: Fraction | None = None         # BALL nodes: P(capture on this throw)
```

Probabilities are exact `fractions.Fraction`, never floats.

## Options

```python
@dataclass
class MacheteOptions:
    max_turns_one: int | None = 50       # BFS depth for machete_one
    max_turns_all: int | None = 20       # DFS depth for machete_all / jane
    log_interval:  int = 500_000         # nodes between progress logs (0 = off)
    parallel:      bool = False          # ProcessPoolExecutor in machete_jane
```

## Related

- Compact simulation: `claytonlib/safari_compact.py`
- Both compasses can hand off directly to machete (`J` / the capture-path prompt).
- Orchestrated versions: `Expedition.machete_one/all/jane()` in [EXPEDITION.md](EXPEDITION.md)
