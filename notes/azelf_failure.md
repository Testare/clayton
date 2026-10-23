
Seed A: 0x6d0203e9 frame 12 (Lax 7 13 13 11 8 24)

0x49023160

E3M1 M2E2hHP119 M2-E2hFhHP058 M2E2hHP045 IhpEparHP134 M2-E1hHP117 M2E1!HP083 S2E3 M2hE2hHP132 S3EparFhHP166


## What went wrong, and it was two things

**Answered.** Both fixed; the whole 15-turn recording now replays exactly
(`tests/test_battle_compass_ground_truth_azelf.py`).

### 1. The Uproar had already ended (clayton-6xu.7.8)

Azelf's second Uproar rolled **duration 3** (roll 47036 at `subscript_uproar`, `47036 % 4 == 0`)
and ran for **two** turns. On the second one it was fully paralyzed, and
`MON_COND_CHECK_STATE_UPROAR` asks `BattleContext_MoveFailed` *before* it reads the counter
(`battle_controller_player.c:1523-1536`): a failed move clears the volatile outright. Hence
"The wild AZELF calmed down." a turn early.

`sim._tick_uproar` had the wake-first half of that rule but not this half, so it counted 3 → 2 and
kept the lock on. A locked target spends **no** move-selection roll, so the sim withheld one the
game spent: turn 11 rolled 21272, `% 4 == 0` → **Swift**, while Clayton predicted the locked
Uproar. See notes/platinum.md §15.3.1 for the nine flags that count as a failure and the five
things — sleep, freeze, truant, recharge, a plain miss — that do not.

### 2. `rng_offset` over-counted on every locked turn (clayton-6xu.7.9)

Found while replaying, and independent of the first. `simulate_turn` charged the selection roll
from `select_target_move` returning a slot rather than from the stream having moved — and a locked
target returns a slot while spending nothing. The stream was right on all 15 turns; the offset was
one high on exactly the six Uproar-locked ones (3, 4, 10, 13, 14, 15). It matters because
`solver._state_key` uses the offset *as* the stream position.

## Notes on the fixture

The replay reads the party off the recording's own `mon` records: THE RADIO is **Lv54**, CATCHMONKE
**Lv64** (not the 58 from the Uxie run), BEEG QRO **Lv52** with Leftovers. Three Uproars, durations
3 / 3 / 6, the last still running when the recording ends. Two Future Sights, the second landing on
a Pokemon that was switched in after it was banked.

One cosmetic difference from the token string above: turn 9 renders `M4h` here, not `M2h` — the ROM
has Smeargle's moves as Spore / Sweet Scent / Mean Look / False Swipe, so False Swipe is slot 4.
Harmless to the simulation (our own move list is whatever the profile says), but the hunt profile
and the game disagree about Smeargle's slot order.
