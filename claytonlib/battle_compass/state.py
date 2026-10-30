"""Battle state for Battle Compass — symmetric, and small on purpose.

Two things keep this much smaller than ``metronome_compass``'s state.

*The target barely moves.* Phase 2 begins with it at exactly 1 HP -- the only precondition --
and we never damage it again, so almost nothing about it changes turn to turn
(notes/battle_compass.md sec 2.2).  Its HP is a declared binary rather than a tracked number.
A status is no longer required: it can be applied mid-path, and ``b`` already varies along one.

*We only simulate forwards.* The grammar's job is canonical rendering, not parsing (sec 13.1):
a candidate seed is simulated to produce the tokens it *would* emit, and filtering is a
comparison against what the player reported.  So there is no interactive context to mirror —
one direction, not two.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from claytonlib.battle.damage import item_key
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

#: Statuses that damage their holder every turn, which at 1 HP kills the target before any ball
#: can land. Phase 2 refuses a target holding one.
#:
#: **And the target's own tick is deliberately not simulated.** There is no reason to ever burn or
#: poison a Pokemon you are trying to catch -- the x1.5 catch bonus is the same as paralysis's and
#: comes with a clock that kills the prize -- so the useful behaviour is to refuse the state, not
#: to model your way through it. Refusing here is the ANSWER rather than a stand-in for missing
#: machinery, which is why `sim.simulate_turn` ticks only our own burn and never the target's.
HP_TICKING_STATUSES = frozenset({Status.BURN, Status.POISON})


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


#: How much a sleeping Pokemon's counter drops when it tries to act, and what Early Bird makes
#: that instead [pokeplatinum src/battle/battle_controller_player.c:2442].
SLEEP_DECREMENT = 1
SLEEP_DECREMENT_EARLY_BIRD = 2


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
    #: Def/SpD stages, which affect damage taken.
    def_stage: int = 0
    spdef_stage: int = 0
    #: Atk/SpA stages, which affect damage DEALT -- by either side. Ours matter because the
    #: simulator really does model our damage: it is how the run knows whether enough False
    #: Swipes have landed for the solver to start. The target's matter because Ancient Power
    #: raises all of its stats at once.
    #:
    #: Separate fields because the moves are: Aurora Beam lowers Attack only, Mist Ball lowers
    #: Sp. Atk only. `execute_move` used to pass one figure as BOTH, so an Aurora Beam drop was
    #: silently applied to Sp. Atk as well.
    atk_stage: int = 0
    spatk_stage: int = 0
    #: Speed stage. Raised on the target by Ancient Power, and it is the one boost that threatens
    #: the no-speed-tie guarantee: stages are applied BEFORE paralysis quarters Speed, so +6
    #: cancels the quartering exactly and puts the target back at full Speed.
    speed_stage: int = 0
    #: Accuracy and evasion stages, which decide whether a move CAN miss. Nothing in Suicune's
    #: moveset touches either, but a 100%-accuracy move becomes missable the moment our accuracy
    #: is dropped or its evasion is raised -- so they are tracked rather than assumed neutral.
    accuracy_stage: int = 0
    evasion_stage: int = 0
    #: Turns of sleep remaining, counted the way ``metronome_compass`` counts them: the status
    #: ends when this reaches 1, and the Pokemon ACTS on that turn. So a rolled duration of 2
    #: costs one turn and 5 costs four. Zero whenever `status` is not SLEEP.
    sleep_turns: int = 0
    #: Turns of confusion left to run, counted the ROM's way: the counter is **decremented
    #: before** the check, so a rolled duration of N gives N-1 turns that actually roll
    #: (`sim.confusion_self_hit`). Zero means not confused.
    #:
    #: Volatile, so it sits outside `status` -- it coexists with paralysis, and it is the one
    #: condition a Pokemon can keep while still attacking (sec 13.4).
    #:
    #: **A counter rather than the flag this used to be.** It was `confused: bool`, which was
    #: honest while nothing inflicted it; Regigigas' Confuse Ray and Dizzy Punch are what need
    #: the number, because the duration is rolled (`sim.CONFUSION_TURNS_*`) and the turn it wears
    #: off spends no roll at all. `confused` survives as a read-only property so the interview
    #: and the snapshot read unchanged.
    confusion_turns: int = 0
    #: 1-based position in the hunt's configured party, and the number the ``S``, ``X`` and ``R``
    #: tokens name. **Stable** -- HGSS never reorders a party, so slot 1 is the first Pokemon in
    #: the hunt configuration for the whole run, whoever happens to be out and however often we
    #: switch. Zero means "no party was built", which is the case for a Battler constructed
    #: directly as the simulator's own tests do; `sim.party_number` then falls back to the old
    #: positional guess. Last in the field order so positional construction keeps working.
    party_slot: int = 0
    #: The move slot a multi-turn move has this battler locked into mid-charge, or None.
    #:
    #: **Different from `choice_locked_slot`**, which is a Choice item's lock: that one still has
    #: its holder PICK a command every turn (it just refuses the other three), while this one
    #: skips command selection entirely -- `Battler_CanPickCommand` returns FALSE and the wild
    #: move-selection roll is never spent (pokeplatinum
    #: src/battle/battle_controller_player.c:334-338, 1885-1888). That is an advance difference,
    #: which is why the two cannot share a field.
    #:
    #: Shadow Force is the only move any configured encounter has in this family, and while it is
    #: charging its user is semi-invulnerable -- see `sim.is_semi_invulnerable`.
    charging_slot: int | None = None
    #: Nightmare, a volatile the ROM keeps in `statusVolatile` alongside confusion rather than
    #: in `status` -- so it coexists with sleep instead of replacing it, which is the whole point
    #: of the move. It only ever damages a SLEEPING holder: the end-of-turn check clears the flag
    #: with no damage the moment the holder is awake
    #: (pokeplatinum src/battle/battle_controller_player.c:1436-1446), which is why waking up is
    #: a cure and not merely a reprieve.
    nightmare: bool = False
    #: Which move slot a Choice item has locked this Pokemon into, or None.
    #:
    #: The ROM records the move itself (``moveNoChoice``) the first time a holder of a
    #: Choice Band / Scarf / Specs attacks, and refuses every other move until it leaves the
    #: field. Kept as a SLOT here because that is what the M1-M4 tokens and `usable_slots` speak
    #: in. Cleared on switching out, which is how the lock ends.
    #:
    #: It matters to Battle Compass through the solver rather than through damage: a dedicated
    #: scarfed paralyzer is locked into Thunder Wave the moment it uses it, and a plan that plays
    #: one of its other three moves is a plan the game will not accept.
    choice_locked_slot: int | None = None

    #: Turns of Uproar left to run, and the slot it is locked into. Nonzero only on a battler
    #: mid-Uproar; Azelf is the one encounter that has the move.
    #:
    #: **Not `charging_slot`**, though the two share the half that matters most -- the ROM's
    #: `Battler_CanPickCommand` returns FALSE for either, so neither spends the move-selection
    #: roll and neither spends PP (battle_lib.c:6224-6236, battle_controller_player.c:334-336).
    #: They part company on everything else. A charge turn fires nothing and makes its user
    #: unhittable; an Uproar turn deals damage every single turn, and `execute_move`'s
    #: `ends_charge` would clear a shared field on the first of them. Two fields, because one
    #: would have to mean two things.
    uproar_turns: int = 0
    uproar_slot: int | None = None
    #: Yawn's countdown. Set to `YAWN_DROWSY_TURNS` by a Yawn aimed at this battler, decremented
    #: at the end of every turn, and sleep lands the turn it reaches zero -- so a Yawn on turn T
    #: puts its victim to sleep at the end of turn T+1 (`BtlCmd_TryYawn`, battle_script.c:6580,
    #: and `MON_COND_CHECK_STATE_YAWN`, battle_controller_player.c:1684).
    #:
    #: Uxie's, and it lives on the Battler rather than on the state because the ROM keeps it in
    #: `moveEffectsMask`, which a freshly sent-out BattleMon zeroes -- so switching out really
    #: does shake it off. That is the opposite of a pending Future Sight; see
    #: `BattleState.future_sight_turns` for why that one does not travel.
    drowsy_turns: int = 0
    #: Taunt's countdown. While it is nonzero this battler cannot SELECT a move with no power --
    #: and that is a change to the move-selection roll's MODULUS, not a refusal after the fact
    #: (see `usable_slots`).
    #:
    #: Ours to inflict: Taunt is in no configured target's moveset, and it is the first move of
    #: ours that changes what the target's turn costs. Set to 3-5 by `subscript_taunt_start.s`'s
    #: ``Random 2, 3``, decremented by `MON_COND_CHECK_STATE_TAUNT` (state 20 of the end-of-turn
    #: condition walk, between Uproar at 14 and Yawn at 24), and it spends nothing on the way out.
    taunted_turns: int = 0
    #: Heal Block's countdown, on whoever the move was aimed at -- so ours, since Dialga and
    #: Palkia are the only carriers and they aim it at us.
    #:
    #: **It blocks far less than its name suggests, and that is the fact worth recording here.**
    #: `Move_HealBlocked` (battle_lib.c:3427-3440) tests a hardcoded list of FOURTEEN MOVES --
    #: Recover, Softboiled, Rest, Milk Drink, Morning Sun, Synthesis, Moonlight, Swallow, Heal
    #: Order, Slack Off, Roost, Lunar Dance, Healing Wish, Wish -- plus the Ingrain and Aqua Ring
    #: residuals. It does **not** block items and does **not** block Leftovers [verified:
    #: `healBlockTurns` is read at exactly those sites and its own countdown, nowhere else]. So
    #: Hyper Potions, Full Restores and Revives work straight through it and the solver's healing
    #: plan is untouched.
    #:
    #: Which means it is tracked for what it COSTS rather than what it stops: a second Heal Block
    #: fails, and a failing move is two advances cheaper than a successful one. The one party it
    #: bites is a Rest or Roost wall, which is a plausible answer to Dialga's damage.
    heal_block_turns: int = 0
    #: A Foresight or Odor Sleuth has landed on this battler -- the ROM's
    #: `VOLATILE_CONDITION_FORESIGHT`, set on the move's DEFENDER by `subscript_foresight.s`.
    #:
    #: Two consequences, and both are read elsewhere rather than here: the two Ghost immunities
    #: stop applying to moves aimed at it (`battle.damage.ignores_ghost_immunity`), and its
    #: positive evasion stages stop counting (`sim.accuracy_net_stage`). Its evasion DROPS still
    #: count -- the ROM zeroes the term only when it favours the defender
    #: (battle_controller_player.c:2888).
    #:
    #: **This is what makes a Ghost target catchable at all.** False Swipe is Normal, so against
    #: Giratina it does nothing until one of these lands; the chip phase is impossible without it.
    #:
    #: A flag with no counter, like `target_water_sport` and unlike every `*_turns` field: the ROM
    #: clears it only when the Pokemon leaves the field, and a wild target never does. So one
    #: Foresight lasts the battle -- and a second one still succeeds, which is why effect 113 is
    #: deliberately absent from `sim.will_fail`.
    #:
    #: **It survives the APPLIER switching out, which is the half worth stating** [verified in
    #: game, by Testare -- Foresight with one Pokemon, switch, False Swipe with another, damage
    #: dealt]. The flag belongs to the target, so whoever put it there is irrelevant from then on;
    #: the Foresight does not have to be on the False Swipe user. `sim.sent_out` clears it only
    #: from the Pokemon being sent out, which is the opposite direction and reachable only for a
    #: Foresight aimed at US (clayton-957.26.5).
    identified: bool = False
    #: A Leech Seed is on this battler -- the ROM's ``MOVE_EFFECT_LEECH_SEED`` in
    #: `moveEffectsMask`, set on the move's DEFENDER by `subscript_leech_seed_start.s`.
    #:
    #: Shaymin's, and the only effect on either side that moves BOTH Pokemon's HP from one
    #: place. The drain sits in the end-of-turn condition walk at
    #: ``MON_COND_CHECK_STATE_LEECH_SEED``, immediately after Leftovers and before poison and
    #: burn (pokeplatinum src/battle/battle_controller_player.c:1263-1267) -- which is why
    #: `sim.leech_seed_tick` is applied where it is rather than next to the burn tick.
    #:
    #: A flag with no counter, like `identified`: nothing ever shakes it off except leaving the
    #: field. So one Leech Seed lasts as long as the seeded Pokemon stays out, and a second one
    #: aimed at an already-seeded victim FAILS (`sim.will_fail`).
    #:
    #: **Whose heal it is matters as much as whose damage.** The ROM hands the seeder the damage
    #: it actually dealt, not the figure it computed, so a drain clamped by our remaining HP
    #: heals Shaymin by the clamped amount -- see `sim.leech_seed_tick`.
    seeded: bool = False

    def __post_init__(self):
        if self.hp is None:
            object.__setattr__(self, "hp", self.stats.get("hp", 0))

    @property
    def confused(self) -> bool:
        """Whether a confusion counter is running.

        Derived rather than stored: two fields that must agree is the drift this codebase keeps
        finding, and `confusion_turns > 0` is the whole of it. Construct with
        ``confusion_turns=N``; `replace(..., confused=True)` now raises, which is the loud
        failure the rename wanted.
        """
        return self.confusion_turns > 0

    @property
    def max_hp(self) -> int:
        return self.stats["hp"]

    @property
    def fainted(self) -> bool:
        return self.hp <= 0

    @property
    def frozen_for_phase2(self) -> bool:
        """Whether this status leaves the target's state still.

        **Not a precondition any more** -- `solver.solve` searches an unstatused target, and a
        target at any HP. This is now a question a caller may ask (the readiness advice does, to
        say what a status would be worth) rather than a gate anything enforces. The name is kept
        because the question is unchanged; only its authority went.

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

    @property
    def holds_choice_item(self) -> bool:
        """Whether this Pokemon's held item locks it into one move once it attacks."""
        from claytonlib.battle.readiness import CHOICE_ITEMS

        return item_key(self.held_item) in CHOICE_ITEMS

    def usable_slots(self) -> tuple[int, ...]:
        """Slots this battler could actually pick right now -- and, under a Choice item, only one.

        This is the list the wild move-selection roll indexes into: ``RANDOM % len(usable)``
        picks a position in it, so the modulus shrinks as PP runs out (sec 5.2 R4). No wild
        target holds an item, so the Choice branch below never narrows that roll; it narrows what
        OUR side may be offered and what the solver may plan.

        **Taunt narrows it too, and that was not the obvious answer.** The ROM builds the wild
        side's choice as a max-score tie broken randomly, and `TrainerAI_Init` zeroes the score of
        every move `BattleSystem_CheckInvalidMoves(..., CHECK_INVALID_ALL)` flags
        (trainer_ai.c:234-237, 317-338). That mask is ``~0``, so it carries both
        CHECK_INVALID_NO_PP -- which is the code path behind the PP rule above -- and
        CHECK_INVALID_TAUNTED. A taunted power-0 move therefore drops out of the tie list and the
        modulus shrinks with it: a taunted Uxie picks from two slots rather than four.

        **And the refusal path is real as well, on exactly one turn.** This docstring used to
        argue it was not -- that `subscript_move_fail_taunted` is reached from
        `CHECK_STATUS_STATE_TAUNT` only when something *forces* a taunted Pokemon into a status
        move, which no configured target can do. What that missed is that the narrowing above
        happens at SELECTION time. On the turn a Taunt LANDS with the taunter moving first, the
        target had already chosen, so there was nothing to narrow and the ROM refuses the move it
        is holding. Measured in data/battle_logs/uxie1.jsonl turn 14 -- and it is the commonest
        Taunt turn there is, because a Taunt is thrown to land and we outspeed a paralyzed target
        by construction.

        So both halves are modelled, in two places: the narrowing here, which is every turn
        AFTER the first, and the refusal in `sim.taunt_refuses`, which is the landing turn and
        carries its own token (`tokens.TAUNTED`). Getting that split wrong either way is a
        desync: modelled as a refusal throughout, every taunted turn would spend two
        post-successful-move advances the game does not spend and pick the wrong move besides;
        modelled as a narrowing throughout, the landing turn spends three the game does not.

        **By POWER, not by category**, which is the ROM's own test. The same set in practice for
        every configured moveset, but transcribed rather than translated.
        """
        # **A mid-charge lock comes first, and unlike the Choice lock it ignores PP.** The ROM
        # relocks into the charging move without consulting it -- the PP was already spent on the
        # charge turn, and `Battler_CanPickCommand` returns FALSE so nothing is picked at all
        # (battle_lib.c:6225-6236). `sim.select_target_move` short-circuits on the same field
        # BEFORE it reaches this method, so adding it here cannot change the selection roll's
        # modulus; what it fixes is the INTERVIEW, which read `usable_slots` and so offered all
        # four of Giratina's moves on a turn it can only continue Shadow Force.
        if self.charging_slot is not None and self.move(self.charging_slot) is not None:
            return (self.charging_slot,)
        if self.choice_locked_slot is not None:
            slot = self.choice_locked_slot
            return (slot,) if self.move(slot) is not None and self.pp_left(slot) > 0 else ()
        return tuple(i for i in range(len(self.moves))
                     if (move := self.move(i)) is not None and self.pp_left(i) > 0
                     and not (self.taunted_turns and not move.power))

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
        """`hp`, clamped to 0..max — and **a Pokemon that lands on 0 loses its status**.

        Fainting clears the non-volatile status, which is what makes a Revive bring back a
        *healthy* Pokemon rather than a burned one. Enforced here, at the one choke point every
        HP change goes through, so no code path can hold a fainted-and-statused Battler.

        Found by replaying the real run (notes/hooh_log_replay.md sec 3): Sacred Fire fainted
        Granbull and burned it on the same roll, the Revive brought it back still burned, and the
        simulator then ticked 20 HP a turn off a Pokemon the game was not burning -- the only
        mismatch in 108 turns of ground truth (clayton-957.10.14).
        """
        landed = max(0, min(hp, self.max_hp))
        if landed == 0 and (self.status is not Status.NONE or self.nightmare
                            or self.charging_slot is not None
                            or self.uproar_turns or self.drowsy_turns
                            or self.taunted_turns or self.identified
                            or self.heal_block_turns or self.seeded
                            or self.confusion_turns):
            # The volatiles go too. `statusVolatile` and `moveEffectsMask` are cleared wholesale
            # when a Pokemon leaves the field, and a fainted one always does -- so a Revive cannot
            # bring back something that is still locked in a nightmare, still mid-Uproar, or still
            # drowsy from a Yawn it will never now fall asleep from.
            return replace(self, hp=0, status=Status.NONE, sleep_turns=0, nightmare=False,
                           charging_slot=None, uproar_turns=0, uproar_slot=None,
                           drowsy_turns=0, taunted_turns=0, identified=False,
                           heal_block_turns=0, seeded=False, confusion_turns=0)
        return replace(self, hp=landed)

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

    def tick_confusion(self) -> tuple["Battler", str]:
        """Resolve a confused Battler's turn: ``(battler, "none" | "confused" | "snapped")``.

        Three outcomes rather than `tick_sleep`'s two, because confusion has a wear-off event the
        player must REPORT: a confused Pokemon can attack perfectly normally, so the move landing
        says nothing about whether the confusion ended (`tokens.RESOLUTION_DETAIL`).

        **The counter is decremented first and then tested**, which is the ROM's order
        (battle_controller_player.c:2617-2620) and the reason a rolled duration of N gives N-1
        turns that roll: the turn the counter reaches zero snaps out instead, and spends nothing.

        ``"confused"`` means the caller still owes the ``& 1`` check -- this method spends no
        rolls itself, exactly like `tick_sleep`.
        """
        if not self.confusion_turns:
            return self, "none"
        remaining = self.confusion_turns - 1
        if remaining:
            return replace(self, confusion_turns=remaining), "confused"
        return replace(self, confusion_turns=0), "snapped"

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
        # Early Bird decrements the counter by TWO rather than one
        # (pokeplatinum src/battle/battle_controller_player.c:2442-2452), so a rolled duration of
        # 2 costs its holder no turn at all. Worth modelling now that a target can put US to
        # sleep: how long we spend asleep is how much Nightmare and Bad Dreams take off, and
        # Noctowl and Xatu are ordinary things to bring.
        decrement = SLEEP_DECREMENT_EARLY_BIRD if self.has_early_bird else SLEEP_DECREMENT
        if self.sleep_turns <= decrement:
            return replace(self, status=Status.NONE, sleep_turns=0), True
        return replace(self, sleep_turns=self.sleep_turns - decrement), False

    @property
    def has_early_bird(self) -> bool:
        return (self.ability or "").strip().lower() == "early bird"


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
    #: Which phase the run is in. **No longer an assertion about the target**: the solver once
    #: required 1 HP and paralysis, then 1 HP, and now neither -- see `solver.solve`. What Phase 2
    #: requires is that the plan not MOVE the target's HP (`solver.holds_target_hp`), which is a
    #: property of the plan rather than of the state.
    phase: int = 1
    #: Reports our Attack stage. A PROPERTY now, delegating to `ours.atk_stage`: the stage has
    #: to live on the Battler, because that is what `execute_move` reads and what survives a
    #: switch, and two copies of it would drift. Read-only for the same reason.
    #:
    #: Its old comment said the drop affects "damage we DEAL, which we do not model". We do model
    #: it -- that is how the run knows when enough False Swipes have landed -- so this was never
    #: merely cosmetic.
    target_trapped: bool = False
    mist_turns: int = 0
    rain_turns: int = 0
    #: Safeguard on the TARGET's side, which is the only side that raises it. While it is up our
    #: status moves fail, so it is a hard block on the Phase 2 precondition rather than a nuisance
    #: (notes/battle_compass_next_targets.md): paralyze before it goes up, or wait out the five
    #: turns. A counter rather than a bool because it expires, unlike Water Sport.
    safeguard_turns: int = 0
    #: Safeguard on OUR side, which the first version of this state did not have at all -- the
    #: comment above said the target's was "the only side that raises one", and that was true only
    #: while no party member knew the move. **Wobbuffet does**, and Wobbuffet is the canonical
    #: roamer trapper, so the omission turned our own Safeguard into a block on our own Spore
    #: [caught by data/battle_logs/mesprit2.jsonl turn 8, where the game slept the target and the
    #: simulator refused to].
    our_safeguard_turns: int = 0
    #: Water Sport, set by the TARGET. A per-battler volatile flag in the ROM rather than a turn
    #: counter, so once up it stays up for the rest of a wild battle -- the user never switches
    #: out. A bool, not a counter, for that reason. Our own side using Water Sport is unmodelled
    #: and no configured moveset contains it; it is tracked at all because a SECOND Water Sport
    #: fails, and a failing move costs the turn two fewer advances.
    target_water_sport: bool = False
    #: Lucky Chant on the TARGET's side -- Mesprit's, and the only side that can raise one, since
    #: no party moveset carries effect 240. While it is up our critical hits are suppressed, and
    #: the crit ROLL is still spent (`sim.EFFECT_LUCKY_CHANT`), so this changes verdicts and never
    #: roll counts. A counter because it expires, like Mist and Safeguard.
    target_lucky_chant_turns: int = 0
    #: Reflect and Light Screen on OUR side, which is the only side that can raise them: no
    #: configured target moveset contains either move. Counters because they expire, and because
    #: a Light Clay makes the figure 8 rather than 5 (`battle.damage.screen_turns`).
    #:
    #: Unlike Mist and Safeguard these are **side** conditions in the ROM
    #: (`ctx->fieldSideConditionFlags[side]`, src/battle/battle_command.c:2577), not battler ones,
    #: so they survive our switches -- Magneton can set Reflect and Smeargle keeps it. They live
    #: on the state rather than on `Battler` for exactly that reason.
    reflect_turns: int = 0
    light_screen_turns: int = 0
    #: A Future Sight already in the air, aimed at OUR slot: turns until it lands, and the damage
    #: it banked at the moment it was used.
    #:
    #: **On the state and not on `Battler`, which is what makes a switch no escape.** The ROM
    #: keeps it in `fieldConditions.futureSightTurns[battler]` -- indexed by battler POSITION, not
    #: by the Pokemon standing there -- and `BtlCmd_TryFutureSight` banks the number at setup
    #: time (battle_script.c:6066). So the hit lands on whoever is out two turns later, for the
    #: damage computed against whoever was out when it was used. Switching a Smeargle out for a
    #: wall does not reduce it; it just changes who takes it.
    #:
    #: Only the TARGET's side can set one: Future Sight is Uxie's and Azelf's, and nothing in a
    #: party may carry it (`sim.MODELLED_OUR_EFFECTS`).
    future_sight_turns: int = 0
    future_sight_damage: int = 0
    #: Which move banked it, by name, because the hit check two turns later uses that move's
    #: accuracy. Mirrors the ROM's `fieldConditions.futureSightMove[battler]`, and it is a stored
    #: value for the same reason the damage is: Future Sight is 90 and Doom Desire 85, and the
    #: two share effect 148, so reading the accuracy off "whatever effect-148 move the target
    #: has" would be right by luck rather than by construction.
    future_sight_move: str = ""
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
    #: Set when a ROAMER got away. Terminal and unrecoverable: the battle ends, and the roamer is
    #: moved to another route by `MoveRoamersOffMap`, so the next attempt starts by hunting for it
    #: again (notes/roamers.md sec 3). A lost run like `party_wiped`, not a lost turn.
    #:
    #: Only reachable with `sim.HuntConfig.target_is_roamer`; a static target has no way to set it.
    target_fled: bool = False
    log: list = field(default_factory=list)

    @property
    def our_attack_stage(self) -> int:
        return self.ours.atk_stage

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
                or self.target.fainted or self.party_wiped or self.target_fled)

    def copy(self) -> "BattleState":
        return BattleState(
            ours=self.ours, target=self.target, rng=self.rng, bench=self.bench,
            turn=self.turn, phase=self.phase,
            target_trapped=self.target_trapped,
            mist_turns=self.mist_turns, rain_turns=self.rain_turns,
            safeguard_turns=self.safeguard_turns,
            our_safeguard_turns=self.our_safeguard_turns,
            target_water_sport=self.target_water_sport,
            target_lucky_chant_turns=self.target_lucky_chant_turns,
            reflect_turns=self.reflect_turns, light_screen_turns=self.light_screen_turns,
            future_sight_turns=self.future_sight_turns,
            future_sight_damage=self.future_sight_damage,
            future_sight_move=self.future_sight_move,
            faints=self.faints,
            rng_offset=self.rng_offset, balls_thrown=self.balls_thrown,
            captured=self.captured, captured_in_wrong_ball=self.captured_in_wrong_ball,
            target_fled=self.target_fled,
            log=list(self.log))
