# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — a proper Clayton app on Windows and macOS.

    pip install pyinstaller
    pyinstaller packaging/clayton.spec        # run from the REPO ROOT

Produces:
  Windows   dist/Clayton/Clayton.exe   windowed (no console), wearing packaging/clayton.ico
  macOS     dist/Clayton.app           a real bundle, wearing packaging/clayton.icns
  Linux     dist/Clayton/Clayton       a binary; the packaged Nix build is the better path
                                       there, since it also installs the .desktop entry

Nix users on Linux need none of this — `nix build .#clayton` already produces an installed
app with its desktop entry and icon theme sizes. This exists for the platforms Nix isn't
doing the packaging on.

DATA FILES: claytonlib and app both load their static data through importlib.resources, which
works inside a frozen build as long as the files are laid down at their package-relative
paths — hence the `datas` entries below rather than any --add-data guesswork. app/main.py
additionally resolves web/index.html and resources/clayton.png through Path(__file__).parent,
which lands in the same place, so one set of entries covers both access styles.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent          # SPECPATH is packaging/, so ROOT is the repo root
PACKAGING = ROOT / "packaging"

datas = [
    (str(ROOT / "app" / "web" / "index.html"), "app/web"),
    (str(ROOT / "app" / "resources"), "app/resources"),
    (str(ROOT / "claytonlib" / "basedata"), "claytonlib/basedata"),
]

# pywebview picks its platform backend at runtime by importing it, which PyInstaller's static
# analysis cannot see -- so the one we actually use has to be named as a hidden import.
#
# The unused backends must then be EXCLUDED, not merely left unnamed. pywebview probes for
# every backend it supports, so PyInstaller's analysis follows those imports and its Qt hooks
# try to bundle the whole of PySide6 if any Qt binding is installed alongside. Observed
# failing exactly that way on a Linux build:
#     ERROR: Unable to find '.../translations/qtwebengine_locales' when adding binary
# Excluding the backends we don't use keeps the bundle to the one that will actually run.
_QT = ["qtpy", "PySide6", "PySide2", "PyQt5", "PyQt6", "shiboken6", "shiboken2",
       "webview.platforms.qt"]
_GTK = ["gi", "webview.platforms.gtk"]
_COCOA = ["webview.platforms.cocoa", "Foundation", "AppKit", "WebKit", "objc"]
_WIN = ["webview.platforms.edgechromium", "webview.platforms.winforms",
        "clr_loader", "pythonnet", "clr"]

hiddenimports = ["webview"]
if sys.platform == "win32":
    hiddenimports += ["webview.platforms.edgechromium", "clr_loader"]
    unused_backends = _QT + _GTK + _COCOA
elif sys.platform == "darwin":
    hiddenimports += ["webview.platforms.cocoa"]
    unused_backends = _QT + _GTK + _WIN
else:
    hiddenimports += ["webview.platforms.gtk"]
    unused_backends = _QT + _COCOA + _WIN

# entry.py, not app/main.py: analysing main.py directly makes it __main__, so its absolute
# `from app.facade import ...` imports are resolved by luck of pathex rather than by the
# package actually being imported. The tiny launcher does `from app.main import main`, which
# makes PyInstaller walk the real package graph.
a = Analysis(
    [str(PACKAGING / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest", "numpy", "matplotlib"] + unused_backends,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Clayton",
    debug=False,
    strip=False,
    upx=False,
    # No console window: this is a GUI app, and a stray terminal behind it looks broken.
    console=False,
    icon=str(PACKAGING / "clayton.ico"),
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="Clayton",
)

# macOS only: wrap the collected tree in a real .app so Finder, the Dock and Launchpad treat
# it as an application (and read the icns) instead of showing a bare unix executable.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Clayton.app",
        icon=str(PACKAGING / "clayton.icns"),
        bundle_identifier="Testare.Clayton.SafariRNG",
        info_plist={
            "CFBundleName": "Clayton",
            "CFBundleDisplayName": "Clayton",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            # Without this the window renders at 1x and looks soft on every Mac made in the
            # last decade.
            "NSHighResolutionCapable": True,
            # It is a normal windowed app, not a background agent.
            "LSUIElement": False,
        },
    )
