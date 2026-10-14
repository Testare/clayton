#!/usr/bin/env python3
"""Generate ``claytonlib/basedata/safari_zones.json`` (all 12 HGSS Safari areas, all 5 methods).

The Safari-Zone encounter tables are block-configurable, so we extract PokeFinder's raw data
rather than transcribe by hand.  This reads Admiral-Fish's raw HGSS safari NARC + an English
species-name list and emits, per area and per method, the default 10-slot tables (by time of
day), the block-conditional replacement slots, and the block thresholds — exactly the fields
``claytonlib.safari_encounters`` resolves against.

Sources (pinned; re-run with network to refresh):
  * NARC:  https://raw.githubusercontent.com/Admiral-Fish/EncounterTableGenerator/master/Gen4/hgss/safari
           (parsed per EncounterTableGenerator/Gen4/hgss.py :: safari() + narc.py)
  * names: https://raw.githubusercontent.com/veekun/pokedex/master/pokedex/data/csv/pokemon_species.csv
           -- the ``identifier`` column (``nidoran-f``), NOT ``pokemon_species_names.csv``'s
           display names (``Nidoran♀``).  This file is joined against safari_pokemon.json and
           base_stats.json by species name, and those key on the slug; naming by display name
           instead made four species unhuntable in the app, since nothing matched and nothing
           errored (clayton-69n).  ``main`` asserts the join resolves before writing, and
           every name is put through ``claytonlib.species_names.canonical_species_name`` so a
           future source's spelling can't reintroduce the mismatch either.

Element layout (912 bytes; from hgss.py ``safari()`` and PokeFinder's
``WildEncounterHGSSSafari`` struct in ``Core/Gen4/Encounters4.cpp``, which agree exactly):

  8-byte header: five per-method block-conditional counts (grass 10, surf 3, old/good/super
  rod 2 each) + 3 pad.  Then, for each of the five methods in that order:
    * 30 normal StaticSlots — 10 per time of day (morning/day/night), for EVERY method, not
      ``count`` per time of day.  Safari always draws a flat 10-slot table (see below).
    * ``count * 3`` block StaticSlots — ``count`` per time of day.
    * ``count`` conditions of (type1, qty1, type2, qty2).
  StaticSlot = u16 specie, u8 level, u8 pad.  8 + 280 + 168 + 152*3 = 912.

Only five areas have water (``has_water``), so only they get surf/rod tables emitted.  That
flag is not in the NARC — PokeFinder's hgss.py hardcodes the area indices — but it is
recoverable from the bytes: the seven waterless areas share one byte-identical filler blob
for all four water methods (a Tentacool/Wooper table the game never reads), while each of
the five water areas is unique.  We derive it that way and assert it against the hardcoded
set, so a future data refresh can't silently disagree with either.

Resolution + the slot formula (``(rand>>16)%10`` for every method; rods draw a nibble check
first) live in ``claytonlib.safari_encounters``.

Verified against notes/pokefinder_spread.md (Mountain/Morning/Peak=56): 132/132 rows.
"""
import csv
import io
import json
import struct
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claytonlib._resources import basedata_json          # noqa: E402
from claytonlib.species_names import canonical_species_name  # noqa: E402

NARC_URL = "https://raw.githubusercontent.com/Admiral-Fish/EncounterTableGenerator/master/Gen4/hgss/safari"
NAMES_URL = "https://raw.githubusercontent.com/veekun/pokedex/master/pokedex/data/csv/pokemon_species.csv"

# NARC element order == area order; game location id = 149 + index (hgss.py LOCATION_START).
AREAS = ["Plains", "Meadow", "Savannah", "Peak", "Rocky Beach", "Wetland",
         "Forest", "Swamp", "Marshland", "Wasteland", "Mountain", "Desert"]
TOD = ["morning", "day", "night"]
# The five sub-tables, in the order they appear in an element.  Our own names; PokeFinder's
# struct fields are grass/surf/old/good/super.
METHODS = ["grass", "surf", "old_rod", "good_rod", "super_rod"]
WATER_METHODS = METHODS[1:]
# hgss.py's hardcoded water_flag indices — cross-checked against the derived answer below.
EXPECTED_WATER_AREAS = {"Meadow", "Rocky Beach", "Wetland", "Swamp", "Marshland"}
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


def parse_element(el: bytes) -> dict:
    """``{method: {"normal": [30 slots], "block": [3*count], "conditions": [count]}}``.

    Consumes the element exactly — a short or long read means the layout assumption is wrong,
    so this asserts rather than guessing.
    """
    s = io.BytesIO(el)
    counts = [s.read(1)[0] for _ in range(5)]   # grass 10, surf 3, old/good/super 2
    s.read(3)                                   # pad

    def slots(n):
        r = []
        for _ in range(n):
            specie = struct.unpack("<H", s.read(2))[0]
            level = s.read(1)[0]
            s.read(1)                           # StaticSlot pad byte
            r.append((specie, level))
        return r

    out = {}
    for method, count in zip(METHODS, counts):
        out[method] = {
            "normal": slots(30),                           # 10 per time of day, every method
            "block": slots(count * 3),                     # count per time of day
            "conditions": [tuple(s.read(1)[0] for _ in range(4)) for _ in range(count)],
        }
    assert s.tell() == len(el), f"parsed {s.tell()} of {len(el)} bytes — layout mismatch"
    return out


