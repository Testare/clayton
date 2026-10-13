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

from claytonlib.battle.damage import (
    item_key,
    ACCURACY_RAISING_ITEMS as _ACCURACY_RAISING_ITEMS,
    ACCURACY_REDUCING_ITEMS as _ACCURACY_REDUCING_ITEMS,
    LIGHT_CLAY as _LIGHT_CLAY,
    TYPE_ENHANCING_ITEMS as _TYPE_ENHANCING_ITEMS,
)
from claytonlib.moves import CATEGORY_STATUS, Move

# sec 1.1, measured by simulation over real LCRNG streams.
REACHABILITY_BY_DISTINCT_COSTS: dict[int, int] = {0: 0, 1: 36, 2: 95, 3: 99}
# Gen 4 paralysis quarters Speed [verified: `speed1 /= 4` in the speed comparison,
# src/battle/overlay_12_0224E4FC.c].  Kept as a float for the callers that report a margin;
# `battle_compass.sim.effective_speed` divides by `PARALYSIS_SPEED_DIVISOR` instead, because the
# ROM truncates at that step and the order it truncates in matters once a held item is involved.
PARALYSIS_SPEED_FACTOR = 0.25
PARALYSIS_SPEED_DIVISOR = 4

# --- speed-modifying held items --------------------------------------------------------------
#
# Transcribed from the speed comparison in src/battle/overlay_12_0224E4FC.c, and the ORDER is the
# point. It goes: stat stages, then the weather abilities, then the halving items, then the Choice
# Scarf, then Quick Powder, and only THEN paralysis. Every step truncates, so a scarfed and
# paralyzed Pokemon is `spe * 15 / 10 / 4` and not `spe / 4 * 15 / 10` -- the two disagree, and
# turn order is what the disagreement decides.
#
# The summary screen does not show any of this, so it has to be MODELLED rather than entered: a
# player reads 124 off a scarfed Magneton that is really moving at 186.
CHOICE_SPEED_ITEMS = frozenset(map(item_key, ("Choice Scarf",)))
#: Every Choice item, for the move LOCK rather than for Speed. All three lock
#: (`HOLD_EFFECT_CHOICE_ATK` / `_SPEED` / `_SPATK` in the ROM's check); only the Scarf is a Speed
#: modifier, which is why these are two sets rather than one.
CHOICE_ITEMS = frozenset(map(item_key, ("Choice Scarf", "Choice Band", "Choice Specs")))
#: `sSpeedHalvingItemEffects`: Macho Brace, Iron Ball and the six Power items.
SPEED_HALVING_ITEMS = frozenset(map(item_key, (
    "Macho Brace", "Iron Ball", "Power Weight", "Power Bracer", "Power Belt",
    "Power Anklet", "Power Lens", "Power Band",
)))
#: Lagging Tail and Full Incense do not touch Speed at all -- they set a lowered-priority flag, so
#: the holder moves last within its bracket. Named here so the distinction is written down
#: somewhere: `metronome_compass` mandates a Lagging Tail, and reading it as a Speed modifier
#: would be wrong in both directions.
MOVES_LAST_ITEMS = frozenset(map(item_key, ("Lagging Tail", "Full Incense")))
#: Leftovers' end-of-turn recovery is max HP / 16. The NAME lives here rather than in
#: `battle_compass.sim` (which owns the divisor and the tick itself) so that
#: `MODELLED_HELD_ITEMS` below can be assembled without the shared battle core importing from a
#: module that depends on it. `sim` imports it from here; a test asserts there is only one.
LEFTOVERS = "leftovers"


#: Held items whose behaviour the simulator actually models, grouped by the mechanism that reads
#: them. The union is the allowlist `unmodelled_held_items` checks against.
#:
#: Assembled rather than hand-listed, because a hand-list goes stale the first time somebody adds
#: a mechanism and forgets this -- and going stale here means *failing to warn*, which is the
#: direction that costs a run.
MODELLED_HELD_ITEMS: dict[str, frozenset[str]] = {
    "raises a matching move's power by 20%": frozenset(_TYPE_ENHANCING_ITEMS),
    "locks the holder into one move (and the Scarf is x1.5 Speed)": CHOICE_ITEMS,
    "halves the holder's Speed": SPEED_HALVING_ITEMS,
    "makes the holder move last in its bracket": MOVES_LAST_ITEMS,
    "cuts the attacker's accuracy": frozenset(_ACCURACY_REDUCING_ITEMS),
    "raises the holder's accuracy": frozenset(_ACCURACY_RAISING_ITEMS),
    "restores 1/16 max HP at end of turn": frozenset({item_key(LEFTOVERS)}),
    "extends a screen from five turns to eight": frozenset({item_key(_LIGHT_CLAY)}),
}

