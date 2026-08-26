# TODO

* Restructure compass metronome to handle magikarp and metronome pokemon similarly, and allow metronome user to go second.
* Figure out how to handle things like sleep in our dual context, where we use RNG to determine state for the path one way but the other way we wait until user observes it happening.
* Remove "Move effect" from code - we don't need human readable names for move effects.
* Choices should be number based ideally, instead of typing in tokens directly.
* Move this to "design docs"

## Durable effect rolls
* For moves that have an effect with a variable duration that is pre-calculated, we should keep a tracker in the context for that effect.
* We should create a helper function for these durations on the context object for when the status is applied.
  * In the RNG context, it generates a random number, the formula parameters (offset and modulo), performs the calculation and stores the result in the provided field.
  * In the Interactive Context, we just store the minimum number of turns.
* We should check each turn for these effects. For status conditions that prevent moves, this will be during the move application logic (according to the effect_status.md doc), but otherwise it should probably be at the end of the turn.
* When we check a given status condition, if the duration is greater than 1, we decrement it. If it is equal to 1, we do one of the following:
  * In the RNG context, the status condition ends now, we emit the relevant token, and we set the value to 0.
  * In the Interactive Context, we ask the user if the effect ended. If it ended, we emit the relevant token, and we set the value to 0, otherwise we leave the value at 1.
* For moves with a durable effect, but the number of moves they last is not variable, we do not need rng/interactive context, or even path tokens to indicate when the end. 
  * This includes all the status conditions that effect the whole field: Trick Room, Gravity, and Weather moves all last 5 turns (unless superceded by another weather or trick room reversed), and Mud/Water sport last until the user switches out. These should be tracked similar to how RNG context tracks variable conditions, even in an interactive context.
  * Entry hazards remain until removed by Defog.
  * Moves that target the user's side of the field all have non-random durations:
    * Light screen/Reflect lasts 5 turns unless removed by Brick Break/Defog.
    * Mist/Safeguard lasts 5 turns unless removed by Defog.
    * Lucky Chant lasts for 5 turns on the user's side of the field.
    * Tailwind lasts for 3 turns.
