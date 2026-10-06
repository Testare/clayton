"""Fainting: the X and R tokens, the shortened turn, and stable party slots.

Rain Dance plus Hydro Pump means a Lv45 Lugia can faint a Pokemon at full HP, and a Lv70 Ho-Oh
can faint a Choice-Scarfed Magneton on the way to paralysing it -- so a faint has to be a
reportable *turn* rather than the end of the run.

The advance accounting is measured in-game and recorded in notes/ss_rng/fainting.md. Every number
asserted here traces back to it:

* the attacker keeps all of its rolls, its secondary-effect roll included;
* fainted before we moved, we spend none of our own AND the between-turn advances are dropped;
* the end-of-turn block shrinks from 4 to 3 (fainted before moving) or to 2 (after);
* sending the replacement out costs nothing.
"""
import unittest

from claytonlib.battle import turn as turn_costs
from claytonlib.battle_compass import items, tokens as tok
from claytonlib.battle_compass.sim import (
    HuntConfig, party_number, party_order, simulate_turn,
)
from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass.state import Action, Battler, BattleState

HUNT = HuntConfig(target_catch_rate=3, target_has_pressure=False)

#: Hydro Pump off a Lv70 Ho-Oh-grade attacker: enough to faint anything in the fixture outright.
BIG_HITTER = dict(name="Lugia", level=70, types=("Psychic", "Flying"),
                  stats={"hp": 1, "atk": 120, "def": 120, "spa": 200, "spd": 154, "spe": 200},
                  moves=("Hydro Pump",), pp=(5,), hp=1)


def _mon(name, *, hp=None, speed=50, slot=0, max_hp=100, moves=("Tackle",), pp=(35,)):
    return Battler(name=name, level=50, types=("Normal",),
                   stats={"hp": max_hp, "atk": 80, "def": 80, "spa": 80, "spd": 80,
                          "spe": speed},
                   moves=moves, pp=pp, hp=hp, party_slot=slot)


def _target(**kw):
    fields = dict(BIG_HITTER)
    fields.update(kw)
    return Battler(**fields)


def _window(n, start=0x4A1B2C3D):
    """A candidate window around consecutive seeds -- enough for the session to have something
    to narrow, which is all these tests need of it."""
    import datetime as dt
    return CandidateWindow(
        key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
        frame_centre=1000, second_centre=30, frame_window=max(1, n // 2), second_window=0,
        candidates=tuple(Candidate(seed=start + i, frame=1000 + i, second=30)
                         for i in range(n)))


def _state(ours, bench=(), *, rng=0x12345678, target=None):
    return BattleState(ours=ours, target=target or _target(), rng=rng,
                       bench=tuple(bench), phase=2)


def _rendered(state):
    return tok.render_turn(tok.normalise(state.log[-1]))


class TestAFaintIsATurnNotAnEnding(unittest.TestCase):
    """`BattleState.over` used to read ``ours.fainted``, which was right only while a faint ended
    the run. Now it reads `party_wiped`, and the difference is the whole feature."""

    def test_a_faint_with_a_replacement_does_not_end_the_battle(self):
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Smeargle", speed=70, slot=2)])
        nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=2)
        self.assertFalse(nxt.over)
        self.assertFalse(nxt.party_wiped)
        self.assertEqual(nxt.ours.name, "Smeargle")

    def test_a_faint_with_nothing_left_does(self):
        nxt = simulate_turn(_state(_mon("Magneton", hp=1, speed=20, slot=1)),
                            Action.FAINTED, HUNT)
        self.assertTrue(nxt.over)
        self.assertTrue(nxt.party_wiped)
        self.assertEqual(_rendered(nxt), "E1hXX")

    def test_a_bench_of_fainted_pokemon_is_still_a_wipe(self):
        """`healthy_bench`, not `bench`: a party of corpses is nobody to send out."""
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Smeargle", hp=0, speed=70, slot=2)])
        nxt = simulate_turn(state, Action.FAINTED, HUNT)
        self.assertTrue(nxt.party_wiped)
        self.assertIn(tok.WIPED, _rendered(nxt))

    def test_the_replacement_is_the_party_slot_the_player_reports(self):
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Mamoswine", speed=80, slot=2),
                        _mon("Smeargle", speed=70, slot=3)])
        nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=3)
        self.assertEqual(_rendered(nxt), "E1hX3")
        self.assertEqual(nxt.ours.name, "Smeargle")

    def test_the_fainted_pokemon_stays_in_the_party(self):
        """So a Revive has something to target. It goes back to its party slot, not to the end."""
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Mamoswine", speed=80, slot=2)])
        nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=2)
        self.assertEqual([(b.name, b.hp, b.party_slot) for b in nxt.bench],
                         [("Magneton", 0, 1)])

    def test_no_hp_token_accompanies_a_faint(self):
        """Zero is implied by the X, and after the switch the number would describe somebody
        else. `tokens.validate_turn` rejects a turn carrying both."""
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Smeargle", speed=70, slot=2)])
        rendered = _rendered(simulate_turn(state, Action.FAINTED, HUNT, replacement=2))
        self.assertNotIn("HP", rendered)
        self.assertEqual(tok.validate_turn(tok.tokenise(rendered)), [])

    def test_the_faint_count_is_what_the_solver_can_see(self):
        """`ours.fainted` is False again once the replacement is out, so the solver's hard
        constraint had to move onto something the switch does not erase."""
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Smeargle", speed=70, slot=2)])
        nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=2)
        self.assertEqual(nxt.faints, state.faints + 1)
        self.assertFalse(nxt.ours.fainted)
        self.assertEqual(nxt.copy().faints, 1, "a copy that drops it is a constraint that lapses")


