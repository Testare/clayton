Reverse RNG:
 ((k-24691)*4005161829) & 0xFFFFFFFF


 Apply this 12 times to a given number to get that on the metronome roll.

 For example, for "false swipe"

Start with  205 * 0x10000 (0xcd0000, though we could replace those 0's with anything)

Then apply prev 12 times, you get 0xb8ee1bd4.

seed_override to that number and metronome is false swipe.

Can use this to verify paths in compass a little bit.
