# Adversarial review of `claytonlib/metronome_compass/effects.py`

Reviewed `effects.py` against `notes/refined/effects.md` and the turn simulator in
`claytonlib/metronome_compass/__init__.py`. All effects are *present*, but many
did not model state or RNG correctly. The unifying theme is exactly the one you
flagged: **secondary effects advance RNG but never mutate battle state**, so any
later move whose behavior depends on that state desyncs the RNG for the rest of
the path.

Why this is severe (not cosmetic): the Magikarp turn in `_simulate_magikarp_turn`
consumes **observable** rolls that depend on Magikarp's status —
`SLP`/`FRZ`/`PAR`/`LV` each roll and emit a token *every turn* the status is
active. If Flamethrower burns Magikarp but we don't record it, a later Thunder
Wave still "succeeds" in our sim (it should fail — target already statused),
consuming the wrong number of rolls, and every subsequent token is garbage.

Legend: **[FIXED]** = changed in this pass (code edited in `effects.py` /
`context.py`). **[TODO]** = documented here, left for you to decide/scope.

---

## Infrastructure changes (the "apply lambda" you suggested)

**[FIXED]** `BattleContext.effect_proc(chance, apply=None)` (`context.py`)
The roll always advances. On a proc, `apply()` (if given) mutates state and
returns whether the effect was **observable**; the `EffectProc` token is emitted
only when it was. This fixes two bugs at once:
1. The state now tracks what the secondary did.
2. A proc that rolls success but shows nothing (target already has a
   non-volatile status; freeze in sun) no longer emits a false `~` token.

**[FIXED]** New appliers in `effects.py`:
- `_status_applier(ctx, status, block_weather=None)` — sets a Magikarp
  non-volatile status if it currently has none (and, for freeze, if not blocked
  by weather). Returns observability.
- `_target_accuracy_applier(ctx)` — lowers Magikarp accuracy stage; returns
  `False` at the −6 floor (rolls but not observable, per the notes).

**[FIXED]** `hit_crit_or_miss` / `_hit_check` now compute the hit roll through
`BattleContext.effective_accuracy(base)`, which applies the Gen-IV
accuracy/evasion stage table, the ±6 clamp, and the 5/3 gravity multiplier.
Previously accuracy/evasion stages and gravity were **completely ignored** — so
tracking them (below) would have been inert.

---

## Secondary status not tracked  **[FIXED]**

Each of these now applies the status on proc via `_status_applier`:

| Effect | Move(s) | Status |
|---|---|---|
| 2 | Poison Sting, Sludge Bomb, Poison Jab… | Poison |
| 4 / 125 / 253 | Flamethrower / Flame Wheel / Flare Blitz | Burn |
| 5 | Ice Beam, Ice Punch, Powder Snow | Freeze |
| 6 / 262 | Thunderbolt, Body Slam / Volt Tackle | Paralyze |
| 200 | Blaze Kick (high-crit + burn) | Burn |
| 202 | Poison Fang | Poison |
| 209 | Poison Tail, Cross Poison (high-crit) | Poison |
| 152 | Thunder | Paralyze |
| 260 | Blizzard | Freeze (blocked in sun) |
| 77 | Twineedle (two procs, shared applier) | Poison |
| 273 / 274 / 275 | Fire / Ice / Thunder Fang | Burn / Freeze / Paralyze |

Notes:
- **Freeze (5, 260, 274)** was the worst offender: a frozen Magikarp can't move
  and rolls a thaw check (`SCFZ`/`FRZ`) every turn. Untracked = catastrophic
  desync.
- **Twineedle**: both poison rolls share one applier instance, so if the first
  lands poison the second correctly sees an existing status and emits no token.
- **Blizzard** only blocks freeze in sun (per the notes). See TODO on Ice
  Beam/Ice Fang in sun below.

## Secondary handlers refactored to take an `apply` arg **[FIXED]**
`_eff_damage_secondary`, `_eff_high_crit_secondary`, and
`_eff_damage_status_flinch` now accept `apply=None` and forward it to
`effect_proc`. Thin typed wrappers (`_eff_burn_secondary`, `_eff_freeze_secondary`,
`_eff_paralyze_secondary`, `_eff_poison_secondary`, `_eff_burn_highcrit`,
`_eff_poison_highcrit`, `_eff_fire_fang`, `_eff_ice_fang`, `_eff_thunder_fang`,
`_eff_accuracy_drop_secondary`) bind the applier and are wired into the registry.

---

## Evasion / accuracy tracking  **[FIXED]**

Previously no-ops; these move Magikarp's hit-rate levers, which now feed
`effective_accuracy`:

- **Effect 24 Sweet Scent** → `_eff_lower_target_evasion` (was `_eff_hit_only`).
  This is your example — it is no longer a no-op.
