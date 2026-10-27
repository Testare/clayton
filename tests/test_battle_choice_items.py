"""Choice Band and Choice Specs: the multiplier, which was modelled as nothing.

All three Choice items were in `readiness.MODELLED_HELD_ITEMS` under "locks the holder into one
move (and the Scarf is x1.5 Speed)". The **lock** was modelled (`state.choice_locked_slot`) and the
Scarf's Speed was (`readiness.speed_after_item`). The Band's and the Specs' multiplier was not,
and because the item was *listed* as modelled, `unmodelled_held_items` did not warn either.

**That is unsound rather than cautious.** It under-predicts the damage WE deal, so the predicted
target HP is wrong from the first hit and every candidate is eliminated with no contradiction
raised — the same failure class as the Scrappy hole (clayton-957.26.3).

**It is a POWER multiplier, not a stat one**, which is the fact worth transcribing rather than
remembering. Gen 4 implements both as `HOLD_EFFECT_POWER_UP_PHYS` / `_SPEC` and the ROM's line is
``movePower = movePower * (100 + heldItemPower) / 100`` keyed on the move's **class**
(battle_lib.c:6776-6783) — the same arithmetic as the type-enhancing items and in the same run of
`movePower` multipliers, after Technician at :6698. "x1.5 Attack" would have put it in the wrong
place and given different numbers wherever the two truncate differently.

Live case: the planned Dialga chipper is a Lv100 max-Atk Gallade with a Choice Band, which cannot
reach 1 HP at all without it (notes/battle_compass_dialga_palkia_shaymin.md §4A, §4E).

(clayton-6xi.7)
"""
import unittest

from claytonlib.battle.damage import (
    CHOICE_ITEM_MODIFIER_PERCENT, CHOICE_POWER_ITEMS, Attacker, Defender, damage,
    effective_power,
)
from claytonlib.battle.readiness import CHOICE_ITEMS, unmodelled_held_items
from claytonlib.moves import CATEGORY_PHYSICAL, CATEGORY_SPECIAL, resolve_move

#: The Dialga chip, as planned: Lv100 Adamant max-Atk/EV Gallade against Dialga's 194 Def at -6
#: from three Screeches.
GALLADE_ATK = 383
DIALGA_HP = 241


def _gallade(**kwargs) -> Attacker:
    return Attacker(level=100, attack=GALLADE_ATK, special_attack=GALLADE_ATK,
                    types=("Psychic", "Fighting"), **kwargs)


def _dialga(def_stage: int = 0) -> Defender:
    return Defender(defence=194, special_defence=166, types=("Steel", "Dragon"),
                    defence_stage=def_stage)


