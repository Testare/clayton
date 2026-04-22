"""
machete.py — Safari capture path solver.

Given a starting seed and a SafariPokemon, performs a breadth-first
search over possible action sequences (bait, mud, ball) to find a path
that leads to a successful capture. Can optionally take a list of
actions already taken to continue searching from mid-encounter state.
Useful for determining whether a known seed is solvable and what
sequence of actions achieves it.
"""
