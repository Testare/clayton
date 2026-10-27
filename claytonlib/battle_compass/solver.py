"""Phase 2: steer the RNG until the capture ball captures.

Given an identified seed and a target at exactly 1 HP, find the sequence of actions whose ball
throw succeeds.  The target's HP never changes again, which is most of why the search is cheap
(notes/battle_compass.md sec 2.2) -- but ``b`` is NOT a single constant any more: a status can
be applied or wear off along a path, so `max_reachable_threshold` prices the prune at the most
generous figure any reachable status allows.  1 HP is the only precondition; burn and poison
are refused because their tick faints the target, not because a status is wanted.

**Windows prune; the simulator decides.**  Section 6.1 describes precomputing the offsets where
four consecutive rolls fall under ``b`` and then solving reachability to ``{w - 4}``.  The
precomputation is worth having, but that goal-set formula is an oversimplification: a ball's shake
rolls sit *after* the wild move-selection roll as well as the four BeforeTurn rolls, so their
offset depends on whether the target can still act.  Rather than encode a state-dependent offset,
:func:`capture_windows_in_horizon` is used as a **necessary condition** — no window in the horizon
means provably unreachable, worth knowing before searching — and every actual capture is settled
by running :func:`~claytonlib.battle_compass.sim.simulate_turn`, which is correct by construction.

**Distance, not turns** (sec 12.7).  Plain BFS minimises turns and will burn a Full Restore to
save one; plain cost minimisation plays forty extra turns to save a Potion.  One scalar prices
both: ``distance = BASE + floor(price / DIVISOR)``, so with the defaults a free action costs 15, a
Poke Ball 19, a Hyper Potion 45 — and one turn is worth up to ₽750.

**Failure is a result.**  Sustainability is a hard constraint rather than a warning (sec 6.2): a
path is returned only if it can actually be executed.  And because the horizon is intrinsic —
Suicune's own PP caps the battle — exhausting the search is a *proof* of unreachability rather
than a timeout, which is exactly the signal that justifies a soft reset (sec 6.3).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field, replace

from claytonlib.battle.catch import (
    BALL_POKE, catch_value, is_guaranteed, shake_threshold,
)
from claytonlib.battle.catch import capture_windows as _capture_windows
from claytonlib.battle import turn as turn_costs
from claytonlib.battle_compass import items
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.sim import (
    HuntConfig, advance, pending_future_sight, simulate_turn, unselectable_reason,
)
from claytonlib.battle_compass.state import (
    HP_TICKING_STATUSES, Action, BattleState, Status,
)
from claytonlib.safari import advance_rng

#: sec 12.7. Both tunable; distance stays an integer.
BASE_DISTANCE = 15
COST_DIVISOR = 50

#: HGSS prices, in pokedollars. Placeholders where the real table is not yet captured — the
#: distance function only needs their relative order to behave sensibly.
#: Prices from the shared item table, so the solver, the simulator and the run page cannot
#: disagree about what an item is or does (see ``battle_compass.items``).
ITEM_PRICES = items.PRICES
BALL_PRICE = 200


def distance_of(price: int, *, base: int = BASE_DISTANCE, divisor: int = COST_DIVISOR) -> int:
    """One action's distance: ``base + floor(price / divisor)``."""
    if price < 0:
        raise ValueError(f"price cannot be negative: {price}")
    return base + price // divisor


#: Turns to search per point of the target's remaining PP. A fully-paralyzed turn costs the
#: target no PP, so the battle outlasts its PP total -- by 4/3 on average at a 25% full-paralysis
#: rate, and by more than that in practice because the solver can prefer paths that proc it.
#: 2.5 leaves room for that without searching so far that the estimate carries real weight; the
#: per-path cutoff below is exact, so this only sizes the search.
TURNS_PER_PP = 2.5


@dataclass(frozen=True)
class SolverConfig:
    """What the search optimises and what it refuses to do."""
    base_distance: int = BASE_DISTANCE
    cost_divisor: int = COST_DIVISOR
    #: Heal when our HP is at or below this. The worst single hit the target can land, so the
    #: bound holds without knowing which move is coming (sec 11.2). Bag actions resolve before
    #: moves, so a heal always lands before the incoming hit regardless of Speed.
    danger_floor: int = 0
    #: A hard ceiling on the search, whatever `struggle_deadline` estimates. The search stops at
    #: whichever is lower, and says which one bound it.
    max_turns: int = 300
    #: Turns to search per point of the target's remaining PP; see `TURNS_PER_PP`.
    turns_per_pp: float = TURNS_PER_PP
    #: Guards a runaway search rather than the battle; exhausting the horizon above is the real
    #: stopping condition.
    max_states: int = 200_000
    #: Visit each RNG offset once, at its cheapest arrival. Whether a throw captures depends
    #: ONLY on the offset, so the goal test is exact under this reduction.
    #:
    #: It remains a heuristic for *reaching* offsets, and more so since field conditions were
    #: modelled: a dearer arrival can carry resources a later turn needs, and two arrivals at one
    #: offset can disagree about rain, mist or the target's PP -- which decides whether the
    #: target's next move fails, and so which offset the next turn lands on. The exhaustive path
    #: (`collapse_offsets=False`) keys those into `_dominance_key` instead. In practice the
    #: cheapest arrival used fewer and cheaper actions and tends to be better-resourced too.
    #: `Unreachable.proven` reflects which search ran.
    collapse_offsets: bool = True
    #: Which of our move slots the solver may use as filler.
    allowed_moves: tuple[int, ...] = (0, 1, 2, 3)
    #: Standard balls are provably safe once the seed is known -- the capture ball failing
    #: implies a standard ball fails -- so they are free filler (sec 12.5).
    allow_standard_balls: bool = True


