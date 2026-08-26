"""metronome_compass — Multi-turn seed identification via Metronome battle observation.

Full dual-mode turn simulation (move outcomes and Magikarp turns).
Filters candidates by comparing full turn paths.
"""
from __future__ import annotations
import datetime as dt
from dataclasses import dataclass, field
from enum import Enum

from claytonlib.safari import advance_rng
from claytonlib.times import get_times, calculate_seed
from claytonlib.compass_premetronome import MetronomeOpponent
from claytonlib.moves import Move, _load_moves, _moves_by_number

from .path import (
    Path as BattlePath, Turn, render_path,
    PathToken, MetronomeMove, MagikarpMove, MultiHit,
    Hit, Miss, Crit, EffectProc,
    PAR, FRZ, CFZ, SCFZ, SLP, FLN, LV, Struggle, Prevented, StatusEnd, PathEnd, Unsupported,
    BindDmg, BindEnd, DrowsySlept, Magnitude, ConversionType,
    NonVolatileStatus, MagikarpStatus, MetronomeBattleState,
)
from .context import BattleContext, RngContext, InteractiveContext
from .effects import move_effect, EFFECT_HANDLERS, simulate_metronome_roll, _METRONOME_POOL


# ---------------------------------------------------------------------------
# Magikarp gender
# ---------------------------------------------------------------------------

class MagikarpGender(Enum):
    MALE   = "male"
    FEMALE = "female"


# ---------------------------------------------------------------------------
# Input dataclass
# ---------------------------------------------------------------------------

@dataclass
class CompassMetronomeInput:
    opponent:       MetronomeOpponent
    key_seed:       int
    target_delay:   int
    initial_time:   dt.datetime
    window:         int
    magikarp_level: int              # determines move pool (< 15: Splash only)
    known_moves:    tuple[int, ...] = field(default_factory=tuple)  # move numbers already known
    second_window:  int = 0


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _generate_candidates(inputs: CompassMetronomeInput) -> list[tuple[int, int]]:
    """Return sorted (seed, delay) pairs for the search window.

    Mirrors the Metronome Compass Testing notebook's generator: a single center
    second — derived once from the *target* delay offset — is enumerated against
    every delay in the ±window range, giving a uniform seconds×delays grid rather
    than tying each delay to its own exact RTC second. This is a superset of the
    strictly-reachable seeds and is robust to imprecision in the 59.8261 Hz frame
    rate (frame-rate-fix plan, "wider compass windows").

    ``second_window`` widens the seconds window; the extra +1 second on the high
    side keeps the "second has ticked" partner, so ``second_window=0`` still emits
    the canonical two seeds per delay.
    """
    from claytonlib.compass import _delay_offset_to_second_frame
    base_delay, _ = get_times(inputs.key_seed)
    center_second, _ = _delay_offset_to_second_frame(max(0, inputs.target_delay - base_delay))
    seen: set[int] = set()
    results: list[tuple[int, int]] = []

    for d in range(inputs.target_delay - inputs.window,
                   inputs.target_delay + inputs.window + 1):
        if d < 0:
            continue
        for s in range(center_second - inputs.second_window,
                       center_second + inputs.second_window + 2):
            if s < 0:
                continue
            seed = calculate_seed(inputs.initial_time + dt.timedelta(seconds=s), d)
            if seed not in seen:
                seen.add(seed)
                results.append((seed, d))

    results.sort(key=lambda x: (x[1], x[0]))
    return results


# ---------------------------------------------------------------------------
# Turn simulation
# ---------------------------------------------------------------------------

_BATTLE_START_ADVANCES = 6   # 4 bellShimmer + 2 ability
_BEFORE_TURN_ADVANCES  = 4   # quick claw checks

# Verified advance counts
_POST_METRONOME_SUCCESS_ADVANCES = 2
_MAGIKARP_TURN_START_ADVANCES    = 2
_POST_MAGIKARP_SUCCESS_ADVANCES  = 2
_END_OF_TURN_ADVANCES            = 4
# A type-immune Tackle still rolls crit + damage + accuracy (3 advances), then
# "doesn't affect" the target, so it is not successful (no post-hit advances).
_IMMUNE_TACKLE_ADVANCES          = 3