- **Effect 23 Sand Attack / Smoke Screen / Kinesis / Flash** →
  `_eff_lower_target_accuracy`.
- **Effect 73 Mud Slap / Muddy Water (secondary)** → `_eff_accuracy_drop_secondary`.
- **Effect 258 Defog** — already cleared hazards; now also lowers target evasion.
- **Effect 25 Haze** → `_eff_haze`, resets all four evasion/accuracy stages
  (Focus Energy is a volatile status, not a stage, so it is intentionally *not*
  cleared).

## Focus Energy crit stage  **[FIXED]**
**Effect 47** set the `user_focus_energy` boolean but never raised the crit
stage, and `hit_crit_or_miss` never read it — so every damaging move after Focus
Energy used the wrong crit modifier. Now sets `user_crit_stage = 2` and
`hit_crit_or_miss` adds it to the per-move crit stage.

## Status-curing moves  **[FIXED]**
- **Effect 217 Wake-Up Slap** (was plain `_eff_damage`) — on hit, cures
  Magikarp's sleep. If Metronome had put Magikarp to sleep, failing to clear it
  meant phantom `SLP` rolls afterward.
- **Effect 171 Smelling Salt** (was plain `_eff_damage`) — on hit, cures
  paralysis (removes the per-turn `PAR` roll).

## Moves that roll a hit check then always fail  **[FIXED]**
These were mapped to `_eff_hit_only`, which returns the hit result (reported
success **and** emitted a Hit/Miss token). Per the notes they always fail and the
hit check is not observable. Now `_eff_hit_then_fail`: consume one unobservable
roll, return `False`.
- **92 Snore, 246 Last Resort, 248 Sucker Punch, 234 Psycho Shift,
  222 Natural Gift.**
- **8 Dream Eater** (target-not-asleep branch) and **158 Fake Out** (turn ≥ 2
  branch) likewise now consume an *unobservable* roll instead of calling
  `_hit_check` (which emitted a bogus observable token).

Note on scope of the observability assumption: the safe reading (matching Snore's
explicit note) is that these show "But it failed!" rather than a miss animation,
so no token. If play-testing shows a miss *is* animated for any of them, that one
should emit a token instead — flagged for verification.

---

## TODO — found but not changed (need a decision or bigger refactor)

### High impact
1. **Effect 29 Multi-hit (`_eff_multi_hit`)** — three bugs plus a faint gate:
   - *Order*: the notes roll hit-count **first**, then C/D/H. The code does the
     hit check first, then `multi_hit()`. Wrong roll order → desync.
   - *Formula*: `context.multi_hit()` uses `roll % 20` with a 7/7/3/3 split. The
     notes specify `2 + RAND%4`, re-rolled once when the first result is 4/5
     (i.e. sometimes **two** rolls). Both the distribution and the number of
     rolls are wrong.
   - *Token model*: each hit should be its own token because Magikarp may faint
     mid-sequence, at which point the total count is **not** observable. Current
     emits a single `MultiHit(count)`.
   - *Faint gate*: because the count is unobservable once Magikarp faints, the
     interactive prompt must **first ask whether Magikarp fainted**, and only ask
     "how many hits?" when it survived. (When it fainted, we emit per-hit tokens
     up to the faint and stop — rolls after the faint are past the last
     observable event.)
