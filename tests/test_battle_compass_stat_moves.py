"""Every status move whose whole job is a stat stage, modelled as one family.

The ROM makes this a family rather than a list. Scan `res/battle/scripts/effects` for a script
that is exactly one `UpdateVar ... MOVE_SIDE_EFFECT_{TO_ATTACKER,TO_DEFENDER}|
MOVE_SUBSCRIPT_PTR_<stat>_<UP|DOWN>_<n>_STAGE(S)` followed by `End`, and 23 effect ids come back
covering 33 moves. Every one of them resolves to `subscript_update_stat_stage`
(include/data/move_side_effect_subscripts.h:22-57), contains no `Random`, and lands in one of
`PRIMARY_SELF_RAISES` / `PRIMARY_STAT_DROPS`.

**The ceiling and the floor are the whole subtlety, and the simulator had one half of it wrong.**
`BtlCmd_ChangeStatStage` (battle_script.c:2804-2975) takes `jumpNoChange` when the stat cannot
move, which for a DIRECT side effect prints "{0}'s {1} won't go higher/lower!" and ends — setting
**no status flag**. Only the Substitute branch sets `MOVE_STATUS_FAILED`. So a stat change that
cannot happen is still a successful move and still costs the two post-successful-move advances.

That is measured, on the drop half: `data/battle_logs/hooh1.jsonl` turns 34-37 are four Sweet
Scents against an evasion already at -6, each spending the full 15 rolls. Modelling them as
failures costs turn 34 two advances and desynchronises the rest of the log. The raise half runs
the identical instruction with the sign flipped, which is why `will_fail` no longer claims a +6
Nasty Plot fails — it used to, and that was wrong by two advances a turn.

**The two-stat moves are the exception and go the other way.** Bulk Up, Calm Mind, Cosmic Power,
Dragon Dance and Tickle each have a subscript of their own that tests *every* stat before calling
`ChangeStatStage` at all, and sets `MOVE_STATUS_NO_MORE_WORK` when none of them can move
(`subscript_user_atk_and_def_up_1_stage.s` `_046` and its four siblings). That flag routes to
`LOOP_SPREAD_MOVES` and skips `USE_MOVE` whole, so those really do fail. [derived — nothing in a
configured moveset can reach it, since it needs every one of a two-stat move's stats at the
limit.]

(clayton-4wr.1.7)
"""
import unittest
from dataclasses import replace

