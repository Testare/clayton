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
    apply_stage, damage, item_key, unsupported_attacker_reason, unsupported_reason,
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
    210: "Water Sport: a per-battler volatile flag, so a second one fails",
    245: "Punishment: power computed from our positive stages (`punishment_power`)",
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
    58: "lowers the target's Attack by two (Charm)",
    59: "lowers the target's Defence by two (Screech)",
    60: "lowers the target's Speed by two (Scary Face)",
    62: "lowers the target's Sp. Def by two (Fake Tears, Metal Sound)",
    65: "Reflect: halves physical damage, and a second one fails",
    67: "paralyzes (Thunder Wave)",
    76: "may confuse (Signal Beam) -- the proc roll only; confusion ON THE TARGET is inert here",
    101: "False Swipe: damage that cannot take the target below 1 HP",
    106: "Mean Look: traps, and a second one fails",
    125: "may burn -- as effect 4",
    136: "Rain Dance: field condition and the weather term",
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


def unselectable_reason(move: Move) -> str | None:
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


def unsupported_our_moves(moves) -> tuple[tuple[str, str], ...]:
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
        reason = unselectable_reason(move)
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
    #: ``(stage field, stages)`` this move drops on its target, or None. Applied by
    #: `simulate_turn`, which owns the state -- and which knows which side the target is.
    stat_drop: tuple[str, int] | None = None
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
    #: ``(stage field, stages)`` this move raises on its OWN USER -- Double Team's evasion. The
    #: mirror of `stat_drop`, and a separate field for the same reason `attacker_status` is: the
    #: side it lands on is the opposite one, and `simulate_turn` is what knows which side that is.
    self_stat_raise: tuple[str, int] | None = None
    #: True when Mist blocked the stat drop. The move still counts as SUCCESSFUL -- verified on
    #: turn 15 of test1.jsonl, which spent its post-successful-move advances anyway.
    blocked_by_mist: bool = False


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
    rolls = 1 if move.accuracy > 0 else 0
    if move.category != CATEGORY_STATUS:
        rolls += 2
    if move.effect_chance > 0:
        rolls += 1
    if status_applied_by(move) is Status.SLEEP:
        rolls += 1
    return rolls


def accuracy_net_stage(attacker: "Battler", defender: "Battler") -> int:
    """The single stage the accuracy check uses: the attacker's accuracy minus the defender's
    evasion, clamped to -6..+6. Combining them is what the game does, and keeping it in one
    function is what stops the simulator and the interview disagreeing about it.
    """
    return max(-6, min(6, attacker.accuracy_stage - defender.evasion_stage))


def _effective_accuracy(move: Move, net_stage: int = 0, *, attacker=None,
                        defender=None) -> int:
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
    accuracy = apply_accuracy_stage(move.accuracy, net_stage)
    return apply_accuracy_items(
        accuracy,
        defender_item=getattr(defender, "held_item", "") or "",
        attacker_item=getattr(attacker, "held_item", "") or "")


def can_miss(move: Move, net_stage: int = 0, *, attacker=None, defender=None) -> bool:
    """Whether an accuracy roll can actually fail.

    Accuracy 0 bypasses the check, and accuracy 100 at a neutral or positive stage passes it
    always -- ``roll % 100 < 100`` can never be false -- so neither can miss. But this is
    stage-dependent, not a property of the move: Spore at 100% becomes missable as soon as our
    accuracy is dropped or the target's evasion is raised, and reporting it as unmissable then
    would suppress a legitimate "missed".

    It is also ITEM-dependent, which is the newer half: a Brightpowder on the target makes a
    100-accuracy Spore missable at a neutral stage, so an interview that did not know about the
    item would refuse to let the player report a miss that really happened.
    """
    return 0 < _effective_accuracy(move, net_stage, attacker=attacker, defender=defender) < 100


