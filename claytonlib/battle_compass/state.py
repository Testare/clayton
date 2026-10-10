"""Battle state for Battle Compass — symmetric, and small on purpose.

Two things keep this much smaller than ``metronome_compass``'s state.

*The target is frozen.* Phase 2 begins with it at exactly 1 HP and held still -- paralyzed, or
asleep against a target that can shed paralysis -- and
we never damage it again, so almost nothing about it changes turn to turn
(notes/battle_compass.md sec 2.2).  Its HP is a declared binary rather than a tracked number.

*We only simulate forwards.* The grammar's job is canonical rendering, not parsing (sec 13.1):
a candidate seed is simulated to produce the tokens it *would* emit, and filtering is a
comparison against what the player reported.  So there is no interactive context to mirror —
one direction, not two.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from claytonlib.moves import Move, resolve_move


class Status(Enum):
    """Non-volatile status. Mutually exclusive, which is why paralysis and sleep are a choice
    rather than a combination (sec 4.2)."""
    NONE = "none"
    PARALYSIS = "par"
    SLEEP = "slp"
    FREEZE = "frz"
    BURN = "brn"
    POISON = "psn"


#: The statuses that hold the target still enough for Phase 2 -- see
#: `Battler.frozen_for_phase2`, which is the explanation. Module-level so the solver can ask
#: which of them it could still APPLY, not merely which one the target has.
HOLDING_STATUSES = frozenset({Status.PARALYSIS, Status.SLEEP, Status.FREEZE})


class Action(Enum):
    """What an actor does on a turn.

    Seven for the solver (sec 12.5), eight while statused. ``SWITCH`` is Phase 1 only: Phase 2's
    precondition guarantees the right Pokemon is already active, so the solver never weighs
    switching against using an item.
    """
    MOVE_1 = "M1"
    MOVE_2 = "M2"
    MOVE_3 = "M3"
    MOVE_4 = "M4"
    CAPTURE_BALL = "C"
    STANDARD_BALL = "P"
    ITEM = "I"
    ITEM_CURE = "Ic"
    SWITCH = "S"
    #: A Revive, used on a party member rather than on whoever is out -- which is why it is its
    #: own action with its own ``R<slot>`` token instead of an item code. Phase 1 only: the
    #: solver never plans one (notes/feedback_battle_compass.md).
    REVIVE = "R"
    #: We were fainted before our move went off, so we took no action at all. Not a choice the
    #: player makes -- it is what the turn did to them -- but it has to be *reportable*, because
    #: the move they selected never executed, spent no PP and cost the stream nothing.
    FAINTED = "X"

    @property
    def move_slot(self) -> int | None:
        """0-based move slot, or None if this is not a move."""
        return {Action.MOVE_1: 0, Action.MOVE_2: 1,
                Action.MOVE_3: 2, Action.MOVE_4: 3}.get(self)

    @property
    def is_bag_action(self) -> bool:
        """Bag actions resolve before any move and cost no RNG advances of their own.

        ``FAINTED`` is deliberately absent. Bag actions resolve FIRST, and being fainted before
        moving is the opposite: the other side has already moved, which is how we got here.
        """
        return self in (Action.CAPTURE_BALL, Action.STANDARD_BALL,
                        Action.ITEM, Action.ITEM_CURE, Action.SWITCH, Action.REVIVE)


@dataclass(frozen=True)
class Battler:
    """One side, as the simulation needs it.

    Our stats are entered off the summary screen; the target's are derived from its IVs and
    nature (sec 15.4.1).  Either way they arrive here as final numbers.
    """
    name: str
    level: int
    types: tuple[str, ...]
    #: Final stats, keyed hp/atk/def/spa/spd/spe.
    stats: dict[str, int]
    #: Move names in slot order — the order the M1..M4 and E1..E4 tokens refer to.
    moves: tuple[str, ...] = ()
    #: Current PP per slot, same order.
    pp: tuple[int, ...] = ()
    ability: str = ""
    #: Held item, per hunt rather than per Pokemon -- a type-enhancing one raises base power.
    held_item: str = ""
    #: None means "start at full"; 0 is a real, distinct value (fainted), so a sentinel is
    #: required here -- defaulting on ``hp == 0`` silently healed a fainted Pokemon to full.
    hp: int | None = None
    status: Status = Status.NONE
    #: Def/SpD stages, which affect damage.
    def_stage: int = 0
    spdef_stage: int = 0
    #: Accuracy and evasion stages, which decide whether a move CAN miss. Nothing in Suicune's
    #: moveset touches either, but a 100%-accuracy move becomes missable the moment our accuracy
    #: is dropped or its evasion is raised -- so they are tracked rather than assumed neutral.
    accuracy_stage: int = 0
    evasion_stage: int = 0
    #: Turns of sleep remaining, counted the way ``metronome_compass`` counts them: the status
    #: ends when this reaches 1, and the Pokemon ACTS on that turn. So a rolled duration of 2
    #: costs one turn and 5 costs four. Zero whenever `status` is not SLEEP.
    sleep_turns: int = 0
    #: Confusion is volatile, so it sits outside `status` -- it can coexist with paralysis, and
    #: it is the one status a Pokemon can keep while still attacking (sec 13.4). Nothing in
    #: Suicune's moveset inflicts it, so it stays False for the v1 fixture.
    confused: bool = False
    #: 1-based position in the hunt's configured party, and the number the ``S``, ``X`` and ``R``
    #: tokens name. **Stable** -- HGSS never reorders a party, so slot 1 is the first Pokemon in
    #: the hunt configuration for the whole run, whoever happens to be out and however often we
    #: switch. Zero means "no party was built", which is the case for a Battler constructed
    #: directly as the simulator's own tests do; `sim.party_number` then falls back to the old
    #: positional guess. Last in the field order so positional construction keeps working.
    party_slot: int = 0

    def __post_init__(self):
        if self.hp is None:
            object.__setattr__(self, "hp", self.stats.get("hp", 0))

    @property
    def max_hp(self) -> int:
        return self.stats["hp"]

    @property
    def fainted(self) -> bool:
        return self.hp <= 0

    @property
    def frozen_for_phase2(self) -> bool:
        """Whether this status leaves the target's state still, which is what Phase 2 needs.

        Not "has any status". Three of the six qualify and three do not, for reasons that matter:

        * **Paralysis** -- permanent, and quarters Speed, which is how sec 4.2 guarantees no
          speed tie. The original and still the default.
        * **Sleep** -- the target cannot act at all, which is stronger. It EXPIRES, so a caller
          also has to respect `sleep_turns`; that is a horizon, not a disqualification.
        * **Freeze** -- same shape as sleep, with a thaw check instead of a counter. Allowed for
          symmetry; nothing in any configured moveset can inflict it.
        * **Burn and poison** are refused: they give the same x1.5 catch bonus as paralysis and
          tick HP every turn, so the target is not frozen and `b` is not a constant.
        * **NONE** is refused because the catch bonus is the point of the precondition at all.

        Refused is not the same as unrecoverable, and the two were conflated. Sleep wearing off
        mid-run lands here with NONE, and `solver.solve` used to read that as "stop"; what it
        means is "re-apply something", which is why :data:`HOLDING_STATUSES` is exposed -- the
        solver asks whether it can put the target back into one rather than only whether it is
        in one now.
        """
        return self.status in HOLDING_STATUSES

    def move(self, slot: int) -> Move | None:
        """The Move in `slot`, or None if the slot is empty or unknown.

        An empty slot is simply not an action the solver can choose, which is what makes the
        "a Pokemon with no moves must Struggle" hazard structural rather than special-cased
        (sec 12.5).
        """
        if not 0 <= slot < len(self.moves):
            return None
        return resolve_move(self.moves[slot])

    def usable_slots(self) -> tuple[int, ...]:
        """Slots with a known move and PP remaining.

        This is the list the wild move-selection roll indexes into: ``RANDOM % len(usable)``
        picks a position in it, so the modulus shrinks as PP runs out (sec 5.2 R4).
        """
        return tuple(i for i in range(len(self.moves))
                     if self.move(i) is not None and self.pp_left(i) > 0)

    def pp_left(self, slot: int) -> int:
        return self.pp[slot] if 0 <= slot < len(self.pp) else 0

    def spend_pp(self, slot: int, amount: int = 1) -> "Battler":
        """Return a copy with `amount` PP deducted from `slot`.

        `amount` is 2 against Pressure: it doubles OUR consumption, not the target's own
        (sec 4.4).
        """
        pp = list(self.pp)
        if 0 <= slot < len(pp):
            pp[slot] = max(0, pp[slot] - amount)
        return replace(self, pp=tuple(pp))

    def with_hp(self, hp: int) -> "Battler":
        return replace(self, hp=max(0, min(hp, self.max_hp)))

    def with_status(self, status: Status, *, sleep_turns: int = 0) -> "Battler":
        """Apply a non-volatile status, which fails if one is already present.

        `sleep_turns` is the rolled duration, and is required in practice for SLEEP: a sleeping
        Battler with a zero counter wakes on its very next turn, which is not what the game
        rolled. Clearing a status clears the counter with it.
        """
        if self.status is not Status.NONE and status is not Status.NONE:
            return self
        if status is Status.NONE:
            return replace(self, status=status, sleep_turns=0)
        return replace(self, status=status,
                       sleep_turns=sleep_turns if status is Status.SLEEP else 0)

    def tick_sleep(self) -> tuple["Battler", bool]:
        """Resolve a sleeping Battler's turn: ``(battler, acts)``.

        The counting is ``metronome_compass``'s, which is RNG-verified: the status ends when the
        remaining count reaches 1, and the Pokemon acts on that turn -- so this returns
        ``(awake, True)`` then, and ``(still asleep with one fewer turn, False)`` otherwise.
        Spends no rolls; the wake is self-evident from the Pokemon acting, so there is no
        wear-off token either.
        """
        if self.status is not Status.SLEEP:
            return self, True
        if self.sleep_turns <= 1:
            return replace(self, status=Status.NONE, sleep_turns=0), True
        return replace(self, sleep_turns=self.sleep_turns - 1), False


@dataclass
class BattleState:
    """Both battlers plus the field, advancing turn by turn."""

    ours: Battler
    target: Battler
    rng: int
    #: The rest of the party, in send-out order, that `ours` can be swapped for. Phase 1 only:
    #: Phase 2's precondition guarantees the right Pokemon is already out (sec 12.5).
    bench: tuple[Battler, ...] = ()
    turn: int = 0
    #: Set once the target is at 1 HP and paralyzed; the solver asserts it (sec 2 / sec 15.3).
    phase: int = 1
    #: -6..+6 on our side, from the target's Aurora Beam. Affects damage we DEAL, which we do
    #: not model -- tracked only so the token stream can report the drop.
    our_attack_stage: int = 0
    target_trapped: bool = False
    mist_turns: int = 0
    rain_turns: int = 0
    #: Water Sport, set by the TARGET. A per-battler volatile flag in the ROM rather than a turn
    #: counter, so once up it stays up for the rest of a wild battle -- the user never switches
    #: out. A bool, not a counter, for that reason. Our own side using Water Sport is unmodelled
    #: and no configured moveset contains it; it is tracked at all because a SECOND Water Sport
    #: fails, and a failing move costs the turn two fewer advances.
    target_water_sport: bool = False
    #: How many of our Pokemon have gone down. Needed because a faint no longer leaves a trace
    #: in `ours`: the replacement switches in at the end of the turn, so ``ours.fainted`` is
    #: False again by the time anyone inspects the result. The solver prunes on this -- a path
    #: that spends a Pokemon is not a path (sec 6.2) -- and without it the check silently stopped
    #: firing the moment fainting became survivable.
    faints: int = 0
    #: Rolls consumed since the battle started, so a turn can be located in the stream.
    rng_offset: int = 0
    balls_thrown: int = 0
    captured: bool = False
    #: Set when a standard ball captures: the run is lost, not won (sec 2.3).
    captured_in_wrong_ball: bool = False
    log: list = field(default_factory=list)

    @property
    def healthy_bench(self) -> tuple[int, ...]:
        """Bench indices that could be sent out — anything not already fainted."""
        return tuple(i for i, b in enumerate(self.bench) if not b.fainted)

    @property
    def party_wiped(self) -> bool:
        """Our active Pokemon is down and there is nobody to replace it.

        This, and not ``ours.fainted``, is what ends a run on our side. A faint with a
        replacement available is a reportable *turn* -- the ``X`` token, plus which party slot
        came in -- after which the battle carries on with somebody else out. Before fainting was
        modelled the two were the same thing, which is why ``over`` used to read ``ours.fainted``.
        """
        return self.ours.fainted and not self.healthy_bench

    @property
    def over(self) -> bool:
        """Whether the battle has stopped advancing.

        A wipe counts -- ``XX`` is as terminal as ``C`` or ``Pc``. Our active Pokemon merely
        fainting does not, as long as something can replace it: the simulator switches the
        replacement in at the end of the turn and keeps going. Without the distinction the
        simulator stopped at the first faint and rendered hits that changed nothing -- ``E2h``
        with no ``HP`` token, which ``tokens.validate_turn`` correctly rejects as ungrammatical.

        The solver still treats any faint as a hard constraint (sec 6.2): a path that spends a
        Pokemon is not a path. It prunes on `faints` rather than on this, and for that matter
        rather than on ``ours.fainted``, which the replacement switch-in clears before the turn
        even returns.
        """
        return (self.captured or self.captured_in_wrong_ball
                or self.target.fainted or self.party_wiped)

    def copy(self) -> "BattleState":
        return BattleState(
            ours=self.ours, target=self.target, rng=self.rng, bench=self.bench,
            turn=self.turn, phase=self.phase,
            our_attack_stage=self.our_attack_stage, target_trapped=self.target_trapped,
            mist_turns=self.mist_turns, rain_turns=self.rain_turns,
            target_water_sport=self.target_water_sport, faints=self.faints,
            rng_offset=self.rng_offset, balls_thrown=self.balls_thrown,
            captured=self.captured, captured_in_wrong_ball=self.captured_in_wrong_ball,
            log=list(self.log))
