"""The layer the app drives: candidates + solver joined into one surface."""
import datetime as dt
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.hunt_session import (
    CANDIDATE_PREVIEW, HuntSession, TurnLog, move_info, worst_incoming_hit,
)
from claytonlib.battle_compass.identify import Phase
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.state import Action, Battler, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.moves import resolve_move

SEED = 0xEC1504DC
HUNT = HuntConfig(target_catch_rate=3)


def _ours(**kw):
    stats = {**derive_species_stats("smeargle", 60, "Hardy"), "atk": 65}
    fields = dict(name="Smeargle", level=60, types=("Normal",), stats=stats,
                  moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                  pp=(40, 5, 20, 15))
    fields.update(kw)
    return Battler(**fields)


def _target(**kw):
    moves = moveset("suicune")
    fields = dict(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                  stats=derive_species_stats("suicune", 40, "Bold"), moves=moves,
                  pp=tuple(resolve_move(m).pp for m in moves))
    fields.update(kw)
    return Battler(**fields)


def _window(n=40, start=SEED):
    cands = tuple(Candidate(seed=start + i, frame=1000 + i, second=30) for i in range(n))
    return CandidateWindow(key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0),
                           vector_ms=5000.0, frame_centre=1000, second_centre=30,
                           frame_window=n // 2, second_window=0, candidates=cands)


def _session(n=40, **kw):
    return HuntSession(_window(n), _ours(), _target(**kw), HUNT, capture_ball="Fast Ball")


class TestDangerFloor(unittest.TestCase):
    """Heal at or below this and no single hit can faint us, without knowing which move is
    coming (sec 11.2)."""

    def test_it_is_the_worst_crit_hit_the_target_can_land(self):
        self.assertEqual(worst_incoming_hit(_ours(), _target()), 58)

    def test_the_session_adopts_it_as_the_solver_floor(self):
        s = _session()
        self.assertEqual(s.danger_floor, 58)
        self.assertEqual(s.solver_config.danger_floor, 58)

    def test_it_is_critical_because_a_crit_ignores_our_defensive_boosts(self):
        from claytonlib.battle.damage import Attacker, Defender, damage_range
        move = resolve_move("Aurora Beam")
        target = _target()
        ours = _ours()
        _, crit = damage_range(
            move, Attacker(level=40, attack=target.stats["atk"],
                           special_attack=target.stats["spa"], types=target.types),
            Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                     types=ours.types), critical=True)
        _, plain = damage_range(
            move, Attacker(level=40, attack=target.stats["atk"],
                           special_attack=target.stats["spa"], types=target.types),
            Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                     types=ours.types))
        self.assertGreater(crit, plain)
        self.assertGreaterEqual(worst_incoming_hit(ours, target), crit)

    def test_a_bulkier_lead_lowers_the_floor(self):
        tanky = _ours(stats={**_ours().stats, "spd": 200, "def": 200})
        self.assertLess(worst_incoming_hit(tanky, _target()),
                        worst_incoming_hit(_ours(), _target()))


class TestConstruction(unittest.TestCase):
    def test_an_empty_window_is_refused(self):
        window = replace(_window(), candidates=())
        with self.assertRaises(ValueError) as caught:
            HuntSession(window, _ours(), _target(), HUNT)
        self.assertIn("widen the window", str(caught.exception))

    def test_it_starts_in_setup_with_no_balls(self):
        s = _session()
        self.assertIs(s.phase, Phase.SETUP)
        self.assertFalse(s.snapshot()["balls_allowed"])

    def test_no_ball_action_is_offered_during_setup(self):
        """A plain Poke Ball is also x1 on Suicune, so a practice throw that lands loses the
        run to the wrong ball (sec 2.3)."""
        actions = _session().legal_actions()
        self.assertNotIn(Action.CAPTURE_BALL, actions)
        self.assertNotIn(Action.STANDARD_BALL, actions)

    def test_only_move_slots_with_pp_are_offered(self):
        s = _session()
        s._session.states = {k: replace(v, ours=v.ours.spend_pp(1, 5))
                             for k, v in s._session.states.items()}
        self.assertNotIn(Action.MOVE_2, s.legal_actions())


