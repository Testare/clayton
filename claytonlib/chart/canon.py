"""
canon.py — Canonical mdmsh-keyed capture map (the chart's compute-reuse layer).

capture is a pure function of the chart seed = (mdms<<24 | hour<<16) + frame, so the whole
capture landscape depends only on ``mdmsh = (mdms, hour)`` and the frame — NOT on which of
the many RNG-equivalent candidate datetimes you picked (key_seed fixes the hour and pins
mdms; on the real metang config all 2858 candidate times collapse to ~a few distinct seeds
per frame).  So instead of a grid per datetime, we build ONE map:

    capture[mdmsh] -> {frame-range bitmasks}

evaluating each distinct (mdmsh, frame) seed exactly once (with a persistent seed cache),
then the scorer resolves a candidate M -> datetime -> (mdmsh, center frame) and looks the
map up over [center +/- k*sigma(M)].  See notes/refined_chart.md section 6.6.

Phase 1 (this module): enumerate the needed (mdmsh, frame) set and evaluate it.
Phase 2 (scoring, later): read this map under the sigma(M) landing kernel.
"""
import datetime as _dt
import json
import math
import os
from dataclasses import dataclass

from claytonlib.chart.grid import BandPolicy, get_bit, pack_row


# ---------------------------------------------------------------------------
# mdmsh helpers
# ---------------------------------------------------------------------------

def mdmsh_of(t: _dt.datetime) -> tuple[int, int]:
    """The (mdms, hour) class of a datetime: mdms = (month*day + minute + second) & 0xFF."""
    return ((t.month * t.day + t.minute + t.second) & 0xFF, t.hour)


def seed_for_mdmsh(mdmsh: tuple[int, int], frame: int) -> int:
    """The chart seed for an (mdmsh, frame) — identical to times.calculate_seed(t, frame)
    for any datetime t with that mdms/hour (year-2000 model, no year term)."""
    mdms, hour = mdmsh
    return ((mdms << 24) | (hour << 16)) + frame


def _parse(t) -> _dt.datetime:
    return t if isinstance(t, _dt.datetime) else _dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S")


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort and merge overlapping/adjacent [lo, hi] intervals."""
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(intervals):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def _subtract_intervals(needed: list[tuple[int, int]],
                        done: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The parts of `needed` not already covered by `done` (both lists of inclusive [lo,hi]).

    This is what makes precompute incremental: only the gaps beyond what's already stored are
    evaluated, so extending a range never re-evaluates frames already computed.
    """
    done = _merge_intervals(done)
    out: list[tuple[int, int]] = []
    for lo, hi in needed:
        cur = lo
        for dlo, dhi in done:
            if dhi < cur or dlo > hi:
                continue
            if dlo > cur:
                out.append((cur, min(dlo - 1, hi)))
            cur = max(cur, dhi + 1)
            if cur > hi:
                break
        if cur <= hi:
            out.append((cur, hi))
    return out


# ---------------------------------------------------------------------------
# Phase 1a — enumerate the needed (mdmsh, frame) set (no evaluation)
# ---------------------------------------------------------------------------

