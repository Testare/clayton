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
- **The calendar/valid-times picker, the click-to-select saved-target picker, and
  especially the whole advance-frame guide** (Enter-to-commit Elm log, in-house
  target-frame search, the Preferences toggle, and the new block_config fields in
  Configure) — all brand new this session, none of it verified in a live window yet.

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
  B's delay and said you're still verifying it. Metronome Compass no longer has
  these fields at all (Feedback 3: not needed there); Safari Compass's Save Run
  modal still has them, now auto-filled from the advance-frame guide (see
  below) when you've planned a route, still editable, and `Run` stores them —
  but no calibration parameter fits them yet; this is purely data capture ahead
  of your analysis.
- **Safari Compass's "in-house" target-frame search isn't built** — the new
  advance-frame guide (Feedback 3, below) makes you paste in a target encounter
  frame from Pokefinder by hand; it doesn't compute which frame holds a given
  species itself the way `utils/safari_advance.py`'s `choose_target_frame` /
  `claytonlib.safari_encounters.iter_encounter_frames` can. Matches that
  module's own documented v1 scope, not a shortcut I invented — but flag if you
  want the in-house search built out.

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
  that one might matter there). Superseded in Feedback 3: Elm calls is gone
  too now — see below.
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

## Addressed this session (your "Feedback 3" notes)

Worked through `notes/clayton_v1_feedback.md`'s "Feedback 3" section (tracked as beads
`clayton-b42.5.1`–`.14`). Still **written blind** — add all of this to the "needs your
hands" list above — a few things worth flagging specifically:

- **Metronome New Run now remembers itself**: Roamer starting positions, ± seconds,
  ± delays, match-parity, and Save Run's Tag all persist per-expedition
  (`Expedition.last_metronome_defaults`) and prefill next time, instead of resetting
  every run. Dropped the "Samwise" placeholder and the *whole* Advance recipe section
  (Elm calls included — full removal this time, per your Feedback 3 note).
- **Roamer starting positions get the same invalid-input red outline as observed
  routes** — applied to both Metronome and Safari Compass, since it's the identical
  field/bug in both.
- **"Choose from saved target…"** button added to both New Run flows' Initial
  time/Vector ms section.
