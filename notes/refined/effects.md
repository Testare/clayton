# Effects

Each move has a specific effect number associated with it, ranging from 0 to 276. There ARE some missing numbers, such as 21, and there are 257 total effects.

The following list was generated with this JQ:

`jq -r 'group_by(.effect) | .[] | "## Effect \(.[0].effect)\nMoves: \(map(.name) | join(", "))\n"' moves.json`

We will include details that impact metronome compass: What rolls occur, in what order, what effects are observable, and how the chance of those effects is determined from the rolls.

# Effect details

## Effect 0
Moves: Pound, Mega Punch, Scratch, Vice Grip, Cut, Wing Attack, Slam, Vine Whip, Mega Kick, Horn Attack, Tackle, Water Gun, Hydro Pump, Peck, Drill Peck, Strength, Rock Throw, Egg Bomb, Megahorn, Hyper Voice, Dragon Claw, Aqua Tail, Seed Bomb, X Scissor, Dragon Pulse, Power Gem, Power Whip

Seems like straight damage.
#TOBEREFINED

## Effect 1
Moves: Sing, Sleep Powder, Hypnosis, Lovely Kiss, Spore, Grass Whistle, Dark Void

#TOBEREFINED

## Effect 2
Moves: Poison Sting, Smog, Sludge, Sludge Bomb, Poison Jab, Gunk Shot

#TOBEREFINED

## Effect 3
Moves: Absorb, Mega Drain, Leech Life, Giga Drain, Drain Punch

#TOBEREFINED

## Effect 4
Moves: Fire Punch, Ember, Flamethrower, Fire Blast, Heat Wave, Lava Plume

#TOBEREFINED

## Effect 5
Moves: Ice Punch, Ice Beam, Powder Snow

#TOBEREFINED

## Effect 6
Moves: Thunder Punch, Body Slam, Thunder Shock, Thunderbolt, Lick, Zap Cannon, Spark, Dragon Breath, Force Palm, Discharge

#TOBEREFINED

## Effect 7
Moves: Selfdestruct, Explosion

#TOBEREFINED

## Effect 8
Moves: Dream Eater

#TOBEREFINED

## Effect 9
Moves: Mirror Move

Not callable by Metronome.

## Effect 10
Moves: Meditate, Sharpen, Howl

#TOBEREFINED

## Effect 11
Moves: Harden, Withdraw

#TOBEREFINED

## Effect 13
Moves: Growth

#TOBEREFINED

## Effect 16
Moves: Double Team

#TOBEREFINED

## Effect 17
Moves: Swift, Faint Attack, Shadow Punch, Aerial Ace, Magical Leaf, Shock Wave, Aura Sphere, Magnet Bomb

#TOBEREFINED

## Effect 18
Moves: Growl

#TOBEREFINED

## Effect 19
Moves: Tail Whip, Leer

#TOBEREFINED

## Effect 20
Moves: String Shot

#TOBEREFINED

## Effect 23
Moves: Sand Attack, Smoke Screen, Kinesis, Flash

#TOBEREFINED

## Effect 24
Moves: Sweet Scent

#TOBEREFINED

## Effect 25
Moves: Haze

#TOBEREFINED

## Effect 26
Moves: Bide

#TOBEREFINED

## Effect 27
Moves: Thrash, Petal Dance, Outrage

#TOBEREFINED

## Effect 28
Moves: Whirlwind, Roar

#TOBEREFINED

## Effect 29
Moves: Double Slap, Comet Punch, Fury Attack, Pin Missile, Spike Cannon, Barrage, Fury Swipes, Bone Rush, Arm Thrust, Bullet Seed, Icicle Spear, Rock Blast

#TOBEREFINED

## Effect 30
Moves: Conversion

#TOBEREFINED

## Effect 31
Moves: Rolling Kick, Headbutt, Bite, Bone Club, Waterfall, Rock Slide, Hyper Fang, Needle Arm, Astonish, Extrasensory, Dark Pulse, Air Slash, Dragon Rush, Zen Headbutt, Iron Head

Flinch chance!

TOCONFIRM: Is flinch chance still rolled when target has already moved?
#TOBEREFINED

## Effect 32
Moves: Recover, Softboiled, Milk Drink, Slack Off, Heal Order

#TOBEREFINED

## Effect 33
Moves: Toxic

