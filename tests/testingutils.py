"""
testingutils.py — Shared test helpers (not test cases themselves).
"""

from pathlib import Path


class FakeChainStore:
    """In-memory ChainStore implementation for use in unit tests."""

    def __init__(self):
        self._files: dict[Path, bytearray] = {}
        self._dirs: set[Path] = set()

    def exists(self, path: Path) -> bool:
        return path in self._files

    def file_size(self, path: Path) -> int:
        return len(self._files.get(path, b''))

    def read_tail(self, path: Path, n_links: int) -> list[int]:
        data = self._files.get(path, bytearray())
        link_size = 16
        n_links = min(n_links, len(data) // link_size)
        if n_links == 0:
            return []
        offset = len(data) - n_links * link_size
        return [int.from_bytes(data[offset + i*link_size:offset + (i+1)*link_size], 'little') for i in range(n_links)]

    def truncate(self, path: Path, size: int) -> None:
        if path in self._files:
            del self._files[path][size:]

    def append(self, path: Path, values: list[int]) -> None:
        if path not in self._files:
            self._files[path] = bytearray()
        for v in values:
            self._files[path] += v.to_bytes(16, 'little')

    def ensure_dir(self, path: Path) -> None:
        self._dirs.add(path)

    def list_chain_files(self, directory: Path) -> list[Path]:
        return sorted(p for p in self._files if p.parent == directory and p.suffix == '.chain')

    def read_all(self, path: Path) -> list[int]:
        """Test helper: read all link values from a chain file."""
        data = self._files.get(path, bytearray())
        n = len(data) // 16
        return [int.from_bytes(data[i*16:(i+1)*16], 'little') for i in range(n)]
