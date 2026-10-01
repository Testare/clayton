"""The second emulator recording — 38 turns, and the bug that only a real log could find.

``data/battle_logs/test2.jsonl`` is a hand-played Bell Tower Suicune battle with the battle seed
forced to 0xc5011e3f.  It is more than twice the length of test1 and much broader: Gust and a
critical Aurora Beam, Mist set and expiring three times, rain set and expiring twice, Sweet Scent
blocked by Mist and then driven to -6 evasion, three potion tiers, and eight Poke Ball throws
shaking zero, one and two times.

It found what test1 could not, because test1 was only ever replayed as a *simulation* and this one
was replayed as an *identification*: ``Session`` seeded every candidate's state with the raw
battle seed, six advances behind the stream the game actually runs.  Every synthetic fixture in
``test_battle_compass_identify`` built its expectations the same wrong way, so they agreed with
each other and nothing failed.  Here the true seed was eliminated on turn one while 29 unrelated
candidates survived -- the worst shape of failure available, since no contradiction is raised and
the run proceeds confidently into a wrong seed.

Unlike test1, the per-turn advance counts here are **derived from the log** rather than
transcribed into a constant: a turn opens with the wild move-selection roll, whose call site is
distinctive, so the segmentation is mechanical. Nothing in this file is a hand-copied number that
could be quietly adjusted until it matched.

Skips if the log is absent, so the suite still runs without it.
"""
import json
import pathlib
import unittest

from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.candidates import Candidate
from claytonlib.battle_compass.identify import Phase, Session
from claytonlib.battle_compass.sim import (
    BATTLE_START_ADVANCES, HuntConfig, opening_rng, simulate_turn,
)
from claytonlib.battle_compass.state import Action, BattleState
from claytonlib.safari import advance_rng
from tests.test_battle_compass_ground_truth import _magneton, _smeargle, _suicune

LOG = pathlib.Path(__file__).resolve().parent.parent / "data" / "battle_logs" / "test2.jsonl"

FORCED_SEED = 0xC5011E3F
#: Call site of the wild move-selection roll, which is what opens a turn. The symbol table
#: cannot name it, but the address is stable within a recording and is the only roll at it.
SELECTION_ROLL_ADDR = "0x0225e46e"

CONFIG = HuntConfig(target_catch_rate=3)

#: What was played, in order. Magneton leads with Thunder Wave and switches to Smeargle, whose
#: slots are False Swipe / Mean Look / Sweet Scent / Spore.
ACTIONS: list[tuple[Action, dict]] = (
    [(Action.MOVE_1, {}), (Action.SWITCH, {"bench_slot": 0})]
    + [(Action.MOVE_1, {})] * 5                     # False Swipe, 141 -> 1 HP
    + [(Action.MOVE_3, {})] * 4                     # Sweet Scent (first two blocked by Mist)
    + [(Action.MOVE_2, {})] * 3                     # Mean Look, then failing twice
    + [(Action.MOVE_4, {})]                         # Spore, failing into paralysis
    + [(Action.MOVE_3, {})] * 2
    + [(Action.MOVE_4, {})] * 2
    + [(Action.ITEM, {"item_code": "p"}), (Action.ITEM, {"item_code": "sp"})]
    + [(Action.MOVE_3, {})] * 4                     # the last two at -6 evasion
    + [(Action.STANDARD_BALL, {})]
    + [(Action.ITEM, {"item_code": "hp"})]          # Hyper Potion, 2 -> 153
    + [(Action.MOVE_4, {})]
    + [(Action.MOVE_1, {})] * 2
    + [(Action.MOVE_4, {})]
    + [(Action.STANDARD_BALL, {})] * 7
)


def _records():
    return json.loads(LOG.read_text())["records"]


