---
date: 2026-04-21
---

# `chart_safari` Implementation Plan

## Requirements

### Overview
`chart_safari` generates a set of binary `.chain` files that encode, for each possible starting seed derived from a key seed, whether a given Safari Zone strategy succeeds on each second of a target window. These files are later used to identify an optimal target seed and time.

### Inputs
A `ChartSafariInput` dataclass wraps all parameters:

| Field | Type | Description |
|---|---|---|
| `key_seed` | `int` | Upper 16 bits of the seed to chart; passed to `generate_times` |
| `setup_delay_seconds` | `int` | Real-world seconds needed after hitting the key seed before the first encounter is reachable (seed confirmation, RNG advance, Sweet Scent, etc.). Defines the offset into the chain where evaluation begins. |
| `max_target_seconds` | `int` | Last second offset (inclusive) to evaluate |
| `strategy` | `Strategy` | Action sequence to simulate each encounter |
| `criteria` | `SuccessCriteria` | Condition that counts as success |
| `pokemon` | `SafariPokemon` | Target Pokémon |
| `project_label` | `str \| None` | Optional subdirectory to separate projects |

### Chains
`generate_times(key_seed)` returns all year-2000 `(datetime, delay)` pairs that produce the key seed. All returned pairs are used — one chain file per pair. Each chain file stores `(max_target_seconds - setup_delay_seconds + 1)` little-endian 64-bit unsigned integers, one per second. Each integer is the bitmask returned by `evaluate_chain_link` for that second's link.

### Output Layout
```
./data/
  <project_label>/          ← omitted if None
    <pokemon_name>_<8hex_key_seed>/
      chart_<strategy_name>_<criteria_name>/
        <YYYY-MM-DD_HH-MM-SS>+<setup_delay_seconds>.chain
        ...
```

Datetime in the filename uses the initial time (before the setup delay offset), with colons replaced by dashes and the date/time separated by an underscore. The `+<setup_delay_seconds>` suffix disambiguates chains from the same initial time with different offsets.

### Deduplication
Chains are evaluated horizontally — one second at a time across all chains simultaneously. Since many chains share the same `ChainLink` at the same second offset, each unique link is evaluated only once per frame using `@functools.lru_cache` on `evaluate_chain_link`. The cache is cleared after each frame.

### Write Cycles
Evaluations accumulate in memory across multiple frames before being flushed to disk. The number of frames per write cycle is controlled by a module-level setting (`evaluation_frames_per_write_cycle`, default `60`). Each flush appends all buffered values to each chain file and clears the buffer.

### Resume / Interrupt
Restarting `chart_safari` with the same parameters implicitly resumes:

1. **Square off**: Find the smallest file size across all chain files, round down to the nearest multiple of 8, and truncate all files to that size. This corrects partial writes from interrupted runs.
2. **Compute offset**: `already_written = file_size // 8`. Resume each chain's generator at `setup_delay_seconds + already_written` seconds from `initial_time`.
3. **Validation** *(optional, off by default)*: Re-evaluate the last N links (configurable, default 2) and compare against the tail bytes of each chain file. Log a warning or raise, depending on a `strict_resume` setting.
4. **Early exit**: If all chains are already complete (`file_size == total_links * 8`), return immediately.

### Testability
All file I/O goes through a `ChainStore` protocol. Production code uses `LocalChainStore`. Tests inject a `FakeChainStore` backed by in-memory data structures.

### Logging
Per write cycle:
- Seconds evaluated in this cycle
- Time spent evaluating (seconds)
- Time spent writing to disk (seconds)

---

## Design

### `ChartSafariInput`
```python
@dataclass
class ChartSafariInput:
    key_seed: int
    setup_delay_seconds: int
    max_target_seconds: int
    strategy: Strategy
    criteria: SuccessCriteria
    pokemon: SafariPokemon
    project_label: str | None = None
```

`evaluation_code` (used in the output path) is derived as `f"{inputs.strategy.name}_{inputs.criteria.name}"`.

### `ChainStore` Protocol
```python
class ChainStore(Protocol):
    def exists(self, path: Path) -> bool: ...
    def file_size(self, path: Path) -> int: ...
    def read_tail(self, path: Path, n_links: int) -> list[int]: ...
    def truncate(self, path: Path, size: int) -> None: ...
    def append(self, path: Path, values: list[int]) -> None: ...
    def ensure_dir(self, path: Path) -> None: ...
    def list_chain_files(self, directory: Path) -> list[Path]: ...
```

`ChainStore`, `LocalChainStore`, and `FakeChainStore` all live in `claytonlib/chart/chain.py`. `LocalChainStore` implements the protocol using `pathlib` and `struct.pack('<Q', ...)` / `struct.unpack('<Q', ...)`.

### `ChainWriter` (internal)
One per `(initial_time, initial_delay)` pair. Created during initialization, holds:

```python
@dataclass
class ChainWriter:
    path: Path
    generator: Iterator[ChainLink]   # chain_at_time(...) already advanced to resume point
    buffer: list[int] = field(default_factory=list)
```

The generator is constructed as:
```python
start_offset = setup_delay_seconds + already_written
chain_at_time(
    initial_time + timedelta(seconds=start_offset),
    initial_delay + start_offset * 60
)
```

