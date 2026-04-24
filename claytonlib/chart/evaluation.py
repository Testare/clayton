"""
evaluation.py — Chart evaluation tools.

Reads completed chain files and ranks individual frames by success likelihood.
Each link in a chain file is a 64-bit bitmask covering 30 frames × 2 seeds:
bits 2j and 2j+1 belong to frame j (0-29). The actual delay for frame j in
link i is:
    base_delay + (setup_delay_seconds + i) * 60 + j * 2
"""

import datetime as dt
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


FRAMES_PER_LINK = 30
SEEDS_PER_LINK  = 60   # 2 per frame


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class TopResult:
    score: int | float
    delay: int   # actual frame delay value fed to calculate_seed
    time: str    # "HH:MM:SS" clock time of the containing second


@dataclass
class CrossChainResult:
    score: int | float
    delay: int   # actual frame delay value fed to calculate_seed
    time: str    # "HH:MM:SS" clock time of the containing second
    chain: str   # path.name of the source chain file


@dataclass
class ChainEvaluationResult:
    max_links_checked: int
    top5: list[TopResult]
    best5: list[TopResult] = field(default_factory=list)


@dataclass
class EvaluationData:
    results: dict[str, ChainEvaluationResult]  # keyed by chain filename (stem + .chain)
    top10: list[CrossChainResult]
    best10: list[CrossChainResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# EvaluationStrategy protocol
# ---------------------------------------------------------------------------

class EvaluationStrategy(Protocol):
    @property
    def filename(self) -> str:
        """Base filename (e.g. 'sliding_window_8') for this strategy's output.
        The .json extension is appended automatically."""
        ...

    def score(self, flat: list[float]) -> list[float]:
        """Apply windowed scoring to a straightened per-frame score list.
        Output length equals input length; edge frames with insufficient
        window coverage are set to 0."""
        ...

    def score_to_probability(self, score: float) -> float:
        """Convert a windowed score value to a probability in [0, 1]."""
        ...

    def evaluate(
        self,
        links: list[int],
        base_delay: int,
        setup_delay_seconds: int,
        initial_time: dt.datetime,
    ) -> list[TopResult]:
        """Convenience wrapper: straighten → score → gather top 5.

        Parameters
        ----------
        links:
            Per-link bitmasks in order. Bit 2j and 2j+1 of links[i] indicate
            whether seeds for frame j of link i led to success.
        base_delay:
            The delay value from get_times(key_seed)[0]. The delay for frame j
            of link i is: base_delay + (setup_delay_seconds + i) * 60 + j * 2
        setup_delay_seconds:
            Seconds between key seed and the first link (link 0).
        initial_time:
            Key seed datetime. The clock time for link i is
            initial_time + timedelta(seconds=setup_delay_seconds + i).
        """
        ...


# ---------------------------------------------------------------------------
# Straightening helpers
# ---------------------------------------------------------------------------

def straighten_link(link: int) -> list[float]:
    """Convert a 64-bit link bitmask into 30 per-frame probability scores.

    For frame j, bit 2j represents the seed that assumes the player is still
    in the current second (weight (30-j)/30) and bit 2j+1 represents the seed
    that assumes the second has already advanced (weight j/30).
    """
    scores = []
    for j in range(FRAMES_PER_LINK):
        bit0 = (link >> (2 * j)) & 1
        bit1 = (link >> (2 * j + 1)) & 1
        scores.append(bit0 * (30 - j) / 30 + bit1 * j / 30)
    return scores


def straighten_chain(links: list[int]) -> list[float]:
    """Flatten all links into a single per-frame score list (length = 30 * len(links))."""
    flat = []
    for link in links:
        flat.extend(straighten_link(link))
    return flat


def _make_top_result(flat_idx: int, score: float, base_delay: int,
                     setup_delay_seconds: int, initial_time: dt.datetime) -> TopResult:
    link_idx = flat_idx // FRAMES_PER_LINK
    frame_idx = flat_idx % FRAMES_PER_LINK
    delay = base_delay + (setup_delay_seconds + link_idx) * 60 + frame_idx * 2
    time_str = (
        initial_time + dt.timedelta(seconds=setup_delay_seconds + link_idx)
    ).strftime("%H:%M:%S")
    return TopResult(score=round(score, 2), delay=delay, time=time_str)


def _gather_top5(
    scored: list[float],
    base_delay: int,
    setup_delay_seconds: int,
    initial_time: dt.datetime,
) -> list[TopResult]:
    """Pick the top 5 frames by score. Ties broken by ascending delay."""
    top_indices = sorted(range(len(scored)), key=lambda i: (-scored[i], i))[:5]
    return [_make_top_result(i, scored[i], base_delay, setup_delay_seconds, initial_time)
            for i in top_indices]


def _gather_best(
    scored: list[float],
    base_delay: int,
    setup_delay_seconds: int,
    initial_time: dt.datetime,
    n: int,
) -> list[TopResult]:
    """Pick up to n results where each successive result has a strictly lower delay
    than the previous, always choosing the highest score available at that constraint.

    Result 1 is the global best score. Result 2 is the best score among frames with
    delay strictly below result 1's delay, and so on. Ties on score are broken by
    lowest delay (to leave the most room for subsequent results).
    """
    # Build (delay, score, flat_idx) for all frames with a non-zero score.
    candidates = [
        (base_delay + (i // FRAMES_PER_LINK + setup_delay_seconds) * 60 + (i % FRAMES_PER_LINK) * 2,
         s, i)
        for i, s in enumerate(scored) if s > 0
    ]

    results = []
    max_delay = None
    for _ in range(n):
        pool = [c for c in candidates if max_delay is None or c[0] < max_delay]
        if not pool:
            break
        delay, score, flat_idx = max(pool, key=lambda c: (c[1], -c[0]))
        results.append(_make_top_result(flat_idx, score, base_delay, setup_delay_seconds, initial_time))
        max_delay = delay
    return results


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------

class SlidingWindowSum:
    """Score each frame as the sum of straightened scores within a fixed window.

    Models timing errors as uniformly distributed within the window.

    Parameters
    ----------
    window:
        Total number of frames in the window. Must be odd so there is a
        clear centre frame.
    """

    def __init__(self, window: int):
        if window % 2 == 0:
            raise ValueError(f"window must be odd, got {window}")
        self.window = window

    @property
    def filename(self) -> str:
        return f"sliding_window_{self.window}"

    def score_to_probability(self, score: float) -> float:
        return score / self.window

    def score(self, flat: list[float]) -> list[float]:
        hw = self.window // 2
        n = len(flat)
        result = [0.0] * n
        if n < self.window:
            return result
        window_sum = sum(flat[:self.window])
        result[hw] = window_sum
        for j in range(hw + 1, n - hw):
            window_sum += flat[j + hw] - flat[j - hw - 1]
            result[j] = window_sum
        return result

    def evaluate(
        self,
        links: list[int],
        base_delay: int,
        setup_delay_seconds: int,
        initial_time: dt.datetime,
    ) -> list[TopResult]:
        flat = straighten_chain(links)
        scored = self.score(flat)
        return _gather_top5(scored, base_delay, setup_delay_seconds, initial_time)


class NormalWindow:
    """Score each frame as a Gaussian-weighted average of surrounding frames.

    Models timing errors as normally distributed, making the score an expected
    success probability for a player whose timing has standard deviation
    sigma_frames frames.

    Parameters
    ----------
    sigma_frames:
        Standard deviation in frames (not delay units; 1 frame = 2 delay).
        Must be >= 1.0. The window extends ±floor(2 * sigma_frames) frames
        (2σ cutoff, retaining ~95.4% of probability mass). Gaussian weights
        are normalised to sum to 1 within the window.
    """

    def __init__(self, sigma_frames: float):
        if sigma_frames < 1.0:
            raise ValueError(f"sigma_frames must be >= 1.0, got {sigma_frames}")
        self.sigma_frames = sigma_frames
        hw = int(2 * sigma_frames)
        raw = [math.exp(-k * k / (2 * sigma_frames ** 2)) for k in range(-hw, hw + 1)]
        total = sum(raw)
        self._weights = [w / total for w in raw]
        self._hw = hw

    @property
    def filename(self) -> str:
        return f"normal_{self.sigma_frames:g}"

    def score_to_probability(self, score: float) -> float:
        return score  # already a probability (weighted average with weights summing to 1)

    def score(self, flat: list[float]) -> list[float]:
        hw = self._hw
        n = len(flat)
        result = [0.0] * n
        for j in range(hw, n - hw):
            result[j] = sum(
                self._weights[k + hw] * flat[j + k] for k in range(-hw, hw + 1)
            )
        return result

    def evaluate(
        self,
        links: list[int],
        base_delay: int,
        setup_delay_seconds: int,
        initial_time: dt.datetime,
    ) -> list[TopResult]:
        flat = straighten_chain(links)
        scored = self.score(flat)
        return _gather_top5(scored, base_delay, setup_delay_seconds, initial_time)


# ---------------------------------------------------------------------------
# JSON file I/O
# ---------------------------------------------------------------------------

def _evaluations_dir(chart_dir: Path) -> Path:
    return chart_dir / "evaluations"


def read_evaluation(chart_dir: Path, strategy: EvaluationStrategy, filename_override: str | None = None) -> EvaluationData | None:
    basename = filename_override if filename_override is not None else strategy.filename
    path = _evaluations_dir(chart_dir) / f"{basename}.json"
    if not path.exists():
        return None
    with open(path) as f:
        raw = json.load(f)
    results = {
        chain_name: ChainEvaluationResult(
            max_links_checked=entry["max_links_checked"],
            top5=[TopResult(**r) for r in entry["top5"]],
            best5=[TopResult(**r) for r in entry.get("best5", [])],
        )
        for chain_name, entry in raw["results"].items()
    }
    top10 = [CrossChainResult(**r) for r in raw.get("top10", [])]
    best10 = [CrossChainResult(**r) for r in raw.get("best10", [])]
    return EvaluationData(results=results, top10=top10, best10=best10)


def write_evaluation(chart_dir: Path, strategy: EvaluationStrategy, data: EvaluationData, filename_override: str | None = None) -> None:
    evals_dir = _evaluations_dir(chart_dir)
    evals_dir.mkdir(parents=True, exist_ok=True)
    basename = filename_override if filename_override is not None else strategy.filename
    path = evals_dir / f"{basename}.json"
    raw = {
        "top10": [asdict(r) for r in data.top10],
        "best10": [asdict(r) for r in data.best10],
        "results": {
            chain_name: {
                "max_links_checked": result.max_links_checked,
                "top5": [asdict(r) for r in result.top5],
                "best5": [asdict(r) for r in result.best5],
            }
            for chain_name, result in data.results.items()
        },
    }
    with open(path, "w") as f:
        json.dump(raw, f, indent=2)
