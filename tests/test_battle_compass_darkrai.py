"""Darkrai Lv50 (Platinum, Newmoon Island), and the four mechanics its moveset forced.

The first Platinum target, and the first one whose danger is not a hit. Every other configured
encounter can only hurt us by attacking; Darkrai's Hypnosis costs no HP and then Nightmare and
Bad Dreams take 37.5% of our max HP a turn for as long as the sleep lasts, which kills any party
member a four-turn roll catches. So the tests here come in two halves: the four effects, and the
clock.

What each move needed, and why none of it existed before:

* **Hypnosis (effect 1)** -- the first status move any TARGET has had. `act_target` applied
  damage, stat drops and secondary statuses but threw `applied_status` away, so the duration roll
  was spent and the sleep dropped on the floor. Simulated, that means attacking through turns the
  game has us asleep for: every prediction after it wrong, with nothing raised.
* **Nightmare (effect 107)** -- the first volatile residual. It needs a flag that coexists with
  sleep rather than replacing it, a quarter-max-HP tick, and waking up as the cure.
* **Double Team (effect 16)** -- the first thing to raise a stat on the target's own side, and it
  is our accuracy that pays: a 100%-accuracy move becomes missable.
* **Faint Attack (effect 17)** -- accuracy 0, so it spends no accuracy roll. The one of the four
  that needed no code, which is worth a test precisely because it looks like it needs one.

(clayton-6xu.3.3)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.hunt_session import (
    MAX_SLEEP_RESIDUAL_TURNS, max_sleep_turns_lost, survivability_warnings,
)
from claytonlib.battle_compass.sim import (
    BAD_DREAMS_DIVISOR, EFFECT_BYPASS_ACCURACY, EFFECT_EVASION_UP, EFFECT_NIGHTMARE,
    MODELLED_TARGET_EFFECTS, NIGHTMARE_DIVISOR, SLEEP_DURATION_MIN, SLEEP_DURATION_SPAN,
    HuntConfig, bad_dreams_tick, burn_tick, can_miss, execute_move, immune_to_status,
    nightmare_tick, opening_rng, simulate_turn, status_applied_by, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    encounter_level, moveset, supported, target_ability, unsupported_moves,
)
from claytonlib.moves import resolve_move


def _darkrai(**kwargs) -> Battler:
    moves = moveset("darkrai")
    return replace(Battler(
        name="darkrai", level=50, types=tuple(species("darkrai")["types"]),
        stats=derive_species_stats("darkrai", 50, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(name).pp for name in moves),
        ability=target_ability("darkrai")), **kwargs)


def _ours(hp: int = 400, **kwargs) -> Battler:
    """A party member with round numbers, so a quarter and an eighth are exact."""
    return replace(Battler(
        name="Blissey", level=50, types=("Normal",),
        stats={"hp": hp, "atk": 10, "def": 40, "spa": 40, "spd": 130, "spe": 200},
        moves=("False Swipe", "Flash"), pp=(40, 20)), **kwargs)


class TestTheRow(unittest.TestCase):

    def test_the_moveset_is_the_last_four_learnable_in_learn_order(self):
        """From res/pokemon/darkrai/data.json's own `learnset.by_level`: Hypnosis 20, Faint
        Attack 29, Nightmare 38, Double Team 47. Haze is 57, so it just misses."""
        self.assertEqual(moveset("darkrai"),
                         ("Hypnosis", "Faint Attack", "Nightmare", "Double Team"))

    def test_the_level_is_fifty_not_the_unused_roamer_slot(self):
        """`StartLegendaryBattle SPECIES_DARKRAI, 50`. The roamer slot in field_roamer.c says 40
        and never activates, which is the number a guide written from the wrong file would
        give."""
        self.assertEqual(encounter_level("darkrai"), 50)

    def test_nothing_in_the_set_is_unmodelled(self):
        self.assertEqual(unsupported_moves("darkrai"), ((), None))

    def test_it_is_platinum_only(self):
        self.assertIn("darkrai", supported("platinum"))
        self.assertNotIn("darkrai", supported("heartgold"))
        self.assertNotIn("darkrai", supported("soulsilver"))

    def test_the_ability_is_bad_dreams(self):
        self.assertEqual(target_ability("darkrai"), "Bad Dreams")

    def test_all_four_effects_are_listed_as_modelled(self):
        for name in moveset("darkrai"):
            self.assertIn(resolve_move(name).effect, MODELLED_TARGET_EFFECTS, name)


class TestHypnosis(unittest.TestCase):
    """Effect 1, and the branch `act_target` was missing."""

    def test_the_effect_applies_sleep(self):
        self.assertIs(status_applied_by(resolve_move("Hypnosis")), Status.SLEEP)

    def test_a_landed_hypnosis_actually_puts_us_to_sleep(self):
        """The regression this target exists for. `act_target` used to spend the duration roll and
        discard the status, so the simulator had us attacking through our own sleep."""
        asleep = self._first_sleep()
        self.assertIsNotNone(asleep, "no seed in the sample landed a Hypnosis")
        state = asleep
        self.assertIs(state.ours.status, Status.SLEEP)
        self.assertTrue(1 <= state.ours.sleep_turns
                        <= SLEEP_DURATION_MIN + SLEEP_DURATION_SPAN - 1)

    def test_the_duration_is_the_roms_two_plus_rand_mod_four(self):
        """`Random 3, 2` with range+1, so 2..5 [subscript_fall_asleep.s]. The same figures HGSS
        was verified at, which is what the user's "assume it is the same" licenses."""
        self.assertEqual((SLEEP_DURATION_MIN, SLEEP_DURATION_SPAN), (2, 4))

    def test_we_lose_the_turns_we_are_asleep_for(self):
        state = self._first_sleep()
        config = _config()
        slept = 0
        for _ in range(6):
            state = simulate_turn(state, Action.MOVE_1, config)
            if any(part.startswith("Mslp") for part in state.log[-1]):
                slept += 1
            if state.ours.status is not Status.SLEEP:
                break
        self.assertGreaterEqual(slept, 1)

    def test_a_second_hypnosis_fails_against_a_sleeping_target(self):
        hypnosis = resolve_move("Hypnosis")
        self.assertTrue(will_fail(hypnosis, _ours(status=Status.SLEEP, sleep_turns=3)))
        self.assertFalse(will_fail(hypnosis, _ours()))

    def test_insomnia_and_vital_spirit_refuse_it_outright(self):
        """`subscript_fall_asleep` checks both before anything else. Without this an Insomnia
        carrier would be simulated as asleep for turns it spends attacking."""
        for ability in ("Insomnia", "Vital Spirit"):
            with self.subTest(ability):
                mon = _ours(ability=ability)
                self.assertTrue(immune_to_status(mon, Status.SLEEP))
                self.assertTrue(will_fail(resolve_move("Hypnosis"), mon))

    def test_immunity_is_about_sleep_only(self):
        self.assertFalse(immune_to_status(_ours(ability="Insomnia"), Status.PARALYSIS))

    def test_early_bird_halves_what_the_sleep_costs(self):
        """Decrements by two rather than one [battle_controller_player.c:2442], so a rolled 2
        costs no turn at all -- which also halves what Nightmare and Bad Dreams take."""
        rolled_two = _ours(status=Status.SLEEP, sleep_turns=2)
        self.assertFalse(rolled_two.tick_sleep()[1])
        self.assertTrue(replace(rolled_two, ability="Early Bird").tick_sleep()[1])

    def test_a_ball_turn_does_not_tick_the_sleep_counter(self):
        """And it is not a modelling shortcut -- it is where the ROM puts the check.

        The counter drops in `BattleControllerPlayer_BeforeMove`'s STATUS_DISRUPTION state
        [battle_controller_player.c:3145-3149], which is only reached when the battler's action
        is a MOVE. A bag action never gets there. So against Darkrai the clock has a nasty
        property: throwing balls while asleep keeps us asleep, losing 37.5% of max HP a turn,
        and only *trying to move* spends the sleep down.
        """
        state = BattleState(
            ours=_ours(status=Status.SLEEP, sleep_turns=4, nightmare=True),
            target=_darkrai(pp=(0, 0, 0, 0)), rng=opening_rng(0x0C0E02CA, _config()))
        state = simulate_turn(state, Action.CAPTURE_BALL, _config())
        self.assertEqual(state.ours.sleep_turns, 4)
        self.assertIs(state.ours.status, Status.SLEEP)
        # ...and the residuals still land, which is what makes it a trap rather than a free turn.
        self.assertLess(state.ours.hp, 400)

    @staticmethod
    def _first_sleep() -> BattleState | None:
        """Simulate until some seed's Darkrai lands a Hypnosis, and return that state.

        Searched rather than hardcoded: which move it picks is a roll, and a frozen seed would
        pin this test to the move-selection arithmetic rather than to the sleep.
        """
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0260):
            state = BattleState(ours=_ours(), target=_darkrai(),
                                rng=opening_rng(seed, config))
            for _ in range(4):
                state = simulate_turn(state, Action.MOVE_1, config)
                if state.ours.status is Status.SLEEP:
                    return state
                if state.over:
                    break
        return None


