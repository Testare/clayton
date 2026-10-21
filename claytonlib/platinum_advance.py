"""platinum_advance.py — Seed A advance-frame identification and routing in Platinum.

The Platinum counterpart of the Seed-A half of :mod:`claytonlib.safari_advance`, built on that
module's primitives rather than reimplementing them. What differs is only the signal and the
labels; the arithmetic is shared, and that is not a coincidence — **Platinum has both halves of
the HGSS route, in the same sizes**:

===================  ==========================  ================================
\\                    HGSS                        Platinum
===================  ==========================  ================================
Bulk, blind          chatot flip — 2 advances    **Journal flip — 2 advances**
Margin, readable     Elm call — 1 advance        **chatot cry — 1 advance**
===================  ==========================  ================================

A Journal flip is 2 advances ("frames are advanced by 2. Flipping your Journal to another page
with a similar entry will also advance it by 2") and a Chatot summary access is 1
([Smogon part 2](https://www.smogon.com/ingame/rng/dpphgss_rng_part2)). So
``safari_advance.plan_advances`` is correct as written and is reused unchanged — its
``chatot_flips`` field counts Journal flips here, and ``elm_before_scent`` counts chatot cries.

Two things that genuinely differ, and both are documented where they bite:

* **There is no REL**, so the leading offset is not a calculation. Identification passes 0 and
  lets the search find the observation wherever it sits; planning wants a per-venue constant
  (``notes/platinum.md`` section 3.4), which is why `start_frame` is an argument and not a
  derivation.
* **The frame is counted, not identified.** HGSS pins its advance frame by hearing Elm calls and
  searching for them in the seed's own sequence. Platinum has no such search, because the player
  is not reporting anything: they start on the venue's starting frame and count their own actions.
  The pitch margin is how they *check* that count — which is why `plan_route` renders pitches and
  nothing here parses one.

  That makes ambiguity matter more here than in HGSS, not less: the margin is the only error
  detection the route has. It is asked in **buckets**, because "would a 1-2 frame miscount be
  invisible?" is a question about what the player would hear.
"""
from __future__ import annotations

from claytonlib.chatot_pitch import bucket_of, format_sequence, pitch_values
from claytonlib.safari_advance import (
    AdvancePlan, margin_ambiguous, margin_guide, plan_advances,
)

#: Advances per Journal flip. The same 2 as an HGSS chatot flip, which is why the plan arithmetic
#: needed no change -- see the module docstring.
JOURNAL_FLIP_ADVANCES = 2

#: The advance frame a freshly loaded seed sits on.
#:
#: Zero, because Clayton counts advances from the seed itself — advance 0 is the raw state, before
#: anything has been spent. PokeFinder agrees (`Core/Gen4/Generators/StaticGenerator4.cpp:57`
#: counts `cnt` from 0 on top of an `initialAdvances` that defaults to 0) [verified].
#:
#: **The published guides are 1-based, so their frame numbers are one higher than ours.** RNG
#: Reporter, which the Smogon guide is written against, calls the first frame 1 — so its
#: "starting frame will be 23" for the Distortion World is advance **22** here, and its 12 is
#: our 11 [derived; the PokeFinder half is verified, the RNG Reporter half is the convention the
#: guides use and is worth one empirical check before a venue constant is trusted].
#:
#: Glass has no venue, so a Seed is simply loaded and routed from 0. A per-venue starting frame
#: is a Hunts concern (clayton-6xu.3.5), which is why `plan_route` takes `start_frame` but Glass
#: never sets it.
PLATINUM_START_FRAME = 0

#: Default readable margin, in chatot cries. Three is the HGSS default for Elm calls and the same
#: reasoning applies: long enough to read uniquely, short enough to get right by ear. Pitch is
#: harder to judge than a letter, so if anything this wants to be *shorter* rather than longer --
#: a question for the first real run, not for this module (notes/platinum.md section 9.2).
DEFAULT_PITCH_MARGIN = 3


def pitch_context(seed: int, count: int = 128, start_frame: int = 0) -> tuple[int, tuple[int, ...]]:
    """``(start_frame, pitches)`` for `seed` — the Platinum analogue of `advance_context`.

    Returns the same shape as its HGSS sibling so the shared primitives take either without
    knowing which game they are serving. The difference is that the first element is **given**,
    not computed: HGSS derives REL's cost from the seed, and Platinum's starting frame is a
    per-venue constant that nothing in the seed can tell you — and with no identification search
    to fall back on, it is the only anchor the player's count has.

    ``pitches[i]`` is the 0-99 pitch heard on the advance from frame ``start_frame + i`` to
    ``start_frame + i + 1``.
    """
    return start_frame, pitch_values(seed, count)


