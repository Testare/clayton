# What's new — desktop app session

Built the Clayton desktop app (pywebview + `claytonlib`) far enough to run a full
Metronome Compass loop. All logic is unit-tested (**659 tests pass**); the **UI was
written blind** (headless session — couldn't render a window), so it needs your eyes.

## Run it
```bash
nix run .#clayton          # or: nix develop; python -m app.main
```

## Test checklist (in order)
1. **Profiles** → New profile (console/cartridge, TID/SID). Add a **metronome user**
   — watch the live warning box as you change species/moveset/lagging-tail.
2. **Expeditions** → New expedition (safari-area dropdown, hex-only/required key seed,
   chatots default 2). Open it → **Expedition Home** (tool grid) → **Configure** / **Preferences**.
3. **Metronome Compass → New Run**:
   - Header: pick user, initial time (ISO), Vector ms.
   - **Seed A**: roamer starting positions + window → **Generate** → narrow by
     observed REL / Elm (live table + key-seed readout) → click a row to identify.
   - **Seed B**: Magikarp level/gender → **Start narrowing** → answer the battle
     questions one at a time until one seed remains (this drives the real
     `narrow_candidates` on a background thread via an input callback).
   - **Save run** → appears in **Review Data**.
4. **Metronome Compass → Review Data**: runs table, tag filter, exclude toggle, delete.
5. **Profiles → Export bundle** / **Import…**: round-trips a profile + its
   expeditions + runs to/from a JSON file (imports as a fresh copy).

## Known caveats / not done yet
- UI unverified in a live window — report anything visually off.
- Seed A search uses `target_delay = key_seed & 0xFFFF` and `target_time = initial time`;
  confirm that's the right pairing for a real run.
- Only **one** narrowing session at a time (it monkeypatches `builtins.input`).
- Review Data is a first cut: no tag weighting / outlier flags / exclude-reason /
  explicit Save-changes yet (that's epic `clayton-dxq`).
- Export/import always imports as a copy (no replace-vs-merge / collision prompt yet);
  models aren't exported (none exist yet); no "include excluded runs?" prompt.
- Safari Compass, Safari Chart, and calibration/model-fit UI are still placeholders.

## Where things live
- `app/` — `store.py` (JSON persistence), `models.py` (Profile/MetronomeUser/Expedition/Run),
  `facade.py` (the js_api surface), `metronome.py` + `metronome_session.py` (seed ID),
  `portability.py` + `files.py` (export/import), `web/index.html` (the whole UI), `main.py`.
- `claytonlib/calibration_tools.py` — moved here from `utils/` so it's packaged;
  `narrow_candidates` now takes `input_fn`/`output_fn`.
- Beads: epic `clayton-b42` mirrors this; `bd ready` for what's next.
