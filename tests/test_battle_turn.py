"""The per-turn RNG cost skeleton, confirmed on the emulator.

Corroborated against the counts metronome_compass verified for the Blackthorn matchup — if those
two ever disagree, one of them is wrong and the simulator would desynchronise.
"""
import unittest

from claytonlib.battle.turn import (
    BAG_ACTION_ADVANCES, BEFORE_TURN_ADVANCES, BETWEEN_TURN_ADVANCES,
    END_OF_TURN_ADVANCES, POST_SUCCESSFUL_MOVE_ADVANCES,
    ActionCost, ball_turn_cost, shake_roll_offset, turn_cost,
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

    def test_shake_rolls_start_just_past_the_before_turn_advances(self):
        """Not at a ball-specific offset -- the 4 is what every turn pays (sec 6.1)."""
        self.assertEqual(shake_roll_offset(0), BEFORE_TURN_ADVANCES)
        self.assertEqual(shake_roll_offset(100), 104)

    def test_a_capturing_ball_consumes_all_four_shake_rolls(self):
        from claytonlib.battle.catch import rolls_consumed
        self.assertEqual(rolls_consumed(4), 4)
        self.assertEqual(ball_turn_cost(4), ball_turn_cost(3))


if __name__ == "__main__":
    unittest.main()
