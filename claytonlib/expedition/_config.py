"""expedition/_config.py — CheckConfig and strategy/criteria registries."""
import re


# ---------------------------------------------------------------------------
# CheckConfig
# ---------------------------------------------------------------------------

class CheckConfig:
    """Persistent configuration for the CheckHelper utilities."""

    def __init__(self):
        self.target_window: int = 30

    def _to_dict(self) -> dict:
        return {'target_window': self.target_window}

    @classmethod
    def _from_dict(cls, data: dict) -> 'CheckConfig':
        cfg = cls()
        cfg.target_window = data.get('target_window', 30)
        return cfg


# ---------------------------------------------------------------------------
# Strategy / criteria name registry
# ---------------------------------------------------------------------------

def _build_strategy_registry():
    from claytonlib.chart import (
        STRATEGY_ONLY_BALLS, STRATEGY_ONE_MUD, STRATEGY_SIX_BAIT,
    )
    return {
        STRATEGY_ONLY_BALLS.name:   STRATEGY_ONLY_BALLS,
        STRATEGY_ONE_MUD.name:      STRATEGY_ONE_MUD,
        STRATEGY_SIX_BAIT.name:     STRATEGY_SIX_BAIT,
    }


def _build_criteria_registry():
    from claytonlib.chart import (
        CRITERIA_CAPTURE, CRITERIA_WONT_FLEE_10_TURNS,
        CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS,
        CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS,
    )
    return {
        CRITERIA_CAPTURE.name:                       CRITERIA_CAPTURE,
        CRITERIA_WONT_FLEE_10_TURNS.name:            CRITERIA_WONT_FLEE_10_TURNS,
        CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS.name: CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS,
        CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS.name: CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS,
    }


def _resolve_strategy(name: str):
    reg = _build_strategy_registry()
    if name in reg:
        return reg[name]
    raise ValueError(f"Unknown strategy name: {name!r}. Known: {list(reg)}")


def _resolve_criteria(name: str):
    from claytonlib.chart import machete_x_turns_n_balls_criteria
    reg = _build_criteria_registry()
    if name in reg:
        return reg[name]
    # parameterised: "machete-{turns}-turns-after-{n}-balls"
    m = re.fullmatch(r'machete-(\d+)-turns-after-(\d+)-balls', name)
    if m:
        return machete_x_turns_n_balls_criteria(int(m.group(1)), int(m.group(2)))
    raise ValueError(f"Unknown criteria name: {name!r}")


def _resolve_eval_strategy(name: str):
    from claytonlib.chart.evaluation import SlidingWindowSum, NormalWindow
    # "sliding_window_N"
    m = re.fullmatch(r'sliding_window_(\d+)', name)
    if m:
        return SlidingWindowSum(int(m.group(1)))
    # "normal_S"
    m = re.fullmatch(r'normal_(.+)', name)
    if m:
        return NormalWindow(float(m.group(1)))
    raise ValueError(f"Unknown evaluation strategy filename: {name!r}")


_EVAL_TYPES = [
    ("sliding_window", "sliding window sum  (prompts for window size, must be odd)"),
    ("normal",         "Gaussian window  (prompts for sigma frames, e.g. 3.0)"),
]
