% Clayton V1 — UI & Data Design (draft 2)

<!--
draft 2 — cleaned up from draft1 (reorganized, unified terminology, fixed heading
levels, tightened prose), then revised to fold in decisions:
  - Runs and models are scoped to a Profile (console/cartridge), shared across
    expeditions; compass runs carry no expedition-specific data.
  - The standard model ships as runs tagged "Standard"; tag view gains a weighting
    control that blends tags into a calibration.
  - "Vector ms" / vector_ms is the standard, public-facing term.
  - "Seed A / Seed B" is kept (the old seed_a/seed_b usage is deprecated).
  - The exclusion detail from the beads (outliers, exclude-reason, explicit save)
    and export/import are written into the Review/Manage Data pages.
  - Tag weighting is a per-run multiplier (weight 0 auto-excludes the tag).
  - A profile owns the console identity and a list of metronome users, each with a
    profile-unique id (from a per-profile counter); runs record that id. Metronome
    users can't be edited; removal warns that old runs lose their user info.
  - Standard runs are read-only: never edited, excluded, or exported by the user.
  - A user guide is a separate standalone document, part of the deliverable.
  - UI convention: normally-typed names over code identifiers ("Vector ms", "Seed A").
The "Open Questions" appendix now holds only what's genuinely unresolved.
-->

# Overview

This is a design doc for structuring the Clayton release to the public as a web
page and/or downloadable executable. It does **not** tackle code fundamentals or
the mechanics of shipping a web page vs. an executable (see the separate
distribution design). It covers the product-level design: data structuring, UI
pages, and user flow.

# Terminology

Terms as this document uses them, to keep the sections below unambiguous:

- **Seed A** — the *initial* seed (the one hit via datetime manipulation).
  Identified from roamer positions (REL) and Elm calls. Stored as `a_seed`.
- **Seed B** — the *battle* seed (drives the encounter: Metronome moves, or Safari
  turn outcomes). Stored as `b_seed`.
- **Vector ms** — the value that aims a run at a good Seed B. This is the
  **standard, public-facing term**, shown in the UI as "Vector ms" (code should
  refactor toward it as it goes). It measures the gap between the button presses for
  Seed A and Seed B; we deliberately avoid calling it a "delay" or "frames," since
  those words are already overloaded (a *delay* is a game frame, and *frame* also
  refers to advance frames).
- **REL** — the starting positions of the three roamers (R, E, L).
- **Target** — an initial time that hits the key seed, plus a Vector ms value aimed
  at landing a good Seed B. Produced by the Chart, consumed by Compass runs.
- **Key seed** — the Seed A the user is trying to hit for the shiny.
- **Model** — the calibration that maps a timer countdown to a landing frame, used
  to hit a Seed B in the target range. A property of the **console** (see Data →
  Models), not of a particular expedition.

> Note: "Seed A / Seed B" here means *initial* vs. *battle* seed. The codebase's
> older `seed_a` / `seed_b` (the two-seeds-per-delay RTC-tick distinction) belongs
> to the deprecated charting model and is not reused by this design.

**UI naming convention.** In the UI, prefer normally-typed names over code-style
identifiers — "Seed A" not `seed_a`, "Vector ms" not `vector_ms`, and so on.
Code-style spellings are for code; this document uses the UI spelling in prose.

# UI Pages / Screens

## Expedition Selection screen

Main screen. Lists created expeditions with a **Create new** button. This is the
screen shown on boot/load when there are no current expeditions. **Create new**
opens the Expedition Configuration screen for a new expedition.

## Expedition Configuration screen

All the basic configuration for an expedition:

