Once we've gathered enough data with metronome compass, we should create a notebook that is very similar to the metronome calibration notebook that is for the safari compass instead of metronome compass. I imagine framerate will probably be pretty similar for both models, but with us changing loading screens I imagine there might be a slightly different offset, so we should try to calibrate the offset of the model a little with data from the safari.

## Terminology: two seeds, two kinds of "frame"

This distinction matters throughout, so pin it down up front.

**Two seeds, both fixed by *game-frame* (clock) timing.** The game loop runs at ~59.8261 Hz; each tick is a game frame (a "delay"), and we control which game frame we land on with our load/timer precision. That timing produces two seeds:

- **Seed A** — the initial RNG state for the *overworld* stream: which pokemon we encounter, roamer relocation, and Elm phone calls.
- **Seed B** — the initial RNG state for the *battle/safari* stream: move hits, crits, misses, which move Metronome picks, secondary-effect chances, capture success, flee odds, etc.

**"Advance frames" (a.k.a. "advances") are a different axis entirely.** Each RNG call advances a seed's state to the next via the LCRNG formula (`advance_rng`). The *advance frame* is how many times that state has been advanced. Advances are driven by **player actions, not the clock** — so they don't depend on our timing. Example: loading into a given Seed A and using Sweet Scent after 10 advances encounters a L42 Larvitar; after 11 advances, a L44 Metang; after 81 advances, a *shiny* Metang.

**What calibration actually cares about: the game frame (Seed B), same as metronome.** The manual-advancement machinery in Section A (Elm calls, chatot flips, Sweet Scent) walks **Seed A's advance frame** so that we encounter a Metang at all — it is purely operational and has **no effect on Seed B or on the calibration model**. Calibration is still the timer → Seed-B game-frame fit; safari just identifies Seed B through safari-encounter mechanics instead of metronome moves, and may carry a slightly different load-screen offset. So: as long as we hit *a* Metang, the exact advance frame we chose is irrelevant to the model.

**Model-update scope (decided):** safari runs adjust only the model's **y-intercept / β (the offset)** for now; the framerate/slope keeps coming from the metronome (timer) runs. A separate low-priority task will add an optional "full-citizen" mode that lets safari runs also refit the other parameters.

Here are some differences between them, section by section:

## Section A differences
We'll still need to identify our seeds, so a lot of this remains the same, at least at the start. Unlike when doing metronome compass though, where we are guaranteed to encounter magikarp, we are not guarnateed to encounter metang in the safari zone, so we'll need to do some advances, and we should have the tool help us to do the right number of advances quickly.

The first step is to figure out what /advance/ frame we're on in **Seed A** (the advance count — not the game frame/delay that generated the seed; see the terminology section above). This whole subsection is Seed-A advance planning to guarantee a Metang encounter; it does not feed calibration. We should assume that we hit pause within the first 10 or so advances after REL was generated, so if we've already put in some ELM calls we can check if that sequence is unique in the first. If not, we can prompt for elm calls until we have uniquely identified the frame. For example, let's say that REL advanced the RNG 3 frames (no rerolls needed), if the user input PEK and the Elm call sequence for the seed is KKPEKEEPPEKK. Since we're starting on frame 3 (Start at 0, 3 advances from REL), PEK occurs at frame 5 and frame 11, meaning the user is now either on frame 8 or 14, and one more ELM call would be able to uniquely identify it, placing the user at frame 9 on E, or frame 15 on K. That might be a bit confusing, I can explain more if needed, and we'll want to make sure testing here is good.

Once we have identified the frame we're on, we should figure out what advance frame we should be targeting. If we hit our target seed exactly, we should always advance to frame 81 (our true target, configurable), but otherwise we'll need to determine what frame to hit that will have a metang. We have two different ways we could do this: In house, or with pokefinder. I'll discuss that in subsections I've added later.

Once we have the target frame, we need to do (target frame) - (current frame) advances: you Sweet Scent while standing **on the target frame itself**. (This was verified in-game against Pokefinder — pressing on `target - 1` lands one frame early; the implementation was corrected accordingly, so this section reflects the fixed math.) If this is more than 3, to make it quicker we can do "chatot flips". Without explaining too much, each chatot flip is 2 advances, and we can do half a flip just fine (I.e. to do 9 advances, we can do 4.5 chatot flips). However, unlike ELM calls, it is hard to verify what frame you are on from the output, so we don't want to do chatot flips all the way to the target frame, since that can cause off-by-one errors. Instead, we want to leave a margin of at least 3 elm calls before the target to make sure we hit it correctly. To continue our earlier example, let's say we found out the user was on frame 9, and our target is frame 81. We want them to do enough chatot flips to land on frame 78, so they can do 3 elm calls and land on frame 81, then do sweet scent (while on 81) to trigger the encounter on frame 81. The math is: (target frame - current frame - 3)/2 chatot flips, so 34.5 flips here (a trailing half flip).

