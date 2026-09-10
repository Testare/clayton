"""Tests for claytonlib.calibration.CalibrationModel and its utils/ fit adapter."""
import math
import os
import sys
import tempfile
import unittest

from claytonlib.calibration import CalibrationModel, Landing

# utils/ is not a package; add it to the path so calibration_tools imports.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))


class TestLineModel(unittest.TestCase):
    def setUp(self):
        # F_b = 256 + 0.0598*M, jitter c*sqrt(M), fit centered at M_bar=300000.
        self.cm = CalibrationModel(
            kind="line", beta=0.0598, alpha=256.0,
            jitter_c=0.05, jitter_rms=20.0, n_fit=10, sxx=2.0e11, m_bar=300000.0,
        )

    def test_mean_and_slope(self):
        self.assertAlmostEqual(self.cm.mean(300000), 256.0 + 0.0598 * 300000)
        self.assertAlmostEqual(self.cm.slope(123456), 0.0598)

    def test_solve_inverts_mean(self):
        M = self.cm.solve(18000)
        self.assertAlmostEqual(self.cm.mean(M), 18000, places=6)

    def test_jitter_grows_as_sqrt(self):
        s1 = self.cm.jitter_sigma(100000)
        s4 = self.cm.jitter_sigma(400000)
        self.assertAlmostEqual(s4 / s1, 2.0, places=6)  # sqrt(4x) = 2x

    def test_mean_band_minimal_at_centroid_and_grows_away(self):
        at_bar = self.cm.mean_band(300000.0)
        away = self.cm.mean_band(600000.0)
        self.assertLess(at_bar, away)
        # at the centroid the band is jitter_rms/sqrt(n)
        self.assertAlmostEqual(at_bar, 20.0 / math.sqrt(10), places=6)

    def test_total_sigma_excludes_band_when_perfect(self):
        M = 500000
        self.assertAlmostEqual(self.cm.total_sigma(M, include_calibration=False),
                               self.cm.jitter_sigma(M))
        self.assertGreater(self.cm.total_sigma(M, include_calibration=True),
                           self.cm.jitter_sigma(M))

    def test_landing_namedtuple(self):
        L = self.cm.landing(400000)
        self.assertIsInstance(L, Landing)
        self.assertAlmostEqual(L.mean, self.cm.mean(400000))
        self.assertAlmostEqual(L.sigma_total,
                               math.hypot(L.sigma_jitter, L.sigma_band))

    def test_hit_probability_in_unit_interval_and_peaks_at_mean(self):
        M = 300000
        mean = self.cm.mean(M)
        on = self.cm.hit_probability(M, round(mean), tolerance=5)
        off = self.cm.hit_probability(M, round(mean) + 300, tolerance=5)
        self.assertTrue(0.0 <= on["p"] <= 1.0)
        self.assertGreater(on["p"], off["p"])

    def test_predict_range_brackets_expected(self):
        p = self.cm.predict(450000, k=2.0)
        self.assertLess(p["lo"], p["expected"])
        self.assertGreater(p["hi"], p["expected"])
        self.assertAlmostEqual(p["expected"], self.cm.mean(450000))


class TestQuadModel(unittest.TestCase):
    def test_quad_mean_and_solve(self):
        # y = 1 + 2u + 0.5u^2, u = (M-300000)/100000
        cm = CalibrationModel(kind="quad", coeffs=(1.0, 2.0, 0.5),
                              m_center=300000.0, m_scale=100000.0)
        # at M=400000, u=1 -> 1+2+0.5 = 3.5
        self.assertAlmostEqual(cm.mean(400000), 3.5)
        M = cm.solve(3.5)
        self.assertAlmostEqual(cm.mean(M), 3.5, places=4)


class TestFrameReconstruction(unittest.TestCase):
    """frame()/solve_frame(): dF models reconstruct the actual low16 via + F_a (year-correct)."""

    def test_fb_model_ignores_base(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=368.0)  # target defaults to "Fb"
        self.assertEqual(cm.target, "Fb")
        for base in (0, 683, 708):
            self.assertAlmostEqual(cm.frame(300000, base), cm.mean(300000))  # base ignored
            self.assertAlmostEqual(cm.solve_frame(18000, base), cm.solve(18000))

    def test_df_model_adds_base(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=-320.0, target="dF")
        M = 300000
        # frame reconstructs dF(M) + base_low16 (the initial seed's low16, year included).
        self.assertAlmostEqual(cm.frame(M, 708), cm.mean(M) + 708)
        # the +25 year term: same M, base 25 higher -> frame 25 higher, dF unchanged.
        self.assertAlmostEqual(cm.frame(M, 708) - cm.frame(M, 683), 25.0)

    def test_solve_frame_inverts_frame_for_df(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=-320.0, target="dF")
        base = 708
        target_frame = 20050
        M = cm.solve_frame(target_frame, base)
        self.assertAlmostEqual(cm.frame(M, base), target_frame, places=4)

    def test_target_round_trips_through_serialization(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=-320.0, target="dF")
        self.assertEqual(CalibrationModel.from_dict(cm.to_dict()).target, "dF")
        # a legacy artifact without the field loads as the back-compat "Fb".
        d = cm.to_dict(); del d["target"]
        self.assertEqual(CalibrationModel.from_dict(d).target, "Fb")


