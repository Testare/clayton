# 4. Timers and hitting seeds

Everything Clayton predicts rests on you pressing three buttons at three planned moments. This
page covers what those moments are and how to set a timer up for them.

## Seed A and Seed B

A core concept going forward is the concept of Seed A and Seed B.
* **Seed A** is the seed that is generated when you start the game. It seeds the RNG state that determines what pokemon you can encounter. When Seed A is your "Key seed", and you perform your key-seed advances, you'll be guarnateed to encounter the pokemon you are hunting.
* **Seed B** is the seed that generated when the encounter with the pokemon starts. This RNG state determines nothing about the pokemon after the encounter is done, but during the encounter it determines the moves it uses, whether they miss, whether secondary effects proc, and whether balls shake/capture. In the safari zone, it also determines if the pokemon runs away, and whether bait or mud "crit".

To catch the pokemon you want, you'll need to hit a pretty specific Seed A. Don't worry about needing to hit two seeds in a row though: You're not going to be trying to hit a specific Seed B. You're going to hit around an _area_ of seeds.

## Use EonTimer

**[EonTimer](https://dasampharos.github.io/EonTimer/)** is what this guide assumes. It beeps
in the run-up to each moment so your presses land consistently, and it rolls straight from one
timer into the next — which matters here, because Clayton needs three in a row.

Any timer that can chain three countdowns will work. If you use something else, everything
below still applies.

## The four moments

```
  t0 ────────── t1 ────────── t2 ────────── t3
  │             │             │             │
  set clock    boot game    load save    Sweet Scent
  start timer  (frame 0)    → SEED A     → SEED B
  │◄─ timer 1 ─►│◄─ timer 2 ─►│◄─ timer 3 ─►│
```

**t0** — set the DS clock and start the timer.** Set the DS to your target datetime and press
the clock's confirm button at the instant EonTimer starts. Then reset the DS, ready to boot.

**t1 — boot the game.** Timer 1 elapses; you press A on the boot screen. The delay counter
starts here, so this is frame zero.

**t2 — load your save.** Timer 2 elapses; you press to continue. **The game generates Seed A.**

**t3 — Sweet Scent.** Timer 3 elapses. During this timer you enter the Safari Zone, make your
RNG advances, get into position, and press Sweet Scent on the beep. An animation plays, the encounter starts and **the game generates Seed B.**


## Vector ms/Vector Delay

**Vector ms is the length of timer 3** — the countdown from loading your save to pressing
Sweet Scent, in milliseconds. It is the number clayton tries to model, it is the single number Safari Chart is choosing for you. It is called "Vector ms" because a vector is an arrow between two points, and this is the time (in ms/milliseconds) from Seed A to Seed B.

It must be long enough to actually do the required setup:
* Enter the safari zone and walking into position
* Identify your seed and your advances
* Make you advances 
* Get ready to press sweet scent

Clayton currently assumes this will take around 3 minutes, so chart defaults to a minimum of 180,000 milliseconds for Vector ms. If you can do this faster you can lower it, or if you need more time you can raise it.

Vector delay is the difference between the delay/game frame of Seed A and Seed B. If the game ran at a perfect 60 FPS, then a Vector MS of 10000 ms (10 seconds) would produce a Vector delay of 600.

## Setting up EonTimer

Use EonTimer's **Custom** mode with three stages:

| Stage | Length | Ends at |
|---|---|---|
| 1 | your usual boot delay | t1 — boot |
| 2 | your usual load delay | t2 — Seed A |
| 3 | **Vector ms** from the target Clayton gives you | t3 — Sweet Scent |

Stages 1 and 2 are whatever you already use to hit initial seeds — Clayton does not manage them. In EonTimer you can use the regular Gen IV timer first to calibrate to a specific time, and then figure out the ms for stage 1 and 2 from the UI and copy those values in milliseconds to the custom timer.
Stage 3 is the Vector MS - In Safari Compass you'll likely be using one that came from Safari Chart. For Metronome Compass, this can be whatever time you'd like to help calibrate around.

---

Next: [Metronome Compass](05-metronome-compass.md)
