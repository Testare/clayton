"""The simulator against a real emulator recording.

`data/battle_logs/test1.jsonl` is a hand-played Bell Tower Suicune battle with the battle seed
forced to 0xc5011c6b, captured by `utils/gdb-battle-reader.py`. It is the first ground truth this
project has for Battle Compass, and it settles R2, R7 and most of R10.

It also found the bug it was run to find. The simulator matched turns 1-2 and then drifted,
because it did not model a move FAILING when the condition it sets is already in place: Suicune
re-used Rain Dance while it was already raining, the game skipped the two post-successful-move
advances, and the simulator spent them. 19 advances against the real 17, and every offset after
that was wrong.

If this file cannot find the log it skips, so the suite still runs on a machine without it.
"""
import json
import pathlib
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.sim import (
    BATTLE_START_ADVANCES as _SIM_START_ADVANCES, HuntConfig, opening_rng,
    simulate_turn,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState
from claytonlib.battle_compass.targets import moveset
from claytonlib.metronome_compass import _BATTLE_START_ADVANCES
from claytonlib.moves import resolve_move

LOG = pathlib.Path(__file__).resolve().parent.parent / "data" / "battle_logs" / "test1.jsonl"

FORCED_SEED = 0xC5011C6B
#: Rolls spent between the seed being forced and the first turn's move-selection roll:
#: 4 bellShimmerReplaceGraphics + 2 for Pressure's announcement [verified]. Re-exported from
#: ``sim`` rather than restated, because the identification path has to burn the same six and
#: for a while did not -- see tests/test_battle_compass_ground_truth_2.py.
BATTLE_START_ADVANCES = _SIM_START_ADVANCES

#: Advances the game spent on each turn, read off the log by caller attribution.
ACTUAL_TURN_ADVANCES = [16, 12, 17, 19, 23, 17, 17, 16, 13, 12, 16, 12, 19, 17, 15, 13, 20]

#: What was played, in order. Magneton leads, switches to Smeargle on turn 2.
ACTIONS = (
    [(Action.MOVE_1, {})]                        # Thunder Wave
    + [(Action.SWITCH, {"bench_slot": 0})]       # -> Smeargle
    + [(Action.MOVE_1, {})] * 5                  # False Swipe x5
    + [(Action.STANDARD_BALL, {}), (Action.STANDARD_BALL, {})]
    + [(Action.ITEM, {"item_code": "p"})]        # Potion, +20 HP
    + [(Action.MOVE_2, {}), (Action.MOVE_2, {})]  # Mean Look x2
    + [(Action.MOVE_4, {})]                      # Spore
    + [(Action.MOVE_3, {}), (Action.MOVE_3, {})]  # Sweet Scent x2
    + [(Action.STANDARD_BALL, {}), (Action.STANDARD_BALL, {})]
)

#: Suicune's HP after each False Swipe, from the log's own HP reads.
ACTUAL_TARGET_HP = [113, 85, 58, 31, 4]
#: Aurora Beam's damage to Smeargle on turns 5, 13 and 17.
ACTUAL_INCOMING = [27, 26, 24]


def _magneton():
    """Level 31, stats straight off the summary screen."""
    return Battler(name="Magneton", level=31, types=("Electric", "Steel"),
                   stats={"hp": 79, "atk": 58, "def": 65, "spa": 84, "spd": 57, "spe": 50},
                   moves=("Thunder Wave", "Tackle"), pp=(20, 35))


def _smeargle():
    # Level 58, not the 60 the fixture was first written down as: the log's five False Swipes
    # only reconcile at 58 (level term 25, not 26), and the HP read of 153 agrees. Stats are the
    # real ones off the summary screen -- note Sp. Def 79 falls inside the 78-80 that solving the
    # three recorded Aurora Beams independently produced.
    return Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15), ability="Technician", held_item="Silk Scarf")


def _suicune():
    moves = moveset("suicune")
    return Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                   stats=derive_species_stats(
                       "suicune", 40, "Bold",
                       ivs={"hp": 29, "atk": 15, "def": 31, "spa": 31, "spd": 31, "spe": 28}),
                   moves=moves, pp=tuple(resolve_move(m).pp for m in moves))