#TOBEREFINED

## Effect 34
Moves: Pay Day

#TOBEREFINED

## Effect 35
Moves: Light Screen

#TOBEREFINED

## Effect 36
Moves: Tri Attack

#TOBEREFINED

## Effect 37
Moves: Rest

#TOBEREFINED

## Effect 38
Moves: Guillotine, Horn Drill, Fissure, Sheer Cold

#TOBEREFINED

## Effect 39
Moves: Razor Wind

#TOBEREFINED

## Effect 40
Moves: Super Fang

#TOBEREFINED

## Effect 41
Moves: Dragon Rage

#TOBEREFINED

## Effect 42
Moves: Bind, Wrap, Fire Spin, Clamp, Sand Tomb, Magma Storm

#TOBEREFINED

## Effect 43
Moves: Karate Chop, Razor Leaf, Crabhammer, Slash, Aeroblast, Cross Chop, Air Cutter, Leaf Blade, Night Slash, Shadow Claw, Psycho Cut, Stone Edge, Attack Order, Spacial Rend

#TOBEREFINED

## Effect 44
Moves: Double Kick, Bonemerang, Double Hit

#TOBEREFINED

## Effect 45
Moves: Jump Kick, Hi Jump Kick

#TOBEREFINED

## Effect 46
Moves: Mist

#TOBEREFINED

## Effect 47
Moves: Focus Energy

#TOBEREFINED

## Effect 48
Moves: Take Down, Submission

#TOBEREFINED

## Effect 49
Moves: Supersonic, Confuse Ray, Sweet Kiss

#TOBEREFINED

## Effect 50
Moves: Swords Dance

#TOBEREFINED

## Effect 51
Moves: Barrier, Acid Armor, Iron Defense

#TOBEREFINED

## Effect 52
Moves: Agility, Rock Polish

#TOBEREFINED

## Effect 53
Moves: Tail Glow, Nasty Plot

#TOBEREFINED

## Effect 54
Moves: Amnesia

#TOBEREFINED

## Effect 57
Moves: Transform

#TOBEREFINED

## Effect 58
Moves: Charm, Feather Dance

#TOBEREFINED

## Effect 59
Moves: Screech

#TOBEREFINED

## Effect 60
Moves: Cotton Spore, Scary Face

#TOBEREFINED

## Effect 62
Moves: Fake Tears, Metal Sound

#TOBEREFINED

## Effect 65
Moves: Reflect

#TOBEREFINED

## Effect 66
Moves: Poison Powder, Poison Gas

#TOBEREFINED

## Effect 67
Moves: Stun Spore, Thunder Wave, Glare

#TOBEREFINED

## Effect 68
Moves: Aurora Beam

#TOBEREFINED

## Effect 69
Moves: Iron Tail, Crunch, Rock Smash, Crush Claw

#TOBEREFINED

## Effect 70
Moves: Bubble Beam, Constrict, Bubble, Icy Wind, Rock Tomb, Mud Shot

#TOBEREFINED

## Effect 71
Moves: Mist Ball

#TOBEREFINED

## Effect 72
Moves: Acid, Psychic, Shadow Ball, Luster Purge, Bug Buzz, Focus Blast, Energy Ball, Earth Power, Flash Cannon

#TOBEREFINED

## Effect 73
Moves: Mud Slap, Octazooka, Muddy Water, Mud Bomb, Mirror Shot

#TOBEREFINED

## Effect 75
Moves: Sky Attack

#TOBEREFINED

## Effect 76
Moves: Psybeam, Confusion, Dizzy Punch, Dynamic Punch, Signal Beam, Water Pulse, Rock Climb

#TOBEREFINED

## Effect 77
Moves: Twineedle

#TOBEREFINED

## Effect 78
Moves: Vital Throw

#TOBEREFINED

## Effect 79
Moves: Substitute

#TOBEREFINED

## Effect 80
Moves: Hyper Beam, Blast Burn, Hydro Cannon, Frenzy Plant, Giga Impact, Rock Wrecker, Roar Of Time

#TOBEREFINED

## Effect 81
Moves: Rage

#TOBEREFINED

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

#TOBEREFINED

## Effect 84
Moves: Leech Seed

#TOBEREFINED

## Effect 85
Moves: Splash

#TOBEREFINED

## Effect 86
Moves: Disable

