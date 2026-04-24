# Complex Metronome Compass — Implementation Plan

## Context

The current `compass_metronome` (simple) takes one Metronome move observation, filters candidates, and exits. The **complex** version tracks RNG state across multiple battle turns — each turn the user observes what move Metronome selected, whether it hit/crit, what Magikarp did, etc., and the compass filters candidates by simulating the full RNG sequence. This is analogous to how `compass_safari` tracks RNG through multiple safari turns.

The key challenge is accurately modeling every RNG call in a battle turn so the simulated state stays in sync with the game's actual RNG state across turns.

## GDB-verified turn RNG sequence (from `notes/gdb/metronome`)

**Battle start**: 4 bellShimmer + 2 ability + 1 flee = **7 advances** (same as safari `start_encounter`)

**Each turn** (observed with a standard damaging move + Magikarp Tackle):
```
BEFORE TURN x4                          # quick claw checks
BtlCmd_Metronome()                      # 1+ rolls (reroll if disallowed/known)
CalcDamage / CheckMoveHit / TryCrit / ApplyDamage   # move execution (variable)
CheckMoveHit                            # opponent's move accuracy
Battle script rand                      # 1
ov12_022585B8 x4 (x3 if Splash)        # post-turn ability processing
ov12_022585B8 x6                        # more ability processing
0x0225e46e                              # flee check
```

**Important uncertainty**: The "x3 if they splash I think" comment in GDB notes needs verification. Getting end-of-turn count wrong means state diverges after turn 1.

## Architecture

### New file: `claytonlib/metronome_compass_full.py`

Rationale: The simple version is a different tool (one-shot analysis). The complex version has fundamentally different state management (multi-turn evolution with undo stack). Follows the pattern where `compass.py` imports from separate implementation files.

The function is named `metronome_compass_full`. The existing simple version should be renamed to `metronome_compass_simple`.

### Data types

```python
@dataclass(frozen=True)
class MoveProfile:
    """Describes how a move consumes RNG during execution."""
    hit_check: bool = True       # rolls accuracy?
    crit_check: bool = True      # rolls crit? (only if hit)
    damage_roll: bool = True     # rolls damage modifier? (only if hit)
    secondary_rolls: int = 0     # number of secondary effect rolls (burn, flinch, etc.)
    high_crit: bool = False      # increased crit rate (Slash, Karate Chop, etc.)
    supported: bool = True       # False = halt state tracking (move name still filters)
    complex: bool = False        # True = uses move-specific logic via match on move number
    gravity_blocked: bool = False  # blocked during Gravity?
    accuracy: int = -1           # base accuracy (0-100), -1 = bypasses accuracy check
    # For multi-hit or other weird moves, complex=True or supported=False

PROFILE_STANDARD_DAMAGE = MoveProfile()                  # hit + crit + damage = 3 RNG
PROFILE_NEVER_MISS      = MoveProfile(hit_check=False)   # Swift, Aerial Ace, etc.
PROFILE_HIGH_CRIT       = MoveProfile(high_crit=True)    # Slash, Karate Chop, etc.
PROFILE_STATUS_ACCURACY = MoveProfile(crit_check=False, damage_roll=False)  # Thunder Wave, etc.
PROFILE_STATUS_SURE     = MoveProfile(hit_check=False, crit_check=False, damage_roll=False)  # Haze, etc.
PROFILE_NO_EFFECT       = MoveProfile(hit_check=False, crit_check=False, damage_roll=False)  # Splash
PROFILE_SET_DAMAGE      = MoveProfile(damage_roll=False) # Night Shade, Seismic Toss (pending GDB verification)
PROFILE_COMPLEX         = MoveProfile(complex=True)      # dispatches to match on move number
PROFILE_UNSUPPORTED     = MoveProfile(supported=False)   # still usable for metronome roll filtering
```

Profile data is stored in `moves.json` alongside existing fields. The `one-offs/populate_moves.py` script iterates through moves and prompts for profile, accuracy, secondary rolls, gravity, and notes. It optionally opens the Bulbapedia page for each move.

