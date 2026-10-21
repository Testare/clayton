"""Uxie and Azelf Lv50 (Platinum), and the first targets that act outside their own turn.

`StartLegendaryBattle SPECIES_UXIE, 50` (res/field/scripts/scripts_acuity_cavern.s:33) and
`SPECIES_AZELF, 50` (scripts_valor_cavern.s:47). Both pure Psychic, Levitate, catch rate 3 and
genderless, so Phase 2's catch maths is Suicune's unchanged. Mesprit has no row and cannot have
one: Platinum makes it a roamer, so it is never met through a legendary-battle script.

The movesets are the last four learnable at 50, in learn order, and they share two slots:

    Uxie   Swift(21), Yawn(31), Future Sight(36), Amnesia(46)
    Azelf  Swift(21), Uproar(31), Future Sight(36), Nasty Plot(46)

Four things make this pair different in kind from the six before it, and each has a section here:

* **Yawn acts on a turn of its own.** It is the first delayed status either side has had: the
  sleep lands at the END of the turn after it, and the duration roll is spent then rather than
  when the move was used.
* **Future Sight banks its damage.** One roll at use and nothing else -- no crit, no accuracy --
  then the hit check two turns later at end of turn. It gets no STAB and no type effectiveness,
  which makes it the one move in this project that a Dark type cannot be immune to; and because
  the ROM keys it to the battler POSITION, switching somebody else in does not dodge it.
* **Uproar locks Azelf into attacking for 3-6 turns**, during which it spends no move-selection
  roll and no PP. It forbids sleep outright while it runs and wakes anything already asleep --
  and a Soundproof party member blanks the whole move, lock and ban included. It is also the
  first DAMAGING sound move any target has had, which is what made Soundproof need code rather
  than only a table row.
* **Nasty Plot doubles Azelf's special attack.** Off base 125 that turns a 60-power Swift into a
  one-shot, and the danger floor had no notion of a +2 primary self-raise at all.

And one finding that is the opposite of the natural guess: **neither of these separates two seeds
one RTC second apart.** See `TestItRunsEndToEnd` for the measurement and the reason -- every roll
either target makes is blind between siblings except Future Sight's 90% check, Uproar's duration
roll included.

(clayton-6xu.7)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.damage import Attacker, Defender, damage
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import (
    banked_hit, field_conditions, reachable_attack_stages, survivability_warnings,
    worst_incoming_hit,
)
from claytonlib.battle_compass.sim import (
    FUTURE_SIGHT_TURNS, MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, PRIMARY_SELF_RAISES,
    SOUND_MOVES, UPROAR_TURNS_MIN, UPROAR_TURNS_SPAN, YAWN_DROWSY_TURNS, HuntConfig, can_miss,
    execute_move, move_roll_cost, opening_rng, pending_future_sight, select_target_move,
    simulate_turn, soundproofed, unselectable_reason, uproar_active, will_fail,
)
from claytonlib.battle_compass.solver import SolverConfig, danger_floor_for
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    encounter_level, moveset, supported, target_ability, unsupported_moves,
)
from claytonlib.moves import resolve_move

#: A seed range the other target modules also sweep, so a "no proc in N seeds" failure is
#: comparable across them.
SEEDS = range(0x0C0E0200, 0x0C0E0260)


def _lake(name: str, **kwargs) -> Battler:
    moves = moveset(name)
    return replace(Battler(
        name=name, level=50, types=tuple(species(name)["types"]),
        stats=derive_species_stats(name, 50, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability(name)), **kwargs)


def _ours(**kwargs) -> Battler:
    # Deliberately bulky: several tests need to survive eight turns of being hit so that the
    # end-of-turn machinery gets to run rather than the run ending in a faint.
    return replace(Battler(
        name="Smeargle", level=73, types=("Normal",),
        stats={"hp": 400, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
        moves=("False Swipe", "Sing"), pp=(40, 15)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


def _state(target: Battler, ours: Battler | None = None, seed: int = 0x0C0E02CA,
           **kwargs) -> BattleState:
    config = _config()
    return BattleState(ours=ours or _ours(), target=target,
                       rng=opening_rng(seed, config), **kwargs)


class TestTheRows(unittest.TestCase):

    def test_the_movesets_are_the_last_four_learnable_at_fifty(self):
        self.assertEqual(moveset("uxie"), ("Swift", "Yawn", "Future Sight", "Amnesia"))
        self.assertEqual(moveset("azelf"), ("Swift", "Uproar", "Future Sight", "Nasty Plot"))

    def test_both_are_level_fifty(self):
        self.assertEqual(encounter_level("uxie"), 50)
        self.assertEqual(encounter_level("azelf"), 50)

    def test_both_are_platinum_only(self):
        for name in ("uxie", "azelf"):
            with self.subTest(name):
                self.assertIn(name, supported("platinum"))
                self.assertNotIn(name, supported("heartgold"))
                self.assertNotIn(name, supported("soulsilver"))

    def test_mesprit_is_not_a_target_because_platinum_roams_it(self):
        """No `StartLegendaryBattle` anywhere for it -- it is met through `field_roamer`, which
        Battle Compass's static-encounter model does not cover."""
        self.assertNotIn("mesprit", supported("platinum"))
        with self.assertRaises(KeyError):
            moveset("mesprit")

    def test_both_abilities_are_levitate(self):
        for name in ("uxie", "azelf"):
            with self.subTest(name):
                self.assertEqual(target_ability(name), "Levitate")

    def test_nothing_in_either_set_is_unmodelled(self):
        self.assertEqual(unsupported_moves("uxie"), ((), None))
        self.assertEqual(unsupported_moves("azelf"), ((), None))

    def test_the_catch_rate_is_suicunes_so_phase_two_is_unchanged(self):
        for name in ("uxie", "azelf", "suicune"):
            with self.subTest(name):
                self.assertEqual(species(name)["catch_rate"], 3)

    def test_the_run_ending_moves_are_pushed_out_by_the_level_window(self):
        """Two strokes of luck. **Rest(1)** would heal off every False Swipe and make the chip
        phase unwinnable, and **Explosion(76)** would end the run against a 1 HP target -- and
        both are outside the four-move window at 50, Rest from below and Explosion from above.
        """
        for name in ("uxie", "azelf"):
            with self.subTest(name):
                self.assertNotIn("Rest", moveset(name))
                self.assertNotIn("Confusion", moveset(name))
        self.assertNotIn("Explosion", moveset("azelf"))
        self.assertNotIn("Last Resort", moveset("azelf"))
        self.assertNotIn("Flail", moveset("uxie"))

    def test_swift_rides_on_the_effect_faint_attack_already_modelled(self):
        """Effect 17: accuracy 0, so it never misses and spends no accuracy roll. It is SPECIAL
        in Gen 4, which is what makes Nasty Plot matter to it."""
        swift, faint_attack = resolve_move("Swift"), resolve_move("Faint Attack")
        self.assertEqual(swift.effect, faint_attack.effect)
        self.assertFalse(can_miss(swift, 0))
        self.assertNotEqual(swift.category, faint_attack.category)   # special vs physical


