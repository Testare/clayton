% Clayton V1

# Overview

This is a design doc for structuring the clayton release to the public: As a web page/executable. It does not tackle code fundamentals, or details about using a web page or a downloadable executable, but basic design ideas for the project, such as data structuring, UI pages, user flow, etc.

# UI Pages/Screens

## Expedition Selection screen
Main screen. Should have a list of created expeditions and a "Create new" button. This is the screen displayed on boot/on load if there are no current expeditions. Create new takes you to the Expedition Configuration screen for a new expedition.

## Expedition Configuration screen
Contains all the basic configurations for the expedition: The "key seed" (The Seed A we are trying to hit for shiny), key seed advances, the pokemon we are searching for, which safari zone area we are searching in, Safari Zone block configuration, metronome user details (Optional, but without them metronome compass is disabled), how many chatots they have (0-2) and other things like that. There should be a "save" button, which saves changes on existing expeditions or creates new expeditions.

## Expedition Preferences screen
Contains settings that shouldn't really impact anything largely, but things that users might like to tweak. For example, how many elm calls they prefer after doing the chatot flips (Default is 3), if they'd like to automatically delete targets/models once there are N newer ones, etc.

## Expedition Home screen

The main home screen for an expedition. If a user has expeditions, the last expedition they worked on is selected and this is the first screen that loads. It contains links to all the tools, grouped by categories and sub-functions.

* Category: Metronome Compass
  * New Run
  * Review Data
* Category: Safari Chart
  * Find Target
  * Manage Data
* Category: Safari Compass
  * New Run
  * Review Data
* Preferences

## Metronome Compass - New Run

The equivalent of Sections A, B, and C of the Metronome Compass Calibration notebook. I personally envision it as having Section A on the left (Call that section "Seed A"), with Section B on the right (Called "Seed B"), and "Section C" being a pop-up after hitting a "Save Run" button. Some common things (Such target selection, and buttons to save the run, reset, or cancel the run) could be on a header at the top.

I see it as incrementally enabling UI elements. First the user must select a target in the common section at the top, this enables the Seed A section. When the Seed A section completes, the Seed B section is enabled. Once Seed B completes, the "Save Run" button is finally enabled. 

Everywhere it is reasonable, inputs should be pre-populated with whatever their values were last. Target, REL starting positions, seed selection ranges, etc.

This section requires the expedition to have valid metronome user details in the expedition details, otherwise everything should be disabled and an explanation shown.

### Common section

Target selection should have input fields for initial time and vector_ms. These should be saved to the expedition, so that they default to whatever the user set them to last. There should also be a button to select values from a common target. Once the user has identified seed A, these fields should lock, unless the user resets the run.

There should be buttons to save the run (See section below), reseting the run (Basically clearing the found Seed A/Seed B), or cancelling the run (Returning to the expedition home page).

### Seed A

The Seed A section should have an input field for REL starting positions. It should also have inputs for "search range (delay)", "search range (second)", and an option to only match parity to the key seed delay, then a "Generate" button to generate the list of seeds in that range, with their roamer positions and elm calls.

There should also be some informational stuff displayed, similar to the "Seed to Time" functions in Pokefinder/RNGReporter. Based on the key seed and the REL starting positions, it should show elm call sequence for the key seed and REL positions for the key seed as well, so the user can quickly identify if they hit the key seed. This is not as important for the metronome compass, but for the safari compass when the user is not doing calibrations but only wants to make actual attempts to catch the shiny, this is helpful so they can quickly identify if they hit the key seed. For metronome compass, this gives the user the option to try and catch a shiny instead of proceeding with the run, and it is still good visual parity between the two.

Once the list of seeds is generated, it should display in a small table. There should be an input for REL that filters this list down, and then a section to input elm calls. Hitting enter on the REL input should jump to the section for elm calls, or the user can click it manually.
Below the elm call should be a text display. It starts with saying "Seed A: ??? Advance Frame: ???". Once the seed is identified, it should display "Seed A: <seed> Advance Frame: <List of possible advance frames>". Once both the seed and advance frame are identified, just like the notebook the text should display the number of chatot flips and the elm call resolution, and then the Seed B section should be enabled.

### Seed B

At the top of Section B should be some configurations like in Seed A: Search range delay +/-, second +/-, these won't need to be disabled with the rest of the section. Metronome user details should be in expedition settings, so they do not need to be displayed here.
First inputs should be Magikarp's level and gender. Once those are input and either enter is hit or "Start" is clicked, it generates the seeds and their paths. The top 15 (or less depending on screen space) are displayed, just like the notebook, and we prompt the user with a series of questions. The list of seeds should be above the questions, and then the input field should be below that. Once we've found the seed, output the relevant data into a text area under the input prompt, disable the prompt, and enable the save run button.

### Save Run Pop-up

When the "Save run" button is clicked, a pop-up that has the same inputs as section C, with defaults filled in the same as Section C, and also a text area section for notes. It also displays the resulting data to be saved. It has a final "Save" button that, when clicked, will save the run and then ask the user if they'd like to do a new run or go back to expedition menu. It also has a "Cancel" button that just closes the pop-up without saving or clearing the run data.

