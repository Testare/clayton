
  One note for when you next verify interactively: the "is confused!" status line that shows every confused turn is deliberately not tokenized on attack-through turns — only the discriminating outcomes (CFZ
  hit-self, SCFZ snap) emit tokens, and the plain metronome move covers the attack-through case. If you'd rather the path visibly mark every confused turn, that's a small addition — let me know.



Test seed: 0x01001386

Magikarp splash
Power trick

Tackle hit
Ember hit

Tackle hit
Kinesis

Splash
Thunder Fang
Paralyzed

Tackle
Body Slam

Tackle
Fury Attack 3 times

Full para
Rapid Spin

Tackle miss
Power whip

Magikarp fainted

Wow that worked really quickly.


## Compass testing
### Run 1 (S)

10F
Splash

String Shot
Withdraw
Sharpen
ExtremeSpeed
Rain Dance
Heal Bell
Sand-Attack
Baton Pass

SEED IDENTIFIED:

  0xE70E0649    1609  -272  KspM159            (Sharpen)

Seed identified: 0xE70E0649  time=2025-07-24 14:46:17  delay=1609  dD=-272

Path: KspM081h KspM110 KspM159 KspM245h KspM240 KspM215 KspM028h KspM226_

Corresponding moves:
* String Shot
* Withdraw
* Sharpen
* ExtremeSpeed
* Rain Dance
* Heal Bell
* Sand Attack
* Baton Pass

Perfect match!

### Run 2 (S)

13 M

* Captivate
* Odor Sleuth
* Tail Glow
* Dragon Dance
* Faint Attack
* Minimize
* Brave Bird
* ExtremeSpeed
* Rain Dance
* Power Swap

0xE70E0639    1593   -16  KspM294            (Tail Glow)

Seed identified: 0xE70E0639  time=2025-07-24 14:46:17  delay=1593  dD=-16

Perfect match to prediction!

### Run 3 (L)
M: 11 M
REL: 44 46 20
INITIAL DELAY: 689
INITIAL SEED: 
* 0B0E02CA  (11 M at frame 7)
* 0C0E02CA (11 M at frame 5)

        Seed   Delay    dD  predicted turn 3
  0xE70E0628    1576   -33  KspM252            (Fake Out)

Seed identified: 0xE70E0628  time=2025-07-24 14:46:17  delay=1576  dD=-33
Remaining Metronome moves (turn 3+):
  Turn 3: Fake Out (M252)
  Turn 4: Baton Pass (M226)


### Run 4 (L)
M: 10 M
REL: 32 33 17
INITIAL DELAY: 685
A SEED: 0C0E02C6 (10 M at frame 4)

* Body Slam
* Uproar

Seed identified: 0xE60E062D  time=2025-07-24 14:46:16  delay=1581  dD=-28
Remaining Metronome moves (turn 3+):
  Turn 8: Aqua Ring (M392)
  Turn 9: Wing Attack (M017)
  Turn 10: Skull Bash (M130)

### Run 5 (L)
M: 8 M
REL: 33 36 11
A DELAY: 675
A SEED: 0C0E02BC (8 M at frame 4)
Different level magikarp, but otherwise identical to Run 4

## 40 second

Estimated time: 14:46:37
Estimated delay: 681 + (1581 - 681)*2 = 2481?

REL before Run 3: 39 39 6
REL from Run 3 on, "REL+" : 43 30 8

### Run 1 (L)

M: 9 F
REL: 33 36 13
A SEED: 0d0e02bc (9 F at frame 4)
A SEC: 56
A DELAY: 675 

* Bug bite
* Tri attack
* Flame wheel
* False Swipe
* Aura Sphere
* Knock Off
* Growth
* Perish Song
* Stealth Rock
* Bite

Seed identified: 0xFB0E0AD4  time=2025-07-24 14:46:37  delay=2772  dD=+291
Remaining Metronome moves (turn 3+):
  Turn 3: Flame Wheel (M172)
  Turn 4: False Swipe (M206)
  Turn 5: Aura Sphere (M396)
  Turn 6: Knock Off (M282)
  Turn 7: Growth (M074)
  Turn 8: Perish Song (M195)
  Turn 9: Stealth Rock (M446)
  Turn 10: Bite (M044)

## Run 2 (L)

M: 16 M
REL: 45 42 5
A DELAY: 669
A SEED: 0d0e02b6 (16 M at frame 3)
A SEC: 56

* M-Tackle crit
* Nightmare fails
* M-Tackle
* ThunderShock Para
<Oops I don't have lagging tail on>

Seed identified: 0xFB0E0AC7  time=2025-07-24 14:46:37  delay=2759  dD=+278
Remaining Metronome moves (turn 2+):
  Turn 2: Thunder Shock (M084)
  Turn 3: Tailwind (M366)
  Turn 4: Aura Sphere (M396)
  Turn 5: Fury Cutter (M210)
  Turn 6: Screech (M103)
  Turn 7: Headbutt (M029)
  Turn 8: Belly Drum (M187) 

## Run 3 (S)
M: 8 M
REL: 38 33 22
A DELAY: 691
A SEED: c0e02cc (@F5)

* Endeavor Fails
* Poison Fang
* Bullet seed - Hit 5 times, no crits
* Weather ball crit - Magikarp Faints

Seed identified: 0xFA0E0AAD  time=2025-07-24 14:46:36  delay=2733  dD=+252
Remaining Metronome moves (turn 3+):
  Turn 3: Bullet Seed (M331)
  Turn 4: Weather Ball (M311)
  Turn 5: Magma Storm (M463)
  Turn 6: Barrier (M112)
  Turn 7: Weather Ball (M311)
  Turn 8: Powder Snow (M181)
  Turn 9: Roar Of Time (M459)
  Turn 10: Perish Song (M195)

## Run 4
M: 12 M
REL: 39 39 14
A DELAY: 691*
A SEED: c0e02c2* (On the money)

* Charm
* Fire spin
* Acid

Seed identified: 0xFA0E0AC5  time=2025-07-24 14:46:36  delay=2757  dD=+276
Remaining Metronome moves (turn 3+):
  Turn 3: Acid (M051)
  Turn 4: Mega Punch (M005)
  Turn 5: Tail Glow (M294)
  Turn 6: Milk Drink (M208)
  Turn 7: Double Hit (M458)
  Turn 8: Belly Drum (M187)
  Turn 9: Thunder (M087)
  Turn 10: Rock Blast (M350)

(Magikarp faints after thunder)

## Run 5
M: 2 F
REL: 31 45 26
A DELAY: 695
A SEED: 0D0E02D0 (@F5)

* Vine whip
* Lovely Kiss
* Double Kick
* Foresight
* Magikarp woke up
* Bullet seed

Seed identified: 0xFA0E0ACD  time=2025-07-24 14:46:36  delay=2765  dD=+284
Remaining Metronome moves (turn 3+):
  Turn 3: Double Kick (M024)
  Turn 4: Foresight (M193)
  Turn 5: Bullet Seed (M331)
  Turn 6: Mega Kick (M025)
  Turn 7: Glare (M137)
  Turn 8: Sandstorm (M201)
  Turn 9: Flail (M175)
  Turn 10: Sing (M047)

# 60 seconds
## Run 1

M:
REL:
A DELAY:
A SEED:
