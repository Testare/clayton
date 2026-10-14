"""Reporting a turn should cost what the surviving candidates cost, not what the window did.

Reported from the app: "Why does it take so long to process a reported turn, even when there is
only 1 candidate remaining?" Measured against a 6,000-candidate window narrowed to ONE survivor,
a single `observe` took **6.2 seconds** and made 7,456 `simulate_turn` calls.

Two causes, both of which made the work proportional to the original window rather than to what
was left:

* `resolve_move` rebuilt its name index on every call -- 59,675 calls and 28 million
  `str.lower()`s for one turn.
* `explain_history` rebuilt a session over every ORIGINAL candidate and re-observed the whole run
  on every snapshot, purely to produce the turn-table tooltips.

The correctness requirement that forced the replay is unchanged and is what these tests mostly
check: a turn played before a switch belongs to a different Pokemon with a different moveset, so
its explanation must still name THAT Pokemon's moves.
"""
import datetime as dt
import time
import unittest

from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.hunt_session import HuntSession, _item_name, _party_namer
from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState
from claytonlib.battle_compass.targets import moveset
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.moves import resolve_move

SEED = 0xEC1504DC


def _session(n=400, bench=()):
    ours = Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15), ability="Technician", held_item="Silk Scarf")
    mv = moveset("lugia")
    target = Battler(name="Lugia", level=45, types=tuple(species("lugia")["types"]),
                     stats=derive_species_stats(
                         "lugia", 45, "Serious",
                         ivs={"hp": 31, "atk": 31, "def": 31, "spa": 17, "spd": 31, "spe": 31}),
                     moves=mv, pp=tuple(resolve_move(m).pp for m in mv), ability="Pressure")
    cands = tuple(Candidate(seed=SEED + i * 7, frame=1000 + i, second=30) for i in range(n))
    window = CandidateWindow(key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0),
                             vector_ms=5000.0, frame_centre=1000, second_centre=30,
                             frame_window=n // 2, second_window=0, candidates=cands)
    return HuntSession(window, ours, target, HuntConfig(target_catch_rate=3),
                       capture_ball="Love Ball", bench=bench)


def _play(session, actions):
    """Report `actions` by simulating the true seed, so the tokens are ones the tool produced."""
    state = BattleState(rng=session._session.states[SEED].rng,
                        ours=session.ours, target=session.target)
    for action in actions:
        nxt = simulate_turn(state, action, session.config)
        session.observe(action, nxt.log[-1])
        state = nxt
    return session


def _explain_by_replay(session):
    """The old implementation, kept here as the oracle the fast path must agree with."""
    fresh = session._fresh()
    out = []
    for turn in session.turns:
        state = next(iter(fresh.states.values()))
        out.append(tok.explain_turn(
            turn.tokens, ours=state.ours.name, ours_moves=tuple(state.ours.moves),
            target=state.target.name, target_moves=tuple(state.target.moves),
            capture_ball=session.capture_ball or "capture ball", item_name=_item_name,
            party_name=_party_namer(state)))
        fresh.observe(turn.action, turn.tokens, **turn.extra)
    return out


