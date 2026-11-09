"""Encore, Yawn, Recover and Struggle — the four moves a Damp Quagsire plan needed.

The plan that asked for them does not survive contact with the ROM: it was built around
Encore-locking a regi into Explosion, and **the Lv30 titans do not have Explosion** --
`BoxPokemon_SetDefaultMoves` keeps the last four learnable and Explosion is the level-1 entry
that gets bubbled out (notes/platinum.md sec 21, and `targets.ENCOUNTERS`' own comment). So Damp
is dead weight against them. Three quarters of the party survives anyway, and Encore turns out to
be worth more than the Explosion lock was:

* **Encore (90)** is the first move on either side that takes the target's CHOICE away rather
  than changing what the choice is worth. While it runs the selection roll is still spent but its
  modulus is one, so the target's half of every turn is predictable.
* **Yawn (187)** was already wired in both directions and only lacked permission -- the one way
  to sleep a Clear Body target without an accuracy roll.
* **Recover (32)** is the first self-heal of ours, and the only move whose ADVANCE COUNT the
  player controls: it fails at full HP, two advances cheaper than when it heals.
* **Struggle (254)** was outside the model entirely, so a target out of PP stood still and the
  turn was silently wrong. It is cheap to model and ruinous to plan into, and those are two
  different decisions made in two different places.

(clayton-ek3 is the HGSS half of Encore's duration; clayton-c3c4 is the capture the roamer
Struggle path still wants.)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.sim import (
    CANNOT_ENCORE_EFFECTS, ENCORE_TURNS_MIN, ENCORE_TURNS_SPAN, EFFECT_ENCORE, EFFECT_RECOVER,
    EFFECT_STRUGGLE, FULL_HP_FAILS_EFFECTS, MODELLED_OUR_EFFECTS, STRUGGLE_RECOIL_DIVISOR,
    HuntConfig, execute_move, move_roll_cost, opening_rng, select_roamer_action,
    select_target_move, sent_out, simulate_turn, struggle_move, unselectable_reason, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.battle_compass import tokens as tok
from claytonlib.moves import resolve_move

ENCORE, YAWN, RECOVER, TAIL_WHIP = 0, 1, 2, 3
STOMP, ROCK_THROW, CURSE, SUPERPOWER = 0, 1, 2, 3


def _titan(**kwargs) -> Battler:
    """Regirock as the game builds it: Stomp, Rock Throw, Curse, Superpower. No Explosion."""
    return replace(Battler(
        name="Regirock", level=30, types=("Rock",),
        stats=derive_species_stats("regirock", 30, "Timid", ivs=31),
        moves=moveset("regirock"),
        pp=tuple(resolve_move(m).pp for m in moveset("regirock")),
        ability="Clear Body"), **kwargs)


def _quagsire(**kwargs) -> Battler:
    """The bred Quagsire: Lv44, Impish, 31s. **Lv44 and not Lv40** -- 49 Speed, which clears a
    +Speed perfect Regice's 48. At Lv43 it would TIE one, and a tie spends extra rolls."""
    return replace(Battler(
        name="Quagsire", level=44, types=("Water", "Ground"),
        stats=derive_species_stats("quagsire", 44, "Impish", ivs=31),
        moves=("Encore", "Yawn", "Recover", "Tail Whip"), pp=(5, 10, 10, 30),
        ability="Damp"), **kwargs)


def _config() -> HuntConfig:
    # Clear Body, not Pressure, so our PP is spent one at a time.
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


def _state(ours=None, target=None, seed: int = 0x12345678) -> BattleState:
    config = _config()
    return BattleState(rng=opening_rng(seed, config),
                       ours=ours if ours is not None else _quagsire(),
                       target=target if target is not None else _titan())


def _rendered(state: BattleState) -> str:
    return tok.render_turn(tok.normalise(state.log[-1]))


def _sim_source(name: str) -> str:
    """One function's source out of `sim`, for the one assertion that is about ORDER.

    Encore's override must stay below the turn-order calculation, and no state the simulator can
    reach proves that: none of the titan's moves carries a priority of its own, so a test that
    tried to observe it would pass either way.
    """
    import inspect

    from claytonlib.battle_compass import sim

    return inspect.getsource(getattr(sim, name))


