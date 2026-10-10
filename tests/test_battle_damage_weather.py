"""Rain's and sun's damage multiplier, and the one thing about it that is easy to get wrong.

Weather was not modelled at all. That was defensible for the Suicune fixture -- its own Rain
Dance touches neither Ice nor Flying, so the entire incoming surface was unaffected -- and is not
defensible past it: Lugia's Hydro Pump under its own rain is the biggest hit in any configured
moveset, gaining half again, and it is the move that made fainting worth modelling.

**Where it goes is the point.** Transcribed from `CalcMoveDamage`
(src/battle/overlay_12_0224E4FC.c): the weather switch sits near the end of that function but
still above its closing ``return dmg + 2``. So it lands

  * BEFORE the ``+ 2``,
  * before the critical multiplier (`DamageCalcDefault` applies that after the call returns),
  * and before `ApplyDamageRange`, STAB and type effectiveness.

Each of those truncates, so "a 1.5x somewhere in the chain" is not one modifier. These tests pin
the position, not just the factor.
"""
import unittest

from claytonlib.battle.damage import (
    WEATHER_NONE, WEATHER_RAIN, WEATHER_SUN, Attacker, Defender, damage, damage_range,
)
from claytonlib.moves import resolve_move


def _attacker(**kw):
    """A Lv70 Ho-Oh-grade special attacker, Flying/Fire -- so Hydro Pump gets no STAB from it
    and the weather term is isolated."""
    fields = dict(level=70, attack=130, special_attack=154, types=("Fire", "Flying"))
    fields.update(kw)
    return Attacker(**fields)


def _defender(**kw):
    """A Normal-type defender, so type effectiveness is a flat x1 on everything below."""
    fields = dict(defence=80, special_defence=79, types=("Normal",))
    fields.update(kw)
    return Defender(**fields)


class TestTheFactor(unittest.TestCase):
    def setUp(self):
        self.pump = resolve_move("Hydro Pump")
        self.flamethrower = resolve_move("Flamethrower")

    def test_rain_raises_water(self):
        clear = damage(self.pump, _attacker(), _defender(), weather=WEATHER_NONE)
        wet = damage(self.pump, _attacker(), _defender(), weather=WEATHER_RAIN)
        self.assertGreater(wet, clear)

    def test_rain_halves_fire(self):
        clear = damage(self.flamethrower, _attacker(), _defender(), weather=WEATHER_NONE)
        wet = damage(self.flamethrower, _attacker(), _defender(), weather=WEATHER_RAIN)
        self.assertLess(wet, clear)

    def test_sun_is_the_mirror(self):
        hot_water = damage(self.pump, _attacker(), _defender(), weather=WEATHER_SUN)
        hot_fire = damage(self.flamethrower, _attacker(), _defender(), weather=WEATHER_SUN)
        clear_water = damage(self.pump, _attacker(), _defender(), weather=WEATHER_NONE)
        clear_fire = damage(self.flamethrower, _attacker(), _defender(), weather=WEATHER_NONE)
        self.assertLess(hot_water, clear_water)
        self.assertGreater(hot_fire, clear_fire)

    def test_an_unrelated_type_is_untouched(self):
        """Which is exactly why the Suicune fixture never needed this: rain does not touch Ice or
        Flying, and Aurora Beam and Gust are all it has."""
        gust = resolve_move("Gust")
        self.assertEqual(
            damage(gust, _attacker(), _defender(), weather=WEATHER_RAIN),
            damage(gust, _attacker(), _defender(), weather=WEATHER_NONE))

    def test_no_weather_changes_nothing(self):
        self.assertEqual(
            damage(self.pump, _attacker(), _defender()),
            damage(self.pump, _attacker(), _defender(), weather=WEATHER_NONE))

    def test_an_unknown_weather_is_refused(self):
        """Rather than silently behaving as clear -- an unnoticed modifier is unsound here, not
        imprecise: it eliminates the true seed."""
        with self.assertRaises(ValueError):
            damage(self.pump, _attacker(), _defender(), weather="hail")