#TOBEREFINED

## Effect 87
Moves: Seismic Toss, Night Shade

#TOBEREFINED

## Effect 88
Moves: Psywave

#TOBEREFINED

## Effect 89
Moves: Counter

Not callable by Metronome.

## Effect 90
Moves: Encore

#TOBEREFINED

## Effect 91
Moves: Pain Split

#TOBEREFINED

## Effect 92
Moves: Snore

#TOBEREFINED

## Effect 93
Moves: Conversion 2

#TOBEREFINED

## Effect 94
Moves: Mind Reader, Lock On

#TOBEREFINED

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

#TOBEREFINED

## Effect 100
Moves: Spite

#TOBEREFINED

## Effect 101
Moves: False Swipe

#TOBEREFINED

## Effect 102
Moves: Heal Bell, Aromatherapy

#TOBEREFINED

## Effect 103
Moves: Quick Attack, Mach Punch, Extreme Speed, Vacuum Wave, Bullet Punch, Ice Shard, Shadow Sneak, Aqua Jet

#TOBEREFINED

## Effect 104
Moves: Triple Kick

#TOBEREFINED

## Effect 105
Moves: Thief, Covet

Not callable by Metronome.

## Effect 106
Moves: Spider Web, Mean Look, Block

#TOBEREFINED

## Effect 107
Moves: Nightmare

#TOBEREFINED

## Effect 108
Moves: Minimize

#TOBEREFINED

## Effect 109
Moves: Curse

#TOBEREFINED

## Effect 111
Moves: Protect, Detect

Not callable by Metronome.

## Effect 112
Moves: Spikes

#TOBEREFINED

## Effect 113
Moves: Foresight, Odor Sleuth

#TOBEREFINED

## Effect 114
Moves: Perish Song

#TOBEREFINED

## Effect 115
Moves: Sandstorm

#TOBEREFINED

## Effect 116
Moves: Endure

Not callable by Metronome.

## Effect 117
Moves: Rollout, Ice Ball

#TOBEREFINED

## Effect 118
Moves: Swagger

#TOBEREFINED

## Effect 119
Moves: Fury Cutter

#TOBEREFINED

## Effect 120
Moves: Attract

#TOBEREFINED

## Effect 121
Moves: Return

#TOBEREFINED

## Effect 122
Moves: Present

#TOBEREFINED

## Effect 123
Moves: Frustration

#TOBEREFINED

## Effect 124
Moves: Safeguard

#TOBEREFINED

## Effect 125
Moves: Flame Wheel, Sacred Fire

#TOBEREFINED

## Effect 126
Moves: Magnitude

#TOBEREFINED

## Effect 127
Moves: Baton Pass

#TOBEREFINED

## Effect 128
Moves: Pursuit

#TOBEREFINED

## Effect 129
Moves: Rapid Spin

#TOBEREFINED

## Effect 130
Moves: Sonic Boom

#TOBEREFINED

## Effect 132
Moves: Morning Sun, Synthesis, Moonlight

#TOBEREFINED

## Effect 135
Moves: Hidden Power

#TOBEREFINED

## Effect 136
Moves: Rain Dance

#TOBEREFINED

## Effect 137
Moves: Sunny Day

#TOBEREFINED

## Effect 138
Moves: Steel Wing

#TOBEREFINED

## Effect 139
Moves: Metal Claw, Meteor Mash

#TOBEREFINED

## Effect 140
Moves: Ancient Power, Silver Wind, Ominous Wind

#TOBEREFINED

## Effect 142
Moves: Belly Drum

#TOBEREFINED

## Effect 143
Moves: Psych Up

#TOBEREFINED

## Effect 144
Moves: Mirror Coat

Not callable by Metronome.

## Effect 145
Moves: Skull Bash

#TOBEREFINED

## Effect 146
Moves: Twister

#TOBEREFINED

## Effect 147
Moves: Earthquake

#TOBEREFINED

## Effect 148
Moves: Future Sight, Doom Desire

#TOBEREFINED

## Effect 149
Moves: Gust

#TOBEREFINED

## Effect 150
Moves: Stomp

#TOBEREFINED

## Effect 151
Moves: Solar Beam

#TOBEREFINED

## Effect 152
Moves: Thunder

#TOBEREFINED

## Effect 153
Moves: Teleport