class TestTheReplacementIsNamedByPartySlot(unittest.TestCase):
    """And not by a bench index, because one turn can invalidate an index: a switch resolves
    before any move, so a turn that switches AND then faints has already rearranged the bench by
    the time the replacement is chosen."""

    def _party(self):
        return (_mon("Magneton", hp=1, speed=20, slot=1),
                (_mon("Mamoswine", speed=80, slot=2),
                 _mon("Smeargle", hp=1, speed=70, slot=3)))

    def test_a_switch_then_a_faint_sends_out_the_slot_asked_for(self):
        ours, bench = self._party()
        state = _state(ours, bench)
        # Switch to Smeargle (bench index 1, party slot 3), which the attack then faints. The
        # bench at that point is Magneton (slot 1) and Mamoswine (slot 2) -- so bench index 1 is
        # Mamoswine, and index 0 is the Magneton we just switched OUT of.
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=1, replacement=1)
        self.assertEqual(_rendered(nxt), "S3E1hX1")
        self.assertEqual(nxt.ours.name, "Magneton")

    def test_the_same_turn_can_send_out_the_other_one_instead(self):
        ours, bench = self._party()
        nxt = simulate_turn(_state(ours, bench), Action.SWITCH, HUNT,
                            bench_slot=1, replacement=2)
        self.assertEqual(_rendered(nxt), "S3E1hX2")
        self.assertEqual(nxt.ours.name, "Mamoswine")

    def test_an_unknown_slot_falls_back_rather_than_crashing(self):
        """A prediction sweep asks every candidate what every action would do, and most of them
        do not faint at all -- so the replacement is optional and the default has to be sane."""
        ours, bench = self._party()
        nxt = simulate_turn(_state(ours, bench), Action.FAINTED, HUNT, replacement=None)
        self.assertEqual(_rendered(nxt), "E1hX2")


