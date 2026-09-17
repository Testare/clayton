"""_resources.py — load packaged app/resources files as importlib resources.

Mirrors claytonlib._resources: importlib.resources works correctly no matter how the
app is deployed (source checkout, installed wheel, or a frozen/Nix-packaged
executable), unlike a Path(__file__).parent guess.
"""
import json
from importlib.resources import files
from typing import Any

_RESOURCES = "resources"


def resource_json(name: str) -> Any:
    """Parse ``app/resources/<name>`` as JSON."""
    return json.loads((files(__package__) / _RESOURCES / name).read_text(encoding="utf-8"))


def standard_calibration_modelset() -> dict:
    """The bundled 'Standard' calibration modelset artifact — a real fitted model,
    seeded into every new profile (see Facade.create_profile) so Safari Chart isn't
    blocked on the user re-running their own Metronome Compass calibration first."""
    return resource_json("standard_calibration_model.json")
