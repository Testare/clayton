"""Battle Compass state: battlers, actions, and the PP/status rules the simulation leans on."""
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status

SMEARGLE_MOVES = ("False Swipe", "Mean Look", "Sweet Scent", "Spore")


def _smeargle(**overrides) -> Battler:
    stats = {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160}
    fields = dict(name="Smeargle", level=58, types=("Normal",), stats=stats,
                  moves=SMEARGLE_MOVES, pp=(40, 5, 20, 15))
    fields.update(overrides)
    return Battler(**fields)


def _suicune(**overrides) -> Battler:
    fields = dict(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                  stats=derive_species_stats("suicune", 40, "Bold"),
                  moves=("Rain Dance", "Gust", "Aurora Beam", "Mist"), pp=(5, 35, 20, 30))
    fields.update(overrides)
    return Battler(**fields)


class TestAction(unittest.TestCase):
    def test_move_slots_are_zero_based(self):
        self.assertEqual([a.move_slot for a in (Action.MOVE_1, Action.MOVE_2,
                                                Action.MOVE_3, Action.MOVE_4)], [0, 1, 2, 3])

    def test_non_moves_have_no_slot(self):
        for action in (Action.CAPTURE_BALL, Action.ITEM, Action.SWITCH):
            self.assertIsNone(action.move_slot)

    def test_bag_actions_are_classified(self):
        for action in (Action.CAPTURE_BALL, Action.STANDARD_BALL, Action.ITEM,
                       Action.ITEM_CURE, Action.SWITCH):
            self.assertTrue(action.is_bag_action, action)
        for action in (Action.MOVE_1, Action.MOVE_4):
            self.assertFalse(action.is_bag_action, action)


class TestBattler(unittest.TestCase):
    def test_hp_defaults_to_max(self):
        self.assertEqual(_smeargle().hp, 153)

    def test_hp_is_clamped_to_the_range(self):
        mon = _smeargle()
        self.assertEqual(mon.with_hp(-5).hp, 0)
        self.assertEqual(mon.with_hp(9999).hp, mon.max_hp)
        self.assertTrue(mon.with_hp(0).fainted)

    def test_usable_slots_skips_empty_and_exhausted_ones(self):
        self.assertEqual(_smeargle().usable_slots(), (0, 1, 2, 3))
        self.assertEqual(_smeargle().spend_pp(1, 5).usable_slots(), (0, 2, 3))
        self.assertEqual(_smeargle(moves=("False Swipe",), pp=(40,)).usable_slots(), (0,))

    def test_a_moveless_pokemon_has_no_usable_slots(self):
        """Which is what makes the Struggle hazard structural: no slot, no action (sec 12.5)."""
        self.assertEqual(_smeargle(moves=(), pp=()).usable_slots(), ())

    def test_pressure_doubles_our_consumption(self):
        mon = _smeargle()
        self.assertEqual(mon.spend_pp(0, 2).pp_left(0), 38)
        self.assertEqual(mon.spend_pp(0, 1).pp_left(0), 39)

    def test_pp_never_goes_negative(self):
        self.assertEqual(_smeargle().spend_pp(1, 99).pp_left(1), 0)

    def test_an_unknown_move_name_resolves_to_none(self):
        self.assertIsNone(_smeargle(moves=("Nonexistent Move",)).move(0))

    def test_out_of_range_slots_are_none(self):
        mon = _smeargle()
        self.assertIsNone(mon.move(-1))
        self.assertIsNone(mon.move(9))
        self.assertEqual(mon.pp_left(9), 0)

    def test_statuses_are_mutually_exclusive(self):
        """Why paralysis and sleep are a choice, not a combination (sec 4.2)."""
        mon = _smeargle().with_status(Status.PARALYSIS)
        self.assertEqual(mon.with_status(Status.SLEEP).status, Status.PARALYSIS)

    def test_a_battler_is_immutable_so_candidates_cannot_alias(self):
        mon = _smeargle()
        self.assertIsNot(mon.spend_pp(0), mon)
        self.assertEqual(mon.pp_left(0), 40)


class TestBattleState(unittest.TestCase):
    def test_copy_does_not_share_the_log(self):
        state = BattleState(ours=_smeargle(), target=_suicune(), rng=1)
        other = state.copy()
        other.log.append(("M1",))
        self.assertEqual(state.log, [])

    def test_over_on_capture_or_faint(self):
        state = BattleState(ours=_smeargle(), target=_suicune(), rng=1)
        self.assertFalse(state.over)
        state.captured = True
        self.assertTrue(state.over)

    def test_a_wrong_ball_capture_also_ends_the_battle(self):
        """It ends it as a loss, not a win (sec 2.3)."""
        state = BattleState(ours=_smeargle(), target=_suicune(), rng=1)
        state.captured_in_wrong_ball = True
        self.assertTrue(state.over)
        self.assertFalse(state.captured)

    def test_a_fainted_target_ends_the_battle(self):
        state = BattleState(ours=_smeargle(), target=_suicune(hp=1), rng=1)
        state.target = state.target.with_hp(0)
        self.assertTrue(state.over)


if __name__ == "__main__":
    unittest.main()