def _replay():
    """Simulate the recorded battle, returning per-turn (advances, rendered tokens, state)."""
    rng = opening_rng(FORCED_SEED, HuntConfig(target_catch_rate=3))
    state = BattleState(ours=_magneton(), target=_suicune(), rng=rng,
                        bench=(_smeargle(),), phase=1)
    out = []
    hunt = HuntConfig(target_catch_rate=3)
    for action, kwargs in ACTIONS:
        before = state.rng_offset
        state = simulate_turn(state, action, hunt, **kwargs)
        out.append((state.rng_offset - before,
                    tok.render_turn(tok.normalise(state.log[-1])), state))
    return out


class TestTheLogIsPresent(unittest.TestCase):
    def test_it_parses(self):
        if not LOG.exists():
            self.skipTest(f"{LOG} not present")
        doc = json.loads(LOG.read_text())
        self.assertEqual(int(doc["forced_seed"], 16), FORCED_SEED)
        self.assertGreater(len(doc["records"]), 300)


class TestBattleStartAdvances(unittest.TestCase):
    """R2, answered."""

    def test_it_is_six_and_matches_metronome_compass(self):
        """4 bellShimmerReplaceGraphics + 2 for Pressure. The same figure metronome_compass
        verified for Blackthorn, which is a useful corroboration rather than a coincidence: the
        2 are the ability announcement either way."""
        self.assertEqual(BATTLE_START_ADVANCES, 6)
        self.assertEqual(BATTLE_START_ADVANCES, _BATTLE_START_ADVANCES)

    def test_the_log_shows_exactly_that_many_before_the_first_turn(self):
        if not LOG.exists():
            self.skipTest("log not present")
        records = json.loads(LOG.read_text())["records"]
        # A turn opens with the wild move-selection roll, whose caller the symbols cannot resolve.
        first_turn = next(i for i, r in enumerate(records)
                          if "roll" in r and r["roll"]["func"] == "??")
        before = sum(1 for r in records[:first_turn] if "roll" in r)
        self.assertEqual(before, BATTLE_START_ADVANCES)


class TestEveryTurnSpendsTheRightAdvances(unittest.TestCase):
    """R7, answered. A count that is wrong by one desynchronises everything after it, so this is
    the single most valuable assertion in the suite."""

    def test_all_seventeen_turns_match(self):
        mismatches = []
        for n, ((advances, rendered, _), actual) in enumerate(
                zip(_replay(), ACTUAL_TURN_ADVANCES), 1):
            if advances != actual:
                mismatches.append(f"turn {n}: simulated {advances}, game spent {actual} "
                                  f"({rendered})")
        self.assertEqual(mismatches, [], "; ".join(mismatches))

    def test_the_first_two_turns_matched_even_before_the_fix(self):
        """Which is why the bug looked like a wrong constant rather than a missing mechanic."""
        replay = _replay()
        self.assertEqual(replay[0][0], 16)
        self.assertEqual(replay[1][0], 12)

    def test_turn_three_is_the_one_that_used_to_drift(self):
        """Suicune re-used Rain Dance while it was raining: 17 advances, not 19."""
        self.assertEqual(_replay()[2][0], 17)
        self.assertEqual(ACTUAL_TURN_ADVANCES[2], 17)


class TestTheTargetsChoicesMatch(unittest.TestCase):
    """The wild move-selection roll, against reality."""

    #: Which move Suicune used each turn, from the log's messages. None = fully paralyzed.
    EXPECTED = ["E1", "Epar", "E1", "E4", "E3", "E4", "E4", "E4", "Epar", "Epar",
                "E1", "E1", "E3", "E4", "Epar", "E4", "E3"]

    def test_every_turn_picks_the_move_the_game_picked(self):
        wrong = []
        for n, ((_, rendered, _), expected) in enumerate(zip(_replay(), self.EXPECTED), 1):
            if expected not in rendered:
                wrong.append(f"turn {n}: expected {expected} in {rendered}")
        self.assertEqual(wrong, [], "; ".join(wrong))

    def test_it_covers_every_move_in_the_moveset_plus_full_paralysis(self):
        """So the match is not luck on one move."""
        self.assertEqual({e for e in self.EXPECTED}, {"E1", "E3", "E4", "Epar"})


