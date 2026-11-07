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

    def test_a_switch_and_a_revive_both_give_the_PARTY_SLOT(self):
        """Which is what the token says, and not what `observe` takes.

        The old reading had a switch coming back as `bench_slot` and a revive as `replacement`,
        and both were wrong. A switch's number is a PARTY SLOT -- stable for the whole run, which
        is why switching out and back reads ``S3`` then ``S1`` -- while `simulate_turn` indexes
        `state.bench`, which a switch rearranges; so a one-member bench got `bench_slot=2` and
        raised. And a revive indexes the bench exactly as a switch does, while `replacement` is a
        different question entirely (who came in after a FAINT), so a Revive turn reached
        `simulate_turn` with no slot at all.

        Translating needs the live bench, which only the caller has, so this stays a pure reader
        of the turn -- see `replay_path` and `sim.bench_slot_for_party_number`.
        """
        self.assertEqual(_action_from_tokens(tok.tokenise("S3"))[1], {"party_slot": 3})
        self.assertEqual(_action_from_tokens(tok.tokenise("R2"))[1], {"party_slot": 2})

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


class TestASwitchInThePathReplays(unittest.TestCase):
    """The reported break (round 9 feedback): "Loading from path breaks for switch tokens?".

    It did, and loudly -- a raw `ValueError` out of `simulate_turn` rather than a contradiction --
    because an ``S`` token carries the PARTY SLOT and `observe` takes a BENCH INDEX. The fixture
    below is the smallest shape that shows it: one Pokemon on the bench, at party slot 2, so the
    token reads ``S2`` and the index is 0.
    """

    @staticmethod
    def _with_bench():
        session = _session()
        magneton = Battler(name="Magneton", level=54, types=("Electric", "Steel"),
                           stats={"hp": 134, "atk": 70, "def": 95, "spa": 120, "spd": 70,
                                  "spe": 124},
                           moves=("Thunder Wave",), pp=(20,), party_slot=2)
        session.bench = (magneton,)
        for state in session._session.states.values():
            state.bench = (magneton,)
        return session

    def _switch_turn(self, session):
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import BattleState

        state = BattleState(rng=session._session.states[SEED].rng, ours=session.ours,
                            target=session.target, bench=session.bench)
        nxt = simulate_turn(state, Action.SWITCH, session.config, bench_slot=0)
        return tok.render_turn(tok.normalise(list(nxt.log[-1])))

    def test_the_token_names_the_party_slot_and_not_the_bench_index(self):
        """Which is the whole reason a translation is needed. Pinned first, because if this ever
        stopped being true the fix below would be the bug."""
        turn = self._switch_turn(self._with_bench())
        self.assertTrue(turn.startswith("S2"), turn)

    def test_and_replaying_that_turn_works(self):
        session = self._with_bench()
        turn = self._switch_turn(session)
        replayed = self._with_bench()
        snap = replayed.replay_path(turn)
        self.assertIsNone(replayed.contradiction, snap.get("contradiction"))
        self.assertEqual(len(replayed.turns), 1)
        self.assertEqual(replayed.turns[0].rendered, turn)

    def test_a_slot_that_names_nobody_is_reported_rather_than_raised(self):
        """A path is something the player pasted, so a slot naming nobody is a typo to report."""
        session = self._with_bench()
        session.replay_path("S5E1")
        self.assertIsNotNone(session.contradiction)
        problems = " ".join(session.contradiction["problems"])
        self.assertIn("party slot 5", problems)
        self.assertIn("Magneton", problems)
        self.assertEqual(len(session.turns), 0)

    def test_a_revive_in_the_path_replays_too(self):
        """The second half of the same bug, and the louder one: a Revive came back as
        `replacement`, so `simulate_turn` got no slot at all and raised "a Revive needs which
        party member it was used on". `replacement` is who came in after a FAINT -- a different
        question, resolved at the end of the turn."""
        from claytonlib.battle_compass.sim import simulate_turn
        from claytonlib.battle_compass.state import BattleState

        def with_fainted():
            session = _session()
            down = Battler(name="Magneton", level=54, types=("Electric", "Steel"),
                           stats={"hp": 134, "atk": 70, "def": 95, "spa": 120, "spd": 70,
                                  "spe": 124},
                           moves=("Thunder Wave",), pp=(20,), party_slot=2).with_hp(0)
            session.bench = (down,)
            for state in session._session.states.values():
                state.bench = (down,)
            return session

        session = with_fainted()
        state = BattleState(rng=session._session.states[SEED].rng, ours=session.ours,
                            target=session.target, bench=session.bench)
        nxt = simulate_turn(state, Action.REVIVE, session.config, bench_slot=0)
        turn = tok.render_turn(tok.normalise(list(nxt.log[-1])))
        self.assertTrue(turn.startswith("R2"), turn)

        replayed = with_fainted()
        snap = replayed.replay_path(turn)
        self.assertIsNone(replayed.contradiction, snap.get("contradiction"))
        self.assertEqual(replayed.turns[0].rendered, turn)

    def test_the_inverse_mapping_round_trips_against_party_number(self):
        """Including the positional fallback for a Battler with no slot set, which the
        simulator's own fixtures rely on."""
        from claytonlib.battle_compass.sim import bench_slot_for_party_number, party_number

        named = Battler(name="A", level=5, types=("Normal",),
                        stats={"hp": 20, "atk": 5, "def": 5, "spa": 5, "spd": 5, "spe": 5},
                        moves=("Tackle",), pp=(35,), party_slot=4)
        bare = Battler(name="B", level=5, types=("Normal",),
                       stats={"hp": 20, "atk": 5, "def": 5, "spa": 5, "spd": 5, "spe": 5},
                       moves=("Tackle",), pp=(35,))
        bench = (named, bare)
        for index, member in enumerate(bench):
            self.assertEqual(bench_slot_for_party_number(bench, party_number(member, index)),
                             index)
        self.assertIsNone(bench_slot_for_party_number(bench, 99))


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
