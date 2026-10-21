"""coin_flips.py — the Poketch coin toss, and why it identifies a Platinum seed for free.

**The coin toss does not read the LCRNG.** `src/applications/poketch/coin_toss/main.c:158` in
pokeplatinum is ``appData->coin.isHeads = MTRNG_Next() % 2`` — the Mersenne Twister, which
``InitRNG`` seeds with the *same* u32 as the LCRNG (``src/main.c:314-315``). Two consequences, and
both of them are why Platinum's Seed A identification is in some ways nicer than HGSS's:

* **A flip costs zero LCRNG advances.** In HGSS the identification signal (an Elm call) is also
  the thing being counted, so identifying the seed spends the frame you are trying to land on.
  Here the two are different generators: you can flip twenty times and the advance frame has not
  moved.
* **Flips separate RTC-second siblings immediately.** Seeds one RTC second apart differ by exactly
  ``k * 2**24``, which the LCRNG hides for a median of ~19 turns (``battle_compass/candidates.py``,
  ``notes/seed_separation.md``). MT's seeding diffuses that difference over the whole 624-word
  state on the first pass, so the flip sequences are unrelated — the second axis stops being the
  expensive one.

The generator is textbook MT19937 (``src/math_util.c:113-152``): ``init_genrand`` with
``f = 1812433253``, the standard twist and the standard tempering. Python's own ``random`` is also
MT19937 but seeds differently (it hashes through ``init_by_array``), so it cannot stand in — hence
the ~30 lines here.

Odd is heads, in both the ROM (``% 2`` of the tempered word, 1 == heads) and PokeFinder
(``Core/Util/Utilities.cpp:151``, ``(rng.next() & 1) == 0 ? "T" : "H"``).

**There is no leading offset.** PokeFinder's ``coinFlips`` builds ``MTFast rng(seed, 0, 20)`` —
seed, *advances = 0*, twenty flips — and the decomp agrees: every ``MTRNG_Next`` consumer reachable
before the Poketch is a save-entry init function (``src/game_start.c:158,162``,
``src/special_encounter.c:22-23``), which runs on a new game and not on a continue. So flip 1 is
MT output 1, and ``flip_sequence`` needs no skip count the way ``elm_calls`` needs REL's.
"""
from __future__ import annotations

# MT19937, in the ROM's own constant names (src/math_util.c:86-102).
_N = 624
_M = 397
_MATRIX_A = 0x9908B0DF
_UPPER_MASK = 0x80000000
_LOWER_MASK = 0x7FFFFFFF
_INIT_F = 1812433253
_MASK32 = 0xFFFFFFFF

#: Flip characters, in the spelling PokeFinder and every guide use.
HEADS = "H"
TAILS = "T"
FLIP_CHARS = (TAILS, HEADS)


class MT19937:
    """The ROM's Mersenne Twister, seeded the way ``MTRNG_SetSeed`` seeds it.

    Deliberately a class rather than a generator function: narrowing wants to pull flips one at a
    time and stop as soon as a candidate contradicts, and a stateful object makes "one more flip"
    the cheap operation it should be.
    """

    __slots__ = ("_state", "_index")

    def __init__(self, seed: int):
        state = [0] * _N
        state[0] = seed & _MASK32
        for i in range(1, _N):
            prev = state[i - 1]
            state[i] = (_INIT_F * (prev ^ (prev >> 30)) + i) & _MASK32
        self._state = state
        # MTRNG_SetSeed leaves the index at N, so the first next() regenerates. Matching that
        # exactly matters: an index of 0 here would hand back the raw seed words untwisted.
        self._index = _N

    def _twist(self) -> None:
        state = self._state
        for i in range(_N):
            y = (state[i] & _UPPER_MASK) | (state[(i + 1) % _N] & _LOWER_MASK)
            state[i] = state[(i + _M) % _N] ^ (y >> 1) ^ (_MATRIX_A if y & 1 else 0)
        self._index = 0

    def next(self) -> int:
        """The next tempered 32-bit output."""
        if self._index >= _N:
            self._twist()
        y = self._state[self._index]
        self._index += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y & _MASK32


def flip_sequence(seed: int, count: int = 20) -> str:
    """`count` coin flips for `seed`, as a string of ``H``/``T``.

    The Platinum counterpart of ``calibration_tools.elm_calls`` — and note what it does *not*
    take: no state to continue from and no skip count, because there is no REL to walk past and
    nothing consumes MT before the player can open the app (see the module docstring).

    20 is PokeFinder's default and about twice what narrowing a normal window needs: each flip is
    one bit, so ~10 flips separate a few hundred candidates.
    """
    if count < 0:
        raise ValueError(f"flip count cannot be negative: {count}")
    rng = MT19937(seed)
    return "".join(FLIP_CHARS[rng.next() & 1] for _ in range(count))


def clean_flips(observed: str) -> str:
    """Keep only the H/T characters (upper-cased) from a raw flip-input string.

    Mirrors ``safari_advance.clean_elm``, and for the same reason: the player types into a text
    box and may well separate flips with spaces or commas.
    """
    return "".join(ch for ch in observed.upper() if ch in FLIP_CHARS)


def flips_match(seed: int, observed: str) -> bool:
    """Whether `seed` could have produced `observed` as its opening flips.

    A **prefix** test, not a search: unlike Elm calls, where you join a sequence already in
    progress at an unknown offset, the coin app is opened fresh and flip 1 is MT output 1. So the
    observed string anchors at the start, and the first mismatched flip rules the seed out.

    Only as many outputs as `observed` needs are generated, which is what makes narrowing cheap
    across a few hundred candidates.
    """
    obs = clean_flips(observed)
    if not obs:
        return True
    rng = MT19937(seed)
    for expected in obs:
        if FLIP_CHARS[rng.next() & 1] != expected:
            return False
    return True
