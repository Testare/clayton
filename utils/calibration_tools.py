"""Compatibility shim — this module moved to ``claytonlib.calibration_tools``.

It now lives in the library so the packaged app can reach it (``utils/`` is dev-only
tooling and isn't distributed). This shim keeps the calibration notebooks and any
external scripts working, whether they do ``from utils.calibration_tools import X``,
``import utils.calibration_tools``, or ``from utils import calibration_tools as ct``.

New code should import from ``claytonlib.calibration_tools`` directly.
"""
from claytonlib import calibration_tools as _ct

# Re-export every name (public and internal) so all historical import forms resolve.
_KEEP = {"__name__", "__loader__", "__spec__", "__package__", "__file__",
         "__builtins__", "__doc__", "__cached__"}
globals().update({k: v for k, v in vars(_ct).items() if k not in _KEEP})
del _ct, _KEEP
