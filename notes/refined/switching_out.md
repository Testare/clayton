## Switching out
One way of dealing with problematic game states is to switch out our metronome user, and perhaps switch them back in. This could save our ability to identify a path, but also introduces many other variables, hence why for now it is P1.

## Speed ties
One of the biggest problems with switching out is speed ties. The new pokemon might speed tie the magikarp. This can be mitigated by having your second pokemon be really fast. At 95 speed, you'll outspeed Magikarp even if it is max speed, rain is set up (and it still has swift swim), or Metronome called accupressure and raised the Magikarp's speed by two stages. You won't outspeed it if all three of those happened, but if there IS a metronome chain where you do accurpressure(speed) + rain dance + transform, I'm betting you can already guess the seed.

Another possible solution is to get a second lagging tail. This can be done by using thief in Slowpoke well. Slowpoke has a 5% chance of holding a lagging tail, which isn't a lot, but slowpoke is a guaranteed spawn so it balances out. Then not only do you not have to worry about speed ties when switching out, if you have a second metronome user switching out can be used to deal with it when Fling is called (though speed ties become a possible problem DURING the turn... We'll have to c)
UNCOFIRMED: Speed tie + Lagging Tail + Fling = ??

However, it seems for P0 we're going to require the metronome user know fling, so that should help with that issue.

## U-Turn and Baton Pass
If we implement logic to handle switching out, we can handle U-Turn and Baton Pass easier. We can simply switch our metronome user back in next turn, or if we have a metronome user in the back, we can just use that metronome user instead.

## Metronome user fainting
Currently, metronome user fainting is assumed to be the end of the chain. But we can add logic to handle that if we have multiple usable metronome users.

## Branching paths
We have a note about branching paths, but switching out means we can also branch on the user's action: Either using metronome or switching out.
