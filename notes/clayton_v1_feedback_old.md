(Note to self: bbBbbb001100)
# Feedback 13

## Profiles/Expeditions

* Deleting a profile should not delete related expeditions.
* When importing a profile or expedition that matches an existing one, and we chose to keep both, can we add (2) after the name? Or if that name already exists, add (3), etc.
* When importing runs, change the time saved to the time that the data was imported, maybe with a slight time increase to keep them in import order (Can we add a millisecond to each consecutive time in the data, but hide that millisecond from the display table?)
* Can we add an option to configure profile settings after creation? (Such as name, trainer name, etc.)

## Safari Compass 
* Hitting enter in the Optional look for <pokemon> near advance field should move focus to the New elm calls heard field.

# Feedback 12

## General
* Stop putting "..." after buttons
## Profiles/Expeditions
* The order of the Import New buttons on profile and expedition are flipped from each other. Make them consistent, and probably rename them both to "New" and "Import"
* When I hit "Import expedition...", I get a prompt asking which profile to import the expedition to, then hit "Import..." but nothing happens, it doesn't even ask me to find a file to import.
* I also don't have a way to delete expeditions or profiles. We should have a button on the page for managing profiles to delete it and likewise on the Expedition configuration page (Though obviously with a prompt that asks if we're sure, since deleting an expedition/profile is a big deal. Be sure it includes the details of what will be deleted)
* We also should have a way to mark expeditions as complete. 
  * We should have a button in the "Configure expedition" page next to the Save/cancel buttons for "Mark as complete". If it is already marked complete, change it to "Mark as incomplete"
  * Expeditions marked complete should have a star or checkmark next to their name on the expedition selection page, and should be positioned below the expeditions not yet complete.
  * If we save a run in Safari compass with a successful capture and Seed A matches the key seed, we should ask the user if they want to mark the expedition as complete after they save.

## Clayton Safari Compass
* When I select the text in the widen search box and let go of the mouse outside the popup window, it closes pre-emptively.
# Feedback 11
## Import/Export 
When exporting runs, let's drop the
* When exporting runs from metronome, let's have the default name be "clayton-runs-metronome.jsonl", and "clayton-runs-safari.jsonl". Let's also add profile and expedition into the output names for those as well to help differentiate them.
* Let's drop "target_timer_calibration" as well as "frame_guide" from the run data.
* When exporting/importing, it always defaults to "~/.local/share/Clayton", let's default to ~ instead on linux? (And probably the user documents folder on Windows). Then let's default to the last location the file explorer was opened to if possible.
* There is an option to export expeditions, but not an option to import expeditions.

## Safari Chart
* IT IS STILL NOT SHOWING (2000-01-01 14:00:11, 180003) AT THE TOP RANKED TARGETS, EVEN THOUGH IT HAS P(SUCCESS) OF 28.6%, WHICH IS GREATER THAN ALL THE ONES IN TOP RANKED TARGETS. IS BEST TARGETS AT TIME USING A DIFFERENT ALGORITHM? A CACHING ISSUE? THIS IS A SERIOUS INCONSISTENCY.
  * I am using the "six-bait-then-balls" strategy, and a criteria of "machete-50-turns-after-3-balls" on the range of 180-186 seconds.
  * Top result in chart is 2000-06-27 14:52:54 and Vector ms of 180003.

## Safari Compass
* My feedback about disabling the "(Optional) Look for metang near advance" field when Seed A hits the Key seed has not been applied. In fact, the field should probably be hidden in that case.
* The guide text is a little confusing, I think instead of "(]! = Sweet Scent here)" it should say '(Sweet scent at the "!")'
* The widened search parameters for Seed B should be saved until the seed is saved, so that if we hit "change seed B" we don't have to re-widen the search.

# Feedback 10
## General
* The new UI for Vector ms looks great, the color is just a little too vibrant/orange (Might make people think something is wrong). Can we make it so that it is obviously visible, but not so vibrant that people think there is something wrong with the number?

## Profiles
* I think I need to make a slight amendment - While we might eventually add support for Serene Grace and other abilties (hence the "yet" in the message), we will never support metronome users that do not know metronome, it doesn't make sense. We can either just remove the yet, or treat not knowing metronome as its own category.

## Review data - Export runs
* There is STILL no obvious UI to select each row. I suggested adding a column to the beginning each row with a checkbox for export (there are no problems with the banner showing up), so the user could actuallly select the rows for export, but nothing like that exists, and clicking on the row itself doesn't do anything either. I took a screenshot to help you. This applies to both Metronome Compass and Safari Compass.