#: Items the simulator does NOT model whose absence fails in the Choice Scarf's *kind* rather
#: than its degree -- the roll COUNT or the turn ORDER changes, so nothing matches for the rest of
#: the run and the contradiction names a cause that did not happen.
#:
#: Separated from the generic "not modelled" message because the two call for different
#: decisions. A Life Orb produces one wrong HP and a visible contradiction on the turn it fires;
#: a Quick Claw silently re-orders a turn and poisons everything after it. The measured version
#: of that distinction is in clayton-957.10.15: removing the Choice Scarf from the hooh1 party
#: left 56 of 57 turns wrong, against 11 for the Silk Scarf and 2 for Leftovers.
HAZARDOUS_UNMODELLED_ITEMS: dict[str, str] = {item_key(k): v for k, v in {
    "Quick Claw": "randomly gives the holder priority -- it flips turn order AND spends a roll",
    "King's Rock": "adds a flinch chance to the holder's damaging moves -- an extra roll per hit",
    "Razor Fang": "adds a flinch chance to the holder's damaging moves -- an extra roll per hit",
    "Scope Lens": "raises the holder's crit stage -- the wrong crit modulus on every hit",
    "Razor Claw": "raises the holder's crit stage -- the wrong crit modulus on every hit",
    "Zoom Lens": "raises accuracy when the holder moves second, which is state-dependent",
}.items()}


def unmodelled_held_items(party: dict[str, str]) -> list[str]:
    """Warnings for ``{pokemon name: held item}`` entries the simulator cannot model.

    **Advisory, and it must stay that way.** A misconfigured held item genuinely should
    desynchronise the run -- the simulator is right once told, and there is no way to be told
    except by the player. What was missing is being told *before* the encounter rather than
    discovering it as a turn-2 contradiction whose message blames the candidate window
    (clayton-957.10.15).

    So this never blocks. A player who knows their Expert Belt is irrelevant to a False Swipe
    must be able to carry it and start.

    An EMPTY item is reported too, and deliberately: all three of the hooh1 party's items had to
    be inferred from the logs afterwards, because held items live on the hunt's party slot and
    the profile export carries none of them. "You left this blank" and "I cannot model this" are
    different sentences, so they are phrased differently.
    """
    allowed = frozenset().union(*MODELLED_HELD_ITEMS.values())
    out: list[str] = []
    for name, item in party.items():
        key = item_key(item or "")
        if not key:
            out.append(f"{name} has no held item recorded. If it is actually holding something, "
                       f"the simulation will be wrong from the first turn the item matters -- "
                       f"and if it is holding nothing, this is correct and can be ignored.")
            continue
        if key in allowed:
            continue
        hazard = HAZARDOUS_UNMODELLED_ITEMS.get(key)
        if hazard is not None:
            out.append(f"{name}'s {item} is NOT modelled, and it is the dangerous kind: it "
                       f"{hazard}. Nothing would match for the rest of the run, and the "
                       f"contradiction would blame the candidate window. Take it off.")
        else:
            out.append(f"{name}'s {item} is not modelled. If it changes anything in battle, the "
                       f"turn it fires on will contradict. Harmless if it is inert here.")
    return out


def speed_after_item(speed: int, held_item: str) -> int:
    """`speed` after a Speed-modifying held item, in the ROM's order: halve, then the Choice x1.5.

    The one implementation, shared by `battle_compass.sim.effective_speed` (which adds the stat
    stage before and paralysis after) and by the readiness check. They have to agree: the
    readiness check is what tells the player a tie is possible, and it was reading the Speed
    straight off the summary screen -- which does not include a Choice Scarf's boost. So it
    cleared a scarfed Lv70 Magneton at 124 when the figure that decides turn order is 186.
    """
    item = item_key(held_item)
    if item in SPEED_HALVING_ITEMS:
        speed //= 2
    if item in CHOICE_SPEED_ITEMS:
        speed = speed * 15 // 10
    return speed
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
    #: The target's Speed stage this row assumes. Carried so a caller can show the unboosted
    #: rows and hide the rest unless they are actually dangerous -- seven stages times two
    #: statuses is a table nobody reads.
    target_speed_stage: int = 0

    @property
    def margin(self) -> int:
        return self.our_speed - self.target_speed

    @property
    def is_tie(self) -> bool:
        return self.margin == 0

    @property
    def is_fragile(self) -> bool:
        return not self.is_tie and abs(self.margin) <= FRAGILE_SPEED_MARGIN

    @property
    def notable(self) -> bool:
        """Worth showing: the unboosted rows, plus any boosted one that ties or nearly does."""
        return self.target_speed_stage == 0 or self.is_tie or self.is_fragile