2. **Effect 36 Tri Attack** — the leading `RAND % 3` picks burn/freeze/paralyze;
   the code discards it with `advance_unobservable(1)` and applies nothing. The
   applied status is observable and changes Magikarp's later turns
   (freeze/paralyze each add a per-turn roll), so it must be both tracked and
   encoded in the path. **Decided design:** add an optional `status` field to the
   `EffectProc` token, rendered `~<FRZ>` / `~<BRN>` / `~<PAR>` (angle brackets so
   it stays distinguishable from a bare `~` and from other tokens); a bare `~`
   (status `None`) is unchanged for every other move whose status is implied by
   the move number. Tri Attack can't ride the generic `effect_proc(chance,
   apply)` path — it needs its own `emit()` where `rng_to_token` reads the type
   roll + proc roll in `RngContext` and `input_to_token` parses the observed
   status in `InteractiveContext`.
3. **Effect 94 Mind Reader / Lock-On** — grants "cannot miss next turn" (and
   guaranteed OHKO). Mapped to `_eff_no_rolls_ok`; the guarantee is never
   applied, so the next move's hit roll can produce a Miss it never could. Needs
   a `lock_on` state flag consulted by `effective_accuracy`/OHKO.
4. **Semi-invulnerable charge turns** — Fly (155), Dig (256), Dive (255),
   Bounce (263), Shadow Force (272) make the user untargetable on turn 1, so
   Magikarp's attack that turn auto-misses. No state marks this, so the Magikarp
   turn during the charge desyncs. (Razor Wind 39, Sky Attack 75, Skull Bash
   145, Solar Beam 151 are *not* semi-invulnerable — those are fine.)
5. **Effect 37 Rest** — only restores HP; it must also put the **user** to sleep
   for a set duration (3 turns: the Rest turn plus two where Chansey can't act).
   This needs two pieces: (a) a user-sleep field in `MetronomeBattleState`, and
   (b) **path-harness support in `simulate_turn` for Chansey staying asleep** —
   on a sleep turn the metronome roll is skipped entirely (no move selected)
   while the sleep counter ticks, resuming normal metronome turns when it wakes.
   Until the harness supports this, Rest silently desyncs the rest of the path.

### Medium impact
6. **Effect 38 OHKO** — threshold hard-coded to `< 55`. It is
   `30 + userLevel − targetLevel`; needs real levels or it desyncs for any other
   matchup. Also should honor Lock-On (see #3).
7. **Track *all* stat stages (both sides), not just evasion/accuracy** — this is
   a correctness requirement for **token matching**, not a nicety: a stat
   secondary that procs while the stat is already at its −6/+6 cap shows no
   message, so it must emit **no** token. That applies to target-lowering
   secondaries (68–72, 197, 271) and user-raising ones (138 def, 139 atk,
   140 all-stats, 276 spatk, 204 spatk-2). Only accuracy (73) and evasion are
   tracked today; the rest always emit on proc, which will mismatch the observed
   path once a stat hits its cap. Extend `MetronomeBattleState` with the full
   stat-stage set for user and target and have each stat applier return
   observability from the cap check (same pattern as `_target_accuracy_applier`).
   Also wire these into `_eff_haze` (reset) and the swap/copy moves
   (Psych Up 143, Power/Guard/Heart Swap 243/244/250, Power Trick 238).
8. **Effect 161 Spit Up** — the crit roll is treated as unobservable
   (`advance_unobservable(1)`), but Spit Up can crit and that's observable. It
   can't reuse `hit_crit_or_miss` because it has no damage roll; needs a
   crit+hit (no damage) variant.
9. **Effect 213 Camouflage** — `_eff_no_rolls_ok`; should **fail** if the user is
   already Water type (e.g. used twice), and it changes `user_types` (matters for
   later Conversion / Conversion 2 eligibility).
10. **Effect 226 Acupressure** — the chosen stat is shown to the player
    (observable) and can be the user's evasion/accuracy. Currently one blind
    `advance_unobservable(1)` with no state change; eligible-stat count depends on
    current stages.
11. **Effect 250 Heart Swap** — per the notes, if it grants Magikarp evasion
    (after a Minimize) the path should end/Unsupported; currently a plain no-op.

### Low impact / verify
12. **Effect 135 Hidden Power** — should throw Unsupported when it connects with a
    **frozen** Magikarp (a Fire HP thaws). Reachable now that we track freeze.
13. **Effect 247 Worry Seed** — clears sleep/drowsy (good) but doesn't record
    that Magikarp has Insomnia, so a later sleep move would wrongly succeed.
14. **Ice Beam (5) / Ice Fang (274) in harsh sun** — the notes only assert
    "freeze impossible in sun" for Blizzard. If it's a general rule, add
    `block_weather='sunny'` to their appliers too. Left matching the notes.
15. **Duration prompts in interactive mode** (Encore 90, Disable 86, Taunt 175,
    Bind 42) — `emit()` asks the player for a number they can't observe at that
    moment. RNG-correct, but a UX/observability wart.
16. **Hit-then-fail observability** (92, 246, 248, 234, 222) — confirm these show
    "But it failed!" and not a miss animation; if any animates a miss, that one
    should emit a token instead of the current silent unobservable roll.
17. **General limitation**: Magikarp HP is untracked, so deterministic-KO moves
    (Dragon Rage 41, Sonic Boom 130, multi-hit) can't end the path on faint. This
    is an accepted P0 limitation, not a regression — noted for completeness.

### Resolved during review (no change needed)
- **Effect 28 Whirlwind / Roar** — confirmed 100 accuracy, so `_hit_check` is
  correct; not the always-hit `0` sentinel.
- **Effect 42 / 261 Bind duration** — confirmed `3 + RAND%3` is correct: the
  final turn frees Magikarp instead of dealing damage, so it takes binding damage
  on 2–4 of the 3–5 bound turns. Matches the `BindDmg`/`BindEnd` logic already in
  `simulate_turn`.

---

## Verification
- `python -m unittest discover -s tests` → **224 passed**.
- Precomputed 10-turn paths for 5,406 seeds with no exceptions, exercising the
  new handlers.
- Behavior for stage-free, gravity-free turns is unchanged (net stage 0 →
  `effective_accuracy(base) == base`), so existing precomputed paths are
  unaffected except where a status/stage is genuinely now in play.
