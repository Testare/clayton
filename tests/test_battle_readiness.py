"""Party readiness checks — action-alphabet diversity and speed ties.

Both encode findings from notes/battle_compass.md that are easy to state and easy to get wrong:
sec 1.1 (one filler action is a ~36% proposition, three is ~99%) and sec 11.4 (a speed tie
desynchronises the simulation).
"""
import unittest

from claytonlib.battle.readiness import (
    FRAGILE_SPEED_MARGIN, PARALYSIS_SPEED_FACTOR, REACHABILITY_BY_DISTINCT_COSTS,
    AlphabetReport, alphabet_report, estimated_move_rolls, speed_checks, speed_warnings,
)
from claytonlib.moves import resolve_move

FIXTURE_MOVESETS = {
    "Smeargle": ["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    "Magneton": ["Thunder Wave"],
}


def _moves(names: dict[str, list[str]]) -> dict[str, list]:
    return {mon: [resolve_move(m) for m in moves] for mon, moves in names.items()}


class TestMoveRollEstimates(unittest.TestCase):
    def test_a_damaging_move_costs_more_than_a_status_move(self):
        self.assertGreater(estimated_move_rolls(resolve_move("False Swipe")),
                           estimated_move_rolls(resolve_move("Spore")))

    def test_an_always_hitting_status_move_is_free(self):
        self.assertEqual(estimated_move_rolls(resolve_move("Mean Look")), 0)

    def test_a_secondary_effect_adds_a_roll(self):
        self.assertGreater(estimated_move_rolls(resolve_move("Body Slam")),
                           estimated_move_rolls(resolve_move("Tackle")))

    def test_suicunes_own_moves_span_more_than_one_cost(self):
        costs = {estimated_move_rolls(resolve_move(m))
                 for m in ("Rain Dance", "Gust", "Aurora Beam", "Mist")}
        self.assertGreater(len(costs), 1)


class TestAlphabet(unittest.TestCase):
    def test_the_fixture_party_reaches_the_three_cost_threshold(self):
        report = alphabet_report(_moves(FIXTURE_MOVESETS))
        self.assertGreaterEqual(len(report.distinct_costs), 3)
        self.assertEqual(report.reachability_percent, 99)
        self.assertEqual(report.warnings, [])

    def test_smeargles_value_is_that_its_moves_differ_in_cost(self):
        """Not their effects: Spore is dead post-paralysis, Mean Look is pointless on a static
        target. They earn their slots by costing different numbers of rolls (sec 11.5)."""
        report = alphabet_report(_moves({"Smeargle": FIXTURE_MOVESETS["Smeargle"]}))
        move_costs = {k.split(": ")[1]: v for k, v in report.costs_by_action.items()}
        self.assertGreaterEqual(len(set(move_costs.values())), 2)

    def test_a_single_cost_party_is_warned_about_loudly(self):
        report = AlphabetReport(costs_by_action={"X: Splash": 0},
                                includes_ball=False, includes_item=False)
        self.assertEqual(report.reachability_percent, 36)
        self.assertEqual(len(report.warnings), 1)
        self.assertIn("36%", report.warnings[0])

    def test_two_costs_warns_more_gently(self):
        report = AlphabetReport(costs_by_action={"X: Splash": 0, "X: Tackle": 3},
                                includes_ball=False, includes_item=False)
        self.assertEqual(report.reachability_percent, 95)
        self.assertIn("95%", report.warnings[0])

    def test_items_contribute_a_zero_cost_action(self):
        """Verified on the emulator: items and switches spend no advances of their own."""
        report = AlphabetReport(costs_by_action={"X: Tackle": 3}, includes_ball=False)
        self.assertIn(0, report.distinct_costs)

    def test_a_ball_contributes_a_variable_cost(self):
        report = AlphabetReport(costs_by_action={}, includes_item=False)
        self.assertEqual(report.distinct_costs, {1, 2, 3, 4})

    def test_reachability_table_matches_the_documented_measurements(self):
        self.assertEqual(REACHABILITY_BY_DISTINCT_COSTS, {0: 0, 1: 36, 2: 95, 3: 99})

    def test_reachability_saturates_at_three_costs(self):
        many = AlphabetReport(costs_by_action={f"m{i}": i for i in range(9)})
        self.assertEqual(many.reachability_percent, 99)


class TestSpeedChecks(unittest.TestCase):
    def test_paralysis_quarters_speed(self):
        self.assertEqual(PARALYSIS_SPEED_FACTOR, 0.25)
        checks = {c.target_state: c.target_speed
                  for c in speed_checks({"X": 100}, 85, include_our_paralysis=False)}
        self.assertEqual(checks, {"unaffected": 85, "paralyzed": 21})

    def test_the_fixture_party_has_no_ties(self):
        checks = speed_checks({"Smeargle": 160, "Magneton": 56}, 85)
        self.assertEqual(speed_warnings(checks), [])

    def test_smeargle_outspeeds_the_target_in_both_states(self):
        checks = [c for c in speed_checks({"Smeargle": 160}, 85,
                                          include_our_paralysis=False)]
        self.assertTrue(all(c.margin > 0 for c in checks))

    def test_a_tie_is_reported_as_desynchronising(self):
        # 21 is a paralyzed Suicune's Speed.
        warnings = speed_warnings(speed_checks({"Slowpoke": 21}, 85,
                                               include_our_paralysis=False))
        self.assertEqual(len(warnings), 1)
        self.assertIn("desynchronise", warnings[0])

    def test_the_lv17_magnemite_margin_of_one_is_flagged_as_fragile(self):
        """The case sec 11.4 caught: 22 vs a paralyzed Suicune's 21."""
        warnings = speed_warnings(speed_checks({"Magnemite": 22}, 85,
                                               include_our_paralysis=False))
        self.assertEqual(len(warnings), 1)
        self.assertIn("within 1", warnings[0])

    def test_ties_are_listed_before_merely_fragile_margins(self):
        checks = speed_checks({"Tied": 21, "Close": 22}, 85, include_our_paralysis=False)
        warnings = speed_warnings(checks)
        self.assertIn("Tied", warnings[0])
        self.assertIn("Close", warnings[1])

    def test_our_own_paralysis_is_checked_too(self):
        """It quarters our Speed, which can flip an order that looked safe."""
        labels = {c.ours for c in speed_checks({"Smeargle": 160}, 85)}
        self.assertIn("Smeargle (paralyzed)", labels)
        without = {c.ours for c in speed_checks({"Smeargle": 160}, 85,
                                                include_our_paralysis=False)}
        self.assertEqual(without, {"Smeargle"})

    def test_fragile_threshold_is_exclusive_of_a_tie(self):
        tie = speed_checks({"X": 21}, 85, include_our_paralysis=False)[1]
        self.assertTrue(tie.is_tie)
        self.assertFalse(tie.is_fragile, "a tie is reported as a tie, not as fragile")

    def test_margins_beyond_the_threshold_are_silent(self):
        speed = 21 + FRAGILE_SPEED_MARGIN + 1
        self.assertEqual(speed_warnings(speed_checks({"X": speed}, 85,
                                                     include_our_paralysis=False)), [])


if __name__ == "__main__":
    unittest.main()
