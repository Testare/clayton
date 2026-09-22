"""Reusable timer-calibration model.

Maps a commanded countdown ``M`` (ms, = target_timer_delay + target_timer_calibration)
to the landing distribution over the battle-seed frame ``F_b``:

    mean F_b(M)         -- the frame you expect to land on
    sigma_jitter(M)     -- irreducible physical spread (frames), grows ~c*sqrt(M)
    sigma_band(M)       -- reducible mean-uncertainty band (frames); ~0 near the
                           measured runs, widening only as you extrapolate

The parameters are fit upstream by ``utils/calibration_tools.calibrate_timer`` from
``data/compass_runs.jsonl``; this module holds only the resulting numbers and the pure
math the chart consumes, with no I/O beyond (de)serialization.  Keeping it in claytonlib
lets the chart depend on it without reaching into utils/ (which owns the interactive fit).

See notes/refined_chart.md for the model derivation.
"""
import json
import math
from dataclasses import asdict, dataclass, replace
from typing import NamedTuple


# Shared artifact path for the fitted model.  utils/calibration_tools writes it after each
# saved run (the expedition "loop-back"); the chart / expedition read it here, so neither
# side has to import the other (the fitter lives in utils/, this pure model in claytonlib/).
DEFAULT_MODEL_PATH = "data/calibration_model.json"

# Selectable frame-rate model shapes (the expedition's `fps_model`).  Accepts a few spellings;
# normalizes to the canonical modelset key ("linear" or "quad").  linear = physically-sane flat
# slope (safe to extrapolate); quad = curvature that fits 3-10 min slightly tighter in-range but
# whose slope runs past the ~59.83 Hz hardware ceiling, so it must not be extrapolated.
FPS_MODEL_KEYS = {"linear": "linear", "quad": "quad", "quadratic": "quad"}


def normalize_fps_model(name: str) -> str:
    """Canonical modelset key ('linear'|'quad') for a user-supplied fps_model spelling."""
    key = str(name).strip().lower()
    if key not in FPS_MODEL_KEYS:
        raise ValueError(f"unknown fps_model {name!r}; choose one of "
                         f"{sorted(set(FPS_MODEL_KEYS))}")
    return FPS_MODEL_KEYS[key]


