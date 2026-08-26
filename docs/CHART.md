# Chart

**Module:** `claytonlib/chart/`

Chart answers the question *"which datetime should I aim for?"* Given a Pokémon
and a strategy, it walks the seeds reachable from a set of candidate datetimes,
evaluates the capture outcome of every one, and ranks time windows by how likely
they are to land on a winning battle seed.

> Status: Chart currently assumes a fixed frame rate for parts of its modelling
> and is one of the tools being reworked for the variable real frame rate. See
> [APPROXIMATE_STATE_OF_THE_PROJECT.md](APPROXIMATE_STATE_OF_THE_PROJECT.md).

## Core concepts

- **Strategy** — a named action-selection function `SafariContext -> SafariStep`.
  Wraps the decisions a player would make each turn (throw bait/mud/ball).
- **SuccessCriteria** — a named predicate `SafariContext -> bool` deciding whether
  a simulated encounter counts as a success.
- **Chain** — the sequence of seeds produced by advancing the RTC one second at a
  time from a starting datetime. Each second is a *chain link*
  `(from_seed, to_seed, n_delays)` where `n_delays` is 59 or 60 (a delay is one
  game frame). Expanding a link yields two candidate seeds per delay: one where
  the RTC second has not yet ticked (`seed_a`), one where it has (`seed_b`).
- **Chart** — a directory of chain files (one per candidate datetime) plus an
  `evaluations/` subdirectory of scored results.

## Built-in strategies and criteria

| Name | Meaning |
|------|---------|
| `STRATEGY_ONLY_BALLS` | Throw a ball every turn. |
| `STRATEGY_ONE_MUD` | One mud on turn 0, then balls. |
| `STRATEGY_SIX_BAIT` | Six baits, then balls. |
| `CRITERIA_CAPTURE` | The Pokémon was captured. |
| `CRITERIA_WONT_FLEE_10_TURNS` | Survived ≥10 turns still watching (won't flee). |
| `CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS` / `..._5_BALLS` | After N balls thrown, a machete search finds a capture path. |

`machete_x_turns_n_balls_criteria(turns, n_balls)` builds a criteria that, after
`n_balls` have been thrown, asks machete for a path within `turns` turns.

## Inputs

```python
@dataclass
class ChartSafariInput:
    key_seed: int                 # identifies the RTC base (base_delay = key_seed & 0xFFFF)
    setup_delay_seconds: int      # minimum elapsed seconds before the target window opens
    max_target_seconds: int       # last second to chart
    strategy: Strategy
    criteria: SuccessCriteria
    pokemon: SafariPokemon
    project_label: str | None = None
    options: ChartOptions = ChartOptions()
```

`ChartOptions` tunes batch sizes and resume validation
(`evaluation_frames_per_write_cycle`, `resume_validation_enabled`, …).

## Workflow

```python
from claytonlib.chart import (
    ChartSafariInput, chart_safari, evaluate_chart,
    STRATEGY_ONE_MUD, CRITERIA_CAPTURE, SlidingWindowSum,
)
from claytonlib.safari import safari_pokemon_by_name

inputs = ChartSafariInput(
    key_seed=0xEC1504DC,
    setup_delay_seconds=..., max_target_seconds=...,
    strategy=STRATEGY_ONE_MUD, criteria=CRITERIA_CAPTURE,
    pokemon=safari_pokemon_by_name("metang"),
)

chart_safari(inputs)                       # build/extend chain files (resumable)
evaluate_chart(inputs, SlidingWindowSum()) # score and rank into evaluations/
```

- `chart_safari(inputs, store=None)` — evaluates each chain link and appends the
  packed result bitmask to the chain file. Resumable: re-running continues where it
  left off.
- `evaluate_chart(inputs, strategy, store=None, eval_max_seconds=None)` — reads all
  chains, scores each frame with an `EvaluationStrategy`, and writes
  `evaluations/<strategy.filename>.json` with per-chain top-5 and a cross-chain
  top-10 (deduplicated by `(delay, score)`).
- `evaluate_chart_top_10(inputs, strategy, store=None)` — convenience printout of
  the best results.
- `evaluate_seed(seed, pokemon, strategy, criteria)` — evaluate a single seed
  directly (no chart needed).

### Evaluation strategies

`EvaluationStrategy` defines the scoring/aggregation and its output filename:

- **`SlidingWindowSum`** — sums success flags over a sliding window of neighbouring
  delays (robustness to landing a delay or two off target).
- **`NormalWindow`** — weights neighbours by a normal distribution.

## Output layout

```
data/[<project_label>/]<pokemon>_<KEY_SEED_HEX>/chart_<strategy>_<criteria>/
    <YYYY-MM-DD_HH-MM-SS>+<setup_delay_seconds>.chain     # one per candidate datetime
    evaluations/<strategy.filename>.json                  # scored + ranked results
```

## Related

- Foundation types: `claytonlib/safari.py`
- Frame-rate helpers and scorers: `claytonlib/chart/evaluation.py`
- Downstream: once a target time is chosen, [COMPASS_SAFARI.md](COMPASS_SAFARI.md)
  identifies the seed actually hit and [MACHETE.md](MACHETE.md) solves the capture.
