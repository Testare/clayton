"""Tests for the safari load-path offset: model flag + fit + Section-E apply (ctd.4)."""
import json
import os
import sys
import tempfile
import unittest

from claytonlib.calibration import CalibrationModel

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import calibration_tools as ct  # noqa: E402


def _df_model(beta=0.0006, alpha=0.0, safari_offset=None):
    return CalibrationModel(kind="line", target="dF", beta=beta, alpha=alpha,
                            safari_offset=safari_offset)


class TestModelSafariFields(unittest.TestCase):
    def test_frame_is_metronome_path_by_default(self):
        m = _df_model(safari_offset=7.0)
        # frame() is always the metronome path; the safari path is via with_safari_offset().
        self.assertAlmostEqual(m.frame(100000, 500),
                               m.mean(100000) + 500)

    def test_serialization_roundtrips_safari_fields(self):
        m = _df_model(safari_offset=7.0)
        m.safari_offset_n, m.safari_offset_std = 4, 1.5
        m2 = CalibrationModel.from_dict(m.to_dict())
        self.assertEqual(m2.safari_offset, 7.0)
        self.assertEqual(m2.safari_offset_n, 4)
        self.assertEqual(m2.safari_offset_std, 1.5)

    def test_old_artifact_without_field_loads(self):
        d = _df_model().to_dict()
        d.pop("safari_offset", None)
        d.pop("safari_offset_n", None)
        d.pop("safari_offset_std", None)
        m = CalibrationModel.from_dict(d)
        self.assertIsNone(m.safari_offset)


def _safari_run(M, Fa, Fb, *, seed=0x0C0E02C2, prior_battles=0, a_seed=True):
    rec = {
        "target_timer_delay": M, "target_timer_calibration": 0,
        "seed": seed, "frame": Fb, "prior_battles": prior_battles,
    }
    if a_seed:
        rec["a_seed"] = {"seed": 1, "delay": Fa}
    return rec


def _write_runs(records):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return path


class TestFitSafariOffset(unittest.TestCase):
    def setUp(self):
        self.model = _df_model(beta=0.0006, alpha=0.0)  # frame = 0.0006*M + Fa

    def test_offset_is_median_residual(self):
        # frame(M,Fa) = 0.0006*M + Fa; craft Fb so residuals are 6, 7, 8 -> median 7.
        runs = [
            _safari_run(100000, 500, int(0.0006 * 100000 + 500) + 6),
            _safari_run(120000, 500, int(0.0006 * 120000 + 500) + 7),
            _safari_run(140000, 500, int(0.0006 * 140000 + 500) + 8),
        ]
        path = _write_runs(runs)
        try:
            fit = ct.fit_safari_offset(self.model, runs_path=path)
        finally:
            os.remove(path)
        self.assertEqual(fit["n"], 3)
        self.assertAlmostEqual(fit["offset"], 7.0, places=6)

    def test_skips_unusable_runs(self):
        runs = [
            _safari_run(100000, 500, 560, seed=None),        # ambiguous -> skip
            _safari_run(100000, 500, 560, prior_battles=2),  # contaminated -> skip
            _safari_run(100000, 500, 560, a_seed=False),     # no F_a -> skip
        ]
        path = _write_runs(runs)
        try:
            self.assertIsNone(ct.fit_safari_offset(self.model, runs_path=path))
        finally:
            os.remove(path)

    def test_contaminated_kept_when_fresh_only_false(self):
        runs = [_safari_run(100000, 500, int(0.0006 * 100000 + 500) + 3, prior_battles=1)]
        path = _write_runs(runs)
        try:
            fit = ct.fit_safari_offset(self.model, runs_path=path, fresh_only=False)
        finally:
            os.remove(path)
        self.assertEqual(fit["n"], 1)
        self.assertAlmostEqual(fit["offset"], 3.0, places=6)


class TestUpdateSafariOffset(unittest.TestCase):
    def test_writes_offset_into_modelset_on_confirm(self):
        runs = [
            _safari_run(100000, 500, int(0.0006 * 100000 + 500) + 5),
            _safari_run(120000, 500, int(0.0006 * 120000 + 500) + 5),
        ]
        runs_path = _write_runs(runs)
        fd, model_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            CalibrationModel.save_set({"linear": _df_model()}, model_path)
            updated = ct.update_safari_offset(model_path=model_path, runs_path=runs_path,
                                              assume_yes=True)
            self.assertIsNotNone(updated)
            reloaded = CalibrationModel.load_set(model_path)["linear"]
            self.assertAlmostEqual(reloaded.safari_offset, 5.0, places=6)
            self.assertEqual(reloaded.safari_offset_n, 2)
        finally:
            os.remove(runs_path)
            os.remove(model_path)

    def test_no_runs_returns_none_and_leaves_model(self):
        runs_path = _write_runs([_safari_run(100000, 500, 560, seed=None)])
        fd, model_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            CalibrationModel.save_set({"linear": _df_model()}, model_path)
            self.assertIsNone(ct.update_safari_offset(
                model_path=model_path, runs_path=runs_path, assume_yes=True))
            self.assertIsNone(CalibrationModel.load_set(model_path)["linear"].safari_offset)
        finally:
            os.remove(runs_path)
            os.remove(model_path)


