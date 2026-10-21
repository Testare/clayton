"""Which ball exists where, and what it multiplies.

Until Platinum this table did not need to exist: every HGSS target/ball pairing the project had
reached was ×1, so `facade` set only `fast_ball_matched` and `HuntConfig.capture_ball_multiplier`
was never assigned at all. Nothing was visibly wrong, because nothing was multiplied.

So these tests are written against the ROM rather than against the implementation — the
conditional multipliers are transcribed independently below from
`BattleScript_CalcCatchShakes` (pokeplatinum `src/battle/battle_script.c:10922-10974`) — and they
pin the two properties that are new rather than merely different:

* a multiplier that **moves with the turn** (Quick, Timer), which the solver's threshold has to
  follow rather than cache;
* a ball whose rule is **not modelled**, which must say so rather than quietly return ×1.
"""
import unittest

from claytonlib.battle.balls import (
    BALLS, DUSK_BALL_BUCKET, TERRAIN_CAVE, TERRAIN_OTHER, TERRAIN_WATER, ThrowContext, ball,
    ball_effect, ball_key, balls_for_game, is_turn_dependent,
)
from claytonlib.battle.catch import catch_value, shake_threshold

#: Transcribed from the ROM switch, independently of `balls.py`: (ball, matched multiplier).
ROM_CONDITIONAL = (
    ("Net Ball", 30), ("Dive Ball", 35), ("Repeat Ball", 30),
    ("Timer Ball", 40), ("Quick Ball", 40), ("Dusk Ball", 35),
)
#: `sBasicBallMod[]` = {20, 15, 10, 15} for Ultra, Great, Poke, Safari (`:10868-10873`).
ROM_BASIC = (("Ultra Ball", 20), ("Great Ball", 15), ("Poké Ball", 10), ("Safari Ball", 15))

#: A catch-rate-3 legendary, the case Battle Compass exists for.
LEGENDARY_RATE = 3


class TestAvailability(unittest.TestCase):

    def test_platinum_has_no_apricorn_balls(self):
        names = {b.name for b in balls_for_game("platinum")}
        for apricorn in ("Fast Ball", "Level Ball", "Lure Ball", "Heavy Ball", "Love Ball",
                         "Friend Ball", "Moon Ball"):
            self.assertNotIn(apricorn, names, apricorn)

    def test_hgss_has_them(self):
        names = {b.name for b in balls_for_game("soulsilver")}
        self.assertIn("Fast Ball", names)
        self.assertIn("Sport Ball", names)

    def test_the_conditional_balls_exist_in_both(self):
        for game in ("platinum", "heartgold"):
            names = {b.name for b in balls_for_game(game)}
            for conditional, _ in ROM_CONDITIONAL:
                self.assertIn(conditional, names, f"{conditional} in {game}")

    def test_an_unset_game_offers_everything(self):
        """Permissive for the same reason `games.tool_refusal` is: offering too many is a smaller
        harm than hiding the ball the player is holding."""
        self.assertEqual(len(balls_for_game("")), len(BALLS))
        self.assertEqual(len(balls_for_game(None)), len(BALLS))

    def test_the_sport_ball_is_hgss_only(self):
        self.assertNotIn("Sport Ball", {b.name for b in balls_for_game("platinum")})


class TestLookup(unittest.TestCase):

    def test_the_accent_is_not_required(self):
        """"Poké Ball" carries an accent nobody types."""
        self.assertEqual(ball("poke ball").name, "Poké Ball")
        self.assertEqual(ball("Poké Ball").name, "Poké Ball")
        self.assertEqual(ball_key("Poké Ball"), ball_key("pokeball"))

    def test_an_unknown_ball_raises_listing_the_known_ones(self):
        with self.assertRaises(ValueError) as caught:
            ball("Beast Ball")
        self.assertIn("Dusk Ball", str(caught.exception))


class TestPlainMultipliers(unittest.TestCase):

    def test_match_the_rom_table(self):
        for name, expected in ROM_BASIC:
            self.assertEqual(ball_effect(name, LEGENDARY_RATE).multiplier, expected, name)

    def test_the_master_ball_is_guaranteed(self):
        self.assertTrue(ball_effect("Master Ball", LEGENDARY_RATE).guaranteed)

    def test_balls_with_no_case_in_the_switch_are_x1(self):
        """Luxury, Premier, Heal, Cherish and Park have no case, so they stay ×1 — the fact
        notes/battle_compass_next_targets.md §3 rests on for the Luxury Ball."""
        for name in ("Luxury Ball", "Premier Ball", "Heal Ball", "Cherish Ball", "Park Ball"):
            effect = ball_effect(name, LEGENDARY_RATE)
            self.assertEqual(effect.multiplier, 10, name)
            self.assertFalse(effect.guaranteed, name)


