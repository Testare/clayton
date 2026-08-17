# Branching Paths

It might be a good idea to build some sort of ability to represent branching paths. Moves that affect speed can mess us up. For Beat Up, we might not know how many pokemon are in the player's party, and we'll likely have to do damage and crit rolls for each. We can control for some of these variables, and in the rare case when speed ties are possible using Lagging tail (Fling), we can just make the path unsupported, but it might be worth considering how to make a branching path grammar work.

# Things that might cause branching

## Recovery moves

Certain recovery moves fail if the user is already at full HP (like Recover), and recover up to 50% of max HP otherwise. While we can do some tracking on whether the pokemon has taken any damage at all or recoverd at all, since it isn't really feasible to track how much damage is dealt since we don't know opponent's IVs or nature, we can't always know ahead of time whether the metronome user will be at full HP or not. This matters because whether the move is successful or fails determines whether the two random rolls occur after the move is completed, which can entirely alter the following path.

For P0 we can track if the metronome user has yet taken any damage, and if they've received any recovery. If they haven't taken damage, we can assume this will fail. If they've taken damage and haven't used any moves that recover HP, we can assume that this will succeed. Otherwise, we cannot make assumptions; For P0 we'll throw not supported, and in the future we'll need branching paths to track both situations.

## Present

Like recovery moves, the move Present can also perform healing, but on the target instead of the user, and likewisie can fail if the target is already at full HP.

For P0 we can do much the same thing as we do for recovery moves: We track if the target has taken damage from a move, and if they've ever had any recovery. If they've not taken damage, Present will fail when attempting to heal. If they've taken damage but not been healed, Present will successfull apply recovery. If they've taken damage and already been healed by a present, a fairly unlikely scenario, then we can throw not supported.

## Substitute

The move "substitute" requires 1/4th of the user's HP in order to be set up. If the user does not have 1/4th of their HP, the move fails.

In addition, substitute fails if it is used a second time while still up.

Finally, there are moves that depend on the user being hit, such as Bide or Counter. While the user is behind a substitute, we can't know for certain whether they were triggered until the substitute disappears.

## Belly Drum

Similar to substitute, requires user to have >= 1/2 max HP or it fails

## Endeavor

Fails if the user has more HP than the target.
