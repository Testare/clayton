# The Goal

The purpose of this project is to create a set of tools to help ensure successful captures in the Johto Safari Zone using RNG manipulation. This tool's ultimate goal is for the creator to use it to capture a Shiny Metang.

# Some terms

## Seed, Battle Seed, Initial Seed, etc.

Randomness is seeded in the game from the clock and the frames taken in game. For this project there will be two important seeds: The initial seed and the battle seed. The initial seed is the seed that we hit for the RNG manipulation. This, along with advances, determines what pokemon we encoutner. The battle seed, usually what we are talking about with "target seed", is the seed that is created for the battle and used to determine random events that happen in that battle.

We should try to avoid talking about seeds without a qualifier, or using the term "encounter seed" since it could refer to either.

# The Tools

## Compass - Metronome

This phase is about creating a tool to help us calibrate our timers so that we can arrive at a specific time. While we can calibrate a little in the safari zone, there isn't as much randomness to take advantage of. Metronome can generate quite a bit of randomness. By getting a metronome user with specific moves and fighting magikarps in an area that only has them and their pre-determined movepool, we can determine battle seeds hit with much more accuracy.

While we have ideas on how to expand the functionality, the current plan is to have a single metronome user, a Lvl 7 Chansey with max bulk and min offense, holding the lagging tail, with Metronome, Solar Beam, Healing Wish, and Fling.

## Chart

Once we have a tool to calibrate we can get an idea of the randomness and range of the frame rate, especially over longer periods of time. We should then try and get all likely battle seeds from a given initial seed/time for a period of time following it, and determine the odds of success for a given strategy. We have tools in compass safari to determine if a seed could be successful. Then we want to statistically determine what time gives us the best odds of landing on a successful battle seed.

## Compass - Safari

Once we have identified a target, we want to identify what seed we have hit by analyzing the results of random chance. The most prominent will be how many times a pokeball shakes, but critical bait or mud can also be used.

## MacheteG

Once we have identified a seed we want to know if there is a sequence of actions that will lead to a successful result. Machete will simulate a certain number of turns into the future to try and identify success cases.

# Plan details

This is details for the current plan. Things we have already implemented might be removed from this list.

## Metang Pre-run information
* Determine how long it takes from game start to verify seed and reach the place to encounter metang and pull up the sweet scent button. This will be our minimum delay in the chart.
## Compass Metronome
* Reliably determine paths from seeds
  * Verify that our seed generation logic correctly generates paths for a specific move.
  * Update gdb script so that we can output roll and battle message data for a seed and write to a file.
  * Find a way to verify seed path generation logic using this data.
* Be able to search for a seed in a time frame given some initial parameters and the path
* Calibrate soul silver around the 5 minute mark and 10 minute mark and collect data. Also attempt to hit specific delays.
## Chart
* Use data from the SS calibration to determine upper and lower bounds for frame rates, and the statical likelihood of hitting a given battle seed from an initial seed (Such as the "average" frame rate).
* Adjust our chart implementation to store seed results generated from this new method (our current method assumes a flat frame rate, but we want to cover a range).
* Create a better statistical strategy of finding the best target battle seed delay based on the data from compass metronome and our previous statistical analysis.
## Compass - Safari
* Verify the compass is accurate using gdb+MelonDS
## Actual Metang Runs
* Make some attempts to hit the initial seed and get into position. For the first handful of attempts at least, we want to make a full attempt even if we miss the initial seed, and try to identify what battle seed we hit so we have an idea if there is a significant difference in frame rate or an offset of some sort from our metronome compass calibrations.
* Once we feel confident that our timing is correct, we should start making attempts where we reset if we do not hit the initial seed.
