# Effects

Each move has a specific effect number associated with it, ranging from 0 to 276. There ARE some missing numbers, such as 21, and there are 257 total effects.

The following list was generated with this JQ:

`jq -r 'group_by(.effect) | .[] | "## Effect \(.[0].effect)\nMoves: \(map(.name) | join(", "))\n"' moves.json`

We will include details that impact metronome compass: What rolls occur, in what order, what effects are observable, and how the chance of those effects is determined from the rolls.

The ``#FUTUREWORK` tag means that there is more investigation that would be helpful, but not necessary for the current priority tier.

# General effect notes

## Random secondary effects

For moves with a secondary effect that has a chance of occurring, a random number is generated and taken mod 100. If that random number is less than effect_chance associated with the move (or double that for serene grace), the extra effect occurs. Putting this here to avoid repeating it too often below, if there are moves with different logic then I will try to be explicit.

## Move failures

Some moves have a chance to fail. Obviously moves can miss, but even when they don't, sometimes they fail. Often this when you use a move that applies a status condition to the pokemon or field that is already in effect.

Failure is distinct from a miss, in that if a move fails it can't be encored, disabled, or copycated, etc. If a move is successful, there are a couple extra rolls that happen afterwards, so I try to be explicit in the effect descriptions about which cases cause them to fail. Here are some general rules though:

### Secondary effect failures

When moves have secondary affects based on the move's effect chance, whether or not the chance succeeds or the effect is applied does not affect the success of the move, even if the secondary affect tries to apply a condition but fails.

### Stat change failures

Contrary to logic, if a pokemon uses a move to raise/lower a stat stage, but it is already at the maximum/minimum stat stage modifier, the moves does NOT count as a failure. Given this I am not entirely certain if tracking stat stage modifiers is important or not.

### Field condition failures

Moves that create field conditions, like Light Screen or Mist, fail if those field conditions are already set up.

# Effect details

## Effect 0
Moves: Pound, Mega Punch, Scratch, Vice Grip, Cut, Wing Attack, Slam, Vine Whip, Mega Kick, Horn Attack, Tackle, Water Gun, Hydro Pump, Peck, Drill Peck, Strength, Rock Throw, Egg Bomb, Megahorn, Hyper Voice, Dragon Claw, Aqua Tail, Seed Bomb, X Scissor, Dragon Pulse, Power Gem, Power Whip

* Check crit
* Damage roll
* Check move hit

## Effect 1
Moves: Sing, Sleep Powder, Hypnosis, Lovely Kiss, Spore, Grass Whistle, Dark Void

* Check move hit
* If hit: Roll for sleep duration

Fails if it hits and the target has the ability Insomnia, or the opponent already has a status condition.

## Effect 2
Moves: Poison Sting, Smog, Sludge, Sludge Bomb, Poison Jab, Gunk Shot

* Check crit
* Damage roll
* Check move hit
* If hit: Roll poison chance: Rand % 100 < effect_chance. Roll even if target is already afflicted with poison or other nonvolatile status condition.

Counts as success if hit, even if poison doesn't proc/poison proc fails

## Effect 3
Moves: Absorb, Mega Drain, Leech Life, Giga Drain, Drain Punch

* Crit/Damage/Hit

User recovered some HP when this move hits.

## Effect 4
Moves: Fire Punch, Ember, Flamethrower, Fire Blast, Heat Wave, Lava Plume

* Crit/Damage/Hit
* If hit: Roll burn chance: Rand % 100 < effect_chance. Roll even if target is already afflicted with a nonvolatile status condition.

Counts as success if hit, even if secondary effect doesn't proc/succeed

## Effect 5
Moves: Ice Punch, Ice Beam, Powder Snow

* Crit/Damage/Hit
* If hit: Roll freeze chance: Rand % 100 < effect_chance. Roll even if target is already afflicted with a nonvolatile status condition.

Counts as success if hit, even if secondary effect doesn't proc/succeed

## Effect 6
Moves: Thunder Punch, Body Slam, Thunder Shock, Thunderbolt, Lick, Zap Cannon, Spark, Dragon Breath, Force Palm, Discharge

* Crit/Damage/Hit
* If hit: Roll paralysis chance based on move's associated effect chance. Roll even if target is already afflicted with a nonvolatile status condition.

Counts as success if hit, even if secondary effect doesn't proc/succeed

## Effect 7
Moves: Selfdestruct, Explosion

* Crit/Damage/Hit
* Chansey Faints. For P0, this means the path ends.

## Effect 8
Moves: Dream Eater

If target is not asleep: Move fails, but a hit check is still performed with no visible effect.
If target is asleep: Crit/Damage/Hit

## Effect 9
Moves: Mirror Move

Not callable by Metronome.

## Effect 10
Moves: Meditate, Sharpen, Howl

User's attack increases by 1 stat stage. No rolls. Does not count as failed even if stages cannot be increased any further.


## Effect 11
Moves: Harden, Withdraw

User's defense increases by 1 stat stage. No rolls. Does not count as failed even if stages cannot be increased any further.


## Effect 13
Moves: Growth

User's special attack increases by 1 stat stage. No rolls. Does not count as failed even if stages cannot be increased any further.


## Effect 16
Moves: Double Team

User's evasiveness increases by 1 stat stage. No rolls.  Does not count as failed even if stages cannot be increased any further.


## Effect 17
Moves: Swift, Faint Attack, Shadow Punch, Aerial Ace, Magical Leaf, Shock Wave, Aura Sphere, Magnet Bomb

These moves automatically hit. 
* Crit check 
* Damage roll

No hit check is done.

## Effect 18
Moves: Growl

* Hit check

If the move hits, opponent's attack is lowered by 1 stage.

## Effect 19
Moves: Tail Whip, Leer

* Hit check

If the move hits, opponent's defense is lowered by 1 stage.

## Effect 20
Moves: String Shot

* Hit check

If the move hits, opponent's speed is lowered by 1 stage.

## Effect 23
Moves: Sand Attack, Smoke Screen, Kinesis, Flash

* Hit check

If hit lands, target's accuracy stage is lowered by 1 stage. If it can't go any lower, that is messaged instead.

Counts as successful if it hits, even if the target's stats can't be lowered.

## Effect 24
Moves: Sweet Scent

* Hit check

If hit lands, target's evasiveness stage is lowered by 1 stage. If it can't go any lower, that is messaged instead.

Counts as successful if it hits, even if the target's stats can't be lowered.

## Effect 25
Moves: Haze

Rests all stat changes of both the target and opponent. No rolls are needed. 

## Effect 26
Moves: Bide

The user gains the status "Biding (Not triggered)", with a duration of 2 turns. The move does not perform any rolls the turn it is used.

If the user takes damage from an opponent's attack (Magikarp uses Tackle or Struggle), "Biding (Not triggered)" will become "Biding (Triggered)".

As a consecutively executed move, the user is prevented from selecting a move until the effect wears off. The next turn, the user will use bide again, which will decrease the duration of its Biding status, which will count as successful and perform the successful move rolls, but not the metronome roll. The next turn, when the duration is decreased again and is now 0, if the status on the user is "Biding (Not trigggered)", the move fails. If the status is "Biding (Triggered)", the user will deal damage to the target proportional to the damage received, performing no crit, damage, or hit rolls, but counting as successful.

If the consecutive use of bide is prevented, such as by the user hitting itself in confusion, the status is immediately cleared without any effect on the target.

If the user is behind a substitute, then that could prevent the user from actually being hit. Before branching paths, we'll simply have to throw Unsupported on the last turn of bide. With branching paths, when we detect Biding (Triggered) AND substitute status, we'll have 3 possible paths: The substitute never broke, the substitute broke but not in time to trigger bide, or the substitute broke and bide was triggered.

## Effect 27
Moves: Thrash, Petal Dance, Outrage

Consecutively executed moves that do damage each turn and end with the user becoming confused.

* C/D/H rolls
* On hit, user gains rampaging status for that move, now being locked in to this move.  A random roll to determine how many consecutive turns it will continue to execute. Formula is `2 + (RAND % 2)`, including this turn, which should mean the move hits 2-3 times (if neither pokemon faint first)

On following turns, make sure not to do a metronome roll, since this is skipped for consecutively executed moves.

During the end-of-turn effect check, if the user is locked into a consecutively executed move, we subtract 1 from the duration. If the duration is now 0, the user is now afflicted with confusion, and we do a roll to determine its duration. This is messaged as the user becoming fatigued, and there should be a token for it.

If the user is already confused, the rampaging status ends without a message, there is no roll for additional confusion duration. If the user is prevented from attacking (such as by hitting itself in confusion), the locked on status immediately ends and the user is not confused.

