# Replaying three emulator logs of the Ho-Oh run against the simulator

> **Status:** the bug in section 3 is **fixed** (`clayton-957.10.14`), and all three runs now
> replay with **zero** mismatching turns. The replay is a permanent test:
> `tests/test_battle_compass_ground_truth_hooh.py`. Sections 4 and 5 are unchanged and still
> open — `clayton-957.10.15` (held items) and `clayton-avk` (the recorder does not log item use).

Three forced-seed runs
(`data/battle_logs/hooh1.jsonl`, `hooh2`, `hooh3`) were replayed through
`battle_compass.sim.simulate_turn`, feeding it the action read off each turn's messages and
diffing the result against the emulator on four axes: **rolls spent**, **HP on both sides**,
**which move Ho-Oh chose**, and **how each move resolved** (hit / crit / miss / fully paralyzed /
secondary / Static / shake count).

| | hooh1 | hooh2 | hooh3 |
|---|---|---|---|
| forced seed | `0xdd0e3043` | `0x100e2b27` | `0x100e2bd5` |
| rolls logged | 911 | 465 | 404 |
| turns | 57 | 28 | 23 |
| ball throws | 18 | 2 | 1 |
| mismatching turns, as found | 0 | 0 | 1 |
| **mismatching turns now** | **0** | **0** | **0** |

That is **1,780 RNG calls and 108 turns**, with one discrepancy — and it is a real bug, described
in section 3. Everything in section 2 is a confirmation; sections 4 and 5 are the two things the
comparison could *not* settle and the configuration hazard it exposed.

The harness is `one-offs/hooh_log_replay.py` (and `one-offs/battle_log_rolls.py` to dump a log's
rolls in order), so every number here is re-checkable:

```
PYTHONPATH=. python one-offs/hooh_log_replay.py data/battle_logs/hooh1.jsonl
```

Turning it into a permanent ground-truth test alongside `test_battle_compass_ground_truth.py` is
the obvious follow-up and is deliberately not done here.

---

## 1. The logs are our stream, exactly

The first thing to establish, because every other comparison depends on it:

```
advance_rng iterated from the forced seed, matched against the logged roll values, in order
  hooh1   911/911      hooh2   465/465      hooh3   404/404
```

Not one gap, not one reorder. Three facts fall out of that:

* **`BATTLE_START_ADVANCES = 6` is confirmed for Ho-Oh at the Bell Tower**, in all three runs —
  a *different encounter* from the Suicune run it was measured on. The breakdown the logs show is
  **4 at `bellShimmerReplaceGraphics` (`0x02251056`) + 2 at `ov12_022585B8` (`0x02258606`)**,
  which is the attribution `notes/battle_compass_next_targets.md` flagged as doubtful. The doubt
  was about whether the symbol lookup had drifted onto a neighbour; the count itself is right
  here, whatever the first four belong to.
* **Every turn opens with the wild Pokemon's move-choice roll at `0x0225e46e`**, before
  `BattleControllerPlayer_BeforeTurn`'s four. This is `sim.select_target_move`, and our model
  already spends it. It also makes a clean turn delimiter: the rolls between two consecutive
  `0x0225e46e` calls are exactly one turn's cost, which is how this replay segmented the logs
  (the message stream is useless for it — the number of "What will X do?" prompts depends on how
  the player navigated the menu).
* The roll sites worth knowing, for the next log read:

| address | symbol | what it is |
|---|---|---|
| `0x0225e46e` | *(unresolved)* | the wild Pokemon's move choice — one per turn, first |
| `0x0224941c` | `BattleControllerPlayer_BeforeTurn` | the four BeforeTurn advances |
| `0x0224ba32` | `ov12_0224B528` | **the paralysis check** — present only once Ho-Oh is paralyzed |
| `0x0224bfd4` | `BattleSystem_CheckMoveHit` | the accuracy roll |
| `0x02257d08` | `TryCriticalHit` | crit |
| `0x02257c3a` | `ApplyDamageRange` | the damage roll |
| `0x02250632` | `ov12_02250490` | the secondary-effect proc roll |
| `0x02253eda` | `CheckAbilityEffectOnHit` | **Static** |
| `0x02258606` | `ov12_022585B8` | the skeleton: post-move, between-turn, end-of-turn |
| `0x02247602` | `FieldSystem_EncounterRateRoll` | a ball's shake roll (mis-attributed symbol) |

---

## 2. What the comparison confirms

Everything below matched on every turn it occurred on. Figures are quoted so each is checkable.

**The turn skeleton**, including all three faint variants, which the three runs happen to cover
between them:

* an ordinary two-move turn — `1 + 4 + ours + 2 + 2 + theirs + 4`
* **fainted before moving** (hooh2 turn 11: Sacred Fire kills Ampharos before it acts, 14 rolls)
  → `END_OF_TURN_ADVANCES_FAINTED_BEFORE_MOVING = 3` holds
* **fainted after moving** (hooh2 turn 23: False Swipe lands, then Ancient Power kills Smeargle,
  20 rolls) → `END_OF_TURN_ADVANCES_FAINTED_AFTER_MOVING = 2` holds
