I want to create a suite of tools to help us verify that our metronome compass is perfectly accurate.

One of these tools will be a GDB python script to force a specific battle scenario and play it out until Magikarp or the metronome user faints.

# Automation

The script should take some initial set-up, and be given a file to read seeds/keys to test. It will go through this file line by line, running a battle simulation on an emulator and generate an output for each line and append it to an output file.

It can use curl to call our script that is set up to use key presses for input. It will need to do this to press "A", which should be pressed twice (with a slight delay between them) to use metronome. It can also press the F# keys (Like F3) to load save states, including the state at the start of the battle, allowing the script to override the seed to the one indicated by the input file.

It will then simulate the battle and watch each call to BattleSystem_Random, similar to how utils/gdb.py does, and collect the results into an object, sending inputs to the program to click A when needed. When criteria for the battle ending is met (One of the pokemon faints or is forced out, or if 10 turns have passed), it writes this object out to a file.

If something goes wrong with the automation, it will share an error message, indicate how many lines of the input file were successfully parsed, and then abort the run.

We also want to have some delay built in so that the user can interrupt the automation at some point if they need control of the computer back.

# Inputs
* What save states correspond to which key presses. For example, F3 will load a battle with a Level 15 magikarp.
* A file with a list of input keys separated by new lines.
* URL to where to send automation commands.
* Output file to save each result.

## Input keys
Input for each battle should be a simple string "key". This key should contain all relevant info for the test, given p0 circumstances.

* Seed
* Magikarp Level - Especially important if magikarp can or cannot use Tackle
* Known moves - Whether it should be "Only metronome" or include the other p0 options.
* A metronome override value for the second metronome use. This is not ideal, but I think trying to find seeds where the same move applies twice might be difficult, and many of these would find this valuable to test.

I think the format should be each parameter separated by a `#`. The first two parameters should be seed and magikarp level, which will always be needed. The remaining parameters are optional. If there is a metronome override, there will be another parameter with an "M" followed by the move number. By default we'll only use metronome, but we can add a paremeter of "+" to indicate we should include the other p0 moves (Fling, Solar Beam, Healing Wish) as known moves.

`<seed>#<magikarp level>(#<metronome override)(#-)`

Examples:

* `BAADF00D#15`
* `BAADF00D#7#+`
* `DEADFOOD#2#M34`
* `ABADFOOD#20#M17#+`

## Output result

Each output result will be a json object. We'll just append these json objects to the file - We can prettify them later with JQ.

Each JSON object should have a "key" field, which would be the input key used to generate the path and run the automation. Then it will have a "rolls" field. This will be an array of arrays. Each inner array starts with a frame name of where BattleSystem_Random was called, followed by at least one number to indicate the number returned by BattleSystem_Random. If the same frame is hit multiple times, the extra times are just added to this array instead of creating a new array with the same frame name.

After the battle ends (Magikarp faints, Metronome user faints, Metronome user forces Magikarp to run away, or 10 turns have passed), these results are appended to the output file with a trailing newline.

Example:
```
{
  "key": "BED0B3D0#15",
  "rolls": [
    ["bellshimmer", 12342, 3532, 23222, 4], 
    ["ov12_something", 65535, 12412, 45421]
    <...>
  ]
}<newline>
```

These results are slightly prettified. It would be nice if they were slightly prettified in the file, but that is not a requirement.

# Updates to F3 presser

Will need to not just press F3, but also some sort of "A" input, as well as being able to load a battle with a Magikarp that is a different level (<15 and >=15), so it will need different F keys as well.

# Details I need to figure out

* Detect when chansey faints
* Detect when opponent is forced out - `BtlCmd_TryWhirlwind`
* Detect when the user is not prompted for input (Just delay a little while after ?? and if we don't hit a breakpoint, send input?)
* How to detect turn end other than "??" for situtations where Magikarp is struggling