from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import move_info, reachable_defensive_drops
from claytonlib.battle_compass.sim import (
    MODELLED_OUR_EFFECTS, MULTI_STAT_EFFECTS, PRIMARY_SELF_RAISES, PRIMARY_STAT_DROPS,
    SECONDARY_STAT_DROPS, STAT_STAGE_CEILING, STAT_STAGE_FLOOR, HuntConfig, apply_stat_drop,
    apply_stat_raise, execute_move, move_roll_cost, opening_rng, primary_self_raise,
    primary_stat_drop, simulate_turn, unselectable_reason, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.moves import resolve_move

#: Every pure stat-stage effect, as read off the ROM's effect scripts, with the moves that use it.
#: Transcribed rather than derived so a change to either table has to be noticed here.
FAMILY: dict[int, tuple[str, tuple[tuple[str, int], ...], tuple[str, ...]]] = {
    # effect: (who it lands on, the pairs, the moves that have it)
    10:  ("self",   (("atk_stage", 1),),    ("Meditate", "Sharpen", "Howl")),
    11:  ("self",   (("def_stage", 1),),    ("Harden", "Withdraw")),
    13:  ("self",   (("spatk_stage", 1),),  ("Growth",)),
    16:  ("self",   (("evasion_stage", 1),), ("Double Team",)),
    50:  ("self",   (("atk_stage", 2),),    ("Swords Dance",)),
    51:  ("self",   (("def_stage", 2),),    ("Barrier", "Acid Armor", "Iron Defense")),
    52:  ("self",   (("speed_stage", 2),),  ("Agility", "Rock Polish")),
    53:  ("self",   (("spatk_stage", 2),),  ("Tail Glow", "Nasty Plot")),
    54:  ("self",   (("spdef_stage", 2),),  ("Amnesia",)),
    206: ("self",   (("def_stage", 1), ("spdef_stage", 1)), ("Cosmic Power", "Defend Order")),
    208: ("self",   (("atk_stage", 1), ("def_stage", 1)), ("Bulk Up",)),
    211: ("self",   (("spatk_stage", 1), ("spdef_stage", 1)), ("Calm Mind",)),
    212: ("self",   (("atk_stage", 1), ("speed_stage", 1)), ("Dragon Dance",)),
    18:  ("target", (("atk_stage", 1),),    ("Growl",)),
    19:  ("target", (("def_stage", 1),),    ("Tail Whip", "Leer")),
    20:  ("target", (("speed_stage", 1),),  ("String Shot",)),
    23:  ("target", (("accuracy_stage", 1),),
         ("Sand Attack", "Smoke Screen", "Kinesis", "Flash")),
    24:  ("target", (("evasion_stage", 1),), ("Sweet Scent",)),
    58:  ("target", (("atk_stage", 2),),    ("Charm", "Feather Dance")),
    59:  ("target", (("def_stage", 2),),    ("Screech",)),
    60:  ("target", (("speed_stage", 2),),  ("Cotton Spore", "Scary Face")),
    62:  ("target", (("spdef_stage", 2),),  ("Fake Tears", "Metal Sound")),
    205: ("target", (("atk_stage", 1), ("def_stage", 1)), ("Tickle",)),
}


def _ours(**kwargs) -> Battler:
    return replace(Battler(
        name="Us", level=60, types=("Normal",),
        stats={"hp": 200, "atk": 120, "def": 100, "spa": 90, "spd": 95, "spe": 110},
        moves=(), pp=()), **kwargs)


def _target(**kwargs) -> Battler:
    return replace(Battler(
        name="Azelf", level=50, types=("Psychic",),
        stats={"hp": 138, "atk": 136, "def": 89, "spa": 135, "spd": 71, "spe": 132},
        moves=("Swift",), pp=(20,), ability="Levitate"), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestTheFamilyIsComplete(unittest.TestCase):

    def test_every_effect_is_in_exactly_one_table(self):
        for effect, (whose, pairs, _) in FAMILY.items():
            with self.subTest(effect=effect):
                table = PRIMARY_SELF_RAISES if whose == "self" else PRIMARY_STAT_DROPS
                other = PRIMARY_STAT_DROPS if whose == "self" else PRIMARY_SELF_RAISES
                self.assertEqual(table.get(effect), pairs)
                self.assertNotIn(effect, other)

    def test_every_move_in_the_family_resolves_to_its_effect(self):
        """The join the other direction: a move whose effect id drifted would silently stop being
        covered, and the table would still look full."""
        for effect, (_, _, names) in FAMILY.items():
            for name in names:
                with self.subTest(name):
                    self.assertEqual(resolve_move(name).effect, effect)

    def test_no_table_row_is_still_a_bare_pair(self):
        """The shape changed when the two-stat moves went in. A row left as `("atk_stage", 2)`
        would iterate as two one-character field names and apply nothing."""
        for table in (PRIMARY_SELF_RAISES, PRIMARY_STAT_DROPS, SECONDARY_STAT_DROPS):
            for effect, pairs in table.items():
                with self.subTest(effect=effect):
                    self.assertIsInstance(pairs, tuple)
                    for pair in pairs:
                        self.assertIsInstance(pair, tuple)
                        field, stages = pair
                        self.assertTrue(hasattr(_ours(), field), field)
                        self.assertIn(stages, (1, 2))

    def test_every_one_of_them_is_reported_as_modelled_for_our_side(self):
        """Listed exhaustively rather than as the ones a party happens to carry: the family costs
        the same nothing and reaches the same tables, so a player who brings Bulk Up should not
        be told it is unmodelled because nobody had typed it."""
        for effect, (_, _, names) in FAMILY.items():
            with self.subTest(effect=effect):
                self.assertIn(effect, MODELLED_OUR_EFFECTS)
                self.assertIsNone(unselectable_reason(resolve_move(names[0])))

    def test_the_multi_stat_set_is_exactly_the_two_stat_rows(self):
        both = {**PRIMARY_SELF_RAISES, **PRIMARY_STAT_DROPS}
        self.assertEqual(MULTI_STAT_EFFECTS,
                         frozenset(e for e, pairs in both.items() if len(pairs) > 1))


class TestWhatTheyCost(unittest.TestCase):

    def test_a_self_raise_spends_nothing_at_all(self):
        """Accuracy 0 and no `Random` in the subscript."""
        for effect, (whose, _, names) in FAMILY.items():
            if whose != "self":
                continue
            move = resolve_move(names[0])
            with self.subTest(names[0]):
                self.assertEqual(move.accuracy, 0)
                self.assertEqual(move_roll_cost(move), 0)
                rng = 0x0C0E02CA
                after, outcome = execute_move(rng, move, _ours(), _target(),
                                              actor="M", slot=0)
                self.assertEqual(outcome.rolls, 0)
                self.assertEqual(after, rng)
                self.assertTrue(outcome.successful)

    def test_a_target_drop_spends_only_its_accuracy_roll(self):
        """These have real accuracies, so they always did spend one -- what is new is that the
        drop now lands."""
        for effect, (whose, _, names) in FAMILY.items():
            if whose != "target":
                continue
            move = resolve_move(names[0])
            with self.subTest(names[0]):
                self.assertGreater(move.accuracy, 0)
                self.assertEqual(move_roll_cost(move), 1)

    def test_they_render_as_the_bare_slot(self):
        """A status move that lands has no hit marker, so the interview must not ask about crits
        or damage."""
        for effect, (whose, _, names) in FAMILY.items():
            move = resolve_move(names[0])
            with self.subTest(names[0]):
                _, outcome = execute_move(0x0C0E02CA, move, _ours(), _target(),
                                          actor="M", slot=0)
                self.assertEqual(outcome.tokens[0], "M1")
                self.assertNotIn(tok.HIT, outcome.tokens)
                self.assertNotIn(tok.CRIT, outcome.tokens)


class TestTheyActuallyMoveTheStages(unittest.TestCase):

    def test_a_self_raise_lands_on_the_user(self):
        config = _config()
        for effect, (whose, pairs, names) in FAMILY.items():
            if whose != "self":
                continue
            with self.subTest(names[0]):
                ours = _ours(moves=(names[0],), pp=(20,))
                state = BattleState(ours=ours, target=_target(),
                                    rng=opening_rng(0x0C0E02CA, config))
                after = simulate_turn(state, Action.MOVE_1, config)
                for field, stages in pairs:
                    self.assertEqual(getattr(after.ours, field), stages, field)
                    self.assertEqual(getattr(after.target, field), 0,
                                     f"{field} moved on the wrong side")

    def test_a_target_drop_lands_on_the_target(self):
        config = _config()
        for effect, (whose, pairs, names) in FAMILY.items():
            if whose != "target":
                continue
            with self.subTest(names[0]):
                ours = _ours(moves=(names[0],), pp=(20,))
                state = BattleState(ours=ours, target=_target(),
                                    rng=opening_rng(0x0C0E02CA, config))
                after = simulate_turn(state, Action.MOVE_1, config)
                for field, stages in pairs:
                    self.assertEqual(getattr(after.target, field), -stages, field)
                    self.assertEqual(getattr(after.ours, field), 0,
                                     f"{field} moved on the wrong side")

    def test_a_two_stat_move_moves_both_and_nothing_else(self):
        """Dragon Dance is Attack AND Speed. Applying only the first pair is the failure mode the
        tuple shape exists to prevent."""
        config = _config()
        ours = _ours(moves=("Dragon Dance",), pp=(20,))
        state = BattleState(ours=ours, target=_target(), rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual((after.ours.atk_stage, after.ours.speed_stage), (1, 1))
        self.assertEqual((after.ours.def_stage, after.ours.spatk_stage,
                          after.ours.spdef_stage), (0, 0, 0))

    def test_the_helpers_clamp_each_pair_independently(self):
        """One stat at the limit does not stop the other moving, which is what the ROM does: the
        two-stat subscripts call `ChangeStatStage` once per stat."""
        raised = apply_stat_raise(_ours(atk_stage=6), PRIMARY_SELF_RAISES[208])
        self.assertEqual((raised.atk_stage, raised.def_stage), (STAT_STAGE_CEILING, 1))
        dropped = apply_stat_drop(_target(atk_stage=-6), PRIMARY_STAT_DROPS[205])
        self.assertEqual((dropped.atk_stage, dropped.def_stage), (STAT_STAGE_FLOOR, -1))


class TestTheCeilingAndTheFloor(unittest.TestCase):
    """The half the simulator had backwards. See this module's docstring for the evidence."""

    def test_a_single_stat_raise_at_the_ceiling_does_not_fail(self):
        for effect, (whose, pairs, names) in FAMILY.items():
            if whose != "self" or effect in MULTI_STAT_EFFECTS:
                continue
            field, _ = pairs[0]
            with self.subTest(names[0]):
                maxed = _ours(**{field: STAT_STAGE_CEILING})
                self.assertFalse(will_fail(resolve_move(names[0]), _target(), actor=maxed))

    def test_a_single_stat_drop_at_the_floor_does_not_fail(self):
        for effect, (whose, pairs, names) in FAMILY.items():
            if whose != "target" or effect in MULTI_STAT_EFFECTS:
                continue
            field, _ = pairs[0]
            with self.subTest(names[0]):
                floored = _target(**{field: STAT_STAGE_FLOOR})
                self.assertFalse(will_fail(resolve_move(names[0]), floored))

    def test_the_wasted_turn_costs_exactly_what_the_useful_one_did(self):
        """The measurement, restated as a comparison the simulator can make. Two fewer advances
        is what the old model claimed and what hooh1 turns 34-37 disprove."""
        config = _config()
        ours = _ours(moves=("Swords Dance",), pp=(20,))
        useful = simulate_turn(
            BattleState(ours=ours, target=_target(), rng=opening_rng(0x0C0E02CA, config)),
            Action.MOVE_1, config)
        wasted = simulate_turn(
            BattleState(ours=replace(ours, atk_stage=6), target=_target(),
                        rng=opening_rng(0x0C0E02CA, config)),
            Action.MOVE_1, config)
        self.assertEqual(useful.rng_offset, wasted.rng_offset)
        self.assertEqual(wasted.ours.atk_stage, STAT_STAGE_CEILING)

    def test_a_two_stat_move_fails_only_when_EVERY_stat_is_at_the_limit(self):
        """Its own subscript tests all of them before reaching `ChangeStatStage`, so one stat
        still free means the move runs."""
        bulk_up = resolve_move("Bulk Up")
        self.assertFalse(will_fail(bulk_up, _target(), actor=_ours(atk_stage=6)))
        self.assertFalse(will_fail(bulk_up, _target(), actor=_ours(def_stage=6)))
        self.assertTrue(will_fail(bulk_up, _target(),
                                  actor=_ours(atk_stage=6, def_stage=6)))

    def test_tickle_is_the_same_rule_with_the_sign_flipped(self):
        tickle = resolve_move("Tickle")
        self.assertFalse(will_fail(tickle, _target(atk_stage=-6)))
        self.assertFalse(will_fail(tickle, _target(def_stage=-6)))
        self.assertTrue(will_fail(tickle, _target(atk_stage=-6, def_stage=-6)))

    def test_a_two_stat_failure_really_does_cost_two_fewer_advances(self):
        config = _config()
        ours = _ours(moves=("Bulk Up",), pp=(20,))
        lands = simulate_turn(
            BattleState(ours=replace(ours, atk_stage=6), target=_target(),
                        rng=opening_rng(0x0C0E02CA, config)), Action.MOVE_1, config)
        fails = simulate_turn(
            BattleState(ours=replace(ours, atk_stage=6, def_stage=6), target=_target(),
                        rng=opening_rng(0x0C0E02CA, config)), Action.MOVE_1, config)
        self.assertEqual(lands.rng_offset - fails.rng_offset, 2)


class TestTheInterviewAndTheFloorReadThemAll(unittest.TestCase):

    def test_move_info_publishes_every_pair_both_ways(self):
        ours = _ours(moves=("Dragon Dance", "Tickle"), pp=(20, 20))
        info = {m["name"]: m for m in move_info(ours, _target())}
        self.assertEqual(info["Dragon Dance"]["self_raise"],
                         [{"stat": "atk", "stages": 1}, {"stat": "spe", "stages": 1}])
        self.assertIsNone(info["Dragon Dance"]["stat_drop"])
        self.assertEqual(info["Tickle"]["stat_drop"],
                         [{"stat": "atk", "stages": 1}, {"stat": "def", "stages": 1}])
        self.assertIsNone(info["Tickle"]["self_raise"])

    def test_the_helpers_agree_with_the_tables(self):
        self.assertEqual(primary_self_raise(resolve_move("Calm Mind")),
                         PRIMARY_SELF_RAISES[211])
        self.assertEqual(primary_stat_drop(resolve_move("Tickle")), PRIMARY_STAT_DROPS[205])
        self.assertIsNone(primary_self_raise(resolve_move("Tickle")))
        self.assertIsNone(primary_stat_drop(resolve_move("Calm Mind")))

    def test_a_two_stat_drop_moves_the_defensive_floor_for_both_stages(self):
        """`reachable_defensive_drops` read only the FIRST pair, which would have priced us at
        the wrong floor for a target holding a two-stat drop."""
        tickler = _target(moves=("Tickle",), pp=(20,))
        self.assertEqual(reachable_defensive_drops(_ours(), tickler),
                         (STAT_STAGE_FLOOR, 0))
        screecher = _target(moves=("Screech", "Metal Sound"), pp=(20, 20))
        self.assertEqual(reachable_defensive_drops(_ours(), screecher),
                         (STAT_STAGE_FLOOR, STAT_STAGE_FLOOR))


if __name__ == "__main__":
    unittest.main()