class TestConditionalMultipliers(unittest.TestCase):

    def test_net_ball_on_type(self):
        self.assertEqual(ball_effect("Net Ball", LEGENDARY_RATE,
                                     ThrowContext(target_types=("Water", "Flying"))).multiplier, 30)
        self.assertEqual(ball_effect("Net Ball", LEGENDARY_RATE,
                                     ThrowContext(target_types=("Bug",))).multiplier, 30)
        self.assertEqual(ball_effect("Net Ball", LEGENDARY_RATE,
                                     ThrowContext(target_types=("Dark",))).multiplier, 10)

    def test_dive_ball_on_water_terrain(self):
        self.assertEqual(ball_effect("Dive Ball", LEGENDARY_RATE,
                                     ThrowContext(terrain=TERRAIN_WATER)).multiplier, 35)
        self.assertEqual(ball_effect("Dive Ball", LEGENDARY_RATE,
                                     ThrowContext(terrain=TERRAIN_CAVE)).multiplier, 10)

    def test_nest_ball_is_forty_minus_level_and_never_reaches_x4(self):
        """`ballMod = 40 - level`, floored at 10, only below level 40. So its ceiling is 39 at
        level 1 — *not* 40, which an earlier comment in catch.py claimed."""
        self.assertEqual(ball_effect("Nest Ball", LEGENDARY_RATE,
                                     ThrowContext(target_level=1)).multiplier, 39)
        self.assertEqual(ball_effect("Nest Ball", LEGENDARY_RATE,
                                     ThrowContext(target_level=25)).multiplier, 15)
        self.assertEqual(ball_effect("Nest Ball", LEGENDARY_RATE,
                                     ThrowContext(target_level=35)).multiplier, 10)
        self.assertEqual(ball_effect("Nest Ball", LEGENDARY_RATE,
                                     ThrowContext(target_level=50)).multiplier, 10)

    def test_repeat_ball_on_registration(self):
        self.assertEqual(ball_effect("Repeat Ball", LEGENDARY_RATE,
                                     ThrowContext(registered=True)).multiplier, 30)
        self.assertEqual(ball_effect("Repeat Ball", LEGENDARY_RATE,
                                     ThrowContext(registered=False)).multiplier, 10)

    def test_quick_ball_is_the_first_turn_only(self):
        self.assertEqual(ball_effect("Quick Ball", LEGENDARY_RATE,
                                     ThrowContext(turn=0)).multiplier, 40)
        for turn in (1, 2, 10):
            self.assertEqual(ball_effect("Quick Ball", LEGENDARY_RATE,
                                         ThrowContext(turn=turn)).multiplier, 10, turn)

    def test_timer_ball_climbs_and_caps(self):
        self.assertEqual(ball_effect("Timer Ball", LEGENDARY_RATE,
                                     ThrowContext(turn=0)).multiplier, 10)
        self.assertEqual(ball_effect("Timer Ball", LEGENDARY_RATE,
                                     ThrowContext(turn=10)).multiplier, 20)
        self.assertEqual(ball_effect("Timer Ball", LEGENDARY_RATE,
                                     ThrowContext(turn=30)).multiplier, 40)
        self.assertEqual(ball_effect("Timer Ball", LEGENDARY_RATE,
                                     ThrowContext(turn=200)).multiplier, 40)

    def test_timer_and_quick_move_in_opposite_directions(self):
        """Which is why a turn-blind `b` is wrong for both, in opposite ways."""
        early, late = ThrowContext(turn=0), ThrowContext(turn=30)
        self.assertGreater(ball_effect("Quick Ball", LEGENDARY_RATE, early).multiplier,
                           ball_effect("Quick Ball", LEGENDARY_RATE, late).multiplier)
        self.assertLess(ball_effect("Timer Ball", LEGENDARY_RATE, early).multiplier,
                        ball_effect("Timer Ball", LEGENDARY_RATE, late).multiplier)

    def test_only_quick_and_timer_are_turn_dependent(self):
        for name in ("Quick Ball", "Timer Ball"):
            self.assertTrue(is_turn_dependent(name), name)
        for name in ("Dusk Ball", "Net Ball", "Ultra Ball", "Fast Ball", "Master Ball"):
            self.assertFalse(is_turn_dependent(name), name)


