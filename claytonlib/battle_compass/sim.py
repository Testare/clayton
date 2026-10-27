"""Turn simulation for Battle Compass.

Simulates **forwards only**: given a seed and the action the player took, produce the tokens that
seed would emit.  Filtering a candidate set is then a comparison against what the player
reported, which is why there is no interactive mirror of this (sec 13.1).

Only the nine moves the reference fixture needs are implemented, and each is cross-validated
against ``metronome_compass``'s verified handler for the same effect id — that free check is what
makes duplicating nine of 235 handlers cheap rather than reckless (sec 15.2).

**Which numbers here are verified, and which are not.** The per-turn skeleton is verified on the
emulator and lives in ``claytonlib.battle.turn``.  The per-move roll counts below are derived
from the pattern ``metronome_compass`` uses (an accuracy roll when the move can miss, two more
for a damaging move's crit and damage rolls, one more for a secondary effect's proc) and are the
R7 residual — still to be confirmed outside the Blackthorn matchup.  Two ordering choices follow
``metronome_compass.simulate_turn`` rather than independent measurement, and are flagged at the
point of use: the wild move-selection roll opening the turn, and a paralysis check costing one
roll before the move it prevents.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from claytonlib.battle import turn as turn_costs
from claytonlib.battle.balls import BallEffect, ThrowContext, ball_effect, is_turn_dependent
from claytonlib.battle.catch import (
    BALL_POKE, SHAKES_TO_CAPTURE, catch_value, fast_ball_catch_rate, is_guaranteed,
    shake_threshold, shakes_for_rolls,
)
from claytonlib.battle.damage import (
    WEATHER_NONE, WEATHER_RAIN, Attacker, Defender, apply_accuracy_items, apply_accuracy_stage,
    apply_stage, damage, is_type_immune, item_key, unsupported_attacker_reason,
    unsupported_reason,
)
from claytonlib.battle.readiness import (
    LEFTOVERS, PARALYSIS_SPEED_DIVISOR, speed_after_item,
)
from claytonlib.battle_compass import items, tokens as tok
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.moves import CATEGORY_STATUS, Move
from claytonlib.safari import advance_rng

#: Sleep lasts ``2 + RAND % 4`` turns, and the roll is spent when sleep is APPLIED -- one extra
#: advance beyond the accuracy check, invisible to the player at the time. Cross-validated
#: against ``metronome_compass.effects._eff_sleep``, which is where this was found: a successful
#: Spore spent one roll here and two there, desynchronising every turn after it.
SLEEP_DURATION_MIN = 2
SLEEP_DURATION_SPAN = 4

#: Move effect ids that can cause a flinch: 31 (the generic "may flinch"), 150 (Stomp) and
#: 158 (Fake Out). Nothing in Suicune's moveset is among them, which is why "flinched" must not
#: be offered as an outcome against it -- but Extrasensory is in both Lv45 bird sets and Zen
#: Headbutt in both Pewter sets, so it is live for every target after the first.
#:
#: A flinched turn spends **no roll of its own**, and the flinch is checked **before** the
#: paralysis check. Both taken from ``metronome_compass``, which is RNG-verified against
#: Blackthorn ground truth and resolves a turn in the order sleep -> freeze -> flinch ->
#: confusion -> paralysis, emitting the flinch with ``raw_emit`` (no advance). The proc roll
#: itself is already spent by the flincher's own move, through ``effect_chance``.
#:
#: The order matters only when a Pokemon is both paralyzed and flinched, which among these
#: targets arises solely against Latios -- its Dragon Breath can leave us paralyzed on an
#: earlier turn than its Zen Headbutt flinches us.
FLINCH_EFFECTS = frozenset({31, 150, 158})


#: Move effect ids whose behaviour is **fully accounted for when the TARGET uses the move**.
#:
#: This list exists because `execute_move` fails SILENTLY on anything else. An unknown status
#: move is treated as "it worked and changed nothing", and an unknown damaging move as plain
#: damage -- so an unmodelled secondary is not refused, it is quietly inert. For incoming damage
#: that is unsound rather than imprecise: it eliminates the true seed.
#:
#: `targets.unsupported_moves` turns this into a configuration-time refusal, so a target can
#: never be "configured" and silently mis-simulated at the same time.
MODELLED_TARGET_EFFECTS: dict[int, str] = {
    0: "no effect beyond damage",
    # Darkrai's four, and the first status move any target has had. Each needed its own piece of
    # machinery before it could be listed here -- see `act_target`, which until Darkrai threw
    # away `applied_status` outright, so a target's Hypnosis was the exact "inert rather than
    # refused" failure this table exists to prevent.
    1: "Hypnosis: sleep ON US, its hidden duration roll, and the turns it costs",
    16: "Double Team: the target's own evasion, which makes our 100%-accuracy moves missable",
    17: "Faint Attack: accuracy 0, so it never misses and spends no accuracy roll",
    107: "Nightmare: the volatile, its quarter-max-HP residual, and waking up as the cure",
    # Giratina's, and the first two-turn move on either side. Listed once all three of its
    # consequences are modelled: the charge turn spends no rolls, the fire turn spends no
    # SELECTION roll, and while it is away everything we throw at it misses -- after spending
    # its rolls (see `execute_move`).
    272: "Shadow Force: the charge turn, the move lock, and the turn it cannot be hit",
    # Heatran's three. 60 and 62 are TWO-stage drops on us, which is what makes this target
    # different in kind from the others: Scary Face can flip turn order, and the no-speed-tie
    # guarantee is what keeps ties out of the search entirely.
    60: "Scary Face: two Speed stages off US, which can flip turn order",
    62: "Metal Sound: two Sp. Def stages off us, raising every special hit after it",
    69: "Crunch: damage plus a 20% Defence drop on us (`SECONDARY_STAT_DROPS`)",
    70: "Rock Tomb and friends: damage plus a Speed drop, the same table",
    # Gust's effect is "double power against a Flying target"; against a grounded Pokemon in a
    # single battle it is plain damage, and it is in the emulator-verified Suicune fixture.
    149: "double power vs airborne, which never applies here",
    4: "may burn: the status, its deterministic tick, and its halved physical Attack",
    31: "may flinch -- applied, and suppressed when unobservable (`flinch_visible`)",
    # Aeroblast, and the only reason Lugia's Lv45 set was refused. Listed as modelled once the
    # crit stage reached `execute_move`: before that the move was simulated as plain damage at
    # 1/16, which is the "inert rather than refused" failure this table exists to prevent.
    43: "high crit ratio: one crit stage up, so `% 8` rather than `% 16`",
    46: "Mist: field condition, and it blocks our stat drops",
    68: "lowers our Attack, which raises how many False Swipes the target needs",
    71: "lowers our Sp. Atk, which lowers the special damage WE deal",
    72: "lowers our Sp. Def, which raises every later special hit we take",
    124: "Safeguard: blocks our status moves for five turns, and a second one fails",
    125: "may burn -- as effect 4",
    136: "Rain Dance: field condition, and the weather term in `battle.damage`",
    140: "Ancient Power: raises every one of the target's stats, Speed included",
    193: "Refresh: fails against an unstatused user",
    # Foresight and Odor Sleuth aimed at US. Unreachable: no configured encounter has either, and
    # a target that did would be using its turn to make our Normal moves work. Listed because the
    # machinery is genuinely symmetric -- `act_target` sets the flag on `new.ours` the same way
    # `act_ours` sets it on `new.target`, and the only thing it would change is whether the
    # target's own Normal/Fighting moves can touch a Ghost or a Gengar of ours.
    113: "Foresight, Odor Sleuth: the flag on US, so its Normal moves reach a Ghost of ours",
    210: "Water Sport: a per-battler volatile flag, so a second one fails",
    245: "Punishment: power computed from our positive stages (`punishment_power`)",
    # Uxie's and Azelf's. Three of the five are the first of their kind on either side, and the
    # two end-of-turn ones are the only entries in this table whose roll POSITION is derived
    # rather than measured -- see `_END_OF_TURN_RESIDUAL_ANCHOR`, which says what is still owed.
    53: "Nasty Plot: Sp. Atk +2 on the target itself, which doubles its special damage",
    54: "Amnesia: Sp. Def +2 on the target itself, which halves what our special moves do",
    148: "Future Sight: one roll at use, the banked damage, and the hit check two turns later",
    159: "Uproar: the 3-6 turn lock, the selection roll it skips, and the sleep it forbids",
    187: "Yawn: the two-turn drowse, and the sleep (and its duration roll) that follows it",
}


#: Move effect ids whose behaviour is fully accounted for when **WE** use the move.
#:
#: The mirror of `MODELLED_TARGET_EFFECTS`, and it did not exist until clayton-957.10.2. The
#: asymmetry was the bug: `targets.unsupported_moves` refuses a target whose moveset the simulator
#: cannot model, while our own side had no check at all -- so Flash, Screech and Charm could be
#: planned into a run and silently simulated as doing nothing.
#:
#: Our side is treated more leniently than the target's on purpose. An unmodelled move of the
#: TARGET's is unavoidable: it picks its own moves, so the run is unsound the moment one fires.
#: An unmodelled move of ours is avoidable -- we simply do not select it, and `allowed_moves`
#: keeps the solver off it too. So this reports rather than refuses, and the caller decides.
MODELLED_OUR_EFFECTS: dict[int, str] = {
    0: "no effect beyond damage",
    1: "Spore and friends: sleep, including the hidden duration roll",
    4: "may burn: the status, its tick, and its halved physical Attack",
    6: "may paralyze (Discharge, Thunderbolt)",
    18: "lowers the target's Attack (Growl)",
    19: "lowers the target's Defence (Tail Whip, Leer)",
    20: "lowers the target's Speed (String Shot)",
    23: "lowers the target's accuracy (Flash)",
    24: "lowers the target's evasion (Sweet Scent), and Mist blocks it",
    31: "may flinch, and suppressed when unobservable",
    35: "Light Screen: halves special damage, and a second one fails",
    # Nothing in the planned parties uses one, but `crit_stage_of` reads the move rather than the
    # side, so a Sketched Night Slash or Psycho Cut simulates correctly and may as well say so.
    43: "high crit ratio: one crit stage up, so `% 8` rather than `% 16`",
    # Nasty Plot and Amnesia. Reached through `PRIMARY_SELF_RAISES` on both halves of the turn, so
    # a party member carrying either is modelled for free -- unlike Uproar, Yawn and Future Sight,
    # which are deliberately NOT listed: each needs state only the target's side maintains, and
    # nothing a party can carry has them.
    # --- the pure stat-stage family, in full ---
    #
    # Every effect whose script is a single `MOVE_SIDE_EFFECT_*|MOVE_SUBSCRIPT_PTR_<stat>_<up or
    # down>_<n>_STAGE(S)` plus `End`. There are 23 of them and they are listed exhaustively
    # rather than as the ones a party happens to carry, because the whole family costs the same
    # nothing and reaches the same two tables -- so a player who brings Bulk Up should not be
    # told it is unmodelled when the only reason it was absent is that nobody had typed it.
    #
    # None of them spends a roll: the subscripts contain no `Random`, and every self-raise has
    # accuracy 0 (the TARGET-facing drops have real accuracies and spend an accuracy roll, which
    # they already did). `will_fail` covers the ceiling and floor cases; see it for the
    # single-stat / two-stat asymmetry, which is the one place they differ from each other.
    10: "Meditate, Sharpen, Howl: our own Attack +1",
    11: "Harden, Withdraw: our own Defence +1",
    13: "Growth: our own Sp. Atk +1",
    # Double Team was listed for the TARGET only, because Darkrai is where it came from. It is
    # the same table row either way, and a party member really can carry the TM -- raising our
    # own evasion makes the target's moves missable, which `_effective_accuracy` already reads.
    16: "Double Team: our own evasion +1, which makes the target's moves missable",
    50: "Swords Dance: our own Attack +2, which raises the physical damage WE deal",
    51: "Barrier, Acid Armor, Iron Defense: our own Defence +2",
    # Agility and Rock Polish. The one entry in the family that can change a turn's COST rather
    # than only its damage, because Speed decides order and an effective-Speed tie spends extra
    # rolls. Modelled, with `readiness.speed_move_ties` warning before one is walked into.
    52: "Agility, Rock Polish: our own Speed +2 — and the tie risk that comes with it",
    # The four two-stat boosters. Same zero cost, different failure: their own subscript tests
    # every stat before calling `ChangeStatStage` at all.
    206: "Cosmic Power, Defend Order: our own Defence and Sp. Def +1",
    208: "Bulk Up: our own Attack and Defence +1",
    211: "Calm Mind: our own Sp. Atk and Sp. Def +1",
    212: "Dragon Dance: our own Attack and Speed +1 — Speed, so the tie risk applies",
    # Tickle, the only two-stat drop, and the mirror of the four above.
    205: "Tickle: the target's Attack and Defence −1",
    53: "Nasty Plot: our own Sp. Atk +2, which raises the special damage WE deal",
    54: "Amnesia: our own Sp. Def +2, which lowers every special hit we take",
    58: "lowers the target's Attack by two (Charm)",
    59: "lowers the target's Defence by two (Screech)",
    60: "lowers the target's Speed by two (Scary Face)",
    62: "lowers the target's Sp. Def by two (Fake Tears, Metal Sound)",
    65: "Reflect: halves physical damage, and a second one fails",
    67: "paralyzes (Thunder Wave)",
    76: "may confuse (Signal Beam) -- the proc roll only; confusion ON THE TARGET is inert here",
    101: "False Swipe: damage that cannot take the target below 1 HP",
    106: "Mean Look: traps, and a second one fails",
    # Foresight and Odor Sleuth, and the first move of ours that changes the TYPE CHART. Listed
    # as modelled only once both halves of the flag were read -- the Ghost immunities in
    # `battle.damage` and the evasion term in `accuracy_net_stage`. Before that it was the exact
    # "inert rather than refused" failure `MODELLED_OUR_EFFECTS` exists to catch: a status move
    # with no recognised effect simulates as having worked and changed nothing, which for this
    # one means every False Swipe afterwards still predicted zero against a Ghost.
    113: "Foresight, Odor Sleuth: the Ghost immunities off and the target's evasion ignored",
    125: "may burn -- as effect 4",
    136: "Rain Dance: field condition and the weather term",
    # Taunt, and it is listed as modelled only because `usable_slots` narrows the selection rather
    # than something pretending to refuse the move afterwards. See `EFFECT_TAUNT`.
    175: "Taunt: the 3-5 turn lock, and the selection modulus it narrows",
    # Haze, and it spends nothing. Listed for OUR side only: no configured target has it, and the
    # `act_target` mirror is wired for symmetry.
    25: "Haze: every stat stage on BOTH sides back to neutral, for no rolls at all",
    149: "double power vs airborne, which never applies in a single battle on the ground",
    # Surf, and it is in here for exactly the reason 149 above is. Effect 257 is
    # `MOVE_EFFECT_DOUBLE_DAMAGE_DIVE` (include/constants/move_effects.h:255), the mirror of
    # 149's `MOVE_EFFECT_DOUBLE_DAMAGE_FLY_OR_BOUNCE` -- a conditional multiplier against a
    # target that is underwater from Dive. Nothing any configured encounter can do puts it
    # there, so the condition never holds and the move is plain damage. Cross-validated:
    # `metronome_compass.effects` maps 257 to `_eff_damage`, with no extra roll.
    #
    # Here because Lugia is at the Whirl Islands, so a party member has to carry Surf to get
    # there at all (`targets.ENCOUNTER_ACCESS`) -- and a move sitting in a real moveset should
    # not read as a coverage gap when it is genuinely inert.
    257: "Surf: double damage vs a Dive target, which nothing here can be",
}


def unselectable_reason(move: Move, defender: "Battler | None" = None) -> str | None:
    """Why the interview must not let us pick `move` this turn, or None if it may.

    **Carrying a move and being able to report a turn that used it are different things**, and
    the split matters because a party slot is not free: Lugia is behind Surf and Whirlpool, so a
    mule has to come along, and refusing to let a Pokemon hold Whirlpool would mean refusing the
    only route to the encounter (`targets.ENCOUNTER_ACCESS`). So the move is allowed on the
    Pokemon and refused at the point of use.

    Two families, both of which make the run unrecoverable rather than merely worse -- which is
    why this is a refusal where `MODELLED_OUR_EFFECTS` coverage is advice:

    * **The simulator cannot model the effect.** `execute_move` has no notion of an unknown one:
      an unknown status move is treated as having worked and changed nothing, and an unknown
      damaging move as plain damage. Either way the predicted stream and the real one part
      company on that turn, and because every candidate is compared exactly, the true seed is
      eliminated with no contradiction raised. Whirlpool is the case this was written for --
      effect 261, which `metronome_compass` resolves as `_eff_bind`, so the game spends a hidden
      duration roll we do not and then chips the target every turn afterwards.
    * **The move would end the battle.** Teleport and Roar, per `RUN_ENDING_EFFECTS`: the target
      is gone and there is no turn left to report.

    Deliberately NOT a reason to refuse: a move that merely does nothing useful, or one that
    `will_fail` says is certain to fail. Those are legal, reportable turns -- and a failing Sing
    against a paralyzed target is one of the sharpest identification probes there is
    (notes/seed_separation.md), so refusing it would cost the run information rather than save it.
    """
    if move.effect in RUN_ENDING_EFFECTS:
        return f"{move.name} would end the battle with the target uncaught."
    if defender is not None and absorbs(defender, move):
        # A third family, and it is about the PAIRING rather than the move: the same Flamethrower
        # is fine against anything without Flash Fire. See `ABSORBED_MOVE_TYPES` for why it is
        # refused instead of simulated as a failure -- the absorb raises the holder's own Fire
        # power, so the next Lava Plume would hit harder than any candidate predicted.
        return (f"{defender.name}'s {defender.ability} absorbs {move.name} and gets something "
                f"for it, which is not modelled.")
    if move.effect not in MODELLED_OUR_EFFECTS:
        # The two failure modes are different, and saying "changed nothing" for a damaging move
        # was both wrong and reassuring in the wrong direction. An unknown STATUS move is treated
        # as having worked and done nothing, which is inert; an unknown DAMAGING move is treated
        # as plain damage, which is not -- any extra roll the real move spends (a trap duration,
        # a charge turn) desynchronises the stream from that turn on, and any residual it leaves
        # keeps the predicted HP wrong forever.
        return (f"{move.name} (effect {move.effect}) is not modelled: it would simulate as "
                + ("plain damage, desynchronising the run."
                   if move.category != CATEGORY_STATUS else
                   "doing nothing, mis-predicting the turn."))
    return None


def unsupported_our_moves(moves, defender: "Battler | None" = None
                          ) -> tuple[tuple[str, str], ...]:
    """``((move name, why), ...)`` for each of OUR moves the simulator cannot fully model.

    Advisory at CONFIGURATION time, unlike `targets.unsupported_moves` -- see
    `MODELLED_OUR_EFFECTS` for why the two differ. The slot is kept out of
    `SolverConfig.allowed_moves` and the interview refuses it at the point of use
    (`unselectable_reason`), so this reports rather than blocks: a mule carrying Whirlpool to
    reach the Whirl Islands is a legitimate party, it just must not be told to use it.

    Shares its rule with `unselectable_reason` rather than restating it, so the warning on the
    configure page and the disabled chip in the interview can never disagree about which moves
    they mean.

    `moves` is an iterable of names or of `Move`s, so a caller can pass a `Battler.moves` tuple or
    the already-resolved list it happens to hold.
    """
    from claytonlib.moves import resolve_move

    problems: list[tuple[str, str]] = []
    for entry in moves:
        if entry is None or entry == "":
            continue
        move = entry if isinstance(entry, Move) else resolve_move(entry)
        if move is None:
            problems.append((str(entry), "is not in the move table at all"))
            continue
        reason = unselectable_reason(move, defender)
        if reason is not None:
            problems.append((move.name, reason))
    return tuple(problems)


def can_flinch(battler) -> bool:
    """Whether any of `battler`'s known moves can make the other side flinch."""
    return any((m := battler.move(slot)) is not None and m.effect in FLINCH_EFFECTS
               for slot in range(len(battler.moves)))


def flinch_visible(victim: "Battler", *, victim_selected_a_move: bool,
                   victim_moves_second: bool) -> bool:
    """Whether a flinch inflicted on `victim` is observable at all.

    A flinch lasts only the turn it is inflicted and announces itself only when the victim
    *tries to use a move* -- so unlike every other secondary effect, a procced flinch can leave
    no trace whatsoever. **The one case where it shows is a victim that selected a move and is
    moving second.** Everything else hides it:

    * **The victim did not select a move at all.** A bag action -- an item, either ball, a switch,
      a Revive -- resolves BEFORE any move, so the victim has already had its turn and there is
      nothing left for the flinch to stop. Same for a victim that was fainted before moving.
      These are stated as their own condition rather than left to fall out of turn order, which
      is how they were covered before: bag actions force the user to act first, so the
      already-acted case was correct only as a side effect of that coupling.
    * **The victim moves first**, by Speed or by priority bracket -- it has acted by the time the
      flinch lands.
    * **The flinch came with a KO.** A fainted victim never reaches its move.
    * **The victim is asleep and staying asleep.** Derived rather than measured: sleep is checked
      before flinch (the verified order is sleep -> freeze -> flinch -> confusion -> paralysis),
      so "is fast asleep" is the message shown and the flinch is masked. Paralysis is *not* on
      this list, and deliberately: it is checked after flinch, so a flinched-and-paralyzed victim
      reports the flinch.

    The proc roll is spent either way -- it belongs to the flincher's own move, through
    ``effect_chance`` -- so suppressing the token costs the turn no advances. It costs
    *information*: an invisible flinch is one the candidate set cannot be filtered on. That is
    the correct trade, because the alternative is filtering on an answer the player is guessing.
    """
    if not victim_selected_a_move or not victim_moves_second or victim.fainted:
        return False
    return not (victim.status is Status.SLEEP and victim.sleep_turns > 1)


#: Crit modifiers by stage; a crit lands when ``roll % modifier == 0``.
CRIT_MODIFIERS = (16, 8, 4, 3, 2)

#: Move effects in the **high-crit-ratio group**, which start one crit stage up -- so they land a
#: critical hit on ``roll % 8 == 0`` rather than ``roll % 16 == 0``.
#:
#: Cross-validated against ``metronome_compass.effects`` rather than inferred, which is the
#: project's rule for anything RNG-shaped: that module resolves all three through
#: ``hit_crit_or_miss(..., crit_stage=1)`` and is verified against Blackthorn ground truth.
#: ``_eff_high_crit`` is 43, ``_eff_burn_highcrit`` is 200 and ``_eff_poison_highcrit`` is 209.
#:
#: Effect 43 is the big one: Karate Chop, Razor Leaf, Crabhammer, Slash, **Aeroblast**, Cross
#: Chop, Air Cutter, Leaf Blade, Night Slash, Shadow Claw, Psycho Cut, Stone Edge, Attack Order
#: and Spacial Rend. Aeroblast is in BOTH Lugia movesets, which is what made this urgent: at
#: ``CRIT_MODIFIERS[0]`` the simulator disagreed with the game whenever
#: ``roll % 8 == 0 and roll % 16 != 0`` -- 1/16 of Aeroblast turns against a 1/4 move choice, so
#: 1.56% of turns, which is a ~47% chance of eliminating the true seed over a 40-turn run. And
#: wrong in two ways on the same turn: the ``h``/``!`` token AND the damage, since a crit doubles
#: it.
#:
#: **The roll COUNT is unchanged** -- ``hit_crit_or_miss``'s own docstring says so ("same RNG roll
#: count as standard"), and that is what keeps this away from every verified advance count. It is
#: an outcome-only correction.
HIGH_CRIT_EFFECTS = frozenset({43, 200, 209})


