"""validate_safari.py -- check emulator ground truth (safari_seeds/*.jsonl) against claytonlib.

For each recorded battle it reconstructs the observed path from the logged MESSAGES (so a stale
cached ``path`` field can't mislead), then replays that path through claytonlib's SafariContext
seeded with the same seed, comparing token by token.  A match means claytonlib's safari RNG model
reproduces the emulator; a mismatch pinpoints exactly where the model diverges.

CLI:  python utils/validate_safari.py [safari_seeds/safari_metang.jsonl ...]
"""
import glob
import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else "utils"
sys.path.insert(0, _HERE)                      # for safari_reader
sys.path.insert(0, os.path.dirname(_HERE))     # repo root, for claytonlib
import safari_reader as sr  # noqa: E402

from claytonlib.safari import SafariContext, SafariStep, safari_pokemon_by_name  # noqa: E402

DEFAULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "safari_seeds")
DEFAULT_BALLS = 30

_THROW = {"b": "throw_bait", "B": "throw_bait", "m": "throw_mud", "M": "throw_mud",
          "0": "throw_ball", "1": "throw_ball", "2": "throw_ball", "3": "throw_ball",
          "C": "throw_ball"}


def pokemon_name_from_filename(path):
    """'safari_metang3.jsonl' / 'safari_metang_p.jsonl' -> 'metang'.

    Drops the 'safari_' prefix and extension, a trailing run index (…3), and a trailing
    underscore-qualifier (…_p) -- species names use hyphens, never '_', so stripping a trailing
    ``_<alnum>`` only removes run qualifiers, never part of a name (e.g. nidoran-f is untouched).
    """
    base = os.path.basename(path)
    base = re.sub(r"\.jsonl$", "", base)
    base = re.sub(r"^safari_", "", base)
    base = re.sub(r"\d+$", "", base)          # trailing run index
    base = re.sub(r"_[a-z0-9]+$", "", base)   # trailing _qualifier (e.g. _p)
    return base or "metang"


def ground_truth_path(record, msgmap=None):
    """The observed compass path, reconstructed from the record's logged messages (current parser)."""
    return sr.messages_to_path(record["results"], msgmap or sr.SAFARI_MESSAGES)[0]


def replay_and_diff(seed, pokemon, path, ball_count=DEFAULT_BALLS):
    """Replay ``path`` through claytonlib for ``seed``; return (generated, diverge_index).

    ``generated`` is what claytonlib produced (a '?' marks where it couldn't continue or the
    flee state disagreed); ``diverge_index`` is the first token where it disagrees with ``path``,
    or None if claytonlib reproduces the whole path.
    """
    ctx = SafariContext.start_encounter(seed, pokemon)
    ctx.balls_remaining = ball_count
    generated = []
    for i, tok in enumerate(path):
        if tok == "F":
            fled = ctx.has_fled()
            generated.append("F" if fled else "?")
            return "".join(generated), (None if fled else i)
        if not ctx.is_watching():           # claytonlib already ended (fled/captured) -- diverges
            generated.append("?")
            return "".join(generated), i
        step = getattr(ctx, _THROW[tok])()
        generated.append(step.value)
        if step.value != tok:
            return "".join(generated), i
    return "".join(generated), None


def validate_record(record, pokemon, ball_count=DEFAULT_BALLS, msgmap=None):
    seed = int(record["seed"], 16)
    gt = ground_truth_path(record, msgmap)
    generated, diverge = replay_and_diff(seed, pokemon, gt, ball_count)
    return {"seed": record["seed"], "end": record.get("end_reason"),
            "gt_path": gt, "generated": generated, "diverge_index": diverge,
            "matched": diverge is None}


def validate_file(path, ball_count=DEFAULT_BALLS):
    poke = safari_pokemon_by_name(pokemon_name_from_filename(path))
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(validate_record(json.loads(line), poke, ball_count))
    return out


def _print_report(path, results):
    print(f"\n=== {os.path.basename(path)} ===")
    for r in results:
        if r["matched"]:
            print(f"  {r['seed']}  MATCH   {r['gt_path']}")
        else:
            i = r["diverge_index"]
            obs = r["gt_path"][i] if i < len(r["gt_path"]) else "?"
            got = r["generated"][i] if i < len(r["generated"]) else "?"
            print(f"  {r['seed']}  DIVERGE at token {i}: observed {obs!r}, claytonlib {got!r}")
            print(f"      observed : {r['gt_path']}")
            print(f"      claytonlib: {r['generated']}")
    return all(r["matched"] for r in results)


def main(argv):
    paths = argv[1:] or sorted(glob.glob(os.path.join(DEFAULT_DIR, "*.jsonl")))
    if not paths:
        print("no ground-truth files (safari_seeds/*.jsonl)")
        return 1
    ok = True
    total = matched = 0
    for p in paths:
        results = validate_file(p)
        ok = _print_report(p, results) and ok
        total += len(results)
        matched += sum(r["matched"] for r in results)
    print(f"\n{matched}/{total} records reproduced by claytonlib.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
