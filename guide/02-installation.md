# 2. Installing Clayton

Three ways in, depending on how much you want to do yourself. Any of them gets you the
same app.

## Download directly

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

## Building from source

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

## Using the Nix flake

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

---

Next: [Getting started](03-getting-started.md)