def remaining_target_pp(target) -> int:
    """The target's PP left, summed over slots that hold a move.

    *Remaining*, not total: by the time Phase 2 begins the target has already spent PP on the
    turns that identified the seed, so a total-PP figure would overstate the battle left.
    """
    return sum(target.pp_left(slot) for slot in range(len(target.moves))
               if target.move(slot) is not None)


def struggle_deadline(target, turns_per_pp: float = TURNS_PER_PP) -> int:
    """How many turns to search before the target must be out of PP.

    Past its PP the target Struggles, and at 1 HP the recoil kills it -- losing the legendary
    outright (sec 4.4).  The simulator does not model Struggle: with no usable slot it spends no
    roll and deals no damage, so such a turn is silently wrong rather than visibly unsupported.

    **This is an estimate, and it is not what actually enforces the deadline.** How many turns
    the PP lasts depends on the RNG path itself -- every full-paralysis turn is a free one -- so
    there is no turn count that bounds the battle from the outside.  The exact cutoff is applied
    per path instead: a state whose target has no usable move is never expanded, because the
    next turn would be Struggle.  This figure only sizes the search, which is why erring high
    is safe and why exhausting it is not a proof of anything about the seed.
    """
    return int(remaining_target_pp(target) * turns_per_pp)


@dataclass(frozen=True)
class Step:
    action: Action
    tokens: tuple[str, ...]
    distance: int
    #: The item the tiering chose, if this was an item turn.
    item: str | None = None

    @property
    def rendered(self) -> str:
        return tok.render_turn(tok.normalise(self.tokens))


@dataclass
class Solution:
    steps: list[Step]
    total_distance: int
    states_explored: int

    @property
    def turns(self) -> int:
        return len(self.steps)

    def rendered(self) -> str:
        return tok.render_path([list(step.tokens) for step in self.steps])

    def item_bill(self) -> dict[str, int]:
        """How many of each item the path spends, for the inventory check."""
        bill: dict[str, int] = {}
        for step in self.steps:
            if step.item:
                bill[step.item] = bill.get(step.item, 0) + 1
        return bill


@dataclass
class Unreachable:
    """Why no path was found — and how much that tells you about the seed.

    Read `proven` before acting on this. A soft reset is only clearly right when the search was
    complete; otherwise the result is a limit of the search, not a fact about the seed (sec 6.3).

    ``capture_windows`` is the trap this class exists to label. A window is a *target* -- four
    consecutive rolls under ``b`` at some RNG offset -- and nothing more. Whether any action
    sequence can arrive at one holding a ball is exactly the question the search answers, so a
    large window count alongside no path is the ordinary outcome. Do not read it as "nearly
    reachable".
    """
    reason: str
    #: True when every action sequence was tried *within* ``searched_turns``: the complete
    #: search (``collapse_offsets=False``), not cut short by the state cap. False whenever the
    #: search was narrowed or gave up, in which case it says nothing about the seed at all.
    #:
    #: Even True is a bounded claim. There is no provable turn bound on the battle -- every
    #: full-paralysis turn costs the target no PP, so no finite budget covers every branch --
    #: so this means "no capture within ``searched_turns`` turns", never "this seed is hopeless
    #: forever". ``searched_turns`` is 2.5x the target's remaining PP by default, which the
    #: battle exceeds only astronomically rarely, but rarely is not never.
    proven: bool
    states_explored: int
    #: Capture windows found in the horizon. Targets, not reachable ones -- see above.
    capture_windows: int = 0
    #: The turn budget actually searched.
    searched_turns: int = 0
    #: Whether any branch ended because the target would have had to Struggle -- the one exact
    #: deadline in the model.
    #: True when at least one branch ended because the target would have had to Struggle. That
    #: is the one exact deadline in the model -- unlike the turn ceiling, it is not an estimate.
    stopped_at_struggle: bool = False


def capture_windows_in_horizon(seed: int, threshold: int, advances: int) -> list[int]:
    """Offsets within `advances` where four consecutive rolls all fall under `threshold`.

    A necessary condition for a capture, used to reject a hopeless seed before searching. At
    ``b = 21845`` these are dense — roughly one offset in 79 — so an empty result over a real
    horizon is a strong signal rather than a near miss (sec 1).
    """
    rolls = []
    state = seed
    for _ in range(advances + 4):
        state, roll = advance(state)
        rolls.append(roll)
    return _capture_windows(rolls, threshold)


def target_threshold(state: BattleState, config: HuntConfig,
                     status: Status | None = None) -> int:
    """``b`` for the capture ball against this target, **at one moment**.

    It used to be documented as constant for the whole of Phase 2, which was true while the only
    permitted status was permanent paralysis. It is not true now that sleep is permitted: sleep
    expires, and a woken target has a smaller ``b`` than a sleeping one. The throw itself has
    always been settled by `sim.simulate_turn`, which reads the status at that instant, so the
    GOAL test was never affected -- but a single `b` used to prune the search was.

    `status` overrides the target's own, for asking what ``b`` *would* be in some other state.
    """
    from claytonlib.battle_compass.sim import _status_bonus
    # The ball is asked what it is worth ON THIS TURN, not in general: a Quick Ball is x4 only
    # while `state.turn` is 0 and a Timer Ball climbs with it, so a `b` computed turn-blind would
    # be wrong in opposite directions for the two of them.
    effect = config.ball_effect_at(state.turn)
    a = catch_value(effect.catch_rate,
                    ball_multiplier=effect.multiplier,
                    cur_hp=max(state.target.hp, 1), max_hp=state.target.max_hp,
                    status_bonus=_status_bonus(status or state.target.status))
    return shake_threshold(a)


