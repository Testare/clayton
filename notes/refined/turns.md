# Before battle starts
RNG advances 6 times from the seed 

# Turn RNG rolls

The rolls in a given turn are

* 1 roll - Determine magikarp's move (IF it has useable moves; Otherwise struggle is selected and no roll is performed)
* <Player prompted for choice of action, unless they are recharging>
* 4 rolls - BeforeTurn
* <Faster pokemon's turn>
* IF the move was successful: 2 more rolls
* 2 rolls between turns
* <Slower pokemon's turn>
* IF the move was successful: 2 more rolls
* 2 rolls before end of turn effects
* End of turn affects applied
* 2 more rolls at the end of the turn 

See the speed.md file for notes about which pokemon is "faster".

Move that aren't successful: Misses, applying status conditions that already exist on a non-damaging move, being asleep, frozen, disabled on your selected move, or hitting yourself in confusion. Basically anything that keeps the move animation from playing.

For the metronome user's turn, unless they are prevented by a status condition such as confusion, sleep, recharging, etc. will pretty much always start with a metronome roll, then any rolls needed for the move metronome selected.
