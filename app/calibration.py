"""calibration.py — the Calibrate Model view, wrapped for the UI.

Bridges the app's profile-scoped Run/Profile entities to claytonlib's calibration_tools
fitting pipeline — Theil-Sen trend, MAD outlier screening, jitter estimation, the safari
load-path offset, and CalibrationModel construction are all reused as-is (see
calibrate_timer's/fit_safari_offset's `runs=` and their `_run_id` passthroughs — added
specifically so this module could call the real, tested fits rather than reimplementing
them).

Metronome and safari runs feed TWO SEPARATE fits, mirroring the D/E split in
"Metronome Compass Calibration.ipynb" and "Safari Compass Calibration.ipynb": Metronome
Compass's Calibrate Model (`preview_fit`) never looks at safari runs and never produces a
`safari_offset` — it only fits the F_b-vs-M trend (slope, intercept, jitter). Safari
Compass has its OWN Calibrate Model flow (`preview_safari_offset`) that takes a
user-chosen BASE model (any saved model, including the bundled "Standard" one) and fits
`safari_offset` — the extra Safari-Zone loading screen's fixed frame offset — against it,
holding that base model's trend fixed (fit_safari_offset). A safari run alone can't
determine the trend; it only matters relative to an already-fitted model.

EXCLUSION SEMANTICS (see notes/clayton_v1_draft2.md / bead clayton-dxq): a run's
effective-included status is NOT manually-excluded AND NOT excluded-by-tag AND NOT an
outlier. The app applies the first two (manual + tag) before fitting; calibrate_timer/
fit_safari_offset apply outlier/contamination screening themselves on whatever subset they
receive — so "outlier" is always freshly computed relative to today's included set, never
stored. The same manual+tag exclusion pass (effective_included) covers both run kinds.

WEIGHTING: draft2 describes per-tag weighting (a per-run multiplier feeding the fit,
weight 0 == excluded). Only the on/off half (tag exclusion) is implemented here —
continuous weighting needs either a weighted trend fit or a principled replication
scheme, neither of which calibrate_timer's Theil-Sen currently supports; tracked as a
follow-up (clayton-dxq.3) rather than approximated.

ADVANCE-RECIPE HYPOTHESIS (unconfirmed): Run carries optional elm_calls/chatot_flips/
advance_frame fields to test whether Seed A's advance recipe correlates with a safari run's
frame miss. Nothing here fits that yet — it's still being verified (see
notes/flagged_for_review.md) — the fields are only captured so historical runs aren't
missing the data once/if it's confirmed.
"""
from __future__ import annotations

from claytonlib.calibration_tools import calibrate_timer, fit_safari_offset


def _record_for_run(run: dict) -> dict | None:
    """A calibrate_timer-shaped record for one app metronome Run, or None if it can't be
    fit (missing Vector ms, or either seed not fully identified)."""
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


def _record_for_safari_run(run: dict) -> dict | None:
    """A fit_safari_offset-shaped record for one app Safari Compass Run, or None if it
    can't feed the offset fit (missing Vector ms, a confident identified seed+frame, or
    Seed A's own identified frame)."""
    if run.get("kind") != "safari":
        return None
    a, b = run.get("a_seed") or {}, run.get("b_seed") or {}
    if run.get("vector_ms") is None or a.get("delay") is None or b.get("seed") is None \
            or b.get("frame") is None:
        return None
    return {
        "_run_id": run["id"],
        "tag": run.get("tag") or None,
        "seed": b["seed"], "frame": b["frame"], "a_seed": {"delay": a["delay"]},
        "target_timer_delay": run["vector_ms"],
        "target_timer_calibration": run.get("target_timer_calibration") or 0,
        "prior_battles": 0,
    }