def statuses_we_can_apply(state: BattleState, config: "SolverConfig") -> set[Status]:
    """Non-volatile statuses our own permitted moves could still inflict, given the PP left.

    Separate from `reachable_statuses`, which is a deliberate over-estimate for the window
    prune. This one has to be exact, because `solve` decides whether to refuse on it.
    """
    from claytonlib.battle_compass.sim import status_applied_by

    out: set[Status] = set()
    for slot in config.allowed_moves:
        move = state.ours.move(slot)
        if move is None or state.ours.pp_left(slot) <= 0:
            continue
        inflicted = status_applied_by(move)
        if inflicted is not None:
            out.add(inflicted)
    return out


def reachable_statuses(state: BattleState, config: "SolverConfig") -> set[Status]:
    """Every status the target could hold at some point in a path from `state`.

    Its current one; NONE, because sleep and freeze wear off; and anything our own permitted
    moves can inflict once it is unstatused. Nothing else -- the target cannot status itself, and
    no item of ours does.
    """
    return {state.target.status, Status.NONE} | statuses_we_can_apply(state, config)


def max_reachable_threshold(state: BattleState, hunt: HuntConfig,
                            config: "SolverConfig") -> int:
    """The largest ``b`` any turn of any path from `state` could throw against.

    This is the threshold the window precomputation must use, and using the *entry* state's
    instead is unsound in one direction that matters. Against a paralyzed Latias, ``b`` is 33824
    awake-and-paralyzed and 36157 asleep; a prune at the smaller figure can report "no four
    consecutive rolls fall under b" -- with ``proven=True`` -- while a Spore-then-throw path
    exists at the larger one. And ``proven=True`` is the signal that justifies a soft reset
    (sec 6.3), so an unsound proof does not merely lose a path, it costs the player the run.

    Taking the maximum keeps the precondition *necessary*, which is all it has to be: a window
    that only exists at some other status is a false positive, and the search settles every
    actual throw with `simulate_turn` anyway.
    """
    return max(target_threshold(state, hunt, status)
               for status in reachable_statuses(state, config))


def choose_item(state: BattleState, config: SolverConfig) -> tuple[str, int] | None:
    """Which item ``USE_ITEM`` resolves to, and its price (sec 12.2).

    Deterministic, which is the whole point: since every item costs zero RNG advances, branching
    on *which* item to use would multiply the search for no reachability gain. One action, one
    answer.

    Decided from the danger floor rather than the exact incoming damage, because the tier has to
    be known before the turn is simulated. Conservative in the right direction — it heals
    slightly too eagerly rather than too late.
    """
    hp, max_hp = state.ours.hp, state.ours.max_hp

    def usable(code: str) -> bool:
        """Whether the game would let us select it -- a Potion at full HP, it would not.

        Checked here as well as in the simulator because this is what PICKS the item, and the
        simulator now raises on an unusable one. The two meet in the case where the danger floor
        exceeds our max HP: we are then "in danger" at full health, and the old unconditional
        Hyper Potion would have been planned, simulated, and refused mid-search.
        """
        return items.unusable_reason(
            code, hp=hp, max_hp=max_hp,
            statused=state.ours.status is not Status.NONE) is None

    if hp <= danger_floor_for(state, config) and usable("hp"):
        # Nothing mitigates a critical hit, so a full heal is the only answer here (sec 12.3).
        return "hp", ITEM_PRICES["hp"]
    if state.ours.spdef_stage < 6:
        # X Sp. Def cuts chip damage but not crits, so it defers heals without moving the floor.
        return "xsd", ITEM_PRICES["xsd"]
    if usable("p"):
        return "p", ITEM_PRICES["p"]
    for code in ("xd", "gs"):
        return code, ITEM_PRICES[code]
    return None


def danger_floor_for(state: BattleState, config: SolverConfig) -> int:
    """The floor to heal at, computed from THIS state rather than once per session.

    `HuntSession` takes `worst_incoming_hit` once at construction and hands it over as
    `SolverConfig.danger_floor`. That was right while nothing could move it; it is wrong now in
    both directions (clayton-957.10.5):

    * **Upward.** Ancient Power raises every one of the target's stats 10% of the time, Attack
      included, and a floor read before that proc understates the next hit.
    * **Downward.** Intimidate and Charm take the target to -1 and then -5, which roughly halves
      every physical hit -- and a floor frozen at entry keeps collapsing `_legal_actions` to
      item-only at HP values that are comfortably safe. That collapse is the whole of
      clayton-957.10.1's symptom.

    So the figure is recomputed from the live stages. `config.danger_floor` survives as a lower
    bound: a caller that deliberately set a floor (or a test that pins one) still gets at least
    it, and the upward enumeration in `worst_incoming_hit` does the rest.

    **Weather is enumerated here and nowhere else.** The solver's only use for this figure is
    `choose_item` deciding between a full heal and cheap filler, and healing against a rain that
    has not happened yet is the safe direction to be wrong in -- the thing that actually stops
    the search walking into a KO is the exact per-action faint test in `solve`. The LIVE
    indicator must not do this, because a Rain Dance the target has not used is not a hit it can
    land this turn (clayton-5rz).

    **One term is not a worst case at all**, and it is the only one: a banked Future Sight landing
    at the end of this turn is damage already decided, and it stacks on top of whatever the target
    does with its turn. So it is ADDED rather than maxed in, and the live indicator adds it too --
    unlike the weather, there is nothing hypothetical about it (`sim.pending_future_sight`).
    """
    from claytonlib.battle_compass.hunt_session import worst_incoming_hit

    # A banked Future Sight ADDS to the floor rather than competing with it. The target still
    # takes its ordinary turn on the turn the Future Sight lands, so the HP one turn can cost is
    # the worst single hit PLUS the stored figure -- and `max` priced only the larger of the two
    # (clayton-6xu.7.3). See `pending_future_sight` for why it is the full figure and why it is
    # keyed on the counter reaching 1.
    return max(config.danger_floor,
               worst_incoming_hit(state.ours, state.target, field=state,
                                  any_reachable_weather=True)) + pending_future_sight(state)


