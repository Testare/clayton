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


def _advances(exp: dict) -> int:
    """The Seed A advance count a run on this expedition will make before Sweet Scent.

    Feeds the model's per-advance safari offset (None/unfit on a model => no effect at all).
    It is the expedition's configured key-seed advances because the chart's whole premise is
    the key-seed run: hit `key_seed` as Seed A, advance `key_seed_advances` times, Sweet Scent.
    """
    return int(exp.get("key_seed_advances") or 0)


def _pick_model(models: dict, fps_model: str, use_safari_offset: bool,
                advances: int = 0) -> "CalibrationModel":
    if not models:
        raise ValueError(
            "no calibration model available — build one from Metronome Compass → Review "
            "Data → Calibrate Model first")
    model = models.get(fps_model) or next(iter(models.values()))
    return model.with_safari_offset(advances) if use_safari_offset else model


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


def _human_bytes(n: int) -> str:
    """A size a person can read at a glance — "4.2 MB", not 4404019."""
    step = 1024.0
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < step or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" or size >= 100 else f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} GB"


def canon_disk_usage(exp: dict, chart: dict) -> dict:
    """Bytes on disk for this chart's computed data — the canon map, its meta sidecar, and the
    cached ranked report — plus a human-readable total (round 17 feedback)."""
    import os
    store = _canon_store(exp, chart)
    total = 0
    for p in (store.path, store.meta_path, _rank_report_path(exp, chart)):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return {"bytes": total, "human": _human_bytes(total)}


def canon_path(exp: dict, chart: dict) -> str:
    """Where this chart's canon map lives. Keyed by pokemon + key seed + strategy + criteria,
    NOT by chart id — several charts can share one map, which is what `reuse_factor` measures."""
    return _canon_store(exp, chart).path


def rank_report_path(exp: dict, chart: dict) -> str:
    """Where this chart's cached ranked report lives (one per expedition x chart)."""
    return _rank_report_path(exp, chart)


def canon_status(exp: dict, chart: dict) -> dict:
    """Whether a canon map exists for this chart, and its coverage, without building it."""
    meta = _canon_store(exp, chart).read_meta()
    usage = canon_disk_usage(exp, chart)
    if meta is None:
        return {"built": False, **usage}
    return {
        "built": True, "n_mdmsh": meta.get("n_mdmsh"),
        "n_distinct_seeds": meta.get("n_distinct_seeds"),
        "reuse_factor": meta.get("reuse_factor"),
        "built_models": meta.get("built_models") or [],
        "last_setup": meta.get("last_setup"), "last_max": meta.get("last_max"),
        **usage,
    }


def delete_canon(exp: dict, chart: dict) -> bool:
    """Delete a chart's canon map (the JSONL store + its meta sidecar) — frees disk and
    forces a full rebuild next time (rather than the usual incremental extend). CanonStore
    has no delete of its own; its files are plain paths, so this just unlinks them."""
    import os
    store = _canon_store(exp, chart)
    existed = os.path.exists(store.path)
    # Every cached ranked report is derived from this map, so they all go with it — including
    # reports belonging to OTHER expeditions that share this canon (see _rank_report_path).
    import glob
    reports = glob.glob(store.path + ".rank.*.json")
    for p in [store.path, store.meta_path, *reports]:
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    for p in reports:
        _RANK_MEMO.pop(p, None)
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
    # Same advance count the rankers will use — the canon is built over the FRAME RANGE the
    # folded models ask for, so a per-advance offset shifts which frames need covering. That
    # makes key_seed_advances a canon-invalidation trigger exactly like safari_offset is
    # (clayton-6h2.5): change it on a model that carries a per-advance term and the canon must
    # be extended before the chart is right again.
    folded = {k: m.with_safari_offset(_advances(exp)) for k, m in models.items()}

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


# ---------------------------------------------------------------------------
# Ranked-target report cache (on disk)
# ---------------------------------------------------------------------------
# rank_best_per_time sweeps every candidate boot time (2,464 of them for a real key seed) and
# takes ~35 s against a real canon map, every single time it's clicked (round 17 feedback).
# The answer only changes when one of its actual inputs does, so the finished report is written
# next to the chart's canon map -- on DISK, not just in memory, since an app restart is exactly
# when re-waiting 35 s hurts most.
#
# The cache key covers everything that feeds the result: the expedition's key seed and advance
# count, the chart's strategy/criteria/window, the FOLDED calibration model's own fields (which
# is stricter than a model id -- it also catches a model edited in place), the sweep parameters,
# and the canon map's coverage (so an incremental precompute invalidates it). `limit` is
# deliberately NOT in the key: the full ranked list is stored and sliced per request, so asking
# for more or fewer rows is instant.
#
# Rows are stored already JSON-shaped (_row_json), so no datetime round-tripping is needed and
# a hit is a plain file read.
_RANK_MEMO: dict = {}        # in-process front cache over the files, same keys
_RANK_MEMO_MAX = 8


def clear_rank_cache() -> None:
    """Drop the in-process memo. On-disk reports stay (their keys make them self-invalidating);
    delete_canon removes a chart's report file along with its map."""
    _RANK_MEMO.clear()


def _rank_report_path(exp: dict, chart: dict) -> str:
    """Sibling of the chart's canon map, so the two live and die together.

    Scoped by EXPEDITION *and* CHART id, because the canon path is neither. A canon map is
    deliberately shared by everything with the same pokemon + key seed + strategy + criteria
    (that sharing is the whole point of `reuse_factor`, and its signature omits setup/max so the
    range can be extended in place) — but a ranked report additionally depends on the
    expedition's key_seed_advances and on the chart's own window, so two things sharing a map do
    NOT share a report. Without both ids in the name they would write to one file and invalidate
    each other on every rank: still correct, since the stored key is checked, but they would take
    turns waiting 35 s. A file each costs a couple of KB.

    What one file holds is exactly one configuration. Re-ranking the same expedition+chart with
    a different active calibration model overwrites it, so flipping between two models pays the
    full sweep each time — the case that's worth the disk, a stable model, is the common one.
    """
    return f"{_canon_store(exp, chart).path}.rank.{exp.get('id', 'anon')}.{chart.get('id', 'anon')}.json"


