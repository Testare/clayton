# Tricky seeds

Seeds whose battles exercise subtle or easy-to-get-wrong mechanics. Each entry
records the seed, what makes it tricky, the ground-truth behaviour, and a pointer
to the regression test guarding it. Add a seed here whenever a bug turns out to
hinge on an interaction that a "normal" seed wouldn't reveal.

All seeds below are from `metronome_seeds/Metroman2_test_7_vs_15f.jsonl`
(Metroman2 Chansey, Metronome-only, vs a level-15 Magikarp) unless noted.

---

## 0x9266B0CF — confusion persists through a locked rampage

**Move:** Thrash (turn 1), then a Metronome'd Uproar while confused.

**What's tricky:** Thrash ends and inflicts fatigue confusion on Chansey. While
still confused, Metronome rolls **Uproar**, which locks Chansey in. The confusion
does **not** clear — it continues to be checked every turn *during* the Uproar
lock, and Chansey **snaps out mid-lock**.

**Ground truth timeline (confusion arc):**
- T3 `is confused!` → hurt itself        (self-hit roll)
- T4 `is confused!` → used Metronome → Uproar   (attacked through; Uproar locks)
- T5 `is confused!` → used Uproar         (attacked through, locked)
- T6 `is confused!` → used Uproar         (attacked through, locked)
- T7 `snapped out of confusion!` → used Uproar  (snap, still locked)

So confusion duration = 5 (2 + RAND%4, R=3): four self-hit checks (T3–T6) then a
roll-less snap on T7 — **while locked into Uproar**.

**Why it caught bugs:**
1. It proved fatigue confusion is `2 + RAND%4` (2–5), not `1 + RAND%4`; a 5-turn
   confusion can't otherwise exist. (clayton-5s8)
2. It proved confusion is **snap-first** for the user too (T7 snaps with no roll).
3. It showed the confusion must be modelled *through* the lock (simulate_turn
   "site (a)"): an earlier hack (`_clear_confusion_on_rampage_lock`) cleared the
   confusion and injected 2 unobservable advances to stay RNG-synced, which kept
   the move sequence correct but dropped the `CFZ`/`SCFZ` tokens for T5–T7. Once
   the counter and snap-first were fixed, site (a) models it exactly and the hack
   was removed. (clayton-f7d)

**Expected path (9 turns):**
`KtkhM037h Ksph KtkhCFZ KspM253h Ksph Ksph KspSCFZh Ksph KtkhM322`
— note `KspSCFZh` on the snap turn: Splash, snapped out, Uproar continuation hit,
with **no** Metronome token that turn (still locked).

**Regression test:** `tests/test_locking_move_advances.py::TestConfusionThroughLock`.

---

## 0xE3623EF0 — user confusion snaps one turn later than a naive counter

**Move:** Petal Dance (rampage) → fatigue confusion.

**What's tricky:** used to expose a counter off-by-one. Ground truth:
- T4 `is confused!` → hurt itself
- T5 `is confused!` → hurt itself
- T6 `is confused!` → used Metronome → Low Kick   (attacked through — NOT a snap)
- T7 `snapped out of confusion!`

The old code (fatigue confusion `1 + RAND%4`, "roll on the last turn") emitted the
snap on **T6**, a turn early. With `2 + RAND%4` + snap-first the snap correctly
falls on T7 (outside a 6-turn path window, so T6 shows the plain move). This is the
seed that disproved the "Chansey confusion is roll-first" theory. (clayton-5s8)

**Regression:** covered indirectly by the full `verify_paths` run (moves) and by
0x9266B0CF's token assertions above.