def _sub_table(parsed_method: dict, count: int, name) -> dict:
    """One method's parsed tuples as the JSON shape, species ids mapped through ``name``."""
    normal, block = parsed_method["normal"], parsed_method["block"]
    return {
        "normal": {tod: [[name(sp), lv] for sp, lv in normal[10 * t:10 * t + 10]]
                   for t, tod in enumerate(TOD)},
        "block": {tod: [[name(sp), lv] for sp, lv in block[count * t:count * t + count]]
                  for t, tod in enumerate(TOD)},
        "conditions": [list(c) for c in parsed_method["conditions"]],
    }


def derive_water_areas(elements: list[bytes]) -> set[str]:
    """Which areas really have water, from the bytes (see the module docstring).

    The water sub-tables start at offset 288 (8-byte header + 280 bytes of grass).  Waterless
    areas all carry the same filler there; water areas each carry their own.
    """
    tails = {AREAS[i]: elements[i][288:] for i in range(len(AREAS))}
    filler = max(set(tails.values()), key=lambda blob: list(tails.values()).count(blob))
    return {area for area, tail in tails.items() if tail != filler}


def check_names_resolve(data: dict) -> None:
    """Every species name emitted must resolve in the files this one is joined against.

    safari_pokemon.json supplies catch and flee rates and backs the app's target list, so a
    name it doesn't carry is a species the app offers and then can't find an area for (or
    finds an area for and can't rate).  base_stats.json is the 493-species table.  Raises with
    the full list rather than writing a file that looks fine and joins to nothing.
    """
    rates, stats = basedata_json("safari_pokemon.json"), basedata_json("base_stats.json")
    emitted = {sp for area, entry in data.items() if not area.startswith("_")
               for method, table in entry.items() if method not in ("location", "has_water")
               for kind in ("normal", "block")
               for rows in table[kind].values() for sp, _lv in rows}
    missing_rates = sorted(sp for sp in emitted if sp not in rates)
    missing_stats = sorted(sp for sp in emitted if sp not in stats)
    if missing_rates or missing_stats:
        raise AssertionError(
            f"species names that don't join (clayton-69n): missing from safari_pokemon.json "
            f"{missing_rates}; missing from base_stats.json {missing_stats}")


def main() -> None:
    names = {}
    reader = csv.DictReader(io.StringIO(_fetch(NAMES_URL).decode("utf-8")))
    for row in reader:
        names[int(row["id"])] = canonical_species_name(row["identifier"])

    def name(sp: int) -> str:
        return names.get(sp, f"species-{sp}")

    els = narc_elements(_fetch(NARC_URL))
    assert len(els) == len(AREAS), f"expected {len(AREAS)} areas, got {len(els)}"

    water_areas = derive_water_areas(els)
    assert water_areas == EXPECTED_WATER_AREAS, (
        f"water areas derived from the data ({sorted(water_areas)}) disagree with hgss.py's "
        f"hardcoded set ({sorted(EXPECTED_WATER_AREAS)})")

    data = {"_meta": {
        "block_types": {"none": 0, "plains": 1, "forest": 2, "peak": 3, "water": 4},
        "tod_index": {"morning": 0, "day": 1, "night": 2},
        "methods": METHODS,
        "slot_formula": "slot(advance N) = (advance_rng^(N+draws)(seedA) >> 16) % 10, "
                        "draws=1 for grass/surf and 2 for a rod (the nibble check draws first)",
        "rod_base_rate": {"old_rod": 25, "good_rod": 50, "super_rod": 75},
        "source": "Admiral-Fish/EncounterTableGenerator hgss/safari NARC; species=veekun EN",
        "note": "all 5 methods; every method draws a flat 10-slot table, but the number of "
                "block-conditionals differs (grass 10, surf 3, rods 2). Block-conditionals "
                "fill top slots in order (PokeFinder Encounters4::getHGSSSafari). Surf/rod "
                "tables are emitted only for the 5 areas with water.",
    }}
    for idx, area in enumerate(AREAS):
        parsed = parse_element(els[idx])
        has_water = area in water_areas
        entry = {"location": 149 + idx, "has_water": has_water}
        for method in METHODS:
            if method in WATER_METHODS and not has_water:
                continue
            count = len(parsed[method]["conditions"])
            entry[method] = _sub_table(parsed[method], count, name)
        data[area] = entry

    check_names_resolve(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
    print(f"wrote {OUT}  ({len(AREAS)} areas, {len(water_areas)} with water)")


if __name__ == "__main__":
    main()
