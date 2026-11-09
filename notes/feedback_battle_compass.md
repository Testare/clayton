* DONE (2026-11-08) Resuming a parked thread does not seem to work: Needs a loading bar if it is running, but I'm not sure it runs at all.
  * It ran and then threw. A run page needs half a dozen page globals and resume set three of
    them; `_hrTurn` is the sharp one — it starts null and `hrTurnReset` is what fills it, so
    `hrInterview` threw on `t.action`, `renderHuntRun` threw with it, and the page stayed on
    whatever was there before. A render that throws leaves nothing on screen, which is why it
    read as "does nothing" rather than as an error.
  * Fixed structurally rather than by lengthening the list: the state-building half of
    `huntRunStart` is now `huntRunLoadState` and both routes call it, so a global added there is
    not a thing resume has to remember separately. Three more were missing and each had its own
    silent symptom — `_huntRunHunt` broke End run, `_huntSetup` made a resumed roamer look
    static, and `_hunt` meant a resumed winning run could not be marked complete.
  * And the loading bar: resuming regenerates the candidate window and replays every turn against
    every candidate, so it says so before the slow call rather than after. A failure lands back
    on the Hunts list, and an empty window lands on the setup page where the window controls are.
  * `hrInterview` now fills a null `_hrTurn` itself, so the next route onto that page cannot fail
    silently the same way.
* Loading from path has trouble with turns pokemon fainted because the simulator picks a different pokemon than I did. e.g., "P0E4hX4" fails because the simulator predicts "P0E4hX1".
* Deferred: Rethink "Only the RTC second is still in doubt" message 
* Deferrred: "Calculating path to frame" not working for platinum target when we hit key seed. Need to think how to message this that is flexible for journal flips or chatot flips.
* Deferred: Figure out how we'll handle roamers.
