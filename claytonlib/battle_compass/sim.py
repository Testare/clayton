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

from dataclasses import dataclass, replace

from claytonlib.battle import turn as turn_costs
from claytonlib.battle.catch import (
    BALL_POKE, SHAKES_TO_CAPTURE, catch_value, fast_ball_catch_rate, is_guaranteed,
    shake_threshold, shakes_for_rolls,
)
from claytonlib.battle.damage import (
    Attacker, Defender, damage, unsupported_attacker_reason, unsupported_reason,
)
from claytonlib.battle.readiness import PARALYSIS_SPEED_FACTOR
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


def can_flinch(battler) -> bool:
    """Whether any of `battler`'s known moves can make the other side flinch."""
    return any((m := battler.move(slot)) is not None and m.effect in FLINCH_EFFECTS
               for slot in range(len(battler.moves)))


def flinch_visible(victim: "Battler", *, victim_still_to_move: bool) -> bool:
    """Whether a flinch inflicted on `victim` is observable at all.

    A flinch lasts only the turn it is inflicted and announces itself only when the victim
    *tries* to move -- so unlike every other secondary effect, a procced flinch can leave no
    trace whatsoever. Three ways it does:

    * **The flincher moved second.** The victim has already taken its turn, so the flinch flag is
      set on a Pokemon that will never check it, and the game says nothing. This is the case this
      function was written for: a Zen Headbutt that goes second cannot be reported, so the
      interview must not ask and the ``~`` token must not appear in the path.
    * **The flinch came with a KO.** A fainted victim never reaches its turn.
    * **The victim is asleep and staying asleep.** Sleep is checked before flinch (the verified
      order is sleep -> freeze -> flinch -> confusion -> paralysis), so "is fast asleep" is the
      message shown and the flinch is masked. Paralysis is *not* on this list, and deliberately:
      it is checked after flinch, so a flinched-and-paralyzed victim reports the flinch.

    The proc roll is spent either way -- it belongs to the flincher's own move, through
    ``effect_chance`` -- so suppressing the token costs the turn no advances. It costs
    *information*: an invisible flinch is one the candidate set cannot be filtered on. That is
    the correct trade, because the alternative is filtering on an answer the player is guessing.
    """
    if not victim_still_to_move or victim.fainted:
        return False
    return not (victim.status is Status.SLEEP and victim.sleep_turns > 1)


#: Crit modifiers by stage; a crit lands when ``roll % modifier == 0``.
CRIT_MODIFIERS = (16, 8, 4, 3, 2)
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


def _effective_accuracy(move: Move, net_stage: int = 0) -> int:
    """Accuracy after the combined accuracy/evasion stage.

    0 means the move bypasses the check entirely. `net_stage` is the attacker's accuracy stage
    minus the defender's evasion stage -- NOT evasion alone, since an accuracy drop on the
    attacker makes a 100%-accuracy move missable just as a raised evasion does.
    """
    if move.accuracy == 0:
        return 0
    net = max(-6, min(6, net_stage))
    if net >= 0:
        return move.accuracy * (3 + net) // 3
    return move.accuracy * 3 // (3 - net)


def can_miss(move: Move, net_stage: int = 0) -> bool:
    """Whether an accuracy roll can actually fail.

    Accuracy 0 bypasses the check, and accuracy 100 at a neutral or positive stage passes it
    always -- ``roll % 100 < 100`` can never be false -- so neither can miss. But this is
    stage-dependent, not a property of the move: Spore at 100% becomes missable as soon as our
    accuracy is dropped or the target's evasion is raised, and reporting it as unmissable then
    would suppress a legitimate "missed".
    """
    return 0 < _effective_accuracy(move, net_stage) < 100


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
    return False


#: Effect ids whose move fails outright when the condition it sets is already in place. Every
#: such failure costs the turn its two post-successful-move advances, which is exactly how the
#: emulator log (data/battle_logs/test1.jsonl) diverged from this simulator on turn 3: Suicune
#: re-used Rain Dance while it was already raining, the game spent 17 advances, and this spent 19.
EFFECT_RAIN_DANCE = 136
EFFECT_MIST = 46
EFFECT_MEAN_LOOK = 106
EFFECT_LOWER_EVASION = 24
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


def status_applied_by(move: Move) -> Status | None:
    """The non-volatile status this move inflicts, if any.

    Public because the interview needs it too: a status our move lands takes effect BEFORE the
    target's half of the same turn, and the snapshot's prevention options are read off the turn's
    opening state, so the page has to add "is asleep" itself once Spore connects.
    """
    return {1: Status.SLEEP, 67: Status.PARALYSIS}.get(move.effect)