- The **key seed** (the Seed A we're trying to hit for the shiny) and its required
  key-seed advances.
- The Pokémon being hunted.
- The Safari Zone area, and the Safari Zone block configuration.
- How many Chatots the player has (0–2).

(Metronome users live on the **profile**, not the expedition — see Data →
Profiles → Metronome Users.)

A **Save** button saves changes to an existing expedition, or creates the
expedition if it's new.

## Expedition Preferences screen

Low-impact settings a user might like to tweak, e.g.:

- How many Elm calls they prefer after the Chatot flips (default 3).
- Whether to automatically delete targets/models once there are *N* newer ones.

## Expedition Home screen

The main home screen for an expedition. If the user has expeditions, the last one
they worked on is selected and this loads first. It links to all the tools,
grouped by category:

- **Metronome Compass** — New Run · Review Data
- **Safari Chart** — Find Target · Manage Data
- **Safari Compass** — New Run · Review Data
- **Preferences**

## Metronome Compass — New Run

The equivalent of Sections A, B, and C of the Metronome Compass Calibration
notebook. Envisioned layout: **Seed A** (Section A) on the left, **Seed B**
(Section B) on the right, and Section C as a pop-up after the **Save Run** button.
Common controls (metronome-user and target selection; save/reset/cancel) live in a
header at the top.

UI elements enable incrementally:

1. The user selects a **metronome user** and a **target** in the common header →
   enables **Seed A**.
2. Completing **Seed A** → enables **Seed B**.
3. Completing **Seed B** → enables the **Save Run** button.

Wherever reasonable, inputs are pre-populated with their last-used values (metronome
user, target, REL starting positions, seed selection ranges, etc.).

This page requires the profile to have **at least one valid** metronome user (see
Data → Profiles → Metronome Users); otherwise everything is disabled and an
explanation is shown. The selected metronome user must itself pass validation.

### Common section (header)

- **Metronome user** selector: choose which of the profile's metronome users this
  run uses (defaults to last used). Its **id** is recorded on the saved run.
- Target selection: input fields for **initial time** and **Vector ms**, saved to
  the expedition so they default to their last values. A button selects values from
  a common target. Once Seed A is identified, these fields lock until the run is
  reset.
- Buttons: **Save Run** (see below), **Reset** (clears the found Seed A / Seed B),
  and **Cancel** (returns to the Expedition Home screen).

### Seed A

Inputs: **REL starting positions**, **search range (delay)**, **search range
(second)**, and an option to match only the parity of the key-seed delay. A
**Generate** button lists the seeds in that range with their roamer positions and
Elm calls.

Informational display (like the "Seed to Time" views in PokéFinder/RNGReporter):
from the key seed and the REL starting positions, show the key seed's Elm-call
sequence and REL positions, so the user can quickly tell whether they hit the key
seed. This matters most in **Safari Compass** when the user is making real catch
attempts rather than calibrating; in Metronome Compass it lets the user opt to go
for a shiny instead of continuing the run, and keeps visual parity between the two.

Once the seed list is generated it displays in a small table. An **REL** input
filters the list, then an **Elm calls** input identifies the seed. Pressing Enter
in the REL input jumps to the Elm-call input (or the user clicks it).

Below the Elm-call input is a status line, starting as
`Seed A: ???  Advance Frame: ???`. Once the seed is identified it shows
`Seed A: <seed>  Advance Frame: <possible advance frames>`. Once both seed and
advance frame are pinned, it also shows the number of Chatot flips and the
Elm-call resolution (as in the notebook), and **Seed B** is enabled.

### Seed B

Top-of-section config (need **not** be disabled with the rest of the section):
search range delay ±, second ±. The metronome user's details come from the one
selected in the common header, so they aren't shown here.

First inputs: Magikarp's **level** and **gender**. On Enter or **Start**, generate
the candidate seeds and their paths. Display the top ~15 (fewer if space is tight),
as in the notebook, and prompt the user with a series of questions — seed list
above, input field below. Once the seed is found, write the relevant data into a
text area under the prompt, disable the prompt, and enable **Save Run**.

### Save Run pop-up

Opened by **Save Run**. Same inputs as notebook Section C (tag, target timer delay
and calibration, etc.), with the same defaults, plus a **notes** text area. It
displays the resulting data to be saved. A final **Save** button saves the run and
then asks whether to start a new run or return to the expedition menu. A **Cancel**
button closes the pop-up without saving or clearing the run data.

### Input details

#### REL input

Space-separated numbers (or dots), as in the current Seed A identification, with a
small parsed display under the input reading `R:  E:  L:`. A `-` marks a roamer as
unavailable, or trailing roamers can be left off. E.g. `34 - 7` → R: 34, L: 7, E
unavailable; `- 44` → E: 44, R and L unavailable.

#### Elm-call input

Show the list of previous Elm calls above the input. The input accepts multiple
Elm-call characters at once and filters out noise, as in the calibration notebook.

#### Magikarp level / gender

Gender is a **male/female** radio pair. Typing `M` or `F` in the **level** field
toggles that radio; all other letters typed into the level field are filtered out.

## Metronome Compass — Review Data

The equivalent of Sections D & E of the Metronome Compass Calibration notebook, and
the place to curate which runs feed a calibration. Shows every Metronome Compass
run for the current **profile** (runs are profile-scoped, not per-expedition — see
Data → Models), including the read-only **"Standard"**-tagged runs that generated
the shipped model. Presented as a table with per-row action buttons, sortable by
tag (alphabetical), chronologically, by deviation from the expected `F_b` under the
current model, and possibly other keys. It also filters to a single tag.

**Exclusion model.** A run's *effective-included* status is:
`NOT auto-outlier AND NOT manually-excluded AND NOT excluded-by-tag`.

- **Outliers are always excluded** from any fit — no exception. Outlier rows are
  marked obviously, and the manual **exclude** checkbox still appears on them; the
  checkbox exists so it can also exclude non-outlier runs the user judges
  unrepresentative.
- **"Standard"-tagged runs are read-only.** They can't be edited, deleted, or
  excluded individually, and they're never included in a user's export — the only
  control over them is the Standard tag's weighting. Keeping them locked lets a
  future release revise the shipped Standard dataset without colliding with user
  edits.
- **Tag exclusion is separate** from per-run exclusion: excluding a tag does **not**
  toggle the individual run checkboxes. Runs excluded because their tag is excluded
  say so.
- An **Exclude reason** column states why a row is out: `outlier` / `manual` /
  `tag:<name>` (combinations possible). The reason is derived from the three inputs
  above, so it can't drift out of sync.

**Save changes.** All exclusion/weighting edits are staged and take effect only on
an explicit **Save changes** action; unsaved edits can be discarded. Exclusions
change only which runs a fit consumes the next time a model is calibrated — they
never silently re-fit the deployed model.

**Export / import.** Runs can be exported (backup, portability, moving between the
web and desktop builds) and imported. On export, prompt whether **excluded runs**
should be included; either way, the exclusion flags travel with the data so state
round-trips on import.

### Run view

The default table, one row per run: tag, date, Vector ms, the identified Seed A /
Seed B data and the run's deviation from the current model, notes, the outlier
marker, the **exclude** checkbox, and the **Exclude reason** column.

### Tag view

A toggle. Instead of individual runs, each row is a **tag**, with: number of runs,
number included, number of outliers, notes, an **include/exclude tag** control, and
a **weighting** control.

**How weighting works.** A tag's weight is a **per-run multiplier** (default 1). A
tag's total influence on the fit is therefore `weight × (its included run count)`,
so tags at equal weight let every run count equally regardless of how the runs are
distributed across tags — the user never has to reason about tag sizes. Example:
`Standard` at weight 0.1 with 50 runs (effective 5) and `Tag2` at weight 1 with 5
runs (effective 5) contribute equally. This is how the shipped **"Standard"** runs
are balanced against the user's own (dial Standard down as personal data grows).

Setting a tag's weight to **0** automatically marks it **excluded** (weight 0 and
exclusion are the same state).

