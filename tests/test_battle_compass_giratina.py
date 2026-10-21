"""Giratina Lv47 (Platinum), met twice, and the two-turn move that comes with it.

**This is the target the encounter-keyed table exists for.** Both fights are Lv47 — the Distortion
World (`StartGiratinaOriginBattle`) and Turnback Cave (`StartLegendaryBattle`) — so the level
cross-check that distinguishes HeartGold's Ho-Oh from SoulSilver's cannot tell them apart at all.
And they differ in more than a moveset: Origin is 120/100/120/100 with **Levitate**, Altered is
100/120/100/120 with **Pressure**, and assuming Pressure where there is none halves every PP
budget the solver plans against.

Shadow Force is the first two-turn move on either side, and it costs three separate things that a
one-turn move does not:

* the **charge turn spends no rolls at all** — its script branches away from CalcCrit/CalcDamage
  and "charge-up moves don't consider accuracy on their first turn";
* the **fire turn spends no selection roll**, because a locked battler never picks a command;
* while it is away, **everything we throw at it misses** — after spending its rolls, because the
  accuracy roll comes first and the invulnerability is layered on afterwards.

A ball is the exception, and it is the fact that matters most: the catch path has no
invulnerability check, so Shadow Force costs us two turns of moves and nothing of the capture.

(clayton-6xu.3.4)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import abilities, derive_species_stats, species
from claytonlib.battle_compass.sim import (
    EFFECT_SHADOW_FORCE, MODELLED_TARGET_EFFECTS, SEMI_INVULNERABLE_EFFECTS, HuntConfig,
    execute_move, is_semi_invulnerable, opening_rng, select_target_move, simulate_turn,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, encounter_level, moveset, resolve, stats_key, supported, target_ability,
    unsupported_moves,
)
from claytonlib.moves import resolve_move

#: Shadow Force's slot in both rows, 0-based. E4 to the player.
FORCE = 3


def _giratina(key="giratina-origin", **kwargs) -> Battler:
    moves = moveset(key)
    row = species(stats_key(key))
    return replace(Battler(
        name=key, level=47, types=tuple(row["types"]),
        stats=derive_species_stats(stats_key(key), 47, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(name).pp for name in moves),
        ability=target_ability(key)), **kwargs)


def _forced(key="giratina-origin", **kwargs) -> Battler:
    """Giratina with only Shadow Force usable, so the selection roll cannot pick anything else."""
    base = _giratina(key, **kwargs)
    return replace(base, pp=(0, 0, 0, base.pp[FORCE]))


def _ours(**kwargs) -> Battler:
    """Smeargle, the planned lead. **Normal-typed, which matters here more than anywhere else.**"""
    return replace(Battler(
        name="Smeargle", level=73, types=("Normal",),
        stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
        moves=("False Swipe", "Flash"), pp=(40, 20)), **kwargs)


def _hittable(**kwargs) -> Battler:
    """A party member Ghost moves can actually touch, for the damage assertions."""
    return replace(_ours(name="Magneton", types=("Electric", "Steel")), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestTheTwoRows(unittest.TestCase):

    def test_both_venues_are_configured_and_both_are_level_47(self):
        self.assertEqual(encounter_level("giratina-origin"), 47)
        self.assertEqual(encounter_level("giratina-altered"), 47)

    def test_the_level_cross_check_cannot_separate_them(self):
        """Which is the whole argument for keying on the encounter. With the roamers a level
        check could at least have caught the mistake; here it cannot."""
        self.assertEqual(ENCOUNTERS["giratina-origin"].level,
                         ENCOUNTERS["giratina-altered"].level)

    def test_the_moveset_is_the_same_in_both(self):
        """The form's own `learnset.by_level` is identical to the species' through 47 -- they
        diverge at Heal Block (50). So the moveset is NOT what distinguishes them."""
        expected = ("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force")
        self.assertEqual(moveset("giratina-origin"), expected)
        self.assertEqual(moveset("giratina-altered"), expected)

    def test_the_ability_differs_and_comes_off_the_row(self):
        self.assertEqual(target_ability("giratina-origin"), "Levitate")
        self.assertEqual(target_ability("giratina-altered"), "Pressure")

    def test_the_species_row_would_have_answered_pressure_for_both(self):
        """The failure the row's `ability` field prevents: `giratina-altered` IS the Giratina row,
        so a species-keyed lookup says Pressure for the Distortion World fight too -- and
        over-budgets every PP figure the solver plans against."""
        self.assertEqual(abilities("giratina-altered"), ("Pressure",))

    def test_the_stats_come_from_the_forme_row(self):
        origin = species(stats_key("giratina-origin"))
        altered = species(stats_key("giratina-altered"))
        self.assertEqual((origin["base_stats"]["atk"], origin["base_stats"]["def"]), (120, 100))
        self.assertEqual((altered["base_stats"]["atk"], altered["base_stats"]["def"]), (100, 120))

    def test_a_bare_giratina_is_refused_and_names_both_venues(self):
        with self.assertRaises(KeyError) as caught:
            resolve("giratina", "platinum")
        message = str(caught.exception)
        self.assertIn("Distortion World", message)
        self.assertIn("Turnback Cave", message)

    def test_both_are_platinum_only(self):
        """Asserted per row rather than by pinning the whole Platinum set, so adding a target
        does not fail a file about Giratina."""
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                self.assertIn(key, supported("platinum"))
                self.assertNotIn(key, supported("heartgold"))
                self.assertNotIn(key, supported("soulsilver"))

    def test_nothing_in_the_set_is_unmodelled(self):
        self.assertEqual(unsupported_moves("giratina-origin"), ((), None))
        self.assertEqual(unsupported_moves("giratina-altered"), ((), None))

    def test_a_forme_encounter_is_keyed_by_its_forme(self):
        """The invariant that lets the player type one name. The species field on a hunt is what
        they typed, and `stats_key` has to land on a real base-stats row -- which it does because
        the encounter key and the forme slug are the same string.
        """
        for key, row in ENCOUNTERS.items():
            if row.forme:
                with self.subTest(key):
                    self.assertEqual(key, row.forme)
                    self.assertEqual(species(row.forme)["name"], row.forme)


class TestTheChargeTurn(unittest.TestCase):

    def test_shadow_force_is_effect_272_and_in_the_modelled_set(self):
        move = resolve_move("Shadow Force")
        self.assertEqual(move.effect, EFFECT_SHADOW_FORCE)
        self.assertIn(move.effect, MODELLED_TARGET_EFFECTS)
        self.assertIn(move.effect, SEMI_INVULNERABLE_EFFECTS)

    def test_it_spends_nothing_and_deals_nothing(self):
        """No CalcCrit, no CalcDamage, and `CheckMoveHitAccuracy` returns before its roll. Zero
        rolls, cross-validated against metronome_compass's `_eff_charge_fire`."""
        rng = 0x1234_5678
        after, outcome = execute_move(rng, resolve_move("Shadow Force"), _giratina(), _ours(),
                                     actor="E", slot=FORCE)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertEqual(outcome.damage, 0)
        self.assertEqual(outcome.starts_charge, FORCE)
        self.assertTrue(outcome.successful)

    def test_the_fire_turn_is_an_ordinary_damaging_move(self):
        """Crit, damage and accuracy: three rolls, because accuracy is only skipped on the FIRST
        turn of a multi-turn move."""
        charging = _giratina(charging_slot=FORCE)
        _, outcome = execute_move(0x1234_5678, resolve_move("Shadow Force"), charging, _hittable(),
                                 actor="E", slot=FORCE)
        self.assertEqual(outcome.rolls, 3)
        self.assertGreater(outcome.damage, 0)
        self.assertTrue(outcome.ends_charge)
        self.assertIsNone(outcome.starts_charge)

    def test_half_its_moveset_cannot_touch_a_normal_party_member(self):
        """Measured while writing this file, and worth stating: Ominous Wind and Shadow Force are
        both **Ghost**, which does nothing at all to a Normal type. So against a Smeargle lead
        Giratina has two live moves, not four -- Ancient Power and Dragon Claw -- and two of its
        four turns are free. The immunity is the type chart's, not an unmodelled ability.
        """
        charging = _giratina(charging_slot=FORCE)
        _, forced = execute_move(0x1234_5678, resolve_move("Shadow Force"), charging, _ours(),
                                actor="E", slot=FORCE)
        self.assertEqual(forced.damage, 0)
        self.assertTrue(forced.successful)           # it connected; it just did nothing
        _, wind = execute_move(0x1234_5678, resolve_move("Ominous Wind"), _giratina(), _ours(),
                              actor="E", slot=0)
        self.assertEqual(wind.damage, 0)

    def test_levitate_is_modelled_rather_than_refused(self):
        """It used to be in `UNMODELLED_DAMAGE_ABILITIES`, which was harmless only because the
        target's Battler carried no ability. Once it did, every Levitate holder -- both Lati twins
        and this one -- was reported as an unmodelled ATTACKER and dealt zero damage: not a
        conservative error but a wrong prediction. In Gen 4 Levitate is a Ground immunity and
        nothing else.
        """
        from claytonlib.battle.damage import (
            UNMODELLED_ATTACKER_ABILITIES, UNMODELLED_DEFENDER_ABILITIES,
            unsupported_attacker_reason, Attacker,
        )
        self.assertNotIn("levitate", UNMODELLED_ATTACKER_ABILITIES)
        self.assertNotIn("levitate", UNMODELLED_DEFENDER_ABILITIES)
        self.assertIsNone(unsupported_attacker_reason(Attacker(
            level=47, attack=100, special_attack=100, types=("Ghost",), ability="Levitate")))

    def test_a_ground_move_against_levitate_is_immune(self):
        from claytonlib.battle.damage import Attacker, Defender, damage

        attacker = Attacker(level=50, attack=200, special_attack=200, types=("Ground",))
        earthquake = resolve_move("Earthquake")
        grounded = Defender(defence=100, special_defence=100, types=("Ghost", "Dragon"))
        floating = Defender(defence=100, special_defence=100, types=("Ghost", "Dragon"),
                            ability="Levitate")
        self.assertGreater(damage(earthquake, attacker, grounded, roll=100), 0)
        self.assertEqual(damage(earthquake, attacker, floating, roll=100), 0)

    def test_a_charging_target_is_semi_invulnerable(self):
        self.assertTrue(is_semi_invulnerable(_giratina(charging_slot=FORCE)))
        self.assertFalse(is_semi_invulnerable(_giratina()))

    def test_a_charge_lock_on_an_ordinary_move_is_not_invulnerability(self):
        """Read off the charging MOVE rather than off a second flag, so the two cannot disagree.
        Dragon Claw is not a vanishing move."""
        self.assertFalse(is_semi_invulnerable(_giratina(charging_slot=2)))