def needed_ranges(base_delay: int, times, setup_delay_seconds: int, max_target_seconds: int,
                  model, policy: BandPolicy = BandPolicy()) -> tuple[dict, dict]:
    """Which (mdmsh, frame) seeds the chart needs, as merged frame ranges per mdmsh.

    For each candidate time t and RTC second s in [setup, max_target], the datetime t+s has
    some mdmsh, and the battle frame for the commanded M that lands on second s is placed by
    the CALIBRATION: M(s) ≈ (s − rtc_offset_seconds)·1000 (real time), frame ≈ model.mean(M(s)).
    The band per second spans that second's M-range (±0.5 s of M) widened by `policy`, so it
    covers the jitter.  Crucially the second s (which sets mdmsh) is REAL time, not the frame's
    physical delay band -- deriving the second from the frame is what mis-placed the mdms.

    Candidate times are first deduped by their (month,day,hour,minute,second) phase (year is
    irrelevant in the chart model), so year-equivalent times aren't re-walked.

    Returns (ranges, stats) where ranges maps mdmsh -> merged [(lo, hi), ...] and stats
    reports the collapse (distinct seeds vs the naive per-time grid).
    """
    # dedup by phase (year dropped): identical (month,day,hour,minute,second) -> identical
    # mdmsh(t+s) for every s.
    phases = list({(t.month, t.day, t.hour, t.minute, t.second): t
                   for t in (_parse(x) for x in times)}.values())

    # Per-second frame band = [mean(M at s−0.5s) − W, mean(M at s+0.5s) + W]; M-based, so it's
    # shared across all times.  W absorbs the sigma jitter (policy); the M-range covers the
    # ~1 s worth of commanded values that round to this RTC second.
    seconds = range(setup_delay_seconds, max_target_seconds + 1)
    bands = []
    for s in seconds:
        m_lo = max(0.0, (s - 0.5 - model.rtc_offset_seconds) * 1000.0)
        m_hi = max(0.0, (s + 0.5 - model.rtc_offset_seconds) * 1000.0)
        f_lo = model.mean(m_lo)
        f_hi = model.mean(m_hi)
        w = policy.half_width((f_lo + f_hi) / 2.0)
        bands.append((int(math.floor(min(f_lo, f_hi) - w)), int(math.ceil(max(f_lo, f_hi) + w))))

    per: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for tt in phases:
        for s_idx, s in enumerate(seconds):
            lo, hi = bands[s_idx]
            key = mdmsh_of(tt + _dt.timedelta(seconds=s))
            per.setdefault(key, []).append((lo, hi))

    ranges = {k: _merge_intervals(v) for k, v in per.items()}
    n_seeds = sum(hi - lo + 1 for rs in ranges.values() for lo, hi in rs)
    naive = len(list(times)) * sum(hi - lo + 1 for lo, hi in bands)
    stats = {
        "n_candidate_times": len(list(times)),
        "n_phase_classes": len(phases),
        "n_mdmsh": len(ranges),
        "n_distinct_seeds": n_seeds,
        "naive_seed_evaluations": naive,
        "reuse_factor": (naive / n_seeds) if n_seeds else 0.0,
    }
    return ranges, stats


# ---------------------------------------------------------------------------
# Persistent seed cache (capture is deterministic per seed + criteria)
# ---------------------------------------------------------------------------

class SeedCache:
    """seed -> bool memo, optionally persisted to JSON so reuse survives runs/expeditions.

    A cache is specific to one (pokemon, strategy, criteria); persist different signatures to
    different paths.  Load once, evaluate misses, save at the end.
    """

    def __init__(self, path: str | None = None):
        self.path = path
        self.data: dict[int, bool] = {}
        self.hits = 0
        self.misses = 0
        if path and os.path.exists(path):
            with open(path) as f:
                self.data = {int(k): bool(v) for k, v in json.load(f).items()}

    def get_or_eval(self, seed: int, fn) -> bool:
        v = self.data.get(seed)
        if v is None:
            v = bool(fn(seed))
            self.data[seed] = v
            self.misses += 1
        else:
            self.hits += 1
        return v

    def save(self) -> None:
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({str(k): int(v) for k, v in self.data.items()}, f)


# ---------------------------------------------------------------------------
# Phase 1b — evaluate into the canonical map
# ---------------------------------------------------------------------------

