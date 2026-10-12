"""The accuracy stage is a transcribed ROM table, not the fraction it looks like.

`sHitChanceTable[13][2]` (src/battle/battle_controller_player.c:2399-2413) is applied as
``hitChance = hitChance * n / d`` (:2490-2491). Two of its thirteen entries are **not** what the
stat-stage-style fraction gives: 3/7 is 42.86 and the table says 43; 3/8 is 37.5 and the table
says 36. Both `battle_compass.sim` and `metronome_compass` had independently computed the
fraction and were therefore independently wrong at the same two stages (clayton-957.27).

These tests exist to make that non-reinventable: the table is asserted entry by entry, and the
two stages that caught it are asserted against the exact figures the old form produced, so a
future "simplification" back to a fraction fails loudly rather than quietly.
"""
import unittest

from claytonlib.battle.damage import (
    GRAVITY_ACCURACY_DEN, GRAVITY_ACCURACY_NUM, HUSTLE_ACCURACY_PERCENT, apply_accuracy_stage,
)
from claytonlib.battle_compass.sim import _effective_accuracy, accuracy_net_stage, can_miss
from claytonlib.moves import resolve_move

#: `sHitChanceTable`, transcribed independently of the implementation so that the test is a
#: second reading of the ROM rather than a copy of the code.
ROM_TABLE = (
    (33, 100), (36, 100), (43, 100), (50, 100), (60, 100), (75, 100), (1, 1),
    (133, 100), (166, 100), (2, 1), (233, 100), (133, 50), (3, 1),
)


def _move(accuracy):
    move = resolve_move("Hydro Pump")
    return type(move)(number=move.number, name=move.name, metronome_usable=False,
                      accuracy=accuracy, category=1)


class TestTheTableIsTheRomTable(unittest.TestCase):
    def test_every_stage_and_every_base_accuracy(self):
        for net in range(-6, 7):
            num, den = ROM_TABLE[net + 6]
            for base in range(1, 101):
                with self.subTest(net=net, base=base):
                    self.assertEqual(apply_accuracy_stage(base, net), base * num // den)

    def test_stages_are_clamped_rather_than_rejected(self):
        """Simple doubles a stage before this point, so the ROM's own clamp has to be here."""
        self.assertEqual(apply_accuracy_stage(100, -12), apply_accuracy_stage(100, -6))
        self.assertEqual(apply_accuracy_stage(100, 99), apply_accuracy_stage(100, 6))


class TestTheTwoStagesThatWereWrong(unittest.TestCase):
    """The regression, named in numbers rather than in prose.

    The old form was ``base * 3 // (3 - net)``. These are the figures it gave and the figures
    the ROM gives, for the moves the Lugia Lv45 hunt actually rolls -- a plan whose Flash x6
    passes through both of these stages on consecutive turns.
    """

    def test_net_minus_five(self):
        for name, base, rom, old in (("Extrasensory", 100, 36, 37),
                                     ("Aeroblast", 95, 34, 35),
                                     ("Hydro Pump", 80, 28, 30),
                                     ("Sing", 55, 19, 20)):
            with self.subTest(name):
                self.assertEqual(apply_accuracy_stage(base, -5), rom)
                self.assertNotEqual(rom, old, "the old computed form, kept as the regression")

    def test_net_minus_four(self):
        self.assertEqual(apply_accuracy_stage(100, -4), 43)
        self.assertNotEqual(43, 100 * 3 // 7, "3/7 floors to 42; the table says 43")

    def test_the_fraction_and_the_table_agree_everywhere_else(self):
        """So the fix is confined to -5 and -4 for a verdict-changing accuracy.

        The +2 and +5 rows also differ by one, and are excluded here rather than fixed up,
        because a hit chance at or above 100 always hits -- they cannot change a verdict.
        """
        for net in (-6, -3, -2, -1, 0, 1, 3, 4, 6):
            for base in (55, 80, 95, 100):
                computed = (base * (3 + net) // 3 if net >= 0 else base * 3 // (3 - net))
                with self.subTest(net=net, base=base):
                    self.assertEqual(apply_accuracy_stage(base, net), computed)


class TestTheCallersDelegate(unittest.TestCase):
    def test_sim_matches_the_table(self):
        for net in range(-6, 7):
            for base in (55, 80, 95, 100):
                with self.subTest(net=net, base=base):
                    self.assertEqual(_effective_accuracy(_move(base), net),
                                     apply_accuracy_stage(base, net))

    def test_accuracy_zero_still_bypasses_the_check(self):
        """0 is the always-hit sentinel and must not go through the table -- Rain Dance and
        Mean Look are accuracy 0, and returning 0 is what skips their accuracy roll."""
        self.assertEqual(_effective_accuracy(_move(0), -6), 0)
        self.assertFalse(can_miss(_move(0), -6))

    def test_metronome_matches_the_table(self):
        """The other caller, which had the same bug. Exercised through the context so the
        delegation is what is tested, not the table a second time."""
        from claytonlib.metronome_compass.context import RngContext
        from claytonlib.metronome_compass.path import MetronomeBattleState

        ctx = RngContext(0x12345678)
        state = MetronomeBattleState()
        ctx.battle_state["state"] = state
        for net in range(-6, 7):
            state.user_accuracy_stage = net
            state.target_evasion_stage = 0
            state.gravity_turns = 0
            with self.subTest(net=net):
                self.assertEqual(ctx.effective_accuracy(80), apply_accuracy_stage(80, net))


class TestOrderAfterTheTable(unittest.TestCase):
    """Gravity is applied LAST and Hustle before it (battle_controller_player.c:2490-2546).

    Gravity used to come first here. Each step truncates, so this is a different number and not
    merely a different spelling.
    """

    def test_hustle_then_gravity_differs_from_gravity_then_hustle(self):
        base = apply_accuracy_stage(55, -1)                     # 41
        rom = base * HUSTLE_ACCURACY_PERCENT // 100
        rom = rom * GRAVITY_ACCURACY_NUM // GRAVITY_ACCURACY_DEN
        reversed_order = base * GRAVITY_ACCURACY_NUM // GRAVITY_ACCURACY_DEN
        reversed_order = reversed_order * HUSTLE_ACCURACY_PERCENT // 100
        self.assertNotEqual(rom, reversed_order,
                            "pick a base where the truncation actually diverges")
        self.assertEqual((rom, reversed_order), (53, 54))

    def test_gravity_is_written_as_the_rom_writes_it(self):
        self.assertEqual((GRAVITY_ACCURACY_NUM, GRAVITY_ACCURACY_DEN), (10, 6))


class TestNetStageIsStillTheAttackerMinusTheDefender(unittest.TestCase):
    def test_an_accuracy_drop_and_an_evasion_boost_are_the_same_figure(self):
        from claytonlib.battle_compass.state import Battler

        lowered = Battler(name="a", level=50, types=("Normal",), stats={},
                          accuracy_stage=-2)
        raised = Battler(name="b", level=50, types=("Normal",), stats={},
                         evasion_stage=2)
        neutral = Battler(name="c", level=50, types=("Normal",), stats={})
        self.assertEqual(accuracy_net_stage(lowered, neutral), -2)
        self.assertEqual(accuracy_net_stage(neutral, raised), -2)


if __name__ == "__main__":
    unittest.main()