This duration is delayed by freeze, sleep, and flinching, but that won't be necessary to track for our project.

See end_of_turn.md for details on interaction with other end of turn effects.

## Effect 28
Moves: Whirlwind, Roar

Rolls are:
* Hit check roll
* Some other roll: CelebiCutscene_InitSwirlData

But this doesn't matter. The moves are 100% accurate, and battle immediately ends; Continuing past this point is impossible.

## Effect 29
Moves: Double Slap, Comet Punch, Fury Attack, Pin Missile, Spike Cannon, Barrage, Fury Swipes, Bone Rush, Arm Thrust, Bullet Seed, Icicle Spear, Rock Blast

The first thing it does is determine hit count. Essentially, it takes a random number mod 4 and adds it to 2. If the result is 4 or 5, it does this again once more, essentially making these results less likely then the 2 or 3 hit results.


Table of results to make it more clear. Note that R2 is not rolled unless R1 % 4 is 2 or 3.

| R1 % 4 | R2 % 4 | Hit count |
| ------ | ------ | --------- |
| 0      | -      | 2         |
| 1      | -      | 3         |
| 2      | 0      | 2         |
| 2      | 1      | 3         |
| 2      | 2      | 4         |
| 2      | 3      | 5         |
| 3      | 0      | 2         |
| 3      | 1      | 3         |
| 3      | 2      | 4         |
| 3      | 3      | 5         |

It then does 1 standard Crit/Hit/Miss. If it misses, then no further rolls are performed.
If it hits, then it does a Crit/Hit roll for each of the rest of the attacks; no more miss checks are performed. For example, if the result from the hit count determination was 3, and the move hits, it would roll Crit, Hit, Miss, Crit, Hit, Crit, Hit.

* Roll hit_count (2 + RAND % 4)
* If hit_count > 3, roll hit_count once more
* Crit check
* Damage Roll
* Hit check
* If move hits, do the following (hit_count - 1) times or until Magikarp faints:
  * Crit check
  * Damage Roll

Magikarp might faint before all the hits are performed, so each hit should be an individual token instead of a numeric token, since the actual number rolled won't be observable to the user in this instance. It doesn't matter if rolls proceed after Magikarp faints, that's the end of observable random events.

## Effect 30
Moves: Conversion

Changes the user's type to match one of its other moves. If the user's moves all match its current type, this move fails. For this reason, it is important to know the type of the metronome user and the type of its other moves, especially for future priority tiers.

If the user has moves that don't match its current type, a random roll is performed, modulus the total number of moves the user knows, and that move is selected. If this move matches the user's type the roll is performed again in a loop until a move is selected that doesn't match the user's current type. It then changes the user's type to match that type.

For priority tier P0 this might be pretty easy since we already know the moves we are planning on having the metronome user know, and none of them are ghost type, but for P3 at least we might need to consider what happens if the metronome user becomes immune to Magikarp's only damaging move Tackle.

#FUTUREWORK
* Need to test with a pokemon that actually has other moves
* How does the RNG work with 1, 2, 3 other moves? 

## Effect 31
Moves: Rolling Kick, Headbutt, Bite, Bone Club, Waterfall, Rock Slide, Hyper Fang, Needle Arm, Astonish, Extrasensory, Dark Pulse, Air Slash, Dragon Rush, Zen Headbutt, Iron Head

* Crit/Dmg/Hit rolls
* A roll for a chance to apply flinch based on move's effect chance. This roll occurs even if the target has already moved, but there will be no chance for the user to observe it.

## Effect 32
Moves: Recover, Softboiled, Milk Drink, Slack Off, Heal Order

User recovers half their HP. Fails if they are at full health. No rolls, but failing does affect RNG. 

For P0 we can track if the metronome user has yet taken any damage, and if they've done any recovery moves. If they haven't taken damage, we can assume this will fail. If they've taken damage and haven't used any moves that recover HP, we can assume that this will succeed. Otherwise, we cannot make assumptions, we'll need branching paths (branching_paths.md) to track both situations.

## Effect 33
Moves: Toxic

* Hit check
On hit, the opponent gains the Poisoned non-volatile status condition (Technically "Badly poisoned", but there isn't really a functional difference for our purposes). Can miss, and can also fail if opponent already has a non-volatile status condition.

## Effect 34
Moves: Pay Day

* C/D/H Rolls

## Effect 35
Moves: Light Screen

Sets up "Light Screen" effect on the user's side of the field for 5 turns, including the turn it is used. Fails if used while Light Screen status is already in effect.

## Effect 36
Moves: Tri Attack

* Rolls for which effect would be applied on effect chance, based on the following table. (Always)
* C/D/H
* On hit, roll for chance to apply status based on move's effect chance.

Table of status effects:
| RAND % 3 | Status    |
| -------- | --------- |
| 0        | Burn      |
| 1        | Freeze    |
| 2        | Paralysis |

If the target already has a non-volatile status condition, no status effect is applied, but all the rolls still occur, and the move still counts as successful on hit.

None of these status conditions apply a set duration at the start, so we don't need to worry about rolls for duration. Counts as successful on hit, regardless of secondary effect proc or not.

## Effect 37
Moves: Rest

If the user has taken damage, the user's HP fully recovers and they gain the sleep status condition. Unlike most conditions that apply sleep, this one is for a set duration: 3 turns, not including the turn rest is used but including the turn they will wake up (So they will not be able to take action for 2 turns following). 

If they are at full HP, the move fails, and the user does not fall asleep. If the user has the ability "Insomnia", the move fails.

## Effect 38
Moves: Guillotine, Horn Drill, Fissure, Sheer Cold

* Rolls for One-hit KO.

Always fails when the user is lower level than the target, but still rolls the random hit. It will say the opponent is unaffected.

If the target is equal to or lower than metronome user's level, the success threshold is (30 + User's Level - Target Level)/100. If RAND % 100 < threshold, move succeeds, and opponent faints. Otherwise, it will claim the move misses. This is not an accuracy check (so stat changes do not apply), but lock-on/mind reader status will guarantee success.

For example, a level 30 Clefable using sheer cold against a Lvl 5 magikarp. The threshold would be 55. If Rand % 100 is 56, 55, 99, etc. the moves fails. If Rand % 100 is 54, 50, or 0 the move would faint Magikarp.


## Effect 39
Moves: Razor Wind

Takes a charging turn, and has increased critical hit ratio. The user will be unable to select a move the next turn, and will instead execute Razor Wind.

* No rolls on charging turn
* C/D/H on the following turn when the move is actually executed.

Razor Wind does not count as the last move used until it executes. It counts as successful on the charging turn if it is not prevented. If the charging turn is prevented, the user will not be locked into Razor Wind next turn.

## Effect 40
Moves: Super Fang

* Roll to hit. 

On hit, target loses half of their current HP.

## Effect 41
Moves: Dragon Rage

* Roll to hit

On hit, deals exactly 40 hp of damage. This will faint almost all magikarp immediately.

## Effect 42
Moves: Bind, Wrap, Fire Spin, Clamp, Sand Tomb, Magma Storm

* Crit/Damage/Hit
* If hit and not already under a binding status condition, rolls a random number to determine duration of effect.

See effect_status.md for details

## Effect 43
Moves: Karate Chop, Razor Leaf, Crabhammer, Slash, Aeroblast, Cross Chop, Air Cutter, Leaf Blade, Night Slash, Shadow Claw, Psycho Cut, Stone Edge, Attack Order, Spacial Rend

Increased crit chance, but rolls are the standard:
* Crit/Damage/Hit rolls

## Effect 44
Moves: Double Kick, Bonemerang, Double Hit

* Crit/Damage/Hit check
* On hit: 2 unimportant contact rolls, then another Crit/Damage roll

## Effect 45
Moves: Jump Kick, Hi Jump Kick

* Crit/Damage/Hit check

If the user misses, the user takes some damage.

## Effect 46
Moves: Mist

* No random rolls

Creates the "Mist" field condition on the user's side of the field for 5 turns, including the turn it is used. If there is already a Mist field condition, the move fails. 

## Effect 47
Moves: Focus Energy

* No random rolls

Grants the user the "Pumped" status condition, granting an increased stage of crit chance to future moves. If the user is already "Pumped", the move fails.

## Effect 48
Moves: Take Down, Submission

* Crit/Damage/Hit check

User takes recoil damage.

## Effect 49
Moves: Supersonic, Confuse Ray, Sweet Kiss

* Hit check

If the move hits and the opponent is not already confused, they become confused and we roll for confusion duration. If the move misses or the opponent was already confused, the moves fails.

## Effect 50
Moves: Swords Dance

