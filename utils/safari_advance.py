"""Section A of the Safari Compass Calibration notebook: Seed-A advance-frame work.

Terminology (see notes/safari_calibration_notebook.md):

  * The seed loaded from the clock is *Seed A*, the initial RNG state for the
    overworld stream (encounters, roamer relocation, Elm phone calls).
  * An **advance frame** ("frame" here) is the number of times Seed A's state has
    been advanced via ``advance_rng`` since the seed was generated.  Frame 0 is
    the seed itself.  Advances are driven by *player actions*, not the clock, so
    walking to a target frame is how we choose *which* pokemon we encounter
    (e.g. frame 11 -> L44 Metang, frame 81 -> shiny Metang).

Roamer relocation (REL) consumes a fixed number of advances -- ``rng_calls`` from
``calibration_tools.roamer_positions`` -- so right after REL the player is on
frame ``rng_calls``.  After that **each Elm phone call is exactly one advance**
(``calibration_tools.elm_calls``), so the P/E/K calls you read off in-game pin
down which advance frame you're currently on.

This module owns the *frame identification* half of Section A (ctd.1): given the
seed's Elm sequence and the calls heard so far, which advance frame are we on?
The advance-*planning* half (chatot flips, Sweet-Scent margin guide -- ctd.2)
builds on the frame this reports.

The core (``frame_candidates``) is pure and takes only ``rng_calls`` + the Elm
string, so it is unit-testable without generating real seeds.
"""
from dataclasses import dataclass

try:                                       # utils/ on sys.path (tests, `import safari_advance`)
    import calibration_tools as ct
except ModuleNotFoundError:                # imported as a package (`utils.safari_advance`, notebooks)
    from utils import calibration_tools as ct

# Re-used so callers don't have to reach into calibration_tools for the basics.
elm_calls = ct.elm_calls
roamer_positions = ct.roamer_positions
_ELM_CHARS = ct._ELM_CHARS


def clean_elm(observed):
    """Keep only the P/E/K characters (upper-cased) from a raw Elm-input string.

    Mirrors calibration_tools.parse_elm_input's character filtering (spaces,
    commas, etc. are ignored) but without the 'M' manual-escape handling, since
    frame identification always works within a single, already-known seed.
    """
    return "".join(ch for ch in observed.upper() if ch in _ELM_CHARS)


def _all_start_positions(haystack, needle):
    """Every start index ``p`` where ``haystack[p:p+len(needle)] == needle``.

    Overlapping matches are all reported.  An empty needle matches at every
    position ``0..len(haystack)`` inclusive (the "no calls heard yet" case: the
    player could be at any offset into the sequence).
    """
    if needle == "":
        return list(range(len(haystack) + 1))
    positions = []
    start = haystack.find(needle)
    while start != -1:
        positions.append(start)
        start = haystack.find(needle, start + 1)
    return positions


def frame_candidates(rng_calls, elm, observed, max_offset=None):
    """The advance frame(s) consistent with hearing ``observed`` in ``elm``.

    Parameters
    ----------
    rng_calls:
        Advances REL consumed (the frame the player is on right after REL).
    elm:
        The seed's Elm-call string starting at frame ``rng_calls`` -- i.e.
        ``elm[i]`` is the call heard on the advance from frame ``rng_calls + i``
        to ``rng_calls + i + 1``.  Generate it with ``elm_calls(state, count)``
        where ``state`` is ``roamer_positions(...)[2]``.
    observed:
        The P/E/K calls heard so far (raw input is cleaned via ``clean_elm``).
    max_offset:
        If given, only consider matches whose start position ``p`` is
        ``<= max_offset`` -- encodes "we paused within N advances of REL" and
        drops spurious late matches.

    Returns a sorted list of candidate *current* advance frames.  Hearing a
    substring that starts at position ``p`` (length ``k``) leaves the player on
    frame ``rng_calls + p + k``.  One element => the frame is pinned; more than
    one => keep listening for Elm calls; empty => the calls don't occur in the
    sequence (bad input, or ``elm`` too short).
    """
    obs = clean_elm(observed)
    positions = _all_start_positions(elm, obs)
    if max_offset is not None:
        positions = [p for p in positions if p <= max_offset]
    return sorted(rng_calls + p + len(obs) for p in positions)


def advance_context(seed, prev_routes, count=128, present=None):
    """(rng_calls, elm) for ``seed`` -- REL advances plus its Elm-call string.

    Convenience wrapper over ``roamer_positions`` + ``elm_calls`` so a caller
    with a raw seed (rather than a candidate row) can feed ``frame_candidates``.
    ``count`` is generated long enough to cover the whole approach to a target
    frame (planning, ctd.2), not just identification.
    """
    _routes, rng_calls, state = roamer_positions(seed, prev_routes, present=present)
    elm = "".join(elm_calls(state, count))
    return rng_calls, elm


