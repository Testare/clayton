"""compass/_types.py — Input types, parsing, and options for the safari compass."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from claytonlib.safari import SafariPokemon, SafariStep
from claytonlib.times import get_times
from claytonlib.chart import Strategy, SuccessCriteria, CRITERIA_CAPTURE


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------

@dataclass
class CompassAction:
    step: SafariStep
    uncertain: bool = False


class UndoAction:
    pass


class JaneAction:
    pass


@dataclass
class ParseError:
    unknown_chars: set[str]

    def __str__(self) -> str:
        chars = ', '.join(repr(c) for c in sorted(self.unknown_chars))
        return f"Unrecognised input character(s): {chars}"


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

_CHAR_TO_STEP: dict[str, SafariStep] = {
    'm': SafariStep.MUD,
    'M': SafariStep.MUD_CRITICAL,
    'a': SafariStep.MUD_CRITICAL,
    'b': SafariStep.BAIT,
    'B': SafariStep.BAIT_CRITICAL,
    'e': SafariStep.BAIT_CRITICAL,
    '0': SafariStep.BALL_0,
    '1': SafariStep.BALL_1,
    '2': SafariStep.BALL_2,
    '3': SafariStep.BALL_3,
    'F': SafariStep.FLED,
    'C': SafariStep.CAPTURED,
}

_UNCERTAIN_CANONICAL: dict[str, SafariStep] = {
    'b': SafariStep.BAIT,   'B': SafariStep.BAIT,   'e': SafariStep.BAIT,
    'm': SafariStep.MUD,    'M': SafariStep.MUD,    'a': SafariStep.MUD,
    '0': SafariStep.BALL_0, '1': SafariStep.BALL_0,
    '2': SafariStep.BALL_0, '3': SafariStep.BALL_0,
}


def parse_input(text: str) -> list | ParseError:
    """Parse one line of compass input into a list of CompassAction/UndoAction."""
    actions: list = []
    unknown: set[str] = set()
    chars = [c for c in text if c not in (' ', ',')]
    i = 0
    while i < len(chars):
        ch = chars[i]
        if ch == 'u':
            actions.append(UndoAction())
            i += 1
        elif ch == 'J':
            actions.append(JaneAction())
            i += 1
        elif ch == '?':
            i += 1
            if i < len(chars) and chars[i] in _UNCERTAIN_CANONICAL:
                actions.append(CompassAction(step=_UNCERTAIN_CANONICAL[chars[i]], uncertain=True))
                i += 1
            else:
                unknown.add('?')
        elif ch in _CHAR_TO_STEP:
            actions.append(CompassAction(step=_CHAR_TO_STEP[ch]))
            i += 1
        else:
            unknown.add(ch)
            i += 1
    if unknown:
        return ParseError(unknown)
    return actions


def _action_to_str(action: CompassAction) -> str:
    if action.uncertain:
        if action.step in (SafariStep.BAIT, SafariStep.BAIT_CRITICAL):
            return '?b'
        if action.step in (SafariStep.MUD, SafariStep.MUD_CRITICAL):
            return '?m'
        return '?0'
    return action.step.value


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

@dataclass
class CompassOptions:
    starting_ball_count:  int = 30
    seeds_displayed:      int = 5
    evaluation_threshold: int = 10
    suggest_jane:         bool = True  # suggest Jane when seeds < cpu_count (once per run)


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class CompassSafariInput:
    pokemon:             SafariPokemon
    strategy:            Strategy
    criteria:            SuccessCriteria
    window:              int
    initial_time:        dt.datetime
    key_seed:            int | None = None
    target_delay:        int | None = None
    target_seed:         int | None = None
    evaluation_strategy: Strategy | None = None
    evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE
    options:             CompassOptions = field(default_factory=CompassOptions)

    def __post_init__(self):
        if self.target_delay is None:
            raise ValueError("target_delay is required")
        if self.key_seed is None:
            raise ValueError("key_seed is required")
        if self.target_seed is not None:
            base_delay, _ = get_times(self.key_seed)
            from claytonlib.compass._core import _seed_reachable
            if not _seed_reachable(self.target_seed, self.target_delay,
                                   base_delay, self.initial_time):
                raise ValueError(
                    f"target_seed 0x{self.target_seed:08X} does not match any candidate "
                    f"at target_delay={self.target_delay} for the given initial_time"
                )

    @classmethod
    def from_chart(cls, chart_input, *, window: int, initial_time: dt.datetime,
                   target_seed: int | None = None, target_delay: int | None = None,
                   pokemon: SafariPokemon | None = None, strategy: Strategy | None = None,
                   criteria: SuccessCriteria | None = None,
                   evaluation_strategy: Strategy | None = None,
                   evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE) -> 'CompassSafariInput':
        return cls(
            pokemon=pokemon or chart_input.pokemon,
            strategy=strategy or chart_input.strategy,
            criteria=criteria or chart_input.criteria,
            window=window,
            initial_time=initial_time,
            key_seed=chart_input.key_seed,
            target_delay=target_delay,
            target_seed=target_seed,
            evaluation_strategy=evaluation_strategy,
            evaluation_criteria=evaluation_criteria,
        )
