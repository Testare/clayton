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
from claytonlib.chart.scorer import best_per_scenario, marginal_capture, rank_boot_marginal, rank_targets
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
    "survived-10-turns-without-fleeing": "Success = still on screen after 10 turns, not "
        "necessarily captured. Useful for calibration paths that need a long observation "
        "window rather than an actual catch.",
}


def _parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def list_strategies() -> list[dict]:
    from claytonlib.chart import STRATEGY_ONE_MUD, STRATEGY_ONLY_BALLS, STRATEGY_SIX_BAIT
    strategies = [STRATEGY_ONLY_BALLS, STRATEGY_ONE_MUD, STRATEGY_SIX_BAIT]
    return [{"name": s.name, "description": _STRATEGY_DESCRIPTIONS.get(s.name, "")} for s in strategies]


def list_criteria() -> list[dict]:
    from claytonlib.chart import CRITERIA_CAPTURE, CRITERIA_WONT_FLEE_10_TURNS
    criteria = [CRITERIA_CAPTURE, CRITERIA_WONT_FLEE_10_TURNS]
    return [{"name": c.name, "description": _CRITERIA_DESCRIPTIONS.get(c.name, "")} for c in criteria]


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
    it = r.get("initial_time", initial_time)
    return {
        "vector_ms": round(r["M"]), "target_delay": int(r["F"]),
        "second": int(r["second"]), "mdmsh": list(r["mdmsh"]),
        "p": r["p"], "sigma": r["sigma"],
        "initial_time": it.strftime(_TIME_FMT) if isinstance(it, dt.datetime) else it,
    }


def rank_best_per_time(exp: dict, chart: dict, models: dict, params: dict) -> dict:
    """Mode A: the best target for each candidate boot time, collapsed to distinct scenarios."""
    store = _canon_store(exp, chart)
    if store.read_meta() is None:
        raise ValueError("no canon map yet — run precompute first")
    cmap = store.load_map()
    model = _pick_model(models, params.get("fps_model", "linear"), params.get("use_safari_offset", True))
    base_delay, times = get_times(exp["key_seed"])
    setup, maxt = int(chart.get("setup_delay_seconds", 0)), int(chart.get("max_target_seconds", 300))

    per_time = rank_boot_marginal(
        cmap, model, times, base_delay, setup, maxt,
        step=int(params.get("step", 4)), k=float(params.get("k", 3.5)),
        include_calibration=bool(params.get("include_calibration", False)))
    overall = best_per_scenario(per_time)
    limit = int(params.get("limit", 10))
    return {
        "top": [_row_json(r) for r in overall[:limit]],
        "per_time_count": len(per_time),
    }


def rank_at_time(exp: dict, chart: dict, models: dict, initial_time: str, params: dict) -> list[dict]:
    """Mode B: rank commanded countdowns for one fixed boot time."""
    store = _canon_store(exp, chart)
    if store.read_meta() is None:
        raise ValueError("no canon map yet — run precompute first")
    cmap = store.load_map()
    model = _pick_model(models, params.get("fps_model", "linear"), params.get("use_safari_offset", True))
    base_delay, _ = get_times(exp["key_seed"])
    setup, maxt = int(chart.get("setup_delay_seconds", 0)), int(chart.get("max_target_seconds", 300))
    it = _parse_time(initial_time)

    rows = rank_targets(
        cmap, model, it, base_delay, setup, maxt,
        step=int(params.get("step", 1)), k=float(params.get("k", 3.5)),
        include_calibration=bool(params.get("include_calibration", False)),
        limit=int(params.get("limit", 10)))
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
