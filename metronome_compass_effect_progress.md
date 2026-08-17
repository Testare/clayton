# Metronome Compass Effect Progress

Tracks implementation status of all move effects from `notes/refined/effects.md`.

## Statuses

- **IMPLEMENTED** — handler exists and correctly models RNG rolls / state changes
- **NOT_YET_IMPLEMENTED** — currently emits `Unsupported()`; implementing it would add correct observable tokens and/or correct path structure (e.g. suppressing metronome rolls on consecutive turns)
- **SUPPORT_NOT_PLANNED** — currently emits `Unsupported()`; even a correct implementation would add no observable path tokens and would not affect path structure in a way that helps seed identification
- **NCM** — not callable by Metronome; no status applies

## Effect List

| Effect | Moves | Status | Notes |
|--------|-------|--------|-------|
| 0 | Pound, Tackle, Hydro Pump, … | IMPLEMENTED | `_eff_damage` |
| 1 | Sing, Sleep Powder, Spore, … | IMPLEMENTED | `_eff_sleep` |
| 2 | Poison Sting, Sludge Bomb, … | IMPLEMENTED | `_eff_damage_secondary` |
| 3 | Absorb, Mega Drain, Drain Punch | IMPLEMENTED | `_eff_damage` |
| 4 | Fire Punch, Flamethrower, Fire Blast | IMPLEMENTED | `_eff_damage_secondary` |
| 5 | Ice Punch, Ice Beam, Powder Snow | IMPLEMENTED | `_eff_damage_secondary` |
| 6 | Thunder Punch, Body Slam, Thunderbolt, … | IMPLEMENTED | `_eff_damage_secondary` |
| 7 | Selfdestruct, Explosion | IMPLEMENTED | `_eff_selfdestruct` — C/D/H then path ends |
| 8 | Dream Eater | IMPLEMENTED | `_eff_dream_eater` |
| 9 | Mirror Move | NCM | |
| 10 | Meditate, Sharpen, Howl | IMPLEMENTED | `_eff_no_rolls_ok` |
| 11 | Harden, Withdraw | IMPLEMENTED | `_eff_no_rolls_ok` |
| 13 | Growth | IMPLEMENTED | `_eff_no_rolls_ok` |
| 16 | Double Team | IMPLEMENTED | `_eff_no_rolls_ok` |
| 17 | Swift, Aerial Ace, Aura Sphere, … | IMPLEMENTED | `_eff_damage` (accuracy=0) |
| 18 | Growl | IMPLEMENTED | `_eff_hit_only` |
| 19 | Tail Whip, Leer | IMPLEMENTED | `_eff_hit_only` |
| 20 | String Shot | IMPLEMENTED | `_eff_hit_only` |
| 23 | Sand Attack, Flash, Kinesis | IMPLEMENTED | `_eff_hit_only` |
| 24 | Sweet Scent | IMPLEMENTED | `_eff_hit_only` |
| 25 | Haze | IMPLEMENTED | `_eff_no_rolls_ok` |
| 26 | Bide | IMPLEMENTED | `_eff_bide` — turn 1 sets lock (user_locked_turns=2, no rolls); turn 2 continuation returns True (no rolls); turn 3 final: if `user_bide_triggered` (Magikarp hit with Tackle/Struggle on turns 1-2) returns True (damage, no rolls) else returns False. `user_substitute` active on turn 1 → Unsupported immediately. |
| 27 | Thrash, Petal Dance, Outrage | IMPLEMENTED | `_eff_thrash` — turn 1 C/D/H + observable duration roll (2+RAND%2 total turns); continuation turns suppress metronome roll via `simulate_locked_continuation`; REND token + confusion applied at end of last continuation turn. |
| 28 | Whirlwind, Roar | IMPLEMENTED | `_eff_whirlwind` — hit check + unobservable roll + path ends |
| 29 | Double Slap, Fury Attack, Bullet Seed, … | IMPLEMENTED | `_eff_multi_hit` |
| 30 | Conversion | IMPLEMENTED | `_eff_conversion` — rolls until non-matching type found; emits `ConversionType` token. `user_move_types` in `battle_state` derived from `known_moves` + Metronome at context init. |
| 31 | Rolling Kick, Headbutt, Bite, Air Slash, … | IMPLEMENTED | `_eff_damage_flinch` |
| 32 | Recover, Softboiled, Milk Drink, … | IMPLEMENTED | `_eff_recovery` |
| 33 | Toxic | IMPLEMENTED | `_eff_poison_hit` |
| 34 | Pay Day | IMPLEMENTED | `_eff_damage` |
| 35 | Light Screen | IMPLEMENTED | `_eff_light_screen` |
| 36 | Tri Attack | IMPLEMENTED | `_eff_tri_attack` |
| 37 | Rest | IMPLEMENTED | `_eff_rest` |
| 38 | Guillotine, Horn Drill, Fissure, Sheer Cold | IMPLEMENTED | `_eff_ohko` |
| 39 | Razor Wind | IMPLEMENTED | `_eff_charge_fire` — turn 1 sets lock (no rolls); turn 2 C/D/H via `simulate_locked_continuation`. |
| 40 | Super Fang | IMPLEMENTED | `_eff_hit_only` |
| 41 | Dragon Rage | IMPLEMENTED | `_eff_hit_only` |
| 42 | Bind, Wrap, Fire Spin, Clamp, … | IMPLEMENTED | `_eff_bind` |
| 43 | Karate Chop, Slash, Leaf Blade, … | IMPLEMENTED | `_eff_high_crit` |
| 44 | Double Kick, Bonemerang, Double Hit | IMPLEMENTED | `_eff_double_hit` |
| 45 | Jump Kick, Hi Jump Kick | IMPLEMENTED | `_eff_damage` |
| 46 | Mist | IMPLEMENTED | `_eff_mist` |
| 47 | Focus Energy | IMPLEMENTED | `_eff_focus_energy` |
| 48 | Take Down, Submission | IMPLEMENTED | `_eff_damage` |
| 49 | Supersonic, Confuse Ray, Sweet Kiss | IMPLEMENTED | `_eff_confuse_hit` |
| 50 | Swords Dance | IMPLEMENTED | `_eff_no_rolls_ok` |
| 51 | Barrier, Acid Armor, Iron Defense | IMPLEMENTED | `_eff_no_rolls_ok` |
| 52 | Agility, Rock Polish | IMPLEMENTED | `_eff_no_rolls_ok` |
| 53 | Tail Glow, Nasty Plot | IMPLEMENTED | `_eff_no_rolls_ok` |
| 54 | Amnesia | IMPLEMENTED | `_eff_no_rolls_ok` |
| 57 | Transform | SUPPORT_NOT_PLANNED | No rolls on use. After transform Chansey loses Metronome entirely — no future metronome path possible. The turn contributes no observable tokens and ends the metronome path. |
| 58 | Charm, Feather Dance | IMPLEMENTED | `_eff_hit_only` |
| 59 | Screech | IMPLEMENTED | `_eff_hit_only` |
| 60 | Cotton Spore, Scary Face | IMPLEMENTED | `_eff_hit_only` |
| 62 | Fake Tears, Metal Sound | IMPLEMENTED | `_eff_hit_only` |
| 65 | Reflect | IMPLEMENTED | `_eff_reflect` |
| 66 | Poison Powder, Poison Gas | IMPLEMENTED | `_eff_poison_hit` |
| 67 | Stun Spore, Thunder Wave, Glare | IMPLEMENTED | `_eff_paralyze` |
| 68 | Aurora Beam | IMPLEMENTED | `_eff_damage_secondary` |
| 69 | Iron Tail, Crunch, Rock Smash, Crush Claw | IMPLEMENTED | `_eff_damage_secondary` |
| 70 | Bubble Beam, Icy Wind, Rock Tomb, Mud Shot, … | IMPLEMENTED | `_eff_damage_secondary` |
| 71 | Mist Ball | IMPLEMENTED | `_eff_damage_secondary` |
| 72 | Acid, Psychic, Shadow Ball, Bug Buzz, … | IMPLEMENTED | `_eff_damage_secondary` |
| 73 | Mud Slap, Muddy Water, Mirror Shot, … | IMPLEMENTED | `_eff_damage_secondary` |
| 75 | Sky Attack | IMPLEMENTED | `_eff_sky_attack` — turn 1 sets lock; turn 2 C/D/H + advance_unobservable(1) for flinch (unobservable; we go second). |
| 76 | Psybeam, Confusion, Water Pulse, … | IMPLEMENTED | `_eff_damage_confuse` |
| 77 | Twineedle | IMPLEMENTED | `_eff_twineedle` |
| 78 | Vital Throw | IMPLEMENTED | `_eff_damage` (always-hit) |
| 79 | Substitute | IMPLEMENTED | `_eff_substitute` |
| 80 | Hyper Beam, Blast Burn, Giga Impact, … | IMPLEMENTED | `_eff_hyper_beam` |
| 81 | Rage | IMPLEMENTED | `_eff_damage` |
| 82 | Mimic | NCM | |
| 83 | Metronome | NCM | Not callable by itself |
| 84 | Leech Seed | IMPLEMENTED | `_eff_leech_seed` |
| 85 | Splash | IMPLEMENTED | `_eff_splash` |
| 86 | Disable | IMPLEMENTED | `_eff_disable` |
| 87 | Seismic Toss, Night Shade | IMPLEMENTED | `_eff_seismic_toss` |
| 88 | Psywave | IMPLEMENTED | `_eff_psywave` |
| 89 | Counter | NCM | |
| 90 | Encore | IMPLEMENTED | `_eff_encore` |
| 91 | Pain Split | IMPLEMENTED | `_eff_pain_split` |
| 92 | Snore | IMPLEMENTED | `_eff_hit_only` (hit check performed; always fails — user can't be asleep for metronome) |
| 93 | Conversion 2 | IMPLEMENTED | `_eff_conversion2` — prereq: `user_was_hit` (Magikarp hit with Tackle/Struggle). Rolls %112 against effectiveness table; given Magikarp is Normal-type only, valid results are index 0 (Rock), 1 (Steel), 109 (Ghost). Emits `ConversionType` token. Resets `user_was_hit`. |
| 94 | Mind Reader, Lock On | IMPLEMENTED | `_eff_no_rolls_ok` |
| 95 | Sketch | NCM | |
| 97 | Sleep Talk | NCM | |
| 98 | Destiny Bond | NCM | |
| 99 | Flail, Reversal | IMPLEMENTED | `_eff_damage` |
| 100 | Spite | IMPLEMENTED | `_eff_hit_only` |
| 101 | False Swipe | IMPLEMENTED | `_eff_damage` |
| 102 | Heal Bell, Aromatherapy | IMPLEMENTED | `_eff_no_rolls_ok` |
| 103 | Quick Attack, Mach Punch, Extreme Speed, … | IMPLEMENTED | `_eff_damage` |
| 104 | Triple Kick | IMPLEMENTED | `_eff_triple_kick` |
| 105 | Thief, Covet | NCM | |
| 106 | Spider Web, Mean Look, Block | IMPLEMENTED | `_eff_spider_web` |
| 107 | Nightmare | IMPLEMENTED | `_eff_nightmare` |
| 108 | Minimize | IMPLEMENTED | `_eff_no_rolls_ok` |
| 109 | Curse | IMPLEMENTED | `_eff_no_rolls_ok` |
| 111 | Protect, Detect | NCM | |
| 112 | Spikes | IMPLEMENTED | `_eff_spikes` |
| 113 | Foresight, Odor Sleuth | IMPLEMENTED | `_eff_no_rolls_ok` |
| 114 | Perish Song | IMPLEMENTED | `_eff_perish_song` |
| 115 | Sandstorm | IMPLEMENTED | `_eff_sandstorm` |
| 116 | Endure | NCM | |
| 117 | Rollout, Ice Ball | IMPLEMENTED | `_eff_rollout` — turn 1 C/D/H; if hit sets user_locked_turns=4. Continuation C/D/H; miss clears lock early. Damage multiplier is unobservable. |
| 118 | Swagger | IMPLEMENTED | `_eff_swagger` |
| 119 | Fury Cutter | IMPLEMENTED | `_eff_damage` |
| 120 | Attract | IMPLEMENTED | `_eff_attract` |
| 121 | Return | IMPLEMENTED | `_eff_damage` |
| 122 | Present | IMPLEMENTED | `_eff_present` |
| 123 | Frustration | IMPLEMENTED | `_eff_damage` |
| 124 | Safeguard | IMPLEMENTED | `_eff_safeguard` |
| 125 | Flame Wheel, Sacred Fire | IMPLEMENTED | `_eff_damage_secondary` |
| 126 | Magnitude | IMPLEMENTED | `_eff_magnitude` |
| 127 | Baton Pass | IMPLEMENTED | `_eff_baton_pass` — path ends |
| 128 | Pursuit | IMPLEMENTED | `_eff_damage` |
| 129 | Rapid Spin | IMPLEMENTED | `_eff_damage` |
| 130 | Sonic Boom | IMPLEMENTED | `_eff_hit_only` |
| 132 | Morning Sun, Synthesis, Moonlight | IMPLEMENTED | `_eff_recovery` |
| 135 | Hidden Power | IMPLEMENTED | `_eff_damage` |
| 136 | Rain Dance | IMPLEMENTED | `_eff_rain_dance` |
| 137 | Sunny Day | IMPLEMENTED | `_eff_sunny_day` |
| 138 | Steel Wing | IMPLEMENTED | `_eff_damage_secondary` |
| 139 | Metal Claw, Meteor Mash | IMPLEMENTED | `_eff_damage_secondary` |
| 140 | Ancient Power, Silver Wind, Ominous Wind | IMPLEMENTED | `_eff_damage_secondary` |
| 142 | Belly Drum | IMPLEMENTED | `_eff_belly_drum` |
| 143 | Psych Up | IMPLEMENTED | `_eff_no_rolls_ok` |
| 144 | Mirror Coat | NCM | |
| 145 | Skull Bash | IMPLEMENTED | `_eff_skull_bash` — turn 1 advance_unobservable(1) (#FUTUREWORK) + sets lock; turn 2 C/D/H. |
| 146 | Twister | IMPLEMENTED | `_eff_damage_flinch` |
| 147 | Earthquake | IMPLEMENTED | `_eff_damage` |
| 148 | Future Sight, Doom Desire | IMPLEMENTED | `_eff_future_sight` — turn 1 advance_unobservable(1) + sets future_sight_turns=3. Re-use while active: advance_unobservable(1), returns False. End-of-turn in simulate_turn: ticks counter; at 0 emits observable hit check (Hit/Miss). |
| 149 | Gust | IMPLEMENTED | `_eff_damage` |
| 150 | Stomp | IMPLEMENTED | `_eff_damage_flinch` |
| 151 | Solar Beam | IMPLEMENTED | `_eff_solar_beam` — if weather=='sunny': immediate C/D/H. Otherwise: sets lock; turn 2 C/D/H. |
| 152 | Thunder | IMPLEMENTED | `_eff_thunder` (weather-dependent accuracy and always-hit) |
| 153 | Teleport | IMPLEMENTED | `_eff_teleport` — path ends |
| 154 | Beat Up | IMPLEMENTED | `_eff_beat_up` |
| 155 | Fly | IMPLEMENTED | `_eff_charge_fire` — turn 1 sets lock (no rolls); turn 2 C/D/H via `simulate_locked_continuation`. |
| 156 | Defense Curl | IMPLEMENTED | `_eff_no_rolls_ok` |
| 158 | Fake Out | IMPLEMENTED | `_eff_fake_out` |
| 159 | Uproar | IMPLEMENTED | `_eff_uproar` — turn 1 C/D/H + observable duration roll (2+RAND%4 extra turns); continuation C/D/H; lock does NOT end early on miss. No confusion at end. |
| 160 | Stockpile | IMPLEMENTED | `_eff_stockpile` |
| 161 | Spit Up | IMPLEMENTED | `_eff_spit_up` |
| 162 | Swallow | IMPLEMENTED | `_eff_swallow` |
| 164 | Hail | IMPLEMENTED | `_eff_hail` |
| 165 | Torment | IMPLEMENTED | `_eff_torment` |
| 166 | Flatter | IMPLEMENTED | `_eff_flatter` |
| 167 | Will-O-Wisp | IMPLEMENTED | `_eff_will_o_wisp` |
| 168 | Memento | IMPLEMENTED | `_eff_memento` |
| 169 | Facade | IMPLEMENTED | `_eff_damage` |
| 170 | Focus Punch | NCM | |
| 171 | Smelling Salt | IMPLEMENTED | `_eff_damage` |
| 172 | Follow Me | NCM | |
| 173 | Nature Power | IMPLEMENTED | `_eff_damage` (always Hydro Pump in this context) |
| 174 | Charge | IMPLEMENTED | `_eff_no_rolls_ok` |
| 175 | Taunt | IMPLEMENTED | `_eff_taunt` |
| 176 | Helping Hand | NCM | |
| 177 | Trick, Switcheroo | NCM | |
| 178 | Role Play | IMPLEMENTED | `_eff_no_rolls_ok` |
| 179 | Wish | IMPLEMENTED | `_eff_no_rolls_ok` |
| 180 | Assist | NCM | |
| 181 | Ingrain | IMPLEMENTED | `_eff_ingrain` |
| 182 | Superpower | IMPLEMENTED | `_eff_damage` |
| 183 | Magic Coat | IMPLEMENTED | `_eff_no_rolls_fail` (Chansey goes second; always fails) |
| 184 | Recycle | IMPLEMENTED | `_eff_no_rolls_fail` (holding Lagging Tail, no lost item) |
| 185 | Revenge, Avalanche | IMPLEMENTED | `_eff_damage` |
| 186 | Brick Break | IMPLEMENTED | `_eff_damage` |
| 187 | Yawn | IMPLEMENTED | `_eff_yawn` — drowsy state applied; sleep + duration via `unobservable_roll()` at end of next turn |
| 188 | Knock Off | IMPLEMENTED | `_eff_damage` |
| 189 | Endeavor | SUPPORT_NOT_PLANNED | In P0 Magikarp HP << Chansey HP so Endeavor always fails. Hit check is still rolled but always yields Miss, adding no seed-differentiating information. |
| 190 | Eruption, Water Spout | IMPLEMENTED | `_eff_damage` |
| 191 | Skill Swap | IMPLEMENTED | `_eff_no_rolls_ok` |
| 192 | Imprison | IMPLEMENTED | `_eff_no_rolls_fail` (no shared moves in P0) |
| 193 | Refresh | IMPLEMENTED | `_eff_no_rolls_fail` (Magikarp can't inflict status on user) |
| 194 | Grudge | IMPLEMENTED | `_eff_no_rolls_ok` |
| 195 | Snatch | NCM | |
| 196 | Low Kick, Grass Knot | IMPLEMENTED | `_eff_damage` |
| 197 | Secret Power | IMPLEMENTED | `_eff_damage_secondary` |
| 198 | Double-Edge, Brave Bird, Wood Hammer | IMPLEMENTED | `_eff_damage` |
| 199 | Teeter Dance | IMPLEMENTED | `_eff_teeter_dance` |
| 200 | Blaze Kick | IMPLEMENTED | `_eff_high_crit_secondary` |
| 201 | Mud Sport | IMPLEMENTED | `_eff_mud_sport` |
| 202 | Poison Fang | IMPLEMENTED | `_eff_damage_secondary` |
| 203 | Weather Ball | IMPLEMENTED | `_eff_damage` |
| 204 | Overheat, Psycho Boost, Draco Meteor, Leaf Storm | IMPLEMENTED | `_eff_damage_secondary` |
| 205 | Tickle | IMPLEMENTED | `_eff_hit_only` |
| 206 | Cosmic Power, Defend Order | IMPLEMENTED | `_eff_no_rolls_ok` |
| 207 | Sky Uppercut | IMPLEMENTED | `_eff_damage` |
| 208 | Bulk Up | IMPLEMENTED | `_eff_no_rolls_ok` |
| 209 | Poison Tail, Cross Poison | IMPLEMENTED | `_eff_high_crit_secondary` |
| 210 | Water Sport | IMPLEMENTED | `_eff_water_sport` |
| 211 | Calm Mind | IMPLEMENTED | `_eff_no_rolls_ok` |
| 212 | Dragon Dance | IMPLEMENTED | `_eff_no_rolls_ok` |
| 213 | Camouflage | IMPLEMENTED | `_eff_no_rolls_ok` (always Water type in this environment) |
| 214 | Roost | IMPLEMENTED | `_eff_recovery` |
| 215 | Gravity | IMPLEMENTED | `_eff_gravity` |
| 216 | Miracle Eye | IMPLEMENTED | `_eff_no_rolls_ok` |
| 217 | Wake-Up Slap | IMPLEMENTED | `_eff_damage` |
| 218 | Hammer Arm | IMPLEMENTED | `_eff_damage` |
| 219 | Gyro Ball | IMPLEMENTED | `_eff_damage` |
| 220 | Healing Wish | IMPLEMENTED | `_eff_healing_wish` — path ends |
| 221 | Brine | IMPLEMENTED | `_eff_damage` |
| 222 | Natural Gift | IMPLEMENTED | `_eff_hit_only` (always fails holding Lagging Tail; hit check still performed) |
| 223 | Feint | NCM | |
| 224 | Pluck, Bug Bite | IMPLEMENTED | `_eff_damage` |
| 225 | Tailwind | IMPLEMENTED | `_eff_tailwind` |
| 226 | Acupressure | IMPLEMENTED | `_eff_acupressure` |
| 227 | Metal Burst | IMPLEMENTED | `_eff_hit_only` |
| 228 | U-Turn | IMPLEMENTED | `_eff_u_turn` — C/D/H then path ends |
| 229 | Close Combat | IMPLEMENTED | `_eff_damage` |
| 230 | Payback | IMPLEMENTED | `_eff_damage` |
| 231 | Assurance | IMPLEMENTED | `_eff_damage` |
| 232 | Embargo | IMPLEMENTED | `_eff_embargo` |
| 233 | Fling | IMPLEMENTED | `_eff_fling` — C/D/H then path ends |
| 234 | Psycho Shift | IMPLEMENTED | `_eff_hit_only` (no status on user to transfer) |
| 235 | Trump Card | IMPLEMENTED | `_eff_damage` (always-hit) |
| 236 | Heal Block | IMPLEMENTED | `_eff_heal_block` |
| 237 | Wring Out, Crush Grip | IMPLEMENTED | `_eff_damage` |
| 238 | Power Trick | IMPLEMENTED | `_eff_no_rolls_ok` |
| 239 | Gastro Acid | IMPLEMENTED | `_eff_gastro_acid` |
| 240 | Lucky Chant | IMPLEMENTED | `_eff_lucky_chant` |
| 241 | Me First | NCM | |
| 242 | Copycat | NCM | |
| 243 | Power Swap | IMPLEMENTED | `_eff_no_rolls_ok` |
| 244 | Guard Swap | IMPLEMENTED | `_eff_no_rolls_ok` |
| 245 | Punishment | IMPLEMENTED | `_eff_damage` |
| 246 | Last Resort | IMPLEMENTED | `_eff_hit_only` (always fails from Metronome) |
| 247 | Worry Seed | IMPLEMENTED | `_eff_worry_seed` |
| 248 | Sucker Punch | IMPLEMENTED | `_eff_hit_only` (Magikarp never selecting a damage move) |
| 249 | Toxic Spikes | IMPLEMENTED | `_eff_toxic_spikes` |
| 250 | Heart Swap | IMPLEMENTED | `_eff_no_rolls_ok` |
| 251 | Aqua Ring | IMPLEMENTED | `_eff_aqua_ring` |
| 252 | Magnet Rise | IMPLEMENTED | `_eff_magnet_rise` |
| 253 | Flare Blitz | IMPLEMENTED | `_eff_damage_secondary` |
| 254 | Struggle | NCM | Not callable by Metronome; Magikarp use handled separately |
| 255 | Dive | IMPLEMENTED | `_eff_charge_fire` — turn 1 sets lock (no rolls); turn 2 C/D/H via `simulate_locked_continuation`. |
| 256 | Dig | IMPLEMENTED | `_eff_charge_fire` — turn 1 sets lock (no rolls); turn 2 C/D/H via `simulate_locked_continuation`. |
| 257 | Surf | IMPLEMENTED | `_eff_damage` |
| 258 | Defog | IMPLEMENTED | `_eff_defog` |
| 259 | Trick Room | IMPLEMENTED | `_eff_trick_room` (4 unobservable rolls after setup) |
| 260 | Blizzard | IMPLEMENTED | `_eff_blizzard` (always-hit in hail) |
| 261 | Whirlpool | IMPLEMENTED | `_eff_bind` |
| 262 | Volt Tackle | IMPLEMENTED | `_eff_damage_secondary` |
| 263 | Bounce | IMPLEMENTED | `_eff_bounce` — turn 1 sets lock; turn 2 C/D/H + observable paralyze proc via `effect_proc`. |
| 265 | Captivate | IMPLEMENTED | `_eff_captivate` |
| 266 | Stealth Rock | IMPLEMENTED | `_eff_stealth_rock` |
| 267 | Chatter | NCM | |
| 268 | Judgment | IMPLEMENTED | `_eff_damage` |
| 269 | Head Smash | IMPLEMENTED | `_eff_damage` |
| 270 | Lunar Dance | IMPLEMENTED | `_eff_lunar_dance` — path ends |
| 271 | Seed Flare | IMPLEMENTED | `_eff_damage_secondary` |
| 272 | Shadow Force | IMPLEMENTED | `_eff_charge_fire` — turn 1 sets lock (no rolls); turn 2 C/D/H via `simulate_locked_continuation`. |
| 273 | Fire Fang | IMPLEMENTED | `_eff_damage_status_flinch` |
| 274 | Ice Fang | IMPLEMENTED | `_eff_damage_status_flinch` |
| 275 | Thunder Fang | IMPLEMENTED | `_eff_damage_status_flinch` |
| 276 | Charge Beam | IMPLEMENTED | `_eff_damage_secondary` |

## Summary

| Status | Count |
|--------|-------|
| IMPLEMENTED | 221 |
| NOT_YET_IMPLEMENTED | 0 |
| SUPPORT_NOT_PLANNED | 2 (Transform=57, Endeavor=189) |
| NCM | 24 |