class TestThePremiseThatStartedThis(unittest.TestCase):
    def test_the_titans_have_no_explosion_to_lock_them_into(self):
        """Asserted rather than assumed, because the whole Damp plan rested on the opposite and
        because `targets.ENCOUNTERS` already said so. Five moves are learnable at 30 --
        Explosion(1), Stomp(1), Rock Throw(9), Curse(17), Superpower(25) -- and the oldest is the
        one that goes."""
        for species in ("regirock", "regice", "registeel"):
            with self.subTest(species):
                self.assertNotIn("Explosion", moveset(species))
                self.assertEqual(len(moveset(species)), 4)

    def test_quagsire_outspeeds_every_regice_at_level_44(self):
        """The level floor is 44, not 40. A +Speed perfect Regice reaches 48 at Lv30; Quagsire is
        45 at Lv40, 48 at Lv43 -- a TIE, which sec 4.2 forbids because ties spend extra rolls --
        and 49 at Lv44."""
        fastest_regice = derive_species_stats("regice", 30, "Jolly", ivs=31)["spe"]
        self.assertEqual(fastest_regice, 48)
        speeds = {level: derive_species_stats("quagsire", level, "Impish", ivs=31)["spe"]
                  for level in (40, 43, 44)}
        self.assertEqual(speeds, {40: 45, 43: 48, 44: 49})
        self.assertGreater(speeds[44], fastest_regice)
        self.assertEqual(speeds[43], fastest_regice)   # the tie the floor exists to clear


class TestEncoresDuration(unittest.TestCase):
    def test_it_is_three_to_seven_because_the_modulus_is_five(self):
        """``BattleSystem_RandNext(battleSys) % 5 + 3`` (battle_script.c:4742). **Seven is the
        assertion that matters**: under the ``% 4`` the shared notes claim, 7 is unreachable, so
        observing it is what tells the two formulas apart. See clayton-ek3."""
        self.assertEqual((ENCORE_TURNS_MIN, ENCORE_TURNS_SPAN), (3, 5))
        move = resolve_move("Encore")
        rolled = {execute_move(0x12345678 + d * 7919, move, _quagsire(),
                               _titan(last_move_slot=STOMP), actor="M", slot=ENCORE,
                               field=None)[1].starts_encore
                  for d in range(400)}
        self.assertEqual(rolled, {3, 4, 5, 6, 7})

    def test_the_modulus_is_what_separates_rtc_second_siblings(self):
        """notes/seed_separation.md's rule: a check is blind to two seeds one RTC second apart iff
        its modulus divides 256. Five does not, which is why the duration is an identification
        signal at all -- and why the ``% 4`` in `metronome_compass` throws one away."""
        self.assertNotEqual(256 % ENCORE_TURNS_SPAN, 0)

    def test_it_costs_two_rolls_when_it_lands_and_one_when_it_fails(self):
        """Taunt's shape exactly: accuracy 100, so the accuracy roll is spent either way, and the
        duration roll sits past every refusal in `BtlCmd_TryEncore`."""
        move = resolve_move("Encore")
        _, landed = execute_move(0x12345678, move, _quagsire(), _titan(last_move_slot=STOMP),
                                 actor="M", slot=ENCORE, field=None)
        _, failed = execute_move(0x12345678, move, _quagsire(), _titan(last_move_slot=None),
                                 actor="M", slot=ENCORE, field=None)
        self.assertEqual((landed.rolls, landed.successful), (2, True))
        self.assertEqual((failed.rolls, failed.successful), (1, False))
        self.assertEqual(move_roll_cost(move), 2)       # the upper bound is the landing case


class TestWhatRefusesAnEncore(unittest.TestCase):
    """All four of `BtlCmd_TryEncore`'s failures, in the ROM's own order."""

    def test_a_victim_that_has_not_moved_cannot_be_encored(self):
        """`DEFENDER_LAST_MOVE` is `movePrevByBattler`, zero until something executes."""
        self.assertTrue(will_fail(resolve_move("Encore"), _titan(last_move_slot=None)))

    def test_an_already_encored_victim_fails_rather_than_refreshing(self):
        self.assertTrue(will_fail(resolve_move("Encore"),
                                  _titan(last_move_slot=STOMP, encored_slot=STOMP,
                                         encored_turns=4)))

    def test_a_slot_out_of_pp_fails(self):
        self.assertTrue(will_fail(resolve_move("Encore"),
                                  _titan(last_move_slot=SUPERPOWER, pp=(20, 15, 10, 0))))

    def test_the_ban_list_is_by_effect_not_by_move_number(self):
        """``MOVE_DATA(sCannotEncoreMoves[i]).effect == MOVE_DATA(move).effect``
        (battle_lib.c:7221-7231), so the ban covers every move sharing an effect with one of the
        six. Nothing in any configured moveset is in it, which is why this is checked against the
        move table rather than against a run."""
        for name in ("Transform", "Mimic", "Sketch", "Mirror Move", "Encore", "Struggle"):
            with self.subTest(name):
                self.assertIn(resolve_move(name).effect, CANNOT_ENCORE_EFFECTS)
        for name in ("Stomp", "Rock Throw", "Curse", "Superpower"):
            with self.subTest(name):
                self.assertNotIn(resolve_move(name).effect, CANNOT_ENCORE_EFFECTS)

    def test_a_fresh_titan_that_just_moved_can_be_encored(self):
        self.assertFalse(will_fail(resolve_move("Encore"), _titan(last_move_slot=STOMP)))