def crit_stage_of(move: Move, attacker: "Battler" = None) -> int:
    """The crit stage a hit by `move` is rolled at, capped at the table's top entry.

    Two contributions, kept separate because only one of them exists yet: the move's own group
    (`HIGH_CRIT_EFFECTS`), and the attacker's accumulated stage from a Focus Energy or a Dire
    Hit or a Scope Lens. Nothing in any configured party or moveset has the second, so `Battler`
    carries no crit stage and `attacker` is accepted and read defensively -- the signature is
    here so that adding one is a field rather than a re-reading of this call site.
    """
    stage = 1 if move.effect in HIGH_CRIT_EFFECTS else 0
    stage += getattr(attacker, "crit_stage", 0) or 0
    return min(stage, len(CRIT_MODIFIERS) - 1)
#: Gen 4 damage variance, transcribed from ApplyDamageRange (src/battle/overlay_12_0224E4FC.c):
#:
#:     damage *= (100 - (BattleSystem_Random(battleSystem) % 16));
#:     damage /= 100;
#:
#: Sixteen multipliers spanning 85..100 percent -- but note the direction. The RNG value is
#: SUBTRACTED, so ``% 16 == 0`` is a 100% roll and ``% 16 == 15`` is 85%. This was implemented as
#: ``85 + roll % 16``, which spans the same set and is therefore invisible to any range check,
#: while getting all sixteen individual values wrong. Caught by data/battle_logs/test1.jsonl,
#: where a roll of ``% 16 == 13`` dealt LESS damage than one of ``% 16 == 9``.
DAMAGE_ROLL_COUNT = 16
DAMAGE_ROLL_MAX_PERCENT = 100


def advance(rng: int) -> tuple[int, int]:
    """Advance once, returning (new state, the roll's high 16 bits)."""
    state = advance_rng(rng)
    return state, state >> 16


@dataclass(frozen=True)
class MoveOutcome:
    """What one move did, and what it cost."""
    rolls: int
    tokens: tuple[str, ...]
    successful: bool
    damage: int = 0
    applied_status: Status | None = None
    #: Rolled sleep duration, when this move applied sleep. Zero otherwise.
    sleep_turns: int = 0
    secondary: bool = False
    #: Field conditions this move set. Applied by `simulate_turn`, which owns the state.
    sets_rain: bool = False
    sets_mist: bool = False
    traps: bool = False
    sets_water_sport: bool = False
    sets_safeguard: bool = False
    #: The ``(stage field, stages)`` pairs this move drops on its target, or None. Applied by
    #: `simulate_turn`, which owns the state -- and which knows which side the target is.
    #: A tuple because Tickle drops two stats; everything else in the family drops one.
    stat_drop: tuple[tuple[str, int], ...] | None = None
    #: A screen this move put up on the user's side, and for how many turns (Light Clay).
    sets_reflect: bool = False
    sets_light_screen: bool = False
    screen_turns: int = 0
    #: A status inflicted on the move's OWN USER by the defender's ability -- Static's paralysis.
    #: Named for the attacker because that is who it lands on, which is the opposite of every
    #: other field here.
    attacker_status: Status | None = None
    #: Nightmare landed on the defender. A volatile rather than a status, so it travels in its
    #: own field instead of in `applied_status` -- it coexists with the sleep it requires.
    sets_nightmare: bool = False
    #: The move slot this move's CHARGE turn just locked its user into, or None. Shadow Force's
    #: first turn: no rolls, nothing lands, and the user is away until it fires.
    starts_charge: int | None = None
    #: Set on the turn a charged move actually fires, so the lock and the vanish come off.
    ends_charge: bool = False
    #: The ``(stage field, stages)`` pairs this move raises on its OWN USER -- Double Team's
    #: evasion, Swords Dance's Attack, Dragon Dance's Attack AND Speed. The mirror of
    #: `stat_drop`, and a separate field for the same reason `attacker_status` is: the side it
    #: lands on is the opposite one, and `simulate_turn` is what knows which side that is.
    self_stat_raise: tuple[tuple[str, int], ...] | None = None
    #: True when Mist blocked the stat drop. The move still counts as SUCCESSFUL -- verified on
    #: turn 15 of test1.jsonl, which spent its post-successful-move advances anyway.
    blocked_by_mist: bool = False
    #: Foresight or Odor Sleuth landed, so the move's DEFENDER is now identified. Aimed at the
    #: other side, like `stat_drop` and unlike `self_stat_raise`, which is why `simulate_turn` is
    #: what applies it -- only it knows which side that is.
    identifies: bool = False
    #: Haze: every stat stage on BOTH sides goes back to neutral. A flag rather than a list of
    #: fields, because the ROM's own loop is over every battler and every stage without exception.
    resets_all_stages: bool = False
    #: Turns of Taunt this move just rolled for its VICTIM, or 0. Ours to inflict; the mirror in
    #: `act_target` is wired for symmetry and no configured target has the move.
    starts_taunt: int = 0
    #: Turns of Uproar this move just rolled for its user, or 0. Azelf's, and the value is the
    #: TOTAL including the turn it was used on (`UPROAR_TURNS_MIN`..+span).
    starts_uproar: int = 0
    #: Yawn made its victim drowsy. A flag rather than a count, because the count is a constant
    #: (`YAWN_DROWSY_TURNS`) and the victim is whichever side `simulate_turn` aimed the move at.
    sets_drowsy: bool = False
    #: Damage a Future Sight just banked against its victim, or None if this was not one. Zero is
    #: a possible banked value, so the sentinel has to be None rather than 0 -- an immune or
    #: hopelessly outclassed attacker still puts a Future Sight in the air.
    banked_future_sight: int | None = None


def move_roll_cost(move: Move) -> int:
    """An UPPER BOUND on the rolls executing `move` spends.

    An accuracy roll when the move can miss, two more for a damaging move (crit and damage), one
    more for a secondary effect's proc roll, and one more when the move applies sleep.

    A bound rather than a count, because the real cost depends on the outcome: a move that misses
    spends no damage rolls, and sleep's duration roll happens only when the status actually lands.
    ``execute_move`` returns the true figure in ``MoveOutcome.rolls``; nothing should use this to
    advance an RNG stream. Cross-validated against ``metronome_compass.effects`` for all nine
    fixture moves (tests/test_battle_compass_effects_parity.py).
    """
    # Future Sight is the one move whose cost is not built from the usual parts at all, and it is
    # one either way it goes: on the turn it LANDS the effect script banks the damage with a
    # single roll and switches the accuracy check off, and on a turn where one is already in the
    # air it jumps past that switch and pays an ordinary accuracy roll instead (see
    # `execute_move`). The hit check it defers is an END-OF-TURN roll two turns later and belongs
    # to no move's cost (`_fire_future_sight`).
    if move.effect == EFFECT_FUTURE_SIGHT:
        return 1
    rolls = 1 if move.accuracy > 0 else 0
    if move.category != CATEGORY_STATUS:
        rolls += 2
    if move.effect_chance > 0:
        rolls += 1
    if status_applied_by(move) is Status.SLEEP:
        rolls += 1
    if move.effect == EFFECT_TAUNT:
        # Its hidden duration, spent only when the Taunt actually lands -- a second one against an
        # already-taunted target fails before the Random. An upper bound, like the sleep line.
        rolls += 1
    if move.effect == EFFECT_UPROAR:
        # The duration roll, spent only when the Uproar actually STARTS -- a continuation turn
        # re-runs the effect script, finds the volatile already set and jumps straight to
        # CalcCrit/CalcDamage (`effect_script_0159.s`). An upper bound, like the sleep line above.
        rolls += 1
    return rolls


def accuracy_net_stage(attacker: "Battler", defender: "Battler") -> int:
    """The single stage the accuracy check uses: the attacker's accuracy minus the defender's
    evasion, clamped to -6..+6. Combining them is what the game does, and keeping it in one
    function is what stops the simulator and the interview disagreeing about it.

    **A Foresighted defender's evasion term is dropped when -- and only when -- it favours the
    defender.** `CheckMoveHitAccuracy` holds the evasion contribution negated
    (``evaStages = 6 - statBoosts[EVASION]``, so a raised evasion is a *negative* term) and then
    does ``if (MON_IS_IDENTIFIED(defender) && evaStages < 0) evaStages = 0``
    [battle_controller_player.c:2876-2890]. So a +3 evasion is ignored while a -3 from our Flashes
    and Sweet Scents still counts -- the asymmetry is the ROM's, and reading it as "evasion is
    neutralised" would throw away the accuracy work a run spends turns on.

    The clamp is the ROM's too: it bounds ``6 + evaStages + accStages`` to 0..12, which is this
    function's -6..+6.
    """
    evasion = defender.evasion_stage
    if defender.identified:
        evasion = min(0, evasion)
    return max(-6, min(6, attacker.accuracy_stage - evasion))


def _effective_accuracy(move: Move, net_stage: int = 0, *, attacker=None,
                        defender=None, deferred_check: bool = False,
                        charge_turn: bool = False) -> int:
    """Accuracy after the combined accuracy/evasion stage.

    0 means the move bypasses the check entirely. `net_stage` is the attacker's accuracy stage
    minus the defender's evasion stage -- NOT evasion alone, since an accuracy drop on the
    attacker makes a 100%-accuracy move missable just as a raised evasion does.

    This computed the stage as a fraction (``accuracy * 3 // (3 - net)`` below zero) and was
    wrong at **-5 and -4**, because the ROM reads a table whose entries are not the fraction
    there -- see `battle.damage.apply_accuracy_stage`, which is now the only place that knows it.
    Not an imprecision: a flipped verdict renders the wrong token and eliminates the true seed
    (clayton-957.27).

    `attacker` and `defender` are read for their HELD ITEMS only -- the stage already arrives in
    `net_stage`. A Brightpowder on the defender cuts the hit chance by a tenth and a Wide Lens on
    the attacker raises it, and both are applied AFTER the stage table because every step
    truncates (`battle.damage.apply_accuracy_items`). Optional, because `can_miss` has callers
    that know neither battler and a missing item is simply no modifier.
    """
    if move.accuracy == 0:
        return 0
    if charge_turn:
        # "Charge-up moves don't consider accuracy on their first turn" --
        # `CheckMoveHitAccuracy` returns 0 before its roll [battle_controller_player.c:2905-2907].
        # The same shape as the Future Sight line below: a real accuracy on the move, bypassed on
        # this particular turn, so the caller has to say which turn it is asking about.
        return 0
    if move.effect == EFFECT_FUTURE_SIGHT and not deferred_check:
        # The accuracy check does not happen on the turn this move is USED: the effect script
        # sets `SYSCTL_NONSTANDARD_ACC_CHECK` and `CheckMoveHitAccuracy` returns 0
        # (battle_controller_player.c:2912-2915). The real 90% roll is made at the end of the
        # turn it lands, two turns later -- `_roll_future_sight`, which is the one caller that
        # passes `deferred_check=True`. Answering 90 here put "Missed" in the interview's options
        # for a turn whose only grammatical rendering is the bare slot.
        return 0
    accuracy = apply_accuracy_stage(move.accuracy, net_stage)
    return apply_accuracy_items(
        accuracy,
        defender_item=getattr(defender, "held_item", "") or "",
        attacker_item=getattr(attacker, "held_item", "") or "")


def can_miss(move: Move, net_stage: int = 0, *, attacker=None, defender=None,
             charge_turn: bool = False) -> bool:
    """Whether an accuracy roll can actually fail.

    Accuracy 0 bypasses the check, and accuracy 100 at a neutral or positive stage passes it
    always -- ``roll % 100 < 100`` can never be false -- so neither can miss. But this is
    stage-dependent, not a property of the move: Spore at 100% becomes missable as soon as our
    accuracy is dropped or the target's evasion is raised, and reporting it as unmissable then
    would suppress a legitimate "missed".

    It is also ITEM-dependent, which is the newer half: a Brightpowder on the target makes a
    100-accuracy Spore missable at a neutral stage, so an interview that did not know about the
    item would refuse to let the player report a miss that really happened.

    **Future Sight answers False**, despite its accuracy of 90, and that is the right answer to
    the question this function is actually asked: it is asked about the turn a move is USED, and
    a Future Sight cannot miss on that turn. Its check is deferred to the end of the turn it
    lands, where the verdict gets a token of its own (`tokens.FUTURE_SIGHT`).

    `charge_turn` is the same shape of answer for the other move whose accuracy belongs to a
    different turn from the one it was picked on: a Shadow Force on its charge turn cannot miss,
    because the check is skipped entirely and spends no roll (`starts_charge_turn`). Unlike
    Future Sight's, this one cannot be read off the move -- the same move DOES roll accuracy on
    its second turn -- so the caller has to say which turn it means.
    """
    return 0 < _effective_accuracy(move, net_stage, attacker=attacker, defender=defender,
                                   charge_turn=charge_turn) < 100


def will_fail(move: Move, defender: "Battler", field=None, *, actor: "Battler" = None) -> bool:
    """Whether this move is certain to do nothing, from state alone.

    Eight families now, all costing the turn its two post-successful-move advances when they fire
    -- which is exactly how the emulator log diverged from this simulator on turn 3, so each
    addition here is a bug avoided rather than a nicety:

    * A status-inflicting move against an already-statused target -- non-volatile statuses are
      mutually exclusive (sec 4.2). "But it failed!"  [verified: test1.jsonl]
    * A field-condition move whose condition is already up: Rain Dance while raining, Mist while
      misted. Suicune re-used both repeatedly in the log.  [verified: test1.jsonl]
    * Mean Look against an already-trapped target.  [verified: test1.jsonl]
    * **Refresh with nothing to cure.** Self-targeting, so it reads `actor`, not `defender` --
      the one family here that does. It cures burn, paralysis and poison only, so an unstatused
      user simply fails. Once sleep is the Phase 2 status this is the COMMON case rather than an
      edge one: an awake, unstatused Latias wastes roughly one turn in four on it
      (notes/battle_compass_next_targets.md sec 4b).
    * **Water Sport while it is already up.** Mirrors
      ``metronome_compass.effects._eff_water_sport``, which returns False when `user_water_sport`
      is already set.

    * **Any sleep move, and Yawn, while an Uproar is running.** The one family here that is
      about the FIELD rather than about either Pokemon, and it is the reason Azelf cannot be
      slept through its own Uproar: `subscript_fall_asleep`'s ``_292``/``_311`` branches refuse
      the status outright ("But {0} can't sleep in an uproar!"), and `subscript_yawn`'s ``_077``
      does the same to Yawn. The duration roll is INSIDE the branch they skip, so a refused
      sleep spends no roll -- which is what makes this a `will_fail` entry rather than a
      post-hoc correction.
    * **Yawn against a victim that cannot take it** -- already statused, already drowsy, or
      holding Insomnia or Vital Spirit (`subscript_yawn.s`, read top to bottom). Yawn inflicts
      nothing at the moment it is used, so `status_applied_by` returns None for it and none of
      the generic status families above fires.
    * **Future Sight with one already in the air.** `BtlCmd_TryFutureSight` jumps to the
      "But it failed!" branch, having spent nothing at all -- so this failure is cheaper than
      every other one here by the one roll the move would otherwise have cost.

    `actor` is keyword-only and optional so that callers which only care about the
    defender-facing families -- `hunt_session.move_info`, which asks "can this move of OURS do
    nothing to the target" -- need not pretend to know who is acting.

    None of these renders as a miss: the simulator emits the bare slot token.
    """
    status = status_applied_by(move)
    if status is not None and defender.status is not Status.NONE:
        return True
    # Safeguard blocks a new non-volatile status outright, which makes it a hard obstacle rather
    # than a nuisance: sec 2.2's precondition is a target held still, so a Safeguard up before we
    # land Thunder Wave or Spore has to be waited out. It does NOT block a ball -- a ball is not
    # a move -- which is what keeps the target catchable through it.
    if status is not None and field is not None and getattr(field, "safeguard_turns", 0) > 0:
        return True
    if soundproofed(defender, move):
        # Blocked outright, and it lands on the same "no more work" flag as the other
        # defender-side refusals -- so it costs what those cost. Heatran's Metal Sound against a
        # Soundproof party member is the live case.
        return True
    if status is not None and immune_to_status(defender, status):
        # Insomnia and Vital Spirit, checked at the very top of `subscript_fall_asleep` and
        # landing on the same no-more-work flag as "is already asleep" -- so the cost is the
        # same as that verified failure's.
        return True
    if status is Status.SLEEP and uproar_active(field):
        # "But {0} can't sleep in an uproar!" -- and the sleep DURATION roll sits past this
        # branch, so refusing here is also what keeps the roll count right.
        return True
    if move.effect == EFFECT_YAWN:
        # Read in `subscript_yawn.s`'s own order. Insomnia and Vital Spirit come first (they
        # print an ability message instead), then an Uproar, then any existing status, then a
        # second Yawn. Our side's Safeguard would block it too and is deliberately absent:
        # `safeguard_turns` is the TARGET's side condition and nothing in any party can set one,
        # so a row for it could never fire.
        return (immune_to_status(defender, Status.SLEEP)
                or uproar_active(field)
                or defender.status is not Status.NONE
                or defender.drowsy_turns > 0)
    if move.effect == EFFECT_TAUNT:
        # A second Taunt fails, and fails FREE of the duration roll -- `subscript_taunt_start.s`
        # tests `BATTLEMON_TAUNTED_TURNS != 0` before reaching its Random. The accuracy roll is
        # still spent, as it is for every other failure in this function.
        return defender.taunted_turns > 0
    if move.effect == EFFECT_FUTURE_SIGHT:
        # Keyed on the FIELD, because the ROM keys it on the victim's battler position rather
        # than on the move's user: `futureSightTurns[defender]`. One can be in the air per side.
        return field is not None and getattr(field, "future_sight_turns", 0) > 0
    if move.effect == EFFECT_NIGHTMARE:
        # Fails against anything not asleep, and against a second application
        # [effect_script_0107.s]. The first half is the one that fires in a real run: Darkrai
        # cannot sequence its own moves, so it throws Nightmare at a wide-awake party member
        # roughly a quarter of the turns it acts.
        return defender.status is not Status.SLEEP or defender.nightmare
    if (raises := PRIMARY_SELF_RAISES.get(move.effect)) is not None:
        # **A single-stat raise at +6 does NOT fail.** This used to return True for it, and that
        # was wrong by two advances a turn. `BtlCmd_ChangeStatStage` (battle_script.c:2841-2851)
        # takes `jumpNoChange` when the stat is already at `MAX_STAT_STAGE` for a DIRECT side
        # effect, and `jumpNoChange` is `subscript_update_stat_stage`'s `_041`: it prints
        # "{0}'s {1} won't go higher!" and ends, setting no status flag. Only
        # `jumpBlockedBySubstitute` sets `MOVE_STATUS_FAILED`.
        #
        # Measured on the MIRROR, which runs the identical instruction with the sign flipped:
        # data/battle_logs/hooh1.jsonl turns 34-37 are four Sweet Scents against an evasion
        # already at -6, each spending the full 15 rolls. Treating them as failures costs turn 34
        # two advances and desynchronises every turn after it, so the game really does spend the
        # post-successful-move pair on a stat change that cannot happen.
        #
        # The TWO-stat boosters are the exception and go the other way, because they do not reach
        # `ChangeStatStage` at all when every stat is maxed: their own subscript tests both stats
        # first and sets `MOVE_STATUS_NO_MORE_WORK`
        # (`subscript_user_atk_and_def_up_1_stage.s` `_046` and its three siblings), which routes
        # to `LOOP_SPREAD_MOVES` and skips `USE_MOVE` whole. [derived -- nothing in a configured
        # moveset can reach it, since it needs a two-stat booster with BOTH stats at the ceiling.]
        if move.effect not in MULTI_STAT_EFFECTS or actor is None:
            return False
        return all(getattr(actor, field) >= STAT_STAGE_CEILING for field, _ in raises)
    if (drops := PRIMARY_STAT_DROPS.get(move.effect)) is not None:
        # The same asymmetry, same way round. A single-stat drop at -6 is the measured case above
        # and is NOT a failure; Tickle with both stats at -6 is, by the mirror of the two-stat
        # argument (`subscript_target_atk_and_def_down_1_stage.s` `_050`).
        if move.effect not in MULTI_STAT_EFFECTS:
            return False
        return all(getattr(defender, field) <= STAT_STAGE_FLOOR for field, _ in drops)
    if move.effect == EFFECT_REFRESH:
        # No actor given means "cannot tell", and guessing True would suppress a question the
        # interview must still ask. Only a known-unstatused user is a known failure.
        return actor is not None and actor.status not in REFRESH_CURES
    if field is None:
        return False
    if move.effect == EFFECT_RAIN_DANCE and field.rain_turns > 0:
        return True
    if move.effect == EFFECT_MIST and field.mist_turns > 0:
        return True
    if move.effect == EFFECT_MEAN_LOOK and field.target_trapped:
        return True
    if move.effect == EFFECT_WATER_SPORT and field.target_water_sport:
        return True
    if move.effect == EFFECT_SAFEGUARD and getattr(field, "safeguard_turns", 0) > 0:
        return True
    # A screen re-used while it is already up fails (the fail branch at
    # src/battle/battle_command.c:2577), which costs the turn its two post-successful-move
    # advances. This half of the screen work bites even with the halving unimplemented, because
    # Ampharos carries Light Screen in its moveset and a player can simply pick it twice.
    if move.effect == EFFECT_REFLECT and getattr(field, "reflect_turns", 0) > 0:
        return True
    if move.effect == EFFECT_LIGHT_SCREEN and getattr(field, "light_screen_turns", 0) > 0:
        return True
    return False


#: Effect ids whose move fails outright when the condition it sets is already in place. Every
#: such failure costs the turn its two post-successful-move advances, which is exactly how the
#: emulator log (data/battle_logs/test1.jsonl) diverged from this simulator on turn 3: Suicune
#: re-used Rain Dance while it was already raining, the game spent 17 advances, and this spent 19.
EFFECT_RAIN_DANCE = 136
EFFECT_MIST = 46
EFFECT_MEAN_LOOK = 106
EFFECT_LOWER_EVASION = 24
#: Aurora Beam's Attack, Mist Ball's Sp. Atk and Luster Purge's Sp. Def all live in
#: `SECONDARY_STAT_DROPS` now, which is why they no longer have a constant apiece. The three they
#: had were there to keep the stats straight -- one figure used to stand for Attack and Sp. Atk
#: both, and Sp. Def is a third thing again: ours is what the target's special attacks are
#: divided by, so a drop there raises every later special hit rather than lowering what we deal.
#: The table keeps them straight by construction instead.
#: Burn halves the holder's physical Attack [Gen 4]. Applied to the stat before the stage, which
#: is where `CalcMoveDamage` reads it.
BURN_ATTACK_DIVISOR = 2
#: Burn's end-of-turn tick: max HP / 8, rounded down, and never less than 1.
BURN_TICK_DIVISOR = 8
#: Leftovers' end-of-turn recovery: max HP / 16, by the same floor-but-never-zero rule as the
#: burn tick -- both go through `DamageDivide` [src/battle/overlay_12_0224E4FC.c:3110].
#:
#: The NAME is re-exported from `battle.readiness` rather than declared twice, so that the
#: modelled-items allowlist there and the tick here cannot disagree about the spelling.
LEFTOVERS_DIVISOR = 16
#: Refresh. Self-targeting, and it cures only the three statuses below -- not sleep and not
#: freeze, which is why sleep is the status of choice against a target that knows it (sec 4b).
EFFECT_REFRESH = 193
#: Water Sport. A per-battler volatile flag in the ROM (MOVE_EFFECT_FLAG_WATER_SPORT) rather
#: than a turn counter, so once up it stays up for the rest of a wild battle -- the user never
#: switches out. It halves Fire damage, which nothing in any configured moveset of ours is.
EFFECT_WATER_SPORT = 210

#: What Refresh can cure. Sleep and freeze are absent from the ROM's list, and in any case a
#: sleeping or frozen Pokemon cannot act to use it.
REFRESH_CURES = frozenset({Status.BURN, Status.PARALYSIS, Status.POISON})

