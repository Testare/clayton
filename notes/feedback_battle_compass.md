* DONE (2026-11-04) Two interview questions with no right answer (the Dialga run):
  * Interview does not understand the "must recharge" requirement of roar of time, and asks for
    dialga's move on the following turn.
    * The snapshot now publishes `target.recharging` and the interview settles the turn as
      `Erch`, below the sleep case to match the ROM's before-move walk. Nothing can be asked:
      no selection roll is spent, so every candidate renders that one token.
  * Interview asks if discharge paralyzes an already status'd target.
    * `move_info` now publishes `secondary_cannot_show` and both secondary questions drop out.
      `sim._visible_tokens` was already suppressing the `~` for it, so the two turns rendered
      identically and "Yes" eliminated every candidate.
  * (This block is already archived as Feedback 8 in `feedback_battle_compass_old.md`.)


* DONE (2026-11-06) Against a roamer, if they are not currently trapped all actions other than mean look should have a warning icon that explains target is not trapped and will flee if mean look is not chosen.
  * The snapshot publishes `roamer_untrapped` (`sim.roamer_trapped_at_selection` read backwards)
    and every action chip but the trapping move carries a ⚠. Marked rather than disabled: a
    capture-ball throw really can win the turn — the battle ends before the escape resolves — and
    a player who has already lost the trap may want to spend the turn rather than abandon it. The
    reasons are per action KIND, because one generic sentence is wrong about the ball and about
    the switch, and the state itself is said once in a banner above the chips.
* DONE (2026-11-06) If the roamer is not trapped, it will always try to flee. If we use mean look, it will fail to flee, if we don't, it will. We don't need to ask in the interview what happened.
  * The interview states it instead of asking, gated on the new per-slot `applies_trap` (Mean
    Look, Block and Spider Web share effect 106, so the flag is asked rather than the name
    matched). Settled ABOVE the sleep short-circuit, because an escape is an ACTION while sleep
    belongs to move execution — a roamer selects and leaves while fast asleep [verified:
    mesprit2.jsonl T9-T11]. The Speed half of "lands first" is guaranteed by configuration now
    rather than checked per turn; see the next item.
* DONE (2026-11-06) Messaging on the holding still is bad: "Do not switch voluntarily." The actual expression should be "Do not switch while <target> is not trapped." If target has been trapped with mean look or shadow tag, switching is totally safe and important.
  * Reworded, and the reasoning is in `targets._switch_advice`: while the roamer is untrapped it
    has already chosen Escape and a switched-in Shadow Tag does not stop it [verified:
    mesprit1.jsonl T2], while a trapped roamer chose a move — so that switch costs the trap and
    nothing else, and whoever comes in re-establishes it on their first action. Only emitted when
    every member can trap, which is why the second half reads as a cost rather than a risk.
* DONE (2026-11-06) Messaging on a pokemon with mean look not outspeeding should be RED and block using compass. Same for party members that do not have a means of trapping the opponent.
  * `targets.trap_errors` carries both rows and `Hunt.hard_errors` extends with it, so the
    readiness panel renders them in its danger notice and `hunt_session_start` raises on them —
    one list makes it both red and blocking. The speed TIE blocks with them: a trap that holds
    half the time is not a trap. An UNKNOWN verdict never blocks (a Speed missing on either side
    is a half-configured hunt, and refusing a run over a number the player cannot look up is how
    a roamer hunt becomes unreachable).
* DONE (2026-11-06) One thing we need to figure out is how to handle roamers that are already asleep at the start of battle Since RNG won't tell us how long their sleep duration is at the beginning. Maybe we should drop support for initial sleep for now and figure
  * Dropped, per your lean. `models.OPENING_SLEEP_PROBLEM` refuses it and the run page's status
    menu no longer offers it. The assumption was the problem rather than the blank: it defaulted
    an unknown counter to the maximum of 5, and every prediction from turn 1 reads that number,
    so a guess is a confidently wrong run that eliminates the true seed on the turn the roamer
    wakes. Sleep is the only persistent status that is a state *plus a number*; paralysis, poison,
    burn and freeze are read correctly or not at all. `hunt_session_start` also re-checks the
    opening state after applying `params`, which was the one door left open.
  * Dropped rather than removed: `opening_sleep_turns` still round-trips and its tests still pin
    the plumbing, so lifting this is one check rather than a feature. **What is still unsolved is
    your actual question** — there is no way to learn the remaining duration, so the only routes
    back are (a) let it wake before hunting the seed, or (b) model the run as a branch per
    possible duration and let the wake-up turn identify which. (b) is real but is a candidate-set
    multiplier, not a small change.
