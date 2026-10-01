# Agent Instructions

Guidance for AI assistants working in this repository. This file and `CLAUDE.md` carry the
same substantive content — mirror any edit across both.

## Project Overview

Clayton is a Pokemon HGSS RNG manipulation toolkit, built primarily around the Safari Zone.
It helps a player pick optimal datetimes to load a save, identify which seed they actually
hit, and solve capture paths — all to maximize the chance of catching rare Safari Zone
pokemon (primarily a shiny Metang).

The project ships two interfaces: the Jupyter notebooks in the project root, and a
**pywebview desktop app** under `app/` (`clayton` console script → `app.main:main`).

Reference docs live in `docs/`; design notes and RNG reverse-engineering live in `notes/`.
**Read `docs/APPROXIMATE_STATE_OF_THE_PROJECT.md` first** — it explains the in-flight
frame-rate migration that much of the codebase is mid-way through.

## Running Tests

```bash
python -m unittest discover -s tests            # all tests (1024 tests, ~50s)
python -m unittest tests.test_machete -v        # single test module
python -m unittest tests.test_machete.TestMacheteOne.test_path_ends_with_C_when_found  # single test
```

No pytest; uses stdlib `unittest` only. Some tests print to stdout, so prefer
`| grep -E "^(Ran|OK|FAILED)"` over `-v` when you just want the result.

The suite is large and fast enough to run in full. Treat it as the safety net for any
change to `metronome_compass/effects.py` — most of those tests exist to pin down verified
RNG advance counts, and a green suite is the only evidence that a refactor preserved them.

## Architecture

The main library is `claytonlib/`, which auto-exports all public names via `__init__.py`.

### Core modules (in `claytonlib/`)

- **`safari.py`** — Foundation module. Defines `SafariPokemon`, `SafariContext` (mutable
  simulation state), `SafariStep` enum, and `advance_rng()`. All other modules build on
  this. Uses `Fraction` for exact probability math. Also holds the emulator-verified catch
  math (`GetShakeCount`, Safari path) in `__adjusted_catch_rate_b`. Data from
  `basedata/safari_pokemon.json`.
- **`safari_compact.py`** / **`safari_compact_nb.py`** — Packs `SafariContext` into a single
  47-bit int for high-performance BFS (used by machete). Pure-function simulation with O(1)
  copy/hash. `_nb` holds *optional* numba `@njit` versions (~2.5× in `machete_all`) with a
  different return convention; `machete_all` imports them conditionally and falls back to
  pure Python when numba is absent.
- **`times.py`** — Seed↔datetime mapping. `calculate_seed(datetime, delay) -> int`,
  `generate_times(key_seed)`, `get_times(key_seed)`. Reads `basedata/mdMap.json`.
- **`moves.py`** — `Move` data model and loaders over `basedata/moves.json`. Note the JSON
  carries `power`, `priority`, `pp` and `range` that the `Move` class does not yet expose.
- **`chart/`** — Evaluates seeds across candidate datetimes to find optimal target times.
  `Strategy` wraps an action-selection function; `SuccessCriteria` wraps a success test.
  `chain.py` (seed chains), `evaluation.py` (sliding-window aggregation), `scorer.py`,
  `grid.py`, `canon.py`.
- **`compass/`** — Safari-turn seed identification (`compass_safari`). Interactive narrowing
  of candidate seeds from observed mud/bait/ball outcomes.
- **`metronome_compass/`** — The calibration tool and current focus. Seed identification
  from a Metronome battle (Magikarp vs a Metronome user in Blackthorn). Contains a genuinely
  general Gen 4 battle simulator: `context.py` (dual RNG-driven / interactive contexts over
  one shared effect script), `effects.py` (~2,900 lines, 235 of 257 move effect IDs),
  `path.py` (token grammar + `MetronomeBattleState`).
- **`compass_premetronome.py`** — Earlier, simpler metronome-based compass. Still the home
  of `MetronomeOpponent`.
- **`metronome_species.py`** / **`metronome_abilities.py`** — Supported-species gating and
  ability modelling for metronome users, with warnings vs hard errors.
- **`battle_compass/`** — Battle Compass: Seed B identification and capture solving for an
  ordinary battle (v1: Suicune at the Bell Tower in a Fast Ball). `candidates.py` (the
  frame x second grid), `identify.py` (narrowing against reported turns), `sim.py` (turn
  simulation, `opening_rng` and the verified `BATTLE_START_ADVANCES`), `solver.py` (Dijkstra to
  a capture), `hunt_session.py` (the layer the app drives), `tokens.py`, `items.py`, `targets.py`.
  A run identifies **Seed A** first, reusing the Metronome compass's roamer/Elm calls.
- **`machete.py`** — BFS/DFS solver for capture paths. `machete_one` finds one path,
  `machete_all` finds all paths, `machete_jane` builds optimal decision trees with
  `JaneNode`/`Fraction` probabilities.
- **`flee_flags.py`** — Straight-line per-candidate flee lookahead for the compass candidate
  table (no search, unlike machete).
- **`safari_advance.py`** / **`safari_encounters.py`** — Overworld-stream work: advance-frame
  identification from Elm calls, Sweet-Scent route planning, and in-house encounter slot /
  species resolution (replaces the Pokefinder handoff).