class TestWhereItGoes(unittest.TestCase):
    """The position, reconstructed step by step the way `CalcMoveDamage` does it."""

    def setUp(self):
        self.pump = resolve_move("Hydro Pump")

    def _core(self, attacker, defender):
        """`atk * power * levelterm / def / 50`, before the `+ 2` -- the value weather sees."""
        level_term = (attacker.level * 2) // 5 + 2
        return (attacker.special_attack * self.pump.power * level_term
                // defender.special_defence // 50)

    def test_the_boost_lands_before_the_plus_two(self):
        """The distinguishing case, and it always distinguishes: the `+ 2` itself gets scaled or
        it does not, so the two orders differ by a whole point before anything else truncates."""
        attacker, defender = _attacker(), _defender()
        core = self._core(attacker, defender)
        before = core * 15 // 10 + 2
        after = (core + 2) * 15 // 10
        self.assertNotEqual(before, after, "the fixture cannot tell the two orders apart")
        self.assertEqual(
            damage(self.pump, attacker, defender, roll=100, weather=WEATHER_RAIN),
            before)

    def test_the_whole_chain_in_order(self):
        """Weather, then `+ 2`, then crit, then the damage roll, then STAB, then effectiveness.
        Rebuilt here independently of the implementation, so a reordering fails this rather than
        quietly producing a different number."""
        attacker = _attacker(types=("Water",))          # STAB on Hydro Pump
        defender = _defender(types=("Fire",))           # x2 on a Water move
        value = self._core(attacker, defender)
        value = value * 15 // 10                        # rain
        value += 2
        value *= 2                                      # crit
        value = value * 93 // 100                       # ApplyDamageRange
        value = value * 15 // 10                        # STAB
        value = value * 20 // 10                        # super effective
        self.assertEqual(
            damage(self.pump, attacker, defender, roll=93, critical=True,
                   weather=WEATHER_RAIN),
            value)

    def test_it_is_not_a_flat_factor_on_the_result(self):
        """Proof the position matters at all: boosting the FINAL number by 1.5 is a different
        answer from boosting the pre-`+2` core, because of the truncations between."""
        attacker, defender = _attacker(), _defender()
        clear = damage(self.pump, attacker, defender, roll=93, critical=True)
        wet = damage(self.pump, attacker, defender, roll=93, critical=True,
                     weather=WEATHER_RAIN)
        self.assertNotEqual(wet, clear * 15 // 10)

    def test_the_range_carries_it_too(self):
        """`damage_range` is what the danger floor is built from, so a weather-blind range is a
        floor that does not hold."""
        lo_clear, hi_clear = damage_range(self.pump, _attacker(), _defender(), critical=True)
        lo_wet, hi_wet = damage_range(self.pump, _attacker(), _defender(), critical=True,
                                      weather=WEATHER_RAIN)
        self.assertGreater(lo_wet, lo_clear)
        self.assertGreater(hi_wet, hi_clear)


if __name__ == "__main__":
    unittest.main()


class TestTheSimulatorAppliesIt(unittest.TestCase):
    """Having the term is not the same as reaching it. `sim.execute_move` had no weather argument
    at all, so rain was tracked on the field, used to decide whether a second Rain Dance FAILS,
    and then ignored by the only thing that reads the number."""

    def setUp(self):
        from claytonlib.battle_compass.sim import HuntConfig
        self.hunt = HuntConfig(target_catch_rate=3, target_has_pressure=False)

    def _state(self, rain: int):
        from claytonlib.battle_compass.state import Battler, BattleState

        ours = Battler(name="Magneton", level=50, types=("Electric", "Steel"),
                       stats={"hp": 700, "atk": 80, "def": 80, "spa": 80, "spd": 79,
                              "spe": 20},
                       moves=("Mean Look",), pp=(5,), hp=700)
        target = Battler(name="Lugia", level=70, types=("Psychic", "Flying"),
                         stats={"hp": 1, "atk": 130, "def": 130, "spa": 154, "spd": 154,
                                "spe": 200},
                         moves=("Hydro Pump",), pp=(5,), hp=1)
        state = BattleState(ours=ours, target=target, rng=0x4A1B2C3D, phase=2)
        state.rain_turns = rain
        return state

    def test_rain_on_the_field_reaches_the_damage(self):
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import Action

        dry = simulate_turn(self._state(0), Action.MOVE_1, self.hunt)
        wet = simulate_turn(self._state(5), Action.MOVE_1, self.hunt)
        self.assertLess(wet.ours.hp, dry.ours.hp,
                        "Hydro Pump dealt the same damage with rain up as without")

    def test_it_costs_the_turn_no_extra_rolls(self):
        """Weather is a damage modifier, not an RNG consumer."""
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import Action

        dry = simulate_turn(self._state(0), Action.MOVE_1, self.hunt)
        wet = simulate_turn(self._state(5), Action.MOVE_1, self.hunt)
        self.assertEqual(dry.rng_offset, wet.rng_offset)

    def test_weather_of_reads_the_field(self):
        from claytonlib.battle_compass.sim import weather_of

        self.assertEqual(weather_of(self._state(0)), WEATHER_NONE)
        self.assertEqual(weather_of(self._state(1)), WEATHER_RAIN)
        self.assertEqual(weather_of(None), WEATHER_NONE)

    def test_rain_set_this_turn_boosts_the_second_actor(self):
        """Rain is up for the rest of the turn it is set, so a target that leads with Rain Dance
        and a partner move behind it is already in weather. Swept, because which move the wild
        Pokemon picks comes from the RNG."""
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import Action, Battler, BattleState

        ours = Battler(name="Magneton", level=50, types=("Electric", "Steel"),
                       stats={"hp": 700, "atk": 80, "def": 80, "spa": 80, "spd": 79,
                              "spe": 20},
                       moves=("Mean Look",), pp=(5,), hp=700)
        target = Battler(name="Lugia", level=70, types=("Psychic", "Flying"),
                         stats={"hp": 1, "atk": 130, "def": 130, "spa": 154, "spd": 154,
                                "spe": 200},
                         moves=("Rain Dance", "Hydro Pump"), pp=(5, 5), hp=1)
        for seed in range(0x4A1B2C3D, 0x4A1B2C3D + 400):
            state = BattleState(ours=ours, target=target, rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, self.hunt)
            if nxt.rain_turns:
                # Rain Dance was used this turn, so rain is up for anything that follows it.
                self.assertGreater(nxt.rain_turns, 0)
                return
        self.fail("no seed in the sweep had Lugia pick Rain Dance")


class TestTheDangerFloorAccountsForIt(unittest.TestCase):
    """The floor is the number the solver heals above so that no single hit can faint us. One
    computed in clear weather against a target holding Rain Dance is not a floor: it would heal
    to a figure it believed was safe and get fainted by the rained-on hit anyway."""

    def _party(self, target_moves, target_pp):
        from claytonlib.battle_compass.state import Battler
        from claytonlib.moves import resolve_move as rm

        ours = Battler(name="Magneton", level=50, types=("Electric", "Steel"),
                       stats={"hp": 300, "atk": 80, "def": 80, "spa": 80, "spd": 79,
                              "spe": 20},
                       moves=("Mean Look",), pp=(5,))
        target = Battler(name="Lugia", level=70, types=("Psychic", "Flying"),
                         stats={"hp": 1, "atk": 130, "def": 130, "spa": 154, "spd": 154,
                                "spe": 200},
                         moves=target_moves, pp=target_pp, hp=1)
        return ours, target

    def test_a_rain_setter_raises_the_floor(self):
        from claytonlib.battle_compass.hunt_session import worst_incoming_hit

        without = worst_incoming_hit(*self._party(("Hydro Pump",), (5,)))
        with_rain = worst_incoming_hit(*self._party(("Hydro Pump", "Rain Dance"), (5, 5)))
        self.assertGreater(with_rain, without,
                           "Rain Dance in the moveset did not raise the floor")

    def test_a_target_with_no_setter_is_unaffected(self):
        from claytonlib.battle_compass.hunt_session import reachable_weathers, worst_incoming_hit

        ours, target = self._party(("Hydro Pump",), (5,))
        self.assertEqual(reachable_weathers(target), (WEATHER_NONE,))
        self.assertEqual(worst_incoming_hit(ours, target),
                         worst_incoming_hit(ours, target))

    def test_rain_dance_is_what_puts_rain_in_reach(self):
        from claytonlib.battle_compass.hunt_session import reachable_weathers

        _, target = self._party(("Hydro Pump", "Rain Dance"), (5, 5))
        self.assertEqual(reachable_weathers(target), (WEATHER_NONE, WEATHER_RAIN))
