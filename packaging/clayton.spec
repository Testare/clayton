# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Clayton Windows desktop app.

Build (on Windows, from the repo root):
    pip install pywebview pyinstaller
    pyinstaller packaging/clayton.spec
Produces dist/clayton.exe (onefile).

pywebview uses the EdgeChromium (WebView2) backend on Windows — its runtime ships
with Windows 10/11. We collect pywebview's bundled JS + WebView2 loader (and
pythonnet, which its EdgeChromium backend needs) via collect_all, and add our own
data: the packaged game data and the web front end.
"""
from PyInstaller.utils.hooks import collect_all

datas = [
    ("claytonlib/basedata", "claytonlib/basedata"),
    ("app/web", "app/web"),
]
binaries = []
hiddenimports = ["clr"]

# Pull everything pywebview (and its .NET bridge) needs; tolerate a package being
# absent so the spec still parses off-Windows.
for pkg in ("webview", "pythonnet"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        d, b, h = [], [], []
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["packaging/entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Backends we don't use on Windows — keep them out of the bundle.
    excludes=["gi", "PyQt5", "PyQt6", "PySide2", "PySide6", "numpy", "numba"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="clayton",
    debug=False,
    strip=False,
    upx=False,
    # Keep a console for first-run diagnostics; switch to console=False once it works.
    console=True,
    disable_windowed_traceback=False,
)
