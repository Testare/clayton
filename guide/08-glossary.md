# 8. Glossary

**Advance frame** — How many times the overworld RNG has ticked since Seed A was generated.
Driven by what you do, not by the clock: each Elm call is one advance, each Chatot flip is
two. The encounter that fires when you Sweet Scent is decided by this number.

**Canon map** — Safari Chart's precomputed table of every reachable seed in a chart's window
and what happens to each under that chart's strategy. Model-independent, so refitting your
calibration doesn't invalidate it. Shared between charts with the same Pokémon, key seed,
strategy and criteria.

**Chart** — A strategy paired with a success condition, scoped to an expedition. What Safari
Chart ranks targets against.

**Chatot flip** — Playing back a recorded Chatot cry. Two RNG advances each, and fast — the
bulk of any long approach. Not verifiable, which is why routes finish on Elm calls instead.

**Delay** — One tick of the DS frame counter, about 59.83 per second. **A delay is a game
frame**; the two words mean the same thing here. Always absolute, counted from boot.

**Delta delay (Δ delay)** — In the Runs tables: how far a run's realized Vector delay sits
from what the active model predicted. Near zero is good. Badged amber past 2σ.

**Elm call** — A phone call from Professor Elm. One RNG advance, and *audible*, which is what
makes it the verifiable part of an approach route. Written as `P`, `E`, `K`.

**Expedition** — One hunt for one Pokémon. Holds the key seed, advance count, area and block
scores; owns charts and saved targets. Names are unique across all profiles.

**Flee flags** — Per-candidate warnings in Safari Compass's Seed B table: `F0` flees this turn
on a ball, `F3` flees within three turns whatever you do, and `F!` means it has **already**
fled and is waiting for you to type `F`.

**Initial time** — The DS clock datetime you aim to hit **Seed A** on. Not when you boot — the
boot is earlier, on timer 1.

**Jitter (σ)** — The spread of the landing frame, in frames. Yours, from your calibration.
Sets how wide every search has to be; smaller is better.

**Key seed** — The Seed A you're trying to hit, found in PokeFinder or RNG Reporter.

**Key-seed advances** — The advance frame your target sits on for the key seed. The count you
advance to before Sweet Scenting.

**Machete path** — Once Seed B is identified, the exact sequence of throws that catches it.

**mdmsh** — The hash identifying a seed's family: `(month × day + minute + second) & 0xFF`
plus the hour. Many different datetimes collapse to the same value.

**Metronome user** — The Pokémon used for calibration battles. Wants Metronome, no other
moves, a Lagging Tail, and a non-interfering ability.

**Profile** — One game on one console. Owns runs and calibration models, because both are
properties of the physical setup.

**Reuse factor** — How many times the average seed in a canon map is shared across the boot
times it covers. High is good; it's why precompute is affordable.

**RTC second** — The DS wall-clock second a seed was made on. One of the two coordinates that
fix a seed; noisier than the frame, and misses independently of it.

**Safari offset** — How far the Safari Zone's extra loading screen pushes the landing frame
compared to the metronome path. Fit separately, in Safari Compass's Calibrate Model.

**Seed A** — The initial seed, generated when your save loads (t2). Drives the overworld:
encounters, roamers, Elm calls.

**Seed B** — The battle seed, generated when the encounter fires (t3). Decides the Pokémon and
everything that happens in the battle.

**Vector delay** — The realized difference in delays between Seed B and Seed A — what actually
happened. Internally `dF`. This is the quantity the calibration model fits.

**Vector ms** — The length of timer 3: the commanded countdown in milliseconds from loading
your save to pressing Sweet Scent. What Safari Chart chooses for you.

---

Next: [Troubleshooting](09-troubleshooting.md)
