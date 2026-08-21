#!/usr/bin/env python3
"""
verify_paths.py — Check testpaths.json against seedslurper actuals.

Usage: python3 utils/verify_paths.py <testpaths.json> <actuals.jsonl> [--interactive]

For each seed in the map, finds its entry in the actuals JSONL and checks
that every move name in the "moves" list appears as a substring in at least
one battle message.  Sets verification=1 on success.  Writes the updated
map back to <testpaths.json> and prints a summary of unverified seeds.

--interactive: on failure, show the predicted path, expected moves, and
               deduped battle messages for that seed, then pause for a keypress.
"""

import json
import re
import sys
import termios
import tty


def _move_pattern(name):
    """Compile a regex for a move name that tolerates spacing/punctuation differences.

    Each space in the name becomes [^a-zA-Z0-9]* so that e.g. 'Thunder Punch'
    matches both 'ThunderPunch' and 'Thunder-Punch', and 'Will O Wisp' matches
    'Will-O-Wisp'.
    """
    parts = re.split(r"\s+", name.strip())
    return re.compile("[^a-zA-Z0-9]*".join(re.escape(p) for p in parts), re.IGNORECASE)


def load_actuals(path):
    """Read a seedslurper JSONL into {seed_key: [msg, ...]}."""
    actuals = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  WARNING: line {lineno} in actuals is not valid JSON ({e}); skipping",
                      file=sys.stderr)
                continue
            seed_int = int(entry["seed"], 16)
            key = f"0x{seed_int:08X}"
            actuals[key] = [r["msg"] for r in entry["results"] if "msg" in r]
    return actuals


def _getch():
    """Read a single keypress without requiring Enter."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        return sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _dedup_consecutive(msgs):
    """Remove consecutive duplicate messages, tracking run lengths."""
    out = []
    for msg in msgs:
        if out and out[-1][0] == msg:
            out[-1] = (msg, out[-1][1] + 1)
        else:
            out.append((msg, 1))
    return out


def show_failure(seed_key, entry, messages, missing):
    """Print the audit view for a failed seed.

    Returns True to continue to the next seed, False to quit immediately.
    May update entry['verification'] if the user presses v.
    """
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"  SEED:    {seed_key}")
    print(f"  PATH:    {entry['path']}")
    print(f"  MOVES:   {entry['moves']}")
    print(f"  MISSING: {missing}")
    print(f"\n  Battle messages ({len(messages)} total):")
    for msg, count in _dedup_consecutive(messages):
        lines = msg.split("\n")
        first = lines[0]
        rest  = lines[1:]
        suffix = f"  ×{count}" if count > 1 else ""
        print(f"    > {first}{suffix}")
        for l in rest:
            print(f"      {l}")
    print(f"{sep}")

    while True:
        print("  [n=next  v=set-verification  q=quit] ", end="", flush=True)
        key = _getch()
        print(key)

        if key == "q":
            return False
        elif key == "n":
            return True
        elif key == "v":
            print("  verification value [0-9 / - for incorrect (-1)]: ", end="", flush=True)
            vkey = _getch()
            print(vkey)
            if vkey == "-":
                entry["verification"] = -1
                print(f"  → verification set to -1")
                return True
            elif vkey.isdigit():
                entry["verification"] = int(vkey)
                print(f"  → verification set to {vkey}")
                return True
            else:
                print(f"  invalid key {vkey!r}, try again")


def main():
    args = sys.argv[1:]
    interactive = "--interactive" in args
    args = [a for a in args if a != "--interactive"]

    if len(args) < 2:
        print(f"Usage: {sys.argv[0]} <testpaths.json> <actuals.jsonl> [--interactive]",
              file=sys.stderr)
        sys.exit(1)

    testpaths_path = args[0]
    actuals_path   = args[1]

    with open(testpaths_path) as f:
        seed_map = json.load(f)

    print(f"Loading actuals from {actuals_path} ...")
    actuals = load_actuals(actuals_path)
    print(f"  {len(actuals)} seeds in actuals, {len(seed_map)} seeds in map\n")

    unverified = []

    for seed_key, entry in seed_map.items():
        moves = entry["moves"]

        if seed_key not in actuals:
            print(f"{seed_key}: MISSING  (not yet in actuals)")
            unverified.append(seed_key)
            continue

        messages = actuals[seed_key]
        all_text = "\n".join(messages)
        missing  = [m for m in moves if not _move_pattern(m).search(all_text)]

        if missing:
            print(f"{seed_key}: FAIL     missing={missing}")
            unverified.append(seed_key)
            if interactive:
                if not show_failure(seed_key, entry, messages, missing):
                    break
        else:
            v = entry["verification"]
            if v == 0:
                entry["verification"] = 1
            preview = moves[:2] + (["..."] if len(moves) > 2 else [])
            tag = "OK" if v == 0 else f"OK (kept verification={v})"
            print(f"{seed_key}: {tag}  moves={preview}")

    # Summary
    verified = len(seed_map) - len(unverified)
    print(f"\nVerified: {verified}/{len(seed_map)}")

    if unverified:
        print(f"\nUnverified seeds ({len(unverified)}):")
        for s in unverified:
            print(f"  {s}")

    with open(testpaths_path, "w") as f:
        json.dump(seed_map, f, indent=2)
    print(f"\nUpdated: {testpaths_path}")


if __name__ == "__main__":
    main()
