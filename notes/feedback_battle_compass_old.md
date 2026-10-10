# Feedback 2
* IMPORTANT: When using spore, "Latias remains asleep" is not presented as an option for latias. In fact, unless Latias was already asleep, Latias is faster than me, or stat chanegs allows it to miss, this is the ONLY possibility.
* IMPORTANT: Make sure it is understood that flinching is invisible on moves that move second - It should not ask me if the secondary effect of zen headbutt proc'd my pokemon when latias moved second, and the token should not be in the path.
* IMPORTANT: We need to start accounting for pokemon fainting. I have a subheading below that describes my thoughts. Read it, ask questions/point out any concerns, and then implement it.

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
