# 3. Timers and hitting seeds

Everything Clayton predicts rests on you pressing three buttons at three planned moments. This
page covers what those moments are and how to set a timer up for them.

## Use EonTimer

**[EonTimer](https://dasampharos.github.io/EonTimer/)** is what this guide assumes. It beeps
in the run-up to each moment so your presses land consistently, and it rolls straight from one
timer into the next — which matters here, because Clayton needs three in a row.

Any timer that can chain three countdowns will work. If you use something else, everything
below still applies; only the buttons differ.

## The four moments

```
  t0 ───────── t1 ───────── t2 ───────── t3
  │            │            │            │
  set clock    boot game    load save    Sweet Scent
  start timer  (frame 0)    → SEED A     → SEED B
               │◄─ timer 1 ─►│◄─ timer 2 ─►│◄─ timer 3 ─►│
```

**t0 — set the DS clock and start the timer.** Set the DS to your target datetime and press
the clock's confirm button at the instant EonTimer starts. Then reset the DS, ready to boot.

**t1 — boot the game.** Timer 1 elapses; you press A on the boot screen. The delay counter
starts here, so this is frame zero.

**t2 — load your save.** Timer 2 elapses; you press to continue. **Seed A is generated here.**

**t3 — Sweet Scent.** Timer 3 elapses. During this timer you enter the Safari Zone, make your
RNG advances, get into position, and press Sweet Scent on the beep. The encounter fires and
**Seed B is generated.**

## Vector ms

**Vector ms is the length of timer 3** — the countdown from loading your save to pressing
Sweet Scent, in milliseconds. It is the single number Safari Chart is choosing for you.

It must be long enough to actually do the setup — entering the zone, walking into position,
making your advances — so charts start around 3 minutes (180,000 ms) and go up from there.

> Clayton shows Vector ms with the last three digits tinted, so `327591` reads as
> `327` seconds and `591` milliseconds at a glance.

## Setting up EonTimer

Use EonTimer's **Custom** mode with three stages:

| Stage | Length | Ends at |
|---|---|---|
| 1 | your usual boot delay | t1 — boot |
| 2 | your usual load delay | t2 — Seed A |
| 3 | **Vector ms** from the target Clayton gives you | t3 — Sweet Scent |

Stages 1 and 2 are whatever you already use to hit initial seeds — Clayton does not change
them. Only stage 3 comes from Clayton.

### The +0.2 second bias

Add about **0.2 s to the first timer**. That shifts all three moments later together, so it
changes none of the gaps between them — it just makes t2 land a fraction *past* the second
boundary instead of a fraction before it.

Being 50 ms early would otherwise drop you onto the previous second's seed entirely. Being
200 ms late costs nothing.

## Two clocks, two ways to miss

A seed is fixed by two independent things, and they go wrong independently:

**The RTC second** — the DS wall clock at the moment the seed is made.

**The frame (delay) counter** — started at boot, ticking about 59.83 times a second.

Both presses at t2 and t3 run off the same EonTimer clock, so a slow reaction on both cancels
out in the *frame* difference. The *second* has no such luck: it also depends on where inside
its second your t2 press landed, which you don't control.

The practical consequence, which the tools are built around:

> **A wrong second with a good frame is normal, and it isn't a frame problem.** You hit the
> frame you aimed at; a boundary moved under you. Clayton's model handles the second as a
> distribution rather than a promise.

## Before you calibrate

Check you can still hit Seed A reliably with just timers 1 and 2. Clayton's whole model is
built on top of that; if your initial seeds are inconsistent, nothing downstream will be
better.

---

Next: [Metronome Compass](04-metronome-compass.md)
