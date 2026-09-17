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


def main() -> None:
    _configure_linux_gtk_env()
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
    index = Path(__file__).parent / "web" / "index.html"
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
    webview.start(gui=gui)


if __name__ == "__main__":
    main()