* a faint on a **switch** turn (hooh2 turn 1, hooh3 turn 9)

**Ho-Oh's move choice, on all 108 turns.** This is the strongest single result in the exercise:
`select_target_move`'s `% 4` *and* its PP accounting predicted which of the four moves Ho-Oh
would use, every turn, across three runs — including the long tail where Sacred Fire, Punishment
and Ancient Power are all exhausted (5 PP each) and it can only Safeguard. The model's running
figure for Ho-Oh's PP at the end of hooh1 is `[0, 0, 0, 2]` after 57 turns.

**Leftovers, and the ordering implemented last session.** `hooh2` turn 4 is the whole thing in
one turn:

```
FlashDrive was burned!                                   215/314
FlashDrive restored a little HP using its Leftovers!     +19   (314/16)
FlashDrive is hurt by its burn!                          -39   (314/8)
                                                         195/314   <- sim: 195
```

Recovery first, tick second, both off max HP, net −19/turn. The emulator prints the two messages
in that order on every one of the ~10 turns it happens.

**Static.** Fired once, `hooh3` turn 3: *"FlashDrive's Static paralyzed the wild HO-OH!"* The
simulator rendered **`E2h*M1HP265`** — the token added yesterday, on the turn it was added for.
The roll is `CheckAbilityEffectOnHit`, and it lands after the accuracy roll.

**Side conditions.** Safeguard up on turn N, *"no longer protected"* at the end of turn N+4
(`SAFEGUARD_TURNS = 5`); Light Screen the same (`SCREEN_TURNS = 5`, no Light Clay). A second
Safeguard while one is up prints *"But it failed!"*, and the measurable consequence is in
`hooh3`: the turn it lands costs 19 rolls and the turn it fails costs 17. Both spend zero
accuracy rolls (Safeguard's accuracy is 0, so there is no check), so the two-roll gap is exactly
the **post-successful-move advances a failed move does not spend** — the rule that desynchronised
the simulator from the Suicune log at turn 3, holding here on a different move and a different
target.

**Intimidate** on a voluntary switch-in and on a post-faint send-out, both deterministic, both
matching — including the case that matters for the plan: in `hooh3` Ho-Oh had `+2` Attack from two
Ancient Power procs, and Granbull's entry took it to `+1`, not to `−1`.

**Spore into a paralyzed target** (`hooh1` turn 31): *"But it failed!"*, 13 rolls — the accuracy
roll **is** spent and the token is the bare slot, not a miss. Exactly what
`notes/seed_separation.md` claims and what `will_fail` implements.

**Pressure.** Smeargle's Sweet Scent has 20 PP and the player used it on ten consecutive turns
(27–37) and then switched to False Swipe. The model's PP for it reads `0` after turn 37: two per
use, so the model predicted the player's *forced* change of move.

**Revive**: `162 // 2 = 81`, and it costs no advances (`R4` turns come in at 15 rolls, the same
as a bag action).

**21 ball throws**, every shake count matching, read off the message table
(`catch.SHAKE_MESSAGES`): *"Oh, no!"* = 0 … *"Gah!"* = 3. All 21 were at **1 HP** — 19 of them
paralyzed as well (hooh1's 18 and hooh3's 1; hooh2 never landed a status). None caught, and the
shake distribution was `P0`×14, `P1`×5, `P2`×1, `P3`×0. That is a plain Poké Ball rather than the
Luxury Ball, but both are ×1 on this target (§7 of `ho_oh_party.md`), so it is the same `b` and
the same 1.23%/throw — and 21 throws producing one `P2` and no `P3` is what that looks like.

---

## 3. The one real discrepancy: a phantom burn survives a faint and a Revive  *[fixed]*

`hooh3` turn 14 — **simulator 61 HP, game 81 HP**, and it diverges further every turn after.

The sequence:

1. **Turn 9.** Granbull is switched in; Ho-Oh's Sacred Fire hits and faints it. Sacred Fire's 50%
   burn secondary *procced on that roll* — the simulator's token correctly omits the `~`
   (`_visible_tokens` already knows a move that faints its victim shows no secondary message),
   **but the simulator applied the burn to the state anyway.**
2. **Turn 13.** The player Revives Granbull: `81/162`. The simulator agrees on the HP and keeps
   the burn.
3. **Turn 14.** Granbull is switched back in. The simulator takes a burn tick — `81 − 20 = 61` —
   and the game does not, because the real Granbull is not burned.

Three separate defects, each sufficient on its own:

| # | defect | where |
|---|---|---|
| a | a secondary status is applied to a victim **the move fainted** | `sim.act_target` / `act_ours`: the new `secondary_landed` gate checks Safeguard and an existing status, but not `victim.fainted` |
| b | **fainting does not clear the status** | nothing clears it; the fainted Battler goes to the bench with `status=BURN` |
| c | **a Revive restores HP but not status** | `act_ours`'s REVIVE branch: `revived.with_hp(items.revive_amount(...))` |

Confirmed in isolation, independent of the logs:

```
(a) seed 0x1010: Granbull fainted to Sacred Fire and is brn on the bench; tokens=E1hX6
(b) seed 0x1000: fainted while burned -> bench status brn, hp 0
(c) revived: hp=81/162 status=brn   tokens=R4E1
```

The logs cannot distinguish (a) from (b) — both produce "no burn" — but both are real: Gen 4
clears a Pokemon's status when it faints, and a Revive brings it back with none. Fixing (b) alone
would resolve this run; (a) is still wrong on its own terms and is where the ROM's behaviour is
clearest (`_visible_tokens` already documents that the outcome is never *shown*).

**All three are fixed.** (b) went into `Battler.with_hp` — the one choke point every HP change
passes through, so no code path can hold a fainted-and-statused Battler however it got there;
(a) is an explicit `not victim.fainted` in both directions, which is needed *because* (b) now
clears the status (a corpse reads as unstatused, so "is it unstatused?" would re-status it); and
(c) clears the status on the way back up as well, for a party member configured as fainted rather
than simulated into it. hooh3 then replays clean, and a Sacred Fire the victim *survives* still
burns it — `hooh2` turn 4 is that turn, and it is in the same test.

**Why it matters beyond one turn.** The phantom tick is 1/8 of max HP per turn on a party member
the plan expects to survive several turns of Charm. In `hooh3` the model would have fainted
Granbull about four turns before the game did, and — worse for the tool's actual job — the first
HP the player reports after a Revive would contradict every candidate, with the contradiction
report blaming the window rather than the burn.

---

## 4. The configuration hazard: held items are not in the exported profile

Not a simulator bug, and the most dangerous thing in this exercise.

Two held items had to be **inferred from the logs** before anything matched, because
`notes/e4c9ed8a4995.json` has no `held_item` field at all — the app keeps held items on the
hunt's *party slot* (`facade`'s `slot.held_item`), not on the profile Pokemon:

