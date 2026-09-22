# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — a proper Clayton app on Windows and macOS.

    pip install pyinstaller
    pyinstaller packaging/clayton.spec        # run from the REPO ROOT

Produces ONE FILE by default -- everything packed into a single executable you can move
around on its own:
  Windows   dist/Clayton.exe    windowed (no console), wearing packaging/clayton.ico
  macOS     dist/Clayton.app    a real bundle, wearing packaging/clayton.icns
  Linux     dist/Clayton        a binary; the packaged Nix build is the better path there,
                                since it also installs the .desktop entry

Set CLAYTON_ONEDIR=1 for a folder build instead (dist/Clayton/ with the exe beside an
_internal directory). That starts noticeably faster, because a one-file build unpacks its
~45 MB into a temp directory on every launch, but it is a folder you have to keep together.
One file is the default because it is what people expect to download and run.

Nix users on Linux need none of this — `nix build .#clayton` already produces an installed
app with its desktop entry and icon theme sizes. This exists for the platforms Nix isn't
doing the packaging on.

DATA FILES: claytonlib and app both load their static data through importlib.resources, which
works inside a frozen build as long as the files are laid down at their package-relative
paths — hence the `datas` entries below rather than any --add-data guesswork. app/main.py
additionally resolves web/index.html and resources/clayton.png through Path(__file__).parent,
which lands in the same place, so one set of entries covers both access styles.
"""
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

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
# PyInstaller ships no hook for pythonnet or clr_loader, so nothing tells it that they carry
# native shims and a managed assembly (Python.Runtime.dll) that must travel with the build.
# collect_all sweeps up their binaries and data rather than relying on the module graph, which
# only sees the Python side. Windows-only: they aren't installed anywhere else.
extra_binaries, extra_datas, extra_hidden = [], [], []
if sys.platform == "win32":
    for pkg in ("pythonnet", "clr_loader"):
        try:
            pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
        except Exception:
            continue                       # not installed -> nothing to collect
        extra_datas += pkg_datas
        extra_binaries += pkg_binaries
        extra_hidden += pkg_hidden

a = Analysis(
    [str(PACKAGING / "entry.py")],
    pathex=[str(ROOT)],
    binaries=extra_binaries,
    datas=datas + extra_datas,
    hiddenimports=hiddenimports + extra_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pytest", "numpy", "matplotlib"] + unused_backends,
    noarchive=False,
)
pyz = PYZ(a.pure)

onedir = bool(os.environ.get("CLAYTON_ONEDIR"))

# Shared between both modes. In one-file mode the binaries and data go INTO the exe; in
# folder mode they are held back and COLLECT lays them out beside it.
_exe_args = [pyz, a.scripts] if onedir else [pyz, a.scripts, a.binaries, a.datas]
exe = EXE(
    *_exe_args,
    [],
    exclude_binaries=onedir,
    name="Clayton",
    debug=False,
    strip=False,
    upx=False,
    # No console window: this is a GUI app, and a stray terminal behind it looks broken.
    console=False,
    icon=str(PACKAGING / "clayton.ico"),
)

# The thing macOS should wrap in a .app: the collected tree, or the single binary.
bundle_target = exe
if onedir:
    bundle_target = COLLECT(
        exe, a.binaries, a.datas,
        strip=False, upx=False, name="Clayton",
    )

# macOS only: wrap it in a real .app so Finder, the Dock and Launchpad treat it as an
# application (and read the icns) instead of showing a bare unix executable.
if sys.platform == "darwin":
    app = BUNDLE(
        bundle_target,
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
