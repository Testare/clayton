"""portability.py — export/import of user data (backup, migration).

A first-class, versioned JSON envelope wraps exported data so older exports stay
importable.

Two export shapes:
* **Expedition** — one expedition plus the charts and targets built from it (a self-
  contained hunt setup).
* **Profile bundle** — a profile plus everything it owns: its expeditions (each with
  their charts/targets), its runs, and its saved calibration models. The whole-
  profile backup / machine-to-machine migration path.

COLLISIONS: importing checks for an existing same-named profile (bundle) or same-
named expedition-in-that-profile (single expedition) and, if one exists, returns a
collision descriptor (`{"collision": True, ...}`) instead of importing — the caller
must re-call with an explicit `on_collision` decision:
* expedition: "copy" (import alongside, as new) or "replace" (overwrite the existing
  one's data, keeping its id so anything set up around it stays put).
* bundle: "new" (import as a separate profile, the always-safe default) or "merge"
  (fold the bundle's expeditions/runs/models into the EXISTING same-named profile,
  leaving that profile's own fields — name, TID/SID, metronome users — untouched).

Every import is otherwise a *copy*: child documents get fresh ids (old id -> new id
maps are built and used to re-point cross-references — a target's chart_id, a
chart/run/model's profile_id or expedition_id) so importing never overwrites
anything by accident. Standard-tagged runs ship with the app and are never
exported. Manually-excluded runs are skipped unless `include_excluded=True`
(bead clayton-dxq.6) — their flags travel with them either way, so re-importing
a bundle that does include them round-trips exclusion state too.
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


def _where(store, collection: str, field: str, value: str) -> list[dict]:
    out = []
    for doc_id in store.list_ids(collection):
        doc = store.read(collection, doc_id)
        if doc is not None and doc.get(field) == value:
            out.append(doc)
    return out


def _find_by_name(store, collection: str, name: str, **extra_match) -> dict | None:
    for doc_id in store.list_ids(collection):
        doc = store.read(collection, doc_id)
        if doc is None or doc.get("name") != name:
            continue
        if all(doc.get(k) == v for k, v in extra_match.items()):
            return doc
    return None


def _const_map(old_value, new_value) -> dict:
    """{old_value: new_value} — a one-entry _import_children `repoint` mapping for a field
    every doc in a batch shares the SAME old value for (e.g. every doc in a profile bundle
    has the same source profile_id, all re-pointing to the one target profile)."""
    return {old_value: new_value}


def _import_children(store, collection: str, docs: list[dict], id_map: dict, **repoint) -> list[dict]:
    """Write each of `docs` as a fresh copy (new id), re-pointing the fields named in
    `repoint` (field -> old value's id_map, e.g. expedition_id=exp_id_map) through their
    own old->new mapping. Returns the new docs (each carrying its fresh id)."""
    out = []
    for doc in docs:
        doc = dict(doc)
        old_id = doc["id"]
        doc["id"] = _new_id()
        id_map[old_id] = doc["id"]
        for field, mapping in repoint.items():
            if doc.get(field) in mapping:
                doc[field] = mapping[doc[field]]
        store.write(collection, doc["id"], doc)
        out.append(doc)
    return out


# ---------------------------------------------------------------------------
# Expedition (+ its charts/targets)
# ---------------------------------------------------------------------------

def export_expedition(store, expedition_id: str) -> dict:
    doc = store.read("expeditions", expedition_id)
    if doc is None:
        raise ValueError(f"no expedition with id {expedition_id!r}")
    charts = _where(store, "charts", "expedition_id", expedition_id)
    targets = _where(store, "targets", "expedition_id", expedition_id)
    return _envelope("expedition", {"expedition": doc, "charts": charts, "targets": targets})


def import_expedition(store, profile_id: str, envelope: dict, on_collision: str | None = None) -> dict:
    """Import one expedition (+ its charts/targets) into `profile_id`.

    Returns {"collision": True, "existing_id", "existing_name"} if an expedition with
    the same name already exists in this profile and `on_collision` wasn't given.
    Otherwise {"expedition_id", "counts": {"charts", "targets"}}.
    """
    data = _require(envelope, "expedition")
    exp = dict(data.get("expedition") or {})
    if not exp:
        raise ValueError("export has no expedition")
    name = exp.get("name")

    existing = _find_by_name(store, "expeditions", name, profile_id=profile_id) if name else None
    if existing and on_collision is None:
        return {"collision": True, "existing_id": existing["id"], "existing_name": existing["name"]}

    old_exp_id = exp["id"]
    exp["profile_id"] = profile_id
    if existing and on_collision == "replace":
        exp["id"] = existing["id"]
    else:
        exp["id"] = _new_id()
    store.write("expeditions", exp["id"], exp)

    exp_id_map = {old_exp_id: exp["id"]}
    chart_id_map: dict = {}
    charts = _import_children(store, "charts", data.get("charts", []), chart_id_map,
                              expedition_id=exp_id_map)
    targets = _import_children(store, "targets", data.get("targets", []), {},
                               expedition_id=exp_id_map, chart_id=chart_id_map)
    return {"expedition_id": exp["id"],
            "counts": {"charts": len(charts), "targets": len(targets)}}


# ---------------------------------------------------------------------------
# Runs (jsonl) — a lighter-weight sibling of the profile bundle's own runs export: just
# the runs themselves, as plain jsonl (one run dict per line, no envelope/versioning —
# matches the raw-jsonl convention claytonlib itself already uses for compass_runs.jsonl/
# safari_runs.jsonl). Each run dict's own "kind" field ("metronome"/"safari") already
# disambiguates the two compasses, so nothing else needs to travel alongside it.
# ---------------------------------------------------------------------------

# Dropped from the exported jsonl (round 11 feedback) -- target_timer_calibration and
# frame_guide are both app-local convenience data (a fit-time offset and a rendered "how to
# get there" route guide) rather than anything a fit or another profile needs; leaving them
# out keeps the export focused on the run's actual observations. A run re-imported without
# them just falls back to Run.from_dict's own defaults (0 and "").
_RUN_EXPORT_DROP_FIELDS = ("target_timer_calibration", "frame_guide")


def export_runs_jsonl(store, run_ids: list[str]) -> list[dict]:
    """The stored run docs for `run_ids`, in the given order — ready to write one per
    line. Silently skips any id that no longer resolves (e.g. deleted since selection)."""
    out = []
    for rid in run_ids:
        doc = store.read("runs", rid)
        if doc is not None:
            out.append({k: v for k, v in doc.items() if k not in _RUN_EXPORT_DROP_FIELDS})
    return out


def import_runs_jsonl(store, profile_id: str, rows: list[dict]) -> list[dict]:
    """Import a list of run dicts (from a jsonl export) into `profile_id` as fresh copies
    — new ids, re-pointed profile_id, everything else (tag/notes/excluded/seeds/...)
    carried through verbatim. Always a copy, never overwrites an existing run."""
    if store.read("profiles", profile_id) is None:
        raise ValueError(f"no profile with id {profile_id!r}")
    out = []
    for row in rows:
        doc = dict(row)
        doc["id"] = _new_id()
        doc["profile_id"] = profile_id
        store.write("runs", doc["id"], doc)
        out.append(doc)
    return out


# ---------------------------------------------------------------------------
# Profile bundle (+ its expeditions/charts/targets/runs/calibration models)
# ---------------------------------------------------------------------------

def export_profile_bundle(store, profile_id: str, include_excluded: bool = True) -> dict:
    """A profile + everything it owns: expeditions (each with their charts/targets),
    runs (Standard-tagged always skipped; manually-excluded skipped unless
    include_excluded), and saved calibration models."""
    profile = store.read("profiles", profile_id)
    if profile is None:
        raise ValueError(f"no profile with id {profile_id!r}")

    expeditions = _where(store, "expeditions", "profile_id", profile_id)
    exp_ids = {e["id"] for e in expeditions}
    charts = [c for eid in exp_ids for c in _where(store, "charts", "expedition_id", eid)]
    targets = [t for eid in exp_ids for t in _where(store, "targets", "expedition_id", eid)]

    runs = _where(store, "runs", "profile_id", profile_id)
    runs = [r for r in runs if r.get("tag") != _STANDARD_TAG]
    if not include_excluded:
        runs = [r for r in runs if not r.get("excluded")]

    models = _where(store, "calibration_models", "profile_id", profile_id)

    return _envelope("profile_bundle", {
        "profile": profile, "expeditions": expeditions, "charts": charts,
        "targets": targets, "runs": runs, "calibration_models": models,
    })


def find_profile_by_name(store, name: str) -> dict | None:
    return _find_by_name(store, "profiles", name)


def import_profile_bundle(store, envelope: dict, on_collision: str | None = None) -> dict:
    """Import a profile bundle.

    Returns {"collision": True, "existing_id", "existing_name"} if a profile with the
    same name already exists and `on_collision` wasn't given. Otherwise
    {"profile_id", "profile_name", "merged": bool, "counts": {...}}.

    on_collision="new" (or no collision at all): always a fresh, separate profile.
    on_collision="merge": fold expeditions/runs/charts/targets/models into the
    EXISTING same-named profile — that profile's own fields are left untouched.
    """
    data = _require(envelope, "profile_bundle")
    profile = dict(data.get("profile") or {})
    if not profile:
        raise ValueError("bundle has no profile")
    name = profile.get("name")
    old_profile_id = profile.get("id")

    existing = find_profile_by_name(store, name) if name else None
    if existing and on_collision is None:
        return {"collision": True, "existing_id": existing["id"], "existing_name": existing["name"]}

    merging = bool(existing and on_collision == "merge")
    if merging:
        target_profile_id = existing["id"]
    else:
        profile["id"] = _new_id()
        store.write("profiles", profile["id"], profile)
        target_profile_id = profile["id"]

    src_expeditions = data.get("expeditions", [])
    src_runs = data.get("runs", [])
    src_models = data.get("calibration_models", [])
    profile_map = _const_map(old_profile_id, target_profile_id)

    # Captured BEFORE importing anything — used to renumber merged-in models below, so it
    # must reflect only what the target profile already had, never the just-imported ones.
    pre_existing_models = _where(store, "calibration_models", "profile_id", target_profile_id) \
        if merging else []

    exp_id_map: dict = {}
    chart_id_map: dict = {}
    expeditions = _import_children(store, "expeditions", src_expeditions, exp_id_map,
                                   profile_id=profile_map)
    charts = _import_children(store, "charts", data.get("charts", []), chart_id_map,
                              expedition_id=exp_id_map)
    targets = _import_children(store, "targets", data.get("targets", []), {},
                               expedition_id=exp_id_map, chart_id=chart_id_map)
    runs = _import_children(store, "runs", src_runs, {}, profile_id=profile_map)
    models = _import_children(store, "calibration_models", src_models, {}, profile_id=profile_map)
    # A merged-in model set shouldn't silently steal "active" from whatever the existing
    # profile already had deployed, and its numbers must not collide with existing ones.
    if merging:
        next_number = max((m.get("number", 0) for m in pre_existing_models), default=0) + 1
        for m in models:
            m["active"] = False
            m["number"] = next_number
            next_number += 1
            store.write("calibration_models", m["id"], m)

    return {
        "profile_id": target_profile_id, "profile_name": name, "merged": merging,
        "counts": {"expeditions": len(expeditions), "charts": len(charts),
                  "targets": len(targets), "runs": len(runs), "calibration_models": len(models)},
    }


# ---------------------------------------------------------------------------
# A single calibration model
# ---------------------------------------------------------------------------

def export_calibration_model(store, model_id: str) -> dict:
    doc = store.read("calibration_models", model_id)
    if doc is None:
        raise ValueError(f"no calibration model with id {model_id!r}")
    return _envelope("calibration_model", {"model": doc})


def import_calibration_model(store, profile_id: str, envelope: dict) -> dict:
    """Import one calibration model into `profile_id` as a new, numbered, inactive entry.

    No collision handling needed — models aren't name-unique, `number` auto-assigns past
    whatever the target profile already has, and importing never sets `active` (an
    imported model is reviewed and activated deliberately, like any other saved fit)."""
    data = _require(envelope, "calibration_model")
    doc = dict(data.get("model") or {})
    if not doc:
        raise ValueError("export has no model")
    existing = _where(store, "calibration_models", "profile_id", profile_id)
    doc["id"] = _new_id()
    doc["profile_id"] = profile_id
    doc["number"] = max((m.get("number", 0) for m in existing), default=0) + 1
    doc["active"] = False
    store.write("calibration_models", doc["id"], doc)
    return {"model_id": doc["id"], "number": doc["number"]}
