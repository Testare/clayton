"""Roamers: the trainer-AI selection path, the flee, and the two traps that are not the same.

Platinum's roaming **Cresselia** Lv50 is the first target of this kind
(`ActivateRoamingPokemon ROAMING_SLOT_CRESSELIA`, res/field/scripts/scripts_fullmoon_island_forest.s:28;
`case ROAMING_SLOT_CRESSELIA: species = SPECIES_CRESSELIA; level = 50`, src/roaming_pokemon.c:259).

Everything asserted here is measured rather than argued. The three forced-seed recordings
`data/battle_logs/mesprit.jsonl`, `mesprit1.jsonl` and `mesprit2.jsonl` cover 20 turns against the
roaming Mesprit with a Wobbuffet (Shadow Tag, Speed 21), a Smeargle (Speed 177) and a Honchkrow
(Speed 94) against the roamer's Speed 100, and every turn's roll count matched the trap state at
selection:

    7 turns trapped by Shadow Tag   -> 5 rolls, chose a move
    7 turns trapped by a Mean Look  -> 5 rolls, chose a move
    6 turns trapped by nothing      -> 4 rolls, chose Escape

Three facts in that table are the opposite of the obvious guess, and each has a class here:

* **Shadow Tag is a LEAD-only trap.** The AI consults abilities at action selection;
  `FleeCommand` consults only the BIND and MEAN_LOOK volatiles at execution. So a Shadow Tag
  Pokemon switched IN behind an already-chosen escape does not stop it (`mesprit1` T2), while a
  Mean Look landing on that same turn does (`mesprit` T3, `mesprit2` T2 and T7).
* **Sleep is not a trap.** A roamer asleep for three turns still chose Escape and left
  (`mesprit2` T9-T11).
* **The roll count is the decision.** The fifth roll is the `% numMaxScoreMoves` tie-break, which
  the escape branch never reaches -- so a recording says what the roamer decided before it acts.

(clayton-957.35.15, .16, .17)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.sim import (
    MODELLED_TARGET_EFFECTS, ROAMER_AI_ADVANCES, HuntConfig, escape_blocked_at_execution,
    opening_rng, roamer_trapped_at_selection, select_roamer_action, select_target_move,
    simulate_turn, traps_by_ability,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    encounter_level, is_roamer, moveset, resolve, supported, target_ability, unsupported_moves,
)
from claytonlib.moves import resolve_move
from claytonlib.safari import advance_rng

SEED = 0x78017333  # mesprit2.jsonl's forced seed, for no reason beyond provenance.


def _cresselia(**kwargs) -> Battler:
    moves = moveset("cresselia", "platinum")
    return replace(Battler(
        name="Cresselia", level=50, types=tuple(species("cresselia")["types"]),
        stats=derive_species_stats("cresselia", 50, "Modest", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability("cresselia", "platinum")), **kwargs)


def _trapper(**kwargs) -> Battler:
    """A Smeargle that outspeeds the roamer and can trap it: the measured configuration."""
    return replace(Battler(
        name="Smeargle", level=64, types=("Normal",),
        stats={"hp": 400, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
        moves=("Mean Look", "False Swipe", "Spore", "Foresight"),
        pp=(5, 40, 15, 40)), **kwargs)


def _wobbuffet(**kwargs) -> Battler:
    """Shadow Tag, and far slower than the roamer -- which is the point of it."""
    return replace(Battler(
        name="Wobbuffet", level=25, types=("Psychic",),
        stats={"hp": 130, "atk": 21, "def": 34, "spa": 21, "spd": 34, "spe": 21},
        moves=("Safeguard",), pp=(25,), ability="Shadow Tag"), **kwargs)


def _config(**kwargs) -> HuntConfig:
    return replace(HuntConfig(target_catch_rate=3, target_has_pressure=False,
                              target_is_roamer=True), **kwargs)


def _state(target: Battler | None = None, ours: Battler | None = None, *,
           seed: int = SEED, **kwargs) -> BattleState:
    config = _config()
    return BattleState(ours=ours or _trapper(), target=target or _cresselia(),
                       rng=opening_rng(seed, config), **kwargs)


class TestCresseliaRow(unittest.TestCase):
    """The encounter row, and the two things that make it the first roamer worth trying."""

    def test_row_is_platinum_lv50_and_flagged_a_roamer(self):
        key, row = resolve("cresselia", "platinum")
        self.assertEqual(key, "cresselia")
        self.assertEqual(encounter_level("cresselia", "platinum"), 50)
        self.assertTrue(is_roamer("cresselia", "platinum"))
        self.assertEqual(row.games, ("platinum",))

    def test_a_static_target_is_not_a_roamer(self):
        """The flag is per ENCOUNTER, which is why it is not derived from the species."""
        self.assertFalse(is_roamer("suicune", "heartgold"))
        self.assertFalse(is_roamer("giratina-origin", "platinum"))

    def test_moveset_is_the_last_four_learnable_at_fifty_in_learn_order(self):
        self.assertEqual(moveset("cresselia", "platinum"),
                         ("Mist", "Aurora Beam", "Future Sight", "Slash"))

    def test_every_move_was_already_modelled(self):
        """The reason Cresselia is first and not Raikou: no new target effects at all."""
        unsupported, _ = unsupported_moves("cresselia", "platinum")
        self.assertEqual(unsupported, ())
        for name in moveset("cresselia", "platinum"):
            self.assertIn(resolve_move(name).effect, MODELLED_TARGET_EFFECTS, name)

    def test_the_level_window_excludes_the_two_moves_that_would_break_a_run(self):
        """Safeguard(11) from below, so sleep lands; Moonlight(57) from above, so nothing heals."""
        moves = moveset("cresselia", "platinum")
        self.assertNotIn("Safeguard", moves)
        self.assertNotIn("Moonlight", moves)
        self.assertNotIn("Roar", moves)

    def test_it_is_offered_on_platinum_only(self):
        self.assertIn("cresselia", supported("platinum"))
        self.assertNotIn("cresselia", supported("heartgold"))


class TestTheTrapListIsCheckedInTheRomsOrder(unittest.TestCase):
    """`RoamingPokemon_Main`, src/battle/trainer_ai/script.s:8073-8089."""

    def test_shadow_tag_traps_a_levitating_roamer(self):
        """The Levitate test sits AFTER Shadow Tag, which is why this works on Cresselia."""
        self.assertEqual(_cresselia().ability, "Levitate")
        self.assertTrue(traps_by_ability(_wobbuffet(), _cresselia()))

    def test_arena_trap_does_not(self):
        dugtrio = Battler(name="Dugtrio", level=40, types=("Ground",),
                          stats={"hp": 120, "atk": 100, "def": 50, "spa": 50, "spd": 70,
                                 "spe": 120},
                          ability="Arena Trap")
        self.assertFalse(traps_by_ability(dugtrio, _cresselia()))
        # ...and it would against a roamer without Levitate, which is what makes the order the
        # thing being tested rather than Arena Trap being unmodelled.
        self.assertTrue(traps_by_ability(dugtrio, _cresselia(ability="Pressure")))

    def test_an_ordinary_ability_traps_nothing(self):
        self.assertFalse(traps_by_ability(_trapper(), _cresselia()))

    def test_a_mean_look_volatile_traps_whatever_is_out(self):
        self.assertTrue(roamer_trapped_at_selection(_state(target_trapped=True)))
        self.assertFalse(roamer_trapped_at_selection(_state()))

    def test_selection_consults_abilities_and_execution_does_not(self):
        """The whole asymmetry, in one pair of assertions (notes/roamers.md sec 2.2)."""
        shadow_tag = _state(ours=_wobbuffet())
        self.assertTrue(roamer_trapped_at_selection(shadow_tag))
        self.assertFalse(escape_blocked_at_execution(shadow_tag))
        mean_look = _state(target_trapped=True)
        self.assertTrue(roamer_trapped_at_selection(mean_look))
        self.assertTrue(escape_blocked_at_execution(mean_look))


class TestTheSelectionCost(unittest.TestCase):
    """5 rolls trapped, 4 fleeing, 0 relocked -- measured over 20 turns in mesprit*.jsonl."""

    def test_trapped_spends_five_and_picks_a_move(self):
        choice = select_roamer_action(SEED, _cresselia(), trapped=True)
        self.assertEqual(choice.rolls, 5)
        self.assertFalse(choice.fled)
        self.assertIn(choice.slot, (0, 1, 2, 3))

    def test_fleeing_spends_four_and_never_reaches_the_tie_break(self):
        choice = select_roamer_action(SEED, _cresselia(), trapped=False)
        self.assertEqual(choice.rolls, ROAMER_AI_ADVANCES)
        self.assertTrue(choice.fled)
        self.assertIsNone(choice.slot)

    def test_the_four_damage_rolls_are_the_same_rolls_either_way(self):
        """They are spent before the decision exists, so the streams agree for four steps."""
        rng = SEED
        for _ in range(ROAMER_AI_ADVANCES):
            rng = advance_rng(rng)
        self.assertEqual(select_roamer_action(SEED, _cresselia(), trapped=False).rng, rng)
        self.assertEqual(select_roamer_action(SEED, _cresselia(), trapped=True).rng,
                         advance_rng(rng))

    def test_a_roamer_costs_four_more_than_a_wild_target(self):
        wild_rng, wild_slot = select_target_move(SEED, _cresselia())
        roamer = select_roamer_action(SEED, _cresselia(), trapped=True)
        self.assertEqual(roamer.rolls, 5)
        self.assertNotEqual(roamer.rng, wild_rng)
        # The PICK is drawn from the same list, four rolls later -- `usable_slots` either way.
        self.assertIn(wild_slot, (0, 1, 2, 3))

    def test_the_tie_list_is_usable_slots_so_pp_narrows_the_modulus(self):
        one_move = _cresselia(pp=(0, 0, 15, 0))
        for delta in range(12):
            choice = select_roamer_action(SEED + delta, one_move, trapped=True)
            self.assertEqual(choice.slot, 2)
            self.assertEqual(choice.rolls, 5)

    def test_all_four_slots_are_reachable(self):
        slots = {select_roamer_action(SEED + d, _cresselia(), trapped=True).slot
                 for d in range(64)}
        self.assertEqual(slots, {0, 1, 2, 3})

    def test_nothing_usable_is_the_unmodelled_struggle_case(self):
        choice = select_roamer_action(SEED, _cresselia(pp=(0, 0, 0, 0)), trapped=True)
        self.assertIsNone(choice.slot)
        self.assertFalse(choice.fled)
        self.assertEqual(choice.rolls, ROAMER_AI_ADVANCES)

    def test_a_relocked_roamer_is_never_asked_and_spends_nothing(self):
        """`Battler_CanPickCommand` is FALSE mid-charge, so TrainerAI_Init is never reached."""
        charging = select_roamer_action(SEED, _cresselia(charging_slot=2), trapped=False)
        self.assertEqual(charging, (SEED, 2, False, 0))
        uproaring = select_roamer_action(SEED, _cresselia(uproar_turns=2, uproar_slot=1),
                                        trapped=False)
        self.assertEqual(uproaring, (SEED, 1, False, 0))


class TestTheFleeInATurn(unittest.TestCase):
    """What `simulate_turn` does with an escape, and what it costs."""

    def test_an_untrapped_roamer_that_outspeeds_us_simply_leaves(self):
        slow = _trapper(stats={**_trapper().stats, "spe": 94})  # the Honchkrow case
        state = _state(ours=slow)
        after = simulate_turn(state, Action.MOVE_1, _config())
        self.assertTrue(after.target_fled)
        self.assertTrue(after.over)
        self.assertEqual(tok.render_turn(after.log[-1]), tok.escaped_token())

    def test_a_flee_turn_costs_the_four_ai_rolls_and_the_before_turn_block(self):
        """mesprit.jsonl T7: 4 AI rolls, 4 BeforeTurn rolls, then 'The wild MESPRIT fled!'."""
        from claytonlib.battle import turn as turn_costs

        slow = _trapper(stats={**_trapper().stats, "spe": 94})
        after = simulate_turn(_state(ours=slow), Action.MOVE_1, _config())
        self.assertEqual(after.rng_offset,
                         ROAMER_AI_ADVANCES + turn_costs.BEFORE_TURN_ADVANCES)

    def test_our_action_never_happens_when_it_flees_first(self):
        slow = _trapper(stats={**_trapper().stats, "spe": 94})
        after = simulate_turn(_state(ours=slow), Action.MOVE_2, _config())
        self.assertEqual(after.ours.pp, _trapper().pp)
        self.assertNotIn("M2", tok.render_turn(after.log[-1]))

    def test_a_faster_mean_look_rescues_an_already_chosen_escape(self):
        """mesprit.jsonl T3 and mesprit2.jsonl T2/T7: the escape fails and the turn is wasted."""
        after = simulate_turn(_state(), Action.MOVE_1, _config())
        self.assertFalse(after.target_fled)
        self.assertFalse(after.over)
        self.assertTrue(after.target_trapped)
        rendered = tok.render_turn(after.log[-1])
        self.assertIn(tok.escape_failed_token(), rendered)
        self.assertIn("M1", rendered)

    def test_a_refused_escape_spends_nothing_of_its_own(self):
        """Our move's two post-move advances, the between-turn two, the full end-of-turn four."""
        from claytonlib.battle import turn as turn_costs

        after = simulate_turn(_state(), Action.MOVE_1, _config())
        self.assertEqual(
            after.rng_offset,
            ROAMER_AI_ADVANCES
            + turn_costs.BEFORE_TURN_ADVANCES
            + turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES      # our Mean Look
            + turn_costs.BETWEEN_TURN_ADVANCES
            + turn_costs.END_OF_TURN_ADVANCES)

    def test_a_trap_already_standing_means_no_escape_was_ever_chosen(self):
        after = simulate_turn(_state(target_trapped=True), Action.MOVE_4, _config())
        rendered = tok.render_turn(after.log[-1])
        self.assertNotIn(tok.escape_failed_token(), rendered)
        self.assertNotIn(tok.escaped_token(), rendered)
        self.assertFalse(after.target_fled)

    def test_a_shadow_tag_lead_is_never_offered_the_choice(self):
        """Seven such turns in the recordings, all of them a move. Speed is irrelevant here."""
        after = simulate_turn(_state(ours=_wobbuffet()), Action.MOVE_1, _config())
        self.assertFalse(after.target_fled)
        self.assertNotIn(tok.escaped_token(), tok.render_turn(after.log[-1]))

    def test_sleep_does_not_hold_a_roamer(self):
        """mesprit2.jsonl T11: asleep for three turns, chose Escape, left."""
        slow = _trapper(stats={**_trapper().stats, "spe": 94})
        asleep = _cresselia(status=Status.SLEEP, sleep_turns=3)
        after = simulate_turn(_state(target=asleep, ours=slow), Action.MOVE_1, _config())
        self.assertTrue(after.target_fled)

    def test_a_static_target_can_never_flee(self):
        """The config flag is the only door to any of this."""
        static = HuntConfig(target_catch_rate=3, target_has_pressure=False)
        state = BattleState(ours=_trapper(), target=_cresselia(),
                            rng=opening_rng(SEED, static))
        after = simulate_turn(state, Action.MOVE_1, static)
        self.assertFalse(after.target_fled)

    def test_the_flee_token_is_terminal_and_grammatical(self):
        slow = _trapper(stats={**_trapper().stats, "spe": 94})
        after = simulate_turn(_state(ours=slow), Action.MOVE_1, _config())
        for turn in after.log:
            self.assertEqual(tok.validate_turn(turn), [])