def simulate_turn(
    ctx: BattleContext,
    state: MetronomeBattleState,
    moves_by_num: dict[int, Move],
    known_moves: frozenset[int],
    magikarp_level: int,
) -> Turn:
    """Simulate one full battle turn and return its token tuple."""
    from .effects import simulate_move_execution, simulate_locked_continuation, _apply_confusion, _apply_user_confusion

    state.user_hit_this_turn = False  # reset per-turn damage flag (Metal Burst)

    # 1. Magikarp move selection.
    # Under Encore, Magikarp repeats its last move without a random selection roll.
    mk_can_move = _magikarp_has_useable_moves(state, magikarp_level)
    mk_move_roll = None
    if mk_can_move and state.mk_encore_turns == 0:
        mk_move_roll = ctx.consume_observable_roll()

    # 2. BeforeTurn checks
    ctx.advance_unobservable(_BEFORE_TURN_ADVANCES)

    # 3. Magikarp's status checks & move execution (Magikarp moves first)
    mk_success = _simulate_magikarp_turn(ctx, state, magikarp_level, mk_move_roll, mk_can_move)

    # 4. IF successful: post-magikarp rolls
    if mk_success:
        ctx.advance_unobservable(_POST_MAGIKARP_SUCCESS_ADVANCES)

    # Did Magikarp land a damaging hit on Chansey this turn? (Tackle hit, or
    # Struggle which always hits.)
    landed_hit = mk_success and (state.mk_last_move == 33 or state.mk_last_move is None)
    if landed_hit:
        state.user_hit_this_turn = True   # Metal Burst (damage taken THIS turn)
        if state.user_locked_effect == 26:
            state.user_bide_triggered = True

    # Conversion 2's recorded "last damaging move that landed on me": set on a
    # damaging hit, left unchanged by a self-targeting Splash, and cleared on any
    # miss or prevention — matching the game rewriting conversion2Move against
    # the defender on every move that resolves against them.
    if landed_hit:
        state.user_conv2_hit = True
    elif not (mk_success and state.mk_last_move == 150):
        state.user_conv2_hit = False

    # 5. Between-actor advances
    ctx.advance_unobservable(_MAGIKARP_TURN_START_ADVANCES)

    # 6-7. Metronome roll + execution, or locked-move continuation (player moves second)
    if state.user_sleep_turns > 0:
        # Rest sleep: Chansey can't act this turn
        state.user_sleep_turns -= 1
        _pre_locked_effect = None
        move_success = False  # no move executed
    elif state.user_recharging:
        # Hyper Beam / recharge: Chansey must recharge, no move executed
        state.user_recharging = False
        _pre_locked_effect = None
        move_success = False
    elif state.user_locked_turns > 0:
        state.user_locked_turns -= 1
        _pre_locked_effect = state.user_locked_effect
        locked_move = moves_by_num[state.user_locked_move_num]
        # Confusion check also happens during locked turns. Chansey's confusion
        # (from a rampage end, duration 2-5) resolves as snap-out / hit-self /
        # attacked-through via confusion_outcome; only the first two emit tokens.
        if state.user_confusion_turns > 0:
            outcome = ctx.confusion_outcome("Chansey", state.user_confusion_turns, 2, 5)
            if outcome == 'hit_self':
                state.user_confusion_turns -= 1
                ctx.advance_unobservable(1)  # self-hit damage roll
                ctx.raw_emit(CFZ())
                move_success = False
            else:
                if outcome == 'snap':
                    state.user_confusion_turns = 0
                    ctx.raw_emit(SCFZ())
                else:  # attacked through the confusion
                    state.user_confusion_turns -= 1
                move_success = simulate_locked_continuation(ctx, state, locked_move)
                if ctx.battle_state.get('unsupported'):
                    return ctx.end_turn()
        else:
            move_success = simulate_locked_continuation(ctx, state, locked_move)
            if ctx.battle_state.get('unsupported'):
                return ctx.end_turn()
        # Hidden-length locks (Rampage 27 / Uproar 159): RNG ends on the rolled
        # length; interactive tracks the max and observes the end here. Only prompt
        # inside the possible-end window; the maximum is handled by the counter
        # reaching 0 naturally. confirm_lock_end() is a no-op in RNG mode.
        if _pre_locked_effect in (27, 159) and state.user_locked_turns > 0:
            _max_locked = 2 if _pre_locked_effect == 27 else 5
            _min_cont = 1 if _pre_locked_effect == 27 else 2
            _cont_turn = _max_locked - state.user_locked_turns
            _label = "Rampage" if _pre_locked_effect == 27 else "Uproar"
            if _cont_turn >= _min_cont and ctx.confirm_lock_end(_label):
                state.user_locked_turns = 0
                if _pre_locked_effect == 159:  # Uproar clears its own lock; Rampage
                    state.user_locked_move_num = None  # clears in the end-of-turn block
                    state.user_locked_effect = None
    elif state.user_confusion_turns > 0:
        # Chansey is confused (from rampage end). The final turn snaps out with no
        # self-hit roll; earlier turns roll hit-self (CFZ) or attacked-through.
        _pre_locked_effect = None
        outcome = ctx.confusion_outcome("Chansey", state.user_confusion_turns, 2, 5)
        if outcome == 'hit_self':
            state.user_confusion_turns -= 1
            ctx.advance_unobservable(1)  # self-hit damage roll
            ctx.raw_emit(CFZ())
            move_success = False
        else:
            if outcome == 'snap':
                state.user_confusion_turns = 0
                ctx.raw_emit(SCFZ())
            else:  # attacked through the confusion
                state.user_confusion_turns -= 1
            move = simulate_metronome_roll(ctx, moves_by_num, known_moves)
            move_success = simulate_move_execution(ctx, move)
            if ctx.battle_state.get('unsupported'):
                return ctx.end_turn()
    else:
        _pre_locked_effect = None
        move = simulate_metronome_roll(ctx, moves_by_num, known_moves)
        move_success = simulate_move_execution(ctx, move)
        if ctx.battle_state.get('unsupported'):
            return ctx.end_turn()

    # 8. IF successful: post-metronome rolls
    if move_success:
        ctx.advance_unobservable(_POST_METRONOME_SUCCESS_ADVANCES)

    # 9. End of turn maintenance
    # First half of end-of-turn advances, then rampage confusion, then second half.
    # The confusion roll lands between END[1] and END[2] in the actual game.
    _HALF_END = _END_OF_TURN_ADVANCES // 2
    ctx.advance_unobservable(_HALF_END)

    # Thrash/Outrage/Petal Dance: confusion applied when rampage ends (between END
    # halves). No token for the rampage ending itself — resuming Metronome next turn
    # already shows it ended; the ensuing confusion is what's observed (SCFZ/CFZ).
    if (_pre_locked_effect == 27
            and state.user_locked_turns == 0
            and state.user_locked_move_num is not None):
        _apply_user_confusion(ctx)
        state.user_locked_move_num = None
        state.user_locked_effect = None

    ctx.advance_unobservable(_END_OF_TURN_ADVANCES - _HALF_END)

    # End-of-turn residual damage to Magikarp (poison/burn status, or sandstorm/
    # hail weather — Magikarp is Water so it's hit by both) leaves it below full
    # HP. This doesn't consume tracked RNG here, but it matters for Present's
    # heal branch, which fails only when the target is provably at full HP.
    if (state.mk_status.status in (NonVolatileStatus.POISON, NonVolatileStatus.BURN)
            or state.weather in ('sand', 'hail')):
        state.mk_took_damage = True
        state.mk_recovered = False

    state.turn_number += 1

    # Binding damage / release. Hidden duration (3-5): BindDmg each turn, BindEnd
    # on the turn it breaks free. RNG mode frees on the rolled turn; interactive
    # confirms the break-free at end of turn (BindEnd) vs damage (BindDmg).
    if state.mk_binding_turns > 0:
        if ctx.hidden_status_ends("Binding", state.mk_binding_turns, 3, 5):
            state.mk_binding_turns = 0
            ctx.raw_emit(BindEnd())
        else:
            state.mk_binding_turns -= 1
            ctx.raw_emit(BindDmg())

    # Drowsy → sleep (from Yawn)
    if state.mk_drowsy_turns > 0:
        state.mk_drowsy_turns -= 1
        from .effects import _mk_has_insomnia
        if (state.mk_drowsy_turns == 0
                and state.mk_status.status == NonVolatileStatus.NONE
                and not _mk_has_insomnia(state)):
            ctx.raw_emit(DrowsySlept())
            state.mk_status.status = NonVolatileStatus.SLEEP
            roll = ctx.unobservable_roll()
            state.mk_status.sleep_turns = 2 + (roll % 4)

    # Tick down fixed-duration statuses
    if state.gravity_turns > 0:
        state.gravity_turns -= 1
        if state.gravity_turns == 0:
            ctx.raw_emit(StatusEnd("GRV"))
    # Hidden-duration statuses: the wear-off is the only observable event, so we
    # emit no token at apply and confirm the end at end of turn. In RNG mode the
    # rolled duration decides; in interactive mode the player confirms the wear-off
    # (tracked as max duration, prompted from the minimum onward). Bounds match the
    # roll ranges in effects.py (Disable 4-7, Taunt 3-5, Encore stored 5-8).
    if state.mk_status.disable_turns > 0:
        if ctx.hidden_status_ends("Disable", state.mk_status.disable_turns, 4, 7):
            state.mk_status.disable_turns = 0
            state.mk_status.disabled_move = None
            ctx.raw_emit(StatusEnd("DIS"))
        else:
            state.mk_status.disable_turns -= 1
    if state.mk_status.taunt_turns > 0:
        if ctx.hidden_status_ends("Taunt", state.mk_status.taunt_turns, 3, 5):
            state.mk_status.taunt_turns = 0
            ctx.raw_emit(StatusEnd("TNT"))
        else:
            state.mk_status.taunt_turns -= 1
    if state.user_light_screen_turns > 0:
        state.user_light_screen_turns -= 1
    if state.user_reflect_turns > 0:
        state.user_reflect_turns -= 1
    if state.user_mist_turns > 0:
        state.user_mist_turns -= 1
    if state.user_safeguard_turns > 0:
        state.user_safeguard_turns -= 1
    if state.user_tailwind_turns > 0:
        state.user_tailwind_turns -= 1
    if state.user_lucky_chant_turns > 0:
        state.user_lucky_chant_turns -= 1
    if state.user_trick_room_turns > 0:
        state.user_trick_room_turns -= 1
    if state.user_magnet_rise_turns > 0:
        state.user_magnet_rise_turns -= 1
    if state.user_lock_on_turns > 0:
        state.user_lock_on_turns -= 1
    if state.mk_encore_turns > 0:
        if ctx.hidden_status_ends("Encore", state.mk_encore_turns, 5, 8):
            state.mk_encore_turns = 0
            ctx.raw_emit(StatusEnd("ENC"))
        else:
            state.mk_encore_turns -= 1

    # Future Sight / Doom Desire: tick counter; fire observable hit check when it reaches 0
    if state.future_sight_turns > 0:
        state.future_sight_turns -= 1
        if state.future_sight_turns == 0 and state.future_sight_move_num is not None:
            fs_move = moves_by_num.get(state.future_sight_move_num)
            fs_acc = fs_move.accuracy if fs_move else 100
            ctx.emit(
                rng_to_token=lambda c: Hit() if c.advance_observable() % 100 < fs_acc else Miss(),
                question="Future Sight/Doom Desire hit? (h/-):",
                input_to_token=lambda s: Hit() if s.strip() == 'h' else Miss(),
            )
            state.future_sight_move_num = None

    return ctx.end_turn()


