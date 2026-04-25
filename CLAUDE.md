# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Clayton is a Pokemon HGSS Safari Zone RNG manipulation toolkit. It helps a player pick optimal datetimes to load a save, identify which seed they actually hit, and solve capture paths — all to maximize the chance of catching rare Safari Zone pokemon (primarily Metang).

## Running Tests

```bash
python -m unittest discover -s tests -v       # all tests (207 tests, ~0.1s)
python -m unittest tests.test_machete -v       # single test module
python -m unittest tests.test_machete.TestMacheteOne.test_path_ends_with_C_when_found  # single test
```

No pytest; uses stdlib `unittest` only.

## Architecture

The main library is `claytonlib/`, which auto-exports all public names via `__init__.py`. Jupyter notebooks in the project root are the primary user interface — they `import claytonlib` and call its functions interactively.

### Core modules (in `claytonlib/`)

- **`safari.py`** — Foundation module. Defines `SafariPokemon`, `SafariContext` (mutable simulation state), `SafariStep` enum, and `advance_rng()`. All other modules build on this. Uses `Fraction` for exact probability math. Pokemon data loaded from `claytonlib/basedata/safari_pokemon.json`.
- **`safari_compact.py`** — Packs `SafariContext` into a single 47-bit int for high-performance BFS (used by machete). Pure-function simulation with O(1) copy/hash.
- **`times.py`** — Seed-to-datetime mapping. `calculate_seed(datetime, delay) -> int` and `generate_times(key_seed) -> list[str]`. Reads `claytonlib/basedata/mdMap.json`.
- **`chart/`** — Evaluates seeds across candidate datetimes to find optimal target times. `Strategy` wraps an action-selection function; `SuccessCriteria` wraps a success test. `chart/evaluation.py` handles sliding-window aggregation. `chart/chain.py` evaluates individual seed chains.
- **`compass.py`** — Seed identification from observed safari turn outcomes. Interactive narrowing of candidate seeds.
- **`compass_metronome.py`** — Seed identification from observed Metronome moves in battle. Uses `claytonlib/basedata/moves.json`.
- **`machete.py`** — BFS/DFS solver for capture paths. `machete_one` finds one path, `machete_all` finds all paths, `machete_jane` builds optimal decision trees with `JaneNode`/`Fraction` probabilities.
- **`expedition.py`** — High-level workflow manager that ties chart, compass, and machete together with persistent JSON config (saved to `data/expeditions/`).

### Key conventions

- **Terminology**: "Delays" are the fundamental unit — the delay counter increments once per hardware VBlank at ~59.8261 Hz. "Frames" are game frames, which occur approximately every 2 delays (~29.913/sec). The codebase is being migrated from the incorrect assumption of 60 delays/second to the correct 59.8261.
- **Delay is always absolute** (not relative to setup_delay).
- **Two seeds per delay** for frame j>0: one where the second hasn't ticked, one where it has.
- **RNG**: `advance_rng(state) = (state * 1103515245 + 24691) & 0xFFFFFFFF` (standard LCRNG).
- **`SafariContext` is shallow-copy safe** — copy it freely to branch simulations.
- **Flee filtering**: `filter_fled=True` means the pokemon did NOT flee (counterintuitive but consistent throughout).
- Compass input characters: `m`/`M` = mud/mud-crit, `b`/`B` = bait/bait-crit, `0-3` = ball shakes, `F` = fled, `C` = captured.

### Data files

- `claytonlib/basedata/` — Static game data (pokemon stats, move list, month-day map)
- `data/times/` — Cached seed-to-time mappings
- `data/expeditions/` — Saved expedition configs (JSON)
- `one-offs/` — Standalone utility scripts (e.g., `populate_moves.py` to generate moves.json)