class TestTheTurnShortens(unittest.TestCase):
    """notes/ss_rng/fainting.md, measured in-game. The end-of-turn figures are the ones that
    matter most: they are spent on every ordinary turn, so a wrong count here desynchronises
    every turn AFTER the faint rather than the faint turn itself."""

    #: Hydro Pump against a fixture defender: crit roll, damage roll, accuracy roll.
    HYDRO_PUMP_ROLLS = 3

    def _offset(self, state, action, **kw):
        return simulate_turn(state, action, HUNT, **kw).rng_offset - state.rng_offset

    def test_fainted_before_moving_drops_our_half_and_the_between_turn_rolls(self):
        state = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                       [_mon("Smeargle", speed=70, slot=2)])
        self.assertEqual(
            self._offset(state, Action.FAINTED, replacement=2),
            turn_costs.SELECTION_ADVANCES
            + turn_costs.BEFORE_TURN_ADVANCES
            + self.HYDRO_PUMP_ROLLS
            + turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES
            + turn_costs.END_OF_TURN_ADVANCES_FAINTED_BEFORE_MOVING)

    def test_fainted_after_moving_keeps_them_and_spends_two_at_the_end(self):
        """We outspeed, so our move goes off and only the end-of-turn block shrinks.

        Mean Look rather than Thunder Wave on purpose: it bypasses the accuracy check and
        inflicts no status, so the turn carries no roll that depends on what our move DID -- the
        end-of-turn figure is then the only thing under test.
        """
        ours = _mon("Magneton", hp=1, speed=300, slot=1, moves=("Mean Look",), pp=(5,))
        state = _state(ours, [_mon("Smeargle", speed=70, slot=2)])
        nxt = simulate_turn(state, Action.MOVE_1, HUNT, replacement=2)
        self.assertIn("X2", _rendered(nxt))
        self.assertEqual(
            nxt.rng_offset - state.rng_offset,
            turn_costs.SELECTION_ADVANCES
            + turn_costs.BEFORE_TURN_ADVANCES
            + 0                                   # Mean Look: accuracy 0, no roll
            + turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES
            + turn_costs.BETWEEN_TURN_ADVANCES
            + self.HYDRO_PUMP_ROLLS
            + turn_costs.POST_SUCCESSFUL_MOVE_ADVANCES
            + turn_costs.END_OF_TURN_ADVANCES_FAINTED_AFTER_MOVING)

    def test_the_three_end_of_turn_figures_are_the_measured_ones(self):
        self.assertEqual(turn_costs.END_OF_TURN_ADVANCES, 4)
        self.assertEqual(turn_costs.END_OF_TURN_ADVANCES_FAINTED_BEFORE_MOVING, 3)
        self.assertEqual(turn_costs.END_OF_TURN_ADVANCES_FAINTED_AFTER_MOVING, 2)
        self.assertEqual(turn_costs.END_OF_TURN_ADVANCES_FAINTED_BY_RESIDUAL,
                         turn_costs.END_OF_TURN_ADVANCES)

    def test_sending_the_replacement_out_costs_nothing(self):
        """Two parties identical but for who is on the bench spend the same stream."""
        self.assertEqual(turn_costs.SEND_OUT_ADVANCES, 0)
        lone = _state(_mon("Magneton", hp=1, speed=20, slot=1))
        with_bench = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                            [_mon("Smeargle", speed=70, slot=2)])
        self.assertEqual(self._offset(lone, Action.FAINTED),
                         self._offset(with_bench, Action.FAINTED, replacement=2))

    def test_the_attacker_keeps_every_roll_it_was_going_to_spend(self):
        """Including the secondary-effect roll -- only its OUTCOME goes unseen. Compared against
        a turn where the same attack lands on a Pokemon that survives it."""
        fast = _target(moves=("Blizzard",), pp=(5,))     # 70% accuracy, 10% freeze secondary
        dies = _state(_mon("Magneton", hp=1, speed=20, slot=1),
                      [_mon("Smeargle", speed=70, slot=2)], target=fast)
        lives = _state(_mon("Magneton", hp=700, speed=20, slot=1, max_hp=700),
                       [_mon("Smeargle", speed=70, slot=2)], target=fast)
        # Same seed, same attack, same rolls spent by the ATTACKER. What differs is only what
        # the faint removes from our side of the turn: the between-turn advances, and one
        # end-of-turn advance.
        self.assertEqual(
            self._offset(lives, Action.FAINTED) - self._offset(dies, Action.FAINTED,
                                                               replacement=2),
            turn_costs.BETWEEN_TURN_ADVANCES
            + turn_costs.END_OF_TURN_ADVANCES
            - turn_costs.END_OF_TURN_ADVANCES_FAINTED_BEFORE_MOVING)

    def test_our_move_costs_nothing_when_we_never_got_it_off(self):
        """No accuracy roll, no crit or damage roll, no PP, and no token. Which is why the
        report need not say which move we had selected."""
        bench = [_mon("Smeargle", speed=70, slot=2)]
        ours = _mon("Magneton", hp=1, speed=20, slot=1, moves=("Tackle",), pp=(35,))
        state = _state(ours, bench)
        nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=2)
        self.assertNotIn("M", _rendered(nxt))
        self.assertEqual([b for b in nxt.bench if b.name == "Magneton"][0].pp, (35,))


