#!/usr/bin/env python3
"""scrape_metronome_species.py — generate claytonlib/basedata/metronome_species.json.

Fetches each species' Serebii Gen4 Pokedex page (these aggregate Diamond/Pearl/Platinum/
HeartGold/SoulSilver data in one page, with per-move "- HGSS Only" annotations where a
move was added specifically in HeartGold/SoulSilver) and extracts exactly what a player's
own HGSS Chansey/Mew/etc. can learn through ordinary level-up / TM-HM / Move Tutor / Egg
Move / pre-evolution mechanics.

Deliberately EXCLUDED as not obtainable through normal HGSS play:
  * "Special Moves" (event-exclusive movesets, e.g. Mew's Pokemon Ranger crossover moves)
  * "<Nth> Gen Only Moves" (moves only known via transfer from an earlier-generation game)

Per the user's own ruling (bead clayton-b42.9.7): a species' effective movepool includes
its pre-evolutions' moves too, since Pokemon don't forget moves on evolving. Serebii's own
"Pre-Evolution Moves" table already reflects this directly (it lists moves the CURRENT
species' earlier evolutionary stage(s) learn, which the current species retains), so no
separate union step is needed here.

Gender category and ability list are NOT scraped — they were independently confirmed
against the same Serebii pages by a prior research pass (source URL per species below) and
hardcoded, since it's a small, already-spot-checked handful of values, unlike the
~50-150-move lists per species this script exists specifically to avoid hand-transcribing.
`gender` is one of "female_only" / "male_only" / "genderless" / "both" — a coarser category
than the exact ratio, because that's all the app's gender dropdown actually needs (see
renderProfiles' species-gender wiring): a "both" species just disables the genderless
option and lets the user pick which they actually have, regardless of the real-world ratio.

Re-run with network access to refresh: `python one-offs/scrape_metronome_species.py`
Source pattern: https://www.serebii.net/pokedex-dp/<national-dex-no>.shtml
"""
import json
import re
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "metronome_species.json"
MOVES_PATH = Path(__file__).resolve().parent.parent / "claytonlib" / "basedata" / "moves.json"

# (National Dex #, name, gender category, abilities) for the 15 species the app's
# Metronome-user Species dropdown offers. gender/abilities confirmed against each
# species' own https://www.serebii.net/pokedex-dp/<no>.shtml (Gender Ratio row / Ability
# row) — see notes/flagged_for_review.md for the research pass this came from.
SPECIES = [
    # Happiny -> Chansey -> Blissey: 100% female; Natural Cure + Serene Grace.
    (440, "Happiny", "female_only", ["Natural Cure", "Serene Grace"]),
    (113, "Chansey", "female_only", ["Natural Cure", "Serene Grace"]),
    (242, "Blissey", "female_only", ["Natural Cure", "Serene Grace"]),
    # Cleffa -> Clefairy -> Clefable: 25% M / 75% F; Cute Charm + Magic Guard.
    (173, "Cleffa", "both", ["Cute Charm", "Magic Guard"]),
    (35, "Clefairy", "both", ["Cute Charm", "Magic Guard"]),
    (36, "Clefable", "both", ["Cute Charm", "Magic Guard"]),
    # Mew: genderless; Synchronize only (no second ability slot).
    (151, "Mew", "genderless", ["Synchronize"]),
    # Togepi -> Togetic -> Togekiss: 87.5% M / 12.5% F; Hustle + Serene Grace.
    (175, "Togepi", "both", ["Hustle", "Serene Grace"]),
    (176, "Togetic", "both", ["Hustle", "Serene Grace"]),
    (468, "Togekiss", "both", ["Hustle", "Serene Grace"]),
    # Munchlax -> Snorlax: 87.5% M / 12.5% F; ability pair CHANGES on evolution.
    (446, "Munchlax", "both", ["Pickup", "Thick Fat"]),
    (143, "Snorlax", "both", ["Immunity", "Thick Fat"]),
    # Snubbull -> Granbull: 25% M / 75% F; ability pair CHANGES on evolution.
    (209, "Snubbull", "both", ["Intimidate", "Run Away"]),
    (210, "Granbull", "both", ["Intimidate", "Quick Feet"]),
]

# Section headers worth keeping moves from — matched against the plain (HTML-stripped)
# header text of each "fooevo"-classed section on the page. Deliberately an ALLOWLIST
# (not a denylist of the excluded sections) so an unrecognised section is dropped by
# default rather than silently included.
_ALLOWED_SECTION_RE = re.compile(
    r"Level Up|TM & HM Attacks|Move Tutor Attacks|Egg Moves|Pre-Evolution Moves")
_MOVE_LINK_RE = re.compile(r'attackdex-dp/[a-z0-9-]+\.shtml">([^<]+)<')
_SECTION_RE = re.compile(r'class="fooevo">(.*?)</', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _fetch(dex_no: int) -> str:
    url = f"https://www.serebii.net/pokedex-dp/{dex_no:03d}.shtml"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("latin-1")


def _section_moves(html: str) -> list[str]:
    """Every move name from every allowed section, deduplicated, in first-seen order."""
    marks = list(_SECTION_RE.finditer(html))
    seen: set[str] = set()
    out: list[str] = []
    for i, m in enumerate(marks):
        header = _TAG_RE.sub("", m.group(1)).strip()
        if not _ALLOWED_SECTION_RE.search(header):
            continue
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(html)
        chunk = html[start:end]
        for mv in _MOVE_LINK_RE.finditer(chunk):
            name = mv.group(1).strip()
            if name and name not in seen:
                seen.add(name)
                out.append(name)
    return out


def _collapse(s: str) -> str:
    """Case/whitespace/punctuation-insensitive key, since Serebii spells some move names
    differently than claytonlib/basedata/moves.json (e.g. "Doubleslap" vs "Double Slap",
    "Double-edge" vs "Double Edge")."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _canonical_move_names() -> dict[str, str]:
    moves = json.loads(MOVES_PATH.read_text())
    return {_collapse(m["name"]): m["name"] for m in moves}


def main():
    canon = _canonical_move_names()
    species_out: dict[str, dict] = {}
    unresolved: dict[str, list[str]] = {}

    for dex_no, name, gender, abilities in SPECIES:
        print(f"Fetching #{dex_no} {name}...")
        html = _fetch(dex_no)
        raw_moves = _section_moves(html)
        resolved: list[str] = []
        missing: list[str] = []
        for mv in raw_moves:
            canon_name = canon.get(_collapse(mv))
            if canon_name:
                if canon_name not in resolved:
                    resolved.append(canon_name)
            else:
                missing.append(mv)
        if missing:
            unresolved[name] = missing
        species_out[name] = {
            "dex_no": dex_no,
            "gender": gender,
            "abilities": abilities,
            "moves": sorted(resolved),
        }
        time.sleep(1)  # be polite to Serebii

    OUT.write_text(json.dumps(species_out, indent=2) + "\n")
    print(f"\nWrote {OUT}")
    for name, info in species_out.items():
        print(f"  {name}: {len(info['moves'])} move(s)")

    if unresolved:
        print("\nWARNING — Serebii move names that did not resolve against moves.json "
              "(NOT included in the output; check these by hand):")
        for name, moves in unresolved.items():
            print(f"  {name}: {moves}")


if __name__ == "__main__":
    main()
