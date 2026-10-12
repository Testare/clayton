"""Speed-modifying held items, and the Choice lock that comes with one of them.

`effective_speed` read `stats["spe"]` and nothing else, so a Choice Scarf was invisible -- and the
summary screen does not show its boost either, so it has to be MODELLED rather than entered. The
consequence is not a slightly-wrong number: a scarfed Lv70 Magneton is 186 against Ho-Oh Lv70's
152, so the model had us moving SECOND on the one turn the whole plan hangs on. Turn order decides
whose rolls come first, so that is a different RNG stream from turn one onward.

Order transcribed from the speed comparison in src/battle/overlay_12_0224E4FC.c: stat stages,
weather abilities, the halving items, the Choice Scarf's `* 15 / 10`, Quick Powder, and only THEN
paralysis's `/ 4`.
"""
import unittest

from claytonlib.battle.readiness import (
    CHOICE_ITEMS, CHOICE_SPEED_ITEMS, MOVES_LAST_ITEMS, PARALYSIS_SPEED_DIVISOR,
    SPEED_HALVING_ITEMS,
)
from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.sim import HuntConfig, effective_speed, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status

HUNT = HuntConfig(target_catch_rate=3)


def _mon(speed, *, item="", status=Status.NONE, moves=("Thunder Wave",), pp=(20,),
         locked=None, slot=1, name="Magneton"):
    return Battler(name=name, level=70, types=("Electric", "Steel"),
                   stats={"hp": 200, "atk": 80, "def": 80, "spa": 80, "spd": 80, "spe": speed},
                   moves=moves, pp=pp, held_item=item, status=status, party_slot=slot,
                   choice_locked_slot=locked)


class TestTheScarfIsVisibleAtAll(unittest.TestCase):
    def test_it_multiplies_speed_by_one_and_a_half(self):
        self.assertEqual(effective_speed(_mon(124, item="Choice Scarf")), 186)

    def test_the_case_of_the_item_name_does_not_matter(self):
        """It is typed by hand into a free-text field."""
        self.assertEqual(effective_speed(_mon(124, item="  CHOICE SCARF ")), 186)

    def test_no_item_leaves_it_alone(self):
        self.assertEqual(effective_speed(_mon(124)), 124)

    def test_an_unrelated_item_leaves_it_alone(self):
        self.assertEqual(effective_speed(_mon(124, item="Silk Scarf")), 124)

    def test_this_is_the_turn_the_ho_oh_plan_hangs_on(self):
        """The reported reason it matters. Ho-Oh Lv70 with 31 IVs and a neutral nature is 152,
        and the Thunder Wave turn is the one race that cannot be won by paralysis -- because
        paralysis is what we are trying to apply."""
        hooh = derive_species_stats("ho-oh", 70, "Hardy")["spe"]
        magneton = derive_species_stats("magneton", 70, "Hardy")["spe"]
        self.assertEqual(hooh, 152)
        self.assertLess(effective_speed(_mon(magneton)), hooh, "bare Magneton is slower")
        self.assertGreater(effective_speed(_mon(magneton, item="Choice Scarf")), hooh,
                           "scarfed Magneton must outspeed, or the model has turn order backwards")

    def test_strictly_greater_is_the_bar(self):
        """A tie is not neutral -- it spends an extra roll, which is the unpredictability the
        paralysis precondition exists to remove."""
        self.assertEqual(effective_speed(_mon(101, item="Choice Scarf")), 151)
        self.assertEqual(effective_speed(_mon(102, item="Choice Scarf")), 153)


class TestTheOrderOfOperations(unittest.TestCase):
    def test_the_halving_items_halve(self):
        for item in ("Macho Brace", "Iron Ball", "Power Anklet"):
            self.assertEqual(effective_speed(_mon(124, item=item)), 62, item)

    def test_paralysis_quarters_after_the_item_not_before(self):
        """Each step truncates, so the two orders are different numbers. 14 is a value where they
        disagree: 14*15/10 = 21, /4 = 5; whereas 14/4 = 3, *15/10 = 4."""
        scarf_then_quarter = 14 * 15 // 10 // PARALYSIS_SPEED_DIVISOR
        quarter_then_scarf = 14 // PARALYSIS_SPEED_DIVISOR * 15 // 10
        self.assertNotEqual(scarf_then_quarter, quarter_then_scarf)
        self.assertEqual(
            effective_speed(_mon(14, item="Choice Scarf", status=Status.PARALYSIS)),
            scarf_then_quarter)

    def test_paralysis_alone_still_quarters(self):
        self.assertEqual(effective_speed(_mon(124, status=Status.PARALYSIS)), 31)

    def test_lagging_tail_is_not_a_speed_item(self):
        """It sets a lowered-priority flag, so the holder moves last within its bracket. Reading
        it as a Speed modifier would be wrong in both directions -- and it would be actively
        harmful here, since Battle Compass wants to move FIRST."""
        self.assertEqual(effective_speed(_mon(124, item="Lagging Tail")), 124)
        for item in MOVES_LAST_ITEMS:
            self.assertNotIn(item, SPEED_HALVING_ITEMS)
            self.assertNotIn(item, CHOICE_SPEED_ITEMS)


