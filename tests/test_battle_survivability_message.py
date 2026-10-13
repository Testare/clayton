"""What `survivability_warnings` says about the solver, which was wrong.

It told the player "the solver will treat every turn as dangerous and refuse to throw a ball
unless you accept the risk explicitly." That described a collapse `clayton-957.10.1` had already
deliberately REMOVED: `_legal_actions` has no "in danger" short-circuit, and `solve` discards
successors by `nxt.faints > current.faints` -- an exact per-action test against a known stream,
not a bound on what the target could do.

So the behaviour was already what a player would want (route around the crit); only the message
lied about it. Reported from the app by the user, which is the only way a stale message gets
found.

Second fix in the same place: the figure is the maximum over every weather the target can SET, so
against Lugia it comes from a Hydro Pump under its own Rain Dance -- 172 against a Lv58 Smeargle,
where a clear-weather crit is 116 and survivable. The message named neither, leaving no way to
tell which number it meant, and the two call for different decisions.
"""
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.hunt_session import (
    survivability_warnings, worst_incoming_hit,
)
from claytonlib.battle_compass.state import Battler


def _lugia():
    return Battler(
        name="Lugia", level=45, types=tuple(species("lugia")["types"]),
        stats=derive_species_stats("lugia", 45, "Serious",
                                   ivs={"hp": 31, "atk": 31, "def": 31,
                                        "spa": 17, "spd": 31, "spe": 31}),
        moves=("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast"),
        pp=(30, 5, 5, 5), ability="Pressure")


def _smeargle():
    return Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160})


class TestTheWeatherIsNamed(unittest.TestCase):
    def test_the_rain_boosted_case_says_so(self):
        (warning,) = survivability_warnings([_smeargle()], _lugia())
        self.assertIn("Hydro Pump in its own rain", warning)
        self.assertIn("172", warning)

    def test_the_two_figures_really_do_differ_enough_to_matter(self):
        """If clear and rained-on were close, naming the weather would be pedantry. 116 is
        survivable against 153 HP and 172 is not, so it is the difference between "train this
        Pokemon" and "do not be out while it is raining"."""
        from claytonlib.battle.damage import Attacker, Defender, damage
        from claytonlib.moves import resolve_move

        lugia, ours = _lugia(), _smeargle()
        attacker = Attacker(level=45, attack=lugia.stats["atk"],
                            special_attack=lugia.stats["spa"], types=lugia.types,
                            ability="Pressure")
        defender = Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                            types=ours.types)
        hydro = resolve_move("Hydro Pump")
        clear = damage(hydro, attacker, defender, roll=100, critical=True)
        rained = damage(hydro, attacker, defender, roll=100, critical=True, weather="rain")
        self.assertLess(clear, ours.max_hp)
        self.assertGreater(rained, ours.max_hp)
        self.assertEqual(rained, worst_incoming_hit(ours, lugia))

    def test_a_target_with_no_weather_move_is_named_plainly(self):
        """Suicune has Rain Dance too, so this uses a target whose worst hit is weather-neutral:
        the suffix must not appear when the weather did not produce the maximum."""
        lugia = _lugia()
        no_rain = Battler(name="Lugia", level=45, types=lugia.types, stats=lugia.stats,
                          moves=("Extrasensory", "Aeroblast", "", ""), pp=(30, 5, 0, 0),
                          ability="Pressure")
        (warning,) = survivability_warnings(
            [Battler(name="Paper", level=5, types=("Normal",),
                     stats={"hp": 12, "atk": 5, "def": 5, "spa": 5, "spd": 5, "spe": 5})],
            no_rain)
        self.assertNotIn("in its own", warning)


