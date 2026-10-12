# Feedback 3

## NEW Feedback
* IMPORTANT: Solver had a solution, I followed the recommendation and clicked "Yes this happened", and now it says there is no solution.
    * Seed A: 0xfa01036e
    * Latias Nature: Timid
    * Latias IVs: 18 151 16 26 1 4
    * Seed B: 0xff011c03
    * Path: M2hE4hHP110 M3Eslp M2hE2 M3Eslp M2hEslp M2hE1 P0E4hHP071 M3Eslp IhpE2HP153 M3Eslp P0Eslp P0Eslp C0Eslp M1E3hHP108
    * The solver was run right before the last token of the above path.

## Feedback to apply/TODO
* Assume pokemon has not fainted, and default the question to "no" when asking.
* Need to be able to mark hunts as "complete"
* When using an item, we can infer what the HP will probably be if the user has not taken damage that turn (If I use a potion and my hp was 73, and there's no reason for my character to take damage, we should default the hp prompt to 93 (or max hp if less than 93)
* "Reset Run" on safari compass (Or any compass) should not clear roamer starting positions or reset the delay/second window to default.
* Make sure the math for applying the damage boost from weather is applied in the right order
* Some of the text in the battle compass says Suicune specifically, even when hunting Latias. Mentions of Aurora Beam also.
* Deferred: Figure out how we'll handle roamers.

# Feedback 2
* IMPORTANT: When using spore, "Latias remains asleep" is not presented as an option for latias. In fact, unless Latias was already asleep, Latias is faster than me, or stat chanegs allows it to miss, this is the ONLY possibility.
* IMPORTANT: Make sure it is understood that flinching is invisible on moves that move second - It should not ask me if the secondary effect of zen headbutt proc'd my pokemon when latias moved second, and the token should not be in the path.
* IMPORTANT: We need to start accounting for pokemon fainting. I have a subheading below that describes my thoughts. Read it, ask questions/point out any concerns, and then implement it.

### FAINTING

Yep, so rain dance will increase damage of hydro pump. That's a lot of damage, which also means it is quite possible for Lugia to faint pokemon that are on full HP, which we didn't actually add tokens for in our grammar library. Even if we weren't too worried about Lvl 45 Lugia, Level 70 Ho-oh can currently faint our scarfed magneton as he goes for paralysis.

I think when our active pokemon faints, we can have a token like X (or F, but given its re-use I like X). Also once a pokemon faints, the user will need to switch in one of their remaining pokemon, so we should add the party index of the new pokemon in after the token. If they have none, then the path ends and cannot be solved. If we chose a move but the opponent moved first and faints us, then our move will not actually have been applied and there should be no token for it. On the other hand, if we chose a move and move first, the fainting and switching will happen after the opponent's turn.

So depending on who moved first, the following are both possible:
```
M0E3!X3
E3!X3
```

If the user has moves that inflict recoil, it is also possible for them to faint from their own move (`M0hX3`), but I don't think any moves that inflict recoil are reasonable for a capture attempt, so let's not worry about that for now.

Since we faint before doing anything, the effect of the move on RNG should not matter, it does not deduct PP, so it is okay that "E3!X3" does not say which move we selected. If the user is slower than the opponent, the opponent has increased priority moves, or the user has decreased priority moves, "Fainted before moving" should be a selectable option for "What did <Pokemon> do?" in the battle compass.

Obviously if the pokemon fainted, a token of "HP000" is redundant and should not be used

Then we have to add logic for revives as well as another possible user action, so long as one of the party pokemon is fainted. Unlike other items, which we assume we will be using on our active pokemon, revives are used on non-active pokemon, so we'll use the party index as a second part as well, just like we do for when we switch pokemon.

While max revives are a thing, we'll only be using base revives, which restore a pokemon to half of their total HP.

These should pretty much only be used during the pathing part - If the user messes up during solving and their pokemon faints, the solver will resolve from the perspective of the pokemon switched in, and we'll not bother trying to revive pokemon on the solver path.

Proposed new tokens for the reporting language:
```
X1 - Pokemon fainted, so we switched in party pokemon 1 to replace it
X2 - Pokemon fainted, so we switched in party pokemon 2 to replace it
X3 - Pokemon fainted, so we switched in party pokemon 3 to replace it
X4 - Pokemon fainted, so we switched in party pokemon 4 to replace it
X5 - Pokemon fainted, so we switched in party pokemon 5 to replace it
X6 - Pokemon fainted, so we switched in party pokemon 6 to replace it
XX - Pokemon fainted, no available pokemon, run ends as definitively as C or Pc

R1 - Revived the pokemon in the first party slot
R2 - Revived the pokemon in the second party slot
R3 - Revived the pokemon in the third party slot
R4 - Revived the pokemon in the fourth party slot
R5 - Revived the pokemon in the fifth party slot
R6 - Revived the pokemon in the sixth party slot

```

# Feedback 1

* When choosing how many shakes, we should output a message below matching the number of shakes (Such as 1 being "Aww! It appeared to be caught!"), since remembering the message is easier than remembering the pokeball shake count.
* Once the solver has run, when we have a recommended action, we should have a box saying "Did this happen?" with all the parts of the token in layman's terms, and then a button that says "Yes" that allows us to skip inputting all the fields in the interview and just put that token directly into the path. The interview should still be present in case something diverged from this, but this will make things easier.
* The buttons become invisible on hover.
* The "Undo last turn" button isn't appearing until a full other turn is filled out: It should be there from the beginning, perhaps at the table documenting previous turns.
* There should be a Turn counter near the top.
* When editting/adding party pokemon, the fields for each stat are too narrow: You can't really see a third digit
* For the turns passed table, add a tooltip on the move tokens that explains the turn in layman's terms.
* The Suicune spread that we display on the search is before the user has caught the suicune and can verify the stat spread - We should add a button near the "Target Suicune" bar that opens a pop-up to display the stats, since this is closer to when they'll actually be able to verify that they are correct.
* Why can't I select any of the text in the app? I would like to either be able to select the text, or we should add copy-on-click to things like the identified Seed A, identified Seed B, and the "Path so far" section.
