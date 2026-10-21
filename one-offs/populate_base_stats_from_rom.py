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

Covers **dex 1-493, plus the nine alternate forms** that live in the same table past 493
(DEOXYS_ATK/DEF/SPD, WORMADAM_SANDY/TRASH, GIRATINA_ORIGIN, SHAYMIN_SKY, the five ROTOM_*).

The forms used to be skipped, with the honest reason that "none is a reachable encounter for this
tool, and inventing key names for them would be guessing at a convention nothing consumes".
**Platinum's Giratina ends that**: the Distortion World fight is the Origin forme, which is
120/100/120/100 against Altered's 100/120/100/120 and **Levitate against Pressure** -- and a
species-keyed table could only hold one of them, so `has_pressure` would be confidently wrong for
one of the two fights and halve every PP budget the solver plans against (clayton-6xu.3.4). The
convention is now consumed: `battle_compass.targets.Encounter.forme` names the row an encounter
takes its stats from.

A form row carries `forme_of` (its base species' key) and **shares that species' dex number**,
because that is what a dex number is. So the invariant is no longer "one row per dex number" --
it is "one row per dex number among rows WITHOUT `forme_of`".

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

#: our key -> (ROM species name past dex 493, the base species' key).
#:
#: Named from the ROM's own constants rather than from veekun ("deoxys-atk", not veekun's
#: "deoxys-attack"), because nothing joins these to veekun and the ROM is the only source they
#: have. `giratina-origin` pairs with the `giratina-altered` alias above, so the two formes read
#: as siblings rather than as a species and an exception.
FORMES: dict[str, tuple[str, str]] = {
    "deoxys-atk": ("DEOXYS_ATK", "deoxys"),
    "deoxys-def": ("DEOXYS_DEF", "deoxys"),
    "deoxys-spd": ("DEOXYS_SPD", "deoxys"),
    "wormadam-sandy": ("WORMADAM_SANDY", "wormadam"),
    "wormadam-trash": ("WORMADAM_TRASH", "wormadam"),
    # The one that forced this. Lv47 in the Distortion World (`StartGiratinaOriginBattle`).
    "giratina-origin": ("GIRATINA_ORIGIN", "giratina-altered"),
    "shaymin-sky": ("SHAYMIN_SKY", "shaymin"),
    "rotom-heat": ("ROTOM_HEAT", "rotom"),
    "rotom-wash": ("ROTOM_WASH", "rotom"),
    "rotom-frost": ("ROTOM_FROST", "rotom"),
    "rotom-fan": ("ROTOM_FAN", "rotom"),
    "rotom-mow": ("ROTOM_MOW", "rotom"),
}

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


def forme_entries(decomp: Path) -> dict[str, dict]:
    """``{ROM species name: row}`` for the form rows past dex 493, unfiltered by dex.

    Read in a second pass rather than by widening `rom_entries`' range, because the two have
    different invariants: a species row's index IS its dex number and the count must be exactly
    493, while a form row's index is a personal-table slot and its dex number has to be borrowed
    from the species it is a form of.
    """
    rows = json.loads((decomp / PERSONAL).read_text())["baseStats"]
    wanted = {rom_name for rom_name, _ in FORMES.values()}
    out = {row["species"]: dict(row) for row in rows if row.get("species") in wanted}
    missing = sorted(wanted - set(out))
    if missing:
        raise SystemExit(f"form rows not in the table: {', '.join(missing)}")
    return out


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

    # The form rows, each borrowing its base species' dex number. Added after the species loop so
    # `data[base]` is already there to read the number off -- and so a typo in FORMES names a key
    # that does not exist rather than silently creating one.
    formes = forme_entries(Path(args.decomp).expanduser())
    for key, (rom_name, base) in sorted(FORMES.items()):
        if base not in data:
            raise SystemExit(f"{key}: no base species {base!r} to take a dex number from")
        entry = build(dict(formes[rom_name], dex_no=data[base]["dex_no"]))
        entry["name"] = key
        entry["forme_of"] = base
        was = existing.get(key)
        if was is None:
            added.append(key)
        else:
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
