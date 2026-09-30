"""The reporting grammar (notes/battle_compass.md sec 13).

Its job is **canonical rendering**: one and only one token sequence per battle state.  Input
reaches the tool through interactive prompts, and filtering is a comparison against each
candidate's rendered turn — so round-tripping from typed text is a convenience for fixtures and
bug reports, not the primary path (sec 13.1).

Shape: an uppercase prefix opens an action, everything after it until the next prefix is that
action's detail, and tokens appear **in the order the events occur**.  The prefixes are
``I C M P S E HP``, which is prefix-free because ``H`` alone is not an action.

One rule earns its keep more than the others: an ``HP###`` token is present exactly when our HP
changed, for *any* reason — damage, a healing item, a burn or poison tick, a confusion self-hit.
Because the simulator predicts whether it changed, that is checkable in both directions, and a
turn where the player took damage but reported no HP is a parse error rather than a silently
wrong state (sec 13.8).
"""
from __future__ import annotations

# Detail tokens for a status, keyed by the Status enum's value.
STATUS_DETAIL = {"par": "par", "slp": "slp", "frz": "frz", "brn": "brn", "psn": "psn"}

HIT = "h"
CRIT = "!"
MISS = "-"
SECONDARY = "~"

#: Uppercase action prefixes, longest-match. Prefix-free: "H" alone is deliberately not one,
#: which is what lets "HP" be two characters.
ACTION_PREFIXES = ("HP", "I", "C", "M", "P", "S", "E")


def hp_token(hp: int) -> str:
    """``HP`` plus exactly three zero-padded digits.

    Three is always enough — the largest possible Gen 4 HP stat is 714 — and fixed width is
    required, or ``HP50M2`` would be ambiguous.
    """
    if not 0 <= hp <= 999:
        raise ValueError(f"HP out of renderable range: {hp}")
    return f"HP{hp:03d}"


def our_move_token(slot: int) -> str:
    """``M1``..``M4`` — our move, by slot in the registered moveset."""
    if not 0 <= slot <= 3:
        raise ValueError(f"move slot out of range: {slot}")
    return f"M{slot + 1}"


def target_move_token(slot: int) -> str:
    """``E1``..``E4`` — the target's move, by slot in its known moveset."""
    if not 0 <= slot <= 3:
        raise ValueError(f"move slot out of range: {slot}")
    return f"E{slot + 1}"


def prevented_token(actor: str, status: str) -> str:
    """``Mpar`` / ``Epar`` — the actor was stopped by a status.

    Chronological, so the status marker comes before any slot: the check happens before the move
    would have executed.  A status that *resolves* and lets the move through renders as the slot
    with no marker, because the move happening at all implies the status ended — except for
    confusion, the one status a Pokemon can keep while still attacking (sec 13.4).
    """
    if actor not in ("M", "E"):
        raise ValueError(f"actor must be M or E, got {actor!r}")
    return f"{actor}{status}"


def ball_token(shakes: int, captured: bool = False, *, capture_ball: bool = False) -> str:
    """A thrown ball, by shake count.

    ``P0``-``P3`` a standard ball broke free · ``Pc`` it captured, so the run is lost because the
    target is in the wrong ball (sec 2.3) · ``C0``-``C3`` the capture ball broke free · ``C`` it
    captured, which is the win.

    The two ball types need distinct prefixes even where they share a threshold, or the log
    cannot say which ball was spent — and against a target the Fast Ball actually matches they
    would not share one anyway. Sec 13.3 listed ``C`` and ``P0``-``P3`` but no token for a
    capture ball that *failed*; ``C0``-``C3`` fills that gap.
    """
    prefix = "C" if capture_ball else "P"
    if captured:
        return "C" if capture_ball else "Pc"
    if not 0 <= shakes <= 3:
        raise ValueError(f"shake count out of range for a non-capture: {shakes}")
    return f"{prefix}{shakes}"


def item_token(code: str) -> str:
    """``Ip`` / ``Ihp`` / ``Ixsd`` / ``Ifh`` ... — an item, by its short code."""
    if not code or not code.islower():
        raise ValueError(f"item code should be lowercase, got {code!r}")
    return f"I{code}"


