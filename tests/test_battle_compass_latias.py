"""Supporting Latias: the pieces that are not the sleep model.

Itemised in notes/battle_compass_next_targets.md sec 4c. This file covers C (flinch), D (the two
`will_fail` cases) and E (target configuration). The sleep work (B) and lifting the paralysis
precondition (A) land separately, because A depends on B.
"""
import unittest

from claytonlib.battle.stats import abilities, derive_species_stats, has_pressure, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.sim import (
    EFFECT_REFRESH, EFFECT_WATER_SPORT, FLINCH_EFFECTS, HuntConfig, REFRESH_CURES,
    flinch_visible, simulate_turn, status_applied_by, will_fail,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass.targets import encounter_level, moveset, supported
from claytonlib.moves import resolve_move

HUNT = HuntConfig(target_catch_rate=3, target_has_pressure=False)


def _ours(speed=160, **kw):
    fields = dict(name="Smeargle", level=58, types=("Normal",),
                  stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": speed},
                  moves=("False Swipe", "Mean Look", "Sweet Scent", "Spore"),
                  pp=(40, 5, 20, 15))
    fields.update(kw)
    return Battler(**fields)


def _latias(**kw):
    mv = moveset("latias")
    fields = dict(name="Latias", level=40, types=tuple(species("latias")["types"]),
                  stats=derive_species_stats("latias", 40, "Bold"), moves=mv,
                  pp=tuple(resolve_move(m).pp for m in mv), hp=1)
    fields.update(kw)
    return Battler(**fields)


class TestTheTargetRow(unittest.TestCase):
    """E1. Derived from wotbl.narc, not transcribed -- InitBoxMonMoveset keeps the last four
    learnable moves IN LEARN ORDER, which is the slot order E1-E4 depends on."""

    def test_latias_is_a_supported_target(self):
        self.assertIn("latias", supported())
        self.assertEqual(encounter_level("latias"), 40)
        self.assertEqual(moveset("latias"),
                         ("Water Sport", "Refresh", "Mist Ball", "Zen Headbutt"))

    def test_latios_differs_only_in_two_slots(self):
        """Both twins learn Refresh at L30 and Zen Headbutt at L40; the other two differ."""
        self.assertEqual(moveset("latios"),
                         ("Protect", "Refresh", "Luster Purge", "Zen Headbutt"))

    def test_every_move_in_both_sets_resolves(self):
        for target in ("latias", "latios"):
            for name in moveset(target):
                self.assertIsNotNone(resolve_move(name), f"{target}: {name}")


class TestPressureIsDerived(unittest.TestCase):
    """E2. `target_has_pressure` defaulted True and nothing set it, so a Latias hunt would have
    double-counted our PP and halved every budget the solver plans against."""

    def test_the_twins_have_levitate(self):
        for name in ("latias", "latios"):
            self.assertEqual(abilities(name), ("Levitate",))
            self.assertFalse(has_pressure(name))

    def test_the_birds_still_have_pressure(self):
        for name in ("suicune", "lugia", "ho-oh"):
            self.assertTrue(has_pressure(name))


class TestRefreshFails(unittest.TestCase):
    """D1. Self-targeting, so it reads the ACTOR -- the only family in `will_fail` that does."""

    def setUp(self):
        self.refresh = resolve_move("Refresh")

    def test_it_cures_only_the_three_the_rom_lists(self):
        self.assertEqual(REFRESH_CURES,
                         {Status.BURN, Status.PARALYSIS, Status.POISON})

    def test_an_unstatused_user_fails(self):
        self.assertTrue(will_fail(self.refresh, _ours(), None, actor=_latias()))

    def test_a_paralyzed_user_succeeds(self):
        self.assertFalse(will_fail(self.refresh, _ours(), None,
                                   actor=_latias(status=Status.PARALYSIS)))

    def test_sleep_is_not_curable_by_it(self):
        """The whole reason sleep is the status of choice against a target that knows Refresh --
        and doubly so, since a sleeping Pokemon cannot act to use it at all."""
        self.assertTrue(will_fail(self.refresh, _ours(), None,
                                  actor=_latias(status=Status.SLEEP)))

    def test_freeze_is_not_curable_either(self):
        self.assertTrue(will_fail(self.refresh, _ours(), None,
                                  actor=_latias(status=Status.FREEZE)))

    def test_without_an_actor_it_does_not_claim_to_know(self):
        """`move_info` asks "can this move of ours do nothing to the target" and has no actor to
        offer. Guessing True there would suppress a question the interview must still ask."""
        self.assertFalse(will_fail(self.refresh, _ours()))

    def test_it_is_the_effect_id_the_sim_names(self):
        self.assertEqual(self.refresh.effect, EFFECT_REFRESH)


class TestWaterSportFails(unittest.TestCase):
    """D2. A per-battler volatile flag in the ROM, not a turn counter -- so once up it stays up
    for a wild battle, and a bool is the right shape."""

    def setUp(self):
        self.ws = resolve_move("Water Sport")
        self.state = BattleState(ours=_ours(), target=_latias(), rng=1, phase=2)

    def test_the_first_one_works(self):
        self.assertFalse(will_fail(self.ws, _ours(), self.state))

    def test_the_second_one_fails(self):
        self.state.target_water_sport = True
        self.assertTrue(will_fail(self.ws, _ours(), self.state))

    def test_using_it_sets_the_flag(self):
        """Swept rather than forced: the target's move comes from the RNG, so the only way to
        see Water Sport used is to find a seed on which it picks slot 1."""
        ours, target = _ours(), _latias()
        for seed in range(0xEC1504DC, 0xEC1504DC + 400):
            state = BattleState(ours=ours, target=target, rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            if "E1" in tok.render_turn(tok.normalise(nxt.log[-1])):
                self.assertTrue(nxt.target_water_sport,
                                "Water Sport was used and the flag did not set")
                return
        self.fail("no seed in the sweep had Latias pick Water Sport")

    def test_a_second_water_sport_costs_two_fewer_advances(self):
        """Why the flag is tracked at all: a failing move earns no post-successful-move
        advances, and getting that wrong is what desynchronised test1 at turn 3."""
        ours, target = _ours(), _latias()
        for seed in range(0xEC1504DC, 0xEC1504DC + 400):
            fresh = BattleState(ours=ours, target=target, rng=seed, phase=2)
            if "E1" not in tok.render_turn(
                    tok.normalise(simulate_turn(fresh, Action.MOVE_1, HUNT).log[-1])):
                continue
            first = simulate_turn(
                BattleState(ours=ours, target=target, rng=seed, phase=2), Action.MOVE_1, HUNT)
            already = BattleState(ours=ours, target=target, rng=seed, phase=2)
            already.target_water_sport = True
            repeat = simulate_turn(already, Action.MOVE_1, HUNT)
            self.assertEqual(first.rng_offset - repeat.rng_offset, 2)
            return
        self.fail("no seed in the sweep had Latias pick Water Sport")

    def test_it_survives_a_state_copy(self):
        """`copy` is how the solver branches, so a flag it drops is a flag that silently resets."""
        self.state.target_water_sport = True
        self.assertTrue(self.state.copy().target_water_sport)

    def test_the_dominance_key_separates_on_it(self):
        """Same argument rain and mist already won: it changes which of the target's moves FAIL,
        and a failing move costs the turn two fewer advances -- so two states at one offset that
        disagree about it are not interchangeable."""
        from claytonlib.battle_compass.solver import _dominance_key
        a = BattleState(ours=_ours(), target=_latias(), rng=1, phase=2)
        b = a.copy()
        b.target_water_sport = True
        self.assertNotEqual(_dominance_key(a), _dominance_key(b))

    def test_it_is_the_effect_id_the_sim_names(self):
        self.assertEqual(self.ws.effect, EFFECT_WATER_SPORT)


class TestFlinchIsApplied(unittest.TestCase):
    """C. `can_flinch`, `FLINCH_EFFECTS` and the `fln` token all existed for the UI, but nothing
    applied one -- so a player could report a flinch the simulator could never predict, and the
    turn would match no candidate and read as a contradiction."""

    def test_zen_headbutt_is_a_flinching_move(self):
        self.assertIn(resolve_move("Zen Headbutt").effect, FLINCH_EFFECTS)
        self.assertEqual(resolve_move("Zen Headbutt").effect_chance, 20)

    def test_extrasensory_is_too(self):
        """Which is why this matters before Latias: it is in both Lv45 bird sets."""
        self.assertIn(resolve_move("Extrasensory").effect, FLINCH_EFFECTS)

    def _sweep(self, our_speed, n=4000):
        ours, target = _ours(speed=our_speed), _latias()
        seen = {}
        for seed in range(0xEC1504DC, 0xEC1504DC + n):
            state = BattleState(ours=ours, target=target, rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            seen[tok.render_turn(tok.normalise(nxt.log[-1]))] = True
        return list(seen)

    def test_a_flinch_prevents_our_move_when_the_target_moved_first(self):
        rendered = self._sweep(our_speed=20)
        flinched = [r for r in rendered if "Mfln" in r]
        self.assertTrue(flinched, "no flinch was ever simulated")
        for r in flinched:
            self.assertNotIn("M1", r, f"our move happened anyway: {r}")

    def test_a_flinch_only_lands_after_a_procced_flinching_move(self):
        for r in self._sweep(our_speed=20):
            if "Mfln" in r:
                self.assertIn("E4", r, f"flinched without Zen Headbutt: {r}")
                self.assertIn("~", r, f"flinched without the secondary proccing: {r}")

    def test_we_are_never_flinched_when_we_move_first(self):
        """The flincher has to have moved already. Smeargle at 160 outspeeds every Lv40 Latias
        spread, so in the real matchup this can never happen -- which is exactly why the bug
        stayed hidden."""
        for r in self._sweep(our_speed=160):
            self.assertNotIn("Mfln", r, r)

    def test_the_rate_matches_the_arithmetic(self):
        """1/4 move choice x 90% accuracy x 20% proc = 4.5%."""
        ours, target = _ours(speed=20), _latias()
        hits = 0
        for seed in range(0xEC1504DC, 0xEC1504DC + 4000):
            state = BattleState(ours=ours, target=target, rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            if "fln" in tok.render_turn(tok.normalise(nxt.log[-1])):
                hits += 1
        self.assertAlmostEqual(hits / 4000, 0.045, delta=0.012)

    def test_a_flinched_turn_is_grammatical(self):
        for r in self._sweep(our_speed=20):
            self.assertEqual(tok.validate_turn(tok.tokenise(r)), [], r)


class TestAFlinchThatGoesSecondIsInvisible(unittest.TestCase):
    """A flinch is announced on the VICTIM's turn, not the flincher's -- so a flinching move
    that moves second shows the player nothing at all.

    Reported from a real Latias run: the interview kept asking whether Zen Headbutt's extra
    effect had procced on turns where Latias moved after Smeargle, which is a question with no
    answer -- and the `~` it produced then filtered the candidate set on a guess. Every other
    secondary effect announces itself as it procs; this is the one that does not.

    The proc ROLL is unaffected either way: it belongs to Zen Headbutt, through `effect_chance`,
    so suppressing the marker costs the turn no advances.
    """

    def _sweep(self, our_speed, n=4000):
        ours, target = _ours(speed=our_speed), _latias()
        out = []
        for seed in range(0xEC1504DC, 0xEC1504DC + n):
            state = BattleState(ours=ours, target=target, rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            out.append((seed, tok.render_turn(tok.normalise(nxt.log[-1])),
                        nxt.rng_offset))
        return out

    def test_zen_headbutt_going_second_never_reports_a_secondary(self):
        """Smeargle at 160 outspeeds every Lv40 Latias spread, so Zen Headbutt always goes
        second here -- and in the real matchup it always will."""
        for seed, rendered, _ in self._sweep(our_speed=160):
            if "E4" in rendered:
                self.assertNotIn("~", rendered, f"{seed:#x}: {rendered}")

    def test_going_first_it_still_does(self):
        """The suppression has to be about turn ORDER, not about the move. At speed 20 Latias
        leads, so a procced flinch is visible and must still render."""
        rendered = [r for _, r, _ in self._sweep(our_speed=20)]
        self.assertTrue(any("E4" in r and "~" in r for r in rendered),
                        "no visible flinch was simulated at all")

    def test_the_marker_appears_exactly_when_the_victim_flinched(self):
        """Which is what lets the interview DEDUCE it rather than ask: `~` on a flinching move
        is present if and only if the victim reported the flinch."""
        for seed, rendered, _ in self._sweep(our_speed=20):
            if "E4" not in rendered:
                continue
            self.assertEqual("~" in rendered, "Mfln" in rendered, f"{seed:#x}: {rendered}")

    def test_suppressing_the_marker_spends_the_same_rolls(self):
        """The roll is Zen Headbutt's own. If hiding the token moved the stream, every candidate
        would desync from the turn after -- which would be far worse than the question it fixes.
        """
        ours, target = _ours(speed=160), _latias()
        for seed in range(0xEC1504DC, 0xEC1504DC + 4000):
            state = BattleState(ours=ours, target=target, rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
            if "E4h" not in rendered and "E4!" not in rendered:
                continue
            # 1 selection + 4 BeforeTurn + our False Swipe (crit, damage, accuracy) + 2
            # post-success + 2 between + Zen Headbutt (crit, damage, accuracy, PROC) + 2
            # post-success + 4 end-of-turn.
            self.assertEqual(nxt.rng_offset, 1 + 4 + 3 + 2 + 2 + 4 + 2 + 4, rendered)
            return
        self.fail("no seed in the sweep had Latias land Zen Headbutt")

    def test_a_turn_with_the_marker_suppressed_is_grammatical(self):
        for _, rendered, _ in self._sweep(our_speed=160):
            self.assertEqual(tok.validate_turn(tok.tokenise(rendered)), [], rendered)


class TestOnlyASelectedMoveCanBeFlinched(unittest.TestCase):
    """The rule stated in full: Zen Headbutt's `~` shows only if the Pokemon being flinched had
    **selected a move** and is **moving second**.

    Everything else hides it, and a bag action hides it for a reason independent of Speed: items,
    balls, switches and Revives resolve BEFORE any move, so our turn is already over and there is
    no move left for the flinch to stop. Reported after the switch case still showed a `~`, which
    is why each kind gets its own row here rather than trusting one of them to stand for the rest.
    """

    def _sweep(self, action, our_speed, n=4000, **kw):
        ours = _ours(speed=our_speed)
        bench = (_ours(speed=70, name="Magneton"),)
        target = _latias()
        emitted = 0
        landed = 0
        for seed in range(0xEC1504DC, 0xEC1504DC + n):
            state = BattleState(ours=ours, target=target, rng=seed, bench=bench, phase=2)
            rendered = tok.render_turn(
                tok.normalise(simulate_turn(state, action, HUNT, **kw).log[-1]))
            if "E4" not in rendered:
                continue
            landed += 1
            emitted += "~" in rendered
        self.assertGreater(landed, 0, "Zen Headbutt was never used in the sweep")
        return emitted

    def test_a_switch_hides_it(self):
        """The reported case. We are slower, so Latias moves after the switch resolves -- but we
        have no move pending, so there is nothing to flinch."""
        self.assertEqual(self._sweep(Action.SWITCH, our_speed=20, bench_slot=0), 0)

    def test_an_item_hides_it(self):
        self.assertEqual(self._sweep(Action.ITEM, our_speed=20, item_code="p"), 0)

    def test_a_status_cure_hides_it(self):
        self.assertEqual(self._sweep(Action.ITEM_CURE, our_speed=20), 0)

    def test_the_capture_ball_hides_it(self):
        self.assertEqual(self._sweep(Action.CAPTURE_BALL, our_speed=20), 0)

    def test_a_standard_ball_hides_it(self):
        self.assertEqual(self._sweep(Action.STANDARD_BALL, our_speed=20), 0)

    def test_being_fainted_before_moving_hides_it(self):
        """We never got a move off, which is what the report says outright."""
        self.assertEqual(self._sweep(Action.FAINTED, our_speed=20, replacement=2), 0)

    def test_moving_first_hides_it(self):
        self.assertEqual(self._sweep(Action.MOVE_1, our_speed=160), 0)

    def test_a_move_going_second_is_the_one_case_that_shows_it(self):
        """And it must still be reachable, or every row above passes for the wrong reason."""
        self.assertGreater(self._sweep(Action.MOVE_1, our_speed=20), 0)

    def test_a_revive_hides_it(self):
        ours = _ours(speed=20)
        downed = _ours(speed=70, name="Magneton", hp=0)
        target = _latias()
        landed = emitted = 0
        for seed in range(0xEC1504DC, 0xEC1504DC + 4000):
            state = BattleState(ours=ours, target=target, rng=seed, bench=(downed,), phase=2)
            rendered = tok.render_turn(tok.normalise(
                simulate_turn(state, Action.REVIVE, HUNT, bench_slot=0).log[-1]))
            if "E4" not in rendered:
                continue
            landed += 1
            emitted += "~" in rendered
        self.assertGreater(landed, 0, "Zen Headbutt was never used in the sweep")
        self.assertEqual(emitted, 0)


class TestFlinchVisibilityRule(unittest.TestCase):
    """`flinch_visible` on its own, including the cases a speed sweep cannot reach.

    The rule as the player stated it: a flinch shows if and only if the Pokemon being flinched
    **had selected a move and is moving second**.
    """

    def _visible(self, victim, **kw):
        fields = dict(victim_selected_a_move=True, victim_moves_second=True)
        fields.update(kw)
        return flinch_visible(victim, **fields)

    def test_a_move_selected_and_moving_second_sees_it(self):
        self.assertTrue(self._visible(_ours()))

    def test_moving_first_does_not(self):
        self.assertFalse(self._visible(_ours(), victim_moves_second=False))

    def test_selecting_no_move_does_not(self):
        """A bag action -- an item, either ball, a switch, a Revive -- resolves before any move,
        so the victim has already had its turn and there is no move left to stop. Separate from
        turn order on purpose: these actions also force the user to move first, and relying on
        that made the rule correct only by coincidence."""
        self.assertFalse(self._visible(_ours(), victim_selected_a_move=False))

    def test_neither_half_rescues_the_other(self):
        self.assertFalse(self._visible(_ours(), victim_selected_a_move=False,
                                       victim_moves_second=False))

    def test_a_fainted_victim_does_not(self):
        """It never reaches its move, so the flinch flag is read by nobody."""
        self.assertFalse(self._visible(_ours().with_hp(0)))

    def test_sleep_that_holds_masks_it(self):
        """Sleep is checked BEFORE flinch, so "is fast asleep" is the message shown."""
        self.assertFalse(self._visible(_ours().with_status(Status.SLEEP, sleep_turns=3)))

    def test_sleep_on_its_last_turn_does_not(self):
        """The victim wakes and acts on a count of 1 -- so it reaches the flinch check."""
        self.assertTrue(self._visible(_ours().with_status(Status.SLEEP, sleep_turns=1)))

    def test_paralysis_does_not_mask_it(self):
        """Deliberately not on the list: the verified order is flinch BEFORE paralysis, so a
        flinched-and-paralyzed victim reports the flinch."""
        self.assertTrue(self._visible(_ours().with_status(Status.PARALYSIS)))


class TestSleepIsModelled(unittest.TestCase):
    """B. Not merely unmodelled before this -- actively wrong: `act_target` checked only
    PARALYSIS, so a sleeping target fell through and ATTACKED, and the rolled duration was
    computed and discarded so it would never have woken either.

    The counting mirrors `metronome_compass`, which is RNG-verified against Blackthorn ground
    truth: the status ends when the remaining count reaches 1 and the Pokemon ACTS on that turn,
    and a sleeping turn spends no roll (`raw_emit`, no advance).
    """

    def test_applying_sleep_stores_the_rolled_duration(self):
        self.assertEqual(_latias().with_status(Status.SLEEP, sleep_turns=4).sleep_turns, 4)

    def test_clearing_a_status_clears_the_counter(self):
        slept = _latias().with_status(Status.SLEEP, sleep_turns=4)
        self.assertEqual(slept.with_status(Status.NONE).sleep_turns, 0)

    def test_a_non_sleep_status_carries_no_counter(self):
        self.assertEqual(
            _latias().with_status(Status.PARALYSIS, sleep_turns=4).sleep_turns, 0)

    def test_the_counter_ends_at_one_and_the_target_acts_that_turn(self):
        slept = _latias().with_status(Status.SLEEP, sleep_turns=3)
        acted = []
        for _ in range(4):
            slept, acts = slept.tick_sleep()
            acted.append(acts)
        self.assertEqual(acted, [False, False, True, True])

    def test_a_rolled_two_costs_exactly_one_turn(self):
        """So the 2..5 the game rolls is 1..4 turns of lost action."""
        slept, acts = _latias().with_status(Status.SLEEP, sleep_turns=2).tick_sleep()
        self.assertFalse(acts)
        _, acts_next = slept.tick_sleep()
        self.assertTrue(acts_next)

    def test_an_awake_battler_always_acts(self):
        for status in (Status.NONE, Status.PARALYSIS, Status.BURN):
            battler, acts = _latias(status=status).tick_sleep()
            self.assertTrue(acts, status)

    def test_a_sleeping_target_does_not_act_in_a_real_turn(self):
        """The bug, stated as the failure: before this the target attacked while asleep."""
        ours = _ours(moves=("Spore", "False Swipe"), pp=(15, 40))
        state = BattleState(ours=ours, target=_latias(), rng=0xEC1504DC, phase=2)
        state = simulate_turn(state, Action.MOVE_1, HUNT)          # Spore
        self.assertIs(state.target.status, Status.SLEEP)
        self.assertGreater(state.target.sleep_turns, 0)
        rendered = tok.render_turn(tok.normalise(state.log[-1]))
        self.assertIn("Eslp", rendered)
        self.assertNotIn("E1", rendered)
        self.assertNotIn("E2", rendered)

    def test_it_wakes_and_acts_after_the_counter_runs_out(self):
        """The counter READ BACK after the Spore turn equals the number of turns the target will
        miss, because that same turn already ticked it once. So a rolled 2..5 costs 1..4 turns,
        and the visible counter is the honest "turns left asleep"."""
        for seed in (0xEC1504DC, 0xEC150500, 0xEC150600):
            ours = _ours(moves=("Spore", "False Swipe"), pp=(15, 40))
            state = BattleState(ours=ours, target=_latias(), rng=seed, phase=2)
            state = simulate_turn(state, Action.MOVE_1, HUNT)
            if state.target.status is not Status.SLEEP:
                continue                      # Spore missed on this seed
            remaining = state.target.sleep_turns
            asleep = 1 if "Eslp" in tok.render_turn(tok.normalise(state.log[-1])) else 0
            for _ in range(remaining + 3):
                state = simulate_turn(state, Action.MOVE_2, HUNT)
                if "Eslp" in tok.render_turn(tok.normalise(state.log[-1])):
                    asleep += 1
                else:
                    break
            self.assertIs(state.target.status, Status.NONE, f"{seed:#x}: it never woke")
            self.assertEqual(asleep, remaining, f"{seed:#x}")
            self.assertTrue(1 <= remaining <= 4, f"{seed:#x}: {remaining} turns")

    def test_a_sleeping_turn_spends_no_roll_of_its_own(self):
        """Verified in metronome_compass by `raw_emit`, and measured here against the only fair
        comparison: a turn the target spends FULLY PARALYZED, which also takes no action but DOES
        pay for its check roll. Comparing against an ordinary paralyzed turn would measure the
        target's move instead, which is a seven-roll difference and no evidence at all.
        """
        ours = _ours(moves=("False Swipe",), pp=(40,))
        for seed in range(0xEC1504DC, 0xEC1504DC + 400):
            para = simulate_turn(
                BattleState(ours=ours, target=_latias().with_status(Status.PARALYSIS),
                            rng=seed, phase=2), Action.MOVE_1, HUNT)
            if "Epar" not in tok.render_turn(tok.normalise(para.log[-1])):
                continue
            slept = simulate_turn(
                BattleState(ours=ours,
                            target=_latias().with_status(Status.SLEEP, sleep_turns=4),
                            rng=seed, phase=2), Action.MOVE_1, HUNT)
            self.assertIn("Eslp", tok.render_turn(tok.normalise(slept.log[-1])))
            self.assertEqual(para.rng_offset - slept.rng_offset, 1,
                             "a fully-paralyzed turn should cost exactly one roll more")
            return
        self.fail("no seed in the sweep had the target fully paralyzed")

    def test_a_sleeping_turn_is_grammatical(self):
        ours = _ours(moves=("Spore", "False Swipe"), pp=(15, 40))
        state = BattleState(ours=ours, target=_latias(), rng=0xEC1504DC, phase=2)
        state = simulate_turn(state, Action.MOVE_1, HUNT)
        for _ in range(3):
            state = simulate_turn(state, Action.MOVE_2, HUNT)
        for entry in state.log:
            self.assertEqual(tok.validate_turn(tok.normalise(entry)), [], entry)

    def test_the_dominance_key_separates_on_remaining_sleep(self):
        """Two states at one offset with different remaining sleep are not interchangeable: one
        wakes sooner and from then on spends different advances."""
        from claytonlib.battle_compass.solver import _dominance_key
        a = BattleState(ours=_ours(), target=_latias().with_status(Status.SLEEP, sleep_turns=4),
                        rng=1, phase=2)
        b = BattleState(ours=_ours(), target=_latias().with_status(Status.SLEEP, sleep_turns=2),
                        rng=1, phase=2)
        self.assertNotEqual(_dominance_key(a), _dominance_key(b))


class TestThePreconditionAcceptsSleep(unittest.TestCase):
    """A. Paralysis was asserted twice; sleep satisfies the purpose more strongly. Burn and
    poison are still refused -- same catch bonus, but they tick HP, so the target is not frozen
    and `b` is not a constant."""

    def test_which_statuses_hold_the_target_still(self):
        for status in (Status.PARALYSIS, Status.SLEEP, Status.FREEZE):
            self.assertTrue(_latias(status=status).frozen_for_phase2, status)
        for status in (Status.NONE, Status.BURN, Status.POISON):
            self.assertFalse(_latias(status=status).frozen_for_phase2, status)

    def test_the_solver_accepts_a_sleeping_target(self):
        from claytonlib.battle_compass.solver import Solution, SolverConfig, Unreachable, solve
        state = BattleState(ours=_ours(), rng=0xEC1504DC, phase=2,
                            target=_latias().with_status(Status.SLEEP, sleep_turns=4))
        result = solve(state, HUNT, SolverConfig(danger_floor=56))
        self.assertNotIsInstance(result, Unreachable) if isinstance(result, Solution) else None
        if isinstance(result, Unreachable):
            self.assertNotIn("preconditions do not hold", result.reason)

    def test_the_solver_still_refuses_a_burned_target(self):
        from claytonlib.battle_compass.solver import SolverConfig, Unreachable, solve
        state = BattleState(ours=_ours(), rng=0xEC1504DC, phase=2,
                            target=_latias().with_status(Status.BURN))
        result = solve(state, HUNT, SolverConfig(danger_floor=56))
        self.assertIsInstance(result, Unreachable)
        self.assertIn("preconditions do not hold", result.reason)

    def test_the_blocker_message_names_what_is_needed(self):
        from claytonlib.battle_compass.candidates import Candidate
        from claytonlib.battle_compass.identify import Phase, Session
        session = Session([Candidate(seed=0xEC1504DC, frame=1, second=0)],
                          _ours(), _latias(status=Status.BURN), HUNT, phase=Phase.PINNING)
        blockers = session.solver_blockers()
        self.assertTrue(any("paralyzed or asleep" in b for b in blockers), blockers)

    def test_a_sleeping_one_hp_target_has_no_status_blocker(self):
        from claytonlib.battle_compass.candidates import Candidate
        from claytonlib.battle_compass.identify import Phase, Session
        session = Session([Candidate(seed=0xEC1504DC, frame=1, second=0)], _ours(),
                          _latias().with_status(Status.SLEEP, sleep_turns=4), HUNT,
                          phase=Phase.PINNING)
        self.assertEqual([b for b in session.solver_blockers() if "asleep" in b], [])

    def test_sleep_is_the_better_catch_status(self):
        """Which is the other half of why this is worth doing, not just a workaround."""
        from claytonlib.battle.catch import (BALL_POKE, STATUS_PARALYSIS, STATUS_SLEEP,
                                             catch_value, shake_threshold)
        stats = derive_species_stats("latias", 40, "Bold", ivs=31)
        b = {}
        for label, bonus in (("par", STATUS_PARALYSIS), ("slp", STATUS_SLEEP)):
            b[label] = shake_threshold(catch_value(
                12, ball_multiplier=BALL_POKE, cur_hp=1, max_hp=stats["hp"],
                status_bonus=bonus))
        self.assertGreater(b["slp"], b["par"])


class TestTheSolverPlansWithSleep(unittest.TestCase):
    """Sleep needs no second clock, and no backwards reasoning.

    The initial plan (sec 4c, B5/B6) said a Phase 2 path "must land its throw before the target
    wakes, or plan the re-Spore", and treated the sleep window as a deadline. That was the wrong
    shape. Sleep is a *state*, the catch bonus is read at the throw and nowhere else, and
    ordinary Dijkstra over states handles entering and leaving it with no special case: Spore is
    an action, waking is a transition, and a re-Spore is just the search taking Spore again.

    What sleep genuinely changes is one thing, and it is a soundness bug rather than a feature:
    `b` is no longer constant across a path, so the single threshold used to PRUNE the search was
    being taken from the entry state.
    """

    HUNT = HuntConfig(target_catch_rate=3, fast_ball_matched=True, target_has_pressure=False)

    def _state(self, status=Status.PARALYSIS, sleep_turns=0, rng=0xEC1504DC):
        target = _latias(status=status, sleep_turns=sleep_turns)
        return BattleState(ours=_ours(), target=target, rng=rng, phase=2)

    def _config(self):
        from claytonlib.battle_compass.solver import SolverConfig
        return SolverConfig(danger_floor=56)

    def test_spore_cannot_miss_so_sleep_is_guaranteed(self):
        """Which is why the forward search needs no assumption: Spore is 100 accuracy, Latias
        has no Safeguard in its set and nothing in Gen 4 is powder-immune, so an awake unstatused
        Latias is asleep next turn with certainty rather than with probability."""
        from claytonlib.battle_compass.sim import can_miss
        spore = resolve_move("Spore")
        self.assertEqual(spore.accuracy, 100)
        self.assertFalse(can_miss(spore, 0))
        self.assertNotIn("Safeguard", moveset("latias"))

    def test_sporing_an_awake_target_always_sleeps_it(self):
        """Swept rather than argued: every seed, not most."""
        ours = _ours(moves=("Spore",), pp=(15,))
        for seed in range(0xEC1504DC, 0xEC1504DC + 300):
            state = BattleState(ours=ours, target=_latias(status=Status.NONE),
                                rng=seed, phase=2)
            nxt = simulate_turn(state, Action.MOVE_1, self.HUNT)
            self.assertIs(nxt.target.status, Status.SLEEP, f"{seed:#x}")
            self.assertGreaterEqual(nxt.target.sleep_turns, 1, f"{seed:#x}")

    def test_the_reachable_statuses_are_the_current_one_none_and_what_we_can_inflict(self):
        from claytonlib.battle_compass.solver import reachable_statuses
        got = reachable_statuses(self._state(), self._config())
        self.assertEqual(got, {Status.PARALYSIS, Status.NONE, Status.SLEEP})

    def test_a_move_with_no_pp_left_cannot_inflict_anything(self):
        from claytonlib.battle_compass.solver import reachable_statuses
        state = self._state()
        state.ours = state.ours.spend_pp(3, 99)            # Spore exhausted
        self.assertNotIn(Status.SLEEP, reachable_statuses(state, self._config()))

    def test_the_prune_threshold_is_the_largest_reachable_one(self):
        from claytonlib.battle_compass.solver import (max_reachable_threshold,
                                                      target_threshold)
        state = self._state()
        entry = target_threshold(state, self.HUNT)
        largest = max_reachable_threshold(state, self.HUNT, self._config())
        self.assertGreater(largest, entry, "Spore reaches a more generous b than paralysis")
        self.assertEqual(largest, target_threshold(state, self.HUNT, Status.SLEEP))

    def test_pruning_at_the_entry_threshold_would_prove_unreachability_falsely(self):
        """The bug, as the failure it would have been. These seeds have NO capture window at a
        paralyzed target's b and several at a sleeping one's -- so the old prune would have
        returned `proven=True`, and `proven` is the signal that justifies a soft reset (sec 6.3).
        A false proof there does not lose a path, it costs the run.
        """
        from claytonlib.battle_compass.solver import capture_windows_in_horizon
        b_par, b_slp = 33824, 36157
        cases = [(0x10000023, 60), (0x1000002f, 120), (0x1000004b, 60)]
        for seed, horizon in cases:
            self.assertEqual(capture_windows_in_horizon(seed, b_par, horizon), [],
                             f"{seed:#x}: fixture expects no window at the paralyzed b")
            self.assertTrue(capture_windows_in_horizon(seed, b_slp, horizon),
                            f"{seed:#x}: fixture expects a window at the sleeping b")

    def test_a_sleeping_entry_state_reaches_the_same_maximum(self):
        """Entering asleep already has the largest b, so nothing changes for that case -- the
        old code was only ever wrong in the direction of too SMALL a threshold."""
        from claytonlib.battle_compass.solver import max_reachable_threshold, target_threshold
        state = self._state(status=Status.SLEEP, sleep_turns=4)
        self.assertEqual(max_reachable_threshold(state, self.HUNT, self._config()),
                         target_threshold(state, self.HUNT))

    def test_the_unreachable_message_says_which_threshold_it_proved_against(self):
        """A proof the player cannot audit is a proof they have to take on trust."""
        from claytonlib.battle_compass.solver import SolverConfig, Unreachable, solve
        state = self._state(rng=0x10000023)
        result = solve(state, self.HUNT, SolverConfig(danger_floor=56, max_turns=2))
        if isinstance(result, Unreachable) and result.capture_windows == 0:
            self.assertIn("most generous", result.reason)

    def test_the_solver_finds_a_path_from_a_paralyzed_latias(self):
        """End to end: ordinary Dijkstra, no sleep-specific machinery."""
        from claytonlib.battle_compass.solver import Solution, solve
        result = solve(self._state(), self.HUNT, self._config())
        self.assertIsInstance(result, Solution, getattr(result, "reason", ""))
        self.assertTrue(result.steps)
        self.assertIs(result.steps[-1].action, Action.CAPTURE_BALL)

    def test_a_solved_path_replays_to_an_actual_capture(self):
        """The goal test is `simulate_turn`, so replaying the path must capture -- which is also
        what proves the throw's status was read at the throw rather than at entry."""
        from claytonlib.battle_compass.solver import Solution, solve
        result = solve(self._state(), self.HUNT, self._config())
        self.assertIsInstance(result, Solution)
        state = self._state()
        for step in result.steps:
            state = simulate_turn(state, step.action, self.HUNT,
                                  **({"item_code": step.item} if step.item else {}))
        self.assertTrue(state.captured, "the solved path did not capture on replay")

    def test_it_can_solve_from_an_asleep_latias_too(self):
        from claytonlib.battle_compass.solver import Solution, solve
        result = solve(self._state(status=Status.SLEEP, sleep_turns=4), self.HUNT,
                       self._config())
        self.assertIsInstance(result, Solution, getattr(result, "reason", ""))

    def test_a_path_may_outlive_the_sleep_window_and_that_is_fine(self):
        """The plan treated this as the thing to prevent. It is not: the bonus is read at the
        throw, so a path that lets the target wake and throws later is simply a path at the awake
        threshold, and distance decides between them. Checked by replaying: whatever the solver
        returns, it captures."""
        from claytonlib.battle_compass.solver import Solution, solve
        for rng in (0xEC1504DC, 0xEC150700, 0xEC150900):
            state = self._state(status=Status.SLEEP, sleep_turns=2, rng=rng)
            result = solve(state, self.HUNT, self._config())
            if not isinstance(result, Solution):
                continue
            replay = self._state(status=Status.SLEEP, sleep_turns=2, rng=rng)
            for step in result.steps:
                replay = simulate_turn(replay, step.action, self.HUNT,
                                       **({"item_code": step.item} if step.item else {}))
            self.assertTrue(replay.captured, f"{rng:#x}")
