"""A target cannot be "configured" and silently mis-simulated at the same time.

`execute_move` has no notion of an unknown effect: an unrecognised status move is treated as
having worked and changed nothing, and an unrecognised damaging move as plain damage. So a
missing secondary is **inert rather than refused** -- and for the target's moves that is unsound
rather than imprecise, because an unnoticed modifier eliminates the true seed.

Adding Ho-Oh to `ENCOUNTERS` is what made this urgent: all four of its Lv70 moves have
unmodelled effects, so without a check it would have looked ready and been confidently wrong on
every turn one of them fired.
"""
import unittest

from claytonlib.battle_compass.sim import MODELLED_TARGET_EFFECTS
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, VERSION_SPLIT_LEVELS, encounter_level, moveset, supported,
    unsupported_moves,
)
from claytonlib.moves import resolve_move


class TestTheCheckFindsWhatIsMissing(unittest.TestCase):
    def test_suicune_is_clean(self):
        """The emulator-verified fixture. If this ever reports a gap, the registry is wrong
        rather than the target."""
        self.assertEqual(unsupported_moves("suicune"), ((), None))

    def test_latias_is_clean(self):
        self.assertEqual(unsupported_moves("latias"), ((), None))

    def test_latios_is_blocked_only_on_protect_now(self):
        """Writing this check is what found Latios mis-simulating at all: it was already a
        configured target with both Protect and Luster Purge unmodelled.

        Luster Purge is done -- its 50% drop is our Sp. DEF, which raises every later special
        hit, so unlike Mist Ball's Sp. Atk drop it was never inert. Protect is not: it needs a
        blocked-move token and an advance count that has to be measured rather than inferred
        (clayton-957.26.2).
        """
        problems, message = unsupported_moves("latios")
        self.assertEqual({name for name, _ in problems}, {"Protect"})
        self.assertIn("cannot be simulated yet", message)

    def test_ho_oh_is_clean_now(self):
        """All four of its Lv70 moves were unmodelled when this check was written: Sacred Fire's
        burn, Punishment's computed power, Ancient Power's self-boost, Safeguard."""
        self.assertEqual(unsupported_moves("ho-oh"), ((), None))

    def test_a_variable_power_move_passes_once_there_is_a_rule_for_it(self):
        """Punishment is power 1, which marks "work it out from state" rather than "unknown
        forever". `unsupported_reason` refuses it by default -- which kept it out of the danger
        floor, and a floor that ignores one of the target's attacks is not a floor -- but the
        check passes `power_known` for the effects that have a rule."""
        from claytonlib.battle_compass.sim import VARIABLE_POWER_EFFECTS

        self.assertEqual(resolve_move("Punishment").power, 1)
        self.assertIn(resolve_move("Punishment").effect, VARIABLE_POWER_EFFECTS)
        self.assertEqual(unsupported_moves("ho-oh"), ((), None))

    def test_a_variable_power_move_with_no_rule_is_still_caught(self):
        """So the `power_known` escape hatch cannot be mistaken for a blanket pass."""
        from claytonlib.battle.damage import unsupported_reason

        seismic = resolve_move("Seismic Toss")
        self.assertEqual(seismic.power, 1)
        self.assertIsNotNone(unsupported_reason(seismic))
        self.assertIsNone(unsupported_reason(seismic, power_known=True))

    def test_a_status_move_dealing_no_damage_is_not_a_gap(self):
        """`unsupported_reason` says "is a status move and deals no damage" for Mist and Rain
        Dance, which is the expected answer rather than a problem."""
        self.assertEqual(unsupported_moves("suicune"), ((), None))
        self.assertIn(resolve_move("Mist").effect, MODELLED_TARGET_EFFECTS)

    def test_it_is_keyed_on_the_effect_not_the_move_name(self):
        """So a new target reusing a modelled effect passes with no list to edit."""
        self.assertIn(resolve_move("Extrasensory").effect, MODELLED_TARGET_EFFECTS)
        self.assertEqual(resolve_move("Extrasensory").effect,
                         resolve_move("Zen Headbutt").effect)

    def test_an_unknown_species_raises_rather_than_passing(self):
        with self.assertRaises(KeyError):
            unsupported_moves("missingno")