class TestYawn(unittest.TestCase):
    """The first delayed status on either side."""

    def test_it_spends_no_roll_of_its_own(self):
        """Accuracy 0, and `subscript_yawn.s` only calls `BtlCmd_TryYawn`, which sets a counter.
        The roll comes two turns later, when the sleep lands."""
        self.assertEqual(move_roll_cost(resolve_move("Yawn")), 0)

    def test_the_sleep_lands_at_the_end_of_the_turn_after_it(self):
        """`BtlCmd_TryYawn` sets 2 and the end-of-turn check decrements before testing for zero,
        so the first turn the sleep costs is the one after next."""
        config = _config()
        state = _state(_lake("uxie", pp=(0, 10, 0, 0)))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.ours.drowsy_turns, YAWN_DROWSY_TURNS - 1)
        self.assertIs(state.ours.status, Status.NONE)
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.ours.drowsy_turns, 0)
        self.assertIs(state.ours.status, Status.SLEEP)
        self.assertGreaterEqual(state.ours.sleep_turns, 2)

    def test_a_second_yawn_fails_rather_than_restarting_the_clock(self):
        state = _state(_lake("uxie"))
        drowsy = _ours(drowsy_turns=1)
        self.assertTrue(will_fail(resolve_move("Yawn"), drowsy, state))
        self.assertFalse(will_fail(resolve_move("Yawn"), _ours(), state))

    def test_it_fails_against_an_already_statused_victim(self):
        """`status_applied_by` returns None for Yawn -- it inflicts nothing at the moment it is
        used -- so none of `will_fail`'s generic status families covers this."""
        state = _state(_lake("uxie"))
        self.assertIsNone(
            __import__("claytonlib.battle_compass.sim", fromlist=["x"])
            .status_applied_by(resolve_move("Yawn")))
        self.assertTrue(will_fail(resolve_move("Yawn"),
                                  _ours(status=Status.PARALYSIS), state))

    def test_insomnia_makes_it_ineffective(self):
        """Checked at the very top of `subscript_yawn.s`, before anything else."""
        state = _state(_lake("uxie"))
        for ability in ("Insomnia", "Vital Spirit"):
            with self.subTest(ability):
                self.assertTrue(will_fail(resolve_move("Yawn"),
                                          _ours(ability=ability), state))

    def test_the_drowse_is_reported_in_the_field_banner(self):
        """It has no status chip of its own, and a player who cannot see the counter finds out by
        losing a turn."""
        state = _state(_lake("uxie"), ours=_ours(drowsy_turns=1))
        (drowsy,) = field_conditions(state)
        self.assertEqual(drowsy, {"name": "Drowsy", "turns": 1, "whose": "ours"})

    def test_switching_out_shakes_it_off(self):
        """The ROM keeps it in `moveEffectsMask`, which a freshly built BattleMon zeroes. The
        opposite of a pending Future Sight, which a switch does not dodge."""
        from claytonlib.battle_compass.sim import sent_out

        self.assertEqual(sent_out(_ours(drowsy_turns=1)).drowsy_turns, 0)


