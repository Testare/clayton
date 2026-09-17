"""files.py — native save/open dialogs for export/import.

Thin wrappers over pywebview's file dialogs so the facade can hand the user a real
"Save as…" / "Open…" window. Kept apart from the pure portability logic (which stays
unit-testable) because these need a live window and can't run headless.
"""
from __future__ import annotations

import json


def _window():
    import webview
    if not webview.windows:
        raise RuntimeError("no application window is open")
    return webview.windows[0]


def save_json_dialog(default_name: str, obj) -> str | None:
    """Prompt for a save location and write ``obj`` as JSON. Returns the path, or None if cancelled."""
    import webview
    result = _window().create_file_dialog(webview.SAVE_DIALOG, save_filename=default_name)
    if not result:
        return None
    path = result if isinstance(result, str) else result[0]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return path


def open_json_dialog():
    """Prompt for a JSON file and return its parsed contents, or None if cancelled."""
    import webview
    result = _window().create_file_dialog(
        webview.OPEN_DIALOG, file_types=("JSON files (*.json)", "All files (*.*)"))
    if not result:
        return None
    path = result[0] if isinstance(result, (list, tuple)) else result
    with open(path, encoding="utf-8") as f:
        return json.load(f)