def execute_move(rng: int, move: Move, attacker: Battler, defender: Battler, *,
                 actor: str, slot: int, net_stage: int | None = None,
                 attack_stage: int = 0, field=None) -> tuple[int, MoveOutcome]:
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

    if move.category == CATEGORY_STATUS:
        hit = True
        if move.accuracy > 0:
            rng, roll = advance(rng)
            used += 1
            hit = roll % 100 < _effective_accuracy(move, net_stage)
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
        # Mist guards its own side's stats. The move still executed, so it stays SUCCESSFUL and
        # still spends the post-move advances [verified: test1.jsonl turn 15 spent 8 skeleton
        # rolls, not 6, on a Sweet Scent the game reported as "protected by Mist"].
        blocked = (move.effect == EFFECT_LOWER_EVASION and field is not None
                   and field.mist_turns > 0)
        return rng, MoveOutcome(
            rolls=used, tokens=tuple(parts), successful=True,
            applied_status=status, sleep_turns=sleep_turns,
            sets_rain=move.effect == EFFECT_RAIN_DANCE,
            sets_mist=move.effect == EFFECT_MIST,
            traps=move.effect == EFFECT_MEAN_LOOK,
            sets_water_sport=move.effect == EFFECT_WATER_SPORT,
            blocked_by_mist=blocked)

    # Damaging.
    rng, crit_roll = advance(rng)
    rng, damage_roll = advance(rng)
    used += 2
    critical = crit_roll % CRIT_MODIFIERS[0] == 0
    hit = True
    if move.accuracy > 0:
        rng, hit_roll = advance(rng)
        used += 1
        hit = hit_roll % 100 < _effective_accuracy(move, net_stage)
    if not hit:
        parts.append(tok.MISS)
        return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=False)
    parts.append(tok.CRIT if critical else tok.HIT)

    dealt = 0
    attacker_side = Attacker(
        level=attacker.level, attack=attacker.stats["atk"],
        special_attack=attacker.stats["spa"], types=attacker.types,
        attack_stage=attack_stage, special_attack_stage=attack_stage,
        ability=attacker.ability, held_item=attacker.held_item)
    if unsupported_reason(move) is None and unsupported_attacker_reason(attacker_side) is None:
        physical = move.category != 1
        dealt = damage(
            move,
            Attacker(level=attacker.level, attack=attacker.stats["atk"],
                     special_attack=attacker.stats["spa"], types=attacker.types,
                     attack_stage=attack_stage, special_attack_stage=attack_stage,
                     ability=attacker.ability, held_item=attacker.held_item),
            Defender(defence=defender.stats["def"], special_defence=defender.stats["spd"],
                     types=defender.types, defence_stage=defender.def_stage,
                     special_defence_stage=defender.spdef_stage),
            roll=DAMAGE_ROLL_MAX_PERCENT - damage_roll % DAMAGE_ROLL_COUNT,
            critical=critical)
        # False Swipe cannot knock out: it leaves the target on 1 HP.
        if move.effect == 101:
            dealt = min(dealt, max(0, defender.hp - 1))

    secondary = False
    if move.effect_chance > 0:
        rng, proc_roll = advance(rng)
        used += 1
        secondary = proc_roll % 100 < move.effect_chance
        if secondary:
            parts.append(tok.SECONDARY)

    return rng, MoveOutcome(rolls=used, tokens=tuple(parts), successful=True,
                            damage=dealt, secondary=secondary)


