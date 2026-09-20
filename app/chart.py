"""chart.py — Safari Chart, wrapped for the UI.

Bridges the app's Expedition/Chart entities to ``claytonlib``'s canonical charting
pipeline (``claytonlib.chart.canon`` + ``.scorer``) via a throwaway
``claytonlib.expedition.Expedition`` — that class already owns the canon-store path
layout, the precompute/rank machinery, and the model-folding logic, and its
``_ensure_*`` prompts are skip-if-already-set, so populating every field before
calling it means no ``input()`` is ever reached. It is never ``.save()``d — the app's
own Chart/Target entities are the persisted record; the bridge exists only to reach
already-correct claytonlib logic without reimplementing it.

CALIBRATION MODEL: every function below that needs one takes a resolved
``models: dict[str, CalibrationModel]`` (the modelset shape — typically
``{"linear": ..., "quad": ...}``) as a plain parameter; this module has no opinion on
*where* it came from. The facade resolves it — a profile's active
``CalibrationModelDoc`` (see app/calibration.py) if one has been saved via Calibrate
Model, else a temporary fallback to claytonlib's one global model artifact (the file
the notebooks maintain), for anyone who calibrated there before the app could.

PATHS: canon maps and chart reports are heavy, non-document data (JSONL, can run to
many MB) and so are deliberately NOT routed through ``app.store`` — they use
claytonlib's own ``data/...``-relative layout. ``app.main`` chdirs the process into
the app's data directory at startup specifically so these land somewhere sane and
writable instead of wherever the executable happened to be launched from.
"""
from __future__ import annotations

import datetime as dt

from claytonlib.calibration import CalibrationModel
from claytonlib.chart import CanonStore
from claytonlib.chart.scorer import (
    best_per_scenario, distinct_targets, marginal_capture, rank_boot_marginal, rank_targets,
    refine_near, seed_breakdown,
)
from claytonlib.expedition import Expedition as _CLExpedition
from claytonlib.expedition._config import _resolve_criteria, _resolve_strategy
from claytonlib.safari import safari_pokemon_by_name
from claytonlib.times import get_times

_TIME_FMT = "%Y-%m-%dT%H:%M:%S"

# name -> one-line description, for the Create Chart form (draft2: "notes on what each
# criterion is and when it's useful"). Kept in app/ rather than claytonlib since these are
# UI copy, not library behavior.
_STRATEGY_DESCRIPTIONS = {
    "only-balls": "Throw balls every turn. Simplest strategy; no bait/mud setup.",
    "one-mud-then-balls": "One mud on turn 1 (raises catch rate), then balls every turn after.",
    "six-bait-then-balls": "Six bait first (suppresses fleeing while it lasts), then balls.",
}
_CRITERIA_DESCRIPTIONS = {
    "capture": "Success = captured. The straightforward goal for an actual catch attempt.",
}

# name -> a friendlier display label for the Create Chart form's dropdowns — `name` itself
# stays the wire value (what gets sent to create_chart / matched against templates below).
_STRATEGY_LABELS = {
    "only-balls": "Balls only",
    "one-mud-then-balls": "One mud, then balls",
    "six-bait-then-balls": "Six bait, then balls",
}
_CRITERIA_LABELS = {
    "capture": "Captured",
    "machete-turns-after-balls": "Machete path after N balls",
    "survived-turns-without-fleeing": "Lasted N turns",
    "balls-no-flee": "Lasted N balls",
}

