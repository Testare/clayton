# Safari encounters beyond grass: surf and the three rods (clayton-858)

Until now `claytonlib.safari_encounters` resolved **grass only**, and
`one-offs/extract_safari_zones.py` parsed only the grass third of each NARC element. This note
records what the other four sub-tables are, how the RNG treats them, and which claims rest on
ground truth versus on reading PokeFinder's source.

Claims are tagged **[verified]** (ground truth in this repo), **[derived]** (read off
PokeFinder/EncounterTableGenerator source, which the grass case already validated),
**[from data]** (recovered from the NARC bytes themselves) and **[needs gdb]**.

## 1. The data

Each of the 12 NARC elements is 912 bytes and holds **five** sub-tables, not one. **[from data]**

```
 8  header: five block-conditional counts (grass 10, surf 3, old/good/super rod 2) + 3 pad
    then, per method, in that order:
120  normal slots   -- 30 StaticSlots: 10 per time of day, for EVERY method
 4c  block slots    -- count * 3 StaticSlots: count per time of day
 4c  conditions     -- count * (type1, qty1, type2, qty2)
     StaticSlot = u16 specie, u8 level, u8 pad
     8 + 280 + 168 + 152*3 = 912  (matches PokeFinder's WildEncounterHGSSSafari asserts)
```

The parser now asserts it consumed the element exactly, so a layout mistake fails loudly
instead of silently shifting every table.

### Only five areas have water

Meadow, Rocky Beach, Wetland, Swamp, Marshland. **[verified]** PokeFinder's `hgss.py` hardcodes
those indices as its `water_flag`, and the bytes agree independently: the other **seven areas
share one byte-identical filler blob** across all four water sub-tables (a Tentacool/Wooper
table the game never reads), while each of the five real ones is unique. **[from data]** The
extractor derives `has_water` that way *and* asserts it against the hardcoded set, so a future
data refresh can't quietly disagree with either source. Waterless areas get no water tables
emitted at all, so the UI can't offer a Tentacool in Mountain.

### What this opens up

Twelve species no grass table anywhere carries — previously unreachable by Clayton at all:
**magikarp, poliwag, poliwhirl, goldeen, seaking, gyarados, lapras, dratini, dragonair,
corphish, barboach, masquerain**. The easiest route to the interesting ones (lowest block
threshold across every area and method): **[from data]**

| Species | Easiest route | Block requirement |
|---|---|---|
| Lapras | Rocky Beach, Surf | none — slots 8-9 at L15/16; water 10/14/18 upgrade slots 0-2 to L37/42/47 |
| Dratini | Swamp, Super Rod | none — slots 8-9 at L36/37 (or Good Rod at water 10) |
| Dragonair | Swamp, Super Rod | water 15 |
| Seaking | Rocky Beach or Swamp, Super Rod | none |
| Gyarados | Marshland, Super Rod | none (or Good Rod at water 3) |
| Kingler | Rocky Beach, Super Rod | none (grass needs peak 8) |
| Corphish | Wetland, Good Rod | water 10 (or Rocky Beach Super Rod at water 15) |
| Barboach | Marshland, Super Rod | water 4 |
| Masquerain | Meadow, Surf | water 10 |

Several species already huntable in grass also get a cheaper water route — Muk, Jumpluff,
Quagsire, Golduck, Murkrow, Duskull, Skiploom all appear in a surf table too.

The capture side needs no new data: `basedata/safari_pokemon.json` already carries catch and
flee rates for **every** species reachable by any water method here. **[verified]**

## 2. The RNG

From PokeFinder `Core/Gen4/Generators/WildGenerator4.cpp :: generateMethodK` and
`Core/Gen4/Encounters4.cpp :: getHGSSSafari`.

### Safari always draws a flat 10-slot table — for every method **[derived]**

```cpp
if (safari) { encounterSlot = go.nextUShort(10); }
else        { encounterSlot = EncounterSlot::kSlot(go.nextUShort(100), area.getEncounter()); }
```

That `if (safari)` sits *above* the per-encounter-type branch, so surf and the rods get the
same flat `(rand >> 16) % 10` grass does. `getHGSSSafari` matches: it fills `slots[0..9]` for
surf and each rod exactly as it does for grass, reading 10 normal slots per time of day even
though only 3 (surf) or 2 (rods) block-conditionals compete for them. The usual Gen-4 surf and
fishing rate thresholds (`60/30/5/4/1`) never apply inside the Safari Zone.

This is the same `safari` flag whose grass path we already validated 132/132 against
`notes/pokefinder_spread.md`, which is why this extension is cheap: the formula we tested *is*
the formula for all five methods.

### No level draw, for any method **[derived]**

