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
"""
from claytonlib.battle_compass.state import (  # noqa: F401
    Action, Battler, BattleState, Status,
)
from claytonlib.battle_compass.sim import (  # noqa: F401
    HuntConfig, execute_move, move_roll_cost, select_target_move, throw_ball,
)

# `simulate` and `simulate_turn` are deliberately NOT re-exported here. claytonlib/__init__
# hoists every public name from every subpackage, last-writer-wins, and `metronome_compass`
# defines its own `simulate_turn` -- so hoisting ours would make `claytonlib.simulate_turn`
# silently resolve to whichever sorted later. Import them from the module instead:
#
#     from claytonlib.battle_compass.sim import simulate, simulate_turn
#
# tests/test_claytonlib_exports.py fails on any such collision, which is how this was caught.