def _visible_tokens(outcome: MoveOutcome, move: Move, *, victim: Battler,
                    victim_still_to_move: bool) -> tuple[str, ...]:
    """`outcome`'s tokens with an unobservable secondary marker removed.

    Two cases, both verified rather than reasoned:

    * **The move fainted the victim.** The secondary roll is still spent, but its outcome is
      never shown -- no "was burned!", no stat-drop message -- so it must not be tokenized
      [notes/ss_rng/fainting.md]. Note the case this does NOT cover: a victim that survives the
      move and then faints to the burn the move inflicted *did* see the burn, so that turn keeps
      its ``~`` (``E3h~X2``). Residual damage is not modelled yet, so the simulator cannot
      produce that form at all; when it can, the distinction is already in the right place,
      because this reads the victim's HP after the move and not at the end of the turn.
    * **A flinch whose victim never reaches its turn**, which is most of them -- see
      `flinch_visible`.

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
    hidden = victim.fainted or (
        move.effect in FLINCH_EFFECTS
        and not flinch_visible(victim, victim_still_to_move=victim_still_to_move))
    if not hidden:
        return outcome.tokens
    return tuple(part for part in outcome.tokens if part != tok.SECONDARY)


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

    One roll always, and the modulus shrinks as PP runs out — so its entropy decays from 2.00
    bits to 1.58 to 1.00 and then to nothing (sec 5.2 R4, verified). Returns (rng, slot), with
    slot None when nothing is usable and the target would have to Struggle.

    **A None slot is outside the model.** Struggle is not simulated: no roll is spent, no damage
    is dealt and no recoil is applied, so such a turn is silently wrong rather than visibly
    unsupported. It also loses the run in reality, because Struggle recoil kills a 1 HP target.
    The solver therefore never searches that far — see ``solver.struggle_deadline`` — and callers
    that might should check for None themselves.
    """
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
    """Everything a simulation needs that does not change during the battle."""
    target_catch_rate: int
    capture_ball_multiplier: int = BALL_POKE
    #: Pressure doubles OUR PP consumption, not the target's own (sec 4.4).
    target_has_pressure: bool = True
    #: True once the target's base Speed clears the Fast Ball's threshold.
    fast_ball_matched: bool = False
    #: Rolls to burn before turn 1. A field rather than a bare constant because the count is
    #: venue-specific: the four animation rolls are the Bell Tower's, and a different encounter
    #: would spend a different number. See :data:`BATTLE_START_ADVANCES`.
    battle_start_advances: int = BATTLE_START_ADVANCES

    def effective_catch_rate(self) -> int:
        return fast_ball_catch_rate(self.target_catch_rate, 100 if self.fast_ball_matched else 0)

    def standard_ball_matches_capture_ball(self) -> bool:
        """Whether a plain Poke Ball is exactly as likely to catch as the capture ball.

        This is the fact behind sec 2.3's warning, and it is a property of the MATCHUP rather
        than of the phase. On Suicune the Fast Ball misses its base-Speed threshold, so both
        balls are a flat x1 and a standard ball that lands is a lost run. Against a target the
        Fast Ball actually matches, a standard ball is far weaker and a probe is correspondingly
        cheaper. Reported to the UI so the warning can say which case the player is in instead of
        asserting the harsher one.
        """
        return (self.capture_ball_multiplier == BALL_POKE
                and self.effective_catch_rate() == self.target_catch_rate)


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
    """Speed after paralysis. Gen 4 quarters it, which is the whole reason paralysis is the
    sanctioned tie-avoidance: it takes Suicune to ~21, so anything outspeeds it and no speed-tie
    roll occurs anywhere in the search (sec 4.2).

    Lagging Tail would be actively harmful here -- it guarantees we move *last*.
    """
    speed = battler.stats["spe"]
    if battler.status is Status.PARALYSIS:
        speed = int(speed * PARALYSIS_SPEED_FACTOR)
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
            multiplier = (config.capture_ball_multiplier
                          if action is Action.CAPTURE_BALL else BALL_POKE)
            rate = (config.effective_catch_rate() if action is Action.CAPTURE_BALL
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
            new.bench = party_order(
                tuple(b for i, b in enumerate(new.bench) if i != bench_slot) + (new.ours,))
            new.ours = incoming
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
            back = revived.with_hp(items.revive_amount(revived.max_hp))
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
            rng, move, new.ours, new.target, actor="M", slot=slot, field=new,
            attack_stage=new.our_attack_stage)
        new.rng_offset += outcome.rolls
        new.ours = new.ours.spend_pp(slot, 2 if config.target_has_pressure else 1)
        apply_field(outcome)
        if outcome.damage:
            new.target = new.target.with_hp(new.target.hp - outcome.damage)
        if outcome.applied_status is not None:
            # The rolled duration was being thrown away, so a slept target never woke.
            new.target = new.target.with_status(outcome.applied_status,
                                                sleep_turns=outcome.sleep_turns)
        if outcome.secondary and move.effect in FLINCH_EFFECTS:
            flinched["E"] = True
        # Emitted AFTER the state changes above, because whether the flinch is reportable depends
        # on them: a KO or a sleep that holds hides it. See `flinch_visible`.
        parts.extend(_visible_tokens(outcome, move, victim=new.target,
                                     victim_still_to_move=ours_first))
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
        rng, outcome = execute_move(
            rng, move, new.target, new.ours, actor="E", slot=target_slot, field=new)
        new.rng_offset += outcome.rolls
        new.target = new.target.spend_pp(target_slot, 1)
        apply_field(outcome)
        if outcome.damage:
            new.ours = new.ours.with_hp(new.ours.hp - outcome.damage)
        if outcome.secondary and move.effect == 68:
            new.our_attack_stage = max(-6, new.our_attack_stage - 1)
        if outcome.secondary and move.effect in FLINCH_EFFECTS:
            flinched["M"] = True
        parts.extend(_visible_tokens(outcome, move, victim=new.ours,
                                     victim_still_to_move=not ours_first))
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

    # HP, then the faint. A faint turn carries no HP token at all: zero is implied by the X, and
    # once the replacement is out the number would describe a different Pokemon.
    if new.ours.fainted:
        new.faints += 1
        parts.append(_send_out(new, replacement))
    elif new.ours.hp != hp_before:
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
    incoming = state.bench[index]
    state.bench = party_order(
        tuple(b for i, b in enumerate(state.bench) if i != index) + (state.ours,))
    state.ours = incoming
    return tok.faint_token(party_number(incoming, index))


def simulate(state: BattleState, actions: list[Action], config: HuntConfig) -> BattleState:
    """Several turns in sequence, stopping early if the battle ends."""
    for action in actions:
        if state.over:
            break
        state = simulate_turn(state, action, config)
    return state
