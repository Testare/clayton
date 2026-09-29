"""Is this party actually able to win the hunt?

Two checks, both from notes/battle_compass.md, and both cheap enough to run on every keystroke
of a Hunt configuration screen.

**Action-alphabet diversity (sec 1.1) — the highest-leverage validation in the tool.**  A
capture is reachable within 40 turns for roughly 36% of seeds when the player has only one
filler action, ~95% with two of differing RNG cost, and ~99% with three.  The specific costs
barely matter; having *distinct* ones is what counts, because the action sequence is how the RNG
is steered onto a capture window.  A single-cost party is a fundamentally worse proposition and
the player should be told so before the encounter, not after.

**Speed ties (sec 11.4).**  A tie costs extra RNG rolls at several points in a turn, which the
simulator does not model — so a configuration where one is possible is unreliable rather than
merely suboptimal.  Margins are checked against the target both unaffected and paralyzed, and
against our own possible paralysis, since that quarters *our* Speed too.

Both results are estimates in one respect each, and say so: the per-move roll counts are derived
from move metadata rather than measured (R7), and the paralysis factor is the believed x0.25
(R8).  Neither affects the *shape* of the advice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from claytonlib.moves import CATEGORY_STATUS, Move

# sec 1.1, measured by simulation over real LCRNG streams.
REACHABILITY_BY_DISTINCT_COSTS: dict[int, int] = {0: 0, 1: 36, 2: 95, 3: 99}
# Gen 4 paralysis quarters Speed.  Believed, not yet confirmed against the emulator (R8).
PARALYSIS_SPEED_FACTOR = 0.25
# A margin this small or smaller is one or two stat points from flipping or tying.
FRAGILE_SPEED_MARGIN = 2


def estimated_move_rolls(move: Move) -> int:
    """Roughly how many RNG rolls executing `move` spends.

    Derived from move metadata, not measured: an accuracy roll when the move can miss, two more
    for a damaging move's crit and damage rolls, and one more for a secondary effect's proc
    roll.  `effects.py` holds the verified counts, but they live inside handler bodies rather
    than as a table, so extracting them is part of R7/the simulator work.  Until then this is
    good enough for the only thing it is used for: telling whether a party's costs *differ*.
    """
    rolls = 1 if move.accuracy > 0 else 0
    if move.category != CATEGORY_STATUS:
        rolls += 2
    if move.effect_chance > 0:
        rolls += 1
    return rolls


@dataclass
class AlphabetReport:
    """What per-turn RNG costs this party can produce."""

    costs_by_action: dict[str, int] = field(default_factory=dict)
    # Ball and item/switch costs are fixed by the mechanics, not by the party.
    includes_ball: bool = True
    includes_item: bool = True

    @property
    def distinct_costs(self) -> set[int]:
        costs = set(self.costs_by_action.values())
        if self.includes_item:
            costs.add(0)          # items and switches consume no advances of their own
        if self.includes_ball:
            costs.update({1, 2, 3, 4})   # a throw stops on its first failed shake
        return costs

    @property
    def reachability_percent(self) -> int:
        """Approximate share of seeds where a capture is reachable within 40 turns."""
        n = min(len(self.distinct_costs), 3)
        return REACHABILITY_BY_DISTINCT_COSTS[n]

    @property
    def warnings(self) -> list[str]:
        n = len(self.distinct_costs)
        if n >= 3:
            return []
        if n == 2:
            return ["This party offers only two distinct per-turn RNG costs, so a capture is "
                    "reachable for roughly 95% of seeds rather than ~99%. A third move with a "
                    "different cost (one with a secondary effect, say) would close the gap."]
        return ["This party offers only one distinct per-turn RNG cost, which makes a capture "
                "reachable for roughly 36% of seeds instead of ~99%. Bring moves whose RNG "
                "costs differ — a damaging move, a status move, and one with a secondary "
                "effect — or most encounters will be unwinnable no matter how long you stall."]


def alphabet_report(movesets: dict[str, list[Move]]) -> AlphabetReport:
    """Build a report from `{pokemon name: [Move, ...]}`.

    Every Pokemon's moves count, since the solver can switch between them in Phase 1 — but note
    Phase 2 never switches, so in practice the active Pokemon's own moves do the work.
    """
    costs = {f"{name}: {move.name}": estimated_move_rolls(move)
             for name, moves in movesets.items() for move in moves}
    return AlphabetReport(costs_by_action=costs)


@dataclass
class SpeedCheck:
    ours: str
    our_speed: int
    target_state: str
    target_speed: int

    @property
    def margin(self) -> int:
        return self.our_speed - self.target_speed

    @property
    def is_tie(self) -> bool:
        return self.margin == 0

    @property
    def is_fragile(self) -> bool:
        return not self.is_tie and abs(self.margin) <= FRAGILE_SPEED_MARGIN


def speed_checks(our_speeds: dict[str, int], target_speed: int, *,
                 include_our_paralysis: bool = True) -> list[SpeedCheck]:
    """Every (our Pokemon x target state) speed comparison worth asserting on.

    Our own paralysis is included because it quarters our Speed, which can flip an order that
    looked safe — a case sec 11.4 only noticed after the fact.
    """
    target_states = {
        "unaffected": target_speed,
        "paralyzed": int(target_speed * PARALYSIS_SPEED_FACTOR),
    }
    checks: list[SpeedCheck] = []
    for name, speed in our_speeds.items():
        our_states = {name: speed}
        if include_our_paralysis:
            our_states[f"{name} (paralyzed)"] = int(speed * PARALYSIS_SPEED_FACTOR)
        for our_label, our_speed in our_states.items():
            for state, their_speed in target_states.items():
                checks.append(SpeedCheck(ours=our_label, our_speed=our_speed,
                                         target_state=state, target_speed=their_speed))
    return checks


def speed_warnings(checks: list[SpeedCheck]) -> list[str]:
    """Human-readable problems: ties first, then fragile margins."""
    messages = []
    for check in checks:
        if check.is_tie:
            messages.append(
                f"{check.ours} ties the target's Speed when it is {check.target_state} "
                f"(both {check.our_speed}). A tie spends extra RNG rolls that are not "
                f"simulated, so the run would desynchronise — change a Speed stat.")
    for check in checks:
        if check.is_fragile:
            messages.append(
                f"{check.ours} is within {abs(check.margin)} of the target's Speed when it is "
                f"{check.target_state} ({check.our_speed} vs {check.target_speed}). One stat "
                f"point either way would tie or reverse the order.")
    return messages