def _magikarp_has_useable_moves(state: MetronomeBattleState, level: int) -> bool:
    """True if Magikarp can use Splash or Tackle (not prevented by Disable/Taunt/Gravity)."""
    # Splash (150)
    splash_prevented = state.gravity_turns > 0 or state.mk_status.taunt_turns > 0
    if not splash_prevented and state.mk_status.disabled_move != 150:
        return True
    # Tackle (33)
    if level >= 15:
        if state.mk_status.disabled_move != 33:
            return True
    return False


def _simulate_magikarp_turn(
    ctx: BattleContext,
    state: MetronomeBattleState,
    level: int,
    mk_move_roll: int | None,
    mk_can_move: bool,
) -> bool:
    """Run through Magikarp's turn status checks and action. Returns True if move successful."""
    status = state.mk_status


    # Sleep. Duration is hidden (2-5); the wake is self-evident from any action,
    # so no wear-off token — just SLP while asleep. RNG mode wakes on the rolled
    # turn; interactive tracks the max and confirms the wake in the 2..5 window.
    if status.status == NonVolatileStatus.SLEEP:
        if ctx.hidden_status_ends("Sleep", status.sleep_turns, 2, 5):
            status.sleep_turns = 0
            status.status = NonVolatileStatus.NONE
            # Wakes up; continues to move
        else:
            status.sleep_turns -= 1
            ctx.raw_emit(SLP())
            state.mk_last_move_prevented = True
            return False

    # Freeze
    if status.status == NonVolatileStatus.FROZEN:
        thaw = ctx.emit(
            rng_to_token=lambda c: SCFZ() if c.advance_observable() % 5 == 0 else FRZ(),
            question="Magikarp thawed? (y/n): ",
            input_to_token=lambda s: SCFZ() if s.strip().lower() == 'y' else FRZ(),
        )
        if isinstance(thaw, FRZ):
            state.mk_last_move_prevented = True
            return False
        status.status = NonVolatileStatus.NONE
        # Thawed; continues to move

    # Flinch
    if status.flinched:
        status.flinched = False
        ctx.raw_emit(FLN())
        state.mk_last_move_prevented = True
        return False

    # Prevented by Disable/Taunt/Gravity
    # If the selected move is prevented, it fails.
    # Note: we need to resolve the selected move first to see if IT is prevented.
    
    # Resolve move
    if not mk_can_move:
        # Forced Struggle because it had no usable moves at start of turn
        ctx.raw_emit(Struggle())
        state.mk_last_move = None # Struggle is not disable-able
        state.mk_last_move_prevented = False
        # Struggle rolls crit + damage; auto-misses during semi-invulnerable charge.
        _SEMI_INVULNERABLE = {155, 256, 255, 263, 272}
        ctx.advance_unobservable(2)  # crit + damage (unobservable for opponent)
        if state.user_locked_effect in _SEMI_INVULNERABLE:
            return False  # Struggle auto-misses; no observable hit token (bypasses accuracy)
        # Struggle recoil damages Chansey → provably not full; clears any prior heal.
        state.user_took_damage = True
        state.user_recovered = False
        return True

    # Has useable moves: resolve the selected one.
    # Under Encore, Magikarp repeats its last move (no random selection roll used).
    if state.mk_encore_turns > 0 and state.mk_last_move is not None:
        move_num = state.mk_last_move
        ctx.raw_emit(MagikarpMove("sp" if move_num == 150 else "tk"))
    else:
        selected_move = ctx.magikarp_move_select(level, mk_move_roll)
        move_num = 150 if selected_move.move == 'sp' else 33

    # Torment: Magikarp cannot use the same move as last turn; auto-switches.
    if state.mk_tormented and move_num == state.mk_last_move:
        move_num = 33 if move_num == 150 else 150

    # Check if this SPECIFIC move is prevented.
    # Taunt/Gravity/Disable only "prevent" Magikarp on the turn they apply; on
    # subsequent turns they force it to a different usable move (effect_status.md).
    # Chansey is always slower, so Taunt lands after Magikarp has already moved —
    # every taunted Magikarp turn is a "subsequent" one, so Splash simply
    # auto-switches to Tackle (no Prevented, no lost turn), like Gravity/Disable.
    if move_num == 150:
        if (state.gravity_turns > 0 or status.disabled_move == 150
                or status.taunt_turns > 0):
            # Wild AI auto-switches to Tackle when Splash is unavailable
            move_num = 33
    elif move_num == 33:
        if status.disabled_move == 33:
            # Tackle disabled → auto-switch to Splash (same reasoning as above:
            # Disable lands after Magikarp has moved, so it only forces a
            # different usable move on later turns, never a "Prevented" lost turn).
            # If Splash were also unavailable, Magikarp would have had no usable
            # moves and Struggled before reaching here.
            move_num = 150

    # Confusion (hidden duration 2-5). On the final turn it snaps out (SCFZ) with
    # NO self-hit roll; otherwise a self-hit check either hurts it (CFZ) or lets it
    # attack through (no token). Interactive prompts these three outcomes directly;
    # RNG mode decides from the rolled duration and the check roll.
    if status.confusion_turns > 0:
        outcome = ctx.confusion_outcome("Magikarp", status.confusion_turns, 2, 5)
        if outcome == 'snap':
            status.confusion_turns = 0
            ctx.raw_emit(SCFZ())
        elif outcome == 'hit_self':
            status.confusion_turns -= 1
            ctx.advance_unobservable(1)  # self-hit damage roll
            ctx.raw_emit(CFZ())
            state.mk_last_move_prevented = True
            return False
        else:  # attacked through the confusion
            status.confusion_turns -= 1

    # Paralysis
    if status.status == NonVolatileStatus.PARALYZED:
        paralyzed = ctx.emit(
            rng_to_token=lambda c: PAR() if c.advance_observable() % 4 == 0 else None,
            question="Magikarp fully paralyzed? (y/n): ",
            input_to_token=lambda s: PAR() if s.strip().lower() == 'y' else None,
        )
        if isinstance(paralyzed, PAR):
            state.mk_last_move_prevented = True
            return False

    # Attract
    if status.infatuated:
        attract = ctx.emit(
            rng_to_token=lambda c: LV() if (c.advance_observable() & 1) == 0 else None,
            question="Magikarp immobilized by love? (y/n): ",
            input_to_token=lambda s: LV() if s.strip().lower() == 'y' else None,
        )
        if isinstance(attract, LV):
            state.mk_last_move_prevented = True
            return False

    # Move executes
    state.mk_last_move = move_num
    state.mk_last_move_prevented = False
    
    if move_num == 33: # Tackle
        # Normal-type Tackle has no effect on a Ghost-type Chansey (e.g. after
        # Conversion 2). The move "doesn't affect" — not successful, no damage.
        if 'Ghost' in state.user_types:
            ctx.advance_unobservable(_IMMUNE_TACKLE_ADVANCES)
            return False
        # Semi-invulnerable moves (Fly/Dig/Dive/Bounce/Shadow Force): Tackle auto-misses.
        # The hit roll is still consumed; result is overridden to Miss.
        _SEMI_INVULNERABLE = {155, 256, 255, 263, 272}
        semi_inv = state.user_locked_effect in _SEMI_INVULNERABLE
        # Tackle accuracy is 95, modified by Magikarp's own accuracy stage (lowered
        # by Mud-Slap/Octazooka/etc.) minus Chansey's evasion stage (Double Team).
        net_stage = max(-6, min(6, state.target_accuracy_stage - state.user_evasion_stage))
        if net_stage >= 0:
            effective_acc = 95 * (3 + net_stage) // 3
        else:
            effective_acc = 95 * 3 // (3 - net_stage)
        if state.gravity_turns > 0:
            effective_acc = effective_acc * 5 // 3  # Gravity boosts accuracy
        # Lucky Chant on Chansey's side blocks Magikarp's crits.
        lucky_chant = state.user_lucky_chant_turns > 0

        def rng_to_hit(ctx: BattleContext) -> PathToken:
            # Crit and damage rolls always advance (they don't change the advance
            # count either way), but the crit result is observable ("A critical
            # hit!") so we must report it for correct path rendering.
            crit_roll = ctx.advance_observable()
            ctx.advance_unobservable(1)  # damage roll
            is_crit = (crit_roll % 16 == 0) and not lucky_chant  # Magikarp crit stage 0
            hit_roll = ctx.advance_observable()
            if semi_inv:
                return Miss()  # auto-miss during charge turn
            if hit_roll % 100 < effective_acc:
                return Crit() if is_crit else Hit()
            return Miss()

        hit_token = ctx.emit(
            rng_to_token=rng_to_hit,
            question="Tackle hit, crit, or miss? (h/!/-):",
            input_to_token=lambda s: {'h': Hit, '!': Crit, '-': Miss}[s.strip()](),
        )
        if not isinstance(hit_token, Miss):
            # Tackle damages Chansey → provably not full; clears any prior heal.
            state.user_took_damage = True
            state.user_recovered = False
            return True
        return False

    # Splash always succeeds (triggers post-success rolls)
    return True