Raises attack by 2 stages, up to 6 stages. Does not count as failed even if stages cannot be increased any further.

## Effect 51
Moves: Barrier, Acid Armor, Iron Defense

Raises defense by 2 stages, up to 6 stages. Does not count as failed even if stages cannot be increased any further.

## Effect 52
Moves: Agility, Rock Polish

Raises speed by 2 stages, up to 6 stages. Does not count as failed even if stages cannot be increased any further.


## Effect 53
Moves: Tail Glow, Nasty Plot

Raises special attack by 2 stages, up to 6 stages. Does not count as failed even if stages cannot be increased any further.

## Effect 54
Moves: Amnesia

Raises special defense by 2 stages, up to 6 stages. Does not count as failed even if stages cannot be increased any further.

## Effect 57
Moves: Transform

Transforms the user into the opponent, copying their species, types, stats, stat stages, and moves (though they are all set to 5 PP). Does not copy status conditions, HP, or held items. Does not involve any RNG rolls the turn it is used.

Definitely not P0, but for P1+ we have a couple of options for how to handle this:
1. If the Magikarp is level 15+ we can adapt to this by using splash and tackle, observing what move the opponent magikarp chooses and looking for tackle crits and misses. The choice of whether to use splash first or tackle first probably depends on whether we're more worried about being fainted or fainting the opponent magikarp.
2. Just switch out to a different metronome user

## Effect 58
Moves: Charm, Feather Dance

* Hit check
If the move hits, opponent's attack is lowered by 2 stages.

## Effect 59
Moves: Screech

* Hit check

If the move hits, opponent's defense is lowered by 2 stages.

## Effect 60
Moves: Cotton Spore, Scary Face

* Hit check

If the move hits, opponent's speed is lowered by 2 stages.

## Effect 62
Moves: Fake Tears, Metal Sound

* Hit check

If the move hits, opponent's special defense is lowered by 2 stages.

## Effect 65
Moves: Reflect

Sets up "Reflect" effect on the user's side of the field for 5 turns, including the turn it is used. Fails if used while Reflect status is already in effect.

## Effect 66
Moves: Poison Powder, Poison Gas

* Hit check

If the move hits and the opponent does not already have a non-volatile status condition, they are poisoned. If they have a status condition, the move fails.

## Effect 67
Moves: Stun Spore, Thunder Wave, Glare

* Hit check is the only roll

If the move hits and the opponent does not have a non-volatile status condition, they become paralyzed. If the opponent already has a status condition, the moves fails.

## Effect 68
Moves: Aurora Beam

* C/D/H
* Roll for secondary effect to proc, according to move's effect chance.

If the secondary effect procs, the target's attack is lowered by a single stage, if possible. If not, the roll still happens, but no message will be shown to the user.

## Effect 69
Moves: Iron Tail, Crunch, Rock Smash, Crush Claw

* Crit/Damage/Hit
* If move hits: Roll to determine if opponent's defense drops based on move's effect chance.

If opponent's defense can't get any lower, the check is still performed, but nothing will happen and no message will be shown to the user. Move counts as successful on hit.

## Effect 70
Moves: Bubble Beam, Constrict, Bubble, Icy Wind, Rock Tomb, Mud Shot

* Crit/Damage/Hit
* If move hits: Roll to determine if opponent's speed drops based on move's effect chance.

If opponent's speed can't get any lower, the check is still performed, but nothing will happen and no message will be shown to the user. Move counts as successful on hit.

## Effect 71
Moves: Mist Ball

* C/D/H
* Roll for secondary effect to proc, according to move's effect chance.

If the secondary effect procs, the target's special attack is lowered by a single stage, if possible. If not, the roll still happens, but no message will be shown to the user.

## Effect 72
Moves: Acid, Psychic, Shadow Ball, Luster Purge, Bug Buzz, Focus Blast, Energy Ball, Earth Power, Flash Cannon

* Crit/Damage/Hit
* If move hits: Roll to determine if opponent's special defense drops based on move's effect chance.

If opponent's special defense can't get any lower, the check is still performed, but nothing will happen and no message will be shown to the user. Move counts as successful on hit.

## Effect 73
Moves: Mud Slap, Octazooka, Muddy Water, Mud Bomb, Mirror Shot

* Crit/Damage/Hit
* If move hits: Roll to determine if opponent's accuracy drops based on move's effect chance.

If opponent's accuracy can't get any lower, the check is still performed, but nothing will happen and no message will be shown to the user. Move counts as successful on hit.

## Effect 75
Moves: Sky Attack

Charging move. On the first turn, the user cloaks itself in harsh light, and no random roll is made. On the second turn:

* C/D/H
* On hit: Roll for secondary effect proc according to move's effect chance.

If the secondary effect procs the opponent flinches, but since the metronome user will usually be slower, this will not usually be visible (flinching only affects that turn, and if you go second flinching is not noticeable). This roll will occur even if the user is moving second.


## Effect 76
Moves: Psybeam, Confusion, Dizzy Punch, Dynamic Punch, Signal Beam, Water Pulse, Rock Climb

* Crit/Damage/Hit check
* Roll to determine if the pokemon is confused based on the move's effect chance. This check is done even if the opponent is already confused.
* If the pokemon is not already confused and the secondary effect procs, then they become confused and a roll is done to determine how long the confusion lasts (see effect_status.md for details)
The move counts as successful if it hits, no matter the outcome of this secondary effect. The opponent becoming confused is an observable effect.

## Effect 77
Moves: Twineedle

Similar to Double Hit, but with poison chance

* Crit/Damage/Hit check
* On hit:
  * Roll for secondary effect proc, according to move's effect chance. On proc, the target is poisoned, unless they already have a nonvolatile status condition.
  * 2 unimportant contact rolls
  * Another set of Crit/Damage rolls
  * Roll again for secondary effect proc, according to move's effect chance. On proc, the target is poisoned, unless they already have a nonvolatile status condition.


As always, this move counts as success on hit, and the secondary effects are rolled even if they wouldn't be able to be applied.

## Effect 78
Moves: Vital Throw

* Crit/Damage rolls, always hits so no roll is done.

## Effect 79
Moves: Substitute

The user loses 1/4th of their HP and creates a subsitute that takes damage in their place. Fails if the user does not have this much HP, or if there is already a substitute in place. Both of these present a problem for us that might require branching paths (see branching_paths.md), which is not planned in P0.

* No rolls are done on the turn substitute is used, or when it breaks.

While substitute breaking is noticable effect, it shouldn't be included on the path because it doesn't effect rolls and we can't fully predict when it will happen. However, since it will affect whether future substitutes can succeed or fail, we'll have to have handling for it occuring a second time. For P0, we'll consider a second substitute in the same path as not supported, and honestly, that's probably fine overall: The odds of using substitute twice is probably more than enough to determine the seed. For future priority tiers, if we implement branching paths, we can simply branch on the question "Was substitute succeessful?", which covers for the lack of health question as well.

The bigger problem is the HP requirement in P0: Unless we know the user is at full HP (which is admittedly possible), we can't know for certain that they were able to execute the move correctly.
### Handling without branching paths (P0)

If metronome user is at full hp and is not behind a substitute, we'll count the move as successful and add the substitute status, otherwise we return not supported (The AND is necessary since Rest can guarantee full hp after substitute).

### Handling with braching paths

If metronome user is at full hp and is not behind a substitute, we'll count the move as successful and add the substitute status. Otherwise, we'll branch on whether or not the substitute was successfully created, not worrying about whether it failed because a substitute was already up or if they didn't have enough HP.

## Effect 80
Moves: Hyper Beam, Blast Burn, Hydro Cannon, Frenzy Plant, Giga Impact, Rock Wrecker, Roar Of Time

The standard Crit/Hit/Miss, but if the move doesn't miss, the user is inflicted with the "recharging" status. This means the user cannot switch out or select a move for their next turn, but will instead automatically spend it "recharging". The turn the move hits will still have the "successful hit rolls", but the turn spent recharging will not have these rolls.


## Effect 81
Moves: Rage

* C/D/H rolls

Applies "Rage" status to user, which makes Rage do more damage if it gets hit while still selecting rage. Using metronome always negates this however.

Rage has a pretty crazy glith where, after the user selects a move other than Rage (i.e. the start of the next turn), it removes SEVERAL non-volatile status conditions:
* Bound
* Curse
* Confusion
* Infatuation
* Substitute
* Torment
* Transform
* Trapping

We luckily don't have to worry much about most of these since Magikarp has no way of inflicting them on the user and the user has no means to inflict them on itself. Transform can be inflicted on the user, but then they lose access to metronome and therefore Rage. 

