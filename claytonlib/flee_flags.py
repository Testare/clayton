"""flee_flags.py — per-candidate flee lookahead for Safari Compass Seed B's candidate table.

Once Seed B narrows to a small handful of candidates, each row can show what happens to
THAT specific candidate if the player repeats a given action from here — a candidate's
future is fully deterministic once its seed and the action sequence are fixed (there's no
RNG branching to explore, unlike machete's capture-path search over action CHOICES), so
this is a plain straight-line simulation, not a search.

"Flees within N turns via action A" means: repeating A starting now, this candidate's
SafariContext reaches FLED by turn N (1-indexed) without ever reaching CAPTURED first (a
capture is a good outcome, not a loss, so it doesn't count as "fleeing") and without still
being WATCHING past N.

Flag string format (draft2 feedback round 8): "F" + action-letter + turn-count, where the
action letter is "0" for ball (matching the compass grammar's own ball-shake digits — here
it just means "ball" generically, not a specific shake count), "b" for bait, "m" for mud, or
omitted entirely when EVERY action leads to a flee within the horizon (nothing you do avoids
it, for this candidate). The turn-count digit is itself omitted when it's exactly 1 ("this
turn") — so a ball flee on the very next action is "F0", not "F01"; the all-actions form for
the same case is bare "F". Two-plus-turn examples: "F03" (ball, 3 turns), "Fb2" (bait, 2
turns), "F2" (every action, 2 turns — the worst case across the three, since that's the
longest it could take depending which one the player actually throws).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

from claytonlib.safari import SafariContext

# action key -> (SafariContext method name, flag letter).
_ACTIONS = {"ball": ("throw_ball", "0"), "bait": ("throw_bait", "b"), "mud": ("throw_mud", "m")}

_ACTION_DESC = {"ball": "you throw a ball", "bait": "you use bait", "mud": "you use mud",
               "any": "you do anything"}


@dataclass(frozen=True)
class FleeFlag:
    action: str    # "ball" | "bait" | "mud" | "any" (every action leads to a flee)
    turns: int      # smallest N (1-indexed) this candidate flees within, for this action
    code: str       # the short flag string, e.g. "F03", "Fb2", "F2", "F0", "F"
    tooltip: str    # a plain-language explanation, e.g. for a table-cell title attribute


def _flee_turn(ctx: SafariContext, method: str, max_turns: int) -> int | None:
    """Simulate repeating `method` on a COPY of `ctx` for up to `max_turns` turns. Returns
    the turn (1-indexed) FLED is first reached, or None if it's captured instead, or if
    it's still watching after max_turns."""
    c = copy.copy(ctx)
    throw = getattr(c, method)
    for turn in range(1, max_turns + 1):
        throw()
        if c.captured():
            return None
        if c.has_fled():
            return turn
    return None


def _make_flag(action: str, turns: int, pokemon_name: str | None = None) -> FleeFlag:
    letter = "" if action == "any" else _ACTIONS[action][1]
    digits = "" if turns == 1 else str(turns)
    when = "this turn" if turns == 1 else f"in {turns} turns"
    name = pokemon_name or "It"
    return FleeFlag(action=action, turns=turns, code=f"F{letter}{digits}",
                    tooltip=f"{name} is guaranteed to flee {when} if {_ACTION_DESC[action]}.")


def compute_flee_flags(ctx: SafariContext, max_turns: int = 3, pokemon_name: str | None = None
                       ) -> list[FleeFlag]:
    """The flee flags for ONE candidate — one FleeFlag per action that leads to a flee
    (not a capture, not still-watching) within `max_turns` turns for THIS candidate
    specifically, plus a single combined "any" flag (using the worst-case turn count
    across all three) when ALL three actions lead to a flee — nothing the player does
    avoids it for this candidate, so listing all three separately would be redundant.
    `pokemon_name`, when given, is used in the tooltip text instead of the generic "It".
    Returns [] if no action leads to a flee within the horizon, OR if `ctx` isn't currently
    watching at all — a candidate's context can legitimately already be FLED/CAPTURED here
    even while the observed path is still ambiguous about it (app.safari_compass._apply_path
    keeps a "pending" action's result uncommitted, filter_fled=False, until the NEXT
    observation resolves whether it really fled — see that module's docstring); throwing
    anything against a non-watching context raises, so this must not even try.
    """
    if not ctx.is_watching():
        return []
    per_action: dict[str, int] = {}
    for action, (method, _letter) in _ACTIONS.items():
        t = _flee_turn(ctx, method, max_turns)
        if t is not None:
            per_action[action] = t

    if len(per_action) == 3:
        return [_make_flag("any", max(per_action.values()), pokemon_name)]
    return [_make_flag(action, per_action[action], pokemon_name)
           for action in ("ball", "bait", "mud") if action in per_action]
