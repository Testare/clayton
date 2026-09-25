"""_version.py — the one place Clayton's version number is read from.

VERSION at the repo root holds it as bare text, so a release workflow or a human can read it
without parsing Python or TOML. Everything else — pyproject, the Nix package, the window
header, the release tag — is expected to agree with that file.
"""
from __future__ import annotations

_FALLBACK = "0.1.0"


def version() -> str:
    """The current version string, e.g. "0.1.0".

    Read from the packaged VERSION resource, falling back to a literal if it is missing —
    a version number is cosmetic and must never be the reason the app fails to start.
    """
    try:
        from importlib.resources import files
        text = (files("app") / "resources" / "VERSION").read_text(encoding="utf-8")
        return text.strip() or _FALLBACK
    except Exception:
        return _FALLBACK