class TestLosingTheTrap(unittest.TestCase):
    """The run-ending cases: our side leaves the field, so the volatile goes with it."""

    def test_a_trapped_roamer_stays_trapped_while_the_trapper_stays_in(self):
        state = _state(target_trapped=True)
        for _ in range(3):
            state = simulate_turn(state, Action.MOVE_4, _config())
            if state.over:
                break
        self.assertFalse(state.target_fled)

    def test_switching_the_trapper_out_frees_it_and_shadow_tag_cannot_save_it(self):
        """mesprit1.jsonl T2, which is the finding this whole asymmetry came from.

        The switch resolves before moves, so Wobbuffet is on the field when the escape runs --
        and the escape succeeds anyway, because `FleeCommand` looks at volatiles and not at
        abilities.
        """
        state = _state(target_trapped=True, bench=(_wobbuffet(),))
        state = simulate_turn(state, Action.SWITCH, _config(), bench_slot=0)
        self.assertEqual(state.ours.name, "Wobbuffet")
        self.assertFalse(state.target_trapped)
        # Turn 2: Shadow Tag is now the ACTIVE ability, so selection traps it after all -- which
        # is the half of mesprit1 T2 that only worked because the switch had already happened.
        self.assertTrue(roamer_trapped_at_selection(state))

    def test_an_escape_chosen_behind_a_switch_still_succeeds(self):
        """The strict reading of mesprit1 T2: the decision was taken before Wobbuffet existed."""
        state = _state(bench=(_wobbuffet(),))
        after = simulate_turn(state, Action.SWITCH, _config(), bench_slot=0)
        self.assertEqual(after.ours.name, "Wobbuffet")
        self.assertTrue(after.target_fled)
        self.assertIn(tok.escaped_token(), tok.render_turn(after.log[-1]))