class TestFutureSight(unittest.TestCase):
    """The first move whose damage is banked rather than dealt."""

    def test_the_use_turn_spends_exactly_one_roll(self):
        """`TryFutureSight` banks the damage with one `CalcDamageVariance` roll and then sets
        `SYSCTL_NONSTANDARD_ACC_CHECK`, which makes the accuracy check return 0. The effect
        script runs BEFORE `TRY_MOVE`, which is what lets that work."""
        self.assertEqual(move_roll_cost(resolve_move("Future Sight")), 1)
        _, outcome = execute_move(0x0C0E02CA, resolve_move("Future Sight"),
                                  _lake("uxie"), _ours(), actor="E", slot=2)
        self.assertEqual(outcome.rolls, 1)
        self.assertTrue(outcome.successful)
        self.assertIsNotNone(outcome.banked_future_sight)

    def test_the_use_turn_renders_as_a_bare_slot_with_no_hit_marker(self):
        """It neither hits nor misses nor crits on the turn it is used, so the token carries no
        detail -- exactly as a successful status move does."""
        _, outcome = execute_move(0x0C0E02CA, resolve_move("Future Sight"),
                                  _lake("uxie"), _ours(), actor="E", slot=2)
        self.assertEqual(outcome.tokens, ("E3",))

    def test_a_second_one_fails_and_costs_nothing_at_all(self):
        """`TryFutureSight` jumps straight to "But it failed!" without reaching `CalcMoveDamage`
        -- the only zero-roll failure in `execute_move`."""
        pending = _state(_lake("uxie"), future_sight_turns=2, future_sight_damage=40,
                         future_sight_move="Future Sight")
        rng = 0x0C0E02CA
        after, outcome = execute_move(rng, resolve_move("Future Sight"), _lake("uxie"),
                                      _ours(), actor="E", slot=2, field=pending)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertFalse(outcome.successful)
        self.assertIsNone(outcome.banked_future_sight)

    def test_it_lands_two_turns_later_with_its_own_token(self):
        config = _config()
        state = _state(_lake("uxie", pp=(0, 0, 15, 0)))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.future_sight_turns, FUTURE_SIGHT_TURNS - 1)
        banked = state.future_sight_damage
        self.assertGreater(banked, 0)
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.future_sight_turns, 1)
        before = state.ours.hp
        state = simulate_turn(state, Action.MOVE_1, config)
        turn = tok.render_turn(state.log[-1])
        self.assertIn("F", turn)
        self.assertEqual(state.future_sight_turns, 0)
        if "Fh" in turn:
            self.assertEqual(state.ours.hp, before - banked)
            self.assertIn("HP", turn)
        else:
            self.assertIn("F-", turn)

    def test_the_token_is_grammatical_and_demands_an_hp_report_on_a_hit(self):
        self.assertEqual(tok.future_sight_token(True), "Fh")
        self.assertEqual(tok.future_sight_token(False), "F-")
        self.assertTrue(tok.turn_requires_hp(["M1h", "Fh"]))
        self.assertFalse(tok.turn_requires_hp(["M1h", "F-"]))
        self.assertEqual(tok.validate_turn(["M1h", "Fh", "HP380"]), [])
        self.assertEqual(tok.validate_turn(["M1h", "F-"]), [])

    def test_a_malformed_future_sight_token_is_rejected_rather_than_ignored(self):
        """The reason the ball tokens are checked explicitly: a malformed one is still a
        well-formed *token*, so it would sit there matching no candidate with nothing to say
        why."""
        self.assertTrue(tok.validate_turn(["M1h", "F!"]))

    def test_nothing_in_either_moveset_can_miss_on_the_turn_it_is_used(self):
        """Including Future Sight, whose 90 is deferred -- so the interview must not offer
        "Missed" on any turn either target takes."""
        for name in ("uxie", "azelf"):
            missable = [m for m in moveset(name) if can_miss(resolve_move(m), 0)]
            with self.subTest(name):
                self.assertEqual(missable, [])
        self.assertEqual(resolve_move("Future Sight").accuracy, 90)
        self.assertFalse(can_miss(resolve_move("Future Sight"), 0))

    def test_the_interview_is_not_offered_a_hit_marker_for_the_use_turn_either(self):
        """`move_info`'s `damaging` answers "does the turn it is used render a hit marker", and
        for a banked move the answer is no: neither hit, nor miss, nor crit."""
        from claytonlib.battle_compass.hunt_session import move_info

        info = {m["name"]: m for m in move_info(_lake("uxie"), _ours())}
        self.assertFalse(info["Future Sight"]["damaging"])
        self.assertFalse(info["Future Sight"]["can_miss"])
        self.assertEqual(info["Future Sight"]["effective_accuracy"], 0)
        self.assertTrue(info["Swift"]["damaging"])

    def test_it_takes_neither_stab_nor_type_effectiveness(self):
        """`SYSCTL_IGNORE_IMMUNITIES` makes `CheckTypeChart` skip the one function that holds
        STAB, effectiveness and Levitate alike -- and the damage is already banked by then. So a
        Dark type, which an ordinary Psychic move cannot touch at all, still takes it.
        """
        dark = Battler(name="Umbreon", level=73, types=("Dark",),
                       stats={"hp": 400, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 100})
        _, outcome = execute_move(0x0C0E02CA, resolve_move("Future Sight"),
                                  _lake("uxie"), dark, actor="E", slot=2)
        self.assertGreater(outcome.banked_future_sight, 0)
        # The comparison that makes the point: an ordinary Psychic move of the same user's is
        # simply zero against the same defender.
        self.assertEqual(
            damage(resolve_move("Extrasensory"),
                   Attacker(level=50, attack=85, special_attack=95, types=("Psychic",)),
                   Defender(defence=70, special_defence=77, types=("Dark",))),
            0)

    def test_the_banked_figure_is_the_same_against_dark_and_normal_but_for_the_stats(self):
        """Not merely "nonzero against Dark": the type is not read at all. Two defenders with
        identical defences and different types bank the identical number.
        """
        stats = {"hp": 400, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 100}
        banked = []
        for types in (("Dark",), ("Normal",), ("Psychic", "Steel")):
            victim = Battler(name="x", level=73, types=types, stats=stats)
            _, outcome = execute_move(0x0C0E02CA, resolve_move("Future Sight"),
                                      _lake("uxie"), victim, actor="E", slot=2)
            banked.append(outcome.banked_future_sight)
        self.assertEqual(len(set(banked)), 1, banked)

    def test_it_is_a_state_condition_so_a_switch_does_not_dodge_it(self):
        """The ROM indexes it by battler POSITION (`futureSightTurns[defender]`), not by the
        Pokemon standing there. So the counter is on `BattleState` and not on `Battler`."""
        self.assertIn("future_sight_turns", vars(_state(_lake("uxie"))))
        self.assertNotIn("future_sight_turns", vars(_ours()))

    def test_the_pending_hit_is_the_first_row_of_the_field_banner(self):
        state = _state(_lake("uxie"), future_sight_turns=2, rain_turns=3)
        self.assertEqual(field_conditions(state)[0],
                         {"name": "Future Sight", "turns": 2, "whose": "target"})

    def test_the_interview_is_told_only_on_the_turn_it_lands(self):
        """Asking a turn early would invite a report of something the player has not seen."""
        for turns, due in ((3, False), (2, False), (1, True), (0, False)):
            with self.subTest(turns=turns):
                self.assertEqual(
                    _state(_lake("uxie"), future_sight_turns=turns).future_sight_turns == 1, due)

    def test_our_side_cannot_bank_one(self):
        """Effect 148 is absent from `MODELLED_OUR_EFFECTS`, so `unselectable_reason` refuses it
        -- the state has one pair of counters and they are aimed at our slot."""
        self.assertNotIn(resolve_move("Future Sight").effect, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Future Sight")))


class TestUproar(unittest.TestCase):
    """The first multi-turn lock that attacks on every turn of it."""

    def test_the_duration_is_three_to_six_turns_in_total(self):
        """`subscript_uproar.s` is `Random 3, 3`, and `BtlCmd_Random` reads that as
        ``(rand % (3 + 1)) + 3``. metronome_compass rolls the same distribution counted as 2-5
        EXTRA turns, which is where the commonly quoted "2-5 turns" comes from.
        """
        self.assertEqual((UPROAR_TURNS_MIN, UPROAR_TURNS_SPAN), (3, 4))
        seen = set()
        for seed in SEEDS:
            _, outcome = execute_move(seed, resolve_move("Uproar"), _lake("azelf"),
                                      _ours(), actor="E", slot=1)
            if outcome.successful:
                seen.add(outcome.starts_uproar)
        self.assertEqual(seen, {3, 4, 5, 6})

    def test_the_duration_roll_is_spent_only_when_the_uproar_starts(self):
        """A continuation turn re-runs the effect script, finds the volatile already set and
        jumps straight to CalcCrit/CalcDamage."""
        starting = _lake("azelf")
        locked = _lake("azelf", uproar_turns=2, uproar_slot=1)
        _, first = execute_move(0x0C0E02CA, resolve_move("Uproar"), starting,
                                _ours(), actor="E", slot=1)
        _, later = execute_move(0x0C0E02CA, resolve_move("Uproar"), locked,
                                _ours(), actor="E", slot=1)
        self.assertEqual(first.rolls - later.rolls, 1)
        self.assertEqual(later.starts_uproar, 0)

    def test_a_locked_turn_spends_no_selection_roll(self):
        """The sharpest separation any configured target offers: a divergence in roll COUNT
        between candidates, not in one roll's verdict. `Battler_CanPickCommand` is FALSE for the
        Uproar volatile, beside THRASH and MOVE_LOCKED in the same condition."""
        rng = 0x12345678
        after_locked, slot = select_target_move(rng, _lake("azelf", uproar_turns=2,
                                                           uproar_slot=1))
        self.assertEqual(slot, 1)
        self.assertEqual(after_locked, rng)
        after_free, _ = select_target_move(rng, _lake("azelf"))
        self.assertNotEqual(after_free, rng)

    def test_a_locked_turn_spends_no_pp_either(self):
        """`ppDecremented` is set TRUE for a battler that cannot pick a command. Spending it on
        all 3-6 turns would empty a 10-PP Uproar in two uses and change the selection modulus.
        """
        config = _config()
        state = _state(_lake("azelf", pp=(0, 10, 0, 0)))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertGreater(state.target.uproar_turns, 0)
        spent_on_the_first = 10 - state.target.pp_left(1)
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(10 - state.target.pp_left(1), spent_on_the_first)

    def test_the_lock_runs_out_and_the_target_picks_again(self):
        config = _config()
        state = _state(_lake("azelf", pp=(0, 10, 0, 0)))
        state = simulate_turn(state, Action.MOVE_1, config)
        rolled = state.target.uproar_turns + 1
        self.assertIn(rolled, (3, 4, 5, 6))
        for _ in range(rolled - 1):
            state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.target.uproar_turns, 0)
        self.assertIsNone(state.target.uproar_slot)

    def test_it_forbids_sleep_outright_while_it_runs(self):
        """`subscript_fall_asleep`'s "But {0} can't sleep in an uproar!" branch. The duration roll
        sits past it, so refusing here is also what keeps the roll count right -- and it means a
        sleep-based plan against Azelf is not risky, it is refused by the game.
        """
        uproaring = _state(_lake("azelf", uproar_turns=2, uproar_slot=1))
        calm = _state(_lake("azelf"))
        self.assertTrue(uproar_active(uproaring))
        self.assertFalse(uproar_active(calm))
        self.assertTrue(will_fail(resolve_move("Sing"), uproaring.target, uproaring))
        self.assertFalse(will_fail(resolve_move("Sing"), calm.target, calm))

    def test_it_wakes_a_sleeper_rather_than_merely_blocking_new_sleep(self):
        config = _config()
        asleep = _ours(status=Status.SLEEP, sleep_turns=5)
        state = _state(_lake("azelf", pp=(0, 10, 0, 0)), ours=asleep)
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertGreater(state.target.uproar_turns, 0)
        self.assertIs(state.ours.status, Status.NONE)

    def test_a_soundproof_party_member_sleeps_through_it(self):
        """The ROM checks Soundproof at both wake-up sites, which is why `uproar_active` is a
        field-wide answer and the exemption is applied per battler."""
        config = _config()
        asleep = _ours(ability="Soundproof", status=Status.SLEEP, sleep_turns=5)
        state = _state(_lake("azelf", pp=(0, 10, 0, 0)), ours=asleep)
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertIs(state.ours.status, Status.SLEEP)

    def test_soundproof_blocks_the_move_outright(self):
        """It is one of the twelve `sSoundMoves`, so an Electrode or a Whismur blanks Azelf's
        whole Uproar -- its damage AND its lock, which takes the sleep ban away with it.

        **Uproar is the first DAMAGING sound move any target has had**, and that is why this
        needed code rather than only a row: `will_fail` is consulted on the status branch only,
        so Metal Sound got Soundproof for free and Uproar would have dealt damage and locked
        anyway.
        """
        self.assertIn("uproar", SOUND_MOVES)
        self.assertTrue(soundproofed(_ours(ability="Soundproof"), resolve_move("Uproar")))
        config = _config()
        blanked = _state(_lake("azelf", pp=(0, 10, 0, 0)), ours=_ours(ability="Soundproof"))
        before_hp, before_offset = blanked.ours.hp, blanked.rng_offset
        blanked = simulate_turn(blanked, Action.MOVE_1, config)
        self.assertEqual(blanked.ours.hp, before_hp)
        self.assertEqual(blanked.target.uproar_turns, 0)
        self.assertEqual(tok.render_turn(blanked.log[-1]), "M1hE2")
        # Crit, damage and accuracy are all spent before the immunity stage refuses the move; the
        # duration roll and the two post-successful-move advances are not.
        self.assertEqual(blanked.rng_offset - before_offset, 20 - 1)

    def test_an_ordinary_party_member_is_not_protected(self):
        config = _config()
        hit = _state(_lake("azelf", pp=(0, 10, 0, 0)))
        before = hit.ours.hp
        hit = simulate_turn(hit, Action.MOVE_1, config)
        self.assertLess(hit.ours.hp, before)
        self.assertGreater(hit.target.uproar_turns, 0)

    def test_the_lock_is_reported_in_the_field_banner(self):
        state = _state(_lake("azelf", uproar_turns=3, uproar_slot=1))
        (uproar,) = field_conditions(state)
        self.assertEqual(uproar, {"name": "Uproar", "turns": 3, "whose": "target"})

    def test_it_is_not_the_charging_slot_field(self):
        """They share the half that matters most -- no selection roll and no PP -- and part
        company on everything else: a charge turn fires nothing and makes its user unhittable,
        while `execute_move`'s `ends_charge` would clear a shared field on the first Uproar turn.
        """
        locked = _lake("azelf", uproar_turns=2, uproar_slot=1)
        self.assertIsNone(locked.charging_slot)
        from claytonlib.battle_compass.sim import is_semi_invulnerable

        self.assertFalse(is_semi_invulnerable(locked))

    def test_our_side_cannot_start_one(self):
        self.assertNotIn(resolve_move("Uproar").effect, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Uproar")))


class TestTheSelfRaises(unittest.TestCase):
    """Nasty Plot and Amnesia, through one table rather than a branch each."""

    def test_both_are_in_the_self_raise_table_beside_double_teams_evasion(self):
        self.assertEqual(PRIMARY_SELF_RAISES[resolve_move("Nasty Plot").effect],
                         ("spatk_stage", 2))
        self.assertEqual(PRIMARY_SELF_RAISES[resolve_move("Amnesia").effect],
                         ("spdef_stage", 2))
        self.assertEqual(PRIMARY_SELF_RAISES[resolve_move("Double Team").effect],
                         ("evasion_stage", 1))

    def test_neither_spends_a_roll(self):
        """Each effect script is a single `MOVE_SIDE_EFFECT_TO_ATTACKER` subscript pointer, and
        both moves have accuracy 0."""
        for name in ("Nasty Plot", "Amnesia"):
            with self.subTest(name):
                self.assertEqual(move_roll_cost(resolve_move(name)), 0)

    def test_nasty_plot_raises_azelfs_own_sp_atk(self):
        config = _config()
        state = _state(_lake("azelf", pp=(0, 0, 0, 20)))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.target.spatk_stage, 2)
        self.assertEqual(state.ours.spatk_stage, 0)

    def test_amnesia_raises_uxies_own_sp_def(self):
        config = _config()
        state = _state(_lake("uxie", pp=(0, 0, 0, 20)))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.target.spdef_stage, 2)

    def test_a_self_raise_at_plus_six_fails_and_so_costs_two_fewer_advances(self):
        """Read off the table rather than naming Double Team, which is how Nasty Plot and Amnesia
        got this for nothing. An Azelf that has Nasty Plotted three times spends two fewer
        advances on the fourth."""
        maxed = _lake("azelf", spatk_stage=6)
        self.assertTrue(will_fail(resolve_move("Nasty Plot"), _ours(), None, actor=maxed))
        self.assertFalse(will_fail(resolve_move("Nasty Plot"), _ours(), None,
                                   actor=_lake("azelf")))

    def test_both_are_usable_by_our_own_side_too(self):
        """Unlike Uproar, Yawn and Future Sight: the table is read on both halves of the turn, so
        a party member carrying either is modelled for free."""
        for name in ("Nasty Plot", "Amnesia"):
            with self.subTest(name):
                self.assertIn(resolve_move(name).effect, MODELLED_OUR_EFFECTS)
                self.assertIsNone(unselectable_reason(resolve_move(name)))

    def test_amnesia_is_the_gentler_of_the_two_against_a_physical_chipper(self):
        """It raises Sp. Def, and False Swipe is physical -- so Uxie spends roughly one turn in
        four on a move that does not slow the chip phase at all."""
        false_swipe = resolve_move("False Swipe")
        attacker = Attacker(level=73, attack=65, special_attack=40, types=("Normal",))
        at_zero = damage(false_swipe, attacker,
                         Defender(defence=150, special_defence=150, types=("Psychic",)))
        boosted = damage(false_swipe, attacker,
                         Defender(defence=150, special_defence=150, types=("Psychic",),
                                  special_defence_stage=6))
        self.assertEqual(at_zero, boosted)


