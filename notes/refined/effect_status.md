Effect statuses are checked in a specific order.

# Effects that might affect Magikarp's ability to perform moves

For each of these effects, they are checked in this order, and if any of them prevents a move from happening the following effects are not checked.

## Sleep
When a move that applies sleep hits, a random number is generated to determine how many turns it will last. The formula is 2 + (RAND % 4). The last turn of sleep, the pokemon wakes up, so if RAND % 4 is 0, the result is 2, meaning the pokemon will sleep one turn and wake up the next.

Fails if Magikarp is already asleep, frozen, burned, poisoned, or badly poisoned.

## Freeze
Unlike sleep, freeze turns are not pre-determined. Instead, before the pokemon moves, a thaw check is done, and the pokemon thaws if (RAND % 5) is 0.

Fails if Magikarp is already asleep, frozen, burned, poisoned, or badly poisoned.

## Flinch
<Prevents Magikarp from taking an action>

Duration is always only THIS turn: Clear this status in the turn-end cleanup. Flinch can be rolled and applied to pokemon that have already moved, but this will not be observable to the user.

Struggle is prevented by flinch.

## Disable
<Prevents move used last turn>

A hit roll is done, even if disable won't be successful.

Disable fails if any of the following is true:
* The opponent is already disabled
* The opponent hasn't made a move yet
* The opponent's last move was prevented, such as by paralysis, gravity, etc.
* The opponent's last move was Struggle

If disable is successful, A roll is performed to determine duration. 

Duration: 4 + (RAND % 4)

Disable turns tick down, even if the user is asleep, frozen, or flinches. It can even end while Magikarp is frozen or asleep as well.

The turn the user uses disable counts towards the duration of disable, even if the user moved second in the turn.

We should have a path token for when disable ends.

## Taunt
<Prevents splash>

A hit roll is done, even if taunt won't be successful.

Taunt fails if the pokemon is already taunted.

Duration: 3 + (RAND % 3)

Taunt turns tick down, even if the user is asleep, frozen, or flinches. It can even end while Magikarp is frozen or asleep. 

We should have a path token for when taunt ends.

## Gravity
<Prevents splash for Magikarp, as well as effects on user>

Lasts 5 turns, including the turn it is used. Fails if gravity is already in effect.

We don't need a path token for when gravity ends, since the duration is always 5.

## Confusion
When a move applies confusion, a random number is generated to determine how many turns it will last. The formula is 2 + (RAND % 4). The last turn of confusion, the pokemon snaps out of confusion.
While confused, and if no previous condition prevents the move from happening, a roll is performed to see if the user hits themself. If RAND is even, (RAND & 1 == 0), the user hits themself in their confusion instead, which means a damage roll but no crit or hit rolls.

The number of turns a pokemon remains confused only decreases when this state is checked - When magikarp is prevented from attacking due to sleep, freeze, flinching, disable, taunt, or gravity, the number of remaining confusion turns is NOT decreased, and the pokemon will not snap out of confusion in those circumstances. The checks that occur after (paralysis and attract) do NOT prevent snapping out of confusion or prolong turns spent confused.

A pokemon may still hit itself in confusion if it would otherwise use Struggle.

## Paralysis
(RAND % 4) == 0 => Full paralysis, move fails

## Attract / Infatuation

RAND & 1 == 0 => Immobilized by love.

# Effects that prohibit magikarp from selecting a move

## Encore

While under the effect of encore, just like when it has no useable moves it skips the roll to determine which move to perform, and performs the last used move. If that move is not in the useable move pool, they struggle instead as they have no useable moves (see below).

## NO USEABLE MOVES
If the user has no useable moves when it comes time to select a move, the usual roll is not performed, and Magikarp uses Struggle. This move always hits, but still rolls crit and damage, and counts as successful. If magikarp's move is prevented after it has chosen that move, it fails, but does not struggle that turn.


# Effects that might affect the metronome user's moves

## Gravity

If metronome selects a gravity-prevented move, we roll again.

## Sleep

Rest is a metronome callable move. Sleep will affect the metronome user the same way as Magikarp.

## Confusion 
Will affect our pokemon the same way it effects Magikarp.

## Recharging

If the metronome user uses a move like hyper beam or blast burn, they will be afflicted with the "recharging" status. This means that the next turn, the metronome user will be forced to do nothing. No metronome roll, no hit rolls, no rolls for a successful move on the next turn. This only matters if Magikarp does not faint from the attack.

## Charging

Moves: Solar beam, Razor Wind, Sky Attack, Skull Bash
Moves like solar beam, razor wind, skull bash, etc. Charge on one turn, then attack on the second, meaning the second turn there won't be a metronome roll.

# Other effects

## Poison/Burn

These status conditions last and deal damage over time. They don't really do anything helpful for our purposes, but prevent other non-volatile status conditions from occuring (sleep, poison, paralysis)

## Nightmare/Curse

The move nightmare does damage at the end of each turn if the target is asleep. Once the target is awake, this condition ends.

Curse, if used by a ghost type, also does damage at the end of each turn, but this is not P0.

## Binding status effects
Moves: Bind/Wrap/Fire Spin/Clamp/Sand Tomb/Magma Storm

Prevents switching out and does damage for a certain number of turns. This happens after both pokemon have made their moves. The duration is random, however, and observable by the user up to the point that Magikarp faints, so we should emit tokens at turn end for that.

These effects do not stack - If metronome does Bind one turn, then fire spin the next, the Magikarp remainins under the effect of "bind" for the predetermined duration, and not fire spin (even if bind's effect ends that turn).

Duration is 3 + RAND % 3. On the last turn, instead of taking damage they are freed. For example, if RAND returns 1, then the duration will be 4. The opponent will take damage at the end of the turn they are hit, then at the end of the next 2 turns. The turn after that, they will be freed and take no damage. We should have tokens for binding damage at end of turn and also for magikarp breaking out.

## Full HP

Being at full HP can cause recovery moves to fail, so we should track if

# Notes about pathing

Gravity, Disable and taunt can only prevent Magikarp from acting at all on the turn they apply, subsequent turns will force Magikarp to use a different move or to struggle. Because of this, we can probably use the same path symbol for any of these outcomes, like "P" for prevented, since it will always be in response to the metronome move used that turn.

