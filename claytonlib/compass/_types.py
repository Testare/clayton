"""compass/_types.py — Input types, parsing, and options for the safari compass."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, replace

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
    # calibrated-mode landing prior (b70.2 / b70.4)
    second_offset_sd:     float = 0.6   # discrete-Gaussian sd over δ; smaller ⇒ more mass on δ=0
    confidence_threshold: float = 0.95  # posterior at which we flag "likely identified"
    # candidate-set bounding (b70.5)
    mass_cap:             float | None = None  # keep the top candidates covering this prior mass
    jane_mass:            float = 0.99  # effective-count mass for the prior-weighted Jane offload


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class CompassSafariInput:
    """Inputs for the safari seed identifier.

    Two candidate-generation modes:

    * **Calibrated** (the new charting model): set ``frame_center`` (F* = model.mean(M)),
      ``sigma`` (σ(M) jitter) and ``target_second`` (T*, the RTC-second offset from boot
      where F* lands).  Candidates are ``calculate_seed(initial_time + (T*+δ), frame)`` swept
      over ``frame ∈ [F* ± k·σ]`` and ``δ ∈ second_offsets`` — no seed_a/seed_b duality (the
      RTC second is an explicit axis).  Build one with ``from_expedition_target``.
    * **Legacy**: set ``target_delay`` + ``window`` for the old delay-window + seed_a/seed_b
      sweep.  Retained for callers not yet migrated to the calibration model.
    """
    pokemon:             SafariPokemon
    strategy:            Strategy
    criteria:            SuccessCriteria
    initial_time:        dt.datetime
    window:              int | None = None
    key_seed:            int | None = None
    target_delay:        int | None = None
    target_seed:         int | None = None
    # calibrated-mode fields (see class docstring)
    frame_center:        float | None = None   # F* = model.mean(M)
    sigma:               float | None = None   # σ(M) jitter (frames)
    target_second:       int | None = None     # T*: RTC-second offset from boot at F*
    second_offsets:      tuple = (0,)           # δ's to cover (±K off-by-one timing)
    k:                   float = 3.5            # frame half-window in units of σ
    evaluation_strategy: Strategy | None = None
    evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE
    options:             CompassOptions = field(default_factory=CompassOptions)

    @property
    def calibrated(self) -> bool:
        """True when this input drives the (second, frame) calibrated sweep."""
        return self.frame_center is not None

    def __post_init__(self):
        if self.key_seed is None:
            raise ValueError("key_seed is required")
        if self.calibrated:
            if self.sigma is None or self.target_second is None:
                raise ValueError("calibrated mode requires sigma and target_second "
                                 "(use CompassSafariInput.from_expedition_target)")
            if not self.second_offsets:
                raise ValueError("second_offsets must be non-empty")
            return
        if self.target_delay is None:
            raise ValueError("target_delay is required (or use calibrated fields / "
                             "from_expedition_target)")
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
    def from_expedition_target(cls, *, model, M: float, initial_time: dt.datetime,
                               key_seed: int, max_target_seconds: int,
                               pokemon: SafariPokemon, strategy: Strategy,
                               criteria: SuccessCriteria,
                               second_offsets: tuple = (0,), k: float = 3.5,
                               mass_cap: float | None = None,
                               evaluation_strategy: Strategy | None = None,
                               evaluation_criteria: SuccessCriteria = CRITERIA_CAPTURE,
                               options: 'CompassOptions | None' = None
                               ) -> 'CompassSafariInput':
        """Build a calibrated input straight from a chosen chart target + calibration model.

        Resolves the commanded countdown ``M`` to a mean battle frame ``F* = model.frame(M, F_a)``
        with spread ``σ = model.jitter_sigma(M)``, and locates the RTC second ``T*`` whose
        variable-width delay band contains F* (via the same ``_centers`` table the scorer
        uses).  No hand-set delay window is needed.
        """
        import bisect
        from claytonlib.times import get_times
        from claytonlib.chart.scorer import _centers

        base_delay, _ = get_times(key_seed)
        # Actual battle-seed low16: frame(M, base_delay) = dF(M)+F_a for a dF model (year carried
        # by base_delay = key_seed low16), mean(M) for a legacy Fb model.  frame - base_delay is
        # then the year-agnostic elapsed count, so _second_of_frame in the search is correct too.
        F = model.frame(M, base_delay)
        sigma = model.jitter_sigma(M)
        centers = _centers(base_delay, max_target_seconds)
        target_second = bisect.bisect_right(centers, F) - 1
        opts = options or CompassOptions()
        if mass_cap is not None:
            opts = replace(opts, mass_cap=mass_cap)
        return cls(
            pokemon=pokemon, strategy=strategy, criteria=criteria,
            initial_time=initial_time, key_seed=key_seed,
            frame_center=F, sigma=sigma, target_second=target_second,
            second_offsets=tuple(second_offsets), k=k,
            evaluation_strategy=evaluation_strategy,
            evaluation_criteria=evaluation_criteria,
            options=opts,
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
