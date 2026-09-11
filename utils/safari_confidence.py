"""Section B confidence / neighbor search for the Safari Compass Calibration notebook.

After the safari battle resolves (Metang captured or fled), gauge how confident
we are in the identified seed by finding OTHER nearby seeds that reproduce the
*exact same* observed path -- aliases the identification window could not have
distinguished.  Because identical-path density is much higher in the safari than
for metronome, a handful of close aliases is expected; many is a red flag.

Seed layout: ``seed = (mds<<24) | (hour<<16) + frame`` (see chart.canon), so the
low 16 bits are the frame/delay and the upper 16 bits the datetime-derived
"mdmsh" key.  We scan three axes around the identified seed --

  * **frame ±** a configurable range (the delay axis, seed ± 1 per step),
  * **mdmsh ± 1** (the upper-16 field, seed ± 0x10000: an adjacent datetime key),
  * the **RTC second** δ ∈ {-1, 0, +1} (the "3 seconds": a one-second timing slip
    shifts the datetime, hence the mds byte),

replay the observed path against each candidate, and report the nearest
surviving aliases ranked by (|Δframe|, |Δmdmsh|).

``find_path_neighbors`` (the core) takes an explicit set of candidate seeds and
is pure/testable; ``neighbor_grid`` builds the default grid from a run's timing;
``path_confidence`` ties them together for the notebook using a CompassSafariInput.
"""
import datetime as dt
from dataclasses import dataclass

from claytonlib.compass import _replay_path, parse_input, ParseError
from claytonlib.compass._core import _second_of_frame
from claytonlib.chart.canon import mdmsh_of, seed_for_mdmsh
from claytonlib.safari import SafariContext
from claytonlib.times import get_times

_SEED_MASK = 0xFFFFFFFF
_FRAME_MASK = 0xFFFF

DEFAULT_FRAME_RANGE = 60
DEFAULT_MDMSH_DELTAS = (-1, 0, 1)
DEFAULT_SECOND_DELTAS = (-1, 0, 1)
DEFAULT_MAX_NEIGHBORS = 6


def frame_of(seed):
    """The frame/delay (low 16 bits) of a seed."""
    return seed & _FRAME_MASK


def mdmsh_of_seed(seed):
    """The mdmsh key (upper 16 bits) of a seed."""
    return (seed >> 16) & _FRAME_MASK


@dataclass(frozen=True)
class Neighbor:
    """An aliasing seed that reproduces the observed path, and how far it is."""
    seed: int
    dframe: int   # frame(seed) - frame(identified)
    dmdmsh: int   # mdmsh(seed) - mdmsh(identified)

    @property
    def seed_hex(self):
        return f"0x{self.seed:08X}"

    @property
    def distance(self):
        """Ranking key: nearer in frame first, then in mdmsh."""
        return (abs(self.dframe), abs(self.dmdmsh))


def _parse_path(observed_path):
    """Accept either a raw compass path string or an already-parsed action list."""
    if isinstance(observed_path, str):
        actions = parse_input(observed_path)
        if isinstance(actions, ParseError):
            raise ValueError(f"unparseable observed path: {observed_path!r} ({actions})")
        return actions
    return list(observed_path)


def _surviving_seeds(candidate_seeds, pokemon, actions, ball_count):
    """Seeds whose simulated path matches the observed one (replayed via compass)."""
    triples = []
    for s in candidate_seeds:
        ctx = SafariContext.start_encounter(s, pokemon)
        ctx.balls_remaining = ball_count
        triples.append((ctx, s, frame_of(s)))
    cache, pending = _replay_path(triples, actions)
    survivors = pending[1] if pending is not None else cache[-1][1]
    return [s for _ctx, s, _f in survivors]


