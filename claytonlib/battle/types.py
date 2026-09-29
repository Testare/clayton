"""Gen 4 type-effectiveness chart.

Generated from ``notes/ss_rng/effectiveness_chart.md``, which records the table the ROM itself
uses — so this is ground truth rather than a transcription from memory.  Only non-neutral
matchups are listed; anything absent is 1.0x.  ``tests/test_battle_types.py`` re-parses that
notes file and asserts this literal still matches it.

Gen 4 specifics worth noting: there is no Fairy type, and **Steel resists both Ghost and Dark**
(that changed in Gen 6).  The two Ghost immunities sit after a FORESIGHT sentinel in the ROM
table because Foresight removes them; Foresight is out of scope, so they are included here
unconditionally.
"""
from __future__ import annotations

# (attacking type, defending type) -> multiplier.  Absent pairs are 1.0.
TYPE_CHART: dict[tuple[str, str], float] = {
    ('Normal', 'Rock'): 0.5,
    ('Normal', 'Steel'): 0.5,
    ('Fire', 'Fire'): 0.5,
    ('Fire', 'Water'): 0.5,
    ('Fire', 'Grass'): 2.0,
    ('Fire', 'Ice'): 2.0,
    ('Fire', 'Bug'): 2.0,
    ('Fire', 'Rock'): 0.5,
    ('Fire', 'Dragon'): 0.5,
    ('Fire', 'Steel'): 2.0,
    ('Water', 'Fire'): 2.0,
    ('Water', 'Water'): 0.5,
    ('Water', 'Grass'): 0.5,
    ('Water', 'Ground'): 2.0,
    ('Water', 'Rock'): 2.0,
    ('Water', 'Dragon'): 0.5,
    ('Electric', 'Water'): 2.0,
    ('Electric', 'Electric'): 0.5,
    ('Electric', 'Grass'): 0.5,
    ('Electric', 'Ground'): 0.0,
    ('Electric', 'Flying'): 2.0,
    ('Electric', 'Dragon'): 0.5,
    ('Grass', 'Fire'): 0.5,
    ('Grass', 'Water'): 2.0,
    ('Grass', 'Grass'): 0.5,
    ('Grass', 'Poison'): 0.5,
    ('Grass', 'Ground'): 2.0,
    ('Grass', 'Flying'): 0.5,
    ('Grass', 'Bug'): 0.5,
    ('Grass', 'Rock'): 2.0,
    ('Grass', 'Dragon'): 0.5,
    ('Grass', 'Steel'): 0.5,
    ('Ice', 'Water'): 0.5,
    ('Ice', 'Grass'): 2.0,
    ('Ice', 'Ice'): 0.5,
    ('Ice', 'Ground'): 2.0,
    ('Ice', 'Flying'): 2.0,
    ('Ice', 'Dragon'): 2.0,
    ('Ice', 'Steel'): 0.5,
    ('Ice', 'Fire'): 0.5,
    ('Fighting', 'Normal'): 2.0,
    ('Fighting', 'Ice'): 2.0,
    ('Fighting', 'Poison'): 0.5,
    ('Fighting', 'Flying'): 0.5,
    ('Fighting', 'Psychic'): 0.5,
    ('Fighting', 'Bug'): 0.5,
    ('Fighting', 'Rock'): 2.0,
    ('Fighting', 'Dark'): 2.0,
    ('Fighting', 'Steel'): 2.0,
    ('Poison', 'Grass'): 2.0,
    ('Poison', 'Poison'): 0.5,
    ('Poison', 'Ground'): 0.5,
    ('Poison', 'Rock'): 0.5,
    ('Poison', 'Ghost'): 0.5,
    ('Poison', 'Steel'): 0.0,
    ('Ground', 'Fire'): 2.0,
    ('Ground', 'Electric'): 2.0,
    ('Ground', 'Grass'): 0.5,
    ('Ground', 'Poison'): 2.0,
    ('Ground', 'Flying'): 0.0,
    ('Ground', 'Bug'): 0.5,
    ('Ground', 'Rock'): 2.0,
    ('Ground', 'Steel'): 2.0,
    ('Flying', 'Electric'): 0.5,
    ('Flying', 'Grass'): 2.0,
    ('Flying', 'Fighting'): 2.0,
    ('Flying', 'Bug'): 2.0,
    ('Flying', 'Rock'): 0.5,
    ('Flying', 'Steel'): 0.5,
    ('Psychic', 'Fighting'): 2.0,
    ('Psychic', 'Poison'): 2.0,
    ('Psychic', 'Psychic'): 0.5,
    ('Psychic', 'Dark'): 0.0,
    ('Psychic', 'Steel'): 0.5,
    ('Bug', 'Fire'): 0.5,
    ('Bug', 'Grass'): 2.0,
    ('Bug', 'Fighting'): 0.5,
    ('Bug', 'Poison'): 0.5,
    ('Bug', 'Flying'): 0.5,
    ('Bug', 'Psychic'): 2.0,
    ('Bug', 'Ghost'): 0.5,
    ('Bug', 'Dark'): 2.0,
    ('Bug', 'Steel'): 0.5,
    ('Rock', 'Fire'): 2.0,
    ('Rock', 'Ice'): 2.0,
    ('Rock', 'Fighting'): 0.5,
    ('Rock', 'Ground'): 0.5,
    ('Rock', 'Flying'): 2.0,
    ('Rock', 'Bug'): 2.0,
    ('Rock', 'Steel'): 0.5,
    ('Ghost', 'Normal'): 0.0,
    ('Ghost', 'Psychic'): 2.0,
    ('Ghost', 'Dark'): 0.5,
    ('Ghost', 'Steel'): 0.5,
    ('Ghost', 'Ghost'): 2.0,
    ('Dragon', 'Dragon'): 2.0,
    ('Dragon', 'Steel'): 0.5,
    ('Dark', 'Fighting'): 0.5,
    ('Dark', 'Psychic'): 2.0,
    ('Dark', 'Ghost'): 2.0,
    ('Dark', 'Dark'): 0.5,
    ('Dark', 'Steel'): 0.5,
    ('Steel', 'Fire'): 0.5,
    ('Steel', 'Water'): 0.5,
    ('Steel', 'Electric'): 0.5,
    ('Steel', 'Ice'): 2.0,
    ('Steel', 'Rock'): 2.0,
    ('Steel', 'Steel'): 0.5,
    ('Normal', 'Ghost'): 0.0,
    ('Fighting', 'Ghost'): 0.0,
}


def type_multiplier(attacking: str, defending: str) -> float:
    """Multiplier for one attacking type against one defending type."""
    return TYPE_CHART.get((attacking.capitalize(), defending.capitalize()), 1.0)


def effectiveness(attacking: str, defending: tuple[str, ...] | list[str] | str) -> float:
    """Multiplier against a defender's full (one- or two-) type combination.

    A dual type multiplies both matchups, so an immunity in either half zeroes the result.
    """
    if isinstance(defending, str):
        defending = (defending,)
    result = 1.0
    for d in defending:
        result *= type_multiplier(attacking, d)
    return result
