# Feedback 5
Jane, guide popup should be an actual new window so the user can position it while typing into the thing.

# Feedback 4
## General
* For both the find-target-at-time and the configured initial time for the tools (and potentially other places), we should have a better way to pick time. Perhaps a button next to the field that if you click, pops up a little calendar time picker for picking the date, and once that is done it gives you a table with all the valid initial times for your configured key seed on that date.
* Choose a saved target - The targets table is slightly too narrow, but it just barely hides the "Use" button. In other tables we just have people click on the row, maybe we can just have them click on a row to select it and then have a button for "Use this target" at the bottom (that enables once one is selected). In that case we wouldn't have to widen the table, just remove the use button from each row.

## Metronome Compass
* I can't believe I haven't mentioned this before, but for Metronome Compass on Seed B, we need to be able to specify a seed search range in terms of delay/seconds. Like with Seed A, these fields should be saved.
## Safari Chart
* Find best target at specific time should save the last used input.
* What does the sigma mean in the ranked targets table?
* Edit delay window still mentions canon map. I think you can drop that whole phrase actually, the user doesn't need to know about signatures
* For the individual seed page 
  * "Individual Seeds" should be captilized
  * "delta" column should be <delta>F, to make it a little clearer what it is the delta of
  * Do NOT call it "Cum capture%" (Come on man, that seems like an obvious issue). If anything call it "Sum capture%", or "<sigma>Capture%"
  * Table is slightly too wide for the viewport, can we make it a bit wider?
## Safari Compass
* Roamer starting positions is not saved upon hitting generate. What's more, the +/- seconds, +/- delay, and match parity fields automatically revert to the default values after you hit generate.
* Advance Frame guide has many issues
  * Advance frame guide is NOT optional, as it is important information for the calibration.
  * It should NOT be looking that far in the future for elm calls, it should match the behavior of the notebook, only looking (I think it is about 16 elm calls in the future? Making sure to skip the number of roamers identified)
  * When calls are input, the "sequence so far" should be displayed above the input, and then the input is cleared. This should not be cleared unless they miss their frame (Part of that future work idea)
  * The input should automatically populate from the elm call field used to find the seed
  * "Enter" should be used to input the calls, not requiring the user to take their hands from the keyboard and game to use the mouse.
  * While having support for using a frame from pokefinder might be good (We should have a toggle for that in the preferences), we should also be able to use the in-house solution we have already built to find a target metang.
  * What could be optional is (when using the in-house solution, not getting a frame from pokefinder) having a "(Optional) Look for <pokemon> near advance:" field.
* While I do finally see the seeds in Seed B, the "Observed path" portion loses focus after every keystroke. Like the elm calls, I think observations should only be applied to the path after "Enter" is hit, and the "Path so far" should be displayed above it. Filtering the seeds should be done after enter is hit as well.

# Feedback 3
# Metronome Compass - New Run
* Roamer Starting positions should be saved when generate is clicked so that they default to the last used values when the user starts a new run. Same with +/- seconds, +/- delay, and the match key-seed delay parity.
* Roamer starting positions should have the same validations as the observed roamer routes.
* We should have a button near the Initial time/Vector ms section to choose values from our saved targets
* Save Run 
  * Just like roamer starting position, Tag should be saved and re-used by default on future runs.
  * Also, remove "Samwise" from the default text for Tag.
  * Remove ALL of the Advance recipe section form, including the elm calls.

# Chart Safari - Find Targets
* There is no way to find the best target for a specific initial time, you only see the top ranked targets.
* We should show the name of the model in the "Compute chart" section.
* We should be able to change the delay window for the chart after creation.
* The "Examine target" shows the summary by second, which is nice, but doesn't show individual seeds and their probability+success like the notebook does. This is important for our understanding of how wide the net is. Maybe you can click on a specific second to pull up this report?
* For the Saved targets, is P(Capture) recalculated when we choose a new model? When I examine

# Safari Compass

* We should show the name of the model we're using in the header
* Unlike Metronome Compass, once we identify the seed we need to identify the frame and then provide a guide for the user on how to get to that frame. 
  * We'll need to check if the elm calls are enough to identify the current frame on that seed, if not, prompt them for more elm calls until the current frame can be identified
  * Once the frame is identified, we should save the instructions for how to get to the frame (chatot flips, then elm call path) and show that with the identified seed in the Seed A collapsed blurb
  * We might want to add a "missed frame" button in the future, so that we can help them find their frame again and choose a different metang frame. We should mark any run where this button is used with a flag. Create a bead for this for now, but it's not an immediate priority
* While generally I prefer the UI being more compact, we should have the full-text guide from the usual notebook for Seed B - Complete with the generated messages explaining each letter (For example, mud crit should say "Metang is beside itself with anger!", presuming the safari is for metang). We can try some different ways to make this work in the UI - perhaps there is a question mark icon next to our current guide that opens a new window with the guide for the user.
* Despite having a target AND a model this time, I still see no seeds populated in the Seed B section.

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