def _norm_cdf(z: float) -> float:
    """Standard-normal CDF via math.erf (stdlib; no scipy/numpy)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class Landing(NamedTuple):
    """The landing distribution at one commanded countdown M (all frames)."""
    M: float
    mean: float          # expected F_b
    sigma_jitter: float  # irreducible physical spread (grows ~sqrt(M))
    sigma_band: float    # reducible mean-uncertainty band (grows on extrapolation)

    @property
    def sigma_total(self) -> float:
        return math.hypot(self.sigma_jitter, self.sigma_band)


@dataclass
class CalibrationModel:
    """Fitted F_b-vs-M model with an M-dependent landing spread.

    ``kind`` selects the mean function:
      * "line" -- F_b = alpha + beta*M   (beta = frames/ms)
      * "quad" -- degree-2 polynomial in the centered/scaled u = (M - m_center)/m_scale
    Spread: sigma_jitter(M) = jitter_c*sqrt(M) (falling back to jitter_rms), plus a
    reducible OLS SE-of-fit band jitter_rms*sqrt(1/n_fit + (M-m_bar)^2/sxx).
    """
    kind: str = "line"
    # What mean()/solve() predict:
    #   "Fb" (legacy) -- mean(M) is the battle-seed low16 frame directly.  Correct only in the
    #        calibration year: it folds F_a AND the (year-2000) term into the intercept alpha.
    #   "dF" (option 2) -- mean(M) is dF = F_b - F_a (year-agnostic).  The actual battle frame
    #        is reconstructed as dF(M) + F_a, where F_a is the low16 of the *identified* initial
    #        seed (key_seed & 0xFFFF), which already carries the year.  So a dF model needs no
    #        year input and reuses calibration data across target years.  Use frame()/solve_frame().
    target: str = "Fb"
    # mean-function parameters
    beta: float = 0.0            # line: frames per ms
    alpha: float = 0.0           # line: intercept (frames)
    coeffs: tuple = ()           # quad: poly coeffs over u
    m_center: float = 0.0        # quad: centering
    m_scale: float = 1.0         # quad: scaling
    # spread parameters
    jitter_c: float | None = None    # sigma_jitter = jitter_c*sqrt(M)
    jitter_rms: float = 0.0          # fallback jitter + reducible-band scale
    # reducible-band geometry (textbook OLS SE-of-fit)
    n_fit: int = 0
    sxx: float = 0.0
    m_bar: float = 0.0
    # RTC-second calibration (SEPARATE from the frame fit): the battle RTC second advances
    # with REAL time, so it is M/1000 seconds past the initial seed plus this fixed real-time
    # setup offset -- NOT derived from the frame counter (which lags real time across loads).
    # 0 = "the RTC second is exactly M ms from the initial seed"; fit from data as it's gathered.
    # A Safari-Zone-entry offset (its extra loading) would add on top of this and is future work.
    rtc_offset_seconds: float = 0.0
    # Spread of the battle RTC second (σ_S): the second isn't deterministic -- the sub-second phase
    # at the load press and the timer-vs-DS misalignment (δ0) wander it, mostly INDEPENDENTLY of the
    # frame (see notes/seed_hitting_process.md).  Used to marginalize capture over the second
    # distribution.  0 = deterministic (commit to round(M/1000 + rtc_offset_seconds), the old behavior).
    rtc_offset_std: float = 0.0
    # Safari load-path offset (frames): safari-compass runs land a fixed Δα off the metronome
    # fit's intercept -- the extra Safari-Zone-entry loading screen (abf.10).  It is fit holding
    # the metronome slope (beta) and applied ONLY when a caller asks for the safari path
    # (frame(..., safari=True) / solve_frame(..., safari=True)); the metronome alpha/beta are
    # untouched, so the metronome/chart path is unchanged.  None = not fit yet.
    safari_offset: float | None = None
    safari_offset_n: int = 0          # safari runs behind the offset
    safari_offset_std: float = 0.0    # spread of the per-run residuals (frames)
    # Per-advance safari offset (frames per Seed A advance): the hypothesis that the number of
    # Seed A advances made during timer 3 (Elm calls + chatot flips) shifts the landing frame,
    # so the safari-path prediction is `safari_offset + safari_offset_per_advance * advances`
    # rather than a flat offset.  ADDITIVE with whatever sign the fit produces -- a negative
    # value means frames are lost per advance (the original hypothesis), a positive one means
    # they're gained; nothing here assumes a direction.  None = not fit / not in use, which
    # reproduces the flat-offset behavior exactly.  UNFIT BY DEFAULT: the advance count is a
    # large multiplier (~80 on a real expedition), so a poorly-determined slope is amplified
    # far past the landing jitter -- see fit_safari_offset's evidence gate.
    safari_offset_per_advance: float | None = None
    safari_offset_per_advance_n: int = 0        # runs carrying an advance count
    safari_offset_per_advance_ci: tuple = ()    # (lo, hi) bootstrap 95% CI on the slope
    # Safari-path landing jitter (frames per sqrt(ms)), fit from the spread of the safari runs
    # themselves rather than inherited from the metronome fit.  The safari load path is a
    # different (longer) path than the metronome one, so its spread need not match; without
    # this, every safari candidate window and capture probability is computed with the
    # METRONOME jitter_c.  None = inherit jitter_c (the historical behavior).
    safari_jitter_c: float | None = None
    # metadata (not used in the math)
    label: str = ""
    n_runs: int = 0
    m_lo: float | None = None    # range of M actually measured (for extrapolation warnings)
    m_hi: float | None = None

    # -- mean function -----------------------------------------------------
    def mean(self, M: float) -> float:
        """Expected F_b frame for commanded countdown M (ms)."""
        if self.kind == "quad":
            u = (M - self.m_center) / self.m_scale
            return sum(c * u ** j for j, c in enumerate(self.coeffs))
        return self.alpha + self.beta * M

    def slope(self, M: float) -> float:
        """dF_b/dM at M (frames per ms) -- the instantaneous rate/1000."""
        if self.kind == "quad":
            u = (M - self.m_center) / self.m_scale
            return sum(j * c * u ** (j - 1)
                       for j, c in enumerate(self.coeffs) if j >= 1) / self.m_scale
        return self.beta

    def frame(self, M: float, base_low16: int = 0) -> float:
        """The actual battle-seed low16 frame for countdown M off the initial seed.

        For a dF model this reconstructs F_b = dF(M) + base_low16, where base_low16 is the
        low16 of the identified initial seed (key_seed & 0xFFFF) -- which carries the year, so
        the result is the actual seed frame the canon is keyed by, in any year.  For a legacy
        Fb model mean(M) is already that frame, so base_low16 is ignored (back-compat).

        To score the safari loading path, hand the scorer ``with_safari_offset()`` rather than
        threading a flag here -- that model's mean already includes the offset.
        """
        return self.mean(M) + (base_low16 if self.target == "dF" else 0)

    def solve_frame(self, target_frame: float, base_low16: int = 0) -> float:
        """Commanded countdown M that centers the actual battle frame on target_frame.

        Inverse of frame(): for a dF model it solves dF = target_frame - base_low16; for a
        legacy Fb model it solves on target_frame directly (base_low16 ignored)."""
        return self.solve(target_frame - (base_low16 if self.target == "dF" else 0))

    def safari_shift(self, advances: int = 0) -> float:
        """Total safari load-path frame shift for `advances` Seed A advances.

        ``safari_offset`` (the flat extra-loading-screen cost) plus
        ``safari_offset_per_advance * advances``.  Either term being unfit contributes 0.
        """
        shift = self.safari_offset or 0.0
        if self.safari_offset_per_advance:
            shift += self.safari_offset_per_advance * advances
        return shift

    def with_safari_offset(self, advances: int = 0) -> "CalibrationModel":
        """A copy with the safari load path folded into the mean, or self if nothing applies.

        The shift (``safari_shift(advances)``) is baked into the intercept (``alpha`` for a line,
        the constant ``coeffs[0]`` for a quad) and the safari offset fields are cleared, so the
        mean now IS the safari-path frame at every M.  This lets the existing chart scorer --
        which calls ``frame``/``solve_frame`` -- score the safari path just by being handed this
        model, with no per-call flag threaded through its internals (ctd.11).  ``advances`` is a
        CONSTANT for any one chart target or compass run (the expedition's key_seed_advances, or
        the planned encounter frame), which is exactly why the per-advance term folds into the
        intercept here instead of threading an advance count through the scorers.

        ``safari_jitter_c``, when fit, also replaces ``jitter_c`` -- the returned model's spread
        is then the one measured on the safari path rather than the metronome path.
        """
        shift = self.safari_shift(advances)
        if not shift and self.safari_jitter_c is None:
            return self
        cleared = dict(safari_offset=None, safari_offset_per_advance=None)
        if self.safari_jitter_c is not None:
            cleared["jitter_c"] = self.safari_jitter_c
            cleared["safari_jitter_c"] = None
        if self.kind == "quad":
            coeffs = list(self.coeffs)
            if coeffs:
                coeffs[0] += shift
            return replace(self, coeffs=tuple(coeffs), **cleared)
        return replace(self, alpha=self.alpha + shift, **cleared)

    def solve(self, target_fb: float) -> float:
        """Commanded countdown M that centers the landing on target_fb (in mean()'s units)."""
        if self.kind == "quad":
            M = self.m_center  # Newton from the centroid; mean is monotonic over the data
            for _ in range(80):
                s = self.slope(M)
                if s == 0:
                    break
                step = (self.mean(M) - target_fb) / s
                M -= step
                if abs(step) < 1e-4:
                    break
            return M
        if self.beta == 0:
            return 0.0
        return (target_fb - self.alpha) / self.beta

    # -- spread ------------------------------------------------------------
    def jitter_sigma(self, M: float) -> float:
        """Irreducible physical spread at M (frames).  Grows ~sqrt(M)."""
        if self.jitter_c is not None and M > 0:
            return self.jitter_c * math.sqrt(M)
        return self.jitter_rms

    def mean_band(self, M: float) -> float:
        """Reducible mean-uncertainty band at M (frames).

        Textbook OLS standard-error-of-fit: ~0 near the measured runs, widening as you
        extrapolate.  Shrinks as more runs are collected.
        """
        if not self.jitter_rms or not self.sxx or self.n_fit < 1:
            return 0.0
        return self.jitter_rms * math.sqrt(1.0 / self.n_fit + (M - self.m_bar) ** 2 / self.sxx)

    def total_sigma(self, M: float, include_calibration: bool = True) -> float:
        """Combined 1-sigma spread of F_b at M.

        include_calibration=False gives the irreducible jitter alone (the spread you'd
        face with perfect calibration).
        """
        sj = self.jitter_sigma(M)
        if not include_calibration:
            return sj
        return math.hypot(sj, self.mean_band(M))

    def landing(self, M: float) -> Landing:
        """The full landing distribution at M as a Landing(mean, sigma_jitter, sigma_band)."""
        return Landing(M, self.mean(M), self.jitter_sigma(M), self.mean_band(M))

    # -- RTC second (real-time; NOT frame-derived) -------------------------
    def battle_second_offset(self, M: float) -> int:
        """RTC seconds from the initial seed to the battle, computed from REAL time.

        M is a real-time countdown (ms), so the RTC clock advances ~M/1000 s during it; the
        battle second is that plus the fixed real-time setup offset.  Deliberately independent
        of the frame counter (which lags real time across loading screens) -- deriving the
        second from the frame is what put the chart on the wrong mdms.  Rounded to the nearest
        second (so e.g. M=100999 ms -> 101 s); the exact sub-second tick depends on the boot's
        sub-second phase, which is a data-collection question, not modeled here yet.
        """
        return round(M / 1000.0 + self.rtc_offset_seconds)

    def second_distribution(self, M: float, k_sigma: float = 3.0,
                            min_prob: float = 1e-3) -> list[tuple[int, float]]:
        """Distribution over the battle RTC second for countdown M, as [(second, prob), ...].

        The second is S = round(R) for real elapsed R ~ N(μ, σ_S), μ = M/1000 + rtc_offset_seconds,
        σ_S = rtc_offset_std -- so P(S=s) = Φ((s+0.5−μ)/σ_S) − Φ((s−0.5−μ)/σ_S).  Covers round(μ)
        ± ceil(k_sigma·σ_S), drops seconds below `min_prob`, renormalizes, and returns them sorted
        by probability descending (so [0] is the modal second).  When σ_S = 0 this is exactly the
        old point estimate [(round(μ), 1.0)] -- i.e. the whole feature is opt-in via a fitted σ_S.
        """
        mu = M / 1000.0 + self.rtc_offset_seconds
        sigma = self.rtc_offset_std
        if sigma <= 0:
            return [(round(mu), 1.0)]
        center = round(mu)
        span = max(1, int(math.ceil(k_sigma * sigma)))
        raw = [(s, _norm_cdf((s + 0.5 - mu) / sigma) - _norm_cdf((s - 0.5 - mu) / sigma))
               for s in range(center - span, center + span + 1)]
        tot = sum(p for _, p in raw) or 1.0
        kept = [(s, p / tot) for s, p in raw if p / tot >= min_prob]
        tot2 = sum(p for _, p in kept) or 1.0
        dist = [(s, p / tot2) for s, p in kept]
        dist.sort(key=lambda sp: -sp[1])
        return dist

    # -- convenience: prediction / hit probability -------------------------
    def predict(self, M: float, k: float = 2.0) -> dict:
        """Expected F_b with a +/-(band + k*jitter) range at M."""
        mean = self.mean(M)
        band = self.mean_band(M)
        j = self.jitter_sigma(M)
        half = band + k * j
        return {"expected": mean, "lo": mean - half, "hi": mean + half,
                "jitter": j, "rate_band": band, "M": M}

    def hit_probability(self, M: float, target_fb: float, tolerance: float = 0.5,
                        include_calibration: bool = True) -> dict:
        """P(land within +/-tolerance frames of target_fb) at commanded countdown M."""
        mean = self.mean(M)
        sj = self.jitter_sigma(M)
        sc = self.mean_band(M)
        sigma = math.hypot(sj, sc) if include_calibration else sj
        if sigma <= 0:
            p = 1.0 if abs(target_fb - mean) <= tolerance else 0.0
        else:
            p = (_norm_cdf((target_fb + tolerance - mean) / sigma)
                 - _norm_cdf((target_fb - tolerance - mean) / sigma))
        return {"p": p, "expected": mean, "delta": target_fb - mean,
                "sigma_jitter": sj, "sigma_calib": sc, "sigma_total": sigma,
                "tolerance": tolerance, "M": M}

    # -- construction / serialization --------------------------------------
    @classmethod
    def from_fit(cls, fit: dict, n_fit: int, sxx: float, m_bar: float,
                 jitter_c: float | None, jitter_rms: float | None, **meta) -> "CalibrationModel":
        """Build from a calibrate_timer fit dict (kind + raw params) and geometry."""
        kind = fit.get("kind", "line")
        common = dict(jitter_c=jitter_c, jitter_rms=jitter_rms or 0.0,
                      n_fit=n_fit, sxx=sxx, m_bar=m_bar, **meta)
        if kind == "quad":
            return cls(kind="quad", coeffs=tuple(fit["coeffs"]),
                       m_center=fit["m_center"], m_scale=fit["m_scale"], **common)
        return cls(kind="line", beta=fit["beta"], alpha=fit["alpha"], **common)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["coeffs"] = list(self.coeffs)
        d["safari_offset_per_advance_ci"] = list(self.safari_offset_per_advance_ci)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationModel":
        d = dict(d)
        d["coeffs"] = tuple(d.get("coeffs", ()))
        d["safari_offset_per_advance_ci"] = tuple(d.get("safari_offset_per_advance_ci") or ())
        # Defensive: a null in the artifact (e.g. an rtc_offset_std written before it was fit)
        # would otherwise flow into `sigma <= 0` comparisons and raise -- coerce to 0.0 (which
        # means "deterministic", the safe default) instead.
        if d.get("rtc_offset_std") is None:
            d["rtc_offset_std"] = 0.0
        if d.get("rtc_offset_seconds") is None:
            d["rtc_offset_seconds"] = 0.0
        return cls(**d)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "CalibrationModel":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def load_default(cls, path: str = DEFAULT_MODEL_PATH,
                     which: str = "linear") -> "CalibrationModel | None":
        """Load one model from the shared fitted-model artifact, or None if not exported yet.

        The chart / expedition call this to pick up the latest calibration without depending on
        the (utils/) fitter.  The artifact is a MODELSET holding both the linear and quad fits
        (see save_set); `which` (the expedition's fps_model, any FPS_MODEL_KEYS spelling) selects
        one.  A legacy single-model file loads as-is for any `which` (back-compat).
        """
        import os
        if not os.path.exists(path):
            return None
        with open(path) as f:
            d = json.load(f)
        return cls._from_artifact(d, which)

    @classmethod
    def _from_artifact(cls, d: dict, which: str = "linear") -> "CalibrationModel | None":
        """Pick a model from a loaded artifact dict (modelset or legacy single-model)."""
        if "models" not in d:                      # legacy: a bare CalibrationModel dict
            return cls.from_dict(d)
        key = normalize_fps_model(which)
        models = d["models"]
        chosen = models.get(key) or models.get(d.get("default", "linear"))
        if chosen is None:
            chosen = next(iter(models.values()), None)
        return cls.from_dict(chosen) if chosen is not None else None

    @staticmethod
    def save_set(models: "dict[str, CalibrationModel]", path: str = DEFAULT_MODEL_PATH,
                 default: str = "linear") -> None:
        """Write a MODELSET artifact: {default, models:{key: model-dict}} (keys are FPS_MODEL_KEYS).

        The chart/expedition read one model out of this via load_default(which=fps_model); storing
        both lets a chart precomputed over their UNION switch fps_model with no re-precompute.
        """
        import os
        payload = {"format": "modelset", "default": normalize_fps_model(default),
                   "models": {normalize_fps_model(k): m.to_dict() for k, m in models.items()}}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def load_set(cls, path: str = DEFAULT_MODEL_PATH) -> "dict[str, CalibrationModel]":
        """{key: CalibrationModel} from a modelset artifact; {'linear': model} for a legacy file.

        Empty dict if the artifact does not exist -- callers building the canon union check this.
        """
        import os
        if not os.path.exists(path):
            return {}
        with open(path) as f:
            d = json.load(f)
        if "models" not in d:
            return {"linear": cls.from_dict(d)}
        return {k: cls.from_dict(v) for k, v in d["models"].items()}