def context_from_row(row):
    """(rng_calls, elm) from a calibration_tools candidate row (dict).

    Rows from ``generate_roamer_candidates_near`` carry ``rng_calls`` and ``elm``
    already; this just pulls them out so the notebook can hand a chosen row
    straight to ``identify_frame`` / ``frame_candidates``.
    """
    return row["rng_calls"], row["elm"]


# --------------------------------------------------------------------------- #
# Interactive driver (prompt / print)                                          #
# --------------------------------------------------------------------------- #
def identify_frame(rng_calls, elm, observed="", max_offset=None, input_fn=None):
    """Interactively pin the current advance frame, looping until one remains.

    Seeds the search with any ``observed`` calls already entered (e.g. the ones
    used to identify the seed), then prompts for more P/E/K calls until a single
    frame is consistent.  Returns that frame (int), or ``None`` if the calls
    stopped matching the sequence.

    ``input_fn`` defaults to the (keyboard-fixup-patched) builtins.input so the
    notebook behaves like the rest of calibration_tools; tests pass their own.
    """
    if input_fn is None:
        ct.install_input_fixup()  # ipykernel resets builtins.input per cell
        import builtins
        input_fn = builtins.input

    heard = clean_elm(observed)
    while True:
        frames = frame_candidates(rng_calls, elm, heard, max_offset=max_offset)
        if len(frames) == 1:
            print(f"Elm calls: {heard or '(none)'}  ->  advance frame {frames[0]}")
            return frames[0]
        if not frames:
            print(f"No advance frame matches '{heard}' -- check the calls "
                  f"(sequence has {len(elm)} entries from frame {rng_calls}).")
            return None
        print(f"Elm calls: {heard or '(none)'}  ->  {len(frames)} possible "
              f"frames: {frames}")
        raw = input_fn("More Elm calls (type P/E/K as heard): ")
        add = clean_elm(raw)
        if not add:
            print("  (no P/E/K read; still ambiguous.)")
            continue
        heard += add


# --------------------------------------------------------------------------- #
# Advance planning: get from the current frame to a Metang-encounter frame     #
# (chatot flips for the bulk, then a verifiable Elm-call margin) -- ctd.2       #
# --------------------------------------------------------------------------- #
# The advance frame whose roll yields the shiny Metang for the reference setup;
# the true target when we hit the intended seed exactly (configurable).
DEFAULT_TARGET_FRAME = 81

# We approach the encounter with a small margin of Elm calls (each a verifiable
# single advance) rather than chatot-flipping all the way, because a chatot flip
# (two advances) can't be read back to confirm the frame, inviting off-by-one.
DEFAULT_ELM_MARGIN = 3


@dataclass
class AdvancePlan:
    """A recipe to reach ``encounter_frame`` from ``current_frame``.

    You Sweet Scent while standing on ``scent_frame`` -- which is the
    ``encounter_frame`` itself (verified in-game against Pokefinder: pressing on
    ``encounter_frame - 1`` lands one frame early).  The bulk of the distance is
    covered by ``chatot_flips`` (two advances each; a trailing half-flip = one
    advance is fine), landing on ``land_frame``; from there ``elm_before_scent``
    Elm calls -- the verifiable margin -- carry you to ``scent_frame``.
    """
    current_frame: int
    encounter_frame: int
    scent_frame: int             # the frame you stand on when pressing Sweet Scent (= encounter_frame)
    total_advances: int          # current_frame -> scent_frame
    chatot_flips: float          # may end in .5 (a half flip = one advance)
    chatot_advances: int
    elm_before_scent: int        # the readable margin (<= margin; = margin when chatot used)
    land_frame: int              # frame after the chatot flips, before the margin calls
    margin: int