class TestTheLastMoveRecord(unittest.TestCase):
    """`movePrevByBattler` is set when the move EXECUTED and cleared when it did not -- which is
    not the same as "when it worked"."""

    def test_a_missed_move_still_counts(self):
        """`SYSCTL_MOVE_SUCCEEDED` goes up when the move's script is loaded
        (battle_controller_player.c:3212), before the accuracy check -- so a miss records.
        Rock Throw is 90 accuracy, which is how the miss is reachable at all."""
        state = _state(target=_titan(pp=(0, 15, 0, 0)))
        for _ in range(12):
            state = simulate_turn(state, Action.MOVE_4, _config())
            if tok.MISS in _rendered(state):
                self.assertEqual(state.target.last_move_slot, ROCK_THROW)
                return
        self.fail("no miss in twelve Rock Throws, so the record was never tested on one")

    def test_a_prevented_move_clears_it(self):
        """Asleep, so the move never executed -- and the next turn's Encore therefore fails."""
        state = _state(target=_titan(status=Status.SLEEP, sleep_turns=9,
                                     last_move_slot=STOMP))
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn("Eslp", _rendered(state))
        self.assertIsNone(state.target.last_move_slot)
        self.assertTrue(will_fail(resolve_move("Encore"), state.target))

    def test_a_bag_action_of_ours_preserves_our_own_record(self):
        """Our Pokemon never enters `FightCommand` on an item turn, so it never reaches MoveEnd
        and its record is kept. Which is the half that matters to a plan: throwing a ball does
        not cost us the Encore we were lining up."""
        state = _state(ours=_quagsire(last_move_slot=TAIL_WHIP))
        state = simulate_turn(state, Action.STANDARD_BALL, _config())
        self.assertEqual(state.ours.last_move_slot, TAIL_WHIP)

    def test_switching_out_clears_the_lock_and_the_record(self):
        """`BattleSystem_UpdateAfterSwitch` clears `movePrevByBattler` and a fresh BattleMon
        zeroes `moveEffectsData` -- so a switch is the clean way out of an Encore."""
        locked = _quagsire(encored_slot=TAIL_WHIP, encored_turns=4, last_move_slot=TAIL_WHIP)
        fresh = sent_out(locked)
        self.assertIsNone(fresh.encored_slot)
        self.assertEqual(fresh.encored_turns, 0)
        self.assertIsNone(fresh.last_move_slot)