# Criteria whose name embeds one or more numbers (claytonlib.expedition._config._resolve_criteria
# parses these back out via regex — see its docstring-less match block). Each entry's `template`
# is filled with `params` (in order) to build the actual criteria_name string sent to create_chart.
_PARAMETERIZED_CRITERIA = [
    {"name": "machete-turns-after-balls",
     "description": "Success = captured via a Machete-solved path, checked after N balls "
        "thrown, searching up to T turns deep.",
     "template": "machete-{turns}-turns-after-{n_balls}-balls",
     "params": [{"key": "turns", "label": "Max Machete turns", "default": 50},
                {"key": "n_balls", "label": "Balls thrown first", "default": 5}]},
    {"name": "survived-turns-without-fleeing",
     "description": "Success = still on screen (not fled) after N turns, not necessarily "
        "captured. Useful for calibration paths that need a long observation window.",
     "template": "survived-{turns}-turns-without-fleeing",
     "params": [{"key": "turns", "label": "Turns", "default": 10}]},
    {"name": "balls-no-flee",
     "description": "Success = captured, or N balls thrown without fleeing. A calibration-"
        "oriented path: the point is a long enough observed path to identify the seed, not "
        "necessarily a catch.",
     "template": "{n_balls}-balls-no-flee",
     "params": [{"key": "n_balls", "label": "Balls", "default": 10}]},
]


def _parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def list_strategies() -> list[dict]:
    from claytonlib.chart import STRATEGY_ONE_MUD, STRATEGY_ONLY_BALLS, STRATEGY_SIX_BAIT
    strategies = [STRATEGY_ONLY_BALLS, STRATEGY_ONE_MUD, STRATEGY_SIX_BAIT]
    return [{"name": s.name, "label": _STRATEGY_LABELS.get(s.name, s.name),
             "description": _STRATEGY_DESCRIPTIONS.get(s.name, "")} for s in strategies]


def list_criteria() -> list[dict]:
    """Fixed criteria plus parameterized templates (see _PARAMETERIZED_CRITERIA) — each
    parameterized entry carries `template`/`params` so the Create Chart form can render
    number inputs for it and build the actual `criteria_name` string client-side."""
    from claytonlib.chart import CRITERIA_CAPTURE
    fixed = [{"name": c.name, "label": _CRITERIA_LABELS.get(c.name, c.name),
              "description": _CRITERIA_DESCRIPTIONS.get(c.name, ""), "params": []}
              for c in [CRITERIA_CAPTURE]]
    parameterized = [dict(c, label=_CRITERIA_LABELS.get(c["name"], c["name"]))
                     for c in _PARAMETERIZED_CRITERIA]
    return fixed + parameterized


def list_safari_pokemon() -> list[str]:
    from claytonlib._resources import basedata_json
    return sorted(basedata_json("safari_pokemon.json"))


# ---------------------------------------------------------------------------
# Calibration models — resolution is the facade's job; this module just consumes
# ---------------------------------------------------------------------------

def global_calibration_models() -> dict[str, "CalibrationModel"]:
    """The one calibration model artifact claytonlib itself maintains (the file the
    notebooks write). A fallback for profiles that haven't saved one via Calibrate
    Model yet — never the primary source once that page is used."""
    return CalibrationModel.load_set()


def summarize_models(models: dict[str, "CalibrationModel"]) -> dict | None:
    """A JSON-friendly summary of a resolved models dict, or None if it's empty."""
    if not models:
        return None
    return {
        "available": sorted(models),
        "models": {
            k: {"kind": m.kind, "n_runs": m.n_runs, "label": m.label,
                "rtc_offset_seconds": m.rtc_offset_seconds, "rtc_offset_std": m.rtc_offset_std}
            for k, m in models.items()
        },
    }


def _pick_model(models: dict, fps_model: str, use_safari_offset: bool) -> "CalibrationModel":
    if not models:
        raise ValueError(
            "no calibration model available — build one from Metronome Compass → Review "
            "Data → Calibrate Model first")
    model = models.get(fps_model) or next(iter(models.values()))
    return model.with_safari_offset() if use_safari_offset else model


# ---------------------------------------------------------------------------
# Bridging to claytonlib.expedition.Expedition (never persisted)
# ---------------------------------------------------------------------------

def _bridge(exp: dict, chart: dict) -> _CLExpedition:
    e = _CLExpedition(name=f"_bridge_{chart['id']}")
    e.pokemon_name = exp["pokemon"]
    e.key_seed = exp["key_seed"]
    e.setup_delay_seconds = int(chart.get("setup_delay_seconds", 0))
    e.max_target_seconds = int(chart.get("max_target_seconds", 300))
    e.strategy_name = chart["strategy_name"]
    e.criteria_name = chart["criteria_name"]
    return e


