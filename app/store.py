"""store.py — JSON document persistence behind one seam.

A ``Store`` keeps small JSON documents grouped into *collections* (``profiles``,
``expeditions``, later ``runs``/``models``/…). The app and facade only ever talk to
this interface, so swapping the backing medium — local files today, potentially
something else later — never touches the callers.

``FileStore`` is the desktop backend: one file per document at
``<root>/<collection>/<doc_id>.json``, written atomically. ``root`` defaults to a
per-OS user-data directory so a user's expeditions and models live somewhere stable
and backup-friendly, not next to the executable.
"""
from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

_APP_DIR_NAME = "Clayton"
# collection / doc-id must be safe path segments — no separators, no traversal.
_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def default_data_dir(app_name: str = _APP_DIR_NAME) -> Path:
    """The per-OS directory for this app's user data (created on first write)."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:  # Linux / other POSIX — follow XDG.
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / app_name


def _check_segment(kind: str, value: str) -> str:
    if not value or any(c not in _SAFE for c in value) or value in (".", ".."):
        raise ValueError(f"unsafe {kind}: {value!r}")
    return value


class Store(ABC):
    """Interface for JSON-document persistence, grouped by collection."""

    @abstractmethod
    def read(self, collection: str, doc_id: str) -> dict | None:
        """Return the document, or ``None`` if it doesn't exist."""

    @abstractmethod
    def write(self, collection: str, doc_id: str, data: dict) -> None:
        """Create or replace the document."""

    @abstractmethod
    def list_ids(self, collection: str) -> list[str]:
        """Return the document ids in the collection (empty if none)."""

    @abstractmethod
    def delete(self, collection: str, doc_id: str) -> bool:
        """Remove the document; return whether it existed."""

    def exists(self, collection: str, doc_id: str) -> bool:
        return self.read(collection, doc_id) is not None


class FileStore(Store):
    """A :class:`Store` backed by one JSON file per document under ``root``."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else default_data_dir()

    def _path(self, collection: str, doc_id: str) -> Path:
        return self.root / _check_segment("collection", collection) / (
            _check_segment("doc_id", doc_id) + ".json"
        )

    def read(self, collection: str, doc_id: str) -> dict | None:
        path = self._path(collection, doc_id)
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def write(self, collection: str, doc_id: str, data: dict) -> None:
        path = self._path(collection, doc_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replace: write a sibling temp file, then rename over the target so a
        # crash mid-write can never leave a half-written document.
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)

    def list_ids(self, collection: str) -> list[str]:
        directory = self.root / _check_segment("collection", collection)
        if not directory.is_dir():
            return []
        return sorted(
            p.stem for p in directory.glob("*.json") if not p.name.startswith(".")
        )

    def delete(self, collection: str, doc_id: str) -> bool:
        path = self._path(collection, doc_id)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