class TestNightmare(unittest.TestCase):
    """Effect 107: a volatile that coexists with sleep, and the residual it ticks."""

    def test_it_fails_against_anything_not_asleep(self):
        """Which is the common case in a real run: Darkrai cannot sequence its own moves, so it
        throws Nightmare at a wide-awake party member about a quarter of the turns it acts."""
        self.assertTrue(will_fail(resolve_move("Nightmare"), _ours()))

    def test_it_fails_a_second_time(self):
        already = _ours(status=Status.SLEEP, sleep_turns=4, nightmare=True)
        self.assertTrue(will_fail(resolve_move("Nightmare"), already))

    def test_it_lands_on_a_sleeping_target(self):
        asleep = _ours(status=Status.SLEEP, sleep_turns=4)
        self.assertFalse(will_fail(resolve_move("Nightmare"), asleep))
        _, outcome = execute_move(0x1234_5678, resolve_move("Nightmare"), _darkrai(), asleep,
                                  actor="E", slot=2)
        self.assertTrue(outcome.successful)
        self.assertTrue(outcome.sets_nightmare)

    def test_the_tick_is_a_quarter_of_max_hp(self):
        asleep = _ours(status=Status.SLEEP, sleep_turns=4, nightmare=True)
        self.assertEqual(nightmare_tick(asleep), 400 // NIGHTMARE_DIVISOR)

    def test_the_tick_floors_at_one_rather_than_zero(self):
        """`BattleSystem_Divide` never returns 0 [battle_lib.c:3599-3618], so a 3 HP sleeper
        still loses 1."""
        tiny = _ours(hp=3, status=Status.SLEEP, sleep_turns=4, nightmare=True)
        self.assertEqual(nightmare_tick(tiny), 1)

    def test_waking_up_is_the_cure(self):
        awake = _ours(nightmare=True)
        self.assertEqual(nightmare_tick(awake), 0)

    def test_the_flag_is_cleared_once_we_are_awake(self):
        """The ROM's own `else` branch: an awake holder has the flag removed with no damage. Left
        set, the next sleep would be nightmared for free."""
        state = BattleState(ours=_ours(nightmare=True), target=_darkrai(),
                            rng=opening_rng(0x0C0E02CA, _config()))
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertFalse(state.ours.nightmare)

    def test_fainting_clears_the_volatile(self):
        """`statusVolatile` goes when a Pokemon leaves the field, so a Revive cannot bring back
        something still locked in a nightmare -- the same rule that made a revived Granbull stop
        being burned (clayton-957.10.14)."""
        mon = _ours(status=Status.SLEEP, sleep_turns=4, nightmare=True)
        self.assertFalse(mon.with_hp(0).nightmare)


class TestBadDreams(unittest.TestCase):

    def test_it_takes_an_eighth_every_sleeping_turn(self):
        asleep = _ours(status=Status.SLEEP, sleep_turns=4)
        self.assertEqual(bad_dreams_tick(asleep, opponent_has_bad_dreams=True),
                         400 // BAD_DREAMS_DIVISOR)

    def test_it_does_nothing_to_an_awake_pokemon(self):
        self.assertEqual(bad_dreams_tick(_ours(), opponent_has_bad_dreams=True), 0)

    def test_it_does_nothing_without_the_ability(self):
        asleep = _ours(status=Status.SLEEP, sleep_turns=4)
        self.assertEqual(bad_dreams_tick(asleep, opponent_has_bad_dreams=False), 0)

    def test_the_config_flag_defaults_off_where_pressure_defaults_on(self):
        """Opposite defaults on purpose: assuming Pressure where there is none over-budgets PP,
        while assuming Bad Dreams where there is none subtracts HP the game never subtracts --
        which contradicts every candidate from that turn on."""
        config = HuntConfig(target_catch_rate=3)
        self.assertTrue(config.target_has_pressure)
        self.assertFalse(config.target_has_bad_dreams)

    def test_both_residuals_apply_in_the_same_turn(self):
        """A quarter plus an eighth, which for 400 HP is exactly 150.

        The target is given no PP so that `select_target_move` returns nothing and it does not
        act at all -- otherwise the turn's own hit is mixed into the figure and the test would be
        asserting a damage roll as well as the residuals.
        """
        state = BattleState(
            ours=_ours(status=Status.SLEEP, sleep_turns=5, nightmare=True),
            target=_darkrai(pp=(0, 0, 0, 0)), rng=opening_rng(0x0C0E02CA, _config()))
        before = state.ours.hp
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertEqual(before - state.ours.hp, 150)

    def test_the_rom_order_is_leftovers_burn_nightmare_dreams(self):
        """None of the four spends a roll, so the order only decides WHICH one faints us -- and
        that is enough to matter, because each is clamped at zero. Asserted as "the last one
        still fires when an earlier one has already brought us low", which is the only
        observable consequence [battle_controller_player.c:1259-1272].
        """
        state = BattleState(
            ours=_ours(hp=400, status=Status.SLEEP, sleep_turns=5, nightmare=True).with_hp(140),
            target=_darkrai(pp=(0, 0, 0, 0)), rng=opening_rng(0x0C0E02CA, _config()))
        state = simulate_turn(state, Action.MOVE_1, _config())
        # Nightmare's 100 then Bad Dreams' 50 against 140: the first lands, the second clamps.
        self.assertEqual(state.ours.hp, 0)

    def test_magic_guard_spares_every_residual(self):
        """One check in the ROM, in three places -- burn, Nightmare and Bad Dreams all open with
        `CheckAbility ... ABILITY_MAGIC_GUARD`."""
        guarded = _ours(ability="Magic Guard", status=Status.SLEEP, sleep_turns=4,
                        nightmare=True)
        self.assertEqual(nightmare_tick(guarded), 0)
        self.assertEqual(bad_dreams_tick(guarded, opponent_has_bad_dreams=True), 0)
        self.assertEqual(burn_tick(replace(guarded, status=Status.BURN)), 0)

    def test_heatproof_halves_the_burn_tick_only(self):
        """From `subscript_burn_damage.s`, which halves the already-divided figure. Not a Darkrai
        mechanic; read off the same script while Magic Guard was being wired."""
        burned = _ours(ability="Heatproof", status=Status.BURN)
        self.assertEqual(burn_tick(burned), 400 // 8 // 2)
        self.assertEqual(burn_tick(replace(burned, ability="")), 400 // 8)


class TestDoubleTeam(unittest.TestCase):

    def test_the_effect_id_and_that_it_costs_no_accuracy_roll(self):
        move = resolve_move("Double Team")
        self.assertEqual(move.effect, EFFECT_EVASION_UP)
        self.assertEqual(move.accuracy, 0)

    def test_it_raises_the_users_own_evasion(self):
        _, outcome = execute_move(0x1234_5678, resolve_move("Double Team"), _darkrai(), _ours(),
                                  actor="E", slot=3)
        self.assertEqual(outcome.self_stat_raise, ("evasion_stage", 1))

    def test_the_stage_lands_on_the_target_not_on_us(self):
        config = _config()
        state = BattleState(ours=_ours(), target=_darkrai(), rng=opening_rng(0x2222_1111, config))
        for _ in range(12):
            state = simulate_turn(state, Action.MOVE_1, config)
            if state.target.evasion_stage:
                break
            if state.over:
                break
        self.assertGreater(state.target.evasion_stage, 0,
                           "no Double Team landed in twelve turns")
        self.assertEqual(state.ours.evasion_stage, 0)

    def test_it_makes_our_hundred_accuracy_moves_missable(self):
        """The whole cost of it. False Swipe cannot miss a neutral target and can miss a boosted
        one, which is what turns a filler action into a risk."""
        false_swipe = resolve_move("False Swipe")
        from claytonlib.battle_compass.sim import accuracy_net_stage

        neutral = accuracy_net_stage(_ours(), _darkrai())
        boosted = accuracy_net_stage(_ours(), _darkrai(evasion_stage=2))
        self.assertFalse(can_miss(false_swipe, neutral))
        self.assertTrue(can_miss(false_swipe, boosted))

    def test_it_fails_at_the_ceiling(self):
        maxed = _darkrai(evasion_stage=6)
        self.assertTrue(will_fail(resolve_move("Double Team"), _ours(), actor=maxed))
        self.assertFalse(will_fail(resolve_move("Double Team"), _ours(), actor=_darkrai()))

    def test_no_actor_means_cannot_tell_rather_than_a_guess(self):
        """`move_info` asks about OUR moves without an actor, and a self-targeting move's
        failure cannot be read off the defender's stages."""
        self.assertFalse(will_fail(resolve_move("Double Team"), _darkrai(evasion_stage=6)))


class TestFaintAttack(unittest.TestCase):
    """Effect 17, the one of the four that needed no code -- which is why it is tested."""

    def test_it_is_accuracy_zero_so_it_cannot_miss(self):
        move = resolve_move("Faint Attack")
        self.assertEqual(move.effect, EFFECT_BYPASS_ACCURACY)
        self.assertEqual(move.accuracy, 0)
        self.assertFalse(can_miss(move, 0))

    def test_it_spends_two_rolls_not_three(self):
        """Crit and damage, and no accuracy roll [effect_script_0017.s is CalcCrit then
        CalcDamage]. An accuracy roll spent here would shift every later roll in the turn."""
        _, outcome = execute_move(0x1234_5678, resolve_move("Faint Attack"), _darkrai(), _ours(),
                                 actor="E", slot=1)
        self.assertEqual(outcome.rolls, 2)

    def test_a_raised_evasion_cannot_save_us_from_it(self):
        self.assertFalse(can_miss(resolve_move("Faint Attack"), -6))


class TestTheSleepClock(unittest.TestCase):
    """The advice, which is the part of this target a hit-shaped warning table could not say."""

    def test_the_longest_sleep_ticks_four_times(self):
        """A rolled duration of d leaves us acting on the turn the counter reaches 1, so d-1
        turns are lost -- and the waking turn's status check clears the sleep before the
        end-of-turn block, so it does not tick."""
        self.assertEqual(MAX_SLEEP_RESIDUAL_TURNS, 4)

    def test_it_warns_that_a_long_sleep_is_lethal(self):
        warnings = survivability_warnings([_ours(hp=153)], _darkrai())
        joined = " ".join(warnings)
        self.assertIn("Nightmare and Bad Dreams", joined)
        self.assertIn("asleep", joined)

    def test_the_figure_is_the_pokemons_own(self):
        """57 a turn against 153 HP survives two ticks of a possible four."""
        warning = " ".join(survivability_warnings([_ours(hp=153)], _darkrai()))
        self.assertIn("57 a turn", warning)
        self.assertIn("survives 2", warning)

    def test_nothing_at_all_survives_a_maximal_sleep_against_the_full_moveset(self):
        """A measured finding rather than a design choice, and the reason this warning fires for
        every party: a quarter plus an eighth is 37.5% a turn, so four ticks is 150% of ANY
        Pokemon's max HP. Levelling cannot fix it -- the figures are fractions of max HP -- so
        the plan has to keep us awake or heal every single turn.
        """
        for hp in (153, 400, 714):
            with self.subTest(hp=hp):
                warning = " ".join(
                    w for w in survivability_warnings([_ours(hp=hp)], _darkrai())
                    if "asleep" in w)
                self.assertIn("asleep", warning)

    def test_bad_dreams_alone_is_never_lethal_through_the_clock(self):
        """Which is both the gate working and a fact about the target.

        An eighth a turn over at most four turns is half of max HP, whatever the HP is -- so a
        Darkrai that has not learned Nightmare yet (anything under Lv38) cannot kill through
        sleep at all, and no party member gets a warning. Nightmare is what turns the clock
        lethal, and the warning fires exactly when it should.
        """
        no_nightmare = _darkrai(moves=("Hypnosis", "Faint Attack"), pp=(20, 20))
        for hp in (60, 200, 400):
            with self.subTest(hp=hp):
                warnings = survivability_warnings([_ours(hp=hp)], no_nightmare)
                self.assertEqual([w for w in warnings if "asleep" in w], [])


class TestOneAbilityBlanksTheWholeChain(unittest.TestCase):
    """clayton-4wr.1.3. Insomnia against Darkrai, which is the best thing our side can do to any
    configured target -- and which nothing pinned.

    The chain is Hypnosis -> Nightmare -> Bad Dreams, and all three are *conditional on the sleep*
    rather than being three separate threats. So one ability takes out all three, and what is left
    is a Dark-type Faint Attack at x0.5 into a Dark/Flying carrier plus Double Team's evasion.
    Each link is tested separately here, because each fails for a DIFFERENT reason and a
    regression in any one of them would leave the other two looking fine.
    """

    def _awake(self, ability: str) -> Battler:
        return _ours(ability=ability)

    def test_hypnosis_is_refused_at_the_top_of_the_sleep_script(self):
        """Insomnia and Vital Spirit are the first two checks in `subscript_fall_asleep`, above
        everything else it tests."""
        for ability in ("Insomnia", "Vital Spirit"):
            with self.subTest(ability):
                self.assertTrue(immune_to_status(self._awake(ability), Status.SLEEP))
                self.assertTrue(will_fail(resolve_move("Hypnosis"), self._awake(ability)))
        self.assertFalse(will_fail(resolve_move("Hypnosis"), _ours()))

    def test_it_spends_the_accuracy_roll_and_not_the_duration_roll(self):
        """The cost has to be right as well as the outcome. Hypnosis is 60 accuracy, so the
        accuracy roll is spent; the `Random 3, 2` sits past the Insomnia check, so it is not.

        Swept rather than asserted at one seed, because Hypnosis misses 40% of the time and an
        ordinary victim then spends one roll too -- so a single seed proves nothing either way.
        """
        hypnosis = resolve_move("Hypnosis")
        landed_costs = set()
        for rng in range(0x0C0E0200, 0x0C0E0240):
            _, blocked = execute_move(rng, hypnosis, _darkrai(),
                                      self._awake("Insomnia"), actor="E", slot=0)
            # Never more than the accuracy roll, at any seed, hit or miss.
            self.assertEqual(blocked.rolls, 1)
            self.assertFalse(blocked.successful)
            self.assertIsNone(blocked.applied_status)
            _, landed = execute_move(rng, hypnosis, _darkrai(), _ours(), actor="E", slot=0)
            landed_costs.add(landed.rolls)
        # And an ordinary victim does pay the second roll when the move connects.
        self.assertEqual(landed_costs, {1, 2})

    def test_nightmare_then_fails_for_a_second_reason(self):
        """Not because of the ability -- because `will_fail` refuses it against anything not
        asleep, and an Insomnia holder never is. Two independent refusals, which is why the chain
        cannot be half-broken."""
        self.assertTrue(will_fail(resolve_move("Nightmare"), self._awake("Insomnia")))
        self.assertTrue(will_fail(resolve_move("Nightmare"), _ours()))        # also awake
        self.assertFalse(will_fail(resolve_move("Nightmare"),
                                   _ours(status=Status.SLEEP, sleep_turns=3)))

    def test_bad_dreams_goes_for_free_because_it_needs_us_asleep(self):
        """No refusal anywhere: the tick simply reads the status. Which is the point -- the
        ability was never aimed at Bad Dreams and takes it out anyway."""
        awake = self._awake("Insomnia")
        self.assertEqual(bad_dreams_tick(awake, opponent_has_bad_dreams=True), 0)
        asleep = _ours(status=Status.SLEEP, sleep_turns=3)
        self.assertGreater(bad_dreams_tick(asleep, opponent_has_bad_dreams=True), 0)

    def test_the_whole_moveset_run_against_an_insomnia_holder_never_sleeps_it(self):
        """End to end rather than per rule, because the three above are checked in three
        different places and only a run exercises all of them in order."""
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0260):
            state = BattleState(ours=self._awake("Insomnia"), target=_darkrai(),
                                rng=opening_rng(seed, config))
            for _ in range(8):
                state = simulate_turn(state, Action.MOVE_1, config)
                self.assertIsNot(state.ours.status, Status.SLEEP)
                self.assertFalse(state.ours.nightmare)
                if state.over:
                    break

    def test_an_ordinary_party_member_really_does_get_slept_in_the_same_sweep(self):
        """The control. Without it the test above passes against a simulator that never sleeps
        anybody."""
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0260):
            state = BattleState(ours=_ours(), target=_darkrai(), rng=opening_rng(seed, config))
            for _ in range(8):
                state = simulate_turn(state, Action.MOVE_1, config)
                if state.ours.status is Status.SLEEP:
                    return
                if state.over:
                    break
        self.fail("no Hypnosis landed in 96 seeds, so the Insomnia sweep proves nothing")

    def test_the_warning_names_the_carrier_instead_of_repeating_the_advice(self):
        """"Insomnia or Vital Spirit refuses it" is useful to somebody picking a party and useless
        to somebody who has brought the carrier. What they need then is WHICH Pokemon."""
        honchkrow = Battler(name="Honchkrow", level=55, types=("Dark", "Flying"),
                            ability="Insomnia",
                            stats={"hp": 200, "atk": 150, "def": 90,
                                   "spa": 120, "spd": 95, "spe": 110})
        alone = " ".join(survivability_warnings([_ours(hp=153)], _darkrai()))
        self.assertIn("Keep it awake or heal every turn", alone)
        withit = " ".join(survivability_warnings([_ours(hp=153), honchkrow], _darkrai()))
        self.assertIn("Honchkrow (Insomnia) is immune to it", withit)
        self.assertNotIn("Keep it awake or heal every turn", withit)

    def test_the_carrier_is_never_offered_as_its_own_answer(self):
        """An immune Pokemon produces no warning to append this to, so it cannot happen in
        practice -- but the two callers reach `_sleep_answer` by different routes."""
        from claytonlib.battle_compass.hunt_session import _sleep_answer

        honchkrow = Battler(name="Honchkrow", level=55, types=("Dark", "Flying"),
                            ability="Insomnia", stats={"hp": 200})
        self.assertEqual(_sleep_answer([honchkrow], honchkrow), "")
        self.assertIn("Honchkrow", _sleep_answer([honchkrow], _ours()))


class TestEarlyBirdHalvesTheClock(unittest.TestCase):
    """The third ability, and the one whose figure the warnings were getting wrong."""

    def test_the_worst_case_is_two_turns_rather_than_four(self):
        """Worked through `tick_sleep` with a decrement of two: a rolled 2 costs nothing at all,
        3 and 4 cost one turn, 5 costs two."""
        plain = _ours()
        early = _ours(ability="Early Bird")
        self.assertEqual(max_sleep_turns_lost(plain), MAX_SLEEP_RESIDUAL_TURNS)
        self.assertEqual(max_sleep_turns_lost(early), MAX_SLEEP_RESIDUAL_TURNS // 2)

    def test_the_counter_really_does_behave_that_way(self):
        """Pinned against `tick_sleep` rather than asserted, so the figure above cannot drift from
        the mechanic it summarises."""
        for duration, expected_lost in ((2, 0), (3, 1), (4, 1), (5, 2)):
            mon = _ours(ability="Early Bird", status=Status.SLEEP, sleep_turns=duration)
            lost = 0
            while True:
                mon, acts = mon.tick_sleep()
                if acts:
                    break
                lost += 1
            with self.subTest(duration=duration):
                self.assertEqual(lost, expected_lost)

    def test_the_clock_warning_quotes_the_holders_own_figure(self):
        """It quoted four at an Early Bird holder, which overstated the danger twofold -- and for a
        residual priced per turn that is the difference between "bring a healer" and "this is
        fine"."""
        early = _ours(hp=240, ability="Early Bird")
        self.assertEqual(survivability_warnings([early], _darkrai()), [])
        plain = _ours(hp=240)
        self.assertTrue(any("can last 4" in w for w in survivability_warnings([plain], _darkrai())))

    def test_it_is_offered_as_a_partial_answer_when_nothing_is_immune(self):
        """Named separately and last, because it HALVES the sleep rather than refusing it -- a
        reader who stops after the first clause must not come away thinking it is immune."""
        xatu = Battler(name="Xatu", level=55, types=("Psychic", "Flying"), ability="Early Bird",
                       stats={"hp": 160, "atk": 80, "def": 80, "spa": 110, "spd": 100, "spe": 120})
        warnings = " ".join(survivability_warnings([_ours(hp=153), xatu], _darkrai()))
        self.assertIn("Xatu's Early Bird halves the counter", warnings)
        self.assertNotIn("immune", warnings)


class TestItRunsEndToEnd(unittest.TestCase):

    def test_eight_turns_against_darkrai_simulate_without_raising(self):
        """The coverage check that matters most: every one of its moves fires somewhere in a
        sweep this wide, and an unmodelled one would either raise or silently do nothing."""
        config = _config()
        seen = set()
        for seed in range(0x0C0E0200, 0x0C0E0230):
            state = BattleState(ours=_ours(), target=_darkrai(), rng=opening_rng(seed, config))
            for _ in range(8):
                state = simulate_turn(state, Action.MOVE_1, config)
                seen.update(part for part in state.log[-1] if part.startswith("E"))
                if state.over:
                    break
        # All four slots picked at least once across the sweep, so none of the four is untested.
        for slot in ("E1", "E2", "E3", "E4"):
            self.assertTrue(any(part.startswith(slot) for part in seen), slot)


def _config() -> HuntConfig:
    """Darkrai's: catch rate 3, no Pressure, Bad Dreams on."""
    return HuntConfig(target_catch_rate=3, target_has_pressure=False,
                      target_has_bad_dreams=True)


if __name__ == "__main__":
    unittest.main()