class TestShakeCountsMatch(unittest.TestCase):
    """Four Poke Ball throws, and the ROM's shake messages map onto them."""

    #: turn -> shakes, from the messages: 0 = "broke free", 1 = "appeared to be caught",
    #: 3 = "so close, too".
    EXPECTED = {8: 3, 9: 0, 16: 0, 17: 1}

    def test_each_throw_shakes_the_recorded_number_of_times(self):
        replay = _replay()
        for turn, shakes in self.EXPECTED.items():
            rendered = replay[turn - 1][1]
            self.assertIn(f"P{shakes}", rendered, f"turn {turn}: {rendered}")

    def test_the_advances_follow_rolls_consumed(self):
        """1-4 rolls, stopping at the first failed shake."""
        from claytonlib.battle.catch import rolls_consumed
        self.assertEqual([rolls_consumed(n) for n in (0, 1, 3)], [1, 2, 4])


class TestTheTargetsHpMatchesExactly(unittest.TestCase):
    """Outgoing damage, which reconciled only once Smeargle's level was corrected from the 60 the
    fixture was written down as to the real 58. The level term is `(level*2/5)+2` in integer
    arithmetic, so 58 and 59 both give 25 while 60 gives 26 -- one point of base damage, which
    is the whole discrepancy.

    Not needed for identification (the target's HP is never in the token stream) but it gates
    Phase 2, which asserts the target is at exactly 1 HP.
    """

    def test_every_false_swipe_lands_the_recorded_damage(self):
        replay = _replay()
        got = [state.target.hp for _, _, state in replay[2:7]]
        self.assertEqual(got, ACTUAL_TARGET_HP)

    def test_false_swipe_never_takes_it_below_one(self):
        replay = _replay()
        for _, _, state in replay:
            self.assertGreaterEqual(state.target.hp, 1)

    def test_level_sixty_would_not_have_matched(self):
        """Pinning why the level mattered, so it cannot quietly drift back."""
        self.assertEqual((58 * 2) // 5 + 2, 25)
        self.assertEqual((60 * 2) // 5 + 2, 26)
        self.assertNotEqual((58 * 2) // 5 + 2, (60 * 2) // 5 + 2)


class TestOurHpMatchesExactly(unittest.TestCase):
    """The strongest assertion available, and the point of the whole exercise.

    Our HP is the only damage figure in the token stream, and an exact HP change identifies which
    of the sixteen damage rolls landed -- ~2.5 bits per hit, the richest signal there is (sec 3.1).
    Predicting it right is what makes identification work; predicting it wrong eliminates the
    true seed.
    """

    #: turn -> our HP, straight from the log's own reads.
    EXPECTED = {5: 126, 10: 146, 13: 120, 17: 96}

    def test_every_recorded_hp_is_predicted_exactly(self):
        replay = _replay()
        for turn, hp in self.EXPECTED.items():
            self.assertIn(f"HP{hp:03d}", replay[turn - 1][1],
                          f"turn {turn}: expected HP{hp:03d} in {replay[turn - 1][1]}")

    def test_it_covers_a_heal_as_well_as_hits(self):
        """Turn 10 is the Potion: +20, which the log confirms as 126 -> 146."""
        self.assertIn("Ip", _replay()[9][1])
        self.assertIn("HP146", _replay()[9][1])
        self.assertEqual(self.EXPECTED[10] - self.EXPECTED[5], 20)


class TestTheDamageRollIsNotInverted(unittest.TestCase):
    """ApplyDamageRange SUBTRACTS the roll:

        damage *= (100 - (BattleSystem_Random(battleSystem) % 16));

    so ``% 16 == 0`` is 100% and ``% 16 == 15`` is 85%. This was implemented as ``85 + roll % 16``,
    which spans the same sixteen multipliers and so passes any range check while getting every
    individual value wrong. The log settles it: a roll of ``% 16 == 13`` dealt LESS than one of
    ``% 16 == 9``, which the ascending form cannot produce.
    """

    #: (multiplier under the corrected mapping, damage dealt) for the three Aurora Beams.
    HITS = [(99, 27), (93, 26), (87, 24)]

    def test_the_corrected_mapping_is_consistent_with_one_base_damage(self):
        """All three hits from a single base of 28 -- which is what a correct formula must give."""
        for mult, dealt in self.HITS:
            self.assertEqual(28 * mult // 100, dealt, f"mult {mult}")

    def test_the_inverted_mapping_gets_all_three_wrong(self):
        """So this is not a subtle preference between two readings."""
        wrong = sum(1 for mult, dealt in self.HITS
                    if 28 * (85 + (100 - mult)) // 100 != dealt)
        self.assertEqual(wrong, 3)

    def test_the_simulator_uses_the_subtracting_form(self):
        from claytonlib.battle_compass.sim import DAMAGE_ROLL_COUNT, DAMAGE_ROLL_MAX_PERCENT
        self.assertEqual(DAMAGE_ROLL_MAX_PERCENT, 100)
        self.assertEqual(DAMAGE_ROLL_COUNT, 16)
        # 100 - 15 = 85 is the floor, so the set of multipliers is unchanged.
        self.assertEqual(DAMAGE_ROLL_MAX_PERCENT - (DAMAGE_ROLL_COUNT - 1), 85)


class TestIncomingDamageIsInRange(unittest.TestCase):
    """R10 for Aurora Beam. Incoming damage is the identification signal, so this is the half
    that has to be right -- an error here eliminates the true seed."""

    def test_the_three_real_hits_fall_inside_the_predicted_spread(self):
        from claytonlib.battle.damage import Attacker, Defender, damage_range
        target = _suicune()
        ours = _smeargle()
        low, high = damage_range(
            resolve_move("Aurora Beam"),
            Attacker(level=target.level, attack=target.stats["atk"],
                     special_attack=target.stats["spa"], types=target.types),
            Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                     types=ours.types))
        for observed in ACTUAL_INCOMING:
            self.assertGreaterEqual(observed, low, f"{observed} below predicted {low}-{high}")
            self.assertLessEqual(observed, high, f"{observed} above predicted {low}-{high}")

    def test_the_spread_is_tight_enough_to_identify_with(self):
        """~2.5 bits per hit is the claim in sec 3.1; a 16-value spread delivers it only if the
        range is narrow relative to the values."""
        from claytonlib.battle.damage import Attacker, Defender, damage_range
        target, ours = _suicune(), _smeargle()
        low, high = damage_range(
            resolve_move("Aurora Beam"),
            Attacker(level=target.level, attack=target.stats["atk"],
                     special_attack=target.stats["spa"], types=target.types),
            Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                     types=ours.types))
        self.assertLessEqual(high - low, 8)


class TestFieldConditionsAreModelled(unittest.TestCase):
    """The mechanics the log forced into the simulator. Each failure costs the turn its two
    post-successful-move advances, which is how a missing one desynchronises a run."""

    def test_rain_dance_fails_while_it_is_raining(self):
        replay = _replay()
        # Turn 1 sets rain, turn 3 re-uses Rain Dance and the game reported "But it failed!".
        self.assertEqual(replay[0][0], 16)
        self.assertEqual(replay[2][0], 17)

    def test_rain_lasts_five_turns(self):
        from claytonlib.battle_compass.sim import RAIN_TURNS
        self.assertEqual(RAIN_TURNS, 5)

    def test_mist_lasts_five_turns(self):
        from claytonlib.battle_compass.sim import MIST_TURNS
        self.assertEqual(MIST_TURNS, 5)

    def test_a_field_move_is_refused_when_its_condition_is_up(self):
        from claytonlib.battle_compass.sim import will_fail
        from dataclasses import replace as dc_replace
        target, ours = _suicune(), _smeargle()
        dry = BattleState(ours=ours, target=target, rng=1)
        wet = dc_replace(dry, rain_turns=3)
        self.assertFalse(will_fail(resolve_move("Rain Dance"), ours, dry))
        self.assertTrue(will_fail(resolve_move("Rain Dance"), ours, wet))

    def test_mean_look_fails_on_an_already_trapped_target(self):
        from claytonlib.battle_compass.sim import will_fail
        from dataclasses import replace as dc_replace
        target, ours = _suicune(), _smeargle()
        free = BattleState(ours=ours, target=target, rng=1)
        held = dc_replace(free, target_trapped=True)
        self.assertFalse(will_fail(resolve_move("Mean Look"), target, free))
        self.assertTrue(will_fail(resolve_move("Mean Look"), target, held))

    def test_a_mist_blocked_stat_drop_still_counts_as_successful(self):
        """Turn 15 spent 8 skeleton rolls, not 6, on a Sweet Scent the game reported as
        "protected by Mist" -- so the move executed and paid its post-move advances."""
        self.assertEqual(_replay()[14][0], 15)
        self.assertEqual(ACTUAL_TURN_ADVANCES[14], 15)


if __name__ == "__main__":
    unittest.main()