class TestTheSessionReportsIt(unittest.TestCase):
    """The layer the app drives has to call a flee an ENDING, not a turn it can continue from."""

    @staticmethod
    def _session(ours: Battler | None = None, **kwargs):
        import datetime as dt

        from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
        from claytonlib.battle_compass.hunt_session import HuntSession

        cands = tuple(Candidate(seed=SEED + i, frame=1000 + i, second=30) for i in range(12))
        window = CandidateWindow(
            key_seed=0x64018903, initial_time=dt.datetime(2026, 10, 27, 12, 0, 0),
            vector_ms=120_000.0, frame_centre=1000, second_centre=30,
            frame_window=6, second_window=0, candidates=cands)
        return HuntSession(window, ours or _trapper(), _cresselia(**kwargs), _config(),
                           capture_ball="Timer Ball", game="platinum")

    def test_an_unavoidable_flee_is_predicted_identically_by_every_candidate(self):
        """Nothing random decides it, so the turn carries no information -- worth knowing, because
        it means a lost run teaches the next attempt nothing about the seed."""
        slow = _trapper(stats={**_trapper().stats, "spe": 94})
        session = self._session(ours=slow)
        predictions = session.predict(Action.MOVE_1)
        self.assertEqual(set(predictions.values()), {tok.escaped_token()})

    def test_the_outcome_is_fled(self):
        slow = _trapper(stats={**_trapper().stats, "spe": 94})
        session = self._session(ours=slow)
        session.observe(Action.MOVE_1, [tok.escaped_token()])
        self.assertEqual(session.outcome(), "fled")
        self.assertTrue(session.snapshot()["target_fled"])
        self.assertTrue(session.snapshot()["over"])

    def test_a_refused_escape_is_not_an_ending(self):
        session = self._session()
        predictions = session.predict(Action.MOVE_1)
        self.assertTrue(all(tok.escape_failed_token() in p for p in predictions.values()))
        session.observe(Action.MOVE_1, ["M1", tok.escape_failed_token()])
        self.assertEqual(session.outcome(), "")
        self.assertFalse(session.snapshot()["target_fled"])