#TOBEREFINED

## Effect 154
Moves: Beat Up

#TOBEREFINED

## Effect 155
Moves: Fly

#TOBEREFINED

## Effect 156
Moves: Defense Curl

#TOBEREFINED

## Effect 158
Moves: Fake Out

#TOBEREFINED

## Effect 159
Moves: Uproar

#TOBEREFINED

## Effect 160
Moves: Stockpile

#TOBEREFINED

## Effect 161
Moves: Spit Up

#TOBEREFINED

## Effect 162
Moves: Swallow

#TOBEREFINED

## Effect 164
Moves: Hail

#TOBEREFINED

## Effect 165
Moves: Torment

#TOBEREFINED

## Effect 166
Moves: Flatter

#TOBEREFINED

## Effect 167
Moves: Will O Wisp

#TOBEREFINED

## Effect 168
Moves: Memento

#TOBEREFINED

## Effect 169
Moves: Facade

#TOBEREFINED

## Effect 170
Moves: Focus Punch

Not callable by Metronome.

## Effect 171
Moves: Smelling Salt

#TOBEREFINED

## Effect 172
Moves: Follow Me

Not callable by Metronome.

## Effect 173
Moves: Nature Power

#TOBEREFINED

## Effect 174
Moves: Charge

#TOBEREFINED

## Effect 175
Moves: Taunt

#TOBEREFINED

## Effect 176
Moves: Helping Hand

Not callable by Metronome.

## Effect 177
Moves: Trick, Switcheroo

Not callable by Metronome.

## Effect 178
Moves: Role Play

#TOBEREFINED

## Effect 179
Moves: Wish

#TOBEREFINED

## Effect 180
Moves: Assist

Not callable by Metronome.

## Effect 181
Moves: Ingrain

#TOBEREFINED

## Effect 182
Moves: Superpower

#TOBEREFINED

## Effect 183
Moves: Magic Coat

#TOBEREFINED

## Effect 184
Moves: Recycle

#TOBEREFINED

## Effect 185
Moves: Revenge, Avalanche

#TOBEREFINED

## Effect 186
Moves: Brick Break

#TOBEREFINED

## Effect 187
Moves: Yawn

#TOBEREFINED

## Effect 188
Moves: Knock Off

#TOBEREFINED

## Effect 189
Moves: Endeavor

#TOBEREFINED

## Effect 190
Moves: Eruption, Water Spout

#TOBEREFINED

## Effect 191
Moves: Skill Swap

#TOBEREFINED

## Effect 192
Moves: Imprison

#TOBEREFINED

## Effect 193
Moves: Refresh

#TOBEREFINED

## Effect 194
Moves: Grudge

#TOBEREFINED

## Effect 195
Moves: Snatch

Not callable by Metronome.

## Effect 196
Moves: Low Kick, Grass Knot

#TOBEREFINED

## Effect 197
Moves: Secret Power

#TOBEREFINED

## Effect 198
Moves: Double Edge, Brave Bird, Wood Hammer

#TOBEREFINED

## Effect 199
Moves: Teeter Dance

#TOBEREFINED

## Effect 200
Moves: Blaze Kick

#TOBEREFINED

## Effect 201
Moves: Mud Sport

#TOBEREFINED

## Effect 202
Moves: Poison Fang

#TOBEREFINED

## Effect 203
Moves: Weather Ball

#TOBEREFINED

## Effect 204
Moves: Overheat, Psycho Boost, Draco Meteor, Leaf Storm

#TOBEREFINED

## Effect 205
Moves: Tickle

#TOBEREFINED

## Effect 206
Moves: Cosmic Power, Defend Order

#TOBEREFINED

## Effect 207
Moves: Sky Uppercut

#TOBEREFINED

## Effect 208
Moves: Bulk Up

#TOBEREFINED

## Effect 209
Moves: Poison Tail, Cross Poison

#TOBEREFINED

## Effect 210
Moves: Water Sport

#TOBEREFINED

## Effect 211
Moves: Calm Mind

#TOBEREFINED

## Effect 212
Moves: Dragon Dance

#TOBEREFINED

## Effect 213
Moves: Camouflage

#TOBEREFINED

## Effect 214
Moves: Roost

#TOBEREFINED

## Effect 215
Moves: Gravity

#TOBEREFINED