def effective_included(runs: list[dict], excluded_tags: set[str], record_fn=_record_for_run
                       ) -> tuple[list[dict], dict[str, str]]:
    """Split `runs` into (fit-ready records via `record_fn`, {run_id: reason}) for runs that
    never reach the fit at all — excluded before the fit's own outlier pass ever runs on
    them. Reasons: "manual", "tag:<name>", or "incomplete" (record_fn returned None).
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
        rec = record_fn(run)
        if rec is None:
            excluded[run["id"]] = "incomplete"
            continue
        records.append(rec)
    return records, excluded


def _stats_for(cm) -> dict:
    return {"kind": cm.kind, "n_runs": cm.n_runs, "n_fit": cm.n_fit,
            "beta": cm.beta, "alpha": cm.alpha, "jitter_c": cm.jitter_c,
            "rtc_offset_seconds": cm.rtc_offset_seconds, "rtc_offset_std": cm.rtc_offset_std,
            "safari_offset": cm.safari_offset, "safari_offset_n": cm.safari_offset_n,
            "safari_offset_std": cm.safari_offset_std}


def preview_fit(metronome_runs: list[dict], excluded_tags: list[str]) -> dict:
    """Fit a calibration model from `metronome_runs` (after exclusions) — Metronome
    Compass's own Calibrate Model preview. Never looks at safari runs and never produces a
    `safari_offset`; see `preview_safari_offset` for Safari Compass's separate flow. Returns
    a JSON-friendly report — per-run exclude reasons (manual/tag/incomplete/outlier/
    contaminated, combinable), fit stats, and the saveable modelset artifact. Touches no
    persisted state.
    """
    records, pre_excluded = effective_included(metronome_runs, set(excluded_tags))
    if not records:
        raise ValueError(
            "no fittable metronome runs after exclusions (need Vector ms + both seeds identified)")

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
        "n_input": len(metronome_runs), "n_pre_excluded": len(pre_excluded),
        "n_runs": m["n_runs"], "n_fit": m["n_fit"],
        "n_outliers": m["n_outliers"], "n_contaminated": m["n_contaminated"],
        "recommended": m["recommended"],
        "reasons": {rid: "+".join(tags) for rid, tags in reasons.items()},
        "artifact": {
            "format": "modelset", "default": "linear",
            "models": {k: cm.to_dict() for k, cm in artifact_models.items()},
        },
        "stats": {k: _stats_for(cm) for k, cm in artifact_models.items()},
    }


def preview_safari_offset(base_models: dict, safari_runs: list[dict],
                          excluded_tags: list[str]) -> dict:
    """Safari Compass's own Calibrate Model preview: fit `safari_offset` from `safari_runs`
    (after exclusions) against each model in `base_models` (a chosen base model's own
    artifact, e.g. from CalibrationModel.from_dict on a saved CalibrationModelDoc) —
    holding that base model's trend (alpha/beta/coeffs) fixed. Never refits the trend
    itself and never touches metronome runs; see `preview_fit` for that separate flow.

    `changed` is True iff the newly-fit safari_offset differs from what `base_models`
    already had for at least one model kind — the UI uses it to disable "Save new model"
    when the base model was already calibrated to the same value (nothing to save).
    """
    records, pre_excluded = effective_included(
        safari_runs, set(excluded_tags), record_fn=_record_for_safari_run)

    fits: dict[str, dict] = {}
    changed = False
    for key, cm in base_models.items():
        old_offset = cm.safari_offset
        fit = fit_safari_offset(cm, runs=records) if records else None
        if fit is None:
            continue
        cm.safari_offset = fit["offset"]
        cm.safari_offset_n = fit["n"]
        cm.safari_offset_std = fit["std"]
        fits[key] = fit
        if old_offset is None or abs(old_offset - fit["offset"]) > 1e-9:
            changed = True

    return {
        "n_safari_input": len(safari_runs), "n_safari_pre_excluded": len(pre_excluded),
        "n_safari_fit": len(records),
        "changed": changed,
        "safari_offset": {k: {"offset": f["offset"], "n": f["n"], "std": f["std"]}
                          for k, f in fits.items()},
        "reasons": dict(pre_excluded),
        "artifact": {
            "format": "modelset", "default": "linear",
            "models": {k: cm.to_dict() for k, cm in base_models.items()},
        },
        "stats": {k: _stats_for(cm) for k, cm in base_models.items()},
    }