For substitute, this is interesting because the user won't *see* substitute disappear: Its sprite will remain, but its effect will have been silently lifted. If the user is behind a substitute and uses rage, we should emit a warning about this.

Similarly, the user will never snap out of confusion, it will simply stop being confused, so no "snap out of confusion" token should appear.

## Effect 82
Moves: Mimic

Not callable by Metronome.

## Effect 83
Moves: Metronome

The most important move here. Rolls a random move and executes it. Some rules apply to which moves can be used:
* Some moves are inherently not callable. Except for Metronome itself and Struggle, these effects don't need to be implemented in compass.
* If gravity is in effect, we can't use moves that it prevents.
* Cannot roll a move the metronome user already knows.

If a move is rolled that can't be used, we reroll until we get a number we can use.
Not callable by itself.

## Effect 84
Moves: Leech Seed

* Hit check

On hit, the target gains the "seeded" status and will start losing HP each turn, while the user recovers HP. Fails if the target is already seeded.

## Effect 85
Moves: Splash

Does nothing. No rolls are done, always counts as successful.

## Effect 86
Moves: Disable

* Hit check
* If successful: Disable duration roll

On a hit, disables the last move the target successfully used. Check [effect_status.md] for more details on disable effect.

Move fails if any of the following is true:
* The opponent is already disabled
* The opponent hasn't made a move yet
* The opponent's last move was prevented, such as by paralysis, gravity, etc.
* The opponent's last move was Struggle

If disable hits and is successful, a roll is performed to determine duration, as detailed in the [effect_status.md] document.

## Effect 87
Moves: Seismic Toss, Night Shade

* Hit check

If it hits, it does damage equal to user's level.

## Effect 88
Moves: Psywave

* Special damage roll
* Hit check

The damage dealt is determined by a special damage roll that ignores hp based on the user's level. It would be difficult to reverse engineer the damage dealt into a useable metric, but we can still check if it hits.

## Effect 89
Moves: Counter

Not callable by Metronome.

## Effect 90
Moves: Encore

* Hit check
* If successful: Roll for encore duration.

If the move hits and is successful, the target is locked into their last successful move for a random duration of 3-7 turns. If the metronome user moved second, this does not count the turn encore is used.
Duration: 3 + RAND % 4.

Fails if the target's last move failed or was prevented, but not if their move simply missed.

## Effect 91
Moves: Pain Split

* No rolls.

Adds the target's and user's remaining HP together and then sets their HP stat to half of that total. 

For P0, since we're using a metronome user of Chansey, even the bulkiest of Magikarp will have much less HP, so there is no chance this heals Chansey back to full HP, so we should mark that Chansey is no longer at full HP after this move.

## Effect 92
Moves: Snore

* Hit check roll

Cannot succeed as a metronome move, since metronome cannot be called while asleep, and this move cannot succeed UNLESS the user is asleep. The hit check is run anyways, but is not observable as the move will always fail.

## Effect 93
Moves: Conversion 2

* If the user has been hit by tackle OR struggle: Roll for conversion type

This one is kinda complicated. First of all, the user must have been hit by a move that dealt damage since it switched in or last used Conversion 2, otherwise the move fails.

It then generates a random number % 112, and use that number to index into a row of the [effectiveness chart](effectiveness_chart.md). We check it against the following conditions:
* Is either not very effective or has no effect
* The move type matches the last move to deal damage to the user
* The target type does not match any of the user's current types

If the conditions are met, the user's type changes to the target type of that row.

If not, we roll another random number up to 1000 times until the conditions are met. If we don't find one, then we just go in order through the table to find one, and there's always going to be a valid result somewhere.

Since Magikarp can only use Tackle and Struggle (which counts as normal type for Conversion 2 in this generation), there are only 3 rows we need to consider:

| Index | Move type | Target type | Effectiveness      |
| ----- | --------- | ----------- | ------------------ |
| 0     | NORMAL    | ROCK        | Not very effective |
| 1     | NORMAL    | STEEL       | Not very effective |
| 109   | NORMAL    | GHOST       | No effect          |

## Effect 94
Moves: Mind Reader, Lock On

