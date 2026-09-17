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

- **Safari Chart** — Find Target, Create Chart modal, Examine target modal, and
  the new **Manage Data** page (canon-map/target tables, delete buttons).
- **Calibrate Model** — the Runs/Tags/Calibrate Model tabs in Review Data, now
  including the safari-offset fit and the saved-models Export/Import buttons.
- **Safari Compass** — New Run (shared Seed A, live path-narrowing Seed B, the
  bold-next-action Machete display) and Review Data (now with exclude/reason
  columns for safari runs, not just a record view).
- **Export/Import** — the "Export…"/"Import expedition…" buttons on the
  Profile and Expedition pages, the include-excluded-runs checkbox modal, and
  the two-step collision-resolution modals (new-copy vs. replace/merge).
- **Staged Save/Discard for exclusion edits** (`clayton-dxq.5`) — both Review
  Data pages' run and tag exclude checkboxes now stage into a dirty set (shown
  highlighted, with an "N unsaved change(s)" bar) instead of applying
  immediately; leaving the page or switching tabs with unsaved changes prompts
  a confirm. Delete is unaffected — that stays immediate, gated by its own
  confirm, since the bead was specifically about exclusion toggles.
- The UI-improvements pass (emoji, Save Run modal, Seed A change/keep flow, Seed B
  transcript log) — you said you'd verify this "later."

## Known incomplete (by design, tracked in beads)

- **Tag weighting is on/off only**, not the continuous per-run multiplier draft2
  originally described. Theil-Sen (the trend fit `calibrate_timer` uses) has no
  principled way to take fractional weights without either a weighted-fit rewrite
  or a replication scheme — implementing one wasn't in scope for getting Chart
  unblocked. See `app/calibration.py`'s docstring. (`clayton-dxq.3`, closed with
  this noted as a deliberate deferral, not a bug.)
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
- **Safari Compass's Jane offload isn't wired up** (draft2 already said Jane isn't
  an immediate priority) — typing `J` in the path field is silently ignored rather
  than switching to Jane, unlike the notebook's interactive `compass_safari()`.
- **Safari Compass has no widen/expand-window flow** — the notebook's interactive
  tool can widen the ±kσ search window or expand the frame range mid-narrowing
  when the observed path eliminates every candidate; the app's stateless version
  doesn't offer that yet (you'd need to go back and change the header/Seed A
  inputs and re-narrow by hand).
- **The advance-recipe fields (elm calls / chatot flips / advance frame) are
  captured but nothing fits them** — you flagged that these might affect Fb/Seed
  B's delay and said you're still verifying it. Both Save Run modals now have
  optional inputs for them and `Run` stores them, but no calibration parameter
  exists yet; this is purely data capture ahead of your analysis.

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

## Corrected this session

- **I was wrong that safari runs don't matter for calibration** — you corrected
  this: they fit the safari load-path offset (`safari_offset`), holding the
  metronome-fitted trend fixed. Fixed in both `claytonlib.calibration_tools`
  (`fit_safari_offset` gained the same `runs=`/`_run_id` treatment as
  `calibrate_timer`) and the app (Calibrate Model now fits both; Safari Compass
  Review Data now has exclude/reason columns, not just a record view). Worth a
  skeptical look since I built and tested this same-session, under correction —
  see the safari-offset math specifically in `preview_calibration`'s report.

## Worth knowing, not a problem

- Saving a calibration model through the app's Calibrate Model page and the
  notebooks' own `update_calibration_model()` both still write/read
  `data/calibration_model.json` independently — no conflict, but if you use both
  workflows on the same profile, know that an app-saved *active* model takes
  precedence over that file the moment one exists (see
  `Facade._resolve_calibration_models`).
