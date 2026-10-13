#!/usr/bin/env python3
"""populate_base_stats_from_rom.py — every Gen 4 species' base stats, from the decompilation.

**This replaces `populate_base_stats.py` as the source of truth**, and the reason is a number:
PokeAPI reports Electrode's Speed as 150, which is its Gen 8 value. In Gen 4 it is **140**. The
old script handled that class of problem with a hand-maintained `KNOWN_POST_GEN4_CHANGES` list,
which works for 26 species and cannot work for 493 -- it can only catch what somebody thought to
look up, and a silently-modern stat does not announce itself. It mis-derives a target's whole
spread from the IVs the player entered, and the run then contradicts on the first hit.

`files/poketool/personal/personal.json` in the decompilation is the game's own table. It is
Gen-4-exact by construction, which is a different kind of claim from "we checked the ones we
thought might have changed".

Covers **dex 1-493**. The alternate forms live in the same table past 493 (DEOXYS_ATK,
WORMADAM_SANDY, GIRATINA_ORIGIN, SHAYMIN_SKY, the five ROTOM_*) and are deliberately skipped:
none is a reachable encounter for this tool, and inventing key names for them would be guessing
at a convention nothing consumes.

What this does NOT supply:

* **weight_hg**, which the Heavy Ball would need. The weight table is a binary NARC
  (`NARC_application_zukanlist_zkn_data_zukan_data`, file 1, read by `GetMonWeight` in
  src/battle/battle_command.c:7374) rather than decompiled source, so it is not here. Existing
  values are PRESERVED rather than dropped, and the Heavy Ball is deferred anyway -- its ROM
  implementation tests the catch rate where it meant to test the weight, so it penalises most
  species.
* **hms**, which `populate_hm_compatibility.py` writes from the same file. Run that afterwards;
  this script preserves whatever is already there.

Usage:
    python one-offs/populate_base_stats_from_rom.py                     # dex 1-493
    python one-offs/populate_base_stats_from_rom.py --decomp /path/to/pokeheartgold
    python one-offs/populate_base_stats_from_rom.py --check             # verify, write nothing

`--check` is the one to run after any change to the file: it reports every species whose stored
values disagree with the ROM, which is how a PokeAPI-sourced error would surface.

clayton-rp2.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "base_stats.json"
PERSONAL = Path("files/poketool/personal/personal.json")

#: Highest Gen 4 dex number. Entries past this are alternate forms and the two egg sentinels.
LAST_GEN4_DEX = 493

#: The ROM's stat field names -> ours. `speed`/`spatk`/`spdef` against `spe`/`spa`/`spd` is the
#: only renaming; the project's order is hp/atk/def/spa/spd/spe (`battle/stats.STAT_KEYS`).
STAT_FIELDS = {"hp": "hp", "atk": "atk", "def": "def",
               "spatk": "spa", "spdef": "spd", "speed": "spe"}

#: base_stats.json key -> the ROM species name, where a naive transform does not reach it.
#: Only the form-bearing base species need one, and only Giratina is currently in the file --
#: PokeAPI names it by its default form and the ROM names it bare. Listed rather than stripped
#: by rule, so adding Deoxys or Shaymin later is a visible decision.
KEY_TO_ROM: dict[str, str] = {"giratina-altered": "GIRATINA"}

#: `genderRatio` as the decomp's JSON writes it: 0.0 always male, 1.0 always female, 2.0
#: genderless, anything else the fraction that is female. Decoded here because the Love Ball
#: turns on it -- `catchRate *= 8` needs `attacker.gender != target.gender`, which a genderless
#: species can never satisfy even against itself (notes/lugia_love_ball.md sec 1).
GENDERLESS = 2.0
ALWAYS_MALE = 0.0
ALWAYS_FEMALE = 1.0


def _name(constant: str, prefix: str) -> str:
    """``ABILITY_FLAME_BODY`` -> ``"Flame Body"``, ``TYPE_PSYCHIC`` -> ``"Psychic"``.

    `ABILITY_COMPOUNDEYES` and `ABILITY_LIGHTNINGROD` come out as one word, and that is correct
    rather than a gap: "Compoundeyes" and "Lightningrod" are what the Gen 4 ability screen says.
    They became "Compound Eyes" and "Lightning Rod" in Gen 6, so a modern spelling here would be
    the same anachronism this script exists to remove.
    """
    return constant.removeprefix(prefix).replace("_", " ").title()


def _dedupe(values: list[str]) -> list[str]:
    """The ROM stores two type and two ability slots, repeating or NONE-filling the spare.

    A single-typed species is ``[TYPE_ELECTRIC, TYPE_ELECTRIC]`` and a single-abilitied one is
    ``[ABILITY_X, ABILITY_NONE]``, where the project stores one entry. Order-preserving, because
    slot order is meaningful for abilities -- `has_pressure` and the facade read slot 0.
    """
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def gender_note(ratio: float) -> dict:
    """The gender fields, decoded from `genderRatio`."""
    if ratio == GENDERLESS:
        return {"genderless": True}
    return {"genderless": False,
            "female_ratio": (1.0 if ratio == ALWAYS_FEMALE
                             else 0.0 if ratio == ALWAYS_MALE else ratio)}


def rom_entries(decomp: Path) -> dict[str, dict]:
    """``{ROM species name: entry}`` for dex 1..493, with the dex number attached."""
    path = decomp / PERSONAL
    if not path.exists():
        raise SystemExit(f"no personal.json at {path} -- pass --decomp")
    rows = json.loads(path.read_text())["baseStats"]
    out: dict[str, dict] = {}
    for dex, row in enumerate(rows):
        if dex < 1 or dex > LAST_GEN4_DEX:
            continue
        if row.get("species", "NONE") == "NONE":
            continue
        out[row["species"]] = dict(row, dex_no=dex)
    if len(out) != LAST_GEN4_DEX:
        raise SystemExit(
            f"expected {LAST_GEN4_DEX} species in dex 1..{LAST_GEN4_DEX}, read {len(out)} -- "
            f"the table's layout is not what this script assumes. Stopping.")
    return out


def build(row: dict) -> dict:
    """One base_stats.json entry from one ROM row."""
    entry = {
        "name": row["species"].lower().replace("_", "-"),
        "dex_no": row["dex_no"],
        "base_stats": {ours: row[theirs] for theirs, ours in STAT_FIELDS.items()},
        "types": _dedupe([_name(t, "TYPE_") for t in row.get("types", [])]),
        "abilities": _dedupe([_name(a, "ABILITY_") for a in row.get("abilities", [])
                              if a != "ABILITY_NONE"]),
        "catch_rate": row["catchRate"],
        "source": "rom",
    }
    entry.update(gender_note(row.get("genderRatio", 0.5)))
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decomp", default="~/arch/pokeheartgold")
    parser.add_argument("--check", action="store_true",
                        help="report disagreements with the ROM and write nothing")
    args = parser.parse_args()

    rom = rom_entries(Path(args.decomp).expanduser())
    existing = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}

    # Our key for each ROM name, honouring KEY_TO_ROM so a key already in the file keeps it.
    # An alias REPLACES the naive key rather than joining it -- adding it produced both
    # `giratina` and `giratina-altered` for one ROM row, i.e. 494 entries for 493 species.
    rom_for_key = {name.lower().replace("_", "-"): name for name in rom}
    for our_key, rom_name in KEY_TO_ROM.items():
        rom_for_key.pop(rom_name.lower().replace("_", "-"), None)
        rom_for_key[our_key] = rom_name
    if len(rom_for_key) != LAST_GEN4_DEX:
        raise SystemExit(f"{len(rom_for_key)} keys for {LAST_GEN4_DEX} species -- an alias in "
                         f"KEY_TO_ROM has added a key instead of replacing one.")

    data: dict[str, dict] = {}
    changed, added = [], []
    for key, rom_name in sorted(rom_for_key.items()):
        entry = build(rom[rom_name])
        entry["name"] = key                      # the file keys on our name, not the ROM's
        was = existing.get(key)
        if was is None:
            added.append(key)
        else:
            # Fields this script does not own are carried over rather than dropped.
            for field in ("weight_hg", "hms"):
                if field in was:
                    entry[field] = was[field]
            differing = {f for f in ("base_stats", "types", "abilities", "catch_rate")
                         if was.get(f) != entry[f]}
            if differing:
                changed.append((key, sorted(differing), was, entry))
        data[key] = entry

    orphans = sorted(set(existing) - set(data))
    for key in orphans:                          # never silently lose an entry
        data[key] = existing[key]

    for key, fields, was, now in changed:
        print(f"  {key}: {', '.join(fields)}")
        for field in fields:
            print(f"      was {was.get(field)!r}")
            print(f"      now {now[field]!r}")
    if orphans:
        print(f"kept {len(orphans)} entry/entries with no ROM match: {', '.join(orphans)}",
              file=sys.stderr)
    print(f"{len(added)} added, {len(changed)} corrected, {len(data)} total")
    if args.check:
        return 1 if changed else 0
    OUTPUT.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