def find_path_neighbors(identified_seed, candidate_seeds, pokemon, observed_path,
                        *, ball_count=30, max_neighbors=DEFAULT_MAX_NEIGHBORS):
    """Nearest aliasing seeds (excluding ``identified_seed``) that match the path.

    Parameters
    ----------
    identified_seed:
        The seed Section B settled on.
    candidate_seeds:
        Iterable of seeds to test (e.g. from ``neighbor_grid``).  The identified
        seed is ignored if present.
    pokemon:
        The SafariPokemon in the battle (same one used for identification).
    observed_path:
        The compass path string (or parsed action list) observed in the battle.
    ball_count:
        Starting Safari balls (matches the run's options).
    max_neighbors:
        Cap on how many nearest aliases to return.

    Returns a list of ``Neighbor`` sorted nearest-first by (|Δframe|, |Δmdmsh|).
    An empty list means the path was unique across the scanned grid (high
    confidence).
    """
    actions = _parse_path(observed_path)
    id_frame = frame_of(identified_seed)
    id_mdmsh = mdmsh_of_seed(identified_seed)

    unique = {s for s in candidate_seeds if s != identified_seed}
    survivors = _surviving_seeds(unique, pokemon, actions, ball_count)

    neighbors = [
        Neighbor(seed=s,
                 dframe=frame_of(s) - id_frame,
                 dmdmsh=mdmsh_of_seed(s) - id_mdmsh)
        for s in survivors
    ]
    neighbors.sort(key=lambda n: (n.distance, n.seed))
    return neighbors[:max_neighbors]


def neighbor_grid(identified_seed, initial_time, base_delay, *,
                  frame_range=DEFAULT_FRAME_RANGE,
                  mdmsh_deltas=DEFAULT_MDMSH_DELTAS,
                  second_deltas=DEFAULT_SECOND_DELTAS):
    """Candidate seeds on the frame × mdmsh × second grid around the identified seed.

    For each frame in ``[id_frame ± frame_range]`` and each RTC-second offset in
    ``second_deltas``, the reachable seed is built from the real datetime
    (``mdmsh_of(initial_time + second)``) exactly as the compass generates
    candidates; each is then also offset by ``mdmsh_deltas`` on the upper-16
    field to reach adjacent datetime keys.  Returns a deduped set of seeds
    (including the identified seed, which the caller filters out).
    """
    id_frame = frame_of(identified_seed)
    seeds = set()
    for df in range(-frame_range, frame_range + 1):
        frame = id_frame + df
        if not (0 <= frame <= _FRAME_MASK):
            continue
        second0 = _second_of_frame(base_delay, frame)
        for ds in second_deltas:
            second = second0 + ds
            if second < 0:
                continue
            base = seed_for_mdmsh(
                mdmsh_of(initial_time + dt.timedelta(seconds=second)), frame)
            for dm in mdmsh_deltas:
                seed = (base + (dm << 16)) & _SEED_MASK
                if frame_of(seed) == frame:  # a raw mdmsh step must not disturb the frame
                    seeds.add(seed)
    return seeds


def path_confidence(inputs, identified_seed, observed_path, *,
                    frame_range=DEFAULT_FRAME_RANGE,
                    max_neighbors=DEFAULT_MAX_NEIGHBORS):
    """Convenience for the notebook: build the grid from a run's CompassSafariInput
    and return the nearest aliasing neighbors of ``identified_seed``.

    Uses the run's ``key_seed`` (for the base delay), ``initial_time``,
    ``pokemon`` and starting ball count so the grid matches how the seed was
    generated.  See ``find_path_neighbors`` for the return shape.
    """
    base_delay, _ = get_times(inputs.key_seed)
    grid = neighbor_grid(identified_seed, inputs.initial_time, base_delay,
                         frame_range=frame_range)
    return find_path_neighbors(
        identified_seed, grid, inputs.pokemon, observed_path,
        ball_count=inputs.options.starting_ball_count,
        max_neighbors=max_neighbors)


def print_confidence(neighbors, scanned=None):
    """Print a short confidence readout from ``find_path_neighbors`` output."""
    if not neighbors:
        print("No other seed in the scanned window reproduces this path "
              "-- high confidence.")
        return
    print(f"{len(neighbors)} aliasing seed(s) reproduce the same path "
          f"(nearest {'first' if len(neighbors) > 1 else ''}):")
    for n in neighbors:
        print(f"  {n.seed_hex}  Δframe={n.dframe:+d}  Δmdmsh={n.dmdmsh:+d}")
