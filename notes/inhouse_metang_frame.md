# In-house Metang target-frame determination (clayton-ctd.8) — research

**Goal:** replace the Pokefinder handoff in Section A.2 (`prompt_target_frame`) with our own
computation: given Seed A, find the advance frame that yields a Metang (ideally the shiny one),
using the Safari-Zone encounter tables + the Gen-4 RNG we already have.

**Verdict: feasible and, for the common case, cheap.** The HGSS *Safari Zone* encounter path is a
special-cased, much simpler branch than normal grass. The species is a one-line function of a
single RNG draw. Shiny detection is more work but fully specified below.

## What we already have

- `advance_rng(state) = (state*0x41C64E6D + 0x6073) & 0xFFFFFFFF` — this **is** the standard Gen-4
  LCRNG (1103515245 / 24691). So "advance frame N of Seed A" = `advance_rng` applied N times.
- Seed A is identified exactly (Section A.1) and its `elm`/advance model already walks this stream.
- Ground truth for verification (notes/safari_calibration_notebook.md): on the reference seed,
  advance **10 → L42 Larvitar**, **11 → L44 Metang**, **81 → shiny Metang**.

## The algorithm (PokeFinder `WildGenerator4::generateMethodK`, Safari branch)

HGSS wild encounters use **Method K**. `safariZone()` is true for `Game::HGSS` with location in
148–160, which routes generation through the Safari-specific branch. Starting from the RNG state at
the encounter frame, draws happen in this order (each `nextUShort(n)` consumes one LCRNG advance and
uses `state>>16`; default Method-K `nextUShort(n) = (state>>16) % n`):

1. **Encounter slot (SPECIES):** `slot = (rand >> 16) % 10`.
   Safari uses a **flat 10-slot** table (`go.nextUShort(10)`), *not* the 100-value `kSlot()`
   thresholds normal grass uses. `species = area.getPokemon(slot).getSpecie()`.
2. **Level:** `area.calculateLevel<false,true>(slot, …)` — one draw, `min + (rand>>16)%(max-min+1)`
   (Pressure lead differs; may skip the draw when `min==max` — confirm during impl; **does not
   affect species**).
3. **Nature / PID / IVs (Safari-special loop):** `if (BugCatchingContest || safari)` runs **up to 4
   iterations** of: nature `= (rand>>16)%25` (no lead); PID loop `do { low; high; pid=(high<<16)|low }
   while pid%25 != nature`; `iv1`; `iv2`; **break early if any of the first three IVs in iv1 or iv2
   == 31**. This is a variable number of draws.
4. **Item:** `(rand>>16) % 100`.
5. **Shiny:** `getShiny(pid, tsv)` with `tsv = TID ^ SID`; shiny iff `(TID^SID^pidHi^pidLo) < 8`.

(No nibble check unless rod/rock-smash; no magnet/static/cute-charm/sync draws unless that lead is
held — for a plain Metang hunt none apply.)

### Key consequence

**Species depends ONLY on the first draw:** `species = table[(rand_at_frame >> 16) % 10]`. So
"is frame N a Metang?" is trivial and robust — it does not depend on the level/PID/IV/item draws or
their exact counts. Consecutive frames change the slot draw, which is why 10→Larvitar and
11→Metang differ. **Shiny** detection needs the full step-3 loop + the trainer's TID/SID.

## What data we need (and what we can skip)

