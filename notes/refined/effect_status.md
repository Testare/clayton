Effect statuses are checked in a specific order.

# Effects that might affect Magikarp
## Sleep
When a move that applies sleep hits, a random number is generated to determine how many turns it will last. The formula is 2 + (RAND % 4). The last turn of sleep, the pokemon wakes up, so if RAND % 4 is 0, the result is 2, meaning the pokemon will sleep one turn and wake up the next.

## Freeze
Unlike sleep, freeze turns are not pre-determined. Instead, before the pokemon moves, a thaw check is done, and the pokemon thaws if (RAND % 5) is 0.

## Flinch
<Prevents Magikarp from taking an action>

## Disable
<Prevents move used last turn>
TO CONFIRM: Do disable turns tick down when asleep/frozen?

A roll is performed to determine duration

TO CONFIRM: Random duration determination

## Taunt
<Prevents splash>
TO CONFIRM: Do taunt turns tick down when asleep/frozen?

TO CONFIRM: Roll for duration (3-5 turns?)

## Gravity
<Prevents splash>

## Confusion
When a move applies confusion, a random number is generated to determine how many turns it will last. The formula is 2 + (RAND % 4). The last turn of confusion, the pokemon snaps out of confusion.
* While asleep, confusion turns do not decrease

While confused, a roll is performed to see if the user hits themself. This roll is not performed if one of the previous conditions prevents the user from acting. If RAND is even, (RAND & 1 == 0), the user hits themself in their confusion instead.

TOCONFIRM: Damage roll is still done for confusion damage, but not crit or miss roll.

TOCONFIRM: Do confusion turns tick down when asleep/frozen, flinched, disabled, etc?

## Paralysis
(RAND % 4) == 0 => Full paralysis, move fails

## Attract
RAND & 1 == 0 => Immobilized by love.

## NO USEABLE MOVES
If the user has no useable moves when it comes time to select a move, the usual roll is not performed, and Magikarp uses Struggle. This move always hits, but still rolls crit and damage.

# Effects that might affect the metronome user

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