## Safari Compass
* With the path observations being below the table now, we can finally see the seed table without scrolling after giving input. But, we should re-order the other elements as well. Basically the order should probably be something like this:
    * Candidate seed table (And the header with the count of matching seeds out of total)
    * The messages about unique seed, with use the "Use this seed" button (When it is visible)
    * Path so far
    * Machete path
    * New Observations Input section
* Since we still can't scroll to the bottom on enter, maybe move the "m mud M mud, crit" mini guide (And the full guide button) to be right under the "New observations" header, and change it to just "New observations - Enter to apply"
* When the user types "u" to undo, it should remove the last element in the "Path so far", not add a u to it.
* When we hit "Change seed B", it should retain the observed path we just had.
* When we hit "Use this seed", if there is a machete path for the seed and the metang has not been captured yet, we should prompt them asking them if they are sure they want to commit the seed when there is a machete path and the <pokemon> has not been captured yet.

# Feedback 9

## Profile
* The following are hard errors, not soft errors, they should prevent metronome user from being used:
  * Not knowing the move metronome
  * Not holding a Lagging Tail

## Expedition home page
* Pokemon name should be capitalized
* "key seed" -> "Key seed:"

## General
I don't know if this is possible, but can we have it so the last 3 digits of Vector ms are a slightly different color, to make it easier not to lose count of zeroes?

## Metronome Compass
* When narrowing ended without a unique seed, the message should be "Path ended prematurely, no unique seed identified. We recommend you reset your run and try again."
* When exporting runs, if I choose "Choose manually...", there is no UI element allowing me to choose runs to export.

## Safari Chart
* When "Rank targets" is clicked, there should be a spinner or loading bar while it loads the chart report. If the chart report is created automatically after the chart is computed, it should show the same ui then.

## Safari Compass
* When we hit our key seed exactly for Seed A, Seed A advances should disable the "target frame" field, with a message that Seed A matches key seed, advancing to key seed advances.
* STILL have to scroll down after putting in the input in Seed B. Maybe the solution is to put the table above the input?
* Got a weird message about "Cannot throw ball, pokemon has fled or been captured" when the cnadidates have all been narrowed down. Took a screnshot. I think it might happen when a seed is eliminated that was previously being used to generate flee flags.
* The full guide sidebar isn't wide enough to see the whole in game message on each row and also see the letter to type. I think it might be okay to make the sidebar a little wider, drop the quote marks around the messages, and allow them to wrap? Or at least give us the ability to resize the sidebar.

# Feedback 8

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

# Feedback 7

## Profile
* Species should be a drop down of pokemon that can learn metronome in HGSS. Species should basically impact all the rest of the fields. It should default to Chansey, the only one we currently fully support.
  * Happiny, Chansey, Blissey
  * Cleffa, Clefairy, Clefable
  * Mew
  * Togepi, Togetic, Togekiss
  * Munchlax, Snorlax
  * Snubbull, Granbull
* Moveset should be 4 different inputs, each a dropdown depending on pokemon species. Serebii.net has the list of possible moves for each pokemon to know.
* Gender should disable invalid options for species when selected, and automatically select one of the remaining options. For example, Mew should automatically select the no-gender option and disable female and male. Likewise, Chansey will disable the male and no gender options, Togepi will just disable the no-gender option, etc.
* Call out that moveset needs to be in order.
* I think that if the user chooses a species other than Chansey, we will issue a warning that metronome compass was built specifically for Natural-cure Chansey, and using other species might result in errors, but we will still allow them to use them in the compass.
* Similarly for abilities, except for the following, for which we will give a hard error and consider the user invalid:
  * Serene Grace
  * Cute Charm
  * Magic Guard
* Drop the requirement for metronome user names to be unique - We'll add the metronome user counter after the name and a # when we want a unique name, such as in the data (So if the name is "Pizza", and they are the third metronome user, internally we'll refer to them as "Pizza#3")

## Find Target
* New chart - Strategy, add a comma in "Six bait then balls" if you're going to use one for "One mud, then balls"
* The sigma you have in the ranked targets table header is capitalized, but the sigma in the explanation is lower-case.
* I just realized using P(Capture) and Sum Capture% is innaccurate when the chart criteria isn't capture. P(success) might be more accurate.
* Best targets at a specific time is mostly just times that are sequentially near the best time, we should try to offer options that are a little less clustered together. Come up with a reasonable idea of how to present different acceptable options that aren't just all clustered together.
* BIG CONFUSING BUG - The best result in Ranked Targets for our current Realshot chart shows a time with a P(CAPTURE) of 28.4%, but the best time in 2026-01-01 is 28.6%.

