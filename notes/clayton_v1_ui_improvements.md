# Feedback 2

## Metronome Compass - New Run 
* Emoji should be forward hand pointing up, not backward hand pointing up. It should look like someone wagging a finger.
* Save run popup:
  * Remove the "Timer calibration (signed ms)" field - This is taken from the Vector ms field.
  * The "Advance recipe" fields aren't needed in Metronome Compass, we don't need to do any chatot flips since we don't care what advance frame we land on. We only do elm calls if we need to identify the seed.
  * The "Run save. Start another run?" prompt is sort of jarring (see screenshot). Maybe make 

## Safari chart - Find Target
* Criteria should include options like the "machete-50-X" options. We might want to add fields based on selected criteria, like number of Machete turns, or "survived X turns without fleeing" and we input the number of turns.
* Search from should default to 180.
* Should not use the terminally "Canon map". Should say something like """Compute chart".
* Build canon map does not have any noticeable progress bar, or it isn't working when I click it.

## Safari Compass - New run
* Seed B does not have the guide that explains what the letters of the path mean
* It also does not display seeds in range. That might be because I don't have a model yet.

## General
We should include a standard model. Just copy the one currently in this directly for now.

## Still need to test

<Still need to test calibrating models>


# Feedback 1

<!-- Implemented in app/web/index.html (see git log). -->

* Add a couple emoji next to each tool category?
  * Metronome compass - Finger pointing up + compass emoji
  * Safari chart - Tent + Map emoji (Or perhaps a safari animal?)
  * Safari Compass - Tent + Compass emoji

* "Save Run" button should be in the header, next to "Reset run"
* I don't like the UI elements in Seed A hiding before "Generate" is clicked actually, I think they should be there, just disabled and the table should be empty.
* With the Seed A section collapsing, I might need to rethink having Seed B be a separate section to the side. Part of me thinks Seed A section should not collapse so that users can review it, but the important detail is surfaced in the generated summary... And it's not likely that they'll need to change seed A other than reseting.
  * In that case, I think Seed B should be NOT be to the side, but rather it can be a faded header below Seed A while it is being populated, then obvious its UI elements can be populated once Seed A is selected.
  * When "Change seed A" is clicked, the previous details for seed A should still be displayed, with some sort of "Keep this seed A" button, so that if "Change Seed A" is accidentally clicked the user doesn't lose their progress.
* While the magikarp level field is selected, "M" or "F" keys should toggle the gender, and "Enter" should start narrowing.
* Big UX issues with Seed B
  * You can't see the history of inputs you've given. This can make it a little confusing when it asks a question like "Did it hit?" and you aren't sure which move it is talking about. I'm not sure how you would solve it, but make an attempt and see what we can do.
  * Also, the Input field loses focus after you give an input.