class TestTheChoiceLock(unittest.TestCase):
    """All three Choice items lock; only the Scarf is a Speed modifier, which is why they are two
    sets rather than one."""

    def test_every_choice_item_locks(self):
        self.assertEqual(CHOICE_ITEMS,
                         {"choice scarf", "choice band", "choice specs"})
        self.assertTrue(CHOICE_SPEED_ITEMS < CHOICE_ITEMS)

    def test_only_the_scarf_changes_speed(self):
        self.assertEqual(effective_speed(_mon(124, item="Choice Band")), 124)
        self.assertEqual(effective_speed(_mon(124, item="Choice Specs")), 124)

    def test_an_unlocked_holder_may_use_anything(self):
        mon = _mon(124, item="Choice Scarf", moves=("Thunder Wave", "Tackle"), pp=(20, 35))
        self.assertEqual(mon.usable_slots(), (0, 1))
        self.assertTrue(mon.holds_choice_item)

    def test_a_locked_holder_may_use_only_the_locked_slot(self):
        mon = _mon(124, item="Choice Scarf", moves=("Thunder Wave", "Tackle"), pp=(20, 35),
                   locked=0)
        self.assertEqual(mon.usable_slots(), (0,))

    def test_a_locked_slot_out_of_pp_leaves_nothing(self):
        """Which is Struggle territory, and the solver already refuses to search that far."""
        mon = _mon(124, item="Choice Scarf", moves=("Thunder Wave", "Tackle"), pp=(0, 35),
                   locked=0)
        self.assertEqual(mon.usable_slots(), ())

    def test_using_a_move_sets_the_lock(self):
        state = BattleState(
            ours=_mon(300, item="Choice Scarf", moves=("Thunder Wave", "Tackle"), pp=(20, 35)),
            target=_mon(20, moves=("Mist",), pp=(30,), name="Target"), rng=0x1234, phase=1)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        self.assertEqual(nxt.ours.choice_locked_slot, 0)
        self.assertEqual(nxt.ours.usable_slots(), (0,))

    def test_without_a_choice_item_nothing_locks(self):
        state = BattleState(
            ours=_mon(300, moves=("Thunder Wave", "Tackle"), pp=(20, 35)),
            target=_mon(20, moves=("Mist",), pp=(30,), name="Target"), rng=0x1234, phase=1)
        self.assertIsNone(simulate_turn(state, Action.MOVE_1, HUNT).ours.choice_locked_slot)

    def test_switching_out_ends_the_lock(self):
        """Leaving the field is the only thing that ends it, so the Pokemon can come back with
        all four moves."""
        bench = (_mon(70, moves=("False Swipe",), pp=(40,), slot=2, name="Smeargle"),)
        state = BattleState(
            ours=_mon(300, item="Choice Scarf", moves=("Thunder Wave", "Tackle"), pp=(20, 35),
                      locked=0),
            target=_mon(20, moves=("Mist",), pp=(30,), name="Target"),
            rng=0x1234, bench=bench, phase=1)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        came_off = [b for b in nxt.bench if b.name == "Magneton"][0]
        self.assertIsNone(came_off.choice_locked_slot)
        self.assertEqual(came_off.usable_slots(), (0, 1))

    def test_fainting_ends_it_too(self):
        """A replacement switch-in is still leaving the field."""
        bench = (_mon(70, moves=("False Swipe",), pp=(40,), slot=2, name="Smeargle"),)
        ours = _mon(20, item="Choice Scarf", moves=("Thunder Wave", "Tackle"), pp=(20, 35),
                    locked=0)
        ours = ours.with_hp(1)
        target = Battler(name="Lugia", level=70, types=("Psychic", "Flying"),
                         stats={"hp": 1, "atk": 130, "def": 130, "spa": 200, "spd": 154,
                                "spe": 200},
                         moves=("Hydro Pump",), pp=(5,), hp=1)
        state = BattleState(ours=ours, target=target, rng=0x12345678, bench=bench, phase=2)
        nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=2)
        downed = [b for b in nxt.bench if b.name == "Magneton"][0]
        self.assertTrue(downed.fainted)
        self.assertIsNone(downed.choice_locked_slot)

    def test_the_solver_will_not_plan_past_the_lock(self):
        from claytonlib.battle_compass.solver import SolverConfig, _legal_actions

        # Locked into Flash, not Tackle. The lock is what this test is about, but the target is
        # at 1 HP -- the Phase 2 precondition -- and `can_faint_target` now (correctly) refuses
        # every damaging move there, so a Tackle lock would be filtered for the OTHER reason and
        # the assertion would pass without proving anything about the lock.
        state = BattleState(
            ours=_mon(300, item="Choice Scarf", moves=("Thunder Wave", "Tackle", "Flash"),
                      pp=(20, 35, 20), locked=2),
            target=_mon(20, moves=("Mist",), pp=(30,), name="Target", status=Status.PARALYSIS),
            rng=0x1234, phase=2)
        state.target = state.target.with_hp(1)
        moves = {a for a, _, _ in _legal_actions(state, SolverConfig(), HUNT)
                 if a.move_slot is not None}
        self.assertEqual(moves, {Action.MOVE_3}, "the solver offered a move the game would refuse")


if __name__ == "__main__":
    unittest.main()
