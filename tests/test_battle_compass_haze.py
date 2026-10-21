"""Haze, the cheapest move in the alphabet, and the one that undoes our own work.

`effect_script_0025.s` is a single `MOVE_SIDE_EFFECT_ON_HIT|MOVE_SUBSCRIPT_PTR_RESET_ALL_STAT_STAGES`
and `subscript_reset_all_stat_stages.s` is `ResetAllStatChanges` plus a message. No Random
anywhere, and Haze's accuracy is 0, so **the move itself spends zero rolls** -- which makes the
turn cost 2, the post-successful-move block every successful move earns, against Flash's 3 and
Taunt's 4. The cheapest move in the alphabet, though not as cheap as a bag action.

`BtlCmd_ResetAllStatChanges` (battle_script.c:3535-3549) loops EVERY battler and sets every one of
its `statBoosts` back to neutral. Which is the whole difficulty: it undoes Giratina's Ancient
Power boosts and our own six Flashes in the same breath, and being the cheapest move there is,
Dijkstra would plan it as filler. Hence `solver.undoes_our_own_work` -- a refusal on the PLAN
that leaves the move fully available to the player, because there are real states where losing
the accuracy work is the right trade.

It also brought `Move.range_id` with it. Haze is RANGE_FIELD, which the ROM points back at its own
user, and that turned out to matter for a whole family of our moves -- see
`TestASelfAimedMoveReachesPastAVanishedTarget`.

(clayton-4wr.1.1)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import STAGE_FIELDS
from claytonlib.battle_compass.sim import (
    EFFECT_HAZE, MODELLED_OUR_EFFECTS, STAGE_FIELD_NAMES, HuntConfig, execute_move,
    is_semi_invulnerable, move_roll_cost, opening_rng, reset_stages, sent_out, simulate_turn,
    unselectable_reason, will_fail,
)
from claytonlib.battle_compass.solver import (
    SolverConfig, _legal_actions, undoes_our_own_work,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import moveset, stats_key, target_ability
from claytonlib.moves import (
    RANGE_FIELD, RANGE_SINGLE_TARGET, RANGE_USER, RANGE_USER_SIDE, resolve_move,
)

HAZE = resolve_move("Haze")
SEEDS = range(0x0C0E0200, 0x0C0E0220)

#: Every stage set to something, so a reset has something to do in all seven.
BOOSTED = {"atk_stage": 2, "def_stage": -1, "spatk_stage": 5, "spdef_stage": 3,
           "speed_stage": 6, "accuracy_stage": -6, "evasion_stage": 4}


def _target(name: str, level: int = 50, **kwargs) -> Battler:
    key = stats_key(name)
    moves = moveset(name)
    return replace(Battler(
        name=name, level=level, types=tuple(species(key)["types"]),
        stats=derive_species_stats(key, level, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability(name)), **kwargs)


def _honchkrow(**kwargs) -> Battler:
    return replace(Battler(
        name="Honchkrow", level=55, types=("Dark", "Flying"), ability="Insomnia",
        stats={"hp": 250, "atk": 150, "def": 90, "spa": 120, "spd": 95, "spe": 110},
        moves=("Haze", "Taunt"), pp=(30, 20)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestWhatItCosts(unittest.TestCase):

    def test_the_move_itself_spends_no_rolls(self):
        """Accuracy 0 so no accuracy roll, and the subscript has no Random. The only move in the
        project whose own cost is nothing -- see the turn-cost test below for why that is still
        not a free turn."""
        self.assertEqual(move_roll_cost(HAZE), 0)
        self.assertEqual(HAZE.accuracy, 0)
        rng = 0x0C0E02CA
        after, outcome = execute_move(rng, HAZE, _honchkrow(), _target("uxie"),
                                      actor="M", slot=0)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertTrue(outcome.successful)
        self.assertTrue(outcome.resets_all_stages)

    def test_a_second_one_succeeds_rather_than_failing(self):
        """There is no "already hazed" check anywhere in the subscript -- unlike Mist, Safeguard,
        Water Sport and the screens, all of which fail when re-used."""
        self.assertFalse(will_fail(HAZE, _target("uxie")))
        state = BattleState(ours=_honchkrow(), target=_target("uxie"), rng=0)
        self.assertFalse(will_fail(HAZE, state.target, state, actor=state.ours))

    def test_it_renders_as_the_bare_slot(self):
        _, outcome = execute_move(0x0C0E02CA, HAZE, _honchkrow(), _target("uxie"),
                                  actor="M", slot=0)
        self.assertEqual(outcome.tokens, ("M1",))

    def test_it_is_listed_as_modelled_for_our_side_only(self):
        """No configured target has it; the `act_target` mirror is wired for symmetry."""
        self.assertIn(EFFECT_HAZE, MODELLED_OUR_EFFECTS)
        self.assertIsNone(unselectable_reason(HAZE))


class TestItResetsBothSides(unittest.TestCase):

    def test_the_helper_clears_every_stage(self):
        cleared = reset_stages(replace(_honchkrow(), **BOOSTED))
        for field in STAGE_FIELD_NAMES:
            with self.subTest(field):
                self.assertEqual(getattr(cleared, field), 0)

    def test_the_stage_list_is_complete_for_the_Battler(self):
        """A stage added to `Battler` and forgotten here would survive a Haze AND a switch,
        silently. The dataclass is the authority, so the list is checked against it."""
        on_battler = {name for name in vars(_honchkrow()) if name.endswith("_stage")}
        self.assertEqual(on_battler, set(STAGE_FIELD_NAMES))

    def test_it_agrees_with_the_UI_label_table(self):
        """`hunt_session.STAGE_FIELDS` is the same seven paired with display labels, and keeps its
        own name because labels are a presentation concern the simulator should not carry. Pinned
        against each other rather than derived, so neither can grow a field alone."""
        self.assertEqual(set(STAGE_FIELD_NAMES), {field for _, field in STAGE_FIELDS})

    def test_a_send_out_and_a_haze_clear_the_same_set(self):
        boosted = replace(_honchkrow(), **BOOSTED)
        hazed, switched = reset_stages(boosted), sent_out(boosted)
        for field in STAGE_FIELD_NAMES:
            with self.subTest(field):
                self.assertEqual(getattr(hazed, field), getattr(switched, field))

    def test_using_it_resets_the_target_AND_us(self):
        config = _config()
        state = BattleState(ours=replace(_honchkrow(), spdef_stage=4),
                            target=_target("uxie", pp=(0, 0, 0, 0), spatk_stage=6,
                                           accuracy_stage=-6),
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.target.spatk_stage, 0)
        self.assertEqual(state.target.accuracy_stage, 0)       # our own Flash work, gone with it
        self.assertEqual(state.ours.spdef_stage, 0)

    def test_it_leaves_status_and_the_volatiles_alone(self):
        """`BtlCmd_ResetAllStatChanges` touches `statBoosts` and Focus Energy and nothing else --
        not status, not the other volatiles, not field conditions."""
        config = _config()
        target = _target("uxie", pp=(0, 0, 0, 0), hp=1, status=Status.PARALYSIS, spatk_stage=3)
        state = BattleState(ours=_honchkrow(drowsy_turns=1), target=target,
                            rng=opening_rng(0x0C0E02CA, config), rain_turns=3, mist_turns=2)
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertIs(state.target.status, Status.PARALYSIS)
        self.assertEqual(state.target.spatk_stage, 0)
        # The durations tick by one at end of turn as they always do, and Haze does not touch them.
        self.assertEqual((state.rain_turns, state.mist_turns), (2, 1))

    def test_it_is_how_a_giratina_at_plus_six_gets_answered(self):
        """The reason to carry it at all. Ancient Power's 10% raises every one of Giratina's
        stats, Speed included -- and Speed at +6 cancels paralysis's quartering exactly, which is
        the no-speed-tie guarantee gone."""
        config = _config()
        boosted = _target("giratina-altered", level=47, pp=(0, 0, 0, 0),
                          atk_stage=6, spatk_stage=6, speed_stage=6, def_stage=6, spdef_stage=6)
        state = BattleState(ours=_honchkrow(), target=boosted,
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_1, config)
        for field in STAGE_FIELD_NAMES:
            with self.subTest(field):
                self.assertEqual(getattr(state.target, field), 0)


class TestTheSolverWillNotPlanItAwayFromUs(unittest.TestCase):
    """Zero rolls makes it Dijkstra's favourite action, which is exactly the problem."""

    def _phase2(self, **kwargs) -> BattleState:
        return BattleState(
            ours=kwargs.pop("ours", _honchkrow()),
            target=kwargs.pop("target", _target("uxie", hp=1, status=Status.PARALYSIS)),
            rng=0x0C0E02CA, phase=2, **kwargs)

    def test_from_a_clean_state_it_is_allowed_as_harmless_filler(self):
        """State-dependent rather than a blanket ban: with no stages in play there is nothing to
        lose and no reason to forbid it."""
        state = self._phase2()
        self.assertIsNone(undoes_our_own_work(HAZE, state))
        actions = [a for a, *_ in _legal_actions(state, SolverConfig(), _config())]
        self.assertIn(Action.MOVE_1, actions)

    def test_it_is_refused_once_our_flashes_have_landed(self):
        """Six Flashes are the biggest accuracy investment a run makes, and permanent -- a wild
        target never switches out."""
        state = self._phase2(
            target=_target("uxie", hp=1, status=Status.PARALYSIS, accuracy_stage=-3))
        reason = undoes_our_own_work(HAZE, state)
        self.assertIsNotNone(reason)
        self.assertIn("accuracy_stage", reason)
        actions = [a for a, *_ in _legal_actions(state, SolverConfig(), _config())]
        self.assertNotIn(Action.MOVE_1, actions)

    def test_it_is_refused_once_the_solver_has_stacked_its_own_x_sp_def(self):
        """`choose_item` prefers X Sp. Def as filler, so this is nonzero from the first filler
        turn of most plans -- which is why the solver stops planning Haze almost immediately."""
        state = self._phase2(ours=_honchkrow(spdef_stage=1))
        self.assertIsNotNone(undoes_our_own_work(HAZE, state))

    def test_a_stage_that_HURTS_us_does_not_refuse_it(self):
        """The direction differs per stage, and the two that matter are adjacent fields on the
        same object: the target's lowered ACCURACY helps us and its raised EVASION hurts us. Get
        that backwards and Haze is refused exactly when it is wanted."""
        helps_to_reset = self._phase2(
            target=_target("uxie", hp=1, status=Status.PARALYSIS,
                           evasion_stage=6, spatk_stage=6))
        self.assertIsNone(undoes_our_own_work(HAZE, helps_to_reset))
        ours_dropped = self._phase2(ours=_honchkrow(spdef_stage=-4, atk_stage=-2))
        self.assertIsNone(undoes_our_own_work(HAZE, ours_dropped))

    def test_it_is_a_solver_refusal_and_not_an_interview_one(self):
        """The distinction is the point. `unselectable_reason` is for moves the simulator would
        MIS-PREDICT -- it also disables the move in the interview and reports it as a coverage
        gap. Haze is modelled exactly; it is merely self-defeating as filler, and whether to
        spend it is the player's call on the turn."""
        state = self._phase2(
            target=_target("uxie", hp=1, status=Status.PARALYSIS, accuracy_stage=-6))
        self.assertIsNotNone(undoes_our_own_work(HAZE, state))
        self.assertIsNone(unselectable_reason(HAZE, state.target))

    def test_no_other_move_is_touched_by_the_check(self):
        state = self._phase2(
            target=_target("uxie", hp=1, status=Status.PARALYSIS, accuracy_stage=-6))
        for name in ("Taunt", "Flash", "False Swipe", "Thunder Wave"):
            with self.subTest(name):
                self.assertIsNone(undoes_our_own_work(resolve_move(name), state))
        self.assertIsNone(undoes_our_own_work(None, state))


