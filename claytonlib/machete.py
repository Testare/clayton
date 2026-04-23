"""
machete.py — Safari capture path solver.

Given a starting seed or SafariContext, searches for action sequences
(bait, mud, ball) that lead to a successful capture.
"""
import copy
import logging
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from fractions import Fraction

from claytonlib.safari import SafariContext, SafariPokemon, SafariStep
from claytonlib.safari_compact import (
    CompactPokemon, encode, is_watching as c_is_watching,
    will_flee as c_will_flee,
    sim_bait, sim_mud, sim_ball,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class MacheteConfig:
    max_turns: int | None = 20
    log_interval: int = 500_000  # nodes between progress log lines (0 = disabled)
    parallel: bool = False        # use ProcessPoolExecutor in machete_jane


_config = MacheteConfig()


def machete_config() -> MacheteConfig:
    return _config


# ---------------------------------------------------------------------------
# JaneNode — optimal decision tree node
# ---------------------------------------------------------------------------

@dataclass
class JaneNode:
    action:               str                          # "BALL", "BAIT", "MUD", "CAPTURED", "FUTILE"
    probability:          Fraction
    branches:             dict[str, 'JaneNode'] | None # None only for terminal nodes
    direct_capture_prob:  Fraction | None = None       # BALL nodes only: P(C on this throw)


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

# Compact simulation action order: mud → ball → bait.
# Decisive actions first to avoid flooding the queue with long bait-only prefixes.
_COMPACT_ACTIONS   = [sim_mud, sim_ball, sim_bait]

# When the pokemon is in WATCHING_WILL_FLEE state, bait and mud both
# immediately trigger the pending flee check and result in FLED. Only a
# ball that captures is useful, so we skip bait and mud entirely.
_COMPACT_BALL_ONLY = [sim_ball]


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
    cp = CompactPokemon(ctx.pokemon)
    s0 = encode(ctx)

    # BFS with a visited set: compact states are plain ints, so "copy" is
    # free and hashing is O(1). The first time we reach a state is always
    # via the shortest path, so skipping revisits is safe.
    visited: set[int] = {s0}
    queue: deque[tuple[int, str, int]] = deque([(s0, '', 0)])
    while queue:
        s, path_so_far, turns = queue.popleft()
        if not c_is_watching(s):
            continue
        if max_turns is not None and turns >= max_turns:
            continue
        for sim in (_COMPACT_BALL_ONLY if c_will_flee(s) else _COMPACT_ACTIONS):
            s2, ch = sim(s, cp)
            new_path = path_so_far + ch
            if ch == 'C':
                return new_path
            if not c_is_watching(s2) or s2 in visited:
                continue
            visited.add(s2)
            if max_turns is not None and turns + 1 >= max_turns:
                continue
            queue.append((s2, new_path, turns + 1))
    return None


# ---------------------------------------------------------------------------
# machete_all worker (module-level for ProcessPoolExecutor pickling)
# ---------------------------------------------------------------------------

def _machete_all_worker(args: tuple) -> tuple[list[str], int]:
    """Module-level worker; must be defined here so ProcessPoolExecutor can pickle it."""
    ctx, max_turns = args
    return machete_all(ctx, max_turns=max_turns)


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
    cp  = CompactPokemon(ctx.pokemon)
    s0  = encode(ctx)

    paths: list[str] = []
    truncated = 0

    # futile_memo maps a compact state → the largest remaining-turns budget
    # under which the state was exhaustively explored and found to yield no
    # captures and no truncations. If we encounter the same state with
    # budget ≤ that value, exploring it again cannot produce new results.
    futile_memo: dict[int, int] = {}

    prefix: list[str] = []   # shared mutable path prefix; push/pop on descent/ascent

    t_start       = time.monotonic()
    nodes_visited = 0
    log_interval  = _config.log_interval
    countdown     = log_interval

    def _dfs(s: int, depth: int) -> None:
        nonlocal truncated, nodes_visited, countdown
        if not c_is_watching(s):
            return
        if max_turns is not None and depth >= max_turns:
            truncated += 1
            return

        nodes_visited += 1
        if log_interval:
            countdown -= 1
            if countdown == 0:
                countdown = log_interval
                elapsed = time.monotonic() - t_start
                logger.debug(
                    "machete_all: %d nodes  %d paths  %d trunc  %.1fs"
                    "  %.0fk/s  memo=%d",
                    nodes_visited, len(paths), truncated, elapsed,
                    nodes_visited / elapsed / 1000, len(futile_memo),
                )

        paths_snap = len(paths)
        trunc_snap = truncated
        child_depth = depth + 1

        for sim in (_COMPACT_BALL_ONLY if c_will_flee(s) else _COMPACT_ACTIONS):
            s2, ch = sim(s, cp)
            if ch == 'C':
                paths.append(''.join(prefix) + 'C')
            elif c_is_watching(s2):
                if max_turns is not None and child_depth >= max_turns:
                    truncated += 1
                else:
                    remaining2 = (
                        (max_turns - child_depth) if max_turns is not None else (1 << 30)
                    )
                    if futile_memo.get(s2, 0) < remaining2:
                        prefix.append(ch)
                        _dfs(s2, child_depth)
                        prefix.pop()

        # On exit: if this subtree produced no captures and no truncations,
        # record it as futile so equal-or-smaller-budget revisits can be skipped.
        if len(paths) == paths_snap and truncated == trunc_snap:
            remaining = (max_turns - depth) if max_turns is not None else (1 << 30)
            if remaining > futile_memo.get(s, 0):
                futile_memo[s] = remaining

    _dfs(s0, 0)
    paths.sort(key=len)

    elapsed = time.monotonic() - t_start
    logger.debug(
        "machete_all done: %d path(s)  %d truncated  %d nodes  %.3fs  memo=%d",
        len(paths), truncated, nodes_visited, elapsed, len(futile_memo),
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

        direct_capture_prob: Fraction | None = None
        if action_name == 'BALL' and 'C' in buckets:
            direct_capture_prob = Fraction(len(buckets['C']), total)

        if probability == Fraction(0):
            node = FUTILE_NODE
        else:
            node = JaneNode(
                action=action_name,
                probability=probability,
                branches=branches,
                direct_capture_prob=direct_capture_prob,
            )

        # Strict > means the first action in _JANE_ACTIONS wins ties (ball > mud > bait).
        if best is None or node.probability > best.probability:
            best = node

    if best is None or best.probability == Fraction(0):
        return FUTILE_NODE
    return best


# ---------------------------------------------------------------------------
# Interactive display helpers
# ---------------------------------------------------------------------------

# All outcomes the player can observe per action type, in display order.
# 'F' (fled) can follow any action via the flee check and is always listed.
_ACTION_OUTCOMES: dict[str, list[str]] = {
    'BALL': ['0', '1', '2', '3', 'C', 'F'],
    'MUD':  ['m', 'M', 'F'],
    'BAIT': ['b', 'B', 'F'],
}


def _outcome_text(ch: str, pokemon_name: str) -> str:
    name = pokemon_name.capitalize()
    descriptions: dict[str, str] = {
        '0': 'Ball, 0 shakes    Oh, no! The Pokémon broke free!',
        '1': 'Ball, 1 shake     Aww! It appeared to be caught!',
        '2': 'Ball, 2 shakes    Aargh! Almost had it!',
        '3': 'Ball, 3 shakes    Shoot! It was so close, too!',
        'C': f'Captured          Gotcha! {name} was caught!',
        'F': f'Fled              {name} fled!',
        'm': f'Mud, no crit      {name} is angry!',
        'M': f'Mud, crit         {name} is beside itself with anger!',
        'b': f'Bait, no crit     {name} is eating!',
        'B': f'Bait, crit        {name} is busy eating!',
    }
    return f'{ch}    {descriptions.get(ch, ch)}'


def _print_outcomes(action: str, branches: dict[str, 'JaneNode'], pokemon_name: str) -> None:
    for ch in _ACTION_OUTCOMES.get(action, []):
        marker = '*' if ch in branches else ' '
        print(f'  {marker} {_outcome_text(ch, pokemon_name)}')


# ---------------------------------------------------------------------------
# machete_jane
# ---------------------------------------------------------------------------

def machete_jane(
    candidates: list[tuple[SafariContext, int] | int],
    pokemon: SafariPokemon | None = None,
    max_turns: int | None = ...,
    interactive: bool = False,
) -> JaneNode | None:
    """Return the optimal decision tree across all candidate seeds.

    Args:
        candidates: list of (ctx, seed) tuples or plain seed ints. When plain
                    seeds are used, pokemon is required to construct contexts.
        pokemon:    Required when candidates contains plain seed ints.
        max_turns:  Turn limit passed to machete_all for path generation.
                    Defaults to machete_config().max_turns.

    Returns:
        The optimal JaneNode tree, FUTILE_NODE if no seed has a viable path,
        or None if candidates is empty.
    """
    if max_turns is ...:
        max_turns = machete_config().max_turns
    n = len(candidates)
    logger.info("machete_jane: %d candidate(s), max_turns=%s", n, max_turns)
    t_start = time.monotonic()

    # Phase 1: resolve all contexts (always sequential — fast).
    resolved: list[tuple[SafariContext, int]] = []   # (ctx, seed)
    for candidate in candidates:
        if isinstance(candidate, int):
            if pokemon is None:
                raise ValueError("pokemon is required when candidates contains plain seed ints")
            seed = candidate
            ctx  = SafariContext.start_encounter(seed, pokemon)
        else:
            ctx  = copy.copy(candidate[0])
            seed = candidate[1]
        resolved.append((ctx, seed))

    # Phase 2: run machete_all on each context.
    use_parallel = _config.parallel and not interactive and n > 1
    if use_parallel:
        logger.info("machete_jane: using ProcessPoolExecutor across %d workers", n)
        worker_args = [(copy.copy(ctx), max_turns) for ctx, _ in resolved]
        with ProcessPoolExecutor() as executor:
            raw_results = list(executor.map(_machete_all_worker, worker_args))
    else:
        raw_results = []
        for i, (ctx, seed) in enumerate(resolved):
            logger.debug("machete_jane: candidate %d/%d", i + 1, n)
            if interactive:
                print(f"Jane is considering 0x{seed:08X}...")
            paths, _ = machete_all(copy.copy(ctx), max_turns=max_turns)
            if interactive:
                if paths:
                    print(
                        f"Jane thinks 0x{seed:08X} has some potential "
                        f"({len(paths)} paths identified)."
                    )
                else:
                    print(f"Jane thinks 0x{seed:08X} is a dead-end.")
            raw_results.append((paths, _))

    # Phase 3: assemble items for _jane_tree.
    items: list[tuple[SafariContext, list[str]]] = [
        (copy.copy(ctx), paths)
        for (ctx, _seed), (paths, _trunc) in zip(resolved, raw_results)
    ]

    t_paths = time.monotonic()
    logger.info(
        "machete_jane: paths collected in %.3fs, building tree across %d candidate(s)...",
        t_paths - t_start, n,
    )
    result = _jane_tree(items)
    logger.info("machete_jane: done in %.3fs total", time.monotonic() - t_start)

    if interactive and result is not None:
        # Resolve pokemon name for outcome display
        pokemon_name = 'the Pokémon'
        if pokemon is not None:
            pokemon_name = pokemon.name
        else:
            for c in candidates:
                if isinstance(c, tuple):
                    pokemon_name = c[0].pokemon.name
                    break

        node: JaneNode = result
        while True:
            if node is CAPTURED_NODE:
                print(f"Gotcha! {pokemon_name.capitalize()} was caught!")
                break
            if node is FUTILE_NODE or node.branches is None:
                print("Bad news I'm afraid...\n\nATTEMPT FAILED")
                break

            pct = float(node.probability) * 100

            if node.action == 'BALL':
                if set(node.branches.keys()) == {'C'}:
                    print("This should be it! Throw the ball!")
                elif 'C' in node.branches and node.direct_capture_prob is not None:
                    cap_pct = float(node.direct_capture_prob) * 100
                    print(
                        f'Jane suggests "Throw ball, this could be our chance..." '
                        f'({pct:.1f}% confidence, {cap_pct:.1f}% chance to capture)'
                    )
                else:
                    print(f'Jane suggests "Throw ball" ({pct:.1f}% confidence)')
            elif node.action == 'MUD':
                print(f'Jane suggests "Throw mud" ({pct:.1f}% confidence)')
            else:
                print(f'Jane suggests "Throw bait" ({pct:.1f}% confidence)')

            _print_outcomes(node.action, node.branches, pokemon_name)

            while True:
                raw = input("What happened? ").strip().replace(',', '').replace(' ', '')
                if raw:
                    break
            ch = raw[0]

            next_node = node.branches.get(ch)
            if next_node is None:
                print("Bad news I'm afraid... ATTEMPT FAILED")
                break

            node = next_node

    return result