def _delta_str(delta: int) -> str:
    return f"+{delta}" if delta > 0 else str(delta)


def _print_candidates(
    candidates: list[tuple[int, int]],
    seed_to_path: dict[int, BattlePath],
    moves_by_num: dict[int, Move],
    target_delay: int,
    total: int,
    current_turn: int,
) -> None:
    print(f"Seeds: {len(candidates)} / {total} remaining")
    by_proximity = sorted(candidates, key=lambda x: (abs(x[1] - target_delay), x[0]))
    display = by_proximity[:10]
    print(f"  {'#':>2}  {'Seed':>10}  {'Delay':>7}  {'Δ':>5}  Turn {current_turn} Path")
    for i, (seed, delay) in enumerate(display, 1):
        delta = delay - target_delay
        marker = " ← target" if delta == 0 else ""
        path = seed_to_path.get(seed, ())
        turn_path = ""
        move_name = "?"
        if len(path) >= current_turn:
            turn = path[current_turn - 1]
            turn_path = "".join(t.render() for t in turn)
            # Find the MetronomeMove token to get the move name
            for token in turn:
                if isinstance(token, MetronomeMove):
                    move_name = moves_by_num[token.move_num].name
                    break
        
        print(f"  {i:>2}. 0x{seed:08X}  {delay:>7}  {_delta_str(delta):>5}  "
              f"{turn_path:<15} ({move_name}){marker}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more")