class TestTheTrapChecksThemselves(unittest.TestCase):
    """`targets.trap_checks` in isolation: the rules, not their wording."""

    @staticmethod
    def _c(**kwargs):
        from claytonlib.battle_compass.targets import TrapCandidate
        return TrapCandidate(**kwargs)

    def _check(self, member, *, target_speed=105, species="cresselia"):
        from claytonlib.battle_compass.targets import trap_checks
        return trap_checks(species, [member], target_speed=target_speed,
                           game="platinum")[0]

    def test_shadow_tag_needs_no_speed_at_all(self):
        check = self._check(self._c(name="Wob", ability="Shadow Tag", speed=1))
        self.assertTrue(check.traps)
        self.assertEqual(check.how, "Shadow Tag")

    def test_arena_trap_is_refused_against_a_levitating_target(self):
        check = self._check(self._c(name="Dug", ability="Arena Trap", speed=160))
        self.assertFalse(check.traps)
        self.assertIn("not grounded", check.problem)

    def test_all_three_pure_trapping_moves_count(self):
        for move in ("Mean Look", "Block", "Spider Web"):
            check = self._check(self._c(name="X", moves=(move,), speed=200))
            self.assertTrue(check.traps, move)
            self.assertEqual(check.how, move)

    def test_a_partial_trap_is_refused_because_it_kills_the_target(self):
        check = self._check(self._c(name="Y", moves=("Whirlpool", "Surf"), speed=200))
        self.assertFalse(check.traps)
        self.assertIn("1/16", check.problem)

    def test_a_trapping_move_must_outspeed(self):
        self.assertTrue(self._check(self._c(name="A", moves=("Mean Look",), speed=106)).traps)
        self.assertFalse(self._check(self._c(name="B", moves=("Mean Look",), speed=104)).traps)

    def test_a_tie_is_not_a_pass(self):
        check = self._check(self._c(name="C", moves=("Mean Look",), speed=105))
        self.assertFalse(check.traps)
        self.assertFalse(check.scarf_would_fix)
        self.assertIn("ties", check.problem)

    def test_a_scarf_is_offered_only_when_it_would_actually_do_it(self):
        close = self._check(self._c(name="D", moves=("Mean Look",), speed=72))
        self.assertTrue(close.scarf_would_fix)
        hopeless = self._check(self._c(name="E", moves=("Mean Look",), speed=20))
        self.assertFalse(hopeless.scarf_would_fix)
        self.assertIn("not even", hopeless.problem)

    def test_a_scarf_already_held_is_not_offered_again(self):
        check = self._check(self._c(name="F", moves=("Mean Look",), speed=90,
                                    held_item="Choice Scarf"))
        self.assertFalse(check.scarf_would_fix)
        self.assertIn("Choice Scarf", check.problem)

    def test_an_unknown_target_speed_is_unknown_and_not_a_failure(self):
        check = self._check(self._c(name="G", moves=("Mean Look",), speed=177),
                            target_speed=None)
        self.assertTrue(check.unknown)
        self.assertFalse(check.traps)

    def test_an_ability_verdict_needs_no_speeds_at_all(self):
        check = self._check(self._c(name="Wob", ability="Shadow Tag"), target_speed=None)
        self.assertTrue(check.traps)
        self.assertFalse(check.unknown)

    def test_arena_trap_reaches_a_grounded_roamer(self):
        """The order in the ROM script is what this is really testing: Levitate skips only the
        Arena Trap check, so a roamer without it is caught by one."""
        from claytonlib.battle_compass.targets import trap_checks

        check = trap_checks("cresselia", [self._c(name="Dug", ability="Arena Trap", speed=160)],
                            target_speed=105, game="platinum")[0]
        self.assertFalse(check.traps)
        # Same party, a grounded target: Raikou roams in HGSS and has Pressure, but it has no row
        # here yet -- so this half is asserted through `is_grounded` directly.
        from claytonlib.battle_compass.targets import is_grounded
        self.assertFalse(is_grounded("cresselia", "platinum"))
        self.assertTrue(is_grounded("suicune", "heartgold"))

    def test_a_static_target_asks_nothing(self):
        from claytonlib.battle_compass.targets import trap_checks
        self.assertEqual(trap_checks("suicune", [self._c(name="Z")], target_speed=50,
                                     game="heartgold"), [])


