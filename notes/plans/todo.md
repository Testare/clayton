# TODO
# To verify
* Add "Flow.adjust()", which allows us to change fields we have already defined. If it is called with an optional parameter, like `Flow.adjust(criteria_name="only-balls")` then we just set it there, otherwise we prompt to ask what field they want to change, and then prompt them for those fields as normal.
* Make it easier to use clayton with EonTimer
  * Make it so that when a seed is chosen in `choose_target`, we output "Delay from key seed" as well with the delay in seconds, which is obviously target_delay - key_seed_delay. This should also be output when we do flow.print(), though it is a calculated field instead of stored in the JSON, so maybe put it after the section break. Make te output tables from choose target prettier and align better
  * Add "Delay from key seed" to the printed output of both compass functions as well. 
* Print timestamp at start of interactive flow methods.
* Flow: For strategies and criteria, it might be easier to offer a numbered list. They can still input the name directly, but if they input a number it chooses that strategy. If the strategy needs number configurations, like sigmaFrames, sliding window, or machete turns, we prompt them for those numbers after.
* Flow: Potential rename to better fit Safari/Tarzan theme. Perhaps "Cruise" (like Jungle Cruise)?

# Details
## Deferred: Ability support for metronome_compass_full
* Cute Charm (Cleffa/Clefairy/Clefable): chance to cause infatuation on contact, adding RNG per Magikarp turn
* Serene Grace (Happiny/Chansey/Togepi/Togetic/Togekiss): doubles secondary effect chances, changes filtering thresholds
* For now, require users to avoid these abilities (all listed pokemon have alternates)

## Compass metronome (complex) notes
We'll need additional information:
  * If metronome sets up gravity, we'll need to factor in moves that metronome can't use during gravity
  * We'll need to identify the randomness of a given move -
    * Does it crit roll?
    * Does it damage roll?
    * Does it make an accuracy check roll?
    * Does it have secondary affect chances? How many?
    * Does it have some other random roll?
  * We'll also need to identify the randomness from magikarp using splash or tackle, but that should be easier.
  * It's possible we can simply create a file/table of possible moves, and have a flag of "currentlySupported" or not in that table for ones where we aren't sure how much it advances RNG.
  * We also might be able to use a python script in the debugger attached to the hgss emulator to force the seed to one that produces that move, then counts how many random rolls the move performs, and save the results to a file. It would require me to manually click metronome.