class TestItNoLongerClaimsTheSolverRefuses(unittest.TestCase):
    def test_the_stale_sentence_is_gone(self):
        (warning,) = survivability_warnings([_smeargle()], _lugia())
        self.assertNotIn("refuse to throw a ball", warning)
        self.assertNotIn("every turn as dangerous", warning)

    def test_it_says_what_the_solver_actually_does(self):
        (warning,) = survivability_warnings([_smeargle()], _lugia())
        self.assertIn("avoids lethal turns", warning)

    def test_and_names_the_real_cost(self):
        """Not "it will not play" but "you cannot heal out of range" -- which is true and is the
        thing the player can act on."""
        (warning,) = survivability_warnings([_smeargle()], _lugia())
        self.assertIn("cannot heal out of range", warning)

    def test_it_fits_on_one_line(self):
        """These are read on every readiness check. The first version of this message ran to 457
        characters of explanation, which trains the reader to skip the panel -- the reasoning
        lives in the docstring now and the warning states the fact."""
        for warning in survivability_warnings([_smeargle()], _lugia()):
            with self.subTest(warning=warning[:40]):
                self.assertLess(len(warning), 160, warning)

    def test_the_solver_has_no_in_danger_collapse_to_describe(self):
        """The claim the message used to make, asserted against the code rather than trusted:
        `_legal_actions` offers moves and balls regardless of how far below the danger floor we
        are, because `solve` tests fainting exactly instead."""
        from claytonlib.battle_compass.sim import HuntConfig
        from claytonlib.battle_compass.solver import (
            SolverConfig, _legal_actions, danger_floor_for,
        )
        from claytonlib.battle_compass.state import Action, BattleState, Status

        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66,
                              "spa": 45, "spd": 79, "spe": 160},
                       moves=("False Swipe", "Sweet Scent", "", ""), pp=(40, 20, 0, 0),
                       ability="Technician", held_item="Silk Scarf", hp=1)
        target = _lugia()
        state = BattleState(
            rng=0x12345678, ours=ours,
            target=Battler(name="Lugia", level=45, types=target.types, stats=target.stats,
                           moves=target.moves, pp=target.pp, ability="Pressure",
                           hp=1, status=Status.PARALYSIS))
        config, hunt = SolverConfig(), HuntConfig(target_catch_rate=3)
        # Well below the floor: 1 HP against a floor of 172.
        self.assertGreater(danger_floor_for(state, config), ours.hp)
        actions = {a for a, _, _ in _legal_actions(state, config, hunt)}
        # The old collapse returned ITEM and nothing else. Moves and a ball are still on offer,
        # which is the whole of the claim.
        self.assertIn(Action.ITEM, actions)
        self.assertIn(Action.STANDARD_BALL, actions)
        self.assertIn(Action.MOVE_1, actions)
        self.assertNotEqual(actions, {Action.ITEM},
                            "item-only below the floor is exactly the removed behaviour")

    def test_the_capture_ball_is_offered_the_moment_it_would_land(self):
        """And it is offered ALONE, because nothing else is worth doing that turn -- so "refuse
        to throw a ball" was wrong in the one case it most mattered. Found by a test that first
        asserted the ball was always on offer: it is not, it is gated on actually capturing,
        which is a stronger guarantee rather than a weaker one."""
        from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
        from claytonlib.battle_compass.solver import SolverConfig, _legal_actions
        from claytonlib.battle_compass.state import Action, BattleState, Status

        target = _lugia()
        hunt, config = HuntConfig(target_catch_rate=3), SolverConfig()
        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66,
                              "spa": 45, "spd": 79, "spe": 160},
                       moves=("False Swipe", "Sweet Scent", "", ""), pp=(40, 20, 0, 0),
                       ability="Technician", held_item="Silk Scarf", hp=1)
        for seed in range(0x1000, 0x400000, 0x1D):
            state = BattleState(
                rng=seed, ours=ours,
                target=Battler(name="Lugia", level=45, types=target.types, stats=target.stats,
                               moves=target.moves, pp=target.pp, ability="Pressure",
                               hp=1, status=Status.PARALYSIS))
            if not simulate_turn(state, Action.CAPTURE_BALL, hunt).captured:
                continue
            self.assertEqual([a for a, _, _ in _legal_actions(state, config, hunt)],
                             [Action.CAPTURE_BALL])
            return
        self.skipTest("no capturing seed found in the sweep")


if __name__ == "__main__":
    unittest.main()