- **The Mountain-area Safari 10-slot table** (slot → species + level range) for the user's
  **current block configuration, day count, and time of day.** Metang unlocks in the **Mountain**
  area after **~30 days**. The 10 slots' contents shift as blocks "level up" over days, so this
  table is a **config input that must be refreshed if the setup/day/ToD changes**, not a constant.
  - **Sources:** read it once from Pokefinder, or from the shinyfinder Safari-Zone slot calculator
    (block scores + area + ToD → the 10 slots); its data lives under `/encounter-slots/safari-zone/`.
  - **We do NOT need to port the block-score → table logic** for an MVP (that's the "decent amount
    of work for modest savings" the ticket flags). Take the resolved table as config.
- **Trainer TID/SID** — only for shiny detection (step 5).
- **The frame offset** between "advance frame we count in the notebook" and "the slot draw index."
  Calibrate against the ground truth (81=shiny Metang, 11=L44 Metang, 10=L42 Larvitar) and/or
  Pokefinder; the notebook already empirically fixed "Sweet Scent on the target frame itself."

## Recommended scope

- **MVP (satisfies acceptance criteria — "a suitable Metang frame, no Pokefinder"):**
  species-only. Config: the 10-slot species table. Scan advance frames f∈[0, ~200], compute
  `slot=(advance(seedA,f)>>16)%10`, return the nearest f whose species is Metang (+ its level from
  step 2). Small: a table dict + a scan fn + tests. This removes the handoff for the usual
  off-target case (where we just need *a* Metang, not the shiny).
- **Stretch (the "81" shiny case):** add step-3 loop + `calculateLevel` + TID/SID input + getShiny
  to locate the shiny-Metang frame. Moderate but fully specified above. Keep Pokefinder as fallback
  until this lands.
- **Avoid:** porting the block-score→table logic. Low value; make the table config/lookup instead.

## Verification plan

1. Reproduce the ground-truth frames on the reference seed (10/11/81).
2. Diff our species-per-frame against Pokefinder over a frame range on a real Seed A.
3. Optionally capture a few encounters via the existing gdb tooling (breakpoint on the encounter
   RNG) to confirm draw order/offset.

## Open items to pin during implementation

- Exact draw count of `calculateLevel` (min==max skip? Pressure branch) — affects only the
  shiny-frame mapping, not species.
- Any fixed pre-encounter advance from Sweet Scent (calibrate empirically).
- Slot-table refresh workflow when the Safari day/ToD/blocks change.

## REVISION (per requirements clarification)

Three corrections that change the design:

1. **Block config is an INPUT and the block→table rules are in scope.** No sidestepping. The tool
   takes the Plains/Forest/Peak/Water block scores and resolves the area's 10-slot table itself.
2. **No shiny.** Drop the whole step-3 PID/IV loop and TID/SID. We never need the PID.
3. **`target_advances` is an input.** When the loaded Seed A **equals the key (target) seed**, the
   answer is simply `target_advances` (the configurable "81" analog — hitting the exact seed means
   we hit the exact intended frame). Only when we land on a *different* seed do we scan for a Metang
   frame in-house.

### The block → 10-slot resolution (PokeFinder `Encounters4::getHGSSSafari`)

Per-area data (from a compressed resource `HGSS_SAFARI`) holds, for `grass` (also `surf`/rods):
- `normal.slots[30]` — the **default** 10 species × 3 ToD baseline table.
- Parallel **block-conditional** arrays: `type1/quantity1` + `type2/quantity2` (dual block-type +
  score thresholds) and `block.slots[]` (the replacement species + level for that block entry).

Resolution: for each block entry, if `blocks[type1] >= quantity1 && blocks[type2] >= quantity2`,
that entry's species/level **replaces** the corresponding slot; entries are processed in order.
Bulbapedia's higher-level description: a block encounter "replaces the topmost available slot, with
higher ID prioritized." Net effect for us: given the four block scores + area + ToD, we get a
concrete 10-slot species array, and **Metang occupies whichever slot(s) its Mountain entry (Peak
score ≥ 24) resolves to.**

Block scores carry a **day multiplier**: a placed block counts ×1, rising to ×2 at 10 days … ×7 at
250 days the area has been active. So "score" = physical count × multiplier(days-active).

### Revised interface (Section A.2, replacing `prompt_target_frame`)

Inputs: `a_seed` (identified), `key_seed = seed_for(a_target_time, a_target_delay)`,
`target_advances` (int), `blocks={plains,forest,peak,water}` scores, `area="mountain"`, `tod`,
`method="land"`.
Logic: if `a_seed == key_seed` → return `target_advances`. Else resolve Metang's slot set from the
blocks, then scan advance frames f, `slot=(advance(a_seed,f)>>16)%10`, return the nearest f whose
slot is Metang (with its level). Species-only; **no PID draws consumed or needed.**

### Effort now (with blocks in, shiny out)

- Frame scan + `a_seed==key_seed` shortcut: trivial.
- Block-resolution logic: small once the DATA exists (a threshold loop).
- **The real cost is the DATA:** the per-area default ToD tables + block-conditional entries
  (type/threshold/species/level). This is transcription, not algorithm.

### Data-source options (the decision to make)

- **(a) Transcribe Mountain-only** (default table by ToD + block-conditionals incl. Metang) into a
  small `claytonlib/basedata/safari_zone_<area>.json`, from Bulbapedia, verified against the ground
  truth (10/11 → Larvitar/Metang) and a Pokefinder dump. Fast; covers the actual hunt.
- **(b) Bundle shinyfinder's JSON** (`/encounter-slots/safari-zone/`) for all areas + replicate its
  resolution. Medium; general.
- **(c) Extract PokeFinder's `HGSS_SAFARI` compressed resource.** Most faithful/general, most work.

**DECIDED: all Safari areas** (user, this session). That rules out manual transcription and points
at extracting the raw table programmatically:

### Chosen data path — extract, don't transcribe

- Raw data: **`hgss_safari.bin`** in Admiral-Fish's **EncounterTableGenerator** repo
  (PokeFinder's `Core/Resources/EncounterTables` submodule). PokeFinder just `zstd.compress`es this
  blob (embed_gen4.py) and reads it back via the `WildEncounterHGSSSafari` struct — so the .bin's
  byte layout **is** that struct: per area, `grass.normal.slots[30]` (10 species × 3 ToD) +
  block-conditional `type1/quantity1/type2/quantity2` + `block.slots[]` (species+level), plus
  surf/rod sub-tables we can ignore.
- Plan: one-off `one-offs/extract_safari_zones.py` → parse `hgss_safari.bin` per the struct
  (layout read from `Core/Gen4/Encounters4.hpp`), map species IDs → names, emit
  `claytonlib/basedata/safari_zones.json` (all 12 areas). Check the EncounterTableGenerator repo
  first — it may already carry a human-readable source (JSON/CSV) for the .bin, which is even easier.

### Runtime pieces

- `resolve_safari_slots(area, tod, blocks) -> list[str]` (len 10): default ToD row, then apply the
  dual-threshold block replacements exactly as `getHGSSSafari` does.
- `find_metang_target(a_seed, key_seed, target_advances, area, tod, blocks, pokemon="metang",
  max_scan=~250) -> int`: if `a_seed == key_seed` return `target_advances`; else Metang slots =
  indices where `resolve_safari_slots(...) == pokemon`, scan f with `slot=(advance(a_seed,f)>>16)%10`,
  return nearest f in a Metang slot (+ level). Replaces `prompt_target_frame` in cell05.

### Decided defaults

- Block input = **resolved scores** (multiplier already applied; matches Pokefinder), unless the
  user asks for raw-counts-+-days-active with the ×1..×7 multiplier computed in-tool.

## Sources

- PokeFinder `Core/Gen4/Generators/WildGenerator4.cpp` (generateMethodK), `EncounterArea4.cpp`
  (safariZone: HGSS + location 148–160): https://github.com/Admiral-Fish/PokeFinder
- Method J vs K / HGSS wild RNG: https://www.pokemonrng.com/emulator-hgss-wild/
- Metang = Mountain area after ~30 days; Safari slot calculator (block scores → 10 slots):
  https://shinyfinder.github.io/tools/safari-zone-calc/ ,
  https://bulbapedia.bulbagarden.net/wiki/Johto_Safari_Zone

## IMPLEMENTED (2026-09-14)

Shipped, all-areas, verified 132/132 against notes/pokefinder_spread.md:
- `claytonlib/basedata/safari_zones.json` — all 12 areas (grass/Land), generated by
  `one-offs/extract_safari_zones.py` (reproducible; byte-identical data on re-run).
- `claytonlib/safari_encounters.py` — `resolve_safari_slots`, `frame_slot`,
  `advance_frame_species`, `find_encounter_frame`. Slot = `(advance_rng^(N+1)(seed)>>16)%10`;
  block scores per type {plains:1,forest:2,peak:3,water:4}. No shiny.
- `utils/safari_advance.py::choose_target_frame` — the toggle: exact key-seed hit →
  `target_advances` regardless of toggle; else in-house (True) or Pokefinder prompt (False).
- Notebook Section A.2 (cell05) config: `a_use_inhouse`, `a_target_advances`, `a_area`, `a_tod`,
  `a_blocks`; `a_key_seed = seed_for(a_target_time, a_target_delay)`.
- Tests: `tests/test_safari_encounters.py`, `TestChooseTargetFrame` in `tests/test_safari_advance.py`.

Note: for a **different** seed (0x0C0E02C8, frame 14) the in-house finder returned frame 31 —
matching the frame the user independently got from Pokefinder in a saved run.

Finding correction: Metang's Mountain threshold is **Peak score ≥ 56** (from the game data),
not the 24 an early web source suggested.