def _same_bucket(a: int, b: int) -> bool:
    """Whether two true pitches would sound the same to the player.

    What `margin_ambiguous` compares through. Buckets rather than exact values, because the
    question it asks — would a 1-2 frame miscount be invisible? — is about what gets *heard*.
    """
    return bucket_of(a) == bucket_of(b)


def plan_route(seed: int, target_frame: int, current_frame: int = PLATINUM_START_FRAME,
               margin: int = DEFAULT_PITCH_MARGIN, start_frame: int = 0,
               count: int | None = None) -> dict:
    """A Journal-flip + chatot-cry route from `current_frame` to `target_frame`.

    `current_frame` defaults to :data:`PLATINUM_START_FRAME` and is **not asked for** in Glass:
    there is no frame-finding step, because there is nothing to find. You load the seed, you are
    on frame 0, and you count from there.

    Shares ``plan_advances`` with HGSS, so the arithmetic — how much of the distance is bulk, how
    much is margin, where you land — is literally the same code. What this adds is the Platinum
    rendering: the guide shows pitches as ``M (41)``, and the labels say Journal flip and chatot
    cry rather than chatot flip and Elm call.

    `count` defaults to covering the whole approach with room to overshoot.
    """
    plan = plan_advances(current_frame, target_frame, margin=_even_bulk_margin(
        current_frame, target_frame, margin), method="grass")   # `method` labels a Safari verb
    horizon = count if count is not None else target_frame + 20
    offset, pitches = pitch_context(seed, count=horizon, start_frame=start_frame)
    # Buckets for the surrounding context, bucket + exact number for the margin itself
    # [design, round 1]: the margin is the part you listen to, and the context only has to be
    # recognisable if you land early or overshoot.
    guide, truncated = margin_guide(offset, pitches, plan,
                                    render=_render_buckets, render_bracket=format_sequence)
    return {
        "current_frame": plan.current_frame,
        "target_frame": plan.encounter_frame,
        "total_advances": plan.total_advances,
        # Journal flips, in the field `plan_advances` calls chatot_flips -- the unit is 2 advances
        # in both games, so the number is the same and only the noun changes. An INT here, not
        # the float that field holds: `_even_bulk_margin` guarantees the bulk is even, so there
        # is never a half flip to report (and no action that could perform one).
        "journal_flips": int(plan.chatot_flips),
        "journal_advances": plan.chatot_advances,
        "cries_before_target": plan.elm_before_scent,
        "land_frame": plan.land_frame,
        "margin": plan.margin,
        "guide": guide,
        "truncated": truncated,
        "ambiguous": margin_ambiguous(offset, pitches, plan, same=_same_bucket),
        "description": describe_route(plan, guide),
    }


def _render_buckets(values) -> str:
    """Context pitches as bare buckets: `MH L H M`."""
    return " ".join(bucket_of(v) for v in values)


def _even_bulk_margin(current_frame: int, target_frame: int, margin: int) -> int:
    """The margin to plan with, so that the Journal-flip half comes out EVEN.

    There is no half Journal flip. HGSS tolerates an odd bulk because half a chatot flip is one
    cry and therefore a real action; a Journal page turn is 2 advances or nothing, so an odd bulk
    is unperformable. The leftover advance becomes one more chatot cry, which costs nothing and
    lengthens the readable margin by one — strictly the better place for it.
    """
    total = target_frame - current_frame
    if total <= 0:
        return margin
    cries = min(total, margin)
    if (total - cries) % 2:
        cries += 1
    return cries


