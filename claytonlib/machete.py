"""
machete.py — Safari capture path solver.

Given a starting seed or SafariContext, searches for action sequences
(bait, mud, ball) that lead to a successful capture.
"""
import copy
import logging
import time
from collections import deque
from dataclasses import dataclass
from fractions import Fraction

from claytonlib.safari import SafariContext, SafariPokemon, SafariStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class MacheteConfig:
    max_turns: int | None = 50


_config = MacheteConfig()


def machete_config() -> MacheteConfig:
    return _config


# ---------------------------------------------------------------------------
# JaneNode — optimal decision tree node
# ---------------------------------------------------------------------------

@dataclass
class JaneNode:
    action:      str                          # "BALL", "BAIT", "MUD", "CAPTURED", "FUTILE"
    probability: Fraction
    branches:    dict[str, 'JaneNode'] | None # None only for terminal nodes


CAPTURED_NODE = JaneNode(action='CAPTURED', probability=Fraction(1), branches=None)
FUTILE_NODE   = JaneNode(action='FUTILE',   probability=Fraction(0), branches=None)


# ---------------------------------------------------------------------------
# Path application
# ---------------------------------------------------------------------------

_CHAR_TO_THROW_AND_STEP: dict[str, tuple] = {
    'b': (SafariContext.throw_bait, SafariStep.BAIT),
    'B': (SafariContext.throw_bait, SafariStep.BAIT_CRITICAL),
    'm': (SafariContext.throw_mud,  SafariStep.MUD),
    'M': (SafariContext.throw_mud,  SafariStep.MUD_CRITICAL),
    '0': (SafariContext.throw_ball, SafariStep.BALL_0),
    '1': (SafariContext.throw_ball, SafariStep.BALL_1),
    '2': (SafariContext.throw_ball, SafariStep.BALL_2),
    '3': (SafariContext.throw_ball, SafariStep.BALL_3),
    'C': (SafariContext.throw_ball, SafariStep.CAPTURED),
}


def _apply_path(ctx: SafariContext, path: str) -> SafariContext:
    """Apply a path string to ctx in-place. Raises ValueError on invalid input."""
    chars = [c for c in path if c not in (' ', ',')]
    errors = []
    unknown = {c for c in chars if c not in _CHAR_TO_THROW_AND_STEP and c not in ('u', 'F')}
    if unknown:
        errors.append(f"unknown character(s): {', '.join(repr(c) for c in sorted(unknown))}")
    if 'u' in chars:
        errors.append("undo ('u') is not supported in machete paths")
    if 'F' in chars:
        errors.append("path contains flee ('F'); cannot search from a fled state")
    if errors:
        raise ValueError('; '.join(errors))
    for ch in chars:
        throw, expected = _CHAR_TO_THROW_AND_STEP[ch]
        result = throw(ctx)
        if result != expected:
            raise ValueError(
                f"path character {ch!r}: expected {expected.name}, got {result.name}"
            )
    return ctx


def _resolve_ctx(pokemon_or_ctx: SafariPokemon | SafariContext,
                 seed: int | None,
                 path: str) -> SafariContext:
    """Return a fresh SafariContext ready to search from."""
    if isinstance(pokemon_or_ctx, SafariContext):
        return copy.copy(pokemon_or_ctx)
    if seed is None:
        raise ValueError("seed is required when passing SafariPokemon")
    ctx = SafariContext.start_encounter(seed, pokemon_or_ctx)
    return _apply_path(ctx, path)


# ---------------------------------------------------------------------------
# BFS internals
# ---------------------------------------------------------------------------

# Action iteration order: mud → ball → bait.
# Decisive actions are explored first to avoid flooding the queue with
# long bait-only prefixes.
_BFS_ACTIONS = [
    SafariContext.throw_mud,
    SafariContext.throw_ball,
    SafariContext.throw_bait,
]