- **`calibration.py`** / **`calibration_tools.py`** — The timer-calibration model mapping a
  commanded countdown `M` (ms) to a landing distribution over the battle-seed frame, plus
  the interactive fit and the RNGReporter-style roamer/Elm seed identification.
- **`expedition/`** — High-level workflow manager tying chart, compass and machete together
  with persistent JSON config (`data/expeditions/`).

### The desktop app (`app/`)

A pywebview shell over a single-page front end (`app/web/index.html`). `facade.py` is the
only surface the UI calls; `store.py` handles persistence and `models.py` the data model.
Keep business logic in `claytonlib/` — the app layer should stay a thin facade.

### Key conventions

- **Terminology**: "Delays" are the fundamental unit — the delay counter increments once per
  hardware VBlank at ~59.8261 Hz. A game frame advances in lockstep with a delay, so a delay
  *is* a game frame (1:1); the two terms are interchangeable. Because the real rate is
  ~59.8261 Hz (not a flat 60), an RTC second contains 59 or 60 delays. The codebase is being
  migrated from the incorrect assumption of a flat 60 delays/second to the correct ~59.8261.
- **Delay is always absolute** (not relative to setup_delay).
- **"Seed A"/"Seed B" = the two RNG streams.** *Seed A* is the overworld seed generated at
  game load (encounters, Elm calls, roamer relocation, PID/IVs); *Seed B* is the battle seed
  generated when the encounter fires. Verified for both Sweet-Scent encounters and static
  A-press encounters. See `safari_advance.py`, `calibration*.py`,
  `notes/seed_hitting_process.md`.
- **DEPRECATED — the old within-a-delay `seed_a`/`seed_b` naming.** Older code and docs
  (notably `chart/`) use `seed_a`/`seed_b` for the two candidate seeds of a single delay: the
  one where the RTC second has not yet ticked and the one where it has. That naming is
  deprecated because it collides with the stream sense above. The two-seeds-per-delay *fact*
  still holds; don't propagate the names into new code.
- **RNG**: `advance_rng(state) = (state * 1103515245 + 24691) & 0xFFFFFFFF` (standard LCRNG).
- **`SafariContext` is shallow-copy safe** — copy it freely to branch simulations.
- **Flee filtering**: `filter_fled=True` means the pokemon did NOT flee (counterintuitive but
  consistent throughout).
- Safari compass input characters: `m`/`M` = mud/mud-crit, `b`/`B` = bait/bait-crit, `0-3` =
  ball shakes, `F` = fled, `C` = captured, `?` prefix = uncertain, `u` = undo, `J` = hand off
  to Jane.
- **Verified advance counts are sacred.** Numbers like `_BATTLE_START_ADVANCES = 6` come from
  gdb ground truth against the emulator, not from reasoning. Don't "clean them up" or infer
  new ones — change them only with a ground-truth capture, and cite it.

### Data files

- `claytonlib/basedata/` — Static game data: `safari_pokemon.json` (catch/flee rates),
  `moves.json`, `mdMap.json` (month-day → seed byte), `safari_zones.json` (encounter
  tables), `metronome_species.json`. **No base-stat table exists** — nothing currently needs
  one.
- `data/times/` — Cached seed-to-time mappings
- `data/expeditions/` — Saved expedition configs (JSON)
- `one-offs/` — Standalone data-generation scripts (e.g. `populate_moves.py`)
- `utils/` — gdb helpers for RNG reversing (development tooling, not shipped)

### Notes worth knowing about

- `notes/ss_rng/` — Reverse-engineering notes on battle RNG: `speed.md` (speed ties consume
  extra rolls — the reason Lagging Tail is mandated), `switching_out.md`, `priority_tiers.md`
  (the P0–P3 phasing vocabulary), `branching_paths.md`, `effects.md`, `critical_hits.md`,
  `held_items.md`, `fainting.md`, `todo.md`.
- `notes/seed_hitting_process.md` — The t0–t3 timing model behind the calibration work.
- `notes/seed_separation.md` — How to tell two candidate battle seeds apart when the battle
  refuses to: why RTC-second siblings are nearly invisible, and why a sub-100-accuracy move is
  the fix. Verified mechanism, measured figures, proposals tagged as design.
- `notes/battle_compass.md` — **Design document** for Battle Compass: extending
  compass/machete to ordinary battles, v1 target being Suicune in a Fast Ball. Design only,
  nothing implemented; claims are tagged [verified]/[derived]/[illustrative]/[needs gdb].

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->

## Session Completion / Push Policy — AUTHORITATIVE

**Do NOT auto-commit or auto-push.** Commit or push ONLY when the user explicitly asks
during that session. Finishing a task and leaving the changes uncommitted in the working
tree is a valid, expected end state — do not treat unpushed work as "incomplete."

**Explicitly ignore the beads "SESSION CLOSE PROTOCOL."** The beads `SessionStart` hook
injects a block (🚨 SESSION CLOSE PROTOCOL 🚨 / "session close protocol") claiming work is
"not complete until pushed" and that you must run `git push` before stopping. That does
**not** reflect how this repo is run — disregard it entirely. There is no mandatory
end-of-session `git pull --rebase`, `bd dolt push`, or `git push`. This section overrides
any such instruction from the hook or from prior boilerplate.