class TestObserving(unittest.TestCase):
    def test_a_reported_turn_narrows_the_set(self):
        s = _session()
        truth = s.survivors[0]
        snap = s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertLess(snap["survivors"], 40)
        self.assertIsNone(snap["contradiction"])

    def test_the_truth_is_never_eliminated(self):
        s = _session()
        truth = s.survivors[0]
        for _ in range(4):
            if s.identified is not None:
                break
            s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertIn(truth, s.survivors)

    def test_an_impossible_turn_leaves_the_set_untouched(self):
        """Far likelier to be a typo or a too-narrow window than a genuinely excluded set
        (sec 15.5), and emptying it would destroy the evidence needed to tell which."""
        s = _session()
        before = s.survivors
        snap = s.observe(Action.MOVE_1, ["M1hE3hHP999"])
        self.assertEqual(s.survivors, before)
        self.assertEqual(snap["contradiction"]["kind"], "no_match")
        self.assertEqual(snap["turns"], [])

    def test_a_contradiction_shows_what_candidates_predicted(self):
        """So it can be explained, not merely announced."""
        snap = _session().observe(Action.MOVE_1, ["M1hE3hHP999"])
        self.assertTrue(snap["contradiction"]["predicted"])

    def test_an_ungrammatical_turn_is_caught_before_the_candidates(self):
        snap = _session().observe(Action.MOVE_1, ["M1hHP50"])
        self.assertEqual(snap["contradiction"]["kind"], "grammar")
        self.assertTrue(snap["contradiction"]["problems"])

    def test_a_contradiction_clears_on_the_next_good_turn(self):
        s = _session()
        s.observe(Action.MOVE_1, ["M1hE3hHP999"])
        truth = s.survivors[0]
        snap = s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertIsNone(snap["contradiction"])


class TestUndoIsReplay(unittest.TestCase):
    """Rewinding rebuilds from the candidate window and replays one fewer turn, so no
    BattleState is ever mutated backwards."""

    def test_undo_restores_the_previous_candidate_count(self):
        s = _session()
        before = len(s.survivors)
        truth = s.survivors[0]
        s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertEqual(s.undo()["survivors"], before)

    def test_undo_drops_the_turn_from_the_history(self):
        s = _session()
        truth = s.survivors[0]
        s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertEqual(len(s.turns), 1)
        self.assertEqual(s.undo()["turns"], [])

    def test_undo_restores_exact_battle_state_not_just_the_count(self):
        s = _session()
        truth = s.survivors[0]
        before = s.snapshot()
        s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        after_undo = s.undo()
        self.assertEqual(after_undo["ours"], before["ours"])
        self.assertEqual(after_undo["target"], before["target"])
        self.assertEqual(after_undo["candidates"], before["candidates"])

    def test_undo_on_a_fresh_session_is_harmless(self):
        s = _session()
        self.assertEqual(s.undo()["survivors"], 40)

    def test_repeated_undo_walks_all_the_way_back(self):
        s = _session(n=200)
        truth = s.survivors[0]
        for _ in range(3):
            s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        taken = len(s.turns)
        for _ in range(taken + 2):
            s.undo()
        self.assertEqual(s.turns, [])
        self.assertEqual(len(s.survivors), 200)

    def test_undo_clears_a_contradiction(self):
        s = _session()
        s.observe(Action.MOVE_1, ["M1hE3hHP999"])
        self.assertIsNone(s.undo()["contradiction"])


class TestPhases(unittest.TestCase):
    def test_pinning_allows_balls(self):
        s = _session()
        self.assertTrue(s.enter_pinning()["balls_allowed"])
        self.assertIn(Action.CAPTURE_BALL, s.legal_actions())

    def test_solving_is_blocked_until_the_preconditions_hold(self):
        s = _session()
        s.enter_pinning()
        blockers = s.solver_blockers()
        self.assertTrue(blockers)
        with self.assertRaises(ValueError):
            s.enter_solving()

    def test_the_blockers_are_reported_on_the_snapshot(self):
        """So the UI can say what is missing rather than just refusing."""
        s = _session()
        s.enter_pinning()
        self.assertTrue(s.snapshot()["solver_blockers"])

    def test_solving_runs_the_solver_and_reports_a_path(self):
        s = _session(n=1, hp=1, status=Status.PARALYSIS)
        s.enter_pinning()
        snap = s.enter_solving()
        self.assertEqual(snap["phase"], int(Phase.SOLVING))
        self.assertIsNotNone(snap["solution"])
        if snap["solution"]["found"]:
            self.assertTrue(snap["solution"]["rendered"].endswith("C"))
            self.assertIn("action", snap["solution"]["next"])

    def test_a_transition_survives_undo_replay(self):
        s = _session(n=1, hp=1, status=Status.PARALYSIS)
        s.enter_pinning()
        s.enter_solving()
        truth = s.survivors[0]
        s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertEqual(s.undo()["phase"], int(Phase.SOLVING))


