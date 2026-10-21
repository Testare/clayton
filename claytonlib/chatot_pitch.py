"""chatot_pitch.py — the readable Platinum advance: one chatot cry, one advance, one pitch.

Platinum has no Elm calls, so the per-advance signal is the **pitch of a Chatot's recorded cry**.
From pokeplatinum ``src/sound_chatot.c:77``, inside ``Sound_Impl_PlayChatotCry``::

    u16 speedVariance = LCRNG_Next() % CHATOT_CRY_SPEED_VARIANCE;   // 8192
    ...
    param.speed = WAVE_OUT_SPEED(1.0) + speedVariance;              // 32768 + variance

So **one cry spends exactly one LCRNG advance** (which is also why this project's HGSS "chatot
flip" has always counted as two — two summary screens, two cries), and the playback speed runs
from ×1.000 to ×1.250, a shade under four semitones.

``LCRNG_Next()`` returns ``state >> 16``, so the pitch is a function of the same 16-bit roll an Elm
call reads ``% 3``. Scaled to the 0-99 figure everyone quotes it is
``((roll % 8192) * 100) >> 13`` — which is PokeFinder's ``Core/Gen4/States/State4.hpp:49``
verbatim. That formula and the ROM reading above were derived independently and agree exactly.

**The buckets are PokeFinder's** (``Core/Util/Utilities.cpp:72-96``): five equal 20-wide bands over
the 0-99 scale. Matching them exactly is the point — a pitch read off one tool has to mean the same
thing in the other.

**A pitch is never an input.** The player does not report pitches and nothing here parses one:
they already know their advance frame by arithmetic — they start on the venue's starting frame and
count what they do (a Journal flip is 2 advances, a Chatot cry is 1). The pitch exists so the
*margin* of a planned route can be shown to them and they can hear whether they landed where the
plan said. It is an error check on a number already known, not a measurement that derives it. So
everything below is display: a value, a bucket, and two renderers.

Two traps worth carrying into the UI:

* **The roll only happens when a RECORDED cry is playable.** ``Sound_IsRecordedChatotCryPlayable``
  (``src/sound_chatot.c:39-57``) gates it, and the recording is **one per save file**
  (``SaveData_GetChatotCry``), not per Pokemon. With no valid recording the default Chatot cry
  plays and **no advance happens at all** — so a player can flip happily and stand still.
* **Reading pitch by ear is error-prone**, which the Smogon guide says outright: *"It may take
  multiple tries until you can match the pitches with their categories, and even then there's room
  for error."* That is an argument for a SHORT margin — the fewer cries a player has to judge, the
  less often a correct route reads as a wrong one.
"""
from __future__ import annotations

from claytonlib.safari import advance_rng

#: ``CHATOT_CRY_SPEED_VARIANCE`` — the modulus the ROM takes of the roll.
PITCH_MODULUS = 8192
#: The 0-99 scale the community and PokeFinder quote. ``>> 13`` is the division by PITCH_MODULUS.
PITCH_SCALE = 100
_PITCH_SHIFT = 13

#: Bucket label -> the value it starts at. Five equal 20-wide bands; `H` runs to 99.
BUCKET_BOUNDS: tuple[tuple[str, int], ...] = (
    ("L", 0), ("ML", 20), ("M", 40), ("MH", 60), ("H", 80),
)
BUCKETS: tuple[str, ...] = tuple(label for label, _ in BUCKET_BOUNDS)

def pitch_value(roll: int) -> int:
    """The 0-99 pitch for a 16-bit `roll` (i.e. ``state >> 16``).

    ``((roll % 8192) * 100) >> 13``. Note the top three bits of the roll are discarded by the
    modulus, so a pitch is 13 bits of information at best and ~2.3 bits as a bucket.
    """
    return ((roll % PITCH_MODULUS) * PITCH_SCALE) >> _PITCH_SHIFT


def bucket_of(value: int) -> str:
    """The ``L``/``ML``/``M``/``MH``/``H`` label for a 0-99 pitch."""
    if not 0 <= value < PITCH_SCALE:
        raise ValueError(f"pitch out of range: {value}")
    label = BUCKETS[0]
    for name, start in BUCKET_BOUNDS:
        if value >= start:
            label = name
    return label


def format_pitch(value: int) -> str:
    """The display form: the bucket with the exact number in parentheses, e.g. ``M (41)``.

    The label is what the player listens for; the number is there for when they want to be precise,
    or to tell apart two cries that landed in the same bucket [design, round 1]. PokeFinder renders
    the same pair as ``M 41``; the parentheses are the only difference.
    """
    return f"{bucket_of(value)} ({value})"


def pitch_values(seed: int, count: int) -> tuple[int, ...]:
    """`count` pitches continuing from LCRNG `seed`.

    The counterpart of ``calibration_tools.elm_calls``, and it follows the same convention: the
    state is **advanced first**, so ``pitch_values(...)[i]`` is the pitch heard on the advance from
    frame ``i`` to frame ``i + 1``.
    """
    if count < 0:
        raise ValueError(f"pitch count cannot be negative: {count}")
    out = []
    state = seed
    for _ in range(count):
        state = advance_rng(state)
        out.append(pitch_value(state >> 16))
    return tuple(out)


def pitch_buckets(seed: int, count: int) -> tuple[str, ...]:
    """`count` pitch *buckets* for `seed` — the symbol alphabet frame identification matches on."""
    return tuple(bucket_of(v) for v in pitch_values(seed, count))


def format_sequence(values: tuple[int, ...] | list[int]) -> str:
    """A whole sequence as display tokens, space-separated: ``M (41) H (88) L (7)``."""
    return " ".join(format_pitch(v) for v in values)
