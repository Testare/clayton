"""files.py — native save/open dialogs for export/import.

Thin wrappers over pywebview's file dialogs so the facade can hand the user a real
"Save as…" / "Open…" window. Kept apart from the pure portability logic (which stays
unit-testable) because these need a live window and can't run headless.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# A small persisted preference (not tied to any profile/expedition) remembering the last
# folder a save/open dialog was pointed at, so repeat exports/imports don't keep landing
# back in the app's own data directory (round 11 feedback: every dialog was defaulting to
# ~/.local/share/Clayton, the app's own CWD, since no `directory` was ever passed at all).
_PREFS_COLLECTION = "app_prefs"
_PREFS_DOC = "dialogs"


def _default_directory() -> str:
    """~ on Linux/macOS; the user's Documents folder on Windows when it exists, else ~."""
    home = Path.home()
    if sys.platform == "win32":
        docs = home / "Documents"
        if docs.is_dir():
            return str(docs)
    return str(home)


def _last_directory(store) -> str:
    doc = store.read(_PREFS_COLLECTION, _PREFS_DOC) if store is not None else None
    d = doc.get("last_dir") if doc else None
    return d if d and Path(d).is_dir() else _default_directory()


def _remember_directory(store, path: str | None) -> None:
    if store is None or not path:
        return
    store.write(_PREFS_COLLECTION, _PREFS_DOC, {"last_dir": str(Path(path).parent)})


def _window():
    import webview
    if not webview.windows:
        raise RuntimeError("no application window is open")
    return webview.windows[0]


def save_json_dialog(default_name: str, obj, store=None) -> str | None:
    """Prompt for a save location and write ``obj`` as JSON. Returns the path, or None if cancelled."""
    import webview
    result = _window().create_file_dialog(
        webview.SAVE_DIALOG, directory=_last_directory(store), save_filename=default_name)
    if not result:
        return None
    path = result if isinstance(result, str) else result[0]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    _remember_directory(store, path)
    return path


def open_json_dialog(store=None):
    """Prompt for a JSON file and return its parsed contents, or None if cancelled."""
    import webview
    result = _window().create_file_dialog(
        webview.OPEN_DIALOG, directory=_last_directory(store),
        file_types=("JSON files (*.json)", "All files (*.*)"))
    if not result:
        return None
    path = result[0] if isinstance(result, (list, tuple)) else result
    _remember_directory(store, path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_jsonl_dialog(default_name: str, rows: list[dict], store=None) -> str | None:
    """Prompt for a save location and write `rows` as jsonl (one JSON object per line,
    the same raw format claytonlib itself uses for compass_runs.jsonl/safari_runs.jsonl —
    no envelope). Returns the path, or None if cancelled."""
    import webview
    result = _window().create_file_dialog(
        webview.SAVE_DIALOG, directory=_last_directory(store), save_filename=default_name)
    if not result:
        return None
    path = result if isinstance(result, str) else result[0]
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    _remember_directory(store, path)
    return path


def open_jsonl_dialog(store=None) -> list[dict] | None:
    """Prompt for a jsonl file and return its parsed rows (blank lines skipped), or None
    if cancelled."""
    import webview
    result = _window().create_file_dialog(
        webview.OPEN_DIALOG, directory=_last_directory(store),
        file_types=("JSONL files (*.jsonl)", "All files (*.*)"))
    if not result:
        return None
    path = result[0] if isinstance(result, (list, tuple)) else result
    _remember_directory(store, path)
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
