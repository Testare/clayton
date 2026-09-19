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