class TestTheSelectionRoll(unittest.TestCase):

    def test_a_locked_target_spends_no_selection_roll(self):
        """`Battler_CanPickCommand` is FALSE for a locked battler and command selection is skipped
        entirely -- one advance fewer on the fire turn. Getting this wrong would desynchronise
        every turn after a Shadow Force."""
        rng = 0x0C0E_02CA
        after, slot = select_target_move(rng, _giratina(charging_slot=FORCE))
        self.assertEqual(after, rng)
        self.assertEqual(slot, FORCE)

    def test_an_unlocked_target_still_spends_one(self):
        rng = 0x0C0E_02CA
        after, slot = select_target_move(rng, _giratina())
        self.assertNotEqual(after, rng)
        self.assertIn(slot, range(4))

    def test_the_locked_slot_wins_even_with_no_pp_left_in_it(self):
        """The ROM relocks into `moveLockedInto` without consulting PP, and PP was already spent
        on the charge turn. A `usable_slots` answer here would both pick the wrong move and spend
        a roll that does not exist."""
        locked = _giratina(charging_slot=FORCE)
        locked = replace(locked, pp=(5, 5, 5, 0))
        rng = 0x0C0E_02CA
        after, slot = select_target_move(rng, locked)
        self.assertEqual((after, slot), (rng, FORCE))


