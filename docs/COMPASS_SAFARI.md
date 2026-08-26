# Compass — Safari

**Module:** `claytonlib/compass/`  ·  **Entry point:** `compass_safari(inputs)`

After you make an attempt, you don't know exactly which seed you hit. The safari
compass narrows a window of candidate seeds down to the one you actually landed
on, using the *observable* outcomes of your early safari turns — most powerfully
the number of times a thrown ball shakes, but also critical bait/mud and flees.

It is an **interactive** tool: it prints the current candidate set, you type what
you observed, and it filters. When one candidate remains, it reports the seed (and
can hand off to machete for a capture path).

## Inputs

```python
@dataclass
class CompassSafariInput:
    pokemon:      SafariPokemon
    strategy:     Strategy          # from chart; used for evaluation display
    criteria:     SuccessCriteria
    window:       int               # ± delays around target_delay to consider
    initial_time: dt.datetime       # required
    key_seed:     int               # required
    target_delay: int               # required
    target_seed:  int | None = None # optional; validated as reachable if given
    evaluation_strategy: Strategy | None = None
    evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE
    options:      CompassOptions = CompassOptions()
```

`__post_init__` raises if `target_delay` or `key_seed` is missing, and (when a
`target_seed` is supplied) if it isn't reachable at that delay for the given time.

`CompassOptions`: `starting_ball_count=30`, `seeds_displayed=5`,
`evaluation_threshold=10`, `suggest_jane=True`.

## Input characters

Type the outcomes you observed, one turn at a time (whitespace/commas ignored):

| Char | Meaning |
|------|---------|
| `m` / `M` (or `a`) | mud thrown / **critical** mud |
| `b` / `B` (or `e`) | bait thrown / **critical** bait |
| `0` `1` `2` `3` | ball thrown, shook that many times (0–3, then broke free) |
| `C` | ball captured the Pokémon (terminal) |
| `F` | the Pokémon fled (terminal) |
| `?` *(prefix)* | **uncertain** last observation, e.g. `?b`, `?0` — matches any variant of that action |
| `u` | undo the last action |
| `J` | hand the remaining candidates to [Jane](MACHETE.md) (machete decision tree) |
| `q` | quit |

Note the project-wide convention: internally `filter_fled=True` means the Pokémon
did **not** flee.

## Behaviour

- After each action the candidate list is filtered and re-printed, sorted by
  proximity to `target_delay` (signed Δ shown).
- Flee/capture are terminal: the tool reports every seed consistent with the full
  observed path.
- When exactly one candidate remains it prints the identified seed and offers to
  run `machete_one` from that state.
- When the surviving count is small (below CPU count), it suggests switching to
  Jane with `J`.

## Returns

A list of hex seed strings (e.g. `['0xABCD1234']`) for the seeds matching the
observed path — length 1 when uniquely identified, empty if nothing matched the
window (widen `window`, or check for input mistakes).

## Example

```python
from claytonlib.compass import compass_safari, CompassSafariInput, CompassOptions
from claytonlib.chart import STRATEGY_ONE_MUD, CRITERIA_CAPTURE
from claytonlib.safari import safari_pokemon_by_name
import datetime as dt

seeds = compass_safari(CompassSafariInput(
    pokemon=safari_pokemon_by_name("metang"),
    strategy=STRATEGY_ONE_MUD, criteria=CRITERIA_CAPTURE,
    window=40,
    initial_time=dt.datetime(2026, 8, 26, 12, 0, 0),
    key_seed=0xEC1504DC, target_delay=1234,
))
```

## Related

- Sibling tool for the calibration phase: [COMPASS_METRONOME.md](COMPASS_METRONOME.md)
- Capture solving after identification: [MACHETE.md](MACHETE.md)
- Orchestrated version with saved config: `Expedition.compass_safari()` in
  [EXPEDITION.md](EXPEDITION.md)