def _canon_store(exp: dict, chart: dict) -> CanonStore:
    return CanonStore(_bridge(exp, chart)._canon_store_path())


def canon_status(exp: dict, chart: dict) -> dict:
    """Whether a canon map exists for this chart, and its coverage, without building it."""
    meta = _canon_store(exp, chart).read_meta()
    if meta is None:
        return {"built": False}
    return {
        "built": True, "n_mdmsh": meta.get("n_mdmsh"),
        "n_distinct_seeds": meta.get("n_distinct_seeds"),
        "reuse_factor": meta.get("reuse_factor"),
        "built_models": meta.get("built_models") or [],
        "last_setup": meta.get("last_setup"), "last_max": meta.get("last_max"),
    }


def delete_canon(exp: dict, chart: dict) -> bool:
    """Delete a chart's canon map (the JSONL store + its meta sidecar) — frees disk and
    forces a full rebuild next time (rather than the usual incremental extend). CanonStore
    has no delete of its own; its files are plain paths, so this just unlinks them."""
    import os
    store = _canon_store(exp, chart)
    existed = os.path.exists(store.path)
    for p in (store.path, store.meta_path):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    return existed


def precompute_runner(exp: dict, chart: dict, models: dict, workers: int = 1):
    """Build a ``runner(progress_cb) -> stats`` closure for a background ProgressSession.

    ``workers`` defaults to 1 (no process pool) — a process pool forked from inside a
    pywebview app's own process is untested territory here; raise it once that's verified safe.
    """
    from claytonlib.chart import precompute_canon

    if not models:
        raise ValueError(
            "no calibration model available — build one from Metronome Compass → Review "
            "Data → Calibrate Model first")

    bridged = _bridge(exp, chart)
    pokemon = safari_pokemon_by_name(exp["pokemon"])
    strategy = _resolve_strategy(chart["strategy_name"])
    criteria = _resolve_criteria(chart["criteria_name"])
    store = _canon_store(exp, chart)
    base_delay, times = get_times(exp["key_seed"])
    folded = {k: m.with_safari_offset() for k, m in models.items()}

    def runner(progress_cb):
        def _progress(done, total, stats):
            progress_cb(done=done, total=total, n_distinct_seeds=stats.get("n_distinct_seeds"))
        return precompute_canon(
            base_delay, times, bridged.setup_delay_seconds, bridged.max_target_seconds,
            pokemon, strategy, criteria, store, folded, progress=_progress, workers=workers)

    return runner


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _row_json(r: dict, initial_time: dt.datetime | None = None) -> dict:
    from claytonlib.safari_encounters import time_of_day
    it = r.get("initial_time", initial_time)
    return {
        "vector_ms": round(r["M"]), "target_delay": int(r["F"]),
        "second": int(r["second"]), "mdmsh": list(r["mdmsh"]),
        "p": r["p"], "sigma": r["sigma"],
        "initial_time": it.strftime(_TIME_FMT) if isinstance(it, dt.datetime) else it,
        # Tracked (not yet filtered on -- clayton-b42.7.1 defers the block-table-aware "which
        # ToDs actually carry this species" check to future work; every bucket counts as valid
        # for now) so a future pass has the data without re-deriving it.
        "tod": time_of_day(it) if isinstance(it, dt.datetime) else None,
    }


