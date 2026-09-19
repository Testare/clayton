## Profile
* Change error messages
  * "This metronome user can't be created" -> "This metronome user cannot be used in metronome compass yet"
  * "The metronome user won't be suitable for calibration" -> "You might experience more errors in metronome compass"
* To be clear, the user should be able to create whatever metronome user they want - They just won't be able to select them in Metronome Compass

## Expedition
* When Pokemon is selected, safari area should be limited to only areas where you can find that pokemon
* If that pokemon has block requirements (Like Metang), the safari block scores should display how many are required (Like changed the titled "Peak (required: 56)") and turn red if the number required is less than the number put in. Our in-house pokemon finder solution for Safari Compass/Seed A Advances should error if requirements rae not met
* I've changed my mind - Remove the configuration for number of chatots, it is more confusing and catching chatot is much easier than most of the effort needed for this project.

## Import/Export
* We can import/export models, expeditions and profiles, which is good.
* We should be also be able to import/export compass and safari runs as jsonl files. When running export, we should prompt if they want to export all runs, all runs except excluded, or to manually choose which runs to export, where we can add a temporary "export" column with checkboxes have a banner similar to the "save changes" banner to "Export selected"

## Find Target
* Once agin, the "top ranked" only has a success chance of 28.5%, but the initial time for a different time (2000-01-01 14:00:11) is 28.6%. Plase make sure ranked targets is truly finding the best target. 
* The table for ranked targets and best targets refers to initial time as "Boot time", we should not change some standard terminology.

## Safari Compass - New Run
* The "Skipped nearer frame(s) with an ambiguous margin" messaging is confusing
  * For Seed A 0x0B0E02CC, I input KPK, and apparently it found a metang 5 frames away so it is only doing 5 elm calls, but it output "(skipped 6 nearer frame(s0 with an ambiguous margin)", which is pretty confusing.
  * More importantly, I chose an aim for a target of 300 frames, and it actually gave me exactly 300 frames, but it says it (skipped 2 nearer frame(s) with an ambiguous margin). How could it have skipped frames when it is exactly on target?
  * Explain to me why these messages were what they said.
* Seed advances should output the user's calculated current frame when it is found
* After determining seed advances, Seed B input field should be focused automatically
* When widening search window, default to 1 second instead of 2.
* Once again I'm having to scroll down after inputting a path change in order to see the seed table.

## New Feature - Flee flags
* This feature is less UI focused than library focused perhaps, but it would be nice to have a tool to help prevent metang fleeing while we're still trying to identify it or find a machete path.So I'm thinking of introducing "Flee flags". Please create a bead for this idea, and once you've implemented and commited the rest of the feedback get started on it.
* When there are 5 or less seeds remaining in the Seed B candidate pool for Safari Compass, we start calculating these flee flags
* We look ahead 3 turns for each remaining seed, sort of a mini-machete, and gather information for each choice. If the pokemon is guaranteed to flee in 3 turns if the user throws a ball here, for example, we could put the flag "F03", or if it will flee in 2 turns if the user throws bait, "Fb2". If it is guaranteed to flee no matter what you do, we can just output "F2" if it will flee in 2 turns, or "F" if it is going to flee this turn, etc.
* We add a column for "Flee flags" to the candidate seed table and add these there. If there are multiple we can separate them by commas ("F03, Fb2, Fm2").
* In the table, each flag should have a tooltip that explains what they mean (For example, hovering over "F02" should say "<Pokemon> is guaranteed to flee in 2 turns if you throw a ball")
