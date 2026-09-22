# 5. Safari Chart

Safari Chart answers one question: **which datetime should I boot on, and how long should
timer 3 be?**

It searches every datetime that produces your key seed, and for each one works out the best
countdown and how likely that attempt is to end in a capture.

## Before you start

- Your own calibration model, active ([page 4](04-metronome-compass.md))
- Key seed and key-seed advances set on the expedition
- Block scores set, if you want the in-house frame search ([page 7](07-safari-blocks.md))

## Charts

A **chart** is a strategy paired with a success condition. You can have several per
expedition and compare them.

**Safari Chart → Find Target → New chart.**

### Strategies — what you'll do each turn

| Strategy | What it assumes |
|---|---|
| **Balls only** | Throw a ball every turn. Simplest |
| **One mud, then balls** | One mud first (raises catch rate), then balls |
| **Six bait, then balls** | Six bait first (suppresses fleeing while it lasts), then balls |

### Criteria — what counts as success

| Criteria | Success means |
|---|---|
| **Captured** | You caught it. The obvious goal |
| **Machete path after N balls** | A solved capture path exists after N balls |
| **Lasted N turns** | Still on screen after N turns — not caught |
| **Lasted N balls** | Caught, or N balls without fleeing |

The last two are for **data gathering**, not catching. A long observed path identifies the
seed precisely, which is what calibration wants. `Captured` is what you use for a real
attempt.

### The window

`setup_delay_seconds` to `max_target_seconds` bounds the countdown. The lower bound must be
long enough to actually do your setup — 180 s is a sensible floor.

> **Screenshot:** the New chart form.

## Computing

**Compute chart** builds the *canon map* — every seed reachable in your window, and what
happens to each under this strategy.

This takes a while and shows a progress bar with an ETA. You can navigate away; it keeps
running and reports back.

It is **resumable and extendable**. Re-running after widening the window computes only the
gap. It is also **model-independent**: refitting your calibration does not invalidate it.

> Charts with the same Pokémon, key seed, strategy and criteria **share** one canon map — the
> `reuse` figure in Manage Data shows how much that saved.

## Ranking

**Rank targets** scores every candidate boot time.

The first run on a chart takes around 35 seconds and shows a progress bar. The result is then
**cached to disk**, so ranking again is instant — including after restarting the app. The
cache invalidates itself whenever anything that feeds it changes: the model, the chart, the
advance count, the precomputed data.

You get a table:

| Column | Meaning |
|---|---|
| **initial time** | the DS clock datetime to aim Seed A at |
| **Vector ms** | the countdown for timer 3 |
| **target delay** | the frame Seed B is predicted to land on |
| **P(capture)** | modelled chance this attempt ends in a capture |
| **σ** | the spread of the landing frame. Smaller is tighter |

> **Screenshot:** the ranked targets table.

### Reading the numbers

**P(capture) is a real probability, not a score.** 28% means roughly one attempt in four.
Safari Zone Pokémon flee; that is the game, not the tool.

**σ is your own precision**, from your calibration. If it's wide, more calibration runs will
do more for you than hunting for a better target.

**Prefer a slightly worse target that you can actually hit.** A 30% target at an awkward
datetime you'll rush is worse than a 27% one you can set up calmly.

## Examining a target

**Examine** breaks a target down by candidate RTC second — how likely each second is, and the
capture chance within it. Click a second for the individual seeds behind it.

This is how you see *why* a target is good: whether its probability rests on one second going
right, or is spread across several.

> **Screenshot:** the Examine breakdown.

## Saving a target

**Save target** keeps it on the expedition so both compasses can pick it up without retyping.

The saved `P(success)*` is **frozen from when you saved it**. Re-examine to score it against
your current model — after recalibrating, the live number will have moved.

## Find best target at a specific time

Already committed to a datetime? This ranks countdowns for that one boot time. It declusters
by default, so you get genuinely different options rather than a clump of near-identical
frames around one peak.

## Manage Data

Charts, their computed data and its size on disk, and your saved targets.

- **Delete computed data** frees the canon map; the chart stays and can rebuild.
- **Delete chart** also removes its computed data — unless another chart shares the map, in
  which case the map survives.

---

Next: [Safari Compass](06-safari-compass.md)