#: Both last five turns, counted inclusive of the turn they are set [verified: test1.jsonl, where
#: rain set on turn 1 stops on turn 5 and mist set on turn 4 wears off on turn 8].
RAIN_TURNS = 5
MIST_TURNS = 5


#: Move effects whose SECONDARY burns the move's target: 4 (Fire Blast) and 125 (Sacred Fire).
#: The status itself, not the chance -- `move.effect_chance` carries that.
BURN_EFFECTS = frozenset({4, 125})
#: Discharge, Thunderbolt, Body Slam, Dragon Breath: the secondary PARALYZES.
#:
#: Its own constant because the primary-effect table (`status_applied_by`) is about moves that
#: paralyze by definition -- Thunder Wave -- while this one only does so when its proc roll lands.
#: `MODELLED_OUR_EFFECTS` claimed this was modelled while nothing applied it: the roll was spent
#: and the status dropped on the floor, which on the one move that matters most (Ampharos's
#: Discharge, against a target whose paralysis IS the Phase 2 precondition) would have
#: contradicted every candidate on the turn it procced (clayton-957.10.10).
EFFECT_PARALYZE_HIT = 6
#: Ancient Power: 10% to raise EVERY stat of the attacker by one stage.
EFFECT_ALL_STATS_UP = 140
#: Safeguard: protects its own side from new non-volatile statuses for five turns.
EFFECT_SAFEGUARD = 124
SAFEGUARD_TURNS = 5
#: Double Team (BATTLE_EFFECT_EVA_UP). One stage on the USER, no roll of its own -- the move's
#: accuracy is 0, so not even an accuracy roll [res/battle/scripts/effects/effect_script_0016.s].
EFFECT_EVASION_UP = 16
#: Faint Attack (BATTLE_EFFECT_BYPASS_ACCURACY). Its script is CalcCrit then CalcDamage with no
#: accuracy check at all [effect_script_0017.s], which is exactly what `execute_move` already
#: does for an accuracy-0 damaging move -- so this id needs no code of its own, only saying so.
EFFECT_BYPASS_ACCURACY = 17
#: Foresight and Odor Sleuth (BATTLE_EFFECT_FORESIGHT), and the move that makes a Ghost target
#: catchable. **Next to Double Team above because it is that move's answer**, and it is the one
#: of ours that answers it.
#:
#: Both moves are effect 113 and byte-for-byte identical in the table: status, Normal, power 0,
#: **accuracy 0**, 40 PP, no effect chance. `effect_script_0113.s` is two instructions --
#: `MOVE_SIDE_EFFECT_ON_HIT|MOVE_SUBSCRIPT_PTR_FORESIGHT` and `SYSCTL_IGNORE_IMMUNITIES` -- and
#: `subscript_foresight.s` is a single `UpdateMonData ... VOLATILE_CONDITION_FORESIGHT` on the
#: DEFENDER plus a message. So:
#:
#: * **Zero rolls.** No accuracy roll (accuracy 0), no `Random` anywhere in either script. Not
#:   even a duration, because there is no duration -- see `Battler.identified`. Cross-validated
#:   against `metronome_compass.effects`, which maps 113 to `_eff_no_rolls_ok`.
#: * **It cannot fail**, and that is a positive statement rather than an omission: the subscript
#:   has no test before it sets the flag, so a second Foresight sets an already-set bit and still
#:   counts as a successful move. Hence no `will_fail` entry -- which also makes it the only
#:   repeatable zero-roll status move either side has, i.e. a filler whose turn cost is
#:   *constant* where Mean Look's second use is two advances cheaper than its first.
#: * **`SYSCTL_IGNORE_IMMUNITIES` is about the move itself**, not about what it grants: it is how
#:   a Normal-type move lands on a Ghost at all. Nothing to model here, because `execute_move`
#:   never consults the type chart on the status branch.
#:
#: What the flag then does is read in two other places -- `accuracy_net_stage` for the evasion
#: half and `battle.damage.ignores_ghost_immunity` for the type half.
EFFECT_FORESIGHT = 113
#: Nightmare. Fails against anything not asleep and against a second application
#: [effect_script_0107.s], then takes a quarter of max HP at the end of every sleeping turn.
EFFECT_NIGHTMARE = 107
#: Nightmare's and Bad Dreams' divisors, both floor-divided with a floor of 1 like every other
#: residual: `BattleSystem_Divide` never returns 0 [src/battle/battle_lib.c:3599-3618].
NIGHTMARE_DIVISOR = 4
BAD_DREAMS_DIVISOR = 8
#: Abilities that change what a residual does. Magic Guard skips burn, Nightmare and Bad Dreams
#: alike (each case opens by checking it); Heatproof halves the burn tick
#: [subscript_burn_damage.s, subscript_nightmare_effect.s, battle_controller_player.c:1484-1496].
ABILITY_MAGIC_GUARD = "magic guard"
ABILITY_HEATPROOF = "heatproof"
ABILITY_BAD_DREAMS = "bad dreams"
#: Sleep-blocking abilities. `subscript_fall_asleep` checks Insomnia and Vital Spirit before
#: anything else, and lands on the same MOVE_STATUS_NO_MORE_WORK flag as "is already asleep" --
#: which is the failure whose advance cost is verified (test1.jsonl), so the cost follows.
#:
#: Leaf Guard is deliberately absent: it blocks sleep only in sunshine, and nothing in any
#: configured moveset can set sun, so a row for it could never fire.
SLEEP_BLOCKING_ABILITIES = frozenset({"insomnia", "vital spirit"})
#: Abilities that ABSORB a whole move type, and the type each one eats. Transcribed from
#: `BattleSystem_TriggerImmunityAbility` (pokeplatinum src/battle/battle_lib.c:3488-3545), which
#: runs at `TRY_MOVE_STATE_TRIGGER_IMMUNITY_ABILITIES` -- i.e. after the accuracy roll and after
#: the type chart, so the rolls are spent either way.
#:
#: **Not modelled, and deliberately refused rather than approximated.** Each one does something
#: extra on top of the immunity -- Volt/Water Absorb and Dry Skin heal a quarter of max HP, Motor
#: Drive raises Speed, and Flash Fire raises the holder's own Fire power by half -- so a Fire move
#: thrown at Heatran would not merely fail, it would make the Lava Plume that follows hit harder
#: than anything predicted. That is unsound, not imprecise.
#:
#: Lightning Rod is absent on purpose: in Gen 4 it redirects in doubles and grants no immunity at
#: all, so a holder is simply hit. Levitate is absent for the opposite reason -- it IS modelled,
#: as the Ground immunity it is (`battle.damage._levitates`).
ABSORBED_MOVE_TYPES: dict[str, str] = {
    "volt absorb": "Electric",
    "water absorb": "Water",
    "flash fire": "Fire",
    "motor drive": "Electric",
    "dry skin": "Water",
}

#: Soundproof blocks these TWELVE MOVES BY NAME, not a type -- `sSoundMoves`
#: (src/battle/battle_lib.c:3473-3486). Heatran's Metal Sound is one of them, which is why this
#: is here: an Electrode or a Whismur in the party would have Metal Sound blocked outright, and
#: the simulator would otherwise apply two Sp. Def stages the game never applied and mis-predict
#: every special hit afterwards.
SOUND_MOVES = frozenset({
    "growl", "roar", "sing", "supersonic", "screech", "snore", "uproar", "metal sound",
    "grass whistle", "hyper voice", "bug buzz", "chatter",
})
ABILITY_SOUNDPROOF = "soundproof"


def absorbs(battler: "Battler", move: Move) -> bool:
    """Whether this defender's ability eats `move` whole, with a side effect we do not model."""
    eaten = ABSORBED_MOVE_TYPES.get((battler.ability or "").strip().lower())
    return eaten is not None and move.type_name == eaten and bool(move.power)


def deals_nothing(move: Move, defender: "Battler", attacker: "Battler" = None) -> bool:
    """Whether the type chart (or Levitate) zeroes this move against `defender`.

    The `Battler`-shaped face of `battle.damage.is_type_immune`, so callers that hold Battlers --
    the UI, mostly -- do not have to build a `Defender` to ask. It reads `defender.identified`
    and the attacker's Scrappy through that function, so one Foresight flips every answer it
    gives about a Normal or Fighting move.

    **Not a reason to refuse the move** (`unselectable_reason`) and not a `will_fail` entry: the
    move connects, spends every roll and renders a hit marker. It is published so the interview
    can explain a turn where nothing happened, which against a Ghost target is half the moveset.

    Deliberately NOT routed through `_defender_side`/`_attacker_side`: those build the damage
    formula's view and need a full stat spread, and this question reads types, two abilities and
    one volatile flag. A `Battler` assembled for a UI test with a partial `stats` dict can still
    be asked whether its moves do anything.
    """
    return is_type_immune(
        move, defender.types,
        defender_ability=defender.ability, identified=defender.identified,
        attacker_ability="" if attacker is None else attacker.ability)


def soundproofed(battler: "Battler", move: Move) -> bool:
    """Whether Soundproof blocks `move` for this defender. By NAME, as the ROM lists it."""
    return ((battler.ability or "").strip().lower() == ABILITY_SOUNDPROOF
            and move.name.strip().lower() in SOUND_MOVES)


def pending_future_sight(field) -> int:
    """Damage a banked Future Sight will take off us at the END of this turn, or 0.

    **The only incoming damage in this simulator that is already decided.** Every other figure a
    danger floor is built from is a worst case over moves the target has not picked yet; this one
    was computed and stored two turns ago by `_future_sight_damage`, and nothing between then and
    now changes it -- not a switch, not a Light Screen, not an Amnesia.

    Which makes it the one thing that **stacks**: on the turn it lands, the target still takes its
    ordinary turn, so the HP we can lose is the worst single hit *plus* this. A floor that priced
    only the larger of the two is the "faints at a number the plan called safe" shape
    (cf. clayton-6xu.6, where the floor ignored our own Sp. Def drops).

    Keyed on the counter reaching **1**, not on one merely being in the air. At 2 or 3 the hit is
    turns away and the floor is recomputed every turn anyway, so pre-paying for it would tighten
    the heal gate for no reason -- which is clayton-957.10.1's collapse approached from the other
    side.

    Deliberately the FULL figure even though the hit can miss: its check is a real 90% roll
    (`_roll_future_sight`), so this is conservative rather than exact, and conservative is the
    correct direction for a gate that decides whether to heal. Do not scale it by the accuracy.
    """
    if getattr(field, "future_sight_turns", 0) != 1:
        return 0
    return getattr(field, "future_sight_damage", 0) or 0


def uproar_active(field) -> bool:
    """Whether an Uproar is running anywhere on the field.

    A FIELD question, not a per-battler one: the ROM sets a bit in `fieldConditionsMask` as well
    as the user's own volatile (`subscript_uproar.s`), and it is the field bit that sleep and
    Yawn consult. So "can we put the target to sleep" has one answer for the whole battle while
    anything is uproaring, and `will_fail` reads it through here.

    **Soundproof is not applied here.** The ROM checks it per battler at each use site -- a
    Soundproof Pokemon can sleep through an Uproar, and is not woken by one
    (`subscript_fall_asleep` ``_036``/``_118``, `MON_COND_CHECK_STATE_UPROAR`) -- so folding it
    into a field-wide answer would give the wrong result for exactly one of the two sides.
    Callers that care about one battler pair it with `soundproofed` themselves; see
    `_wake_for_uproar`.

    `field` may be None, which is "we were not told" and answers False: every caller that cannot
    see the field is asking about a move in isolation, where assuming an Uproar would suppress a
    question the interview must still ask.
    """
    if field is None:
        return False
    return any(getattr(getattr(field, side, None), "uproar_turns", 0) > 0
               for side in ("ours", "target"))


def _wake_for_uproar(battler: Battler, field) -> Battler:
    """`battler` woken if an Uproar is keeping it awake, unchanged otherwise. Costs no rolls.

    The ROM wakes a sleeper in two places and spends nothing in either: at the end of every turn
    while any Uproar is running (`MON_COND_CHECK_STATE_UPROAR`, which loops over all battlers and
    runs `subscript_wake_up` for the first sleeping one) and again when a sleeping battler tries
    to act (`CHECK_STATUS_STATE_SLEEP`, battle_controller_player.c:2433-2440). Both are applied
    here, which is why it is called from the two act functions AND from the end-of-turn block.

    **Soundproof is the exemption, and both sites check it**, which is the reason this is not
    folded into `uproar_active`: a Soundproof Pokemon sleeps straight through an Uproar.

    Not a cure in the ordinary sense -- it is the same wake-up the sleep counter would eventually
    have produced, arriving early -- so there is no token. The Pokemon acting at all is what says
    it is awake, exactly as a sleep running out is.
    """
    if battler.status is not Status.SLEEP or not uproar_active(field):
        return battler
    if (battler.ability or "").strip().lower() == ABILITY_SOUNDPROOF:
        return battler
    return battler.with_status(Status.NONE)
#: How many of the end-of-turn advances fall BEFORE the conditional end-of-turn rolls -- Yawn's
#: sleep duration and a Future Sight's hit check.
#:
#: **This is the one figure in this module that is derived rather than measured, and it is owed a
#: gdb capture** (clayton-957: "verified advance counts are sacred"). What is known:
#:
#: * `turn_costs.END_OF_TURN_ADVANCES = 4` is measured, on turns where none of these fired.
#: * `metronome_compass` measured a rampage-end confusion-duration roll landing after TWO of
#:   those four ("the confusion roll lands between END[1] and END[2] in the actual game",
#:   metronome_compass/__init__.py:245-248). That roll is `MON_COND_CHECK_STATE_THRASH`, state
#:   **15** of the end-of-turn condition walk.
#: * Yawn is state **24** of the same walk, and Future Sight is in the walk AFTER it
#:   (`SIDE_COND_CHECK_STATE_FUTURE_SIGHT`, which `BattleControllerPlayer_CheckSideConditions`
#:   runs once `CheckMonConditions` is done). So both are at or after the measured anchor, and
#:   Yawn is before Future Sight.
#:
#: What is NOT known is where the remaining two advances sit relative to states 15-24 and the
#: side-condition walk. Anchoring at 2 puts both rolls where the measured neighbour is; the
#: residual uncertainty is two advances, and it matters because both verdicts are observable --
#: a wrong roll means a wrong sleep length or a wrong Future Sight hit, which eliminates the true
#: seed rather than merely mispredicting a number. Uxie is the target that makes it load-bearing:
#: both of its end-of-turn rolls are in its own moveset and the target picks its own moves, so a
#: run cannot route around them.
_END_OF_TURN_RESIDUAL_ANCHOR = 2

#: Shadow Force. A two-turn move: turn 1 vanishes and spends NOTHING, turn 2 is an ordinary
#: damaging move [res/battle/scripts/effects/effect_script_0272.s].
EFFECT_SHADOW_FORCE = 272
#: Effects whose charge turn makes their user untouchable. Only Shadow Force is in any configured
#: moveset; Fly (19), Dig (39) and Dive (256) belong here the day a target has one, and the ROM
#: tests all four in the same condition (`CheckMoveHitOverrides`).
SEMI_INVULNERABLE_EFFECTS = frozenset({EFFECT_SHADOW_FORCE})

#: Uproar (BATTLE_EFFECT_UPROAR). Azelf's, and the first move either side has that locks its user
#: into attacking for several turns in a row.
#:
#: `subscript_uproar.s` is `Random 3, 3` -- and `BtlCmd_Random` reads that as
#: ``(rand % (3 + 1)) + 3`` (battle_script.c:3201-3208), so the counter is **3 to 6 and the move
#: is used on that many turns in total**. The end-of-turn check decrements it and re-locks while
#: it is nonzero (`MON_COND_CHECK_STATE_UPROAR`, battle_controller_player.c:1506-1536), so a
#: rolled 3 means two continuation turns after the one that started it.
#:
#: Cross-checked against `metronome_compass.effects._eff_uproar`, which rolls 2-5 EXTRA turns --
#: the same distribution counted from the other end, which is the corroboration worth having
#: because the commonly quoted figure for Gen 4 Uproar is "2-5 turns" and that is the extras.
EFFECT_UPROAR = 159
UPROAR_TURNS_MIN = 3
UPROAR_TURNS_SPAN = 4

#: Yawn (BATTLE_EFFECT_YAWN). Accuracy 0, so no accuracy roll, and `subscript_yawn.s` spends no
#: roll of its own either: `BtlCmd_TryYawn` just sets the counter (battle_script.c:6580-6592).
#: The roll comes two turns later, when the sleep actually lands.
EFFECT_YAWN = 187
#: What `BtlCmd_TryYawn` sets: ``moveEffectsMask |= 1 << (YAWN_SHIFT + 1)``, i.e. 2. The
#: end-of-turn check decrements first and applies sleep on reaching zero, so a Yawn used on turn
#: T puts its victim to sleep at the END of turn T+1 -- the first turn it costs is T+2.
YAWN_DROWSY_TURNS = 2

#: Future Sight (BATTLE_EFFECT_HIT_IN_3_TURNS), in both Uxie's and Azelf's sets.
#:
#: Unlike every other damaging move this spends **exactly one roll on the turn it is used** and
#: nothing else: `effect_script_0148.s` runs `TryFutureSight` -- which banks
#: ``CalcMoveDamage`` through ``CalcDamageVariance``, one roll -- and then sets
#: `SYSCTL_NONSTANDARD_ACC_CHECK`, which makes `CheckMoveHitAccuracy` return 0 and spend no
#: accuracy roll (battle_controller_player.c:2912-2915). No crit roll either: the effect script
#: never reaches `CalcCrit`, and `TryFutureSight` passes a critical multiplier of 1.
#:
#: The effect script runs BEFORE the accuracy check, which is what makes that work -- the move's
#: script is loaded at the end of `BEFORE_MOVE` with `commandNext = TRY_MOVE`
#: (battle_controller_player.c:3215-3220). The same ordering is why `SYSCTL_IGNORE_IMMUNITIES`
#: skips the type chart entirely; see `battle.damage.damage`'s ``type_chart`` argument.
EFFECT_FUTURE_SIGHT = 148
#: The counter `BtlCmd_TryFutureSight` sets (battle_script.c:6074). Decremented at the end of
#: every turn, and it lands on reaching zero -- so a Future Sight used on turn T hits at the end
#: of turn T+2.
FUTURE_SIGHT_TURNS = 3

#: Haze (BATTLE_EFFECT_HAZE). **The move itself spends no rolls at all** -- accuracy 0, so no
#: accuracy roll, and `subscript_reset_all_stat_stages.s` is `ResetAllStatChanges` plus a message
#: with no Random anywhere.
#:
#: Which is not the same as a free TURN: it succeeds, so the turn still spends the two
#: post-successful-move advances. That makes it cost 2 against Flash's 3 and Taunt's 4 -- the
#: cheapest move in the action alphabet, and dearer than a bag action's nothing.
#:
#: `BtlCmd_ResetAllStatChanges` (battle_script.c:3535-3549) loops EVERY battler and sets every one
#: of its `statBoosts` back to neutral, then clears Focus Energy. It touches nothing else: not
#: status, not the other volatiles, not field conditions. And there is no "already hazed" check,
#: so a second Haze succeeds and costs the same nothing.
#:
#: Which means it resets OUR stages too, and that is the trap rather than a detail -- see
#: `solver.undoes_our_own_work`.
EFFECT_HAZE = 25

#: Taunt (BATTLE_EFFECT_TAUNT), and the first move of OURS that changes what the target's turn
#: costs rather than only what it does.
#:
#: `subscript_taunt_start.s` fails free if the defender is already taunted or the move missed, and
#: otherwise rolls ``Random 2, 3`` -- ``(rand % (2 + 1)) + 3``, so **3 to 5 turns**, one roll. The
#: move's accuracy is 100, so the accuracy roll is spent too: two rolls when it lands, one when it
#: fails.
#:
#: What it DOES is narrow the target's move-selection modulus; see `Battler.usable_slots`, which
#: is also where the reasoning behind that lives. Nothing here refuses a move after the fact.
EFFECT_TAUNT = 175
TAUNT_TURNS_MIN = 3
TAUNT_TURNS_SPAN = 3


def taunt_refuses(move: Move, actor: Battler) -> bool:
    """Whether a Taunt on `actor` refuses `move` at execution time.

    The ROM's own test, transcribed: ``CHECK_STATUS_STATE_TAUNT`` is
    ``tauntedTurns && aiContext.moveTable[moveCur].power == 0``
    (src/battle/battle_controller_player.c:2557-2570). By POWER, like `Battler.usable_slots`.

    **This is reachable, and `usable_slots` used to argue it was not.** The argument was that the
    wild AI never PICKS a taunted status move -- true, and `usable_slots` still models it -- so
    the only way into the refusal would be something forcing the choice, which no configured
    target can do. What it missed is that the AI's narrowing happens at SELECTION time. On the
    turn a Taunt lands with the taunter moving first, the target had already chosen, so there was
    nothing to narrow and the refusal is what fires. Measured:
    data/battle_logs/uxie1.jsonl turn 14, "The wild UXIE can't use Amnesia after the taunt!"
    with `sub_seq:subscript_move_fail_taunted` on the phase record.

    It is the common case rather than a corner, because a Taunt is thrown to land and we outspeed
    a paralyzed target by construction.
    """
    return actor.taunted_turns > 0 and not move.power

#: Stat raises a move puts on its OWN USER, by effect -- the mirror of `PRIMARY_STAT_DROPS`.
#:
#: A table rather than a branch per effect because Uxie and Azelf would each have added one:
#: Amnesia is Sp. Def +2 and Nasty Plot Sp. Atk +2, both reached through exactly the machinery
#: Double Team's evasion already used. Each is its effect script's whole content -- a single
#: `MOVE_SIDE_EFFECT_TO_ATTACKER` subscript pointer -- so none of them spends a roll, and all
#: three moves have accuracy 0 and so spend no accuracy roll either.
#:
#: Mist does not guard against these: Mist blocks REDUCTIONS to its own side, and this is the
#: user raising its own stage.
PRIMARY_SELF_RAISES: dict[int, tuple[tuple[str, int], ...]] = {
    # --- one stat, one stage ---
    10: (("atk_stage", 1),),             # Meditate, Sharpen, Howl
    11: (("def_stage", 1),),             # Harden, Withdraw
    13: (("spatk_stage", 1),),           # Growth
    16: (("evasion_stage", 1),),         # Double Team -- Darkrai's
    # Swords Dance, and ours: no configured encounter has it. Its effect script is byte-for-byte
    # the shape the two below have -- `effect_script_0050.s` against `0053`/`0054`, differing only
    # in the subscript pointer, all three resolving to `subscript_update_stat_stage` -- so it is a
    # row here and nothing else. Corroborated independently by
    # `metronome_compass.effects._eff_swords_dance`, which is atk+2 and no rolls.
    #
    # It earns its place on our side rather than being completeness: it raises the physical damage
    # WE deal, and False Swipe cannot take the target below 1 HP (effect 101), so it is strictly
    # fewer turns to the Phase 2 precondition with no risk of overshooting it. And the boost
    # survives the turn it matters most on -- `battle.damage` discards the attacker's stage on a
    # critical hit only when it is NEGATIVE.
    # --- one stat, two stages ---
    50: (("atk_stage", 2),),             # Swords Dance -- ours, and it DOUBLES our physical damage
    51: (("def_stage", 2),),             # Barrier, Acid Armor, Iron Defense
    # Agility and Rock Polish. The one self-raise that can change a TURN'S COST rather than only
    # its damage, because Speed decides order and an effective-Speed tie spends extra rolls
    # (notes/ss_rng/speed.md). Modelled, and `readiness.speed_move_ties` is what warns before a
    # player walks into one -- see that function for why a warning rather than a refusal.
    52: (("speed_stage", 2),),           # Agility, Rock Polish
    53: (("spatk_stage", 2),),           # Nasty Plot -- Azelf's, and it DOUBLES its special damage
    54: (("spdef_stage", 2),),           # Amnesia -- Uxie's
    # --- two stats, one stage each ---
    #
    # These fail differently from the single-stat rows above, and the difference is an advance
    # difference. Each has its own subscript (`subscript_user_atk_and_def_up_1_stage.s` and
    # friends) which tests BOTH stats first and, when both are already at +6, sets
    # `MOVE_STATUS_NO_MORE_WORK` and never reaches `ChangeStatStage` at all. A single-stat raise
    # at the ceiling takes `ChangeStatStage`'s `jumpNoChange` branch instead, which sets no flag.
    # See `will_fail` for what that costs.
    206: (("def_stage", 1), ("spdef_stage", 1)),      # Cosmic Power, Defend Order
    208: (("atk_stage", 1), ("def_stage", 1)),        # Bulk Up
    211: (("spatk_stage", 1), ("spdef_stage", 1)),    # Calm Mind
    212: (("atk_stage", 1), ("speed_stage", 1)),      # Dragon Dance -- also a Speed mover
}


