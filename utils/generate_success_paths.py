#!/usr/bin/env python3
"""generate_success_paths.py -- turn target-successful seeds into slurper command strings.

After the safari catch-rate /3 fix (clayton-ctd.15) the precompute charts are being rerun.
To confirm the new "successful" seeds really do capture on the emulator, this script takes the
seeds the chart flags as successful (one hex seed per line on STDIN) and, for each:

  1. Reproduces the chart's own strategy: throw 6 Bait, then 5 Balls, then hand the resulting
     mid-encounter state to ``machete_one`` for the shortest capture suffix.
  2. Concatenates prefix + suffix into a full compass path (e.g. ``bbbbbb01230...C``).
  3. Converts that path into a run-length safari-slurper command string, grouping by ACTION
     TYPE (bait / mud / ball), so ``bbbMm031mC`` -> ``3b2m3c1m1c``  (b=bait, m=mud, c=ball).
  4. Emits one JSONL line ``{"seed","path","command"}`` per seed, and appends ``<seed> <command>``
     to ``safari_seeds.md`` for the slurper to replay.

The slurper then produces emulator actuals for exactly these paths; compare against the JSONL to
confirm every one ends in capture and the observed path matches the generated one.

Usage:
    python utils/generate_success_paths.py < seeds.txt
    chart-successful-seeds | python utils/generate_success_paths.py --jsonl runs.jsonl

Options:
    --pokemon NAME   safari pokemon (default: metang)
    --jsonl PATH     JSONL output (default: safari_success_paths.jsonl)
    --seeds-md PATH  file to append '<seed> <command>' lines to (default: safari_seeds.md)
    --balls N        balls available at encounter start (default: 30)
    --max-turns N    machete_one turn limit for the suffix (default: library default)
    --no-append      compute + write JSONL but do NOT touch safari_seeds.md (dry run)
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root

from claytonlib.machete import machete_one  # noqa: E402
from claytonlib.safari import SafariContext, safari_pokemon_by_name  # noqa: E402

PREFIX_BAIT = 6
PREFIX_BALL = 5

# compass token -> action type letter for the slurper command string.
_TOKEN_TYPE = {
    "b": "b", "B": "b",                          # bait (crit or not)
    "m": "m", "M": "m",                          # mud  (crit or not)
    "0": "c", "1": "c", "2": "c", "3": "c", "C": "c",  # ball throw (any shake count / capture)
}


def path_to_command(path):
    """Run-length encode a compass path into a slurper command string, grouped by action type.

    ``bbbMm031mC`` -> ``3b2m3c1m1c``.  Bait (b/B), mud (m/M) and ball (0-3/C) each collapse to a
    single type letter (b/m/c); consecutive tokens of the same type become ``<count><letter>``.
    Raises ValueError on an unknown token (e.g. an 'F' flee -- a non-capturing path).
    """
    groups = []  # list of [type_letter, count]
    for tok in path:
        letter = _TOKEN_TYPE.get(tok)
        if letter is None:
            raise ValueError(f"path token {tok!r} has no slurper action (path {path!r})")
        if groups and groups[-1][0] == letter:
            groups[-1][1] += 1
        else:
            groups.append([letter, 1])
    return "".join(f"{count}{letter}" for letter, count in groups)


def build_full_path(seed, pokemon, balls, max_turns):
    """Return ``(full_path, note)`` for one seed.

    Plays the fixed 6-bait / 5-ball prefix, then machete_one for the capture suffix.  ``full_path``
    is the token string (ending in 'C' on success) or None when no capture path exists / the
    encounter ended early; ``note`` explains a None (e.g. 'fled during prefix', 'no capture path').
    """
    ctx = SafariContext.start_encounter(seed, pokemon)
    ctx.balls_remaining = balls
    prefix = []

    for _ in range(PREFIX_BAIT):
        if not ctx.is_watching():
            return None, "encounter ended during bait prefix"
        prefix.append(ctx.throw_bait().value)
    for _ in range(PREFIX_BALL):
        if not ctx.is_watching():
            return None, "encounter ended during ball prefix"
        step = ctx.throw_ball().value
        prefix.append(step)
        if step == "C":
            return "".join(prefix), None  # captured within the 5-ball prefix

    if not ctx.is_watching():
        return None, "pokemon fled after prefix (before ball phase)"

    kwargs = {} if max_turns is None else {"max_turns": max_turns}
    suffix = machete_one(ctx, **kwargs)
    if suffix is None:
        return None, "machete found no capture path from post-prefix state"
    return "".join(prefix) + suffix, None


def iter_seeds(stream):
    """Yield (raw_line, seed_int) for each non-blank, non-comment line; skip '#' and blanks."""
    for line in stream:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        yield s, int(s.split()[0], 16) & 0xFFFFFFFF


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate slurper command strings for successful seeds.")
    ap.add_argument("--pokemon", default="metang")
    ap.add_argument("--jsonl", default="safari_success_paths.jsonl")
    ap.add_argument("--seeds-md", default="safari_seeds.md")
    ap.add_argument("--balls", type=int, default=30)
    ap.add_argument("--max-turns", type=int, default=None)
    ap.add_argument("--no-append", action="store_true",
                    help="write JSONL only; do not append to the seeds-md file")
    args = ap.parse_args(argv)

    pokemon = safari_pokemon_by_name(args.pokemon)

    ok = fail = 0
    md = None if args.no_append else open(args.seeds_md, "a")
    try:
        with open(args.jsonl, "w") as jf:
            for raw, seed in iter_seeds(sys.stdin):
                seed_hex = f"0x{seed:08X}"
                full, note = build_full_path(seed, pokemon, args.balls, args.max_turns)
                if full is None:
                    fail += 1
                    rec = {"seed": seed_hex, "path": None, "command": None, "error": note}
                    jf.write(json.dumps(rec) + "\n")
                    print(f"{seed_hex}  FAIL  {note}", file=sys.stderr)
                    continue
                command = path_to_command(full)
                ok += 1
                jf.write(json.dumps({"seed": seed_hex, "path": full, "command": command}) + "\n")
                if md is not None:
                    md.write(f"{seed_hex} {command}\n")
                    md.flush()
                print(f"{seed_hex}  {full}  ->  {command}", file=sys.stderr)
    finally:
        if md is not None:
            md.close()

    print(f"\n{ok} captured, {fail} failed  (JSONL: {args.jsonl}"
          + ("" if args.no_append else f", appended to {args.seeds_md}") + ")", file=sys.stderr)
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
