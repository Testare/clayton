"""Phase 2: steer the RNG until the capture ball captures.

Given an identified seed and a target at exactly 1 HP and permanently paralyzed, find the
sequence of actions whose ball throw succeeds.  The state is nearly frozen — the target's HP and
status do not change, so ``b`` is a single constant — which is why the search is cheap
(notes/battle_compass.md sec 2.2).

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
from claytonlib.battle_compass.sim import HuntConfig, advance, simulate_turn
from claytonlib.battle_compass.state import Action, BattleState, Status
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


def target_threshold(state: BattleState, config: HuntConfig) -> int:
    """``b`` for the capture ball against this target. Constant for the whole of Phase 2."""
    from claytonlib.battle_compass.sim import _status_bonus
    a = catch_value(config.effective_catch_rate(),
                    ball_multiplier=config.capture_ball_multiplier,
                    cur_hp=max(state.target.hp, 1), max_hp=state.target.max_hp,
                    status_bonus=_status_bonus(state.target.status))
    return shake_threshold(a)


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
    if hp <= config.danger_floor:
        # Nothing mitigates a critical hit, so a full heal is the only answer here (sec 12.3).
        return "hp", ITEM_PRICES["hp"]
    if state.ours.spdef_stage < 6:
        # X Sp. Def cuts chip damage but not crits, so it defers heals without moving the floor.
        return "xsd", ITEM_PRICES["xsd"]
    if hp < max_hp:
        return "p", ITEM_PRICES["p"]
    for code in ("xd", "gs"):
        return code, ITEM_PRICES[code]
    return None


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

    in_danger = state.ours.hp <= config.danger_floor
    item = choose_item(state, config)
    if item is not None:
        out.append((Action.ITEM, dist(item[1]), item[0]))
    if in_danger:
        # Only an item can prevent the faint, so the branching factor collapses to one.
        return out

    for slot in config.allowed_moves:
        move = state.ours.move(slot)
        if move is None or state.ours.pp_left(slot) <= 0:
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
            state.target_trapped, state.target.pp)


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
    if state.target.hp != 1 or state.target.status is not Status.PARALYSIS:
        return Unreachable(
            reason=(f"the solver's preconditions do not hold: the target is at "
                    f"{state.target.hp} HP and {state.target.status.value}, not 1 HP and "
                    f"paralyzed"),
            proven=False, states_explored=0)

    deadline = struggle_deadline(state.target, config.turns_per_pp)
    max_turns = min(config.max_turns, deadline)
    threshold = target_threshold(state, hunt)
    if is_guaranteed(threshold):
        pass  # any throw captures; the search will find it on turn one
    horizon_advances = max_turns * turn_costs.max_turn_advances()
    windows = capture_windows_in_horizon(state.rng, threshold, horizon_advances)
    if not windows:
        return Unreachable(
            reason=(f"no four consecutive rolls fall under b={threshold} within "
                    f"{horizon_advances} advances -- an upper bound on what {max_turns} turns "
                    f"can spend -- so no action sequence captures inside that budget"),
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
            nxt = simulate_turn(current, action, hunt)
            if nxt.captured_in_wrong_ball:
                continue          # never a path; the run would be lost
            if nxt.ours.fainted:
                continue          # sustainability is a hard constraint, not a warning
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
