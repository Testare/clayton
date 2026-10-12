"""Ranking is the one slow thing the tool does, and it describes exactly one position.

~8s at 6,000 candidates, because it simulates every surviving candidate against every legal
action. The page already dropped a stale REPLY, but nothing stopped the computation: report a
turn while it runs and the sweep carried on ranking actions for a turn that had been played,
competing with the report for the interpreter (clayton-957.10.11).

So the sweep now polls a predicate and abandons itself. Two things are worth pinning: that it
really stops *part-way* rather than running to completion and being discarded, and that the
facade reports the abort as an outcome rather than letting an exception reach the page -- there
is nothing for the player to fix.
"""
import datetime as dt
import unittest
from unittest import mock

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.hunt_session import HuntSession
from claytonlib.battle_compass.identify import AdviceAborted, Session
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.state import Action, Battler
from claytonlib.battle_compass.targets import moveset
from claytonlib.moves import resolve_move

SEED = 0xEC1504DC
HUNT = HuntConfig(target_catch_rate=3)


def _ours():
    return Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15))


def _target():
    moves = moveset("suicune")
    return Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                   stats=derive_species_stats("suicune", 40, "Bold"), moves=moves,
                   pp=tuple(resolve_move(m).pp for m in moves))


def _session(n=8):
    cands = tuple(Candidate(seed=SEED + i, frame=1000 + i, second=30) for i in range(n))
    window = CandidateWindow(key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0),
                             vector_ms=5000.0, frame_centre=1000, second_centre=30,
                             frame_window=n // 2, second_window=0, candidates=cands)
    return HuntSession(window, _ours(), _target(), HUNT, capture_ball="Fast Ball")


class TestThePositionCounter(unittest.TestCase):
    """What counts as "the run has moved". Everything that changes what advice would say."""

    def test_an_accepted_turn_moves_it(self):
        session = _session()
        before = session.position
        session.observe(Action.MOVE_1, ["M1h", "E2h", "HP138"])
        self.assertFalse(session.contradiction, "fixture turn should be reportable")
        self.assertGreater(session.position, before)

    def test_a_contradiction_does_not(self):
        """The position is unchanged on a rejected turn -- the set was left untouched -- so the
        advice on screen is still the advice for it, and aborting a sweep would be gratuitous."""
        session = _session()
        before = session.position
        session.observe(Action.MOVE_1, ["M1h", "E1h", "HP1"])
        self.assertTrue(session.contradiction, "fixture turn should be impossible")
        self.assertEqual(session.position, before)

    def test_an_undo_moves_it(self):
        session = _session()
        session.observe(Action.MOVE_1, ["M1h", "E2h", "HP138"])
        before = session.position
        session.undo()
        self.assertGreater(session.position, before)

    def test_a_phase_change_moves_it(self):
        """The one case a turn COUNT cannot see: the position changes without a turn."""
        session = _session()
        before = session.position
        session.enter_pinning()
        self.assertGreater(session.position, before)

    def test_the_predicate_follows_it(self):
        session = _session()
        keep_going = session._still_at(session.position)
        self.assertTrue(keep_going())
        session._moved()
        self.assertFalse(keep_going())


class TestTheSweepStopsPartWay(unittest.TestCase):
    """Not "finishes and is discarded" -- stops. That is the whole point."""

    def test_rank_actions_raises_once_the_predicate_goes_false(self):
        session = _session()
        with self.assertRaises(AdviceAborted):
            session._session.rank_actions([Action.CAPTURE_BALL, Action.MOVE_1],
                                          keep_going=lambda: False)

    def test_a_sweep_with_no_predicate_still_runs(self):
        """The default is unchanged: every other caller passes nothing and sweeps to the end."""
        ranked = _session()._session.rank_actions([Action.CAPTURE_BALL, Action.MOVE_1])
        self.assertEqual(len(ranked), 2)

    def test_advice_abandons_itself_at_the_first_action(self):
        """A turn reported mid-sweep: `advice` must not go on to rank the other six actions."""
        session = _session()
        original = Session.partition
        seen = []

        def moving_partition(inner, action, *, keep_going=None):
            seen.append(action)
            session._moved()          # the player reports a turn while this is computing
            return original(inner, action, keep_going=keep_going)

        with mock.patch.object(Session, "partition", moving_partition):
            with self.assertRaises(AdviceAborted):
                session.advice()
        self.assertEqual(len(seen), 1,
                         "it ranked on past the abort; the whole sweep was still being spent")

    def test_the_ball_risk_sweep_aborts_too(self):
        """The same cost as one ranked action, computed for the same position."""
        session = _session()
        session.position += 1         # as if a turn had landed between the two calls
        keep_going = session._still_at(session.position - 1)
        self.assertFalse(keep_going())
        with mock.patch.object(session, "_still_at", lambda _at: keep_going):
            with self.assertRaises(AdviceAborted):
                session.standard_ball_risk()

    def test_an_undisturbed_sweep_returns_advice_as_before(self):
        session = _session()
        advice = session.advice()
        self.assertTrue(advice)
        self.assertEqual(sorted(advice, key=lambda row: row["expected_survivors"]), advice,
                         "best first, lowest expected survivors first")
        for row in advice:
            self.assertIn("action", row)
            self.assertIn("groups", row)
            self.assertNotIn("_sort", row, "the sort key is internal")


