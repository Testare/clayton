"""Lugia Lv45 (SoulSilver, Whirl Islands) in a Love Ball.

Three things this fixes in place, because each was wrong or absent once and each would be
invisible if it went wrong again:

* the **version split runs the opposite way from Ho-Oh's** -- HeartGold gets Lv70 Lugia and
  SoulSilver Lv45, where Ho-Oh is the other way round;
* the **Love Ball is x1 on Lugia**, because it needs the same species AND opposite genders and
  Lugia is genderless. The bead that planned this target originally quoted Fast Ball figures;
* **Aeroblast is effect 43**, so the target is simulatable only once the crit stage exists.

(clayton-957.3)
"""
import unittest

from claytonlib.battle.catch import (
    BALL_POKE, STATUS_NONE, STATUS_PARALYSIS, STATUS_SLEEP, apricorn_catch_rate, catch_value,
    fast_ball_catch_rate, shake_threshold,
)
from claytonlib.battle.stats import derive_species_stats, has_fast_ball_bonus, species
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, VERSION_SPLIT_LEVELS, encounter_level, moveset, unsupported_moves,
)
from claytonlib.moves import resolve_move

#: The spread being hunted, in the project's hp/atk/def/spa/spd/spe order (battle/stats.py).
TARGET_IVS = {"hp": 31, "atk": 31, "def": 31, "spa": 17, "spd": 31, "spe": 31}


class TestTheRow(unittest.TestCase):
    def test_the_soulsilver_moveset_in_learn_order(self):
        self.assertEqual(moveset("lugia"),
                         ("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast"))

    def test_the_level_is_forty_five_not_seventy(self):
        self.assertEqual(encounter_level("lugia"), 45)

    def test_the_version_split_goes_the_opposite_way_from_ho_oh(self):
        """The trap this entry exists for: "SoulSilver gets the Lv70 bird" is true of Ho-Oh and
        false of Lugia, so a note on one row could not have covered both."""
        self.assertEqual(encounter_level("ho-oh"), 70)
        self.assertEqual(VERSION_SPLIT_LEVELS["ho-oh"][0], 45)
        self.assertEqual(encounter_level("lugia"), 45)
        self.assertEqual(VERSION_SPLIT_LEVELS["lugia"][0], 70)

    def test_nothing_in_the_set_is_unmodelled(self):
        self.assertEqual(unsupported_moves("lugia"), ((), None))

    def test_the_name_is_normalised_like_the_other_rows(self):
        self.assertEqual(moveset("Lugia"), moveset("lugia"))


class TestAeroblastWasTheOnlyBlocker(unittest.TestCase):
    def test_it_is_the_high_crit_group(self):
        from claytonlib.battle_compass.sim import HIGH_CRIT_EFFECTS, crit_stage_of

        aeroblast = resolve_move("Aeroblast")
        self.assertEqual(aeroblast.effect, 43)
        self.assertIn(aeroblast.effect, HIGH_CRIT_EFFECTS)
        self.assertEqual(crit_stage_of(aeroblast), 1)

    def test_the_other_three_were_already_covered_or_generic(self):
        self.assertEqual(resolve_move("Rain Dance").effect, 136)    # implemented
        self.assertEqual(resolve_move("Extrasensory").effect, 31)   # flinch, implemented
        self.assertEqual(resolve_move("Hydro Pump").effect, 0)      # generic


class TestTheLoveBallIsTimesOne(unittest.TestCase):
    """`catchRate *= 8` only when ``attacker.species == target.species &&
    attacker.gender != target.gender`` (src/battle/battle_command.c:7295-7300, with a proper
    `break` -- the missing-break fall-through is Fast into Moon, two cases up).

    Lugia is genderless, so the gender test fails even Lugia-against-Lugia. Pinned here so that
    nobody later "fixes" the Love Ball to x8 on the strength of its name.
    """

    def test_lugia_is_catch_rate_three_and_the_ball_does_not_change_it(self):
        self.assertEqual(species("lugia")["catch_rate"], 3)
        self.assertEqual(apricorn_catch_rate(3, multiplier=1), 3)

    def test_the_hunt_config_leaves_it_at_times_one(self):
        """A Love Ball reaches `HuntConfig` as "not a Fast Ball", which is the right answer here
        and is right by fall-through rather than by a rule -- hence the test."""
        config = HuntConfig(target_catch_rate=3, capture_ball_multiplier=BALL_POKE,
                            fast_ball_matched=False)
        self.assertEqual(config.effective_catch_rate(), 3)

    def test_a_standard_ball_probe_is_exactly_as_dangerous(self):
        """The consequence that changes how the run is played: with a x1 capture ball a Poke Ball
        that lands is a lost run, so the probe has to be thrown early, at full HP."""
        config = HuntConfig(target_catch_rate=3, capture_ball_multiplier=BALL_POKE,
                            fast_ball_matched=False)
        self.assertTrue(config.standard_ball_matches_capture_ball())

    def test_a_fast_ball_would_have_applied_which_is_why_the_plan_was_misquoted(self):
        """Lugia's base Speed 110 does clear the Fast Ball threshold -- the x4 is real, it is
        just not what a Love Ball does. This is the figure the bead used to carry."""
        self.assertTrue(has_fast_ball_bonus("lugia"))
        self.assertEqual(fast_ball_catch_rate(3, 110), 12)


