"""main.py — launch the Clayton desktop app.

Opens a native window (pywebview) whose HTML front end talks to :class:`app.facade.Facade`
over the ``js_api`` bridge. No web server is started; the window loads a local file and
calls Python directly.

Run from the repo root:

    python -m app.main

Requires pywebview (``pip install -r app/requirements.txt``) and a system webview
(WebKitGTK / Qt on Linux, WebView2 on Windows, WKWebView on macOS).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The identity the desktop environment keys on. APP_ID must equal the StartupWMClass in
# packaging/clayton.desktop; APP_USER_MODEL_ID is the Windows equivalent and is conventionally
# a dotted, reverse-DNS-ish string.
APP_ID = "clayton"
APP_USER_MODEL_ID = "Testare.Clayton.SafariRNG.1"


def _configure_linux_gtk_env() -> None:
    """Make WebKitGTK behave on the range of Linux setups people actually run.

    Two env tweaks, both overridable if already set:

    * ``GDK_BACKEND=x11`` when an X display exists. GDK otherwise prefers Wayland
      whenever ``WAYLAND_DISPLAY`` is set, which on some setups (including X11
      sessions that still export it) fails with a Wayland protocol error. X11 is
      robust and also covers Wayland sessions via XWayland.
    * ``WEBKIT_DISABLE_DMABUF_RENDERER=1``. WebKitGTK's DMABUF/GPU renderer paints a
      blank page on many drivers (Nvidia, some Intel, VMs) — the window chrome shows
      but the content never appears. Disabling it fixes the blank view at a
      negligible cost for a form-shaped UI.
    """
    if not sys.platform.startswith("linux"):
        return
    if "GDK_BACKEND" not in os.environ and os.environ.get("DISPLAY"):
        os.environ["GDK_BACKEND"] = "x11"
    os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")


def _chdir_into_app_data() -> None:
    """Run the process out of the app's own data directory, not wherever it was launched from.

    claytonlib still has a handful of CWD-relative ``data/...`` paths (the calibration model,
    the get_times cache, chart canon maps/reports) left over from the notebook workflow, where
    the convention was "run from the repo root". A packaged app has no such convention — it can
    be launched from anywhere — so this anchors those relative paths to a real, writable,
    per-OS location instead of leaving them to resolve against an arbitrary CWD. It sits
    alongside (not inside) app.store's FileStore root, which already uses an absolute path and
    is unaffected either way.
    """
    from app.store import default_data_dir
    root = default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)


def _set_app_identity() -> None:
    """Tell the desktop environment which application this window belongs to.

    Without this the window is an orphan: on Linux the taskbar shows it beside the launcher
    instead of merged with it, and on Windows it groups under a generic Python entry wearing
    the interpreter's icon rather than ours.

    * Linux/GTK — WM_CLASS is derived from the GLib program name, which otherwise follows
      whatever argv[0] happened to be (a Nix wrapper, a PyInstaller bundle). Pinning it keeps
      it equal to the desktop entry's StartupWMClass.
    * Windows — the shell groups taskbar buttons and resolves the icon by AppUserModelID,
      which for an un-set process defaults to the host interpreter's.

    Both are best-effort: a missing GI typelib or an older Windows must not stop the app.
    """
    if sys.platform.startswith("linux"):
        try:
            from gi.repository import GLib
            GLib.set_prgname(APP_ID)
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass


def _icon_path():
    """The app's window icon (a Safari Ball, drawn by one-offs/make_icon.py), or None.

    Returned as a path for ``webview.start(icon=)``, which hands it to the platform's own
    loader (GTK: ``set_icon_from_file`` / ``set_default_icon_from_file``). None when the file
    isn't there — an icon is cosmetic, so a packaging that dropped it must still launch.
    """
    path = Path(__file__).parent / "resources" / "clayton.png"
    return path if path.exists() else None


def main() -> None:
    _configure_linux_gtk_env()
    _chdir_into_app_data()
    try:
        import webview
    except ImportError:
        sys.exit(
            "pywebview is not installed.\n"
            "  pip install -r app/requirements.txt\n"
            "(plus a system webview backend — see app/requirements.txt)."
        )

    from app.facade import Facade
    from app.store import FileStore

    api = Facade(FileStore())
    index = (Path(__file__).parent / "web" / "index.html").resolve()
    webview.create_window(
        "Clayton",
        url=str(index),
        js_api=api,
        width=1100,
        height=760,
        min_size=(820, 600),
    )
    # Force the GTK backend on Linux. pywebview would otherwise auto-pick whichever
    # backend it finds first, and the Nix package (like most Linux packagings) wires
    # up GTK/WebKitGTK, not Qt — letting it choose Qt lands you in a "no Qt platform
    # plugin" dead end. macOS/Windows keep their native backend (gui=None).
    gui = "gtk" if sys.platform.startswith("linux") else None
    _set_app_identity()
    icon = _icon_path()
    if icon is None:
        webview.start(gui=gui)
        return
    try:
        webview.start(gui=gui, icon=str(icon))
    except TypeError:
        # `icon` arrived in pywebview 6; an older one raises rather than ignoring it, and a
        # missing window icon is never worth failing to launch over.
        webview.start(gui=gui)


if __name__ == "__main__":
    main()