def _rank_cache_key(exp: dict, chart: dict, model, params: dict, meta: dict | None) -> list:
    meta = meta or {}
    return [
        exp.get("key_seed"), _advances(exp),
        chart.get("strategy_name"), chart.get("criteria_name"),
        int(chart.get("setup_delay_seconds", 0)), int(chart.get("max_target_seconds", 300)),
        model.to_dict(),
        int(params.get("step", 4)), float(params.get("k", 3.5)),
        bool(params.get("include_calibration", False)),
        meta.get("n_distinct_seeds"), meta.get("n_mdmsh"),
        meta.get("last_setup"), meta.get("last_max"),
    ]


def _rank_cache_read(path: str, key: list):
    """The cached (rows, per_time_count) for `key`, or None if absent/stale/unreadable.

    A corrupt or half-written report must never break ranking -- it just means a recompute,
    so every failure mode here is swallowed deliberately.
    """
    import json
    memo = _RANK_MEMO.get(path)
    if memo is not None and memo[0] == key:
        return memo[1], memo[2]
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    # json turns tuples into lists; the key is built as a list for exactly that reason.
    if doc.get("key") != json.loads(json.dumps(key)):
        return None
    rows, n = doc.get("rows") or [], doc.get("per_time_count", 0)
    _rank_memo_put(path, key, rows, n)
    return rows, n


def _rank_memo_put(path: str, key: list, rows: list, n: int) -> None:
    _RANK_MEMO[path] = (key, rows, n)
    while len(_RANK_MEMO) > _RANK_MEMO_MAX:      # evict oldest (insertion-ordered dict)
        _RANK_MEMO.pop(next(iter(_RANK_MEMO)))


def _rank_cache_write(path: str, key: list, rows: list, n: int) -> None:
    """Write the report atomically (temp file + replace) so a crash mid-write can't leave a
    truncated report that later reads as valid-but-wrong."""
    import json, os
    _rank_memo_put(path, key, rows, n)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w") as f:
            json.dump({"key": key, "per_time_count": n, "rows": rows}, f)
        os.replace(tmp, path)
    except OSError:
        # A read-only or full disk shouldn't fail the ranking the user asked for.
        try:
            os.remove(tmp)
        except OSError:
            pass


def rank_cached_only(exp: dict, chart: dict, models: dict, params: dict) -> dict | None:
    """The cached ranking if one is valid, else None — without loading the canon map.

    Lets a caller serve an instant answer on the common path and only pay for a background,
    progress-reporting run when there's real work to do (clayton-6n6.2).
    """
    store = _canon_store(exp, chart)
    meta = store.read_meta()
    if meta is None:
        return None
    model = _pick_model(models, params.get("fps_model", "linear"),
                        params.get("use_safari_offset", True), _advances(exp))
    cached = _rank_cache_read(_rank_report_path(exp, chart),
                             _rank_cache_key(exp, chart, model, params, meta))
    if cached is None:
        return None
    rows, per_time_count = cached
    return {"top": rows[:int(params.get("limit", 10))],
            "per_time_count": per_time_count, "cached": True}


def rank_best_per_time(exp: dict, chart: dict, models: dict, params: dict, progress=None) -> dict:
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
    meta = store.read_meta()
    if meta is None:
        raise ValueError("no canon map yet — run precompute first")
    model = _pick_model(models, params.get("fps_model", "linear"),
                        params.get("use_safari_offset", True), _advances(exp))

    limit = int(params.get("limit", 10))
    report_path = _rank_report_path(exp, chart)
    cache_key = _rank_cache_key(exp, chart, model, params, meta)
    cached = _rank_cache_read(report_path, cache_key)
    if cached is not None:
        rows, per_time_count = cached
        return {"top": rows[:limit], "per_time_count": per_time_count, "cached": True}

    cmap = store.load_map()
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
        step=step, k=k, include_calibration=include_calibration, keep_top_k=5,
        progress=(lambda d, t: progress(phase="scan", done=d, total=t)) if progress else None)

    radius = max(step - 1, 0)
    if radius:
        refined_per_time = []
        # The refine loop, not the sweep above, is where the time actually goes: measured on a
        # real chart it is 36.7 s of a 38.0 s rank (96.7%), against 1.25 s for the sweep. So
        # this is the loop a progress bar has to track -- driving one off the sweep would sit
        # at 0% for a second and then at 100% for another 37.
        for _i, r in enumerate(per_time):
            if progress is not None and _i % 32 == 0:
                progress(phase="refine", done=_i, total=len(per_time))
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

    if progress is not None:
        progress(phase="refine", done=len(per_time), total=len(per_time))
    overall = best_per_scenario(per_time)
    rows = [_row_json(r) for r in overall]
    _rank_cache_write(report_path, cache_key, rows, len(per_time))

    return {"top": rows[:limit], "per_time_count": len(per_time), "cached": False}


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
    model = _pick_model(models, params.get("fps_model", "linear"),
                        params.get("use_safari_offset", True), _advances(exp))
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
    model = _pick_model(models, params.get("fps_model", "linear"),
                        params.get("use_safari_offset", True), _advances(exp))
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
    model = _pick_model(models, params.get("fps_model", "linear"),
                        params.get("use_safari_offset", True), _advances(exp))
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