#: The non-volatile status a move's SECONDARY inflicts on its victim, by effect.
#:
#: Deliberately not a superset of what the game has. Freeze (effects 5 and 260) is left out
#: because freeze is not MODELLED -- a frozen Pokemon skips turns on a thaw roll this simulator
#: does not make -- and inflicting one here would produce a prediction nothing could match.
#: Neither effect appears in `MODELLED_OUR_EFFECTS` or in any configured target's moveset, so the
#: omission is guarded on both sides rather than merely hoped for.
SECONDARY_STATUSES: dict[int, Status] = {
    **{effect: Status.BURN for effect in BURN_EFFECTS},
    EFFECT_PARALYZE_HIT: Status.PARALYSIS,
}


def can_inflict(battler: "Battler", status: Status) -> bool:
    """Whether `battler` has any way to put `status` on the other side.

    Four routes, all of them real for some configured target: a move whose PRIMARY effect is
    the status (Thunder Wave, Spore), a move whose SECONDARY is (Discharge, Sacred Fire), the
    holder's own ability firing on contact (Static), and -- Uxie's -- a move that leads to the
    status on a LATER turn.

    That fourth one is Yawn, and it had to be named rather than derived: `status_applied_by`
    returns None for it, because Yawn inflicts nothing at the moment it is used. So a Uxie
    answered False to "can this put us to sleep", which is the wrong answer to every question
    that asks it.

    Written for the speed checks. `speed_checks` enumerates our Pokemon both healthy and
    paralyzed because paralysis quarters our Speed and can flip an order that looked safe -- but
    `include_our_paralysis` defaulted on and nothing derived it, so a hunt against Lugia (no
    paralysing move, Pressure not Static) reported ties for a state the player could not reach.
    Half the rows in the table were hypotheticals (clayton-36b).

    Deliberately over-inclusive on abilities: an ability we do not model is assumed capable
    rather than assumed safe, because the cost of a spurious row is a line of advice and the cost
    of a missing one is an unmodelled desync.
    """
    for slot in range(len(battler.moves)):
        move = battler.move(slot)
        if move is None:
            continue
        if status_applied_by(move) is status or secondary_status(move) is status:
            return True
        if status is Status.SLEEP and move.effect == EFFECT_YAWN:
            return True
    return _ability_inflicts(battler.ability, status)


#: Abilities that inflict a status on whoever touches their holder. Only the ones this project
#: models; `can_inflict` treats an UNKNOWN ability as capable, so a new one is a spurious speed
#: row rather than a silent hole.
_CONTACT_STATUS_ABILITIES: dict[str, Status] = {
    "static": Status.PARALYSIS,
    "flame body": Status.BURN,
    "poison point": Status.POISON,
    "effect spore": Status.PARALYSIS,      # also sleep and poison; any of them is enough here
}
#: Abilities known to inflict nothing on contact, so a target holding one produces no rows at
#: all. Everything outside both sets is treated as capable.
_INERT_ABILITIES = frozenset({
    "pressure", "levitate", "technician", "own tempo", "sturdy", "magnet pull",
    "serene grace", "synchronize", "early bird", "keen eye", "tangled feet", "", "none",
    # Darkrai's, and it is not inert in general -- it costs us an eighth of our max HP every
    # sleeping turn (`bad_dreams_tick`). It belongs here because this set is only about CONTACT:
    # touching a Darkrai inflicts nothing, which is the one question `can_inflict` asks.
    "bad dreams",
    # Heatran's, and the same reasoning: Flash Fire eats a Fire move aimed AT it
    # (`ABSORBED_MOVE_TYPES`) and does nothing to whoever touches it.
    "flash fire",
    # The defensive abilities this project already names elsewhere, every one of which is about
    # what its holder is immune TO rather than what touching it does. Insomnia in particular was
    # a real omission: it is the headline ability of the wall the whole support kit is built
    # around (`SLEEP_BLOCKING_ABILITIES`), so leaving it out of this set made every party
    # containing one answer "yes, we can paralyze" on the strength of its ability alone.
    "insomnia", "vital spirit", "limber", "water veil", "immunity", "magma armor",
    "inner focus", "shield dust", "clear body", "white smoke", "hyper cutter", "soundproof",
    "super luck", "sniper", "scrappy",
})


def _ability_inflicts(ability: str, status: Status) -> bool:
    key = (ability or "").strip().lower()
    if key in _INERT_ABILITIES:
        return False
    known = _CONTACT_STATUS_ABILITIES.get(key)
    if known is not None:
        return known is status or key == "effect spore"
    return True             # unknown ability: assume it can, and say so in a spurious row


def secondary_status(move: Move) -> Status | None:
    """The status this move's secondary effect would inflict, or None.

    Public because the interview needs it for the same reason it needs `status_applied_by`: a
    status that lands mid-turn changes what the other side can have done on the same turn, and
    the snapshot's option lists are read off the turn's opening state.
    """
    return SECONDARY_STATUSES.get(move.effect)


#: What a move's secondary effect looks like TO THE PLAYER: ``(side, clause)``, where side is
#: ``"victim"`` or ``"attacker"`` and the clause carries ``{who}`` for that Pokemon's name.
#:
#: The interview has to name the thing it is asking about, and naming it wrongly is worse than
#: being vague. The page used to hardcode "Yes -- <ours>'s stat fell", which was written against
#: Suicune (Aurora Beam, Mist Ball and Luster Purge all really do drop our stats) and is wrong
#: twice over on Ho-Oh: Ancient Power raises HO-OH's stats and Sacred Fire burns us. An unlisted
#: effect gets no clause at all, and the page falls back to the generic wording -- vague, but
#: never a claim about something the game did not say (clayton-957.10.9).
SECONDARY_DESCRIPTIONS: dict[int, tuple[str, str]] = {
    4: ("victim", "{who} was burned"),
    125: ("victim", "{who} was burned"),
    5: ("victim", "{who} was frozen"),
    260: ("victim", "{who} was frozen"),
    EFFECT_PARALYZE_HIT: ("victim", "{who} was paralyzed"),
    76: ("victim", "{who} became confused"),
    68: ("victim", "{who}'s Attack fell"),
    71: ("victim", "{who}'s Sp. Atk fell"),
    72: ("victim", "{who}'s Sp. Def fell"),
    69: ("victim", "{who}'s Defence fell"),
    70: ("victim", "{who}'s Speed fell"),
    EFFECT_ALL_STATS_UP: ("attacker", "{who}'s stats all rose"),
    **{effect: ("victim", "{who} flinched") for effect in FLINCH_EFFECTS},
}


def secondary_description(move: Move) -> tuple[str, str] | None:
    """``(side, clause)`` describing this move's secondary, or None when it is not described.

    None means "say something generic", not "there is no secondary" -- `move.effect_chance`
    answers that.
    """
    return SECONDARY_DESCRIPTIONS.get(move.effect)


#: Punishment. Power is state-dependent: 60 plus 20 per positive stat stage ON ITS TARGET,
#: capped at 200 [verified: `BtlCmd_CalcPunishmentPower`, src/battle/battle_command.c]. The cap is
#: 200 and not the 120 an earlier note claimed.
EFFECT_PUNISHMENT = 245
PUNISHMENT_BASE_POWER = 60
PUNISHMENT_PER_STAGE = 20
PUNISHMENT_MAX_POWER = 200


def punishment_power(defender: Battler) -> int:
    """Punishment's base power against `defender`.

    The ROM sums every one of the target's eight stat-change entries that sits above neutral, so
    accuracy and evasion count alongside the five battle stats.

    **It is fed by our own buffs**, which is the interaction worth remembering: `choose_item`
    reaches for X Sp. Def as cheap filler, and every stage of that is +20 power on the move
    hitting us. A defensive item that makes the incoming attack stronger is not obviously a bad
    trade -- X Sp. Def still cuts the special damage it feeds -- but it is a trade, not a free
    action.
    """
    stages = (defender.atk_stage, defender.def_stage, defender.spatk_stage,
              defender.spdef_stage, defender.speed_stage, defender.accuracy_stage,
              defender.evasion_stage)
    boosts = sum(stage for stage in stages if stage > 0)
    return min(PUNISHMENT_MAX_POWER,
               PUNISHMENT_BASE_POWER + PUNISHMENT_PER_STAGE * boosts)


#: Effects whose base power is computed from state rather than read from the table. Named as a
#: set so the static coverage check can tell "power 1 means work it out" from "power 1 means we
#: have no rule for this".
VARIABLE_POWER_EFFECTS = frozenset({EFFECT_PUNISHMENT})


# --- primary stat drops, i.e. the ones a STATUS move exists to do ------------------------------
#
# These had no home at all until now, and the absence was silent rather than loud: `execute_move`
# returned a successful outcome with no stat payload and `simulate_turn` applied nothing, so
# Flash, Screech and Charm each read as "it worked and changed nothing" (clayton-957.10.2).
#
# Flash was the unsound one. `_effective_accuracy` already reads `attacker.accuracy_stage`, so the
# stage simply never got set and every later hit/miss was computed at the wrong threshold -- the
# accuracy roll spent correctly and the verdict wrong, which eliminates the true seed rather than
# merely blurring it.
#
# Distinct from the SECONDARY drops below, which ride on a damaging move and are applied off
# `outcome.secondary`. These are the move's whole purpose, so they land whenever it succeeds.
#: effect id -> (`Battler` stage field, how many stages it drops)
PRIMARY_STAT_DROPS: dict[int, tuple[tuple[str, int], ...]] = {
    18: (("atk_stage", 1),),      # Growl
    19: (("def_stage", 1),),      # Tail Whip, Leer
    # String Shot, and a Speed mover: it slows the TARGET, which moves the order for every
    # Pokemon we have rather than only the one that used it -- a wild target never switches out,
    # so the drop is permanent. `readiness.speed_move_ties` is what warns about it.
    20: (("speed_stage", 1),),    # String Shot
    23: (("accuracy_stage", 1),), # Flash, Sand Attack, Smoke Screen, Kinesis
    24: (("evasion_stage", 1),),  # Sweet Scent
    58: (("atk_stage", 2),),      # Charm, Feather Dance
    59: (("def_stage", 2),),      # Screech
    60: (("speed_stage", 2),),    # Cotton Spore, Scary Face -- Speed movers, as 20 above
    62: (("spdef_stage", 2),),    # Fake Tears, Metal Sound
    # Tickle, the only two-stat DROP, and the mirror of 206/208/211/212 above in every respect
    # including how it fails: `subscript_target_atk_and_def_down_1_stage.s` tests both stats and
    # sets `MOVE_STATUS_NO_MORE_WORK` only when BOTH are already at -6.
    205: (("atk_stage", 1), ("def_stage", 1)),        # Tickle
}

#: The effects above whose subscript tests every stat FIRST and refuses the move outright when
#: none of them can move -- as opposed to the single-stat rows, which run `ChangeStatStage` and
#: take its no-change branch. The distinction is worth a set of its own because it is the only
#: thing separating "the move did nothing and cost a full turn" from "the move did not happen".
MULTI_STAT_EFFECTS: frozenset[int] = frozenset({205, 206, 208, 211, 212})

#: effect id -> the stage a DAMAGING move drops on its victim when its secondary procs.
#:
#: A table because it was three hand-written branches in `simulate_turn` -- one per effect, on
#: each side -- and Heatran's Crunch would have been a fourth. Each branch was a separate chance
#: to apply the drop to the wrong side or to forget the clamp, and two of the three only existed
#: on the target's half of the turn (clayton-6xu.6).
#:
#: **Crunch (69) drops DEFENCE in Gen 4.** It dropped Sp. Def in Gen 3 and the change is exactly
#: the kind of thing a modern reference gets wrong for this project -- taken from
#: `effect_script_0069.s`, whose subscript is `MOVE_SUBSCRIPT_PTR_DEFENSE_DOWN_1_STAGE`.
SECONDARY_STAT_DROPS: dict[int, tuple[tuple[str, int], ...]] = {
    68: (("atk_stage", 1),),     # Aurora Beam
    69: (("def_stage", 1),),     # Crunch
    70: (("speed_stage", 1),),   # Rock Tomb, Icy Wind, Bubble
    71: (("spatk_stage", 1),),   # Mist Ball
    72: (("spdef_stage", 1),),   # Luster Purge, Shadow Ball
}
STAT_STAGE_FLOOR = -6
STAT_STAGE_CEILING = 6

#: False Swipe's effect: damage, but never below 1 HP. The reason it is the only damaging move
#: that stays legal once the target is at 1 -- see `solver.can_faint_target`.
FALSE_SWIPE_EFFECT = 101

#: Effects that END A WILD BATTLE, and so end the run with the target uncaught.
#:
#: The same class of hazard as a move that KOs the target (`solver.can_faint_target`) and a worse
#: one, because it costs the encounter rather than the Pokemon: there is no reviving from it and no
#: second attempt at this seed.
#:
#: * **153 Teleport** -- the USER flees. Natu learns it at L9, and Natu is the Synchronize lead,
#:   so it is in the party by necessity rather than by choice.
#: * **28 Roar / Whirlwind** -- the TARGET is forced out, which against a wild Pokemon ends the
#:   battle. Granbull learns Roar at L27, on the way to the Lv35 it needs.
#:
#: Both are a level-up move on a party member the plan requires, so neither is hypothetical. The
#: simulator does not model either outcome, which is the second reason to refuse them: an
#: unmodelled battle-ending move would be simulated as a status move that did nothing.
RUN_ENDING_EFFECTS = frozenset({153, 28})


def primary_stat_drop(move: Move) -> tuple[tuple[str, int], ...] | None:
    """``(stage field, stages)`` this status move drops on its target, or None."""
    return PRIMARY_STAT_DROPS.get(move.effect)


def apply_stat_drop(battler: Battler, drops: tuple[tuple[str, int], ...]) -> Battler:
    """`battler` with every pair in `drops` applied, each clamped at the -6 floor.

    A SEQUENCE rather than one pair, because Tickle drops two stats and so does every one of the
    four two-stat boosters on the other side. One pair was the shape while every stat move in
    play moved exactly one stat; making it a sequence is what let the rest of the family in
    without a second code path per move.

    **Clamped rather than refused.** A drop against a stat already at -6 does nothing, and does
    not change the turn's roll count -- so unlike the field conditions it is NOT a `will_fail`
    case, and Flash stays a usable filler action all the way down.
    [verified: data/battle_logs/hooh1.jsonl turns 34-37, four Sweet Scents against an evasion
    already at -6, each spending the full 15 rolls. Modelling them as failures costs turn 34 two
    advances and desynchronises everything after it.]

    A stat at the floor still clamps silently here even when another stat in the same `drops`
    moves, which is exactly what the ROM does: the two-stat subscripts call `ChangeStatStage`
    once per stat and each call takes its own no-change branch.
    """
    for field, stages in drops:
        current = getattr(battler, field)
        battler = replace(battler, **{field: max(STAT_STAGE_FLOOR, current - stages)})
    return battler


def apply_stat_raise(battler: Battler, raises: tuple[tuple[str, int], ...]) -> Battler:
    """`battler` with every pair in `raises` applied, each clamped at the +6 ceiling.

    The mirror of `apply_stat_drop`, and symmetric with it in the way that matters: a raise
    against a stat already at +6 does nothing and still costs a full turn. That is the opposite
    of what this said before -- see `will_fail` for the correction and its evidence.

    **Permanent.** A wild target never switches out, so the ROM's stat reset never runs on it:
    every Double Team Darkrai gets off is one our 100%-accuracy moves keep paying for.
    """
    for field, stages in raises:
        current = getattr(battler, field)
        battler = replace(battler, **{field: min(STAT_STAGE_CEILING, current + stages)})
    return battler


def primary_self_raise(move: Move) -> tuple[tuple[str, int], ...] | None:
    """The stage raises a status move puts on its own user, or None. Mirror of
    `primary_stat_drop`."""
    return PRIMARY_SELF_RAISES.get(move.effect)


# --- screens -----------------------------------------------------------------------------------
#
# OUR side's, and only ours: no configured target moveset contains either move, the same way
# `mist_turns` is only ever the target's. If one ever does, these become per-side pairs rather
# than single counters.
EFFECT_LIGHT_SCREEN = 35
EFFECT_REFLECT = 65
SCREEN_EFFECTS = frozenset({EFFECT_LIGHT_SCREEN, EFFECT_REFLECT})


# --- abilities that act without being asked ----------------------------------------------------
#
# Lowercased, because `Battler.ability` is entered by a player rather than read from the ROM.
ABILITY_INTIMIDATE = "intimidate"
ABILITY_STATIC = "static"
#: Intimidate drops one stage of Attack. It spends NO advances -- `sendOutState` case 3
#: (src/battle/overlay_12_0224E4FC.c:3253) sets BATTLE_SUBSCRIPT_INTIMIDATE with no
#: `BattleSystem_Random` in the branch at all.
INTIMIDATE_DROP = (("atk_stage", 1),)
#: Static's paralysis chance, as the ROM writes it: ``BattleSystem_Random() % 10 < 3``.
STATIC_MODULUS = 10
STATIC_THRESHOLD = 3


def intimidates(battler: Battler) -> bool:
    return battler.ability.strip().lower() == ABILITY_INTIMIDATE


def _apply_intimidate(incoming: Battler, opponent: Battler) -> Battler:
    """`opponent` after `incoming`'s Intimidate, if it has one. Costs no advances.

    **It re-triggers on every send-out.** `intimidateFlag = 0` sits at
    src/battle/overlay_12_0224E4FC.c:82, inside the battler-initialisation function that reads IVs
    and the nickname off the mon -- so it runs per entry, not once per battle. The same Pokemon
    switched out and back in fires again, stacking to -6. That is what makes an Intimidate body a
    *shuttle* rather than a one-shot (notes/ho_oh_party.md sec 5.3).

    It applies on the switch-in turn itself, because a switch resolves before any move -- which is
    why the entry turn is the strictest survival bar for the Intimidate holder and not the easiest.

    Nothing in any configured target blocks it: none has Clear Body or Hyper Cutter, none has Mist
    up at the moment we send out, and Safeguard does not touch stat drops. A target that did would
    need the same guard `apply_stat_drop`'s callers use.
    """
    if not intimidates(incoming) or opponent.fainted:
        return opponent
    return apply_stat_drop(opponent, INTIMIDATE_DROP)


def variable_base_power(move: Move, defender: Battler) -> int | None:
    """Base power for a move whose table entry is a placeholder, or None for a fixed-power move.

    Power 1 in moves.json means "work this out from state", and treating it as unmodellable is
    what kept Punishment out of the damage model -- and out of the danger floor, which is worse:
    a floor that ignores one of the target's attacks is not a floor.
    """
    if move.effect == EFFECT_PUNISHMENT:
        return punishment_power(defender)
    return None


