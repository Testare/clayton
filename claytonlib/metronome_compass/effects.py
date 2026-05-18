"""Effect scripts and registry for metronome battle simulation.

Each effect number from the decompiled source maps to a handler function that
calls ctx.emit() helpers to advance RNG (in RngContext) or prompt the user
(in InteractiveContext). Unknown effect numbers fall back to _effect_unsupported.

Add handlers incrementally: populate move_effect() with a description first,
then implement the handler when the GDB-verified RNG sequence is known.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Callable

from claytonlib.moves import Move
from .path import NonVolatileStatus

if TYPE_CHECKING:
    from .context import BattleContext


# ---------------------------------------------------------------------------
# Human-readable effect descriptions
# ---------------------------------------------------------------------------

def move_effect(effect: int, effect_chance: int = 0) -> str:
    """Return a human-readable description of an effect number."""
    match effect:
        case 0:   return "standard"
        case 1:   return "sleep"
        case 4:   return f"burn {effect_chance}%"
        case 5:   return f"freeze {effect_chance}%"
        case 6:   return f"paralyze {effect_chance}%"
        case 29:  return "multi-hit"
        case 43:  return "high crit"
        case 49:  return "confusion"
        case 67:  return "paralyze"
        case 86:  return "disable"
        case 175: return "taunt"
        case 215: return "gravity"
        case _:   return f"unsupported({effect})"


# ---------------------------------------------------------------------------
# Effect handlers
# ---------------------------------------------------------------------------

def _effect_standard_damage(ctx: 'BattleContext', move: Move) -> bool:
    """Standard damaging move: accuracy check, crit check, damage roll."""
    from .path import Miss
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    # Damage roll is not observable
    ctx.advance_unobservable(1)
    return True


def _effect_high_crit(ctx: 'BattleContext', move: Move) -> bool:
    """Move with increased critical hit rate (effect 43: Slash, Karate Chop, etc.).

    TODO: implement with adjusted crit threshold via ctx.hit_crit_or_miss().
    """
    return _effect_standard_damage(ctx, move)


def _effect_with_secondary(ctx: 'BattleContext', move: Move) -> bool:
    """Standard damage + one secondary effect roll (burn/freeze/paralyze/flinch chance)."""
    from .path import Miss
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    # Damage roll
    ctx.advance_unobservable(1)
    # Secondary effect roll
    ctx.effect_proc(move.effect_chance)
    return True


def _effect_sleep(ctx: 'BattleContext', move: Move) -> bool:
    """Effect 1: Sleep (Sleep Powder, Hypnosis, etc.)."""
    from .path import Miss, MetronomeBattleState
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    
    state: MetronomeBattleState = ctx.battle_state['state']
    status = state.mk_status
    
    # Fails if already has a non-volatile status
    if status.status != NonVolatileStatus.NONE:
        return False
        
    def rng_to_duration(ctx: 'BattleContext'):
        roll = ctx.advance_observable()
        return 2 + (roll % 4)
        
    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Sleep duration? (2-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    status.status = NonVolatileStatus.SLEEP
    status.sleep_turns = int(duration) if isinstance(duration, int) else duration
    return True


def _effect_confusion(ctx: 'BattleContext', move: Move) -> bool:
    """Effect 49: Confusion (Confuse Ray, etc.)."""
    from .path import Miss, MetronomeBattleState
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
        
    state: MetronomeBattleState = ctx.battle_state['state']
    status = state.mk_status
    if status.confusion_turns > 0:
        return False
        
    def rng_to_duration(ctx: 'BattleContext'):
        return 2 + (ctx.advance_observable() % 4)
        
    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Confusion duration? (2-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    status.confusion_turns = int(duration)
    return True


def _effect_paralyze(ctx: 'BattleContext', move: Move) -> bool:
    """Effect 67: Paralysis (Thunder Wave, etc.)."""
    from .path import Miss, MetronomeBattleState
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
        
    state: MetronomeBattleState = ctx.battle_state['state']
    status = state.mk_status
    if status.status != NonVolatileStatus.NONE:
        return False
        
    status.status = NonVolatileStatus.PARALYZED
    return True


def _effect_disable(ctx: 'BattleContext', move: Move) -> bool:
    """Effect 86: Disable."""
    from .path import Miss, MetronomeBattleState
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
        
    state: MetronomeBattleState = ctx.battle_state['state']
    status = state.mk_status
    
    if (status.disabled_move is not None or 
        state.mk_last_move is None or 
        state.mk_last_move_prevented):
        return False
        
    def rng_to_duration(ctx: 'BattleContext'):
        return 4 + (ctx.advance_observable() % 4)
        
    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Disable duration? (4-7):",
        input_to_token=lambda s: int(s.strip()),
    )
    status.disabled_move = state.mk_last_move
    status.disable_turns = int(duration)
    return True


def _effect_taunt(ctx: 'BattleContext', move: Move) -> bool:
    """Effect 175: Taunt."""
    from .path import Miss, MetronomeBattleState
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
        
    state: MetronomeBattleState = ctx.battle_state['state']
    status = state.mk_status
    if status.taunt_turns > 0:
        return False
        
    def rng_to_duration(ctx: 'BattleContext'):
        return 3 + (ctx.advance_observable() % 3)
        
    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Taunt duration? (3-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    status.taunt_turns = int(duration)
    return True


def _effect_gravity(ctx: 'BattleContext', move: Move) -> bool:
    """Effect 215: Gravity."""
    from .path import Miss, MetronomeBattleState
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
        
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.gravity_turns > 0:
        return False
        
    state.gravity_turns = 5
    return True


def _effect_multi_hit(ctx: 'BattleContext', move: Move) -> bool:
    """Multi-strike move (effect 29): accuracy check + hit-count roll + per-hit crits."""
    from .path import Miss
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    # Hit count roll
    count = ctx.multi_hit()
    # Damage + crit rolls per hit (beyond the first which was checked by hit_crit_or_miss)
    # TODO: verify how many rolls happen for subsequent hits.
    # Placeholder: 2 rolls per extra hit (crit + damage).
    for _ in range(count - 1):
        ctx.advance_unobservable(2)
    return True


def _effect_status_accuracy(ctx: 'BattleContext', move: Move) -> bool:
    """Status move that performs an accuracy check (Thunder Wave, Will-O-Wisp, etc.)."""
    from .path import Miss, Hit
    # Status moves often use 100% accuracy but still roll for hit.
    # They don't have crit or damage rolls.
    # ctx.hit_crit_or_miss() is overkill (does crit/damage).
    # TODO: verify status move RNG sequence.
    def rng_to_token(ctx: 'BattleContext'):
        roll = ctx.advance_observable()
        is_hit = roll % 256 < move.accuracy * 255 // 100
        return Hit() if is_hit else Miss()

    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Move hit? (h/-):",
        input_to_token=lambda s: Hit() if s.strip() == 'h' else Miss(),
    )
    return not isinstance(token, Miss)


def _effect_no_rng(ctx: 'BattleContext', move: Move) -> bool:
    """Move that consumes no RNG rolls (Splash, Haze, etc.)."""
    # Splash always fails animation-wise, so it's not "successful".
    return False


def _effect_unsupported(ctx: 'BattleContext', move: Move) -> bool:
    """Fallback for unrecognised effect numbers.

    Emits an Unsupported token and sets battle_state['unsupported'] so the
    caller halts further turn simulation for this seed.
    """
    from .path import Unsupported, PathEnd
    ctx.raw_emit(Unsupported())
    ctx.raw_emit(PathEnd())
    ctx.battle_state['unsupported'] = True
    return False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EffectHandler = Callable[['BattleContext', Move], bool]

EFFECT_HANDLERS: dict[int, EffectHandler] = {
    0:   _effect_standard_damage,
    1:   _effect_sleep,
    4:   _effect_with_secondary,    # burn chance
    5:   _effect_with_secondary,    # freeze chance
    6:   _effect_with_secondary,    # paralyze chance
    29:  _effect_multi_hit,
    43:  _effect_high_crit,
    49:  _effect_confusion,
    67:  _effect_paralyze,
    86:  _effect_disable,
    175: _effect_taunt,
    215: _effect_gravity,
}


def simulate_move_execution(ctx: 'BattleContext', move: Move) -> bool:
    """Dispatch to the appropriate effect handler for the given move.

    Sets battle_state['unsupported'] if the effect is unknown, which signals
    that further RNG tracking for this session should be halted.

    Returns True if the move was successful (animation played).
    """
    handler = EFFECT_HANDLERS.get(move.effect, _effect_unsupported)
    return handler(ctx, move)


# ---------------------------------------------------------------------------
# Metronome roll simulation
# ---------------------------------------------------------------------------

_METRONOME_POOL = 0x1D3  # 467 — total moves in the roll range
_METRONOME_MOVE_NUM = 118  # Metronome itself is always excluded


def simulate_metronome_roll(
    ctx: 'BattleContext',
    moves_by_number: dict[int, Move],
    known_moves: frozenset[int],
) -> Move:
    """Roll/ask for the Metronome move selection. Emits MetronomeMove token.

    known_moves: move numbers already known by the user's Pokemon (excluded from pool).
    Metronome itself is always excluded regardless of known_moves.
    Rerolls until a valid metronome-usable, non-known, non-gravity-blocked move is found.

    Returns the selected Move.
    """
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    gravity = state.gravity_turns > 0
    excluded = known_moves | {_METRONOME_MOVE_NUM}

    def rng_to_token(ctx: 'BattleContext'):
        from .path import MetronomeMove
        while True:
            roll = ctx.advance_observable()
            move_num = roll % _METRONOME_POOL + 1
            move = moves_by_number.get(move_num)
            if move is None:
                continue
            if not move.metronome_usable:
                continue
            if move_num in excluded:
                continue
            if gravity and move.is_gravity_blocked():
                continue
            return MetronomeMove(move_num)

    def input_to_token(s: str):
        from .path import MetronomeMove
        s = s.strip()
        if s.upper().startswith('M') and s[1:].isdigit():
            num = int(s[1:])
            if num not in moves_by_number:
                raise ValueError(f"Unknown move number: {num}")
            return MetronomeMove(num)
        # Try resolving by name
        key = s.lower().replace('-', ' ').replace('_', ' ')
        for move in moves_by_number.values():
            if move.name.lower() == key:
                return MetronomeMove(move.number)
        raise ValueError(f"Unknown move: {s!r}")

    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Metronome selected? (move name or M###):",
        input_to_token=input_to_token,
    )
    from .path import MetronomeMove
    assert isinstance(token, MetronomeMove)
    return moves_by_number[token.move_num]