### Details on input
#### REL input
I think for REL input, we should ask for input as space-separated numbers (or dots), like we currently do when trying to identify seed A, but there should be a little display under that input that parses it out as "R: E: L: ". When inputting roamer starting positions, we can use a "-" to indicate that that roamer is not available, or just leave numbers off the end. For example, "34 - 7" is R: 34, L: 7, E not available. "- 44" would indicate E: 44, and neither R or L is available.

#### Elm call input
When inputing elm calls, the list of previous elm calls should be displayed above the input. The input should be able to take multiple elm call characters at once and filter out noise, just like in the calibration notebook.

#### Magikarp Level/Gender
The gender field should be radio buttons between male and female, but we should allow typing "M" or "F" while in the level field to toggle the gender radio buttons between male and female. Obviously all letter inputs to the level field should be filtered out.

## Metronome Compass - Review Data

The equivalent of Sections D & E of the Metronome Compass Calibration notebook. Should show data from across all the compass metronome runs, giving us the options to view, edit, delete, or exclude/include certain runs. This view should be like a table, with buttons on the end of each row to perform actions on those runs. We should be able to sort the table by tag alphabetically, chronologically, by deviation from the expected Fb given the current model, and maybe other ways.

### Run view
The default view.
### Tag view
There should be a button to toggle "Tag view" on. Instead of showing individual runs, each row represents a tag, with data about that tag instead (Such as number of runs in that tag, notes, and whether to include/exclude the tag.)
### Calibrate model view
When the user clicks "Calibrate model", this view shows the changes from the currently selected model, with a section for the number of the new model (Just a strict increment of the most recent model), an optional name input for the model, and the option to save the new model.

## Chart Safari - Find Target

Based on the Expedition Workflow notebook's Chart Safari section.

The user first has to select a chart to use, or create a new one. Once they have, they also select a model to use. Defaults to last used options for both. Once they have, they can click the "run calculations" button, and it'll show a detailed progress bar as it creates the canon map, refreshes it, or just validates that it is already filled. If there is already a chart report for that model-canon map pairing, it'll re-use it, otherwise it'll generate one automatically. Once that's done, it'll show top results.

The user can then use another section to choose either one of the top results or the best result for a specific time, and give the target an optional name, then hit "Save target." They can save multiple target from the same chart report. It'll also have a button to "examine target" and it'll make a pop-up with the report just like expedition workflows' chart_check_target_landing() function.

### View - Create chart

Sections to select strategy and criteria. It should give some details about the criteria and when they are useful. Also an option to give the chart a name.

## Chart Safari - Manage Data
A page to manage the various chart associated data - Canon Maps, targets, etc.

## Compass Safari - New Run

Very similar to Metronome Compass - New Run, except for maybe the Seed B section.

## Seed B

Pretty similar to Section B of the Safari Compass Calibration notebook. One note is if machete is run successfully, we should show the full machete-generated path and the previous actions above the input, with the next expected action in BOLD. I.E., if we've already done bbbBbb0321, and machete says mMmC, and we've already thrown one mud since then (and it still matches the seed), it should show bbbBbb0321m*M*mC. If we break from the Machete path, it should be cleared.

# Data
## Profiles
Trainer profiles - Basically a TID and SID, similar to pokefinder. Each expedition has one associated with it. If we support DPPt in the future, we could add that configuration here.
## Expedition Data
Each expedition is sort of the associated data with a quest to obtain a specific pokemon.
### Expedition Configuration
Key configuration details, such as the pokemon we are hunting, key seed and key seed advances needed to find that pokemon.
#### Metronome User details
Optional data, but required to use the metronome compass - new run page. Should include Metronome user species, gender (if applicable based on species), level, moveset, and whether or not he user is holding a lagging tail. It should be noted that because of P0, we might only support Chansey with Natural Cure at the start. Validations should be performed, and a warning emitted if the metronome user is not suitable: Not holding the lagging tail, doesn't actually know metronome, etc. If the user opens Metronome Compass - New Run and the metronome user fails validations, all fields should be disabled and the error reiterated.

## Models
The data models used to figure out how to accurately hit a Seed B in target range. There should be a standard one that ships by default, but the user can create more using the Review Data tabs of Metronome Compass or Safari Compass.

## Targets
A target is an initial time that would hit the key seed, and an associated vector_ms value that should help us hit a good Seed B. This list is initially empty, but is populated in the "Chart - Find Target" page, and can be used in the Compass new-run pages.

## Charts/Canon Maps
Basically a precomputed map of seeds to given success outcomes, associated with a specific strategy and criteria. Can be re-used when models change, and are calculated in the "Safari Chart - Find Target" page. It basically combines the strategy/criteria settings concept with the canon map concept from the notebook.

## Chart reports
Data generated as a pairing between model and chart, showing ideal times and vector_ms values with associated probabilities.
