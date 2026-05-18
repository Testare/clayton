
# Things we need to know about each pokemon

* Species
* Ablity
* Gender
* Speed (scalar for Player's pokemon, range for wild Magikarp)
* Held Item
* Known Moves
* Status (Non-volatile statuses and volatile ones)

Also each turn, we need to know "selected move". For metronome user this should always be metronome.

# Player's Party
Each phase, we will need information about the player's party.
P0 - Enforce the Player has a full party of 6 pokemon, and only have the stats for the first one, the metronome user. We'll assume Beat-up will roll the full 6 hits.
P1 - Have information about how many pokemon are in the Player's party, and how many are metronome users. We need the above stats for each metronome user we intend to use.