### Calibrate Model view

Opened by **Calibrate model**. Fits from the effective-included runs under the
current tag weightings and shows the changes relative to the currently selected
model, with: the new model's number (a strict increment of the most recent model),
an optional model name, and a **Save** option for the new model.

## Safari Chart — Find Target

Based on the Expedition Workflow notebook's Chart Safari section.

The user selects a **chart** to use (or creates a new one), then selects a
**model** (both default to last used). **Run calculations** shows a detailed
progress bar as it builds the canon map, refreshes it, or validates that it's
already filled. If a chart report already exists for that model / canon-map
pairing it's reused; otherwise it's generated automatically. Then it shows the top
results.

A second section lets the user choose one of the top results (or the best result
for a specific time), give the target an optional name, and hit **Save target**.
Multiple targets can be saved from the same chart report. An **Examine target**
button opens a pop-up with the report, as in the Expedition Workflow notebook's
`chart_check_target_landing()`.

### Create chart

Sections to select **strategy** and **criteria**, with notes on what each
criterion is and when it's useful. Also an option to name the chart.

## Safari Chart — Manage Data

A page to manage chart-associated data — canon maps, targets, charts, chart
reports. Supports **export / import** of this data for backup and portability.

## Safari Compass — New Run

Very similar to Metronome Compass — New Run, differing mainly in the Seed B
section. (The **Seed A** section is the same roamer/Elm identification.)