class TestASelfAimedMoveReachesPastAVanishedTarget(unittest.TestCase):
    """What `Move.range_id` was added for, and a pre-existing bug it fixed.

    Haze is RANGE_FIELD and the ROM points a field-, side- or self-range move back at its own
    user: ``defender = attacker`` (battle_lib.c:1664-1683). So there is nothing out of reach while
    Giratina is away mid-Shadow Force -- and before this, every such move of ours rendered as a
    MISS and set nothing.
    """

    def _vanished_giratina(self) -> Battler:
        return _target("giratina-origin", level=47, charging_slot=3)

    def _us(self) -> Battler:
        return Battler(
            name="Magneton", level=54, types=("Electric", "Steel"),
            stats={"hp": 122, "atk": 80, "def": 134, "spa": 140, "spd": 110, "spe": 120},
            moves=("Light Screen", "Flash", "Haze", "Reflect"), pp=(30, 20, 30, 20))

    def test_the_ranges_decode_as_the_decomp_names_them(self):
        """Flag values rather than an index, with SINGLE_TARGET as the zero. All 467 rows land on
        the twelve named values and nothing else."""
        self.assertEqual(resolve_move("Haze").range_id, RANGE_FIELD)
        self.assertEqual(resolve_move("Light Screen").range_id, RANGE_USER_SIDE)
        self.assertEqual(resolve_move("Double Team").range_id, RANGE_USER)
        self.assertEqual(resolve_move("Flash").range_id, RANGE_SINGLE_TARGET)

    def test_reaches_opponent_splits_them_the_right_way(self):
        for name in ("Haze", "Light Screen", "Reflect", "Mist", "Safeguard", "Rain Dance",
                     "Refresh", "Double Team", "Nasty Plot", "Amnesia"):
            with self.subTest(name):
                self.assertFalse(resolve_move(name).reaches_opponent)
        for name in ("Flash", "Taunt", "Swift", "Surf", "False Swipe", "Thunder Wave"):
            with self.subTest(name):
                self.assertTrue(resolve_move(name).reaches_opponent)

    def test_a_screen_goes_up_while_the_target_is_away(self):
        """The bug: it rendered `M1-`, set no screen, and cost the turn its two
        post-successful-move advances. A desync, not a mispredicted number -- and reachable,
        because Magneton carries Light Screen in the configured party."""
        giratina = self._vanished_giratina()
        self.assertTrue(is_semi_invulnerable(giratina))
        _, outcome = execute_move(0x0C0E02CA, resolve_move("Light Screen"), self._us(),
                                  giratina, actor="M", slot=0)
        self.assertEqual(outcome.tokens, ("M1",))
        self.assertTrue(outcome.successful)
        self.assertTrue(outcome.sets_light_screen)

    def test_haze_works_through_it_too(self):
        """Which is the case that matters for the kit: Giratina's Ancient Power boosts are exactly
        what Haze is carried for, and Shadow Force is in the same moveset."""
        _, outcome = execute_move(0x0C0E02CA, resolve_move("Haze"), self._us(),
                                  self._vanished_giratina(), actor="M", slot=2)
        self.assertTrue(outcome.successful)
        self.assertTrue(outcome.resets_all_stages)

    def test_a_move_that_WAS_aimed_at_it_still_misses(self):
        """The control, and the behaviour that was already right: Flash is RANGE_SINGLE_TARGET, so
        it cannot reach something that is not there -- after spending its accuracy roll."""
        _, outcome = execute_move(0x0C0E02CA, resolve_move("Flash"), self._us(),
                                  self._vanished_giratina(), actor="M", slot=1)
        self.assertEqual(outcome.tokens, ("M2", tok.MISS))
        self.assertFalse(outcome.successful)
        self.assertEqual(outcome.rolls, 1)

    def test_and_a_damaging_move_still_misses(self):
        attacker = Battler(name="Smeargle", level=73, types=("Normal",),
                           stats={"hp": 154, "atk": 65, "def": 70, "spa": 40,
                                  "spd": 77, "spe": 160},
                           moves=("False Swipe",), pp=(40,))
        _, outcome = execute_move(0x0C0E02CA, resolve_move("False Swipe"), attacker,
                                  self._vanished_giratina(), actor="M", slot=0)
        self.assertEqual(outcome.damage, 0)
        self.assertFalse(outcome.successful)
        self.assertIn(tok.MISS, outcome.tokens)


