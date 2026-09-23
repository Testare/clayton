"""Tests for SafariPokemon.capture_chance / flee_chance — the base rates shown in the UI.

The game's raw catch/flee numbers say little on their own (a catch rate of 255 is a 50% ball,
not a certainty), so the Expedition form shows what they actually work out to. These pin the
arithmetic against the simulation it describes, so the displayed percentage can't drift away
from what throw_ball/__flee_check really do.
"""
import unittest

from claytonlib.safari import SafariContext, SafariStep, safari_pokemon_by_name


class TestCaptureChance(unittest.TestCase):
    def test_matches_the_worked_example(self):
        # Spinda, catch rate 255 -> 50% per ball (the example this feature was specified from).
        spinda = safari_pokemon_by_name("spinda")
        self.assertEqual(spinda.base_catch_rate, 255)
        self.assertAlmostEqual(spinda.capture_chance(), 0.5028, places=3)
        self.assertEqual(round(spinda.capture_chance() * 100), 50)

    def test_a_low_catch_rate_is_small_but_not_zero(self):
        # Metang is 0.42% -- the case where rounding to whole percents would read as
        # "impossible", which is why the UI shows "<1%" rather than "0%".
        metang = safari_pokemon_by_name("metang")
        self.assertEqual(metang.base_catch_rate, 3)
        self.assertGreater(metang.capture_chance(), 0)
        self.assertLess(metang.capture_chance(), 0.005)

    def test_it_is_b_over_65536_to_the_fourth(self):
        # A capture needs all four shake rolls under b, and a roll is the RNG's high 16 bits.
        for name in ("metang", "spinda", "kangaskhan", "larvitar"):
            p = safari_pokemon_by_name(name)
            b = p.adjusted_catch_rates_b[0]
            self.assertAlmostEqual(p.capture_chance(), (b / 65536.0) ** 4, places=12)

    def test_raising_the_catch_stage_raises_the_chance(self):
        metang = safari_pokemon_by_name("metang")
        self.assertGreater(metang.capture_chance(1), metang.capture_chance(0))

    def test_agrees_with_the_simulation_over_many_seeds(self):
        """The real check: throw a ball on many seeds and count captures.

        Ties the formula to throw_ball itself rather than to a re-derivation of it, so a
        change to the capture path that the formula didn't follow would fail here.
        """
        spinda = safari_pokemon_by_name("spinda")
        captures = trials = 0
        for seed in range(0, 200_000, 37):
            ctx = SafariContext(spinda, seed)
            if ctx.throw_ball() == SafariStep.CAPTURED:
                captures += 1
            trials += 1
        observed = captures / trials
        self.assertAlmostEqual(observed, spinda.capture_chance(), delta=0.01)


class TestFleeChance(unittest.TestCase):
    def test_matches_the_worked_example(self):
        # Flee rate 60 -> 61/255 -> 24%.
        spinda = safari_pokemon_by_name("spinda")
        self.assertEqual(spinda.base_flee_rate, 60)
        self.assertAlmostEqual(spinda.flee_chance(), 61 / 255, places=6)
        self.assertEqual(round(spinda.flee_chance() * 100), 24)

    def test_the_plus_one_is_not_an_off_by_one(self):
        # __flee_check rolls `advance() % 255` (0..254) and flees on `<= flee_rate`, which is
        # flee_rate+1 of the 255 outcomes. Dropping the +1 would give 23.5% here, not 23.9%.
        p = safari_pokemon_by_name("spinda")
        self.assertNotAlmostEqual(p.flee_chance(), 60 / 255, places=6)

    def test_a_higher_flee_rate_is_more_likely_to_flee(self):
        self.assertGreater(safari_pokemon_by_name("kangaskhan").flee_chance(),
                           safari_pokemon_by_name("metang").flee_chance())

    def test_every_species_is_a_real_probability(self):
        from claytonlib._resources import basedata_json
        for name in basedata_json("safari_pokemon.json"):
            p = safari_pokemon_by_name(name)
            for stage in (0, 1, -1):
                self.assertGreaterEqual(p.capture_chance(stage), 0.0)
                self.assertLessEqual(p.capture_chance(stage), 1.0)
                self.assertGreaterEqual(p.flee_chance(stage), 0.0)
                self.assertLessEqual(p.flee_chance(stage), 1.0)


class TestFacadeExposesRates(unittest.TestCase):
    def setUp(self):
        import tempfile
        from app.facade import Facade
        from app.store import FileStore
        self.api = Facade(FileStore(tempfile.mkdtemp()))

    def test_shape_and_values(self):
        r = self.api.safari_pokemon_rates("spinda")
        self.assertEqual(r["catch_rate"], 255)
        self.assertEqual(r["flee_rate"], 60)
        self.assertEqual(round(r["catch_percent"] * 100), 50)
        self.assertEqual(round(r["flee_percent"] * 100), 24)

    def test_unknown_or_missing_species_is_none_not_an_error(self):
        # The form calls this on every change, including while the select is still blank.
        self.assertIsNone(self.api.safari_pokemon_rates("nosuchmon"))
        self.assertIsNone(self.api.safari_pokemon_rates(""))
        self.assertIsNone(self.api.safari_pokemon_rates(None))


if __name__ == "__main__":
    unittest.main()