# ---------------------------------------------------------------------------
# Public path pre-computation
# ---------------------------------------------------------------------------

def precompute_path(
    seed: int,
    magikarp_level: int,
    opposite_gender: bool,
    moveset: tuple[int, ...] = (),
    n_turns: int = 10,
) -> BattlePath:
    """Pre-compute the battle path for a single seed.

    `moveset` is the Metronome user's non-Metronome movepool (move numbers).
    It affects two things: Metronome re-rolls whenever it would call a move in
    the movepool, and Conversion 2's success (it fails while every movepool move,
    including Metronome, is Normal-type). Defaults to Metronome-only.
    """
    moves_by_num = _moves_by_number()
    known = frozenset(moveset)
    ctx = RngContext(seed)
    state = MetronomeBattleState()
    # Wire the known Magikarp level into OHKO handling (fails when user < target;
    # else threshold = 30 + user - target). The Metronome user's level has no input
    # source yet and keeps its default of 7 (MetronomeBattleState.user_level).
    state.target_level = magikarp_level
    ctx.battle_state['opposite_gender'] = opposite_gender
    ctx.battle_state['state'] = state
    # Build move-type list for Conversion 2 (Metronome + the rest of the movepool)
    metronome = moves_by_num[118]
    user_move_types = [metronome.type_name]
    for num in moveset:
        m = moves_by_num.get(num)
        if m is not None:
            user_move_types.append(m.type_name)
    ctx.battle_state['user_move_types'] = user_move_types
    ctx.advance_unobservable(_BATTLE_START_ADVANCES)
    for _ in range(n_turns):
        simulate_turn(ctx, state, moves_by_num, known, magikarp_level)
        if ctx.battle_state.get('unsupported'):
            break
    return ctx.path


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------