class TestTheLockItself(unittest.TestCase):
    def test_it_collapses_the_selection_modulus_without_skipping_the_roll(self):
        """**The fact a run desynchronises on if it is got wrong.** Encore is nowhere in
        `Battler_CanPickCommand`, so unlike a charge or an Uproar the roll is still spent -- the
        ROM marks every other slot invalid and the wild picker does
        ``validMoves[RandNext % 1]`` (battle_display.c:3611)."""
        locked = _titan(encored_slot=CURSE, encored_turns=4)
        self.assertEqual(locked.usable_slots(), (CURSE,))
        seed = 0xABCDEF01
        for offset in range(16):
            with self.subTest(offset):
                rng, slot = select_target_move(seed + offset, locked)
                self.assertEqual(slot, CURSE)
                self.assertNotEqual(rng, seed + offset)     # the roll WAS spent

    def test_a_charge_lock_does_skip_the_roll_which_is_the_contrast(self):
        """Stated beside the test above because the two look alike and cost differently."""
        seed = 0xABCDEF01
        rng, slot = select_target_move(seed, _titan(charging_slot=STOMP))
        self.assertEqual((rng, slot), (seed, STOMP))

    def test_the_lock_runs_for_exactly_the_rolled_number_of_turns_after_the_encore(self):
        """A rolled D locks turns T+1..T+D and the wear-off lands at the end of T+D. The counter
        is decremented while nonzero and released on the tick it is FOUND at zero, which is where
        the extra turn comes from.

        Entered mid-lock with three turns left, which is the state an Encore that rolled 4 leaves
        behind after its own end-of-turn tick. So FOUR more forced turns, not three: 3->2, 2->1,
        1->0, then the release -- and the release turn was itself forced, because selection
        happens before the end-of-turn walk.
        """
        state = _state(target=_titan(encored_slot=STOMP, encored_turns=3))
        seen = []
        for _ in range(4):
            state = simulate_turn(state, Action.MOVE_4, _config())
            seen.append(_rendered(state))
        self.assertEqual([("E1" in t) for t in seen], [True, True, True, True])
        self.assertEqual([(tok.encore_ended_token("target") in t) for t in seen],
                         [False, False, False, True])
        self.assertIsNone(state.target.encored_slot)

    def test_the_counter_ticks_while_its_victim_is_asleep(self):
        """**The question the plan turned on, and the answer is the unhelpful one.**
        `MON_COND_CHECK_STATE_ENCORE` is state 17 of the end-of-turn condition walk and its
        decrement is not gated on anything the victim did -- the opposite of
        `Battler.tick_confusion`, which only moves when its holder tries to act. So a Yawn aimed
        at an Encored target SPENDS the lock rather than protecting it."""
        state = _state(target=_titan(encored_slot=STOMP, encored_turns=3,
                                     status=Status.SLEEP, sleep_turns=9))
        counters = []
        for _ in range(4):
            state = simulate_turn(state, Action.MOVE_4, _config())
            self.assertIn("Eslp", _rendered(state))      # it never acted on any of them
            counters.append(state.target.encored_turns)
        self.assertEqual(counters, [2, 1, 0, 0])
        self.assertIsNone(state.target.encored_slot)     # released anyway

    def test_running_the_encored_move_out_of_pp_releases_the_lock(self):
        """And **does NOT force a Struggle**, which is what notes/ss_rng/effects.md claims. State
        17 zeroes `encoredTurns` the moment ``ppCur[slot] == 0`` and falls into the release branch
        on the same tick, so the next selection happens with Encore already gone."""
        state = _state(target=_titan(encored_slot=SUPERPOWER, encored_turns=5,
                                     pp=(20, 15, 10, 1)))
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn("E4", _rendered(state))                       # the last Superpower
        self.assertIn(tok.encore_ended_token("target"), _rendered(state))
        self.assertIsNone(state.target.encored_slot)
        self.assertEqual(state.target.pp_left(SUPERPOWER), 0)
        # Free again, and picking from the three slots that still have PP rather than Struggling.
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertNotIn("E0", _rendered(state))

    def test_the_whole_sequence_against_a_titan(self):
        """End to end, which is the test that would have caught any of the above being wrong: a
        Tail Whip to give the titan a last move, an Encore, then the lock."""
        state = _state()
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIsNotNone(state.target.last_move_slot)
        state = simulate_turn(state, Action.MOVE_1, _config())
        self.assertIsNotNone(state.target.encored_slot)
        self.assertIn(state.target.encored_turns, range(ENCORE_TURNS_MIN, ENCORE_TURNS_MIN
                                                        + ENCORE_TURNS_SPAN))
        locked_slot = state.target.encored_slot
        for _ in range(3):
            state = simulate_turn(state, Action.MOVE_4, _config())
            self.assertIn(f"E{locked_slot + 1}", _rendered(state))


