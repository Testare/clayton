# TODO
* Optimize machete_all - See resumed session for details
* compass_metronome (simple vs magikarp) - For now, just narrows down as much as possible using a single metronome move doing 9 advances until the metronome, and rerolling if metronome move is in the do-not-allow list.
* Flow for making the process more clean.

## Flow
Flow will help us naturally choose inputs for the other tools. Create a `flow.py` file. Inside should be a global dictionary variable that maps names to `Flow` class objects, which contain lots of configurations. When the main function `flow(name)` is called, it should check this dictionary for a Flow object. If it is not there, it checks for `./data/flows/{name}.json`, and if it finds it it loads it into the dictionary object from that file and returns it. Otherwise, it inserts a new dictionary object and returns it.

The flow object should have a `save()` function that saves the configuration to the file above. It should also have a `print()` function that prints a pretty description of the fields in the flow object. `reload()` will reload from file. We'll need to be able to create strategy, criteria, and evaluation strategies from their names in order to load flow from file. This shouldn't be too hard to reverse-engineer the names.

The flow object will have lots of functions that are just simple facades over the other tools, using internal configurations and user interaction to populate the inputs.

The flow object should have functions `chart_safari()`,  `evaluate_chart()`, `choose_target()`, `compass_safari()`, `machete_one()`, `machete_all()`, and `machete_jane()`. Most of these just call other tools of the same name, using the internal configuration to construct the input objects. Before we do that, we check if that field has been set yet, and prompt the user to pick an option. For instance, before `chart_safari()`, we would check that pokemon, keye_seed, setup_delay_seconds, and max_target_seconds are configured first. If not we prompt the user for this information. `evaluate_chart()` will internally call its own `chart_safari()` method to make sure that has completed first, and `choose_target()` will call its own `evaluate_chart()` method to get the top 10 and best 10 lists.

`choose_target()` will present best10 and top10 to the user, with them labels t1-t10 and b1-b10 respectively. We prompt the user to pick one, or to input a valid seed number to use (while b1-b10 are valid hex, no seed is possible to be this low, so we are safe to assume there will be no overlap). We will save the initial time and target delay for this target to config.

There should be output messages throughout these messages to help explain what we're doing.

After we have a target seed, we can run `compass_safari()`. If a target has not been chosen, will ask user if they'd like to choose a target, and call `chart_target()` accordingly, or abort. It will also make sure a window size has been chosen. We'll default to using machete_one for the compass evaluation strategy, (might need to make a code adjustment so that is possible). We should make the normal compass_safari return a list of seeds when it finishes, and add a "q" command to quit (prompting to confirm), and we'll save the resulting list of string inside Flow as "target_seeds", as well as "target_seeds_path".

We should also have a `compass_metronome` method. This requires `compass_metronome_histsize` to be configured (The number of compass results to save to aid in calibration, might be set to 0, prompt user to give value if not set). We'll also have `compass_m_clear()` to clear this history, and `compass_m_suggest()`, which will suggest the most likely time we are hitting based on these saved results. For now just stub this out, we'll implement this as future work. Noteable, this will not save the results to `target_seeds` or `target_seeds_path` like `compass_safari` does.

Flow should also have `machete_one`, `machete_all`, and `machete_jane` methods. These will use the target_seeds, aborting if none are set, as well as `target_seeds_path` since we don't want to just save safari context objects in Flow. If more than one are set, `machete_one` and `machete_all` will prompt the user to pick one from the list, presenting a numbered list of seeds. We should prompt the user to pick 

Once this is all done, we should create a second version of the Clayton Metang notebook: The first cell should have all imports and tool global configurations. Then we should divide cells by tool use (chart/compass/machete) using headers, with each cell just having a call to `flow.<method>()` followed by `flow.save()`.

## Compass metronome (complex) notes
We'll need additional information:
  * If metronome sets up gravity, we'll need to factor in moves that metronome can't use during gravity
  * We'll need to identify the randomness of a given move -
    * Does it crit roll?
    * Does it damage roll?
    * Does it make an accuracy check roll?
    * Does it have secondary affect chances? How many?
    * Does it have some other random roll?
  * We'll also need to identify the randomness from magikarp using splash or tackle, but that should be easier.
  * It's possible we can simply create a file/table of possible moves, and have a flag of "currentlySupported" or not in that table for ones where we aren't sure how much it advances RNG.
  * We also might be able to use a python script in the debugger attached to the hgss emulator to force the seed to one that produces that move, then counts how many random rolls the move performs, and save the results to a file. It would require me to manually click metronome.