class TestTheDangerFloor(unittest.TestCase):
    """What these two can do to a party, and the two ways the floor was wrong about it."""

    def test_nasty_plot_now_counts_as_a_booster(self):
        """It used to ask only about Ancient Power's all-stats secondary. Nasty Plot is worse in
        every respect: +2 rather than +1, a primary rather than a 10% secondary, and on the stat
        Azelf actually attacks off."""
        self.assertEqual(reachable_attack_stages(_lake("azelf")), (0, 1, 2, 3, 4, 5, 6))
        self.assertEqual(reachable_attack_stages(_lake("uxie")), (0,))

    def test_the_boosted_floor_is_far_above_the_current_one_for_azelf(self):
        ours = _ours()
        now = worst_incoming_hit(ours, _lake("azelf"))
        boosted = worst_incoming_hit(ours, _lake("azelf"), any_reachable_stage=True)
        self.assertGreater(boosted, now * 2)

    def test_a_banked_hit_is_priced_without_a_crit_or_the_type_chart(self):
        """It was priced as an ordinary hit, which overstates it by 3x against a neutral
        defender -- 2x for a crit it can never take and 1.5x for a STAB it never gets. Not a
        conservative error in the solver's heal threshold: it is a floor above every party
        member's max HP, so the gate can never open.
        """
        self.assertTrue(banked_hit(resolve_move("Future Sight")))
        self.assertFalse(banked_hit(resolve_move("Swift")))
        uxie = _lake("uxie")
        attacker = Attacker(level=50, attack=uxie.stats["atk"],
                            special_attack=uxie.stats["spa"], types=uxie.types)
        defender = Defender(defence=70, special_defence=77, types=("Normal",))
        banked = damage(resolve_move("Future Sight"), attacker, defender, type_chart=False)
        as_an_ordinary_crit = damage(resolve_move("Future Sight"), attacker, defender,
                                     critical=True)
        self.assertGreater(as_an_ordinary_crit, banked * 2)
        self.assertLessEqual(worst_incoming_hit(_ours(), uxie), as_an_ordinary_crit)

    def test_the_warning_does_not_call_a_future_sight_critical(self):
        """The word travels with the move rather than sitting in the template, because it is not
        true of all of them."""
        frail = _ours(name="Chatot", stats={"hp": 40, "atk": 65, "def": 70,
                                            "spa": 40, "spd": 77, "spe": 160})
        warnings = " ".join(survivability_warnings([frail], _lake("uxie")))
        self.assertTrue(warnings)
        if "Future Sight" in warnings:
            self.assertNotIn("critical Future Sight", warnings)

    def test_uxie_is_the_gentlest_target_on_the_list_and_azelf_one_of_the_nastiest(self):
        """Uxie is 75/75/130/75/130/95 and Azelf 75/125/70/125/70/115 -- same species line,
        opposite ends of it. The plan for one is not the plan for the other."""
        ours = _ours()
        self.assertLess(worst_incoming_hit(ours, _lake("uxie")),
                        worst_incoming_hit(ours, _lake("azelf")))


