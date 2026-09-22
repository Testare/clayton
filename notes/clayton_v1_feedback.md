## X Compass - New Run
* I should probably rename "Match key-seed delay parity" to "Even/Odd delay matches key seed", uses more understandable diction.

## Safari Chart - Find Target
* For the Ranking, is it possible to have a loading bar to indicate progress of the ranking? If so, it might be better than a spinner so we can show progress being made and help people estimate how long it'll take.

## Safari Chart - Manage Data
* Okay, I know I asked for the buttons to be stacked vertically, but the text inside them is also being stacked vertically and it looks bad (see screenshot). 
* Let's have each button NOT wrap internally, but each button be stacked vertically within their row.
* Similarly, for the "Computed" column, instead of just separating each point with a dot, let's make it a bulleted list
* To save horizontal width, we could add the computed size to the "Computed" column as another list item instead of having its own column. Makes a lot of sense for it to be there.
* Name, Criteria, and strategy columns can wrap, that's fine.
* I'd also prefer if "Window" didn't wrap, but I'm flexible on that if we can't get it to fit otherwise
* When deleting a chart, it should delete the computed data as well so long as no other expedition has a matching chart.