def describe_route(plan: AdvancePlan, guide: str | None = None) -> str:
    """A human-readable instruction block, in Platinum's nouns.

    Deliberately not ``safari_advance.describe_plan``: that one ends every route in an encounter
    verb (Sweet Scent, cast the rod), which is true of a Safari expedition and meaningless for a
    Seed in Glass. Glass already learned this lesson once — see the "As built" list in
    notes/glass.md, where a backwards route is answered by the page for the same reason.
    """
    lines = [
        f"On advance frame {plan.current_frame}; want to reach frame {plan.encounter_frame}.",
        f"  Advances to go: {plan.total_advances}",
    ]
    if plan.chatot_advances > 0:
        flips = int(plan.chatot_flips)
        lines.append(
            f"  1. {flips} Journal {'flip' if plan.chatot_advances == 2 else 'flips'} "
            f"({plan.chatot_advances} advances) "
            f"-> land on frame {plan.land_frame}")
    else:
        lines.append("  1. (no Journal flips needed)")
    cries = plan.elm_before_scent
    lines.append(
        f"  2. {cries} Chatot {'cry' if cries == 1 else 'cries'} "
        f"-> frame {plan.encounter_frame}.")
    if guide is not None:
        lines.append(f"  Guide: {guide}   (]! = you are on frame {plan.encounter_frame})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Candidate seeds (the flips half of identification)
# ---------------------------------------------------------------------------
#
# The counterpart of `calibration_tools.generate_roamer_candidates_near`. PokeFinder draws exactly
# this fork in one line -- `roamer ? getCalls(seed, skips) : coinFlips(seed)`
# (`Core/Gen4/SeedTime4.cpp:77`) -- so the shape is established rather than invented, and a player
# moving between the two tools sees the same two columns.
#
# What carries over from the HGSS version unchanged: the (second x delay) grid itself, both window
# sizes, and `match_parity`. The seed formula is identical in Platinum (verified), so the grid is
# the same grid. What has no Platinum meaning: `prev_routes` and `rng_calls`, because there is no
# roamer relocation at game load to walk past.

def generate_flip_candidates_near(
    target_time, target_delay: int, seconds_window: int, delay_window: int,
    flip_count: int = 20, pitch_count: int = 12, match_parity: bool = False,
) -> list[dict]:
    """Every seed within ±`seconds_window` seconds and ±`delay_window` delays of the target,
    annotated with its coin flips and its opening chatot pitches.

    Rows are grouped by time (chronological) then delay ascending, exactly as the HGSS table is,
    so one renderer serves both. Keys: ``seed``, ``time``, ``delay``, ``sec_delta``,
    ``delay_delta``, ``flips``, ``pitches`` (the 0-99 values) and ``pitch_display``.

    Both signals are carried because they answer different questions and the player uses them in
    sequence: flips say *which seed* (at no cost to the advance frame), pitches then say *which
    frame* of it you are on.
    """
    import datetime as dt

    from claytonlib.calibration_tools import seed_for
    from claytonlib.coin_flips import flip_sequence

    by_seed: dict[int, tuple] = {}
    for sec in range(-seconds_window, seconds_window + 1):
        when = target_time + dt.timedelta(seconds=sec)
        for delay in range(target_delay - delay_window, target_delay + delay_window + 1):
            if delay < 0:
                continue
            if match_parity and (delay % 2) != (target_delay % 2):
                continue
            seed = seed_for(when, delay)
            # Two (time, delay) pairs can land on one seed; keep the nearest-to-target spelling,
            # as the roamer table does, so the deltas shown are the smallest true ones.
            key = (abs(delay - target_delay), abs(sec), seed)
            if seed in by_seed and by_seed[seed][0] <= key:
                continue
            pitches = pitch_values(seed, pitch_count)
            by_seed[seed] = (key, {
                "seed": seed,
                "time": when,
                "delay": delay,
                "sec_delta": sec,
                "delay_delta": delay - target_delay,
                "flips": flip_sequence(seed, flip_count),
                "pitches": pitches,
                "pitch_display": format_sequence(pitches),
            })
    rows = [entry for _, entry in by_seed.values()]
    rows.sort(key=lambda row: (row["time"], row["delay"]))
    return rows


def filter_flips(rows: list[dict], observed: str) -> list[dict]:
    """Keep the candidate rows whose flips start with `observed`.

    A **prefix** filter, unlike the Elm one: the coin app is opened fresh, so flip 1 is MT output
    1 and there is no unknown join offset to search for (see `coin_flips.flips_match`). That is
    also why this narrows so fast — every flip is a full bit rather than a position in a search.
    """
    from claytonlib.coin_flips import clean_flips

    wanted = clean_flips(observed)
    if not wanted:
        return list(rows)
    return [row for row in rows if row["flips"].startswith(wanted)]
