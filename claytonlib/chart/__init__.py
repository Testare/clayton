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
    "Only balls",
    lambda ctx: ctx.throw_ball()
)

STRATEGY_ONE_MUD = Strategy(
    "One mud then balls",
    lambda ctx: ctx.throw_mud() if ctx.turn_count == 0 else ctx.throw_ball()
)

STRATEGY_SIX_BAIT = Strategy(
    "Six bait then balls",
    lambda ctx: ctx.throw_bait() if ctx.turn_count < 6 else ctx.throw_ball()
)

CRITERIA_CAPTURE = SuccessCriteria(
    "Capture",
    lambda ctx: ctx.captured()
)

CRITERIA_WONT_FLEE_10_TURNS = SuccessCriteria(
    "Survived 10 turns without fleeing",
    lambda ctx: ctx.turn_count >= 10 and ctx.is_watching()
)

def evaluate_seed(seed: int, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> bool:
    ctx = SafariContext.start_encounter(seed, pokemon)
    while ctx.is_watching():
        strategy.take_action(ctx)
        if criteria.met(ctx):
            return True
    return False


CRITERIA_CAPTURE_MACHETE_AFTER_3_BALLS = SuccessCriteria(
    "Capture via machete after 3 balls",
    lambda ctx: True  # TODO: implement
)


# ---------------------------------------------------------------------------
# ChartConfig
# ---------------------------------------------------------------------------

@dataclass
class ChartConfig:
    evaluation_frames_per_write_cycle: int = 60
    resume_validation_enabled: bool = False
    resume_validation_frames: int = 2
    resume_strict: bool = False  # True = raise on mismatch, False = warn and continue

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

def evaluate_chart(inputs: ChartSafariInput, strategy, store=None) -> None:
    """
    Evaluate a completed chart and write results to the evaluations subdirectory.

    Reads all chain files in the chart directory, scores each frame using
    the given EvaluationStrategy, and writes a JSON file at:
        <chart_dir>/evaluations/<strategy.filename>.json

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
    """
    # TODO: implement
    raise NotImplementedError
