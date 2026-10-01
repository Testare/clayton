"""The winning turn: reporting the throw that lands.

The one turn a run exists to reach raised `IndexError: list index out of range` the moment it was
reported, and the cause is worth stating precisely because every part of it was behaving
correctly on its own.

`observe` re-solves after every Phase 2 turn. On the turn the ball lands the state it re-solves
from is already captured, so the solver returns a `Solution` with **zero steps** -- a correct and
meaningful answer: there is nothing left to do. `snapshot` then read `steps[0]` unconditionally.

Underneath that was the real gap: the snapshot never reported that the run had ENDED. With no
terminal flag the page had no reason to stop asking for the next turn, so the only thing standing
between a landed ball and a fresh question was the crash.
"""
import datetime as dt
import unittest

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.hunt_session import HuntSession
from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.solver import Solution, SolverConfig, solve
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.moves import resolve_move

HUNT = HuntConfig(target_catch_rate=3)
#: A seed whose very first capture-ball throw LANDS against a 1 HP paralyzed Suicune. Found by
#: sweeping rather than chosen, so it is the plain case and not a contrivance.
CAPTURING_SEED = 0xEC150528


def _ours(**kw):
    fields = dict(name="Smeargle", level=58, types=("Normal",),
                  stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                  moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                  pp=(40, 5, 20, 15))
    fields.update(kw)
    return Battler(**fields)


def _target(**kw):
    moves = moveset("suicune")
    fields = dict(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                  stats=derive_species_stats("suicune", 40, "Bold"), moves=moves,
                  pp=tuple(resolve_move(m).pp for m in moves),
                  hp=1, status=Status.PARALYSIS)
    fields.update(kw)
    return Battler(**fields)


def _pinned_session(seed=CAPTURING_SEED):
    """One candidate, Phase 2 -- the position a run is in when it throws for the win."""
    window = CandidateWindow(
        key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
        frame_centre=1000, second_centre=30, frame_window=0, second_window=0,
        candidates=(Candidate(seed=seed, frame=1000, second=30),))
    session = HuntSession(window, _ours(), _target(), HUNT, capture_ball="Fast Ball")
    session.enter_pinning()
    session.enter_solving()
    return session


class TestTheSeedReallyCaptures(unittest.TestCase):
    """The fixture's premise, checked separately so a failure below cannot be blamed on it."""

    def test_the_first_throw_lands(self):
        state = BattleState(ours=_ours(), target=_target(),
                            rng=opening_rng(CAPTURING_SEED, HUNT), phase=2)
        after = simulate_turn(state, Action.CAPTURE_BALL, HUNT)
        self.assertTrue(after.captured)
        self.assertTrue(after.over)
        self.assertFalse(after.captured_in_wrong_ball)


class TestSolvingFromACapturedState(unittest.TestCase):
    def test_it_returns_a_solution_with_no_steps(self):
        """Not an error and not Unreachable. The goal is already met, so the path is empty and
        its distance is zero -- which is the correct answer to "how do I get from here to a
        capture" when here IS a capture."""
        state = BattleState(ours=_ours(), target=_target(),
                            rng=opening_rng(CAPTURING_SEED, HUNT), phase=2)
        after = simulate_turn(state, Action.CAPTURE_BALL, HUNT)
        solution = solve(after, HUNT, SolverConfig(danger_floor=56))
        self.assertIsInstance(solution, Solution)
        self.assertEqual(solution.steps, [])
        self.assertEqual(solution.total_distance, 0)