class TestTheCatchNumbers(unittest.TestCase):
    """`b` for the thresholds the solver prunes on, so a change to the catch maths that moves
    them is visible as a Lugia-specific number rather than only as a generic one."""

    def setUp(self):
        self.max_hp = derive_species_stats("lugia", 45, "Serious", ivs=TARGET_IVS)["hp"]

    def test_the_spread_gives_164_max_hp(self):
        self.assertEqual(self.max_hp, 164)

    def test_b_at_one_hp(self):
        for status, expected_a, expected_b in ((STATUS_NONE, 2, 19784),
                                               (STATUS_PARALYSIS, 3, 21845),
                                               (STATUS_SLEEP, 4, 23301)):
            with self.subTest(status=status):
                a = catch_value(3, ball_multiplier=BALL_POKE, cur_hp=1, max_hp=self.max_hp,
                                status_bonus=status)
                self.assertEqual((a, shake_threshold(a)), (expected_a, expected_b))

    def test_paralyzed_at_one_hp_matches_suicune_exactly(self):
        """Which is the headline: a Love Ball Lugia is not an easier Suicune, it is the same
        problem. 21845/65536 to the fourth is 1.23% per throw."""
        suicune_hp = derive_species_stats("suicune", 40, "Bold")["hp"]
        lugia = catch_value(3, cur_hp=1, max_hp=self.max_hp, status_bonus=STATUS_PARALYSIS)
        suicune = catch_value(3, cur_hp=1, max_hp=suicune_hp, status_bonus=STATUS_PARALYSIS)
        self.assertEqual(shake_threshold(lugia), shake_threshold(suicune))

    def test_the_status_bonus_is_wasted_at_full_hp(self):
        """With a x1 ball the HP term floors `a` to 1 before the status multiplies it, so
        paralysis buys nothing until the target is actually at 1 HP."""
        full = catch_value(3, cur_hp=self.max_hp, max_hp=self.max_hp,
                           status_bonus=STATUS_PARALYSIS)
        self.assertEqual(full, catch_value(3, cur_hp=self.max_hp, max_hp=self.max_hp,
                                           status_bonus=STATUS_NONE))


class TestTheDerivedTargetIsWhatThePlanAssumed(unittest.TestCase):
    def test_the_spread(self):
        self.assertEqual(
            derive_species_stats("lugia", 45, "Serious", ivs=TARGET_IVS),
            {"hp": 164, "atk": 99, "def": 135, "spa": 93, "spd": 157, "spe": 117})

    def test_every_attack_is_special_so_our_defence_never_matters(self):
        """Which is why Reflect and X Defend do nothing against this target, unlike Ho-Oh where
        two of three attacks are physical."""
        from claytonlib.moves import CATEGORY_SPECIAL, CATEGORY_STATUS

        for name in moveset("lugia"):
            move = resolve_move(name)
            with self.subTest(name):
                self.assertIn(move.category, (CATEGORY_SPECIAL, CATEGORY_STATUS))

    def test_a_smeargle_outspeeds_every_reachable_spread(self):
        """No Thunder Wave race and no speed tie: the Lv45 set has no Safeguard, and 160 clears
        Lugia's ceiling even with a boosting nature."""
        fastest = derive_species_stats("lugia", 45, "Timid", ivs=31)["spe"]
        self.assertLess(fastest, 160)

    def test_pressure_is_derived_rather_than_defaulted(self):
        from claytonlib.battle.stats import has_pressure

        self.assertTrue(has_pressure("lugia"))


if __name__ == "__main__":
    unittest.main()