def plan_advances(current_frame, encounter_frame, margin=DEFAULT_ELM_MARGIN):
    """Plan the advances from ``current_frame`` to ``encounter_frame``.

    ``encounter_frame`` is the frame whose roll you want (e.g. 81 for the shiny
    Metang).  You Sweet Scent while standing ON that frame (empirically -- pressing
    a frame early misses by one).  Raises ValueError if ``encounter_frame`` is
    already behind ``current_frame`` (overshot -- you'd need to reset).

    When more than ``margin`` advances remain, chatot flips close the gap to
    ``margin`` Elm calls short of the scent frame; otherwise the whole (short)
    distance is Elm calls and no chatot flips are used.
    """
    scent_frame = encounter_frame   # press Sweet Scent standing on the encounter frame
    total = scent_frame - current_frame
    if total < 0:
        raise ValueError(
            f"already past the target: on frame {current_frame}, but Sweet Scent "
            f"for encounter frame {encounter_frame} must fire on frame {scent_frame}")
    elm_before = min(total, margin)
    chatot_advances = total - elm_before
    # A single (or half) chatot flip -- 1 or 2 leftover advances -- isn't worth the unverifiable
    # flip; just do those as extra Elm calls (a 4- or 5-call margin), the mirror of shrinking the
    # margin below `margin` when that's all the distance there is.
    if 0 < chatot_advances <= 2:
        elm_before = total
        chatot_advances = 0
    return AdvancePlan(
        current_frame=current_frame,
        encounter_frame=encounter_frame,
        scent_frame=scent_frame,
        total_advances=total,
        chatot_flips=chatot_advances / 2,
        chatot_advances=chatot_advances,
        elm_before_scent=elm_before,
        land_frame=current_frame + chatot_advances,
        margin=margin,
    )


def margin_guide(rng_calls, elm, plan, n_before=5, n_after=3):
    """The Elm-call guide string around the approach, e.g. ``PEEEP[KPE]!KEP``.

    ``n_before`` calls precede the bracket (in case you land early), the bracket
    holds the ``elm_before_scent`` calls you should hear approaching the target,
    ``!`` marks where to Sweet Scent (on ``scent_frame`` = the encounter frame),
    and ``n_after`` trailing calls follow (in case you overshoot).

    ``elm[i]`` is the call heard leaving frame ``rng_calls + i``, so the bracket's
    first call leaves ``land_frame``.  If ``elm`` is too short to reach the scent
    point the guide is truncated and a warning printed.
    """
    j_land = plan.land_frame - rng_calls
    j_scent = j_land + plan.elm_before_scent  # index just past the bracket
    if j_land < 0:
        raise ValueError(
            f"land_frame {plan.land_frame} precedes REL end (frame {rng_calls})")
    if len(elm) < j_scent:
        print(f"WARNING: Elm sequence has {len(elm)} entries but the scent point "
              f"needs {j_scent}; regenerate with a larger count.")
    before = elm[max(0, j_land - n_before):j_land]
    bracket = elm[j_land:j_scent]
    after = elm[j_scent:j_scent + n_after]
    return f"{before}[{bracket}]!{after}"


def describe_plan(plan, guide=None):
    """A multi-line, human-readable instruction block for the notebook."""
    lines = [
        f"On advance frame {plan.current_frame}; want a Metang encounter on "
        f"frame {plan.encounter_frame} (Sweet Scent while on frame {plan.scent_frame}).",
        f"  Advances to go: {plan.total_advances}",
    ]
    if plan.chatot_advances > 0:
        flips = (f"{plan.chatot_flips:.1f}" if plan.chatot_flips % 1
                 else f"{int(plan.chatot_flips)}")
        lines.append(
            f"  1. {flips} chatot flips ({plan.chatot_advances} advances) "
            f"-> land on frame {plan.land_frame}")
        step2 = 2
    else:
        lines.append("  1. (no chatot flips needed)")
        step2 = 2
    lines.append(
        f"  {step2}. {plan.elm_before_scent} Elm calls "
        f"-> frame {plan.scent_frame}, then Sweet Scent.")
    if guide is not None:
        lines.append(f"  Guide: {guide}   (]! = Sweet Scent here)")
    return "\n".join(lines)


def prompt_target_frame(seed, default=DEFAULT_TARGET_FRAME, input_fn=None):
    """Pokefinder handoff: print Seed A and read back the chosen encounter frame.

    v1 leaves *which* frame has a (shiny) Metang to Pokefinder: the user pastes
    the printed seed into Pokefinder, finds a suitable frame, and types it here.
    Blank input keeps ``default`` (the shiny-Metang frame when we hit the target
    seed exactly).  Returns the chosen encounter frame (int).
    """
    if input_fn is None:
        ct.install_input_fixup()
        import builtins
        input_fn = builtins.input
    print(f"Seed A: 0x{seed:08X}  -- find a Metang encounter frame in Pokefinder.")
    while True:
        raw = input_fn(f"Target encounter frame [{default}]: ").strip()
        if raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            print("  enter an integer frame (or blank for the default).")


def margin_calls(rng_calls, elm, plan):
    """The Elm calls you'd hear over the plan's margin (the bracketed calls before Sweet Scent)."""
    j_land = plan.land_frame - rng_calls
    return elm[j_land:j_land + plan.elm_before_scent]