class TestReportingTheWinningThrow(unittest.TestCase):
    def setUp(self):
        self.session = _pinned_session()

    def test_the_solver_recommends_the_throw_by_name(self):
        """Not "C". A code the player has to translate under time pressure is a code they
        translate wrongly."""
        nxt = self.session.snapshot()["solution"]["next"]
        self.assertEqual(nxt["action"], "C")
        self.assertEqual(nxt["label"], "Throw the Fast Ball")

    def test_reporting_it_does_not_raise(self):
        """The regression. This raised IndexError: list index out of range."""
        snapshot = self.session.observe(Action.CAPTURE_BALL, ("C",))
        self.assertIsNone(snapshot["contradiction"])

    def test_the_snapshot_says_the_run_was_won(self):
        snapshot = self.session.observe(Action.CAPTURE_BALL, ("C",))
        self.assertTrue(snapshot["captured"])
        self.assertTrue(snapshot["over"])
        self.assertFalse(snapshot["captured_in_wrong_ball"])
        self.assertFalse(snapshot["we_fainted"])

    def test_the_finished_solution_reports_done_with_no_next_step(self):
        solution = self.session.observe(Action.CAPTURE_BALL, ("C",))["solution"]
        self.assertTrue(solution["found"])
        self.assertTrue(solution["done"])
        self.assertIsNone(solution["next"])
        self.assertEqual(solution["steps"], [])

    def test_an_unfinished_solution_is_not_marked_done(self):
        """So `done` means what it says rather than being true whenever a solution exists."""
        solution = self.session.snapshot()["solution"]
        self.assertFalse(solution["done"])
        self.assertIsNotNone(solution["next"])

    def test_everything_the_page_calls_next_still_works(self):
        """The crash was in `snapshot`, so the check is that the whole post-win render path is
        clean rather than only the call that happened to fail."""
        self.session.observe(Action.CAPTURE_BALL, ("C",))
        for name, call in (("snapshot", lambda: self.session.snapshot()),
                           ("snapshot+advice",
                            lambda: self.session.snapshot(include_advice=True)),
                           ("advice", self.session.advice),
                           ("legal_actions", self.session.legal_actions),
                           ("standard_ball_risk", self.session.standard_ball_risk),
                           ("hp_range", lambda: self.session.hp_range("ours"))):
            with self.subTest(name):
                call()

    def test_undo_puts_the_run_back(self):
        """A misreported capture has to be rewindable like any other turn, and the undo path
        re-solves too -- so it hits the same empty-path case from the other direction."""
        self.session.observe(Action.CAPTURE_BALL, ("C",))
        snapshot = self.session.undo()
        self.assertFalse(snapshot["captured"])
        self.assertFalse(snapshot["over"])
        self.assertIsNotNone(snapshot["solution"]["next"])


class TestTerminalFlagsNeedEveryCandidateToAgree(unittest.TestCase):
    """`all`, not `any`. A candidate set that disagrees about whether the ball landed has not
    finished, and announcing a win on one member of it would be a lie."""

    def test_a_mixed_set_is_not_reported_as_over(self):
        window = CandidateWindow(
            key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
            frame_centre=1000, second_centre=30, frame_window=2, second_window=0,
            candidates=tuple(Candidate(seed=CAPTURING_SEED + i, frame=1000 + i, second=30)
                             for i in range(5)))
        session = HuntSession(window, _ours(), _target(), HUNT, capture_ball="Fast Ball")
        session.enter_pinning()
        predictions = session.predict(Action.CAPTURE_BALL)
        self.assertIn("C", predictions.values())
        self.assertGreater(len({p for p in predictions.values()}), 1,
                           "this fixture needs candidates that disagree about the throw")
        snapshot = session.snapshot()
        self.assertFalse(snapshot["captured"])
        self.assertFalse(snapshot["over"])


class TestTheLabelNamesTheItemToo(unittest.TestCase):
    """A path with two bag actions read "Use an item" twice, which is not a usable instruction."""

    def test_an_item_step_names_the_item(self):
        session = _pinned_session()
        self.assertEqual(session.action_label(Action.ITEM, "hp"), "Use a Hyper Potion")
        self.assertEqual(session.action_label(Action.ITEM, "sp"), "Use a Super Potion")

    def test_without_a_code_it_falls_back_to_the_generic_wording(self):
        session = _pinned_session()
        self.assertEqual(session.action_label(Action.ITEM), "Use an item")

    def test_an_unknown_code_falls_back_rather_than_raising(self):
        """A label is cosmetic; it must never be the thing that breaks a snapshot."""
        session = _pinned_session()
        self.assertEqual(session.action_label(Action.ITEM, "nope"), "Use an item")

    def test_no_label_is_ever_just_the_bare_code(self):
        session = _pinned_session()
        for action in Action:
            label = session.action_label(action)
            self.assertNotEqual(label, action.value, action)


class TestThePageUsesTheLabels(unittest.TestCase):
    def setUp(self):
        import pathlib
        self.html = (pathlib.Path(__file__).resolve().parent.parent
                     / "app" / "web" / "index.html").read_text()

    def test_the_next_action_is_shown_by_name(self):
        self.assertIn("Next: <b>${esc(sol.next.label || sol.next.action)}</b>", self.html)

    def test_the_code_is_kept_alongside_rather_than_dropped(self):
        """It is still what the path string and the turn history are written in, so a player
        cross-referencing them needs it -- just not as the primary label."""
        self.assertIn("<span class=\"muted\">(<code>${esc(sol.next.action)}</code>)</span>",
                      self.html)

    def test_the_solver_panel_tolerates_a_finished_path(self):
        self.assertIn("s.solution.found && s.solution.next", self.html)
        self.assertIn("Nothing left to do", self.html)

    def test_a_finished_run_stops_asking_for_turns(self):
        self.assertIn("${s.over ? \"\" : `<div class=\"panel\">", self.html)
        self.assertIn("Caught it — in the", self.html)
        self.assertIn("Caught in the wrong ball.", self.html)


