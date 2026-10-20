# Glass — a seed reference tool

**Design document.** Claims are tagged [verified] (read out of the code or the ROM),
[derived] (follows from a verified fact) or [design] (a decision made here).

## What it is

Glass is the fourth nav tab, alongside Expeditions, Hunts and Profiles. Where an
Expedition is a quest and a Hunt is one capture attempt, a **Seed** is just a seed you
care about: the key seed, an initial time to load it at, a frame you usually want to
reach, and notes about what it is for. Glass identifies which Seed A you actually
landed on and routes you to a frame on it — nothing else.

The tab is named for the tool (**Glass**) and the records inside it are **Seeds**
[design, round 1 Q1].

## What it deliberately is not

* **No Seed B.** Glass never touches the battle seed, so there is no Metronome
  Compass, no Safari Compass and no battle simulation under a Seed.
* **No chart.** The initial time is picked from the key seed's own valid times, not
  optimised against a strategy.
* **Not a calibration source.** Both fits in `app/calibration.py` require
  `vector_ms` *and* a Seed B (`_record_for_run` wants `b_seed["time"]`,
  `_record_for_safari_run` wants `b_seed["seed"]`) [verified]. Glass has neither, so a
  Glass identification can never feed the model — its history is a journal, not data.
* **Not in the portability layer.** `app/portability.py` does not carry Hunts either
  [verified]; Seeds follow Hunts until that changes.

## Data model

A new `seeds` store collection, one document per seed, shaped like `Hunt`:

```
id, profile_id
label            # optional; the hex seed is shown either way [design, Q4]
key_seed         # int, entered and displayed as hex
initial_time     # ISO-8601, picked from the key seed's valid times
default_frame    # the advance frame the route planner aims at by default
notes            # free-form
seed_a_defaults  # {startrel, seconds_window, delay_window, match_parity}
history          # up to 10 saved identifications, newest first [design, Q5]
```

`seed_a_defaults` exists for the reason a Hunt has one: the roamers' starting positions
are a property of the save file, so retyping them every visit is pure friction.

`history` entries are written only by an explicit **Save to history** button, hold
`{saved_at, seed_hex, delay, delay_delta, sec_delta, elm_heard, frame, routed_to}`, and
are capped at 10 **including repeats** — the same seed identified twice is two entries.
The live identification itself stays transient, like every other compass: reopening the
page starts clean [design, Q5].

A seed needs no uniqueness rule and no `completed` flag. Several Seeds may share a key
seed; the document id is the only real key, as for metronome users.

## The list

One row per Seed: the label when set, the hex key seed always, a time-of-day emoji, the
derived delay, the default frame, and the first line of the notes.

The emoji comes from `safari_encounters.time_of_day` (morning 4:00–9:59, day
10:00–19:59, night 20:00–3:59) [verified]. It can be shown as soon as the key seed is
entered, before any time is picked: `times.generate_times` reads the hour straight out
of bits 16–23 of the seed and stamps every time it emits with it [verified], so **every
valid initial time for one key seed shares one hour**, and therefore one bucket
[derived].

## The page

Configuration and identification share one page — the tool is small enough that a
landing page would be a door with nothing behind it [design, Q2 context].

1. **Configure** — label, key seed (hex), initial time (+ *Pick time*), default frame,
   notes. The derived delay sits next to the initial time.
2. **Seed A** — roamer start positions, ± seconds, ± delays, parity → *Generate* →
   narrow by observed R/E/L and Elm calls → click a candidate. Byte-for-byte the step
   Battle Compass runs at `app/web/index.html:4152–4400`, through the same
   `metronome_seed_a` / `metronome_key_seed_info` calls and the same `renderCandA` /
   `_seedASummary` renderers.
3. **Seed A advances** — type the Elm calls heard to pin the current advance frame
   (`safari_compass_identify_frame`), then plan a chatot-flip + Elm route to a frame
   (`safari_compass_plan_frame`). The destination starts at the seed's `default_frame`
   but sits in its own editable box, and **re-plans as you type** so another frame can
   be routed to without disturbing the stored default [design, Q2].
4. **Recent history** — the last 10 saved identifications, collapsible.

Neither facade call in step 3 takes anything Safari-specific, which is why Battle
Compass already reuses both unchanged [verified].

## The year, and the delay we show

Unlike every other tool, Glass shows the player an **absolute delay** — the number to
dial into the timer. That number depends on the year on the DS clock:

`calibration_tools.seed_for` folds `(delay + year - 2000)` into the seed's low 16 bits
(RNGReporter's `CCCC`) [verified], so

> delay = (key_seed & 0xFFFF) - (year - 2000)

which is exactly what `app/metronome._target_delay_for_key_seed` already computes
[verified]. `_seedASummary` refuses to show an absolute delay for this very reason,
printing only the delta from the search centre [verified].

The existing time picker makes this a trap: `facade.times_on_date` re-stamps the real
year **only** when a month or day filter is set, and otherwise returns the
`generate_times` placeholder year 2000 [verified]. A Seed saved from an unfiltered pick
would therefore advertise a delay 26 too high for a player who sets 2026.

The fix: `times_on_date` grows an optional `year`, and the picker grows a **year field
that appears only when Glass opens it** — when it is filled, every time the picker
offers is stamped with that year, so the stored `initial_time` always carries the year
the player will actually set [design, Q3]. Feb 29 is dropped for a non-leap year, as
the picker already does when re-stamping.

Edge case: a key seed whose low 16 bits are smaller than `year - 2000` yields a
negative delay, and `generate_roamer_candidates_near` skips negative delays entirely
[verified]. Glass should say the year cannot produce this seed rather than print a
negative number.

## Reuse map

| Glass needs | Already exists |
| --- | --- |
| Candidate seeds near a time | `facade.metronome_seed_a` (`app/metronome.py:116`) |
| Key seed's own R/E/L + Elm | `facade.metronome_key_seed_info` |
| Valid initial times | `facade.times_on_date` (+ new `year`) |
| Candidate table / summary line | `renderCandA`, `_seedASummary` |
| Advance-frame identification | `facade.safari_compass_identify_frame` |
| Route to a frame | `facade.safari_compass_plan_frame` |
| Time-of-day bucket | `safari_encounters.time_of_day` |
| Absolute delay | `app/metronome._target_delay_for_key_seed` (to be made public) |
| CRUD + store collection | `Hunt` CRUD at `app/facade.py:354-430` |

No `claytonlib/` change is needed: every piece of RNG work Glass does is already
written and already called from two places.

## Guardrails

`tests/test_app_web_ui.py` already asserts that every `api(...)` call names a real
facade method, that every nav button has a `setView` branch, that every handler the
markup calls is defined, that `_`-prefixed module variables are declared, and that the
inline script parses [verified]. The UI work is covered by those without new tests;
the facade and model work needs its own, following `tests/test_app_hunt_facade.py`.

## As built

Seven beads under `clayton-co7`, all closed. Differences from the design above, all small:

* **`app/glass.py`** holds the readout and the history-entry shaping — the one piece of Glass
  that is not a call something else already makes. `target_delay_for_key_seed` was made public
  in `app/metronome.py` for it (every other caller only ever used it to centre a search, which
  is why it read as private).
* **`save_seed(seed_id, fields)` is field-wise**, not a whole-document upsert: the page saves as
  you type, and a page that has never loaded the history would otherwise have deleted it on the
  first keystroke. An omitted field is left alone; `""` clears it.
* **A backwards route is answered by the page**, before the facade is called. `plan_advances`
  raises a perfectly good overshoot message that ends in a Safari encounter verb, which is true
  for an expedition and meaningless for a Seed — and "frame N is behind you, you are on M" is
  the better sentence for the ordinary mistake anyway.
* **`seed_clear_history`** was added alongside the cap. Ten entries including repeats fill up
  quickly when the point is to see what you keep landing on.
* **The list sorts labelled seeds first**, alphabetically, then unlabelled ones by seed — a seed
  someone bothered to name never sorts below one they didn't.
* **An unreachable key seed is reported, not crashed on.** An hour byte above 23 makes
  `times.get_times` raise (it emits `"2000-01-01 255:00:00"` and then parses it), so the readout
  checks the hour and the page refuses to open the picker. The list row carries the explanation
  rather than the listing dying on one bad record.

Tests: `tests/test_app_glass.py` (the model, the CRUD, the delay arithmetic and its two
impossible cases, the year stamping, the history cap). `tests/test_app_web_ui.py` gained four
Glass guards — the facade surface is reached, Seed A and the frame calls are the shared ones,
the route guide carries no encounter verb, and the picker asks for a year in exactly one place.
