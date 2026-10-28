* DONE (2026-10-28) URGENT FIXES:
  * Can't open battle compass because stopwatch isn't input - That should be an input during battle compass, not during configuration.
    * The reading is no longer a configuration `hard_error`, so Start Run is reachable; the run
      page takes it and Start is gated on it there, with a reason naming it.
  * Can't input Cresselia's beginning parameters during configuration (HP, status conditions)
    * When species is a roamer, we should disable/hide the target advances and vector ms field, but show fields for HP and status conditions (For now only support "No status" or "Paralyzed")
    * Configure now has "What it walks in with" (HP + status, none/paralyzed only) for a roamer,
      and hides Advances, Vector ms and the starting advance frame.

* Messaging on the holding still is bad: "Do not switch voluntarily." The actual expression should be "Do not switch while <target> is not trapped." If target has been trapped with mean look or shadow tag, switching is totally safe and important.
* Messaging on a pokemon with mean look not outspeeding should be RED and block using compass. Same for party members that do not have a means of trapping the opponent.
* One thing we need to figure out is how to handle roamers that are already asleep at the start of battle Since RNG won't tell us how long their sleep duration is at the beginning. Maybe we should drop support for initial sleep for now and figure 
* Have a drop-down of supported species for each profile, instead of having the user type the species name in. Then adjust the level field based on the legendary chosen. We validate the level already, why require the user to type it in? 
* When the path doesn't match a seed, the button to expand second also increases delay. We should create a "Expand both" button that does this, and change it so that the one to expand seconds only expands seconds.
* Change notes default height to 4 lines in glass.
* When the page is re-rendered, such as when hitting generate, the notes in glass reverts back to default height.
* Do not show terrain or already-caught prompt unless the user chooses the relevant ball
* Normalize capitalization in configuration menus
* Have the ability to "cache" a single battle compass run to resume later; makes bug fixes easier.
* Loading from path breaks for switch tokens?
* Deferred: Rethink "Only the RTC second is still in doubt" message 
* Deferrred: "Calculating path to frame" not working for platinum target when we hit key seed. Need to think how to message this that is flexible for journal flips or chatot flips.
* Deferred: Figure out how we'll handle roamers.
