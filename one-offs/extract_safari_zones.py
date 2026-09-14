#!/usr/bin/env python3
"""Generate ``claytonlib/basedata/safari_zones.json`` (all 12 HGSS Safari areas, grass/Land).

The Safari-Zone encounter tables are block-configurable, so we extract PokeFinder's raw data
rather than transcribe by hand.  This reads Admiral-Fish's raw HGSS safari NARC + an English
species-name list and emits the per-area default 10-slot tables (by time of day), the
block-conditional replacement slots, and the block thresholds — exactly the fields
``claytonlib.safari_encounters`` resolves against.

Sources (pinned; re-run with network to refresh):
  * NARC:  https://raw.githubusercontent.com/Admiral-Fish/EncounterTableGenerator/master/Gen4/hgss/safari
           (parsed per EncounterTableGenerator/Gen4/hgss.py :: safari() + narc.py)
  * names: https://raw.githubusercontent.com/veekun/pokedex/master/pokedex/data/csv/pokemon_species_names.csv

Element layout (from hgss.py), per area, grass sub-encounter:
  8-byte header (5 encounter counts + 3 pad); 30 normal StaticSlots (morning/day/night x10),
  30 block StaticSlots, then 10 conditions of (type1, qty1, type2, qty2).  StaticSlot = u16 specie,
  u8 level, u8 pad.  Resolution + the (rand>>16)%10 slot formula live in claytonlib.safari_encounters.

Verified against notes/pokefinder_spread.md (Mountain/Morning/Peak=56): 132/132 rows.
"""
import csv
import io
import json
import struct
import urllib.request
from pathlib import Path

NARC_URL = "https://raw.githubusercontent.com/Admiral-Fish/EncounterTableGenerator/master/Gen4/hgss/safari"
NAMES_URL = "https://raw.githubusercontent.com/veekun/pokedex/master/pokedex/data/csv/pokemon_species_names.csv"

# NARC element order == area order; game location id = 149 + index (hgss.py LOCATION_START).
AREAS = ["Plains", "Meadow", "Savannah", "Peak", "Rocky Beach", "Wetland",
         "Forest", "Swamp", "Marshland", "Wasteland", "Mountain", "Desert"]
TOD = ["morning", "day", "night"]
OUT = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "safari_zones.json"


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def narc_elements(data: bytes) -> list[bytes]:
    """The file images of a NARC container (Admiral-Fish/EncounterTableGenerator narc.py)."""
    fat_b = 0x10
    (num,) = struct.unpack_from("<I", data, 0x18)
    fnt_b = struct.unpack_from("<I", data, 0x18)[0] * 8 + fat_b + 12
    fimg = struct.unpack_from("<I", data, fnt_b + 4)[0] + fnt_b
    out = []
    for i in range(num):
        s, e = struct.unpack_from("<II", data, fat_b + 0xC + 8 * i)
        out.append(data[fimg + s + 8: fimg + s + 8 + (e - s)])
    return out


def parse_grass(el: bytes):
    s = io.BytesIO(el)
    [s.read(1) for _ in range(5)]  # per-type encounter counts
    s.read(3)                      # pad

    def slots(n):
        r = []
        for _ in range(n):
            specie = struct.unpack("<H", s.read(2))[0]
            level = s.read(1)[0]
            s.read(1)              # StaticSlot pad byte
            r.append((specie, level))
        return r

    normal = slots(30)             # morning[10] day[10] night[10]
    block = slots(30)
    conds = [tuple(s.read(1)[0] for _ in range(4)) for _ in range(10)]
    return normal, block, conds


def main() -> None:
    names = {}
    reader = csv.DictReader(io.StringIO(_fetch(NAMES_URL).decode("utf-8")))
    for row in reader:
        if row["local_language_id"] == "9":            # English
            names[int(row["pokemon_species_id"])] = row["name"].lower()

    def name(sp: int) -> str:
        return names.get(sp, f"species-{sp}")

    els = narc_elements(_fetch(NARC_URL))
    assert len(els) == len(AREAS), f"expected {len(AREAS)} areas, got {len(els)}"

    data = {"_meta": {
        "block_types": {"none": 0, "plains": 1, "forest": 2, "peak": 3, "water": 4},
        "tod_index": {"morning": 0, "day": 1, "night": 2},
        "slot_formula": "slot(advance N) = (advance_rng^(N+1)(seedA) >> 16) % 10",
        "source": "Admiral-Fish/EncounterTableGenerator hgss/safari NARC; species=veekun EN",
        "note": "grass (Land) only; block-conditionals fill top slots in order "
                "(PokeFinder Encounters4::getHGSSSafari)",
    }}
    for idx, area in enumerate(AREAS):
        normal, block, conds = parse_grass(els[idx])
        grass = {"normal": {}, "block": {}, "conditions": [list(c) for c in conds]}
        for t, tod in enumerate(TOD):
            grass["normal"][tod] = [[name(sp), lv] for sp, lv in normal[10 * t:10 * t + 10]]
            grass["block"][tod] = [[name(sp), lv] for sp, lv in block[10 * t:10 * t + 10]]
        data[area] = {"location": 149 + idx, "grass": grass}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
    print(f"wrote {OUT}  ({len(AREAS)} areas)")


if __name__ == "__main__":
    main()
