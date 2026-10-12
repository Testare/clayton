"""High-crit moves start one crit stage up, so they land on ``% 8`` rather than ``% 16``.

`execute_move` read `CRIT_MODIFIERS[0]` unconditionally, which made every effect-43 move crit
half as often as the game does -- and wrong in two ways on the same turn, because a crit also
doubles the damage. Aeroblast is in both Lugia movesets, so this was the single reason
`targets.unsupported_moves('lugia')` refused the Lv45 set (clayton-957.2).

The effect ids are cross-validated against `metronome_compass.effects`, which resolves all three
through ``hit_crit_or_miss(..., crit_stage=1)`` and is verified against Blackthorn ground truth.
That cross-check is itself a test here, so the two modules cannot drift apart silently.
"""
import unittest

from claytonlib.battle_compass.sim import (
    CRIT_MODIFIERS, HIGH_CRIT_EFFECTS, MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS,
    crit_stage_of, execute_move, move_roll_cost,
)
from claytonlib.battle_compass.state import Battler
from claytonlib.moves import resolve_move

#: Every effect-43 move in the table, so a data change that drops one is visible.
EFFECT_43_MOVES = (
    "Karate Chop", "Razor Leaf", "Crabhammer", "Slash", "Aeroblast", "Cross Chop",
    "Air Cutter", "Leaf Blade", "Night Slash", "Shadow Claw", "Psycho Cut", "Stone Edge",
    "Attack Order", "Spacial Rend",
)


def _lugia():
    from claytonlib.battle.stats import derive_species_stats
    return Battler(
        name="Lugia", level=45, types=("Psychic", "Flying"),
        stats=derive_species_stats("lugia", 45, "Serious",
                                   ivs={"hp": 31, "atk": 31, "def": 31,
                                        "spa": 17, "spd": 31, "spe": 31}),
        moves=("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast"),
        pp=(30, 5, 5, 5), ability="Pressure")


def _smeargle():
    return Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15), ability="Technician", held_item="Silk Scarf")


class TestTheGroup(unittest.TestCase):
    def test_the_ids_match_metronome_compass(self):
        """The cross-validation, asserted rather than written in a comment.

        `metronome_compass` is the RNG-verified module; if it gains or loses a high-crit handler
        this fails and the two are reconciled deliberately.
        """
        from claytonlib.metronome_compass import effects

        theirs = {eid for eid, fn in effects.EFFECT_HANDLERS.items()
                  if fn in (effects._eff_high_crit, effects._eff_burn_highcrit,
                            effects._eff_poison_highcrit)}
        self.assertEqual(theirs, set(HIGH_CRIT_EFFECTS))

    def test_every_effect_43_move_is_in_the_group(self):
        for name in EFFECT_43_MOVES:
            with self.subTest(name):
                self.assertEqual(resolve_move(name).effect, 43)
                self.assertEqual(crit_stage_of(resolve_move(name)), 1)

    def test_an_ordinary_damaging_move_stays_at_stage_zero(self):
        for name in ("Hydro Pump", "Extrasensory", "False Swipe"):
            with self.subTest(name):
                self.assertEqual(crit_stage_of(resolve_move(name)), 0)

    def test_the_stage_is_capped_at_the_tables_top_entry(self):
        class Boosted:
            crit_stage = 99
        self.assertEqual(crit_stage_of(resolve_move("Aeroblast"), Boosted()),
                         len(CRIT_MODIFIERS) - 1)

    def test_a_battler_without_a_crit_stage_contributes_nothing(self):
        """`Battler` carries no crit stage -- nothing in any configured party has a Focus Energy
        or a Scope Lens -- so the attacker term must be read defensively, not required."""
        self.assertEqual(crit_stage_of(resolve_move("Aeroblast"), _smeargle()), 1)
        self.assertEqual(crit_stage_of(resolve_move("Aeroblast"), None), 1)


