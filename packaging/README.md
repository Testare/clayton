# Packaging Clayton as a desktop app

Everything here exists so Clayton shows up as a real application — a name, an icon in the
launcher and taskbar, and a window the desktop associates with it — rather than an unnamed
window with a generic icon.

## The icon

All icon files are generated from one 32×32 source drawing by `one-offs/make_icon.py`:

```
python one-offs/make_icon.py
```

| Output | Used by |
|---|---|
| `app/resources/clayton.png` | the running app's window icon (`webview.start(icon=)`) |
| `packaging/icons/<N>x<N>/clayton.png` | the Linux hicolor icon theme |
| `packaging/clayton.ico` | the Windows `.exe` |
| `packaging/clayton.icns` | the macOS `.app` bundle |

The art is a **hand-drawn approximation** of a Safari Ball, not a rip of the game's sprite.
To swap in a different image, replace the PNGs (and regenerate the `.ico`/`.icns`, or supply
your own) — nothing reads the art except through these files.

## Desktop identity

Two things have to agree or the desktop environment treats the window as unrelated to the
launcher — the classic symptom being a duplicate, generic-icon entry in the taskbar:

- `packaging/clayton.desktop` sets `StartupWMClass=clayton`
- `app/main.py` pins the GTK program name to `clayton` (`_set_app_identity`)

On Windows the same function sets an explicit **AppUserModelID**; without one the shell groups
the window under the host Python interpreter and shows *its* icon rather than ours.

## Linux — Nix (recommended)

```
nix build .#clayton
```

The package installs the binary, `share/applications/clayton.desktop`, and all eight hicolor
icon sizes. Nothing else is needed.

## Windows

**See [BUILDING-WINDOWS.md](BUILDING-WINDOWS.md)** for the full step-by-step. In short:

```
pip install pywebview pyinstaller
pyinstaller packaging\clayton.spec         # run from the REPO ROOT
```

Produces `dist/Clayton/Clayton.exe` — windowed (no console), wearing `clayton.ico`. The
EdgeChromium backend needs the **WebView2 runtime**, which ships with Windows 11 and recent
Windows 10; on older machines install the Evergreen redistributable.

## macOS

```
pip install pyinstaller
pyinstaller packaging/clayton.spec
```

Produces `dist/Clayton.app` with `clayton.icns` and an `Info.plist` declaring
`NSHighResolutionCapable` (without which the window renders soft on any Retina display).
Unsigned, so first launch needs right-click → Open, or `xattr -dr com.apple.quarantine`.

## Linux — PyInstaller

The spec builds on Linux too, but the resulting binary needs GTK 3, WebKitGTK and the GObject
**typelibs** present on the target machine — PyInstaller does not bundle those, so a build
that works on your machine can fail elsewhere with `Namespace Gtk not available`. Use the Nix
package on Linux.

## What has actually been tested

| | Built | Ran |
|---|---|---|
| Nix (Linux) | yes | yes |
| PyInstaller on Linux | yes | reaches backend selection; fails on host GTK typelibs, as above |
| PyInstaller on Windows | **not tested** | **not tested** |
| PyInstaller on macOS | **not tested** | **not tested** |

The Windows and macOS paths are written from the documented behaviour of PyInstaller and
pywebview, and the spec's platform-independent parts (data collection, backend excludes, icon
wiring, bundle layout) are exercised by the Linux build. Treat the first build on each of
those platforms as the real test.

### One failure already found and fixed

The first Linux build died with:

```
ERROR: Unable to find '.../translations/qtwebengine_locales' when adding binary and data files
```

pywebview probes for every backend it supports, so PyInstaller followed those imports and its
Qt hooks tried to bundle the whole of PySide6. The spec now **excludes** the backends the
current platform will not use, which is why the bundle is 47 MB rather than several hundred.
The same trap applies on Windows and macOS if any Qt binding is installed alongside.
