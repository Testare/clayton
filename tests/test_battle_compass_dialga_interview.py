"""Two interview bugs from the Dialga run, both of them questions with no right answer.

Reported by Testare against Spear Pillar. Neither is a simulator bug -- `sim` was already
correct on both counts, which is what makes them dangerous: the page asked for something no
candidate could render, so the honest answer eliminated every seed including the true one.

1. **The recharge turn.** Roar of Time connects, and the turn after it Dialga does nothing at
   all. The ROM never asks a recharging battler to choose (`Battler_CanPickCommand` is FALSE, so
   no selection roll is spent) and `act_target` checks the flag before it looks at a move, so
   every candidate renders ``Erch``. The interview asked which of the four moves it used.

2. **A secondary that could not show.** Non-volatile statuses are mutually exclusive, so a 30%
   Discharge proc against an already-paralyzed target sets nothing and announces nothing --
   `sim._visible_tokens` suppresses the ``~`` for exactly this case, so the turn where the proc
   happened and the turn where it did not render IDENTICALLY. The interview asked whether the
   extra effect happened; "Yes" described something the player never saw.

Paralysis is the state the whole run is built on reaching, so (2) was live on nearly every turn
after the one that mattered.

3. **The recharge turn was ungrammatical.** `turn_requires_hp` scanned for the hit markers
   anywhere in a token, and ``rch`` ENDS IN ``h`` -- so ``Erch`` read as a hit and
   `validate_turn` refused the turn with "the target hit us, so this turn needs an HP token".
   Pre-existing since ``rch`` was added, and invisible until (1) made the turn reportable at
   all. See `TestPreventedTurnsNeedNoHp`.

4. **And the regression dropping (2) caused.** `hrTurnComplete` -- which decides whether "Report
   turn" is enabled -- carried its own copy of the secondary question's condition, so when the
   question stopped being asked the copy went on waiting for its answer. The button sat disabled
   with nothing on screen to explain it, on the turn after a Thunder Wave, which is every turn
   the plan has. The fix is to delegate rather than restate: see `TestTheButtonGate`.
"""
import datetime as dt
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.hunt_session import HuntSession, move_info, prevention_options
from claytonlib.battle_compass.sim import (
    EFFECT_ROAR_OF_TIME, MODELLED_OUR_EFFECTS, HuntConfig, opening_rng, select_target_move,
    simulate_turn, unselectable_reason,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.battle_compass import tokens as tok
from claytonlib.moves import resolve_move

HUNT = HuntConfig(target_catch_rate=30, target_has_pressure=True)
SEED = 0x0C0E02CA
#: Roar of Time is 90 accuracy, so a fixture that wants the recharge has to pick a seed where it
#: connects -- on `SEED` itself it misses, and a miss costs the recharge with it. This one also
#: happens to leave Discharge un-procced, which keeps the two halves of this file independent.
HIT_SEED = SEED + 2

ROAR, HEAL_BLOCK, EARTH_POWER, SLASH = 0, 1, 2, 3


def _dialga(**kw) -> Battler:
    """Only Roar of Time has PP, so the selection roll cannot pick away from it."""
    return replace(Battler(
        name="Dialga", level=70, types=("Steel", "Dragon"),
        stats=derive_species_stats("dialga", 70, "Timid", ivs=31),
        moves=moveset("dialga"), pp=(5, 0, 0, 0), ability="Pressure"), **kw)


def _ours(**kw) -> Battler:
    """A wall that outspeeds, holding **Discharge** -- the 30% paralysis secondary that is the
    other half of this file. Tanky enough that Roar of Time cannot end the turn."""
    return replace(Battler(
        name="Ampharos", level=100, types=("Electric",),
        stats={"hp": 500, "atk": 100, "def": 200, "spa": 150, "spd": 200, "spe": 250},
        moves=("Discharge", "Ancient Power"), pp=(15, 5)), **kw)


def _state(**kw) -> BattleState:
    fields = dict(ours=_ours(), target=_dialga(), rng=opening_rng(SEED, HUNT))
    fields.update(kw)
    return BattleState(**fields)


class TestTheSimulatorWasAlreadyRight(unittest.TestCase):
    """Pinned first, because it is what licenses calling both of these interview bugs."""

    def test_a_connecting_roar_of_time_leaves_it_recharging(self):
        state = simulate_turn(_state(rng=opening_rng(HIT_SEED, HUNT)), Action.MOVE_1, HUNT)
        self.assertEqual(resolve_move("Roar of Time").effect, EFFECT_ROAR_OF_TIME)
        self.assertTrue(state.target.recharging)

    def test_the_recharge_turn_renders_Erch_and_nothing_else_from_it(self):
        state = simulate_turn(_state(rng=opening_rng(HIT_SEED, HUNT)), Action.MOVE_1, HUNT)
        state = simulate_turn(state, Action.MOVE_1, HUNT)
        self.assertIn(tok.prevented_token("E", "rch"), tok.render_turn(state.log[-1]))

    def test_no_selection_roll_is_spent_on_it(self):
        """Which is why offering the four moves was not merely cosmetic: a slot the player picked
        would have been compared against a turn that never chose one."""
        target = _dialga(recharging=True)
        self.assertEqual(select_target_move(0x1234_5678, target)[0], 0x1234_5678)

    def test_our_own_side_can_never_reach_this_state(self):
        """So the target-only fix is complete rather than half of one: effect 80 is absent from
        `MODELLED_OUR_EFFECTS`, and `unselectable_reason` refuses the move outright."""
        self.assertNotIn(EFFECT_ROAR_OF_TIME, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Roar of Time")))

    def test_a_proc_against_a_paralyzed_target_is_already_suppressed(self):
        """The ``~`` never appears, over every seed in a sweep -- `_visible_tokens` drops it. So
        the two turns are indistinguishable and the question had no answer to give."""
        marked = 0
        for i in range(60):
            rng = opening_rng(SEED + i * 0x1000, HUNT)
            state = _state(rng=rng, target=_dialga(status=Status.PARALYSIS))
            marked += tok.SECONDARY in tok.render_turn(
                simulate_turn(state, Action.MOVE_1, HUNT).log[-1])
        self.assertEqual(marked, 0)

    def test_and_it_really_does_appear_against_an_unstatused_one(self):
        """The control. Without it the test above would pass on a Discharge that never procs."""
        marked = 0
        for i in range(60):
            rng = opening_rng(SEED + i * 0x1000, HUNT)
            state = _state(rng=rng)
            marked += tok.SECONDARY in tok.render_turn(
                simulate_turn(state, Action.MOVE_1, HUNT).log[-1])
        self.assertGreater(marked, 20)


class TestWhatTheSnapshotPublishes(unittest.TestCase):
    def test_the_target_reports_that_it_must_recharge(self):
        session = _pinned()
        session._session.states = {
            seed: replace(st, target=replace(st.target, recharging=True))
            for seed, st in session._session.states.items()}
        self.assertTrue(session.snapshot()["target"]["recharging"])

    def test_and_says_nothing_on_an_ordinary_turn(self):
        self.assertFalse(_pinned().snapshot()["target"]["recharging"])

    def test_it_is_not_offered_as_a_prevention_option(self):
        """A settled outcome rather than a question, so it stays out of the menu `prevention_
        options` builds -- the page asserts it, the way it asserts a sleep we just landed."""
        codes = {o["code"] for o in prevention_options(
            _dialga(recharging=True), _ours(), actor_moves_first=False)}
        self.assertNotIn("rch", codes)


class TestWhenASecondaryCannotShow(unittest.TestCase):
    def test_a_paralysis_secondary_against_a_paralyzed_target(self):
        row = move_info(_ours(), _dialga(status=Status.PARALYSIS))[0]
        self.assertEqual(row["name"], "Discharge")
        self.assertTrue(row["has_secondary"])
        self.assertTrue(row["secondary_cannot_show"])

    def test_any_status_blocks_it_not_only_the_matching_one(self):
        """Mutual exclusion is the mechanic, so a sleeping target blocks a paralysis proc just as
        a paralyzed one does."""
        for status in (Status.SLEEP, Status.BURN, Status.FREEZE, Status.POISON):
            with self.subTest(status.value):
                self.assertTrue(
                    move_info(_ours(), _dialga(status=status))[0]["secondary_cannot_show"])

    def test_an_unstatused_target_keeps_the_question(self):
        self.assertFalse(move_info(_ours(), _dialga())[0]["secondary_cannot_show"])

    def test_a_secondary_that_is_not_a_status_keeps_it_too(self):
        """Ancient Power raises the ATTACKER's stats, which shows regardless of what the victim
        is carrying -- so the flag must read the secondary's KIND and not just the status."""
        row = move_info(_ours(), _dialga(status=Status.PARALYSIS))[1]
        self.assertEqual(row["name"], "Ancient Power")
        self.assertTrue(row["has_secondary"])
        self.assertFalse(row["secondary_cannot_show"])

    def test_a_move_with_no_secondary_at_all(self):
        row = move_info(_dialga(status=Status.PARALYSIS), _ours())[SLASH]
        self.assertEqual(row["effect_chance"], 0)
        self.assertFalse(row["secondary_cannot_show"])

    def test_an_empty_slot_carries_the_key(self):
        """Every other flag is published for an empty slot too; a missing key reads as `undefined`
        in the page, which is falsey by luck rather than by design."""
        row = move_info(Battler(name="x", level=1, types=("Normal",), stats={},
                                moves=("Discharge", ""), pp=(15, 0)), _dialga())[1]
        self.assertFalse(row["known"])
        self.assertIn("secondary_cannot_show", row)

    def test_it_needs_a_defender_to_decide(self):
        """`move_info` is called without one for the bench list, and a flag that guessed there
        would suppress a question on a turn it knows nothing about."""
        self.assertFalse(move_info(_ours())[0]["secondary_cannot_show"])


class TestThePageActsOnBoth(unittest.TestCase):
    """The fixes live in `index.html`, so this is the only place they can be pinned."""

    @classmethod
    def setUpClass(cls):
        import pathlib

        cls.html = (pathlib.Path(__file__).resolve().parent.parent
                    / "app" / "web" / "index.html").read_text()

    def test_the_recharge_turn_settles_itself(self):
        self.assertIn("if (s.target.recharging){", self.html)
        self.assertIn('t.target = {prevented: "rch"}', self.html)

    def test_it_is_settled_below_the_sleep_case(self):
        """Matching the ROM's before-move walk: `tick_sleep` precedes the recharge check at state
        4, so a target we put to sleep on its recharge turn reports as asleep."""
        self.assertLess(self.html.index('t.target = {prevented: "slp"}'),
                        self.html.index('t.target = {prevented: "rch"}'))

    def test_neither_secondary_question_survives_the_flag(self):
        self.assertIn("if (info.secondary_cannot_show)", self.html)
        self.assertIn("info.has_secondary && info.secondary_cannot_show && hrLanded(t.target)",
                      self.html)

    def test_and_the_interview_does_not_stall_waiting_for_it(self):
        """`hrOurSecondaryPending` gates the whole turn, so dropping the question without
        dropping the wait would leave the report unsubmittable."""
        self.assertIn("&& !info.secondary_cannot_show && hrLanded(t.ours)", self.html)


def _pinned(seed=SEED):
    """One candidate, Phase 2 -- enough to read a snapshot off."""
    window = CandidateWindow(
        key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
        frame_centre=1000, second_centre=30, frame_window=0, second_window=0,
        candidates=(Candidate(seed=seed, frame=1000, second=30),))
    session = HuntSession(window, _ours(), _dialga(), HUNT, capture_ball="Dusk Ball")
    session.enter_pinning()
    return session


class TestTheButtonGate(unittest.TestCase):
    """The reported turn, and the gate that refused to report it.

    Raichu Thunder Waves Dialga; next turn it Discharges, Dialga crits with Slash and Raichu
    faints. Every answer the interview asks for is given and "Report turn" stays disabled,
    because the completeness check was still waiting on a secondary question that is no longer
    asked -- the proc could not have shown against a target the Thunder Wave had already
    paralyzed (reported by Testare).
    """

    #: The crit, found by sweeping rather than chosen.
    CRIT_SEED = SEED + 14

    def _turn(self):
        raichu = Battler(
            name="Raichu", level=50, types=("Electric",),
            stats={"hp": 130, "atk": 90, "def": 55, "spa": 90, "spd": 80, "spe": 110},
            moves=("Discharge", "Thunder Wave"), pp=(15, 20), ability="Static", hp=69)
        bench = (Battler(
            name="Magneton", level=50, types=("Electric", "Steel"),
            stats={"hp": 120, "atk": 60, "def": 95, "spa": 120, "spd": 70, "spe": 70},
            moves=("Thunder Wave",), pp=(20,), party_slot=2),)
        state = BattleState(ours=raichu, target=_dialga(pp=(0, 0, 0, 20),
                                                        status=Status.PARALYSIS),
                            bench=bench, rng=opening_rng(self.CRIT_SEED, HUNT))
        return simulate_turn(state, Action.MOVE_1, HUNT)

    def test_the_turn_the_player_watched(self):
        """`M1hE4!X2` -- and no `~` on the Discharge, which is the whole point: the proc either
        happened or did not and the turn reads the same either way."""
        after = self._turn()
        rendered = tok.render_turn(after.log[-1])
        self.assertEqual(rendered, "M1hE4!X2")
        self.assertNotIn(tok.SECONDARY, rendered)

    def test_it_needs_no_HP_and_the_grammar_accepts_it(self):
        """So nothing else in the interview was holding the button -- a faint replaces the HP
        token rather than joining it."""
        after = self._turn()
        self.assertFalse(tok.turn_requires_hp(after.log[-1]))
        self.assertEqual(tok.validate_turn(after.log[-1]), [])

    def test_static_was_never_the_blocker(self):
        """Worth pinning, because Slash makes contact and Raichu's ability is Static -- so this
        turn has a second question of exactly the same shape. `hrStaticPossibleOnTarget` already
        reads the target's status, which is the precedent `secondary_cannot_show` follows."""
        self.assertIn('if (s.target.status && s.target.status !== "none") return false;',
                      _html())

    def _gate(self):
        """`hrTurnComplete`'s body, so the assertions below cannot be satisfied by some other
        function that happens to mention the same names."""
        html = _html()
        start = html.index("function hrTurnComplete(){")
        return html[start:html.index("\n}\n", start)]

    def test_our_half_delegates_instead_of_restating(self):
        """One source of truth. A second copy of the condition is what broke, so the test is that
        there is no second copy rather than that the copy was updated."""
        gate = self._gate()
        self.assertIn("if (hrOurSecondaryPending()) return false;", gate)
        self.assertNotIn("t.ours.secondary === undefined", gate)

    def test_the_target_half_reads_the_flag(self):
        """It cannot delegate the same way -- there is no target-side pending helper -- so it
        carries the flag explicitly."""
        gate = self._gate()
        self.assertIn("!info.secondary_cannot_show", gate)
        self.assertIn("t.target.secondary === undefined", gate)

    def test_the_two_gates_cannot_disagree_about_our_half(self):
        """The rendering gate and the button gate are now the same predicate, which is the
        invariant that was violated: a question nobody asks must not be waited on."""
        html = _html()
        start = html.index("function hrOurSecondaryPending(){")
        pending = html[start:html.index("\n}\n", start)]
        self.assertIn("!info.secondary_cannot_show", pending)
        self.assertIn("hrOurSecondaryPending()", self._gate())


class TestPreventedTurnsNeedNoHp(unittest.TestCase):
    """A substring collision, and the reason the recharge turn could not be reported at all.

    `tokens.turn_requires_hp` asked whether the hit markers appeared anywhere in an ``E`` token.
    ``rch`` ends in ``h``, so ``Erch`` -- a Dialga doing nothing whatever -- read as a hit, and
    `validate_turn` rejected the turn with "the target hit us, so this turn needs an HP token".

    Pre-existing since ``rch`` was added, and invisible until the interview started producing the
    turn: before that nobody could report one, so nothing ever handed this function an `Erch`.
    """

    def test_no_prevention_marker_demands_hp(self):
        """The structural guard. Written over the whole set rather than over ``rch`` so the next
        marker carrying an ``h`` or a ``!`` fails here instead of silently reading as a hit --
        which is how this one got in."""
        for marker in sorted(tok.PREVENTION_DETAIL):
            with self.subTest(marker):
                turn = ("M1", tok.prevented_token("E", marker))
                self.assertFalse(tok.turn_requires_hp(turn))
                self.assertEqual(tok.validate_turn(turn), [])

    def test_the_reported_turn(self):
        self.assertFalse(tok.turn_requires_hp(("M2", "Erch")))
        self.assertEqual(tok.validate_turn(("M2", "Erch")), [])

    def test_a_real_hit_still_demands_it(self):
        """The control -- a fix that stopped asking for HP at all would pass everything above."""
        for turn in (("M1", "E1h"), ("M1", "E1!")):
            with self.subTest(turn):
                self.assertTrue(tok.turn_requires_hp(turn))
                self.assertIn("the target hit us, so this turn needs an HP token",
                              tok.validate_turn(turn))

    def test_a_RESOLVED_status_is_not_skipped_with_them(self):
        """`scfz` precedes a slot because the move went AHEAD, so a turn that snapped out of
        confusion and then hit us still needs its HP. Only `PREVENTION_DETAIL` is skipped, and
        this is the token that proves the distinction is load-bearing."""
        self.assertTrue(tok.turn_requires_hp(("Escfz2h",)))

    def test_a_taunt_refusal_needs_none_either(self):
        """Not a prevention marker -- it keeps its slot -- but the move never executed. It was
        already right, because `tnt` carries no ``h``; pinned so it stays right."""
        self.assertFalse(tok.turn_requires_hp(("M1", "E2tnt")))


class TestReportingARechargeTurnEndToEnd(unittest.TestCase):
    """The whole path the player walks: a Roar of Time connects, then the recharge is reported.

    Through `HuntSession.observe`, because that is where both failures lived -- the grammar check
    rejected the turn before the candidate comparison ever ran.
    """

    #: Roar of Time is 90 accuracy and Dialga is paralyzed, so most seeds give a miss or a full
    #: paralysis. This one connects.
    CONNECTS = SEED + 3

    def _session(self):
        ours = Battler(
            name="Magneton", level=100, types=("Electric", "Steel"),
            stats={"hp": 400, "atk": 60, "def": 200, "spa": 120, "spd": 200, "spe": 300},
            moves=("Thunder Wave", "Flash"), pp=(20, 20), ability="Sturdy")
        window = CandidateWindow(
            key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
            frame_centre=1000, second_centre=30, frame_window=0, second_window=0,
            candidates=(Candidate(seed=self.CONNECTS, frame=1000, second=30),))
        session = HuntSession(window, ours, _dialga(pp=(5, 0, 0, 0), status=Status.PARALYSIS),
                              HUNT, capture_ball="Dusk Ball")
        session.enter_pinning()
        return session

    def test_both_turns_are_accepted(self):
        session = self._session()
        first = session.predict(Action.MOVE_2)[self.CONNECTS]
        self.assertEqual(tok.render_turn(first), "M2E1hHP321")
        snapshot = session.observe(Action.MOVE_2, first)
        self.assertIsNone(snapshot["contradiction"])
        self.assertTrue(snapshot["target"]["recharging"])

        second = session.predict(Action.MOVE_2)[self.CONNECTS]
        self.assertEqual(tok.render_turn(second), "M2Erch")
        snapshot = session.observe(Action.MOVE_2, second)
        self.assertIsNone(snapshot["contradiction"])
        self.assertFalse(snapshot["target"]["recharging"])

    def test_the_recharge_turn_carries_no_hp_and_is_not_asked_to(self):
        """Which is the agreement that was broken: the simulator rendered no HP token and the
        grammar demanded one, so the turn the tool itself predicted was unreportable."""
        session = self._session()
        session.observe(Action.MOVE_2, session.predict(Action.MOVE_2)[self.CONNECTS])
        second = session.predict(Action.MOVE_2)[self.CONNECTS]
        self.assertFalse(any(t.startswith("HP") for t in second))
        self.assertFalse(tok.turn_requires_hp(second))
        self.assertEqual(tok.validate_turn(list(second)), [])


def _html():
    import pathlib

    return (pathlib.Path(__file__).resolve().parent.parent
            / "app" / "web" / "index.html").read_text()


if __name__ == "__main__":
    unittest.main()
