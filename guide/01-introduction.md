# 1. Introduction

## What Clayton does

| Tool | What it's for |
|---|---|
| **Metronome Compass** | Measures *your* setup: how many frames actually elapse during a countdown of a given length. Everything else depends on this. |
| **Safari Chart** | Given your calibration, searches every candidate boot datetime and tells you which ones give the best chance of a capture — and how good that chance is. |
| **Safari Compass** | During a run, narrows down which seed you *actually* hit from what you see on screen, and solves the capture path from there. |

## The shape of a hunt

```
  Set up a profile and an expedition            once per game / per target
        │
        ▼
  Calibrate with Metronome Compass (Optional)   a handful of runs, once per setup
        │
        ▼
  Safari Chart → pick a target                  (initial time, Vector ms)
        │
        ▼
  Run it: boot, load, advance, Sweet Scent
        │
        ▼
  Safari Compass → identify the seed you hit
        │                                     ↑
        ├── caught it?  done                  │
        └── missed?  save the run ────────────┘   feeds back into calibration
```

The loop matters. A missed attempt might not be wasted: saving the run improves your calibration,
which makes the next target more accurate.

## What Clayton does not do

- **It won't find the seed for you.** Use PokeFinder or RNG Reporter to work out which seed
  produces the Pokémon you want, then tell Clayton about it.
- **It won't teach you to hit a seed.** Setting the DS clock, timing the boot, hitting an
  initial seed — that's assumed knowledge.
- **It won't place your blocks.** See [Safari blocks](07-safari-blocks.md) for what's needed
  and why.

---

Next: [Getting started](02-getting-started.md)