class TestASecondaryIsHiddenByAKo(unittest.TestCase):
    """Verified: a move that faints us still rolls its secondary, but the outcome is never shown.
    The roll is spent; the `~` must not be emitted, or the candidate set gets filtered on
    something the player never saw."""

    def _sweep(self, our_hp, n=3000):
        # Blizzard: 10% freeze. Swept, because whether the secondary procs comes from the RNG.
        target = _target(moves=("Blizzard",), pp=(5,))
        out = []
        for seed in range(0x4A1B2C3D, 0x4A1B2C3D + n):
            state = _state(_mon("Magneton", hp=our_hp, speed=20, slot=1,
                                max_hp=max(our_hp, 100)),  # 700 is the Gen 4 HP ceiling
                           [_mon("Smeargle", speed=70, slot=2)], rng=seed, target=target)
            nxt = simulate_turn(state, Action.FAINTED, HUNT, replacement=2)
            out.append(_rendered(nxt))
        return out

    def test_a_ko_turn_never_carries_the_marker(self):
        for rendered in self._sweep(our_hp=1):
            if "X2" in rendered:
                self.assertNotIn("~", rendered, rendered)

    def test_a_survivable_hit_still_does(self):
        """So the suppression is about the KO and not about the move."""
        self.assertTrue(any("~" in r for r in self._sweep(our_hp=700)),
                        "the sweep never procced the secondary at all")


class TestReviving(unittest.TestCase):
    """A Revive is the one bag item used on somebody who is NOT out, which is why it carries a
    party slot and is its own action rather than an entry in the item table."""

    def test_it_restores_half_of_max_hp_rounded_down(self):
        self.assertEqual(items.revive_amount(100), 50)
        self.assertEqual(items.revive_amount(101), 50)
        self.assertEqual(items.revive_amount(153), 76)

    def test_it_never_restores_zero(self):
        self.assertEqual(items.revive_amount(1), 1)

    def test_it_is_not_in_the_item_table(self):
        """The solver prices everything in there as a filler action for the ACTIVE Pokemon."""
        self.assertNotIn("rev", {i.code for i in items.ITEMS})

    def test_using_one_renders_the_party_slot_and_heals_the_bench(self):
        """Against a harmless target, so the Revive is the only thing the turn does -- a Hydro
        Pump would faint the active Pokemon and swap the bench around underneath the assertion.
        """
        state = _state(_mon("Magneton", hp=60, speed=300, slot=1),
                       [_mon("Mamoswine", hp=0, speed=80, slot=2, max_hp=120)],
                       target=_target(moves=("Mist",), pp=(30,)))
        nxt = simulate_turn(state, Action.REVIVE, HUNT, bench_slot=0)
        self.assertTrue(_rendered(nxt).startswith("R2"))
        self.assertEqual([(b.name, b.hp) for b in nxt.bench], [("Mamoswine", 60)])

    def test_it_costs_no_advances(self):
        bench = [_mon("Mamoswine", hp=0, speed=80, slot=2)]
        ours = _mon("Magneton", hp=700, speed=300, slot=1, max_hp=700)
        revived = simulate_turn(_state(ours, bench), Action.REVIVE, HUNT, bench_slot=0)
        itemed = simulate_turn(_state(ours, bench), Action.ITEM, HUNT, item_code="p")
        self.assertEqual(revived.rng_offset, itemed.rng_offset)

    def test_reviving_someone_who_has_not_fainted_is_a_caller_bug(self):
        """Silently healing a healthy Pokemon would make the predicted HP diverge from the real
        one and contradict every candidate on the next report."""
        state = _state(_mon("Magneton", hp=60, speed=300, slot=1),
                       [_mon("Mamoswine", hp=50, speed=80, slot=2)])
        with self.assertRaises(ValueError):
            simulate_turn(state, Action.REVIVE, HUNT, bench_slot=0)

    def test_it_needs_a_target(self):
        state = _state(_mon("Magneton", hp=60, speed=300, slot=1),
                       [_mon("Mamoswine", hp=0, speed=80, slot=2)])
        with self.assertRaises(ValueError):
            simulate_turn(state, Action.REVIVE, HUNT)