def switch_token(party_slot: int) -> str:
    """``S1``..``S6`` — switch to that party slot. Phase 1 only (sec 12.5)."""
    if not 1 <= party_slot <= 6:
        raise ValueError(f"party slot out of range: {party_slot}")
    return f"S{party_slot}"


def render_turn(tokens: list[str] | tuple[str, ...]) -> str:
    """One turn's tokens, concatenated with no delimiter."""
    return "".join(tokens)


def render_path(turns: list[list[str]] | list[tuple[str, ...]]) -> str:
    """A whole battle: turns joined by spaces (sec 13.9)."""
    return " ".join(render_turn(turn) for turn in turns)


def split_turns(path: str) -> list[str]:
    """A rendered path back into per-turn strings."""
    return [chunk for chunk in path.split(" ") if chunk]


def tokenise(turn: str) -> list[str]:
    """One turn's string into its tokens, by longest match over the action prefixes.

    Provided for fixtures and bug reports rather than for the main flow; the tool compares
    rendered output against reported observations, so it never needs to parse a typed path.
    """
    tokens: list[str] = []
    i = 0
    while i < len(turn):
        prefix = next((p for p in ACTION_PREFIXES if turn.startswith(p, i)), None)
        if prefix is None:
            raise ValueError(f"no action prefix at index {i} of {turn!r}")
        j = i + len(prefix)
        while j < len(turn):
            if any(turn.startswith(p, j) for p in ACTION_PREFIXES):
                break
            j += 1
        tokens.append(turn[i:j])
        i = j
    return tokens


def hp_from_token(token: str) -> int | None:
    """The HP a token reports, or None if it is not an HP token."""
    if token.startswith("HP") and len(token) == 5 and token[2:].isdigit():
        return int(token[2:])
    return None


def normalise(tokens: list[str] | tuple[str, ...]) -> list[str]:
    """Canonical, merged tokens from either form.

    The simulator accumulates *fragments* (``["M1", "h", "E3", "!"]``) while ``tokenise``
    produces merged tokens (``["M1h", "E3!"]``).  The grammar's unit is the merged form, so
    everything that inspects tokens normalises first — without this, a rule looking for a hit
    inside an ``E``-prefixed token silently never fires on a fragment list.
    """
    return tokenise(render_turn(tokens))


def turn_requires_hp(tokens: list[str] | tuple[str, ...]) -> bool:
    """Whether this turn must carry an HP token: did anything hit us?

    The check that makes the grammar self-verifying. A player who takes damage and forgets to
    report HP produces an invalid turn rather than a silently wrong state, which matters because
    Phase 2 runs to a precomputed path and HP is how a desync is caught (sec 2.5).
    """
    for token in normalise(tokens):
        if not token.startswith("E"):
            continue
        # The target's move landing on us is the only thing in scope that can damage us.
        if any(marker in token for marker in (HIT, CRIT)):
            return True
    return False


def validate_turn(tokens: list[str] | tuple[str, ...]) -> list[str]:
    """Grammar invariants, as a list of problems (sec 13.8). Empty means the turn is well formed.

    Checkable against the simulator's own prediction, which is what makes them worth enforcing
    rather than merely documenting.
    """
    problems: list[str] = []
    tokens = normalise(tokens)
    seen_move = False
    for token in tokens:
        if token.startswith("HP"):
            if hp_from_token(token) is None:
                problems.append(f"{token!r} is not HP plus exactly three digits")
            continue
        if token[0] in ("E", "M"):
            seen_move = True
            continue
        if token[0] in ("I", "C", "P", "S") and seen_move:
            problems.append(
                f"{token!r} is a bag action but follows a move; bag actions resolve first")
    if turn_requires_hp(tokens) and not any(t.startswith("HP") for t in tokens):
        problems.append("the target hit us, so this turn needs an HP token")
    terminal = [t for t in tokens if t in ("C", "Pc")]
    if terminal and tokens[-1] not in ("C", "Pc"):
        problems.append(f"{terminal[0]!r} is terminal; nothing may follow it")
    return problems