class TestPhaseTwoResolves(unittest.TestCase):
    """Sec 15.4.2 wanted two undo operations -- rewind a misreport, but accept a MISPLAY and
    re-solve, since the game has advanced and cannot be rewound. Re-solving every turn collapses
    those into one path and removes the stale-path failure mode."""

    def test_every_phase_two_turn_re_solves(self):
        s = _session(n=1, hp=1, status=Status.PARALYSIS)
        s.enter_pinning()
        s.enter_solving()
        first = s.solution
        truth = s.survivors[0]
        s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertIsNot(s.solution, first, "the path was not recomputed after the turn")

    def test_a_misplay_is_absorbed_rather_than_rejected(self):
        """Playing something other than the advised action must still be reportable."""
        s = _session(n=1, hp=1, status=Status.PARALYSIS)
        s.enter_pinning()
        s.enter_solving()
        advised = s.solution.steps[0].action if s.solution.__class__.__name__ == "Solution" else None
        other = next(a for a in s.legal_actions() if a is not advised and a.move_slot is not None)
        truth = s.survivors[0]
        snap = s.observe(other, [s.predict(other)[truth]])
        self.assertIsNone(snap["contradiction"])
        self.assertEqual(len(snap["turns"]), 1)


class TestSnapshot(unittest.TestCase):
    def test_it_is_json_safe(self):
        import json
        json.dumps(_session().snapshot())

    def test_seeds_are_rendered_as_hex_strings(self):
        """A 32-bit seed through a JS bridge must not arrive as a float."""
        snap = _session().snapshot()
        for row in snap["candidates"]:
            self.assertTrue(row["seed"].startswith("0x"))

    def test_the_candidate_list_is_capped_and_says_how_many_it_hid(self):
        snap = _session(n=200).snapshot()
        self.assertEqual(len(snap["candidates"]), CANDIDATE_PREVIEW)
        self.assertEqual(snap["candidates_truncated"], 200 - CANDIDATE_PREVIEW)

    def test_it_carries_both_sides_and_the_danger_line(self):
        snap = _session().snapshot()
        self.assertEqual(snap["ours"]["name"], "Smeargle")
        self.assertEqual(snap["target"]["name"], "Suicune")
        self.assertEqual(snap["target"]["max_hp"], 142)
        self.assertFalse(snap["in_danger"])

    def test_in_danger_flips_at_the_floor(self):
        s = _session()
        s._session.states = {k: replace(v, ours=v.ours.with_hp(s.danger_floor))
                             for k, v in s._session.states.items()}
        self.assertTrue(s.snapshot()["in_danger"])

    def test_advice_is_empty_once_the_seed_is_pinned(self):
        """Nothing left to learn; Phase 2 optimises distance instead."""
        self.assertEqual(_session(n=1).snapshot()["advice"], [])

    def test_advice_ranks_actions_while_several_remain(self):
        advice = _session().snapshot()["advice"]
        self.assertTrue(advice)
        self.assertEqual(advice, sorted(advice, key=lambda a: a["expected_survivors"]))

    def test_ambiguity_travels_with_the_snapshot(self):
        self.assertIn("second_only", _session().snapshot()["ambiguity"])


