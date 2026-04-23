"""
safari_compact.py — Compact integer state encoding for high-performance BFS.

Packs the full mutable SafariContext state into a single Python int (47 bits),
enabling O(1) "copy" (integer assignment) and O(1) hashing for visited-set
deduplication. Pure-function simulation replaces SafariContext method calls,
eliminating object allocation in the BFS hot path.

Bit layout
----------
  bits  0–31  rng_state
  bits 32–35  flee_stage_idx  = flee_rate_stages + 6  (range 0–12)
  bits 36–39  cap_stage_idx   = capture_rate_stages + 6 (range 0–12)
  bits 40–44  balls_remaining  (range 0–30)
  bits 45–46  watch_state      (0=WONT_FLEE, 1=WILL_FLEE, 2=FLED, 3=CAPTURED)

Stage index mapping
-------------------
SafariContext stores flee_rate_stages / capture_rate_stages as integers in
[−6, +6] and indexes adjusted_flee_rates / adjusted_catch_rates_b with them
directly (relying on Python's negative-list-index trick). CompactPokemon
reindexes these tuples to a linear 0–12 layout so the compact flee_idx /
cap_idx can be used directly without sign arithmetic.
"""

from __future__ import annotations

from claytonlib.safari import SafariContext, SafariPokemon

# ---------------------------------------------------------------------------
# LCG constants
# ---------------------------------------------------------------------------

_MULT: int = 1103515245
_ADD:  int = 24691
_MASK: int = 0xFFFF_FFFF

# ---------------------------------------------------------------------------
# Bit-field layout
# ---------------------------------------------------------------------------

_FLEE_SH:  int = 32
_CAP_SH:   int = 36
_BALLS_SH: int = 40
_WATCH_SH: int = 45

# ---------------------------------------------------------------------------
# Watch-state codes  (match SafariContextState.value)
# ---------------------------------------------------------------------------

WONT_FLEE: int = 0
WILL_FLEE: int = 1
FLED:      int = 2
CAPTURED:  int = 3

# ---------------------------------------------------------------------------
# CompactPokemon
# ---------------------------------------------------------------------------

class CompactPokemon:
    """Pre-processed, linearly reindexed pokemon rates for compact simulation.

    Args:
        pokemon: Source SafariPokemon instance.
    """
    __slots__ = ('flee_rates', 'catch_rates_b')

    def __init__(self, pokemon: SafariPokemon) -> None:
        # Reindex from Python's negative-index ordering to linear 0–12
        # (index 0 = stage −6, index 6 = stage 0, index 12 = stage +6).
        self.flee_rates: tuple[int, ...] = tuple(
            pokemon.adjusted_flee_rates[s] for s in range(-6, 7)
        )
        self.catch_rates_b: tuple[int, ...] = tuple(
            pokemon.adjusted_catch_rates_b[s] for s in range(-6, 7)
        )


# ---------------------------------------------------------------------------
# Encode / decode
# ---------------------------------------------------------------------------

def encode(ctx: SafariContext) -> int:
    """Pack a SafariContext into a compact integer."""
    return (ctx.rng_state
            | ((ctx.flee_rate_stages + 6)    << _FLEE_SH)
            | ((ctx.capture_rate_stages + 6) << _CAP_SH)
            | (ctx.balls_remaining           << _BALLS_SH)
            | (ctx.state.value               << _WATCH_SH))


# ---------------------------------------------------------------------------
# State predicates (operate directly on compact int)
# ---------------------------------------------------------------------------

def is_watching(s: int) -> bool:
    """True when the pokemon has not yet fled or been captured."""
    return (s >> _WATCH_SH) & 3 < 2


def will_flee(s: int) -> bool:
    """True when the next flee check will immediately transition to FLED."""
    return (s >> _WATCH_SH) & 3 == WILL_FLEE


# ---------------------------------------------------------------------------
# Pure-function simulation
# ---------------------------------------------------------------------------

