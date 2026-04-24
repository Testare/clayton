#!/usr/bin/env python3
"""
populate_moves.py — Interactive tool for populating move profiles in moves.json.

Iterates through moves that need profile data and prompts the user to classify
each one. Optionally opens the Bulbapedia page for each move.

Usage:
    python populate_moves.py                    # unpopulated metronome-usable moves
    python populate_moves.py --unsupported      # re-visit moves marked unsupported
    python populate_moves.py --start 50         # start from move number 50
    python populate_moves.py --no-browser       # don't open Bulbapedia pages
    python populate_moves.py --start 50 --end 100  # only moves 50-100
    python populate_moves.py --stats            # print summary stats and exit
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

MOVES_PATH = Path(__file__).parent.parent / "claytonlib" / "basedata" / "moves.json"

# Profile names — these are the strings stored in the JSON.
# The actual MoveProfile dataclass mapping lives in claytonlib.
PROFILES = {
    "standard":     "Standard damaging move (accuracy + crit + damage)",
    "never_miss":   "Damaging, bypasses accuracy check (Swift, Aerial Ace, etc.)",
    "status":       "Status move with accuracy check, no crit/damage",
    "status_sure":  "Status move, bypasses accuracy check (e.g. Haze, Light Screen)",
    "no_effect":    "No RNG beyond metronome roll (Splash, etc.)",
    "high_crit":    "Damaging with increased crit rate",
    "set_damage":   "Set/fixed damage move (Night Shade, Seismic Toss, etc.)",
    "complex":      "Needs move-specific logic (multi-hit, charging, etc.)",
    "unsupported":  "Not yet classified or too complex to handle",
}

PROFILE_SHORTCUTS = {str(i+1): name for i, name in enumerate(PROFILES)}


def load_moves() -> list[dict]:
    with open(MOVES_PATH) as f:
        return json.load(f)


def save_moves(moves: list[dict]) -> None:
    with open(MOVES_PATH, "w") as f:
        json.dump(moves, f, indent=2)
        f.write("\n")
    print(f"  Saved {MOVES_PATH.name}")


def bulbapedia_url(name: str) -> str:
    slug = name.replace(" ", "_")
    return f"https://bulbapedia.bulbagarden.net/wiki/{slug}_(move)"


def open_browser(url: str) -> None:
    try:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print(f"  (Could not open browser. URL: {url})")


def print_profile_menu():
    print("  Profiles:")
    for key, name in PROFILE_SHORTCUTS.items():
        desc = PROFILES[name]
        print(f"    {key}. {name:15s} — {desc}")


def prompt_profile() -> str | None:
    """Prompt for a profile selection. Returns profile name or None to skip."""
    print_profile_menu()
    print("    s. skip          — skip this move for now")
    print("    q. quit          — save and exit")
    while True:
        raw = input("  Profile: ").strip().lower()
        if raw == "s":
            return "SKIP"
        if raw == "q":
            return None
        if raw in PROFILE_SHORTCUTS:
            return PROFILE_SHORTCUTS[raw]
        if raw in PROFILES:
            return raw
        print(f"    Unknown choice {raw!r}. Enter a number, profile name, 's', or 'q'.")


def prompt_accuracy() -> int | None:
    """Prompt for accuracy. Returns int (0-100 or -1 for bypass), or None to use default."""
    print("  Accuracy: enter 0-100, or -1 for 'bypasses accuracy check', or blank for N/A")
    while True:
        raw = input("  Accuracy: ").strip()
        if raw == "":
            return None
        try:
            val = int(raw)
            if val == -1 or 0 <= val <= 100:
                return val
            print("    Enter -1, 0-100, or blank.")
        except ValueError:
            print("    Enter a number.")


def prompt_secondary_rolls() -> int:
    """Prompt for number of secondary effect rolls."""
    while True:
        raw = input("  Secondary effect rolls (0 if none): ").strip()
        if raw == "":
            return 0
        try:
            val = int(raw)
            if val >= 0:
                return val
            print("    Enter 0 or more.")
        except ValueError:
            print("    Enter a number.")


def prompt_gravity_blocked() -> bool:
    """Prompt for whether the move is blocked by Gravity."""
    while True:
        raw = input("  Blocked by Gravity? (y/n, default n): ").strip().lower()
        if raw in ("", "n", "no"):
            return False
        if raw in ("y", "yes"):
            return True
        print("    Enter y or n.")


def prompt_notes() -> str:
    """Prompt for optional notes about the move."""
    return input("  Notes (optional, blank to skip): ").strip()


def print_stats(moves: list[dict]) -> None:
    metronome_usable = [m for m in moves if m.get("metronome_usable")]
    populated = [m for m in metronome_usable if "profile" in m]
    by_profile: dict[str, int] = {}
    for m in populated:
        p = m["profile"]
        by_profile[p] = by_profile.get(p, 0) + 1

    print(f"Total moves:          {len(moves)}")
    print(f"Metronome-usable:     {len(metronome_usable)}")
    print(f"Populated:            {len(populated)}")
    print(f"Remaining:            {len(metronome_usable) - len(populated)}")
    print()
    if by_profile:
        print("By profile:")
        for name, count in sorted(by_profile.items(), key=lambda x: -x[1]):
            print(f"  {name:20s} {count}")


def needs_population(move: dict, unsupported_mode: bool) -> bool:
    if not move.get("metronome_usable"):
        return False
    if unsupported_mode:
        return move.get("profile") == "unsupported"
    return "profile" not in move


def populate(args):
    moves = load_moves()

    if args.stats:
        print_stats(moves)
        return

    to_process = [
        m for m in moves
        if needs_population(m, args.unsupported)
        and m["number"] >= args.start
        and (args.end is None or m["number"] <= args.end)
    ]

    if not to_process:
        print("No moves to populate in the specified range.")
        print_stats(moves)
        return

    print(f"Moves to populate: {len(to_process)}")
    print()

    modified = False
    for i, move in enumerate(to_process):
        num = move["number"]
        name = move["name"]
        remaining = len(to_process) - i
        print(f"--- [{remaining} remaining] #{num}: {name} ---")

        if not args.no_browser:
            open_browser(bulbapedia_url(name))

        profile = prompt_profile()
        if profile is None:  # quit
            break
        if profile == "SKIP":
            print("  Skipped.")
            print()
            continue

        move["profile"] = profile

        # Accuracy — prompt for damaging/status profiles, skip for no_effect
        if profile not in ("no_effect", "unsupported"):
            acc = prompt_accuracy()
            if acc is not None:
                move["accuracy"] = acc

        # Secondary rolls — only for damaging profiles
        if profile in ("standard", "never_miss", "high_crit"):
            sr = prompt_secondary_rolls()
            if sr > 0:
                move["secondary_rolls"] = sr

        # Gravity — quick check
        if profile != "unsupported":
            if prompt_gravity_blocked():
                move["gravity_blocked"] = True

        # Notes
        note = prompt_notes()
        if note:
            move["notes"] = note

        modified = True
        print(f"  → {name}: profile={profile}")
        print()

        # Save periodically (every 10 moves)
        if (i + 1) % 10 == 0:
            save_moves(moves)

    if modified:
        save_moves(moves)
        print()
        print_stats(moves)
    else:
        print("No changes made.")


def main():
    parser = argparse.ArgumentParser(
        description="Populate move profiles in moves.json for metronome compass."
    )
    parser.add_argument(
        "--start", type=int, default=1,
        help="Start from this move number (default: 1)",
    )
    parser.add_argument(
        "--end", type=int, default=None,
        help="Stop at this move number (inclusive)",
    )
    parser.add_argument(
        "--unsupported", action="store_true",
        help="Re-visit moves currently marked as 'unsupported'",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't open Bulbapedia pages in the browser",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print summary stats and exit",
    )
    args = parser.parse_args()
    populate(args)


if __name__ == "__main__":
    main()
