# Metronome effect token table

Catalogue of every entry in `EFFECT_HANDLERS`
(`claytonlib/metronome_compass/effects.py`), classifying each by observability
and path-token coverage. This is the source-of-truth table for two epics:

- **clayton-ckb** — every *observable random* effect must emit a token.
- **clayton-8vn** — the interactive context must be able to reproduce every path.

## How to read the columns

**Observable** — can the player see the outcome, and *when*?
- `Immediate` — visible the moment it resolves (hit/miss/crit, a secondary
  proc message, Magnitude level, a stat drop, a type change).
- `Later` — the *application* is hidden (e.g. a duration roll shows no number),
  but a downstream moment is observable (a status wears off, a bound Pokémon
  takes end-of-turn damage, a drowsy Pokémon falls asleep, confusion snaps).
  The RNG advance still happens at application; only its *consequence* is what
  the player reads later.
- `Never` — rolls the RNG but produces nothing the player can distinguish
  (flinch roll while moving second, Tri Attack's status-type roll, the
  unobservable damage roll inside a crit/damage/hit triple).
- `Deterministic` — observable message but **no RNG** (plain stat boosts, field
  screens, weather, hazards). No token needed: it never discriminates seeds.

**Has token** — the `PathToken` (see `path.py`) that captures the observable
outcome, or `—` when none exists, or `N/A` for deterministic effects that need
none. Duration rolls (Disable/Encore/Sleep/Bind/Confusion/Thrash) advance an
*observable* RNG call but `emit()` returns a plain `int`, so **no token is
appended** — the number is unobservable at apply time; the wear-off token
covers it.