The user gains a "locked on" status, which lasts until the end of the next turn, unless the user or target switch out/retreat (in which case it ends immediately), or baton passed (in which case it lasts another turn until that pokemon's first turn). 

While this status is active, the user will not miss the opponent with any moves. Hit checks are still rolled, but their rolls don't matter. We will need some sort of abstration over hit checks in these effects to account for this status. Also guarantees 1HKO moves hit, unless the user is a lower level than the target.

Does not fail if already active, just resets the status.

## Effect 95
Moves: Sketch

Not callable by Metronome.

## Effect 97
Moves: Sleep Talk

Not callable by Metronome.

## Effect 98
Moves: Destiny Bond

Not callable by Metronome.

## Effect 99
Moves: Flail, Reversal

* Crit/Damage/Hit check

## Effect 100
Moves: Spite

* Hit check

On hit, decreases PP of target's last move by 4. Since Splash has 40 PP and Tackle has 35, we would have to use this at least 6 times for it to have any effect on that battle whatsoever during our 10 turns of 10 pp metronome, and the odds of that are so improbable it is quite possible that there is NO seed that generates that outcome. For that reason, there is no need to implement PP tracking for Magikarp's moves until at least P2.

## Effect 101
Moves: False Swipe

* C/D/H rolls

This move will never directly faint a Magikarp. If magikarp is poisoned, burned, or under other damaging end-of-turn effects it might faint, but this move will not faint it.

## Effect 102
Moves: Heal Bell, Aromatherapy

Cures user and whole party of non-volatile status conditions. Counts as successful even if nobody was healed. Does not cure confusion.

## Effect 103
Moves: Quick Attack, Mach Punch, Extreme Speed, Vacuum Wave, Bullet Punch, Ice Shard, Shadow Sneak, Aqua Jet

Priority moves. Normally means they'd likely go first, but this doesn't matter with Metronome. Simple Crit/Damage/Hit check.

## Effect 104
Moves: Triple Kick

This move hits up to 3 times, doing a set of standard attack rolls for each one.

* C/D/H roll
* If it misses, stop here, and the move counts as failed
* 2 contact rolls (unobservable)
* C/D/H roll
* If it misses, stop here, but the move counts as successful
* 2 contact rolls (unobservable)
* C/D/H roll

The move counts as successful if it hits at least one time.

## Effect 105
Moves: Thief, Covet

Not callable by Metronome.

## Effect 106
Moves: Spider Web, Mean Look, Block

Opponent gets blocked condition until metronome user switches out. No accuracy checks or other rolls. Fails if the opponent already has the blocked condition.

## Effect 107
Moves: Nightmare

* Hit check

If target is asleep, afflicts them with the nightmare status condition, dealing damage at the end of each turn they stay asleep. If they are not asleep, the move fails, even on a hit.

## Effect 108
Moves: Minimize

No rolls. Raise's user's evasion by 1 stage.

## Effect 109
Moves: Curse

No rolls. Curse has different effects depending on the user's type. The user is unlikely to be ghost type, since no metronome users currently are, but with moves like Conversion and Conversion 2 it is possible.

When the user is not a ghost type, it lower's the user's speed stat by 1, and increase's their attack and defense stat by 1. 

When the user IS a ghost type, the user takes damage equal to half their max HP, possibly fainting themselves, and afflicting the curse status condition on the opponent, doing significant damage at the end of each turn.

Fails if the user is ghost type and the target is already cursed. When it fails the user does not take damage.

## Effect 111
Moves: Protect, Detect

Not callable by Metronome.

## Effect 112
Moves: Spikes

No rolls. Sets up a single layer of spikes on the opponent's side of the field. Fails if there are already 3 layers of spikes.

## Effect 113
Moves: Foresight, Odor Sleuth

No rolls.

Gives user "Foresight" status until target switches out, which allows us to ignore evasion changes and hit ghost types. Since there is no way for Magikarp to gain evasion stat changes or be ghost type, this status does not really matter, especially since using it again does not cause the move to fail, so we can basically treat this move as a "no-op."


## Effect 114
Moves: Perish Song

No rolls. Puts both pokemon under the "Perish Song" status condition, with a duration of 4. At the end of each turn, if the pokemon has not switched out this duration will decrease, including the turn it is used. When this decreases to 0, that pokemon faints.

Fails if all pokemon on the field already have this status condition.

Since we cannot progress once Magikarp faints, and we can't cure it, there isn't much point switching out or anything like that.

## Effect 115
Moves: Sandstorm

No rolls. If the weather is not currently sandstorm, it sets the weather to sandstorm with a duration of 5 turns. Fails if the weather is already sandstorm.

## Effect 116
Moves: Endure

Not callable by Metronome.

## Effect 117
Moves: Rollout, Ice Ball

A consecutively executed move.

* C/D/H rolls

If the attack lands, user gains Fixated status for that move for the next 4 turns, forcing the user to use this move. The user will not do a metronome roll for these following attacks. If the user misses or is prevented from attacking for another reason, this status is removed and the user can select their move as normal the following turn.

## Effect 118
Moves: Swagger

* Hit check
* On hit, if the target is not already confused, rolls for confusion duration.

On hit, raises the target's attack stat by 2 stages, and then applies confusion if the target is not already confused. Counts as successful on hit, even if the target is already confused or already at max attack.

## Effect 119
Moves: Fury Cutter

* C/D/H

Does increasing damage if used consecutively, but since we don't track damage this is basically just a damaging attack for our purposes.

## Effect 120
Moves: Attract

* Hit check

Fails if the target is already attracted, if either the target or user are genderless, or if the target and user are the same gender. Otherwise they gain the "infatuated" status, which affects their odds of performing moves (see [effect_status.md]).

## Effect 121
Moves: Return

* Crit/Dmg/Hit

## Effect 122
Moves: Present

* Roll for effect
* If we roll damage: C/D/H rolls
* If we roll healing: Hit check

Starts with a roll to determine what effect this move will have. If (RAND & 0xFF) is less than 204 (0xCC), then we do a damaging move of varying power and do the standard attack rolls, otherwise we do a move that heals the target.

If the target is under the effect of heal block and present rolls healing, the move will not heal them, but will not count as failed, even if they are already at full HP. Fails if target IS at full hp and present selects healing and target is not under the effect of heal block. See [branching_paths.md] for more information.

## Effect 123
Moves: Frustration

* Crit/Dmg/Hit

## Effect 124
Moves: Safeguard

Sets up safeguard on the user's side of the field, preventing the user from common status conditions. It does not prevent the user falling asleep from Rest, but it does prevent confusion from Thrash/Outrage/Petal Dance.

Fails if safeguard is already set up on the user's side of the field. Last for 5 turns unless removed by defog, which we don't need to worry about.

## Effect 125
Moves: Flame Wheel, Sacred Fire

* Crit/Dmg/Hit rolls
* Roll to burn

Thaws user, chance to burn. Since there isn't really a way for the metronome user to become frozen, this is identical to effect 4.

## Effect 126
Moves: Magnitude

* Roll to determine magnitude
* C/D/H

The magnitude roll is taken mod 100, and then the magnitude of the move is determine by this table.

| Roll  | Magnitude |
| ----- | --------- |
| 0-4   | 4         |
| 5-14  | 5         |
| 15-34 | 6         |
| 35-64 | 7         |
| 65-84 | 8         |
| 85-94 | 9         |
| 95-99 | 10        |

Magnitude effects damage, which we won't be able to do anthing with, but the chosen Magnitude IS shown to the user, and a token should definitely be created for the different magnitudes.

## Effect 127
Moves: Baton Pass

No rolls. Immediately switches out the user, passing on several conditions to the new pokemon that switches in. In P0 this is not supported, but is planned to be supported in later priority tiers.

No rolls are done, no additional rolls triggered other than the usual "successful move" roll. 

Effects passed (that might matter to us):
* Stat stage changes
* Confusion
* Focus Energy
* Ingrain
* Substitute
* Perish Song
* Magnet Rise
* Aqua Ring

#FUTUREWORK (P3 only) What if they are the only non-fainted pokemon in the party?


## Effect 128
Moves: Pursuit

* C/D/H rolls

## Effect 129
Moves: Rapid Spin

* C/D/H rolls

No additional effects that matter in our expected context.

## Effect 130
Moves: Sonic Boom

* Hit check

Does exactly 20 damage.

## Effect 132
Moves: Morning Sun, Synthesis, Moonlight

Chansey recovers HP. Fails if Chansey is at full HP. Amount recoverd depends on weather, but since we don't track HP we won't worry about that. No rolls, but if the move fails it'll obviously impact RNG. See effect 32 or the [branch_paths.md] page for more details.

## Effect 135
Moves: Hidden Power

* C/D/H rolls

Can have different types. If the user has a fire type hidden power, it can thaw the opponent if they are frozen. Rather than have to know hidden power types, we'll just throw unsupported when hidden power connects with a frozen target, at least for P0-P2.

## Effect 136
Moves: Rain Dance

No rolls. If the weather is not currently rain, it sets the weather to rain with a duration of 5 turns. Fails if the weather is already rain.

## Effect 137
Moves: Sunny Day

No rolls. If the weather is not currently sun (harsh sunlight), it sets the weather to sun with a duration of 5 turns. Fails if the weather is already sun.

## Effect 138
Moves: Steel Wing

* C/D/H rolls
* Roll for secondary effect proc. If it procs, the user's defense stat is raised one stage.

## Effect 139
Moves: Metal Claw, Meteor Mash

* Crit/Dmg/Hit roll
* Roll for secondary effect proc. If it procs, the user's attack stat is raised one stage.

## Effect 140
Moves: Ancient Power, Silver Wind, Ominous Wind

* Crit/Dmg/Hit roll
* Roll for proc chance based on move effect chance (10% for each move). If the secondary effect procs, the user's Attack, Defense, Speed, Sp. Attack, and Sp. Defense all raise 1 stage.

## Effect 142
Moves: Belly Drum

No rolls. If it would not faint the user, they lose HP equal half their max HP and their Attack stat is raised to the maximum of 6 stat stage increases, no matter what point it is already at. If losing this amount of HP would cause the user to faint, the move fails and they do not lose HP or gain attack stat stages.

#FUTUREWORK Branching paths?

## Effect 143
Moves: Psych Up

No rolls. Copies the stat change stages of target (Attack, Defense, Sp. Atk, Sp. Def, speed, accuracy, evasion). Does not fail even if the target's stats are all neutral or the same as the user's.

## Effect 144
Moves: Mirror Coat

Not callable by Metronome.

## Effect 145
Moves: Skull Bash

Two turn move.

First turn: 1 random roll, but no obvious result from roll. User "Tucked in its head" message. Move counts as successful, user's defense is raised by 1 stage.  User is not given a prompt for a second move.

Second turn: No metronome roll, but normal Crit/Damage/Hit rolls.

#FUTUREWORK confirm random roll purpose

## Effect 146
Moves: Twister

* Crit/Damage/Hit rolls
* Roll for a chance to flinch based on move effect chance.

Not relevant here, but would normally do double damage to a pokemon in the semi-invulnerable turn of fly or bounce, which is why it has a different effect from other flinching moves, but for our use case it is the same.

## Effect 147
Moves: Earthquake

* Crit/Damage/Hit rolls

Not relevant here, but would normally do double damage to a pokemon in the semi-invulnerable turn of dig, but for us it is basically a normal damaging move.

## Effect 148
Moves: Future Sight, Doom Desire

* Damage roll

Does not do direct damage on the turn it is used, but instead deals damage on a future turn.

On the turn it is selected, only a "damage" roll is done, and then the opponent gains the Future Attack status with a duration of 3 (not including this turn). This roll does not have any observable effect, on the turn it is used or when the attack lands.

During the end-of-turn effect check, this duration is checked and reduced by 1. If it is 0 after this subtraction, the future sight attack occurs. A hit check is performed, making it possible for future sight to miss, though it cannot possibly crit. The messaging is that future sight failed, not that it missed. It doesn't count as the last move used, and it doesn't cause any "successful attack" rolls to occur on hit.

If the target already has the Future Attack status, then the move fails, but performs an additional hit check roll for no apparent reason.

See end_of_turn.md for notes on the order end of turn effects are resolved.

## Effect 149
Moves: Gust

* Crit/Damage/Hit rolls

Not relevant here, but would normally do double damage to a pokemon in the semi-invulnerable turn of dig/bounce, but for us it is basically a normal damaging move.

## Effect 150
Moves: Stomp

* Crit/Damage/Hit rolls
* Roll for a chance to flinch based on move effect chance.

Not relevant here, but would normally do double damage to a pokemon who has previously used the move minimize without switching out, which is why it has a different effect from other flinching moves, but for our use case it is the same.

## Effect 151
Moves: Solar Beam

The behavior of this move changes based on whether the weather is harsh sunlight or not. 

Without harsh sunlight, there is a charging turn that is performed first. There are no random rolls after the metronome roll, and the message "<User> absorbed light" is shown. The user is unable to switch pokemon or select a move afterwards, like all multi-turn moves. The next turn, the user uses solar beam, with the usual Crit/Damage/Hit rolls of a normal attack.

If there is harsh sunlight, the charging turn is completely skipped, and this essentially functions as a basic attack, with the usual crit/damage/hit rolls.

## Effect 152
Moves: Thunder

Normal behavior:
* Normal Crit/Damage/Hit rolls.
* Rolls for a chance to paralyze target according to move effect chance. This check is performed even if target can't be paralyzed.

The accuracy of this move changes based on the weather:
* During Harsh Sunlight: Same rolls as normal, but accuracy is overwritten to 50 instead of the usual 70%
* During Rain: Same rolls as normal, but the result of the accuracy check is discarded, and the move will instead always hit.

## Effect 153
Moves: Teleport

No rolls, battle immediately ends.

## Effect 154
Moves: Beat Up

This move has the whole player's party attack, excluding pokemon that have a non-volatile status condition or have fainted.

* C/D/H rolls.
* Two "attack successful" rolls.

For each other party member (including the user)
* Crit/Damage rolls (no hit check)
* Two "attack successful" rolls.

The above includes the usual "attack successful" rolls that are usually not mentioned in these requirements, so we should be careful not to double count those in the code.

For P0, we should assume a full party, and make sure to note that in the requirements. In later priority tiers, we can try to track party status and can ask user for party details at start.

## Effect 155
Moves: Fly

Two-turn move. 

The first turn, no rolls are performed, the message "<user> flew up high" is shared, and the user gains the "Sky High" status, making most moves automatically miss (Tackle and struggle included, splash not affected as it doesn't attack).

Second turn, the user attacks, with the usual crit/damage/hit rolls. Interestingly, the move counts as successful and performs the successful move rolls even if it misses.

## Effect 156
Moves: Defense Curl

Raises defense by 1 stages, up to 6 stages. Does not count as failed even if stages cannot be increased any further. Additionally, gains a "Defense Curl" status which doubles the damage of roll out or ice ball, but that doesn't really matter to us so we should probably not bother tracking it.

## Effect 158
Moves: Fake Out

If it is the first turn: Crit/Dmg/Hit rolls + Flinch chance roll (Despite chance being 100)
If it is the second turn: Roll Hit chance first, then the move fails.

Flinch chance roll occurs even when moving second.

## Effect 159
Moves: Uproar

Very similar to Effect 27 (Uproar, Thrash).

First turn:
* C/D/H rolls
* Random roll to determine duration of "Uproar" status.

Consecutive turns (until it wears off):
* C/D/H rolls.

The user gains the "Uproar" status. While afflicted by uproar status, user is unable to select another move.  The duration of this status is 2 + (RAND % 4), not including the turn uproar is used. This means if RAND returned 0, the user would use uproar as a result of metronome once, and then for the following 2 turns as well. Not relevant here, but moves that would cause pokemon to fall asleep (including Rest) would fail during uproar.

## Effect 160
Moves: Stockpile

The user gains the "Stockpile" status, with a count of 1, and raises its defense and special defense stat stages by 1. If the user already has a stockpile status with a count 1 or 2, it increases that count, and the user's stat stages are still increased. If it already has a stockpile status with a count of 3, no stat stages are increased and the move counts as failed.

#FUTUREWORK what if (special) defense was maxed before stockpiling? Does it matter?

## Effect 161
Moves: Spit Up

If the user has the "Stockpile" status: Deals damage, doing a crit roll and a hit roll but oddly no random damage roll.  Defense and special defense are decreased one stage per count of stockpile, and then the status is cleared.

If the user does not have the stockpile status, a hit check is still performed oddly, but the move fails.

## Effect 162
Moves: Swallow

If the user has the "Stockpile" status: The user recovers HP, proportional to the amount stockpiled. Defense and special defense are decreased one stage per count of stockpile, then the status is cleared.

If the user has no stockpile status, the move fails and no health is recovered.

## Effect 164
Moves: Hail

No rolls. If the weather is not currently hail, it sets the weather to hail with a duration of 5 turns. Fails if the weather is already hail.

## Effect 165
Moves: Torment

* Hit check

Afflicts the target with the "Torment" status, preventing them from using the same move twice in a row. That means the last selected move is removed from their pool of candidate moves when selecting a move. If they only have one move, they might be forced to struggle every other turn. This status lasts until the user is switched out. We will have to be careful with this when implementing logic around AI choosing a move at random.

Being prevented from using a move counts as the move not being used last turn. For instance, if the magikarp is tormented and uses tackle one turn, and is fully paralyzed the second turn, they are able to use tackle on the third turn.

## Effect 166
Moves: Flatter

* Hit check
* On hit and if target is not confused: Roll for confusion duration

If this move hits and target is not confused, the target becomes confused for the duration rolled (see effect_status.md for details), as well as having their special attack raised one stage. If they are already confused, their special attack is still raised and the move does not count as failed.

## Effect 167
Moves: Will O Wisp

* Hit check

On a succesful hit, target is burned.

## Effect 168
Moves: Memento

* Hit check

On a successful hit, the target's attack and special attack are lowered 2 stages, then the user faints. On P0 this ends our run, but in future priority tiers we might be able to support it with multiple pokemon.

## Effect 169
Moves: Facade

* Hit/Damage/Crit rolls

## Effect 170
Moves: Focus Punch

Not callable by Metronome.

## Effect 171
Moves: Smelling Salt

* Hit/Damage/Crit rolls

If the target is paralyzed, this does more damage and cures them of paralysis.

## Effect 172
Moves: Follow Me

Not callable by Metronome.

## Effect 173
Moves: Nature Power

* No implicit rolls
* Hit/Damage/Crit roll for Hydro pump

In our use case, it always becomes Hydro pump. If we supported other scenarios then vs magikarp, we would have to revisit, but basically it just executes hydro pump and has the same accuracy.

## Effect 174
Moves: Charge

* No rolls

Raises user's special defense by 1 stage.

## Effect 175
Moves: Taunt

* Hit check
* Roll for random duration

The target is unable to select status moves (like splash) for the random duration. See effect_status.md for details.

## Effect 176
Moves: Helping Hand

Not callable by Metronome.

## Effect 177
Moves: Trick, Switcheroo

Not callable by Metronome.

## Effect 178
Moves: Role Play

* No rolls.
Change's the user's ability to the target's. Counts as successful even if they have the same ability.

## Effect 179
Moves: Wish

* No rolls

The pokemon's side of the field gains the "Wish" status. At the end of the next turn, this status fades, and if the pokemon hasn't fainted that turn, whichever pokemon is active recovers half of their max HP. Move fails if they already have the wish status (i.e. if the move is used a second time in a row).

## Effect 180
Moves: Assist

Not callable by Metronome.

## Effect 181
Moves: Ingrain

* No rolls

User gains "Ingrained" status. This prevents the user from switching out normally, and they recover some HP at the end of each turn. They can still switch out if metronome calls a move that switches the user out (Like baton pass or U-turn).

## Effect 182
Moves: Superpower

* C/D/H rolls

The user's attack and defense stats are lowered by a single stage after.

## Effect 183
Moves: Magic Coat

* No rolls

Given the user is intended to always move last, this move always fails. If it somehow moved first it would reflect certain status moves back, but none of those are useable by Magikarp so it isn't worth implementing as anything other than an automatic failure.

## Effect 184
Moves: Recycle

* No rolls

Unless the user lost their lagging tail due to Fling, this move does nothing and fails, and considering all the other variables we have to worry about with Fling, it is unlikely we will support it so we might as well implement this as an automatic failure for P0. For future tiers, we might support other items, in which case we can work to support this.

## Effect 185
Moves: Revenge, Avalanche

* Typical C/D/H rolls

## Effect 186
Moves: Brick Break

* C/D/H rolls

Would remove screens from target's side of the field, but target cannot set up screens.

## Effect 187
Moves: Yawn

Turn attack is used:
* No rolls
When drowsy status wears off:
* Rolls for sleep duration

No accuracy check, gives target "Drowsy" status. At the end of the next turn, drowsy status wears off and the target falls asleep, and the usual random call is made to determine duration, unless the target already has a nonvolatile status condition, has acquired the ability Insomnia, or the user is using uproar (basically any of the usual things that prevent sleep). Fails if target is already drowsy, already has a nonvolatile status condition, or if they have the ability "Insomnia".

## Effect 188
Moves: Knock Off

* C/D/H rolls

## Effect 189
Moves: Endeavor

* Hit check

Reduces target's HP to the user's current HP. Fails if their HP is lower than the user's, which would often be the case with our P0 parameters. Requires branching paths, so not supported in P0.

## Effect 190
Moves: Eruption, Water Spout

Typical C/D/H rolls

## Effect 191
Moves: Skill Swap

* No rolls

User and target exchange abilities.

## Effect 192
Moves: Imprison

* No rolls

Creates a status on the user that prevents opponents from using moves the user knows, but fails if they have no moves in common. For P0, this will always be the case.

## Effect 193
Moves: Refresh

* No rolls

Cures user of paralysis, poison or burn, or fails if the use doesn't have these conditions. Since there is no way for Magikarp or metronome to inflict the user with these statuses, this move always fails.

## Effect 194
Moves: Grudge

* No rolls

Gives the user the "grudge" status. If fainted by direct attack damage (Future sight does not count), the opponent's move that fainted the target will be instantly depleted of PP. For P0, since we only have one metronome user, this ends the path.

## Effect 195
Moves: Snatch

Not callable by Metronome.

## Effect 196
Moves: Low Kick, Grass Knot

Typical C/D/H rolls

## Effect 197
Moves: Secret Power

* C/D/H rolls
* Roll for secondary effect proc. 

The secondary effect changes depending on the environment, but for the magikarp fight it will always be the sea water environment, and so it will always lower target attack.

## Effect 198
Moves: Double Edge, Brave Bird, Wood Hammer

* Crit/Damage/Hit rolls

User is hit with recoil damage.

## Effect 199
Moves: Teeter Dance

* Hit check
* On hit and if target is not confused: Roll for confusion duration (Per effect_status)

Causes target to become confused. Fails if target is already confused.

## Effect 200
Moves: Blaze Kick

* C/D/H check
* Roll for effect chance proc to apply burn.

In addition to chance to apply burn, this attack has an increased critical chance stage.

## Effect 201
Moves: Mud Sport

* No rolls
Sets up field effect "Mud Sport". Fails if mud sport already active.

## Effect 202
Moves: Poison Fang

* C/D/H check
* Roll for effect chance proc to apply bad poison according to move effect chance.

The difference between bad poison and regular poison doesn't really matter to us, so we can just treat this as the same as effect 2 (Like poison sting).

## Effect 203
Moves: Weather Ball

* C/D/H rolls
Does different types of damage in different weather, but the difference doesn't matter to us.

## Effect 204
Moves: Overheat, Psycho Boost, Draco Meteor, Leaf Storm

* Crit/dmg/hit rolls
* Roll for chance to drop user's special attack by 2 stages, according to move's secondary effect chance. It should be noted that for all of the actual moves, this effect chance is 100, so it actually always occurs, but the random roll still occurs.


## Effect 205
Moves: Tickle

* Hit check

On hit, lower's targets attack and defense by 1 stage.

## Effect 206
Moves: Cosmic Power, Defend Order

Raises user's Defense and Special Defense by 1 stage each. No rolls needed.

## Effect 207
Moves: Sky Uppercut

* C/D/H rolls

## Effect 208
Moves: Bulk Up

* No rolls

Raises user's attack and defense by 1 stage each.

## Effect 209
Moves: Poison Tail, Cross Poison

Increased critical hit chance + chance to poison.

* C/D/H rolls
* Proc effect chance based on move's effect chance.

Increased critical hit rate + chance to poison. Basically the same as Effect 2, but with an increased stage of crit chance. Succeeds if it hits, even if poison or crit don't proc.

## Effect 210
Moves: Water Sport

Sets up field effect "Water Sport". Fails if water sport already active.

## Effect 211
Moves: Calm Mind

* No rolls

Increases user's special attack and special defense by 1 stage each.

## Effect 212
Moves: Dragon Dance

* No rolls

Increases user's speed and attack by 1 stage each.

## Effect 213
Moves: Camouflage

* No rolls

Changes the user's type to match the environment. In the magikarp fight, this will always be the Water type. Fails if the user is already that type (Such as because they already used that move).
## Effect 214
Moves: Roost

* No rolls

User recovers half their health, and loses the flying type if they have it. If they are at full HP, the move fails (see branching_paths.md)

## Effect 215
Moves: Gravity

* No rolls.

The field gains the "Gravity" status for a duration of 5 turns (including this one). Certain moves are not callable by metronome during gravity and all moves gain a 5/3 increase to accuracy. Fails if used while gravity is still in effect. In addition, Splash is not a usable move either, so magikarp might be forced to tackle or struggle.

## Effect 216
Moves: Miracle Eye

* No rolls

Functionally the same as Odor Sleuth (Effect 113), the only difference being it applies to dark types not ghost types. None of this matters, so this is essentially a no-op.

## Effect 217
Moves: Wake Up Slap

* C/D/H Rolls

If the target is asleep and not behind a substitute, this move does double damage, but more importantly it ends sleep.

## Effect 218
Moves: Hammer Arm

* C/D/H rolls

Deals damage and lower's user's speed by 1 stage.

## Effect 219
Moves: Gyro Ball

* C/D/H rolls

## Effect 220
Moves: Healing Wish

User faints, and next pokemon is fully healed (status conditions and HP). For P0, this means immediate path termination.

## Effect 221
Moves: Brine

* C/D/H rolls

## Effect 222
Moves: Natural Gift

* Check move hit

Always fails when holding lagging tail, which we always should be for P0.

## Effect 223
Moves: Feint

Not callable by Metronome.

## Effect 224
Moves: Pluck, Bug Bite

Standard C/D/H rolls; Additional effect will never apply since Magikarp doesn't have any wild held items. If we start supporting battles against things other than Magikarp, we might have a branching path sitation on our hands.

## Effect 225
Moves: Tailwind

* No rolls

Sets up "Tailwind" field effect on user's side of the field. This effect lasts for 3 turns including the turn it is used. This doubles the user's effective speed, but for P0 this does not matter since we'll be holding lagging tail.

Fails if used while "Tailwind" status is already set up.

## Effect 226
Moves: Acupressure

Counts how many of the following stats are not at max stat stages for USER, and creates a list of them in this order.

Order:
0. Attack
1. Defense
2. Speed
3. Sp. Attack
4. Sp. Def
5. Accuracy
6. Evasion

index = RAND % CountOfEligibleStats, and we index into the list that has the non-eligible stats filtered. The chosen stat is raised by two for the metronome user. This is the only rand roll for this move.

For example, if the user used Belly Drum in the previous turn and maxed the Attack stat, the count of eligible stats would be 6. If random generated 13, 13 % 6 = 1, so the increased stat would be speed (Attack is ineligible, defense would be index 0).

## Effect 227
Moves: Metal Burst

* Check move hit

If the move hits, the user does damage equal to 1.5x the damage taken this turn. If the user has not taken damage this turn, then the move fails, but the hit check is still performed.

## Effect 228
Moves: U Turn

* C/D/H rolls

On a successful hit, the user immediately switches out. In later priorities when we have multiple metronome users or can support the user needing to switch their metronome user back in immediately, we can continue (see switching_out.md), but for P0 this ends the sequence. However, we can still build a path based on whether it crits.

## Effect 229
Moves: Close Combat

* C/D/H rolls

Deals damage, and on a successful hit, lower's the user's special defense and defense stats by one stage.

## Effect 230
Moves: Payback

* C/D/H rolls

## Effect 231
Moves: Assurance

* C/D/H rolls

## Effect 232
Moves: Embargo

* Hit check

On a hit, the target gets "embargo" status, preventing use of held items (which in P0 won't matter). Fails if used on a target with this status though, so we still need to track it.

## Effect 233
Moves: Fling

* C/D/H rolls

User loses their held item and deals damage based on the held item. Since we depend on the lagging tail to make sure our pokemon goes last, this will end our run in the earlier priority tiers, though we can still add the crit/hit/miss chance to the path.

## Effect 234
Moves: Psycho Shift

* Hit check

Transfers non-volatile status conditions upon hit.  Since the only non-volatile status condition we can afflict ourselves with is sleep, and we can't call metronome while sleeping, this move essentially is an auto fail.

## Effect 235
Moves: Trump Card

* Crit check
* Damage roll

Does damage and never misses.

## Effect 236
Moves: Heal Block

* Hit check

Applies "Heal Block" status to target for 5 turns. The user cannot be healed. Fails if the target is already afflicted with this status.

The only way for Magikarp to heal is through the move Present anyways.

## Effect 237
Moves: Wring Out, Crush Grip

Standard C/D/H rolls

## Effect 238
Moves: Power Trick

* No rolls

Switches the user's attack and defense stats (not stat stages). Can be used repeatedl without failing. In our case, it is essentially a no-op.

## Effect 239
Moves: Gastro Acid

* Hit check

On a hit, the target gains the "gasto acid" status, which suppresses their ability. Fails if this status is already applied.

## Effect 240
Moves: Lucky Chant

* No rolls

Applies "Lucky Chant" to the user's side of the field for 5 turns. While this status in in effect, all moves against them will not crit, even if their rolls normally would result in a crit. The crits are still rolled for as normal.

## Effect 241
Moves: Me First

Not callable by Metronome.

## Effect 242
Moves: Copycat

Not callable by Metronome.

## Effect 243
Moves: Power Swap

* No rolls
Swaps the stat stages of the user's Attack and Special Attack stats with the target.

## Effect 244
Moves: Guard Swap

* No rolls
Swaps the stat stages of the user's Defense and Special Defense stats with the target.

## Effect 245
Moves: Punishment

* C/D/H rolls

## Effect 246
Moves: Last Resort

* Hit check

Performs a hit check, and then always fails when called by metronome.

## Effect 247
Moves: Worry Seed

* Hit check

On a hit, changes the target's ability to "Insomnia". Succeeds on hit even if the target already has the ability Insomnia. If the opponent has the sleep status condition or drowsy status condition it is immediately ended.

## Effect 248
Moves: Sucker Punch

* Hit check

After the hit check, moves fails if the target has not selected a damage move. For our case, this essentially means it always fails.

## Effect 249
Moves: Toxic Spikes

* No rolls

Sets up a field condition on the opponent's side of the field called "Toxic spikes" with a level of 1. If there is already a level 1 Toxic spikes condition on the opponent's side of the field, it is increased to level 2. If there is already a level 2 Toxic spikes condition on the opponent's side of the field, the move fails.

## Effect 250
Moves: Heart Swap

* No rolls

Swaps the user's stat stages with the target's stat stages, including evasiveness and accuracy. Because of this, my assumption throughout this document that magikarp does not have a way to increase its evasion is incorrect - If metronome chooses minimize and then heart swap, the magikarp DOES gain evasion stages. Of course the odds of this specific combo are pretty unlikely, so for P0 we can just end the path if this move gives magikarp any evasion stat boosts, and we can make sure these assumptions aren't problematic for future priority tiers.

This move does not fail even if neither target has stat stage changes to swap.

## Effect 251
Moves: Aqua Ring

* No rolls

Sets up "Aqua ring" status on user. The user restores up to 1/16th of its max HP every turn. The move fails if the user already has this status, but does not fail if the user is at full HP. This can impact branching_paths.md by recovering lost HP back to full after taking damage, but otherwise should be fine without branching paths logic.

## Effect 252
Moves: Magnet Rise

* No rolls

The user gains "Magnet Rise" status for 5 turn. Fails if user already has this status, or if they have the "Ingrain" status. Baton pass passes this status.

## Effect 253
Moves: Flare Blitz

* C/D/H rolls
* Rolls for secondary effect proc based on move effect chance (If successful, applies burn unless the target already has a nonvolatile status condition)

Deals damage, thaws user, and also hits the user with recoil damage. It also has a chance to apply burn.

## Effect 254
Moves: Struggle

Not callable by Metronome, but must be implemented - Used when no other moves can be used. We won't be having our metronome users struggle, but Magikarp can be forced to struggle.

* Crit roll
* Damage roll

Bypasses accuracy checks, deals damage and then the user takes recoil damage.

## Effect 255
Moves: Dive

Two-turn move. 

First turn:
* No rolls
Second turn:
* <No metronome roll>
* C/D/H rolls

Like Fly or Dig, the pokemon becomes immune to damage the first turn, then attacks the second turn.

The first turn, no rolls are performed, the message "<user> hid underwater" is shared, and the user gains the "Submerged" status, making most moves automatically miss (Tackle and struggle included, splash not affected as it doesn't attack).

Second turn, the user attacks, with the usual crit/damage/hit rolls.

## Effect 256
Moves: Dig

Two turn move.

First turn:
* No rolls
Second turn:
* <No metronome roll>
* C/D/H rolls

The first turn, no rolls are performed, the message "<user> burrowed its way underground!" is shared, and the user gains the "Underground" status, making most moves automatically miss (Tackle and struggle included, splash not affected as it doesn't attack).

Second turn, the user attacks, with the usual crit/damage/hit rolls.

## Effect 257
Moves: Surf

* C/D/H Rolls

## Effect 258
Moves: Defog

No rolls. Lowers the evasiveness of the target pokemon, which is important to track for less accurate moves. It also removes the following field effects from the target's side of the field:
* Spikes
* Toxic spikes
* Stealth rocks
* Mist
* Light screen
* Reflect 
* Safeguard

I can't think of a possible way for the last 4 to be set up on Magikarp's side of the field, but the first three might matter since it changes whether a move fails or not.

## Effect 259
Moves: Trick Room

* 4 rolls that seem to have no purpose that occur after the field status is set up.

Creates the field status "Trick room," which lasts for 5 turns (including the turn it is used). This normally reverses speed order of pokemon, but with lagging tail it doesn't effect us. Using it again ends the effect prematurely.

## Effect 260
Moves: Blizzard

Aspects of this move change based on the weather.

* C/D/H rolls
* On hit: Roll for secondary effect proc. On success, target is frozen.

During hail: 
* Blizzard automatically hits, ignoring results from hit roll entirely.
During sun:
* Rolls for chance to freeze, though freeze is not possible in the sun.

## Effect 261
Moves: Whirlpool

* Crit/Damage/Hit
* If hit and not already under a binding status condition, rolls a random number to determine duration of effect.

See effect_status.md for more details. Effectively the same as effect 42.

## Effect 262
Moves: Volt Tackle

* C/D/H rolls
* If hit, rolls for secondary effect chance to apply paralysis.

Damage and a chance to paralyze, also hits the user with recoil damage on hit.

## Effect 263
Moves: Bounce

Two turn move.

First turn:
* No rolls
Second turn:
* C/D/H rolls
* On hit: Rolls for chance to apply paralysis based on effect chance of move.


The first turn, no rolls are performed, the message "<user> sprang up" is shared, and the user gains the "Sky High" status, making most moves automatically miss (Tackle and struggle included, splash not affected as it doesn't attack). This is just like the move Fly.

Second turn, the user attacks, with the usual crit/damage/hit rolls. Unlike fly, this has a chance to paralyze the target if it hits. Interestingly, the move counts as successful and performs the successful move rolls even if it misses.

## Effect 265
Moves: Captivate

* Hit check

If the target is not the opposite gender of the user, this move fails, even if the move would normally miss. If the target IS the opposite gender of the user, and the move hits, the target's special attack is lowered by 2.

## Effect 266
Moves: Stealth Rock

* No rolls

Sets up field effect "stealth rocks" on opponent's side of the field. Fails if already set up.

## Effect 267
Moves: Chatter

Not callable by Metronome.

## Effect 268
Moves: Judgment

* C/D/H rolls

## Effect 269
Moves: Head Smash

* C/D/H rolls

Deals damage and user takes recoil damage.

## Effect 270
Moves: Lunar Dance

* User faints

## Effect 271
Moves: Seed Flare

* C/D/H rolls
* Roll for chance to proc secondary effect according to move effect chance.

On the secondary effect proc, target's special defense is lowered by two stages.

## Effect 272
Moves: Shadow Force

Two turn move.

First turn:
* No rolls
Second turn:
* C/D/H rolls
* On hit: Rolls for chance to apply paralysis based on effect chance of move.

The first turn, no rolls are performed, the message "<user> vanished instantly" is shared, and the user gains the "Vanished" status, making most moves automatically miss (Tackle and struggle included, splash not affected as it doesn't attack).

Second turn, the user attacks, with the usual crit/damage/hit rolls. This move ignored protection, but that doesn't matter for any priority tier.

## Effect 273
Moves: Fire Fang

* C/D/H Rolls
* On hit: Roll for chance to burn
* On hit: Roll for chance to flinch

The chance to burn or flinch is (RAND % 100 < 10). Of course flinching won't matter because we alawys move second, but the burn chance is noticeable.

## Effect 274
Moves: Ice Fang

* C/D/H Rolls
* On hit: Roll for chance to freeze
* On hit: Roll for chance to flinch

The chance to freeze or flinch is (RAND % 100 < 10). Of course flinching won't matter because we alawys move second, but the freeze chance is noticeable.


## Effect 275
Moves: Thunder Fang

* C/D/H Rolls
* On hit: Roll for chance to paralyze
* On hit: Roll for chance to flinch

The chance to paralyze or flinch is (RAND % 100 < 10). Of course flinching won't matter because we alawys move second, but the paralyze chance is noticeable.

## Effect 276
Moves: Charge Beam

* C/D/H rolls
* Roll for secondary effect proc based on effect chance. 

When the secondary effect procs, the user's special attack is raised by a single stage.

