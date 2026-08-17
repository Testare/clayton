"""Generate a TSV of precomputed paths for every Metronome-usable move.

Two seeds per move (offset=0 and offset=1) are generated using reverse-RNG
so that Turn 1 always produces that move. Paths are computed with a level-2
Magikarp (Splash only) to keep the Magikarp side of each turn simple.

Output: data/move_paths.tsv
Columns: move_name, move_num, seed, path
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claytonlib.moves import _moves_by_number
from claytonlib.metronome_compass import precompute_path, render_path
from claytonlib.testing_utils import generate_seed_for_move

MAGIKARP_LEVEL = 2
N_TURNS = 5
OFFSETS = (0, 1)
OUTPUT = Path(__file__).resolve().parent.parent / "data" / "move_paths.tsv"


def main() -> None:
    moves = _moves_by_number()
    metronome_moves = sorted(
        (m for m in moves.values() if m.metronome_usable),
        key=lambda m: m.number,
    )

    rows: list[tuple[str, int, str, str]] = []
    for move in metronome_moves:
        for offset in OFFSETS:
            seed = generate_seed_for_move(move.name, magikarp_level=MAGIKARP_LEVEL, offset=offset)
            path = precompute_path(
                seed,
                magikarp_level=MAGIKARP_LEVEL,
                opposite_gender=False,
                n_turns=N_TURNS,
            )
            rows.append((move.name, move.number, f"0x{seed:08X}", render_path(path)))

    with open(OUTPUT, "w") as f:
        f.write("move_name\tmove_num\tseed\tpath\n")
        for move_name, move_num, seed_hex, path_str in rows:
            f.write(f"{move_name}\t{move_num}\t{seed_hex}\t{path_str}\n")

    print(f"Wrote {len(rows)} rows to {OUTPUT}")


if __name__ == "__main__":
    main()
