"""Battle state for Battle Compass — symmetric, and small on purpose.

Two things keep this much smaller than ``metronome_compass``'s state.

*The target is frozen.* Phase 2 begins with it at exactly 1 HP and permanently paralyzed, and
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

    @property
    def move_slot(self) -> int | None:
        """0-based move slot, or None if this is not a move."""
        return {Action.MOVE_1: 0, Action.MOVE_2: 1,
                Action.MOVE_3: 2, Action.MOVE_4: 3}.get(self)

    @property
    def is_bag_action(self) -> bool:
        """Bag actions resolve before any move and cost no RNG advances of their own."""
        return self in (Action.CAPTURE_BALL, Action.STANDARD_BALL,
                        Action.ITEM, Action.ITEM_CURE, Action.SWITCH)


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
    #: Confusion is volatile, so it sits outside `status` -- it can coexist with paralysis, and
    #: it is the one status a Pokemon can keep while still attacking (sec 13.4). Nothing in
    #: Suicune's moveset inflicts it, so it stays False for the v1 fixture.
    confused: bool = False

    def __post_init__(self):
        if self.hp is None:
            object.__setattr__(self, "hp", self.stats.get("hp", 0))

    @property
    def max_hp(self) -> int:
        return self.stats["hp"]

    @property
    def fainted(self) -> bool:
        return self.hp <= 0

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

    def with_status(self, status: Status) -> "Battler":
        """Apply a non-volatile status, which fails if one is already present."""
        if self.status is not Status.NONE and status is not Status.NONE:
            return self
        return replace(self, status=status)


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
    #: Rolls consumed since the battle started, so a turn can be located in the stream.
    rng_offset: int = 0
    balls_thrown: int = 0
    captured: bool = False
    #: Set when a standard ball captures: the run is lost, not won (sec 2.3).
    captured_in_wrong_ball: bool = False
    log: list = field(default_factory=list)

    @property
    def over(self) -> bool:
        return self.captured or self.captured_in_wrong_ball or self.target.fainted

    def copy(self) -> "BattleState":
        return BattleState(
            ours=self.ours, target=self.target, rng=self.rng, bench=self.bench,
            turn=self.turn, phase=self.phase,
            our_attack_stage=self.our_attack_stage, target_trapped=self.target_trapped,
            mist_turns=self.mist_turns, rain_turns=self.rain_turns,
            rng_offset=self.rng_offset, balls_thrown=self.balls_thrown,
            captured=self.captured, captured_in_wrong_ball=self.captured_in_wrong_ball,
            log=list(self.log))