## Safari Compass - New Run
* A lot of that feedback I gave previously about how to change the focus and operate with enter for Metronome Compass also would help here, such as being able to hit enter on the "roaming starting positions" to generate seeds.
* Seed B:  Full guide sidebar covers the current interface a little. I would prefer that it squish it down some, or that we adjust the UI elements so that the sidebar doesn't cover them.
* Seed A Advances- When hitting enter for elm calls heard so far, the input field loses focus
* Despite hitting "Widen search window" and it telling me about adjusted parameters, the number of candidates in the "0/1371 candidate(s) match" does not increase. We had this problem in the notebook at one point, that the way seeds are selected for the first pass is based off of the standard distribution instead of a simple +/- frames +/- seeds range. We should open a pop-up asking how many frames and seeds we should widen the search area for, and show all seeds within that frame, same as we do for other seed searches in this project.
* Save run - Tag should be saved each time so that it defaults to the last used tag.
* The option to look for a frame "near target advance" should be shown right at the start of the Seed A advances, before the current frame is identified. When Seed A is identified, the elm calls input for this section should be focused automatically, so it should skip this field by default, but it should be available for them to find the frame before the current frame is identified.
# Feedback 6
## Choose a saved target 
* Table has a horizontal scrollbar that makes it hard to select bottom target.
* Don't need "Use this target" button - Clicking row should be enough to select.

## Time picker
* Title change: "Pick initial time for key seed"
* Filter by date should allow partial inputs - Only choosing a month, only choosing month+day, etc.
* Clicking the "filter by date" pops up the calendar dialog, but then it removes focus from the text dialog you just clicked, making it require another click in order to type anything manually, which is annoying. If possible, keep focus on text even with popping up the calendar.
* With no filters, it is only showing 500 of 2464 initial times. This is an anti-feature, please show ALL initial times if no filter is set.

## Metronome Compass - New Run
* When the page is first entered:
  * If metronome user, initial time, or Vector MS are not set, the first empty field of those should be focused.
  * Otherwise, "Roamer starting positions" should be focused
* Clicking "Enter" on Roamer starting positions, +/- seconds, or +/- delay in Seed A should be the same as clicking generate.
* After seeds are generated, observed roamer routes should be automatically focused.
* Hitting enter on observer roamer routes should move focus to elm calls heard. Hitting enter on elm calls heard when there is only 1 candidate seed remaining should confirm that seed for Seed A.
* When Seed A is identified and Seed B section opened, Magikarp level field should be automatically focused.
* When Seed B is identified, the summary shown should:
  * Just like Seed A, do not show a static value for delay, only a delta from the expected.
  * Showing the full magikarp path is nice too, but it should also show a summary of all the metronome moves for that seed so that the user can confirm they hit the seed they expected, like the notebook does (Including the ones observed would be nice too)


## Safari Chart - Find Target
* Translate strategy and criteria names into more friendly names. Some examples:
  * six-bait-then-balls -> "Six bait then balls"
  * machete-turns-after-balls -> "Machete path after N balls"
  * survived-turns-without-fleeing -> "Lasted N turns"
  * balls-no-flee -> "Lasted N balls"
* Default for machete-turns-after-balls should be 5 balls.
* Remove 'e.g. "machete-50-turns-after-3-balls"' from criteria description of machete turns criteria.
* When chart is computing, displaying an ETA that updates after each mdmsh class computed would be nice (Wait until 2 classes have finished computing first before displaying anything)
* While chart is computing I am unable to leave this page - Attempting to do so brings me right back to it. I should be able to navigate away while it computes in the background. It should run in the background and, if the user is not on this page when the computation completes, we can have a toast notification or something pop up saying that chart compute is done.
* That said, it is good I can't change chart while it is computing.

# Feedback 5
## General <Refine before giving to R2>
* It occurs to me that time of day is something I am not properly accounting for. 
  * For pokemon that matters for (Like Murkrow for example), I should probably verify which times of day work for the key seed - Morning, Day, and Night. This can all be checked by default. As a future task we can be intelligent about the checking - We can use data and our understanding of safari block tables to figure out if morning, day, and night allow the pokemon at all, or would alter their encounter rates. For some pokemon morning/day/night might alter the encounters, so we would still have to prompt if 
  * By default, initial times that are not within this range should not be considered, and should be filtered from chart report top times, or Seed B times (Will need to track this for our chart report). If the user chooses one of these times specifically, we should warn them.
  * Times:
    * Morning: 4am-9:59am
    * Day: 10am-7:59pm
    * Night: 8pm-3:59am
