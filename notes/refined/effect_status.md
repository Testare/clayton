Effect statuses are checked in a specific order.

# Effects that might affect Magikarp

For each of these effects, they are checked in this order, and if any of them prevents a move from happening the following effects are not checked.

## Sleep
When a move that applies sleep hits, a random number is generated to determine how many turns it will last. The formula is 2 + (RAND % 4). The last turn of sleep, the pokemon wakes up, so if RAND % 4 is 0, the result is 2, meaning the pokemon will sleep one turn and wake up the next.

Fails if Magikarp is already asleep, frozen, burned, poisoned, or badly poisoned.

## Freeze
Unlike sleep, freeze turns are not pre-determined. Instead, before the pokemon moves, a thaw check is done, and the pokemon thaws if (RAND % 5) is 0.

Fails if Magikarp is already asleep, frozen, burned, poisoned, or badly poisoned.

## Flinch
<Prevents Magikarp from taking an action>

Duration is always only THIS turn.

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

TOCONFIRM: When disable happens second, does that turn count as one of the disabled turns?

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

## Attract
RAND & 1 == 0 => Immobilized by love.

## NO USEABLE MOVES
If the user has no useable moves when it comes time to select a move, the usual roll is not performed, and Magikarp uses Struggle. This move always hits, but still rolls crit and damage, and counts as successful. If magikarp's move is prevented after it has chosen that move, it fails, but does not struggle that turn.

# Effects that might affect the metronome user

## Gravity

If metronome selects a gravity-prevented move, we roll again.

## Sleep

Rest is a metronome callable move.

## Confusion 

The metronome user might become confused as a result of using Outrage, Thrash, or Petal Dance, and it also forces the Metronome user to use that move multiple times. However, it is hard to imagine Magikarp surviving any of these moves, so handling the case where it occurs is not a priority.

## Recharging

Similarly, a max-stat level 20 Magikarp might survive Blast Burn or Roar of Time from a lower level Clefable, but it is unlikely so not the priority to support right now. That said, there are a decent number of recharging moves...

# Notes about pathing

Gravity, Disable and taunt can only prevent Magikarp from acting at all on the turn they apply, subsequent turns will force Magikarp to use a different move or to struggle. Because of this, we can probably use the same path symbol for any of these outcomes, like "P" for prevented, since it will always be in response to the metronome move used that turn.

# Turn rolls

The rolls in a given turn are

1 roll - Determine magikarp's move (IF it has useable moves)
<Player chooses a move>
4 rolls - BeforeTurn
<Metronome roll>
<Rolls for the move determined by metronome>
IF the move was successful: 2 more rolls
2 rolls to start Magikarp's turn
<Magikarp's move>
IF the move was successful: 2 more rolls
4 rolls at the end of the turn 

Move that aren't successful: Misses, applying status conditions that already exist on a non-damaging move, being asleep, frozen, disabled on your selected move, or hitting yourself in confusion. Basically anything that keeps the move animation from playing.



