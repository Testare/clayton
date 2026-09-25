# 2. Getting started

## Installing

Three ways in, depending on how much you want to do yourself.

### Download directly

The quickest route. Grab a build from the
**[Releases page](https://github.com/Testare/clayton/releases)**:

| File | Platform |
|---|---|
| `Clayton-windows.exe` | Windows |
| `Clayton-macos` | macOS |
| `Clayton-linux` | Linux |

Each is a single self-contained executable — nothing needs to sit beside it, and there is no
installer. On macOS or Linux, make it executable first:

```
chmod +x Clayton-macos
```

> **Only the Windows download has actually been tested.** The macOS and Linux builds are
> produced by the same process but nobody has yet run them on those platforms — treat them as
> unproven, and fall back to one of the sections below if a build misbehaves. The Linux binary
> in particular needs GTK 3 and WebKitGTK already present on your machine; if you are on Linux,
> the Nix route below is the one to trust.

Both Windows and macOS will warn that the publisher is unrecognised, because these builds are
unsigned. On Windows choose **More info** → **Run anyway**; on macOS right-click the file and
choose **Open** rather than double-clicking it.

### Building from source

Works anywhere Python does, and is the route to use if you want to change anything. You need
**Python 3.11 or newer**.

Clone the repository and set up an isolated environment, so Clayton's dependencies stay out of
your system Python:

```
git clone https://github.com/Testare/clayton.git
cd clayton

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

Install what it needs and run it:

```
pip install -r app/requirements.txt
python -m app.main
```

That runs Clayton straight from the source tree — no build step. To produce a standalone
executable like the ones on the Releases page:

```
pip install pyinstaller
pyinstaller packaging/clayton.spec
```

which leaves a single file at `dist/Clayton` (`dist/Clayton.exe` on Windows). Windows has its
own walkthrough, including the failures worth expecting, in
[packaging/BUILDING-WINDOWS.md](../packaging/BUILDING-WINDOWS.md).

**On Windows** you also need the **WebView2 runtime**, which is what actually draws the
interface. Windows 11 and recent Windows 10 already have it; otherwise install the Evergreen
redistributable from
[Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/).

**On Linux** you need GTK 3, WebKitGTK and the GObject introspection typelibs from your
distribution — on Debian/Ubuntu, `gir1.2-gtk-3.0`, `gir1.2-webkit2-4.1` and `libgtk-3-0`.

### Using the Nix flake

The best route on Linux: it builds the app *and* installs a launcher entry and icon, so
Clayton appears in your application menu like anything else.

Run it without installing anything permanent:

```
nix run github:Testare/clayton
```

Or build it and keep the result:

```
nix build github:Testare/clayton
./result/bin/clayton
```

From a local clone, drop the URL — `nix build .#clayton`, then `./result/bin/clayton`.

To install it into your profile:

```
nix profile install github:Testare/clayton
```

This route needs no Python setup and no system GTK packages: the flake pulls in WebKitGTK and
the typelibs itself, which is exactly why it is the dependable option on Linux.

## Where your data lives

Outside the app, always — so replacing or rebuilding Clayton never touches your profiles, runs
or charts.

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

| Field        | What to put                                               |
| ------------ | --------------------------------------------------------- |
| Name         | Anything you'll recognise: `SoulSilver — DSi`             |
| Trainer name | Your in-game name (a label; nothing is computed from it)  |
| Version      | HeartGold or SoulSilver                                   |
| Console      | Which DS. Worth recording — timing differs between models |

> **Screenshot:** the New Profile form.

Once created, you'll have an option to add metronome users to the profile. Don't worry about that for now, we'll cover that in the metronome compass section.

## Step 2 — Make an expedition

An **expedition** is one hunt for one Pokémon. It holds the target seed, the area, and your
block scores. Charts and saved targets belong to it.

**Expeditions → New.**

| Field                 | What to put                                                            |
| --------------------- | ---------------------------------------------------------------------- |
| Name                  | Whatever you want. Must be unique across *all* profiles                   |
| Profile               | The profile above                                                      |
| Pokémon               | The species you're after                                               |
| Safari area           | Which area it's in — narrowed to areas that actually hold your species |
| **Key seed**          | The initial seed (Seed A) you intend to hit: `0x0D0E02BA`      |
| **Key-seed advances** | The Seed A advance frame you'll Sweet Scent on                         |
| Safari block scores   | See [page 7](07-safari-blocks.md)                                      |

### Where the key seed/key-seed advances comes from

From whatever tool you prefer, like PokeFinder or RNGReporter. When you find a combination of seed and advances that produces the pokemon you want, that is your key seed and the key-seed advances. For example, on my file, seed 0x0C0E02C2 and 81 advances produces a shiny adamant Metang.

> **Screenshot:** the expedition Configure form.

## Step 3 — Check the tools are there

Open the expedition. You should see three tools:

- **☝️🧭 Metronome Compass** — New Run, Review Data
- **⛺🗺️ Safari Chart** — Find Target, Manage Data
- **⛺🧭 Safari Compass** — New Run, Review Data

> **Screenshot:** the expedition home page with the three tool cards.

## What next

For the perfect, ideal run, you should now get ready to use metronome compass. However, it is not STRICTLY necessary, and it'll take time both to get set up and also to collect data.

If you do not use metronome compass, you can use the standard statistical model that ships with this software instead, and jump straight to using Safari Chart. It might not be as accurate or precise for your specfic model, but it might be accurate enough to identify seeds in Safari Compass, and you can do some reasonable calibrations using only Safari Compass.

Set up your timer first ([page 3](03-timers.md)), then calibrate
([page 4](04-metronome-compass.md)).

---

Next: [Timers and hitting seeds](03-timers.md)
