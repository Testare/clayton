# 6. Safari Compass

This is the tool you have open *during* a run. It tells you which seed you actually hit, walks
you to the right advance frame, and once the battle starts, tells you what to throw.

## Before you start

A target from Safari Chart, your timers set, and the app open on **Safari Compass → New Run**.

## Set the target

**Choose from saved target**, or type the initial time and Vector ms by hand.

> **Screenshot:** the New Run header with a target chosen.

## Step 1 — Seed A

Run timers 1 and 2. Then tell Clayton what you see — exactly as in Metronome Compass:

- **Roamer starting positions (R E L)** — where the roamers started, in Raikou / Entei /
  Latias-or-Latios order. `-` for any not roaming
- **± seconds / ± delays** — the search window
- **Observed roamer routes** — where they are now. `.` matches any
- **Elm calls heard** — `P`, `E`, `K` as you hear them

Candidates narrow as you type. One row left means Seed A is pinned.

**If you hit your key seed exactly, Clayton says so** and skips straight to your configured
advance count — no frame search needed. That is the good case.

> **Screenshot:** Seed A identified, showing a key-seed hit.

## Step 2 — Seed A advances

This section is the part that has no equivalent in an ordinary RNG hunt, and it is where runs
are most often lost.

You are not trying to reach a *time*. You are trying to reach an **advance frame** — a count
of how many times the overworld RNG has ticked since your save loaded.

### Pinning where you are

Type the Elm calls you've heard so far. Each call is one advance, so the calls pin your
current frame exactly. Keep typing as more come in until Clayton reports a single frame.

### The route

Clayton then plans a route to your target frame:

```
34 chatot flip(s), then 3 Elm call(s) → frame 81, Sweet Scent there.
```

- **Chatot flips** cover distance fast — two advances each
- **Elm calls** are the final approach — one advance each, and *verifiable*, because you hear
  them

The guide string shows the calls you should hear on approach, with `!` marking where to Sweet
Scent:

```
PEEEP[KPE]!KEP
```

Hear the bracketed calls, then Sweet Scent on the `!`.

> **Sweet Scent while standing ON the target frame.** Pressing one frame early misses.

### When the margin is ambiguous

Clayton flags routes whose final Elm calls read the same a frame or two either side — a
miscount would be invisible. Where it can, it picks a different target frame with an
unambiguous approach instead.

> **Screenshot:** the advance-frame guide with its route and guide string.

## Step 3 — Seed B

Sweet Scent on the beep. The encounter fires.

Now type what you see, one character per turn:

| Type | Action | What you saw |
|---|---|---|
| `m` | Mud, no crit | *"X is angry!"* |
| `M` | Mud, crit | *"X is beside itself with anger!"* |
| `b` | Bait, no crit | *"X is eating!"* |
| `B` | Bait, crit | *"X is busy eating!"* |
| `0` | Ball, 0 shakes | *"Oh, no! The Pokémon broke free!"* |
| `1` | Ball, 1 shake | *"Aww! It appeared to be caught!"* |
| `2` | Ball, 2 shakes | *"Aargh! Almost had it!"* |
| `3` | Ball, 3 shakes | *"Shoot! It was so close, too!"* |
| `C` | Captured — ends the run | *"Gotcha!"* |
| `F` | Fled — ends the run | *"X fled!"* |
| `u` | Undo the last character | |

The **?** button opens this table for your species, with the exact messages.

Candidates narrow with every character. Once one seed is left, Clayton shows the **machete
path** — the exact sequence to catch it from here.

> **Screenshot:** Seed B narrowed to one candidate, with a machete path.

### Flee flags

Once you're down to a handful of candidates, each row is checked three turns ahead:

| Flag | Meaning |
|---|---|
| `F0` | flees **this turn** if you throw a ball |
| `Fb2` | flees within 2 turns if you bait |
| `F3` | flees within 3 turns **whatever** you do |
| **`F!`** | this candidate has **already fled** — type `F` to confirm it |

`F!` is shown in a different colour because it is not a prediction. It means the last thing
you did already ended the run for that candidate, and Clayton is waiting for you to confirm.

### If candidates run out

Type a character and everything disappears? Either you mistyped, or you landed outside the
search window. **Widen search window** grows it and drops the probability cap, which is
usually enough. Your typed path is kept.

## Step 4 — Save the run

**Save Run**, win or lose.

The **Advance recipe** fields — Elm calls, Chatot flips, advance frame — are prefilled from
the route you planned. Leave them; they feed the calibration work on whether advance count
affects timing.

If you caught it on the key seed, Clayton offers to mark the expedition complete.

## Feeding calibration

**Safari Compass → Review Data → Calibrate Model** fits the **safari offset** — how far the
Safari Zone's extra loading screen pushes the frame compared to the metronome path.

It works from a **base model** you choose (your metronome fit) and only adjusts the safari
offset, leaving the trend alone. A safari run cannot determine the trend by itself.

Two optional checkboxes:

- **Fit a per-advance offset** — tests whether the number of advances shifts the landing
  frame. Off by default. When on, the fitted slope comes with an uncertainty in frames at
  *your* advance count; treat a wide interval as "keep collecting", not as a result.
- **Use the safari runs' own spread** — measures scatter on the safari path rather than
  inheriting the metronome path's.

---

Next: [Safari blocks](07-safari-blocks.md)