* **Smeargle: a Silk Scarf.** Every False Swipe was ~17% low without it. The chain is
  `40 → 60` (Technician) `→ 72` (+20%), and at Ho-Oh's `−4` Defence that is 60–72 observed where
  the unscarfed model predicts 50–60. Of the items `damage.py` models it is the only one that
  reproduces all of them, and it is the only Normal-type booster in Gen 4 anyway.
* **Magneton: a Choice Scarf.** `107 × 1.5 = 160`, which beats Ho-Oh's 152 — and `hooh1` turn 2
  has Magneton's Thunder Wave landing **first**.

What each omission costs, measured by re-running with it removed:

| missing | mismatching turns (hooh1, of 57) | symptom |
|---|---|---|
| Silk Scarf | 11 | every False Swipe low by ~1/6; HP diverges, rolls stay right |
| Leftovers | 2 | HP low by 19/turn while Ampharos is out |
| **Choice Scarf** | **56** | the Speed order flips on turn 2 and **the stream desyncs for the rest of the run** |

The Choice Scarf row is the one to take seriously. A single mis-set held item does not degrade the
prediction, it **destroys** it — and the only symptom the player sees is that nothing matches from
turn 2 onward, which reads exactly like a mis-centred candidate window. The readiness check
already knows this mechanism (`readiness.speed_after_item` exists precisely because the summary
screen does not show a scarf's boost); what it cannot do is notice that the field is *empty*.

Also found while building the party for the replay: **Natu's moveset is empty in the profile**
(`"moveset": []`, as is Mamoswine's). It never acts in any of the three runs, so nothing here
depends on it, but a `Battler` cannot be built from it and the lead is exactly where the shiny
seed plan puts the Natu.

---

## 5. What the logs could not settle

**Static's roll order relative to a damaging move's secondary proc** — flagged in `sim.py` and in
`ho_oh_party.md` §9 — is **unobservable against Ho-Oh in principle**, which is a stronger
statement than the "costs nothing in the planned run" currently recorded there:

* Static needs a **contact** move. Of Ho-Oh's four, only Punishment makes contact.
* Punishment has **no secondary** (`effect_chance = 0`).
* Sacred Fire has a secondary but makes no contact; Ancient Power boosts the attacker and makes
  no contact; Safeguard is a status move.

So no turn of this matchup can ever contain both rolls, and the only Static trigger in 108 turns
(`hooh3` turn 3) had `['TryCriticalHit', 'ApplyDamageRange', 'CheckMoveHit',
'CheckAbilityEffectOnHit']` and nothing else. The uncertainty is real but it cannot bite here; it
would need a different target, or a Body-Slam-alike, to resolve or to matter.

**Which bag item was used on an unlogged turn.** Two turns have no action message of ours at all
(`hooh2` 24 and `hooh3` 13 — `hooh1`'s turn 58 is just a truncated trailing turn, one move-choice
roll and nothing else). The emulator logs
*"Kyle used one Poké Ball!"* but apparently not a Revive, so the action had to be reconstructed
from a later switch-in showing a previously-fainted member at exactly half HP. Both were Revives
and both matched at 15 rolls. Worth knowing for the next capture: a Revive leaves no message in
the log, so if the recorder can be made to log item use it would remove a guess
(`clayton-avk`).