`if (Grass || safari) calculateLevel<false, true>(...)` takes the non-`diff` branch, which
consumes no rand (absent a Pressure lead) and just reads the slot's level. `getHGSSSafari`
builds each slot as `Slot(specie, level, level)` — min == max. So level stays a table lookup,
and species stays a one-draw question. No PID/IV work is needed, as before.

### A rod rolls the nibble check FIRST **[derived]** / **[needs gdb]**

```cpp
if ((RockSmash || OldRod || GoodRod || SuperRod) && go.nextUShort(100) >= rate) valid = false;
```

This precedes the slot draw, so for a rod:

* `nibble  = (advance_rng^(frame+1)(seedA) >> 16) % 100`, bites iff `< rate`
* `slot    = (advance_rng^(frame+2)(seedA) >> 16) % 10`

i.e. **a rod's slot sits exactly one advance later than grass/surf's**. A failed check is
"Not even a nibble..." — no encounter, and the stream is left exactly one advance on, which
makes a deliberately wasted cast a cheap single advance.

`rate` is 25 / 50 / 75 for old / good / super rod **[derived]** (`getHGSSSafari` passes those
as each area's `rate`), plus the lead's happiness bonus, then doubled by a Suction Cups lead:
`rate = (base + happiness) * (2 if suction_cups)`. It may exceed 100, which simply means it
always bites.

**[needs gdb]** Two things here are reasoning, not capture, and should be confirmed before a
rod run is trusted to the frame:

1. The `+2` slot offset for rods. The `+1` for grass was *fit to ground truth*; the rod's extra
   advance is inferred from the draw order above. Per CLAUDE.md's rule on verified advance
   counts, treat `_SLOT_DRAW[rod] = 2` as derived until a capture backs it.
2. The happiness bonus. PokeFinder offers the tiers **0 / 20 / 30 / 40 / 50** but doesn't say
   which friendship bands produce them, so Clayton takes the bonus as a configured input and
   defaults it to **0** — which under-predicts hooks (frames we skip that would in fact have
   bitten) rather than promising ones that never happen. Getting it wrong does not shift which
   species a frame yields; it changes which frames are offered at all.

### An upstream typo we deliberately don't copy **[from data]**

PokeFinder's `OldRod` branch of `getHGSSSafari` reads `data[i].surf.type1[block]` and
`data[i].surf.type2[block]` while reading `data[i].old.quantity1/2[block]` — mixing surf's
block *types* with the old rod's *quantities*. We use the old rod's own types. It makes no
difference on this data: every water area's surf and old-rod conditions use type1 = water (4)
and type2 = the 0 sentinel, so both readings agree. Worth knowing if a future comparison
against PokeFinder ever disagrees on a rod.

## 3. What Clayton does with it

* `claytonlib/basedata/safari_zones.json` — now all 12 areas x up to 5 methods, plus
  `has_water`. The grass data is byte-identical to the previous file (checked).
* `claytonlib.safari_encounters` — `METHODS`, `normalize_method`, `safari_methods`,
  `has_water`, `hook_rate`, `rod_hooks`, `locations_for_species`, `methods_for_species`; and
  `method=` on `resolve_safari_slots`, `frame_slot`, `advance_frame_species`,
  `iter_encounter_frames`, `find_encounter_frame`, `areas_for_species`,
  `block_requirement_for`. A water method in a waterless area raises and names the five areas
  that do have water. For a rod, `iter_encounter_frames` yields only frames that actually hook.
* `claytonlib.safari_advance` / `utils/safari_advance.py` — the route is unchanged (chatot
  flips, then a readable Elm margin, acting ON the target frame), but `AdvancePlan` carries its
  `method` and exposes `action`, so the guide says "cast the Super Rod" where it used to say
  "Sweet Scent" regardless.
* The app — `Expedition.safari_method` (default `"grass"`, so every expedition saved before
  this reads correctly), plus `fishing_happiness_bonus` and `fishing_suction_cups`. Configure
  asks "How you'll find it" *before* the area, because the method narrows the areas: a Lapras
  is a Rocky Beach surf encounter and nothing else, so asking for the area first would offer
  eleven areas that can never produce one.

## 4. Not modelled

* **Leads other than Suction Cups.** Pressure (which adds a level draw and can bump the slot),
  Magnet Pull / Static (which replace the slot draw entirely), Cute Charm and Synchronize all
  change the draw sequence. None apply to a plain Safari hunt, and Clayton has never modelled
  them for grass either.
* **Shiny / PID / IVs.** Same as grass: we only ever need the species.
* **Rock Smash**, which shares the rod's nibble-check shape but isn't a Safari method.