class TestWhereThePinnedSeedLanded(unittest.TestCase):
    """A pinned seed on its own says nothing about whether the window was aimed well.

    The deltas are the run's only feedback on its own timing, and the two axes miss
    near-independently (notes/seed_hitting_process.md sec 3-4) -- so "30 frames late, dead on the
    second" is a different problem from "a second out", and collapsing them to one number would
    hide which.
    """

    def _window_offset_from(self, true_seed, frames=3):
        """A window centred `frames` below the true seed, so the deltas are not all zero."""
        candidates = tuple(
            Candidate(seed=true_seed - frames + i, frame=1000 - frames + i,
                      second=30 + (i % 2))
            for i in range(2 * frames + 1))
        return CandidateWindow(
            key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
            frame_centre=1000, second_centre=30, frame_window=frames, second_window=1,
            candidates=candidates)

    def _session(self):
        session = HuntSession(self._window_offset_from(CAPTURING_SEED), _ours(), _target(),
                              HUNT, capture_ball="Fast Ball")
        session.enter_pinning()
        return session

    def test_nothing_is_reported_before_the_seed_is_pinned(self):
        self.assertIsNone(self._session().snapshot()["identified_at"])

    def test_every_candidate_carries_its_own_deltas(self):
        rows = self._session().snapshot()["candidates"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["frame_delta"], row["frame"] - 1000)
            self.assertEqual(row["second_delta"], row["second"] - 30)

    def test_the_pinned_seed_reports_where_it_landed(self):
        session = self._session()
        predicted = session.predict(Action.CAPTURE_BALL)[CAPTURING_SEED]
        session.observe(Action.CAPTURE_BALL, (predicted,))
        snapshot = session.snapshot()
        self.assertEqual(snapshot["identified"], f"{CAPTURING_SEED:#010x}")
        at = snapshot["identified_at"]
        self.assertEqual(at["seed"], f"{CAPTURING_SEED:#010x}")
        self.assertEqual(at["frame"], 1000)
        self.assertEqual(at["frame_delta"], 0)
        self.assertEqual(at["second_delta"], at["second"] - 30)

    def test_a_late_seed_reports_a_positive_frame_delta(self):
        """Sign convention: actual minus aim, so positive is LATE -- the same direction
        calibration_tools uses for its own frame_delta."""
        info = Candidate(seed=1, frame=1030, second=30)
        self.assertEqual(info.frame_delta(1000), 30)
        self.assertEqual(info.frame_delta(1060), -30)

    def test_the_deltas_follow_a_rebase_rather_than_going_stale(self):
        """Computed against the LIVE window centre, not stored on the candidate. A stored delta
        would keep describing the window it was built in after a mid-run widening."""
        session = self._session()
        wider = self._window_offset_from(CAPTURING_SEED, frames=6)
        before = session.snapshot()["candidates"][0]["frame_delta"]
        session.rebase(wider)
        rows = {r["seed"]: r for r in session.snapshot()["candidates"]}
        for row in rows.values():
            self.assertEqual(row["frame_delta"], row["frame"] - session.window.frame_centre)
        self.assertIsInstance(before, int)


class TestTheCandidateDeltaStubIsGone(unittest.TestCase):
    """`Candidate.frame_delta` was a no-argument property returning a hardcoded 0, documented as
    "set by generate" -- which generate could not do, since this is a frozen dataclass and that
    was a property. Nothing ever read it, so the zero never surfaced."""

    def test_it_now_takes_the_centre_and_computes_a_real_value(self):
        candidate = Candidate(seed=1, frame=1007, second=31)
        self.assertEqual(candidate.frame_delta(1000), 7)
        self.assertEqual(candidate.second_delta(30), 1)

    def test_it_is_not_a_property_any_more(self):
        self.assertFalse(isinstance(
            type(Candidate(seed=1, frame=1, second=1)).__dict__.get("frame_delta"), property))


class TestThePageShowsTheDeltas(unittest.TestCase):
    def setUp(self):
        import pathlib
        self.html = (pathlib.Path(__file__).resolve().parent.parent
                     / "app" / "web" / "index.html").read_text()

    def test_the_pinned_line_reports_frame_and_second_with_their_misses(self):
        self.assertIn("Landed on frame", self.html)
        self.assertIn("from the ${s.window.frame_centre} aimed for", self.html)
        self.assertIn("RTC second", self.html)

    def test_a_late_miss_is_shown_with_an_explicit_plus(self):
        """Matching renderCandA's columns in the other compasses -- the sign is the informative
        half, so a bare "30" would not say which way."""
        self.assertIn('const signed = (n) => `${n >= 0 ? "+" : ""}${n}`;', self.html)

    def test_the_candidate_table_gained_both_delta_columns(self):
        self.assertIn(">Δframe</th>", self.html)
        self.assertIn(">Δsec</th>", self.html)

    def test_the_truncation_row_spans_the_new_column_count(self):
        """Five columns now, not three -- a stale colspan leaves the "and N more" row short."""
        self.assertIn('<tr><td colspan="5" class="muted">', self.html)
