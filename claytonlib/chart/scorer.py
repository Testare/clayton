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


def _frame_bounds(model, setup_delay_seconds: int, max_target_seconds: int) -> tuple[int, int]:
    """The battle-frame range spanning target RTC seconds [setup, max] via the calibration.

    A target RTC second s corresponds to a commanded M ≈ (s − rtc_offset_seconds)·1000 (real time),
    whose battle frame is model.mean(M).  So the frame sweep runs between the frames for the
    two endpoint seconds -- NOT the physical delay_at_second table (that frame↔second lockstep
    is exactly the conflation this model removes)."""
    m_lo = (setup_delay_seconds - model.rtc_offset_seconds) * 1000.0
    m_hi = (max_target_seconds - model.rtc_offset_seconds) * 1000.0
    f_lo = int(math.floor(model.mean(max(0.0, m_lo))))
    f_hi = int(math.ceil(model.mean(m_hi)))
    return (f_lo, f_hi) if f_lo <= f_hi else (f_hi, f_lo)


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
    f_lo, f_hi = _frame_bounds(model, setup_delay_seconds, max_target_seconds)
    results = []
    for F_target in range(f_lo, f_hi + 1, step):
        M = model.solve(F_target)
        if M <= 0:
            continue
        # RTC second from REAL time (M), not the frame -- see model.battle_second_offset.
        s = model.battle_second_offset(M)
        if s < setup_delay_seconds or s > max_target_seconds:
            continue
        mdmsh = mdmsh_of(initial_time + _dt.timedelta(seconds=s))
        cp = capture_probability(canon_map, model, mdmsh, M, k, include_calibration)
        results.append({"M": M, "F": F_target, "second": s, "mdmsh": mdmsh,
                        "p": cp["p"], "sigma": cp["sigma"]})
    results.sort(key=lambda r: (-r["p"], r["M"]))
    return results[:limit] if limit else results


def rank_over_times(canon_map, model, times, base_delay: int, setup_delay_seconds: int,
                    max_target_seconds: int, step: int = 1, k: float = 3.5,
                    include_calibration: bool = False, limit: int | None = None) -> list[dict]:
    """Rank the best (boot time, commanded countdown) pairs across ALL candidate boot times.

    Since capture at a target depends only on the target second's mdmsh — which collapses to a
    few values across the (RNG-equivalent) candidate boot times — we score each distinct
    (target frame, mdmsh) once and attach one example boot datetime realizing that mdmsh.
    Returns dicts {M, F, second, mdmsh, initial_time (example), p, sigma} sorted by p desc.
    Use when initial_time is an *output* (mode A); rank_targets is the fixed-time mode (B).
    """
    parsed = [t if isinstance(t, _dt.datetime) else _dt.datetime.fromisoformat(t) for t in times]
    # dedup identical (month,day,hour,minute,second) phases (year is irrelevant here)
    phases = list({(t.month, t.day, t.hour, t.minute, t.second): t for t in parsed}.values())

    # per second: {mdmsh -> one example boot datetime that yields it at that second}
    groups: dict[int, dict] = {}
    for s in range(setup_delay_seconds, max_target_seconds + 1):
        g: dict = {}
        for t in phases:
            m = mdmsh_of(t + _dt.timedelta(seconds=s))
            g.setdefault(m, t)
        groups[s] = g

    f_lo, f_hi = _frame_bounds(model, setup_delay_seconds, max_target_seconds)
    results = []
    for F_target in range(f_lo, f_hi + 1, step):
        M = model.solve(F_target)
        if M <= 0:
            continue
        # RTC second from REAL time (M), not the frame -- see model.battle_second_offset.
        s = model.battle_second_offset(M)
        if s < setup_delay_seconds or s > max_target_seconds:
            continue
        for mdmsh, example in groups[s].items():
            cp = capture_probability(canon_map, model, mdmsh, M, k, include_calibration)
            results.append({"M": M, "F": F_target, "second": s, "mdmsh": mdmsh,
                            "initial_time": example, "p": cp["p"], "sigma": cp["sigma"]})
    results.sort(key=lambda r: (-r["p"], r["M"]))
    return results[:limit] if limit else results


def rank_boot_from_scored(scored: list[dict], times, setup_delay_seconds: int,
                          max_target_seconds: int, limit: int | None = None) -> list[dict]:
    """The best target for EACH candidate boot time, from an existing rank_over_times list.

    One row per boot time (deduped by phase), its best achievable target over the range.
    Splitting this out of rank_by_boot_time lets a caller reuse one rank_over_times sweep for
    both the overall pairs and the per-boot-time bests.
    """
    best_sm: dict = {}
    for r in scored:
        key = (r["second"], r["mdmsh"])
        if key not in best_sm or r["p"] > best_sm[key]["p"]:
            best_sm[key] = r

    parsed = [t if isinstance(t, _dt.datetime) else _dt.datetime.fromisoformat(t) for t in times]
    phases = list({(t.month, t.day, t.hour, t.minute, t.second): t for t in parsed}.values())

    out = []
    for t in phases:
        best = None
        for s in range(setup_delay_seconds, max_target_seconds + 1):
            r = best_sm.get((s, mdmsh_of(t + _dt.timedelta(seconds=s))))
            if r is not None and (best is None or r["p"] > best["p"]):
                best = r
        if best is not None:
            out.append({**best, "initial_time": t})
    out.sort(key=lambda r: (-r["p"], r["M"]))
    return out[:limit] if limit else out


