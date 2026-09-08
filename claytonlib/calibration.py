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
from dataclasses import asdict, dataclass
from typing import NamedTuple


# Shared artifact path for the fitted model.  utils/calibration_tools writes it after each
# saved run (the expedition "loop-back"); the chart / expedition read it here, so neither
# side has to import the other (the fitter lives in utils/, this pure model in claytonlib/).
DEFAULT_MODEL_PATH = "data/calibration_model.json"


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

    def solve(self, target_fb: float) -> float:
        """Commanded countdown M that centers the landing on target_fb."""
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
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationModel":
        d = dict(d)
        d["coeffs"] = tuple(d.get("coeffs", ()))
        return cls(**d)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "CalibrationModel":
        with open(path) as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def load_default(cls, path: str = DEFAULT_MODEL_PATH) -> "CalibrationModel | None":
        """Load the shared fitted-model artifact, or None if it hasn't been exported yet.

        The chart / expedition call this to pick up the latest calibration without depending
        on the (utils/) fitter -- it is refreshed automatically each time a run is saved.
        """
        import os
        if not os.path.exists(path):
            return None
        return cls.load(path)
