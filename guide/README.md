# Clayton — User Guide

Clayton is a toolkit for RNG manipulation in the **Pokémon HeartGold / SoulSilver Safari Zone**. While you can use other guides and tools to manipulate the RNG state to determine *which pokemon you encounter*, this tool helps you with manipulating the other relevant RNG state - The state of the encounter that determines whether you actually catch the pokemon before it flees.

## Read in this order

|   | Page                                          | What it covers                                 |
| - | --------------------------------------------- | ---------------------------------------------- |
| 1 | [Introduction](01-introduction.md)            | What Clayton does, and the problem it solves   |
| 2 | [Installing Clayton](02-installation.md)      | Download a build, or build it yourself         |
| 3 | [Getting started](03-getting-started.md)      | Make a profile, make an expedition             |
| 4 | [Timers and hitting seeds](04-timers.md)      | EonTimer, the three-timer process, Vector ms   |
| 5 | [Metronome Compass](05-metronome-compass.md)  | Calibrating to *your* hardware — do this first |
| 6 | [Safari Chart](06-safari-chart.md)            | Finding a target datetime worth attempting     |
| 7 | [Safari Compass](07-safari-compass.md)        | Running the hunt and identifying what you hit  |
| — | [Safari blocks](08-safari-blocks.md)          | Getting the right Pokémon to appear at all     |
| — | [Glossary](09-glossary.md)                    | Every term, in one place                       |
| — | [Troubleshooting](10-troubleshooting.md)      | When something doesn't work                    |

## What this guide assumes

That you already RNG manipulate — you know what a seed is, you can hit an initial seed on
your DS, and you can use tools like PokeFinder or RNG Reporter to find the seed that produces the
Pokémon you want. Clayton picks up from there.

If none of that is familiar, start with a general HGSS RNG guide first; Clayton will make far
more sense afterwards.

## A note on hardware

Every piece of timing advice here depends on your **console, your flashcart or cartridge, and
your reflexes**. That is exactly why Clayton makes you calibrate ([page 5](05-metronome-compass.md))
before it will give you good targets. Numbers quoted in this guide are illustrative — yours
will differ, and that is normal.

---
