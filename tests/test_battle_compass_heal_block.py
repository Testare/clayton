"""Heal Block — modelled for what it COSTS, not for what it stops.

Dialga's and Palkia's slot 2, and the surprise is how little it does. `Move_HealBlocked`
(battle_lib.c:3427-3440) tests a hardcoded list of **fourteen moves** plus the Ingrain and Aqua
Ring residuals. It does **not** block items and does **not** block Leftovers — verified by
exhaustion: `healBlockTurns` is read at exactly those sites plus its own countdown and nowhere
else. So Hyper Potions, Full Restores and Revives work straight through it, and the solver's
healing plan is untouched.

What it still has to be modelled for is cost: a 100-accuracy roll, a five-turn counter, and a
**second one failing** — two advances cheaper than a successful move, which is the trap Rain Dance
set on turn 3 of test1.jsonl.

(clayton-6xu.9.8)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.readiness import MODELLED_HELD_ITEMS
from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.hunt_session import field_conditions
from claytonlib.battle_compass.sim import (
    EFFECT_HEAL_BLOCK, HEAL_BLOCK_TURNS, HEAL_BLOCKED_MOVES, MODELLED_OUR_EFFECTS,
    MODELLED_TARGET_EFFECTS, HuntConfig, execute_move, opening_rng, simulate_turn,
    unselectable_reason, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.moves import resolve_move

BLOCK = 0


def _dialga(**kwargs) -> Battler:
    """Heal Block in slot 0 and nothing else usable, so the selection roll cannot pick away."""
    return replace(Battler(
        name="Dialga", level=70, types=("Steel", "Dragon"),
        stats=derive_species_stats("dialga", 70, "Timid", ivs=31),
        moves=("Heal Block", "Slash"), pp=(15, 0), ability="Pressure"), **kwargs)


def _wall(**kwargs) -> Battler:
    """A Flying wall, which is the shape Dialga's damage actually calls for — immune to Earth
    Power and neutral to Roar of Time. Fat enough that nothing here ends the battle."""
    return replace(Battler(
        name="Wall", level=100, types=("Flying",),
        stats={"hp": 400, "atk": 100, "def": 150, "spa": 100, "spd": 150, "spe": 200},
        moves=("Sweet Scent",), pp=(20,)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=30, target_has_pressure=True)


class TestTheMoveData(unittest.TestCase):
    def test_it_is_effect_236_and_modelled_target_side(self):
        self.assertEqual(resolve_move("Heal Block").effect, EFFECT_HEAL_BLOCK)
        self.assertIn(EFFECT_HEAL_BLOCK, MODELLED_TARGET_EFFECTS)

    def test_it_is_NOT_modelled_on_our_side(self):
        """Nothing a party can carry has it, and the mirror in `act_ours` is wired for symmetry
        rather than for use — so the move must still be refused at the point of use."""
        self.assertNotIn(EFFECT_HEAL_BLOCK, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Heal Block")))

    def test_it_spends_an_accuracy_roll(self):
        """100 accuracy, so the roll is spent even though at a neutral stage it cannot fail."""
        rng = 0x0C0E_02CA
        after, outcome = execute_move(rng, resolve_move("Heal Block"), _dialga(), _wall(),
                                      actor="E", slot=BLOCK)
        self.assertEqual(outcome.rolls, 1)
        self.assertNotEqual(after, rng)
        self.assertTrue(outcome.sets_heal_block)


class TestTheCounter(unittest.TestCase):
    def test_it_lands_on_us_and_counts_down(self):
        config = _config()
        state = BattleState(ours=_wall(), target=_dialga(),
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_1, config)
        # Five turns, counted inclusive of the turn it lands -- Safeguard's and Taunt's rule.
        self.assertEqual(state.ours.heal_block_turns, HEAL_BLOCK_TURNS - 1)
        self.assertEqual(state.target.heal_block_turns, 0)
        for expected in (3, 2, 1, 0):
            state = simulate_turn(state, Action.MOVE_1, config)
            self.assertEqual(state.ours.heal_block_turns, expected)

    def test_a_second_one_fails_while_it_is_up(self):
        """The half that costs advances. Keyed on the DEFENDER, because the ROM keeps
        `healBlockTurns` in the victim's own `moveEffectsData` rather than as a side condition."""
        move = resolve_move("Heal Block")
        self.assertFalse(will_fail(move, _wall()))
        self.assertTrue(will_fail(move, _wall(heal_block_turns=3)))

    def test_a_failing_one_still_spends_the_accuracy_roll(self):
        """Every failure in `will_fail` costs the accuracy roll and then stops, which is what
        makes the two post-successful-move advances the whole of the difference."""
        rng = 0x0C0E_02CA
        _, blocked = execute_move(rng, resolve_move("Heal Block"), _dialga(),
                                  _wall(heal_block_turns=3), actor="E", slot=BLOCK)
        _, landed = execute_move(rng, resolve_move("Heal Block"), _dialga(), _wall(),
                                 actor="E", slot=BLOCK)
        self.assertEqual(blocked.rolls, landed.rolls)
        self.assertFalse(blocked.successful)
        self.assertTrue(landed.successful)

    def test_fainting_clears_it(self):
        """`healBlockTurns` lives in `moveEffectsData`, which a departing Pokemon's cleanup
        zeroes wholesale."""
        self.assertEqual(_wall(heal_block_turns=4).with_hp(0).heal_block_turns, 0)


class TestWhatItDoesNotBlock(unittest.TestCase):
    """The reason this is a cost model and not an obstacle."""

    def test_the_move_list_is_the_ROMs_fourteen(self):
        self.assertEqual(len(HEAL_BLOCKED_MOVES), 14)
        for name in ("rest", "roost", "recover", "synthesis", "wish"):
            with self.subTest(name):
                self.assertIn(name, HEAL_BLOCKED_MOVES)

    def test_leftovers_is_not_in_it(self):
        """Verified by exhaustion in the ROM: the residual heals are gated for Ingrain and Aqua
        Ring only. A Leftovers wall keeps ticking through a Heal Block."""
        self.assertNotIn("leftovers", HEAL_BLOCKED_MOVES)
        self.assertIn("leftovers", set().union(*MODELLED_HELD_ITEMS.values()))

    def test_no_item_is_in_it(self):
        """The list is moves, so nothing in the bag can appear in it -- which is the statement
        that keeps the solver's healing plan intact."""
        from claytonlib.battle_compass.items import BY_CODE
        for entry in BY_CODE.values():
            with self.subTest(entry.name):
                self.assertNotIn(entry.name.strip().lower(), HEAL_BLOCKED_MOVES)


class TestTheBanner(unittest.TestCase):
    def test_it_shows_up_once_it_lands(self):
        config = _config()
        state = BattleState(ours=_wall(), target=_dialga(),
                            rng=opening_rng(0x0C0E02CA, config))
        self.assertNotIn("Heal Block", [r["name"] for r in field_conditions(state)])
        after = simulate_turn(state, Action.MOVE_1, config)
        rows = [r for r in field_conditions(after) if r["name"] == "Heal Block"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["whose"], "ours")


if __name__ == "__main__":
    unittest.main()