Finally, to help compensate for off-by-one (-or-more)  errors, we should output what we expect those last 3 elm calls to be, as well as some of the elm calls directly proceeding them and following. I think a good format would be something like PEEEP[KPE]!KEP. We have 5 elm calls preceeding in case they landed early, then the 3 we expect them to see in the bracketes, followed by the exclamation point to indicate this is when they should sweet scent, followed by a few extra elm calls in case they overshot.

It might be worth considering what to do if there is some ambiguity, such as if the result was KPEKP[PPP]!KEP. If they get 3 P calls in a row, they might still be a row early. We could detect this happening ahead of time, and instead of landing 3 calls early we land 4 (then output KPEK[PPPP]!KEP instead), but let's call that a stretch objective, since it doesn't affect our current goal.

### Determining frame: In house (stretch)

It would be nice if we could determine ourselves what frame will have metang for our current seed. We could potentially do this by looking through the source code of pokefinder. We might have to configure how many plains/peak/water/forest blocks we have in the Safari zone in order for this to work. It'll be a decent amount of work for not terribly much savings, and if we want it to be flexible for other safari zone pokemon it might be even more work than that.

### Determining frame: with Pokefinder

We just output the seed, the user can copy it into pokefinder and find the suitable frame, and then paste/type it back into the notebook as input.

## Section B difference

Obviously we'll be doing safari compass instead of metronome compass, so instead of metronome moves we'll be inputing whether we threw a bait, mud, or ball, and whether it was critical or not. I believe the logic for this already exists in safari compass. It shouldn't be too different, but we need to make sure we are checking the appropriate range of seeds. We should also continue gathering the path once the seed is identified. Once metang flees or is captured, we should check a wide area (configurable) around the identified seed to see if there is another one with the same path, both by increasing/decreasing frame and then incrementing/decrementing mdmsh by 1. This gives us an idea of how confident we are in the seed we identified. We should find the nearest seeds up/down in all the 3 seconds (within the configurable range) for up to 6 possible other seeds that match the path, and how far away they are.

## Section C differences

**This already largely exists — reuse it, don't fork a new file.** Safari runs are already persisted separately from `compass_runs.jsonl` in **`data/safari_runs.jsonl`**, via `save_safari_run()` / `load_safari_runs()` in `utils/calibration_tools.py` (there's also an expedition loop-back). That helper already prompts for tag / target timer delay / calibration / fresh_boot / prior_battles / observed path, recovers the calibrated landing `frame` + second-offset `δ`, and records `matched_seeds` plus a single `seed` only when the candidate set narrowed to one. So Section C is mostly wiring the notebook to this existing save (extending the record schema only if we need new fields — e.g. the confidence/neighbor results from Section B). The earlier proposal of a new `safari_compass_runs.jsonl` is dropped.

The saved data should always contain the actual observed path and the identified ("expected") seed we hit. Since the density of identical paths is much higher for safari, we may later add a check for whether a *different* offset of seeds matches our paths more cleanly — a future refinement, not v1.

## Section D differences
Analysis of the `safari_runs.jsonl` data, updated as demands come. May be sparse/blank at first. Candidate contents: confidence that we correctly identified each run's seed (fed by Section B's neighbor search), and comparing the safari `F_b`-vs-`M` fit against the metronome one to measure the load-screen offset — this is the analysis tracked by **clayton-abf.10**.

## Section E differences
Same as section E in the original notebook (review a re-fit vs. the deployed `calibration_model.json`, write only on confirm), plus a flag to optionally fold in the `safari_runs.jsonl` data — set true in this notebook, false in the metronome one. **Decided:** for now the safari data only shifts the model's **y-intercept / β (offset)**; the framerate/slope stays from the metronome runs. A separate **low-priority** task adds an optional "full-citizen" mode where safari runs also refit the other parameters.

## Future

Once this notebook is complete and has been used successfully, we should probably shorten the process and upsert it into expedition, so that it can be used during runs without leaving the expedition notebook.
