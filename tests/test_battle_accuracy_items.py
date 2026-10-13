"""Brightpowder and friends: a multiplier on the hit chance, applied after the stage table.

Transcribed from `BattleSystem_CheckMoveHit` (src/battle/battle_controller_player.c:2520-2531).
Two things make this worth its own module:

* **It is not an evasion stage.** It does not enter `var`, so Simple does not double it and
  Unaware does not zero it. Reading it as a stage would be wrong in both directions.
* **The order is load-bearing and the obvious example does not show it.** A 100-accuracy move
  under six Flashes is 29 whichever way round you apply the item, so an eyeball check passes a
  wrong implementation. The real divergence is 467 of the 1300 (accuracy, stage) pairs.

clayton-957.28.
"""
import unittest

from claytonlib.battle.damage import (
    item_key,
    ACCURACY_RAISING_ITEMS, ACCURACY_REDUCING_ITEMS, apply_accuracy_items, apply_accuracy_stage,
)
from claytonlib.battle_compass.sim import _effective_accuracy, can_miss
from claytonlib.battle_compass.state import Battler
from claytonlib.moves import resolve_move


def _mon(item=""):
    return Battler(name="x", level=50, types=("Normal",), stats={}, held_item=item)


class TestTheTable(unittest.TestCase):
    def test_both_accuracy_reducing_items_are_ten_percent(self):
        self.assertEqual(ACCURACY_REDUCING_ITEMS,
                         {item_key("BrightPowder"): 10, item_key("Lax Incense"): 10})

    def test_wide_lens_raises_and_zoom_lens_is_deliberately_absent(self):
        """Zoom Lens is conditional on moving second, so it is state-dependent rather than a flat
        modifier -- and the decomp's own TODO notes its hold-effect constant is mislabeled."""
        self.assertEqual(ACCURACY_RAISING_ITEMS, {item_key("Wide Lens"): 10})

    def test_an_unknown_or_absent_item_is_no_modifier(self):
        for item in ("", "   ", "Leftovers", "Silk Scarf", "Choice Scarf"):
            with self.subTest(item=item):
                self.assertEqual(apply_accuracy_items(80, defender_item=item), 80)
                self.assertEqual(apply_accuracy_items(80, attacker_item=item), 80)

    def test_case_and_whitespace_do_not_matter(self):
        for spelling in ("brightpowder", "BrightPowder", "  BRIGHTPOWDER  "):
            with self.subTest(spelling):
                self.assertEqual(apply_accuracy_items(100, defender_item=spelling), 90)


class TestTheOrderIsTheRomsOrder(unittest.TestCase):
    def test_the_obvious_example_does_NOT_diverge(self):
        """Stated as a test so nobody "verifies" the ordering against it and concludes wrongly."""
        stage_first = apply_accuracy_items(apply_accuracy_stage(100, -6),
                                           defender_item="brightpowder")
        item_first = apply_accuracy_stage(100 * 90 // 100, -6)
        self.assertEqual((stage_first, item_first), (29, 29))

    def test_but_it_diverges_on_moves_this_project_rolls(self):
        for name, net, rom, item_first in (("Aeroblast", -6, 27, 28),
                                           ("Screech", -1, 56, 57),
                                           ("Sing", -4, 20, 21)):
            base = resolve_move(name).accuracy
            with self.subTest(name=name, net=net):
                self.assertEqual(
                    apply_accuracy_items(apply_accuracy_stage(base, net),
                                         defender_item="brightpowder"), rom)
                self.assertEqual(apply_accuracy_stage(base * 90 // 100, net), item_first)

    def test_the_divergence_is_widespread_rather_than_a_corner(self):
        """467 of 1300 pairs. Pinned so that a refactor which "simplifies" the order has to
        confront the number rather than a hand-wave."""
        differing = sum(
            1
            for base in range(1, 101)
            for net in range(-6, 7)
            if apply_accuracy_items(apply_accuracy_stage(base, net),
                                    defender_item="brightpowder")
            != apply_accuracy_stage(base * 90 // 100, net))
        self.assertEqual(differing, 467)

    def test_the_defenders_reduction_comes_before_the_attackers_boost(self):
        """Base 41 rather than a round number on purpose: at 95 the two orders agree (93 either
        way), so a test written against the obvious figure proves nothing. 42 of the bases 1..120
        diverge."""
        both = apply_accuracy_items(41, defender_item="brightpowder", attacker_item="wide lens")
        reduce_first = (41 * 90 // 100) * 110 // 100
        raise_first = (41 * 110 // 100) * 90 // 100
        self.assertEqual((reduce_first, raise_first), (39, 40), "the two orders must differ here")
        self.assertEqual(both, reduce_first)


class TestItReachesTheSimulator(unittest.TestCase):
    def test_a_defenders_brightpowder_cuts_our_accuracy(self):
        hydro = resolve_move("Hydro Pump")
        self.assertEqual(_effective_accuracy(hydro, 0, defender=_mon("Brightpowder")), 72)
        self.assertEqual(_effective_accuracy(hydro, 0, defender=_mon()), 80)

    def test_an_attackers_wide_lens_raises_it(self):
        screech = resolve_move("Screech")
        self.assertEqual(_effective_accuracy(screech, 0, attacker=_mon("Wide Lens")), 93)

    def test_an_accuracy_zero_move_still_bypasses_the_check_entirely(self):
        """0 is the always-hit sentinel: it must not be multiplied into something missable."""
        for name in ("Rain Dance", "Mean Look"):
            with self.subTest(name):
                self.assertEqual(
                    _effective_accuracy(resolve_move(name), 0, defender=_mon("Brightpowder")), 0)

    def test_a_hundred_accuracy_move_becomes_MISSABLE(self):
        """The consequence that matters for the interview. Spore cannot miss at a neutral stage,
        and against a Brightpowder holder it can -- so an interview that did not know about the
        item would refuse to let the player report a miss that really happened."""
        spore = resolve_move("Spore")
        self.assertFalse(can_miss(spore, 0, defender=_mon()))
        self.assertTrue(can_miss(spore, 0, defender=_mon("Brightpowder")))

    def test_both_battlers_are_optional(self):
        """`can_miss` has callers that know neither, and a missing item is simply no modifier."""
        hydro = resolve_move("Hydro Pump")
        self.assertEqual(_effective_accuracy(hydro, 0), 80)
        self.assertEqual(_effective_accuracy(hydro, -2), apply_accuracy_stage(80, -2))


class TestTheInterviewSeesIt(unittest.TestCase):
    def test_move_info_reports_the_reduced_accuracy_and_the_miss_option(self):
        from claytonlib.battle_compass.hunt_session import move_info

        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66,
                              "spa": 45, "spd": 79, "spe": 160},
                       moves=("False Swipe", "Spore", "", ""), pp=(40, 15, 0, 0))
        target = Battler(name="Lugia", level=45, types=("Psychic", "Flying"),
                         stats={"hp": 164, "atk": 99, "def": 135,
                                "spa": 93, "spd": 157, "spe": 117},
                         held_item="Brightpowder")
        by_name = {m["name"]: m for m in move_info(ours, target)}
        self.assertEqual(by_name["Spore"]["effective_accuracy"], 90)
        self.assertTrue(by_name["Spore"]["can_miss"])


if __name__ == "__main__":
    unittest.main()
