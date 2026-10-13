"""Replaying a rendered path, so a run can be recovered instead of retyped.

Requested from the app: "A button to 'load path' would be good after loading seed A, where we
could paste the path we copied from the shared summary screen... I've had some issues where an
error with the code occured, or I missed a frame when doing not-shiny runs and couldn't tell
until damage calculations were off."

The round-trip is what makes this safe: `tokens.render_path` writes what the tool displays and
`tokens.split_turns` + `tokens.tokenise` read it back, so a path the tool produced is a path it
can consume. This asserts that end to end rather than trusting it.

clayton-fag.
"""
import datetime as dt
import unittest

from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.hunt_session import HuntSession, _action_from_tokens
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.state import Action, Battler
from claytonlib.battle_compass.targets import moveset
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.moves import resolve_move

SEED = 0xEC1504DC


def _session(n=24):
    ours = Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                   moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                   pp=(40, 5, 20, 15))
    moves = moveset("suicune")
    target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                     stats=derive_species_stats("suicune", 40, "Bold"), moves=moves,
                     pp=tuple(resolve_move(m).pp for m in moves))
    cands = tuple(Candidate(seed=SEED + i, frame=1000 + i, second=30) for i in range(n))
    window = CandidateWindow(key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0),
                             vector_ms=5000.0, frame_centre=1000, second_centre=30,
                             frame_window=n // 2, second_window=0, candidates=cands)
    return HuntSession(window, ours, target, HuntConfig(target_catch_rate=3),
                       capture_ball="Fast Ball")


class TestTheActionIsReadOffTheTokens(unittest.TestCase):
    def test_each_of_our_actions_round_trips(self):
        for turn, action in (("M2hE4hHP110", Action.MOVE_2),
                             ("M3Eslp", Action.MOVE_3),
                             ("C0Eslp", Action.CAPTURE_BALL),
                             ("P0Eslp", Action.STANDARD_BALL),
                             ("IhpE2HP153", Action.ITEM),
                             ("IcE2", Action.ITEM_CURE),
                             ("S3E1", Action.SWITCH),
                             ("R2E3h", Action.REVIVE),
                             ("X3", Action.FAINTED)):
            with self.subTest(turn):
                self.assertEqual(_action_from_tokens(tok.tokenise(turn))[0], action)

    def test_a_turn_where_the_TARGET_moved_first_still_parses(self):
        """`E3!X3` -- their crit, then our faint and replacement. We never acted, so the turn
        does not lead with our half, and reading token zero called a legal turn unparseable."""
        action, extra = _action_from_tokens(tok.tokenise("E3!X3"))
        self.assertEqual(action, Action.FAINTED)
        self.assertEqual(extra, {"replacement": 3})

    def test_an_item_carries_its_code_and_a_bare_item_does_not_invent_one(self):
        self.assertEqual(_action_from_tokens(tok.tokenise("IhpE2"))[1], {"item_code": "hp"})
        self.assertEqual(_action_from_tokens(tok.tokenise("I"))[1], {})

    def test_a_switch_gives_a_bench_slot_and_a_revive_a_party_slot(self):
        """The one asymmetry `observe` imposes, so getting them the same way round would send a
        revive to the wrong Pokemon."""
        self.assertEqual(_action_from_tokens(tok.tokenise("S3"))[1], {"bench_slot": 3})
        self.assertEqual(_action_from_tokens(tok.tokenise("R2"))[1], {"replacement": 2})

    def test_a_turn_with_no_action_of_ours_is_refused(self):
        with self.assertRaises(ValueError):
            _action_from_tokens(tok.tokenise("E1HP040"))

    def test_an_empty_turn_is_refused(self):
        with self.assertRaises(ValueError):
            _action_from_tokens([])