def will_fail(move: Move, defender: "Battler", field=None, *, actor: "Battler" = None) -> bool:
    """Whether this move is certain to do nothing, from state alone.

    Five families now, all costing the turn its two post-successful-move advances when they fire
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
    if status is not None and immune_to_status(defender, status):
        # Insomnia and Vital Spirit, checked at the very top of `subscript_fall_asleep` and
        # landing on the same no-more-work flag as "is already asleep" -- so the cost is the
        # same as that verified failure's.
        return True
    if move.effect == EFFECT_NIGHTMARE:
        # Fails against anything not asleep, and against a second application
        # [effect_script_0107.s]. The first half is the one that fires in a real run: Darkrai
        # cannot sequence its own moves, so it throws Nightmare at a wide-awake party member
        # roughly a quarter of the turns it acts.
        return defender.status is not Status.SLEEP or defender.nightmare
    if move.effect == EFFECT_EVASION_UP:
        # A stat already at +6 cannot go higher, and the move fails outright rather than landing
        # for nothing -- which is an advance difference, not a cosmetic one.
        # Self-targeting, so it reads `actor` the way Refresh does -- and no actor means "cannot
        # tell" rather than a guess about the defender's stages.
        return actor is not None and actor.evasion_stage >= STAT_STAGE_CEILING
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
#: Aurora Beam's Attack drop and Mist Ball's Sp. Atk drop. Separate, because the stats are: one
#: figure used to stand for both, so an Attack drop lowered Sp. Atk as well.
EFFECT_LOWER_ATTACK = 68
EFFECT_LOWER_SPATK = 71
#: Luster Purge drops Sp. DEF, which is not the same thing at all: our Sp. Def is what the
#: target's special attacks are divided by, so a drop raises every later special hit. Mist Ball's
#: Sp. Atk drop is the one that only touches damage we deal.
EFFECT_LOWER_SPDEF = 72
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
#: Shadow Force. A two-turn move: turn 1 vanishes and spends NOTHING, turn 2 is an ordinary
#: damaging move [res/battle/scripts/effects/effect_script_0272.s].
EFFECT_SHADOW_FORCE = 272
#: Effects whose charge turn makes their user untouchable. Only Shadow Force is in any configured
#: moveset; Fly (19), Dig (39) and Dive (256) belong here the day a target has one, and the ROM
#: tests all four in the same condition (`CheckMoveHitOverrides`).
SEMI_INVULNERABLE_EFFECTS = frozenset({EFFECT_SHADOW_FORCE})


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

    Three routes, all of them real for some configured target: a move whose PRIMARY effect is
    the status (Thunder Wave, Spore), a move whose SECONDARY is (Discharge, Sacred Fire), and
    the holder's own ability firing on contact (Static).

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
# Distinct from the three SECONDARY drops (effects 68, 71, 72), which ride on a damaging move and
# are applied off `outcome.secondary`. These are the move's whole purpose, so they land whenever
# it succeeds.
#: effect id -> (`Battler` stage field, how many stages it drops)
PRIMARY_STAT_DROPS: dict[int, tuple[str, int]] = {
    18: ("atk_stage", 1),        # Growl
    19: ("def_stage", 1),        # Tail Whip, Leer
    20: ("speed_stage", 1),      # String Shot
    23: ("accuracy_stage", 1),   # Flash, Sand Attack, Kinesis
    24: ("evasion_stage", 1),    # Sweet Scent
    58: ("atk_stage", 2),        # Charm, Feather Dance
    59: ("def_stage", 2),        # Screech
    60: ("speed_stage", 2),      # Scary Face
    62: ("spdef_stage", 2),      # Fake Tears, Metal Sound
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


def primary_stat_drop(move: Move) -> tuple[str, int] | None:
    """``(stage field, stages)`` this status move drops on its target, or None."""
    return PRIMARY_STAT_DROPS.get(move.effect)


def apply_stat_drop(battler: Battler, drop: tuple[str, int]) -> Battler:
    """`battler` with `drop` applied, clamped at the -6 floor.

    **Clamped rather than refused.** A drop against a stat already at -6 does nothing, and the
    player reports that it does not change the turn's roll count either -- so unlike the field
    conditions it is NOT a `will_fail` case, and Flash stays a usable filler action all the way
    down. Worth a ground-truth capture if it ever becomes load-bearing; for now the clamp is the
    whole of it.
    """
    field, stages = drop
    current = getattr(battler, field)
    return replace(battler, **{field: max(STAT_STAGE_FLOOR, current - stages)})


def apply_stat_raise(battler: Battler, raise_: tuple[str, int]) -> Battler:
    """`battler` with `raise_` applied to its own stage, clamped at the +6 ceiling.

    The mirror of `apply_stat_drop`, with one asymmetry worth stating: a raise at the ceiling
    really does make the move FAIL (`will_fail`), so the clamp here is belt-and-braces rather
    than the rule -- where a drop at the floor merely does nothing and keeps costing a full turn.

    **Permanent.** A wild target never switches out, so the ROM's stat reset never runs on it:
    every Double Team Darkrai gets off is one our 100%-accuracy moves keep paying for.
    """
    field, stages = raise_
    current = getattr(battler, field)
    return replace(battler, **{field: min(STAT_STAGE_CEILING, current + stages)})


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
INTIMIDATE_DROP = ("atk_stage", 1)
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
        if hit and is_semi_invulnerable(defender):
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
            applied_status=status, sleep_turns=sleep_turns,
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
            # Double Team. Mist does not guard against it -- Mist blocks REDUCTIONS to its own
            # side, and this is the user raising its own stage.
            self_stat_raise=(("evasion_stage", 1) if move.effect == EFFECT_EVASION_UP else None),
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
    # reach something that is not there.
    if is_semi_invulnerable(defender):
        hit = False
    if not hit:
        parts.append(tok.MISS)
        # The lock comes off even on a miss: the effect script's cleanup (`_055`) is fallen
        # through to from the fire branch, and the hit verdict is decided after the script runs.
        return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=False,
                                ends_charge=attacker.charging_slot == slot)
    parts.append(tok.CRIT if critical else tok.HIT)

    dealt = 0
    # Atk and SpA stages read off the attacker SEPARATELY. One figure used to be passed as both,
    # so an Aurora Beam Attack drop was silently applied to Sp. Atk too -- and it is also the
    # attacker's own Battler now rather than a parameter, which is what lets the TARGET's own
    # boosts (Ancient Power) reach the damage it deals us.
    #
    # Burn halves the holder's physical Attack, and that matters in both directions: it is also
    # how many more False Swipes a burned Smeargle needs before the target reaches 1 HP.
    attack_stage = attacker.atk_stage
    attack = attacker.stats["atk"]
    if attacker.status is Status.BURN:
        attack = max(1, attack // BURN_ATTACK_DIVISOR)
    attacker_side = Attacker(
        level=attacker.level, attack=attack,
        special_attack=attacker.stats["spa"], types=attacker.types,
        attack_stage=attack_stage, special_attack_stage=attacker.spatk_stage,
        ability=attacker.ability, held_item=attacker.held_item)
    base_power = variable_base_power(move, defender)
    if (unsupported_reason(move, power_known=base_power is not None) is None
            and unsupported_attacker_reason(attacker_side) is None):
        physical = move.category != 1
        dealt = damage(
            move,
            attacker_side,
            Defender(defence=defender.stats["def"], special_defence=defender.stats["spd"],
                     types=defender.types, defence_stage=defender.def_stage,
                     special_defence_stage=defender.spdef_stage,
                     # Only Levitate is read, and only as a Ground immunity. It reaches the
                     # calculation at all because the target's Battler now carries its encounter's
                     # ability, and Giratina Origin's is Levitate.
                     ability=defender.ability),
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
        secondary = proc_roll % 100 < move.effect_chance
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
    return replace(battler, atk_stage=0, def_stage=0, spatk_stage=0, spdef_stage=0,
                   speed_stage=0, accuracy_stage=0, evasion_stage=0)


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

    One roll per turn **except while the target is locked into a multi-turn move**, and the
    modulus shrinks as PP runs out — so its entropy decays from 2.00
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
    rng, target_slot = select_target_move(rng, new.target)
    if target_slot is not None:
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
        new.ours, awake = new.ours.tick_sleep()
        if not awake:
            parts.append(tok.prevented_token("M", "slp"))
            return False
        if flinched["M"]:
            parts.append(tok.prevented_token("M", "fln"))
            return False
        if new.ours.status is Status.PARALYSIS:
            # R7 residual: a paralysis check costs one roll, as metronome_compass models it.
            rng, roll = advance(rng)
            new.rng_offset += 1
            if roll % 4 == 0:
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
        if outcome.starts_charge is not None:
            new.ours = replace(new.ours, charging_slot=outcome.starts_charge)
        elif outcome.ends_charge:
            new.ours = replace(new.ours, charging_slot=None)
        if outcome.sets_nightmare:
            # Nothing in any configured party carries Nightmare; wired for symmetry with
            # `act_target`, where it is Darkrai's, so that a party move would need a moveset row
            # and nothing else.
            new.target = replace(new.target, nightmare=True)
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
        new.target, awake = new.target.tick_sleep()
        if not awake:
            parts.append(tok.prevented_token("E", "slp"))
            return False
        if flinched["E"]:
            parts.append(tok.prevented_token("E", "fln"))
            return False
        if new.target.status is Status.PARALYSIS:
            rng, roll = advance(rng)
            new.rng_offset += 1
            if roll % 4 == 0:
                parts.append(tok.prevented_token("E", "par"))
                return False
        move = new.target.move(target_slot)
        if move is None:
            return False
        was_charging = new.target.charging_slot == target_slot
        rng, outcome = execute_move(
            rng, move, new.target, new.ours, actor="E", slot=target_slot, field=new)
        new.rng_offset += outcome.rolls
        # **PP is spent on the charge turn only.** The ROM marks `ppDecremented` TRUE for a
        # battler that cannot pick a command [battle_controller_player.c:334-336], so the turn
        # Shadow Force fires costs no PP. Spending it twice would empty a 5-PP move in two uses,
        # shrink `usable_slots` early and change the selection modulus -- a desync, not a
        # rounding error.
        if not was_charging:
            new.target = new.target.spend_pp(target_slot, 1)
        if outcome.starts_charge is not None:
            new.target = replace(new.target, charging_slot=outcome.starts_charge)
        elif outcome.ends_charge:
            new.target = replace(new.target, charging_slot=None)
        apply_field(outcome)
        if outcome.damage:
            new.ours = new.ours.with_hp(new.ours.hp - outcome.damage)
        if outcome.secondary and move.effect == EFFECT_LOWER_ATTACK:
            # Aurora Beam: our ATTACK only. Held on the Battler now, so it reaches the damage
            # calculation the same way every other stage does.
            new.ours = replace(new.ours, atk_stage=max(-6, new.ours.atk_stage - 1))
        if outcome.secondary and move.effect == EFFECT_LOWER_SPATK:
            # Mist Ball drops Sp. Atk, which is not inert: our special damage is what some
            # parties use to bring the target down.
            new.ours = replace(new.ours, spatk_stage=max(-6, new.ours.spatk_stage - 1))
        if outcome.applied_status is not None:
            # Hypnosis. **This branch did not exist before Darkrai**, and its absence was the
            # exact failure `MODELLED_TARGET_EFFECTS` guards against: the duration roll was spent
            # and the sleep dropped on the floor, so the simulator would have had us attacking
            # through turns the game had us asleep for -- every prediction after the first
            # Hypnosis wrong, with no contradiction raised. Nothing fired it until now only
            # because no configured target had a status move.
            new.ours = new.ours.with_status(outcome.applied_status,
                                            sleep_turns=outcome.sleep_turns)
        if outcome.sets_nightmare:
            new.ours = replace(new.ours, nightmare=True)
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
        if outcome.secondary and move.effect == EFFECT_LOWER_SPDEF:
            # Luster Purge drops our Sp. DEF, raising every later special hit we take. Latios
            # was already a configured target with this unmodelled, so the model under-predicted
            # incoming damage from the first proc (clayton-957.26.1).
            new.ours = replace(new.ours, spdef_stage=max(-6, new.ours.spdef_stage - 1))
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

    if not battle_halted():
        # The end-of-turn block shrinks when a MOVE faints us: 4 -> 3 before we moved, 4 -> 2
        # after. Getting this wrong would not show up on the faint turn, which the X token
        # explains on its own -- it would desynchronise every turn after it.
        if not new.ours.fainted:
            end_of_turn = turn_costs.END_OF_TURN_ADVANCES
        elif fainted_before_moving:
            end_of_turn = turn_costs.END_OF_TURN_ADVANCES_FAINTED_BEFORE_MOVING
        else:
            end_of_turn = turn_costs.END_OF_TURN_ADVANCES_FAINTED_AFTER_MOVING
        for _ in range(end_of_turn):
            rng = advance_rng(rng)
        new.rng_offset += end_of_turn

    # Durations tick at end of turn: rain set this turn shows "Rain continues to fall" on the
    # same turn and stops four turns later [verified: test1.jsonl].
    if not battle_halted():
        new.rain_turns = max(0, new.rain_turns - 1)
        new.mist_turns = max(0, new.mist_turns - 1)
        new.safeguard_turns = max(0, new.safeguard_turns - 1)
        new.reflect_turns = max(0, new.reflect_turns - 1)
        new.light_screen_turns = max(0, new.light_screen_turns - 1)

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