def _turns(records):
    """Segment the log into turns at each move-selection roll.

    Returns one entry per completed turn: (advances, messages, HP reads). The trailing partial
    turn -- the recording stops mid-turn -- is dropped.
    """
    starts = [i for i, r in enumerate(records)
              if "roll" in r and r["roll"]["addr"] == SELECTION_ROLL_ADDR]
    out = []
    for a, b in zip(starts, starts[1:] + [len(records)]):
        segment = records[a:b]
        out.append((
            sum(1 for r in segment if "roll" in r),
            [r["msg"].replace("\n", " ") for r in segment
             if "msg" in r and not r["msg"].startswith("What will")],
            [(x["battler"], x["hp"]) for r in segment if "hp" in r for x in r["hp"]],
        ))
    return out[:-1]


def _replay():
    """Simulate the recorded battle. Returns per-turn (advances, rendered tokens, state)."""
    state = BattleState(ours=_magneton(), target=_suicune(),
                        rng=opening_rng(FORCED_SEED, CONFIG),
                        bench=(_smeargle(),), phase=1)
    out = []
    for action, kwargs in ACTIONS:
        before = state.rng_offset
        state = simulate_turn(state, action, CONFIG, **kwargs)
        out.append((state.rng_offset - before,
                    tok.render_turn(tok.normalise(state.log[-1])), state))
    return out


def _truth_tokens():
    """The token stream the log's turns actually produced, for feeding an identification."""
    return [(action, kwargs, tuple(tok.normalise(state.log[-1])))
            for (action, kwargs), (_, _, state) in zip(ACTIONS, _replay())]


def _window(frame_window=60):
    """A frame window centred on the true seed, as a run against this seed would have.

    Built by varying the low 16 bits directly rather than through ``calculate_seed``: the forced
    seed was written into memory by gdb and never corresponded to a real datetime, so there is no
    (time, delay) pair to centre on. The shape -- one RTC second, a contiguous run of frames --
    is what ``candidates.generate`` produces.
    """
    base, centre = FORCED_SEED & 0xFFFF0000, FORCED_SEED & 0xFFFF
    return [Candidate(seed=base + f, frame=f, second=0)
            for f in range(centre - frame_window, centre + frame_window + 1)]


class TestTheLogIsPresent(unittest.TestCase):
    def setUp(self):
        if not LOG.exists():
            self.skipTest(f"{LOG} not present")

    def test_it_parses_and_declares_the_forced_seed(self):
        doc = json.loads(LOG.read_text())
        self.assertEqual(int(doc["forced_seed"], 16), FORCED_SEED)

    def test_it_holds_thirty_eight_complete_turns(self):
        self.assertEqual(len(_turns(_records())), 38)
        self.assertEqual(len(ACTIONS), 38)

    def test_the_roll_values_are_the_lcrng_from_the_forced_seed(self):
        """Validates the parse and the RNG together: if either were wrong this diverges at once.

        Each roll is the high 16 bits of the next LCRNG state, which is what makes a
        hand-transcribed log impossible to fake and this whole file trustworthy.
        """
        rolls = [r["roll"]["val"] for r in _records() if "roll" in r]
        rng = FORCED_SEED
        for index, actual in enumerate(rolls):
            rng = advance_rng(rng)
            self.assertEqual(rng >> 16, actual, f"roll {index} diverged")

    def test_exactly_the_start_advances_precede_the_first_turn(self):
        records = _records()
        first = next(i for i, r in enumerate(records)
                     if "roll" in r and r["roll"]["addr"] == SELECTION_ROLL_ADDR)
        self.assertEqual(sum(1 for r in records[:first] if "roll" in r),
                         BATTLE_START_ADVANCES)


class TestEveryTurnSpendsTheRightAdvances(unittest.TestCase):
    """Thirty-eight independent checks of the per-turn skeleton. One wrong count desynchronises
    everything after it, so a clean run across this many turns is strong evidence."""

    def setUp(self):
        if not LOG.exists():
            self.skipTest("log not present")

    def test_all_thirty_eight_match(self):
        mismatches = []
        for n, ((advances, rendered, _), (actual, msgs, _)) in enumerate(
                zip(_replay(), _turns(_records())), 1):
            if advances != actual:
                mismatches.append(f"turn {n}: simulated {advances}, game spent {actual} "
                                  f"({rendered}) :: {' | '.join(msgs)}")
        self.assertEqual(mismatches, [], "; ".join(mismatches))


