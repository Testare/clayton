"""
chain.py — Chain and chain link utilities.

A chain link is a tuple (from_seed, to_seed) representing the seeds at
the boundary of one second and the next. Expanding a link produces the
60 candidate seeds across all 30 frames of that second, two per frame:
one assuming the second has not yet advanced, one assuming it has.
"""

import datetime as dt
import functools
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol

from . import Strategy, SuccessCriteria, evaluate_seed
from claytonlib.safari import SafariPokemon
from claytonlib.times import calculate_seed

ChainLink = tuple[int, int]

_LINK_STRUCT = struct.Struct('<Q')


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
        n_links = size // _LINK_STRUCT.size
        if n_links == 0:
            return []
        with open(path, 'rb') as f:
            data = f.read(n_links * _LINK_STRUCT.size)
        return [_LINK_STRUCT.unpack_from(data, i * _LINK_STRUCT.size)[0] for i in range(n_links)]

    def read_tail(self, path: Path, n_links: int) -> list[int]:
        size = self.file_size(path)
        n_links = min(n_links, size // _LINK_STRUCT.size)
        if n_links == 0:
            return []
        offset = size - n_links * _LINK_STRUCT.size
        with open(path, 'rb') as f:
            f.seek(offset)
            data = f.read(n_links * _LINK_STRUCT.size)
        return [_LINK_STRUCT.unpack_from(data, i * _LINK_STRUCT.size)[0] for i in range(n_links)]

    def truncate(self, path: Path, size: int) -> None:
        with open(path, 'ab') as f:
            f.truncate(size)

    def append(self, path: Path, values: list[int]) -> None:
        with open(path, 'ab') as f:
            f.write(b''.join(_LINK_STRUCT.pack(v) for v in values))

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


def chain_at_time(time: dt.datetime, delay: int) -> Iterator[ChainLink]:
    from_seed = calculate_seed(time, delay)
    while True:
        next_time = time + dt.timedelta(seconds=1)
        to_seed = calculate_seed(next_time, delay + 60)
        yield (from_seed, to_seed)
        time = next_time
        delay += 60
        from_seed = to_seed


def link_at_time(time: dt.datetime, delay: int) -> ChainLink:
    from_seed = calculate_seed(time, delay)
    to_seed = calculate_seed(time + dt.timedelta(seconds=1), delay + 60)
    return (from_seed, to_seed)


@functools.lru_cache(maxsize=None)
def evaluate_chain_link_cached(link: ChainLink, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> int:
    return evaluate_chain_link(link, pokemon, strategy, criteria)


def evaluate_chain_link(link: ChainLink, pokemon: SafariPokemon, strategy: Strategy, criteria: SuccessCriteria) -> int:
    result = 0
    for n, seed in enumerate(expand_chain_link(link)):
        if evaluate_seed(seed, pokemon, strategy, criteria):
            result |= (1 << n)
    return result


def expand_chain_link(link: ChainLink) -> list[int]:
    f, t = link
    return [
        f,    f,
        f+2,  t-58,
        f+4,  t-56,
        f+6,  t-54,
        f+8,  t-52,
        f+10, t-50,
        f+12, t-48,
        f+14, t-46,
        f+16, t-44,
        f+18, t-42,
        f+20, t-40,
        f+22, t-38,
        f+24, t-36,
        f+26, t-34,
        f+28, t-32,
        f+30, t-30,
        f+32, t-28,
        f+34, t-26,
        f+36, t-24,
        f+38, t-22,
        f+40, t-20,
        f+42, t-18,
        f+44, t-16,
        f+46, t-14,
        f+48, t-12,
        f+50, t-10,
        f+52, t-8,
        f+54, t-6,
        f+56, t-4,
        f+58, t-2,
    ]