class TestDuskBall(unittest.TestCase):
    """The one ball whose multiplier depends on the key seed itself."""

    def test_night_matches(self):
        self.assertEqual(ball_effect("Dusk Ball", LEGENDARY_RATE,
                                     ThrowContext(time_of_day=DUSK_BALL_BUCKET)).multiplier, 35)

    def test_morning_and_day_do_not(self):
        for bucket in ("morning", "day"):
            self.assertEqual(ball_effect("Dusk Ball", LEGENDARY_RATE,
                                         ThrowContext(time_of_day=bucket)).multiplier, 10, bucket)

    def test_a_cave_matches_at_any_hour(self):
        """The ROM's third condition, and the one that makes the hour irrelevant underground."""
        for bucket in ("morning", "day", "night", ""):
            effect = ball_effect("Dusk Ball", LEGENDARY_RATE,
                                 ThrowContext(terrain=TERRAIN_CAVE, time_of_day=bucket))
            self.assertEqual(effect.multiplier, 35, bucket)
            self.assertIn("cave", effect.reason)

    def test_the_night_bucket_is_the_shared_three_bucket_one(self):
        """The ROM tests NIGHT or LATE_NIGHT and not twilight — hours 20-3, which is exactly the
        three-bucket reading's `night`. That is why there is one time-of-day function, not two
        (notes/platinum.md §4.3)."""
        from claytonlib.safari_encounters import time_of_day
        matching = {hour for hour in range(24) if time_of_day(hour) == DUSK_BALL_BUCKET}
        self.assertEqual(matching, {20, 21, 22, 23, 0, 1, 2, 3})


class TestApricornBalls(unittest.TestCase):

    def test_fast_ball_scales_the_catch_rate_not_the_multiplier(self):
        """The two mechanisms are different: an apricorn ball scales the RATE and clamps."""
        effect = ball_effect("Fast Ball", LEGENDARY_RATE,
                             ThrowContext(target_base_speed=125))
        self.assertEqual(effect.catch_rate, LEGENDARY_RATE * 4)
        self.assertEqual(effect.multiplier, 10)

    def test_fast_ball_needs_base_speed_one_hundred(self):
        """Suicune's 85 misses it, which is the whole reason that target is the hard case."""
        effect = ball_effect("Fast Ball", LEGENDARY_RATE, ThrowContext(target_base_speed=85))
        self.assertEqual(effect.catch_rate, LEGENDARY_RATE)

    def test_apricorn_scaling_is_clamped(self):
        effect = ball_effect("Fast Ball", 200, ThrowContext(target_base_speed=125))
        self.assertEqual(effect.catch_rate, 255)

    def test_unmodelled_rules_say_so_instead_of_returning_x1_silently(self):
        """A silently wrong `b` eliminates the true seed, so an unmodelled rule has to declare
        itself — the same policy `targets.unsupported_moves` applies to moves."""
        for name in ("Level Ball", "Lure Ball", "Heavy Ball", "Moon Ball", "Love Ball"):
            effect = ball_effect(name, LEGENDARY_RATE)
            self.assertEqual(effect.multiplier, 10, name)
            self.assertEqual(effect.catch_rate, LEGENDARY_RATE, name)
            self.assertTrue(effect.unmodelled, f"{name} should declare itself unmodelled")

    def test_the_friend_ball_is_genuinely_x1_rather_than_unmodelled(self):
        """It only affects friendship, so ×1 is the truth and not a fallback."""
        self.assertEqual(ball_effect("Friend Ball", LEGENDARY_RATE).unmodelled, "")


class TestWhatThisChangesForACapture(unittest.TestCase):
    """The figures the solver steers by, so the point of all this is visible."""

    #: A catch-rate-3 target at 1 HP with max HP 150: (multiplier, a, b).
    EXPECTED = ((10, 2, 19784), (20, 5, 24965), (35, 9, 29126), (40, 11, 29958))

    def test_thresholds_for_each_multiplier(self):
        for multiplier, expected_a, expected_b in self.EXPECTED:
            a = catch_value(LEGENDARY_RATE, ball_multiplier=multiplier, cur_hp=1, max_hp=150)
            self.assertEqual(a, expected_a, multiplier)
            self.assertEqual(shake_threshold(a), expected_b, multiplier)

    def test_a_dusk_ball_at_night_is_a_different_stream_geometry(self):
        """`b = 21845` is the figure every HGSS target so far has shared. A conditional ball
        sits somewhere else, which changes how dense capture windows are and therefore how far
        ahead the solver has to look."""
        plain = catch_value(LEGENDARY_RATE, ball_multiplier=10, cur_hp=1, max_hp=150)
        dusk = ball_effect("Dusk Ball", LEGENDARY_RATE,
                           ThrowContext(time_of_day=DUSK_BALL_BUCKET))
        boosted = catch_value(dusk.catch_rate, ball_multiplier=dusk.multiplier,
                              cur_hp=1, max_hp=150)
        self.assertGreater(shake_threshold(boosted), shake_threshold(plain))


if __name__ == "__main__":
    unittest.main()