def ends_the_run(move) -> bool:
    """Whether using `move` would end the wild battle with the target uncaught.

    Teleport and Roar, and both are a level-up move on a party member the Ho-Oh plan requires
    rather than a hypothetical: Natu learns Teleport at L9 and is the Synchronize lead, Granbull
    learns Roar at L27 on the way to the Lv35 it needs. See `sim.RUN_ENDING_EFFECTS`.

    Worse than `can_faint_target`, which this sits beside: a KO costs the Pokemon and a flee costs
    the encounter. `unsupported_our_moves` already reports both as unmodelled, but a report is
    advice and this is a refusal -- the solver must not be able to plan one even if the player
    leaves it in the moveset.
    """
    from claytonlib.battle_compass.sim import RUN_ENDING_EFFECTS

    return move is not None and move.effect in RUN_ENDING_EFFECTS


#: Stages that are in OUR favour, as ``(whose, field, the sign that helps us)``.
#:
#: Haze resets every stage on both sides, so whether it helps or hurts is entirely a question of
#: which of these are currently nonzero. Spelled out rather than inferred because the direction
#: differs per stage and getting one backwards would refuse Haze exactly when it is wanted: the
#: target's lowered ACCURACY helps us, its raised EVASION hurts us, and those are adjacent fields
#: on the same object.
_STAGES_IN_OUR_FAVOUR: tuple[tuple[str, str, int], ...] = (
    # The target's, lowered: six Flashes are the biggest accuracy investment a run makes, and
    # permanent, because a wild target never switches out.
    ("target", "accuracy_stage", -1),
    # Ours, raised: X Sp. Def is `choose_item`'s preferred filler, so after one filler turn this
    # is nonzero in most plans -- which is why the solver stops planning Haze almost immediately.
    ("ours", "spdef_stage", +1),
    ("ours", "atk_stage", +1),
    ("ours", "def_stage", +1),
    ("ours", "spatk_stage", +1),
    ("ours", "speed_stage", +1),
    ("ours", "accuracy_stage", +1),
    ("ours", "evasion_stage", +1),
)


def undoes_our_own_work(move, state: BattleState) -> str | None:
    """Why the solver must not PLAN `move` from this state, or None if it may.

    Haze, and only Haze. The move itself spends no rolls, so a Haze turn costs 2 -- just the
    post-successful-move block -- against Flash's 3 and Taunt's 4, which makes it the cheapest
    move in the alphabet and Dijkstra's favourite. And it resets **both** sides' stages. Left unchecked the solver plans it as free filler and silently throws away the Flash
    accuracy work and the X Sp. Def stacks it spent earlier turns building, which is incoherent:
    a plan that undoes its own earlier moves.

    **A solver refusal, not a `sim.unselectable_reason` one**, and the distinction is the point.
    `unselectable_reason` is for moves the simulator would MIS-PREDICT, and it also disables the
    move in the interview and reports it as a coverage gap. Haze is modelled exactly; it is
    merely self-defeating as *filler*. There are real states where losing the accuracy work is
    the right trade -- a Giratina at +6 from Ancient Power, an Azelf two Nasty Plots in -- and
    those are the player's call to make on the turn, which is why this refuses the PLAN and
    leaves the move fully available to the interview.

    State-dependent rather than a blanket ban, because from a state with no stages in play Haze
    genuinely is harmless zero-cost filler and there is no reason to forbid it. In practice
    `choose_item` stacks X Sp. Def from the first filler turn onward, so this refuses it from
    turn two of most plans.
    """
    from claytonlib.battle_compass.sim import EFFECT_HAZE

    if move is None or move.effect != EFFECT_HAZE:
        return None
    lost = [f"{whose} {field}" for whose, field, helpful in _STAGES_IN_OUR_FAVOUR
            if getattr(getattr(state, whose), field) * helpful > 0]
    if not lost:
        return None
    return (f"{move.name} would reset every stage on both sides, including "
            f"{', '.join(lost)}, which earlier turns spent to get.")