class TestATurnPair(unittest.TestCase):
    """The two turns together, through `simulate_turn`."""

    def _pair(self, action=Action.MOVE_1):
        config = _config()
        state = BattleState(ours=_ours(), target=_forced(),
                            rng=opening_rng(0x0C0E02CA, config))
        charge = simulate_turn(state, action, config)
        fire = simulate_turn(charge, action, config)
        return charge, fire

    def test_the_charge_turn_locks_it_and_the_fire_turn_releases(self):
        charge, fire = self._pair()
        self.assertEqual(charge.target.charging_slot, FORCE)
        self.assertIsNone(fire.target.charging_slot)

    def test_pp_is_spent_once_across_the_two_turns(self):
        """`ppDecremented` is set TRUE for a battler that cannot pick a command, so the fire turn
        is free. Spending it twice would empty a 5-PP move in two uses, shrink `usable_slots`
        early and change the selection modulus."""
        charge, fire = self._pair()
        self.assertEqual(charge.target.pp_left(FORCE), 4)
        self.assertEqual(fire.target.pp_left(FORCE), 4)

    def test_our_move_misses_on_the_turn_it_fires(self):
        """**Not on the charge turn**, and the difference is turn order. Smeargle outspeeds
        Giratina, so on the charge turn our move resolves before it vanishes and lands normally.
        It is the FIRE turn we lose: the vanish is still up when we move, and the flag only comes
        off once the move goes off (`_055`).
        """
        charge, fire = self._pair()
        self.assertNotIn("-", charge.log[-1])
        self.assertIn("-", fire.log[-1])

    def test_our_move_still_spends_its_rolls_against_a_vanished_target(self):
        """`CheckMoveHitAccuracy` spends the accuracy roll and `CheckMoveHitOverrides` layers the
        invulnerability on afterwards [battle_controller_player.c:219-220]. So a move at something
        that is not there costs exactly what an ordinary miss costs -- it is not a free turn, and
        a model that skipped the rolls would desynchronise from the turn it happened on.
        """
        false_swipe = resolve_move("False Swipe")
        rng = 0x0C0E_02CA
        _, landed = execute_move(rng, false_swipe, _ours(), _giratina(),
                                actor="M", slot=0)
        _, missed = execute_move(rng, false_swipe, _ours(), _giratina(charging_slot=FORCE),
                                actor="M", slot=0)
        self.assertEqual(landed.rolls, missed.rolls)
        self.assertTrue(landed.successful)
        self.assertFalse(missed.successful)
        self.assertIn("-", missed.tokens)

    def test_an_accuracy_zero_move_of_ours_cannot_reach_it_either(self):
        """Nothing rolls accuracy for an accuracy-0 move, and it still cannot hit something that
        is not there -- the invulnerability is not an accuracy check."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Faint Attack"), _ours(),
                                 _giratina(charging_slot=FORCE), actor="M", slot=0)
        self.assertFalse(outcome.successful)
        self.assertIn("-", outcome.tokens)

    def test_a_ball_still_works_while_it_is_away(self):
        """The fact that matters most. The catch path has no invulnerability check at all, so
        Shadow Force costs us two turns of MOVES and nothing of the capture."""
        config = _config()
        state = BattleState(ours=_ours(),
                            target=_forced(charging_slot=FORCE, hp=1, status=Status.SLEEP,
                                           sleep_turns=4),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.CAPTURE_BALL, config)
        self.assertEqual(after.balls_thrown, 1)
        self.assertTrue(any(part.startswith("C") or part.startswith("P")
                            for part in after.log[-1]), after.log[-1])

    def test_fainting_clears_the_lock(self):
        """`statusVolatile` goes when a Pokemon leaves the field, and the charge lock with it."""
        self.assertIsNone(_giratina(charging_slot=FORCE).with_hp(0).charging_slot)


class TestItRunsEndToEnd(unittest.TestCase):

    def test_a_sweep_against_both_formes_simulates_without_raising(self):
        config = _config()
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                seen = set()
                for seed in range(0x0C0E0200, 0x0C0E0220):
                    state = BattleState(ours=_ours(), target=_giratina(key),
                                        rng=opening_rng(seed, config))
                    for _ in range(8):
                        state = simulate_turn(state, Action.MOVE_1, config)
                        seen.update(p for p in state.log[-1] if p.startswith("E"))
                        if state.over:
                            break
                for slot in ("E1", "E2", "E3", "E4"):
                    self.assertTrue(any(p.startswith(slot) for p in seen), f"{key}: {slot}")


if __name__ == "__main__":
    unittest.main()
