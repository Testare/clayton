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


def _safari_run(M, Fa, Fb, *, seed=0x0C0E02C2, prior_battles=0, a_seed=True,
                advance_frame=None):
    rec = {
        "target_timer_delay": M, "target_timer_calibration": 0,
        "seed": seed, "frame": Fb, "prior_battles": prior_battles,
        "advance_frame": advance_frame,
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


class TestFitSafariPerAdvance(unittest.TestCase):
    """The per-advance safari offset (clayton-6h2.3): a slope on the Seed A advance count,
    fit jointly with the intercept and REPORTED WITH ITS UNCERTAINTY rather than withheld --
    the only hard refusal is a slope that mathematically doesn't exist."""

    def setUp(self):
        self.model = _df_model(beta=0.0006, alpha=0.0)  # frame(M=100000, Fa=500) = 560 exactly

    def _runs(self, advances, offset=10.0, slope=2.0, noise=None):
        """Runs whose residual is exactly offset + slope*advance (plus optional noise)."""
        out = []
        for i, adv in enumerate(advances):
            resid = offset + slope * adv + ((noise[i]) if noise else 0)
            out.append(_safari_run(100000, 500, int(560 + resid), advance_frame=adv))
        return out

    def _fit(self, runs, **kw):
        path = _write_runs(runs)
        try:
            return ct.fit_safari_offset(self.model, runs_path=path, **kw)
        finally:
            os.remove(path)

    def test_off_by_default_matches_the_flat_median_fit(self):
        fit = self._fit(self._runs(range(10, 130, 10)))
        self.assertEqual(fit["per_advance"], 0.0)
        self.assertIsNone(fit["quality"])
        self.assertIsNone(fit["jitter_c"])

    def test_refuses_only_when_no_slope_exists_at_all(self):
        # Every run at the SAME advance count: slope and offset are the same parameter, so
        # there is no estimate to make, rough or otherwise. This is the one hard refusal.
        fit = self._fit(self._runs([80] * 8), per_advance=True)
        self.assertFalse(fit["quality"]["estimable"])
        self.assertIn("DIFFERENT advance counts", fit["quality"]["reason"])
        self.assertEqual(fit["per_advance"], 0.0)
        # ...and the flat offset is still fit over everything, so the fit stays usable.
        self.assertEqual(fit["n"], 8)

    def test_refuses_when_no_run_recorded_an_advance_count(self):
        runs = [_safari_run(100000, 500, 600), _safari_run(100000, 500, 610)]
        fit = self._fit(runs, per_advance=True)
        self.assertFalse(fit["quality"]["estimable"])
        self.assertIn("no run has recorded an advance count", fit["quality"]["reason"])

    def test_a_rough_slope_from_few_runs_is_reported_not_withheld(self):
        # The user's call (round 14): a wide interval early is useful feedback, so a small-n
        # slope is fit and surfaced with its uncertainty rather than blocked. The old version
        # of this test asserted the opposite -- that 5 runs were refused outright.
        fit = self._fit(self._runs([10, 40, 70, 100, 130]), per_advance=True)
        self.assertTrue(fit["quality"]["estimable"])
        self.assertAlmostEqual(fit["per_advance"], 2.0, places=6)
        self.assertIsNotNone(fit["quality"]["ci_halfwidth"])

    def test_two_distinct_advances_fit_a_slope_but_admit_no_uncertainty(self):
        fit = self._fit(self._runs([10, 90]), per_advance=True)
        self.assertTrue(fit["quality"]["estimable"])
        self.assertAlmostEqual(fit["per_advance"], 2.0, places=6)
        self.assertIsNone(fit["quality"]["ci_halfwidth"])   # can't bootstrap 2 points
        self.assertIn("too few", fit["quality"]["reason"])

    def test_uncertainty_shrinks_as_runs_accumulate(self):
        # The property that makes reporting-instead-of-blocking worth it: the interval visibly
        # narrows with more (and more varied) runs, so progress is legible.
        noise = lambda k: [7, -7] * k
        small = self._fit(self._runs(range(10, 70, 10), noise=noise(3)), per_advance=True)
        large = self._fit(self._runs(range(10, 250, 10), noise=noise(12)), per_advance=True)
        self.assertLess(large["quality"]["ci_halfwidth"], small["quality"]["ci_halfwidth"])

    def test_quality_reports_the_landing_spread_to_compare_against(self):
        # sigma_ref lets a caller say how the correction's uncertainty compares to the noise
        # it is correcting -- but is deliberately NOT scaled by any advance count here.
        model = _df_model(beta=0.0006, alpha=0.0)
        model.jitter_c = 0.15
        self.model = model
        fit = self._fit(self._runs(range(10, 130, 10)), per_advance=True)
        self.assertAlmostEqual(fit["quality"]["sigma_ref"],
                               0.15 * (100000 ** 0.5), places=6)

    def test_recovers_the_slope_and_offset(self):
        fit = self._fit(self._runs(range(10, 130, 10), offset=10.0, slope=2.0),
                        per_advance=True)
        self.assertTrue(fit["quality"]["estimable"])
        self.assertEqual(fit["quality"]["n_with_advances"], 12)
        self.assertAlmostEqual(fit["per_advance"], 2.0, places=6)
        self.assertAlmostEqual(fit["offset"], 10.0, places=6)
        self.assertEqual(fit["per_advance_n"], 12)

    def test_one_wild_run_cannot_drag_the_slope(self):
        # The whole reason this is Theil-Sen and not least squares: a single misidentified run
        # (here a 5000-frame residual at a leverage point) must not move the estimate. OLS on
        # this same data lands nowhere near 2.0.
        runs = self._runs(range(10, 130, 10), offset=10.0, slope=2.0)
        runs.append(_safari_run(100000, 500, 560 + 5000, advance_frame=125))
        fit = self._fit(runs, per_advance=True)
        self.assertAlmostEqual(fit["per_advance"], 2.0, places=6)

    def test_reports_a_bootstrap_ci_bracketing_the_slope(self):
        fit = self._fit(self._runs(range(10, 130, 10), slope=2.0), per_advance=True)
        lo, hi = fit["per_advance_ci"]
        self.assertLessEqual(lo, 2.0)
        self.assertGreaterEqual(hi, 2.0)
        self.assertAlmostEqual(fit["quality"]["ci_halfwidth"], (hi - lo) / 2, places=9)

    def test_runs_without_an_advance_count_are_reported_not_guessed(self):
        runs = self._runs(range(10, 130, 10))
        runs += [_safari_run(100000, 500, 600), _safari_run(100000, 500, 610)]  # no advance_frame
        fit = self._fit(runs, per_advance=True)
        self.assertEqual(fit["quality"]["n_with_advances"], 12)
        self.assertEqual(fit["quality"]["n_missing_advances"], 2)
        # They sat out the slope fit entirely rather than being defaulted to 0 advances.
        self.assertAlmostEqual(fit["per_advance"], 2.0, places=6)

    def test_jitter_is_measured_about_the_adopted_fit(self):
        # Residual scatter of +-3 frames about the line at M=100000 -> c = 3/sqrt(100000).
        noise = [3, -3] * 6
        fit = self._fit(self._runs(range(10, 130, 10), noise=noise),
                        per_advance=True, jitter=True)
        self.assertTrue(fit["quality"]["estimable"])
        self.assertAlmostEqual(fit["jitter_c"], 3.0 / (100000 ** 0.5), places=9)

    def test_jitter_without_per_advance_uses_the_flat_residuals(self):
        fit = self._fit(self._runs([10, 20, 30], slope=0.0, noise=[4, -4, 0]),
                        jitter=True)
        self.assertIsNone(fit["quality"])
        self.assertGreater(fit["jitter_c"], 0.0)


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


class TestWithSafariOffsetPerAdvance(unittest.TestCase):
    """with_safari_offset(advances) folds offset + per_advance*advances (clayton-6h2.2).

    The advance count is CONSTANT for any one chart target or compass run, which is why the
    term folds into the intercept here rather than threading through the scorers.
    """

    def _model(self, **kw):
        return CalibrationModel(kind="line", target="dF", beta=0.0006, alpha=10.0, **kw)

    def test_advances_scale_the_per_advance_term(self):
        m = self._model(safari_offset=30.0, safari_offset_per_advance=-2.0)
        self.assertEqual(m.with_safari_offset(0).alpha, 40.0)     # 10 + 30
        self.assertEqual(m.with_safari_offset(20).alpha, 0.0)     # 10 + 30 - 40
        self.assertIsNone(m.with_safari_offset(20).safari_offset_per_advance)

    def test_advances_ignored_when_the_model_has_no_per_advance_term(self):
        # An advance count reaching a model fit without this feature must change nothing --
        # that's what keeps every existing model's behavior identical.
        m = self._model(safari_offset=30.0)
        self.assertEqual(m.with_safari_offset(81).alpha, m.with_safari_offset(0).alpha)

    def test_per_advance_alone_still_applies(self):
        m = self._model(safari_offset=None, safari_offset_per_advance=1.5)
        self.assertAlmostEqual(m.with_safari_offset(10).alpha, 25.0)
        self.assertIs(m.with_safari_offset(0), m)   # nothing to fold at zero advances

    def test_quad_folds_the_per_advance_term_too(self):
        m = CalibrationModel(kind="quad", coeffs=(1.0, 2.0, 3.0), m_center=0.0, m_scale=1.0,
                             safari_offset=5.0, safari_offset_per_advance=0.5)
        self.assertEqual(m.with_safari_offset(10).coeffs, (11.0, 2.0, 3.0))

    def test_safari_jitter_replaces_the_metronome_jitter(self):
        m = self._model(safari_offset=30.0, jitter_c=0.1, safari_jitter_c=0.25)
        baked = m.with_safari_offset(0)
        self.assertEqual(baked.jitter_c, 0.25)
        self.assertIsNone(baked.safari_jitter_c)    # cleared, so a second fold is a no-op
        self.assertEqual(m.jitter_c, 0.1)           # original untouched

    def test_safari_jitter_applies_even_with_no_offset_to_fold(self):
        m = self._model(safari_offset=None, jitter_c=0.1, safari_jitter_c=0.25)
        self.assertEqual(m.with_safari_offset().jitter_c, 0.25)

    def test_safari_shift_is_the_sum_of_both_terms(self):
        m = self._model(safari_offset=-400.0, safari_offset_per_advance=-2.0)
        self.assertAlmostEqual(m.safari_shift(81), -562.0)
        self.assertAlmostEqual(m.safari_shift(), -400.0)

    def test_new_fields_roundtrip_and_old_artifacts_still_load(self):
        m = self._model(safari_offset=30.0, safari_offset_per_advance=-2.0,
                        safari_jitter_c=0.25)
        m.safari_offset_per_advance_ci = (-3.0, -1.0)
        m2 = CalibrationModel.from_dict(json.loads(json.dumps(m.to_dict())))
        self.assertEqual(m2.safari_offset_per_advance, -2.0)
        self.assertEqual(m2.safari_offset_per_advance_ci, (-3.0, -1.0))
        self.assertEqual(m2.safari_jitter_c, 0.25)
        d = m.to_dict()
        for k in ("safari_offset_per_advance", "safari_offset_per_advance_n",
                  "safari_offset_per_advance_ci", "safari_jitter_c"):
            d.pop(k)
        old = CalibrationModel.from_dict(d)
        self.assertIsNone(old.safari_offset_per_advance)
        self.assertIsNone(old.safari_jitter_c)
        self.assertEqual(old.with_safari_offset(81).alpha, 40.0)   # flat offset only


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