class TestTheModulusActuallyChanges(unittest.TestCase):
    def test_aeroblast_crits_on_eight_and_hydro_pump_on_sixteen(self):
        self.assertEqual(CRIT_MODIFIERS[crit_stage_of(resolve_move("Aeroblast"))], 8)
        self.assertEqual(CRIT_MODIFIERS[crit_stage_of(resolve_move("Hydro Pump"))], 16)

    def test_the_rolls_that_used_to_be_wrong_now_crit(self):
        """The regression, stated as the disagreement itself: a crit roll with
        ``% 8 == 0 and % 16 != 0`` is a crit the old code called an ordinary hit.

        Driven through `execute_move` against a real stream rather than asserted on the helper,
        because the call site is what was broken.
        """
        lugia, smeargle = _lugia(), _smeargle()
        aeroblast = resolve_move("Aeroblast")
        found = 0
        for seed in range(0x1000, 0x80000, 0x97):
            # `execute_move` takes the crit roll FIRST, so the seed one advance back from a
            # chosen high-16 value puts that value in the crit slot.
            from claytonlib.safari import advance_rng
            crit_roll = advance_rng(seed) >> 16
            if crit_roll % 16 == 0 or crit_roll % 8 != 0:
                continue
            found += 1
            _, outcome = execute_move(seed, aeroblast, lugia, smeargle, actor="E", slot=3)
            if outcome.successful:
                self.assertIn("!", "".join(outcome.tokens),
                              f"crit roll {crit_roll} is % 8 == 0 and should be a crit")
            if found >= 12:
                break
        self.assertGreaterEqual(found, 12, "the sweep found too few qualifying rolls")

    def test_an_ordinary_move_on_the_same_rolls_does_not_crit(self):
        """The other half: those same rolls must stay ordinary hits for a stage-0 move, or the
        change has moved something it should not have."""
        from claytonlib.safari import advance_rng

        lugia, smeargle = _lugia(), _smeargle()
        hydro = resolve_move("Hydro Pump")
        checked = 0
        for seed in range(0x1000, 0x80000, 0x97):
            crit_roll = advance_rng(seed) >> 16
            if crit_roll % 16 == 0 or crit_roll % 8 != 0:
                continue
            _, outcome = execute_move(seed, hydro, lugia, smeargle, actor="E", slot=2)
            if outcome.successful:
                self.assertNotIn("!", "".join(outcome.tokens))
                checked += 1
            if checked >= 12:
                break
        self.assertGreaterEqual(checked, 12)


class TestItMovesNoAdvanceCounts(unittest.TestCase):
    """The reason this fix is safe: the high-crit group spends the same rolls.

    ``metronome_compass``'s `_eff_high_crit` says so in its docstring ("same RNG roll count as
    standard"), and that is what keeps a verified advance count out of this change.
    """

    def test_the_roll_cost_is_unchanged_by_the_stage(self):
        self.assertEqual(move_roll_cost(resolve_move("Aeroblast")),
                         move_roll_cost(resolve_move("Hydro Pump")))

    def test_execute_move_spends_the_same_rolls_either_way(self):
        lugia, smeargle = _lugia(), _smeargle()
        _, high = execute_move(0x2468ACE0, resolve_move("Aeroblast"), lugia, smeargle,
                               actor="E", slot=3)
        _, plain = execute_move(0x2468ACE0, resolve_move("Stone Edge"), lugia, smeargle,
                                actor="E", slot=3)
        # Stone Edge is also effect 43 and also accuracy 80-95, so this is the control for the
        # accuracy roll rather than for the stage.
        self.assertEqual(high.rolls, plain.rolls)


class TestLugiaIsNowSimulatable(unittest.TestCase):
    def test_effect_43_is_declared_modelled_on_both_sides(self):
        self.assertIn(43, MODELLED_TARGET_EFFECTS)
        self.assertIn(43, MODELLED_OUR_EFFECTS)

    def test_aeroblast_no_longer_reads_as_unmodelled(self):
        """The specific refusal this unblocks. Asserted on the move rather than on the Lugia row
        so that it holds before that row exists."""
        from claytonlib.battle.damage import unsupported_reason

        aeroblast = resolve_move("Aeroblast")
        self.assertIn(aeroblast.effect, MODELLED_TARGET_EFFECTS)
        self.assertIsNone(unsupported_reason(aeroblast))


if __name__ == "__main__":
    unittest.main()
