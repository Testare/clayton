"""portability.py — export/import of user data (backup, migration).

A first-class, versioned JSON envelope wraps exported data so older exports stay
importable. The headline use is the **profile bundle**: a profile plus its
expeditions and runs, which round-trips a whole hunt setup between machines or
between the desktop and (future) browser builds.

Imports bring data in as a *copy*: every document gets a fresh id and the profile's
children are re-pointed at the new profile id, so importing never collides with or
overwrites what's already there. (Replace-vs-merge semantics come later.)
Standard-tagged runs ship with the app and are never exported.
"""
from __future__ import annotations

import datetime as dt

from app.models import _new_id

EXPORT_VERSION = 1
_STANDARD_TAG = "Standard"


def _envelope(kind: str, data: dict) -> dict:
    return {
        "clayton_export": True,
        "version": EXPORT_VERSION,
        "kind": kind,
        "exported_at": dt.datetime.now().isoformat(timespec="seconds"),
        "data": data,
    }


def _require(envelope: dict, kind: str) -> dict:
    if not isinstance(envelope, dict) or not envelope.get("clayton_export"):
        raise ValueError("not a Clayton export file")
    if envelope.get("version", 0) > EXPORT_VERSION:
        raise ValueError(f"export is version {envelope.get('version')}, this build reads up to {EXPORT_VERSION}")
    if envelope.get("kind") != kind:
        raise ValueError(f"expected a {kind} export, got {envelope.get('kind')!r}")
    return envelope.get("data") or {}


def _children(store, collection: str, profile_id: str) -> list[dict]:
    out = []
    for doc_id in store.list_ids(collection):
        doc = store.read(collection, doc_id)
        if doc is not None and doc.get("profile_id") == profile_id:
            out.append(doc)
    return out


def export_expedition(store, expedition_id: str) -> dict:
    doc = store.read("expeditions", expedition_id)
    if doc is None:
        raise ValueError(f"no expedition with id {expedition_id!r}")
    return _envelope("expedition", {"expedition": doc})


def export_profile_bundle(store, profile_id: str) -> dict:
    """A profile + its expeditions + its runs (excluding Standard-tagged runs)."""
    profile = store.read("profiles", profile_id)
    if profile is None:
        raise ValueError(f"no profile with id {profile_id!r}")
    runs = [r for r in _children(store, "runs", profile_id) if r.get("tag") != _STANDARD_TAG]
    return _envelope("profile_bundle", {
        "profile": profile,
        "expeditions": _children(store, "expeditions", profile_id),
        "runs": runs,
    })


def import_profile_bundle(store, envelope: dict) -> dict:
    """Import a bundle as a fresh copy; returns the new profile id and counts."""
    data = _require(envelope, "profile_bundle")
    profile = dict(data.get("profile") or {})
    if not profile:
        raise ValueError("bundle has no profile")
    profile["id"] = _new_id()
    store.write("profiles", profile["id"], profile)

    counts = {"expeditions": 0, "runs": 0}
    for coll in ("expeditions", "runs"):
        for child in data.get(coll, []):
            child = dict(child)
            child["id"] = _new_id()
            child["profile_id"] = profile["id"]
            store.write(coll, child["id"], child)
            counts[coll] += 1
    return {"profile_id": profile["id"], "profile_name": profile.get("name"), "counts": counts}