def can_faint_target(move, ours, target, *, field=None) -> bool:
    """Whether `move` could knock the target out -- on any roll, crit included.

    The guard the solver never had (clayton-957.10.4). `_legal_actions` offered every slot in
    `allowed_moves`, which defaults to all four, and **at 1 HP every damaging move is lethal** --
    so the solver could propose, as filler, the move that ends the run. It went unnoticed through
    v1 because Suicune's Phase 2 Pokemon was a Smeargle whose only attack is False Swipe.

    What makes it concrete: Ho-Oh is Fire/Flying, so Electric is 2x, and an Ampharos with 336
    Sp. Atk does 222-264 with Discharge against a 250 HP Ho-Oh -- a KO from FULL HP on the top
    rolls, let alone at 1. Even Signal Beam's resisted 17-20 kills at 1 HP. There is no safe
    damaging move against a target on 1 HP except one that *cannot* reduce it further.

    Deliberately pessimistic in three ways, because a false positive costs one filler action and a
    false negative costs the hunt:

    * the **maximum** roll, not the minimum;
    * **critical**, since a crit can KO where a normal hit would not;
    * and an unmodellable move counts as dangerous rather than safe.

    The exception is effect 101 -- False Swipe's floor at 1 HP, which the simulator already
    applies. That is what keeps it available as unlimited Phase 2 filler.
    """
    from claytonlib.battle.damage import (
        Attacker, Defender, damage_range, unsupported_attacker_reason, unsupported_reason,
    )
    from claytonlib.battle_compass.sim import (
        FALSE_SWIPE_EFFECT, variable_base_power, weather_of,
    )
    from claytonlib.moves import CATEGORY_STATUS

    if move is None or move.category == CATEGORY_STATUS:
        return False
    if move.effect == FALSE_SWIPE_EFFECT:
        return False
    attacker = Attacker(
        level=ours.level, attack=ours.stats["atk"], special_attack=ours.stats["spa"],
        types=ours.types, attack_stage=ours.atk_stage,
        special_attack_stage=ours.spatk_stage, ability=ours.ability,
        held_item=ours.held_item)
    base_power = variable_base_power(move, target)
    if (unsupported_reason(move, power_known=base_power is not None) is not None
            or unsupported_attacker_reason(attacker) is not None):
        return True           # cannot price it, so cannot promise it is safe
    _, high = damage_range(
        move, attacker,
        Defender(defence=target.stats["def"], special_defence=target.stats["spd"],
                 types=target.types, defence_stage=target.def_stage,
                 special_defence_stage=target.spdef_stage,
                 # A Foresight already landed makes a Normal move lethal that was harmless
                 # before it. Without this the check answered "safe" for a False Swipe-less
                 # Normal attacker against an identified Ghost, which is the one direction this
                 # function must never be wrong in.
                 identified=target.identified),
        base_power=base_power, critical=True, weather=weather_of(field))
    return high >= target.hp


def holds_target_hp(move, state: BattleState) -> bool:
    """Whether playing `move` leaves the target's HP exactly where it is.

    **The invariant Phase 2 runs on, and the reason it can run at any HP at all.** `b` is computed
    from the target's current HP (`target_threshold`), and `max_reachable_threshold` maximises over
    every status a path can reach but *not* over every HP -- so a plan that lowered the target's HP
    could reach a larger `b` than the window precomputation priced, and pruning at the smaller
    figure can prove unreachability that the larger one disproves. That is the same unsoundness the
    status version of this gate was fixed for, and `proven=True` is what justifies a soft reset, so
    an unsound proof costs the player the run rather than a path.

    Rather than teach the precomputation to maximise over HP as well, Phase 2 simply does not
    move it: **chipping is Phase 1's job**, which is player-driven and already where it happens.
    So this is a narrowing of the filler alphabet, not a loss of a capability.

    At 1 HP it changes nothing, which is what keeps every pre-existing run bit-for-bit identical:
    False Swipe's floor (effect 101) already made it deal exactly 0 there, so it stayed legal as
    unlimited filler and still does.

    Two kinds of move hold the line:

    * a status move, which deals no damage at all; and
    * a damaging move the target is **immune** to, which the type chart zeroes -- a False Swipe at
      an unidentified Giratina is a genuine constant-cost filler, and refusing it would be refusing
      a turn the game plays perfectly happily.
    """
    from claytonlib.battle_compass.sim import FALSE_SWIPE_EFFECT, deals_nothing
    from claytonlib.moves import CATEGORY_STATUS

    if move is None or move.category == CATEGORY_STATUS:
        return True
    if deals_nothing(move, state.target, state.ours):
        return True
    # False Swipe at 1 HP: the floor makes it deal exactly zero, so it moves nothing.
    return state.target.hp <= 1 and move.effect == FALSE_SWIPE_EFFECT


