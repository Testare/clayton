# Abilities

Abilties can affect the game in significant ways. While we might want to focus on only implementing the abilities that are most likely to come into play, we have to make sure we track them because they can change things pretty drastically, and because metronome can use several moves that change abilities, there are a number of situations we need to account for.

# Metronome User Abilities

## Cute Charm

30% chance for pokemon to become infatuated if hit with a contact move.

Implementation drawbacks:
* Have to add information about which moves are contact moves to deal with Magikarp getting Cute Charm

TOCONFIRM: Does cute charm cause extra rolls to see if it procs when hit by tackle?

## Hustle

Lowers accuracy of physical moves by 20%, but increases attack stat by 50%.

Cons probably trump the benefits: While missing CAN prolong the metronome chain, hitting hard with a physical attack will definitely end it.

## Intimidate

Lowers attack of opponent. Useful both at start of battle AND if swapped onto Magikarp.

## Magic Guard

Prevents damage from sources outside direct damage, including recoil. Useful to keep metronome user alive from recoil of own moves, though it might mess with our calculations if it prevents damage rolls from occurring.

## Natural Cure

Heals user upon switchig out. Useful, but most importantly the effect only applies when switching out and that is something the user can control, if we decide to implement switching out.

## Quick Feet

Speeds up user if afflicted with a status condition. If we use lagging tail, this should not be terribly impactful, though it shouldn't be too hard to implement.

## Run Away

There is no condition where running away is helpful to calibration, and Magikarp can't run away, so this is basically a free useless ability.

## Serene Grace

Doubles chance of secondary effects. This can be nice for moves with low-chance secondary effects, though it means moves that already have a 50% chance of occurring now always occur.

## Synchronize

Forces opponent to become burned, poisoned, or paralyzed if the user receives one of those conditions. Not likely to happen to us, but if we use skill swap or entrainment it becomes possible.

Additionally, gives a 50% chance that the magikarp will have the same nature as the user.

# Other Abilities

## Swift Swim

Magikarp's only possible ability. Doubles speed in the rain. Only really a problem if rain dance is called, but Lagging Tail makes it kinda irrelevant.

## Insomnia

When Metronome calls Worry Seed, the opponent will get Insomnia, curing sleep and preventing it from occuring again.

TOCONFIRM: Does using Sing on an opponent with Insomnia prevent sleep turn rolls?

# Moves that change abilities

Note: Simple Beam wasn't introduced until Gen V so we don't need to worry about that

## Role Play, Skill Swap, Entrainment

Each of these moves changes the user's ability to the opponents, the opponent's to the user's, or both. That means we can't just consider any of the abilities from one pokemon's perspective.

## Transform

Has its own note, but Transform DOES copy the opponent's ability... As well as everything else.

## Worry Seed

Gives the opponent Insomnia.

# Priority Abilities

While this might change, these are currently the abilities that are part of P0, the rest are all P3:

* Natural Cure
* Swift Swim
* Insomnia

This is because if we only use a single Chansey with Natural Cure as its ability, these are the only possible ability interactions.