class TestPartySlotsAreStable(unittest.TestCase):
    """HGSS never reorders a party, so neither may the token stream. Switching out and back used
    to emit the same number twice, because the outgoing Pokemon was appended to the END of the
    bench and every index after it described somebody else."""

    def _party(self):
        return (_mon("Magneton", speed=300, slot=1, moves=("Thunder Wave",), pp=(20,)),
                (_mon("Mamoswine", speed=80, slot=2, moves=("Thunder Wave",), pp=(20,)),
                 _mon("Smeargle", speed=70, slot=3, moves=("Thunder Wave",), pp=(20,))))

    def test_switching_out_and_back_reads_s3_then_s1(self):
        ours, bench = self._party()
        state = _state(ours, bench, target=_target(moves=("Mist",), pp=(30,)))
        out = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=1)
        self.assertTrue(_rendered(out).startswith("S3"))
        self.assertEqual(out.ours.name, "Smeargle")
        # Magneton is back in slot 1 of the bench, where the party says it belongs.
        back = simulate_turn(out, Action.SWITCH, HUNT,
                             bench_slot=[b.name for b in out.bench].index("Magneton"))
        self.assertTrue(_rendered(back).startswith("S1"))
        self.assertEqual(back.ours.name, "Magneton")

    def test_the_bench_stays_in_party_order(self):
        ours, bench = self._party()
        state = _state(ours, bench, target=_target(moves=("Mist",), pp=(30,)))
        out = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=1)
        self.assertEqual([b.party_slot for b in out.bench], [1, 2])
        self.assertEqual([b.name for b in out.bench], ["Magneton", "Mamoswine"])

    def test_party_order_is_stable_when_no_slots_are_assigned(self):
        """Which is what keeps a directly-constructed fixture behaving as it always did."""
        unslotted = (_mon("A"), _mon("B"), _mon("C"))
        self.assertEqual([b.name for b in party_order(unslotted)], ["A", "B", "C"])

    def test_the_positional_guess_is_only_a_fallback(self):
        self.assertEqual(party_number(_mon("X", slot=4), 0), 4)
        self.assertEqual(party_number(_mon("X", slot=0), 0), 2,
                         "no party built: the active Pokemon was slot 1, so bench 0 is slot 2")


if __name__ == "__main__":
    unittest.main()


class TestTheSessionReportsAFaint(unittest.TestCase):
    """End to end through `HuntSession`, which is the layer the app drives."""

    def _session(self):
        from claytonlib.battle_compass.hunt_session import HuntSession

        ours = _mon("Magneton", hp=1, speed=20, moves=("Thunder Wave",), pp=(20,))
        bench = (_mon("Mamoswine", speed=80, moves=("Thunder Wave",), pp=(20,)),
                 _mon("Smeargle", hp=0, speed=70, moves=("Thunder Wave",), pp=(20,)))
        return HuntSession(_window(8), ours, _target(), HUNT, bench=bench)

    def _faint_turn(self, session):
        """A surviving candidate whose Hydro Pump actually connects, with its prediction.

        Picked rather than assumed: the attack can miss, and a seed where it does predicts a
        turn with no faint in it at all -- which is the correct prediction, and useless here.
        """
        from claytonlib.battle_compass.state import Action as A
        predicted = session.predict(A.FAINTED, replacement=2)
        for seed in session.survivors:
            if "X" in predicted[seed]:
                return seed, predicted[seed]
        self.fail("no candidate in the window had the attack connect")

    def test_party_slots_are_assigned_from_the_party_order(self):
        snap = self._session().snapshot()
        self.assertEqual(snap["ours_party_slot"], 1)
        self.assertEqual([(b["name"], b["party_slot"]) for b in snap["bench"]],
                         [("Mamoswine", 2), ("Smeargle", 3)])

    def test_a_fainted_bench_member_is_flagged_and_offers_a_revive(self):
        snap = self._session().snapshot()
        self.assertEqual([b["fainted"] for b in snap["bench"]], [False, True])
        self.assertIn("R", snap["legal_actions"])

    def test_fainted_before_moving_is_offered_only_when_the_target_can_lead(self):
        slow = self._session()
        self.assertIn("X", slow.snapshot()["legal_actions"])
        self.assertTrue(slow.snapshot()["target_can_move_first"])

    def test_it_is_withheld_when_we_always_move_first(self):
        """Offering it then invites a report no candidate can predict, which reads exactly like
        a wrong model constant."""
        from claytonlib.battle_compass.hunt_session import HuntSession

        fast = _mon("Magneton", speed=400, moves=("Thunder Wave",), pp=(20,))
        session = HuntSession(_window(1), fast, _target(moves=("Mist",), pp=(30,)), HUNT)
        self.assertNotIn("X", session.snapshot()["legal_actions"])
        self.assertFalse(session.snapshot()["target_can_move_first"])

    def test_reporting_the_faint_narrows_and_keeps_the_run_going(self):
        from claytonlib.battle_compass.state import Action as A
        session = self._session()
        _, rendered = self._faint_turn(session)
        snap = session.observe(A.FAINTED, [rendered], replacement=2)
        self.assertIsNone(snap["contradiction"])
        self.assertFalse(snap["over"])
        self.assertFalse(snap["party_wiped"])
        self.assertEqual(snap["ours"]["name"], "Mamoswine")
        # Magneton is back on the bench, still in party slot 1, still down.
        self.assertIn(("Magneton", 1, True),
                      [(b["name"], b["party_slot"], b["fainted"]) for b in snap["bench"]])

    def test_undo_puts_the_fainted_pokemon_back_out(self):
        """Undo is replay, so the replacement has to be part of what gets replayed."""
        from claytonlib.battle_compass.state import Action as A
        session = self._session()
        _, rendered = self._faint_turn(session)
        session.observe(A.FAINTED, [rendered], replacement=2)
        snap = session.undo()
        self.assertEqual(snap["ours"]["name"], "Magneton")
        self.assertEqual(snap["ours"]["hp"], 1)

    def test_a_revive_is_counted_in_what_the_run_spent(self):
        from claytonlib.battle_compass.state import Action as A
        session = self._session()
        truth = session.survivors[0]
        predicted = session.predict(A.REVIVE, bench_slot=1)[truth]
        session.observe(A.REVIVE, [predicted], bench_slot=1)
        self.assertEqual(session.items_spent().get("rev"), 1)

    def test_neither_new_action_is_offered_as_advice(self):
        """A Revive needs a target the ranker does not have, and being fainted before moving is
        not a choice -- ranking either would offer advice nobody can act on."""
        codes = {row["action"] for row in self._session().advice()}
        self.assertNotIn("R", codes)
        self.assertNotIn("X", codes)

    def test_a_faint_reads_as_plain_language(self):
        from claytonlib.battle_compass.state import Action as A
        session = self._session()
        _, rendered = self._faint_turn(session)
        session.observe(A.FAINTED, [rendered], replacement=2)
        sentences = " ".join(session.snapshot()["turns"][0]["explain"])
        self.assertIn("fainted", sentences)
        self.assertIn("Mamoswine", sentences, "the replacement should be named, not numbered")


