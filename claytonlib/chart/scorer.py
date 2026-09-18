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

from claytonlib.chart.canon import mdmsh_of, seed_for_mdmsh
from claytonlib.chart.evaluation import frames_in_second


def _centers(base_delay: int, upto_second: int) -> list[int]:
    """centers[s] = delay_at_second(base_delay, s) for s in 0..upto_second (built in O(n))."""
    centers = [base_delay]
    for s in range(upto_second):
        centers.append(centers[-1] + frames_in_second(s))
    return centers


def _frame_bounds(model, base_delay: int, setup_delay_seconds: int,
                  max_target_seconds: int) -> tuple[int, int]:
    """The battle-frame range spanning commanded countdowns M ∈ [setup, max] SECONDS.

    setup/max bound the countdown M itself (the t2→t3 prep duration), NOT the derived battle RTC
    second -- the ~rtc_offset_seconds encounter lead is post-countdown and isn't usable prep time,
    so M must be ≥ setup.  The battle frame is model.frame(M, base_delay) (= dF(M)+F_a for a dF
    model; = mean(M) for a legacy Fb model), so the sweep runs between the frames at M=setup·1000
    and M=max·1000."""
    f_lo = int(math.floor(model.frame(setup_delay_seconds * 1000.0, base_delay)))
    f_hi = int(math.ceil(model.frame(max_target_seconds * 1000.0, base_delay)))
    return (f_lo, f_hi) if f_lo <= f_hi else (f_hi, f_lo)


def capture_probability(canon_map, model, mdmsh, M, base_delay: int = 0, k: float = 3.5,
                        include_calibration: bool = False) -> dict:
    """Landing-weighted capture probability at commanded countdown M for a fixed mdmsh.

    Integrates the CanonMap's capture bits at `mdmsh` against a Gaussian centered at
    frame(M, base_delay) with sd sigma(M) (physical jitter; + the reducible band if
    include_calibration), truncated at k sigma and renormalized.  Returns {p, F, sigma, lo, hi, M}.
    """
    F = model.frame(M, base_delay)
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


def marginal_capture(canon_map, model, initial_time: _dt.datetime, M, base_delay: int,
                     k: float = 3.5, include_calibration: bool = False) -> dict | None:
    """Capture probability at countdown M, MARGINALIZED over the RTC-second distribution.

    P(capture|M) = Σ_s P(S=s|M) · capture_probability(mdmsh(initial_time + s), M).  The frame
    center is the SAME at every second (model.frame(M, base_delay)) -- a second miss is a phase/δ0
    effect that doesn't move the frame (notes/seed_hitting_process.md), so we do NOT recenter per
    second.  The battle second is derived from M (M/1000 + rtc_offset ± σ_S), so it is not clipped
    to the M-range bounds.  Returns {p, F, second (modal), mdmsh (modal), sigma, M, breakdown} or
    None if the distribution is empty.  With σ_S=0 this reduces to the single modal second.
    """
    secs = model.second_distribution(M)
    if not secs:
        return None
    p = 0.0
    breakdown = []
    for s, ps in secs:
        mdmsh = mdmsh_of(initial_time + _dt.timedelta(seconds=s))
        cp = capture_probability(canon_map, model, mdmsh, M, base_delay, k, include_calibration)
        p += ps * cp["p"]
        breakdown.append({"second": s, "p_second": ps, "mdmsh": mdmsh, "cp": cp["p"],
                          "F": cp["F"], "sigma": cp["sigma"], "lo": cp["lo"], "hi": cp["hi"]})
    modal_s = secs[0][0]
    return {"p": p, "F": model.frame(M, base_delay), "second": modal_s,
            "mdmsh": mdmsh_of(initial_time + _dt.timedelta(seconds=modal_s)),
            "sigma": model.jitter_sigma(M), "M": M, "breakdown": breakdown}


