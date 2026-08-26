# File Structure

A map of the repository. The library lives in `claytonlib/`; the Jupyter
notebooks in the project root are the primary interactive interface.

```
clayton/
├── claytonlib/               Core library (imported by the notebooks)
│   ├── __init__.py           Auto-imports every public name from every submodule
│   ├── safari.py             Foundation: SafariPokemon, SafariContext, SafariStep, advance_rng()
│   ├── safari_compact.py     Bit-packed SafariContext for high-performance BFS (used by machete)
│   ├── safari_compact_nb.py  Notebook helpers around the compact representation
│   ├── times.py              Seed ↔ datetime mapping: calculate_seed(), generate_times(), get_times()
│   ├── moves.py              Move data model + loaders (moves.json)
│   ├── chart/                Optimal-datetime evaluation  (see CHART.md)
│   │   ├── __init__.py        Strategy, SuccessCriteria, chart_safari(), evaluate_chart()
│   │   ├── chain.py           Chain links, on-disk chain files, seed expansion
│   │   └── evaluation.py      Frame-rate helpers + EvaluationStrategy scorers
│   ├── compass/              Safari-turn seed identification  (see COMPASS_SAFARI.md)
│   │   ├── __init__.py        compass_safari()
│   │   ├── _types.py          CompassSafariInput, CompassOptions, input parsing
│   │   ├── _core.py           Candidate generation, filtering, evaluation
│   │   └── _display.py        Terminal display helpers
│   ├── compass_premetronome.py  Earlier/simpler metronome-based compass
│   ├── metronome_compass/    Metronome-move seed identification  (see COMPASS_METRONOME.md)
│   │   ├── __init__.py        metronome_compass(), CompassMetronomeInput, simulate_turn()
│   │   ├── path.py            Battle path tokens + rendering
│   │   ├── context.py         Battle/RNG/interactive simulation contexts
│   │   └── effects.py         Per-move effect handlers, Metronome roll pool
│   ├── machete.py            Capture-path solver  (see MACHETE.md)
│   ├── expedition/           High-level workflow orchestration  (see EXPEDITION.md)
│   │   ├── __init__.py        expedition(), Expedition
│   │   └── _config.py         Strategy/criteria registries, CheckConfig
│   ├── testing_utils.py      Shared test helpers
│   └── basedata/             Static factual game data
│       ├── safari_pokemon.json   Catch/flee rates
│       ├── moves.json            Move list
│       └── mdMap.json            Month-day → seed-byte map
│
├── tests/                    unittest suite (~290 tests, stdlib only)
├── docs/                     This documentation
├── notes/                    RNG research notes and gdb reverse-engineering logs
├── one-offs/                 Standalone data-generation scripts (populate_moves.py, etc.)
├── utils/                    gdb helpers for RNG reversing
├── data/                     Generated output (chains, evaluations, expeditions, cached times) — gitignored
├── metronome_seeds/          Recorded metronome calibration data
├── *.ipynb                   Interactive workflow notebooks
├── flake.nix / flake.lock    Nix dev shell (Python, Jupyter, ruff, ARM toolchain)
├── README.md                 Project overview
├── CLAUDE.md / AGENTS.md     Contributor / AI-assistant guidance
└── LICENSE                   MIT
```

## Layering

`safari.py` is the foundation everything builds on. `safari_compact.py` is a
performance-oriented mirror of it. The four tools (chart, compass, metronome
compass, machete) build on those, and `expedition/` sits on top, tying the
tools together with persistent config.

```
                    expedition/
        ┌───────────────┼───────────────┐
      chart/     compass/ + metronome_compass/     machete.py
        └───────────────┼───────────────┘
              safari.py / safari_compact.py / times.py
```

## Terminology note

A **delay** is one hardware-VBlank tick (~59.8261 Hz) and is identical to one
**game frame** (1:1). "Delay" and "frame" are used interchangeably. See
`CLAUDE.md` for the full convention list. The current reworking status of the
tools is tracked in [APPROXIMATE_STATE_OF_THE_PROJECT.md](APPROXIMATE_STATE_OF_THE_PROJECT.md).
