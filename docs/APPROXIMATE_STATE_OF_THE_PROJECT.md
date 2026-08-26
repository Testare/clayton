## Current state
Since I am sharing this publicly, this is my attempt to share the current state of the project.

While most of the tools are built, they have a foundational flaw. When first built, I assumed that delay increased once every 1/30th of a second more or less exactly. Then 1/60th. Then I read somewhere it was 59.345 FPS or something like that. Then experience has taught me the somewhat obvious truth - The frame rate is approximate and it fluctuates. With this, a lot of the tools need to be reworked to consider this.

So for the first step we need to get an idea of how the frame rate actually behaves. For this, I have been focusing heavily on getting metronome compass working, using it in the "Metronome Compass Testing.ipynb". I'm using this and EonTimer to try and figure out an approximate range of frame rates, and especially how frame rate might different between delays of different lengths. This is important because to confirm the seed, get into the Safari Zone and perform the advances to reach the shiny all take time, and if we want to hit a target delay with a high probability of success it'll take significant amount of time, which increases how much the variable frame rate can impact the seed we hit.

Once we have that data, we can hopefully do statistics well enough to generalize about the frame rate: Create a lower and upper bound of the number of frame advances given the time elapsed since the initial seed, as well as a way to determine an estimated probability of hitting each seed in that range.

Then, we'll have to figure out how to re-implement chart. It is currently based on the idea that the frame rate is fixed, but we need to make it take this newfound range of possible frames into consideration.

One last piece of information is we need to get an idea of how long it takes to get into position so we can set a minimum for this elapsed duration. Once that is done, we can try and find a good target for our battle seeds.

Finally, Machete and its related tools will also need to be reworked not to only look at seeds on a fixed framerate, but on this variable frame rate. Once that is complete, I think our tools will be in good shape to actually start attempting to catch the shiny metang.

## Current concerns

There is one thing I am worried about - Differences between the frame rate in Blackthorn City and in the Safari Zone. I do not know how to correct for this currently if there is a large difference.
