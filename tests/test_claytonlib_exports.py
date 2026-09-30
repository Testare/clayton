"""claytonlib/__init__.py hoists every public name from every top-level module into the
package namespace with globals().update(), so a name defined by two modules silently
resolves to whichever module pkgutil visits last.

That matters as claytonlib grows a shared battle core: `battle` and `battle_compass` sort
early, so any name they share with a later module (metronome_compass, moves, safari, times)
would resolve to the *existing* one — `claytonlib.BattleContext` would quietly hand back the
Metronome version instead of the shared one.  See notes/battle_compass.md sec 17.3.
"""
import importlib
import pkgutil
import unittest
from pathlib import Path

import claytonlib

# Names legitimately defined by more than one module.  Module-level loggers are per-module by
# design and nothing imports claytonlib.logger, so the shadowing is harmless.
ALLOWED_COLLISIONS = {"logger"}


def _collisions() -> dict[str, list[str]]:
    """Public names bound to *different* objects by more than one top-level module."""
    root = Path(claytonlib.__file__).parent
    seen: dict[str, tuple[str, object]] = {}
    collisions: dict[str, list[str]] = {}
    for info in pkgutil.iter_modules([str(root)]):
        module = importlib.import_module(f"claytonlib.{info.name}")
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            if name in seen and seen[name][1] is not value:
                collisions.setdefault(name, [seen[name][0]]).append(info.name)
            seen[name] = (info.name, value)
    return collisions


class TestClaytonlibExports(unittest.TestCase):
    def test_no_unexpected_export_collisions(self):
        unexpected = {k: v for k, v in _collisions().items() if k not in ALLOWED_COLLISIONS}
        self.assertEqual(
            unexpected, {},
            "claytonlib.__init__ would silently shadow these names; rename them, or add to "
            "ALLOWED_COLLISIONS with a reason:\n"
            + "\n".join(f"  {k}: defined by {v}" for k, v in sorted(unexpected.items())),
        )

    def test_detector_actually_detects(self):
        """Guard the guard: the allow-list entry must still be a real collision."""
        self.assertTrue(
            ALLOWED_COLLISIONS <= set(_collisions()),
            "ALLOWED_COLLISIONS names something that no longer collides — drop it, so the "
            "allow-list cannot mask a future collision on the same name.",
        )


if __name__ == "__main__":
    unittest.main()


class TestBattleCompassIsNotShadowed(unittest.TestCase):
    """battle_compass sorts before metronome_compass, so a shared name would resolve to the
    metronome one at claytonlib.<name>. Two were caught this way: sim.resolve_move shadowing
    moves.resolve_move (a different concept -- executing a move versus looking one up), and
    simulate_turn colliding outright."""

    def test_simulate_turn_is_not_hoisted(self):
        import claytonlib.battle_compass as bc
        self.assertFalse(hasattr(bc, "simulate_turn"),
                         "re-exporting simulate_turn would be shadowed by metronome_compass")

    def test_the_move_executor_is_not_called_resolve_move(self):
        from claytonlib.battle_compass import sim
        self.assertTrue(hasattr(sim, "execute_move"))
        self.assertFalse(hasattr(sim, "resolve_move"),
                         "resolve_move would shadow claytonlib.moves.resolve_move")

    def test_looking_up_a_move_by_name_still_reaches_the_right_function(self):
        import claytonlib
        from claytonlib.moves import Move
        self.assertIsInstance(claytonlib.resolve_move("Aurora Beam"), Move)