## Effect 216
Moves: Miracle Eye

#TOBEREFINED

## Effect 217
Moves: Wake Up Slap

#TOBEREFINED

## Effect 218
Moves: Hammer Arm

#TOBEREFINED

## Effect 219
Moves: Gyro Ball

#TOBEREFINED

## Effect 220
Moves: Healing Wish

#TOBEREFINED

## Effect 221
Moves: Brine

#TOBEREFINED

## Effect 222
Moves: Natural Gift

#TOBEREFINED

## Effect 223
Moves: Feint

Not callable by Metronome.

## Effect 224
Moves: Pluck, Bug Bite

#TOBEREFINED

## Effect 225
Moves: Tailwind

#TOBEREFINED

## Effect 226
Moves: Acupressure

#TOBEREFINED

## Effect 227
Moves: Metal Burst

#TOBEREFINED

## Effect 228
Moves: U Turn

#TOBEREFINED

## Effect 229
Moves: Close Combat

#TOBEREFINED

## Effect 230
Moves: Payback

#TOBEREFINED

## Effect 231
Moves: Assurance

#TOBEREFINED

## Effect 232
Moves: Embargo

#TOBEREFINED

## Effect 233
Moves: Fling

#TOBEREFINED

## Effect 234
Moves: Psycho Shift

#TOBEREFINED

## Effect 235
Moves: Trump Card

#TOBEREFINED

## Effect 236
Moves: Heal Block

#TOBEREFINED

## Effect 237
Moves: Wring Out, Crush Grip

#TOBEREFINED

## Effect 238
Moves: Power Trick

#TOBEREFINED

## Effect 239
Moves: Gastro Acid

#TOBEREFINED

## Effect 240
Moves: Lucky Chant

#TOBEREFINED

## Effect 241
Moves: Me First

Not callable by Metronome.

## Effect 242
Moves: Copycat

Not callable by Metronome.

## Effect 243
Moves: Power Swap

#TOBEREFINED

## Effect 244
Moves: Guard Swap

#TOBEREFINED

## Effect 245
Moves: Punishment

#TOBEREFINED

## Effect 246
Moves: Last Resort

#TOBEREFINED

## Effect 247
Moves: Worry Seed

#TOBEREFINED

## Effect 248
Moves: Sucker Punch

#TOBEREFINED

## Effect 249
Moves: Toxic Spikes

#TOBEREFINED

## Effect 250
Moves: Heart Swap

#TOBEREFINED

## Effect 251
Moves: Aqua Ring

#TOBEREFINED

## Effect 252
Moves: Magnet Rise

#TOBEREFINED

## Effect 253
Moves: Flare Blitz

#TOBEREFINED

## Effect 254
Moves: Struggle

Not callable by Metronome, but must be implemented - Used when no other moves can be used. We won't be having our metronome users struggle, but Magikarp can be forced to struggle.
#TOBEREFINED

## Effect 255
Moves: Dive

#TOBEREFINED

## Effect 256
Moves: Dig

#TOBEREFINED

## Effect 257
Moves: Surf

#TOBEREFINED

## Effect 258
Moves: Defog

#TOBEREFINED

## Effect 259
Moves: Trick Room

#TOBEREFINED

## Effect 260
Moves: Blizzard

#TOBEREFINED

## Effect 261
Moves: Whirlpool

#TOBEREFINED

## Effect 262
Moves: Volt Tackle

#TOBEREFINED

## Effect 263
Moves: Bounce

#TOBEREFINED

## Effect 265
Moves: Captivate

#TOBEREFINED

## Effect 266
Moves: Stealth Rock

#TOBEREFINED

## Effect 267
Moves: Chatter

Not callable by Metronome.

## Effect 268
Moves: Judgment

#TOBEREFINED

## Effect 269
Moves: Head Smash

#TOBEREFINED

## Effect 270
Moves: Lunar Dance

#TOBEREFINED

## Effect 271
Moves: Seed Flare

#TOBEREFINED

## Effect 272
Moves: Shadow Force

#TOBEREFINED

## Effect 273
Moves: Fire Fang

#TOBEREFINED

## Effect 274
Moves: Ice Fang

#TOBEREFINED

## Effect 275
Moves: Thunder Fang

#TOBEREFINED

## Effect 276
Moves: Charge Beam

#TOBEREFINED

