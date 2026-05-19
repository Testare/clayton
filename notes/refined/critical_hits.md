# Critical hit logic

## P0 Logic
First we calculate how many critical hit stages the pokemon has.

Crit stages start at 0.

If using a move with increased critical hit ratio, increase crit stage counter by 1.

If the pokemon is under the effect of Focus Energy: Increase critical stage counter by 2.

There are some other modifiers, but they don't apply in P0. See the "P3 Logic"

If critical stages is more than 4, reduce to 4.

Once we have the final critical stage counter, we use it to index into the critical stage modifier list, which is `[16, 8, 4, 3, 2]`.

Example: A move with a normal crit rate after focus energy will have a counter of 2, and the index will return a crit stage of 4.

A random roll is done to determine if a crit should land, using logic `RAND % crit_stage_modifier == 0`. If this is true, a final check is done to see if Lucky Chant is in effect, and if it is not, the move crits.

## P3 Logic

These stage modifiers are not required until P3, but apply at the obvious point in the logic before.

If the user is holding something that increases critical hit chance, crit stage +1

If the user is chansey and holding lucky punch, crit chance +2
