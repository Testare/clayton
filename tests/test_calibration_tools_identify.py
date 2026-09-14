"""identify_seed / narrow_by_elm: surface the Elm calls entered while narrowing.

Section A.2 of the Safari Compass Calibration notebook re-uses the P/E/K calls the
user typed in A.1 (clayton-pwy), so identify_seed must record them on the returned
row as `elm_observed` -- and clear them when the roamer routes alone were unique.
"""
import contextlib
import datetime as dt
import io
import os
import sys
import unittest
from unittest import mock

# utils/ is not a package; add it to the path so calibration_tools imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))

import calibration_tools as ct  # noqa: E402


def _row(seed, elm, r, e, l, delay=685):
    """A minimal candidate row carrying every key the identify path touches."""
    return {
        "seed": seed,
        "time": dt.datetime(2025, 7, 24, 14, 45, 55),
        "delay": delay,
        "delay_delta": 0,
        "sec_delta": 0,
        "r_route": r, "e_route": e, "l_route": l,
        "rng_calls": 3,
        "elm": elm,
    }


def _quiet(fn, *args, **kwargs):
    """Run fn swallowing its (interactive) stdout so the test log stays clean."""
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*args, **kwargs)


def _feed(*responses):
    """Patch builtins.input with a plain function returning `responses` in order.

    A plain function (not a Mock) is used deliberately: identify_seed's
    install_input_fixup reads getattr(builtins.input, "_original", ...) and a Mock
    auto-creates that attribute, which would swallow the response.
    """
    answers = iter(responses)
    return mock.patch("builtins.input", lambda prompt="": next(answers))


class TestElmObservedSurfaced(unittest.TestCase):
    def test_single_route_match_clears_elm_observed(self):
        # Distinct routes -> the observed readout pins one seed with no Elm calls.
        cands = [_row(0x0D0E02C6, "KPKPEKKEEKPKKEK", 32, 33, 17),
                 _row(0x0C0E02CA, "PPPEEKEKPEEEEPP", 44, 46, 20)]
        result = _quiet(ct.identify_seed, cands, observed_rel="32 33 17")
        self.assertIsNotNone(result)
        self.assertEqual(result["seed"], 0x0D0E02C6)
        self.assertEqual(result["elm_observed"], "")

    def test_elm_calls_are_surfaced(self):
        # Same routes -> narrowing falls through to Elm calls; "PK" picks A only.
        cands = [_row(0x0D0E02C6, "KPKPEKKEEK", 32, 33, 17),
                 _row(0x0B0E02C6, "EEEEEEEEEE", 32, 33, 17)]
        with _feed("pk"):
            result = _quiet(ct.identify_seed, cands, observed_rel="32 33 17")
        self.assertIsNotNone(result)
        self.assertEqual(result["seed"], 0x0D0E02C6)
        self.assertEqual(result["elm_observed"], "PK")  # upper-cased, as parsed

    def test_narrow_by_elm_returns_calls(self):
        cands = [_row(0x0D0E02C6, "KPKPEKKEEK", 32, 33, 17),
                 _row(0x0B0E02C6, "EEEEEEEEEE", 32, 33, 17)]
        with _feed("pk"):
            result, calls = _quiet(ct.narrow_by_elm, cands)
        self.assertEqual(result["seed"], 0x0D0E02C6)
        self.assertEqual(calls, "PK")


if __name__ == "__main__":
    unittest.main()