class TestTheSolverWillNotLoseTheRun(unittest.TestCase):
    """A path that lets the roamer go is not a path, however cheap it looks."""

    @staticmethod
    def _state(**kwargs):
        from claytonlib.battle_compass.sim import opening_rng

        ours = _trapper(hp=400, pp=(5, 40, 15, 40))
        target = _cresselia(hp=1, status=Status.SLEEP, sleep_turns=5)
        return BattleState(ours=ours, target=target, rng=opening_rng(SEED, _config()),
                           phase=2, target_trapped=True, **kwargs)

    def test_a_switch_that_releases_the_trap_is_never_planned(self):
        """The only way a flee is reachable mid-solve, and the search would otherwise take it:
        a switch is the cheapest action there is (no rolls at all)."""
        from claytonlib.battle_compass.solver import SolverConfig, solve

        bench = (_wobbuffet(hp=130),)
        state = self._state(bench=bench)
        result = solve(state, _config(capture_ball="Timer Ball"),
                       SolverConfig(max_turns=6))
        steps = getattr(result, "steps", ())
        self.assertNotIn(Action.SWITCH, [s.action for s in steps])

    def test_the_prune_is_on_the_outcome_rather_than_on_the_action(self):
        """A switch is fine when something else holds it -- which is why this prunes `target_fled`
        and not `Action.SWITCH`: a Shadow Tag bench member keeps the trap through one."""
        from claytonlib.battle_compass.sim import simulate_turn

        state = self._state(bench=(_wobbuffet(hp=130),))
        after = simulate_turn(state, Action.SWITCH, _config(), bench_slot=0)
        self.assertFalse(after.target_trapped)
        self.assertFalse(after.target_fled)          # Shadow Tag is out now
        self.assertTrue(roamer_trapped_at_selection(after))
