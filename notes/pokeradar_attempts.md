# Attempt 1
Seed hit: 0xEE0203F1

Did 2 journal flips and used pokeradar, matched utility, including hard shake at -(1, -1). Utility says 9 rolls were consumed.

Utility says slot 5 at 18 advances, so I did 3 journal flips (3*4+2 => 14), then turned, walked, turned, walked.

4+9+14 => 27 advances total

I encountered machoke 48 M.
* Machoke, Lvl 48 (Slot 0)
* Male
* Timid Nature
* "Often scatters things"
* stats 147/90/78/61/63/58
* No Guard

Except for the characteristic (Which I might've messed up for pokefinder might have messed up), this matches the machoke at advance 33. Given we are off by my party count, it's possible I hit the counter RNG advance, so I'll take a couple steps then resave.

Then I missed recording the follow-up.

# Attempt 2

(I took a couple steps and resaved and reloaded before hitting the seed so that the party count issue would not recur)
Seed hit: 0xEE0203EF

18 advances to find hard shaking grass, 9 pages. Everything matches utility. Utility claims 11 rolls consumed, bringing us to 29.

Slot 4 in 2 advances, so I just turned and walked into the grass (2 advances, turn and step). Got Graveler 49 M, still not primeape.

Graveler
* 49 M (Slot 1)
* Impish
* Sturdy Body
* 119 108 145 54 60 40
* Rock Head


Clip shows shaking grass at (+1, +1) (soft), (-2, +2) (hard), (-2, +3) (hard), and 4th ring not visible (But might be near trees at bottom left)

This matches Advance 99 in the utility, excep that patch 1 (-2, +3) is shaking hard in mine but soft in the utility (And I can't see the patch at (-3, +4), so I don't know how hard it was shaking). I have chain set to 1, and it is "hard after a capture", so it should match.

I walked into the hard shaking patch 2, at (-2, -2) (2 steps right, turn, 2 steps up). The utility says this should continue the chain, but I encountered a Primeape 49 M, and the chain definitely broke.

Primeape
* 49 M (Encounter Slot 4)
* CarefulG
* Mischievous
* 126 109 68 70 94 110
* Vital Spirit

## Post analysis

Graveler matches advance 33. This means the turn and step must've taken more than 2 advances, which we have confirmed is a possibility. Might need to add some sort of mode to this thing to calculate actual advances for pathing to the encounter.
(This graveler matches advance 33 in pokefinder)

Pokefinder says battle advances go to advance frame 100, which is close to the advance frame that matched the placement of the follow-up tiles (99), if not whether they shook or if they continued the chain.

The utility claims 12 advances for this calculation, bringing us to either 111 or 112 depending on whether we use the advance from pokefinder or the utility. We took 5 steps (4 and turned), which should bring us to at least 116, or 119 on average if the 1.5 advances per step average is to be believed.

Primeape matches advance 119 in pokefinder, so that maths out okay.

Interestingly, if I don't lock in pokefinder mode, primeape matches advance 118 in pokefinder (except for it being obvously wingull and not primeape in slot 4) and graveler matches advance 32. So pokefinder encounters take one less roll it seems? This is probably more to do with how pokefinder is implemented than anything, but since I'm using pokefinder to find a shiny frame, I'll need to keep this in mind.
# Attempt 3
0xEC0203ED 

Pokeradar at advance 0, Matches utility. says 11 rolls consumed, 9 more to hit encounter slot 4, though 10 or 11 also works.
Turned to the right, steped, turned to face down, then up, which should have been 5 advances. Did 2 journal pages to get to 9 advances, then stepped up. This should be 20 advances total, plus however many it took to step into the grass

Got encounter slot 4! Primeape 49 M

Spore worked, so it is anger point, which matches primeape at 21, 22, and 25. The post battle advances are 44, 65, and 106.

The shakes match 64, leading me to believe they'll consistently match battle advances - 1 and we hit frame 22.

I'm going to try and catch a primeape with a payapa berry, the next one is at advance 109. Utility says "12 rolls plus roamer" after 64, so I'm saying we're on advance 77, meaning 22 advances? I'm going to turn left, then down, and then I'll be facing a patch and 2 advances ahead (79). 20 advances, I think walking into the patch will take 2, so I'll do 18 advances with my journal.

Ack, I screwed up and did the steps AFTER the 18 advances, and I didn't turn to the left first, I only turned down and took a step. The primeape is female (109 was male), so I definitely didn't do it right.

I also forgot that I could get information from the chain by recording the patch locations, oops. I saw them though, so I have a vague idea of where they were.

First Primeape does indeed match the one at advance 22. The second one matches advances 67, 93, 97, and 133. It occurs to me now that I did my math wrong earlier - 77 then 22 advances is 99, not 109. so my 18 advances, then turn and step probably brought me to 97.

All of them advance to frame 200 in pokefinder, and indeed if I set advances to 199 it looks like my vague memory of where the patches were after I caught primeape.

## Primeape 1
* 49 M
* Mild Nature
* Anger Point
* IV's 6 21 12 21 9 24

## Primeape 2
* 49 F
* Naive Nature
* Vital Spirit
* IV's 20 26 22 9 1 18
G
# Attempt 4 (not yet complete)
0xED0203EF (Actual seed!)
TARGET PID: E9375A48
Hard shakes at advance 14, so I'll do 7 journal pages, then pokeradar. Consumes 10 advances, so advance 24.
Slot 5 after 9 or 22 advances
Slot 4 after 13, 15, 16, or 17 advances

## Plans
### Plan A (No)
Slot 5 after 9 advances, or 5 steps exactly. Turn left, step, turn right, turn left, turn down, then step.

This should be 14+10+9+2 => 35 advances. Oh dear, that's 276 battle advances, which is too many (our target is 138).

### Plan B
Slot 4 after 13 advances. If I turn right, step, turn down that brings us to 5, then 8 advances via journal (4 pages) brings us to 13. 
14+10+13+2 => 39. That brings us to 112, a little scary, but let's see.

At 111, all the patches are still on grass, and 13 rolls are consumed, bringing us to 124. Turn, step, turn takes 4 advances, so 128.

I am still not sure what the math is for the final step that continues the chain, but I think it is 1. I'm asking Artoo...

...

Artoo says it depends on the regular grass step RNG, so it is state dependent. But it is building a feature to hit PID's in the tool.

I also forgot that static affects encounter tables, so I'll swap raichu out for technician smeargle.

...

Okay, now the tool says 13c at 111 for my target PID. So If I turn to the right, step, turn up, that's 3 advances. Then I do 5 journal flips (10 advances), and that'll be 13. Those 13 advances and the 13 from the pokeradar itself bring me to 137, and the roll from stepping into the patch is 138, so that matches pokefinder pretty good.


## Actual results

7 Journal flips, results match expectations. Now I want to hit 13 advances more, so 3 steps should bring me to 3, then 5 journal pages, then step.

49 M Primeape, looks promising.

Confirmed vital spirit. Promising doubly so.

Caught the primeape. Recording patches.

Patches match expectations for advance 111!

Turn, step, turn.

5 Journal pages.

Shiny! It worked!





