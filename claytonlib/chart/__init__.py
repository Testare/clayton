"""
chart/ — Target seed charting tool.

Given a Pokemon and a strategy, evaluates seeds derived from candidate
datetimes to find optimal target times. Aggregates per-seed capture
probability across neighboring frames and ranks results so the player
knows the best datetime to aim for.
"""
import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from claytonlib.safari import SafariContext, SafariPokemon, SafariStep
from claytonlib.times import get_times
from claytonlib.chart.evaluation import (
    EvaluationStrategy,
    EvaluationData,
    ChainEvaluationResult,
    CrossChainResult,
    TopResult,
    SlidingWindowSum,
    NormalWindow,
    read_evaluation,
    write_evaluation,
)

logger = logging.getLogger(__name__)


class Strategy:
    def __init__(self, name: str, fn: Callable[[SafariContext], SafariStep]):
        self.name = name
        self._fn = fn

    def take_action(self, ctx: SafariContext) -> None:
        result = self._fn(ctx)
        logger.debug("turn[%d] strategy[%s] %s", ctx.turn_count, self.name, result.name)


class SuccessCriteria:
    def __init__(self, name: str, fn: Callable[[SafariContext], bool]):
        self.name = name
        self._fn = fn

    def met(self, ctx: SafariContext) -> bool:
        result = self._fn(ctx)
        logger.debug("turn[%d] criteria[%s] %s", ctx.turn_count, self.name, result)
        return result


STRATEGY_ONLY_BALLS = Strategy(
    "only-balls",
    lambda ctx: ctx.throw_ball()
)

STRATEGY_ONE_MUD = Strategy(
    "one-mud-then-balls",
    lambda ctx: ctx.throw_mud() if ctx.turn_count == 0 else ctx.throw_ball()
)

STRATEGY_SIX_BAIT = Strategy(
    "six-bait-then-balls",
    lambda ctx: ctx.throw_bait() if ctx.turn_count < 6 else ctx.throw_ball()
)

CRITERIA_CAPTURE = SuccessCriteria(
    "capture",
    lambda ctx: ctx.captured()
)

CRITERIA_WONT_FLEE_10_TURNS = SuccessCriteria(
    "survived-10-turns-without-fleeing",
    lambda ctx: ctx.turn_count >= 10 and ctx.is_watching()
)

def evaluate_seed(seed: int, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> bool:
    ctx = SafariContext.start_encounter(seed, pokemon)
    while ctx.is_watching():
        strategy.take_action(ctx)
        if criteria.met(ctx):
            return True
    return False


def _make_machete_after_n_balls_criteria(n_balls: int) -> SuccessCriteria:
    def _check(ctx: SafariContext) -> bool:
        from claytonlib.machete import machete_one
        balls_thrown = 30 - ctx.balls_remaining
        if balls_thrown != n_balls:
            return False
        path = machete_one(ctx)
        if path is not None:
            return True
        ctx.force_flee()
        return False
    return SuccessCriteria(f"capture-via-machete-after-{n_balls}-balls", _check)


CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS = _make_machete_after_n_balls_criteria(3)
CRITERIA_CAPTURE_MACHETE_AFTER_5_BALLS = _make_machete_after_n_balls_criteria(5)

def machete_x_turns_n_balls_criteria(turns: int, n_balls: int) -> SuccessCriteria:
    def _check(ctx: SafariContext) -> bool:
        from claytonlib.machete import machete_one
        balls_thrown = 30 - ctx.balls_remaining
        if balls_thrown != n_balls:
            return False
        path = machete_one(ctx, max_turns = turns)
        if path is not None:
            return True
        ctx.force_flee()
        return False
    return SuccessCriteria(f"machete-{turns}-turns-after-{n_balls}-balls", _check)


# ---------------------------------------------------------------------------
# ChartConfig
# ---------------------------------------------------------------------------

@dataclass
class ChartConfig:
    evaluation_frames_per_write_cycle: int = 60
    resume_validation_enabled: bool = False
    resume_validation_frames: int = 2
    resume_strict: bool = False  # True = raise on mismatch, False = warn and continue
    evaluation_chains_per_write_cycle: int = 5

_config = ChartConfig()

def chart_config() -> ChartConfig:
    return _config


# ---------------------------------------------------------------------------
# ChartSafariInput and path helpers
# ---------------------------------------------------------------------------

@dataclass
class ChartSafariInput:
    key_seed: int
    setup_delay_seconds: int
    max_target_seconds: int
    strategy: Strategy
    criteria: SuccessCriteria
    pokemon: SafariPokemon
    project_label: str | None = None


def _evaluation_code(inputs: ChartSafariInput) -> str:
    return f"{inputs.strategy.name}_{inputs.criteria.name}"


def _output_dir(inputs: ChartSafariInput) -> Path:
    parts = ['data']
    if inputs.project_label:
        parts.append(inputs.project_label)
    parts.append(f"{_pokemon_name(inputs.pokemon)}_{inputs.key_seed:08X}")
    parts.append(f"chart_{_evaluation_code(inputs)}")
    return Path(*parts)


def _chain_path(inputs: ChartSafariInput, initial_time: dt.datetime) -> Path:
    time_str = initial_time.strftime('%Y-%m-%d_%H-%M-%S')
    filename = f"{time_str}+{inputs.setup_delay_seconds}.chain"
    return _output_dir(inputs) / filename


def _pokemon_name(pokemon: SafariPokemon) -> str:
    from claytonlib.safari import _safari_pokemon
    if _safari_pokemon is not None:
        for name, p in _safari_pokemon.items():
            if p is pokemon:
                return name
    return "unknown"


# ---------------------------------------------------------------------------
# Internal chart_safari helpers
# ---------------------------------------------------------------------------

def _initialize_writers(inputs: ChartSafariInput, store) -> tuple:
    from claytonlib.chart.chain import ChainWriter, chain_at_time

    delay, times = get_times(inputs.key_seed)
    output_dir = _output_dir(inputs)
    store.ensure_dir(output_dir)

    complete_size = (inputs.max_target_seconds - inputs.setup_delay_seconds + 1) * 8
    paths = [_chain_path(inputs, t) for t in times]
    sizes = [store.file_size(p) for p in paths]

    # Partition into complete (size >= complete_size) and incomplete chains.
    # Truncate any over-sized complete chains down to exactly complete_size.
    complete_paths = []
    incomplete = []  # list of (path, time, size)
    for path, time, size in zip(paths, times, sizes):
        if size >= complete_size:
            if size > complete_size:
                store.truncate(path, complete_size)
            complete_paths.append(path)
        else:
            incomplete.append((path, time, size))

    if not incomplete:
        return [], 0

    if complete_paths:
        logger.info(
            "%d chain(s) already complete, resuming %d incomplete chain(s).",
            len(complete_paths), len(incomplete),
        )

    # Square off incomplete chains: truncate all to the smallest safe size among them.
    min_size = min(s for _, _, s in incomplete)
    safe_size = (min_size // 8) * 8
    already_written = safe_size // 8

    for path, _, size in incomplete:
        if size > safe_size:
            store.truncate(path, safe_size)

    if already_written > 0:
        logger.info("Resuming incomplete chains from link %d.", already_written)

    writers = []
    for path, time, _ in incomplete:
        start_offset = inputs.setup_delay_seconds + already_written
        gen = chain_at_time(
            time + dt.timedelta(seconds=start_offset),
            delay + start_offset * 60,
        )
        writers.append(ChainWriter(path=path, generator=gen))

    return writers, already_written


def _validate_resume(writers, inputs: ChartSafariInput, store, links_done: int) -> None:
    from claytonlib.chart.chain import chain_at_time, evaluate_chain_link

    n = min(_config.resume_validation_frames, links_done)
    delay, times = get_times(inputs.key_seed)

    for writer, time in zip(writers, times):
        # Reconstruct a generator starting n links before the resume point
        recheck_offset = inputs.setup_delay_seconds + links_done - n
        gen = chain_at_time(
            time + dt.timedelta(seconds=recheck_offset),
            delay + recheck_offset * 60,
        )
        expected = [evaluate_chain_link(next(gen), inputs.pokemon, inputs.strategy, inputs.criteria) for _ in range(n)]
        actual = store.read_tail(writer.path, n)
        if expected != actual:
            msg = "Resume validation failed for %s: expected %s, got %s"
            if _config.resume_strict:
                raise RuntimeError(msg % (writer.path, expected, actual))
            else:
                logger.warning(msg, writer.path, expected, actual)


def chart_safari(inputs: ChartSafariInput, store=None) -> None:
    import time as time_mod
    from claytonlib.chart.chain import evaluate_chain_link_cached

    if store is None:
        from claytonlib.chart.chain import LocalChainStore
        store = LocalChainStore()

    total_links = inputs.max_target_seconds - inputs.setup_delay_seconds + 1
    writers, links_done = _initialize_writers(inputs, store)

    if not writers:
        logger.info("All chains already complete, nothing to do.")
        return

    if _config.resume_validation_enabled and links_done > 0:
        _validate_resume(writers, inputs, store, links_done)

    logger.info("Charting %d chain(s), links %d-%d.", len(writers), links_done, total_links - 1)

    while links_done < total_links:
        batch = min(_config.evaluation_frames_per_write_cycle, total_links - links_done)

        t0 = time_mod.perf_counter()
        for _ in range(batch):
            for writer in writers:
                link = next(writer.generator)
                writer.buffer.append(evaluate_chain_link_cached(link, inputs.pokemon, inputs.strategy, inputs.criteria))
            evaluate_chain_link_cached.cache_clear()
        t1 = time_mod.perf_counter()

        for writer in writers:
            store.append(writer.path, writer.buffer)
            writer.buffer.clear()
        t2 = time_mod.perf_counter()

        links_done += batch
        logger.info("links %d-%d: eval=%.3fs write=%.3fs",
                    links_done - batch, links_done - 1, t1 - t0, t2 - t1)


# ---------------------------------------------------------------------------
# evaluate_chart
# ---------------------------------------------------------------------------

def evaluate_chart(inputs: ChartSafariInput, strategy, store=None, eval_max_seconds: int | None = None) -> None:
    """
    Evaluate a completed chart and write results to the evaluations subdirectory.

    Reads all chain files in the chart directory, scores each frame using
    the given EvaluationStrategy, and writes a JSON file at:
        <chart_dir>/evaluations/<strategy.filename>.json

    If eval_max_seconds is set and less than the full chain length, only links
    up to that many seconds are scored, and the output is written to:
        <chart_dir>/evaluations/<strategy.filename>_MAX_<eval_max_seconds>s.json

    The output contains per-chain top-5 results and a cross-chain top-10
    (deduplicated by (delay, score)) with the source chain name included.

    Parameters
    ----------
    inputs:
        The same ChartSafariInput used to produce the chart.
    strategy:
        An EvaluationStrategy instance that defines the scoring logic and
        output filename.
    store:
        Optional ChainStore override (defaults to LocalChainStore).
    eval_max_seconds:
        If set, truncate chains to this many seconds (from time 0) before
        scoring. Uses a suffixed filename unless this equals the full chain
        length.
    """
    import time as time_mod
    from claytonlib.chart.chain import LocalChainStore
    from claytonlib.chart.evaluation import straighten_chain, _gather_top5, _gather_best

    t_start = time_mod.perf_counter()

    if store is None:
        store = LocalChainStore()

    chart_dir = _output_dir(inputs)
    base_delay, _ = get_times(inputs.key_seed)

    def _chain_setup_delay(path: Path) -> int:
        return int(path.stem.split('+')[1])

    def _chain_initial_time(path: Path) -> dt.datetime:
        return dt.datetime.strptime(path.stem.split('+')[0], '%Y-%m-%d_%H-%M-%S')

    def _flush(data: EvaluationData) -> None:
        # top10: plain sorted ranking across all chains
        seen: set[tuple] = set()
        top_candidates: list[CrossChainResult] = []
        for chain_name, result in data.results.items():
            for r in result.top5:
                key = (r.delay, r.score)
                if key not in seen:
                    seen.add(key)
                    top_candidates.append(CrossChainResult(
                        score=r.score, delay=r.delay, time=r.time, chain=chain_name,
                    ))
        top_candidates.sort(key=lambda r: (-r.score, r.delay))
        data.top10 = top_candidates[:10]

        # best10: greedy descending-delay chain across all chains,
        # pooling each chain's top5 and best5 as candidates
        seen2: set[tuple] = set()
        best_candidates: list[tuple] = []  # (delay, score, time, chain)
        for chain_name, result in data.results.items():
            for r in result.top5 + result.best5:
                key = (r.delay, r.score, chain_name)
                if key not in seen2:
                    seen2.add(key)
                    best_candidates.append((r.delay, r.score, r.time, chain_name))
        best10: list[CrossChainResult] = []
        max_delay = None
        for _ in range(10):
            pool = [c for c in best_candidates if max_delay is None or c[0] < max_delay]
            if not pool:
                break
            delay, score, time_str, chain_name = max(pool, key=lambda c: (c[1], -c[0]))
            best10.append(CrossChainResult(score=score, delay=delay, time=time_str, chain=chain_name))
            max_delay = delay
        data.best10 = best10

        write_evaluation(chart_dir, strategy, data, filename_override=_filename_override)

    chain_paths = [
        p for p in store.list_chain_files(chart_dir)
        if _chain_setup_delay(p) == inputs.setup_delay_seconds
    ]

    # Determine filename override and link truncation limit.
    _filename_override: str | None = None
    _max_links: int | None = None
    if eval_max_seconds is not None and chain_paths:
        _eval_max_links = eval_max_seconds - inputs.setup_delay_seconds + 1
        _full_links = store.file_size(chain_paths[0]) // 8
        if _eval_max_links < _full_links:
            _filename_override = f"{strategy.filename}_MAX_{eval_max_seconds}s"
            _max_links = _eval_max_links

    existing = read_evaluation(chart_dir, strategy, filename_override=_filename_override)
    data = existing if existing is not None else EvaluationData(results={}, top10=[], best10=[])

    # Write stubs for any chains not yet present so the file is immediately
    # interruptable and resumable from the first run.
    for path in chain_paths:
        if path.name not in data.results:
            data.results[path.name] = ChainEvaluationResult(max_links_checked=0, top5=[])
    _flush(data)

    t_total_start = time_mod.perf_counter()
    t_batch_start = t_total_start
    chains_since_write = 0

    for path in chain_paths:
        links = store.read_all(path)
        if _max_links is not None:
            links = links[:_max_links]
        max_links_checked = len(links)

        existing_result = data.results.get(path.name)
        if existing_result is not None and existing_result.max_links_checked == max_links_checked:
            continue

        initial_time = _chain_initial_time(path)

        t0 = time_mod.perf_counter()
        flat = straighten_chain(links)
        t1 = time_mod.perf_counter()
        scored = strategy.score(flat)
        t2 = time_mod.perf_counter()
        top5 = _gather_top5(scored, base_delay, inputs.setup_delay_seconds, initial_time)
        best5 = _gather_best(scored, base_delay, inputs.setup_delay_seconds, initial_time, n=5)
        t3 = time_mod.perf_counter()

        data.results[path.name] = ChainEvaluationResult(
            max_links_checked=max_links_checked, top5=top5, best5=best5,
        )
        logger.info(
            "chain %s: flatten=%.3fs score=%.3fs results=%.3fs total=%.3fs",
            path.name, t1 - t0, t2 - t1, t3 - t2, t3 - t0,
        )

        chains_since_write += 1
        if chains_since_write >= _config.evaluation_chains_per_write_cycle:
            t_before_flush = time_mod.perf_counter()
            _flush(data)
            t_after_flush = time_mod.perf_counter()
            logger.info(
                "checkpoint: evaluated %d chain(s) in %.3fs, wrote in %.3fs",
                chains_since_write, t_before_flush - t_batch_start, t_after_flush - t_before_flush,
            )
            t_batch_start = t_after_flush
            chains_since_write = 0

    t_chains_done = time_mod.perf_counter()
    _flush(data)
    t_top10_done = time_mod.perf_counter()
    logger.info(
        "top10 across %d chain(s): %.3fs",
        len(chain_paths), t_top10_done - t_chains_done,
    )
    logger.info("evaluate_chart complete in %.3fs", t_top10_done - t_start)


def evaluate_chart_top_10(inputs: ChartSafariInput, strategy, store=None) -> None:
    """Run evaluate_chart (if not already up to date) and print the top 10 results."""
    evaluate_chart(inputs, strategy, store)

    chart_dir = _output_dir(inputs)
    data = read_evaluation(chart_dir, strategy)

    if not data or not data.top10:
        print("No results found.")
        return

    base_delay, _ = get_times(inputs.key_seed)

    def _fmt_time_diff(delay_from_key: int) -> str:
        total_s = delay_from_key / 60
        m = int(total_s) // 60
        s = total_s - m * 60
        return f"{m}m {s:.3f}s"

    def _fmt_initial_time(chain: str) -> str:
        time_str = chain.split('+')[0]
        d = dt.datetime.strptime(time_str, '%Y-%m-%d_%H-%M-%S')
        return d.strftime('%Y-%m-%d %H:%M:%S')

    def _print_table(rows: list[CrossChainResult], title: str) -> None:
        header = f"{'#':>2}  {'Score(p)':>14}  {'Delay':>7}  {'Time':>8}  {'Δ Time':>12}  Initial Time"
        print(title)
        print(header)
        print("-" * len(header))
        for i, r in enumerate(rows, 1):
            delay_from_key = r.delay - base_delay
            prob = strategy.score_to_probability(r.score)
            score_col = f"{r.score}({prob * 100:.1f}%)"
            print(
                f"{i:>2}  {score_col:>14}  {r.delay:>7}  "
                f"{r.time:>8}  {_fmt_time_diff(delay_from_key):>12}  {_fmt_initial_time(r.chain)}"
            )

    _print_table(data.top10, "Top 10 (by score)")
    print()
    _print_table(data.best10, "Best 10 (highest score at each successively lower delay)")