def rank_by_boot_time(canon_map, model, times, base_delay: int, setup_delay_seconds: int,
                      max_target_seconds: int, step: int = 1, k: float = 3.5,
                      include_calibration: bool = False, limit: int | None = None) -> list[dict]:
    """The best target (best commanded M) for EACH candidate boot time, ranked by that best P."""
    scored = rank_over_times(canon_map, model, times, base_delay, setup_delay_seconds,
                             max_target_seconds, step=step, k=k,
                             include_calibration=include_calibration)
    return rank_boot_from_scored(scored, times, setup_delay_seconds, max_target_seconds, limit)


def print_pairs_rows(rows: list[dict], k: float = 3.5, include_calibration: bool = False,
                     title: str = "Best (boot time, commanded countdown) pairs") -> None:
    """Print a given list of (boot time, M) rows (already sliced to however many you want)."""
    band = "jitter+calib" if include_calibration else "jitter"
    print(f"{title}  ({band} kernel, k={k}):")
    print(f"  {'#':>2}  {'boot time':>19}  {'M (ms)':>9}  {'target F_b':>10}  "
          f"{'second':>6}  {'P(capture)':>10}  {'sigma':>6}")
    for i, r in enumerate(rows, 1):
        print(f"  {i:>2}  {r['initial_time']:%Y-%m-%d %H:%M:%S}  {r['M']:>9.0f}  "
              f"{r['F']:>10}  {r['second']:>6}  {r['p'] * 100:>9.1f}%  {r['sigma']:>6.1f}")


def best_per_scenario(ranked: list[dict]) -> list[dict]:
    """Keep the best-scoring row per (second, mdmsh) scenario (ranked must be p-desc sorted)."""
    seen: dict = {}
    for r in ranked:
        seen.setdefault((r["second"], r["mdmsh"]), r)
    return sorted(seen.values(), key=lambda r: (-r["p"], r["M"]))


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
    """Print the top-`top` distinct commanded countdowns; RETURN the full ranked list."""
    ranked = rank_targets(canon_map, model, initial_time, base_delay, setup_delay_seconds,
                          max_target_seconds, step=step, k=k,
                          include_calibration=include_calibration)
    # separate distinct targets by ~1 sigma at the median M so the list isn't one cluster
    med_sigma = ranked[len(ranked) // 2]["sigma"] if ranked else 1.0
    all_rows = distinct_targets(ranked, max(1, int(med_sigma)), len(ranked))
    band = "jitter+calib" if include_calibration else "jitter"
    print(f"Best commanded countdowns (boot {initial_time:%Y-%m-%d %H:%M:%S}, "
          f"{band} kernel, k={k}):  [top {top} of {len(all_rows)}]")
    print(f"  {'#':>2}  {'M (ms)':>9}  {'target F_b':>10}  {'second':>6}  "
          f"{'P(capture)':>10}  {'sigma':>6}")
    for i, r in enumerate(all_rows[:top], 1):
        print(f"  {i:>2}  {r['M']:>9.0f}  {r['F']:>10}  {r['second']:>6}  "
              f"{r['p'] * 100:>9.1f}%  {r['sigma']:>6.1f}")
    return all_rows


def print_pairs_report(canon_map, model, times, base_delay, setup_delay_seconds,
                       max_target_seconds, step: int = 1, k: float = 3.5,
                       include_calibration: bool = False, top: int = 10) -> list[dict]:
    """Rank and print the best (boot time, commanded countdown) pairs.  Returns the rows."""
    ranked = rank_over_times(canon_map, model, times, base_delay, setup_delay_seconds,
                             max_target_seconds, step=step, k=k,
                             include_calibration=include_calibration)
    best = best_per_scenario(ranked)[:top]
    band = "jitter+calib" if include_calibration else "jitter"
    print(f"Best (boot time, commanded countdown) pairs  ({band} kernel, k={k}):")
    print(f"  {'#':>2}  {'boot time':>19}  {'M (ms)':>9}  {'target F_b':>10}  "
          f"{'second':>6}  {'P(capture)':>10}  {'sigma':>6}")
    for i, r in enumerate(best, 1):
        print(f"  {i:>2}  {r['initial_time']:%Y-%m-%d %H:%M:%S}  {r['M']:>9.0f}  "
              f"{r['F']:>10}  {r['second']:>6}  {r['p'] * 100:>9.1f}%  {r['sigma']:>6.1f}")
    return best


def print_by_boot_time_report(canon_map, model, times, base_delay, setup_delay_seconds,
                              max_target_seconds, step: int = 1, k: float = 3.5,
                              include_calibration: bool = False, top: int = 10) -> list[dict]:
    """Rank and print the best target for each candidate starting time.  Returns the rows."""
    best = rank_by_boot_time(canon_map, model, times, base_delay, setup_delay_seconds,
                             max_target_seconds, step=step, k=k,
                             include_calibration=include_calibration, limit=top)
    band = "jitter+calib" if include_calibration else "jitter"
    print(f"Best target for each starting time  (top {top}, {band} kernel, k={k}):")
    print(f"  {'#':>2}  {'boot time':>19}  {'best M (ms)':>11}  {'target F_b':>10}  "
          f"{'second':>6}  {'P(capture)':>10}  {'sigma':>6}")
    for i, r in enumerate(best, 1):
        print(f"  {i:>2}  {r['initial_time']:%Y-%m-%d %H:%M:%S}  {r['M']:>11.0f}  "
              f"{r['F']:>10}  {r['second']:>6}  {r['p'] * 100:>9.1f}%  {r['sigma']:>6.1f}")
    return best
