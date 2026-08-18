This is a project to create a tool to enable me to increase odds of capturing a pokemon in the safari zone using RNG manipulation, especially ones such as Metang or Beldum with very low capture chances.

## Step 1 - Datetimes from seeds

Step 1 is mapping a key seed to specific times. The sequence of seeds is different for different times, though they are more or less the same within the same year, not including leap-year day. Most of the bits can be predetermined from the seed, but month and day we'll want to create a pre-computed table that takes the top 16 bits and maps directly to a list of possible months+days.

## Step 2 - Calculating possible sequential seeds

Step 2 would be calculating what seeds follow from those times. We should have a minimum delay input from user indicating how long they'll want to confirm the seed and get to the target frame, as well as a maximum delay they are willing to wait each attempt. Seeds will crop up again and again, both in sequence for a given time and for the different times, and being able to reliably copy sequences is going to be important to saving time.

We need to remember that delay increases by 2 every frame.

It should be noted that we don't know exactly what time in milliseconds we hit the key seed at, so except for every 30th frame there are actually 2 possible seeds: one where we're still on the same second, and one where the second has advanced.

## Step 3 - Calculate success of seed

Given a specific Pokemon and a specific strategy (Such as "throw 6 baits then 30 balls", "Just throw balls", "Throw bait and balls except when mud would crit", etc). Might also make notes of when special messages will be generated, such as "X is busy eating", which could help identify if we're on a good seed or not. This can be a separate, optional step.

We also can define different criteria for what counts as success. Obviously pokeball capture is best, but if we can find a range where metang is unlikely to flee before we've thrown out 6 baits, it raises the chance of us identifying the seed and then we can hopefully drive it to success.

I'll need to make sure that I know exactly how the seed advances, what the capture rate and flee rate stages are going to be at each step, how the chance to flee is determined, etc. for this to work.

When running the algorithm, this should probably be done with step 2.

OH NO WHAT IF FLEEING USES A DIFFERENT RNG ENTIRELY? I'll have to think that through.

## Step 4 - Aggregate over seed lists, looking for optimal target
Using some algorithmic parameters, process the sequence of seed success for each given time. For seeds on the same frame, we'll probably weight them by the probabilty of them being the next second: The easiest way would probably be linearly (i.e. Every 1st, 31st, 61st, etc, our chance of success is 29/30 that the second is the same, 1/30 that it is the next second, and weight the success probably accordingly). Then we'll use an algorithm to determine chance of success if we target that frame, such as getting the chance of success from all the previous X frames, the next X frames, and then average them with a normal distribution or some-such. I'm not a statistician, so I'm not sure the right statistical model for this.

## Step 5 - Present ideal target seeds

Find best target seeds for each time, as well as top X (default: 5) overall

# Tools

## chart.py — Target seed charting
Given a Pokemon and a strategy, evaluates seeds derived from candidate datetimes to find optimal target times. Aggregates per-seed capture probability across neighboring frames and ranks results so the player knows the best datetime to aim for. Covers steps 2–5 of the pipeline.

## compass.py — Seed identification
Helps the player determine which seed they actually hit during an attempt. Takes observed in-game events (e.g. metronome move choices, early safari turn outcomes) as input and narrows down the candidate seed list to identify the current RNG state.

## machete.py — Safari capture path solver
Given a starting seed and a SafariPokemon, performs a breadth-first search over possible action sequences (bait, mud, ball) to find all paths that lead to a successful capture. Useful for determining whether a known seed is solvable and what sequence of actions achieves it.

# Other tools

## Seed identifier - Metronome battle
To help with calibration, we should have a tool that can identify what seed you hit by the move metronome, since this has the widest array of random possibilities. We'll have to calibrate for specific wild pokemon. The ideal wild pokemon is a very common encounter in a specific place (guaranteed would be ideal, so we don't need to actually check seed/advances to guarantee it during calibration) who is unlikely to faint from metronome, unlikely to faint your pokemon, a pokemon we can reliably either outspeed or underspeed, and we must be able to use sweet scent to encounter them.
* 
Current ideas:
* Magikarp (surf at blackthorn city, guaranteed encounter, probably won't kill us, but highish speed and low defense)
* Oddish in Ilex forest
* Rattata at sprout tower
* Gastly at sprout tower (in case of nighttime)
* Smeargle at ruins of Alph

## Seed identifier - Safari
This won't help with calibration as much, but during an actual attempt, if you can identify your seed before metang flees, you can adjust your strategy to a successful one, especially if we implement the next tool.

## Seed full safari solver
A tool that, given a specific seed and a list of actions and results already taken, can search for a path that leads to capture.

## Current scope
* Should assume that you are using RNG manipulation to hit a specific seed when loading the game. This will be refered to as the key seed.
* Should generate data files so that progressive steps of the process are quicker.
* You will need some time to confirm the seed and hit the target frame. 
* Tweakable inputs might be needed, like the algorithm for determining the likelihood of hitting seed X given target seed Y. Examples include window size, and whether to use normal distribution or not.
* We will assume that 1 second means 30 frames pass perfectly: While technically there IS a possibility of being on the same second after 30 frames, it makes our lives much more complicated for a miniscule chance.
* Since we're doing a lot of simple calculations on a large number of numbers, getting the GPU involved with calculations would be great: Using shaders for calculations.


## Not currently in scope, but future ideas
## Seed identifier - Full battle
While metronome is the most useful identifier, 

## Step 5 - Seed find any successful path
* Instead of just searching using a given path/strategy, make an algorithm that can potentially solve for a catch using any of the 3 actions, and making a note of all paths that succeed, especially with messages that identify the seed compared to the peers.

## Step 6
* Do step 5 for many seeds, calculating data about if you can guarantee a capture after receiving X message, and comparing these to their neighbors. This seems like a lot more work and it would likely consume a lot of time to do all of those calculations, but for those who don't mind burning a bunch of CPU time, it could lead to even more optimal results and a more interactive play.

## Step X - Not just for safari zone
Might be worth considering not doing this for safari zone, but for all pokemon as well. Given the random chance in selecting moves, enemy AI, move effects, this becomes much more chaotic to try and find success with, but you can also use these things to inform you of what seed you're on. That said, it's also less useful: While some pokemon like Groudon are a pain to catch with risk of them using struggle, you don't have to worry about these pokemon fleeing except for the roamers, and with the roamers, they don't reroll when they flee.