class TestOnePartitionPerAction(unittest.TestCase):
    """`advice` used to call `rank_actions` and then `partition` again for the group count --
    sweeping the whole candidate set twice for the same answer, which was half the wait."""

    def test_the_candidate_set_is_swept_once_per_action(self):
        session = _session()
        original = Session.partition
        seen = []

        def counting_partition(inner, action, *, keep_going=None):
            seen.append(action)
            return original(inner, action, keep_going=keep_going)

        with mock.patch.object(Session, "partition", counting_partition):
            advice = session.advice()
        self.assertEqual(len(seen), len(set(seen)), "an action was partitioned twice")
        self.assertEqual(len(seen), len(advice))

    def test_the_figures_match_what_rank_actions_computes(self):
        """The restructure has to be a refactor, not a new answer."""
        session = _session()
        advice = session.advice()
        choosable = [a for a in session.legal_actions()
                     if a not in (Action.REVIVE, Action.FAINTED)]
        ranked = session._session.rank_actions(choosable)
        self.assertEqual([row["action"] for row in advice], [a.value for a, _ in ranked])
        self.assertEqual([row["expected_survivors"] for row in advice],
                         [round(score, 2) for _, score in ranked])


class TestTheFacadeReportsItRatherThanRaising(unittest.TestCase):

    def test_an_aborted_sweep_comes_back_as_an_outcome(self):
        from app.facade import Facade

        facade = Facade.__new__(Facade)
        session = _session()
        facade._hunt_sessions = mock.Mock(get=lambda _id: session)
        original = Session.partition

        def moving_partition(inner, action, *, keep_going=None):
            session._moved()
            return original(inner, action, keep_going=keep_going)

        with mock.patch.object(Session, "partition", moving_partition):
            result = facade.hunt_session_advice("whatever")
        self.assertTrue(result["aborted"])
        self.assertEqual(result["advice"], [])
        self.assertIsNone(result["standard_ball_risk"])

    def test_an_ordinary_sweep_says_it_was_not_aborted(self):
        """Present either way, so the page can test one field rather than infer from emptiness --
        an empty ranking is also what a PINNED seed returns, and that is not an abort."""
        from app.facade import Facade

        facade = Facade.__new__(Facade)
        facade._hunt_sessions = mock.Mock(get=lambda _id: _session())
        result = facade.hunt_session_advice("whatever")
        self.assertFalse(result["aborted"])
        self.assertTrue(result["advice"])


class TestThePageDropsAStaleReplyWhole(unittest.TestCase):
    """Including its right to clear the loading flag, which the turn count could not do for a
    reply that landed on the same turn."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.html = (Path(__file__).resolve().parents[1]
                    / "app" / "web" / "index.html").read_text()

    def test_requests_carry_a_generation(self):
        self.assertIn("let _huntAdviceGen = 0;", self.html)
        self.assertIn("const gen = _huntAdviceGen;", self.html)

    def test_invalidating_bumps_it(self):
        self.assertIn("_huntAdviceGen++;", self.html)

    def test_a_stale_or_aborted_reply_is_not_stored(self):
        self.assertIn("if (gen !== _huntAdviceGen || result.aborted) return;", self.html)

    def test_only_the_current_generation_clears_the_spinner(self):
        self.assertIn("if (gen === _huntAdviceGen) _huntAdviceLoading = false;", self.html)

    def test_the_old_turn_count_guard_is_gone(self):
        """It was the thing that could not see a phase change."""
        self.assertNotIn("_huntSnap.turns.length !== forTurn", self.html)