def margin_ambiguous(rng_calls, elm, plan):
    """Whether the plan's Elm-call margin can't reliably confirm the Sweet-Scent frame.

    The margin (the bracketed calls) confirms the frame only if it reads *uniquely* -- if the same
    call pattern repeats one step off, a landing/count error by that step is invisible.  So the
    margin is ambiguous when a full copy of the bracket sits ``p`` positions before or after it --
    i.e. the bracket's pattern *continues* into a flank -- for a period ``p`` of 1 or 2 (we assume
    landing/count errors are within 2 advances):

      * a flat run only when the run extends past the bracket -- ``E[EEE]`` / ``[EEE]!E`` (ambiguous),
        but ``K[EEE]K`` (bounded) is fine;
      * a period-2 unit -- ``EK[EKE]`` / ``[EKE]!KE``.

    (A period-3 repeat like ``PKE[PKE]`` is *not* flagged, since a 3-advance error is out of scope.)
    A flank that runs off the known ``elm`` can't be checked, so it isn't flagged (``margin_guide``
    already warns when ``elm`` is too short).  The fix (in ``choose_target_frame``) is to take the
    next target frame whose margin reads uniquely.
    """
    m = plan.elm_before_scent
    lo = plan.land_frame - rng_calls          # bracket = elm[lo:hi]
    hi = lo + m
    if m < 1 or lo < 0 or hi > len(elm):
        return False
    bracket = elm[lo:hi]
    for p in range(1, min(m, 2) + 1):         # errors assumed within 2 advances
        if lo - p >= 0 and elm[lo - p:hi - p] == bracket:      # copy p steps earlier (early landing)
            return True
        if hi + p <= len(elm) and elm[lo + p:hi + p] == bracket:  # copy p steps later (late landing)
            return True
    return False


def choose_target_frame(seed, *, key_seed, target_advances, use_inhouse,
                        area="Mountain", tod="morning", blocks=None, target="metang",
                        current_frame=0, search_margin=DEFAULT_ELM_MARGIN, max_frame=300,
                        rng_calls=None, elm=None, input_fn=None):
    """Pick the advance frame to Sweet Scent on, honoring the in-house/Pokefinder toggle.

    Exact-seed rule (ALWAYS, regardless of ``use_inhouse``): if the loaded ``seed`` is the intended
    ``key_seed`` we hit the target dead-on, so the frame is exactly ``target_advances`` (the
    configured true target, e.g. 81 for the shiny Metang).

    Otherwise we landed on a nearby seed and must find *a* Metang frame:
      * ``use_inhouse=True``  -> compute it here from the Safari block config (no Pokefinder).  Takes
        the nearest ``target`` frame at least ``search_margin`` advances ahead of ``current_frame``;
        when ``rng_calls``/``elm`` are given, frames whose Elm-call approach margin is an ambiguous
        run (``margin_ambiguous``) are skipped for the next candidate.
      * ``use_inhouse=False`` -> previous behavior: print the seed and prompt for a Pokefinder frame
        (blank keeps ``target_advances``).
    """
    if seed == key_seed:
        # Exact target seed -> the configured target_advances (e.g. the shiny frame), even if its
        # Elm margin is ambiguous: that's THE frame we want, so we never skip it here.  Any margin
        # ambiguity on the true target is an accepted risk.
        print(f"Loaded the target seed exactly (0x{seed:08X}) -> target advances {target_advances}.")
        return target_advances
    if use_inhouse:
        if blocks is None:
            raise ValueError("in-house mode needs `blocks`, e.g. {'peak': 56}")
        from claytonlib.safari_encounters import iter_encounter_frames
        lo = current_frame + search_margin
        candidates = iter_encounter_frames(seed, area, tod, blocks, target,
                                           min_frame=lo, max_frame=max_frame)
        first = None
        for frame, level in candidates:
            plan = plan_advances(current_frame, frame, margin=search_margin)
            if first is None:
                first = (frame, level)
            if rng_calls is None or elm is None or not margin_ambiguous(rng_calls, elm, plan):
                if first != (frame, level):
                    print(f"  (skipped nearer {target} frames with an ambiguous Elm margin)")
                print(f"In-house: {target} at advance frame {frame} (L{level}); "
                      f"advance {frame - current_frame} from the current frame {current_frame}.")
                return frame
        if first is not None:      # every candidate was ambiguous -- fall back to the nearest
            frame, level = first
            print(f"In-house: all {target} frames in range have an ambiguous Elm margin; "
                  f"using the nearest, advance frame {frame} (L{level}) -- verify carefully.")
            return frame
        raise RuntimeError(
            f"no {target} frame in [{lo}, {max_frame}] for {area}/{tod} blocks={blocks} -- "
            f"check the block scores, area, and time of day.")
    return prompt_target_frame(seed, default=target_advances, input_fn=input_fn)
