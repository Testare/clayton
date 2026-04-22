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
from dataclasses import asdict, dataclass
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


@dataclass
class EvaluationData:
    results: dict[str, ChainEvaluationResult]  # keyed by chain filename (stem + .chain)
    top10: list[CrossChainResult]


# ---------------------------------------------------------------------------
# EvaluationStrategy protocol
# ---------------------------------------------------------------------------

class EvaluationStrategy(Protocol):
    @property
    def filename(self) -> str:
        """Base filename (e.g. 'sliding_window_8') for this strategy's output. The .json extension is appended automatically."""
        ...

    def evaluate(
        self,
        links: list[int],
        base_delay: int,
        setup_delay_seconds: int,
        initial_time: dt.datetime,
    ) -> list[TopResult]:
        """
        Score every frame in the chain and return the top 5 results sorted
        by score descending.

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
# JSON file I/O
# ---------------------------------------------------------------------------

def _evaluations_dir(chart_dir: Path) -> Path:
    return chart_dir / "evaluations"


def read_evaluation(chart_dir: Path, strategy: EvaluationStrategy) -> EvaluationData | None:
    path = _evaluations_dir(chart_dir) / f"{strategy.filename}.json"
    if not path.exists():
        return None
    with open(path) as f:
        raw = json.load(f)
    results = {
        chain_name: ChainEvaluationResult(
            max_links_checked=entry["max_links_checked"],
            top5=[TopResult(**r) for r in entry["top5"]],
        )
        for chain_name, entry in raw["results"].items()
    }
    top10 = [CrossChainResult(**r) for r in raw.get("top10", [])]
    return EvaluationData(results=results, top10=top10)


def write_evaluation(chart_dir: Path, strategy: EvaluationStrategy, data: EvaluationData) -> None:
    evals_dir = _evaluations_dir(chart_dir)
    evals_dir.mkdir(parents=True, exist_ok=True)
    path = evals_dir / f"{strategy.filename}.json"
    raw = {
        "top10": [asdict(r) for r in data.top10],
        "results": {
            chain_name: {
                "max_links_checked": result.max_links_checked,
                "top5": [asdict(r) for r in result.top5],
            }
            for chain_name, result in data.results.items()
        },
    }
    with open(path, "w") as f:
        json.dump(raw, f, indent=2)