class TestTheExplanationsAreUnchanged(unittest.TestCase):
    """The accumulated list must equal what replaying produces, turn for turn."""

    def test_a_plain_run_agrees_with_the_replay(self):
        s = _play(_session(), [Action.MOVE_1, Action.MOVE_3, Action.MOVE_1, Action.MOVE_4])
        self.assertEqual(s.explain_history(), _explain_by_replay(s))
        self.assertTrue(s.explain_history(), "the fixture produced no explanations to compare")

    def test_one_explanation_per_reported_turn(self):
        s = _play(_session(), [Action.MOVE_1, Action.MOVE_3, Action.MOVE_1])
        self.assertEqual(len(s.explain_history()), len(s.turns))

    def test_a_rejected_turn_adds_no_explanation(self):
        """The capture happens at report time, so it must only be kept if the turn is accepted --
        otherwise the list and the turn log drift apart and every tooltip shifts by one."""
        s = _play(_session(), [Action.MOVE_1, Action.MOVE_1])
        before = len(s.explain_history())
        s.observe(Action.MOVE_1, ["E1", "HP040"])     # nothing predicts this
        self.assertIsNotNone(s.contradiction)
        self.assertEqual(len(s.explain_history()), before)
        self.assertEqual(len(s.explain_history()), len(s.turns))

    def test_an_undo_rebuilds_it(self):
        s = _play(_session(), [Action.MOVE_1, Action.MOVE_3, Action.MOVE_1])
        s.undo()
        self.assertEqual(len(s.explain_history()), len(s.turns))
        self.assertEqual(s.explain_history(), _explain_by_replay(s))

    def test_a_REBASE_rebuilds_it(self):
        """What widening calls. It replaces the window outright, so the accumulated list has to
        be dropped and refilled rather than trusted."""
        from dataclasses import replace as _replace

        s = _play(_session(n=200), [Action.MOVE_1, Action.MOVE_3])
        wider = _session(n=400).window
        s.rebase(_replace(wider, frame_centre=s.window.frame_centre,
                          second_centre=s.window.second_centre))
        self.assertEqual(len(s.explain_history()), len(s.turns))
        self.assertEqual(s.explain_history(), _explain_by_replay(s))

    def test_a_turn_before_a_SWITCH_still_names_the_old_pokemon(self):
        """The hazard the replay existed for, and the whole reason this cannot be read off the
        current state: after a switch, whoever is out now has a different moveset."""
        bench = (Battler(name="Magneton", level=55, types=("Electric", "Steel"),
                         stats={"hp": 137, "atk": 85, "def": 120,
                                "spa": 170, "spd": 99, "spe": 118},
                         moves=("Thunder Wave", "Screech", "", ""), pp=(20, 40, 0, 0),
                         party_slot=2),)
        s = _play(_session(bench=bench), [Action.MOVE_1, Action.MOVE_3])
        # The session's OWN state, which carries the bench -- an ad-hoc BattleState has none, and
        # a switch needs to know who came in.
        state = next(iter(s._session.states.values()))
        nxt = simulate_turn(state, Action.SWITCH, s.config, bench_slot=0)
        s.observe(Action.SWITCH, nxt.log[-1], bench_slot=0)
        if s.contradiction:
            self.skipTest("the fixture's switch turn was not predicted")
        explained = s.explain_history()
        self.assertEqual(explained, _explain_by_replay(s))
        # Turn 1 was a False Swipe by Smeargle; nothing in its sentence may name a Magneton move.
        first = " ".join(explained[0])
        self.assertNotIn("Thunder Wave", first)
        self.assertNotIn("Screech", first)


class TestTheCostTracksSurvivors(unittest.TestCase):
    """Timing, kept loose enough not to be flaky but tight enough to catch a regression of the
    kind reported -- the old code was ~1.8 SECONDS per turn here."""

    def test_a_narrowed_run_reports_a_turn_quickly(self):
        s = _play(_session(n=2000), [Action.MOVE_1, Action.MOVE_3, Action.MOVE_1, Action.MOVE_4])
        self.assertEqual(len(s.survivors), 1, "the fixture did not narrow to one seed")
        state = next(iter(s._session.states.values()))
        nxt = simulate_turn(state, Action.MOVE_1, s.config)
        start = time.perf_counter()
        s.observe(Action.MOVE_1, nxt.log[-1])
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.5,
                        f"one turn at one survivor took {elapsed:.2f}s; it was 1.8s before "
                        f"explain_history stopped replaying the run")

    def test_the_explanations_are_not_recomputed_on_every_snapshot(self):
        """The specific regression: a snapshot used to re-observe the whole run."""
        s = _play(_session(n=2000), [Action.MOVE_1, Action.MOVE_3, Action.MOVE_1])
        start = time.perf_counter()
        for _ in range(20):
            s.snapshot()
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 0.5, f"20 snapshots took {elapsed:.2f}s")


class TestTheMoveIndexIsCached(unittest.TestCase):
    def test_resolve_move_does_not_rebuild_its_index(self):
        start = time.perf_counter()
        for _ in range(50_000):
            resolve_move("False Swipe")
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0,
                        f"50,000 lookups took {elapsed:.2f}s; rebuilding the dict each time "
                        f"cost ~4s and 28M str.lower() calls")

    def test_it_still_resolves_every_spelling_it_used_to(self):
        for query, name in (("False Swipe", "False Swipe"), ("false swipe", "False Swipe"),
                            ("thunder-wave", "Thunder Wave"), ("THUNDER_WAVE", "Thunder Wave"),
                            ("  Hydro Pump ", "Hydro Pump")):
            with self.subTest(query):
                self.assertEqual(resolve_move(query).name, name)
        self.assertIsNone(resolve_move("Nonsense Move"))

    def test_the_number_index_is_cached_too(self):
        from claytonlib.moves import _moves_by_number

        self.assertIs(_moves_by_number(), _moves_by_number())


if __name__ == "__main__":
    unittest.main()