def _resolve_move_input(raw: str, moves_by_num: dict[int, Move]) -> Move | None:
    """Parse user input as a move name or M### notation. Returns None if unresolved."""
    s = raw.strip()
    if s.upper().startswith('M') and s[1:].isdigit():
        num = int(s[1:])
        return moves_by_num.get(num)
    key = s.lower().replace('-', ' ').replace('_', ' ')
    for move in moves_by_num.values():
        if move.name.lower() == key:
            return move
    return None


def _parse_turn_tokens(raw: str, moves_by_num: dict[int, Move]) -> tuple[PathToken, ...]:
    """Parse a space-separated string of tokens like 'M053 h sp'."""
    from .path import Hit, Miss, Crit, EffectProc, MagikarpMove
    parts = raw.split()
    tokens: list[PathToken] = []
    for p in parts:
        p = p.strip()
        if not p: continue
        
        # Conversion result token: CVNormal, CVFire, CVElectric, etc.
        if p.upper().startswith('CV') and len(p) > 2:
            tokens.append(ConversionType(p[2:].capitalize()))
            continue

        # Metronome move
        if p.upper().startswith('M') and p[1:].isdigit():
            num = int(p[1:])
            if num in moves_by_num:
                tokens.append(MetronomeMove(num))
                continue
        
        # Tri Attack EffectProc with status: ~<BRN>, ~<FRZ>, ~<PAR>
        if p.startswith('~<') and p.endswith('>'):
            status = p[2:-1].upper()
            if status in ('BRN', 'FRZ', 'PAR'):
                tokens.append(EffectProc(status=status))
                continue
            raise ValueError(f"Unknown EffectProc status: {p!r}")

        # Shortcuts / specific tokens
        match p.lower():
            case 'h': tokens.append(Hit())
            case '-': tokens.append(Miss())
            case '!': tokens.append(Crit())
            case '~': tokens.append(EffectProc())
            case 'sp': tokens.append(MagikarpMove('sp'))
            case 'tk': tokens.append(MagikarpMove('tk'))
            case _:
                # Try move name
                move = _resolve_move_input(p, moves_by_num)
                if move:
                    tokens.append(MetronomeMove(move.number))
                else:
                    raise ValueError(f"Unknown token: {p}")
    return tuple(tokens)


