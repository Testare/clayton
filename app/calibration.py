"""calibration.py — the Calibrate Model view, wrapped for the UI.

Bridges the app's profile-scoped Run/Profile entities to claytonlib's calibration_tools
fitting pipeline — Theil-Sen trend, MAD outlier screening, jitter estimation, and
CalibrationModel construction are all reused as-is (see calibrate_timer's `runs=` and
_run_metrics's `_run_id` passthrough — added specifically so this module could call the
real, tested fit rather than reimplementing it).

EXCLUSION SEMANTICS (see notes/clayton_v1_draft2.md / bead clayton-dxq): a run's
effective-included status is NOT manually-excluded AND NOT excluded-by-tag AND NOT an
outlier. The app applies the first two (manual + tag) before fitting; calibrate_timer
applies the third itself, on whatever subset it receives — so "outlier" is always freshly
computed relative to today's included set, never stored.

WEIGHTING: draft2 describes per-tag weighting (a per-run multiplier feeding the fit,
weight 0 == excluded). Only the on/off half (tag exclusion) is implemented here —
continuous weighting needs either a weighted trend fit or a principled replication
scheme, neither of which calibrate_timer's Theil-Sen currently supports; tracked as a
follow-up (clayton-dxq.3) rather than approximated.
"""
from __future__ import annotations

from claytonlib.calibration_tools import calibrate_timer

_METRONOME_ONLY = "only metronome runs can be fit right now (calibrate_timer's F_b-vs-M model)"


def _record_for_run(run: dict) -> dict | None:
    """A calibrate_timer-shaped record for one app Run, or None if it can't be fit
    (missing Vector ms, or either seed not fully identified)."""
    if run.get("kind", "metronome") != "metronome":
        return None
    a, b = run.get("a_seed") or {}, run.get("b_seed") or {}
    if run.get("vector_ms") is None or "time" not in a or "time" not in b:
        return None
    return {
        "_run_id": run["id"],
        "tag": run.get("tag") or None,
        "target_timer_delay": run["vector_ms"],
        "target_timer_calibration": run.get("target_timer_calibration") or 0,
        "a_seed": a, "b_seed": b,
        # The app doesn't track mid-boot battle provenance yet — every saved run is treated
        # as a clean fresh boot (calibrate_timer's own default for older/appless records too).
        "prior_battles": 0, "fresh_boot": True,
    }


def effective_included(runs: list[dict], excluded_tags: set[str]) -> tuple[list[dict], dict[str, str]]:
    """Split `runs` into (calibrate_timer-ready records, {run_id: reason}) for runs that
    never reach the fit at all — excluded before calibrate_timer's own outlier pass ever
    runs on them. Reasons: "manual", "tag:<name>", or "incomplete" (no Vector ms / seeds).
    """
    records, excluded = [], {}
    for run in runs:
        if run.get("excluded"):
            excluded[run["id"]] = "manual"
            continue
        tag = run.get("tag") or ""
        if tag in excluded_tags:
            excluded[run["id"]] = f"tag:{tag}"
            continue
        rec = _record_for_run(run)
        if rec is None:
            excluded[run["id"]] = "incomplete"
            continue
        records.append(rec)
    return records, excluded


def preview_fit(runs: list[dict], excluded_tags: list[str]) -> dict:
    """Fit a calibration model from `runs` (after exclusions) and return a JSON-friendly
    report: per-run exclude reasons (manual/tag/incomplete/outlier/contaminated, combinable),
    fit stats, and the saveable modelset artifact. Touches no persisted state.
    """
    records, pre_excluded = effective_included(runs, set(excluded_tags))
    if not records:
        raise ValueError(
            "no fittable runs after exclusions (need Vector ms + both seeds identified)")

    m = calibrate_timer(runs=records, verbose=False)

    reasons: dict[str, list[str]] = {rid: [reason] for rid, reason in pre_excluded.items()}
    for r in m["runs"]:
        rid = r.get("_run_id")
        if rid is None:
            continue
        tags = []
        if r.get("outlier"):
            tags.append("outlier")
        if r.get("contaminated"):
            tags.append("contaminated")
        if tags:
            reasons.setdefault(rid, []).extend(tags)

    models = m["models"]
    artifact_models = {}
    if "linear_df" in models:
        artifact_models["linear"] = models["linear_df"]["model"]
    if "quad_df" in models:
        artifact_models["quad"] = models["quad_df"]["model"]
    if not artifact_models and m.get("recommended"):
        artifact_models["linear"] = models[m["recommended"]]["model"]

    return {
        "n_input": len(runs), "n_pre_excluded": len(pre_excluded),
        "n_runs": m["n_runs"], "n_fit": m["n_fit"],
        "n_outliers": m["n_outliers"], "n_contaminated": m["n_contaminated"],
        "recommended": m["recommended"],
        "reasons": {rid: "+".join(tags) for rid, tags in reasons.items()},
        "artifact": {
            "format": "modelset", "default": "linear",
            "models": {k: cm.to_dict() for k, cm in artifact_models.items()},
        },
        "stats": {
            k: {"kind": cm.kind, "n_runs": cm.n_runs, "n_fit": cm.n_fit,
                "beta": cm.beta, "alpha": cm.alpha, "jitter_c": cm.jitter_c,
                "rtc_offset_seconds": cm.rtc_offset_seconds, "rtc_offset_std": cm.rtc_offset_std}
            for k, cm in artifact_models.items()
        },
    }
