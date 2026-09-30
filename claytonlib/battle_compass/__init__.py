"""Battle Compass — identify a battle seed from observed turns, then steer the RNG to a capture.

Its own tool, built alongside ``metronome_compass`` rather than by refactoring it, which keeps
the 2,900-line symmetric refactor of ``effects.py`` off the critical path
(notes/battle_compass.md sec 15.2).  Shared, matchup-agnostic mechanics live in
``claytonlib.battle``; only the nine moves the reference fixture needs are implemented here.

v1 target: Suicune at the Bell Tower in a Fast Ball — base Speed 85, under the Fast Ball's 100
threshold, so a flat x1 and the hardest multiplier case there is.

Modules:

* ``state`` — battlers, actions, and the battle state, deliberately small because Phase 2's
  target is frozen at 1 HP and permanently paralyzed.
* ``tokens`` — the reporting grammar (sec 13).  Its job is *canonical rendering*: a candidate
  seed is simulated forwards to produce the tokens it would emit, and filtering is a comparison
  against what the player reported.
* ``sim`` — turn resolution over the emulator-verified skeleton in ``claytonlib.battle.turn``.
* ``candidates`` — the uniform (frame x second) grid of possible battle seeds (sec 17.1).
* ``identify`` — narrowing that grid against what the player reports, and the phase machine.
* ``targets`` — known static-encounter movesets, in slot order (not derivable from base stats:
  a moveset belongs to the encounter, not the species).
* ``hunt_session`` — the layer the app drives: one run from first turn to capture, joining
  narrowing and solving behind a single snapshot. Undo is replay, and Phase 2 re-solves every
  turn so a misplay costs nothing.
* ``solver`` — Phase 2: the cheapest action sequence that lands the capture ball on a winning
  set of shake rolls.  The Machete equivalent, and the reason the whole tool works: 99% of seeds
  are steerable to a capture, at a median of 6-7 turns.  Read ``Unreachable``'s docstring before
  acting on a failure: a capture window is a *target*, not a reachable one, and no search can
  prove a seed hopeless because paralysis leaves the battle with no provable turn bound.

**One finding worth knowing before using any of this.** The two axes of the candidate grid are
not equally identifiable.  The frame is easy — 1,201 frame candidates narrow to one in three
turns.  The RTC second is *impossible*: it lives in the seed's top 8 bits, an LCRNG difference of
``k * 2**24`` stays in the top 8 bits forever, and every modulus the game takes reads only the low
bits.  A second window of 2 stalls at five survivors and never resolves, and balls are not a
practical remedy — separating four seconds took ten throws in testing, two of which captured and
would have lost the run.  Hence ``second_window`` defaults to 0, and
``identify.Session.ambiguity`` explains the situation when a set is stuck.
"""
from claytonlib.battle_compass.state import (  # noqa: F401
    Action, Battler, BattleState, Status,
)
from claytonlib.battle_compass.sim import (  # noqa: F401
    HuntConfig, execute_move, move_roll_cost, select_target_move, throw_ball,
)
from claytonlib.battle_compass.candidates import (  # noqa: F401
    Candidate, CandidateWindow,
)
from claytonlib.battle_compass.identify import (  # noqa: F401
    Narrowing, Observation, Phase, Session,
)
from claytonlib.battle_compass.targets import (  # noqa: F401
    STATIC_ENCOUNTERS, encounter_level, moveset,
)
from claytonlib.battle_compass.hunt_session import (  # noqa: F401
    HuntSession, TurnLog, worst_incoming_hit,
)
from claytonlib.battle_compass.solver import (  # noqa: F401
    Solution, SolverConfig, Step, Unreachable, distance_of, remaining_target_pp, solve,
    struggle_deadline,
)

# `simulate` and `simulate_turn` are deliberately NOT re-exported here. claytonlib/__init__
# hoists every public name from every subpackage, last-writer-wins, and `metronome_compass`
# defines its own `simulate_turn` -- so hoisting ours would make `claytonlib.simulate_turn`
# silently resolve to whichever sorted later. Import them from the module instead:
#
#     from claytonlib.battle_compass.sim import simulate, simulate_turn
#
# tests/test_claytonlib_exports.py fails on any such collision, which is how this was caught.