## Profile
* It occurs to me that we don't actually care about TID/SID - We aren't doing the shiny-checking logic. So instead we should ask for Trainer Name and Version.
* On Metronme users page, I have a metronome user with a status of "1 warning(s)", but no way to actually see what that warning is. I think it should be rephrased as 1 error(s), and clicking on it should pop up a window with the error message.

## Expedition configuration
* Drop "Required" from Key seed and Key seed advances. Of course they're required.
* Drop the note on "hexadecimal only"

## Initial time picker
I've rethought this a bit:
* Instead of "Pick valid time...", just do "Pick time" for the button text
* I think the date field should be renamed "Filter by date"
* If the user inputs an invalid year (Less than 2000, more than 2099), it should be normalized to 2000 when "Show times" is clicked and the results should be for the year 2000
* There should also be an input "Filter by second", that accepts a numeric value 0-59, and filters results so that only times with that second value are shown.
* The date you input, like many inputs, should be saved and re-used by default. Same with the filter by second value.
* Both fields should be optional - If neither is filled in, show times shows all valid initial times
* Text should be simplified to "Pick a valid time for the key seed - Year does not matter"

## Metronome compass

Looking pretty good!
* Seed A: When seed is selected, do not output the delay for that seed (because that value depends on the year), only output the "delay +0", "delay -4", etc.
* Seed B: The defaults for seed +/- and delay +/- should be 2 and 2000 for this field.
* Seed B: When you click "narrow results", a spinner should be shown while the list of candidates is generating.
* Runs: The runs don't have a display for the notes taken on the runs! Since they might be long, we should have a notes column and, if notes are present on the run, have a little note emoji/icon shown there. We should have it so the notes are either displayed as a tooltip if you hover over the note icon (preferred), or have a pop-up with the note come up when you click it (If easier).
* Runs: When a row is manually excluded, the exclude checkbox looks disabled, implying we are not able to re-enable it. It should not look disabled.
* Calibrate model: When the standard model is selected, it shows "-" for the current active fields, despite the standard model actually having values for these fields.

## Preferences
* Using the in-house frame finder should be the default.
* We should have an option to configure "Safari Compass Machete depth". Default should be 50. There should be a warning that high values increase odds of a match, but also increase compute time exponentially. This preference should be used to determine on the machete runs on a single seed that is done in Seed B of Safari Compass.

## Safari Compass 
### Seed A
When seed is selected, do not output the delay for that seed (because that value depends on the year), only output the "delay +0", "delay -4", etc.

### Advance-frame guide
* Time of day should not be prompted for - Just assume one from the chosen initial time, given the boundaries I mention above.
* When we hit the seed exactly we do not need to search for a frame - Use the expedition configuration to choose the frame automatically.
* There should be no "Use this frame" prompt, once a frame is found we should use it.
* The optional "Aiming" dialogue should be added 
* The advance frame guide should be its own section "Seed A advances", between Seed A and Seed B. Seed B should not be enabled until the advance frame guide is done.
* The previous values for "Elm calls" should populate the input field for the advance-frame guide, not the "Elm calls so far" section, in case the user typed something wrong.
Jane, guide popup should be an actual new window so the user can position it while typing into the thing.
* If the user accidentally inputs a wrong sequence, we need a way for them to change elm calls so far. Add a small button next to Elm calls so far with "Change" on it. Clicking this takes the elm calls so far, moves them back into the input field, and then clears the Elm calls so far value.
* Change "Add" to "Apply"

### Seed B
* The full guide pop-up should actually either be a pane that opens to the right of the UI, or a full window that the user can position on their screen how they like. Having it as a pop-up that covers the usual screen makes it hard to actually keep the guide open while they input the observed path!
* Also, the full guide mentions Jane, which I'm not planning (immediately) to enable for the app. Please remove its mention. Also in the explanation at the top of the guide, Simplify it to "Type the letter for whichever message you see." Also for uncertain result, add "(You know the action but missed the message)" for the ingame message.
* The observed path field loses focus on enter, and the page scrolls up, hiding the seed results. We should automatically scroll to the bottom and keep this field in focus.
* When we run out of candidate seeds, there is no option to expand our serach area.
* The inputs are not filtered from the path so far, and "undo" is not working.
* Just like with the observed elm path, we should have a change button next to the path so far that moves the pat hso far to the input field
### Save run
* Like metronome compass, don't need timer calibration here, use the configured Vector ms.
* Remove "(Optional)" from advance recipe, and drop the line about not used by any fit yet.

### Review Data
* Should have its own tags and tag exclusions
* Also the notes from the metronome compass review data tab about the exclude checkbox and notes.

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