- **Safari Chart**: model name now shown in Compute chart (and Safari Compass's
  header); a chart's delay window can be edited after creation (safe — the canon
  map's signature doesn't include it); `chart_rank_at_time` — already fully
  implemented in the backend but never called from the UI — is now wired to a "Find
  best target at a specific time" button; Examine target's per-second table is
  clickable through to individual (frame, seed, hit, weight%) rows, matching the
  notebook's `chart_check_target_landing` detail (new `claytonlib.chart.scorer.
  seed_breakdown`, capped/centered at 400 rows so the bridge payload stays sane for
  a wide sigma).
- **Saved targets' P(capture) is frozen at save time; Examine always recomputes
  live** against whichever model is currently active — that was already true, just
  unlabeled before. Relabeled the column and added a note. No behavior change.
- **Seed B "no candidates" bug**: still couldn't reproduce it synthetically (wide
  M/time grid against the Standard model). Made the failure mode visible either way
  — inline error + loading state in the panel instead of a toast that's easy to miss.
- **New: Safari Compass advance-frame guide** (the big one) — after Seed A is
  identified, a new panel lets you (1) pin Seed A's own current advance frame from
  the Elm calls heard so far (prompts for more if ambiguous, exactly like Seed A's
  REL narrowing already does), then (2) enter a target encounter frame (from
  Pokefinder — v1 doesn't compute this in-house, see above) to get a chatot-flip +
  Elm-call route with a bracketed guide string (`EKPPK[PKE]!PPE`, `]!` = Sweet Scent
  here), flagging an ambiguous confirmation margin when the notebook's own
  `margin_ambiguous` check would. This is a **port** of `utils/safari_advance.py`'s
  pure math into `claytonlib/safari_advance.py` (new module) — I did NOT reinvent
  this from scratch, it's the same tested algorithm the notebooks already use for
  this exact purpose. The plan prefills Save Run's advance-recipe fields, and a new
  `Run.frame_guide` text field saves the full instructions with the run. This is by
  far the least-tested-by-you piece of this whole session — please look closely.
- **Full Seed B guide**: a "? full guide" button next to the compact legend opens
  the complete per-action table with the exact in-game message for each (reuses
  `claytonlib.compass._display`'s own cheatsheet data, so it can't drift from what
  the notebook prints).
- **Deferred, as you asked**: a "missed frame" recovery button + run-flagging stays
  as its own open bead (`clayton-b42.5.12`) — not built, per your "not an immediate
  priority."

## Addressed this session (your "Feedback 4" notes)

Worked through `notes/clayton_v1_feedback.md`'s "Feedback 4" section (tracked as beads
`clayton-b42.6.1`–`.13`, all closed). Still **written blind** — add all of this to the
"needs your hands" list above. Highlights and judgment calls:

- **Real bug**: Safari Compass's Roamer positions/±seconds/±delays/parity were never
  bound to state at all — they silently reverted to hardcoded defaults after every
  Generate, even though the search itself used whatever you'd typed. Fixed with the
  same persistence pattern Metronome got in Feedback 3 (new
  `Expedition.last_safari_compass_defaults`).
- **Calendar/valid-times picker**: added everywhere Initial-time is typed (both New
  Run pages, Find-best-target-at-time). Turned out `claytonlib.times.get_times`
  already had everything needed — the only real subtlety was that it stamps a
  nominal placeholder year (year never enters the seed math), so matching is by
  month/day and results are re-stamped with whatever year you actually pick.
- **Saved-target picker**: click a row to select it, one "Use this target" button
  at the bottom — no more hidden per-row buttons.
- **Metronome Seed B** now has its own ± seconds/± delays fields (the backend always
  accepted them independently of Seed A's; the UI just silently reused Seed A's
  window before).
- **Advance-frame guide**: dropped "(optional)"; Elm lookahead now matches the
  notebook's short window (~15 calls) instead of 300; the calls typed to narrow/pick
  Seed A auto-carry into frame identification; both the Elm-calls input and Safari
  Compass's Seed B path input are now Enter-to-commit with a persistent "so far" log
  instead of running a full query on every keystroke (this should also fix the
  input-losing-focus complaint from Feedback 1/2, since the element isn't recreated
  mid-keystroke anymore).
- **In-house target-frame search, the big one**: ported
  `choose_target_frame`'s in-house branch from `utils/safari_advance.py` into
  `claytonlib.safari_advance.find_in_house_frame` (block-config search via
  `claytonlib.safari_encounters` + the same ambiguous-margin skip logic, `aim_advance`
  support included). Added a Preferences toggle (Pokefinder vs. in-house) and
  `Expedition.block_config` fields in Configure (plains/forest/peak/water — this was
  scaffolded on the model already but had no UI). **Time-of-day is a plain dropdown
  in the guide itself, not derived from any clock** — I deliberately did not try to
  guess it from boot time, since HGSS's actual morning/day/night hour boundaries are
  a game-data fact I'd have been guessing at, not something already in this codebase.
  Flag if you'd rather it auto-derive from something.
- **Safari Chart**: sigma explained (tooltip + hint), Edit window's canon-map/
  signature mention dropped, Individual Seeds modal polished (capitalized heading,
  "ΔF" column, "Sum capture%" instead of the bad "Cum capture%", wider modal),
  find-best-target-at-time remembers its last input for the session (not persisted
  across restarts — a P3 nicety, didn't seem worth a new Expedition field).

## Addressed this session (your "Feedback 5" notes)

Worked through `notes/clayton_v1_feedback.md`'s "Feedback 5" section — the biggest batch
yet (beads `clayton-b42.7.1`–`.21`, all closed; `.22` is the block-table-aware ToD
filtering you explicitly deferred, left open on purpose). Still **written blind**. A few
things worth flagging specifically:

- **Real bugs found and fixed**: Seed B's new (Feedback-4) window defaulted to 10 delays
  instead of 2000; Calibrate Model showed dashes for the Standard model's active-column
  because it only read a field that a real fit populates, not the seeded model's own
  data; the exclude checkbox on an excluded run LOOKED disabled because the whole row
  (including the checkbox) got dimmed via opacity, even though it was always still
  togglable; and — while fixing the guide text you asked for — I found the path-
  character validator I added last round rejected `?`/`a`/`e`, which the backend fully
  supports and the guide itself documents.
- **Profile TID/SID → Trainer Name/Version**: confirmed via grep these were never read
  by any RNG/calibration math before removing them.
- **Time of day**: built the classifier and boundary constants you gave exactly
  (morning 4-9:59, day 10-19:59, night 20-3:59) and wired it into the advance-frame
  guide (auto-derives from the initial time, no more prompt). The "verify which ToDs
  actually work + filter + warn" piece needs block-table intelligence you said is
  future work — split into `clayton-b42.7.22` rather than build a filter with no real
  trigger condition yet.
- **Advance-frame guide got a substantial rework**: its own "Seed A advances" section
  gating Seed B, no confirm step (auto-plans once the frame resolves), an exact
  key-seed hit auto-uses your configured `key_seed_advances` with no search, Elm-call
  prefill instead of auto-commit, "Change" buttons on both the Elm log and Seed B's
  path log, an in-house target-frame search (ported from `utils/safari_advance.py`'s
  `choose_target_frame`), and a Machete-depth preference actually wired into Seed B's
  single-seed search (previously hardcoded to the library default with no way to
  configure it).
- **Seed B guide is now a side pane, not a blocking modal** — openSidePane has no
  backdrop, so the path input stays usable while the guide is open. A true
  repositionable OS window would need new pywebview multi-window plumbing; flag if you
  want that instead of the pane.
- **Widened Seed B's search window** is now available when a path eliminates every
  candidate — the backend already took `k`/`second_offsets` overrides, just had no UI.
- Safari Compass Review Data now has its own Tags tab, mirroring Metronome's.
- This is the least-tested-by-you surface in the app by a wide margin now (New Run's
  advance-frame section touches almost everything in Safari Compass) — please look
  closely, especially the auto-pilot frame resolution and the exact-key-seed-hit path.

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