### Seed B (Safari)

Similar to Section B of the Safari Compass Calibration notebook. One addition: if
machete runs successfully, show the full machete-generated path and the actions so
far above the input, with the **next expected action in bold**. E.g. if we've done
`bbbBbb0321`, machete says `mMmC`, and we've since thrown one mud that still matches
the seed, show `bbbBbb0321m`**`M`**`mC`. If the user breaks from the machete path,
clear it.

## Safari Compass — Review Data

Mirrors **Metronome Compass — Review Data** over the Safari run dataset: the same
run/tag/calibrate views, the same exclusion model (outliers always excluded,
per-run and per-tag exclusion with an Exclude-reason column, explicit **Save
changes**), the same tag **weighting**, and the same **export / import** with the
"include excluded runs?" prompt.

# Data

## Profiles

A profile represents a **console + cartridge** identity — a TID and SID (like
PokéFinder) plus the console it's played on. It's the home for everything that's a
property of the hardware/save rather than of a particular hunt: the calibration
**models**, the compass **runs** that build them, and the list of **metronome
users** all belong to the profile and are shared across every expedition that uses
it. Each expedition references one profile. If DPPt support is added later, that
configuration could live here.

Because the model captures a **console's** timing, the profile should note that
playing the same cartridge on a *different console* under the same profile may
produce model inconsistencies (that scenario really wants its own profile).

### Metronome Users

A profile holds a **list** of metronome users. Each gets a **profile-unique id**
from a per-profile counter (a monotonic number that never reuses a value), and its
**name must be unique within the profile** (for human selection). A metronome user
includes: species, gender (if applicable for the species), level, moveset, and
whether it holds a Lagging Tail. Because of P0, only **Chansey with Natural Cure**
may be supported at the start.

Metronome users are **immutable — editing is not allowed**. To change one, add a new
user and (optionally) remove the old one. This keeps a user's identity stable for
the runs that reference it.

Validations run per user, with a warning if one is unsuitable (no Lagging Tail,
doesn't actually know Metronome, etc.). **Metronome Compass — New Run** requires the
profile to have at least one valid metronome user, and the user picks which one a
run uses.

Each saved metronome run records the metronome user's **id**. Since users are
immutable, a run's user info stays accurate for the life of that user. **Removing** a
metronome user is allowed but warns that Metronome Compass runs performed with it
will no longer be able to display that user's information (the id becomes a dangling
reference). This is acceptable: the metronome user matters *during* the run far more
than after it.

## Expedition Data

An expedition is the data associated with a quest to obtain a specific Pokémon. It
references a profile but owns no compass runs or models itself — a user hunting
several Pokémon on one console shares one set of runs and models across all of them,
and never re-calibrates per hunt.

