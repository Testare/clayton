"""
grid.py — Second-indexed capture grid (the "swap the axes" chain rework).

Supersedes the frame-indexed, 2-bit-per-frame packed links of chain.py/evaluation.py.
A grid stores, per RTC second, a **1-bit-per-frame** bitmask of
``capture(calculate_seed(T, D))`` over a wide frame band ``D in [center-W, center+W]``.
Consecutive rows' bands overlap (W >> ~60 frames/second), so a given absolute frame is
covered by many rows — that overlap is what provides "multiple candidate seeds per frame"
without any per-frame variable structure.

The band is **calibration-independent**: its half-width comes from a fixed conservative
ceiling (``BandPolicy``), NOT the live sigma.  The live sigma(M) kernel is applied at
scoring time and fits inside the stored band by construction, so calibration/loop-back
updates never invalidate the (expensive) precomputed grid.

This module is the storage + geometry foundation only: band math, row bit-packing, and a
self-describing binary store (fixed-width rows + a JSON sidecar header, appended per second
and resumable by fixed stride).  Generation (evaluating seeds into rows) and scoring
(reading rows under a sigma(M) kernel) build on top of it.

See notes/refined_chart.md section 6.5.
"""
import json
import math
import os
from dataclasses import asdict, dataclass, field

from claytonlib.chart.evaluation import DPS, cumulative_frames, delay_at_second

GRID_FORMAT_VERSION = 1


# ---------------------------------------------------------------------------
# Band policy (calibration-independent coverage width)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BandPolicy:
    """How wide a frame band each second's row covers.

    The half-width is ``ceil(k * c_ceiling * sqrt(M))`` frames, where M is the commanded
    countdown (ms) a battle at that absolute frame corresponds to.  ``c_ceiling`` is a fixed
    conservative ceiling on the jitter coefficient (today's fitted value is ~0.128), so the
    stored grid does not depend on the live calibration.
    """
    k: float = 3.5
    c_ceiling: float = 0.16
    nominal_rate: float = DPS  # frames/s, maps absolute frame <-> approximate M (ms)

    def m_ms_for_frame(self, center_frame: int) -> float:
        """Approximate commanded countdown M (ms) for a battle at this absolute frame."""
        return max(0.0, center_frame * 1000.0 / self.nominal_rate)

    def half_width(self, center_frame: int) -> int:
        """Band half-width in frames at an absolute frame (grows ~sqrt of the frame)."""
        M = self.m_ms_for_frame(center_frame)
        return int(math.ceil(self.k * self.c_ceiling * math.sqrt(M)))


# ---------------------------------------------------------------------------
# Header / geometry
# ---------------------------------------------------------------------------

@dataclass
class GridHeader:
    """Self-describing geometry for a capture grid (persisted as a JSON sidecar).

    Rows are indexed 0..n_seconds-1, row r being RTC second (setup_delay_seconds + r).
    Row r covers absolute frames [center(r) - w_max, center(r) + w_max] where
    center(r) = delay_at_second(base_delay, setup_delay_seconds + r); bit i of the row is
    frame center(r) - w_max + i.  All rows share the padded width row_width_bits = 2*w_max+1
    (so the file is fixed-stride / resumable); the per-second *evaluated* band is the
    narrower policy.half_width(center(r)).
    """
    base_delay: int
    setup_delay_seconds: int
    max_target_seconds: int
    policy: dict                       # asdict(BandPolicy)
    w_max: int
    row_width_bits: int
    n_seconds: int
    format_version: int = GRID_FORMAT_VERSION

    # -- geometry helpers --------------------------------------------------
    def band_policy(self) -> BandPolicy:
        return BandPolicy(**self.policy)

    def center(self, row: int) -> int:
        """Absolute frame at the centre of row `row`."""
        return delay_at_second(self.base_delay, self.setup_delay_seconds + row)

    def eval_half_width(self, row: int) -> int:
        """Half-width actually worth evaluating for this row (<= w_max)."""
        return min(self.w_max, self.band_policy().half_width(self.center(row)))

    def frame_to_bit(self, row: int, frame: int) -> int | None:
        """Bit index within `row` for absolute `frame`, or None if outside the padded band."""
        i = frame - (self.center(row) - self.w_max)
        return i if 0 <= i < self.row_width_bits else None

    def bit_to_frame(self, row: int, bit: int) -> int:
        return self.center(row) - self.w_max + bit

    def row_bytes(self) -> int:
        return (self.row_width_bits + 7) // 8


def build_header(base_delay: int, setup_delay_seconds: int, max_target_seconds: int,
                 policy: BandPolicy = BandPolicy()) -> GridHeader:
    """Compute the padded geometry for a grid over [setup, max_target] seconds."""
    seconds = range(setup_delay_seconds, max_target_seconds + 1)
    centers = [delay_at_second(base_delay, s) for s in seconds]
    w_max = max((policy.half_width(c) for c in centers), default=0)
    return GridHeader(
        base_delay=base_delay,
        setup_delay_seconds=setup_delay_seconds,
        max_target_seconds=max_target_seconds,
        policy=asdict(policy),
        w_max=w_max,
        row_width_bits=2 * w_max + 1,
        n_seconds=len(centers),
    )