def metronome_compass(inputs: CompassMetronomeInput) -> list[str]:
    """Interactive multi-turn seed identification via Metronome battle observation.

    Filters by full turn paths with status and battle state tracking.
    """
    moves_by_num = _moves_by_number()
    initial_candidates = _generate_candidates(inputs)
    total = len(initial_candidates)
    moveset = "Splash only" if inputs.magikarp_level < 15 else "Splash + Tackle"

    print("=== Metronome Compass ===")
    print(f"Opponent:       {inputs.opponent.value.capitalize()}")
    print(f"Magikarp level: {inputs.magikarp_level} ({moveset})")
    sw = f"  second_window=±{inputs.second_window}" if inputs.second_window else ""
    print(f"Window:         ±{inputs.window} delays{sw}  ({total} initial candidates)")
    if inputs.known_moves:
        names = ', '.join(moves_by_num[n].name for n in inputs.known_moves
                          if n in moves_by_num)
        print(f"Known moves:    {names}")
    
    # Magikarp gender determines if Attract (selected via Metronome) can land.
    while True:
        g = input("Magikarp gender? (m/f): ").strip().lower()
        if g in ('m', 'f'):
            opp = input("Is Magikarp opposite gender to your Pokemon? (y/n): ").strip().lower()
            opposite_gender = (opp == 'y')
            break
        print("  Please enter 'm' or 'f'.")

    print("\nPre-computing paths for all candidates...")
    seed_to_path = {
        seed: precompute_path(seed, inputs.magikarp_level, opposite_gender, inputs.known_moves)
        for seed, delay in initial_candidates
    }
    print("Done.\n")

    while True:
        # history: list of (observed_path, candidates) snapshots.
        history: list[tuple[BattlePath, list[tuple[int, int]]]] = [
            ((), list(initial_candidates)),
        ]

        print("--- Session ---")

        while True:
            observed_path, candidates = history[-1]
            turn_n = len(observed_path) + 1

            print()
            _print_candidates(candidates, seed_to_path, moves_by_num,
                              inputs.target_delay, total, turn_n)

            if not candidates:
                print()
                print("No matching seeds. Check for input errors or expand the window.")
                break

            if len(candidates) == 1:
                seed, delay = candidates[0]
                delta = delay - inputs.target_delay
                print()
                print(f"Seed identified: 0x{seed:08X}  delay={delay}  Δ={_delta_str(delta)}")
                return [f"0x{seed:08X}"]

            print()
            print(f"Turn {turn_n} — enter observations (e.g. 'Flamethrower h sp')")
            raw = input("  (or u=undo, q=quit): ").strip()

            if raw.lower() in ('q', 'quit'):
                return [f"0x{s:08X}" for s, d in candidates]

            if raw.lower() == 'u':
                if len(history) > 1:
                    history.pop()
                    print(f"  Undone. Back to turn {len(history)}.")
                else:
                    print("  Nothing to undo.")
                continue

            try:
                observed_turn = _parse_turn_tokens(raw, moves_by_num)
            except ValueError as e:
                print(f"  Error: {e}")
                continue

            if not observed_turn:
                print("  No tokens entered.")
                continue

            # Filter candidates by comparing their pre-computed turn against the observed turn.
            def matches(seed_seed: int, obs_turn: tuple[PathToken, ...]) -> bool:
                path = seed_to_path.get(seed_seed, ())
                if len(path) < turn_n:
                    return False
                cand_turn = path[turn_n - 1]
                # Prefix match
                if len(cand_turn) < len(obs_turn):
                    return False
                return cand_turn[:len(obs_turn)] == obs_turn

            new_candidates = [(s, d) for s, d in candidates if matches(s, observed_turn)]
            
            new_path = observed_path + (observed_turn,)
            history.append((new_path, new_candidates))

        _, candidates = history[-1]
        print()
        again = input("Go again? (y/n): ").strip().lower()
        if again != 'y':
            return [f"0x{s:08X}" for s, d in candidates]
        print()