class TestTheRoundTrip(unittest.TestCase):
    """The property that makes this safe: a path the tool rendered replays to the same place."""

    def test_a_played_run_replays_to_an_identical_state(self):
        played = _session()
        # Play a few turns by simulating the true seed, so the tokens are ones the tool produced.
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import BattleState

        state = BattleState(rng=played._session.states[SEED].rng,
                            ours=played.ours, target=played.target)
        actions = [Action.MOVE_1, Action.MOVE_3, Action.MOVE_1, Action.MOVE_4]
        for action in actions:
            nxt = simulate_turn(state, action, played.config)
            played.observe(action, nxt.log[-1])
            self.assertFalse(played.contradiction, f"fixture turn {action} was rejected")
            state = nxt

        path = played.snapshot()["path"]
        self.assertTrue(path, "the fixture produced no path to replay")

        replayed = _session()
        snap = replayed.replay_path(path)
        self.assertIsNone(replayed.contradiction, snap.get("contradiction"))
        self.assertEqual(len(replayed.turns), len(played.turns))
        self.assertEqual(snap["path"], path)
        self.assertEqual(snap["survivors"], played.snapshot()["survivors"])
        self.assertEqual(snap["identified"], played.snapshot()["identified"])

    def test_replaying_eliminates_the_same_candidates(self):
        played = _session()
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import BattleState

        state = BattleState(rng=played._session.states[SEED].rng,
                            ours=played.ours, target=played.target)
        for action in (Action.MOVE_1, Action.MOVE_1, Action.MOVE_1):
            nxt = simulate_turn(state, action, played.config)
            played.observe(action, nxt.log[-1])
            state = nxt
        before = set(played.survivors)
        self.assertLess(len(before), 24, "the fixture turns eliminated nothing to compare")

        replayed = _session()
        replayed.replay_path(played.snapshot()["path"])
        self.assertEqual(set(replayed.survivors), before)


class TestItStopsAtTheFirstBadTurn(unittest.TestCase):
    """Pressing on would report later turns against a state the game never reached, and the
    candidate set would end up confidently wrong rather than visibly stuck."""

    @staticmethod
    def _valid_first_turn():
        """A turn the fixture's candidates actually predict.

        Made up paths do not work here and that is the point: a bare ``M1h`` is a False Swipe
        with no target half, which no candidate predicts, so it contradicts at turn ONE. Taking
        the first turn from a simulated run is the only way to test "stops at turn 2".
        """
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import BattleState

        session = _session()
        state = BattleState(rng=session._session.states[SEED].rng,
                            ours=session.ours, target=session.target)
        nxt = simulate_turn(state, Action.MOVE_1, session.config)
        return tok.render_turn(tok.normalise(list(nxt.log[-1])))

    def test_an_ungrammatical_turn_stops_the_replay_and_says_where(self):
        first = self._valid_first_turn()
        session = _session()
        session.replay_path(f"{first} NONSENSE {first}")
        self.assertIsNotNone(session.contradiction)
        self.assertEqual(len(session.turns), 1,
                         "the valid first turn should be committed, the rest abandoned")
        problems = " ".join(session.contradiction["problems"])
        self.assertIn("turn 2", problems)

    def test_a_contradicting_turn_stops_and_keeps_the_turns_before_it(self):
        first = self._valid_first_turn()
        session = _session()
        session.replay_path(f"{first} E1HP040")
        self.assertIsNotNone(session.contradiction)
        self.assertEqual(len(session.turns), 1)

    def test_an_empty_path_is_reported_rather_than_silently_accepted(self):
        session = _session()
        session.replay_path("   ")
        self.assertIsNotNone(session.contradiction)
        self.assertIn("no turns", " ".join(session.contradiction["problems"]))

    def test_the_reported_turn_number_is_one_based_and_names_the_turn(self):
        first = self._valid_first_turn()
        session = _session()
        session.replay_path(f"{first} E1HP040")
        problems = " ".join(session.contradiction["problems"])
        self.assertIn("turn 2", problems)
        self.assertIn("E1HP040", problems)


if __name__ == "__main__":
    unittest.main()
