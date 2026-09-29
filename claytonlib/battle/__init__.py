"""claytonlib.battle — mechanics shared between the Metronome and Battle compasses.

Matchup-agnostic Gen 4 battle mechanics, kept separate from either front-end.  Battle Compass
is its own tool built alongside `metronome_compass` rather than by refactoring it (see
notes/battle_compass.md sec 15.2), so this package is where the genuinely common pieces live.

NB: `claytonlib/__init__.py` hoists every public name from every top-level module into the
package namespace, last-writer-wins, and `battle` sorts early — so a name defined here that
collides with a later module would be silently shadowed at `claytonlib.<name>`.
`tests/test_claytonlib_exports.py` fails on any such collision.
"""
from claytonlib.battle.stats import (  # noqa: F401
    NATURES, StatKey, nature_multiplier, calc_stat, calc_hp, derive_stats,
    species, derive_species_stats, has_fast_ball_bonus,
)
from claytonlib.battle.types import (  # noqa: F401
    TYPE_CHART, type_multiplier, effectiveness,
)