### `ChartConfig`
```python
@dataclass
class ChartConfig:
    evaluation_frames_per_write_cycle: int = 60
    resume_validation_enabled: bool = False
    resume_validation_frames: int = 2
    resume_strict: bool = False  # True = raise on mismatch, False = warn and continue

_config = ChartConfig()

def chart_config() -> ChartConfig:
    return _config
```

Users mutate fields directly: `chart_config().evaluation_frames_per_write_cycle = 120`.

### `chart_safari` Outline
```python
def chart_safari(inputs: ChartSafariInput, store: ChainStore = LocalChainStore()) -> None:
    total_links = inputs.max_target_seconds - inputs.setup_delay_seconds + 1
    writers = _initialize_writers(inputs, store)   # square-off, optional validation, construct generators
    links_done = _get_links_done(writers, store)   # file_size // 8 after square-off

    if links_done >= total_links:
        logger.info("Chart already complete, nothing to do.")
        return

    while links_done < total_links:
        batch = min(chart_config().evaluation_frames_per_write_cycle, total_links - links_done)
        t0 = time.perf_counter()
        for _ in range(batch):
            for writer in writers:
                link = next(writer.generator)
                writer.buffer.append(evaluate_chain_link(link, inputs.pokemon, inputs.strategy, inputs.criteria))
            evaluate_chain_link.cache_clear()
        t1 = time.perf_counter()
        for writer in writers:
            store.append(writer.path, writer.buffer)
            writer.buffer.clear()
        t2 = time.perf_counter()
        links_done += batch
        logger.info("links %d-%d: eval=%.3fs write=%.3fs",
                    links_done - batch, links_done - 1, t1 - t0, t2 - t1)
```

---

## Module Structure

```
claytonlib/
  chart/
    __init__.py     ← Strategy, SuccessCriteria, evaluate_seed, ChartSafariInput, chart_safari
    chain.py        ← ChainLink, ChainWriter, EvaluationChain, ChainStore, LocalChainStore,
                       expand_chain_link, evaluate_chain_link, evaluate_chain_link_cached,
                       chain_at_time, link_at_time
tests/
  testingutils.py  ← FakeChainStore (shared test helper, not a test itself)
  test_chart.py    ← unit and integration tests
```

`evaluate_chain_link_cached` is a thin wrapper around `evaluate_chain_link` decorated with `@functools.lru_cache`, exposed so the caller can invoke `.cache_clear()` between frames cleanly.

---

## Implementation Steps

1. **`ChainStore` protocol + `LocalChainStore`**
   Add to `claytonlib/chart/chain.py`. Implement `LocalChainStore` using `pathlib` and `struct`. Add `FakeChainStore` to `tests/testingutils.py`.

2. **`evaluate_chain_link_cached`**
   Add to `claytonlib/chart/chain.py` as a `@functools.lru_cache`-decorated wrapper around `evaluate_chain_link`.

3. **`ChartSafariInput` and path helpers**
   Add the dataclass to `claytonlib/chart/__init__.py`. Implement `_output_dir(inputs) -> Path` and `_chain_path(inputs, initial_time) -> Path` helpers producing the correct directory and filename.

4. **Cached initial times**
   `generate_times(key_seed)` results are cached to disk under `./data/times/<8hex_key_seed>.json`. File format (see existing reference):
   ```json
   { "delay": 1244, "times": ["2000-04-30 21:57:59", ...] }
   ```
   The `delay` is `key_seed & 0xFFFF`; all times share the same delay since it is encoded in the seed. Add a `get_times(key_seed) -> tuple[int, list[datetime]]` function to `claytonlib/times.py` that checks for a cached file, loads it if present, otherwise calls `generate_times` and writes the cache. Putting this in `times.py` keeps it available to compass and machete as well.

5. **`ChainWriter` and `_initialize_writers`**
   Add `ChainWriter` to `claytonlib/chart/chain.py`. Implement `_initialize_writers(inputs, store) -> list[ChainWriter]` in `__init__.py`: load cached times, compute `already_written` per chain, perform square-off, construct each generator from the correct resume offset (`setup_delay_seconds + already_written` seconds from `initial_time`).

6. **Main evaluation loop**
   Implement `chart_safari` body in `__init__.py`: batch loop, `evaluate_chain_link_cached` with `.cache_clear()` per frame, write-cycle flushing, performance logging.

7. **`ChartConfig`**
   Add `ChartConfig` dataclass, `_config` instance, and `chart_config()` to `claytonlib/chart/__init__.py`.

8. **Resume validation**
   Implement `_validate_resume(writers, inputs, store)`: re-evaluate last N links per writer, compare to `store.read_tail`. Warn or raise per `_resume_strict`. Call from `_initialize_writers` when `_resume_validation_enabled`.

9. **Integration test**
   End-to-end test in `tests/test_chart.py` using `FakeChainStore` with a known seed, Pokémon, and strategy. Assert correct file contents and correct resume behavior after a simulated partial write.

10. **Future work** *(not in scope)*
    - `ProcessPoolExecutor`-based parallel evaluation as an alternative to `lru_cache`