def rank_best_per_time(exp: dict, chart: dict, models: dict, params: dict) -> dict:
    """Mode A: the best target for each candidate boot time, collapsed to distinct scenarios.

    Uses a coarse step (default 4 frames) across the whole window for performance — scoring
    every candidate boot time at step=1 would be far more expensive than rank_at_time's
    single-boot-time search. That coarseness means a boot time's reported best frame can sit
    up to `step - 1` frames from ITS OWN true local peak, which rank_at_time's own step=1
    search on that same boot time can then appear to "beat" — a confusing inconsistency, not
    a real one.

    EVERY candidate boot time's own row is refined with a small step=1 local search
    (refine_near) BEFORE collapsing to distinct scenarios and cutting to the requested limit
    — refining only the already-cut top-K (an earlier version of this function did that) is
    not enough: the coarse sweep's ranking order isn't guaranteed to match the TRUE order, so
    a boot time whose coarse score placed it outside the top-K could still have the highest
    TRUE score and needs to be in contention before the cut, not after.
    """
    store = _canon_store(exp, chart)
    if store.read_meta() is None:
        raise ValueError("no canon map yet — run precompute first")
    cmap = store.load_map()
    model = _pick_model(models, params.get("fps_model", "linear"), params.get("use_safari_offset", True))
    base_delay, times = get_times(exp["key_seed"])
    setup, maxt = int(chart.get("setup_delay_seconds", 0)), int(chart.get("max_target_seconds", 300))
    step = int(params.get("step", 4))
    k = float(params.get("k", 3.5))
    include_calibration = bool(params.get("include_calibration", False))

    # keep_top_k tracks, per boot phase, the F values of the next-best few COARSE-sampled
    # points too -- not just the single winner. A coarse sweep can land its #1 pick nowhere
    # near a boot time's TRUE local peak (a real, reproduced issue: a jagged/narrow capture
    # landscape -- e.g. machete-based criteria, where nearby frames' outcomes are essentially
    # uncorrelated -- can put the true peak more than `step` frames from wherever the coarse
    # sweep's single best point happened to land, which a narrow single-point refine_near can
    # then never reach). Refining around EACH of the top-K coarse points instead of just #1
    # costs only a few extra cheap refine_near calls per phase (negligible next to the main
    # sweep), and catches far more real-world cases -- though it still can't mathematically
    # guarantee finding an arbitrarily narrow peak that happens to fall in the gap between
    # every one of the top-K coarse samples. See tests/test_scorer.py's
    # TestRankBestPerTimeRefinesBeforeCutting for the reproduced failure this widens against.
    per_time = rank_boot_marginal(
        cmap, model, times, base_delay, setup, maxt,
        step=step, k=k, include_calibration=include_calibration, keep_top_k=5)

    radius = max(step - 1, 0)
    if radius:
        refined_per_time = []
        for r in per_time:
            candidates = [r["F"]] + r.get("_coarse_alt_F", [])
            best_refined = None
            for F_c in candidates:
                better = refine_near(cmap, model, r["initial_time"], base_delay, F_c, radius,
                                     k=k, include_calibration=include_calibration)
                if better and (best_refined is None or better["p"] > best_refined["p"]):
                    best_refined = better
            if best_refined and best_refined["p"] > r["p"]:
                best_refined["initial_time"] = r["initial_time"]
                refined_per_time.append(best_refined)
            else:
                refined_per_time.append(r)
        # THE ACTUAL ROOT CAUSE of the "Ranked Targets misses a target that's clearly better"
        # bug reported across rounds 7/8/11 despite three earlier attempts at the coarse-sweep
        # angle: per_time entered this loop p-desc sorted (rank_boot_marginal's own sort), but
        # refining updates each row's `p` in place and the list was never re-sorted afterward.
        # best_per_scenario's own docstring requires p-desc input -- it just keeps the FIRST
        # row seen per (second, mdmsh) key via setdefault, trusting sort order to make that the
        # highest one. Fed the STALE (coarse-order) sort, it could just as easily keep a lower-p
        # row over a higher-p one that happened to have a worse COARSE score (and so sorted
        # later) but a better REFINED one -- silently discarding the true best for that
        # scenario. Confirmed directly against a real profile/chart/canon map: without this
        # re-sort, best_per_scenario's top-3 differed from the correctly-sorted version's.
        per_time = sorted(refined_per_time, key=lambda r: (-r["p"], r["M"]))

    overall = best_per_scenario(per_time)
    limit = int(params.get("limit", 10))
    top = overall[:limit]

    return {
        "top": [_row_json(r) for r in top],
        "per_time_count": len(per_time),
    }