# ---------------------------------------------------------------------------
# machete_one
# ---------------------------------------------------------------------------

def machete_one(
    pokemon_or_ctx: SafariPokemon | SafariContext,
    seed: int | None = None,
    path: str = '',
    max_turns: int | None = ...,
) -> str | None:
    """Return the shortest capture path via BFS, or None if no path exists.

    Args:
        pokemon_or_ctx: SafariPokemon (requires seed) or mid-encounter SafariContext.
        seed:           Required when passing SafariPokemon; ignored otherwise.
        path:           Compass-syntax actions already taken (e.g. '010'). Applied
                        before searching. Ignored when SafariContext is passed.
        max_turns:      Turn limit per branch. None = unlimited.
                        Defaults to machete_config().max_turns.
    """
    if max_turns is ...:
        max_turns = machete_config().max_turns
    ctx = _resolve_ctx(pokemon_or_ctx, seed, path)
    queue: deque[tuple[SafariContext, str, int]] = deque([(ctx, '', 0)])
    while queue:
        curr, path_so_far, turns = queue.popleft()
        if not curr.is_watching():
            continue
        if max_turns is not None and turns >= max_turns:
            continue
        for throw in _BFS_ACTIONS:
            ctx2 = copy.copy(curr)
            result = throw(ctx2)
            new_path = path_so_far + result.value
            if result == SafariStep.CAPTURED:
                return new_path
            if result == SafariStep.FLED:
                continue
            if max_turns is not None and turns + 1 >= max_turns:
                continue
            queue.append((ctx2, new_path, turns + 1))
    return None


# ---------------------------------------------------------------------------
# machete_all
# ---------------------------------------------------------------------------

def machete_all(
    pokemon_or_ctx: SafariPokemon | SafariContext,
    seed: int | None = None,
    path: str = '',
    max_turns: int | None = ...,
) -> tuple[list[str], int]:
    """Return all capture paths and the count of depth-limited branches.

    Returns:
        (paths, truncated) where paths is every capture path found and
        truncated counts branches discarded only due to max_turns. A
        non-zero truncated count means raising max_turns may reveal more paths.

    Args: same as machete_one.
    """
    if max_turns is ...:
        max_turns = machete_config().max_turns
    ctx = _resolve_ctx(pokemon_or_ctx, seed, path)
    paths: list[str] = []
    truncated = 0
    max_depth_reached = -1
    t_start = time.monotonic()
    queue: deque[tuple[SafariContext, str, int]] = deque([(ctx, '', 0)])
    while queue:
        curr, path_so_far, turns = queue.popleft()
        if turns > max_depth_reached:
            max_depth_reached = turns
            elapsed = time.monotonic() - t_start
            logger.debug(
                "machete_all depth=%d  queue=%d  elapsed=%.3fs",
                max_depth_reached, len(queue), elapsed,
            )
        if not curr.is_watching():
            continue
        if max_turns is not None and turns >= max_turns:
            truncated += 1
            continue
        for throw in _BFS_ACTIONS:
            ctx2 = copy.copy(curr)
            result = throw(ctx2)
            new_path = path_so_far + result.value
            if result == SafariStep.CAPTURED:
                paths.append(new_path)
            elif result == SafariStep.FLED:
                pass
            elif max_turns is not None and turns + 1 >= max_turns:
                truncated += 1
            else:
                queue.append((ctx2, new_path, turns + 1))
    elapsed = time.monotonic() - t_start
    logger.debug(
        "machete_all done: %d path(s), %d truncated, elapsed=%.3fs",
        len(paths), truncated, elapsed,
    )
    return paths, truncated


# ---------------------------------------------------------------------------
# jane_tree (internal recursive function)
# ---------------------------------------------------------------------------