# ---------------------------------------------------------------------------
# Row bit-packing (little-endian bit order within the byte payload)
# ---------------------------------------------------------------------------

def pack_row(width_bits: int, set_bits) -> bytes:
    """Pack an iterable of set bit-indices into a width_bits-wide little-endian bitmask."""
    buf = bytearray((width_bits + 7) // 8)
    for i in set_bits:
        if 0 <= i < width_bits:
            buf[i >> 3] |= 1 << (i & 7)
    return bytes(buf)


def get_bit(row: bytes, i: int) -> bool:
    return bool(row[i >> 3] & (1 << (i & 7)))


def iter_set_bits(row: bytes, width_bits: int):
    """Yield the set bit-indices of a packed row (0..width_bits-1)."""
    for i in range(width_bits):
        if row[i >> 3] & (1 << (i & 7)):
            yield i


# ---------------------------------------------------------------------------
# Store: fixed-stride binary rows + JSON sidecar header
# ---------------------------------------------------------------------------

@dataclass
class GridFile:
    """A single grid: binary rows at `path`, JSON header at `path + '.json'`.

    Rows are appended in second order; because every row is row_bytes() wide, the file is a
    fixed stride and generation resumes from rows_written().
    """
    path: str
    header: GridHeader | None = None

    @property
    def header_path(self) -> str:
        return self.path + ".json"

    # -- header I/O --------------------------------------------------------
    def write_header(self) -> None:
        if self.header is None:
            raise ValueError("no header to write")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.header_path, "w") as f:
            json.dump(asdict(self.header), f, indent=2)

    def read_header(self) -> GridHeader:
        with open(self.header_path) as f:
            self.header = GridHeader(**json.load(f))
        return self.header

    def header_exists(self) -> bool:
        return os.path.exists(self.header_path)

    # -- row I/O -----------------------------------------------------------
    def _row_bytes(self) -> int:
        if self.header is None:
            self.read_header()
        return self.header.row_bytes()

    def rows_written(self) -> int:
        if not os.path.exists(self.path):
            return 0
        return os.path.getsize(self.path) // self._row_bytes()

    def append_rows(self, rows) -> None:
        rb = self._row_bytes()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "ab") as f:
            for row in rows:
                if len(row) != rb:
                    raise ValueError(f"row is {len(row)} bytes, expected {rb}")
                f.write(row)

    def read_row(self, index: int) -> bytes:
        rb = self._row_bytes()
        with open(self.path, "rb") as f:
            f.seek(index * rb)
            data = f.read(rb)
        if len(data) != rb:
            raise IndexError(f"row {index} out of range")
        return data

    def read_all(self) -> list[bytes]:
        rb = self._row_bytes()
        if not os.path.exists(self.path):
            return []
        with open(self.path, "rb") as f:
            data = f.read()
        return [data[i:i + rb] for i in range(0, len(data), rb)]

    # -- generation --------------------------------------------------------
    def generate(self, initial_time, pokemon, strategy, criteria, batch_rows: int = 8,
                 progress=None) -> int:
        """Fill this grid by evaluating capture over each second's band; returns rows written.

        Row r is RTC second (setup_delay_seconds + r), whose datetime is
        ``initial_time + (setup_delay_seconds + r) seconds``; for each absolute frame D in the
        row's evaluated band, bit is set iff ``calculate_seed(datetime, D)`` captures under
        (strategy, criteria).  Only the calibration-independent band is evaluated; the row is
        padded to the shared width.  Resumable: generation continues from rows_written().
        """
        import datetime as _dt
        from claytonlib.times import calculate_seed
        from claytonlib.chart import evaluate_seed  # lazy: avoids an import cycle

        if self.header is None:
            self.read_header()
        h = self.header
        start = self.rows_written()
        buf: list[bytes] = []
        for r in range(start, h.n_seconds):
            t = initial_time + _dt.timedelta(seconds=h.setup_delay_seconds + r)
            center = h.center(r)
            w = h.eval_half_width(r)
            set_bits = []
            for frame in range(center - w, center + w + 1):
                if evaluate_seed(calculate_seed(t, frame), pokemon, strategy, criteria):
                    set_bits.append(frame - (center - h.w_max))  # bit index within the row
            buf.append(pack_row(h.row_width_bits, set_bits))
            if len(buf) >= batch_rows:
                self.append_rows(buf)
                buf.clear()
                if progress is not None:
                    progress(self.rows_written(), h.n_seconds)
        if buf:
            self.append_rows(buf)
            if progress is not None:
                progress(self.rows_written(), h.n_seconds)
        return self.rows_written()

    # -- convenience: capture lookup --------------------------------------
    def captured(self, row_index: int, frame: int) -> bool:
        """Whether calculate_seed(second, frame) is a capture, from the stored grid.

        False if `frame` is outside row_index's padded band (treat unknown as no-capture).
        """
        if self.header is None:
            self.read_header()
        bit = self.header.frame_to_bit(row_index, frame)
        if bit is None:
            return False
        return get_bit(self.read_row(row_index), bit)