class TestTheMultiplierApplies(unittest.TestCase):

    def test_a_band_raises_a_physical_move_by_half(self):
        """40 -> 60, the ROM's ``40 * (100 + 50) / 100``."""
        false_swipe = resolve_move("False Swipe")
        self.assertEqual(effective_power(false_swipe, _gallade()), 40)
        self.assertEqual(effective_power(false_swipe, _gallade(held_item="Choice Band")), 60)

    def test_specs_raises_a_special_move_by_half(self):
        surf = resolve_move("Surf")
        plain = effective_power(surf, _gallade())
        self.assertEqual(effective_power(surf, _gallade(held_item="Choice Specs")),
                         plain * (100 + CHOICE_ITEM_MODIFIER_PERCENT) // 100)

    def test_it_was_inert_before_and_is_not_now(self):
        """The regression, stated as the bug: the item used to change nothing at all."""
        false_swipe = resolve_move("False Swipe")
        self.assertNotEqual(damage(false_swipe, _gallade(held_item="Choice Band"), _dialga(),
                                   roll=100),
                            damage(false_swipe, _gallade(), _dialga(), roll=100))


class TestItIsKeyedOnTheMoveClass(unittest.TestCase):
    """The difference from `TYPE_ENHANCING_ITEMS`, which is keyed on type."""

    def test_a_band_boosts_every_physical_move_whatever_its_type(self):
        for name in ("False Swipe", "Psycho Cut", "Earthquake", "Aerial Ace"):
            move = resolve_move(name)
            if move.category != CATEGORY_PHYSICAL:
                continue
            with self.subTest(name):
                self.assertGreater(effective_power(move, _gallade(held_item="Choice Band")),
                                   effective_power(move, _gallade()))

    def test_a_band_does_nothing_for_a_special_move(self):
        surf = resolve_move("Surf")
        self.assertEqual(surf.category, CATEGORY_SPECIAL)
        self.assertEqual(effective_power(surf, _gallade(held_item="Choice Band")),
                         effective_power(surf, _gallade()))

    def test_specs_does_nothing_for_a_physical_move(self):
        false_swipe = resolve_move("False Swipe")
        self.assertEqual(effective_power(false_swipe, _gallade(held_item="Choice Specs")), 40)

    def test_neither_touches_a_status_move(self):
        """A status move reaches `effective_power` only through a caller that already refused it,
        but the table must not claim a category it does not have."""
        screech = resolve_move("Screech")
        self.assertNotIn(screech.category, CHOICE_POWER_ITEMS.values())

    def test_the_scarf_is_absent_from_the_power_table(self):
        """It shares the lock and touches Speed, not power -- so it belongs to `CHOICE_ITEMS` and
        `speed_after_item`, and listing it here would boost damage the game does not."""
        self.assertIn("choicescarf", CHOICE_ITEMS)
        self.assertNotIn("choicescarf", CHOICE_POWER_ITEMS)

    def test_all_three_still_share_the_lock(self):
        """The mechanism that was already modelled, asserted so this change cannot be read as
        replacing it."""
        for key in ("choiceband", "choicespecs", "choicescarf"):
            with self.subTest(key):
                self.assertIn(key, CHOICE_ITEMS)


class TestTheOrderIsTheROMs(unittest.TestCase):

    def test_technician_comes_first(self):
        """Technician at battle_lib.c:6698, the Choice item at :6776. 40 -> 60 -> 90, not
        40 -> 60 -> 90 by the other route -- the two agree here and the order is transcribed
        rather than fitted, because they do not agree for every power."""
        false_swipe = resolve_move("False Swipe")
        self.assertEqual(
            effective_power(false_swipe, _gallade(ability="Technician",
                                                  held_item="Choice Band")), 90)

    def test_a_type_item_and_a_choice_item_cannot_both_apply(self):
        """One item slot, so this is theoretical -- and worth pinning anyway, because the tables
        are independent and a future combined item would land between them."""
        false_swipe = resolve_move("False Swipe")
        scarfed = effective_power(false_swipe, _gallade(held_item="Silk Scarf"))
        banded = effective_power(false_swipe, _gallade(held_item="Choice Band"))
        self.assertEqual((scarfed, banded), (48, 60))

    def test_the_arithmetic_is_the_ROMs_percentage_form(self):
        """``power * (100 + 50) / 100`` rather than ``power * 3 / 2``. They agree for most
        figures and the ROM's shape is what truncates correctly for the rest."""
        for power in range(1, 160):
            with self.subTest(power=power):
                move = resolve_move("False Swipe")
                got = effective_power(move, _gallade(held_item="Choice Band"), base=power)
                self.assertEqual(got, power * (100 + CHOICE_ITEM_MODIFIER_PERCENT) // 100)


class TestTheDialgaChip(unittest.TestCase):
    """Why this was worth fixing now rather than filing."""

    def test_three_screeches_and_a_band_take_most_of_dialgas_hp(self):
        false_swipe = resolve_move("False Swipe")
        banded = damage(false_swipe, _gallade(held_item="Choice Band"), _dialga(-6), roll=100)
        plain = damage(false_swipe, _gallade(), _dialga(-6), roll=100)
        # ~56% of 241 HP unmodelled against ~84% with the item: three hits predicted where the
        # game takes two, and a wrong predicted HP after the first.
        self.assertLess(plain / DIALGA_HP, 0.60)
        self.assertGreater(banded / DIALGA_HP, 0.80)

    def test_it_still_cannot_knock_dialga_out(self):
        """The floor has to survive the boost: False Swipe's effect 101 is what makes the chip
        safe, and a 302-damage False Swipe against a 241 HP target would otherwise end the run.
        `execute_move` applies the clamp; this asserts the raw figure really does exceed the HP,
        so the clamp is load-bearing rather than incidental.
        """
        raw = damage(resolve_move("False Swipe"),
                     _gallade(ability="Technician", held_item="Choice Band"),
                     _dialga(-6), roll=100)
        self.assertGreater(raw, DIALGA_HP)


class TestTheWarningStaysQuiet(unittest.TestCase):

    def test_a_choice_item_is_not_reported_as_unmodelled(self):
        """It was not reported before either -- that was the trap, since it was listed as modelled
        while doing nothing. Now the listing is true."""
        self.assertEqual(unmodelled_held_items({"Gallade": "Choice Band"}), [])
        self.assertEqual(unmodelled_held_items({"Gallade": "Choice Specs"}), [])


if __name__ == "__main__":
    unittest.main()
