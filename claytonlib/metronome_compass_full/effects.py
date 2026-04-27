"""Effect scripts and registry for metronome battle simulation.

Each effect number from the decompiled source maps to a handler function that
calls ctx.emit() helpers to advance RNG (in RngContext) or prompt the user
(in InteractiveContext). Unknown effect numbers fall back to _effect_unsupported.

Add handlers incrementally: populate move_effect() with a description first,
then implement the handler when the GDB-verified RNG sequence is known.
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .context import BattleContext


# ---------------------------------------------------------------------------
# Move data type used by effect scripts
# ---------------------------------------------------------------------------

class Move:
    """Move metadata needed by effect scripts."""
    __slots__ = ('number', 'name', 'metronome_usable', 'effect', 'effect_chance', 'accuracy')

    def __init__(self, number: int, name: str, metronome_usable: bool,
                 effect: int = 0, effect_chance: int = 0, accuracy: int = 0):
        self.number = number
        self.name = name
        self.metronome_usable = metronome_usable
        self.effect = effect
        self.effect_chance = effect_chance
        self.accuracy = accuracy  # 0 = always hits (bypasses accuracy check)


# ---------------------------------------------------------------------------
# Human-readable effect descriptions
# ---------------------------------------------------------------------------

def move_effect(effect: int, effect_chance: int = 0) -> str:
    """Return a human-readable description of an effect number.

    Returns 'unsupported(N)' for effect numbers whose RNG sequence is not
    yet verified. Add entries here as effects are confirmed via GDB.
    """
    match effect:
        case 0:   return "standard"
        case 4:   return f"burn {effect_chance}%"
        case 5:   return f"freeze {effect_chance}%"
        case 6:   return f"paralyze {effect_chance}%"
        case 29:  return "multi-hit"
        case 43:  return "high crit"
        case _:   return f"unsupported({effect})"


# ---------------------------------------------------------------------------
# Effect handlers
# ---------------------------------------------------------------------------

def _effect_standard_damage(ctx: 'BattleContext', move: Move) -> None:
    """Standard damaging move: accuracy check, crit check, damage roll.

    TODO (Phase 2): replace advance_unobservable calls with ctx.hit_crit_or_miss()
    once GDB-verified roll order and thresholds are confirmed.
    """
    ctx.advance_unobservable(3)  # placeholder: hit + crit + damage


def _effect_high_crit(ctx: 'BattleContext', move: Move) -> None:
    """Move with increased critical hit rate (effect 43: Slash, Karate Chop, etc.).

    TODO (Phase 2): implement with adjusted crit threshold via ctx.hit_crit_or_miss().
    """
    ctx.advance_unobservable(3)  # placeholder


def _effect_with_secondary(ctx: 'BattleContext', move: Move) -> None:
    """Standard damage + one secondary effect roll (burn/freeze/paralyze/flinch chance).

    TODO (Phase 2): ctx.hit_crit_or_miss() + ctx.effect_proc(move.effect_chance).
    """
    ctx.advance_unobservable(4)  # placeholder: hit + crit + damage + secondary


def _effect_multi_hit(ctx: 'BattleContext', move: Move) -> None:
    """Multi-strike move (effect 29): accuracy check + hit-count roll + per-hit crits.

    TODO (Phase 2): ctx.hit_crit_or_miss() + ctx.multi_hit().
    """
    ctx.advance_unobservable(4)  # placeholder: hit + count + ~2 crit rolls


def _effect_status_accuracy(ctx: 'BattleContext', move: Move) -> None:
    """Status move that performs an accuracy check (Thunder Wave, Will-O-Wisp, etc.).

    TODO (Phase 2): single accuracy roll only, no crit or damage.
    """
    ctx.advance_unobservable(1)  # placeholder: accuracy check only


def _effect_no_rng(ctx: 'BattleContext', move: Move) -> None:
    """Move that consumes no RNG rolls (Splash, Haze, etc.)."""
    pass


def _effect_unsupported(ctx: 'BattleContext', move: Move) -> None:
    """Fallback for unrecognised effect numbers.

    Emits an Unsupported token and sets battle_state['unsupported'] so the
    caller halts further turn simulation for this seed.
    """
    from .path import Unsupported, PathEnd
    ctx.raw_emit(Unsupported())
    ctx.raw_emit(PathEnd())
    ctx.battle_state['unsupported'] = True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EffectHandler = Callable[['BattleContext', Move], None]

EFFECT_HANDLERS: dict[int, EffectHandler] = {
    0:  _effect_standard_damage,
    4:  _effect_with_secondary,    # burn chance
    5:  _effect_with_secondary,    # freeze chance
    6:  _effect_with_secondary,    # paralyze chance
    29: _effect_multi_hit,
    43: _effect_high_crit,
}


def simulate_move_execution(ctx: 'BattleContext', move: Move) -> None:
    """Dispatch to the appropriate effect handler for the given move.

    Sets battle_state['unsupported'] if the effect is unknown, which signals
    that further RNG tracking for this session should be halted.
    """
    handler = EFFECT_HANDLERS.get(move.effect, _effect_unsupported)
    handler(ctx, move)


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
    gravity = ctx.battle_state.get('gravity_turns', 0) > 0
    excluded = known_moves | {_METRONOME_MOVE_NUM}

    def rng_to_token(ctx: 'BattleContext'):
        from .path import MetronomeMove
        while True:
            roll = ctx.advance_observable()
            move_num = (roll >> 16) % _METRONOME_POOL + 1
            move = moves_by_number.get(move_num)
            if move is None:
                continue
            if not move.metronome_usable:
                continue
            if move_num in excluded:
                continue
            # TODO (Phase 3): check gravity-blocked moves when gravity is active
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
