#!/usr/bin/env python3
"""populate_base_stats.py — build claytonlib/basedata/base_stats.json from PokeAPI.

Battle Compass needs base stats for two things: deriving a *target's* actual stats from the
IVs and nature the player enters (notes/battle_compass.md sec 15.4.1), and the Fast Ball's
base-Speed >= 100 test.  Our own party's stats are typed in off the summary screen, so this
data is only ever consulted for targets.

Also records each species' types (for the damage model's effectiveness lookup) and weight in
hectograms (for the Heavy Ball, which is deferred but free to capture while we are here).

Usage:
    python one-offs/populate_base_stats.py                  # the default species list
    python one-offs/populate_base_stats.py suicune lugia     # named species only
    python one-offs/populate_base_stats.py --all-gen4        # every species up to #493
    python one-offs/populate_base_stats.py --check           # verify the file, fetch nothing

PokeAPI returns Gen 9 data.  No base stat, type or weight among the species below has changed
since Gen 4, but --check reports anything that would silently differ if the list grows: see
KNOWN_POST_GEN4_CHANGES.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "base_stats.json"
API = "https://pokeapi.co/api/v2/pokemon/{}"
# capture_rate lives on the SPECIES resource, not the pokemon one.
SPECIES_API = "https://pokeapi.co/api/v2/pokemon-species/{}"
# PokeAPI 403s without one.
HEADERS = {"User-Agent": "clayton/0.1 (+https://github.com/Testare/clayton)"}

# PokeAPI's stat names -> ours.
_STAT_MAP = {
    "hp": "hp", "attack": "atk", "defense": "def",
    "special-attack": "spa", "special-defense": "spd", "speed": "spe",
}
_STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")

# Species whose Gen 4 stats/types differ from what PokeAPI reports.  Nothing in DEFAULT_SPECIES
# is affected; this exists so --all-gen4 cannot quietly introduce modern values.  Base-stat
# revisions landed in Gen 6 (e.g. several base-stat buffs) and type changes in Gen 6 (Fairy).
KNOWN_POST_GEN4_CHANGES: dict[str, str] = {
    "clefairy": "became Fairy in Gen 6", "clefable": "became Fairy in Gen 6",
    "jigglypuff": "became Fairy in Gen 6", "wigglytuff": "became Fairy in Gen 6",
    "mr-mime": "gained Fairy in Gen 6", "cleffa": "became Fairy in Gen 6",
    "igglybuff": "became Fairy in Gen 6", "togepi": "became Fairy in Gen 6",
    "togetic": "became Fairy in Gen 6", "marill": "gained Fairy in Gen 6",
    "azumarill": "gained Fairy in Gen 6", "snubbull": "became Fairy in Gen 6",
    "granbull": "became Fairy in Gen 6", "ralts": "gained Fairy in Gen 6",
    "kirlia": "gained Fairy in Gen 6", "gardevoir": "gained Fairy in Gen 6",
    "azurill": "gained Fairy in Gen 6", "mawile": "gained Fairy in Gen 6",
    "mime-jr": "gained Fairy in Gen 6", "togekiss": "became Fairy in Gen 6",
    "cottonee": "Fairy line, post-Gen 4", "gorebyss": "base stats revised in Gen 6",
    "butterfree": "base stats revised in Gen 6",
    "beedrill": "base stats revised in Gen 6", "pidgeot": "base stats revised in Gen 6",
    "alakazam": "base stats revised in Gen 6", "victreebel": "base stats revised in Gen 6",
    "golem": "base stats revised in Gen 6", "ampharos": "base stats revised in Gen 6",
}

# Species whose ABILITIES differ from what PokeAPI reports, which is a shorter list than it
# looks only because DEFAULT_SPECIES is short.  Abilities were revised far more often than base
# stats were -- Gen 7 and Gen 9 both reshuffled several -- so this refuses rather than guesses.
# The values currently in base_stats.json were taken from the ROM's own personal.json, which is
# Gen 4 by construction; this table exists so a regeneration cannot quietly replace them.
KNOWN_POST_GEN4_ABILITY_CHANGES: dict[str, str] = {
    "gyarados": "gained Moxie in Gen 5",
    "snorlax": "gained Gluttony in Gen 5 as a second slot",
    "magnemite": "gained Analytic in Gen 5", "magneton": "gained Analytic in Gen 5",
    "mamoswine": "gained Thick Fat in Gen 5",
}

# The section 11 fixture plus the HGSS statics Battle Compass is likely to target next.
DEFAULT_SPECIES = [
    # fixture
    "suicune", "magneton", "magnemite", "smeargle", "mamoswine",
    # mechanics-validation stand-ins (re-encounterable, nothing lost on a mistake)
    "snorlax", "sudowoodo",
    # other HGSS static legendaries
    "ho-oh", "lugia", "entei", "raikou", "mewtwo",
    "groudon", "kyogre", "rayquaza",
    "dialga", "palkia", "giratina-altered", "latias", "latios",
]


def _get(url: str, name: str, retries: int = 3) -> dict | None:
    """One GET, retried politely; PokeAPI rate-limits aggressive clients.

    None on a 404, so a form that needs its suffix is reported rather than discarding everything
    fetched so far.
    """
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=HEADERS), timeout=20
            ) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                print(f"  ! no such species: {name} (a form suffix may be needed)")
                return None
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def fetch(name: str, retries: int = 3) -> dict:
    """One species, normalised.  Two requests: stats/types/weight, then the capture rate."""
    payload = _get(API.format(name.lower()), name, retries)
    if payload is None:
        return {}
    stats = {_STAT_MAP[s["stat"]["name"]]: s["base_stat"] for s in payload["stats"]}
    missing = [k for k in _STAT_KEYS if k not in stats]
    if missing:
        raise SystemExit(f"{name}: PokeAPI returned no {missing}")
    types = [t["type"]["name"].capitalize()
             for t in sorted(payload["types"], key=lambda t: t["slot"])]
    # The catch rate the capture formula needs (battle.catch). Unchanged since Gen 3 for
    # everything in scope, so Gen 9 data is safe here for the same reason the stats are.
    species = _get(SPECIES_API.format(payload["species"]["name"]), name, retries) or {}
    catch_rate = species.get("capture_rate")
    if not isinstance(catch_rate, int) or not 1 <= catch_rate <= 255:
        raise SystemExit(f"{name}: PokeAPI returned capture_rate {catch_rate!r}")
    # Abilities, for `battle.stats.has_pressure` -- Pressure doubles OUR PP consumption, and
    # assuming it where there is none halves every PP budget the solver plans against.
    #
    # Hidden abilities are dropped: they are a Gen 5 concept and a Gen 4 wild Pokemon cannot
    # have one, so including them would let a Gen 5+ hidden ability answer a Gen 4 question.
    # Abilities DID change after Gen 4 more often than stats or types did, so any species whose
    # ability matters is listed in KNOWN_POST_GEN4_ABILITY_CHANGES below and refused outright
    # rather than silently taking the modern value.
    abilities = [a["ability"]["name"].replace("-", " ").title()
                 for a in sorted(payload["abilities"], key=lambda a: a["slot"])
                 if not a.get("is_hidden")]
    changed = KNOWN_POST_GEN4_ABILITY_CHANGES.get(payload["name"])
    if changed:
        raise SystemExit(f"{name}: abilities changed after Gen 4 ({changed}); take them from "
                         f"the ROM's personal.json instead of PokeAPI.")
    return {
        "name": payload["name"],
        "dex_no": payload["id"],
        "base_stats": {k: stats[k] for k in _STAT_KEYS},
        "types": types,
        "weight_hg": payload["weight"],
        "catch_rate": catch_rate,
        "abilities": abilities,
    }


def load() -> dict[str, dict]:
    return json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}


def save(entries: dict[str, dict]) -> None:
    OUTPUT.write_text(json.dumps(dict(sorted(entries.items())), indent=2) + "\n")
    print(f"  wrote {len(entries)} species to {OUTPUT.relative_to(OUTPUT.parents[3])}")


def check(entries: dict[str, dict]) -> int:
    """Validate the stored file without hitting the network.  Returns an exit code."""
    problems = []
    for key, entry in sorted(entries.items()):
        for field in ("name", "dex_no", "base_stats", "types", "weight_hg", "catch_rate"):
            if field not in entry:
                problems.append(f"{key}: missing {field}")
        for stat in _STAT_KEYS:
            value = entry.get("base_stats", {}).get(stat)
            if not isinstance(value, int) or not 1 <= value <= 255:
                problems.append(f"{key}: base {stat} is {value!r}")
        rate = entry.get("catch_rate")
        if not isinstance(rate, int) or not 1 <= rate <= 255:
            problems.append(f"{key}: catch_rate is {rate!r}")
        if not 1 <= len(entry.get("types", [])) <= 2:
            problems.append(f"{key}: {len(entry.get('types', []))} types")
        if "Fairy" in entry.get("types", []):
            problems.append(f"{key}: Fairy does not exist in Gen 4")
        if key in KNOWN_POST_GEN4_CHANGES:
            problems.append(f"{key}: {KNOWN_POST_GEN4_CHANGES[key]} — verify against HGSS")
    for problem in problems:
        print(f"  ! {problem}")
    print(f"  {len(entries)} species, {len(problems)} problem(s)")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("species", nargs="*", help="species to fetch (default: DEFAULT_SPECIES)")
    parser.add_argument("--all-gen4", action="store_true", help="every species up to #493")
    parser.add_argument("--check", action="store_true", help="validate the file, fetch nothing")
    parser.add_argument("--force", action="store_true", help="re-fetch species already stored")
    args = parser.parse_args()

    entries = load()
    if args.check:
        return check(entries)

    if args.all_gen4:
        wanted = [str(n) for n in range(1, 494)]
    else:
        wanted = args.species or DEFAULT_SPECIES

    for name in wanted:
        if not args.force and name.lower() in entries:
            print(f"  {name}: already stored, skipping")
            continue
        entry = fetch(name)
        if not entry:
            continue
        entries[entry["name"]] = entry
        stats = entry["base_stats"]
        print(f"  {entry['name']:12} #{entry['dex_no']:<4} "
              f"{'/'.join(entry['types']):16} "
              + " ".join(f"{k} {stats[k]:3}" for k in _STAT_KEYS))
        time.sleep(0.4)  # be a good citizen

    save(entries)
    return check(entries)


if __name__ == "__main__":
    sys.exit(main())
