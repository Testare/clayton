# Flagged for your review

Things I've called out across the app-build sessions that you haven't yet confirmed,
overridden, or addressed. Organized so you can triage quickly. Nothing here is
blocking — the app builds and the test suite passes — but each is a real gap or an
unverified claim worth your eyes.

## Needs your hands (I have no browser here)

Every UI change this whole build has been **written blind** — verified via facade
tests and manual precompute/rank runs against real data, never rendered in an actual
window. You've verified and fixed real bugs in the Metronome Compass New Run flow
already; everything since is still unverified:

- **Safari Chart** — Find Target, Create Chart modal, Examine target modal.
- **Calibrate Model** — the new Runs/Tags/Calibrate Model tabs in Review Data.
- The UI-improvements pass (emoji, Save Run modal, Seed A change/keep flow, Seed B
  transcript log) — you said you'd verify this "later."

## Known incomplete (by design, tracked in beads)

- **Tag weighting is on/off only**, not the continuous per-run multiplier draft2
  originally described. Theil-Sen (the trend fit `calibrate_timer` uses) has no
  principled way to take fractional weights without either a weighted-fit rewrite
  or a replication scheme — implementing one wasn't in scope for getting Chart
  unblocked. See `app/calibration.py`'s docstring. (`clayton-dxq.3`, closed with
  this noted as a deliberate deferral, not a bug.)
- **No staged Save/discard for exclusion edits** (`clayton-dxq.5`, open) — every
  exclude checkbox in Review Data (run or tag) applies immediately. The original
  design called for staging edits with an explicit Save and a Discard option.
- **Export doesn't prompt "include excluded runs?"** (`clayton-dxq.6`, open) and
  doesn't carry exclusion flags yet.
- **Safari Chart → Manage Data is still a placeholder** (`clayton-9z6.3`).
- **No fps_model picker in the Find Target UI** — always uses "linear"; "quad" is
  fit and stored but never selectable from the page.
- **No cooperative cancel on a running canon precompute** — once started, the
  background thread runs to completion regardless of what the UI does; "Rebuild"
  just starts tracking a new session. `precompute_canon` itself has no cancel hook.
- **Metronome-run provenance isn't tracked yet** — every saved run is treated as a
  clean fresh boot (`prior_battles=0`) when fed to the calibration fit, since the
  app doesn't yet ask about mid-boot battle history the way the notebook does.
- **Review Data's Runs table doesn't show which metronome user a run used** — the
  data (`metronome_user_id`) is there, just not surfaced in that table yet.

## Untested at real scale

- `chart_precompute_runner` defaults to `workers=1` (no process pool) — I called
  out that forking a pool from inside a pywebview process is untested territory
  and left it single-core rather than guess. Worth verifying if a real precompute
  (wide setup/max range) feels too slow.
- All chart/calibration tests use tiny synthetic ranges (seconds, not minutes) for
  speed. The pipeline is verified correct, not verified fast/practical at the size
  a real hunt's canon map would actually be.
- The Windows build (`packaging/`, GitHub Actions workflow) has never actually run
  — I can't cross-compile or test PyInstaller from this NixOS machine. First real
  signal comes from you running the Actions workflow.

## Cosmetic, likely fine to ignore

- **GStreamer plugin warning** (`libgstlame.so: undefined symbol`) on launch — a
  Nix store version mismatch in an audio codec plugin the app never uses. Judged
  harmless; not fixed.
- **Fontconfig warnings** ("invalid constant used: serif/sans-serif/...") on
  Linux launch — the bundled fontconfig reading newer named constants from your
  system `/etc/fonts` it doesn't recognize; fonts still resolve via fallback.
  Judged harmless; not fixed.

## Worth knowing, not a problem

- Saving a calibration model through the app's Calibrate Model page and the
  notebooks' own `update_calibration_model()` both still write/read
  `data/calibration_model.json` independently — no conflict, but if you use both
  workflows on the same profile, know that an app-saved *active* model takes
  precedence over that file the moment one exists (see
  `Facade._resolve_calibration_models`).