@dataclass
class CanonMap:
    """capture[mdmsh] -> list of (lo, hi, bitmask) frame ranges (bit i = capture at lo+i)."""
    ranges: dict  # tuple[int,int] -> list[tuple[int, int, bytes]]

    def captured(self, mdmsh: tuple[int, int], frame: int) -> bool:
        for lo, hi, bm in self.ranges.get(mdmsh, ()):
            if lo <= frame <= hi:
                return get_bit(bm, frame - lo)
        return False

    def save(self, path: str) -> None:
        """Write the map as JSONL, one line per (mdmsh, frame-range)."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            for mdmsh, built in self.ranges.items():
                for lo, hi, bm in built:
                    f.write(json.dumps(_range_to_json(mdmsh, lo, hi, bm)) + "\n")

    @classmethod
    def load(cls, path: str) -> "CanonMap":
        """Read a per-range JSONL, grouping ranges under their mdmsh (in first-seen order)."""
        ranges: dict = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    mdmsh, lo, hi, bm = _range_from_json(json.loads(line))
                    ranges.setdefault(mdmsh, []).append((lo, hi, bm))
        return cls(ranges)


# ---------------------------------------------------------------------------
# JSONL (de)serialization of one (mdmsh, frame-range)
# ---------------------------------------------------------------------------

def _range_to_json(mdmsh: tuple[int, int], lo: int, hi: int, bm: bytes) -> dict:
    mdms, hour = mdmsh
    return {"m": mdms, "h": hour, "lo": lo, "hi": hi, "b": bm.hex()}


def _range_from_json(d: dict) -> tuple[tuple[int, int], int, int, bytes]:
    return (d["m"], d["h"]), d["lo"], d["hi"], bytes.fromhex(d["b"])


# ---------------------------------------------------------------------------
# Persistent, resumable offline precompute
# ---------------------------------------------------------------------------

class CanonStore:
    """A resumable, EXTENDABLE on-disk canonical map: append-one-JSONL-line-per-(mdmsh,range)
    + a meta sidecar.

    Each frame-range is written atomically as one line, so an interrupted precompute resumes
    by re-computing only the frame gaps not already stored (done_coverage()); a crash costs at
    most the one range in progress.  Because the map is keyed by (mdmsh, frame) — inherently
    range-agnostic — a later precompute over a WIDER second range just appends the new gaps on
    top of an existing store (no re-evaluation).  The meta's config signature deliberately
    omits setup/max so extending the range is allowed; changing pokemon/strategy/criteria/
    base_delay/policy is not.
    """

    def __init__(self, path: str):
        self.path = path

    @property
    def meta_path(self) -> str:
        return self.path + ".meta.json"

    def _iter_lines(self):
        if os.path.exists(self.path):
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        yield json.loads(line)

    def done_coverage(self) -> dict:
        """{mdmsh: merged [(lo, hi), ...]} of the frames already stored."""
        cov: dict = {}
        for d in self._iter_lines():
            cov.setdefault((d["m"], d["h"]), []).append((d["lo"], d["hi"]))
        return {k: _merge_intervals(v) for k, v in cov.items()}

    def done_mdmsh(self) -> set:
        return {(d["m"], d["h"]) for d in self._iter_lines()}

    def append_range(self, mdmsh: tuple[int, int], lo: int, hi: int, bm: bytes) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(_range_to_json(mdmsh, lo, hi, bm)) + "\n")

    def read_meta(self) -> dict | None:
        if not os.path.exists(self.meta_path):
            return None
        with open(self.meta_path) as f:
            return json.load(f)

    def write_meta(self, meta: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    def load_map(self) -> CanonMap:
        return CanonMap.load(self.path) if os.path.exists(self.path) else CanonMap({})


def _config_signature(pokemon, strategy, criteria, base_delay, policy, model) -> dict:
    # Deliberately excludes setup/max/n_times: the map is keyed by (mdmsh, frame) and is
    # range-agnostic, so a store can be extended to a wider second range in place.  The
    # calibration DOES enter the signature: it places each RTC second's frame band (mean) and
    # sets the second-from-M mapping (rtc_offset_seconds), so a different fit needs a fresh map.
    return {
        "pokemon": getattr(pokemon, "name", str(pokemon)),
        "strategy": getattr(strategy, "name", str(strategy)),
        "criteria": getattr(criteria, "name", str(criteria)),
        "base_delay": base_delay,
        "policy": [policy.k, policy.c_ceiling, policy.nominal_rate],
        "second_model": "M-based",
        "calibration": _model_sig(model),
    }


def _model_sig(model) -> dict:
    """The calibration parameters that affect which (mdmsh, frame) seeds the chart needs."""
    return {
        "kind": model.kind,
        "beta": round(model.beta, 9), "alpha": round(model.alpha, 6),
        "coeffs": [round(c, 9) for c in model.coeffs],
        "m_center": model.m_center, "m_scale": model.m_scale,
        "rtc_offset_seconds": model.rtc_offset_seconds,
    }


# Set in the parent just before forking a worker pool; workers read it from inherited memory
# so the (often unpicklable) strategy/criteria closures never have to be pickled.
_WORKER_CTX = None


def _worker_eval(seed):
    from claytonlib.chart import evaluate_seed
    pokemon, strategy, criteria = _WORKER_CTX
    return evaluate_seed(seed, pokemon, strategy, criteria)


def precompute_canon(base_delay: int, times, setup_delay_seconds: int, max_target_seconds: int,
                     pokemon, strategy, criteria, store: CanonStore, model,
                     policy: BandPolicy = BandPolicy(), progress=None, workers: int = 1) -> dict:
    """Evaluate the canonical map to `store`, resumably and INCREMENTALLY.

    Computes the (mdmsh, frame) ranges needed for [setup, max], subtracts what the store
    already covers per mdmsh, and evaluates only the gaps — so resuming an interrupted run OR
    extending to a wider second range both cost only the un-computed frames.  Refuses to
    resume a store built for a different config (setup/max are NOT part of the signature).

    `workers` > 1 evaluates each range's seeds across a fork-based process pool (evaluate_seed
    is CPU-bound and GIL-blocked, so processes — not threads — give the speedup; near-linear
    in cores since each seed is independent).  Results are still appended per range in order,
    so resumability/idempotency are unchanged.  Returns needed_ranges stats plus
    `evaluated_this_run` (gap frames actually evaluated).
    """
    from claytonlib.chart import evaluate_seed  # lazy: avoid an import cycle

    ranges, stats = needed_ranges(base_delay, times, setup_delay_seconds,
                                  max_target_seconds, model, policy)
    sig = _config_signature(pokemon, strategy, criteria, base_delay, policy, model)
    meta = store.read_meta()
    if meta is not None and meta.get("signature") != sig:
        raise ValueError("CanonStore was built for a different config; refusing to resume "
                         "(use a fresh path or delete the existing store)")

    pool = None
    if workers and workers > 1:
        import multiprocessing as mp
        global _WORKER_CTX
        _WORKER_CTX = (pokemon, strategy, criteria)
        pool = mp.get_context("fork").Pool(workers)

    def _eval_range(lo, hi):
        seeds = [seed_for_mdmsh(mdmsh, frame) for frame in range(lo, hi + 1)]
        if pool is not None:
            caps = pool.map(_worker_eval, seeds, chunksize=64)
        else:
            caps = [evaluate_seed(s, pokemon, strategy, criteria) for s in seeds]
        return [i for i, c in enumerate(caps) if c]

    coverage = store.done_coverage()
    ordered = sorted(ranges)  # deterministic order so resume is well-defined
    total = len(ordered)
    evaluated = 0
    try:
        for i, mdmsh in enumerate(ordered):
            for lo, hi in _subtract_intervals(ranges[mdmsh], coverage.get(mdmsh, [])):
                store.append_range(mdmsh, lo, hi, pack_row(hi - lo + 1, _eval_range(lo, hi)))
                evaluated += hi - lo + 1
            if progress is not None:
                progress(i + 1, total, stats)
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    stats = dict(stats, evaluated_this_run=evaluated)
    store.write_meta({"signature": sig, "n_mdmsh": total,
                      "n_distinct_seeds": stats["n_distinct_seeds"],
                      "reuse_factor": stats["reuse_factor"],
                      "last_setup": setup_delay_seconds, "last_max": max_target_seconds})
    return stats


def build_canon(ranges: dict, pokemon, strategy, criteria, cache: SeedCache | None = None,
                progress=None) -> tuple[CanonMap, SeedCache]:
    """Evaluate capture over every (mdmsh, frame) in `ranges`, once per distinct seed.

    Returns (CanonMap, cache).  The cache dedups repeated seeds (the same seed can appear in
    several mdmsh's ranges) and, if persistent, across runs.
    """
    from claytonlib.chart import evaluate_seed  # lazy: avoid an import cycle
    cache = cache or SeedCache()
    fn = lambda seed: evaluate_seed(seed, pokemon, strategy, criteria)

    out: dict = {}
    done = 0
    total = len(ranges)
    for mdmsh, rs in ranges.items():
        built = []
        for lo, hi in rs:
            set_bits = [frame - lo for frame in range(lo, hi + 1)
                        if cache.get_or_eval(seed_for_mdmsh(mdmsh, frame), fn)]
            built.append((lo, hi, pack_row(hi - lo + 1, set_bits)))
        out[mdmsh] = built
        done += 1
        if progress is not None:
            progress(done, total, cache)
    return CanonMap(out), cache
