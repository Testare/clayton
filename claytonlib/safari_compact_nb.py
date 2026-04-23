"""
safari_compact_nb.py — Optional numba-JIT simulation functions.

Provides numba @njit versions of sim_bait, sim_mud, sim_ball that operate
on the same compact integer state as safari_compact.py but execute at native
speed (~2.5x faster overall in machete_all).

Return convention (differs from Python sims):
  sim_bait_nb / sim_mud_nb → (s2: int, is_critical: int)   0=normal 1=critical
  sim_ball_nb               → (s2: int, shakes: int)        4=captured  -1=fled(no balls)

Imported conditionally by machete_all; if numba is not installed, machete_all
falls back to pure-Python sims.  First call triggers JIT compilation (~seconds).
"""

try:
    from numba import njit
    import numpy as np

    @njit
    def sim_bait_nb(s, flee_rates, catch_rates_b):
        M, A, MK = 1103515245, 24691, 0xFFFFFFFF
        rng = s & MK
        fi  = (s >> 32) & 0xF
        ci  = (s >> 36) & 0xF
        ba  = (s >> 40) & 0x1F
        w   = (s >> 45) & 0x3
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        rng=(rng*M+A)&MK
        crit = (rng >> 16) % 10 == 0
        if not crit and ci > 0: ci -= 1
        if fi > 0: fi -= 1
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        if w == 0:
            rng=(rng*M+A)&MK
            w2 = 1 if (rng >> 16) % 255 <= flee_rates[fi] else 0
        else:
            w2 = 2
        return rng | (fi << 32) | (ci << 36) | (ba << 40) | (w2 << 45), 1 if crit else 0

    @njit
    def sim_mud_nb(s, flee_rates, catch_rates_b):
        M, A, MK = 1103515245, 24691, 0xFFFFFFFF
        rng = s & MK
        fi  = (s >> 32) & 0xF
        ci  = (s >> 36) & 0xF
        ba  = (s >> 40) & 0x1F
        w   = (s >> 45) & 0x3
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        rng=(rng*M+A)&MK
        crit = (rng >> 16) % 10 == 0
        if not crit and fi < 12: fi += 1
        if ci < 12: ci += 1
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        if w == 0:
            rng=(rng*M+A)&MK
            w2 = 1 if (rng >> 16) % 255 <= flee_rates[fi] else 0
        else:
            w2 = 2
        return rng | (fi << 32) | (ci << 36) | (ba << 40) | (w2 << 45), 1 if crit else 0

    @njit
    def sim_ball_nb(s, flee_rates, catch_rates_b):
        M, A, MK = 1103515245, 24691, 0xFFFFFFFF
        rng = s & MK
        fi  = (s >> 32) & 0xF
        ci  = (s >> 36) & 0xF
        ba  = (s >> 40) & 0x1F
        w   = (s >> 45) & 0x3
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        b = catch_rates_b[ci]
        shakes = 0
        rng=(rng*M+A)&MK
        if (rng >> 16) < b:
            shakes = 1; rng=(rng*M+A)&MK
            if (rng >> 16) < b:
                shakes = 2; rng=(rng*M+A)&MK
                if (rng >> 16) < b:
                    shakes = 3; rng=(rng*M+A)&MK
                    if (rng >> 16) < b: shakes = 4
        ba -= 1
        if shakes == 4:
            return rng | (fi << 32) | (ci << 36) | (ba << 40) | (3 << 45), 4
        if ba == 0:
            return rng | (fi << 32) | (ci << 36) | (0 << 40) | (2 << 45), -1
        rng=(rng*M+A)&MK; rng=(rng*M+A)&MK
        if w == 0:
            rng=(rng*M+A)&MK
            w2 = 1 if (rng >> 16) % 255 <= flee_rates[fi] else 0
        else:
            w2 = 2
        return rng | (fi << 32) | (ci << 36) | (ba << 40) | (w2 << 45), shakes

    def make_arrays(cp):
        """Convert CompactPokemon rate tuples to numpy int64 arrays for numba."""
        return (np.array(cp.flee_rates,    dtype=np.int64),
                np.array(cp.catch_rates_b, dtype=np.int64))

except ModuleNotFoundError:
    # numba not installed — module imports cleanly but exports nothing.
    # machete_all catches the resulting ImportError and falls back to Python sims.
    pass
