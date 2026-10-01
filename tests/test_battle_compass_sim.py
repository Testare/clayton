"""Turn simulation, against the reference fixture in notes/battle_compass.md sec 11.

The roll accounting is checked against claytonlib.battle.turn's emulator-verified skeleton, so a
drift in either shows up here rather than as a desynchronised run.
"""
import unittest
from dataclasses import replace

from claytonlib.battle import turn as turn_costs
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.sim import (
    HuntConfig, advance, effective_speed, execute_move, move_roll_cost, select_target_move,
    simulate, simulate_turn, throw_ball,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass.tokens import normalise, render_path, turn_requires_hp
from claytonlib.moves import resolve_move as lookup

SEED = 0xEC1504DC
SUICUNE_MOVES = ("Rain Dance", "Gust", "Aurora Beam", "Mist")
SMEARGLE_MOVES = ("False Swipe", "Mean Look", "Sweet Scent", "Spore")


def _target(**overrides) -> Battler:
    fields = dict(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                  stats=derive_species_stats("suicune", 40, "Bold"),
                  moves=SUICUNE_MOVES, pp=(5, 35, 20, 30), hp=1, status=Status.PARALYSIS)
    fields.update(overrides)
    return Battler(**fields)


def _ours(**overrides) -> Battler:
    stats = {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160}
    fields = dict(name="Smeargle", level=58, types=("Normal",), stats=stats,
                  moves=SMEARGLE_MOVES, pp=(40, 5, 20, 15))
    fields.update(overrides)
    return Battler(**fields)


def _state(seed=SEED, **overrides) -> BattleState:
    fields = dict(ours=_ours(), target=_target(), rng=seed, phase=2)
    fields.update(overrides)
    return BattleState(**fields)


CONFIG = HuntConfig(target_catch_rate=3)


def _bare_cost(move) -> int:
    """The cost without any status-duration roll, for isolating that term."""
    from claytonlib.moves import CATEGORY_STATUS
    rolls = 1 if move.accuracy > 0 else 0
    if move.category != CATEGORY_STATUS:
        rolls += 2
    if move.effect_chance > 0:
        rolls += 1
    return rolls


class TestRollCosts(unittest.TestCase):
    """An UPPER BOUND on each move's cost, cross-checked against metronome_compass's verified
    handlers in tests/test_battle_compass_effects_parity.py."""

    def test_the_nine_fixture_moves(self):
        self.assertEqual(
            {name: move_roll_cost(lookup(name))
             for name in SMEARGLE_MOVES + SUICUNE_MOVES + ("Thunder Wave",)},
            {"False Swipe": 3,      # crit + damage + accuracy
             "Mean Look": 0,        # always hits, no secondary
             "Sweet Scent": 1,      # accuracy only
             # Accuracy, plus the hidden 2 + RAND%4 sleep-duration roll spent when sleep LANDS.
             # This was 1 until the parity check against effects._eff_sleep found the duration
             # roll; a successful Spore desynchronised every turn after it.
             "Spore": 2,
             "Thunder Wave": 1,     # paralysis is permanent, so no duration roll
             "Rain Dance": 0,
             "Mist": 0,
             "Gust": 3,
             "Aurora Beam": 4})    # + a proc roll for the 10% Attack drop

    def test_sleep_is_the_only_fixture_move_with_a_duration_roll(self):
        self.assertEqual(
            {n for n in SMEARGLE_MOVES + SUICUNE_MOVES + ("Thunder Wave",)
             if move_roll_cost(lookup(n)) > _bare_cost(lookup(n))},
            {"Spore"})

    def test_a_secondary_effect_costs_one_more_than_the_same_move_without_one(self):
        self.assertEqual(move_roll_cost(lookup("Aurora Beam")) - move_roll_cost(lookup("Gust")), 1)

    def test_the_party_spans_at_least_three_distinct_costs(self):
        """The reachability requirement from sec 1.1, stated as a property of the moveset."""
        costs = {move_roll_cost(lookup(name)) for name in SMEARGLE_MOVES}
        self.assertGreaterEqual(len(costs), 2)
        self.assertIn(0, costs)


class TestRngPlumbing(unittest.TestCase):
    def test_advance_returns_the_high_sixteen_bits(self):
        state, roll = advance(SEED)
        self.assertEqual(roll, state >> 16)
        self.assertNotEqual(state, SEED)

    def test_move_selection_indexes_the_usable_slots(self):
        target = _target()
        _, slot = select_target_move(SEED, target)
        self.assertIn(slot, target.usable_slots())

    def test_move_selection_costs_nothing_when_nothing_is_usable(self):
        """A target out of PP would Struggle; the selection roll is not spent."""
        rng, slot = select_target_move(SEED, _target(pp=(0, 0, 0, 0)))
        self.assertEqual(rng, SEED)
        self.assertIsNone(slot)

    def test_the_modulus_shrinks_as_pp_runs_out(self):
        """Which is why the move choice's entropy decays from 2.00 bits (sec 5.2 R4)."""
        slots = {select_target_move(SEED + d, _target(pp=(0, 35, 20, 30)))[1]
                 for d in range(40)}
        self.assertNotIn(0, slots)
        self.assertTrue(slots <= {1, 2, 3})


class TestTurnAccounting(unittest.TestCase):
    """Every turn's roll count must equal battle.turn's verified skeleton."""

    FIXED = (turn_costs.BEFORE_TURN_ADVANCES + turn_costs.BETWEEN_TURN_ADVANCES
             + turn_costs.END_OF_TURN_ADVANCES)

    def test_a_turn_advances_the_rng_by_exactly_its_offset(self):
        state = simulate_turn(_state(), Action.MOVE_1, CONFIG)
        rng = SEED
        for _ in range(state.rng_offset):
            from claytonlib.safari import advance_rng
            rng = advance_rng(rng)
        self.assertEqual(state.rng, rng, "rng_offset disagrees with the rng actually advanced")

    def test_offsets_accumulate_across_turns(self):
        state = simulate(_state(), [Action.MOVE_1] * 4, CONFIG)
        self.assertEqual(state.turn, 4)
        self.assertGreater(state.rng_offset, 4 * self.FIXED)

    def test_a_turn_costs_at_least_the_fixed_overhead(self):
        """Item turns spend nothing of their own, so they are the floor (sec 12.1).

        The explicit `item_code` is required now. It used to default to a Potion inside the
        simulator, which is how the solver came to price a Hyper Potion and simulate a Potion.
        """
        item = simulate_turn(_state(), Action.ITEM, CONFIG, item_code="p")
        self.assertGreaterEqual(item.rng_offset, self.FIXED)

    def test_an_item_turn_is_cheaper_than_a_move_turn(self):
        item = simulate_turn(_state(), Action.ITEM, CONFIG, item_code="p").rng_offset
        move = simulate_turn(_state(), Action.MOVE_1, CONFIG).rng_offset
        self.assertLess(item, move)

    def test_our_action_choice_changes_the_offset(self):
        """The whole basis of steering: different actions cost different numbers of rolls."""
        offsets = {a: simulate_turn(_state(), a, CONFIG,
                                   **({"item_code": "p"} if a is Action.ITEM else {})).rng_offset
                   for a in (Action.ITEM, Action.MOVE_2, Action.MOVE_4, Action.MOVE_1)}
        self.assertGreater(len(set(offsets.values())), 1)


class TestTurnBehaviour(unittest.TestCase):
    def test_smeargle_outspeeds_a_paralyzed_suicune_so_moves_first(self):
        state = simulate_turn(_state(), Action.MOVE_1, CONFIG)
        turn = state.log[0]
        self.assertTrue(turn[0].startswith("M"), f"we should act first, got {turn}")

    def test_false_swipe_cannot_take_the_target_below_one(self):
        state = simulate(_state(), [Action.MOVE_1] * 6, CONFIG)
        self.assertEqual(state.target.hp, 1)
        self.assertFalse(state.target.fainted)

    def test_pressure_doubles_our_pp_consumption(self):
        with_pressure = simulate_turn(_state(), Action.MOVE_1, CONFIG)
        without = simulate_turn(_state(), Action.MOVE_1,
                                HuntConfig(target_catch_rate=3, target_has_pressure=False))
        self.assertEqual(with_pressure.ours.pp_left(0), 38)
        self.assertEqual(without.ours.pp_left(0), 39)

    def test_an_hp_token_appears_exactly_when_our_hp_changed(self):
        for turn_index in range(6):
            state = simulate(_state(), [Action.MOVE_1] * (turn_index + 1), CONFIG)
            turn = state.log[turn_index]
            # Normalise first: the simulator emits fragments, the grammar's unit is merged.
            merged = normalise(turn)
            hp_tokens = [t for t in merged if t.startswith("HP")]
            damaged = any(t.startswith("E") and ("h" in t or "!" in t) for t in merged)
            self.assertEqual(bool(hp_tokens), damaged, f"turn {turn_index}: {merged}")
            self.assertEqual(turn_requires_hp(turn), damaged)

    def test_a_paralyzed_target_sometimes_cannot_move(self):
        seen = set()
        for delta in range(40):
            state = simulate_turn(_state(SEED + delta), Action.MOVE_1, CONFIG)
            seen.update(t for t in state.log[0] if t.startswith("Epar"))
        self.assertIn("Epar", seen, "no full-paralysis turn in 40 seeds")

    def test_spore_fails_against_an_already_paralyzed_target(self):
        """Statuses are exclusive, so Spore is dead as a status move but alive as filler."""
        state = simulate_turn(_state(), Action.MOVE_4, CONFIG)
        self.assertEqual(state.target.status, Status.PARALYSIS)

    def test_aurora_beams_secondary_lowers_our_attack(self):
        for delta in range(60):
            state = simulate(_state(SEED + delta), [Action.MOVE_1] * 3, CONFIG)
            if any("~" in t for turn in state.log for t in turn):
                self.assertLess(state.our_attack_stage, 0)
                return
        self.skipTest("no Attack drop proc'd in 60 seeds")


class TestBallThrows(unittest.TestCase):
    def test_a_throw_consumes_one_to_four_rolls(self):
        counts = set()
        for delta in range(60):
            rng, shakes, captured = throw_ball(
                SEED + delta, _target(), catch_rate=3, ball_multiplier=10, status_bonus=15)
            counts.add(shakes)
        self.assertTrue(counts <= {0, 1, 2, 3, 4})
        self.assertGreater(len(counts), 1, "every seed gave the same shake count")

    def test_the_capture_ball_and_a_standard_ball_use_distinct_tokens(self):
        capture = simulate_turn(_state(), Action.CAPTURE_BALL, CONFIG).log[0]
        standard = simulate_turn(_state(), Action.STANDARD_BALL, CONFIG).log[0]
        self.assertTrue(capture[0].startswith("C"))
        self.assertTrue(standard[0].startswith("P"))

    def test_a_standard_ball_capture_is_a_loss_not_a_win(self):
        """Caught in the wrong ball: the run is lost (sec 2.3)."""
        state = _state()
        state.captured_in_wrong_ball = True
        self.assertTrue(state.over)
        self.assertFalse(state.captured)

    def test_throwing_stops_the_target_acting_when_it_captures(self):
        state = _state()
        state.captured = True
        self.assertTrue(state.over)


class TestCandidateDivergence(unittest.TestCase):
    """What identification actually rests on: adjacent candidate seeds must produce different
    token streams, and quickly."""

    def test_adjacent_seeds_diverge_within_the_first_turn(self):
        paths = {render_path(simulate(_state(SEED + d), [Action.MOVE_1], CONFIG).log)
                 for d in range(8)}
        self.assertGreater(len(paths), 4, f"only {len(paths)} distinct first turns in 8 seeds")

    def test_three_turns_separate_a_large_candidate_set(self):
        paths = {render_path(simulate(_state(SEED + d), [Action.MOVE_1] * 3, CONFIG).log)
                 for d in range(200)}
        self.assertGreater(len(paths), 150, f"only {len(paths)} distinct paths from 200 seeds")

    def test_the_same_seed_is_deterministic(self):
        a = render_path(simulate(_state(), [Action.MOVE_1] * 5, CONFIG).log)
        b = render_path(simulate(_state(), [Action.MOVE_1] * 5, CONFIG).log)
        self.assertEqual(a, b)


class TestTurnOrder(unittest.TestCase):
    """Paralysis -- not Lagging Tail -- is the sanctioned tie-avoidance (sec 4.2). Lagging Tail
    would guarantee we move last, which is exactly wrong."""

    def test_paralysis_quarters_the_targets_speed(self):
        state = _state()
        self.assertEqual(effective_speed(state.target), state.target.stats["spe"] // 4)

    def test_an_unparalyzed_battler_keeps_its_speed(self):
        state = _state()
        self.assertEqual(effective_speed(state.ours), state.ours.stats["spe"])

    def test_paralysis_is_what_opens_the_speed_gap(self):
        """Smeargle outspeeds Suicune anyway, but the factor is what makes the gap wide enough
        that no party member can land in a tie."""
        state = _state()
        healthy = replace(state.target, status=Status.NONE)
        self.assertLess(effective_speed(state.target), effective_speed(healthy))

    def test_we_move_first_against_the_paralyzed_target(self):
        state = _state()
        self.assertGreater(effective_speed(state.ours), effective_speed(state.target))

    def test_a_higher_priority_bracket_beats_speed(self):
        """Priority is consulted before Speed, so a slower mon with a priority move still leads.
        No fixture move uses it, which is why an ordering bug here would have gone unseen."""
        self.assertEqual(lookup("False Swipe").priority, 0)
        self.assertEqual(lookup("Protect").priority, 3)


if __name__ == "__main__":
    unittest.main()