class TestHoOhIsConfigured(unittest.TestCase):
    def test_it_is_the_soulsilver_level_and_set(self):
        """`GetGameVersion` then `Compare VAR_SPECIAL_RESULT, 7` / `GoToIfNe` picks Lv45 and the
        fall-through picks Lv70 (scr_seq_0021_D17R0110.s:63-73)."""
        self.assertEqual(encounter_level("ho-oh"), 70)
        self.assertEqual(moveset("ho-oh"),
                         ("Sacred Fire", "Punishment", "Ancient Power", "Safeguard"))

    def test_the_other_version_is_recorded_rather_than_forgotten(self):
        """Ho-Oh is Lv45 in HeartGold with a different moveset. Only one row is on file, so the
        level cross-check is what stops a HeartGold hunt being simulated against four moves its
        Pokemon does not have."""
        self.assertIn("ho-oh", VERSION_SPLIT_LEVELS)
        level, note = VERSION_SPLIT_LEVELS["ho-oh"]
        self.assertEqual(level, 45)
        self.assertIn("different moveset", note)

    def test_every_configured_target_has_a_level_and_four_moves(self):
        for key, row in ENCOUNTERS.items():
            self.assertTrue(1 <= row.level <= 100, key)
            self.assertEqual(len(row.moves), 4, key)
            for move in row.moves:
                self.assertIsNotNone(resolve_move(move), f"{key}: {move}")

    def test_it_is_in_the_supported_list(self):
        self.assertIn("ho-oh", supported())


class TestReadinessRefusesWhatCannotBeSimulated(unittest.TestCase):
    """Hard rather than advisory: running it would mis-predict every turn the move fires on, so
    refusing beats spending an hour of real play on predictions that cannot match."""

    def _target(self, species, level):
        from app.models import HuntTarget

        return HuntTarget(species=species, level=level, nature="Bold",
                          ivs={k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")})

    def test_a_clean_target_passes(self):
        self.assertEqual(self._target("suicune", 40).hard_errors(), [])

    def test_ho_oh_passes_now_that_its_four_mechanics_are_in(self):
        self.assertEqual(self._target("ho-oh", 70).hard_errors(), [])

    def test_latios_is_still_refused_and_names_the_move(self):
        """Protect is genuinely not modelled, so the refusal is correct rather than stale."""
        errors = " ".join(self._target("latios", 40).hard_errors())
        self.assertIn("Protect", errors)

    def test_the_wrong_version_level_is_reported(self):
        errors = " ".join(self._target("ho-oh", 45).hard_errors())
        self.assertIn("Lv70 encounter, not Lv45", errors)
        self.assertIn("HeartGold", errors)

    def test_an_unconfigured_species_is_reported_as_such(self):
        errors = " ".join(self._target("mewtwo", 70).hard_errors())
        self.assertIn("mewtwo", errors)
        self.assertIn("no known encounter", errors)
        # And what the player CAN hunt, which is the half that makes the message actionable.
        self.assertIn("suicune", errors)

    def test_a_target_from_another_game_says_so_rather_than_denying_it_exists(self):
        """The two mistakes need different fixes: a typo and the wrong cartridge.

        A Platinum profile asking for Lugia used to be told it was "not a configured target",
        which is false -- it is configured, for a game this profile is not.
        """
        errors = " ".join(self._target("lugia", 45).hard_errors("platinum"))
        self.assertIn("Platinum", errors)
        self.assertIn("SoulSilver", errors)
        self.assertIn("darkrai", errors)         # what Platinum does have

    def test_an_unset_game_filters_nothing(self):
        """Every profile written before the game field existed has none, and refusing those
        would lock out every hunt that already works."""
        self.assertEqual(self._target("ho-oh", 70).hard_errors(""), [])
        self.assertEqual(self._target("darkrai", 50).hard_errors(""), [])

    def test_the_spread_errors_stay_separate_from_the_encounter_ones(self):
        """`hunt_readiness` gates the derived stats on the SPREAD, so an unsupported encounter
        does not withhold base stats that were perfectly good."""
        target = self._target("mewtwo", 70)
        self.assertEqual(target.spread_errors(), [])
        self.assertTrue(target._encounter_errors())

    def test_an_incomplete_spread_is_still_a_spread_error(self):
        from app.models import HuntTarget

        self.assertTrue(HuntTarget(species="suicune").spread_errors())


if __name__ == "__main__":
    unittest.main()