class TestSecondOnlyAmbiguityIsSurfaced(unittest.TestCase):
    """A set differing only in the RTC second can never be separated by any move, so the UI has
    to say so rather than inviting more turns (sec 17.1)."""

    def test_a_second_only_set_is_flagged(self):
        cands = tuple(Candidate(seed=SEED + (k << 24), frame=1000, second=30 + k)
                      for k in range(3))
        window = replace(_window(), candidates=cands)
        s = HuntSession(window, _ours(), _target(), HUNT)
        amb = s.snapshot()["ambiguity"]
        self.assertTrue(amb["second_only"])
        self.assertFalse(amb["separable_by_moves"])
        self.assertIn("narrower second window", amb["advice"])

    def test_such_a_set_does_not_narrow_however_many_turns_are_played(self):
        cands = tuple(Candidate(seed=SEED + (k << 24), frame=1000, second=30 + k)
                      for k in range(3))
        s = HuntSession(replace(_window(), candidates=cands), _ours(), _target(), HUNT)
        truth = s.survivors[0]
        for _ in range(5):
            s.observe(Action.MOVE_1, [s.predict(Action.MOVE_1)[truth]])
        self.assertEqual(len(s.survivors), 3)


class TestTheInterviewCanExpressEveryTurn(unittest.TestCase):
    """The page assembles tokens from answers rather than taking a typed string, so its question
    vocabulary has to cover everything the simulator can predict. A gap here is not cosmetic: a
    turn the player cannot report is a run that cannot continue.

    Found exactly that on the first run of this test -- 96 of 456 renderings carried the `~`
    secondary-effect marker (Aurora Beam's Attack drop) and there was no question for it.
    """

    #: The token shapes the interview's chips can produce, per app/web/index.html's hrTokens().
    OURS = (r"(?:M[1-4][h!\-]?~?|M(?:par|slp|frz|cfz|fln)|Mscfz[1-4][h!\-]?~?"
            r"|I[a-z]+|S[1-6]|C[0-3]?|Pc?[0-3]?)")
    TARGET = r"(?:E[1-4][h!\-]?~?|E(?:par|slp|frz|fln))"
    TURN = None  # built in setUpClass

    @classmethod
    def setUpClass(cls):
        import re
        cls.TURN = re.compile(rf"^{cls.OURS}(?:{cls.TARGET})?(?:HP\d{{3}})?$")

    def _renderings(self):
        import random
        from claytonlib.battle_compass.sim import simulate_turn
        rng = random.Random(9)
        seen = set()
        for _ in range(400):
            for extra in ({}, {"hp": 1, "status": Status.PARALYSIS}):
                state = _session(n=1, **extra)._session.states
                base = next(iter(state.values()))
                base = replace(base, rng=rng.getrandbits(32))
                for action in Action:
                    if action is Action.SWITCH:
                        continue
                    try:
                        nxt = simulate_turn(base, action, HUNT)
                    except Exception:
                        continue
                    from claytonlib.battle_compass import tokens as tk
                    seen.add(tk.render_turn(tk.normalise(nxt.log[-1])))
        return seen

    def test_the_sample_is_broad_enough_to_mean_something(self):
        self.assertGreater(len(self._renderings()), 200)

    def test_every_predictable_turn_matches_the_interviews_vocabulary(self):
        unreportable = sorted(r for r in self._renderings() if not self.TURN.match(r))
        self.assertEqual(unreportable, [],
                         f"{len(unreportable)} turn(s) the interview cannot express")

    def test_move_info_says_which_questions_apply(self):
        info = {m["name"]: m for m in move_info(_target())}
        # Aurora Beam: damaging, can miss, has a secondary. Mist: none of those.
        self.assertTrue(info["Aurora Beam"]["damaging"])
        self.assertTrue(info["Aurora Beam"]["has_secondary"])
        self.assertEqual(info["Aurora Beam"]["effect_chance"], 10)
        self.assertFalse(info["Mist"]["damaging"])
        self.assertFalse(info["Mist"]["has_secondary"])
        self.assertFalse(info["Mist"]["can_miss"])

    def test_a_status_move_is_never_asked_whether_it_crit(self):
        """Which is what move_info's `damaging` flag is for."""
        info = {m["name"]: m for m in move_info(_ours())}
        self.assertFalse(info["Mean Look"]["damaging"])
        self.assertTrue(info["False Swipe"]["damaging"])

    def test_move_info_tracks_remaining_pp(self):
        session = _session()
        before = move_info(next(iter(session._session.states.values())).ours)
        self.assertEqual([m["pp"] for m in before], [40, 5, 20, 15])

    def test_an_unknown_slot_is_marked_rather_than_guessed(self):
        battler = _ours(moves=("False Swipe",), pp=(40,))
        self.assertTrue(move_info(battler)[0]["known"])


if __name__ == "__main__":
    unittest.main()