def burn_tick(battler: Battler) -> int:
    """Burn's end-of-turn damage: max HP / 8, rounded down, never less than 1.

    **Deterministic, and that is the whole reason it needs no token of its own.** It consumes no
    RNG advances -- corroborated by the fainting measurements, where dying to an end-of-turn
    effect leaves the turn's advance count unchanged -- so it carries no information about the
    stream and its result is computable from the HP before it. An `HP###` token earns its place
    by reading back a damage roll or by catching a Phase 2 desync, and a tick does neither.

    The check is not lost: on any turn where something random ALSO moved our HP, the single HP
    token reports the total, tick included. See notes/battle_compass_next_targets.md sec 4a.

    Two abilities change the figure, both read straight off `subscript_burn_damage.s`: Magic
    Guard skips the tick entirely and Heatproof halves it. Neither is in a planned party, but
    both are ordinary enough to bring -- and a predicted HP that is wrong by a tick is wrong
    forever afterwards, because every comparison is exact.
    """
    if ignores_residuals(battler):
        return 0
    tick = max(1, battler.max_hp // BURN_TICK_DIVISOR)
    if (battler.ability or "").strip().lower() == ABILITY_HEATPROOF:
        # The ROM halves the already-divided figure with the same floor-of-1 divide, so a
        # 16-HP holder still takes 1 rather than 0.
        tick = max(1, tick // 2)
    return tick


def ignores_residuals(battler: Battler) -> bool:
    """Whether Magic Guard spares this Pokemon the deterministic ticks.

    One helper rather than three checks because the ROM really does ask the same question in
    three places -- `subscript_burn_damage`, `subscript_nightmare_effect` and the Bad Dreams case
    all open with `CheckAbility ... ABILITY_MAGIC_GUARD` and skip to the end. Nothing in the
    planned parties has it, but a holder would otherwise be predicted to lose HP it never loses,
    and every HP comparison after that point is exact.
    """
    return (battler.ability or "").strip().lower() == ABILITY_MAGIC_GUARD


def immune_to_status(battler: Battler, status: Status) -> bool:
    """Whether `battler`'s own ability refuses `status` outright.

    Only sleep so far, and only now that it matters: Hypnosis is the first status move pointed at
    OUR side, and an Insomnia carrier (Noctowl, Xatu, Hypno) would otherwise be simulated as
    falling asleep for several turns it actually spends awake and attacking.

    Asked of the VICTIM, which is what makes it the mirror of `can_inflict` rather than a
    duplicate of it: that one asks whether an attacker has any route to a status at all.
    """
    if status is not Status.SLEEP:
        return False
    return (battler.ability or "").strip().lower() in SLEEP_BLOCKING_ABILITIES


def is_semi_invulnerable(battler: Battler) -> bool:
    """Whether `battler` is away mid-charge, so nothing can touch it this turn.

    Read off the charging move rather than a second flag, so the two cannot disagree. Shadow
    Force is the only one any configured encounter has; `SEMI_INVULNERABLE_EFFECTS` is where Fly,
    Dig and Dive would join it, which is the same condition the ROM tests
    [src/battle/battle_controller_player.c:3034-3041].
    """
    if battler.charging_slot is None:
        return False
    move = battler.move(battler.charging_slot)
    return move is not None and move.effect in SEMI_INVULNERABLE_EFFECTS


def starts_charge_turn(battler: Battler, slot: int) -> bool:
    """Whether picking `slot` right now is the CHARGE turn of a two-turn move.

    The other half of `is_semi_invulnerable`: that one asks whether a battler is already away,
    this one whether it is about to go. Same condition as `execute_move`'s own first branch
    (``move.effect in SEMI_INVULNERABLE_EFFECTS and attacker.charging_slot != slot``), named once
    so the simulator and the interview cannot disagree about which turn it is.

    **Why the interview needs it.** A charge turn fires nothing: `execute_move` returns before
    CalcCrit, CalcDamage and the accuracy check, so it renders the bare slot token, spends no
    rolls and moves no HP. But Shadow Force is a PHYSICAL move by category, so everything that
    asked "is this damaging" answered yes on both of its turns -- and the interview offered "Hit
    us" and "Critical hit" as the only answers to a turn that can render neither, then asked for
    an HP figure that had not changed. `tokens.turn_requires_hp` and the simulator were both
    already right; only the questions were wrong.

    Reads the MOVE's effect rather than a list of names, so Fly, Dig and Dive are covered the day
    a target has one -- see `SEMI_INVULNERABLE_EFFECTS`.
    """
    move = battler.move(slot)
    return (move is not None and move.effect in SEMI_INVULNERABLE_EFFECTS
            and battler.charging_slot != slot)


def nightmare_tick(battler: Battler) -> int:
    """Nightmare's end-of-turn damage: a quarter of max HP, or 0 if it does not apply.

    Gated on being ASLEEP, not merely on carrying the volatile: the ROM's end-of-turn case
    damages a sleeping holder and otherwise clears the flag outright
    [src/battle/battle_controller_player.c:1436-1446]. So waking up is the cure, which is why the
    rolled sleep duration decides the total rather than the move landing doing so.

    Deterministic, like every other residual here, and therefore carries no token of its own --
    the HP token reports the total on any turn where something random also moved our HP.
    """
    if not battler.nightmare or battler.status is not Status.SLEEP or battler.fainted:
        return 0
    if ignores_residuals(battler):
        return 0
    return max(1, battler.max_hp // NIGHTMARE_DIVISOR)


def bad_dreams_tick(battler: Battler, *, opponent_has_bad_dreams: bool) -> int:
    """Darkrai's ability: an eighth of max HP for every turn we spend asleep.

    Takes the opponent's ability as a flag rather than reading a Battler, mirroring
    `HuntConfig.target_has_pressure`: the facade derives it from the species once, and the
    simulator should not have to hold a second copy of the target's ability to answer it.

    With Nightmare that is 37.5% of our max HP a turn, which is what makes falling asleep against
    this target a different kind of event from falling asleep against any other -- not a lost
    turn but a clock.
    """
    if not opponent_has_bad_dreams or battler.status is not Status.SLEEP or battler.fainted:
        return 0
    if ignores_residuals(battler):
        return 0
    return max(1, battler.max_hp // BAD_DREAMS_DIVISOR)


def leftovers_tick(battler: Battler) -> int:
    """Leftovers' end-of-turn recovery: ``max(1, max HP / 16)``, or 0 if it does not apply.

    Transcribed from `CheckItemGradualHPRestore` [src/battle/overlay_12_0224E4FC.c:4136]:
    `HOLD_EFFECT_HP_RESTORE_GRADUAL` restores ``DamageDivide(maxHp, 16)`` and **only while
    ``hp < maxHp``** -- at full HP the item does nothing at all rather than healing zero.

    Deterministic and RNG-free, exactly like `burn_tick`, so it carries no token of its own; the
    HP token on a turn where something random also moved our HP reports the total.

    **It lands BEFORE the burn tick**, which is not a detail: `UpdateMonConditionState`
    [src/battle/battle_controller_player.c:1143] orders `UMC_STATE_LEFTOVERS_RECOVERY` ahead of
    `UMC_STATE_BURN`. So a burned holder can never *end* a turn on full HP -- the recovery is
    gated on being below maximum, so at full HP it is skipped and the tick takes 1/8 -- but every
    turn after that nets 1/16 of max HP instead of 1/8, which roughly doubles how long it lasts.

    Ours only, at the one call site. A wild target holds whatever its personal data gives it
    (Ho-Oh's is a Sacred Ash, inert in battle) and none of them is Leftovers, so wiring the target
    would be untested code; this stays side-agnostic so that doing it later is one line.
    """
    if item_key(battler.held_item) != item_key(LEFTOVERS):
        return 0
    if battler.hp >= battler.max_hp:
        return 0
    return max(1, battler.max_hp // LEFTOVERS_DIVISOR)



def status_applied_by(move: Move) -> Status | None:
    """The non-volatile status this move inflicts, if any.

    Public because the interview needs it too: a status our move lands takes effect BEFORE the
    target's half of the same turn, and the snapshot's prevention options are read off the turn's
    opening state, so the page has to add "is asleep" itself once Spore connects.
    """
    return {1: Status.SLEEP, 67: Status.PARALYSIS}.get(move.effect)


def weather_of(field) -> str:
    """The field's weather, as `battle.damage` names it.

    Rain is the only one any configured moveset can set -- Rain Dance is in both Suicune's and
    Lugia's. Sun has no setter yet, so there is nothing to read it off; it stays a lookup here
    rather than a branch so that adding one is a field on `BattleState` and nothing else.
    """
    if field is not None and getattr(field, "rain_turns", 0) > 0:
        return WEATHER_RAIN
    return WEATHER_NONE


def screen_turns_for(held_item: str) -> int:
    """How long a screen this holder sets will last -- 5 turns, or 8 with a Light Clay.

    Thin wrapper so `battle.damage` stays the one place that knows the figures, and so the item
    name is matched in exactly one spot.
    """
    from claytonlib.battle.damage import screen_turns

    return screen_turns(held_item)


def _attacker_side(battler: Battler) -> Attacker:
    """`battler` as `battle.damage` wants the attacking side.

    Pulled out of `execute_move` so that Future Sight, which banks its damage through a different
    path, cannot drift from the live calculation. Atk and SpA stages are read SEPARATELY -- one
    figure passed as both silently applied an Aurora Beam Attack drop to Sp. Atk as well -- and
    the attacker's own Battler is what reaches the call, which is how the TARGET's boosts
    (Ancient Power's, and now Nasty Plot's) reach the damage it deals us.

    Burn halves the holder's physical Attack, and that matters in both directions: it is also how
    many more False Swipes a burned Smeargle needs before the target reaches 1 HP.
    """
    attack = battler.stats["atk"]
    if battler.status is Status.BURN:
        attack = max(1, attack // BURN_ATTACK_DIVISOR)
    return Attacker(
        level=battler.level, attack=attack,
        special_attack=battler.stats["spa"], types=battler.types,
        attack_stage=battler.atk_stage, special_attack_stage=battler.spatk_stage,
        ability=battler.ability, held_item=battler.held_item)


def _defender_side(battler: Battler) -> Defender:
    """`battler` as `battle.damage` wants the defending side.

    Only Levitate is read off the ability, and only as a Ground immunity. It reaches the
    calculation at all because the target's Battler carries its encounter's ability, and Giratina
    Origin's is Levitate.

    `identified` goes with it, and the two are worth contrasting precisely because this one
    function carries both: a Foresight takes the GHOST immunities off and leaves Levitate's GROUND
    immunity standing, since the ROM tests Levitate in the branch before the table walk the
    Foresight sentinel lives in. So a Foresighted Giratina Origin can be False Swiped and still
    cannot be Earthquaked.
    """
    return Defender(
        defence=battler.stats["def"], special_defence=battler.stats["spd"],
        types=battler.types, defence_stage=battler.def_stage,
        special_defence_stage=battler.spdef_stage, ability=battler.ability,
        identified=battler.identified)


def _future_sight_damage(move: Move, attacker: Battler, defender: Battler, *,
                         damage_roll: int, field=None) -> int:
    """The damage a Future Sight banks at the moment it is used.

    Three things make it different from every other hit in this module, and all three come from
    `BtlCmd_TryFutureSight` (battle_script.c:6066-6096) rather than from inference:

    * **No crit.** It passes a critical multiplier of 1, and the effect script never reaches
      `CalcCrit` -- so no crit roll is spent and none could apply.
    * **No STAB and no type effectiveness**, because `SYSCTL_IGNORE_IMMUNITIES` makes
      `CheckTypeChart` skip the one function that holds all of it. See `damage`'s ``type_chart``.
    * **Banked against the Pokemon standing there NOW**, at this turn's stages and screens. Two
      turns later it is applied as a stored number, so nothing in between -- a switch, a Light
      Screen, an Amnesia -- changes it.

    Our Light Screen and the weather DO apply, because both are read inside `CalcMoveDamage`
    itself: `TryFutureSight` passes the defender's side conditions and the field conditions
    straight through. Light Screen is the one that can matter, Future Sight being special;
    Psychic appears in no weather table, so rain is along for completeness.
    """
    attacker_side = _attacker_side(attacker)
    if (unsupported_reason(move, power_known=False) is not None
            or unsupported_attacker_reason(attacker_side) is not None):
        return 0
    return damage(
        move, attacker_side, _defender_side(defender),
        roll=DAMAGE_ROLL_MAX_PERCENT - damage_roll % DAMAGE_ROLL_COUNT,
        critical=False,
        weather=weather_of(field),
        light_screen=getattr(field, "light_screen_turns", 0) > 0,
        type_chart=False)


def execute_move(rng: int, move: Move, attacker: Battler, defender: Battler, *,
                 actor: str, slot: int, net_stage: int | None = None,
                 field=None) -> tuple[int, MoveOutcome]:
    """Execute one move against the RNG, returning (new rng, outcome).

    Named ``execute_move`` rather than ``resolve_move`` so it cannot be confused with — or
    shadow — ``claytonlib.moves.resolve_move``, which looks a Move up by name.

    Roll order follows ``metronome_compass``'s ``hit_crit_or_miss``: crit, then the damage roll
    (unobservable on its own, but readable from an HP change — sec 3.1), then accuracy.
    """
    used = 0
    if net_stage is None:
        net_stage = accuracy_net_stage(attacker, defender)
    slot_token = tok.our_move_token(slot) if actor == "M" else tok.target_move_token(slot)
    parts: list[str] = [slot_token]

    if move.effect in SEMI_INVULNERABLE_EFFECTS and attacker.charging_slot != slot:
        # The CHARGE turn, and it costs **nothing**: its effect script branches away from
        # CalcCrit/CalcDamage, and `CheckMoveHitAccuracy` returns before its roll because
        # "charge-up moves don't consider accuracy on their first turn"
        # [battle_controller_player.c:2905-2907]. Cross-validated against
        # `metronome_compass.effects._eff_charge_fire`, which spends no rolls either and was fit
        # to the Blackthorn ground truth.
        #
        # SUCCESSFUL, so the turn still gets its two post-successful-move advances. That is the
        # one part of this move's cost that is derived rather than measured: the move went off
        # and printed a message, which is every other successful move's situation, but nothing
        # has watched a charge turn in the emulator. See notes/platinum.md section 13.
        #
        # A Power Herb (`HOLD_EFFECT_CHARGE_SKIP`) skips the charge turn entirely; no wild
        # Pokemon holds one, so that branch is not modelled.
        return rng, MoveOutcome(rolls=0, tokens=tuple(parts), successful=True,
                                starts_charge=slot)

    if move.effect == EFFECT_FUTURE_SIGHT:
        # Its own branch because it fits neither of the two below. It is a SPECIAL move by
        # category, but on the turn it is used it neither hits nor misses nor crits: the effect
        # script banks the damage with one roll and switches the accuracy check off before
        # `TRY_MOVE` ever runs. So the turn renders as the bare slot token, exactly as a
        # successful status move does.
        if will_fail(move, defender, field, actor=attacker):
            # One already in the air, so `TryFutureSight` jumps straight to "But it failed!"
            # without reaching `CalcMoveDamage` -- no damage roll. **But an accuracy roll IS
            # spent**, and it took ground truth to see why. `effect_script_0148.s` is:
            #
            #     _000:
            #         TryFutureSight _010
            #         UpdateVar OPCODE_FLAG_ON, BTLVAR_BATTLE_CTX_STATUS, ...
            #                   ...|SYSCTL_NONSTANDARD_ACC_CHECK|...
            #         End
            #     _010:
            #         PrintAttackMessage / Wait / WaitButtonABTime 30
            #         Call BATTLE_SUBSCRIPT_BUT_IT_FAILED
            #         End
            #
            # SYSCTL_NONSTANDARD_ACC_CHECK -- the flag that makes `CheckMoveHitAccuracy` return 0
            # and is why `accuracy_for` answers 0 on a use turn -- is set on the SUCCESS path
            # only. The already-pending path jumps over it, so the ordinary TRY_MOVE phase
            # afterwards runs CheckMoveHit against Future Sight's real 90.
            #
            # Measured: data/battle_logs/uxie1.jsonl turn 4, roll 60087 at the accuracy PC
            # 0x0224f230 with no damage-variance roll on the turn, right after "The wild UXIE
            # used Future Sight! / But it failed!" (clayton-6xu.7.5). This was modelled as zero,
            # which desynchronised every turn after a target re-picked Future Sight while one was
            # in the air -- frequent, since Uxie and Azelf pick from four slots and the bank
            # lasts two turns.
            #
            # The VERDICT is not observable: the script has already printed "But it failed!"
            # before the roll happens, so nothing downstream reads it. One advance, no token.
            rng, _unseen = advance(rng)
            return rng, MoveOutcome(rolls=used + 1, tokens=tuple(parts), successful=False)
        rng, damage_roll = advance(rng)
        used += 1
        return rng, MoveOutcome(
            rolls=used, tokens=tuple(parts), successful=True,
            banked_future_sight=_future_sight_damage(move, attacker, defender,
                                                     damage_roll=damage_roll, field=field))

    if move.category == CATEGORY_STATUS:
        hit = True
        if move.accuracy > 0:
            rng, roll = advance(rng)
            used += 1
            hit = roll % 100 < _effective_accuracy(
            move, net_stage, attacker=attacker, defender=defender)
        # ...and then it misses anyway if the defender is away mid-charge. **After** the roll, not
        # instead of it: `CheckMoveHitAccuracy` spends the accuracy roll and the semi-invulnerable
        # verdict is layered on by `CheckMoveHitOverrides` afterwards
        # [battle_controller_player.c:219-220]. So the cost is an ordinary miss's.
        #
        # **Only for a move that was aimed at it.** The ROM points a self-, side- or field-range
        # move back at its own user (`defender = attacker`), so there is nothing out of reach:
        # Light Screen, Mist, Safeguard, Rain Dance, Haze, Double Team and Refresh all go off as
        # usual while Giratina is away. Without `reaches_opponent` every one of them rendered as a
        # MISS and set nothing -- a desync, not a mispredicted number, and reachable, because
        # Magneton carries Light Screen.
        if hit and move.reaches_opponent and is_semi_invulnerable(defender):
            hit = False
        if not hit:
            parts.append(tok.MISS)
            return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=False)
        # Every failure below spends the accuracy roll and then stops, so it costs the turn its
        # two post-successful-move advances. Getting this wrong is what desynchronised the
        # simulator from data/battle_logs/test1.jsonl at turn 3.
        if will_fail(move, defender, field, actor=attacker):
            return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=False)
        status = status_applied_by(move)
        sleep_turns = 0
        if status is Status.SLEEP:
            # Applying sleep costs one more roll for its hidden duration. The cost of this move
            # is therefore OUTCOME-dependent, which is why move_roll_cost can only be an upper
            # bound for it.
            rng, duration_roll = advance(rng)
            used += 1
            sleep_turns = SLEEP_DURATION_MIN + duration_roll % SLEEP_DURATION_SPAN
        taunt_turns = 0
        if move.effect == EFFECT_TAUNT:
            # The same shape as sleep's: a hidden duration, rolled only once every earlier check
            # in the subscript has passed. `will_fail` above has already handled the one case that
            # fails free, so reaching here means the Taunt really is going on.
            rng, duration_roll = advance(rng)
            used += 1
            taunt_turns = TAUNT_TURNS_MIN + duration_roll % TAUNT_TURNS_SPAN
        # Mist guards its own side's stats, against EVERY reduction and not just Sweet Scent's.
        # The move still executed, so it stays SUCCESSFUL and still spends the post-move advances
        # [verified: test1.jsonl turn 15 spent 8 skeleton rolls, not 6, on a Sweet Scent the game
        # reported as "protected by Mist"]. `mist_turns` is the TARGET's Mist, so this guards a
        # drop we aim at the target -- which is the only direction any configured moveset can
        # produce.
        drop = primary_stat_drop(move)
        blocked = (drop is not None and field is not None and field.mist_turns > 0)
        return rng, MoveOutcome(
            rolls=used, tokens=tuple(parts), successful=True,
            applied_status=status, sleep_turns=sleep_turns, starts_taunt=taunt_turns,
            stat_drop=None if blocked else drop,
            sets_rain=move.effect == EFFECT_RAIN_DANCE,
            sets_mist=move.effect == EFFECT_MIST,
            traps=move.effect == EFFECT_MEAN_LOOK,
            sets_water_sport=move.effect == EFFECT_WATER_SPORT,
            sets_safeguard=move.effect == EFFECT_SAFEGUARD,
            sets_reflect=move.effect == EFFECT_REFLECT,
            sets_light_screen=move.effect == EFFECT_LIGHT_SCREEN,
            screen_turns=(screen_turns_for(attacker.held_item)
                          if move.effect in SCREEN_EFFECTS else 0),
            sets_nightmare=move.effect == EFFECT_NIGHTMARE,
            sets_drowsy=move.effect == EFFECT_YAWN,
            resets_all_stages=move.effect == EFFECT_HAZE,
            # Unconditional on reaching here, which is the whole of this move's behaviour: the
            # subscript tests nothing before setting the bit, so a Foresight against an
            # already-identified target lands again and costs exactly what the first one did.
            identifies=move.effect == EFFECT_FORESIGHT,
            # Double Team, Swords Dance, Nasty Plot, Amnesia. Mist does not guard against any of
            # them -- Mist blocks REDUCTIONS to its own side, and this is the user raising its own
            # stage.
            self_stat_raise=PRIMARY_SELF_RAISES.get(move.effect),
            blocked_by_mist=blocked)

    # Damaging.
    rng, crit_roll = advance(rng)
    rng, damage_roll = advance(rng)
    used += 2
    # The STAGE, not `CRIT_MODIFIERS[0]`. A high-crit move lands on `% 8`, and reading the
    # modifier off slot 0 unconditionally made Aeroblast crit half as often as the game does --
    # wrong token and wrong damage on the same turn (clayton-957.2).
    critical = crit_roll % CRIT_MODIFIERS[crit_stage_of(move, attacker)] == 0
    hit = True
    if move.accuracy > 0:
        rng, hit_roll = advance(rng)
        used += 1
        hit = hit_roll % 100 < _effective_accuracy(
            move, net_stage, attacker=attacker, defender=defender)
    # As in the status branch: the rolls are spent first, the invulnerability decides afterwards.
    # An accuracy-0 move is not exempt -- Faint Attack spends no accuracy roll and still cannot
    # reach something that is not there. A move that never aimed at it is exempt, and the gate
    # reads the same way on both branches; no damaging move in any configured moveset has a
    # self-aimed range, so this half is for symmetry.
    if move.reaches_opponent and is_semi_invulnerable(defender):
        hit = False
    if not hit:
        parts.append(tok.MISS)
        # The lock comes off even on a miss: the effect script's cleanup (`_055`) is fallen
        # through to from the fire branch, and the hit verdict is decided after the script runs.
        return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=False,
                                ends_charge=attacker.charging_slot == slot)
    if soundproofed(defender, move):
        # The immunity-ability stage, and it is the reason this check cannot live in `will_fail`
        # alone: `will_fail` is consulted only on the status branch, and Uproar is the first
        # DAMAGING sound move any target has had. Metal Sound got here for free; Uproar would
        # have dealt damage and started its lock against an Electrode.
        #
        # Every roll is still spent. `BattleSystem_TriggerImmunityAbility` runs at
        # `TRY_MOVE_STATE_TRIGGER_IMMUNITY_ABILITIES` (battle_lib.c:3523-3530) -- after the effect
        # script's CalcCrit/CalcDamage and after the accuracy check -- so crit, damage and
        # accuracy are all behind us by the time the move is refused.
        #
        # And `subscript_blocked_by_soundproof` REPLACES `USE_MOVE`, which is where a
        # MOVE_SIDE_EFFECT_ON_HIT subscript would have run. So Uproar's duration roll is not
        # spent and no lock is set: a Soundproof party member blanks the move whole, and with it
        # the field-wide ban on sleep that an Uproar would have brought.
        #
        # Neither a hit nor a miss: the token is the bare slot, as every other blocked move's is.
        return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=False,
                                ends_charge=attacker.charging_slot == slot)
    # **A type immunity renders no hit marker**, and the ROM says so in its own vocabulary:
    # `MOVE_STATUS_INEFFECTIVE` is a member of `MOVE_STATUS_DID_NOT_HIT`
    # (include/constants/battle/moves.h:80-82), sitting in the same group as `MOVE_STATUS_MISSED`
    # and `MOVE_STATUS_SEMI_INVULNERABLE`. The player sees "It doesn't affect Smeargle!" and no
    # hit, no crit and no HP change -- so the bare slot, exactly as a soundproofed move above.
    #
    # Live against Giratina and the reason this was found: Ominous Wind and Shadow Force are both
    # Ghost and the planned lead is a Normal-typed Smeargle, so half of Giratina's turns land
    # here. With the marker on, `tokens.turn_requires_hp` demanded an HP token for a turn whose HP
    # had not moved, while `simulate_turn` emits one only on a CHANGE -- so the prediction was
    # `E4h` against a report of `E4hHP154` and every candidate was eliminated, the true seed
    # included.
    #
    # Deliberately NOT an early return, unlike soundproof's: the rolls after this point are
    # still spent. See `ineffective`'s use at the secondary below, which is where the ROM draws
    # the line -- the roll happens, the effect does not.
    ineffective = deals_nothing(move, defender, attacker)
    if not ineffective:
        parts.append(tok.CRIT if critical else tok.HIT)

    starts_uproar = 0
    if move.effect == EFFECT_UPROAR and not attacker.uproar_turns:
        # The lock's duration, rolled by `subscript_uproar.s` -- a MOVE_SIDE_EFFECT_ON_HIT
        # subscript, so it runs during `subscript_use_move` and only when the move connected.
        #
        # Placed here, after the accuracy roll and before the secondary and contact-ability
        # rolls below, because that is the order the ROM's command states run in: the side-effect
        # subscript is part of `USE_MOVE`, while `CheckAbilityEffectOnHit` is a later state
        # (`TRIGGER_AFTER_HIT_EFFECTS`). No move can reach both this and the secondary roll --
        # Uproar's `effect_chance` is 0 -- and Uproar is not a contact move, so Static cannot
        # fire on it either. The order is therefore unobservable today and transcribed anyway.
        rng, duration_roll = advance(rng)
        used += 1
        starts_uproar = UPROAR_TURNS_MIN + duration_roll % UPROAR_TURNS_SPAN

    dealt = 0
    # Atk and SpA stages read off the attacker SEPARATELY. One figure used to be passed as both,
    # so an Aurora Beam Attack drop was silently applied to Sp. Atk too -- and it is also the
    # attacker's own Battler now rather than a parameter, which is what lets the TARGET's own
    # boosts (Ancient Power) reach the damage it deals us.
    #
    # Burn halves the holder's physical Attack, and that matters in both directions: it is also
    # how many more False Swipes a burned Smeargle needs before the target reaches 1 HP.
    attacker_side = _attacker_side(attacker)
    base_power = variable_base_power(move, defender)
    if (unsupported_reason(move, power_known=base_power is not None) is None
            and unsupported_attacker_reason(attacker_side) is None):
        dealt = damage(
            move,
            attacker_side,
            _defender_side(defender),
            base_power=base_power,
            roll=DAMAGE_ROLL_MAX_PERCENT - damage_roll % DAMAGE_ROLL_COUNT,
            critical=critical,
            # Rain Dance is in the target's own moveset, and under rain Hydro Pump gains half
            # again. Leaving this out did not make the prediction imprecise -- it made every
            # candidate wrong from the first rained-on hit, because the predicted HP is compared
            # exactly.
            weather=weather_of(field),
            # OUR screens, so they apply only when the TARGET is the one attacking. Both are
            # ignored on a crit, which `damage` handles itself.
            reflect=actor == "E" and getattr(field, "reflect_turns", 0) > 0,
            light_screen=actor == "E" and getattr(field, "light_screen_turns", 0) > 0)
        # False Swipe cannot knock out: it leaves the target on 1 HP.
        if move.effect == FALSE_SWIPE_EFFECT:
            dealt = min(dealt, max(0, defender.hp - 1))

    secondary = False
    if move.effect_chance > 0:
        rng, proc_roll = advance(rng)
        used += 1
        # **The roll is spent even on an ineffective hit; the effect is not applied.** Both halves
        # come from one function, `BattleSystem_TriggerSecondaryEffect` (battle_lib.c:1519). It
        # runs from the controller loop rather than from the effect script -- which is why it is
        # reached at all after a move that did not connect -- and its generic branch
        # (battle_lib.c:1569-1586) reads:
        #
        #     if (BattleSystem_RandNext(battleSys) % 100 < effectChance) {
        #         SetupSideEffect(...);
        #         if (curHP && !substituteWasHit
        #             && (moveStatusFlags & MOVE_STATUS_NO_EFFECTS) == FALSE) { result = TRUE; }
        #     }
        #
        # The `Random` is outside every guard, so the advance is unconditional; `result` is what
        # runs the subscript. `MOVE_STATUS_NO_EFFECTS` contains `MOVE_STATUS_DID_NOT_HIT`, which
        # contains `MOVE_STATUS_INEFFECTIVE` (include/constants/battle/moves.h:80-83) -- so a
        # type immunity suppresses the effect and prints nothing.
        #
        # **That makes this an outcome-only correction with no advance-count change**, which is
        # why it needed no capture (clayton-957.26.6). Getting it the other way round -- skipping
        # the roll -- was the reading that WOULD have needed one, and it was wrong.
        #
        # Every chance-based secondary in every configured moveset lands in that branch: the two
        # branches that skip the `NO_EFFECTS` gate are `MOVE_SIDE_EFFECT_PROBABILISTIC` (used by
        # effects 253 and 262 alone -- Flare Blitz and Volt Tackle, in nobody's moveset) and
        # `MOVE_SIDE_EFFECT_CHECK_HP`, which reads no `effectChance` at all and so cannot be a
        # chance-based one. `tests/test_battle_compass_giratina.py` pins that.
        #
        # It applies whatever side the effect lands on. Ancient Power and Ominous Wind boost
        # their own USER, and the ROM gates them on the same flag -- so an Ominous Wind that does
        # nothing to a Normal-typed lead raises none of Giratina's five stats, Speed included.
        secondary = proc_roll % 100 < move.effect_chance and not ineffective
        if secondary:
            parts.append(tok.SECONDARY)

    # The defender's contact abilities. Static is the only one any configured party has, and it is
    # Ampharos's sole ability, so it cannot be opted out of.
    #
    # **Its position relative to the secondary proc above is NOT verified.** The roll COUNT is
    # safe either way -- one extra advance under the conditions `_contact_ability` lists -- but the
    # ORDER decides which roll is which, and swapping two rolls changes every prediction
    # downstream of them. Placed after the secondary because that is the order the battle scripts
    # read in, and flagged here rather than left to look settled: per CLAUDE.md an advance count
    # changes only with a ground-truth capture, and this one has not had one. It costs nothing
    # today, because the planned run paralyzes Ho-Oh on turn 1 and a statused attacker spends no
    # Static roll at all -- so no turn of the real plan contains both rolls.
    rng, used, attacker_status = _contact_ability(
        rng, used, move, attacker, defender, dealt=dealt)
    if attacker_status is not None:
        # It gets a token because nothing else in the turn announces it: the game says "Ho-Oh is
        # paralyzed!" with no move attached, so without a marker of its own the roll is
        # unreportable -- and two candidates differing only in it rendered identical turns, so
        # both survived and the tool held a split belief about the one status the run is built on
        # (clayton-957.10.13). Only emitted when the status LANDED: `_contact_ability` returns
        # None for every case where it could not, so there is nothing to suppress afterwards.
        parts.append(tok.STATIC)

    return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=True,
                            damage=dealt, secondary=secondary,
                            attacker_status=attacker_status,
                            starts_uproar=starts_uproar,
                            # The charged move has fired, so the lock and the vanish come off
                            # (`_055` in the effect script). True for every other move too, where
                            # there is nothing to clear.
                            ends_charge=attacker.charging_slot == slot)


def _contact_ability(rng: int, used: int, move: Move, attacker: Battler, defender: Battler,
                     *, dealt: int) -> tuple[int, int, Status | None]:
    """The defender's on-hit ability. Returns (rng, rolls used, status inflicted on the attacker).

    Only Static so far. `CheckAbilityEffectOnHit`
    (src/battle/overlay_12_0224E4FC.c:3589) reads, in source order:

    ```c
    battleMons[attacker].hp && !battleMons[attacker].status && !(moveStatusFlag & MOVE_STATUS_FAIL)
      && !(battleStatus & CHARGE_TURN) && !(battleStatus2 & UTURN)
      && (selfTurnData[target].physicalDamage || specialDamage)
      && (moveData[moveNoCur].unkB & 1)                     // contact
      && (BattleSystem_Random(battleSystem) % 10 < 3)       // 30%, and LAST
    ```

    **The RNG call is the final term, so C short-circuits before it.** That is the whole point of
    transcribing the order rather than the outcome: every condition in front of it is a condition
    under which the roll is NOT SPENT, and a roll wrongly spent desynchronises every later turn.
    Two consequences worth stating outright:

    * **An already-statused attacker costs nothing.** So the planned turn-1 Thunder Wave makes
      Ampharos's Static permanently dormant for the rest of the battle -- the roll stops existing
      rather than merely stopping mattering.
    * **Contact only**, read off `Move.makes_contact` rather than a move-name list. Among the
      configured targets that is Punishment and nothing else.

    The 30% paralysis is a *benefit* once modelled: an unplanned second route to the Phase 2
    precondition.
    """
    if (defender.ability.strip().lower() != ABILITY_STATIC
            or not move.makes_contact
            or dealt <= 0
            or attacker.fainted
            or attacker.status is not Status.NONE):
        return rng, used, None
    rng, roll = advance(rng)
    used += 1
    if roll % STATIC_MODULUS < STATIC_THRESHOLD:
        return rng, used, Status.PARALYSIS
    return rng, used, None


def _visible_tokens(outcome: MoveOutcome, move: Move, *, victim: Battler,
                    victim_selected_a_move: bool,
                    victim_moves_second: bool,
                    secondary_landed: bool = True) -> tuple[str, ...]:
    """`outcome`'s tokens with an unobservable secondary marker removed.

    Three cases:

    * **The move fainted the victim.** The secondary roll is still spent, but its outcome is
      never shown -- no "was burned!", no stat-drop message -- so it must not be tokenized
      [notes/ss_rng/fainting.md]. Note the case this does NOT cover: a victim that survives the
      move and then faints to the burn the move inflicted *did* see the burn, so that turn keeps
      its ``~`` (``E3h~X2``). Residual damage is not modelled yet, so the simulator cannot
      produce that form at all; when it can, the distinction is already in the right place,
      because this reads the victim's HP after the move and not at the end of the turn.
    * **A flinch whose victim never reaches its turn**, which is most of them -- see
      `flinch_visible`.
    * **A secondary STATUS that could not land** (`secondary_landed`). Non-volatile statuses are
      mutually exclusive, so a Sacred Fire proc against an already-burned Ampharos sets nothing
      and says nothing -- and the plan has Sacred Fire hitting a burned Ampharos for the rest of
      its 8 PP, at a 50% proc rate. The simulator emitted ``E1h~`` for every one of those, so a
      player correctly reporting "no message" eliminated every candidate that procced, the true
      seed included. Same for a Discharge proc against an already-paralyzed Ho-Oh, which is the
      state the whole run is built on reaching.

      The *Safeguard* half of that is the one unverified corner: whether a Safeguard-blocked
      secondary prints a protection message is decided in the battle scripts in `NARC_a_0_0_1`,
      which is not in the decompilation (only four `SIDE_CONDITION_SAFEGUARD` references exist in
      all of `src/`: set, self-fail, expire). Suppressed here on the same reasoning as the rest of
      this function -- losing an observation costs information, inventing one costs the run.

    Only the marker goes; the roll that produced it was already spent inside ``execute_move``, so
    the stream is untouched. The cost is information: a suppressed marker is one the candidate
    set cannot be filtered on. That is the correct trade, because the alternative is filtering on
    something the player never saw.

    A secondary that applies to the ATTACKER (a self-boost like Ancient Power's) would be visible
    even on a KO. No configured moveset has one, and when one lands it belongs here as an
    exception rather than anywhere else.
    """
    if not outcome.secondary:
        return outcome.tokens
    hidden = victim.fainted or not secondary_landed or (
        move.effect in FLINCH_EFFECTS
        and not flinch_visible(victim, victim_selected_a_move=victim_selected_a_move,
                               victim_moves_second=victim_moves_second))
    if not hidden:
        return outcome.tokens
    return tuple(part for part in outcome.tokens if part != tok.SECONDARY)


def sent_out(battler: Battler) -> Battler:
    """`battler` as it arrives on the field: **every stat stage back to neutral**.

    A Pokemon being sent out gets a freshly built BattleMon, and that is where the reset lives
    [verified: `BattleSystem_GetBattleMon`, src/battle/overlay_12_0224E4FC.c:75 --
    ``if (!(battleStatus & BATTLE_STATUS_BATON_PASS)) for (i = 0; i < 8; i++)
    statChanges[i] = 6;``, 6 being neutral]. Baton Pass is the ROM's own exception and nothing in
    any configured party has it.

    On the way IN rather than on the way out, because that is where the ROM does it -- a benched
    Pokemon's stages are simply never read.

    What does NOT reset is the non-volatile status: the same function reads it from
    `MON_DATA_STATUS`, the PARTY Pokemon's own byte, so a burned Pokemon switches out and back
    still burned. That is also why a revived one comes back clean (clayton-957.10.14), so the two
    rules are the same rule read from both ends.
    """
    return replace(reset_stages(battler),
                   # `moveEffectsMask` and `statusVolatile` are zeroed by the same fresh
                   # BattleMon, so a Yawn shaken off by switching really is shaken off and an
                   # Uproar cannot be carried onto the field by somebody else. Which is the
                   # OPPOSITE of a pending Future Sight: that one is a field condition indexed by
                   # battler position, so the newcomer takes it (`BattleState.future_sight_turns`).
                   #
                   # `nightmare` and `charging_slot` live in those same two ROM fields and are
                   # NOT reset here. That is a pre-existing gap rather than a decision, and it is
                   # left alone rather than changed in passing because the advance counts around
                   # Darkrai were all fitted with it as it is (clayton-6xu.7.2).
                   #
                   # `identified` is in `statusVolatile` and so belongs to the same zeroing: a
                   # Foresight a target put on us is shaken off by switching. Reachable only in
                   # that direction, since the target itself never switches out -- which is what
                   # makes OUR Foresight on it last the whole battle.
                   drowsy_turns=0, uproar_turns=0, uproar_slot=None, taunted_turns=0,
                   identified=False)


#: Every stage field on a `Battler`: what Haze resets, and what a send-out resets. Named once so
#: the two cannot drift -- a field added to `Battler` and forgotten in one of them would be a
#: stage that survives a Haze or a switch, silently.
#:
#: Not to be confused with `hunt_session.STAGE_FIELDS`, which is the same seven paired with their
#: UI labels. That one keeps its own name because the labels are a presentation concern this
#: module should not carry; a test pins the two against each other.
STAGE_FIELD_NAMES = ("atk_stage", "def_stage", "spatk_stage", "spdef_stage", "speed_stage",
                     "accuracy_stage", "evasion_stage")


def reset_stages(battler: Battler) -> Battler:
    """`battler` with every stat stage back to neutral.

    `BtlCmd_ResetAllStatChanges` loops `BATTLE_STAT_HP` to `BATTLE_STAT_MAX`, i.e. all of them,
    with no exceptions -- so this is deliberately not selective. Focus Energy is cleared in the
    same loop and is not modelled on either side; nothing in any configured moveset sets it.
    """
    return replace(battler, **{field: 0 for field in STAGE_FIELD_NAMES})


def _all_stats_up(battler: Battler) -> Battler:
    """Ancient Power's 10%: every stat up one stage, capped at +6.

    Mostly harmless against a target held still -- except Speed. Stages are applied BEFORE
    paralysis quarters Speed (`effective_speed`), so they claw it back: +6 restores the full
    figure exactly and the speed-tie guarantee sec 4.2 buys with paralysis is gone.
    """
    return replace(
        battler,
        atk_stage=min(6, battler.atk_stage + 1),
        def_stage=min(6, battler.def_stage + 1),
        spatk_stage=min(6, battler.spatk_stage + 1),
        spdef_stage=min(6, battler.spdef_stage + 1),
        speed_stage=min(6, battler.speed_stage + 1))


def party_number(battler: Battler, bench_slot: int) -> int:
    """The 1-based party slot an ``S``/``X``/``R`` token should name.

    `battler.party_slot` whenever a party was actually built, which the app always does. The
    fallback is the old positional guess -- the active Pokemon was slot 1, so bench index *i* was
    slot *i* + 2 -- and it exists only for a Battler constructed directly, as the simulator's own
    tests do. The guess is what the stable slot replaces: it is right until the first switch and
    wrong afterwards, because the bench it counts along has moved.
    """
    return battler.party_slot or bench_slot + 2


def party_order(bench: tuple[Battler, ...]) -> tuple[Battler, ...]:
    """`bench` in party order, so a bench index means the same thing all run.

    HGSS never reorders a party, so neither may this. The outgoing Pokemon used to be appended to
    the end of the bench, which made every index after the first switch describe somebody else.
    Sorting is stable, so a bench with no party slots assigned keeps the order it came in with.
    """
    return tuple(sorted(bench, key=lambda b: b.party_slot))


def select_target_move(rng: int, target: Battler) -> tuple[int, int | None]:
    """The wild move-selection roll: ``RANDOM % (moves with PP)``, indexing the survivors.

    One roll per turn **except while the target is locked into a multi-turn move or an Uproar**,
    and the modulus shrinks as PP runs out — so its entropy decays from 2.00
    bits to 1.58 to 1.00 and then to nothing (sec 5.2 R4, verified). Returns (rng, slot), with
    slot None when nothing is usable and the target would have to Struggle.

    **A None slot is outside the model.** Struggle is not simulated: no roll is spent, no damage
    is dealt and no recoil is applied, so such a turn is silently wrong rather than visibly
    unsupported. It also loses the run in reality, because Struggle recoil kills a 1 HP target.
    The solver therefore never searches that far — see ``solver.struggle_deadline`` — and callers
    that might should check for None themselves.
    """
    if target.charging_slot is not None:
        # Locked into the second half of a multi-turn move, so the ROM never asks it to pick:
        # `Battler_CanPickCommand` is FALSE and command selection is skipped entirely
        # [src/battle/battle_controller_player.c:334-338]. **One advance fewer on that turn**,
        # and getting it wrong would desynchronise every turn after Giratina's Shadow Force.
        return rng, target.charging_slot
    if target.uproar_turns and target.uproar_slot is not None:
        # Mid-Uproar, and the same branch of `Battler_CanPickCommand` is what skips the roll --
        # `VOLATILE_CONDITION_UPROAR` sits beside `THRASH` and `MOVE_LOCKED` in the same
        # condition (battle_lib.c:6224-6236). So an Azelf three turns into an Uproar has spent
        # three fewer selection rolls than a candidate that thought the Uproar had ended, which
        # is the sharpest separation any configured target offers: it is a divergence in roll
        # COUNT rather than in one roll's verdict.
        return rng, target.uproar_slot
    usable = target.usable_slots()
    if not usable:
        return rng, None
    rng, roll = advance(rng)
    return rng, usable[roll % len(usable)]


def throw_ball(rng: int, target: Battler, *, catch_rate: int, ball_multiplier: int,
               status_bonus: int) -> tuple[int, int, bool]:
    """Resolve a throw, returning (rng, shakes, captured).

    The ROM stops rolling at the first failure, so a throw spends 1-4 rolls rather than always 4
    — which is what makes a ball a variable-cost filler action (sec 12.5).
    """
    a = catch_value(catch_rate, ball_multiplier=ball_multiplier,
                    cur_hp=max(target.hp, 1), max_hp=target.max_hp,
                    status_bonus=status_bonus)
    if is_guaranteed(a):
        return rng, SHAKES_TO_CAPTURE, True
    threshold = shake_threshold(a)
    rolls: list[int] = []
    for _ in range(SHAKES_TO_CAPTURE):
        rng, roll = advance(rng)
        rolls.append(roll)
        if roll >= threshold:
            break
    shakes = shakes_for_rolls(rolls, threshold)
    return rng, shakes, shakes == SHAKES_TO_CAPTURE


def _status_bonus(status: Status) -> int:
    from claytonlib.battle import catch
    return {
        Status.NONE: catch.STATUS_NONE,
        Status.PARALYSIS: catch.STATUS_PARALYSIS,
        Status.SLEEP: catch.STATUS_SLEEP,
        Status.FREEZE: catch.STATUS_FREEZE,
        Status.BURN: catch.STATUS_BURN,
        Status.POISON: catch.STATUS_POISON,
    }[status]


#: Rolls the game spends between generating the battle seed and the first turn's move-selection
#: roll. Four for the Bell Tower's Suicune shimmer (`bellShimmerReplaceGraphics`) plus two for
#: Pressure's announcement [verified: data/battle_logs/test1.jsonl, test2.jsonl].
#: ``metronome_compass._BATTLE_START_ADVANCES`` independently landed on the same 6 for
#: Blackthorn, where the 2 are the same ability announcement -- corroboration, not coincidence.
BATTLE_START_ADVANCES = 6


@dataclass(frozen=True)
class HuntConfig:
    """Everything a simulation needs that does not change during the battle.

    **"Does not change" stopped being true of the ball.** Platinum's Quick Ball is ×4 on turn 1
    only and its Timer Ball climbs to ×4, so a throw's multiplier is a function of the turn
    (notes/platinum.md §5.3). That is why the multiplier is reached through `ball_multiplier_at`
    rather than read off a field: everything else here really is constant, and the one thing that
    is not says so in its name.
    """
    target_catch_rate: int
    #: The ball by name, resolved through `claytonlib.battle.balls`. When set it is the authority,
    #: and `capture_ball_multiplier` / `fast_ball_matched` below are ignored.
    capture_ball: str = ""
    #: The non-turn context a conditional ball needs: terrain, time of day, the target's types,
    #: level and base Speed, and whether the species is already registered. The turn is filled in
    #: per throw, which is the whole point.
    throw: ThrowContext = field(default_factory=ThrowContext)
    #: Explicit multiplier, for a caller that has one and no ball name. Pre-dates `capture_ball`
    #: and is kept so every existing fixture and test still means what it meant.
    capture_ball_multiplier: int = BALL_POKE
    #: Pressure doubles OUR PP consumption, not the target's own (sec 4.4).
    target_has_pressure: bool = True
    #: Bad Dreams takes an eighth of our max HP every turn we spend asleep. Darkrai's only
    #: ability, so for that target it is not optional.
    #:
    #: Defaults FALSE where `target_has_pressure` defaults True, and the asymmetry is deliberate:
    #: the default has to be the one that is wrong in the safe direction, and these two are
    #: opposite. Assuming Pressure where there is none only over-budgets PP; assuming Bad Dreams
    #: where there is none would subtract HP the game never subtracts, which contradicts every
    #: candidate from that turn on.
    target_has_bad_dreams: bool = False
    #: True once the target's base Speed clears the Fast Ball's threshold.
    fast_ball_matched: bool = False
    #: Rolls to burn before turn 1. A field rather than a bare constant because the count is
    #: venue-specific: the four animation rolls are the Bell Tower's, and a different encounter
    #: would spend a different number. See :data:`BATTLE_START_ADVANCES`.
    battle_start_advances: int = BATTLE_START_ADVANCES

    def ball_effect_at(self, turn: int = 0) -> BallEffect:
        """What the capture ball is worth on `turn` (0 == the first turn, as the ROM counts).

        Falls back to the explicit `capture_ball_multiplier` / `fast_ball_matched` pair when no
        ball name is set, so a config built the old way behaves exactly as it did.
        """
        if self.capture_ball:
            return ball_effect(self.capture_ball, self.target_catch_rate,
                               replace(self.throw, turn=turn))
        return BallEffect(
            catch_rate=fast_ball_catch_rate(self.target_catch_rate,
                                            100 if self.fast_ball_matched else 0),
            multiplier=self.capture_ball_multiplier)

    def effective_catch_rate(self, turn: int = 0) -> int:
        return self.ball_effect_at(turn).catch_rate

    def ball_multiplier_at(self, turn: int = 0) -> int:
        return self.ball_effect_at(turn).multiplier

    @property
    def ball_is_turn_dependent(self) -> bool:
        """Whether `b` moves with the turn — a Quick or Timer Ball.

        Worth reporting rather than inferring: the solver's dominance key assumes a threshold that
        does not improve over time, and a Timer Ball's does.
        """
        return bool(self.capture_ball) and is_turn_dependent(self.capture_ball)

    def standard_ball_matches_capture_ball(self, turn: int = 0) -> bool:
        """Whether a plain Poke Ball is exactly as likely to catch as the capture ball.

        This is the fact behind sec 2.3's warning, and it is a property of the MATCHUP rather
        than of the phase. On Suicune the Fast Ball misses its base-Speed threshold, so both
        balls are a flat x1 and a standard ball that lands is a lost run. Against a target the
        Fast Ball actually matches, a standard ball is far weaker and a probe is correspondingly
        cheaper. Reported to the UI so the warning can say which case the player is in instead of
        asserting the harsher one.
        """
        effect = self.ball_effect_at(turn)
        return (not effect.guaranteed and effect.multiplier == BALL_POKE
                and effect.catch_rate == self.target_catch_rate)


def opening_rng(seed: int, config: HuntConfig) -> int:
    """The RNG state turn 1 actually starts from, given the *battle seed*.

    **A candidate seed is not a usable RNG state.** The game spends
    ``config.battle_start_advances`` rolls between generating the battle seed and the first turn,
    so a simulation seeded with the raw seed is running the wrong stream. Every candidate is
    wrong by the same six advances, which is why the mistake hides so well: a synthetic fixture
    built with the same convention agrees with itself perfectly, and only a real recording
    disagrees.

    It disagreed in exactly the way that matters. Replaying ``data/battle_logs/test2.jsonl``
    against its own forced seed, the true seed was **eliminated on turn 1** while 29 unrelated
    candidates survived -- no contradiction raised, just a confidently wrong set. With the
    advances applied the same 121-candidate window narrows to the true seed by turn 5 and holds
    it for all 38 recorded turns.
    """
    rng = seed
    for _ in range(config.battle_start_advances):
        rng = advance_rng(rng)
    return rng


def effective_speed(battler: Battler) -> int:
    """Speed as the turn-order comparison sees it: stat stage, held item, then paralysis.

    Paralysis quartering Speed is the whole reason it is the sanctioned tie-avoidance: it takes
    Suicune to ~21, so anything outspeeds it and no speed-tie roll occurs anywhere in the search
    (sec 4.2).

    **The order is not cosmetic.** Transcribed from the speed comparison in
    src/battle/overlay_12_0224E4FC.c: the stat stage first, then the weather abilities, then a
    Macho Brace or Iron Ball halving, then the Choice Scarf's ``* 15 / 10``, then Quick Powder,
    and only then paralysis's ``/ 4``. Each step truncates, so `spe * 15 / 10 / 4` and
    `spe / 4 * 15 / 10` are different numbers.

    The stage going first is what makes Ancient Power dangerous rather than merely annoying:
    stages multiply and paralysis divides, so **+6 cancels the quartering exactly** -- a paralyzed
    target at +6 Speed is back to its full figure, and the no-speed-tie guarantee that sec 4.2
    buys with paralysis is gone.

    This read `stats["spe"]` and nothing else, which made a Choice Scarf invisible -- and a
    scarfed Lv70 Magneton is 186 against Ho-Oh's 152, so the model had us moving SECOND on the
    one turn the whole plan hangs on. Turn order decides whose rolls come first, so that is not a
    slightly-wrong prediction; it is a different stream from the first turn onward.

    Lagging Tail is deliberately NOT here: it sets a lowered-priority flag rather than changing
    Speed, so the holder moves last within its bracket (`readiness.MOVES_LAST_ITEMS`). Reading it
    as a Speed modifier would be wrong in both directions -- and it would be actively harmful
    here, since Battle Compass wants to move FIRST.
    """
    speed = speed_after_item(apply_stage(battler.stats["spe"], battler.speed_stage),
                             battler.held_item)
    if battler.status is Status.PARALYSIS:
        speed //= PARALYSIS_SPEED_DIVISOR
    return speed


def _we_move_first(state: BattleState, action: Action, target_slot: int | None) -> bool:
    """Turn order: the higher priority bracket, then the higher effective Speed.

    A tie would cost an extra roll (notes/ss_rng/speed.md), so the solver's contract is that one
    cannot arise: paralysis guarantees a Speed gap. `speed_warnings` in ``battle.readiness`` is
    what checks that before a hunt starts.
    """
    if action is Action.FAINTED:
        # Reporting that we were fainted before moving IS the statement that the target moved
        # first -- that is how we got fainted. Said explicitly so the two can never disagree:
        # otherwise a faster Pokemon of ours would be simulated as acting (and doing nothing)
        # first, and the turn would spend the wrong end-of-turn advances.
        return False
    ours = state.ours.move(action.move_slot) if action.move_slot is not None else None
    theirs = state.target.move(target_slot) if target_slot is not None else None
    our_priority = ours.priority if ours is not None else 0
    their_priority = theirs.priority if theirs is not None else 0
    if our_priority != their_priority:
        return our_priority > their_priority
    return effective_speed(state.ours) > effective_speed(state.target)


def _tick_uproar(state: BattleState, move_failed: dict[str, bool] | None = None) -> None:
    """The Uproar end-of-turn check, state 14 of the condition walk. Costs no rolls.

    Three things happen here and the order between them is the whole content of
    `MON_COND_CHECK_STATE_UPROAR` (battle_controller_player.c:1505-1545):

    1. **It wakes sleepers first**, looping every battler for one that is asleep, alive and not
       Soundproof -- and if it finds one it runs `subscript_wake_up` and **breaks out before the
       countdown**. So an Uproar that woke somebody lasts one turn longer than its rolled length.
    2. **Then it decrements, and then it asks `BattleContext_MoveFailed` BEFORE it looks at what
       the counter now holds.** If the uproarer's move failed this turn, the volatile and the
       field bit are cleared outright and `subscript_uproar_end` runs -- whatever is left on the
       counter. `move_failed` carries that verdict in from the turn; see its declaration in
       `simulate_turn` for which of the ROM's nine flags are reachable and which are not.
    3. Otherwise the lock comes off on the turn the counter reaches zero.

    Point 2 is MEASURED, and getting it wrong was a desync rather than a cosmetic error.
    data/battle_logs/azelf_failure.jsonl (forced seed 0x49023160, confirmed) has Azelf roll
    duration 3 for its second Uproar -- roll 47036 at `subscript_uproar`, 47036 % 4 == 0 -- and
    then run it for only TWO turns, because it was fully paralyzed on the second one and
    "The wild AZELF calmed down." printed a turn early. With the lock wrongly still on,
    `select_target_move` withholds a selection roll the game spends: the next turn the game rolled
    21272 % 4 == 0 -> Swift while this simulator predicted a locked Uproar, and every roll after
    that was off by one.

    Point 1 is unreachable against either configured Uproar user as things stand: only Azelf has
    the move, nothing in its set can sleep us, and `will_fail` refuses a sleep move of ours while
    an Uproar is up -- so by the time this runs nobody is asleep. Transcribed anyway, because the
    alternative is a silent off-by-one the day anything changes, and because the two act functions
    already call `_wake_for_uproar` for the mid-turn half of the same rule.

    `MON_COND_CHECK_STATE_THRASH`, immediately after, carries the identical `MoveFailed` rule for
    Thrash and Petal Dance (same file, 1547-1570). No modelled battler has either move, so there
    is nothing here to tick for it.
    """
    for side, actor in (("ours", "M"), ("target", "E")):
        battler = getattr(state, side)
        if not battler.uproar_turns:
            continue
        woke = False
        for victim_side in ("ours", "target"):
            victim = getattr(state, victim_side)
            awakened = _wake_for_uproar(victim, state)
            if awakened is not victim:
                setattr(state, victim_side, awakened)
                woke = True
                break                    # the ROM breaks on the FIRST sleeper it finds
        if woke:
            continue                     # ...and skips the countdown entirely
        if move_failed is not None and move_failed.get(actor):
            # The early exit. Not `uproar_turns - 1`: the ROM clears the volatile whole, so a
            # duration-6 Uproar disrupted on its first continuation turn is simply over.
            setattr(state, side, replace(battler, uproar_turns=0, uproar_slot=None))
            continue
        left = battler.uproar_turns - 1
        setattr(state, side, replace(battler, uproar_turns=left,
                                     uproar_slot=battler.uproar_slot if left else None))


def _tick_taunt(state: BattleState) -> None:
    """Taunt's countdown, state 20 of the end-of-turn condition walk. Costs no rolls.

    `MON_COND_CHECK_STATE_TAUNT` (battle_controller_player.c:1636-1644) decrements and runs
    `subscript_taunt_end` on reaching zero -- a message and nothing else. So this spends nothing
    and needs no position inside the measured end-of-turn advances, which is the one mercy in the
    whole of `_END_OF_TURN_RESIDUAL_ANCHOR`'s neighbourhood.

    Ordered between `_tick_uproar` (state 14) and `_tick_drowsy` (state 24) because that is the
    walk's order. Nothing observable depends on it -- none of the three spends a roll where this
    one sits -- but a reader checking the sequence against the ROM should find it in the right
    place.
    """
    for side in ("ours", "target"):
        battler = getattr(state, side)
        if battler.taunted_turns:
            setattr(state, side, replace(battler, taunted_turns=battler.taunted_turns - 1))


def _tick_drowsy(rng: int, state: BattleState) -> tuple[int, int, int]:
    """Yawn's countdown, state 24 of the condition walk.

    Returns ``(rng, rolls spent, rolled sleep turns for OUR side)``.

    The counter is decremented first and `subscript_fall_asleep` runs when it reaches zero; that
    script then re-checks everything -- Insomnia and Vital Spirit, an Uproar, an existing status
    -- and bails *before* its ``Random 3, 2``. So **the duration roll is spent only when the
    sleep actually lands**, and a drowse that expires onto an already-paralyzed Pokemon costs
    nothing at all. The counter is consumed either way: the ROM decrements unconditionally.

    Our side's duration is RETURNED rather than applied, because the status has to land after the
    HP residuals (states 9 and 12 come before state 24, so Nightmare and Bad Dreams tick on a
    victim that is still awake). The target's is applied here and now -- the target's residuals
    are deliberately not simulated at all (`state.HP_TICKING_STATUSES`), so there is nothing for
    it to be ordered against. Reachable only through a Yawn of ours, which
    `MODELLED_OUR_EFFECTS` does not list; it is ticked rather than left to rot so that the
    counter cannot be set by a path that never clears it.
    """
    spent = 0
    ours_turns = 0
    for side in ("ours", "target"):
        battler = getattr(state, side)
        if not battler.drowsy_turns:
            continue
        battler = replace(battler, drowsy_turns=battler.drowsy_turns - 1)
        setattr(state, side, battler)
        if battler.drowsy_turns:
            continue
        if (battler.status is not Status.NONE
                or immune_to_status(battler, Status.SLEEP)
                or uproar_active(state)):
            continue                     # bailed before the Random; nothing spent
        rng, duration_roll = advance(rng)
        spent += 1
        turns = SLEEP_DURATION_MIN + duration_roll % SLEEP_DURATION_SPAN
        if side == "ours":
            ours_turns = turns
        else:
            setattr(state, side, battler.with_status(Status.SLEEP, sleep_turns=turns))
    return rng, spent, ours_turns


def _roll_future_sight(rng: int, state: BattleState) -> tuple[int, int, bool | None]:
    """A pending Future Sight's countdown and its hit check.

    Returns ``(rng, rolls spent, hit)``, with `hit` None when nothing landed this turn.

    The ROM is one condition (`SIDE_COND_CHECK_STATE_FUTURE_SIGHT`,
    battle_controller_player.c:1768-1771)::

        if (futureSightTurns[battler] && --futureSightTurns[battler] == FALSE
                && battleMons[battler].curHP) { ...PrepareSubroutineSequence(subscript_future_sight_damage) }

    **The decrement is inside the condition and the HP check is after it**, which is the detail
    worth transcribing: a Future Sight whose turn comes up while its victim is fainted still
    counts down to zero and then simply never fires. No subscript, so no roll -- and the damage
    is lost rather than deferred.

    When it does fire, `subscript_future_sight_damage.s` opens with `CheckMoveHit`: one ordinary
    accuracy roll, at the BANKED move's accuracy, with this turn's accuracy and evasion stages.
    `SYSCTL_NONSTANDARD_ACC_CHECK` was set on the turn the move was used and does not survive it,
    so the check really happens -- 90 for Future Sight, which makes it the only sub-100 event in
    either Uxie's or Azelf's moveset.
    """
    if not state.future_sight_turns:
        return rng, 0, None
    state.future_sight_turns -= 1
    if state.future_sight_turns or state.ours.fainted:
        return rng, 0, None
    # Imported here rather than at module scope on purpose: `claytonlib.moves.resolve_move` looks
    # a Move up by NAME, and a module-level import would shadow it into this module's namespace --
    # which is the exact confusion `execute_move` is named the way it is to avoid, and which
    # tests/test_claytonlib_exports.py asserts against.
    from claytonlib.moves import resolve_move as move_by_name

    move = move_by_name(state.future_sight_move)
    if move is None:                     # a state built by hand, or a move table gap
        return rng, 0, None
    rng, hit_roll = advance(rng)
    # The attacker is the target: Future Sight is in no party moveset, and `act_ours` refuses to
    # bank one. So the accuracy stage read is the TARGET's and the evasion stage OURS, which is
    # what `accuracy_net_stage` does with these two arguments in this order.
    net_stage = accuracy_net_stage(state.target, state.ours)
    hit = hit_roll % 100 < _effective_accuracy(
        move, net_stage, attacker=state.target, defender=state.ours, deferred_check=True)
    return rng, 1, hit


def simulate_turn(state: BattleState, action: Action, config: HuntConfig, *,
                  item_code: str | None = None,
                  bench_slot: int | None = None,
                  replacement: int | None = None) -> BattleState:
    """One turn, advancing `state` and appending its rendered tokens to ``state.log``.

    Structure per ``claytonlib.battle.turn`` (verified): the wild move-selection roll, four
    BeforeTurn rolls, the first actor, two more if that was a successful move, two between-turn
    rolls, the second actor, two more if successful, four end-of-turn rolls.

    Two ordering choices follow ``metronome_compass.simulate_turn`` rather than direct
    measurement, and are the R7 residual: the selection roll opening the turn, and a paralysis
    check costing one roll before the move it prevents.

    `bench_slot` is which party member a ``SWITCH`` brought in, or which one a ``REVIVE`` was
    used on, as an **index into `state.bench`**. `replacement` is which one came in if we FAINT
    this turn, as a **party slot** -- a different question and deliberately a different kind of
    number, because a faint is not an action we chose and it resolves at the END of the turn,
    after a switch may already have rearranged the bench. See `_send_out`.
    """
    new = state.copy()
    rng = new.rng
    start_offset = new.rng_offset
    parts: list[str] = []
    hp_before = new.ours.hp

    # The wild mon picks its move at the top of the turn, whoever ends up moving first.
    #
    # The offset is charged from whether the stream MOVED, not from whether a slot came back.
    # `select_target_move` returns a non-None slot and spends nothing on the two turns where its
    # user cannot pick a command -- mid-Uproar and mid-charge -- so `target_slot is not None` was
    # charging a roll the game never spent, once per locked turn. The stream stayed right and the
    # offset drifted, which is the worse of the two failures: `solver._state_key` uses the offset
    # AS the stream position and `solver` dedupes its visited set on it.
    #
    # An LCRNG step can never be a no-op here -- a fixed point needs state * (A - 1) == -C mod
    # 2**32, and A - 1 is even while C is odd -- so an unchanged `rng` means exactly "no roll".
    rng_before = rng
    rng, target_slot = select_target_move(rng, new.target)
    if rng != rng_before:
        new.rng_offset += 1

    for _ in range(turn_costs.BEFORE_TURN_ADVANCES):
        rng = advance_rng(rng)
    new.rng_offset += turn_costs.BEFORE_TURN_ADVANCES

    # Bag actions resolve before any move, so we always act first when using one. Otherwise
    # priority brackets first, then effective Speed -- paralysis quarters the target's, which is
    # what removes speed ties from the search entirely (sec 4.2).
    ours_first = action.is_bag_action or _we_move_first(new, action, target_slot)

    def apply_field(outcome) -> None:
        """Field conditions the move just set. Applied here because the state lives here."""
        if outcome.sets_rain:
            new.rain_turns = RAIN_TURNS
        if outcome.sets_mist:
            new.mist_turns = MIST_TURNS
        if outcome.traps:
            new.target_trapped = True
        if outcome.sets_water_sport:
            new.target_water_sport = True
        if outcome.sets_safeguard:
            new.safeguard_turns = SAFEGUARD_TURNS
        # Screens are OUR side's, so a `sets_*` can only come from `act_ours`. The duration is
        # carried on the outcome rather than read here, because it depends on the setter's held
        # item (Light Clay) and the setter is whoever used the move.
        if outcome.sets_reflect:
            new.reflect_turns = outcome.screen_turns
        if outcome.sets_light_screen:
            new.light_screen_turns = outcome.screen_turns

    #: Set when the actor that moved FIRST procced a flinch, so the second actor loses its move.
    #: A dict rather than two nonlocals because both sides are symmetric and only one can ever be
    #: set in a turn -- the flincher has to have moved already.
    flinched = {"M": False, "E": False}
    #: Set when a battler's move was prevented this turn by a disruption the ROM counts as a
    #: FAILURE, which is a narrower thing than "did not move". `BattleContext_MoveFailed`
    #: [battle_lib.c:2808-2821] reads nine flags -- paralyzed, noEffect, imprisoned, infatuated,
    #: disabled, taunted, flinched, gravity, confused -- and sleep, freeze, truant, recharge, a
    #: plain miss and Heal Block are all deliberately absent from that list. Three of the nine are
    #: reachable here (paralysis, flinch, a taunt refusal); the other six belong to mechanics this
    #: simulator does not model at all, so the flag is set at exactly three sites.
    #:
    #: Read by `_tick_uproar`, where it is the difference between a lock that counts down and one
    #: that comes off early -- see the measured case in that docstring. Cleared per turn because
    #: `BattleSystem_SetupNextTurn` clears the ROM's copy [battle_lib.c:2228-2234].
    move_failed = {"M": False, "E": False}

    def act_ours() -> bool:
        nonlocal rng, hp_before
        if action is Action.FAINTED or new.ours.fainted:
            # No rolls at all: not the move's own, not the two post-successful-move advances,
            # and not even a status check [verified, notes/ss_rng/fainting.md]. The move the
            # player selected never executed, so it costs no PP and emits no token -- which is
            # why `Action.FAINTED` need not say which move it was.
            return False
        if action is Action.CAPTURE_BALL or action is Action.STANDARD_BALL:
            # `new.turn` is still the count of COMPLETED turns here -- it is incremented at the
            # end of the turn -- which is exactly the ROM's `totalTurns`, so a Quick Ball's
            # "first turn" and a Timer Ball's climb line up without an adjustment.
            effect = config.ball_effect_at(new.turn)
            multiplier = (effect.multiplier
                          if action is Action.CAPTURE_BALL else BALL_POKE)
            rate = (effect.catch_rate if action is Action.CAPTURE_BALL
                    else config.target_catch_rate)
            rng, shakes, captured = throw_ball(
                rng, new.target, catch_rate=rate, ball_multiplier=multiplier,
                status_bonus=_status_bonus(new.target.status))
            new.rng_offset += min(shakes + 1, SHAKES_TO_CAPTURE)
            new.balls_thrown += 1
            parts.append(tok.ball_token(shakes, captured=captured,
                                        capture_ball=action is Action.CAPTURE_BALL))
            if action is Action.CAPTURE_BALL:
                new.captured = captured
            else:
                new.captured_in_wrong_ball = captured
            return False
        if action is Action.SWITCH:
            # Costs no advances of its own (verified), but it changes WHO is out -- which decides
            # turn order, what the incoming damage is computed against, and whose HP the rest of
            # the turn refers to. An earlier version emitted an item token and swapped nobody,
            # so a switch silently kept simulating the Pokemon that had left.
            if bench_slot is None or not 0 <= bench_slot < len(new.bench):
                raise ValueError(
                    f"a switch needs which party member came in: bench_slot={bench_slot!r} with "
                    f"{len(new.bench)} on the bench")
            incoming = new.bench[bench_slot]
            # Kept in PARTY order, not rotated. Appending the outgoing Pokemon to the end made
            # every bench index after the first switch point at somebody else, so switching out
            # and back emitted the same token twice instead of S3 then S1.
            # Leaving the field ends a Choice lock, which is the only way it ends. Cleared on
            # the way out so the Pokemon can be sent back in later with all four moves.
            new.bench = party_order(
                tuple(b for i, b in enumerate(new.bench) if i != bench_slot)
                + (replace(new.ours, choice_locked_slot=None),))
            incoming = sent_out(incoming)
            new.ours = incoming
            # Intimidate fires on the way in, before any move of this turn resolves, and costs no
            # advances. Re-fires on every entry, so a shuttle can stack it (see
            # `_apply_intimidate`).
            new.target = _apply_intimidate(incoming, new.target)
            # The HP token reports a CHANGE to one Pokemon, so the baseline has to follow whoever
            # is out at the end of the turn. Left as the outgoing Pokemon's HP it compared two
            # different Pokemon and emitted a token for a switch that took no damage at all.
            # Safe here because a switch always resolves before any move, so nothing has hit the
            # incoming Pokemon yet.
            hp_before = incoming.hp
            parts.append(tok.switch_token(party_number(incoming, bench_slot)))
            return False
        if action is Action.REVIVE:
            # Used on somebody who is NOT out, which is why it carries a slot and why it cannot
            # be an entry in the item table. Costs no advances, like every other bag action.
            if bench_slot is None or not 0 <= bench_slot < len(new.bench):
                raise ValueError(
                    f"a Revive needs which party member it was used on: bench_slot="
                    f"{bench_slot!r} with {len(new.bench)} on the bench")
            revived = new.bench[bench_slot]
            if not revived.fainted:
                raise ValueError(
                    f"{revived.name} has not fainted, so a Revive would do nothing")
            # Healthy, not merely alive. `with_hp` clears the status on the way DOWN, so this is
            # belt-and-braces for a party member configured as fainted rather than simulated into
            # it -- and it states the rule where a reader looks for it.
            back = (revived.with_status(Status.NONE)
                    .with_hp(items.revive_amount(revived.max_hp)))
            new.bench = tuple(back if i == bench_slot else b
                              for i, b in enumerate(new.bench))
            parts.append(tok.revive_token(party_number(revived, bench_slot)))
            return False
        if action.is_bag_action:
            # Items cost no advances of their own (verified) -- but they are not inert. A potion
            # that healed nothing here would make the predicted HP diverge from the real one and
            # contradict every candidate on the next report.
            # ITEM_CURE has one sensible reading, so it defaults. ITEM does NOT: potions
            # differ by an order of magnitude, and a silent fallback here let the solver price a
            # Hyper Potion and simulate a Potion for as long as nobody checked the numbers. A
            # missing code is a caller bug, so it is raised rather than guessed.
            if action is Action.ITEM and not item_code:
                raise ValueError(
                    "Action.ITEM needs an item_code: there is no safe default among items that "
                    "heal 20 and 200. Pass the code the player actually used.")
            code = item_code or "fh"
            entry = items.item(code)
            # The game refuses a heal at full HP and a cure with nothing to cure, so a turn
            # reporting one is not a turn that happened. Raised rather than rendered, because the
            # rendering was unvalidatable: no HP changed, so no HP token, which
            # `tokens.turn_requires_hp` then rejected.
            refusal = items.unusable_reason(
                code, hp=new.ours.hp, max_hp=new.ours.max_hp,
                statused=new.ours.status is not Status.NONE)
            if refusal:
                raise ValueError(refusal)
            if entry.heals and new.ours.hp is not None:
                healed = items.heal_amount(code, new.ours.hp, new.ours.max_hp)
                if healed:
                    new.ours = new.ours.with_hp(new.ours.hp + healed)
            if entry.cures_status:
                new.ours = new.ours.with_status(Status.NONE)
            if entry.raises:
                stat, stages = entry.raises
                if stat == "spd":
                    new.ours = replace(new.ours,
                                       spdef_stage=min(6, new.ours.spdef_stage + stages))
                elif stat == "def":
                    new.ours = replace(new.ours,
                                       def_stage=min(6, new.ours.def_stage + stages))
            parts.append(tok.item_token(code))
            return False
        slot = action.move_slot
        move = new.ours.move(slot)
        if move is None:
            return False
        # sleep -> flinch -> paralysis, which is metronome_compass's verified turn order.
        # A sleeping or flinched turn spends no roll; the paralysis CHECK does.
        # An Uproar ends our sleep before the counter would -- and before the counter is read, so
        # the turns it had left are simply gone.
        new.ours = _wake_for_uproar(new.ours, new)
        new.ours, awake = new.ours.tick_sleep()
        if not awake:
            parts.append(tok.prevented_token("M", "slp"))
            return False
        if flinched["M"]:
            move_failed["M"] = True
            parts.append(tok.prevented_token("M", "fln"))
            return False
        if taunt_refuses(move, new.ours):
            # BEFORE the paralysis check, and that order is the whole cost model: the taunt test
            # is state 6 of the before-move walk and the paralysis roll is state 11, and a refusal
            # returns CHECK_STATUS_DISRUPT_MOVE, which stops the walk there. So a taunted AND
            # paralyzed actor spends NOTHING -- not even the paralysis roll it would otherwise
            # owe. Zero rolls, no post-successful-move advances, and the slot is reported because
            # the game names the move (`tokens.TAUNTED`).
            move_failed["M"] = True
            parts.append(tok.taunted_token("M", slot))
            return False
        if new.ours.status is Status.PARALYSIS:
            # R7 residual: a paralysis check costs one roll, as metronome_compass models it.
            rng, roll = advance(rng)
            new.rng_offset += 1
            if roll % 4 == 0:
                move_failed["M"] = True
                parts.append(tok.prevented_token("M", "par"))
                return False
        rng, outcome = execute_move(
            rng, move, new.ours, new.target, actor="M", slot=slot, field=new)
        new.rng_offset += outcome.rolls
        new.ours = new.ours.spend_pp(slot, 2 if config.target_has_pressure else 1)
        # A Choice item locks its holder into the first move it uses, and stays locked until the
        # Pokemon leaves the field. Set here rather than on the attempt, because the ROM records
        # it alongside the move actually going off.
        if new.ours.holds_choice_item and new.ours.choice_locked_slot is None:
            new.ours = replace(new.ours, choice_locked_slot=slot)
        apply_field(outcome)
        if outcome.damage:
            new.target = new.target.with_hp(new.target.hp - outcome.damage)
        if outcome.applied_status is not None:
            # The rolled duration was being thrown away, so a slept target never woke.
            new.target = new.target.with_status(outcome.applied_status,
                                                sleep_turns=outcome.sleep_turns)
        if outcome.stat_drop is not None:
            # Flash, Screech and Charm. **Permanent**, because a wild target never switches out
            # and the ROM's stat reset runs only on the Pokemon being sent out -- which is what
            # makes six Flashes worth more than any five-turn field condition.
            new.target = apply_stat_drop(new.target, outcome.stat_drop)
        if outcome.identifies:
            # Foresight or Odor Sleuth. **Permanent, for the same reason a stat drop on a wild
            # target is**: the ROM clears `statusVolatile` only when the Pokemon leaves the field
            # and a wild one never does. So this is bought once and keeps paying -- every False
            # Swipe after it connects against a Ghost, and the target's Double Teams stop
            # mattering.
            new.target = replace(new.target, identified=True)
        if outcome.starts_charge is not None:
            new.ours = replace(new.ours, charging_slot=outcome.starts_charge)
        elif outcome.ends_charge:
            new.ours = replace(new.ours, charging_slot=None)
        if outcome.sets_nightmare:
            # Nothing in any configured party carries Nightmare; wired for symmetry with
            # `act_target`, where it is Darkrai's, so that a party move would need a moveset row
            # and nothing else.
            new.target = replace(new.target, nightmare=True)
        if outcome.starts_uproar:
            # Unreachable today -- `MODELLED_OUR_EFFECTS` omits effect 159, so
            # `unselectable_reason` refuses an Uproar of ours at the point of use and the solver
            # never offers it. Wired for the same reason Nightmare's mirror is: the asymmetry is
            # the trap, since the two halves of a turn are meant to differ only in which side
            # they read. Note what it would mean if it were reachable: our own Uproar would make
            # the target unsleepable too, which is the opposite of what a plan wants.
            new.ours = replace(new.ours, uproar_turns=outcome.starts_uproar, uproar_slot=slot)
        if outcome.resets_all_stages:
            # Haze, and it really does hit BOTH sides -- `BtlCmd_ResetAllStatChanges` loops every
            # battler. Which is the whole difficulty with the move: it undoes the target's Ancient
            # Power boosts and our own Flashes and X Sp. Defs in the same breath. The solver is
            # kept off it where that costs us (`solver.undoes_our_own_work`); the player is not,
            # because there are states where losing the accuracy work is the right trade.
            new.ours = reset_stages(new.ours)
            new.target = reset_stages(new.target)
        if outcome.starts_taunt:
            # Ours to inflict, and the live one: from here the target picks only from the slots
            # `usable_slots` still offers it, which is a narrower modulus rather than a refused
            # move. Permanent in the sense that matters -- a wild target never switches out, so
            # nothing resets it but the counter running down.
            new.target = replace(new.target, taunted_turns=outcome.starts_taunt)
        if outcome.sets_drowsy:
            new.target = replace(new.target, drowsy_turns=YAWN_DROWSY_TURNS)
        if outcome.banked_future_sight is not None:
            # A Future Sight of ours would be aimed at the TARGET, so it would need its own pair
            # of counters on the state rather than this pair. Refused rather than half-wired:
            # effect 148 is absent from `MODELLED_OUR_EFFECTS`, so this cannot be reached, and
            # pretending otherwise would bank damage against a target we are trying not to kill.
            raise NotImplementedError(
                "Future Sight on our side is not modelled; it is refused by "
                "unselectable_reason, so reaching here means that check was bypassed")
        if outcome.self_stat_raise is not None:
            new.ours = apply_stat_raise(new.ours, outcome.self_stat_raise)
        if outcome.attacker_status is not None:
            # The target's own ability paralyzed US on contact -- nothing has this yet, but the
            # path is symmetric with `act_target` and costing nothing is the point.
            new.ours = new.ours.with_status(outcome.attacker_status)
        secondary_landed = True
        if outcome.secondary and (sec := secondary_status(move)) is not None:
            # A secondary status, and Safeguard blocks one exactly as it blocks a primary: the
            # ROM's status scripts do not care which effect asked. An existing status blocks it
            # too, and that is the commoner case here -- a 30% Discharge proc against an
            # already-paralyzed Ho-Oh changes nothing, and shows nothing either, which is why the
            # verdict is carried down to `_visible_tokens` rather than only applied.
            # A victim the move FAINTED takes nothing: the roll is spent, the status script
            # never runs, and `with_hp` has already cleared what status it had -- so this has to
            # be explicit or a corpse gets re-statused.
            secondary_landed = (new.safeguard_turns <= 0
                                and not new.target.fainted
                                and new.target.status is Status.NONE)
            if secondary_landed:
                new.target = new.target.with_status(sec)
        if outcome.secondary and (drop := SECONDARY_STAT_DROPS.get(move.effect)):
            # The mirror of the same lookup in `act_target`, and it did not exist: a secondary
            # drop from one of OUR moves was applied nowhere. Nothing in a planned party has one,
            # so it cost nothing -- but the asymmetry was a trap, since the two halves of a turn
            # are meant to differ only in which side they read.
            new.target = apply_stat_drop(new.target, drop)
        if outcome.secondary and move.effect == EFFECT_ALL_STATS_UP:
            new.target = _all_stats_up(new.target)
        if outcome.secondary and move.effect in FLINCH_EFFECTS:
            flinched["E"] = True
        # Emitted AFTER the state changes above, because whether the flinch is reportable depends
        # on them: a KO or a sleep that holds hides it. See `flinch_visible`.
        #
        # A wild Pokemon always picks a move -- it has no bag -- so the only question for the
        # target as victim is whether it still has that move to take. `target_slot is None` is
        # the exception: with no PP anywhere it would Struggle, which is unmodelled, and
        # `act_target` returns without moving at all.
        parts.extend(_visible_tokens(
            outcome, move, victim=new.target,
            victim_selected_a_move=target_slot is not None,
            victim_moves_second=ours_first,
            secondary_landed=secondary_landed))
        return outcome.successful

    def act_target() -> bool:
        nonlocal rng
        if target_slot is None:
            return False
        # Symmetric with our side, and reachable: nothing in a party can start an Uproar
        # (`MODELLED_OUR_EFFECTS` omits it), but the target's OWN Uproar wakes the target too if
        # we ever slept it and it then started one -- which `will_fail` makes impossible in the
        # other order.
        new.target = _wake_for_uproar(new.target, new)
        new.target, awake = new.target.tick_sleep()
        if not awake:
            parts.append(tok.prevented_token("E", "slp"))
            return False
        if flinched["E"]:
            move_failed["E"] = True
            parts.append(tok.prevented_token("E", "fln"))
            return False
        move = new.target.move(target_slot)
        if move is None:
            return False
        if taunt_refuses(move, new.target):
            # Resolved BEFORE the paralysis check, which is why `move` is fetched above rather
            # than below it as it used to be. See the mirror of this in `act_ours`: the ROM's
            # taunt test is state 6 of the before-move walk and the paralysis roll is state 11,
            # so a taunted and paralyzed Uxie -- which is every Uxie in a real run -- spends no
            # roll at all on the turn its Yawn or Amnesia is refused.
            move_failed["E"] = True
            parts.append(tok.taunted_token("E", target_slot))
            return False
        if new.target.status is Status.PARALYSIS:
            rng, roll = advance(rng)
            new.rng_offset += 1
            if roll % 4 == 0:
                move_failed["E"] = True
                parts.append(tok.prevented_token("E", "par"))
                return False
        was_charging = new.target.charging_slot == target_slot
        # An Uproar continuation turn is the same case as a charge turn and for the same reason:
        # `Battler_CanPickCommand` is FALSE, so `ppDecremented` is set TRUE at command selection
        # and the move goes off free. Spending PP on all 3-6 turns would empty a 10-PP Uproar in
        # two uses, shrink `usable_slots` early and change the selection modulus -- a desync.
        was_locked = was_charging or (new.target.uproar_turns > 0
                                      and new.target.uproar_slot == target_slot)
        rng, outcome = execute_move(
            rng, move, new.target, new.ours, actor="E", slot=target_slot, field=new)
        new.rng_offset += outcome.rolls
        # **PP is spent on the charge turn only.** The ROM marks `ppDecremented` TRUE for a
        # battler that cannot pick a command [battle_controller_player.c:334-336], so the turn
        # Shadow Force fires costs no PP. Spending it twice would empty a 5-PP move in two uses,
        # shrink `usable_slots` early and change the selection modulus -- a desync, not a
        # rounding error.
        if not was_locked:
            new.target = new.target.spend_pp(target_slot, 1)
        if outcome.starts_charge is not None:
            new.target = replace(new.target, charging_slot=outcome.starts_charge)
        elif outcome.ends_charge:
            new.target = replace(new.target, charging_slot=None)
        apply_field(outcome)
        if outcome.damage:
            new.ours = new.ours.with_hp(new.ours.hp - outcome.damage)
        if outcome.secondary and (drop := SECONDARY_STAT_DROPS.get(move.effect)):
            # Aurora Beam's Attack, Mist Ball's Sp. Atk, Luster Purge's Sp. Def, Crunch's
            # Defence. One lookup where there were three branches in two places: each drop
            # reaches the damage calculation the same way every other stage does, and none of
            # them is inert -- our own damage is what brings the target to 1 HP.
            new.ours = apply_stat_drop(new.ours, drop)
        if outcome.applied_status is not None:
            # Hypnosis. **This branch did not exist before Darkrai**, and its absence was the
            # exact failure `MODELLED_TARGET_EFFECTS` guards against: the duration roll was spent
            # and the sleep dropped on the floor, so the simulator would have had us attacking
            # through turns the game had us asleep for -- every prediction after the first
            # Hypnosis wrong, with no contradiction raised. Nothing fired it until now only
            # because no configured target had a status move.
            new.ours = new.ours.with_status(outcome.applied_status,
                                            sleep_turns=outcome.sleep_turns)
        if outcome.identifies:
            # The mirror, and unreachable: no configured target has Foresight or Odor Sleuth.
            # Wired for the same reason Nightmare's and Taunt's mirrors are -- the two halves of a
            # turn are meant to differ only in which side they read. Aimed at us it would be
            # escapable, which it is not in the other direction: `sent_out` clears the flag, so
            # switching sheds it exactly as it sheds a Yawn -- and the target, which never
            # switches, has no such way out.
            new.ours = replace(new.ours, identified=True)
        if outcome.sets_nightmare:
            new.ours = replace(new.ours, nightmare=True)
        if outcome.starts_uproar:
            # The lock goes on the TARGET -- it is the user. From here it picks no move and
            # spends no PP until the counter runs out (`select_target_move`).
            new.target = replace(new.target, uproar_turns=outcome.starts_uproar,
                                 uproar_slot=target_slot)
        if outcome.resets_all_stages:
            # Symmetric, and unreachable: no configured target has Haze. Worth noting what it
            # would mean if one did -- it would wipe our Flash investment on its own turn, with
            # nothing we could do about it.
            new.ours = reset_stages(new.ours)
            new.target = reset_stages(new.target)
        if outcome.starts_taunt:
            # Unreachable: Taunt is in no configured target's moveset. Wired for the same reason
            # Nightmare's mirror is -- the two halves of a turn are meant to differ only in which
            # side they read. Note what it would mean: OUR status moves would stop being
            # selectable, which includes the paralyzer the whole run is built on.
            new.ours = replace(new.ours, taunted_turns=outcome.starts_taunt)
        if outcome.sets_drowsy:
            # Uxie's Yawn, aimed at us. `will_fail` has already refused every case the ROM
            # refuses, so reaching here means the counter really is being set.
            new.ours = replace(new.ours, drowsy_turns=YAWN_DROWSY_TURNS)
        if outcome.banked_future_sight is not None:
            # On the STATE, not on us: the ROM indexes it by battler position, so switching
            # somebody else in does not dodge it -- see `BattleState.future_sight_turns`.
            new.future_sight_turns = FUTURE_SIGHT_TURNS
            new.future_sight_damage = outcome.banked_future_sight
            new.future_sight_move = move.name
        if outcome.self_stat_raise is not None:
            # Double Team raises the TARGET's own evasion, which is why this reads
            # `new.target`: it degrades our accuracy for the rest of the battle, and permanently
            # -- a wild Pokemon never switches out, so nothing ever resets it.
            new.target = apply_stat_raise(new.target, outcome.self_stat_raise)
        if outcome.stat_drop is not None:
            # No configured target has a primary stat-drop move; wired anyway so that adding one
            # is a row in `PRIMARY_STAT_DROPS` and nothing else. Our own Mist would guard this,
            # and nothing in the party can set Mist.
            new.ours = apply_stat_drop(new.ours, outcome.stat_drop)
        if outcome.attacker_status is not None:
            # Static. The target hit a Static holder of ours with a contact move and got
            # paralyzed for it -- an unplanned route to the Phase 2 precondition, and the reason
            # the roll has to be spent in the right places and nowhere else.
            new.target = new.target.with_status(outcome.attacker_status)
        secondary_landed = True
        if outcome.secondary and (sec := secondary_status(move)) is not None:
            # Sacred Fire's burn is the live case, and the one that made this worth getting right:
            # once Ampharos is burned, every later proc is invisible. No Safeguard check on this
            # side -- Safeguard is the TARGET's side condition (nothing in any party can set one),
            # so a status aimed at us is never blocked by it.
            secondary_landed = not new.ours.fainted and new.ours.status is Status.NONE
            if secondary_landed:
                new.ours = new.ours.with_status(sec)
        if outcome.secondary and move.effect == EFFECT_ALL_STATS_UP:
            # Ancient Power boosts the ATTACKER, so the target's own stats -- including the Speed
            # that the no-speed-tie guarantee depends on.
            new.target = _all_stats_up(new.target)
        if outcome.secondary and move.effect in FLINCH_EFFECTS:
            flinched["M"] = True
        # Our side is the one with a bag, so both halves of the rule do work here. A flinch on
        # us shows only if we SELECTED A MOVE and are moving second: an item, either ball, a
        # switch or a Revive resolves before any move, so we have already had our turn and there
        # is no move left to flinch -- and `Action.FAINTED` says outright that we never got one
        # off. `move_slot` is None for every one of those.
        parts.extend(_visible_tokens(
            outcome, move, victim=new.ours,
            victim_selected_a_move=action.move_slot is not None,
            victim_moves_second=not ours_first,
            secondary_landed=secondary_landed))
        return outcome.successful

    def battle_halted() -> bool:
        """Whether the battle itself has stopped, as opposed to our Pokemon going down.

        Deliberately not ``new.over``: our Pokemon fainting shortens the rest of the turn but
        does not end it, and the replacement comes in once the turn finishes. A capture (either
        ball) or the target fainting really does stop everything there.
        """
        return new.captured or new.captured_in_wrong_ball or new.target.fainted

    first, second = (act_ours, act_target) if ours_first else (act_target, act_ours)
    if first():
        for _ in range(turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES):
            rng = advance_rng(rng)
        new.rng_offset += turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES

    # A faint *before* we moved takes our whole half of the turn with it -- the between-turn
    # advances included [verified, notes/ss_rng/fainting.md]. Which is only possible when the
    # target moved first, since otherwise we had already acted.
    fainted_before_moving = new.ours.fainted and not ours_first
    if not battle_halted() and not fainted_before_moving:
        for _ in range(turn_costs.BETWEEN_TURN_ADVANCES):
            rng = advance_rng(rng)
        new.rng_offset += turn_costs.BETWEEN_TURN_ADVANCES
        if second():
            for _ in range(turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES):
                rng = advance_rng(rng)
            new.rng_offset += turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES

    #: Whether a MOVE put us down, as opposed to an end-of-turn residual. The distinction decides
    #: how much the end-of-turn block costs -- a move-faint shortens it, a residual faint does not
    #: (`turn_costs.END_OF_TURN_ADVANCES_FAINTED_BY_RESIDUAL`) -- and it has to be captured here
    #: because the residual block now runs FIRST and would otherwise answer for both.
    fainted_by_move = new.ours.fainted

    # Burn's residual, which is a RESIDUAL in the sense that matters here: deterministic, free of
    # RNG, and therefore not reported. `hp_before` is deliberately NOT moved by it, so the HP
    # token still describes only what the turn did randomly -- and on a turn where something
    # random also landed, the one token reports the total including the tick.
    #
    # Leftovers' recovery is the other half of the same block, and it goes FIRST -- see
    # `leftovers_tick` for the ROM's ordering. `residual` is the NET deterministic change with
    # damage positive, so a healing turn simply makes it negative and the HP-token comparison
    # below keeps working unchanged.
    residual = 0
    if not battle_halted() and not new.ours.fainted:
        # Measured rather than predicted: both figures are clamped by `with_hp`, so a recovery
        # that tops us off restores LESS than max HP / 16 and a predicted total would then demand
        # an HP token on a turn where nothing random happened at all.
        hp_at_block = new.ours.hp
        recovery = leftovers_tick(new.ours)
        if recovery:
            new.ours = new.ours.with_hp(new.ours.hp + recovery)
        if new.ours.status is Status.BURN:
            new.ours = new.ours.with_hp(new.ours.hp - burn_tick(new.ours))
        # Leftovers -> burn -> Nightmare -> Bad Dreams, which is the ROM's own order:
        # MON_COND_CHECK_STATE_LEFTOVERS, _BURN, _NIGHTMARE then _BAD_DREAMS
        # [src/battle/battle_controller_player.c:1259-1272]. Order matters here even though none
        # of the four spends a roll, because each is clamped at 0 and the one that reaches it
        # first is the one that faints us.
        nightmare = nightmare_tick(new.ours)
        if nightmare:
            new.ours = new.ours.with_hp(new.ours.hp - nightmare)
        elif new.ours.nightmare and new.ours.status is not Status.SLEEP:
            # Awake, so the flag is cleared with no damage -- the ROM's `else` branch on the same
            # case. Waking up really is the cure, and leaving the flag set would re-nightmare us
            # the next time anything put us to sleep.
            new.ours = replace(new.ours, nightmare=False)
        dreams = bad_dreams_tick(
            new.ours, opponent_has_bad_dreams=config.target_has_bad_dreams)
        if dreams:
            new.ours = new.ours.with_hp(new.ours.hp - dreams)
        residual = hp_at_block - new.ours.hp

    #: Rolled sleep duration when Yawn's counter expired into sleep this turn, else 0. The roll
    #: is spent inside the end-of-turn block below, and the status is applied after it -- Yawn is
    #: state 24 of the condition walk and Nightmare and Bad Dreams are states 9 and 12, so both
    #: of those have already ticked on a victim that was still awake.
    drowsy_sleep_turns = 0
    #: Whether a Future Sight landed, missed, or was not in the air at all (None).
    future_sight_hit: bool | None = None
    if not battle_halted():
        # The end-of-turn block shrinks when a MOVE faints us: 4 -> 3 before we moved, 4 -> 2
        # after. Getting this wrong would not show up on the faint turn, which the X token
        # explains on its own -- it would desynchronise every turn after it. A faint to a
        # RESIDUAL spends the full four, which is why the test is `fainted_by_move`.
        if not fainted_by_move:
            end_of_turn = turn_costs.END_OF_TURN_ADVANCES
        elif fainted_before_moving:
            end_of_turn = turn_costs.END_OF_TURN_ADVANCES_FAINTED_BEFORE_MOVING
        else:
            end_of_turn = turn_costs.END_OF_TURN_ADVANCES_FAINTED_AFTER_MOVING
        # Split around the conditional rolls rather than spent in one run, because two of the
        # end-of-turn condition states can spend a roll of their own -- see
        # `_END_OF_TURN_RESIDUAL_ANCHOR` for what is measured here and what is still owed.
        # `min` rather than the constant so a faint-shortened block degrades instead of
        # over-advancing.
        head = min(_END_OF_TURN_RESIDUAL_ANCHOR, end_of_turn)
        for _ in range(head):
            rng = advance_rng(rng)
        new.rng_offset += head
        # Uproar, state 14: it wakes before it counts down, and a turn on which it woke somebody
        # does not count down at all.
        _tick_uproar(new, move_failed)
        # Taunt, state 20. Spends nothing, which is why it needs no anchor of its own.
        _tick_taunt(new)
        # Yawn, state 24.
        rng, spent, drowsy_sleep_turns = _tick_drowsy(rng, new)
        new.rng_offset += spent
        # Future Sight, the first state of the side-condition walk that follows. It is checked
        # against our HP *after* the residual block above, which is the ROM's order and the
        # reason that block was moved here: `--futureSightTurns[battler] == FALSE &&
        # battleMons[battler].curHP` means a burn tick that faints us stops the Future Sight
        # firing at all, so the roll is not spent and the token is not emitted.
        rng, spent, future_sight_hit = _roll_future_sight(rng, new)
        new.rng_offset += spent
        for _ in range(end_of_turn - head):
            rng = advance_rng(rng)
        new.rng_offset += end_of_turn - head

    # Durations tick at end of turn: rain set this turn shows "Rain continues to fall" on the
    # same turn and stops four turns later [verified: test1.jsonl].
    if not battle_halted():
        new.rain_turns = max(0, new.rain_turns - 1)
        new.mist_turns = max(0, new.mist_turns - 1)
        new.safeguard_turns = max(0, new.safeguard_turns - 1)
        new.reflect_turns = max(0, new.reflect_turns - 1)
        new.light_screen_turns = max(0, new.light_screen_turns - 1)


    # Yawn's sleep lands here, after every HP residual, because state 24 comes after states 9 and
    # 12 -- so the Nightmare and Bad Dreams ticks above ran against a victim that was still
    # awake, and the first turn this sleep costs is the next one. The roll was already spent.
    if drowsy_sleep_turns and not battle_halted() and not new.ours.fainted:
        new.ours = new.ours.with_status(Status.SLEEP, sleep_turns=drowsy_sleep_turns)

    # The Future Sight, last of all, and NOT folded into `residual`: its hit check is a real
    # random verdict, so the HP it takes has to show up as a change the HP token reports. Folding
    # it in would hide the one observable event either of these targets offers.
    if future_sight_hit is not None:
        parts.append(tok.future_sight_token(future_sight_hit))
        if future_sight_hit and not new.ours.fainted:
            new.ours = new.ours.with_hp(new.ours.hp - new.future_sight_damage)
        new.future_sight_damage = 0

    # HP, then the faint. A faint turn carries no HP token at all: zero is implied by the X, and
    # once the replacement is out the number would describe a different Pokemon.
    if new.ours.fainted:
        new.faints += 1
        parts.append(_send_out(new, replacement))
    elif new.ours.hp != hp_before - residual:
        # Compared against the post-residual figure, so a turn whose ONLY change was the tick
        # emits nothing while a turn that also took a hit still reports the real number.
        parts.append(tok.hp_token(new.ours.hp))
    new.rng = rng
    new.turn += 1
    new.log.append(tuple(parts))
    return new


def _send_out(state: BattleState, replacement: int | None) -> str:
    """Replace our fainted Pokemon, returning the ``X`` token for it. Costs no advances.

    `replacement` is a **party slot**, not a bench index -- unlike `bench_slot`, which names a
    position among whoever is currently benched. The difference matters on the one turn where it
    can: a switch resolves before any move, so a turn that switches *and then* faints has already
    rearranged the bench by the time this runs, and an index the page computed beforehand would
    name the wrong Pokemon. A party slot cannot go stale.

    It is a *reported* fact rather than something the simulator can decide -- which party member
    the player sent out is their choice. Optional all the same, because a prediction sweep
    (`identify.Session.rank_actions`) asks every candidate what every action would do and most of
    those candidates do not faint at all; defaulting to the first one still standing keeps that
    sweep working. A real report always passes it, so the default never decides a token the
    player can see.
    """
    healthy = state.healthy_bench
    if not healthy:
        return tok.WIPED                     # the party is wiped; nothing follows this
    index = next((i for i in healthy
                  if party_number(state.bench[i], i) == replacement), healthy[0])
    incoming = sent_out(state.bench[index])
    state.bench = party_order(
        tuple(b for i, b in enumerate(state.bench) if i != index)
        + (replace(state.ours, choice_locked_slot=None),))
    state.ours = incoming
    # A replacement Intimidates exactly as a voluntary switch-in does -- this is a send-out, and
    # `intimidateFlag` is cleared per send-out. Free of advances, so it cannot disturb the
    # end-of-turn counts this runs inside.
    state.target = _apply_intimidate(incoming, state.target)
    return tok.faint_token(party_number(incoming, index))


def simulate(state: BattleState, actions: list[Action], config: HuntConfig) -> BattleState:
    """Several turns in sequence, stopping early if the battle ends."""
    for action in actions:
        if state.over:
            break
        state = simulate_turn(state, action, config)
    return state
