"""stopwatch.py — the battle-seed centre for an encounter that was MEASURED, not commanded.

A static hunt times its encounter: the player runs a countdown of M ms and the fitted
`calibration.CalibrationModel` maps that commanded M to a landing frame. **A roamer encounter
cannot be timed.** Finding one means walking between maps until it lands on yours, so the moment
the battle fires is observed rather than chosen, and what the player can report is a stopwatch
reading: started at the load press, stopped when the encounter fired (notes/roamers.md sec 6).

Those are two different quantities and this module exists so they cannot be confused.
`CalibrationModel.frame` is `alpha + beta*M`, and its **intercept is the timer workflow's own
misalignment** — where in the loading sequence the seed is generated relative to a countdown that
hit zero. Feeding a stopwatch reading through it would add that constant to a measurement that
already includes everything it needs. So `StopwatchVector` has the same two-method surface the
candidate grid actually calls — `frame(ms, base_low16)` and `battle_second_offset(ms)` — and
`battle_compass.candidates.generate` takes either object without knowing which it has.

**The elapsed time is the whole model.** There is nothing to fit: a delay is one hardware VBlank,
the rate is ~59.8261 Hz, and the frame difference between the load and the encounter is the elapsed
real time times that rate. What there *is* to say is how wrong it can be, which is why
`frame_sigma` and the two window suggestions are the substance of this file rather than
`frame` is.

Where the error comes from, in the order it matters:

=========================================  ==================================================
source                                     size
=========================================  ==================================================
the player's reaction, twice               ~0.2-0.5 s total, so ~12-30 frames
stopwatch vs DS clock drift                a fraction of the elapsed time; 0.1% of 10 min is
                                           ~36 frames
the load press's own landing jitter        the calibration model's sigma at the run's M, and
                                           it stays because Seed A is never identified
=========================================  ==================================================

The third is passed in rather than guessed (`load_sigma_frames`), because the only honest source
for it is the profile's own fitted model.

**A roamer hunt therefore opens with a window in the low hundreds of frames where a static hunt
opens with 60**, and that is affordable for a reason specific to this target: a trapped roamer
gives unbounded turns to separate candidates in, where a static encounter is racing a flee or a
faint. See `notes/roamers.md` sec 6 for the alternative that would shrink it — timing from console
power-on instead, which drops the load-press term entirely.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Hardware VBlank rate: delays per second, and a delay IS a game frame (1:1). The same figure
#: `chart.evaluation.DPS` and `calibration_tools._NOMINAL_RATE` carry; not a flat 60, which is the
#: assumption this project is migrating away from.
DELAYS_PER_SECOND = 59.8261

#: Default total reaction spread for the two button presses, as a standard deviation in
#: milliseconds. Starting a stopwatch on a load press and stopping it when a battle transition
#: begins are both visual-cue reactions, which the human-factors literature puts near 250 ms with
#: a spread of that order; two of them in quadrature is where this comes from.
#:
#: A DEFAULT and not a constant: a player who measures their own spread should pass it. It is
#: deliberately generous rather than optimistic, because the cost of the two errors is not
#: symmetric -- too wide a window costs compute on the first sweep, while too narrow a window
#: excludes the true seed and the run cannot recover.
DEFAULT_REACTION_STD_MS = 300.0

#: Default assumed relative drift between the stopwatch and the DS clock, as a fraction. 0.1%,
#: which is pessimistic for two quartz clocks and cheap to carry: it only matters for a long hunt,
#: and a long hunt is exactly when it is unverifiable.
DEFAULT_DRIFT_FRACTION = 0.001

#: How long a save load could plausibly take, in seconds, used as a window allowance for as long
#: as `StopwatchVector.seed_lag_seconds` is unmeasured.
#:
#: It is an allowance and not a correction, because the sign is known but the size is not: the
#: centre sits LATE by however long the load takes, so the window has to reach that far below it.
#: Ten seconds is generous for a DS save load and the cost of being generous is compute, while the
#: cost of being tight is a window that cannot contain the true seed however long the run goes.
#:
#: **It disappears the moment the lag is measured**, which is the point: one wide-window run pins
#: `seed_lag_seconds` (see `implied_seed_lag`) and every later hunt gets a window a tenth the size.
UNMEASURED_LAG_SECONDS = 10.0


@dataclass(frozen=True)
class StopwatchVector:
    """A measured elapsed time, as the candidate grid's centre and its spread.

    Duck-compatible with `calibration.CalibrationModel` for the two methods
    `battle_compass.candidates` calls, and deliberately nothing else: it is not a fitted model and
    should not be usable as one. In particular there is no `solve_frame` -- you cannot ask a
    stopwatch what countdown to run, because on a roamer there is no countdown to run.
    """

    #: Delays per second. A field rather than the module constant so a measurement campaign can
    #: refine it without editing code.
    delays_per_second: float = DELAYS_PER_SECOND
    #: Real-time seconds the stopwatch was running BEFORE the initial seed existed, subtracted
    #: from every reading. The player starts it at the load press and the seed is generated part
    #: way through the loading sequence, so a raw reading measures press-to-encounter while the
    #: grid needs seed-to-encounter.
    #:
    #: **This is the one number here that has to be measured, and it is worth more than every
    #: other field in this class.** It is a systematic shift, not a spread: at ~59.83 Hz, being
    #: wrong by one second moves the centre by SIXTY frames, which is a whole static-hunt window.
    #: Left at zero it is not merely imprecise, it is biased, and the bias is in a known
    #: direction -- the centre sits late by however long the load takes.
    #:
    #: Deliberately NOT inferred from `CalibrationModel.alpha` (-290 frames on the deployed fit,
    #: which is ~4.8 s and looks like exactly this quantity): that intercept was fitted for a
    #: workflow where the commanded countdown ENDS at the encounter press, so its sign and its
    #: endpoints are not these. Guessing it from a number that happens to be the right size is
    #: how a confident, consistently-wrong centre gets built.
    #:
    #: How to pin it without a gdb session: run the first roamer hunt with a window wide enough
    #: to find the seed anyway, then read the lag off the frame the run actually landed on --
    #: `implied_seed_lag`. One run is enough, because it is a constant of the load path and not
    #: of the hunt.
    seed_lag_seconds: float = 0.0
    #: Real-time seconds from the seed to the battle that are NOT in the reading -- the
    #: counterpart of `CalibrationModel.rtc_offset_seconds`, and normally zero here because the
    #: stopwatch spans the whole interval itself. Kept so a workflow that starts the stopwatch at
    #: some other cue can say so.
    rtc_offset_seconds: float = 0.0
    #: Spread of the player's two button presses (ms), as a standard deviation.
    reaction_std_ms: float = DEFAULT_REACTION_STD_MS
    #: Relative clock drift, as a fraction of the elapsed time.
    drift_fraction: float = DEFAULT_DRIFT_FRACTION
    #: Landing spread of the load press itself, in FRAMES. Zero only if Seed A was identified --
    #: which a roamer run does not do, so a zero here is a claim the run cannot support.
    load_sigma_frames: float = 0.0
    label: str = ""

    # -- the two methods the candidate grid calls ------------------------------------------

    def seconds_from_seed(self, ms: float) -> float:
        """The reading, in seconds, with the load's head cut off: seed-to-encounter.

        Both public methods go through this, so the lag cannot be applied to one axis and
        forgotten on the other -- which would put the frame and the second on different
        encounters, the exact failure `candidates` keeps the two axes independent to avoid.
        """
        return ms / 1000.0 - self.seed_lag_seconds + self.rtc_offset_seconds

    def frame(self, ms: float, base_low16: int = 0) -> float:
        """The battle seed's low16 frame, for a stopwatch reading of `ms` started at the load press.

        Returns ``base_low16 + elapsed``, matching a ``target="dF"`` `CalibrationModel`: the
        caller (`candidates.centre`) subtracts `base_low16` back off to get the pure frame
        difference and adds it to Seed A's year-adjusted delay, so the year never enters here.
        """
        return base_low16 + self.frames_in(1000.0 * self.seconds_from_seed(ms))

    def battle_second_offset(self, ms: float) -> int:
        """RTC seconds from the initial seed to the battle, from REAL time.

        Identical in form to `CalibrationModel.battle_second_offset`, and for the identical
        reason: the RTC advances with real time, while the frame counter lags it across loading
        screens (notes/seed_hitting_process.md). Deriving one from the other is the mistake that
        once produced a candidate set disjoint from the chart scorer's.
        """
        return round(self.seconds_from_seed(ms))

    # -- what it is worth ------------------------------------------------------------------

    def frames_in(self, ms: float) -> float:
        """Frames elapsed in `ms` of real time. The entire mean model."""
        return ms * self.delays_per_second / 1000.0

    def frame_sigma(self, ms: float) -> float:
        """Standard deviation of the centred frame, in frames.

        The three terms in quadrature, which assumes they are independent -- they are: a reaction
        time, two crystals' relative rate, and where a button press landed inside a loading
        sequence have nothing to do with each other.
        """
        reaction = self.frames_in(self.reaction_std_ms)
        drift = self.frames_in(ms) * self.drift_fraction
        return math.hypot(math.hypot(reaction, drift), self.load_sigma_frames)

    def second_sigma(self, ms: float) -> float:
        """Standard deviation of the battle RTC second, in seconds.

        The same reaction and drift terms, in seconds -- and **not** the frame sigma divided by
        the rate, even though it would come to nearly the same number here. The load-press jitter
        belongs to the frame counter and not to the wall clock: a load that lands a hundred frames
        late was still pressed when it was pressed.
        """
        reaction = self.reaction_std_ms / 1000.0
        drift = (ms / 1000.0) * self.drift_fraction
        return math.hypot(reaction, drift)

    def lag_allowance_frames(self) -> int:
        """Window allowance in frames for an unmeasured load lag, or 0 once it is measured.

        `k_sigma` cannot cover this and it would be wrong to pretend otherwise: an unmeasured
        `seed_lag_seconds` is a BIAS of up to `UNMEASURED_LAG_SECONDS`, not a spread, so widening
        by a multiple of sigma does not reach it. It is added to the window rather than to the
        sigma for the same reason.
        """
        if self.seed_lag_seconds:
            return 0
        return int(math.ceil(self.frames_in(1000.0 * UNMEASURED_LAG_SECONDS)))

    def suggest_frame_window(self, ms: float, *, k_sigma: float = 3.0,
                             minimum: int = 60) -> int:
        """Half-width in frames to pass as ``frame_window``.

        `k_sigma` of 3 covers 99.7% of a normal centred correctly, and the asymmetry of the two
        failure modes (see `DEFAULT_REACTION_STD_MS`) is why the default is not 2. `minimum`
        floors it at a static hunt's own default, so a short stopwatch reading never produces a
        window narrower than the one a *timed* encounter gets.

        Plus `lag_allowance_frames`, which usually dominates: ~600 frames while the load lag is
        unmeasured, against ~60-130 for the whole spread budget. That is deliberately generous and
        in line with what Battle Compass is actually run at -- Testare reports static hunts
        working well at +-2000 frames and +-7 seconds, so a roamer's first window being an order
        of magnitude wider than a static hunt's default is normal rather than alarming.
        """
        if ms < 0:
            raise ValueError(f"elapsed time cannot be negative: {ms}")
        spread = int(math.ceil(k_sigma * self.frame_sigma(ms)))
        return max(minimum, spread + self.lag_allowance_frames())

    def suggest_second_window(self, ms: float, *, k_sigma: float = 3.0,
                              minimum: int = 1) -> int:
        """Half-width in RTC seconds to pass as ``second_window``.

        **Never 0, unlike a static hunt's default.** `candidates.generate` defaults the second
        window to zero because `rtc_offset_seconds` normally pins the second, and that argument
        rests on the encounter being timed. Here the second is a measurement with a reaction time
        in it, so a zero window is a claim the stopwatch was pressed exactly on the tick -- and
        being wrong about it excludes the true seed from the grid permanently, with no symptom
        except that nothing ever matches.
        """
        if ms < 0:
            raise ValueError(f"elapsed time cannot be negative: {ms}")
        spread = int(math.ceil(k_sigma * self.second_sigma(ms)))
        allowance = 0 if self.seed_lag_seconds else int(math.ceil(UNMEASURED_LAG_SECONDS))
        return max(minimum, spread + allowance)

    def estimated_candidates(self, ms: float, *, k_sigma: float = 3.0) -> int:
        """How many candidates the suggested windows come to, before generating them.

        Worth having for the same reason `candidates.estimate_size` is: the practical limit on a
        roamer window is compute on the first turn's sweep, not information, and the UI should be
        able to say so before it hangs on one.
        """
        from claytonlib.battle_compass.candidates import estimate_size

        return estimate_size(self.suggest_frame_window(ms, k_sigma=k_sigma),
                             self.suggest_second_window(ms, k_sigma=k_sigma))

    def implied_seed_lag(self, ms: float, landed_frame: int, base_low16: int) -> float:
        """The `seed_lag_seconds` that would have centred this run exactly.

        `landed_frame` is the frame of the seed a finished run actually identified, and
        `base_low16` is the key seed's own low16. One completed run pins the constant for every
        later one -- which is why a first roamer hunt should be run with a deliberately wide
        window rather than a clever one.

        Returns the lag INCLUDING whatever this object already assumed, so the result is the
        value to store rather than a correction to apply.
        """
        measured_frames = landed_frame - base_low16
        return (ms / 1000.0 + self.rtc_offset_seconds
                - measured_frames / self.delays_per_second)

    @classmethod
    def from_calibration(cls, model, **kwargs) -> "StopwatchVector":
        """A vector that inherits what a fitted model legitimately knows, and nothing else.

        Takes only the **load press's landing spread** (`jitter_rms`, which is M-independent and
        happens to sit at 73 frames on the deployed fit -- the same order as `jitter_sigma` at a
        typical five-minute countdown). That spread belongs here because a roamer run never
        identifies Seed A, so the uncertainty in where the load landed is never resolved.

        It does **not** take `alpha`, `beta`, or `rtc_offset_seconds`: those describe a commanded
        countdown, and `seed_lag_seconds` says why reusing them would be a confident error. Pass
        `seed_lag_seconds` explicitly once a run has measured it.
        """
        return cls(load_sigma_frames=float(getattr(model, "jitter_rms", 0.0) or 0.0), **kwargs)

    def describe(self, ms: float) -> str:
        """One line for the UI: the centre, the spread, and what it will cost."""
        frames = self.frames_in(ms)
        return (f"{ms / 1000.0:.1f} s measured ≈ {frames:.0f} frames "
                f"± {self.frame_sigma(ms):.0f} (1σ), "
                f"second ± {self.second_sigma(ms):.1f}; "
                f"suggested window {self.suggest_frame_window(ms)} frames "
                f"× {self.suggest_second_window(ms)} s "
                f"≈ {self.estimated_candidates(ms)} candidates")
