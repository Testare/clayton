* PARTLY DONE: Hunt doesn't seem to be saving the seed A +/- delay/second parameter or parity match parameter for platinum hunts.
  — the Python side is ruled out and pinned (`test_app_hunt_platinum.TestTheSeedASearchSettingsPersist`):
  the write lands, survives a restart, and a later Configure round trip does not clobber it. The page
  used to save them only at the end of a *successful* Generate, after two API calls that can raise;
  they now persist on change. If it still happens, watch for a toast on Generate. clayton-6xu.8
* DONE: Next to user HP, display a percentage, rounding down except not to 0%.
* DONE: Next to enemy HP, display the same thing, though if the enemy's HP is 1 exactly change the percentage to a check mark.
* DONE: The pokeball messages for shake checks are slightly different in platinum - It says "Shoot!", not "Gah!"
  — `BattleStrings_Text_ShootItWasSoCloseToo`; the other three lines are byte-identical. The chips
  and `explain_turn` both follow the hunt's game now.
* DONE: Glass's notes section does not match the aesthetic and is too small, even if it is resizable.
  — `textarea` was missing from the `.field input,.field select` rule entirely, so both multi-line
  fields were rendering as browser defaults.
* DONE: It says "frame 0" on platinum hunts that you hit the key seed frame on.
  — `start_frame` defaults to 0 and nothing said so, so an unconfigured venue constant read as a
  measurement. It is now annotated wherever it shows. If what you meant was something else, say so:
  this was the only reading I could verify from the code.
* Deferred: Rethink "Only the RTC second is still in doubt" message
* Deferrred: "Calculating path to frame" not working for platinum target when we hit key seed. Need to think how to message this that is flexible for journal flips or chatot flips.
* Deferred: Figure out how we'll handle roamers.