### Expedition Configuration

Key configuration: the Pokémon being hunted, the Safari Zone area and block
configuration, the number of Chatots, the key seed, and the key-seed advances
needed to find it. (Metronome users are on the profile, not here.)

## Models

The calibrations used to hit a Seed B in the target range. Models capture a
**console's** timing behavior, so they belong to the **profile** and are shared
across every expedition on that console (not owned per-expedition).

A **standard** model ships by default. Rather than shipping only the fitted
numbers, the runs that generated it ship too, tagged **"Standard"**, so they appear
(read-only) in Review Data alongside the user's own runs. Calibration then blends
tags by their **weighting** (Tag view), which is how a user balances the Standard
runs against their own — turning the Standard weight down as their personal dataset
grows. Users create additional models from the **Review Data** tabs of Metronome
Compass or Safari Compass.

## Runs

The individual Metronome/Safari Compass runs. Profile-scoped (see Profiles); each
carries its tag, Vector ms, identified Seed A / Seed B data, notes, and its
exclusion flags — but **no expedition-specific data**. A metronome run also records
the **id of the metronome user** it used (see Profiles → Metronome Users). These are
the raw material Review Data curates and models are fit from.

## Targets

A target is an initial time that hits the key seed plus an associated Vector ms
value aimed at a good Seed B. Initially empty; populated in **Safari Chart — Find
Target**, and consumed on the Compass new-run pages.

## Charts / Canon Maps

A canon map is a precomputed map of seeds → success outcomes for a given
**strategy** and **criteria**. It's model-independent, so it can be reused when the
model changes. A **chart** bundles the strategy/criteria selection with its canon
map. Charts are built in **Safari Chart — Find Target**.

## Chart Reports

Data generated for a **model × chart** pairing: ideal times and Vector ms values
with associated probabilities.

## Export / Import

A first-class, supported feature (not an afterthought) for both the profile-level
run/model data (via **Review Data**) and the chart-associated data (via **Manage
Data**). Export writes a versioned file; on export of runs, prompt whether excluded
runs are included, and carry the exclusion flags so state round-trips on import.
**"Standard"-tagged runs are never exported** (they ship with the app). Import
offers a clear replace-vs-merge choice and confirms name collisions. Exporting a
full profile bundle doubles as the migration path between the web and desktop
builds.

**Metronome-user references across profiles.** Because metronome runs reference a
metronome user by profile-local **id**, runs imported into a *different* profile (or
a fresh install) may carry ids that don't resolve against that profile's users.
Such runs display with an unknown/unresolved user — the same behavior as a run whose
user was removed. This is acceptable for the same reason: the metronome user matters
during the run, not after. (Importing a *full profile bundle* carries the users
too, so their ids resolve.)

---

# User Guide (deliverable)

Building Clayton for a public audience includes writing a **usage guide**, produced
as a **separate standalone document** (not in-app help) and shipped as part of the
deliverable. At minimum it should walk a new user through: creating a profile (and
adding a metronome user), creating an expedition, finding a target with Safari
Chart, running Metronome and Safari Compass, and curating runs / calibrating a model
in Review Data. It should also explain the concepts a user needs but can't infer
from the UI alone (Seed A vs. Seed B, Vector ms, tags and weighting, the Standard
model).

---

# Open Questions (to resolve in a later draft)

*Resolved and folded into the sections above: model & run scope (profile-scoped);
tag weighting (a per-run multiplier, default 1, so influence = weight × run count,
and weight 0 auto-excludes); Vector ms as the standard term and the UI naming
convention; Seed A/Seed B naming; the full exclusion model; export/import;
console-as-part-of-profile (with the different-console caveat); metronome users
owned by the profile, each with a profile-unique id and unique name, immutable
(no editing), removable with a warning, and runs recording the user's id; Standard
runs read-only and never exported; the user guide as a separate standalone document.*

Nothing substantial is currently open.