class TestItRunsEndToEnd(unittest.TestCase):

    def test_hazing_every_turn_against_every_target_stays_grammatical(self):
        config = _config()
        for name in ("uxie", "azelf", "heatran", "giratina-altered", "darkrai"):
            level = 47 if name.startswith("giratina") else 50
            for seed in SEEDS:
                state = BattleState(ours=_honchkrow(), target=_target(name, level),
                                    rng=opening_rng(seed, config))
                for _ in range(5):
                    state = simulate_turn(state, Action.MOVE_1, config)
                    problems = tok.validate_turn(state.log[-1])
                    self.assertEqual(problems, [],
                                     f"{name} {seed:#x}: {tok.render_turn(state.log[-1])}")
                    if state.over:
                        break

    def test_a_haze_turn_costs_an_item_turn_plus_the_post_move_advances(self):
        """**Zero rolls of its own is not zero cost for the turn.** Haze is a SUCCESSFUL move, so
        the turn still spends the two post-successful-move advances that every successful move
        earns, where a bag action spends none.

        So Haze is the cheapest MOVE in the alphabet, at 2 against Flash's 3 and Taunt's 4 -- not
        level with an item. Pinned because the difference is exactly the block it is easy to
        forget, and because the solver's reason for refusing it as filler rests on it being cheap
        rather than on it being free.
        """
        from claytonlib.battle import turn as turn_costs

        config = _config()
        quiet = _target("uxie", pp=(20, 0, 0, 0))        # Swift only, so the target's half is fixed
        hazing = BattleState(ours=_honchkrow(), target=quiet,
                             rng=opening_rng(0x0C0E02CA, config))
        itemising = BattleState(ours=_honchkrow(), target=quiet,
                                rng=opening_rng(0x0C0E02CA, config))
        hazing = simulate_turn(hazing, Action.MOVE_1, config)
        itemising = simulate_turn(itemising, Action.ITEM, config, item_code="xsd")
        self.assertEqual(hazing.rng_offset - itemising.rng_offset,
                         turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES)

    def test_and_it_is_still_the_cheapest_move_we_can_make(self):
        config = _config()
        quiet = _target("uxie", pp=(20, 0, 0, 0))
        costs = {}
        for slot, name in enumerate(("Haze", "Flash", "Taunt")):
            ours = _honchkrow(moves=("Haze", "Flash", "Taunt"), pp=(30, 20, 20))
            state = BattleState(ours=ours, target=quiet, rng=opening_rng(0x0C0E02CA, config))
            before = state.rng_offset
            state = simulate_turn(state, (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3)[slot],
                                  config)
            costs[name] = state.rng_offset - before
        self.assertLess(costs["Haze"], costs["Flash"])
        self.assertLess(costs["Flash"], costs["Taunt"])


if __name__ == "__main__":
    unittest.main()