* DONE (2026-11-06) Have a drop-down of supported species for each profile, instead of having the user type the species name in. Then adjust the level field based on the legendary chosen. We validate the level already, why require the user to type it in?
  * `targets.supported_options` renders one row per encounter and `hunt_readiness` publishes it,
    game-filtered. Picking a target sets the level with it; the level input stays, read only, and
    goes back to editable for a species the table does not recognise. The label disambiguates
    rather than decorates — the Lati twins are each on file at two venues, and the Giratina formes
    differ in ability and nothing else a label could show.
* DONE (2026-11-06) When the path doesn't match a seed, the button to expand second also increases delay. We should create a "Expand both" button that does this, and change it so that the one to expand seconds only expands seconds.
  * `hunt_session_widen` doubles the frame range when handed null, and the seconds button handed
    it null. It passes the current frame window explicitly now, and "Expand both" is its own
    button that says plainly you will not learn which axis admitted the seed.
* DONE (2026-11-06) Change notes default height to 4 lines in glass.
* DONE (2026-11-06) When the page is re-rendered, such as when hitting generate, the notes in glass reverts back to default height.
  * Both at once, because the second is what makes the first safe: a `ResizeObserver` remembers
    the dragged height for the session and the render re-applies it, so four rows is a starting
    point rather than a setting. The 180px floor came down with the default — it was also what
    made dragging the box smaller impossible.
* DONE (2026-11-06) Do not show terrain or already-caught prompt unless the user chooses the relevant ball
  * `balls._RULE_INPUTS` declares which `ThrowContext` fields each conditional rule reads,
    `list_balls` publishes it per ball, and the page gates both prompts on it — by field rather
    than by ball name, since the Dusk Ball reads two. The stored answers survive hiding the
    question, so changing the ball back brings the answer back rather than a default.
* DONE (2026-11-06) Normalize capitalization in configuration menus
  * The terrain and status menus were lowercase against Title Case natures, balls and species.
    Both are Title Case now, from one table apiece, shared with the run page — two surfaces
    disagreeing about how to spell "paralyzed" is how a label drifts apart.
* DONE (2026-11-06) Have the ability to "cache" a single battle compass run to resume later; makes bug fixes easier.
  * "Park run" on the run page, a resume offer on both hunt screens, one slot. What is stored is
    the run's HISTORY and not its state, which follows from your last clause: a pickled candidate
    set would carry the old simulation's conclusions across the very fix it was parked for.
    Replaying the turns puts the new model to work on the same observations, and `_replay` already
    refuses a history the model can no longer explain. Three things travel with the turns because
    the path does not imply them — the phase transitions, the spread the run started with (per
    attempt, not the hunt's), and the window actually in use (a widen moves it).
* DONE (2026-11-06) Loading from path breaks for switch tokens?
  * It did, two ways. An `S` token carries the PARTY SLOT while `simulate_turn` indexes
    `state.bench`, and `_action_from_tokens` handed the token's number over as `bench_slot` — so
    a one-member bench raised "bench_slot=2 with 1 on the bench", as an exception rather than a
    contradiction. A Revive was worse: it came back as `replacement`, which is who came in after
    a FAINT, so the turn reached the simulator with no slot at all. Both come back as
    `party_slot` now and `replay_path` translates per turn through
    `sim.bench_slot_for_party_number` — per turn, because an earlier switch has already moved the
    bench. A slot naming nobody is a reported typo with the available slots listed.
* Deferred: Rethink "Only the RTC second is still in doubt" message 
* Deferrred: "Calculating path to frame" not working for platinum target when we hit key seed. Need to think how to message this that is flexible for journal flips or chatot flips.
* Deferred: Figure out how we'll handle roamers.
