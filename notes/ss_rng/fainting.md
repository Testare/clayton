## Fainting Logic

Tested having my pokemon faint from using explosion - There was only 4 rolls after the explosion istead of the usual 6 for the successful move.

## Our Pokemon fainting mid-turn [verified, in-game testing]

Measured by playing it out, not by gdb — but measured, not reasoned. The turn does not stop when
our Pokemon faints; it *shortens*, and by how much depends on whether we had already moved.

* **The opponent's rolls all still occur.** Nothing about our fainting takes anything away from
  the attacker's own move.
* **A move that faints us still rolls its secondary effect** (a burn chance, a stat drop, a
  flinch) — but the outcome is never shown, so it must NOT be tokenized. The roll is spent; the
  `~` is not emitted.
* **Fainted before we moved:** we spend none of our own rolls — not the move's accuracy, crit,
  damage or secondary rolls, and not the two post-successful-move advances. **The two
  between-turn advances are also dropped.**
* **End-of-turn advances change when a MOVE faints us:** 4 normally, **3** if we were fainted
  before we moved, **2** if we were fainted after we moved.
* **Fainting from an end-of-turn effect** (a burn or poison tick) changes nothing: the turn
  spends its usual 4.
* **Switching the replacement in costs no advances.**

### Why the secondary rule has two readable outcomes

Say the opponent uses Fire Blast while we are on low HP. On some seeds the damage alone faints
us; on others it does not, but the 10% burn procs and the burn tick finishes us at end of turn.
Those are different token streams, and both are reportable:

```
E3hX2     the move fainted us outright -- the burn roll happened, its outcome was never shown
E3h~X2    the move burned us, we survived it, and the burn tick fainted us at end of turn
```

The second case also keeps the full 4 end-of-turn advances, because what fainted us was the tick
rather than the move.

**Residual damage is not modelled yet** (burn/poison ticks — see the Burn bead), so the simulator
can currently only produce the first form. The advance accounting above is written to cover both.
