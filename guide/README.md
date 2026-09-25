# Clayton — User Guide

Clayton is a toolkit for RNG manipulation in the **Pokémon HeartGold / SoulSilver Safari Zone**. While you can use other guides and tools to manipulate the RNG state to determine *which pokemon you encounter*, this tool helps you with manipulating the other relevant RNG state - The state of the encounter that determines whether you actually catch the pokemon before it flees.

## Read in this order

|   | Page                                         | What it covers                                 |
| - | -------------------------------------------- | ---------------------------------------------- |
| 1 | [Introduction](01-introduction.md)           | What Clayton does, and the problem it solves   |
| 2 | [Getting started](02-getting-started.md)     | Install, make a profile, make an expedition    |
| 3 | [Timers and hitting seeds](03-timers.md)     | EonTimer, the three-timer process, Vector ms   |
| 4 | [Metronome Compass](04-metronome-compass.md) | Calibrating to *your* hardware — do this first |
| 5 | [Safari Chart](05-safari-chart.md)           | Finding a target datetime worth attempting     |
| 6 | [Safari Compass](06-safari-compass.md)       | Running the hunt and identifying what you hit  |
| - | [Safari blocks](07-safari-blocks.md)         | Getting the right Pokémon to appear at all     |
| — | [Glossary](08-glossary.md)                   | Every term, in one place                       |

## What this guide assumes

That you already RNG manipulate — you know what a seed is, you can hit an initial seed on
your DS, and you can use tools like PokeFinder or RNG Reporter to find the seed that produces the
Pokémon you want. Clayton picks up from there.

If none of that is familiar, start with a general HGSS RNG guide first; Clayton will make far
more sense afterwards.

## A note on hardware

Every piece of timing advice here depends on your **console, your flashcart or cartridge, and
your reflexes**. That is exactly why Clayton makes you calibrate ([page 4](04-metronome-compass.md))
before it will give you good targets. Numbers quoted in this guide are illustrative — yours
will differ, and that is normal.

---