def seed_breakdown(canon_map, model, initial_time: _dt.datetime, M, base_delay: int,
                   second: int, k: float = 3.5, include_calibration: bool = False,
                   max_rows: int | None = 400) -> dict | None:
    """Individual (frame, seed) rows for ONE candidate RTC second of a marginal_capture
    breakdown -- the same per-seed detail the notebook's chart_check_target_landing() prints
    (frame/delta/seed/hit/weight%/cumulative-capture%), returned as data instead of printed.
    `second` must be one of marginal_capture's breakdown seconds (its own `second` field, not
    an arbitrary offset) -- None is returned if it isn't (or if the distribution is empty).

    weight%/cum_capture% are always computed over the FULL window so they stay exact even when
    `max_rows` culls what's returned -- only the returned `rows` are centered/truncated (the far
    tails carry little mass anyway), not the underlying sums. `total_frames`/`truncated` tell
    the caller how much was cut.
    """
    mc = marginal_capture(canon_map, model, initial_time, M, base_delay, k, include_calibration)
    if mc is None:
        return None
    b = next((row for row in mc["breakdown"] if row["second"] == second), None)
    if b is None:
        return None
    F, sigma, mdmsh, lo, hi = b["F"], b["sigma"], b["mdmsh"], b["lo"], b["hi"]
    two_s2 = 2.0 * sigma * sigma
    weighted = []
    den = 0.0
    for frame in range(lo, hi + 1):
        w = math.exp(-((frame - F) ** 2) / two_s2)
        den += w
        weighted.append((frame, w, canon_map.captured(mdmsh, frame)))
    den = den or 1.0
    center_frame = round(F)
    all_rows = []
    cum = 0.0
    for frame, w, hit in weighted:
        if hit:
            cum += w
        all_rows.append({
            "frame": frame, "delta": frame - center_frame,
            "seed": seed_for_mdmsh(mdmsh, frame), "hit": hit,
            "weight_pct": w / den * 100.0, "cum_capture_pct": cum / den * 100.0,
        })
    total = len(all_rows)
    if max_rows is not None and total > max_rows:
        center_idx = min(range(total), key=lambda i: abs(all_rows[i]["delta"]))
        start = max(0, center_idx - max_rows // 2)
        rows = all_rows[start:start + max_rows]
        truncated = True
    else:
        rows, truncated = all_rows, False
    return {"second": second, "p_second": b["p_second"], "cp": b["cp"], "mdmsh": mdmsh,
            "F": F, "sigma": sigma, "rows": rows, "total_frames": total, "truncated": truncated}


def rank_targets(canon_map, model, initial_time: _dt.datetime, base_delay: int,
                 setup_delay_seconds: int, max_target_seconds: int, step: int = 1,
                 k: float = 3.5, include_calibration: bool = False,
                 limit: int | None = None) -> list[dict]:
    """Rank candidate target frames (each with the M that centers on it) by capture prob.

    For each target frame F across the charted range, M = model.solve_frame(F) is the countdown to
    center there (kept only when M ∈ [setup, max] SECONDS -- setup/max bound the countdown itself),
    and the score is the SECOND-MARGINALIZED capture probability (Σ_s P(S=s|M)·cp at that second's
    mdmsh) -- so an M whose second is split across two seeds is penalised.  Returns dicts
    {M, F, second (modal), mdmsh (modal), p, sigma} sorted by p desc (ties by smaller M).
    """
    f_lo, f_hi = _frame_bounds(model, base_delay, setup_delay_seconds, max_target_seconds)
    m_min, m_max = setup_delay_seconds * 1000.0, max_target_seconds * 1000.0
    results = []
    for F_target in range(f_lo, f_hi + 1, step):
        M = model.solve_frame(F_target, base_delay)
        if not (m_min <= M <= m_max):
            continue
        mc = marginal_capture(canon_map, model, initial_time, M, base_delay, k, include_calibration)
        if mc is None:
            continue
        results.append({"M": M, "F": F_target, "second": mc["second"], "mdmsh": mc["mdmsh"],
                        "p": mc["p"], "sigma": mc["sigma"]})
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

    f_lo, f_hi = _frame_bounds(model, base_delay, setup_delay_seconds, max_target_seconds)
    results = []
    for F_target in range(f_lo, f_hi + 1, step):
        M = model.solve_frame(F_target, base_delay)
        if M <= 0:
            continue
        # RTC second from REAL time (M), not the frame -- see model.battle_second_offset.
        s = model.battle_second_offset(M)
        if s < setup_delay_seconds or s > max_target_seconds:
            continue
        for mdmsh, example in groups[s].items():
            cp = capture_probability(canon_map, model, mdmsh, M, base_delay, k, include_calibration)
            results.append({"M": M, "F": F_target, "second": s, "mdmsh": mdmsh,
                            "initial_time": example, "p": cp["p"], "sigma": cp["sigma"]})
    results.sort(key=lambda r: (-r["p"], r["M"]))
    return results[:limit] if limit else results


def rank_boot_marginal(canon_map, model, times, base_delay: int, setup_delay_seconds: int,
                       max_target_seconds: int, step: int = 1, k: float = 3.5,
                       include_calibration: bool = False, limit: int | None = None) -> list[dict]:
    """Best target M for EACH candidate boot time, scored by SECOND-MARGINALIZED capture prob.

    For each boot phase and target frame F, P(capture) = Σ_s P(S=s|M(F)) · cp(mdmsh(boot+s), F),
    the full second-marginalized probability with the frame center fixed across seconds.  Unlike
    rank_over_times (which scores one modal second per F and attaches an example boot), this must
    combine each boot's several seconds, so it works per boot phase.  Returns one row per phase
    {M, F, second (modal), mdmsh (modal), initial_time, p, sigma}, sorted by p desc.

    cp(F, mdmsh) is memoized and each phase's mdmsh(boot+s) is pretabulated, so the cost stays
    close to the single-second sweep despite the per-boot marginalization.
    """
    parsed = [t if isinstance(t, _dt.datetime) else _dt.datetime.fromisoformat(t) for t in times]
    phases = list({(t.month, t.day, t.hour, t.minute, t.second): t for t in parsed}.values())
    # Battle seconds are derived (M/1000 + rtc_offset ± σ_S), so they run above `max`; pretabulate
    # mdmsh(phase + s) across that derived range (removes datetime math from the hot loop).
    _pad = model.rtc_offset_seconds + 3.0 * (model.rtc_offset_std or 0.0) + 1.0
    s_lo = max(0, int(math.floor(setup_delay_seconds + model.rtc_offset_seconds
                                 - 3.0 * (model.rtc_offset_std or 0.0) - 1.0)))
    s_hi = int(math.ceil(max_target_seconds + _pad))
    mtab = [{s: mdmsh_of(t + _dt.timedelta(seconds=s)) for s in range(s_lo, s_hi + 1)}
            for t in phases]

    f_lo, f_hi = _frame_bounds(model, base_delay, setup_delay_seconds, max_target_seconds)
    m_min, m_max = setup_delay_seconds * 1000.0, max_target_seconds * 1000.0
    cp_memo: dict = {}
    best: dict = {}
    for F_target in range(f_lo, f_hi + 1, step):
        M = model.solve_frame(F_target, base_delay)
        if not (m_min <= M <= m_max):     # setup/max bound the countdown M (in seconds)
            continue
        secs = model.second_distribution(M)
        if not secs:
            continue
        modal_s = secs[0][0]
        sigma = model.jitter_sigma(M)
        for i, t in enumerate(phases):
            tab = mtab[i]
            pmarg = 0.0
            for s, ps in secs:
                mm = tab.get(s)
                if mm is None:                # edge rounding beyond the pretabulated span
                    mm = mdmsh_of(t + _dt.timedelta(seconds=s))
                key = (F_target, mm)
                cp = cp_memo.get(key)
                if cp is None:
                    cp = capture_probability(canon_map, model, mm, M, base_delay, k,
                                             include_calibration)["p"]
                    cp_memo[key] = cp
                pmarg += ps * cp
            tkey = (t.month, t.day, t.hour, t.minute, t.second)
            prev = best.get(tkey)
            if prev is None or pmarg > prev["p"]:
                best[tkey] = {"M": M, "F": F_target, "second": modal_s, "mdmsh": tab[modal_s],
                              "initial_time": t, "p": pmarg, "sigma": sigma}
    rows = sorted(best.values(), key=lambda r: (-r["p"], r["M"]))
    return rows[:limit] if limit else rows


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
                        include_calibration: bool = False, top: int = 10,
                        use_safari_offset: bool = True) -> list[dict]:
    """Print the top-`top` distinct commanded countdowns; RETURN the full ranked list.

    ``use_safari_offset`` (default True) scores the safari loading path when the model carries a
    fitted ``safari_offset``: the offset is folded into the model here (``with_safari_offset``),
    so the scorer internals are untouched.  A no-op when no offset is set."""
    if use_safari_offset:
        model = model.with_safari_offset()
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
                       include_calibration: bool = False, top: int = 10,
                       use_safari_offset: bool = True) -> list[dict]:
    """Rank and print the best (boot time, commanded countdown) pairs.  Returns the rows.

    ``use_safari_offset`` (default True): fold a fitted ``safari_offset`` into the model to score
    the safari loading path (no-op when unset)."""
    if use_safari_offset:
        model = model.with_safari_offset()
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
                              include_calibration: bool = False, top: int = 10,
                              use_safari_offset: bool = True) -> list[dict]:
    """Rank and print the best target for each candidate starting time.  Returns the rows.

    ``use_safari_offset`` (default True): fold a fitted ``safari_offset`` into the model to score
    the safari loading path (no-op when unset)."""
    if use_safari_offset:
        model = model.with_safari_offset()
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