class TestTheLockOverridesTheMoveAtExecutionTime(unittest.TestCase):
    """The half of Encore that was missing, and the turn it is visible on is the first one.

    `BattleSystem_CheckInvalidMoves` narrowing the selection to one slot is only half the lock.
    `BattleControllerPlayer_FightCommand` (battle_controller_player.c:1861-1896) picks what the
    attacker actually USES, and its second branch -- above every "use the selected slot" case and
    below only Struggle -- replaces the move with the encored one outright [verified].

    On every turn but one the two halves agree. The exception is the turn the Encore lands with
    us moving first: the target had already chosen, from all four slots, so the selection roll was
    spent at the full modulus -- and then the override throws that verdict away. Reported from a
    real run (clayton-957.44): an Encore on a Regirock that had just used Superpower forced
    Superpower, while the simulator predicted whatever the roll had picked.
    """

    def test_we_do_outspeed_the_titan_which_is_what_makes_this_reachable(self):
        """Stated first, because the whole case is "the Encorer moved first"."""
        from claytonlib.battle_compass.sim import effective_speed

        self.assertGreater(effective_speed(_quagsire()), effective_speed(_titan()))

    def test_the_encore_turn_itself_uses_the_encored_move_for_every_seed(self):
        """Swept, because the bug was invisible on the seeds where the roll happened to agree:
        one slot in four looked correct."""
        used = set()
        for seed in range(0x1000, 0x1100):
            state = _state(target=_titan(last_move_slot=SUPERPOWER), seed=seed)
            state = simulate_turn(state, Action.MOVE_1, _config())
            self.assertIsNotNone(state.target.encored_slot, "the fixture must land the Encore")
            used.add(next(t[:2] for t in tok.tokenise(_rendered(state)) if t.startswith("E")))
        self.assertEqual(used, {f"E{SUPERPOWER + 1}"})

    def test_the_roll_is_still_spent_at_the_FULL_modulus_and_its_verdict_discarded(self):
        """Nothing about the stream moves. The Encore does not exist when the target picks, so
        the roll is taken over all four slots exactly as it always was -- and then the override
        throws the answer away. Both halves are asserted, because getting the first one wrong
        instead would desynchronise every turn of the lock rather than mispredicting one move.
        """
        rolled, executed = set(), set()
        for seed in range(0x1000, 0x1100):
            state = _state(target=_titan(last_move_slot=SUPERPOWER), seed=seed)
            # What the target picked, read off the pre-turn state: it is not encored yet, so the
            # modulus really is four.
            self.assertIsNone(state.target.encored_slot)
            rolled.add(select_target_move(state.rng, state.target)[1])
            state = simulate_turn(state, Action.MOVE_1, _config())
            executed.add(next(t[:2] for t in tok.tokenise(_rendered(state))
                              if t.startswith("E")))
        self.assertEqual(rolled, {STOMP, ROCK_THROW, CURSE, SUPERPOWER},
                         "the selection roll must still range over every slot")
        self.assertEqual(executed, {f"E{SUPERPOWER + 1}"},
                         "and every one of those turns must still USE the encored move")

    def test_pp_comes_off_the_move_used_and_not_the_one_chosen(self):
        """`BattleControllerPlayer_DecrementPP` looks the slot up from `moveTemp`, the move
        actually used (battle_controller_player.c:2271) [verified]."""
        for seed in range(0x1000, 0x1040):
            state = _state(target=_titan(last_move_slot=SUPERPOWER), seed=seed)
            before = state.target.pp
            state = simulate_turn(state, Action.MOVE_1, _config())
            spent = [i for i, (a, b) in enumerate(zip(before, state.target.pp)) if a != b]
            with self.subTest(seed=seed):
                self.assertEqual(spent, [SUPERPOWER], state.target.pp)

    def test_the_turn_ORDER_still_reads_the_move_that_was_CHOSEN(self):
        """`CalcTurnOrder` runs before the override and reads the priority of the move in
        `moveSlot` (`BattleSystem_CompareBattlerSpeed`, battle_lib.c:1188-1300) [verified]. None
        of the titan's four moves has a priority of its own, so this is a guard on the shape of
        the fix rather than a live case: the override must not reach `_we_move_first`."""
        body = _sim_source("simulate_turn")
        order = body.index("_we_move_first(new, action, target_slot)")
        override = body.index("acting_slot = new.target.encored_slot")
        self.assertLess(order, override)

    def test_a_struggling_target_is_not_overridden(self):
        """Struggle is the ROM's FIRST branch, above the Encore one -- and it is reachable the
        other way round in principle, since `CheckInvalidMoves` marks a 0-PP encored slot invalid
        too."""
        out_of_pp = _titan(encored_slot=SUPERPOWER, encored_turns=3, pp=(0, 0, 0, 0))
        self.assertEqual(out_of_pp.usable_slots(), ())
        state = _state(target=out_of_pp)
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn(f"E{tok.STRUGGLE_SLOT + 1}", _rendered(state))

    def test_the_later_turns_were_right_all_along(self):
        """The regression guard. Selection narrows to the encored slot from the turn after, so
        those turns never depended on the override -- and must not start to."""
        state = _state(target=_titan(encored_slot=CURSE, encored_turns=4))
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn(f"E{CURSE + 1}", _rendered(state))