def target_speed_states(target_speed: int, *,
                        speed_stages: tuple[int, ...] = (0,)) -> dict[str, int]:
    """``label -> Speed`` for every state the target can be in, in the ROM's own order.

    **Stage first, then paralysis**, with integer truncation at each step -- the order in the
    speed comparison (src/battle/overlay_12_0224E4FC.c). It is what makes a Speed boost dangerous
    rather than merely annoying: stages multiply where paralysis divides, so **+6 cancels the
    quartering exactly** and a paralyzed target at +6 is back to its full figure. That is the
    no-speed-tie guarantee of sec 4.2 evaporating, and Ancient Power is in both Lv70 sets.

    Intermediate stages matter too, and not only as a path to +6: a tie can land at +2 and at no
    other stage, so every reachable one is enumerated rather than just the extremes.
    """
    from claytonlib.battle.damage import apply_stage

    out: dict[str, int] = {}
    for stage in sorted(set(speed_stages)):
        boosted = apply_stage(target_speed, stage)
        suffix = "" if stage == 0 else f" at +{stage} Spe"
        out[f"unaffected{suffix}"] = boosted
        out[f"paralyzed{suffix}"] = boosted // PARALYSIS_SPEED_DIVISOR
    return out


def speed_checks(our_speeds: dict[str, int], target_speed: int, *,
                 include_our_paralysis: bool = True,
                 target_speed_stages: tuple[int, ...] = (0,)) -> list[SpeedCheck]:
    """Every (our Pokemon x target state) speed comparison worth asserting on.

    Our own paralysis is included because it quarters our Speed, which can flip an order that
    looked safe — a case sec 11.4 only noticed after the fact.

    `target_speed_stages` is every Speed stage the target can reach. Pass ``(0,)`` for a target
    that cannot boost, and ``range(7)`` for one holding Ancient Power -- its 10% raises *every*
    stat, and the Speed half of that is what can claw back the paralysis we rely on.
    """
    stage_of = {}
    for stage in sorted(set(target_speed_stages)):
        suffix = "" if stage == 0 else f" at +{stage} Spe"
        stage_of[f"unaffected{suffix}"] = stage
        stage_of[f"paralyzed{suffix}"] = stage
    target_states = target_speed_states(target_speed, speed_stages=target_speed_stages)
    checks: list[SpeedCheck] = []
    for name, speed in our_speeds.items():
        our_states = {name: speed}
        if include_our_paralysis:
            our_states[f"{name} (paralyzed)"] = speed // PARALYSIS_SPEED_DIVISOR
        for our_label, our_speed in our_states.items():
            for state, their_speed in target_states.items():
                checks.append(SpeedCheck(ours=our_label, our_speed=our_speed,
                                         target_state=state, target_speed=their_speed,
                                         target_speed_stage=stage_of[state]))
    return checks


def speed_warnings(checks: list[SpeedCheck]) -> list[str]:
    """Human-readable problems: ties first, then fragile margins."""
    messages = []
    for check in checks:
        if check.is_tie:
            messages.append(
                f"{check.ours} ties the target's Speed when it is {check.target_state} "
                f"(both {check.our_speed}). A tie spends extra RNG rolls that are not "
                f"simulated, so the run would desynchronise — change a Speed stat."
                + _boost_note(check))
    for check in checks:
        if check.is_fragile:
            messages.append(
                f"{check.ours} is within {abs(check.margin)} of the target's Speed when it is "
                f"{check.target_state} ({check.our_speed} vs {check.target_speed}). One stat "
                f"point either way would tie or reverse the order."
                + _boost_note(check))
    return messages


def _boost_note(check: SpeedCheck) -> str:
    """Where a boosted row came from, so it does not read as an arbitrary hypothetical."""
    if check.target_speed_stage == 0:
        return ""
    extra = (" At +6 the boost cancels the quartering exactly, putting it back at full Speed."
             if check.target_speed_stage == 6 else "")
    return (f" This assumes the target has reached +{check.target_speed_stage} Speed, which its "
            f"Ancient Power can do one stage at a time (10% per use).{extra}")
