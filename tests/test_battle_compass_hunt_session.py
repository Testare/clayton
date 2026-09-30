"""The layer the app drives: candidates + solver joined into one surface."""
import datetime as dt
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
from claytonlib.battle_compass import items
from claytonlib.battle_compass.hunt_session import (
    CANDIDATE_PREVIEW, HuntSession, TurnLog, move_info, prevention_options,
    resolution_options, worst_incoming_hit,
)
from claytonlib.battle_compass.identify import Phase
from claytonlib.battle_compass.sim import (
    HuntConfig, accuracy_net_stage, can_miss, effective_speed, will_fail,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.targets import moveset
from claytonlib.moves import resolve_move

SEED = 0xEC1504DC
HUNT = HuntConfig(target_catch_rate=3)


def _ours(**kw):
    stats = {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160}
    fields = dict(name="Smeargle", level=58, types=("Normal",), stats=stats,
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


def _bench(**kw):
    fields = dict(name="Magneton", level=30, types=("Electric", "Steel"),
                  stats={"hp": 85, "atk": 50, "def": 70, "spa": 90, "spd": 60, "spe": 60},
                  moves=("Thunder Wave", "Tackle"), pp=(20, 35))
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
        """56, a maximum-roll critical Aurora Beam. Was 58 when the damage range was applied
        after STAB rather than before it, and with Smeargle's stats assumed rather than entered."""
        self.assertEqual(worst_incoming_hit(_ours(), _target()), 56)

    def test_the_session_adopts_it_as_the_solver_floor(self):
        s = _session()
        self.assertEqual(s.danger_floor, 56)
        self.assertEqual(s.solver_config.danger_floor, 56)

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
        self.assertEqual(_session(n=1).snapshot(include_advice=True)["advice"], [])

    def test_advice_ranks_actions_while_several_remain(self):
        advice = _session().snapshot(include_advice=True)["advice"]
        self.assertTrue(advice)
        self.assertEqual(advice, sorted(advice, key=lambda a: a["expected_survivors"]))

    def test_ambiguity_travels_with_the_snapshot(self):
        self.assertIn("second_only", _session().snapshot()["ambiguity"])


class TestSecondOnlyAmbiguityIsSurfaced(unittest.TestCase):
    """A set differing only in the RTC second separates slowly -- median 19 turns -- so the UI
    has to say that, not that it is hopeless (sec 17.1, corrected)."""

    def test_a_second_only_set_is_flagged(self):
        cands = tuple(Candidate(seed=SEED + (k << 24), frame=1000, second=30 + k)
                      for k in range(3))
        window = replace(_window(), candidates=cands)
        s = HuntSession(window, _ours(), _target(), HUNT)
        amb = s.snapshot()["ambiguity"]
        self.assertTrue(amb["second_only"])
        self.assertTrue(amb["separable_by_moves"])
        self.assertIn("narrower second window", amb["advice"])
        self.assertIn("not impossible", amb["advice"])

    def test_such_a_set_narrows_rather_than_never(self):
        """The old assertion was that no number of turns would do it.

        Played from a Phase 2 position with an unkillable lead. Both conditions are deliberate:
        Phase 2 is the state the claim was ever about, and 65 unhealed turns of Aurora Beam kill
        a real Smeargle in about ten -- which is a fact about survival, not about whether the RNG
        diverges. The mechanism itself is tested directly in
        tests/test_battle_compass_identify.py.
        """
        cands = tuple(Candidate(seed=SEED + (k << 24), frame=1000, second=30 + k)
                      for k in range(3))
        # 999 is the most an HP token can render (three digits), and huge defences floor each
        # incoming hit at 1, so the lead survives the horizon without any healing turns muddying
        # what is being measured.
        tanky = _ours(stats={**_ours().stats, "hp": 999, "def": 999, "spd": 999})
        session = HuntSession(replace(_window(), candidates=cands), tanky,
                              _target(hp=1, status=Status.PARALYSIS), HUNT)
        truth = session.survivors[0]
        for _ in range(5):
            session.observe(Action.MOVE_1, [session.predict(Action.MOVE_1)[truth]])
        after_five = len(session.survivors)
        for _ in range(60):
            if session.identified:
                break
            session.observe(Action.MOVE_1, [session.predict(Action.MOVE_1)[truth]])
        self.assertEqual(after_five, 3, "five turns should not have been enough")
        self.assertIsNotNone(session.identified, "they should separate within 65 turns")


class TestTheInterviewCanExpressEveryTurn(unittest.TestCase):
    """The page assembles tokens from answers rather than taking a typed string, so its question
    vocabulary has to cover everything the simulator can predict. A gap here is not cosmetic: a
    turn the player cannot report is a run that cannot continue.

    Found exactly that on the first run of this test -- 96 of 456 renderings carried the `~`
    secondary-effect marker (Aurora Beam's Attack drop) and there was no question for it.
    """

    #: The token shapes the interview's chips can produce, per app/web/index.html's hrTokens().
    #: Item codes are enumerated rather than [a-z]+ so a code the page cannot offer fails here.
    OURS = (r"(?:M[1-4][h!\-]?~?|M(?:par|slp|frz|cfz|fln)|Mscfz[1-4][h!\-]?~?"
            r"|I(?:" + "|".join(i.code for i in items.ITEMS) + r")"
            r"|S[1-6]|C[0-3]?|Pc?[0-3]?)")
    TARGET = r"(?:E[1-4][h!\-]?~?|E(?:par|slp|frz|fln))"
    TURN = None  # built in setUpClass

    @classmethod
    def setUpClass(cls):
        import re
        cls.TURN = re.compile(rf"^{cls.OURS}(?:{cls.TARGET})?(?:HP\d{{3}})?$")

    def _renderings(self):
        """Every turn shape reachable from the fixture, switches and items included."""
        import random
        from claytonlib.battle_compass import tokens as tk
        from claytonlib.battle_compass.sim import simulate_turn
        rng = random.Random(9)
        codes = [i.code for i in items.ITEMS]
        seen = set()
        for _ in range(200):
            for extra in ({}, {"hp": 1, "status": Status.PARALYSIS}):
                for our_hp in (None, 90, 40):
                    base = next(iter(_session(n=1, **extra)._session.states.values()))
                    base = replace(base, rng=rng.getrandbits(32),
                                   ours=base.ours.with_hp(our_hp or base.ours.max_hp),
                                   bench=(_bench(),))
                    for action in Action:
                        kwargs = {}
                        if action is Action.SWITCH:
                            kwargs["bench_slot"] = 0
                        if action in (Action.ITEM, Action.ITEM_CURE):
                            kwargs["item_code"] = rng.choice(codes)
                        try:
                            nxt = simulate_turn(base, action, HUNT, **kwargs)
                        except Exception:
                            continue
                        seen.add(tk.render_turn(tk.normalise(nxt.log[-1])))
        return seen

    def test_the_sample_is_broad_enough_to_mean_something(self):
        self.assertGreater(len(self._renderings()), 600)

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


class TestSwitchingActuallySwitches(unittest.TestCase):
    """SWITCH used to fall into the bag-action branch, emit an ITEM token, and swap nobody -- so
    the run kept simulating the Pokemon that had left, and asked for its HP at end of turn."""

    def _session_with_bench(self):
        return HuntSession(_window(8), _ours(), _target(), HUNT, bench=(_bench(),))

    def test_it_emits_a_switch_token_not_an_item_one(self):
        session = self._session_with_bench()
        rendered = session.predict(Action.SWITCH, bench_slot=0)[session.survivors[0]]
        self.assertTrue(rendered.startswith("S2"), rendered)
        self.assertNotIn("I", rendered.split("E")[0])

    def test_the_party_slot_counts_the_active_pokemon(self):
        """Bench slot 0 is party slot 2, because the active one is slot 1."""
        session = self._session_with_bench()
        self.assertTrue(
            session.predict(Action.SWITCH, bench_slot=0)[session.survivors[0]].startswith("S2"))

    def test_the_incoming_pokemon_becomes_active(self):
        session = self._session_with_bench()
        truth = session.survivors[0]
        rendered = session.predict(Action.SWITCH, bench_slot=0)[truth]
        snap = session.observe(Action.SWITCH, [rendered], bench_slot=0)
        self.assertEqual(snap["ours"]["name"], "Magneton")
        self.assertEqual(snap["ours"]["max_hp"], 85)

    def test_the_outgoing_pokemon_goes_to_the_bench(self):
        session = self._session_with_bench()
        truth = session.survivors[0]
        rendered = session.predict(Action.SWITCH, bench_slot=0)[truth]
        snap = session.observe(Action.SWITCH, [rendered], bench_slot=0)
        self.assertEqual([b["name"] for b in snap["bench"]], ["Smeargle"])

    def test_the_hp_reported_belongs_to_the_incoming_pokemon(self):
        """The bug behind 'it asks for Magneton's HP when I switched to Smeargle'."""
        session = self._session_with_bench()
        truth = session.survivors[0]
        rendered = session.predict(Action.SWITCH, bench_slot=0)[truth]
        hp = [t for t in tok.tokenise(rendered) if t.startswith("HP")]
        if hp:
            self.assertLessEqual(int(hp[0][2:]), 85, "HP exceeds the incoming Pokemon's maximum")

    def test_a_switch_without_a_target_is_refused(self):
        session = self._session_with_bench()
        with self.assertRaises(ValueError) as caught:
            session.predict(Action.SWITCH)
        self.assertIn("which party member came in", str(caught.exception))

    def test_switch_is_not_offered_with_an_empty_bench(self):
        self.assertNotIn(Action.SWITCH, _session().legal_actions())

    def test_switch_is_offered_when_there_is_a_bench(self):
        self.assertIn(Action.SWITCH, self._session_with_bench().legal_actions())

    def test_the_bench_survives_undo(self):
        session = self._session_with_bench()
        truth = session.survivors[0]
        rendered = session.predict(Action.SWITCH, bench_slot=0)[truth]
        session.observe(Action.SWITCH, [rendered], bench_slot=0)
        snap = session.undo()
        self.assertEqual(snap["ours"]["name"], "Smeargle")
        self.assertEqual([b["name"] for b in snap["bench"]], ["Magneton"])

    def test_ranking_can_score_a_switch_without_being_told_who(self):
        """Information gain cannot depend on it -- a switch costs zero RNG advances -- so the
        ranking defaults it rather than refusing."""
        session = self._session_with_bench()
        ranked = dict(session._session.rank_actions(session.legal_actions()))
        self.assertIn(Action.SWITCH, ranked)


class TestItemsActuallyApply(unittest.TestCase):
    """The simulator appended an item token and healed nothing, so after a potion its predicted
    HP diverged from the real one and the next report contradicted every candidate."""

    def test_a_potion_heals_and_the_token_names_it(self):
        session = _session()
        state = next(iter(session._session.states.values()))
        session._session.states = {s: replace(st, ours=st.ours.with_hp(100))
                                   for s, st in session._session.states.items()}
        rendered = session.predict(Action.ITEM, item_code="sp")[session.survivors[0]]
        self.assertTrue(rendered.startswith("Isp"), rendered)

    def test_healing_is_capped_at_the_missing_amount(self):
        from claytonlib.battle_compass.items import heal_amount
        self.assertEqual(heal_amount("hp", 140, 170), 30)
        self.assertEqual(heal_amount("mp", 10, 170), 160)
        self.assertEqual(heal_amount("p", 170, 170), 0)

    def test_a_full_heal_clears_status_without_healing(self):
        from claytonlib.battle_compass.items import item
        self.assertTrue(item("fh").cures_status)
        self.assertFalse(item("fh").heals)

    def test_the_solvers_prices_come_from_the_same_table(self):
        """Three consumers used to disagree about what an item was."""
        from claytonlib.battle_compass.items import PRICES
        from claytonlib.battle_compass.solver import ITEM_PRICES
        self.assertEqual(PRICES, ITEM_PRICES)

    def test_the_snapshot_offers_the_items_so_the_page_can_ask(self):
        offered = _session().snapshot()["items"]
        self.assertEqual({i["code"] for i in offered}, set(items.PRICES))
        for entry in offered:
            self.assertTrue(entry["name"])


class TestTokenOrderIsChronological(unittest.TestCase):
    """The grammar's only ordering rule is that tokens appear in the order events occurred
    (sec 13.4). A Lv30 Magneton at Speed 60 does NOT outrun an unparalyzed Suicune at 85, so
    that turn opens with E, not M -- and an interview that always emitted M first produced
    "M1E1" for a turn no candidate could have predicted."""

    def _pair(self, our_speed, target_status=Status.NONE):
        ours = _ours(name="Us", level=30, types=("Electric", "Steel"),
                     stats={"hp": 85, "atk": 50, "def": 70, "spa": 90, "spd": 60,
                            "spe": our_speed},
                     moves=("Thunder Wave", "Tackle"), pp=(20, 35))
        return ours, _target(status=target_status)

    def _first_actor(self, ours, target, seed=SEED):
        from claytonlib.battle_compass.sim import simulate_turn
        state = BattleState(ours=ours, target=target, rng=seed, phase=1)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        parts = [t for t in tok.tokenise(tok.render_turn(tok.normalise(nxt.log[-1])))
                 if not t.startswith("HP")]
        return parts[0][0] if parts else ""

    def test_a_slower_pokemon_acts_second(self):
        ours, target = self._pair(60)
        self.assertLess(effective_speed(ours), effective_speed(target))
        self.assertEqual(self._first_actor(ours, target), "E")

    def test_a_faster_pokemon_acts_first(self):
        ours, target = self._pair(200)
        self.assertEqual(self._first_actor(ours, target), "M")

    def test_paralysis_can_flip_the_order(self):
        """Quartering 85 to 21 is what lets a Speed-60 Magneton move first."""
        ours, target = self._pair(60, Status.PARALYSIS)
        self.assertEqual(effective_speed(target), 21)
        self.assertEqual(self._first_actor(ours, target), "M")

    def test_the_snapshot_publishes_the_order_and_both_speeds(self):
        """The page cannot derive it -- the rule and the numbers live here."""
        session = HuntSession(_window(4), *self._pair(60), config=HUNT)
        snap = session.snapshot()
        self.assertFalse(snap["we_move_first"])
        self.assertEqual(snap["ours"]["effective_speed"], 60)
        self.assertEqual(snap["target"]["effective_speed"], 85)

    def test_a_bag_action_always_resolves_before_any_move(self):
        """Whatever the Speeds, so the order only matters when we use a move (sec 12.1)."""
        ours, target = self._pair(60)
        state = BattleState(ours=ours, target=target, rng=SEED, phase=1)
        from claytonlib.battle_compass.sim import simulate_turn
        for action, kwargs in ((Action.ITEM, {"item_code": "p"}),
                               (Action.CAPTURE_BALL, {})):
            nxt = simulate_turn(replace(state, phase=2), action, HUNT, **kwargs)
            rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
            self.assertFalse(rendered.startswith("E"), f"{action.name}: {rendered}")

    def test_the_order_holds_over_many_seeds(self):
        import random
        rng = random.Random(3)
        for our_speed, expected in ((60, "E"), (200, "M")):
            ours, target = self._pair(our_speed)
            for _ in range(60):
                self.assertEqual(self._first_actor(ours, target, rng.getrandbits(32)), expected)


class TestOnlyPossibleOutcomesAreOffered(unittest.TestCase):
    """Offering an impossible outcome invites a report no candidate could ever have predicted,
    which is indistinguishable from a wrong model constant -- the one diagnosis that matters."""

    def test_an_unparalyzed_pokemon_cannot_be_fully_paralyzed(self):
        options = prevention_options(_ours(), _target(), actor_moves_first=False)
        self.assertEqual([o["code"] for o in options], [])

    def test_a_paralyzed_pokemon_can_be(self):
        options = prevention_options(_ours(status=Status.PARALYSIS), _target(),
                                     actor_moves_first=False)
        self.assertEqual([o["code"] for o in options], ["par"])

    def test_sleep_and_freeze_are_offered_only_when_present(self):
        for status, code in ((Status.SLEEP, "slp"), (Status.FREEZE, "frz")):
            options = prevention_options(_ours(status=status), _target(), actor_moves_first=False)
            self.assertEqual([o["code"] for o in options], [code])

    def test_confusion_is_offered_only_while_confused(self):
        self.assertEqual(
            [o["code"] for o in prevention_options(_ours(confused=True), _target(),
                                                   actor_moves_first=False)], ["cfz"])
        self.assertEqual(
            [o["code"] for o in resolution_options(_ours(confused=True))], ["scfz"])
        self.assertEqual(resolution_options(_ours()), [])

    def test_flinch_needs_the_other_side_to_have_a_flinching_move(self):
        """Nothing in Suicune's moveset flinches, so it must never be offered against it."""
        from claytonlib.battle_compass.sim import can_flinch
        self.assertFalse(can_flinch(_target()))
        options = prevention_options(_ours(status=Status.PARALYSIS), _target(),
                                     actor_moves_first=False)
        self.assertNotIn("fln", [o["code"] for o in options])

    def test_flinch_needs_the_other_side_to_move_first(self):
        flincher = _target(moves=("Headbutt",), pp=(15,))
        from claytonlib.battle_compass.sim import can_flinch
        self.assertTrue(can_flinch(flincher))
        second = prevention_options(_ours(), flincher, actor_moves_first=False)
        first = prevention_options(_ours(), flincher, actor_moves_first=True)
        self.assertIn("fln", [o["code"] for o in second])
        self.assertNotIn("fln", [o["code"] for o in first])

    def test_the_snapshot_carries_them_for_both_sides(self):
        snap = _session(status=Status.PARALYSIS).snapshot()
        self.assertEqual([o["code"] for o in snap["prevention"]["ours"]], [])
        self.assertEqual([o["code"] for o in snap["prevention"]["target"]], ["par"])


class TestAdviceIsSeparateFromTheSnapshot(unittest.TestCase):
    """Ranking simulates every candidate against every action -- seconds at a few thousand
    candidates, and the only slow part of a snapshot. A turn must never wait on it."""

    def test_a_snapshot_omits_advice_by_default(self):
        snap = _session().snapshot()
        self.assertIsNone(snap["advice"])
        self.assertTrue(snap["advice_pending"])

    def test_it_can_still_be_asked_for_inline(self):
        snap = _session().snapshot(include_advice=True)
        self.assertTrue(snap["advice"])
        self.assertFalse(snap["advice_pending"])

    def test_nothing_is_pending_once_the_seed_is_pinned(self):
        """There is nothing left to learn, so there is nothing to load."""
        snap = _session(n=1).snapshot()
        self.assertFalse(snap["advice_pending"])

    def test_omitting_advice_is_much_cheaper(self):
        import time
        session = _session(n=200)
        start = time.time()
        session.snapshot()
        without = time.time() - start
        start = time.time()
        session.snapshot(include_advice=True)
        with_advice = time.time() - start
        self.assertLess(without * 5, with_advice,
                        "advice is supposed to dominate the cost of a snapshot")


class TestSwitchHpToken(unittest.TestCase):
    """An HP token reports a CHANGE to one Pokemon. The baseline was captured before the switch,
    so it compared the OUTGOING Pokemon's HP with the INCOMING one's and emitted a token for a
    turn where nothing was damaged -- Magneton 85 against Smeargle 153 reads as a 68-point
    change."""

    def _switch(self, seed, target_status=Status.PARALYSIS, our_hp=None):
        from claytonlib.battle_compass.sim import simulate_turn
        incoming = _ours(hp=our_hp)
        outgoing = _bench()
        state = BattleState(ours=outgoing, target=_target(status=target_status),
                            rng=seed, bench=(incoming,), phase=1)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        return tok.render_turn(tok.normalise(nxt.log[-1])), nxt

    def test_a_switch_where_nothing_hits_us_reports_no_hp(self):
        """The reported glitch: switched in, target fully paralyzed, HP153 emitted anyway."""
        found = False
        for seed in range(0xEC1504DC, 0xEC1504DC + 400):
            rendered, _ = self._switch(seed)
            if "Epar" not in rendered:
                continue
            found = True
            self.assertNotIn("HP", rendered, rendered)
        self.assertTrue(found, "no fully-paralyzed switch turn in the sample")

    def test_the_hp_baseline_follows_the_incoming_pokemon(self):
        """So a token, when one IS emitted, is the incoming Pokemon's HP and not a difference
        between two different Pokemon."""
        for seed in range(0xEC1504DC, 0xEC1504DC + 200):
            rendered, nxt = self._switch(seed)
            hp = [t for t in tok.tokenise(rendered) if t.startswith("HP")]
            if hp:
                self.assertEqual(int(hp[0][2:]), nxt.ours.hp)
                self.assertLessEqual(int(hp[0][2:]), nxt.ours.max_hp)

    def test_a_switch_that_does_take_damage_still_reports_hp(self):
        """The fix must not suppress a real change."""
        reported = 0
        for seed in range(0xEC1504DC, 0xEC1504DC + 400):
            rendered, nxt = self._switch(seed, target_status=Status.NONE)
            if nxt.ours.hp < nxt.ours.max_hp:
                self.assertIn("HP", rendered, rendered)
                reported += 1
        self.assertGreater(reported, 10, "no damaging switch turn in the sample")

    def test_the_grammar_agrees_that_no_hp_is_needed(self):
        """turn_requires_hp and the simulator must not disagree, or a valid turn would be
        rejected as ungrammatical."""
        for seed in range(0xEC1504DC, 0xEC1504DC + 300):
            rendered, _ = self._switch(seed)
            self.assertEqual(tok.validate_turn(tok.tokenise(rendered)), [], rendered)

    def test_switching_to_a_damaged_pokemon_keeps_its_own_hp(self):
        """Its HP on the bench is the baseline, not its maximum."""
        rendered, nxt = self._switch(0xEC1504DC, our_hp=100)
        self.assertLessEqual(nxt.ours.hp, 100)


class TestARejectedTurnIsRecoverable(unittest.TestCase):
    """A contradiction leaves the candidate set untouched, so the run must be able to continue --
    the likeliest cause is one mistyped answer, not a genuinely excluded set (sec 15.5)."""

    def test_the_set_is_unchanged_and_the_turn_is_not_recorded(self):
        session = _session()
        before = session.survivors
        session.observe(Action.MOVE_1, ["M1hE3hHP999"])
        self.assertEqual(session.survivors, before)
        self.assertEqual(session.turns, [])

    def test_a_good_turn_straight_after_a_rejection_is_accepted(self):
        """Nothing about a rejection may leave the session unable to accept the next report."""
        session = _session()
        session.observe(Action.MOVE_1, ["M1hE3hHP999"])
        truth = session.survivors[0]
        snap = session.observe(Action.MOVE_1, [session.predict(Action.MOVE_1)[truth]])
        self.assertIsNone(snap["contradiction"])
        self.assertEqual(len(snap["turns"]), 1)

    def test_repeated_rejections_do_not_degrade_the_session(self):
        session = _session()
        before = session.survivors
        for _ in range(5):
            session.observe(Action.MOVE_1, ["M1hE3hHP999"])
        self.assertEqual(session.survivors, before)
        truth = session.survivors[0]
        self.assertIsNone(
            session.observe(Action.MOVE_1,
                            [session.predict(Action.MOVE_1)[truth]])["contradiction"])


class TestHpIsARangeNotAGuess(unittest.TestCase):
    """The snapshot used to publish whichever candidate came first out of the dict, presenting one
    prediction as fact. Candidates genuinely disagree: they predict different damage rolls and
    different critical hits, so after one False Swipe 61 candidates can hold six different HPs."""

    def _advanced(self, n=40):
        """Every candidate moved one turn WITHOUT filtering -- what the bar has to depict."""
        from claytonlib.battle_compass.sim import simulate_turn
        session = _session(n=n)
        session._session.states = {
            seed: simulate_turn(state, Action.MOVE_1, session.config)
            for seed, state in session._session.states.items()}
        return session

    def test_a_fresh_session_is_certain(self):
        rng = _session().hp_range("target")
        self.assertTrue(rng["certain"])
        self.assertEqual(rng["low"], rng["high"])

    def test_candidates_disagree_after_a_hit(self):
        rng = self._advanced().hp_range("target")
        self.assertFalse(rng["certain"])
        self.assertLess(rng["low"], rng["high"])

    def test_the_range_spans_every_candidate(self):
        session = self._advanced()
        hps = [st.target.hp for st in session._session.states.values()]
        rng = session.hp_range("target")
        self.assertEqual(rng["low"], min(hps))
        self.assertEqual(rng["high"], max(hps))

    def test_our_own_hp_is_a_range_too(self):
        rng = self._advanced().hp_range("ours")
        self.assertLessEqual(rng["low"], rng["high"])

    def test_both_sides_carry_it_on_the_snapshot(self):
        snap = self._advanced().snapshot()
        for side in ("ours", "target"):
            self.assertIn("hp_range", snap[side])
            self.assertIn("certain", snap[side]["hp_range"])

    def test_it_collapses_once_the_seed_is_pinned(self):
        self.assertTrue(_session(n=1).snapshot()["target"]["hp_range"]["certain"])

    def test_the_snapshot_publishes_ability_and_item(self):
        """So the bar can show what the damage figures were computed from."""
        session = HuntSession(_window(4), _ours(ability="Technician", held_item="Silk Scarf"),
                              _target(), HUNT)
        snap = session.snapshot()
        self.assertEqual(snap["ours"]["ability"], "Technician")
        self.assertEqual(snap["ours"]["held_item"], "Silk Scarf")


class TestAbilityAndItemReachTheSimulation(unittest.TestCase):
    def test_technician_and_silk_scarf_increase_the_damage_dealt(self):
        from claytonlib.battle_compass.sim import simulate_turn
        plain = _ours()
        buffed = _ours(ability="Technician", held_item="Silk Scarf")
        target = _target()
        weak = strong = None
        for seed in range(SEED, SEED + 60):
            a = simulate_turn(BattleState(ours=plain, target=target, rng=seed, phase=1),
                              Action.MOVE_1, HUNT)
            b = simulate_turn(BattleState(ours=buffed, target=target, rng=seed, phase=1),
                              Action.MOVE_1, HUNT)
            if a.target.hp < target.max_hp and b.target.hp < target.max_hp:
                weak = target.max_hp - a.target.hp
                strong = target.max_hp - b.target.hp
                break
        self.assertIsNotNone(weak, "no damaging turn in the sample")
        self.assertGreater(strong, weak)

    def test_the_danger_floor_sees_the_targets_ability_and_item(self):
        """It is computed from the TARGET as attacker, so its modifiers matter too."""
        bare = worst_incoming_hit(_ours(), _target())
        boosted = worst_incoming_hit(_ours(), _target(held_item="Mystic Water"))
        self.assertGreaterEqual(boosted, bare)


class TestPhaseTwoCanBeForced(unittest.TestCase):
    """The blockers are what the SIMULATION believes. It can be wrong in ways the player can see
    -- an unmodelled damage modifier leaves the simulated target above 1 HP when the real one is
    there -- so refusing outright would lock the run out exactly when the model is at fault."""

    def test_the_normal_path_still_refuses(self):
        session = _session()
        session.enter_pinning()
        with self.assertRaises(ValueError):
            session.enter_solving()

    def test_forcing_enters_phase_two_anyway(self):
        session = _session()
        session.enter_pinning()
        snap = session.enter_solving(force=True)
        self.assertEqual(snap["phase"], int(Phase.SOLVING))

    def test_forcing_past_an_unpinned_seed_explains_itself(self):
        """There is no single state to solve from, so say so rather than failing the transition."""
        session = _session()
        session.enter_pinning()
        snap = session.enter_solving(force=True)
        self.assertIsNone(snap["solution"])
        self.assertIn("pinned", snap["forced_reason"])

    def test_forcing_a_pinned_ready_target_actually_solves(self):
        session = _session(n=1, hp=1, status=Status.PARALYSIS)
        session.enter_pinning()
        snap = session.enter_solving(force=True)
        self.assertIsNone(snap["forced_reason"])
        self.assertIsNotNone(snap["solution"])

    def test_a_forced_transition_survives_undo(self):
        session = _session(n=1, hp=1, status=Status.PARALYSIS)
        session.enter_pinning()
        session.enter_solving(force=True)
        self.assertEqual(session.undo()["phase"], int(Phase.SOLVING))


class TestNoImpossibleMoveOutcomes(unittest.TestCase):
    """Spore against an already-paralyzed Suicune is certain to fail, and the simulator renders
    that as the BARE slot token. The interview offered "Missed / failed", the player picked it
    truthfully, and the resulting M4- matched no candidate.

    The same audit found accuracy 100 being treated as missable: `roll % 100 < 100` can never be
    false, so Spore, False Swipe and Sweet Scent cannot miss either."""

    def test_accuracy_one_hundred_cannot_miss(self):
        for name in ("Spore", "False Swipe", "Sweet Scent"):
            move = resolve_move(name)
            self.assertEqual(move.accuracy, 100, name)
            self.assertFalse(can_miss(move), name)

    def test_accuracy_zero_cannot_miss_either(self):
        """It bypasses the check entirely."""
        move = resolve_move("Mean Look")
        self.assertEqual(move.accuracy, 0)
        self.assertFalse(can_miss(move))

    def test_a_genuinely_missable_move_still_is(self):
        self.assertTrue(can_miss(resolve_move("Hypnosis")))   # 60 accuracy

    def test_an_accuracy_drop_makes_a_hundred_percent_move_missable(self):
        """can_miss is a property of the SITUATION, not the move. Reporting Spore as unmissable
        under an accuracy drop would suppress a legitimate "missed"."""
        spore = resolve_move("Spore")
        self.assertFalse(can_miss(spore, 0))
        self.assertTrue(can_miss(spore, -1))
        self.assertTrue(can_miss(spore, -6))

    def test_a_raised_evasion_does_the_same(self):
        self.assertTrue(can_miss(resolve_move("Spore"), -2))

    def test_a_raised_accuracy_keeps_it_unmissable(self):
        self.assertFalse(can_miss(resolve_move("Spore"), 3))

    def test_the_stage_is_the_net_of_accuracy_and_evasion(self):
        ours = _ours(accuracy_stage=-1)
        target = _target(evasion_stage=2)
        self.assertEqual(accuracy_net_stage(ours, target), -3)
        self.assertEqual(accuracy_net_stage(_ours(), _target()), 0)

    def test_the_net_stage_is_clamped(self):
        self.assertEqual(accuracy_net_stage(_ours(accuracy_stage=6),
                                            _target(evasion_stage=-6)), 6)
        self.assertEqual(accuracy_net_stage(_ours(accuracy_stage=-6),
                                            _target(evasion_stage=6)), -6)

    def test_move_info_computes_it_against_the_real_defender(self):
        neutral = {m["name"]: m for m in move_info(_ours(), _target())}
        evasive = {m["name"]: m for m in move_info(_ours(), _target(evasion_stage=2))}
        self.assertFalse(neutral["Spore"]["can_miss"])
        self.assertTrue(evasive["Spore"]["can_miss"])

    def test_the_simulator_uses_the_same_net_stage(self):
        """Or the interview would offer outcomes the simulator cannot produce, and vice versa."""
        from claytonlib.battle_compass.sim import simulate_turn
        target = _target(evasion_stage=6)
        missed = False
        for seed in range(SEED, SEED + 400):
            nxt = simulate_turn(BattleState(ours=_ours(), target=target, rng=seed, phase=1),
                                Action.MOVE_4, HUNT)
            if "-" in tok.render_turn(tok.normalise(nxt.log[-1])).split("E")[0]:
                missed = True
                break
        self.assertTrue(missed, "a heavily evasive target should sometimes dodge Spore")

    def test_a_status_move_fails_against_an_already_statused_target(self):
        spore = resolve_move("Spore")
        self.assertTrue(will_fail(spore, _target(status=Status.PARALYSIS)))
        self.assertTrue(will_fail(spore, _target(status=Status.SLEEP)))
        self.assertFalse(will_fail(spore, _target(status=Status.NONE)))

    def test_a_damaging_move_never_guaranteed_fails(self):
        self.assertFalse(will_fail(resolve_move("False Swipe"),
                                   _target(status=Status.PARALYSIS)))

    def test_move_info_reports_it_against_the_actual_defender(self):
        against_healthy = {m["name"]: m for m in move_info(_ours(), _target())}
        against_para = {m["name"]: m
                        for m in move_info(_ours(), _target(status=Status.PARALYSIS))}
        self.assertFalse(against_healthy["Spore"]["guaranteed_fail"])
        self.assertTrue(against_para["Spore"]["guaranteed_fail"])

    def test_the_simulator_renders_it_bare_and_never_as_a_miss(self):
        """The invariant the interview has to match."""
        from claytonlib.battle_compass.sim import simulate_turn
        target = _target(status=Status.PARALYSIS)
        for seed in range(SEED, SEED + 250):
            nxt = simulate_turn(BattleState(ours=_ours(), target=target, rng=seed, phase=1),
                                Action.MOVE_4, HUNT)
            ours = tok.render_turn(tok.normalise(nxt.log[-1])).split("E")[0]
            self.assertEqual(ours, "M4", ours)

    def test_the_offered_outcomes_match_what_the_simulator_emits(self):
        """Offer a superset and the player can report something impossible; offer a subset and a
        real turn becomes unreportable."""
        from claytonlib.battle_compass.sim import simulate_turn
        for status in (Status.NONE, Status.PARALYSIS):
            target = _target(status=status)
            info = {m["slot"]: m for m in move_info(_ours(), target)}
            for slot, action in ((0, Action.MOVE_1), (3, Action.MOVE_4)):
                entry = info[slot]
                emitted = set()
                for seed in range(SEED, SEED + 200):
                    nxt = simulate_turn(
                        BattleState(ours=_ours(), target=target, rng=seed, phase=1),
                        action, HUNT)
                    ours = tok.render_turn(tok.normalise(nxt.log[-1])).split("E")[0]
                    emitted.add(ours[2:] or "")
                offered = set()
                if entry["damaging"]:
                    offered |= {"h", "!"}
                else:
                    offered |= {""}
                if entry["can_miss"] and not entry["guaranteed_fail"]:
                    offered |= {"-"}
                self.assertEqual(emitted - offered, set(),
                                 f"{entry['name']} vs {status.value}: simulator can emit "
                                 f"{emitted - offered} which the interview does not offer")
                self.assertEqual(offered - emitted - {"!"}, set(),
                                 f"{entry['name']} vs {status.value}: interview offers "
                                 f"{offered - emitted} which cannot happen")


if __name__ == "__main__":
    unittest.main()