class TestTheObservableStreamMatches(unittest.TestCase):
    """Advance counts can agree while the *reasons* differ, so the visible outcomes are checked
    against the log's own messages independently."""

    def setUp(self):
        if not LOG.exists():
            self.skipTest("log not present")
        self.replay = _replay()
        self.actual = _turns(_records())

    def _expected_target_token(self, msgs):
        """Which E-token the log's messages imply, or None where they imply nothing checkable."""
        for msg in msgs:
            if "It can't move!" in msg:
                return "Epar"
            if "used Rain Dance" in msg:
                return "E1"
            if "used Gust" in msg:
                return "E2"
            if "used Aurora Beam" in msg:
                return "E3"
            if "used Mist" in msg:
                return "E4"
        return None

    def test_every_turn_picks_the_move_the_game_picked(self):
        wrong = []
        for n, ((_, rendered, _), (_, msgs, _)) in enumerate(zip(self.replay, self.actual), 1):
            expected = self._expected_target_token(msgs)
            if expected and expected not in rendered:
                wrong.append(f"turn {n}: expected {expected} in {rendered}")
        self.assertEqual(wrong, [], "; ".join(wrong))

    def test_it_covers_the_whole_moveset_and_full_paralysis(self):
        """So the agreement is not luck on one or two moves. Gust in particular appears here and
        never did in test1."""
        seen = {self._expected_target_token(msgs) for _, msgs, _ in self.actual}
        self.assertEqual(seen - {None}, {"E1", "E2", "E3", "E4", "Epar"})

    def test_our_hp_matches_every_read(self):
        """Incoming damage, healing and the critical hit on turn 26, against the log's HP reads.
        Battler 0 is our side."""
        wrong = []
        for n, ((_, rendered, state), (_, _, hps)) in enumerate(zip(self.replay, self.actual), 1):
            for battler, hp in hps:
                if battler == 0 and state.ours.hp != hp:
                    wrong.append(f"turn {n}: simulated {state.ours.hp}, log read {hp} "
                                 f"({rendered})")
        self.assertEqual(wrong, [], "; ".join(wrong))

    def test_the_targets_hp_matches_every_read(self):
        """Outgoing damage: five False Swipes taking Suicune 141 -> 1."""
        wrong = []
        for n, ((_, rendered, state), (_, _, hps)) in enumerate(zip(self.replay, self.actual), 1):
            for battler, hp in hps:
                if battler == 1 and state.target.hp != hp:
                    wrong.append(f"turn {n}: simulated {state.target.hp}, log read {hp} "
                                 f"({rendered})")
        self.assertEqual(wrong, [], "; ".join(wrong))

    def test_the_critical_hit_is_rendered_as_one(self):
        """Turn 26's Aurora Beam crit, which took us to 2 HP -- the only crit in either log."""
        self.assertIn("!", self.replay[25][1])
        self.assertIn("A critical hit!", self.actual[25][1])

    def test_every_shake_count_matches(self):
        """Eight throws, and the ROM's message names the count exactly.

        The four messages are a strictly ordered ladder, and writing this map down carelessly is
        how a shake count gets "verified" against the wrong wording: "Aargh! Almost had it!" is
        TWO shakes and "Gah! It was so close, too!" is three. Drafting it with both at three
        failed here against a simulated P2 -- the test was wrong and the simulator right, which
        is the only reason it is worth stating the ladder in full.
        """
        wording = {"broke free": 0, "appeared to be caught": 1,
                   "Almost had it": 2, "so close, too": 3}
        checked = 0
        for n, ((_, rendered, _), (_, msgs, _)) in enumerate(zip(self.replay, self.actual), 1):
            for msg in msgs:
                for phrase, shakes in wording.items():
                    if phrase in msg:
                        self.assertIn(f"P{shakes}", rendered, f"turn {n}: {rendered}")
                        checked += 1
        self.assertEqual(checked, 8)

    def test_the_attack_drop_is_rendered(self):
        """Aurora Beam's 10% secondary, which procced once in 38 turns (turn 35)."""
        drops = [n for n, (_, msgs, _) in enumerate(self.actual, 1)
                 if any("Attack fell" in m for m in msgs)]
        self.assertEqual(drops, [35])
        self.assertIn("~", self.replay[34][1])


