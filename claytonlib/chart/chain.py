"""
chain.py — Chain and chain link utilities.

A chain link is a (from_seed, to_seed, n_delays) tuple. Expanding a link
produces the candidate seeds across all delays of that second, two per delay:
one assuming the current second (seed_a), one assuming the next second (seed_b).
(A delay is one game frame; the terms are interchangeable.)

n_delays is 59 or 60 depending on where this second falls in the VBlank/RTC
phase cycle. The packed bitmask stored in chain files encodes the evaluation
result: bit 2j = seed_a result, bit 2j+1 = seed_b result for delay j.
Bit 120 is set when the link has 59 delays.
"""

import datetime as dt
import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

from .evaluation import (
    DPS, FPS, FPS_CEIL, OFPS, SPF,
    offset_frames, frames_in_second, cumulative_frames, delay_at_second,
)
from . import Strategy, SuccessCriteria, evaluate_seed
from claytonlib.safari import SafariPokemon
from claytonlib.times import calculate_seed

ChainLink = tuple[int, int, int]  # (from_seed, to_seed, n_delays)

_LINK_SIZE = 16  # bytes per link (128-bit integer, little-endian)
_WIDTH_BIT = 120


# ---------------------------------------------------------------------------
# ChainStore protocol + LocalChainStore
# ---------------------------------------------------------------------------

class ChainStore(Protocol):
    def exists(self, path: Path) -> bool: ...
    def file_size(self, path: Path) -> int: ...
    def read_all(self, path: Path) -> list[int]: ...
    def read_tail(self, path: Path, n_links: int) -> list[int]: ...
    def truncate(self, path: Path, size: int) -> None: ...
    def append(self, path: Path, values: list[int]) -> None: ...
    def ensure_dir(self, path: Path) -> None: ...
    def list_chain_files(self, directory: Path) -> list[Path]: ...


class LocalChainStore:
    def exists(self, path: Path) -> bool:
        return path.exists()

    def file_size(self, path: Path) -> int:
        return path.stat().st_size if path.exists() else 0

    def read_all(self, path: Path) -> list[int]:
        size = self.file_size(path)
        n_links = size // _LINK_SIZE
        if n_links == 0:
            return []
        with open(path, 'rb') as f:
            data = f.read(n_links * _LINK_SIZE)
        return [int.from_bytes(data[i*_LINK_SIZE:(i+1)*_LINK_SIZE], 'little') for i in range(n_links)]

    def read_tail(self, path: Path, n_links: int) -> list[int]:
        size = self.file_size(path)
        n_links = min(n_links, size // _LINK_SIZE)
        if n_links == 0:
            return []
        offset = size - n_links * _LINK_SIZE
        with open(path, 'rb') as f:
            f.seek(offset)
            data = f.read(n_links * _LINK_SIZE)
        return [int.from_bytes(data[i*_LINK_SIZE:(i+1)*_LINK_SIZE], 'little') for i in range(n_links)]

    def truncate(self, path: Path, size: int) -> None:
        with open(path, 'ab') as f:
            f.truncate(size)

    def append(self, path: Path, values: list[int]) -> None:
        with open(path, 'ab') as f:
            f.write(b''.join(v.to_bytes(_LINK_SIZE, 'little') for v in values))

    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def list_chain_files(self, directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(directory.glob('*.chain'))


# ---------------------------------------------------------------------------
# Chain generation and evaluation
# ---------------------------------------------------------------------------

@dataclass
class EvaluationChain:
    initial_time: dt.datetime
    initial_delay: int
    setup_delay_seconds: int
    evaluation_code: str
    evaluations: list[int] = field(default_factory=list)


@dataclass
class ChainWriter:
    path: Path
    generator: Iterator[ChainLink]
    buffer: list[int] = field(default_factory=list)


def chain_at_time(time: dt.datetime, delay: int, start_second: int = 0) -> Iterator[ChainLink]:
    """Yield ChainLink tuples indefinitely from the given starting point.

    Parameters
    ----------
    time:
        The RTC datetime at the start of the first link.
    delay:
        The delay counter value at the start of the first link.
    start_second:
        The second index (0 = key seed moment) of the first link.
        Used to determine the correct n_frames per second.
    """
    from_seed = calculate_seed(time, delay)
    s = start_second
    while True:
        n = frames_in_second(s)
        next_delay = delay + n
        next_time = time + dt.timedelta(seconds=1)
        to_seed = calculate_seed(next_time, next_delay)
        yield (from_seed, to_seed, n)
        time = next_time
        delay = next_delay
        from_seed = to_seed
        s += 1


def link_at_time(time: dt.datetime, delay: int, s: int) -> ChainLink:
    n = frames_in_second(s)
    to_seed = calculate_seed(time + dt.timedelta(seconds=1), delay + n)
    return (calculate_seed(time, delay), to_seed, n)


@functools.lru_cache(maxsize=None)
def evaluate_chain_link_cached(link: ChainLink, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> int:
    return evaluate_chain_link(link, pokemon, strategy, criteria)


def evaluate_chain_link(link: ChainLink, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> int:
    _, _, n = link
    result = 0
    for bit_idx, seed in enumerate(expand_chain_link(link)):
        if evaluate_seed(seed, pokemon, strategy, criteria):
            result |= (1 << bit_idx)
    if n == 59:
        result |= (1 << _WIDTH_BIT)
    return result


def expand_chain_link(link: ChainLink) -> list[int]:
    """Expand a ChainLink into a flat list of seeds: [seed_a_0, seed_b_0, seed_a_1, seed_b_1, ...]

    For delay j (0-based):
      seed_a(j) = from_seed + j   = calculate_seed(T,   D + j)
      seed_b(j) = to_seed - (n-j) = calculate_seed(T+1, D + j)
    """
    f, t, n = link
    t_base = t - n
    result = []
    for j in range(n):
        result.append(f + j)        # seed_a: current second
        result.append(t_base + j)   # seed_b: next second
    return result