class TestSerialization(unittest.TestCase):
    def test_round_trip_preserves_predictions(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=250.0,
                              jitter_c=0.04, jitter_rms=18.0,
                              n_fit=8, sxx=1e11, m_bar=280000.0, label="x")
        cm2 = CalibrationModel.from_dict(cm.to_dict())
        for M in (150000, 300000, 600000):
            self.assertAlmostEqual(cm.mean(M), cm2.mean(M))
            self.assertAlmostEqual(cm.total_sigma(M), cm2.total_sigma(M))

    def test_save_load(self):
        cm = CalibrationModel(kind="quad", coeffs=(1.0, 2.0, 0.5),
                              m_center=3e5, m_scale=1e5, jitter_c=0.03)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.json")
            cm.save(path)
            cm2 = CalibrationModel.load(path)
        self.assertEqual(cm2.kind, "quad")
        self.assertAlmostEqual(cm2.mean(400000), cm.mean(400000))


class TestModelSet(unittest.TestCase):
    """The modelset artifact: save/load both fps_model shapes + fps_model normalization."""

    def _pair(self):
        lin = CalibrationModel(kind="line", beta=0.06, alpha=-320.0, target="dF", label="lin")
        quad = CalibrationModel(kind="quad", coeffs=(19000.0, 3600.0, 40.0),
                                m_center=3e5, m_scale=1e5, target="dF", label="quad")
        return {"linear": lin, "quad": quad}

    def test_normalize_fps_model(self):
        from claytonlib.calibration import normalize_fps_model
        self.assertEqual(normalize_fps_model("linear"), "linear")
        self.assertEqual(normalize_fps_model("quad"), "quad")
        self.assertEqual(normalize_fps_model("QUADRATIC"), "quad")
        with self.assertRaises(ValueError):
            normalize_fps_model("cubic")

    def test_save_load_set_round_trip(self):
        models = self._pair()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.json")
            CalibrationModel.save_set(models, path, default="linear")
            got = CalibrationModel.load_set(path)
            self.assertEqual(set(got), {"linear", "quad"})
            self.assertEqual(got["linear"], models["linear"])
            self.assertEqual(got["quad"], models["quad"])

    def test_load_default_selects_by_fps_model(self):
        models = self._pair()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.json")
            CalibrationModel.save_set(models, path, default="linear")
            self.assertEqual(CalibrationModel.load_default(path), models["linear"])  # default
            self.assertEqual(CalibrationModel.load_default(path, "quadratic"), models["quad"])

    def test_legacy_single_model_file_loads_for_any_which(self):
        cm = CalibrationModel(kind="line", beta=0.06, alpha=250.0, target="dF")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.json")
            cm.save(path)  # legacy single-model format (bare dict, no "models" key)
            self.assertEqual(CalibrationModel.load_default(path, "linear"), cm)
            self.assertEqual(CalibrationModel.load_default(path, "quad"), cm)
            self.assertEqual(CalibrationModel.load_set(path), {"linear": cm})

    def test_load_default_missing_is_none(self):
        self.assertIsNone(CalibrationModel.load_default(
            os.path.join(tempfile.mkdtemp(), "absent.json")))
        self.assertEqual(CalibrationModel.load_set(
            os.path.join(tempfile.mkdtemp(), "absent.json")), {})


class TestFitAdapterParity(unittest.TestCase):
    """build_calibration_model must agree with calibrate_timer's own closures."""

    def _runs_path(self):
        return os.path.join(os.path.dirname(__file__), "..", "data", "compass_runs.jsonl")

    def test_parity_with_calibrate_timer(self):
        import calibration_tools as ct
        path = self._runs_path()
        if not os.path.exists(path):
            self.skipTest("no compass_runs.jsonl data present")
        full = ct.calibrate_timer(path=path, verbose=False)
        cm = ct.build_calibration_model(path=path)
        # Independent re-fit of the same data -> an equal (not identical) model.
        self.assertEqual(cm, full["calibration_model"])
        # The reusable model's predict(M) must match the notebook closure predict(delay, cal).
        delay, cal = 420000, -5000
        M = delay + cal
        a = full["predict"](delay, cal)
        b = cm.predict(M)
        self.assertAlmostEqual(a["expected"], b["expected"], places=6)
        self.assertAlmostEqual(a["lo"], b["lo"], places=6)
        self.assertAlmostEqual(a["hi"], b["hi"], places=6)
        hp_a = full["hit_probability"](delay, cal, round(a["expected"]), tolerance=25)
        hp_b = cm.hit_probability(M, round(b["expected"]), tolerance=25)
        self.assertAlmostEqual(hp_a["p"], hp_b["p"], places=9)


if __name__ == "__main__":
    unittest.main()