class TestTheSolverStillRefusesToSpendAPokemon(unittest.TestCase):
    """Sec 6.2's hard constraint. It was keyed on `ours.fainted`, which a replacement switch-in
    clears before the turn returns -- so the check stopped firing the moment fainting became
    survivable, and the solver would have planned straight through a faint."""

    def _doomed(self):
        """A state where our Pokemon cannot survive the turn, whatever we do.

        Aerial Ace rather than Hydro Pump, because it has accuracy 0 -- it bypasses the check
        entirely, so EVERY seed in the search connects and there is no lucky branch for the
        solver to escape down. The target is at 1 HP and paralyzed, which is the solver's
        precondition.
        """
        from claytonlib.battle_compass.state import Status
        ours = _mon("Magneton", hp=1, speed=20, slot=1, moves=("Mean Look",), pp=(5,))
        target = _target(moves=("Aerial Ace",), pp=(20,), status=Status.PARALYSIS)
        return _state(ours, [_mon("Mamoswine", speed=80, slot=2)], target=target)

    def test_the_fixture_really_does_faint_us(self):
        """Otherwise the test below passes for the wrong reason."""
        state = self._doomed()
        self.assertEqual(simulate_turn(state, Action.MOVE_1, HUNT).faints, 1)

    def test_no_step_of_a_solution_ever_faints_us(self):
        from claytonlib.battle_compass.solver import Solution, SolverConfig, solve

        state = self._doomed()
        answer = solve(state, HUNT, SolverConfig(max_turns=6))
        if not isinstance(answer, Solution):
            return      # no path at all is the right answer here, and the honest one
        # A ball resolves before any move, so a capture on the very first throw is a legitimate
        # escape -- what must never appear is a step that trades a Pokemon for RNG position.
        walk = state
        for step in answer.steps:
            walk = simulate_turn(walk, step.action, HUNT, item_code=step.item)
            self.assertEqual(walk.faints, 0, f"the plan spends a Pokemon at {step.rendered}")

    def test_the_prune_is_keyed_on_the_faint_count(self):
        """Directly, because the integration test above depends on the fixture reaching a
        capture at all."""
        import inspect

        from claytonlib.battle_compass import solver

        source = inspect.getsource(solver.solve)
        self.assertIn("nxt.faints > current.faints", source)
        self.assertNotIn("if nxt.ours.fainted:", source)
