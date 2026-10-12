#!/usr/bin/env python3
"""populate_hm_compatibility.py — merge HM compatibility into base_stats.json from the decomp.

**From the ROM, not PokeAPI**, unlike its sibling `populate_base_stats.py`. HM compatibility is
exactly the kind of fact PokeAPI reports for the wrong generation: the HM list itself differs
(Gen 4 has eight, HGSS made Flash a TM where DPPt had it as HM05), and move pools have shifted
every generation since. `files/poketool/personal/personal.json` in the decompilation carries a
per-species `hms` list and is the authority.

The indices are **1-based, HM01..HM08**. Confirmed against species whose compatibility is not in
question rather than assumed from the ordering:

    LAPRAS     [3, 4, 5, 6, 7]   Surf, Strength, Whirlpool, Rock Smash, Waterfall
    GYARADOS   [3, 4, 5, 6, 7]   the same
    TENTACRUEL [1, 3, 5, 7]      Cut, Surf, Whirlpool, Waterfall
    PIDGEOT    [2]               Fly
    GEODUDE    [4, 6, 8]         Strength, Rock Smash, Rock Climb
    MAGIKARP   []                none

Why this is wanted: `targets.access_warnings` can say "nobody knows Surf or Whirlpool", and the
useful next sentence is who *could* learn it. For the Lugia party the answer turned out to be
nobody at all -- Natu, Magneton and Smeargle have no HM compatibility, Ampharos is
Strength/Rock Smash/Rock Climb and Chatot is Fly -- which means the run needs a seventh Pokemon
in a slot one of the six is holding. A tool can only say that if it knows compatibility.

Scope is deliberately the species base_stats.json ALREADY has. The candidates a player might go
and catch (Lapras, Gyarados, Tentacruel) mostly are not in it and have no reason to be: naming
which Water type to raise is not this tool's job, and "none of your party can carry this" is the
sentence that matters.

Usage:
    python one-offs/populate_hm_compatibility.py                      # ~/arch/pokeheartgold
    python one-offs/populate_hm_compatibility.py --decomp /path/to/pokeheartgold
    python one-offs/populate_hm_compatibility.py --check              # verify, write nothing

clayton-957.29.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "base_stats.json"
PERSONAL = Path("files/poketool/personal/personal.json")

#: HM01..HM08 in HGSS, indexed to match the ROM's 1-based `hms` entries. Flash is NOT here: HGSS
#: moved it to TM70, where DPPt had it as HM05 -- which is the concrete reason this data has to
#: come from the HGSS decomp rather than from a generic Gen 4 list.
HM_MOVES: dict[int, str] = {
    1: "Cut", 2: "Fly", 3: "Surf", 4: "Strength",
    5: "Whirlpool", 6: "Rock Smash", 7: "Waterfall", 8: "Rock Climb",
}

#: Species whose `hms` list is unambiguous, used to prove the indexing rather than trust it. If
#: the decomp's encoding ever changes, this fails loudly instead of silently shifting every
#: species' move list by one.
INDEX_PROBES: dict[str, set[str]] = {
    "LAPRAS": {"Surf", "Strength", "Whirlpool", "Rock Smash", "Waterfall"},
    "GYARADOS": {"Surf", "Strength", "Whirlpool", "Rock Smash", "Waterfall"},
    "TENTACRUEL": {"Cut", "Surf", "Whirlpool", "Waterfall"},
    "PIDGEOT": {"Fly"},
    "GEODUDE": {"Strength", "Rock Smash", "Rock Climb"},
    "MAGIKARP": set(),
}


#: base_stats.json key -> the decomp's species name, where they differ. PokeAPI names alternate
#: FORMS ("giratina-altered") and the ROM's personal.json carries the bare species, so the two
#: disagree for exactly the species that have one. Listed rather than stripped by rule, so a new
#: form is a visible "no decomp entry for" line instead of a silent wrong match.
FORM_ALIASES: dict[str, str] = {"giratina-altered": "giratina"}


def _rom_species_key(name: str) -> str:
    """`personal.json`'s SPECIES_* name -> our base_stats.json key."""
    return name.strip().lower().replace("_", "-")


def load_rom_hms(decomp: Path) -> dict[str, list[str]]:
    """``{our species key: [HM move names]}`` for every species in the decomp."""
    path = decomp / PERSONAL
    if not path.exists():
        raise SystemExit(f"no personal.json at {path} -- pass --decomp")
    entries = json.loads(path.read_text())["baseStats"]
    out: dict[str, list[str]] = {}
    for entry in entries:
        rom_name = entry.get("species", "")
        if not rom_name or rom_name == "NONE":
            continue
        try:
            moves = [HM_MOVES[i] for i in entry.get("hms", [])]
        except KeyError as exc:
            raise SystemExit(
                f"{rom_name} has HM index {exc} outside 1..8 -- the encoding is not what "
                f"HM_MOVES assumes, and every species' list would be wrong. Stopping.")
        out[_rom_species_key(rom_name)] = sorted(moves)
    return out


def check_indexing(by_rom_name: dict[str, list[str]]) -> None:
    """Prove the 1-based reading against the probes before writing anything."""
    for rom_name, expected in INDEX_PROBES.items():
        got = set(by_rom_name.get(_rom_species_key(rom_name), []))
        if got != expected:
            raise SystemExit(
                f"index probe failed for {rom_name}: expected {sorted(expected)}, got "
                f"{sorted(got)}. The `hms` encoding is not 1-based HM01..HM08 -- do NOT write.")
    print(f"index probes pass ({len(INDEX_PROBES)} species)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decomp", default="~/arch/pokeheartgold",
                        help="path to the pokeheartgold checkout")
    parser.add_argument("--check", action="store_true",
                        help="report what would change and write nothing")
    args = parser.parse_args()

    rom = load_rom_hms(Path(args.decomp).expanduser())
    check_indexing(rom)

    data = json.loads(OUTPUT.read_text())
    changed, missing = [], []
    for key, entry in sorted(data.items()):
        rom_key = FORM_ALIASES.get(key, key)
        if rom_key not in rom:
            missing.append(key)
            continue
        hms = rom[rom_key]
        if entry.get("hms") != hms:
            changed.append((key, entry.get("hms"), hms))
        entry["hms"] = hms
        # `source` is deliberately NOT touched. In this file it means "the BASE STATS were
        # transcribed from the decompilation rather than fetched by populate_base_stats.py"
        # (CLAUDE.md), and setting it here would claim that of every species whose stats really
        # did come from PokeAPI. The `hms` field's provenance is this script's docstring.

    for key, before, after in changed:
        print(f"  {key:18s} {before!r} -> {after!r}")
    if missing:
        print(f"no decomp entry for: {', '.join(missing)}", file=sys.stderr)
    if args.check:
        print(f"--check: {len(changed)} entr{'y' if len(changed) == 1 else 'ies'} would change")
        return 0
    OUTPUT.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT} ({len(changed)} changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
