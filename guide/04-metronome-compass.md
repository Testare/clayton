# 4. Metronome Compass

**Do this before anything else.** Safari Chart's targets are only as good as the model behind
them, and until you calibrate you are using one fitted on somebody else's hardware.

## What it measures

One number, over and over: **for a countdown of length M, how many frames actually elapse?**

The relationship is close to linear — roughly 59.83 frames per second — but the intercept and
the scatter are yours. They depend on your console, your cartridge or flashcart, and how
consistently you press.

## Why Metronome

You need a way to see *exactly* which battle seed you landed on. Metronome does that: it picks
a move at random from the full move list, so the sequence of moves across a battle is a
near-unique fingerprint of the seed.

Feed Clayton the moves you saw, and it tells you precisely which seed produced them.

The Magikarp in the lake outside is the usual target — easy to reach, easy to re-encounter.

### Setting up a Metronome user

**Profile → Metronome users → Add.** You need a Pokémon that:

- knows **Metronome**
- ideally knows **nothing else** (every extra move adds ambiguity)
- holds a **Lagging Tail** (so it always moves second, making the opponent's roll readable)
- has an ability that doesn't interfere

Chansey with Natural Cure is the classic. Clayton will warn you about unsuitable choices and
will *block* ones that make identification impossible — Serene Grace, for instance, changes
the rolls.

> **Screenshot:** the Metronome user form, with the suitability warnings.

## Doing a calibration run

**Metronome Compass → New Run.**

### Set the target

| Field | What to put |
|---|---|
| Metronome user | The one you just made |
| Initial time | The datetime you're aiming to hit Seed A on |
| Vector ms | The countdown you're going to time |

For calibration, **vary Vector ms between runs**. A model fitted on six runs all at 300,000 ms
knows one point on a line and has to guess the slope. Spread them — 180,000 / 240,000 /
300,000 / 360,000 and so on — and the fit gets much better fast.

### Identify Seed A

Run your timers 1 and 2, then tell Clayton what you observed:

- **Roamer starting positions (R E L)** — the routes the three roamers *started* on, in
  Raikou / Entei / Latias-or-Latios order. Use `-` for any that isn't roaming.
- **± seconds / ± delays** — how wide to search. Start wide, tighten as you learn your setup.
- **Observed roamer routes** — where they are *now*, same order. `.` matches any.
- **Elm calls heard** — the phone calls as letters: `P`, `E`, `K`.

The candidate list narrows as you type. When one row is left, Seed A is identified.

> **Screenshot:** Seed A narrowing down to a single candidate.

### Identify Seed B

Now run timer 3 and get into the Magikarp battle. Clayton asks about the battle one turn at a
time — what Metronome called, what happened — and eliminates candidates as you answer.

It searches around where **your active calibration model predicts Seed B lands** for the
Vector ms you entered. On a fresh profile that prediction comes from the Standard model and
may be some way off; widen **± delays** until you find it. This gets much tighter once you
have your own model.

> **Screenshot:** the Seed B narrowing questions.

### Save the run

**Save Run.** Tag it — a tag groups a session, and you can exclude a whole bad session later
in one click.

Save **every** run, including ones where you missed badly. The fit wants to see your spread,
not just your successes. Only leave out runs where something genuinely went wrong (you
fumbled a press, the game did something unexpected) — and even then, prefer excluding it in
Review Data over never saving it.

## How many runs?

Rough guidance:

| Runs | What you get |
|---|---|
| under 6 | not really a fit — the model is guessing |
| 6–15 | usable; expect targets to be approximate |
| 15–30 | good; this is where most people should aim |
| 30+ | diminishing returns unless you change hardware |

**Spread of Vector ms matters more than raw count.** Fifteen runs across a wide range beat
thirty runs all at the same countdown.

## Building the model

**Metronome Compass → Review Data → Calibrate Model.**

You'll see a live preview of the fit against your saved runs. Key numbers:

| Parameter | What it means |
|---|---|
| `beta` | frames per millisecond — should land near 0.0598 |
| `alpha` | the intercept — your setup's fixed offset |
| `jitter_c` | your scatter. Lower is better; it sets how wide every search has to be |
| `rtc_offset_seconds` | how far the battle second sits from the countdown |

The **reason** column flags runs left out of the fit — `manual` (you excluded it), `tag:...`
(its whole tag is excluded), or `outlier` (automatically flagged as far off-trend).

> An `outlier` is worth a look rather than a shrug. One genuine misfire is fine. Several
> suggests something systematic — the wrong Metronome user, a misread move, a timer stage set
> wrong.

Happy with it? **Save new model**, and tick *make active*. Every tool now scores against it.

> **Screenshot:** the Calibrate Model preview with the parameter comparison.

## Reading the Runs table

| Column | What it tells you |
|---|---|
| **Vms** | the countdown you commanded |
| **V delay** | the frame difference you actually got (Seed B − Seed A) |
| **Δ delay** | how far that sits from what the active model predicted |

**Δ delay is the one to watch.** Near zero means the model describes that run well. A value
badged in amber is more than 2σ out — worth investigating before it drags the fit.

---

Next: [Safari Chart](05-safari-chart.md)
