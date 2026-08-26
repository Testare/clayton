# Expedition

**Module:** `claytonlib/expedition/`  ·  **Entry point:** `expedition(name)`

An expedition is the high-level workflow manager that ties chart, both compasses,
and machete together behind a single object with **persistent configuration**, so
you don't re-enter `key_seed`, `target_delay`, pokemon, strategy, etc. every
session. It's the object you drive from the notebooks.

```python
from claytonlib.expedition import expedition

x = expedition("metang")   # load data/expeditions/metang.json, or create fresh
x.chart_safari()           # each step prompts for any missing config
x.save()                   # persist config + results back to JSON
```

`expedition(name)` returns the named `Expedition`, loading it from
`data/expeditions/<name>.json` if it exists (and caching it in-process), otherwise
creating a new one.

## Stored configuration

An `Expedition` holds everything the tools need, grouped roughly by phase:

- **Chart:** `pokemon_name`, `key_seed`, `setup_delay_seconds`,
  `max_target_seconds`, `strategy_name`, `criteria_name`, `eval_strategy_name`
- **Compass:** `window`, `target_delay`, `initial_time` (ISO string)
- **Metronome compass:** `metronome_second_window`, `compass_m_history`,
  `compass_m_delay` (saved calibration delay), `known_moves`,
  `compass_premetronome_histsize`
- **Results:** `target_seeds`, `target_seeds_path`
- **Validation:** `check_config`

Strategy/criteria/eval names are resolved to real objects through registries in
`expedition/_config.py`, so the JSON stays human-readable.

## Persistence & config management

| Method | Purpose |
|--------|---------|
| `save()` | Write config + results to `data/expeditions/<name>.json`. |
| `reload()` | Discard in-memory changes, re-read from disk. |
| `print()` | Pretty-print the current configuration. |
| `adjust(**kwargs)` | Change one or more already-set fields. |

## Workflow methods

Each method reads stored config, prompts for anything still missing, runs the
underlying tool, and saves results where appropriate.

| Method | Wraps | Notes |
|--------|-------|-------|
| `chart_safari()` | `chart.chart_safari` | Build/extend chain files. |
| `evaluate_chart()` | `chart.evaluate_chart` | Runs `chart_safari()` first if needed. |
| `choose_target()` | — | Presents top-10 / best-10 and prompts you to pick a target delay. |
| `compass_premetronome(second_window=None)` | `compass_premetronome` | Simpler metronome calibration. |
| `metronome_compass(second_window=None)` | `metronome_compass` | Full multi-turn metronome compass. |
| `compass_m_clear()` / `compass_m_suggest()` | — | Clear metronome history / suggest a time (suggest not yet implemented). |
| `compass_safari()` | `compass.compass_safari` | Identify the hit seed; saves resulting `target_seeds`. |
| `machete_one(max_turns=None)` | `machete.machete_one` | Shortest capture path for the chosen seed. |
| `machete_all()` | `machete.machete_all` | All capture paths for the chosen seed. |
| `machete_jane()` | `machete.machete_jane` | Optimal decision tree across all `target_seeds`. |
| `check()` | — | Returns a `CheckHelper` for validating the implementation against this config. |

## Validation helper

`x.check()` returns a `CheckHelper` (config in `check_config`). For example,
`check().chart_check_target_window(window=None)` shows the per-delay seed
evaluation and sliding-window scores around the target delay — useful for sanity
checking a chart before committing to a target.

## Typical end-to-end session

```python
x = expedition("metang")
x.chart_safari()          # 1. chart candidate datetimes
x.evaluate_chart()        # 2. score them
x.choose_target()         # 3. pick a target delay
# ...make the attempt in-game, calibrating with the metronome compass...
x.metronome_compass()     # 4. calibrate timing / frame rate
x.compass_safari()        # 5. identify the seed actually hit
x.machete_jane()          # 6. solve the optimal capture plan
x.save()
```

## Related

Per-tool detail: [CHART.md](CHART.md) · [COMPASS_METRONOME.md](COMPASS_METRONOME.md)
· [COMPASS_SAFARI.md](COMPASS_SAFARI.md) · [MACHETE.md](MACHETE.md). Overall
reworking status: [APPROXIMATE_STATE_OF_THE_PROJECT.md](APPROXIMATE_STATE_OF_THE_PROJECT.md).