# Action order for jane_tree: ball > mud > bait for tie-breaking.
# Balls have 5 possible outcomes vs 2 for bait/mud, so they eliminate
# seed ambiguity fastest. Since we use strict > for comparison, the first
# action in this list wins ties.
_JANE_ACTIONS = [
    ('BALL', SafariContext.throw_ball),
    ('MUD',  SafariContext.throw_mud),
    ('BAIT', SafariContext.throw_bait),
]


def _jane_tree(candidates: list[tuple[SafariContext, list[str]]]) -> JaneNode | None:
    """Recursively build the optimal capture decision tree.

    Args:
        candidates: list of (ctx, paths) where ctx is the current encounter
                    state for each candidate seed and paths is the list of
                    viable capture paths from that state (from machete_all).

    Returns:
        The best JaneNode, FUTILE_NODE if no captures are possible, or None
        if candidates is empty.
    """
    if not candidates:
        return None
    if all(not paths for _, paths in candidates):
        return FUTILE_NODE

    total = len(candidates)
    best: JaneNode | None = None

    for action_name, throw in _JANE_ACTIONS:
        # Step 1 & 2: simulate the action on every active candidate and
        # group by outcome character. Terminated seeds (fled/captured) are
        # skipped — they can't produce a new outcome — but still count in
        # total so the probability stays accurate.
        buckets: dict[str, list[tuple[SafariContext, list[str]]]] = {}
        for ctx, paths in candidates:
            if ctx.has_fled() or ctx.captured():
                continue
            ctx2 = copy.copy(ctx)
            result = throw(ctx2)
            ch = result.value
            if ch not in buckets:
                buckets[ch] = []
            buckets[ch].append((ctx2, paths))

        # Step 3 & 4: recurse per outcome bucket and compute weighted probability.
        branches: dict[str, JaneNode] = {}
        numerator = Fraction(0)

        for ch, bucket in buckets.items():
            bucket_size = len(bucket)

            if action_name == 'BALL' and ch == 'C':
                # Capture is terminal — no recursion needed.
                subtree = CAPTURED_NODE
            else:
                # For each seed in this bucket, keep only the paths that
                # start with this outcome character, then strip that character.
                # Paths not starting with ch are dropped: we have committed to
                # this action/outcome, so those paths are no longer viable.
                next_candidates = [
                    (ctx2, [p[1:] for p in paths if p and p[0] == ch])
                    for ctx2, paths in bucket
                ]
                subtree = _jane_tree(next_candidates)
                if subtree is None or subtree is FUTILE_NODE:
                    continue  # skip zero-probability branches

            branches[ch] = subtree
            numerator += bucket_size * subtree.probability

        probability = numerator / total

        if probability == Fraction(0):
            node = FUTILE_NODE
        else:
            node = JaneNode(action=action_name, probability=probability, branches=branches)

        # Strict > means the first action in _JANE_ACTIONS wins ties (ball > mud > bait).
        if best is None or node.probability > best.probability:
            best = node

    if best is None or best.probability == Fraction(0):
        return FUTILE_NODE
    return best


# ---------------------------------------------------------------------------
# machete_jane
# ---------------------------------------------------------------------------

def machete_jane(
    candidates: list[tuple[SafariContext, int]],
    max_turns: int | None = ...,
) -> JaneNode | None:
    """Return the optimal decision tree across all candidate seeds.

    Args:
        candidates: list of (ctx, seed) tuples — typically the candidate list
                    from compass after narrowing. ctx should reflect the current
                    encounter state; it is never mutated.
        max_turns:  Turn limit passed to machete_all for path generation.
                    Defaults to machete_config().max_turns.

    Returns:
        The optimal JaneNode tree, FUTILE_NODE if no seed has a viable path,
        or None if candidates is empty.
    """
    if max_turns is ...:
        max_turns = machete_config().max_turns
    items: list[tuple[SafariContext, list[str]]] = []
    for ctx, _seed in candidates:
        paths, _ = machete_all(ctx, max_turns=max_turns)
        items.append((copy.copy(ctx), paths))
    return _jane_tree(items)