def _legal_actions(state: BattleState, config: SolverConfig,
                   hunt: HuntConfig) -> list[tuple[Action, int, str | None]]:
    """(action, distance, item) triples available from `state` — sec 12.5's seven actions.

    ``SWITCH`` is absent: Phase 2's precondition guarantees the right Pokemon is already active,
    so the solver never weighs switching against an item.
    """
    out: list[tuple[Action, int, str | None]] = []
    dist = lambda price: distance_of(price, base=config.base_distance,
                                     divisor=config.cost_divisor)

    # If a capture is available this turn it is the only thing worth doing.
    if simulate_turn(state, Action.CAPTURE_BALL, hunt).captured:
        return [(Action.CAPTURE_BALL, dist(0), None)]

    item = choose_item(state, config)
    if item is not None:
        out.append((Action.ITEM, dist(item[1]), item[0]))

    # **There is no "in danger" collapse here any more, and there never should have been.**
    #
    # This used to read `if state.ours.hp <= danger_floor: return out` -- only an item, on the
    # reasoning that nothing else can prevent the faint. Two things are wrong with that.
    #
    # It is redundant. `solve` already discards every successor with `nxt.faints >
    # current.faints`, which is an EXACT per-action test against the known stream: in Phase 2 the
    # seed is identified, so whether a given action faints us this turn is computed, not estimated.
    # The floor is a bound on what the target *could* do; the simulator knows what it *will* do.
    #
    # And it is ruinous whenever the floor exceeds our max HP, which is the common case rather
    # than a corner: a Sacred Fire crit is 573 against Smeargle's 153 and no amount of levelling
    # closes that. `in_danger` was then permanently true, so the only action ever offered was an
    # item, no ball was ever legal, and the run reported Unreachable for a reason that had nothing
    # to do with capture windows (clayton-957.10.1). The guard was refusing to play at all over a
    # risk of roughly 1.1% per turn -- a 1/4 move choice, a ~31% hit through six Flashes and a
    # 1/16 crit -- and refusing it on every turn, including the turns where the stream says
    # plainly that nothing hits us.
    #
    # So the floor keeps the one job it is actually good at: `choose_item` reads it to decide
    # whether to reach for a full heal rather than cheap filler. What it no longer does is veto
    # the rest of the alphabet on a hypothetical.

    # `usable_slots` rather than the raw slot list, because it is what honours a Choice lock: a
    # scarfed paralyzer is locked into Thunder Wave the moment it uses it, and planning one of
    # its other three moves is planning a turn the game will refuse.
    usable = state.ours.usable_slots()
    for slot in config.allowed_moves:
        if slot not in usable:
            continue
        move = state.ours.move(slot)
        if can_faint_target(move, state.ours, state.target, field=state):
            continue
        # ...and a move that merely CHIPS the target is out too, above 1 HP. Not because it is
        # dangerous -- `can_faint_target` has already taken the dangerous ones -- but because it
        # would move `b` out from under the window precomputation. See `holds_target_hp`, which
        # is also why this is a no-op for every run that reaches Phase 2 at 1 HP.
        if not holds_target_hp(move, state):
            continue
        if ends_the_run(move):
            continue
        # A move the simulator cannot model. `allowed_moves` defaults to all four and nothing
        # ever narrowed it, so this was a real hole rather than a belt-and-braces guard:
        # `MODELLED_OUR_EFFECTS` has said since it was written that the caller should "keep the
        # slots out of `SolverConfig.allowed_moves`", and no caller did -- so the solver could
        # plan a Whirlpool as filler and the plan would desynchronise on the turn it ran.
        #
        # Enforced here rather than left to `allowed_moves` for the same reason `ends_the_run` is:
        # a caller that forgets gets the safe behaviour, and a caller that deliberately widens
        # `allowed_moves` still cannot reach a move the simulator would mis-predict.
        if unselectable_reason(move, state.target) is not None:
            continue
        # Soundly modelled but self-defeating as filler -- see `undoes_our_own_work`, and note
        # this deliberately does NOT reach the interview.
        if undoes_our_own_work(move, state) is not None:
            continue
        out.append((getattr(Action, f"MOVE_{slot + 1}"), dist(0), None))
    if config.allow_standard_balls:
        out.append((Action.STANDARD_BALL, dist(BALL_PRICE), None))
    return out


def _dominance_key(state: BattleState) -> tuple:
    """What makes two states at the same RNG offset comparable.

    Keyed on the offset because it increases monotonically and is the dominant coordinate; the
    rest is what a later turn's cost depends on (sec 12.8).

    The field conditions and the target's PP belong here, not in `_dominates`: they are not
    better-or-worse, they change which of the target's moves *fail*, and a failing move costs the
    turn two fewer advances. Two states at the same offset that disagree about rain are therefore
    not interchangeable at all -- one of them will reach a different offset next turn. Verified
    against data/battle_logs/test1.jsonl, where exactly this cost Suicune's Rain Dance its
    post-move advances on turns 3 and 12.
    """
    return (state.rng_offset, state.rain_turns > 0, state.mist_turns > 0,
            state.target_trapped, state.target_water_sport,
            # Safeguard, for exactly the reason rain and mist are here: while it is up our
            # status moves FAIL, and a failing move costs the turn two fewer advances -- so two
            # states at one offset that disagree about it reach different offsets next turn.
            state.safeguard_turns > 0,
            # Remaining sleep, for the same reason as the field conditions: one of two states
            # that disagree about it wakes sooner, and from that turn on spends different
            # advances. The status itself is in here too, since waking changes it.
            state.target.status, state.target.sleep_turns, state.target.pp,
            # Screens, for the same reason as the field conditions above: a second one FAILS, and
            # a failing move costs the turn two fewer advances.
            state.reflect_turns > 0, state.light_screen_turns > 0,
            # The target's accuracy stage, because it decides whether the target's own move can
            # miss -- and a miss spends fewer rolls than a hit, so two states that disagree about
            # it reach different offsets next turn. Its Attack stage is NOT here: it changes how
            # hard the target hits, which `_dominates` already weighs through our HP, not how many
            # advances the turn costs.
            state.target.accuracy_stage,
            # The target's HP, because `b` is computed from it: two states at one offset that
            # disagree about it are not interchangeable, and it is not better-or-worse either --
            # lower HP is a bigger `b` but also fewer legal filler moves, so it belongs in the
            # KEY rather than in `_dominates`.
            #
            # Constant along any path `_legal_actions` will build (`holds_target_hp`), so this
            # costs nothing today. It is here so the invariant is enforced by the search rather
            # than assumed by it -- if a future change lets a plan chip, the search stays correct
            # instead of silently merging states with different capture odds.
            state.target.hp,
            # **The target's move LOCKS, because a locked battler spends no selection roll.**
            # `Battler_CanPickCommand` returns FALSE while it is mid-charge or mid-Uproar
            # (battle_lib.c:6225-6236), so `select_target_move` skips the roll entirely -- which
            # means two states at one offset that disagree about the lock reach DIFFERENT offsets
            # next turn. That is exactly the argument the field conditions above are here for.
            #
            # Reachable: Giratina can Shadow Force during Phase 2 and Azelf can be mid-Uproar, so
            # merging a charging state with a non-charging one would have the search plan against
            # an advance count the battle does not spend. `uproar_slot` joins `uproar_turns`
            # because it decides WHICH move fires, and the two moves need not cost the same.
            #
            # Our own side is deliberately absent: nothing a party may carry has a charge or an
            # Uproar (`MODELLED_OUR_EFFECTS` omits 272 and 159), so a row for it could never fire.
            state.target.charging_slot,
            state.target.uproar_turns,
            state.target.uproar_slot)


