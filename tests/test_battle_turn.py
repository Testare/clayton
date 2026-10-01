"""The per-turn RNG cost skeleton, confirmed on the emulator.

Corroborated against the counts metronome_compass verified for the Blackthorn matchup — if those
two ever disagree, one of them is wrong and the simulator would desynchronise.
"""
import unittest

from claytonlib.battle.turn import (
    BAG_ACTION_ADVANCES, BEFORE_TURN_ADVANCES, BETWEEN_TURN_ADVANCES,
    END_OF_TURN_ADVANCES, POST_SUCCESSFUL_MOVE_ADVANCES,
    ActionCost, ball_turn_cost, max_turn_advances, shake_roll_offset, turn_cost,
)


class TestConstantsAgreeWithMetronomeCompass(unittest.TestCase):
    """metronome_compass's values are gdb-verified for Blackthorn; these are the emulator-
    confirmed general ones. They must match, or one measurement is wrong."""

    def test_counts_match(self):
        from claytonlib.metronome_compass import (
            _BEFORE_TURN_ADVANCES, _END_OF_TURN_ADVANCES,
            _MAGIKARP_TURN_START_ADVANCES, _POST_MAGIKARP_SUCCESS_ADVANCES,
            _POST_METRONOME_SUCCESS_ADVANCES,
        )
        self.assertEqual(BEFORE_TURN_ADVANCES, _BEFORE_TURN_ADVANCES)
        self.assertEqual(END_OF_TURN_ADVANCES, _END_OF_TURN_ADVANCES)
        self.assertEqual(BETWEEN_TURN_ADVANCES, _MAGIKARP_TURN_START_ADVANCES)
        self.assertEqual(POST_SUCCESSFUL_MOVE_ADVANCES, _POST_METRONOME_SUCCESS_ADVANCES)
        self.assertEqual(POST_SUCCESSFUL_MOVE_ADVANCES, _POST_MAGIKARP_SUCCESS_ADVANCES)


class TestActionCost(unittest.TestCase):
    def test_a_bag_action_costs_nothing(self):
        self.assertEqual(BAG_ACTION_ADVANCES, 0)
        self.assertEqual(ActionCost(rolls=BAG_ACTION_ADVANCES).total, 0)

    def test_a_successful_move_adds_the_post_success_advances(self):
        self.assertEqual(ActionCost(rolls=3, successful_move=True).total, 5)

    def test_a_failed_or_missed_move_does_not(self):
        self.assertEqual(ActionCost(rolls=3, successful_move=False).total, 3)


class TestTurnCost(unittest.TestCase):
    FIXED = BEFORE_TURN_ADVANCES + BETWEEN_TURN_ADVANCES + END_OF_TURN_ADVANCES  # 10

    def test_the_fixed_advances_are_spent_even_when_nobody_acts(self):
        self.assertEqual(turn_cost(ActionCost(rolls=0)), self.FIXED)

    def test_both_actors_contribute(self):
        self.assertEqual(turn_cost(ActionCost(3, True), ActionCost(4, True)),
                         self.FIXED + 5 + 6)

    def test_a_missing_second_actor_still_pays_the_fixed_advances(self):
        """A fully-paralyzed opponent does not act, but the turn still costs its overhead."""
        self.assertEqual(turn_cost(ActionCost(1, True), None), self.FIXED + 3)

    def test_an_item_turn_is_the_cheapest_action_available(self):
        opponent = ActionCost(4, True)
        item = turn_cost(ActionCost(BAG_ACTION_ADVANCES), opponent)
        move = turn_cost(ActionCost(3, True), opponent)
        self.assertLess(item, move)


class TestBallTurns(unittest.TestCase):
    def test_cost_rises_with_shake_count_then_plateaus_on_a_capture(self):
        opponent = ActionCost(4, True)
        costs = [ball_turn_cost(n, opponent) for n in range(5)]
        self.assertEqual(costs, [17, 18, 19, 20, 20])

    def test_a_ball_is_a_variable_cost_action(self):
        """Which is what makes it useful filler for steering the RNG (sec 12.5)."""
        self.assertGreater(len({ball_turn_cost(n) for n in range(5)}), 1)

    def test_a_capturing_ball_consumes_all_four_shake_rolls(self):
        from claytonlib.battle.catch import rolls_consumed
        self.assertEqual(rolls_consumed(4), 4)
        self.assertEqual(ball_turn_cost(4), ball_turn_cost(3))

    def test_shake_rolls_start_just_past_the_before_turn_advances(self):
        """Not at a ball-specific offset -- the 4 is what every turn pays (sec 6.1)."""
        self.assertEqual(shake_roll_offset(0, target_can_act=False), BEFORE_TURN_ADVANCES)
        self.assertEqual(shake_roll_offset(100, target_can_act=False), 104)

    def test_the_selection_roll_shifts_the_shake_offset_when_the_target_can_act(self):
        """Section 6.1's goal set of {window_start - 4} is short by the wild mon's move-selection
        roll, which for a full-PP target is spent every turn. The offset is state-dependent,
        which is why the solver prunes on windows but lets the simulator settle each throw."""
        self.assertEqual(shake_roll_offset(0, target_can_act=True), BEFORE_TURN_ADVANCES + 1)
        self.assertEqual(shake_roll_offset(100, target_can_act=True), 105)

    def test_target_can_act_has_no_default(self):
        """A default would let the wrong offset back in silently."""
        with self.assertRaises(TypeError):
            shake_roll_offset(0)


class TestTurnUpperBound(unittest.TestCase):
    """The solver sizes its capture-window horizon with this, and treats an empty horizon as a
    proof of unreachability -- so the bound must really bound."""

    def test_the_bound_is_the_sum_of_the_worst_case_skeleton(self):
        self.assertEqual(max_turn_advances(), 24)

    def test_the_bound_exceeds_every_fixed_cost(self):
        self.assertGreater(max_turn_advances(),
                           BEFORE_TURN_ADVANCES + BETWEEN_TURN_ADVANCES + END_OF_TURN_ADVANCES)

    def test_no_simulated_turn_ever_exceeds_it(self):
        """The bound is derived from the skeleton; this checks the simulator agrees with it."""
        import random
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
        from claytonlib.battle_compass.state import Action, Battler, BattleState, Status

        hunt = HuntConfig(target_catch_rate=3)
        rng = random.Random(11)
        worst = 0
        for _ in range(400):
            stats = {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160}
            ours = Battler(name="Smeargle", level=58, types=("Normal",), stats=stats,
                           moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                           pp=(40, 5, 20, 15))
            target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                             stats=derive_species_stats("suicune", 40, "Bold"),
                             moves=("Rain Dance", "Gust", "Aurora Beam", "Mist"),
                             pp=(5, 35, 20, 30), hp=1, status=Status.PARALYSIS)
            state = BattleState(ours=ours, target=target, rng=rng.getrandbits(32), phase=2)
            for action in Action:
                if action is Action.SWITCH:
                    continue
                # ITEM needs its code stated; the simulator no longer guesses one.
                extra = {"item_code": "p"} if action is Action.ITEM else {}
                spent = (simulate_turn(state, action, hunt, **extra).rng_offset
                         - state.rng_offset)
                worst = max(worst, spent)
                self.assertLessEqual(spent, max_turn_advances(), action.name)
        self.assertGreater(worst, 12, "the sample never exercised an expensive turn")


if __name__ == "__main__":
    unittest.main()
