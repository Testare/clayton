
* Loading from path has trouble with turns pokemon fainted because the simulator picks a different pokemon than I did. e.g., "P0E4hX4" fails because the simulator predicts "P0E4hX1".
* DONE (2026-11-08) I think encore is throwing things off. An encored pokemon does NOT roll to determine the move it uses - It doesn't need to. If it is encored into a move with no PP, encore ends immediately I believe. Normal paralysis and stuff can still happen though.
  * **You were right and this repo's notes were wrong, with citations.** `notes/ss_rng/effect_status.md`
    carried a "correction" claiming the skip was the player's side only: an Encored wild has every
    other slot marked invalid (`CheckInvalidMoves`) and then still rolls `validMoves[RandNext % 1]`.
    Every clause of that is true and the conclusion does not follow. `COMMAND_SELECTION_SELECT`'s
    `PLAYER_INPUT_FIGHT` case (battle_controller_player.c:431-456) runs for EVERY battler — the
    loop at `:319` is over all of them and the branch is not player-gated — and an `encoredMove`
    fills `moveSlot`/`moveSelected` from the Encore and routes to `COMMAND_SELECTION_WAIT`
    instead of `COMMAND_SELECTION_MOVE_SELECT_INIT`. Only that third branch shows the move menu,
    and the roll lives inside the task it starts. `% 1` is what would happen *if* the menu were
    reached; the Encore branch is what stops it being reached. So: **no selection roll**, one
    advance cheaper per locked turn — which is exactly a drift that compounds over a lock.
  * **And the same step costs a ROAMER its escape.** `TrainerAI_Main` holds both the four
    `TrainerAI_Init` rolls and the escape decision, and it is called from inside the same menu
    task. An Encored roamer never starts it, so it cannot decide to flee, trapped or not, and its
    turn costs nothing. Reachable: a party can carry Encore and Cresselia is a configured target.
  * The 0-PP release was already right — `MON_COND_CHECK_STATE_ENCORE` re-checks the move before
    the counter, zeroes `encoredTurns` and falls into the release branch on the same tick, so the
    lock is gone before the next selection. Pinned already, and now so is your third point: the
    before-move walk is downstream of selection, so sleep, flinches, confusion and paralysis's
    `% 4` all still apply on a locked turn.
  * Separately, and found on the way in: the lock also forces the move at EXECUTION time
    (`FightCommand`, :1861-1896), which is why Encore on a Regirock that had just used Superpower
    forced Superpower on the Encore turn itself even though the roll had already picked something
    else. Both halves are modelled now.
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
* Deferred: Rethink "Only the RTC second is still in doubt" message 
* Deferrred: "Calculating path to frame" not working for platinum target when we hit key seed. Need to think how to message this that is flexible for journal flips or chatot flips.
* Deferred: Figure out how we'll handle roamers.
