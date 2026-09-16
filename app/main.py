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

import sys
from pathlib import Path


def main() -> None:
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
    webview.start()


if __name__ == "__main__":
    main()