class TestWhatTheReadinessCheckSays(unittest.TestCase):
    """Two planning facts a hit-shaped warning table could not state."""

    def test_uxies_sleep_is_priced_in_turns_rather_than_in_hp(self):
        """The third shape of danger in the table. Uxie has no Nightmare and no Bad Dreams, so a
        sleep costs no HP and the sleep-clock warning correctly says nothing -- but it costs
        TURNS, and Phase 2 runs a precomputed path."""
        warnings = survivability_warnings([_ours(name="Smeargle")], _lake("uxie"))
        joined = " ".join(warnings)
        self.assertIn("to sleep", joined)
        self.assertIn("turns rather than HP", joined)
        self.assertIn("Early Bird", joined)

    def test_the_warning_names_a_carrier_when_the_party_has_one(self):
        """The turn-cost path's half of clayton-4wr.1.3. Darkrai exercises the same
        `_sleep_answer` through the sleep-CLOCK warning, which is a different function -- both
        reach it, so both are pinned.
        """
        honchkrow = Battler(name="Honchkrow", level=55, types=("Dark", "Flying"),
                            ability="Insomnia",
                            stats={"hp": 200, "atk": 150, "def": 90,
                                   "spa": 120, "spd": 95, "spe": 110})
        alone = " ".join(survivability_warnings([_ours()], _lake("uxie")))
        self.assertIn("Insomnia or Vital Spirit refuses it", alone)
        withit = " ".join(survivability_warnings([_ours(), honchkrow], _lake("uxie")))
        self.assertIn("Honchkrow (Insomnia) is immune to it", withit)
        self.assertNotIn("Insomnia or Vital Spirit refuses it", withit)

    def test_it_is_silent_for_a_party_member_that_cannot_be_slept(self):
        for ability in ("Insomnia", "Vital Spirit", "Early Bird"):
            with self.subTest(ability):
                warnings = " ".join(
                    survivability_warnings([_ours(ability=ability)], _lake("uxie")))
                self.assertNotIn("to sleep", warnings)

    def test_can_inflict_had_to_learn_about_yawn_first(self):
        """`status_applied_by` returns None for Yawn -- it inflicts nothing on the turn it is
        used -- so a Uxie answered False to "can this put us to sleep", which is the wrong answer
        to every question that asks it."""
        from claytonlib.battle_compass.sim import can_inflict, status_applied_by

        self.assertIsNone(status_applied_by(resolve_move("Yawn")))
        self.assertTrue(can_inflict(_lake("uxie"), Status.SLEEP))
        self.assertFalse(can_inflict(_lake("azelf"), Status.SLEEP))

    def test_azelfs_uproar_is_reported_as_a_ban_on_sleep(self):
        """Not per party member: it is a fact about the target. A plan that uses sleep as its
        holding status is refused by the game, not merely risky."""
        warnings = " ".join(survivability_warnings([_ours()], _lake("azelf")))
        self.assertIn("forbids sleep", warnings)
        self.assertIn("paralysis is the only holding status", warnings)
        self.assertIn("Soundproof", warnings)

    def test_no_other_target_gets_the_sleep_ban_warning(self):
        for name in ("uxie", "suicune", "darkrai"):
            with self.subTest(name):
                self.assertNotIn("forbids sleep",
                                 " ".join(survivability_warnings([_ours()], _lake_or(name))))

    def test_the_two_sleep_warnings_never_contradict_each_other(self):
        """`_sleep_clock_warning` used not to read OUR ability, so a Noctowl against Darkrai was
        told to "keep it awake or heal every turn" about a state it can never enter -- while the
        turn-cost warning was silent for the same Pokemon for the same reason."""
        noctowl = _ours(name="Noctowl", ability="Insomnia")
        for name in ("uxie", "darkrai"):
            with self.subTest(name):
                warnings = " ".join(survivability_warnings([noctowl], _lake_or(name)))
                self.assertNotIn("Keep it awake", warnings)
                self.assertNotIn("to sleep for up to", warnings)


