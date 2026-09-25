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

> 🚧 **Current status:** We have a coded app and a guide! Please test both out and
> give us any feedback you have.

## How it works

Randomness in HGSS is seeded from the clock and the number of game frames elapsed.
Two seeds matter here:

- **Seed A, "Initial seed"** — the seed hit via RNG manipulation (chosen datetime). Together
  with RNG advances it determines which Pokémon you encounter.
- **Seed B, "Battle seed"** ("target seed") — created for the battle, driving random events
  within it (ball shakes, bait/mud crits, flee rolls).

The toolkit is organized around four cooperating tools:

| Tool                    | Module                          | Purpose                                                                                                                                |
| ----------------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **Chart**               | `claytonlib/chart/`             | Evaluate seeds across candidate datetimes to find the time that gives the best odds of landing on a winning battle seed.               |
| **Compass — Metronome** | `claytonlib/metronome_compass/` | Calibrate timers by identifying battle seeds from observed Metronome moves (fighting Magikarp against a fixed-moveset Chansey).        |
| **Compass — Safari**    | `claytonlib/compass/`           | Identify which seed you hit from observed in-battle outcomes (ball shakes, critical bait/mud, flees).                                  |
| **Machete**             | `claytonlib/machete.py`         | BFS/DFS solver that simulates turns ahead to find action sequences leading to a successful capture, and builds optimal decision trees. |

`claytonlib/expedition/` is the high-level workflow manager that ties Chart,
Compass, and Machete together with persistent config.

## Guide

The guide to its use and installation is in the [guide](./guide/README.md) folder

## License

Original code is released under the [MIT License](LICENSE). Pokémon and all related
names are trademarks of Nintendo, Game Freak, and The Pokémon Company. This project
claims no rights to them.