class TestIdentificationPinsTheTrueSeed(unittest.TestCase):
    """The end-to-end check this log exists for: the assertion test1 never made.

    Simulation agreeing with a recording is necessary but not sufficient -- identification seeds
    its candidates independently, and that is where the six missing advances lived."""

    def setUp(self):
        if not LOG.exists():
            self.skipTest("log not present")

    def _session(self):
        return Session(_window(), _magneton(), _suicune(), CONFIG, phase=Phase.SETUP)

    def test_a_sixty_frame_window_narrows_to_the_true_seed(self):
        session = self._session()
        for state in session.states.values():
            state.bench = (_smeargle(),)   # Session takes no bench; HuntSession injects it too
        self.assertEqual(len(session.states), 121)
        self.assertIn(FORCED_SEED, session.states)

        pinned_at = None
        for n, (action, kwargs, tokens) in enumerate(_truth_tokens(), 1):
            # No phase juggling needed any more: balls are legal from Phase 1 on. The log's own
            # eight Poke Ball throws replay as ordinary turns, which is what the real run does.
            result = session.observe(action, tokens, **kwargs)
            self.assertFalse(result.contradiction, f"turn {n} matched no candidate")
            self.assertIn(FORCED_SEED, session.states,
                          f"the true seed was eliminated on turn {n}")
            if pinned_at is None and session.identified is not None:
                pinned_at = n
        self.assertEqual(session.identified, FORCED_SEED)
        self.assertIsNotNone(pinned_at)
        self.assertLessEqual(pinned_at, 10, f"pinned only on turn {pinned_at}")

    def test_without_the_start_advances_the_true_seed_dies_on_turn_one(self):
        """The regression, stated as the failure it was. Note it is not a contradiction: 29 wrong
        candidates survive turn 1, so there is no signal that anything went wrong."""
        candidates = _window()
        wrong = Session(candidates, _magneton(), _suicune(),
                        HuntConfig(target_catch_rate=3, battle_start_advances=0),
                        phase=Phase.SETUP)
        for state in wrong.states.values():
            state.bench = (_smeargle(),)
        action, kwargs, tokens = _truth_tokens()[0]
        result = wrong.observe(action, tokens, **kwargs)
        self.assertFalse(result.contradiction)
        self.assertNotIn(FORCED_SEED, wrong.states)
        self.assertGreater(len(wrong.states), 1)


class TestTheStartAdvanceConventionLivesInOnePlace(unittest.TestCase):
    def test_the_session_seeds_its_candidates_through_opening_rng(self):
        """Which is what stops a fixture from re-introducing the bug by agreeing with itself."""
        session = Session([Candidate(seed=FORCED_SEED, frame=0, second=0)],
                          _magneton(), _suicune(), CONFIG)
        self.assertEqual(session.states[FORCED_SEED].rng, opening_rng(FORCED_SEED, CONFIG))
        self.assertNotEqual(session.states[FORCED_SEED].rng, FORCED_SEED)

    def test_the_count_is_six_and_configurable(self):
        self.assertEqual(BATTLE_START_ADVANCES, 6)
        self.assertEqual(CONFIG.battle_start_advances, 6)
        self.assertEqual(opening_rng(FORCED_SEED, HuntConfig(target_catch_rate=3,
                                                             battle_start_advances=0)),
                         FORCED_SEED)


if __name__ == "__main__":
    unittest.main()
