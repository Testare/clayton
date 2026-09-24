## What is Clayton

Clayton is a collection of tools focused on helping create successful capture encounters within the Johto Safari Zone in Pokemon HeartGold/SoulSilver.

## What does that mean

Most RNG manipulation focuses on the pokemon selection - What pokemon you want to find, and its attributes (Shininess, IVs, etc). This guide and tools assumes you're already familiar with how that works, but if not, you can find other guides online pretty easily. ([I used this one](https://www.smogon.com/ingame/rng/dpphgss_rng_part1))

While these guides manipulate the seed and advances to control the RNG that generates pokemon, this tool is focused on another relevant RNG state - The random encounter state. While not the most important in 99% of cases, where you're pretty much guaranteed to capture if you prepped well, when you're in the Safari Zone this matters **significantly**; Even the easiest pokemon to catch in the Safari Zone is far from a guaranteed capture, and this state is what determines that success.

This state is generated using pretty much the same formula as the RNG state as the pokemon manipulation one, but is seeded not when you load the game, but when the encounter starts, and is a lot harder to hit since frame rate in the game is pretty variable. 

Luckily, you don't have to hit an exact frame. While sometimes the odds of capturing a pokemon in the Safari Zone are a bit nightmarish, they aren't anywhere near as bad as the odds of hitting a shiny pokemon. This tool helps us use data to determine timings where seeds are more likely to be successful, to identify the seeds we actually hit, and determine how to manipulate the RNG state from that seed into a successful capture (if possible).

## Disclaimers

This tool is very much in its infancy, so I hope you'll be patient with any issues that you find.

1. I spent months of work working on these techniques specifically with the goal of catching a Shiny Metang myself, and I accomplished it using these tools (are at least the prototypes for them). These tools might not be as suitable for other pokemon, or as flexible as you might want.
2. Our standard statistical model is far from perfect. I'm trying to release this in its current state to help people as early as possible given the impending shutdown of Pokemon Bank, but the model would benefit from having lots more data.
3. Given the time crunch, I leaned heavily on AI tools to help me make large code changes quickly, and I know some parts are not quite perfect. In addtion, since I'm not a great statistician I also had to rely on AI to determine the statistical math. 

Given these disclaimers, I would love help from the community!

1. Tell me about successful/unsuccessful uses of the tools!
2. Share data with me from your expeditions! Compass runs, hardware details, etc, so I can build a better standard model.
3. Let me know when you encounter issues with the tools, or what features you would like to see!


## Possible future work
* Finding a regular encounter seed so you can save your rare balls for when you know you'll be successful (Identifying the encounter through in-game RNG events, then determining how to manipulate the RNG state until a ball's success rate is perfect)
* More metronome compass support (Fix moves, support other metronome users better, maybe support locations like Slowpoke well)
* Extending to work with other games (DPPt Great Marsh especially, since the code is likely similar)
* Finding a battle seed RNG for speedrunning


