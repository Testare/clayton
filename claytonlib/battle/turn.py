"""The RNG cost of one battle turn.

The skeleton every advance count hangs off, confirmed on the emulator [verified]:

===  ======================================================================
 4   BeforeTurn advances
 ?   the FIRST actor's action -- a bag item (0), a ball (1-4 shake rolls), or a move
 2   ...but only if that was a move and it succeeded
 2   between-turn advances
 ?   the SECOND actor's move
 2   ...but only if that succeeded
 4   end-of-turn advances
===  ======================================================================

Three things fall out of it that the solver depends on:

* **A ball's shake rolls are just that turn's action rolls.** They follow the four BeforeTurn
  advances every turn already spends, so there is no ball-specific offset -- a point an earlier
  draft of the design doc got wrong.
* **Bag actions and switches cost nothing of their own**, which makes them the cheapest entry in
  the action alphabet and is why item choice can be optimised without moving any RNG offset.
* **The between-turn and end-of-turn advances happen regardless**, including on a turn where we
  only used an item, and the opponent still takes its move and its post-success advances.

The counts here match the values `metronome_compass` verified for the Blackthorn matchup, which
is a useful corroboration: `_BEFORE_TURN_ADVANCES = 4`, `_MAGIKARP_TURN_START_ADVANCES = 2`
(between turns), `_POST_*_SUCCESS_ADVANCES = 2`, `_END_OF_TURN_ADVANCES = 4`.

Still unmeasured, and therefore not modelled here: the battle-START advance count for a given
encounter (R2 -- `metronome_compass`'s 6 is "4 bellShimmer + 2 ability" for Blackthorn, and
Suicune's intro plus Pressure will differ), and the per-move roll counts, which live in
`effects.py`'s handlers per effect id.
"""
from __future__ import annotations

from dataclasses import dataclass

BEFORE_TURN_ADVANCES = 4
BETWEEN_TURN_ADVANCES = 2
POST_SUCCESSFUL_MOVE_ADVANCES = 2
END_OF_TURN_ADVANCES = 4

# A bag action -- item, ball (beyond its own shake rolls), or switch -- costs nothing itself.
BAG_ACTION_ADVANCES = 0

#: The most rolls one move can spend: an accuracy check, a crit roll and a damage roll, and a
#: secondary effect's proc roll (see ``battle_compass.sim.move_roll_cost``).
MAX_MOVE_ADVANCES = 4
#: One more if a status made the actor check whether it can move at all (R7 residual).
MAX_STATUS_CHECK_ADVANCES = 1
#: The wild mon's move-selection roll, spent at the top of the turn (R7 residual).
SELECTION_ADVANCES = 1


@dataclass(frozen=True)
class ActionCost:
    """One actor's contribution to a turn.

    ``rolls`` is what the action itself spends: 0 for a bag action, 1-4 for a ball (it stops on
    its first failed shake), or the move's own count.  ``successful_move`` adds the post-success
    advances, and is False for a bag action, a missed or failed move, and a turn where a status
    prevented the actor from moving.
    """
    rolls: int
    successful_move: bool = False

    @property
    def total(self) -> int:
        return self.rolls + (POST_SUCCESSFUL_MOVE_ADVANCES if self.successful_move else 0)


def turn_cost(first: ActionCost, second: ActionCost | None = None) -> int:
    """Total RNG advances for one turn.

    `second` is None when only one actor acts -- e.g. the opponent is fully paralyzed, or has
    fainted. The fixed advances are spent either way.
    """
    total = BEFORE_TURN_ADVANCES + first.total + BETWEEN_TURN_ADVANCES
    if second is not None:
        total += second.total
    return total + END_OF_TURN_ADVANCES


def ball_turn_cost(shakes: int, opponent: ActionCost | None = None) -> int:
    """A turn spent throwing a ball, by the shake count observed.

    Bag actions resolve before moves, so the ball is always the first actor -- which is also why
    a successful capture ends the battle before the opponent can attack, and why a heal always
    lands before the incoming hit regardless of Speed.
    """
    from claytonlib.battle.catch import rolls_consumed
    return turn_cost(ActionCost(rolls=rolls_consumed(shakes)), opponent)


def max_turn_advances() -> int:
    """An upper bound on the advances one turn can spend.

    The solver needs this to size the RNG horizon it scans for capture windows: a horizon of
    ``max_turns * max_turn_advances()`` is guaranteed to cover every roll the search could reach,
    which is what makes "no window in the horizon" a *proof* of unreachability rather than a
    guess.  Being a bound, it is deliberately loose -- both actors landing their worst case at
    once is not a turn that actually occurs.
    """
    worst_actor = MAX_STATUS_CHECK_ADVANCES + MAX_MOVE_ADVANCES + POST_SUCCESSFUL_MOVE_ADVANCES
    return (SELECTION_ADVANCES + BEFORE_TURN_ADVANCES + worst_actor + BETWEEN_TURN_ADVANCES
            + MAX_MOVE_ADVANCES + POST_SUCCESSFUL_MOVE_ADVANCES + END_OF_TURN_ADVANCES)


def shake_roll_offset(turn_start_offset: int, *, target_can_act: bool) -> int:
    """Where a ball thrown this turn takes its first shake roll.

    Bag actions resolve before moves, so a ball is always the turn's first actor and its shake
    rolls follow the four BeforeTurn advances directly -- but *after* the wild mon's
    move-selection roll, which is spent at the top of the turn whether or not that mon ends up
    moving.  So the offset is state-dependent, and the design doc's goal set of
    ``{window_start - BEFORE_TURN_ADVANCES}`` (sec 6.1) is an oversimplification: it is short by
    the selection roll whenever the target has a move with PP left, which for a full-PP Suicune
    is every turn of the hunt.

    This is why the solver treats capture windows as a *pruning* condition only and lets the
    simulator settle every actual throw.  `target_can_act` has no default for the same reason:
    there is no safe one.
    """
    offset = turn_start_offset + BEFORE_TURN_ADVANCES
    return offset + (SELECTION_ADVANCES if target_can_act else 0)
