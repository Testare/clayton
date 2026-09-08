"""
scorer.py — Phase 2: rank commanded countdowns against the canonical capture map.

For a boot datetime and a commanded countdown M, the RTC second at battle is ~fixed by M
(stable crystal) while the frame counter spreads by sigma(M) (calibration jitter).  So we
resolve M -> mean frame F* -> its RTC second -> mdmsh, then integrate the CanonMap's capture
bits at that mdmsh against the sigma(M) landing kernel — the landing-weighted capture
probability.  Ranking these over candidate target frames gives the best countdowns to dial.

Because sigma grows with M, this automatically prefers a wide contiguous capture region over
a lone spike far out (the kernel is wider there), and reports honestly lower probabilities
for long countdowns.  See notes/refined_chart.md sections 2-3, 6.6.
"""
import bisect
import datetime as _dt
import math

from claytonlib.chart.canon import mdmsh_of
from claytonlib.chart.evaluation import frames_in_second


def _centers(base_delay: int, upto_second: int) -> list[int]:
    """centers[s] = delay_at_second(base_delay, s) for s in 0..upto_second (built in O(n))."""
    centers = [base_delay]
    for s in range(upto_second):
        centers.append(centers[-1] + frames_in_second(s))
    return centers


def capture_probability(canon_map, model, mdmsh, M, k: float = 3.5,
                        include_calibration: bool = False) -> dict:
    """Landing-weighted capture probability at commanded countdown M for a fixed mdmsh.

    Integrates the CanonMap's capture bits at `mdmsh` against a Gaussian centered at
    mean(M) with sd sigma(M) (physical jitter; + the reducible band if include_calibration),
    truncated at k sigma and renormalized.  Returns {p, F, sigma, lo, hi, M}.
    """
    F = model.mean(M)
    sigma = (model.total_sigma(M, include_calibration=True) if include_calibration
             else model.jitter_sigma(M))
    sigma = max(sigma, 1e-9)
    lo = int(math.floor(F - k * sigma))
    hi = int(math.ceil(F + k * sigma))
    two_s2 = 2.0 * sigma * sigma
    num = den = 0.0
    for frame in range(lo, hi + 1):
        w = math.exp(-((frame - F) ** 2) / two_s2)
        den += w
        if canon_map.captured(mdmsh, frame):
            num += w
    return {"p": (num / den if den > 0 else 0.0), "F": F, "sigma": sigma,
            "lo": lo, "hi": hi, "M": M}


def rank_targets(canon_map, model, initial_time: _dt.datetime, base_delay: int,
                 setup_delay_seconds: int, max_target_seconds: int, step: int = 1,
                 k: float = 3.5, include_calibration: bool = False,
                 limit: int | None = None) -> list[dict]:
    """Rank candidate target frames (each with the M that centers on it) by capture prob.

    For each target frame F across the charted range, M = model.solve(F) is the countdown to
    center there; the frame's RTC second fixes the mdmsh (from initial_time), and the score is
    capture_probability at that mdmsh.  Returns dicts {M, F, second, mdmsh, p, sigma} sorted
    by p desc (ties by smaller M).  `step` is the frame granularity of the sweep.
    """
    centers = _centers(base_delay, max_target_seconds)
    f_lo, f_hi = centers[setup_delay_seconds], centers[max_target_seconds]
    results = []
    for F_target in range(f_lo, f_hi + 1, step):
        M = model.solve(F_target)
        if M <= 0:
            continue
        s = bisect.bisect_right(centers, F_target) - 1
        if s < setup_delay_seconds or s > max_target_seconds:
            continue
        mdmsh = mdmsh_of(initial_time + _dt.timedelta(seconds=s))
        cp = capture_probability(canon_map, model, mdmsh, M, k, include_calibration)
        results.append({"M": M, "F": F_target, "second": s, "mdmsh": mdmsh,
                        "p": cp["p"], "sigma": cp["sigma"]})
    results.sort(key=lambda r: (-r["p"], r["M"]))
    return results[:limit] if limit else results


def distinct_targets(ranked: list[dict], min_separation: int, n: int) -> list[dict]:
    """Top-n results that are each >= min_separation frames apart (greedy by score).

    Adjacent target frames score almost identically (overlapping kernels); this collapses a
    cluster to its best representative so the report shows genuinely different targets.
    """
    picked: list[dict] = []
    for r in ranked:  # already sorted by p desc
        if all(abs(r["F"] - q["F"]) >= min_separation for q in picked):
            picked.append(r)
            if len(picked) >= n:
                break
    return picked


def print_target_report(canon_map, model, initial_time, base_delay, setup_delay_seconds,
                        max_target_seconds, step: int = 1, k: float = 3.5,
                        include_calibration: bool = False, top: int = 10) -> list[dict]:
    """Rank targets and print the best distinct commanded countdowns.  Returns the rows."""
    ranked = rank_targets(canon_map, model, initial_time, base_delay, setup_delay_seconds,
                          max_target_seconds, step=step, k=k,
                          include_calibration=include_calibration)
    # separate distinct targets by ~1 sigma at the median M so the list isn't one cluster
    med_sigma = ranked[len(ranked) // 2]["sigma"] if ranked else 1.0
    best = distinct_targets(ranked, max(1, int(med_sigma)), top)
    band = "jitter+calib" if include_calibration else "jitter"
    print(f"Best commanded countdowns (boot {initial_time:%Y-%m-%d %H:%M:%S}, "
          f"{band} kernel, k={k}):")
    print(f"  {'#':>2}  {'M (ms)':>9}  {'target F_b':>10}  {'second':>6}  "
          f"{'P(capture)':>10}  {'sigma':>6}")
    for i, r in enumerate(best, 1):
        print(f"  {i:>2}  {r['M']:>9.0f}  {r['F']:>10}  {r['second']:>6}  "
              f"{r['p'] * 100:>9.1f}%  {r['sigma']:>6.1f}")
    return best