class TestWithSafariOffset(unittest.TestCase):
    def test_line_bakes_offset_into_alpha_and_clears_field(self):
        m = CalibrationModel(kind="line", target="dF", beta=0.0006, alpha=10.0,
                             safari_offset=30.0)
        baked = m.with_safari_offset()
        self.assertEqual(baked.alpha, 40.0)
        self.assertIsNone(baked.safari_offset)
        self.assertEqual(m.alpha, 10.0)              # original untouched

    def test_baked_mean_is_metronome_frame_plus_offset(self):
        m = CalibrationModel(kind="line", target="dF", beta=0.0006, alpha=10.0,
                             safari_offset=30.0)
        baked = m.with_safari_offset()
        for M in (0, 50000, 300000):
            self.assertAlmostEqual(baked.frame(M, base_low16=500),
                                   m.frame(M, base_low16=500) + 30.0)

    def test_quad_bakes_offset_into_constant_coeff(self):
        m = CalibrationModel(kind="quad", coeffs=(1.0, 2.0, 3.0), m_center=0.0,
                             m_scale=1.0, safari_offset=5.0)
        baked = m.with_safari_offset()
        self.assertEqual(baked.coeffs, (6.0, 2.0, 3.0))
        self.assertIsNone(baked.safari_offset)

    def test_returns_self_when_no_offset(self):
        m = CalibrationModel(kind="line", beta=0.0006, alpha=10.0)
        self.assertIs(m.with_safari_offset(), m)


class TestReportUsesSafariOffset(unittest.TestCase):
    """The report folds the offset in at the surface -- no scorer-internal threading (ctd.11)."""

    def _spy_model(self, use_safari_offset):
        import datetime as dt
        from unittest.mock import patch
        import claytonlib.chart.scorer as scorer
        m = CalibrationModel(kind="line", target="Fb", beta=0.06, alpha=10.0,
                             jitter_rms=5.0, safari_offset=30.0)
        seen = {}

        def fake_rank(canon_map, model, *a, **kw):
            seen["alpha"] = model.alpha
            seen["safari_offset"] = model.safari_offset
            return []

        with patch.object(scorer, "rank_targets", fake_rank):
            scorer.print_target_report(None, m, dt.datetime(2000, 1, 1), 1000, 5, 15,
                                       use_safari_offset=use_safari_offset)
        return seen

    def test_offset_folded_when_enabled(self):
        seen = self._spy_model(use_safari_offset=True)
        self.assertEqual(seen["alpha"], 40.0)        # 10 + 30 baked in
        self.assertIsNone(seen["safari_offset"])

    def test_offset_untouched_when_disabled(self):
        seen = self._spy_model(use_safari_offset=False)
        self.assertEqual(seen["alpha"], 10.0)
        self.assertEqual(seen["safari_offset"], 30.0)


class TestExpeditionFoldsSafariOffset(unittest.TestCase):
    """The expedition surface must fold the offset for ALL safari scoring paths, so precompute,
    chart_report, and compass_safari share one frame model (clayton-xqf)."""

    def _patch_model(self, model):
        import claytonlib.calibration as cal
        orig = cal.CalibrationModel.load_default
        cal.CalibrationModel.load_default = classmethod(lambda cls, *a, **k: model)
        self.addCleanup(setattr, cal.CalibrationModel, "load_default", orig)

    def test_calibration_model_folds_offset_by_default(self):
        from claytonlib.expedition import Expedition
        self._patch_model(_df_model(alpha=-300.0, safari_offset=-437.0))
        exp = Expedition("t")
        m = exp.calibration_model()                      # default: use_safari_offset True
        self.assertAlmostEqual(m.alpha, -737.0)          # offset baked into the intercept
        self.assertIsNone(m.safari_offset)               # cleared, so a second fold is a no-op
        self.assertAlmostEqual(exp.calibration_model(safari=False).alpha, -300.0)

    def test_use_safari_offset_toggle(self):
        from claytonlib.expedition import Expedition
        self._patch_model(_df_model(alpha=-300.0, safari_offset=-437.0))
        exp = Expedition("t")
        exp.use_safari_offset = False
        self.assertAlmostEqual(exp.calibration_model().alpha, -300.0)

    def test_no_offset_is_noop(self):
        from claytonlib.expedition import Expedition
        self._patch_model(_df_model(alpha=-300.0, safari_offset=None))
        exp = Expedition("t")
        self.assertAlmostEqual(exp.calibration_model().alpha, -300.0)

    def test_config_roundtrips_flag_and_defaults_true(self):
        from claytonlib.expedition import Expedition
        exp = Expedition("t")
        exp.use_safari_offset = False
        self.assertFalse(Expedition._from_dict(exp._to_dict()).use_safari_offset)
        # an older config with no such key opts in (default True)
        d = exp._to_dict()
        d.pop("use_safari_offset")
        self.assertTrue(Expedition._from_dict(d).use_safari_offset)


if __name__ == "__main__":
    unittest.main()