class TestTheWearOffToken(unittest.TestCase):
    def test_it_renders_for_either_side_and_validates(self):
        self.assertEqual(tok.encore_ended_token("target"), "Ne")
        self.assertEqual(tok.encore_ended_token("ours"), "Nm")
        with self.assertRaises(ValueError):
            tok.encore_ended_token("theirs")
        self.assertEqual(tok.validate_turn(["M4", "E1h", "Ne", "HP120"]), [])
        self.assertTrue(tok.validate_turn(["Nx"]))      # not a wear-off

    def test_it_has_a_plain_language_form(self):
        self.assertEqual(
            tok.explain_turn(["Ne"], target="Regirock", ours="Quagsire"),
            ["Regirock's Encore ended"])
        self.assertEqual(
            tok.explain_turn(["Nm"], target="Regirock", ours="Quagsire"),
            ["Quagsire's Encore ended"])

    def test_it_carries_no_hp_requirement_of_its_own(self):
        """The lock coming off changes nothing but what the victim may select next turn."""
        self.assertFalse(tok.turn_requires_hp(["M4", "Ne"]))


class TestYawnFromOurSide(unittest.TestCase):
    def test_it_is_allowed_now_and_was_only_ever_missing_permission(self):
        self.assertIn(187, MODELLED_OUR_EFFECTS)
        self.assertIsNone(unselectable_reason(resolve_move("Yawn"), _titan()))

    def test_the_sleep_lands_at_the_end_of_the_turn_after(self):
        """A Yawn on turn T makes its victim drowsy, the counter reaches zero at the end of T+1,
        and the first turn it COSTS is T+2."""
        state = _state()
        state = simulate_turn(state, Action.MOVE_2, _config())
        self.assertEqual(state.target.drowsy_turns, 1)
        self.assertIs(state.target.status, Status.NONE)
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertEqual(state.target.drowsy_turns, 0)
        self.assertIs(state.target.status, Status.SLEEP)
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn("Eslp", _rendered(state))

    def test_the_duration_roll_is_spent_at_the_end_of_turn_rather_than_at_use(self):
        """`subscript_yawn.s` spends nothing; the `Random` is in `subscript_fall_asleep`, two
        turns later. So the Yawn turn is as cheap as any other accuracy-0 status move and the
        turn the sleep lands is one roll dearer."""
        _, outcome = execute_move(0x12345678, resolve_move("Yawn"), _quagsire(), _titan(),
                                  actor="M", slot=YAWN, field=None)
        self.assertEqual(outcome.rolls, 0)
        self.assertTrue(outcome.sets_drowsy)

    def test_it_is_the_one_sleep_a_clear_body_titan_cannot_dodge(self):
        """Accuracy 0, so there is no roll to lose -- and Clear Body guards stat stages, not
        status. The contrast worth having: every stat drop we aim at a titan is refused."""
        self.assertEqual(resolve_move("Yawn").accuracy, 0)
        state = _state()
        state = simulate_turn(state, Action.MOVE_4, _config())        # Tail Whip
        self.assertEqual(state.target.def_stage, 0)                   # refused by Clear Body
        state = simulate_turn(state, Action.MOVE_2, _config())        # Yawn
        self.assertEqual(state.target.drowsy_turns, 1)                # not refused

    def test_every_refusal_the_rom_has_is_modelled(self):
        for label, victim in (("statused", _titan(status=Status.PARALYSIS)),
                              ("already drowsy", _titan(drowsy_turns=1)),
                              ("insomnia", _titan(ability="Insomnia")),
                              ("vital spirit", _titan(ability="Vital Spirit"))):
            with self.subTest(label):
                self.assertTrue(will_fail(resolve_move("Yawn"), victim))
        self.assertFalse(will_fail(resolve_move("Yawn"), _titan()))