def _lake_or(name: str) -> Battler:
    """`_lake` for a Lv50 Platinum target, and the right level for the HGSS ones used as foils."""
    levels = {"suicune": 40, "lugia": 45, "darkrai": 50}
    level = levels.get(name, 50)
    moves = moveset(name)
    return Battler(
        name=name, level=level, types=tuple(species(name)["types"]),
        stats=derive_species_stats(name, level, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability(name))


class TestAPendingFutureSightStacksOnTheFloor(unittest.TestCase):
    """clayton-6xu.7.3. The only incoming damage in this simulator that is already decided."""

    def _paralyzed_at_one(self, name: str = "uxie") -> Battler:
        return _lake(name, hp=1, status=Status.PARALYSIS)

    def _solver_state(self, **kwargs) -> BattleState:
        return BattleState(ours=_lean(), target=self._paralyzed_at_one(),
                           rng=0x0C0E02CA, phase=2, **kwargs)

    def _pending(self, turns: int, damage: int = 40) -> BattleState:
        return self._solver_state(future_sight_turns=turns, future_sight_damage=damage,
                                  future_sight_move="Future Sight")

    def test_the_helper_fires_only_on_the_turn_it_lands(self):
        """At 2 or 3 the hit is turns away and the floor is recomputed every turn, so pre-paying
        for it would tighten the heal gate for no reason."""
        for turns, expected in ((0, 0), (1, 40), (2, 0), (3, 0)):
            with self.subTest(turns=turns):
                self.assertEqual(pending_future_sight(self._pending(turns)), expected)

    def test_it_tolerates_a_field_that_is_not_a_state(self):
        """`will_fail` and the floor are both asked about states built by hand and about None."""
        self.assertEqual(pending_future_sight(None), 0)

    def test_the_solver_floor_ADDS_it_rather_than_maxing_it_in(self):
        """The bug. The target still takes its ordinary turn on the turn the Future Sight lands,
        so one turn can cost the worst single hit PLUS the banked figure -- and `max` priced only
        the larger of the two."""
        base = danger_floor_for(self._solver_state(), SolverConfig())
        due = danger_floor_for(self._pending(1), SolverConfig())
        self.assertEqual(due, base + 40)

    def test_a_future_sight_still_in_the_air_does_not_move_the_floor(self):
        config = SolverConfig()
        base = danger_floor_for(self._solver_state(), config)
        for turns in (2, 3):
            with self.subTest(turns=turns):
                self.assertEqual(danger_floor_for(self._pending(turns), config), base)

    def test_an_hp_just_above_the_old_floor_is_now_in_danger(self):
        """The behavioural consequence, which is the whole point: this figure IS the solver's heal
        threshold, so understating it is how a run faints at a number the plan called safe."""
        config = SolverConfig()
        base = danger_floor_for(self._solver_state(), config)
        state = self._pending(1)
        state.ours = replace(state.ours, hp=base + 1)
        self.assertLessEqual(state.ours.hp, danger_floor_for(state, config))
        safe = self._pending(3)
        safe.ours = replace(safe.ours, hp=base + 1)
        self.assertGreater(safe.ours.hp, danger_floor_for(safe, config))

    def test_the_full_figure_is_used_even_though_the_hit_can_miss(self):
        """Its check is a real 90% roll, so this is conservative rather than exact -- and
        conservative is the right direction for a gate that decides whether to heal. Pinned so
        that nobody "fixes" it by scaling by the accuracy."""
        self.assertEqual(pending_future_sight(self._pending(1, damage=97)), 97)

    def test_the_live_indicator_adds_it_too(self):
        """The opposite of how weather is treated. A Rain Dance the target has not used is a
        hypothesis; a banked Future Sight is landing at the end of this turn for a number fixed
        two turns ago, so the live figure must include it."""
        import inspect

        from claytonlib.battle_compass import hunt_session

        source = inspect.getsource(hunt_session.HuntSession.danger_floor.fget)
        self.assertIn("pending_future_sight(state)", source)

    def test_the_weather_half_of_the_live_figure_gets_it_by_delegation(self):
        """`danger_floor_if_weather` is `danger_floor_for`, so it cannot drift from the solver's
        figure -- which is the point of it delegating rather than recomputing."""
        import inspect

        from claytonlib.battle_compass import hunt_session

        source = inspect.getsource(hunt_session.HuntSession.danger_floor_if_weather.fget)
        self.assertIn("danger_floor_for(state, self.solver_config)", source)


def _lean() -> Battler:
    """A real Lv58 Smeargle rather than the bulky probe `_ours` builds.

    The floor tests need a Pokemon the target can genuinely threaten, and 400 HP is not one.
    """
    return Battler(
        name="Smeargle", level=58, types=("Normal",),
        stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
        moves=("False Swipe", "Sing"), pp=(40, 15))


class TestTheEndOfTurnRollsAreAccountedFor(unittest.TestCase):
    """Both of the new conditional rolls, and the ordering they sit in."""

    def test_the_anchor_is_documented_as_derived_rather_than_measured(self):
        """The one derived advance position in the module, and it is owed a gdb capture
        (clayton-6xu.7.1). Asserted so the comment cannot quietly go away."""
        import inspect

        from claytonlib.battle_compass import sim

        source = inspect.getsource(sim)
        self.assertIn("_END_OF_TURN_RESIDUAL_ANCHOR", source)
        self.assertIn("derived rather than measured", source)

    def test_a_turn_with_neither_roll_costs_what_it_always_did(self):
        """The regression that matters most: splitting the end-of-turn block must not change a
        turn where nothing fires."""
        config = _config()
        quiet = _lake("uxie", pp=(20, 0, 0, 0))             # Swift only: no Yawn, no Future Sight
        state = _state(quiet)
        before = state.rng_offset
        state = simulate_turn(state, Action.MOVE_1, config)
        # Selection 1 + before-turn 4 + our False Swipe 3 (crit, damage, accuracy) + post 2
        # + between 2 + their Swift 2 (crit, damage -- effect 17 spends no accuracy roll)
        # + post 2 + end-of-turn 4 = 20.
        self.assertEqual(state.rng_offset - before, 20)

    def test_the_sleep_from_a_drowse_costs_exactly_one_extra_advance(self):
        config = _config()
        yawner = _lake("uxie", pp=(0, 10, 0, 0))
        state = _state(yawner)
        state = simulate_turn(state, Action.MOVE_1, config)   # Yawn lands, drowsy = 1
        before = state.rng_offset
        state = simulate_turn(state, Action.MOVE_1, config)   # the drowse expires into sleep
        self.assertIs(state.ours.status, Status.SLEEP)
        plain = _state(_lake("uxie", pp=(0, 10, 0, 0)), ours=_ours(ability="Insomnia"))
        plain = simulate_turn(plain, Action.MOVE_1, config)
        plain_before = plain.rng_offset
        plain = simulate_turn(plain, Action.MOVE_1, config)
        # Insomnia bails before the `Random 3, 2`, so the cheaper turn is the one that slept.
        self.assertEqual((state.rng_offset - before)
                         - (plain.rng_offset - plain_before), 1)

    def test_a_drowse_onto_an_already_statused_pokemon_spends_no_roll(self):
        """`subscript_fall_asleep` bails before its `Random`, and the counter is consumed
        anyway."""
        config = _config()
        state = _state(_lake("uxie", pp=(20, 0, 0, 0)),
                       ours=_ours(status=Status.PARALYSIS, drowsy_turns=1))
        before = state.rng_offset
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.ours.drowsy_turns, 0)
        self.assertIs(state.ours.status, Status.PARALYSIS)
        # 20 as above, plus the one paralysis check our own side now makes.
        self.assertEqual(state.rng_offset - before, 21)

    def test_the_residuals_run_before_the_future_sight_check(self):
        """`--futureSightTurns[battler] == FALSE && battleMons[battler].curHP`: a burn tick that
        faints us stops the Future Sight firing at all, so no roll is spent and no token is
        emitted. Which is also why a faint turn never carries an F token, whatever caused it.
        """
        config = _config()
        dying = _ours(hp=1, status=Status.BURN)
        state = _state(_lake("uxie", pp=(0, 0, 0, 0)), ours=dying,
                       future_sight_turns=1, future_sight_damage=10,
                       future_sight_move="Future Sight")
        state = simulate_turn(state, Action.MOVE_1, config)
        turn = tok.render_turn(state.log[-1])
        self.assertNotIn("F", turn)
        self.assertIn("X", turn)


