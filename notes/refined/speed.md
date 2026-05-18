# Magikarp speeds
Slowest possible Magikarp with modifiers: 7 (lvl 2 with negative nature)
Fastest possible Magikarp with no modifiers: 47 (lvl 20 with positive nature and max IV)

# The Problem: Speed Ties

Useful link: https://github.com/pret/pokeheartgold/blob/5a8d3a0e95dca896ae1f24b693519ecaa5705df8/src/battle/overlay_12_0224E4FC.c#L962

Speed ties are kinda a nightmare for our RNG - They cause lots of extra RNG rolls, and it'll be hard to pinpoint exactly where they occur in all the effects. The most important is at the start of the game, before the BeforeTurn rolls, which determines which pokemon moves first, but lots of other rolls occur.

Example where both pokemon are forced to use "Splash", and we 

* ?? (Magikarp chooses splash)
* CheckSortSpeed (Pokemon move order determine - Forced to odd for Magikarp to go first
* BeforeTurn x4
* CheckSortSpeed
* ov12_B8 x2 (Magikarp Splash success)
* ov12_B8 x2 (Interturn rolls)
* CheckSortSpeed
* BtlCmd_Metronome (Splash)
* ov12_B8 x2 (Metronome user Splash success)
* ov12_B8 x2 (Half of the end turn rolls)
* CheckSortSpeed x2
* ov12_B8 x2 (Other half of end turn rolls)
* CheckSortSpeed


I didn't even check how it effects the battle start rolls, but it's doubtless going to affect those too.

Because of this extra randomness, we will need to do two things:
1. Make sure there are no speed ties when the game starts
2. Make sure that we have a way to handle factors that manipulate speed.

# Methods of handling speed ties

## Speed > 47
If the Metronome user's effective speed is 48 or more, it will never be outsped by a wild Magikarp in Blackthorn City... At least, not at the start of battle. Since most metronome users are slower naturally than Magikarp, and we don't want to overlevel too much, using a Choice Scarf makes this significantly more achievable.

## Lagging Tail

Lagging tail is a beautiful solution to our problem. It ignores speed entirely, and forces the holder to go second.

# Things that are a problem for Lagging Taail

## Fling

Unfortunately, fling will have the metronome user discard the lagging tail. Suddenly speed very much might matter, and all the problems that exist for the non lagging tail case are suddenly apparently. We'll need the user to provide the metronome user's speed as input, even if they have lagging tail, and when fling occurs we'll have to check the possible range of speeds the Magikarp might have. If the range is completely below or above the metronome user's speed, we're good and can continue on one solid path, but if not then we'll have to either implement branching paths or close the path with an Unsupported token. Even doing this initial check of possible speed ranges means we'll have to do a lot of tracking for this one edge case, so we'll probably just have to start with Fling being not supported.

# Things that are only a problem for non-lagging tail cases

## Moves that increase/decrease speed

Moves that increase/decrease the user or Magikarp's speed can be problematic, especially for the route of trying to just outspeed or underspeed Magikarp. We might need to implement branching paths to handle what happens if, given Magikarp's level and the board state, speed order changes are possible (especially if speed ties are possible). We would only need to branch where the speed order change occurs, so hopefully it shouldn't branch out too many times. The easiest way around this is with Lagging Tail, which makes speed irrelevant.

## Trick/Switcheroo

If holding choice scarf, or a speed lowering item (power belt, iron ball) and we trick the item onto the Magikarp, that might change the speed order, just like the above we might need to branch. With Lagging Tail, this is actually great - We'll just start moving first, and then we're safe from Fling.

## Swift Swim
Magikarp's only ability is swift swim. That means in the rain, its speed will double.

The moves Skill Swap and Entrainment mean we'll have to track Magikarp's ability as well, since in rain the metronome user's speed will double in the rain if skill swapped, or nothing will happen if metronome uses entrainments Magikarp.

# Things that are not problems for speed tie handling

## Priority
Metronome, Splash, and Tackle are all same priority, and any moves Metronome calls will not change that order.

