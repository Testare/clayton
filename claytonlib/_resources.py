"""_resources.py — load packaged ``basedata`` files as importlib resources.

Using ``importlib.resources`` (rather than ``Path(__file__).parent``) means the
static game data loads correctly no matter how ``claytonlib`` is deployed: a source
checkout, an installed wheel, a frozen executable, or Pyodide in the browser. Those
targets don't all keep the package on a real filesystem laid out next to ``__file__``.
"""
import json
from importlib.resources import files
from typing import Any

_BASEDATA = "basedata"


def basedata_text(name: str) -> str:
    """Return the text contents of ``claytonlib/basedata/<name>``."""
    return (files(__package__) / _BASEDATA / name).read_text(encoding="utf-8")


def basedata_json(name: str) -> Any:
    """Parse ``claytonlib/basedata/<name>`` as JSON."""
    return json.loads(basedata_text(name))