class TestRecover(unittest.TestCase):
    def test_it_heals_half_our_max_hp_for_no_rolls(self):
        hurt = _quagsire(hp=40)
        _, outcome = execute_move(0x12345678, resolve_move("Recover"), hurt, _titan(),
                                  actor="M", slot=RECOVER, field=None)
        self.assertEqual(outcome.self_heal, hurt.max_hp // 2)
        self.assertEqual(outcome.rolls, 0)
        self.assertTrue(outcome.successful)

    def test_it_ignores_weather_where_synthesis_reads_it(self):
        """The only way the two differ: both end in `BATTLE_SUBSCRIPT_RECOVER_HP`, but Recover's
        caller divides max HP by two flat while `BtlCmd_WeatherHPRecovery` branches."""
        hurt = _quagsire(hp=40)
        state = replace(_state(ours=hurt), rain_turns=4)
        _, outcome = execute_move(0x12345678, resolve_move("Recover"), hurt, _titan(),
                                  actor="M", slot=RECOVER, field=state)
        self.assertEqual(outcome.self_heal, hurt.max_hp // 2)

    def test_at_full_hp_it_fails_and_the_turn_is_two_advances_cheaper(self):
        """``_036`` of `subscript_recover_hp.s`: "{0}'s HP is full!" plus
        `MOVE_STATUS_NO_MORE_WORK`, and nothing spent before it. **The one lever we have on a
        turn's advance count that needs no roll to go our way.**"""
        self.assertIn(EFFECT_RECOVER, FULL_HP_FAILS_EFFECTS)
        self.assertTrue(will_fail(resolve_move("Recover"), _titan(), actor=_quagsire()))
        self.assertFalse(will_fail(resolve_move("Recover"), _titan(), actor=_quagsire(hp=40)))
        healing = simulate_turn(_state(ours=_quagsire(hp=40), seed=1), Action.MOVE_3, _config())
        refused = simulate_turn(_state(ours=_quagsire(), seed=1), Action.MOVE_3, _config())
        self.assertEqual(healing.rng_offset - refused.rng_offset, 2)
        self.assertEqual(healing.ours.hp, 40 + _quagsire().max_hp // 2)


class TestStruggle(unittest.TestCase):
    def test_a_target_with_nothing_usable_struggles_rather_than_standing_still(self):
        """It used to stand still, which spent no roll, dealt no damage and applied no recoil --
        silently wrong rather than visibly unsupported."""
        state = _state(target=_titan(pp=(0, 0, 0, 0)))
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn("E0", _rendered(state))

    def test_the_selection_roll_is_still_not_spent(self):
        """The one thing the old model had right, and for the ROM's own reason: a battler with
        nothing valid never reaches move select at all
        (``STRUGGLING_ALL``, battle_controller_player.c:433-441)."""
        seed = 0xABCDEF01
        rng, slot = select_target_move(seed, _titan(pp=(0, 0, 0, 0)))
        self.assertEqual((rng, slot), (seed, None))

    def test_a_roamer_with_nothing_usable_spends_nothing_either(self):
        """The same ROM branch, and the four AI rolls live past it -- `TrainerAI_Main` is inside
        the move-select menu task. This row used to spend four. [derived, not captured:
        clayton-c3c4]"""
        seed = 0xABCDEF01
        choice = select_roamer_action(seed, _titan(pp=(0, 0, 0, 0)), trapped=True)
        self.assertEqual((choice.rng, choice.slot, choice.fled, choice.rolls),
                         (seed, None, False, 0))

    def test_it_costs_two_rolls_and_no_accuracy_roll(self):
        """`effect_script_0254.s` is `CalcCrit` then `CalcDamage`, and its accuracy is 0 -- so it
        is priced exactly like Faint Attack."""
        move = struggle_move()
        self.assertEqual((move.effect, move.accuracy), (EFFECT_STRUGGLE, 0))
        self.assertEqual(move_roll_cost(move), 2)
        _, outcome = execute_move(0x12345678, move, _titan(), _quagsire(),
                                  actor="E", slot=tok.STRUGGLE_SLOT, field=None)
        self.assertEqual(outcome.rolls, 2)

    def test_the_recoil_is_a_quarter_of_the_users_max_hp(self):
        """`subscript_struggle.s`, with no `Random` on the path. 97 max HP for a Lv30 titan, so
        24 a turn: four bring it to exactly 1 and the fifth faints it."""
        state = _state(target=_titan(pp=(0, 0, 0, 0)))
        self.assertEqual(state.target.max_hp, 97)
        expected = 97 // STRUGGLE_RECOIL_DIVISOR
        self.assertEqual(expected, 24)
        hp = [97]
        for _ in range(4):
            state = simulate_turn(state, Action.MOVE_4, _config())
            hp.append(state.target.hp)
        self.assertEqual(hp, [97, 73, 49, 25, 1])

    def test_it_is_typeless_so_a_ghost_is_not_immune(self):
        """`BattleSystem_CalcEffectiveness` and `BattleSystem_ApplyTypeMultipliers` both
        early-return on it (battle_lib.c:2686 and 2573), so there is no Normal-against-Ghost
        zero -- no type chart, and no STAB either."""
        ghost = Battler(name="Gengar", level=50, types=("Ghost", "Poison"),
                        stats=derive_species_stats("gengar", 50, "Timid", ivs=31),
                        moves=("Encore", "Yawn", "Recover", "Tail Whip"), pp=(5, 10, 10, 30))
        state = _state(ours=ghost, target=_titan(pp=(0, 0, 0, 0)))
        before = state.ours.hp
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertIn("E0h", _rendered(state))
        self.assertLess(state.ours.hp, before)

    def test_it_spends_no_pp_and_cannot_itself_be_encored(self):
        """There is no slot to spend from, and `Move_CanBeEncored` bans the effect -- which the
        slot sentinel gets right for free, since `Battler.move` answers None for it."""
        state = _state(target=_titan(pp=(0, 0, 0, 0)))
        state = simulate_turn(state, Action.MOVE_4, _config())
        self.assertEqual(state.target.pp, (0, 0, 0, 0))
        self.assertEqual(state.target.last_move_slot, tok.STRUGGLE_SLOT)
        self.assertTrue(will_fail(resolve_move("Encore"), state.target))


class TestTheSolverKnowsAboutAllOfIt(unittest.TestCase):
    def test_the_dominance_key_separates_states_that_disagree_about_the_lock(self):
        """Two states at one RNG offset that disagree about an Encore are not interchangeable:
        the lock decides WHICH move fires next turn, and two moves need not cost the same."""
        from claytonlib.battle_compass.solver import _dominance_key

        free = _state()
        locked = _state(target=_titan(encored_slot=CURSE, encored_turns=4))
        later = _state(target=_titan(encored_slot=CURSE, encored_turns=1))
        self.assertNotEqual(_dominance_key(free), _dominance_key(locked))
        self.assertNotEqual(_dominance_key(locked), _dominance_key(later))

    def test_it_separates_states_that_disagree_about_a_drowse_or_a_last_move(self):
        """Drowsy because the sleep's DURATION roll is spent at end of turn, and the last-move
        record because our own Encore's success is keyed on it -- and a failing Encore costs the
        turn two fewer advances than a landing one."""
        from claytonlib.battle_compass.solver import _dominance_key

        plain = _state()
        self.assertNotEqual(_dominance_key(plain),
                            _dominance_key(_state(target=_titan(drowsy_turns=1))))
        self.assertNotEqual(_dominance_key(plain),
                            _dominance_key(_state(target=_titan(last_move_slot=STOMP))))

    def test_all_four_moves_are_offered_to_the_interview(self):
        """`unselectable_reason` is the gate, and until now it refused three of these four."""
        for name in ("Encore", "Yawn", "Recover", "Tail Whip"):
            with self.subTest(name):
                self.assertIsNone(unselectable_reason(resolve_move(name), _titan()))

    def test_the_encore_question_is_asked_when_a_lock_could_end(self):
        """`encore_due` on the snapshot, computed over EVERY candidate rather than one -- the
        value of the answer is precisely that candidates which rolled different durations
        disagree about it."""
        from claytonlib.battle_compass.hunt_session import field_conditions

        running = field_conditions(_state(target=_titan(encored_slot=CURSE, encored_turns=2)))
        # Three, not two: the row reports the turns left INCLUDING this one, because the counter
        # reaches zero a tick before the lock comes off. See `hunt_session.ENCORE_ROW_LABEL`.
        self.assertIn({"name": "Encore", "turns": 3, "whose": "target"}, running)
        last = field_conditions(_state(target=_titan(encored_slot=CURSE, encored_turns=0)))
        self.assertIn({"name": "Encore", "turns": 1, "whose": "target"}, last)


class TestWhatDampWouldHaveBeenFor(unittest.TestCase):
    def test_explosion_is_blocked_for_no_rolls_but_nothing_here_has_it(self):
        """Kept as a note rather than modelled, because there is nothing to model against: Damp's
        branch in `effect_script_0007.s` jumps past `CalcCrit`/`CalcDamage` to a message, so a
        blocked Explosion costs only its accuracy roll -- and no configured encounter can use
        one. If a target ever gets Explosion, this is the test that has to grow a real body."""
        explosion = resolve_move("Explosion")
        self.assertEqual(explosion.effect, 7)
        self.assertEqual(explosion.accuracy, 100)
        for species in ("regirock", "regice", "registeel", "regigigas"):
            with self.subTest(species):
                self.assertNotIn("Explosion", moveset(species))


if __name__ == "__main__":
    unittest.main()
