# 2. Getting started

## Installing

**Linux (Nix)** — the packaged build, with a launcher entry and icon:

```
nix build .#clayton
./result/bin/clayton
```

**Windows** — see [packaging/BUILDING-WINDOWS.md](../packaging/BUILDING-WINDOWS.md).

**From source, any platform:**

```
pip install -r app/requirements.txt
python -m app.main
```

Your data lives outside the app and survives rebuilds:

| Platform | Location |
|---|---|
| Linux | `~/.local/share/Clayton` |
| Windows | `%LOCALAPPDATA%\Clayton` |
| macOS | `~/Library/Application Support/Clayton` |

## Step 1 — Make a profile

A **profile** is one game on one console. It owns your saved runs and your calibration
models, because both are properties of that physical setup — a different console, or the same
game on a different flashcart, times differently and needs its own profile.

**Profiles → New.**

| Field | What to put |
|---|---|
| Name | Anything you'll recognise: `SoulSilver — DSi` |
| Trainer name | Your in-game name (a label; nothing is computed from it) |
| Version | HeartGold or SoulSilver |
| Console | Which DS. Worth recording — timing differs between models |

Every new profile starts with a bundled **Standard** calibration model so the tools work
immediately. It is a real fitted model, but it is not *yours* — replace it as soon as you have
your own ([page 4](04-metronome-compass.md)).

> **Screenshot:** the New Profile form.

## Step 2 — Make an expedition

An **expedition** is one hunt for one Pokémon. It holds the target seed, the area, and your
block scores. Charts and saved targets belong to it.

**Expeditions → New.**

| Field | What to put |
|---|---|
| Name | `Shiny Metang`. Must be unique across *all* profiles |
| Profile | The profile above |
| Pokémon | The species you're after |
| Safari area | Which area it's in — narrowed to areas that actually hold your species |
| **Key seed** | The initial seed (Seed A) you intend to hit, as hex: `0x0D0E02BA` |
| **Key-seed advances** | The Seed A advance frame you'll Sweet Scent on |
| Safari block scores | See [page 7](07-safari-blocks.md) |

### Where the key seed comes from

From PokeFinder or RNG Reporter: search for the spread you want, and note the **initial seed**
that produces it. That's your key seed. Clayton takes it from there and never second-guesses
it.

### What "key-seed advances" means

After your save loads on Seed A, the overworld RNG advances as you act — each Elm phone call
is one advance, each Chatot cry flip is two. The encounter that fires when you Sweet Scent is
decided by how many advances you've made.

So: **key-seed advances** is the advance frame your target Pokémon sits on for that seed.
PokeFinder will tell you which frame holds your spread; that number goes here.

If you'd rather Clayton work it out, it can search for the frame itself using your block
scores — set **Preferences → Target frame source** to `in_house`. Either way the field is
required, because Safari Chart needs it to know how long your run will take.

> **Screenshot:** the expedition Configure form.

## Step 3 — Check the tools are there

Open the expedition. You should see three tools:

- **☝️🧭 Metronome Compass** — New Run, Review Data
- **⛺🗺️ Safari Chart** — Find Target, Manage Data
- **⛺🧭 Safari Compass** — New Run, Review Data

> **Screenshot:** the expedition home page with the three tool cards.

## What next

Do **not** jump to Safari Chart. Its targets are only as good as your calibration, and right
now you're using a model fitted on somebody else's hardware.

Set up your timer first ([page 3](03-timers.md)), then calibrate
([page 4](04-metronome-compass.md)).

---

Next: [Timers and hitting seeds](03-timers.md)