```python
@dataclass
class MetronomeBattleState:
    rng_state: int
    gravity_turns: int = 0            # 0 = inactive, >0 = turns remaining
    weather: str | None = None        # "sunny" / "rain" / "sand" / "hail" / None
    weather_until: int = 0            # turn number weather expires
    user_evasion_stage: int = 0       # -6 to +6
    target_evasion_stage: int = 0     # -6 to +6
    user_accuracy_stage: int = 0
    target_accuracy_stage: int = 0
    user_crit_stage: int = 0          # modified by Focus Energy, etc.
    target_status: str | None = None  # "paralysis" / "sleep" / "freeze" / "burn" / "poison" / None
    target_infatuated: bool = False   # from Attract / Cute Charm
    target_confused: bool = False
    # Note: Disable/Taunt/Encore effects on Magikarp tracked separately if needed

@dataclass
class TurnObservation:
    move_name: str                          # Metronome's chosen move
    hit: bool | None = None                 # True/False/None(N/A)
    crit: bool = False
    secondary_triggered: list[bool] | None = None  # per secondary roll (for filtering)
    magnitude: int | None = None            # Magnitude level (1-10) if applicable
    target_fainted: bool = False
    magikarp_move: str | None = None        # "splash" / "tackle" (None if fainted)
    magikarp_hit: bool | None = None        # Tackle hit?
    magikarp_crit: bool | None = None       # Tackle crit?
```

### Move profiles registry

A `dict[int, MoveProfile]` keyed by move number. Most moves default to `PROFILE_STANDARD_DAMAGE`. Only overrides for special cases:

- **No-accuracy moves** (Swift #129, Aerial Ace #332, Magical Leaf #345, etc.)
- **Status moves** (Thunder Wave #86, Will-O-Wisp #261, etc.)
- **No-effect moves** (Splash #150)
- **Moves with secondary effects** (Flamethrower #53, Thunderbolt #85, Ice Beam #58, etc.)
- **Unsupported** (multi-hit, field-setup, two-turn, self-targeting stat boosts, etc.)
- **Gravity-blocked** (Fly #19, Bounce #340, Hi Jump Kick #136, Jump Kick #26, Magnet Rise #393)

We do NOT need to classify all 442 metronome-usable moves upfront. The default profile covers most simple damaging moves. Unsupported moves halt the compass gracefully. Over time, more profiles can be added.

### Turn simulation

Core function — returns new state or `None` if observation doesn't match:

```python
def _simulate_turn(state: MetronomeBattleState, obs: TurnObservation,
                   profiles: dict, known_moves: tuple, magikarp_moves: int
                   ) -> MetronomeBattleState | None | str:
    # Returns "unsupported" string if move profile says supported=False
    rng = state.rng_state
    
    # 1. Before turn: 4 advances
    rng = advance_n(rng, 4)
    
    # 2. Metronome roll (1+ advances with reroll)
    move_num, rng = _simulate_metronome_roll(rng, state.gravity_turns > 0, known_moves)
    if move_name_for(move_num) != obs.move_name:
        return None  # wrong move → candidate eliminated
    
    # 3. Get move profile
    profile = profiles.get(move_num, PROFILE_STANDARD_DAMAGE)
    if not profile.supported:
        return "unsupported"
    
    # 4. Move execution (variable RNG based on profile + observations)
    rng = _simulate_move_execution(rng, profile, obs)
    if rng is None: return None  # observation mismatch
    
    # 5. Magikarp's turn (if alive)
    if not obs.target_fainted:
        rng = _simulate_magikarp(rng, obs, magikarp_moves)
        if rng is None: return None
    
    # 6. End-of-turn processing
    magikarp_splashed = (obs.magikarp_move == "splash") if not obs.target_fainted else False
    rng = _simulate_end_of_turn(rng, magikarp_splashed, obs.target_fainted)
    
    # 7. Update gravity
    new_gravity = state.gravity_turns - 1 if state.gravity_turns > 0 else 0
    if move_num == 278:  # Gravity
        new_gravity = 5
    
    return MetronomeBattleState(rng_state=rng, gravity_turns=new_gravity)
```

### Move execution simulation

```python
def _simulate_move_execution(rng, profile, obs):
    if profile.hit_check:
        rng = advance_rng(rng)
        hit_roll = (rng >> 16) % 100
        # We know from obs whether it hit — validate consistency
        # (We don't need to check the exact accuracy threshold since the
        # observation tells us the outcome, and we just need to advance RNG)
    
    if obs.hit is False:
        return rng  # miss → skip remaining rolls
    
    if profile.crit_check:
        rng = advance_rng(rng)
        # Validate crit observation against the roll
    
    if profile.damage_roll:
        rng = advance_rng(rng)
    
    for _ in range(profile.secondary_rolls):
        rng = advance_rng(rng)
    
    return rng
```

**Key insight**: We don't need to compute exact damage or validate thresholds — we just need to advance RNG the right number of times. The observations (hit/miss, crit/nocrit) tell us which code path the game took, which determines how many RNG calls happened.

However, for **filtering** we DO need to validate: if the observation says "crit", we need to check that the crit roll actually produces a crit for this candidate. Otherwise we'd keep candidates that couldn't have produced the observed outcome.

So the simulation must both (a) advance RNG correctly and (b) validate that each observable matches.

### Magikarp simulation

```python
def _simulate_magikarp(rng, obs, num_moves):
    if num_moves > 1:
        rng = advance_rng(rng)
        selected_idx = (rng >> 16) % num_moves
        # Validate: does selected_idx map to the observed move?
        # Need to know the move order (Splash=0, Tackle=1? — needs GDB verification)
    
    if obs.magikarp_move == "tackle":
        # Accuracy check
        rng = advance_rng(rng)
        # Validate hit observation
        if obs.magikarp_hit:
            # Crit check + damage roll
            rng = advance_rng(rng)  # crit
            rng = advance_rng(rng)  # damage
    # Splash: 0 additional RNG
    return rng
```

### End-of-turn processing

```python
def _simulate_end_of_turn(rng, magikarp_splashed, target_fainted):
    rng = advance_rng(rng)  # Battle script rand
    
    ability_block_1 = 3 if magikarp_splashed else 4  # GDB: "x4 (3 if they splash)"
    for _ in range(ability_block_1):
        rng = advance_rng(rng)
    
    for _ in range(6):  # ov12_022585B8 x6
        rng = advance_rng(rng)
    
    rng = advance_rng(rng)  # flee check
    return rng
```

**Open question**: Does this change when Magikarp faints? If Magikarp faints, there's no opponent turn and possibly different end-of-turn processing. The compass should halt (or at minimum warn) if Magikarp faints, since the battle effectively ends.

### User input format

Interactive prompts per field (like the user answering questions about what they saw):

```
Turn 1:
  Metronome move: flamethrower
  Hit? (h/m): h
  Critical hit? (c/n): n
  Magikarp fainted? (F/n): n
  Magikarp used: splash
```

Also support compact one-line format using distinct characters per category:
- `h`/`m` = hit/miss
- `c`/`n` = crit/no-crit
- `F` = fainted (similar to "Flee" in safari compass)

```
>> flamethrower h n n splash
>> pound h c F
```

And `u` for undo, `q` for quit.

The number of prompts adapts to the move profile (e.g., skip "Hit?" for never-miss moves, skip Magikarp prompts if fainted). For moves with secondary effects, prompt whether each effect proc'd.

After completing (seed identified or quit), prompt whether the user wants to go again. This creates visible history of identified seeds in the notebook output, useful for calibration.

### Undo & caching

Same stack-based approach as `compass_safari`:
```python
cache: list[tuple[str, list[MetronomeCandidate]]] = [("", initial_candidates)]
```

`u` pops the stack. Each turn pushes a new entry.

### Integration

1. **`compass_metronome.py`**: Add `known_moves: tuple[int, ...] = ()` and `magikarp_level: int` fields to `CompassMetronomeInput`. Metronome is always implicit in known_moves — if the user provides it interactively, filter it out. Max 3 additional known moves. Magikarp level determines moveset: level < 15 = Splash only, 15-29 = Splash + Tackle. Level 30+ (Flail) is not supported for now — use `BLACKTHORN_MAGIKARP` target which caps at level 20.

2. **`compass.py`**: Add re-export: `from claytonlib.metronome_compass_full import metronome_compass_full`. Rename existing function export to `metronome_compass_simple`.

3. **`expedition.py`**: Add `metronome_compass_full()` method, following pattern of existing `compass_metronome()`. Add `magikarp_level` and `known_moves` config fields. Save results to `compass_m_history` up to `compass_metronome_histsize` for calibration suggestions.

## Files to create/modify

| File | Action |
|------|--------|
| `claytonlib/metronome_compass_full.py` | **Create** — core implementation |
| `claytonlib/compass_metronome.py` | Modify — add `known_moves`, `magikarp_level` to `CompassMetronomeInput` |
| `claytonlib/compass.py` | Modify — add re-export, rename simple |
| `claytonlib/expedition.py` | Modify — add `metronome_compass_full()` method |
| `one-offs/populate_moves.py` | **Created** — CLI tool for populating move profiles in moves.json |

## Ability restrictions (deferred)

Cute Charm (Cleffa/Clefairy/Clefable) and Serene Grace (Happiny/Chansey/Togepi/Togetic/Togekiss) can interfere with RNG calculations. For now, require the user to use a metronome Pokemon without these abilities (all listed Pokemon have alternate abilities). Add to TODO for future support.

## Implementation phases

**Phase 1**: Data types + move profiles registry + metronome roll simulation + basic interactive loop that filters ONLY on the metronome move name (no post-move RNG tracking). This already provides multi-turn filtering power equivalent to running the simple compass multiple times. Includes "go again" loop for calibration use. Common status conditions, crits/hit/miss should be handled here. Unsupported moves still allow filtering by move name — they just halt further state tracking for that session.

**Phase 2**: Full turn simulation — move execution RNG, Magikarp RNG, end-of-turn RNG. Now candidates track state forward and each turn's filtering uses all observations. Requires GDB verification of exact RNG call counts and ordering (accuracy→crit→damage? miss skips crit+damage?).

**Phase 3**: Gravity tracking (move pool + accuracy modifier), weather effects, stat stage tracking (accuracy/evasion/crit), status condition effects on Magikarp. Add `battle_state` dict. Consider "partially supported" flag for moves that work in common cases but may be inaccurate in edge cases (e.g. Blizzard in snow).

**Phase 4**: Expedition integration, history saving, calibration suggestions, polish.

## Verification

- Unit test: given a known seed, verify the metronome roll matches the simple compass
- Integration test: construct a multi-turn scenario with known seed, verify filtering narrows correctly
- Manual test: use the existing notebook to run the complex compass against a known seed/delay and compare with emulator output

## Resolved questions

1. **Magikarp's level**: Interactive input. Blackthorn City = levels 2-20. Level <15 = Splash only, 15-29 = Splash+Tackle. Flail (30+) not supported → `BLACKTHORN_MAGIKARP` target.
2. **Known moves**: Part of input + expedition config. Metronome always implicit. Max 3 additional. Filter out if user provides "Metronome" interactively.
3. **Magikarp fainting**: Halts compass. User can still observe hit/crit from the killing move before halt. No further turns tracked.
4. **End-of-turn uncertainty**: All GDB numbers need re-verification. Not carefully taken initially.
5. **Tackle accuracy**: 95% in Gen IV (not 100% — that's Gen V). Still needs GDB verification whether the accuracy roll is consumed.

# Logan's feedback

There are a lot of minutia about the randomness I need to triple check before we code, those notes I took were pretty fast-and-loose. But I like the approach of having common profiles for the different moves, as well as profiles with a simple tracker for the number of possible additional affect rolls. The majority of moves are probably simple damaging moves, damaging moves with one additional possible affect, or 100% accurate status moves. This is a very good plan.

## Answers to your questions
1. Magikarp level: Magikarp's level should be an interactive input at the start - I'm specifically planning to use this in Blackthorn city, where Magikarp can be from level 2 to 20. This is a good callout: If used somewhere else, Magikarp could even be level 30+, at which point it would know flail. For now we're going to assume Blackthorn City is used: We might even rename this target specifically to BLACKTHORN_MAGIKARP since we don't want to deal with flail right now.
2. Known moves: This should be part of the initial input and the expedition config, though I am planning to not have any other moves on my metronome user. Metronome should of course be assumed as a known move: If the user provides it in a interactive input step it should be filtered out, and the list should not contain more than 3 moves.
3. Magikarp fainting forces compass to halt before considering any actions taken from the magikarp and any further metronome turns. You can still observe hit (though that should be implied) or crit rolls from the move though.
4. Yes, I am uncertain of pretty much all of my exact numbers in those notes, they were not taken very carefully, they were mostly focused on getting the simple metronome compass working.
5. I think it still rolls accuracy checks, but that is something I need to confirm. That said, Tackle has *95%* accuracy in Gen IV, it's not until Gen V that Tackle becomes 100% accurate.

## Feedback not related to your questions

* For the multiple inputs on one line, I suggest we don't just do a string of y/n since the order of them could be easily confused, and use different characters for the categories. I suggest we use "h"/"m" for hit/miss, "c"/"n" for crit/no crit, and "F" for fainted (Conveniently similar to "Flee" for safari). 
* Also, since this tool will mostly be used for calibrating, we might prompt afterwards if the user would like to go again without requiring the cell to be re-run. This has the bonus of creating natural visible history of hit seeds.
* When using expedition, results from compass_metronome should be saved to flow, up to a preconfigured histsize. We can use this to suggest calibrations.
* Despite my naming in documentation, the function should be called "metronome_compass_full". We can rename the original to "metronome_compass_simple" (or something else, suggestions?)
* For moves that require move-specific logic, we should use PROFILE_COMPLEX. This can defer to a match statement that matches based on move number. We should also add an accuracy field to moves.
* We need to also track moves with increased critical hit rates, probably PROFILE_HIGH_CRIT.
* We also need to track the accuracy of each move. We can use -1 to indicate a move does not perform an accuracy check.
* Moves that affect evasion/accuracy (sweet scent, defog, double team, minimize, ) and critical hit rates (like focus energy) create state that affects future rolls: We'll need special profiles for these. The move acupressure will need extra special consideration: It raises a stat at random, which can be accuracy or evasion.
* For moves that can have secondary affects, we should ask if secondary effects occur/"proc", for the purpose of filtering. This is especially important for moves that can disrupt Magikarp's moves or accuracy.
* Moves that inflict status conditions can impact the ability of Magikarp to perform its moves. I put a subcategory section with ideas of conditions that can affect things.
* Gravity, outside of limiting metronome move pool, also affects accuracy of moves: both for the user and opponent. It's good you're keeping track of the number of turns it is active.
* Some moves are affected by weather conditions, for example Blizzard is 100% accurate in snow, but never freezes in the sun. Since the game state is so complex, we might want to create a simple "battle_state" dictionary that contains flags set/removed/checked by different moves. Sunny day, for instance, can have code like this:
```
battle_state["weather"] = "sunny"
battle_state["weatherUntil"] = currentTurn + 5
```
* I want to be clear that "unsupported" moves can still be input by the user to narrow the seed down: We just can't narrow it down further afterwards.

### Subcategory: Problematic metronome user abilities
There are two abilities that I think can mess with our calculations.

* Cleffa/Clefairy/Clefable: Cute Charm
* Happiny/Chansey/Togepi/Togetic/Togekiss: Serene Grace

Cute charm has a chance to cause infatuation when Magikarp hits with Tackle, and Serene grace doubles the chance of secondary effects.

We can make things simpler by requiring the user to not use these for their metronome users, as all these pokemon have alternate possible abilities. Let's push to off as a later requirement, make a note of it in the TODO.

### Moves that might require special treatment
There are broadly two kinds of moves that could cause problems for us:


### Subcategory: Things that could affect Magikarp's ability to perform moves
* Infatuation & paralysis: Each subsequent move has a chance to fail
* Sleep & Freeze: Pokemon is prevented from moving, with a chance to thaw each turn (specific mechanics apply to each).
* Some moves automatically or have an added chance of thawing Frozen pokemon.
* Flinching
* Disable, Taunt, and Encore restrict move selection

### Subcategory: Moves that affect accuracy, evasion, or critical chance rates
* Sweet scent: -1 evasion target
* Defog: -1 evasion target
* Double Team: +1 evasion user
* Minimize: +1 evasion user
* Flash: -1 accuracy target
* Kinesis: -1 accuracy target
* Mud-Slap: -1 accuracy target
* Sand Attack: -1 accuracy target
* Smokescreen: -1 accuracy target
* Mirror Shot: -1 accuracy target (30% chance)
* Mud Bomb: -1 accuracy target (30% chance)
* Muddy Water: -1 accuracy target (30% chance)
* Octazooka: -1 accuracy target (50% chance)
* Accupressure: +2 to one the user's stats at random, possibly accuracy or evasion (not crit stages).
* Secret Power: If on plain/sand terrain this can lower accuracy by one stage, but since magikarp is always on water, this does not apply for this target specifically.
* Focus Energy: +2 stages of crit chance on the pokemon.

### Subcategory: Other moves that require special attention:
* Hyper Beam/Frenzy Plant/etc: These moves require a recovery turn the following turn. We need to confirm how the RNG handles this... though in most cases this will probably faint the Magikarp anyways, so unsupported is probably fine.
* Solar beam: Similar to Hyper beam, but instead requires a charging turn beforehand, *unless the weather is sunny*.
* Fly/Dig/Dive: Player becomes impossible to hit for a turn, then attacks the next turn. Fly in particular is troublesome, since it is both a 2-turn move AND blocked by gravity...
* Magnitude: As mentioned, a roll is performed to determine its strength.
* Moves with multiple effects (like Ice Fang), we need to know what order the effect rolls are done in. This might be rare enough we can just use the complex profile instead (off the top of my head, Ice Fang and tri-attack are the only Gen IV moves with multiple secondary/chance effects)
* Trick room: Should probably just straight up be not supported for the first version: It inverts turn order which means we'd have to do magikarp's turns first.
* Future Sight & Doom Desire: Cannot crit, and the damage is not applied until turns later. If we choose to support them, we'll need to figure out when their rolls occur and we'll have to prompt the user for those results

## Things I need to confirm
Not feedback for you, but something I need to do before we can really begin implmenting
* Do calc/crit/accuracy rolls still happen for moves like night shade, with set damage?
* Do accuracy rolls still happen for 100% accurate moves? (Not to be confused with moves that bypass accuracy checks, like skill swap)
* What order do crit/accuracy/damage rolls happen? If the move misses, does it prevent damage and/or crit rolls from happening?
* What is the exact formula used for calculating misses or crits? Needed for filtering. Make sure the math is accurate with stage modifiers and gravity given the use of C integer arithmetic.
* How does confusion/paralysis/infatuation/sleep/freeze work.
* For moves with multiple effects, how are the different effects rolled?
* (Future work, not yet planned) If Serene grace raises the chance of a secondary effect to 100% (like with rock smash), is a roll still performed?

## Implementation phase ideas

I think your idea to not classify/support all moves up front is a good idea, as I keep coming up with other moves that make things complicated. We should at least classify the ones that meet our criteria. Common things like status conditions, crits/hit/miss, etc. Should be handled in the first phase, With less common things like blizzards in the sun handled later. This can be handled with the "unsupported" flag in the moves. We might also add "partially supported" as an option, where we support it but we warn that we might not be accurate in specific circumstances.

I think a good idea would be to have a tool to specifially to help populate the move information. This tool should not be part of claytonlib, but a separate python tool, probably not even in a notebook but a commandline script. It should iterate through moves that aren't supported/populated yet from moves.json and prompt for details to populate the data; Bonus if it opens the corresponding bulbapedia page in my browser when it iterates to it. This includes profile, accuracy (if it applies). Commandline flags should indicate at what point we start, and whether we are iterating through moves with the "unsupported" flag or just moves that haven't had a profile set yet.