def rank_at_time(exp: dict, chart: dict, models: dict, initial_time: str, params: dict) -> list[dict]:
    """Mode B: rank commanded countdowns for one fixed boot time.

    Adjacent target frames score almost identically (the landing kernel overlaps), so the raw
    top-N is mostly a single cluster around one peak, not meaningfully different alternatives —
    declusters by default (distinct_targets) to at least `min_separation` frames apart (~0.5s
    of real time by default) so what's returned are genuinely different options. Pass
    min_separation=0 to get the raw (possibly clustered) ranking instead.
    """
    store = _canon_store(exp, chart)
    if store.read_meta() is None:
        raise ValueError("no canon map yet — run precompute first")
    cmap = store.load_map()
    model = _pick_model(models, params.get("fps_model", "linear"), params.get("use_safari_offset", True))
    base_delay, _ = get_times(exp["key_seed"])
    setup, maxt = int(chart.get("setup_delay_seconds", 0)), int(chart.get("max_target_seconds", 300))
    it = _parse_time(initial_time)
    limit = int(params.get("limit", 10))
    min_separation = int(params.get("min_separation", 30))

    rows = rank_targets(
        cmap, model, it, base_delay, setup, maxt,
        step=int(params.get("step", 1)), k=float(params.get("k", 3.5)),
        include_calibration=bool(params.get("include_calibration", False)),
        limit=None if min_separation else limit)
    if min_separation:
        rows = distinct_targets(rows, min_separation, limit)
    return [_row_json(r, initial_time=it) for r in rows]


# ---------------------------------------------------------------------------
# Examine (the "Examine target" breakdown)
# ---------------------------------------------------------------------------

def examine(exp: dict, chart: dict, models: dict, initial_time: str, vector_ms: int, params: dict) -> dict:
    """The per-second landing breakdown behind one (initial_time, Vector ms) target."""
    store = _canon_store(exp, chart)
    if store.read_meta() is None:
        raise ValueError("no canon map yet — run precompute first")
    cmap = store.load_map()
    model = _pick_model(models, params.get("fps_model", "linear"), params.get("use_safari_offset", True))
    base_delay, _ = get_times(exp["key_seed"])
    it = _parse_time(initial_time)

    mc = marginal_capture(cmap, model, it, vector_ms, base_delay,
                          k=float(params.get("k", 3.5)),
                          include_calibration=bool(params.get("include_calibration", False)))
    if mc is None:
        raise ValueError("empty second distribution for this target")
    return {
        "p": mc["p"], "F": mc["F"], "sigma": mc["sigma"],
        "seconds": [
            {"second": b["second"], "p_second": b["p_second"], "mdmsh": list(b["mdmsh"]),
             "cp": b["cp"], "lo": b["lo"], "hi": b["hi"]}
            for b in mc["breakdown"]
        ],
    }


def examine_second(exp: dict, chart: dict, models: dict, initial_time: str, vector_ms: int,
                   second: int, params: dict) -> dict:
    """Individual (frame, seed) rows for ONE candidate RTC second of an examine() breakdown —
    the same per-seed detail the notebook's chart_check_target_landing() prints."""
    store = _canon_store(exp, chart)
    if store.read_meta() is None:
        raise ValueError("no canon map yet — run precompute first")
    cmap = store.load_map()
    model = _pick_model(models, params.get("fps_model", "linear"), params.get("use_safari_offset", True))
    base_delay, _ = get_times(exp["key_seed"])
    it = _parse_time(initial_time)

    result = seed_breakdown(cmap, model, it, vector_ms, base_delay, int(second),
                            k=float(params.get("k", 3.5)),
                            include_calibration=bool(params.get("include_calibration", False)))
    if result is None:
        raise ValueError("that second isn't part of this target's landing distribution")
    return {
        "second": result["second"], "p_second": result["p_second"], "cp": result["cp"],
        "mdmsh": list(result["mdmsh"]), "F": result["F"], "sigma": result["sigma"],
        "total_frames": result["total_frames"], "truncated": result["truncated"],
        "rows": [{"frame": r["frame"], "delta": r["delta"], "seed_hex": f"0x{r['seed']:08X}",
                  "hit": r["hit"], "weight_pct": r["weight_pct"],
                  "cum_capture_pct": r["cum_capture_pct"]} for r in result["rows"]],
    }