class TestItRunsEndToEnd(unittest.TestCase):

    def test_a_sweep_of_uxie_fires_every_move_without_raising(self):
        config = _config()
        seen = set()
        for seed in SEEDS:
            state = _state(_lake("uxie"), seed=seed)
            for _ in range(10):
                state = simulate_turn(state, Action.MOVE_1, config)
                seen.update(p for p in state.log[-1] if p.startswith(("E", "F")))
                if state.over:
                    break
        for slot in ("E1", "E2", "E3", "E4"):
            self.assertTrue(any(p.startswith(slot) for p in seen), slot)
        self.assertTrue(any(p.startswith("F") for p in seen), "no Future Sight landed")

    def test_a_sweep_of_azelf_fires_every_move_without_raising(self):
        config = _config()
        seen = set()
        for seed in SEEDS:
            state = _state(_lake("azelf"), seed=seed)
            for _ in range(10):
                state = simulate_turn(state, Action.MOVE_1, config)
                seen.update(p for p in state.log[-1] if p.startswith(("E", "F")))
                if state.over:
                    break
        for slot in ("E1", "E2", "E3", "E4"):
            self.assertTrue(any(p.startswith(slot) for p in seen), slot)

    def test_every_rendered_turn_is_grammatical(self):
        config = _config()
        for name in ("uxie", "azelf"):
            for seed in SEEDS:
                state = _state(_lake(name), seed=seed)
                for _ in range(10):
                    state = simulate_turn(state, Action.MOVE_1, config)
                    problems = tok.validate_turn(state.log[-1])
                    self.assertEqual(problems, [],
                                     f"{name} {seed:#x}: {tok.render_turn(state.log[-1])}")
                    if state.over:
                        break

    def test_neither_target_separates_rtc_second_siblings_on_its_own(self):
        """**The headline strategy finding, and the opposite of the natural guess.**

        Both have one sub-100 check -- Future Sight's 90 -- and it fires on about one turn in
        four, two turns after it is chosen. Everything else either target rolls is *permanently*
        blind between seeds one RTC second apart, by notes/seed_separation.md's rule that a check
        is blind iff its modulus divides 256: the move choice and the paralysis check are ``% 4``,
        the crit and damage rolls ``% 16``, and -- the one worth saying out loud, because it reads
        like information -- **Uproar's duration roll is ``% 4`` too**, so both siblings roll the
        same length every time.

        So the second axis has to come from our own side: a Sing flips 49.5% of the time and a
        ball's shake check 44.5%, against Future Sight's 17.9%. Asserted as a BOUND rather than an
        exact count, so the test says "this is weak" without pinning a figure that a later
        mechanic fix would move.
        """
        config = _config()
        for name in ("uxie", "azelf"):
            with self.subTest(name):
                separated = 0
                pairs = range(0x0C0E0200, 0x0C0E0240)
                for base in pairs:
                    paths = []
                    for seed in (base, (base + (1 << 24)) & 0xFFFFFFFF):
                        state = _state(_lake(name), seed=seed)
                        for _ in range(10):
                            state = simulate_turn(state, Action.MOVE_1, config)
                            if state.over:
                                break
                        paths.append(tok.render_path(state.log))
                    if paths[0] != paths[1]:
                        separated += 1
                self.assertLess(separated, len(pairs) // 2,
                                f"{name} separated {separated}/{len(pairs)} -- if this target "
                                f"has become a good separator, the advice above is now wrong")

    def test_the_uproar_length_is_identical_between_siblings(self):
        """The specific claim the test above rests on, isolated: ``3 + roll % 4``, and 4 divides
        256, so the difference between two sibling rolls vanishes in the modulus."""
        for base in range(0x0C0E0200, 0x0C0E0210):
            sibling = (base + (1 << 24)) & 0xFFFFFFFF
            lengths = set()
            for seed in (base, sibling):
                _, outcome = execute_move(opening_rng(seed, _config()), resolve_move("Uproar"),
                                          _lake("azelf"), _ours(), actor="E", slot=1)
                lengths.add(outcome.starts_uproar)
            with self.subTest(f"{base:#x}"):
                self.assertEqual(len(lengths), 1, lengths)


if __name__ == "__main__":
    unittest.main()
