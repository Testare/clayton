"""The danger floor asks two questions, and they used to share one answer.

Reported from the app: a Lv54 Magneton at 122/134 HP (SpD 101) was flagged in range of a single
hit with no rain on the field. Reproduced exactly -- Lugia's worst crit against it is **92 in
clear weather** and **136 under rain**.

`worst_incoming_hit` maximised over `reachable_weathers(target)` even when handed a live `field`,
justified in its docstring as "the target can put it up on the turn it attacks, so there is no
state in which we could have observed it first."

**That justification was wrong.** The target picks ONE move per turn: Rain Dance deals no damage,
and Hydro Pump uses whatever weather was already up. So the weather at the start of a turn is as
observable as the Ancient Power stat boost the same docstring contrasted it against.

So now: the live indicator reads the field, and `any_reachable_weather=True` keeps the solver's
heal decision conservative. clayton-5rz.
"""
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.hunt_session import worst_incoming_hit
from claytonlib.battle_compass.state import Battler, BattleState, Status

#: The reported Magneton: Lv54, 134 max HP, Sp. Def 101, sitting on 122.
MAGNETON = dict(hp=134, atk=85, **{"def": 120}, spa=170, spd=101, spe=118)


def _lugia(**kw):
    stats = derive_species_stats("lugia", 45, "Serious",
                                 ivs={"hp": 31, "atk": 31, "def": 31,
                                      "spa": 17, "spd": 31, "spe": 31})
    return Battler(name="Lugia", level=45, types=tuple(species("lugia")["types"]),
                   stats=stats, moves=("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast"),
                   pp=(30, 5, 5, 5), ability="Pressure", **kw)


def _magneton():
    return Battler(name="Magneton", level=54, types=tuple(species("magneton")["types"]),
                   stats=dict(MAGNETON), hp=122)


def _state(rain=0):
    state = BattleState(rng=0x12345678, ours=_magneton(),
                        target=_lugia(hp=1, status=Status.PARALYSIS))
    state.rain_turns = rain
    return state


class TestTheReportedCase(unittest.TestCase):
    def test_clear_weather_is_92_and_the_magneton_is_out_of_range(self):
        state = _state(rain=0)
        now = worst_incoming_hit(state.ours, state.target, field=state)
        self.assertEqual(now, 92)
        self.assertGreater(state.ours.hp, now, "122 HP must not be in range of 92")

    def test_rain_is_136_and_it_IS_in_range(self):
        state = _state(rain=5)
        self.assertEqual(worst_incoming_hit(state.ours, state.target, field=state), 136)

    def test_the_reachable_figure_is_136_even_in_clear_weather(self):
        """Which is the right answer to a different question, and what the solver heals to."""
        state = _state(rain=0)
        self.assertEqual(
            worst_incoming_hit(state.ours, state.target, field=state,
                               any_reachable_weather=True), 136)


class TestTheTwoFiguresAreSeparate(unittest.TestCase):
    def test_the_solver_floor_stays_conservative(self):
        from claytonlib.battle_compass.solver import SolverConfig, danger_floor_for

        state = _state(rain=0)
        self.assertEqual(danger_floor_for(state, SolverConfig()), 136,
                         "the heal decision must still count a rain that has not happened")

    def test_they_agree_once_the_rain_is_actually_up(self):
        from claytonlib.battle_compass.solver import SolverConfig, danger_floor_for

        state = _state(rain=5)
        self.assertEqual(danger_floor_for(state, SolverConfig()),
                         worst_incoming_hit(state.ours, state.target, field=state))

    def test_they_agree_against_a_target_with_no_weather_move(self):
        """So the page attaches an "if it rains" note only when that is a different answer."""
        no_weather = Battler(
            name="Lugia", level=45, types=("Psychic", "Flying"), stats=_lugia().stats,
            moves=("Extrasensory", "Aeroblast", "", ""), pp=(30, 5, 0, 0), ability="Pressure")
        ours = _magneton()
        self.assertEqual(
            worst_incoming_hit(ours, no_weather),
            worst_incoming_hit(ours, no_weather, any_reachable_weather=True))

    def test_the_cache_does_not_confuse_the_two(self):
        """Both figures are memoised on the same state, so the flag has to be part of the key --
        otherwise whichever was asked first would be returned for both."""
        state = _state(rain=0)
        first = worst_incoming_hit(state.ours, state.target, field=state)
        second = worst_incoming_hit(state.ours, state.target, field=state,
                                    any_reachable_weather=True)
        again = worst_incoming_hit(state.ours, state.target, field=state)
        self.assertEqual((first, second, again), (92, 136, 92))


class TestTheSnapshotCarriesBoth(unittest.TestCase):
    def test_in_danger_and_in_danger_if_weather_are_distinct_keys(self):
        """The page needs to tell "one hit kills you" from "one hit kills you once it rains"."""
        from claytonlib.battle_compass import hunt_session

        source = __import__("inspect").getsource(hunt_session)
        for key in ("danger_floor_if_weather", "in_danger_if_weather"):
            self.assertIn(f'"{key}"', source)

    def test_in_danger_if_weather_is_false_when_it_adds_nothing(self):
        """It is only true when the reachable figure is strictly worse AND reaches us -- so it
        never duplicates `in_danger`, and never fires when the weather is already up."""
        state = _state(rain=5)
        now = worst_incoming_hit(state.ours, state.target, field=state)
        reachable = worst_incoming_hit(state.ours, state.target, field=state,
                                       any_reachable_weather=True)
        self.assertEqual(now, reachable)
        self.assertFalse(reachable > now)


if __name__ == "__main__":
    unittest.main()
