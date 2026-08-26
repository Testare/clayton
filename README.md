# Clayton

**A Pokémon HeartGold/SoulSilver Safari Zone RNG-manipulation toolkit.**

Clayton helps a player pick optimal datetimes to load a save, identify which RNG
seed they actually hit, and solve capture paths — all to maximize the chance of
catching rare Safari Zone Pokémon (primarily Metang, with the ultimate goal of a
shiny one).

> ⚠️ **Unofficial fan project.** This is a hobby tool for RNG research and is not
> affiliated with or endorsed by Nintendo, Game Freak, or The Pokémon Company. It
> contains **no ROMs, game assets, or copyrighted code** — only original analysis
> code and factual game data (base stats, move lists, etc.). You must supply your
> own legally-obtained game to use it. See [LICENSE](LICENSE).

> Disclaimer 2: This project is kinda rough-shod right now. Once we have the
> tools in a working state we'll try to clean up and make the tools a little more
> accessible and well tested, but for now be patient as we break stuff and try
> to make working tools!

> 🚧 **Current status:** for a candid rundown of where the project actually stands
> and what still needs reworking, read
> [`docs/APPROXIMATE_STATE_OF_THE_PROJECT.md`](docs/APPROXIMATE_STATE_OF_THE_PROJECT.md).

## How it works

Randomness in HGSS is seeded from the clock and the number of game frames elapsed.
Two seeds matter here:

- **Initial seed** — the seed hit via RNG manipulation (chosen datetime). Together
  with RNG advances it determines which Pokémon you encounter.
- **Battle seed** ("target seed") — created for the battle, driving random events
  within it (ball shakes, bait/mud crits, flee rolls).

The toolkit is organized around four cooperating tools:

| Tool | Module | Purpose |
|------|--------|---------|
| **Chart** | `claytonlib/chart/` | Evaluate seeds across candidate datetimes to find the time that gives the best odds of landing on a winning battle seed. |
| **Compass — Metronome** | `claytonlib/metronome_compass/` | Calibrate timers by identifying battle seeds from observed Metronome moves (fighting Magikarp against a fixed-moveset Chansey). |
| **Compass — Safari** | `claytonlib/compass/` | Identify which seed you hit from observed in-battle outcomes (ball shakes, critical bait/mud, flees). |
| **Machete** | `claytonlib/machete.py` | BFS/DFS solver that simulates turns ahead to find action sequences leading to a successful capture, and builds optimal decision trees. |

`claytonlib/expedition/` is the high-level workflow manager that ties Chart,
Compass, and Machete together with persistent config.

## Documentation

Detailed docs live in [`docs/`](docs/), including [Current project status](docs/APPROXIMATE_STATE_OF_THE_PROJECT.md) — where things actually stand and what's being reworked.

## Requirements

- Python **3.10+** (standard library only — no third-party runtime dependencies)
- Jupyter (optional, for the interactive notebooks)

There is also a [Nix flake](flake.nix) providing a dev shell with Python, Jupyter,
`ruff`, and the ARM toolchain used for RNG reverse-engineering.

## Getting started

```bash
git clone https://github.com/Testare/clayton.git
cd clayton

# Run the test suite (stdlib unittest, ~0.3s)
python -m unittest discover -s tests -v

# Or drop into the Nix dev shell
nix develop
```

The library auto-exports its public API, so interactive use is simply:

```python
import claytonlib

# Map a datetime + delay to an initial seed
seed = claytonlib.calculate_seed(some_datetime, delay)

# ...then use chart / compass / machete to plan and identify runs
```

The Jupyter notebooks in the project root (e.g. `Expedition Workflow.ipynb`)
are the primary interactive interface and show end-to-end workflows.

## Project layout

```
claytonlib/            Core library (imported by the notebooks)
  safari.py            Foundation: SafariPokemon, SafariContext, advance_rng()
  safari_compact.py    Bit-packed SafariContext for high-performance BFS
  times.py             Seed <-> datetime mapping
  chart/               Optimal-datetime evaluation
  compass/             Seed identification from safari-turn outcomes
  metronome_compass/   Seed identification from Metronome moves
  machete.py           Capture-path solver
  expedition/          High-level workflow orchestration
  basedata/            Static factual game data (stats, moves, month-day map)
tests/                 unittest suite (~290 tests)
notes/                 RNG research notes and reverse-engineering logs
one-offs/              Standalone data-generation scripts
utils/                 gdb helpers for RNG reversing
*.ipynb                Interactive workflow notebooks
```
## Running tests

```bash
python -m unittest discover -s tests -v                      # everything
python -m unittest tests.test_machete -v                     # one module
python -m unittest tests.test_machete.TestMacheteOne.test_path_ends_with_C_when_found
```

## License

Original code is released under the [MIT License](LICENSE). Pokémon and all related
names are trademarks of Nintendo, Game Freak, and The Pokémon Company. This project
claims no rights to them.