**Interactively verified** — has the effect been confirmed reproducible through
`InteractiveContext`? This is the first catalogue, so every row is `☐` (pending,
tracked by clayton-8vn). Rows flagged ⚠ have a *known* interactive concern
(they prompt the player for something not visible at that moment) — see
[Interactive gaps](#interactive-gaps-feeds-clayton-8vn).

Shared token producers: `hit_crit_or_miss()` → `Hit`/`Miss`/`Crit`;
`_hit_check()` → `Hit`/`Miss`; `effect_proc()`/`effect_proc(apply)` → `EffectProc`.

**Sources:** cross-checked against `notes/refined/effect_status.md` (status-check
order, duration formulas, which effects want wear-off tokens) and
`notes/refined/branching_paths.md` (HP-dependent failure → Unsupported).

---

## 1. Standard damage — crit / damage / hit

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 0,3,17,34,78,81,99,101,103,119,121,123,128,129,147,149,169,182,185,186,188,190,196,203,207,218,219,221,224,229,230,231,235,237,245,257,268 | `_eff_damage` | Standard damaging move (Pound, Surf, Earthquake, …). Swift/Vital Throw/Trump Card have acc 0 → always hit. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 43 | `_eff_high_crit` | Karate Chop / Slash — raised crit stage, same roll count. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 48,198,269 | `_eff_recoil` | Take Down / Double-Edge / Head Smash — recoil on hit (recoil itself deterministic). | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 45 | `_eff_recoil_crash` | Jump Kick / Hi Jump Kick — crash damage **on miss** (deterministic given Miss). | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 44 | `_eff_double_hit` | Double Kick / Bonemerang — first hit C/D/H observable, second hit rolls unobservably. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 104 | `_eff_triple_kick` | Triple Kick — escalating per-hit rolls. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 80 | `_eff_hyper_beam` | Hyper Beam / Blast Burn — damage, then forced recharge next turn (deterministic). | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 87 | `_eff_seismic_toss` | Seismic Toss / Night Shade — fixed damage, hit check only (no crit/damage roll). | Immediate | `Hit`/`Miss` | ☐ |
| 88 | `_eff_psywave` | Psywave — damage roll + hit check. | Immediate | `Hit`/`Miss` | ☐ |
| 135 | `_eff_hidden_power` | Hidden Power — damage; ends path (Unsupported) vs a frozen target (Fire HP would thaw). | Immediate | `Hit`/`Miss`/`Crit`, else `Unsupported`+`PathEnd` | ☐ |
| 171,217 | `_eff_smelling_salt`,`_eff_wake_up_slap` | Damage + cure target status (paralysis / sleep) — cure deterministic. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 173 | `_eff_nature_power` | Nature Power → Hydro Pump (acc 80) vs Magikarp. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 8 | `_eff_dream_eater` | Dream Eater — damage only if target asleep. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 7 | `_eff_selfdestruct` | Selfdestruct / Explosion — C/D/H then user faints → path ends. | Immediate | `Hit`/`Miss`/`Crit` + `PathEnd` | ☐ |

## 2. Fixed-damage & OHKO — hit check only

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 40,41,130 | `_eff_fixed_damage` | Super Fang / Dragon Rage / Sonic Boom — hit check, fixed damage, no crit. | Immediate | `Hit`/`Miss` | ☐ |
| 38 | `_eff_ohko` | OHKO (Fissure/Guillotine/Sheer Cold) — fails if user level < target; special threshold. | Immediate | `Hit`/`Miss` | ☐ |

## 3. Damage + observable secondary proc

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 2,202 | `_eff_poison_secondary` | Damage + chance to poison. Proc rolls even if it can't land (status already present) — token only when it lands. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 4,125 | `_eff_burn_secondary` | Damage + chance to burn. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 5 | `_eff_freeze_secondary` | Damage + chance to freeze. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 6 | `_eff_paralyze_secondary` | Damage + chance to paralyze. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 68,69,70,71,72,197 | `_eff_target_*_minus1` | Damage + chance to drop a target stat one stage (Aurora Beam, Crunch, …). | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 271 | `_eff_target_spdef_minus2` | Seed Flare — damage + chance to drop target Sp.Def two stages. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 73 | `_eff_accuracy_drop_secondary` | Mud-Slap / Muddy Water — damage + chance to drop target accuracy. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 138,139,276 | `_eff_user_*_plus_secondary` | Steel Wing / Metal Claw / Charge Beam — damage + chance to raise a user stat. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 204 | `_eff_user_spatk_minus2` | Overheat / Psycho Boost — damage + guaranteed user Sp.Atk −2. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 140 | `_eff_user_all_stats_plus1` | Ancient Power / Silver Wind / Ominous Wind — damage + 10% raise **five** main stats (not acc/eva — decomp `subscript_0119`). | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 36 | `_eff_tri_attack` | Damage + 20% status; status *type* chosen by an unobservable roll, then proc. | Immediate + proc; type roll Never | `Hit`/`Miss`/`Crit`, `EffectProc(status)` | ☐ |
| 152 | `_eff_thunder` | Thunder — acc varies by weather; + paralyze secondary. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 260 | `_eff_blizzard` | Blizzard — acc 100 in hail; + freeze secondary. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 77 | `_eff_twineedle` | Twineedle — two hits + poison chance. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 126 | `_eff_magnitude` | Magnitude — random power level 4–10 (observable), then C/D/H. | Immediate | `Magnitude(level)`, `Hit`/`Miss`/`Crit` | ☐ |
| 200 | `_eff_burn_highcrit` | Blaze Kick — high crit + burn chance. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 209 | `_eff_poison_highcrit` | Poison Tail / Cross Poison — high crit + poison chance. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 154 | `_eff_beat_up` | Beat Up — first attacker C/D/H observable; remaining party members roll unobservably (party assumed 6). | Immediate (first) | `Hit`/`Miss`/`Crit` | ☐ |
| 253 | `_eff_flare_blitz` | Flare Blitz — recoil on hit + burn secondary. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |
| 262 | `_eff_volt_tackle` | Volt Tackle — recoil on hit + paralyze secondary. | Immediate + proc | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |

## 4. Damage + flinch (flinch unobservable — user moves second)

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 31,146,150 | `_eff_damage_flinch` | Rolling Kick / Twister / Stomp — flinch roll consumed but never observable (we move second). | Immediate; flinch Never | `Hit`/`Miss`/`Crit` | ☐ |
| 273,274,275 | `_eff_fire_fang`/`_eff_ice_fang`/`_eff_thunder_fang` | Fang moves — burn/freeze/paralyze secondary (observable) + flinch (unobservable). | Immediate + proc; flinch Never | `Hit`/`Miss`/`Crit`, `EffectProc` | ☐ |

## 5. Multi-hit

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 29 | `_eff_multi_hit` | Double Slap / Fury Swipes etc. — hit-count rolled unobservably; each landed hit shows C/D/H. | Immediate (per hit) | `Hit`/`Miss`/`Crit` per hit | ☐ |

## 6. Binding

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 42,261 | `_eff_bind` | Bind / Wrap / Whirlpool / Fire Spin … — hit check; hidden duration. | Immediate (hit) + Later (BindDmg/BindEnd) | `Hit`/`Miss`; end-of-turn `BindDmg`/`BindEnd` | ☐ (impl) |

## 7. Status-on-hit (non-volatile)

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 1 | `_eff_sleep` | Sleep-inducing (Spore/Hypnosis) — hit check; hidden duration. Wake is self-evident from any action, so no wear-off token — just `SLP` while asleep. | Immediate (hit) + Later (wake) | `Hit`/`Miss`; per-turn `SLP` | ☐ (impl) |
| 33,66 | `_eff_poison_hit` | Toxic / Poison Powder — hit check; poison shown later via end-of-turn damage. | Immediate (hit) + Later | `Hit`/`Miss` | ☐ |
| 167 | `_eff_will_o_wisp` | Will-O-Wisp — hit check; burn shown later. | Immediate (hit) + Later | `Hit`/`Miss` | ☐ |
| 67 | `_eff_paralyze` | Thunder Wave / Stun Spore / Glare — hit check; paralysis shown later (full-para / speed). | Immediate (hit) + Later | `Hit`/`Miss` | ☐ |

## 8. Confusion

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 49 | `_eff_confuse_hit` | Confuse Ray / Supersonic / Sweet Kiss — hit check; hidden duration. Each Magikarp turn resolves snap-out (`SCFZ`) / hit-self (`CFZ`) / attacked (no token) via `confusion_outcome`. | Immediate (hit) + Later | `Hit`/`Miss`; `CFZ`/`SCFZ` | ☐ (impl) |
| 76 | `_eff_damage_confuse` | Psybeam / Water Pulse — damage + confuse proc; hidden duration resolved per turn (`SCFZ`/`CFZ`/none). | Immediate + proc + Later | `Hit`/`Miss`/`Crit`, `EffectProc`; `CFZ`/`SCFZ` | ☐ (impl) |
| 118,166,199 | `_eff_swagger`/`_eff_flatter`/`_eff_teeter_dance` | Raise target stat(s) + confuse (if not already); confusion resolved per turn (`SCFZ`/`CFZ`/none). | Immediate (hit) + Later | `Hit`/`Miss`; `CFZ`/`SCFZ` | ☐ (impl) |

## 9. Disable / Taunt / Gravity / Encore & lockout statuses

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 86 | `_eff_disable` | Disable — hit check; duration hidden; blocks a Magikarp move (Prevented) and wears off observably. | Immediate (hit) + Later | `Hit`/`Miss`; `Prevented`; `StatusEnd("DIS")` | ☐ (impl) |
| 175 | `_eff_taunt` | Taunt — hit check; blocks status moves; wears off observably. | Immediate (hit) + Later | `Hit`/`Miss`; `Prevented`; `StatusEnd("TAUNT")` | ☐ (impl) |
| 215 | `_eff_gravity` | Gravity — field; boosts accuracy (deterministic), grounds/blocks some moves. Duration always 5 turns, so per `effect_status.md` no wear-off token is *needed* (code still emits `StatusEnd("GRV")` harmlessly). | Deterministic | `Prevented` (wear-off token optional) | ☐ |
| 90 | `_eff_encore` | Encore — hit check; duration hidden; forces Magikarp to repeat its move. | Immediate (hit) + Later | `Hit`/`Miss`; `StatusEnd("ENC")` | ☐ (impl) |
| 84 | `_eff_leech_seed` | Leech Seed — hit check; drains at end of turn. | Immediate (hit) + Later | `Hit`/`Miss` | ☐ |
| 107 | `_eff_nightmare` | Nightmare — hit check; end-of-turn damage while asleep. | Immediate (hit) + Later | `Hit`/`Miss` | ☐ |
| 165 | `_eff_torment` | Torment — hit check; bars repeated moves. | Immediate (hit) | `Hit`/`Miss` | ☐ |
| 106 | `_eff_spider_web` | Spider Web / Mean Look — hit check; traps. | Immediate (hit) | `Hit`/`Miss` | ☐ |
| 232,236,239,247,265 | `_eff_embargo`/`_eff_heal_block`/`_eff_gastro_acid`/`_eff_worry_seed`/`_eff_captivate` | Misc lockouts — hit check + deterministic state change. | Immediate (hit) | `Hit`/`Miss` | ☐ |

## 10. Attract & Yawn

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 120 | `_eff_attract` | Attract — hit check; infatuation may immobilize Magikarp later. | Immediate (hit) + Later | `Hit`/`Miss`; later `LV` | ☐ |
| 187 | `_eff_yawn` | Yawn — no hit roll; sets drowsy, sleep applied at end of a later turn. | Later | `DrowsySlept` | ☐ |

## 11. Hit-check-only stat / utility moves

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 18,19,20,23,24,58,59,60,62,205 | `_eff_growl`/`_eff_leer`/`_eff_string_shot`/`_eff_lower_target_accuracy`/`_eff_lower_target_evasion`/`_eff_charm`/`_eff_screech`/`_eff_scary_face`/`_eff_fake_tears`/`_eff_tickle` | Lower target stat(s) after a hit check; stat change deterministic. | Immediate (hit) | `Hit`/`Miss` | ☐ |
| 100 | `_eff_hit_only` | Spite — hit check, PP effect (no state we model). | Immediate (hit) | `Hit`/`Miss` | ☐ |
| 92,222,234,246,248 | `_eff_hit_then_fail` | Snore / Natural Gift / Psycho Shift / Last Resort / Sucker Punch — hit check, then always fails in P0. | Immediate (hit) | `Hit` then fail | ☐ |
| 168 | `_eff_memento` | Memento — user faints, lowers target stats. | Immediate (hit) + `PathEnd`? | `Hit`/`Miss` | ☐ |
| 227 | `_eff_metal_burst` | Metal Burst — hit check; fails if no damage taken this turn (simplified). | Immediate (hit) | `Hit`/`Miss` | ☐ |

## 12. No-roll success — stat boosts, field, weather, hazards (deterministic)

Observable messages but **no RNG** → no token required. All `☐` for interactive
(they should replay trivially, but must still be exercised).

| Effects | Handlers | Description | Observable | Has token |
|---|---|---|---|---|
| 10,11,13,16,50,51,52,53,54,108,109,143,156,174,206,208,211,212,238,243,244,178,191 | `_eff_meditate`,`_eff_harden`,`_eff_growth`,`_eff_double_team`,`_eff_swords_dance`,`_eff_barrier`,`_eff_agility`,`_eff_nasty_plot`,`_eff_amnesia`,`_eff_minimize`,`_eff_curse_stat`,`_eff_psych_up`,`_eff_defense_curl`,`_eff_charge`,`_eff_cosmic_power`,`_eff_bulk_up`,`_eff_calm_mind`,`_eff_dragon_dance`,`_eff_power_trick`,`_eff_power_swap`,`_eff_guard_swap`,`_eff_role_play`,`_eff_skill_swap` | User stat boosts, stat/ability swaps, Psych Up copy. | Deterministic | N/A |
| 25 | `_eff_haze` | Reset all stat stages. | Deterministic | N/A |
| 35,46,65,124,225,240,259 | `_eff_light_screen`,`_eff_mist`,`_eff_reflect`,`_eff_safeguard`,`_eff_tailwind`,`_eff_lucky_chant`,`_eff_trick_room` | Field screens/effects (turn-counted). | Deterministic | N/A |
| 115,136,137,164 | `_eff_sandstorm`,`_eff_rain_dance`,`_eff_sunny_day`,`_eff_hail` | Weather setters. | Deterministic (weather residual observable later) | N/A |
| 112,249,266 | `_eff_spikes`,`_eff_toxic_spikes`,`_eff_stealth_rock` | Entry hazards (no effect vs a wild single). | Deterministic | N/A |
| 181,201,210,251,252,258 | `_eff_ingrain`,`_eff_mud_sport`,`_eff_water_sport`,`_eff_aqua_ring`,`_eff_magnet_rise`,`_eff_defog` | Misc field/self effects. | Deterministic | N/A |
| 47,94,102,113,179,194,216 | `_eff_focus_energy`,`_eff_lock_on`,`_eff_no_rolls_ok` (Heal Bell/Foresight/Wish/Grudge/Miracle Eye) | Guaranteed-success utility. | Deterministic | N/A |
| 213 | `_eff_camouflage` | Become Water type (Safari env). Type shown but no roll. | Deterministic | — (no type token) |
| 250 | `_eff_heart_swap` | Swap all stat stages; ends path (Unsupported) if Magikarp would gain evasion. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` |
| 156→ etc | — | (Defense Curl also primes Rollout.) | Deterministic | N/A |

## 13. No-roll, may fail (HP / precondition dependent)

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 32,132,214 | `_eff_recovery` | Recover / Softboiled / Morning Sun / Roost — fails at full HP; **Unsupported** when HP unprovable. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` (ambiguous HP) | ☐ |
| 37 | `_eff_rest` | Rest — sleep + full heal; HP-precondition. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` | ☐ |
| 142 | `_eff_belly_drum` | Belly Drum — needs ≥50% HP; Unsupported when unprovable. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` | ☐ |
| 79 | `_eff_substitute` | Substitute — needs >25% HP; Unsupported when unprovable. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` | ☐ |
| 160,162 | `_eff_stockpile`,`_eff_swallow` | Stockpile / Swallow — stockpile count; Swallow HP-precondition. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` | ☐ |
| 91 | `_eff_pain_split` | Pain Split — averages HP; HP-knowledge dependent. | Deterministic / else `Unsupported` | `Unsupported`+`PathEnd` | ☐ |
| 161 | `_eff_spit_up` | Spit Up — fails at 0 stockpile; else crit + hit (no damage roll). | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 85 | `_eff_splash` | Splash — always "But nothing happened!". | Deterministic | N/A | ☐ |
| 114 | `_eff_perish_song` | Perish Song — sets 3-turn countdown for both. | Deterministic + Later (faint) | N/A | ☐ |
| 183,184,192,193 | `_eff_no_rolls_fail` | Magic Coat / Recycle / Imprison / Refresh — always fail in P0. | Deterministic | N/A | ☐ |
| 226 | `_eff_acupressure` | Acupressure — randomly picks an eligible stat to raise +2. | Immediate | `EffectProc` (selected stat) | ☐ |

## 14. Path-ending moves

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 28 | `_eff_whirlwind` | Whirlwind / Roar — ends the wild battle. | Immediate | `PathEnd` | ☐ |
| 153 | `_eff_teleport` | Teleport — user flees; battle over. | Immediate | `PathEnd` | ☐ |
| 127 | `_eff_baton_pass` | Baton Pass — no party to switch; ends path. | Immediate | `PathEnd` | ☐ |
| 220,270 | `_eff_healing_wish`,`_eff_lunar_dance` | User faints, requires a switch; ends path. | Immediate | `PathEnd` | ☐ |
| 228 | `_eff_u_turn` | U-turn — damage (C/D/H) then switch; ends path. | Immediate | `Hit`/`Miss`/`Crit` + `PathEnd` | ☐ |
| 233 | `_eff_fling` | Fling — hurls held item; C/D/H then path-relevant end. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |

## 15. Context-dependent

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 122 | `_eff_present` | Present — roll picks damage-vs-heal mode (observable), then C/D/H or heal (heal fails at full target HP → Unsupported when unprovable). | Immediate | `Hit`/`Miss` (mode), `Hit`/`Miss`/`Crit` (damage) | ☐ |
| 158 | `_eff_fake_out` | Fake Out — only on the user's first turn; C/D/H + flinch. | Immediate; flinch Never | `Hit`/`Miss`/`Crit` | ☐ |

## 16. Multi-turn / locked (charge & rampage) moves

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 39,155,255,256,272 | `_eff_charge_fire` | Razor Wind / Fly / Dive / Dig / Shadow Force — charge turn then release C/D/H. | Immediate (on release) | `Hit`/`Miss`/`Crit` | ☐ |
| 75,145,263 | `_eff_sky_attack`,`_eff_skull_bash`,`_eff_bounce` | Two-turn charge attacks. | Immediate (on release) | `Hit`/`Miss`/`Crit` | ☐ |
| 151 | `_eff_solar_beam` | Solar Beam — one-turn in sun, else charges. | Immediate (on release) | `Hit`/`Miss`/`Crit` | ☐ |
| 117 | `_eff_rollout` | Rollout / Ice Ball — locked; a miss ends the lock early. | Immediate | `Hit`/`Miss`/`Crit` | ☐ |
| 27 | `_eff_thrash` | Thrash / Outrage / Petal Dance — rampage; hidden total-turns; confusion at end. No end token (Metronome resuming + confusion show it ended); interactive confirms via `confirm_lock_end`. | Immediate + Later | `Hit`/`Miss`/`Crit`; then `SCFZ`/`CFZ` | ☐ (impl) |
| 159 | `_eff_uproar` | Uproar — hidden multi-turn lock (2–5 extra); prevents sleep. Interactive observes the end via `confirm_lock_end`. | Immediate + Later | `Hit`/`Miss`/`Crit` | ☐ (impl) |
| 148 | `_eff_future_sight` | Future Sight / Doom Desire — sets a delayed hit that fires (and rolls to hit) a later turn. | Later (fires) | `Hit`/`Miss` at fire; else `Unsupported`+`PathEnd` | ☐ |

## 17. Bide & Conversion

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 26 | `_eff_bide` | Bide — stores damage two turns then releases; ends path (Unsupported) where unmodellable. | Later | `Unsupported`+`PathEnd` | ☐ |
| 30 | `_eff_conversion` | Conversion — become one of the user's move types; fails if all match current type. | Immediate | `ConversionType` | ☐ |
| 93 | `_eff_conversion2` | Conversion 2 — become a type resisting the last move that landed; fails if none recorded. | Immediate | `ConversionType` | ☐ |

## 18. Explicitly unsupported

| Effects | Handler | Description | Observable | Has token | Int. verified |
|---|---|---|---|---|---|
| 57,189 | `_eff_unsupported` | Transform (Chansey loses Metronome) & Endeavor (always fails in P0). Also the fallback for any unmapped effect. | — | `Unsupported`+`PathEnd` | ☐ |

---

## Interactive gaps (feeds clayton-8vn)

Rows flagged ⚠ share one problem: `InteractiveContext` used to ask the player
for a value they **cannot observe at that moment**. The RNG-mode duration/total
rolls emit a plain `int` (no path token); the fix is to emit no token at apply
and confirm the wear-off later, so both contexts produce identical paths.

**Implemented (clayton-xk7):** Disable, Taunt, Encore use
`ctx.roll_hidden_duration(min, max)` at apply (RNG rolls the real value; interactive
tracks the max, no prompt) and `ctx.hidden_status_ends(label, remaining, min, max)`
at end of turn (RNG ends on the rolled turn; interactive forces no-end before the
minimum, forces end at the maximum, and prompts "did it wear off?" in between).
The `StatusEnd` token is emitted at the confirmed wear-off, never at apply.

**Implemented (clayton-1sn):** the same deferral, adapted to each observable moment —
- **Sleep** (2–5): no wear-off token; `hidden_status_ends` decides the wake turn
  (interactive confirms it, since any Magikarp action makes waking self-evident).
- **Binding** (3–5): `hidden_status_ends` picks `BindDmg` (still bound) vs `BindEnd`
  (broke free) at end of turn.
- **Confusion** (Magikarp, 2–5): `ctx.confusion_outcome(...)` resolves the turn as
  snap-out (`SCFZ`), hit-self (`CFZ`), or attacked-through (no token). Interactive
  prompts these three directly; snapping is only offered inside the min–max window.
- **Rampage** (Thrash/Outrage/Petal Dance): the `RampageEnd`/`REND` token was
  **removed** — resuming Metronome next turn shows it ended, and the ensuing
  confusion (`SCFZ`/`CFZ`) is the real observable.

**Implemented (clayton-rs1):** hidden-length locks and the Chansey confusion split.
- **Rampage total turns** (Thrash/Outrage/Petal Dance, 2–3) and **Uproar** (2–5 extra)
  use `ctx.roll_hidden_duration` at apply (no prompt). At the end of each continuation
  turn, inside the possible-end window, `ctx.confirm_lock_end(label)` lets interactive
  observe the stop (Metronome resuming / confusion). RNG never forces early — its
  counter is authoritative; the maximum is handled by the counter reaching 0.
- **Chansey's rampage-end confusion** now routes through `confusion_outcome` at both
  sites (locked and unlocked), and `_apply_confusion` / `_apply_user_confusion` defer
  their duration.

**Confusion mechanic — single snap-first rule (corrected):** both Magikarp
(move-inflicted) and Chansey (rampage fatigue) confusion are **snap-first**: a
duration-N confusion rolls the self-hit check on N−1 turns, then on turn N snaps
out with **no** roll ("snapped out of confusion!"). Verified against ground truth
(0xE3623EF0: turn 6 is still "is confused!" → attacked through; the snap is turn 7).
An earlier attempt treated Chansey as "roll-first" — that was a mis-diagnosis of a
**counter off-by-one**: Chansey's fatigue confusion was rolled as `1 + RAND%4` but is
actually `2 + RAND%4` (2-5 turns, like move confusion). `roll-first(1+R)` is
RNG-identical to `snap-first(2+R)` (same advances) but emits the `SCFZ` a turn early;
fixing the counter makes snap-first correct *and* keeps all 442 paths byte-identical.
`confusion_outcome` is now a single snap-first rule (no per-source parameter).

**Still deferred (charge/recharge):** Fly/Dig/Solar Beam/etc. and Hyper Beam recharge
have **fixed** lock lengths (1 continuation / 1 recharge), so interactive already knows
the release turn — no hidden-length prompt needed. Rollout's fixed length (4) can end
early only on an observable miss. No further work required there.

## Coverage summary

- **Damage / secondary / hit-check moves** — fully tokenised (`Hit`/`Miss`/`Crit`,
  `EffectProc`, `Magnitude`). No gaps.
- **Later-observable statuses** — tokenised at the observable moment
  (`StatusEnd`, `BindDmg`/`BindEnd`, `DrowsySlept`, `CFZ`/`SCFZ`, `LV`,
  `RampageEnd`, `Prevented`). No missing tokens found for RNG-driven outcomes.
- **Deterministic effects** — intentionally untokenised (no seed discrimination).
- **Possible token gap:** Camouflage (213) changes the user's type but emits no
  `ConversionType`; it is deterministic so it doesn't break seed-matching, but
  for display parity it could reuse the type token. Flag for clayton-ckb review.
- **Interactive gaps:** the hidden-duration prompts listed above (clayton-8vn).
