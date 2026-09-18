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

## Addressed this session (your "Feedback 2" notes)

Worked through `notes/clayton_v1_ui_improvements.md`'s "Feedback 2" section. Still
**written blind** like everything else — add these to the list above needing your
eyes — but a couple are worth flagging specifically:

- **Found a real bug behind "Build canon map… isn't working when I click it"**:
  the precompute progress-poll loop called a `sleep()` helper that appeared
  undefined by a literal grep for `sleep(` — but a `const sleep = (ms) => ...`
  actually already existed further down the file (my grep missed it: no `(`
  directly after the name). Adding a second `function sleep(ms){...}` created
  a duplicate top-level declaration — a `SyntaxError` that broke the ENTIRE
  script, not just the precompute loop. **This is what you actually hit**: the
  app stuck on the loading screen at launch, nothing running at all. Fixed by
  removing my duplicate (commit `f277412`) — verified this time with a real JS
  parser (`nix shell nixpkgs#nodejs`, previously unavailable to me) rather than
  grep, confirmed no other top-level name is declared twice, and confirmed
  top-level script execution completes without a runtime error. Sorry — this
  one shipped broken between your two messages. Please re-test app launch, and
  separately, still worth confirming the progress bar behaves during a real
  (non-trivial) chart compute once the app itself comes up.
- **Also found (not just guessed) the Safari Compass "no seeds in range" bug**:
  the candidate list only ever fetched on the path input's `oninput` — so it
  stayed empty until your first keystroke, independent of whether a calibration
  model existed. Now fetches the full candidate set (empty path) as soon as
  Seed A is picked. Added an explicit m/M/b/B/0-3/F/C/u legend too.
- **Renamed "canon map" → "Compute chart" / "computed data"** everywhere in
  Safari Chart (Find Target + Manage Data) — button/label text only, no
  internal names changed.
- **Criteria can now be parameterized** — "N Machete turns after M balls" and
  a generalized "survived N turns without fleeing" (was hardcoded to 10) both
  get number inputs in Create Chart. Added `n_turns_no_flee_criteria` to
  claytonlib + a regex case in `_resolve_criteria`; `machete-X-turns-after-Y-
  balls` and `N-balls-no-flee` were already resolvable, just not exposed in the
  UI. "Search from" now defaults to 180s.
- **Metronome Compass Save Run**: dropped the "Timer calibration" field and the
  Chatot-flips/Advance-frame inputs (kept Elm calls, per your note that only
  that one might matter there). Safari Compass's Save Run modal is untouched —
  you didn't flag it, and it may genuinely need those fields differently.
- **Replaced the jarring `confirm()` "Run saved. Start another run?"** with a
  proper modal (Done / Start another run) in **both** Metronome Compass and
  Safari Compass — your note only named Metronome, but it was the exact same
  code pattern and flaw in both places, so I fixed both rather than leaving
  Safari Compass with the bug I'd just diagnosed. Say if you wanted Safari
  Compass left alone.
- **New profiles now seed a "Standard" calibration model automatically**
  (active by default, model #1) — bundled into the app as
  `app/resources/standard_calibration_model.json`, a literal copy of this
  repo's own `data/calibration_model.json` per your instruction. This is your
  *real* fitted calibration data, now baked into the packaged app for every
  profile going forward — flag if that's not what you meant by "for now" (e.g.
  if you'd rather this be a placeholder/fixture instead of your actual
  numbers, or opt-in rather than automatic).
  **Follow-up bug you hit**: this only seeded on `create_profile`, so your
  existing profile (created before this landed) never got one — Safari Chart
  kept saying "no calibration model" even after the fix. `_resolve_calibration_
  models` (the one choke point every model lookup goes through) now self-heals:
  if a profile has zero calibration model docs at all, it seeds Standard right
  there before resolving, so any pre-existing profile picks it up the next
  time you open Find Target / New Run / anything else that needs a model — no
  need to delete and recreate your profile.

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