def sim_bait(s: int, cp: CompactPokemon) -> tuple[int, str]:
    """Simulate throw_bait; return (new_compact_state, outcome_char)."""
    rng      = s & _MASK
    flee_idx = (s >> _FLEE_SH)  & 0xF
    cap_idx  = (s >> _CAP_SH)   & 0xF
    balls    = (s >> _BALLS_SH) & 0x1F
    watch    = (s >> _WATCH_SH) & 0x3

    # 4 pre-turn advances
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    # critical check
    rng = (rng * _MULT + _ADD) & _MASK
    critical = (rng >> 16) % 10 == 0

    # Stage updates (clamped in index space: 0 = stage −6, 12 = stage +6)
    if not critical and cap_idx > 0:
        cap_idx -= 1   # capture stage decreases on non-critical bait
    if flee_idx > 0:
        flee_idx -= 1  # flee stage always decreases on bait

    # 2 ability advances
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK

    # flee check
    if watch == WONT_FLEE:
        rng = (rng * _MULT + _ADD) & _MASK
        if (rng >> 16) % 255 <= cp.flee_rates[flee_idx]:
            watch = WILL_FLEE
    elif watch == WILL_FLEE:
        watch = FLED

    return (rng | (flee_idx << _FLEE_SH) | (cap_idx << _CAP_SH)
            | (balls << _BALLS_SH) | (watch << _WATCH_SH),
            'B' if critical else 'b')


def sim_mud(s: int, cp: CompactPokemon) -> tuple[int, str]:
    """Simulate throw_mud; return (new_compact_state, outcome_char)."""
    rng      = s & _MASK
    flee_idx = (s >> _FLEE_SH)  & 0xF
    cap_idx  = (s >> _CAP_SH)   & 0xF
    balls    = (s >> _BALLS_SH) & 0x1F
    watch    = (s >> _WATCH_SH) & 0x3

    # 4 pre-turn advances
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    # critical check
    rng = (rng * _MULT + _ADD) & _MASK
    critical = (rng >> 16) % 10 == 0

    # Stage updates
    if not critical and flee_idx < 12:
        flee_idx += 1  # flee stage increases on non-critical mud
    if cap_idx < 12:
        cap_idx += 1   # capture stage always increases on mud

    # 2 ability advances
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK

    # flee check
    if watch == WONT_FLEE:
        rng = (rng * _MULT + _ADD) & _MASK
        if (rng >> 16) % 255 <= cp.flee_rates[flee_idx]:
            watch = WILL_FLEE
    elif watch == WILL_FLEE:
        watch = FLED

    return (rng | (flee_idx << _FLEE_SH) | (cap_idx << _CAP_SH)
            | (balls << _BALLS_SH) | (watch << _WATCH_SH),
            'M' if critical else 'm')


def sim_ball(s: int, cp: CompactPokemon) -> tuple[int, str]:
    """Simulate throw_ball; return (new_compact_state, outcome_char)."""
    rng      = s & _MASK
    flee_idx = (s >> _FLEE_SH)  & 0xF
    cap_idx  = (s >> _CAP_SH)   & 0xF
    balls    = (s >> _BALLS_SH) & 0x1F
    watch    = (s >> _WATCH_SH) & 0x3

    # 4 pre-turn advances
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK

    # Shake loop — exits as soon as one check fails (early break is intentional)
    b = cp.catch_rates_b[cap_idx]
    shakes = 0
    for _ in range(4):
        rng = (rng * _MULT + _ADD) & _MASK
        if (rng >> 16) >= b:
            break
        shakes += 1

    balls -= 1

    if shakes == 4:
        return (rng | (flee_idx << _FLEE_SH) | (cap_idx << _CAP_SH)
                | (balls << _BALLS_SH) | (CAPTURED << _WATCH_SH),
                'C')

    if balls == 0:
        return (rng | (flee_idx << _FLEE_SH) | (cap_idx << _CAP_SH)
                | (FLED << _WATCH_SH),   # balls field is already 0
                '0123'[shakes])

    # 2 ability advances + flee check
    rng = (rng * _MULT + _ADD) & _MASK
    rng = (rng * _MULT + _ADD) & _MASK
    if watch == WONT_FLEE:
        rng = (rng * _MULT + _ADD) & _MASK
        if (rng >> 16) % 255 <= cp.flee_rates[flee_idx]:
            watch = WILL_FLEE
    elif watch == WILL_FLEE:
        watch = FLED

    return (rng | (flee_idx << _FLEE_SH) | (cap_idx << _CAP_SH)
            | (balls << _BALLS_SH) | (watch << _WATCH_SH),
            '0123'[shakes])