def _dominates(a: BattleState, a_dist: int, b: BattleState, b_dist: int) -> bool:
    """Whether `a` is at least as good as `b` in every respect that matters."""
    return (a_dist <= b_dist
            and a.ours.hp >= b.ours.hp
            and a.ours.spdef_stage >= b.ours.spdef_stage
            and all(x >= y for x, y in zip(a.ours.pp, b.ours.pp)))


def solve(state: BattleState, hunt: HuntConfig,
          config: SolverConfig | None = None) -> Solution | Unreachable:
    """Cheapest path to a capture, or why there is none.

    Dijkstra over :func:`distance_of`, with memoisation on the RNG offset and dominance pruning:
    among states at the same offset, one with no less HP, no worse stat stages, no less PP and no
    greater accumulated distance makes the other pointless to explore.
    """
    config = config or SolverConfig()
    # **Any HP, not just 1.** The precondition is that the target's HP is KNOWN and that the plan
    # does not change it -- not that it is 1. The capture arithmetic never assumed 1: `throw_ball`
    # and `target_threshold` both read `cur_hp` off the live state, so `b` has always been
    # computed from whatever HP the target actually has.
    #
    # This is the third time this gate has relaxed, and each time for the same reason. It began as
    # "1 HP and permanently paralyzed", which made `b` a single constant (sec 2.2). Sleep broke the
    # constant and the solver was taught to cope. Then "some holding status" went, because a target
    # we cannot status is not unreachable, only a smaller `b`. HP is that argument once more: a
    # target at full HP is not unreachable, only a smaller `b`, and the window search simply runs
    # at the smaller figure.
    #
    # For these Platinum targets it is not even smaller. Dialga and Palkia are catch rate 30 and
    # Shaymin 45, so full HP asleep in a Dusk Ball is b=47661 and b=52428 against 33824 for
    # Suicune at 1 HP in the same ball. And Dialga **cannot reach 1 HP at all** with a Smeargle:
    # Steel resists False Swipe, and Pressure halves 40 PP to 20 uses against the 20-27 hits it
    # needs (notes/battle_compass_dialga_palkia_shaymin.md sec 4A).
    #
    # What the relaxation costs is the chip phase as *filler*: `_legal_actions` now refuses a move
    # that would move the target's HP, because `max_reachable_threshold` maximises over status and
    # not over HP. See `holds_target_hp` -- and note it is a no-op at 1 HP, so every run that
    # reaches Phase 2 the old way is unchanged.
    #
    # A FAINTED target is still refused, and that is not a precondition but an observation: there
    # is nothing left to catch.
    if state.target.hp <= 0:
        return Unreachable(
            reason="the target has fainted, so there is nothing left to catch",
            proven=True, states_explored=0)
    # An unstatused target is not a dead end -- it is the ordinary consequence of a sleep wearing
    # off, and the fix is a turn of the search rather than the end of the run.
    #
    # **No status is required.** The target at 1 HP is the precondition; it does not have to be
    # paralyzed, asleep, frozen, or anything else, and our moveset does not have to be able to
    # make it so.
    #
    # That gate was the last holdout of the paralysis-only design, and everything it was
    # protecting had already been built: `reachable_statuses` includes the current status AND
    # NONE, `max_reachable_threshold` prices the largest `b` any reachable status allows,
    # `_dominance_key` separates states by status and sleep counter so the search plans through a
    # wake-up, and every actual throw is settled by `simulate_turn` rather than by the prune.
    #
    # It had relaxed once already -- an unstatused target was accepted provided our moveset could
    # put a holding status back on it. That proviso was the same mistake one step smaller. A
    # target we cannot status is not unreachable, only less likely per throw: `b` is 19784 at a
    # x1 ball and 1 HP against 21845 paralyzed, and the window search simply runs at the smaller
    # figure. Refusing it reported "no solution" for a battle the player could still win, which
    # is the costliest wrong answer this tool can give -- `proven=False` or not, it is what stops
    # them trying.
    #
    # **Burn and poison are still refused, and the reason is not the one this comment used to
    # lead with.**
    #
    # It led with the faint: the tick is a fixed fraction of max HP every turn, and at 1 HP it
    # kills the prize before any ball can land. True, and it reads as though the refusal were a
    # consequence of the 1 HP precondition -- so that when the precondition relaxes (and it is
    # relaxing: see the HP gate above), this gate looks like it should relax with it. It should
    # not, and the right argument never mentioned HP at all:
    #
    #   **Burn and poison give exactly the x1.5 that paralysis gives, and arrive attached to a
    #   clock. There is no HP at which that is the right trade.**
    #
    # Above 1 HP the clock is slower, not absent, and a target on a timer is strictly worse than
    # the same target not on one -- for an identical catch bonus. So there is no reason to ever
    # burn or poison a Pokemon you are trying to catch, at any HP.
    #
    # That is why the target's own tick is deliberately NOT simulated -- `simulate_turn` ticks our
    # burn and never the target's -- and why this refusal is the answer rather than a placeholder
    # for machinery somebody should write later.
    #
    # It has to stay a GATE for that reason. Without it the search runs against a target the
    # simulator believes is healthy and returns a confident plan: removing it produced
    # `M1hE3hHP125 M3E4 M1hE3hHP098 M1hE1 C` for a burned 1 HP target, five steps against
    # something that died on turn one.
    if state.target.status in HP_TICKING_STATUSES:
        return Unreachable(
            reason=(f"the target is {state.target.status.value}, which ticks its HP every turn "
                    f"-- at 1 HP that faints it before any ball can land, so there is no path "
                    f"to a capture from here"),
            proven=False, states_explored=0)
    deadline = struggle_deadline(state.target, config.turns_per_pp)
    max_turns = min(config.max_turns, deadline)
    # The MAXIMUM b any reachable status allows, not the entry state's -- see
    # `max_reachable_threshold`. Pruning at the entry figure can prove unreachability that a
    # Spore would have disproved, and `proven=True` is what justifies a soft reset.
    threshold = max_reachable_threshold(state, hunt, config)
    horizon_advances = max_turns * turn_costs.max_turn_advances()
    windows = capture_windows_in_horizon(state.rng, threshold, horizon_advances)
    if not windows:
        return Unreachable(
            reason=(f"no four consecutive rolls fall under b={threshold} -- the most generous "
                    f"threshold any status the target can reach allows -- within "
                    f"{horizon_advances} advances, an upper bound on what {max_turns} turns "
                    f"can spend. So no action sequence captures inside that budget."),
            proven=True, states_explored=0, capture_windows=0,
            searched_turns=max_turns)

    # (accumulated distance, tiebreak, turns, state, path)
    counter = 0
    queue: list[tuple[int, int, int, BattleState, tuple[Step, ...]]] = [(0, 0, 0, state, ())]
    # Offset-keyed closed set when collapsing; otherwise a per-offset bucket of incomparable
    # states pruned by dominance (sec 12.8).
    visited: set[int] = set()
    buckets: dict[tuple, list[tuple[BattleState, int]]] = {}
    explored = 0

    hit_turn_ceiling = False
    hit_struggle = False
    while queue:
        dist_so_far, _, turns, current, path = heapq.heappop(queue)
        explored += 1
        if explored > config.max_states:
            return Unreachable(
                reason=(f"search gave up after {config.max_states} states, with "
                        f"{len(windows)} capture window(s) in the horizon it had not reached; "
                        f"this says nothing about the seed"),
                proven=False, states_explored=explored, capture_windows=len(windows),
                searched_turns=max_turns)
        if current.captured:
            return Solution(steps=list(path), total_distance=dist_so_far,
                            states_explored=explored)
        if turns >= max_turns:
            hit_turn_ceiling = True
            continue
        if not current.target.usable_slots():
            # Exact deadline: the next turn would be Struggle, which is unmodelled and which
            # kills a 1 HP target. Unlike the turn ceiling above this is not an estimate, so a
            # search that only ever stopped here really did see the whole battle.
            hit_struggle = True
            continue

        if config.collapse_offsets:
            if current.rng_offset in visited:
                continue
            visited.add(current.rng_offset)
        else:
            key = _dominance_key(current)
            bucket = buckets.setdefault(key, [])
            if any(_dominates(other, other_dist, current, dist_so_far)
                   for other, other_dist in bucket):
                continue
            bucket.append((current, dist_so_far))

        for action, step_distance, item in _legal_actions(current, config, hunt):
            # `item_code=item`, which was missing. The step was PRICED as whatever
            # `choose_item` picked and SIMULATED as `sim`'s fallback Potion, so a Hyper Potion
            # cost 1200 and healed 20 -- and the search explored states that cannot occur. The
            # token was wrong too: the path said `Ip` where the real turn emits `Ihp`, so
            # following the plan contradicted it on the next report.
            nxt = simulate_turn(current, action, hunt, item_code=item)
            if nxt.captured_in_wrong_ball:
                continue          # never a path; the run would be lost
            # Sustainability is a hard constraint, not a warning (sec 6.2). Keyed on the faint
            # COUNT rather than on `ours.fainted`: a faint now switches the replacement in before
            # the turn returns, so the Pokemon on the field is healthy again and the old check
            # stopped firing the moment fainting became survivable.
            if nxt.faints > current.faints:
                continue
            counter += 1
            step = Step(action=action, tokens=tuple(nxt.log[-1]),
                        distance=step_distance, item=item)
            heapq.heappush(queue, (dist_so_far + step_distance, counter, turns + 1,
                                   nxt, path + (step,)))

    # A window is a *target*, not a reachable one: it says four consecutive rolls under b exist
    # at some offset, not that any action sequence arrives there with a ball in hand. So finding
    # windows and then finding no path is the ordinary outcome, not a contradiction.
    targets = len(windows)
    complete = not config.collapse_offsets
    if config.collapse_offsets:
        limit = ("collapsing each RNG offset to its cheapest arrival, so a dearer arrival that "
                 "carried the PP or HP for a later turn was never tried")
    elif hit_turn_ceiling:
        limit = (f"stopping at {max_turns} turns, which is "
                 + (f"{config.turns_per_pp}x the target's {remaining_target_pp(state.target)} "
                    f"remaining PP -- an estimate, since every full-paralysis turn is a free one"
                    if max_turns == deadline else "the configured ceiling"))
    else:
        limit = ("searching every action sequence to the point where the target runs out of PP "
                 "and must Struggle")
    return Unreachable(
        reason=(f"{targets} capture window{'' if targets == 1 else 's'} in reach of the horizon, "
                f"but no action sequence arrives at one with a ball in hand -- "
                f"{limit}"),
        proven=complete, states_explored=explored, capture_windows=targets,
        searched_turns=max_turns, stopped_at_struggle=hit_struggle)
