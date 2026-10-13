"""The party-side mechanics the Ho-Oh run needs, and the two directions each one can be wrong in.

Every gap here was *silent* rather than loud, which is what made them worth a test file of their
own. `execute_move` has no notion of an unrecognised effect: an unknown status move is treated as
having worked and changed nothing, so Flash, Screech and Charm all simulated as no-ops while
reporting success (clayton-957.10.2). Flash is the one that made this unsound rather than
imprecise -- `_effective_accuracy` already read `accuracy_stage`, so the stage never got set and
every later hit/miss was decided at the wrong threshold, spending the accuracy roll correctly and
getting the verdict wrong. That eliminates the true seed.

The figures are Ho-Oh Lv70 (SoulSilver) at 31 IVs and a neutral nature and the party in
notes/ho_oh_party.md, so a number changing here should mean the game changed, not the model.
"""
import unittest
from dataclasses import replace

from claytonlib.battle.damage import (
    SCREEN_TURNS, SCREEN_TURNS_LIGHT_CLAY, Attacker, Defender, damage_range, screen_turns,
)
from claytonlib.battle_compass.hunt_session import (
    reachable_attack_stages, worst_incoming_hit,
)
from claytonlib.battle_compass.sim import (
    HuntConfig, PRIMARY_STAT_DROPS, apply_stat_drop, execute_move, primary_stat_drop,
    simulate_turn, unsupported_our_moves, will_fail,
)
from claytonlib.battle_compass.solver import (
    SolverConfig, _legal_actions, can_faint_target, danger_floor_for,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.moves import resolve_move

HUNT = HuntConfig(target_catch_rate=3)

#: Ho-Oh Lv70, 31 IVs, neutral: 250 / 208 / 152 / 180 / 242 / 152.
HOOH_STATS = {"hp": 250, "atk": 208, "def": 152, "spa": 180, "spd": 242, "spe": 152}
HOOH_MOVES = ("Sacred Fire", "Punishment", "Ancient Power", "Safeguard")


def hooh(*, hp=250, status=Status.NONE, atk_stage=0, moves=HOOH_MOVES, pp=(5, 5, 5, 25)):
    mon = Battler(name="Ho-Oh", level=70, types=("Fire", "Flying"), stats=dict(HOOH_STATS),
                  moves=moves, pp=pp, ability="Pressure", status=status, atk_stage=atk_stage)
    return mon.with_hp(hp)


def ampharos(*, level=93, hp=311, moves=("Light Screen", "Flash", "Discharge", "Signal Beam"),
             pp=(30, 20, 15, 15), item="Leftovers", ability="Static"):
    mon = Battler(name="Ampharos", level=level, types=("Electric",),
                  stats={"hp": 311, "atk": 137, "def": 182, "spa": 336, "spd": 210, "spe": 143},
                  moves=moves, pp=pp, held_item=item, ability=ability, party_slot=2)
    return mon.with_hp(hp)


def smeargle(*, hp=153, moves=("False Swipe", "Spore"), pp=(40, 15)):
    mon = Battler(name="Smeargle", level=58, types=("Normal",),
                  stats={"hp": 153, "atk": 82, "def": 66, "spa": 20, "spd": 70, "spe": 160},
                  moves=moves, pp=pp, ability="Technician", party_slot=4)
    return mon.with_hp(hp)


def granbull(*, level=36, hp=144, ability="Intimidate"):
    mon = Battler(name="Granbull", level=level, types=("Normal",),
                  stats={"hp": 144, "atk": 153, "def": 100, "spa": 60, "spd": 64, "spe": 61},
                  moves=("Charm", "Bite"), pp=(20, 25), ability=ability, party_slot=3)
    return mon.with_hp(hp)


def state_with(ours, target, *, bench=(), rng=0x1234, phase=2, **kwargs):
    return BattleState(ours=ours, target=target, rng=rng, bench=tuple(bench), phase=phase,
                       **kwargs)


# --- clayton-957.10.2: our own stat-change moves -----------------------------------------------

class TestFlashActuallyLowersAccuracy(unittest.TestCase):
    """The unsound one. A dropped accuracy stage must reach the hit check."""

    def test_the_table_knows_flash(self):
        self.assertEqual(primary_stat_drop(resolve_move("Flash")), ("accuracy_stage", 1))

    def test_six_flashes_reach_minus_six_and_stop(self):
        mon = hooh()
        for _ in range(8):
            mon = apply_stat_drop(mon, ("accuracy_stage", 1))
        self.assertEqual(mon.accuracy_stage, -6, "the floor is -6, not unbounded")

    def test_a_flash_turn_moves_the_targets_stage(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS), phase=1)
        nxt = simulate_turn(state, Action.MOVE_2, HUNT)     # slot 1 is Flash
        self.assertEqual(nxt.target.accuracy_stage, -1,
                         "Flash reported success and changed nothing -- the original bug")

    def test_the_stage_changes_what_the_accuracy_check_decides(self):
        """-6 takes Sacred Fire from 95 to 31 and Punishment from unmissable to a coin flip."""
        from claytonlib.battle_compass.sim import _effective_accuracy

        self.assertEqual(_effective_accuracy(resolve_move("Sacred Fire"), 0), 95)
        self.assertEqual(_effective_accuracy(resolve_move("Sacred Fire"), -6), 31)
        self.assertEqual(_effective_accuracy(resolve_move("Punishment"), 0), 100)
        self.assertEqual(_effective_accuracy(resolve_move("Punishment"), -6), 33)

    def test_a_drop_at_the_floor_is_not_a_will_fail(self):
        """Clamped, not refused. Per the player's report it costs the same rolls at -6, so Flash
        stays usable filler -- unlike a second Rain Dance, which really does fail."""
        maxed = hooh()
        for _ in range(6):
            maxed = apply_stat_drop(maxed, ("accuracy_stage", 1))
        self.assertFalse(will_fail(resolve_move("Flash"), maxed, None, actor=ampharos()))


class TestScreechAndCharm(unittest.TestCase):
    def test_screech_is_two_stages_of_defence(self):
        self.assertEqual(primary_stat_drop(resolve_move("Screech")), ("def_stage", 2))

    def test_charm_is_two_stages_of_attack(self):
        self.assertEqual(primary_stat_drop(resolve_move("Charm")), ("atk_stage", 2))

    def test_leer_is_a_worse_screech_and_the_data_says_so(self):
        """Half the drop, same -6 floor, so three Screeches already reach the cap."""
        self.assertEqual(primary_stat_drop(resolve_move("Leer")), ("def_stage", 1))
        self.assertEqual(primary_stat_drop(resolve_move("Tail Whip")), ("def_stage", 1))

    def test_three_screeches_cut_false_swipe_from_ten_hits_to_three(self):
        """The reason Screech is worth two switch-ins: it is Smeargle's exposure, not its damage."""
        import math

        ours = smeargle()
        attacker = Attacker(level=58, attack=82, special_attack=20, types=("Normal",),
                            ability="Technician")
        counts = []
        for stage in (0, -6):
            target = Defender(defence=152, special_defence=242, types=("Fire", "Flying"),
                              defence_stage=stage)
            _, high = damage_range(resolve_move("False Swipe"), attacker, target)
            counts.append(math.ceil(249 / high))
        self.assertEqual(counts, [10, 3])
        self.assertEqual(ours.stats["atk"], 82)      # the spread the figures assume

    def test_charm_cannot_lower_the_floor_because_a_crit_discards_it(self):
        """The limit worth pinning: Charm changes the hit we plan around, never the floor."""
        ours = smeargle()
        self.assertEqual(worst_incoming_hit(ours, hooh()), 573, "a Sacred Fire crit at +0")
        self.assertEqual(worst_incoming_hit(ours, hooh(atk_stage=-5)), 573,
                         "a crit DISCARDS the lowered Attack, so the floor must not fall")
        # What it does move is the non-crit figure, which is the hit we actually plan around.
        attacker_plain = Attacker(level=70, attack=208, special_attack=180,
                                  types=("Fire", "Flying"), ability="Pressure")
        attacker_charmed = Attacker(level=70, attack=208, special_attack=180,
                                    types=("Fire", "Flying"), ability="Pressure",
                                    attack_stage=-5)
        defender = Defender(defence=66, special_defence=70, types=("Normal",))
        self.assertEqual(damage_range(resolve_move("Sacred Fire"), attacker_plain, defender)[1],
                         286)
        self.assertEqual(damage_range(resolve_move("Sacred Fire"), attacker_charmed, defender)[1],
                         82)


class TestMistStillGuardsEveryDrop(unittest.TestCase):
    """It used to guard only Sweet Scent's, because that was the only drop we had."""

    def test_mist_blocks_a_flash(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS), phase=1, mist_turns=5)
        nxt = simulate_turn(state, Action.MOVE_2, HUNT)
        self.assertEqual(nxt.target.accuracy_stage, 0)

    def test_a_mist_blocked_move_is_still_successful(self):
        """Verified on turn 15 of test1.jsonl: it spends the post-move advances anyway."""
        rng, outcome = execute_move(
            0x1234, resolve_move("Flash"), ampharos(), hooh(),
            actor="M", slot=1, field=state_with(ampharos(), hooh(), mist_turns=5))
        self.assertTrue(outcome.successful)
        self.assertTrue(outcome.blocked_by_mist)
        self.assertIsNone(outcome.stat_drop)


class TestOurMoveCoverageIsCheckedAtAll(unittest.TestCase):
    def test_the_whole_planned_party_is_covered(self):
        planned = ["False Swipe", "Spore", "Thunder Wave", "Screech", "Flash", "Light Screen",
                   "Charm", "Reflect", "Rain Dance", "Mean Look", "Discharge", "Signal Beam"]
        self.assertEqual(unsupported_our_moves(planned), ())

    def test_an_unmodelled_move_is_reported_rather_than_simulated_as_inert(self):
        """Asserted on the move and its effect id rather than on a phrase. This used to look for
        the literal "not modelled" and broke when the reason split damaging from status moves --
        the claim being made is that the move is REPORTED, not that it is reported in those
        words."""
        problems = unsupported_our_moves(["Belly Drum"])
        self.assertEqual(len(problems), 1)
        name, why = problems[0]
        self.assertEqual(name, "Belly Drum")
        self.assertIn(str(resolve_move("Belly Drum").effect), why)
        self.assertIn("doing nothing", why, "Belly Drum is a status move")

    def test_every_table_entry_resolves_to_a_real_effect(self):
        """Guards against a typo'd effect id silently covering nothing."""
        for effect in PRIMARY_STAT_DROPS:
            field, stages = PRIMARY_STAT_DROPS[effect]
            self.assertTrue(hasattr(hooh(), field), f"effect {effect} names no such stage")
            self.assertIn(stages, (1, 2))


# --- clayton-957.10.3: Intimidate ---------------------------------------------------------------

class TestIntimidate(unittest.TestCase):
    def test_a_switch_in_lowers_the_targets_attack(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS),
                           bench=(granbull(),), phase=1)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(nxt.target.atk_stage, -1)

    def test_it_costs_no_advances(self):
        """`sendOutState` case 3 makes no RNG call at all, so turn order and offsets are untouched."""
        plain = state_with(ampharos(), hooh(status=Status.PARALYSIS),
                           bench=(granbull(ability="Quick Feet"),), phase=1)
        intim = state_with(ampharos(), hooh(status=Status.PARALYSIS),
                           bench=(granbull(),), phase=1)
        a = simulate_turn(plain, Action.SWITCH, HUNT, bench_slot=0)
        b = simulate_turn(intim, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(a.rng_offset, b.rng_offset)
        self.assertEqual(a.rng, b.rng)

    def test_it_re_triggers_on_every_entry_and_stacks(self):
        """The shuttle. `intimidateFlag` is cleared per send-out, not per battle."""
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS),
                           bench=(granbull(),), phase=1)
        state = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)      # Granbull in, -1
        self.assertEqual(state.target.atk_stage, -1)
        back = [i for i, b in enumerate(state.bench) if b.name == "Ampharos"][0]
        state = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=back)   # Granbull out
        self.assertEqual(state.target.atk_stage, -1, "leaving must not re-apply or undo it")
        again = [i for i, b in enumerate(state.bench) if b.name == "Granbull"][0]
        state = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=again)  # and back in, -2
        self.assertEqual(state.target.atk_stage, -2)

    def test_a_replacement_after_a_faint_intimidates_too(self):
        """A faint replacement is a send-out, and `intimidateFlag` is cleared per send-out.

        Drives `_send_out` rather than a whole turn: reaching a faint needs the target to both
        pick an attack and land it, which a paralyzed Ho-Oh at full HP often does not do, and the
        send-out is the unit under test either way.
        """
        from claytonlib.battle_compass.sim import _send_out

        state = state_with(smeargle(hp=1), hooh(status=Status.PARALYSIS),
                           bench=(granbull(),), phase=2)
        state.ours = state.ours.with_hp(0)
        token = _send_out(state, replacement=3)
        self.assertEqual(state.ours.name, "Granbull")
        self.assertEqual(state.target.atk_stage, -1)
        self.assertTrue(token.startswith("X"))

    def test_a_non_intimidate_switch_in_changes_nothing(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS),
                           bench=(smeargle(),), phase=1)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(nxt.target.atk_stage, 0)

    def test_it_stops_at_the_floor(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS, atk_stage=-6),
                           bench=(granbull(),), phase=1)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(nxt.target.atk_stage, -6)


# --- clayton-957.10.4: the no-KO guard ----------------------------------------------------------

class TestTheSolverWillNotKillTheTarget(unittest.TestCase):
    def test_discharge_would_ko_ho_oh_from_full_hp(self):
        """Not a near miss -- 2x on Flying off 336 Sp. Atk is lethal before any chipping."""
        attacker = Attacker(level=93, attack=137, special_attack=336, types=("Electric",),
                            ability="Static")
        defender = Defender(defence=152, special_defence=242, types=("Fire", "Flying"))
        low, high = damage_range(resolve_move("Discharge"), attacker, defender)
        self.assertEqual((low, high), (222, 264))
        self.assertGreaterEqual(high, 250, "the top rolls kill a full-HP Ho-Oh")

    def test_every_damaging_move_is_refused_at_one_hp(self):
        ours, target = ampharos(), hooh(hp=1, status=Status.PARALYSIS)
        for name in ("Discharge", "Signal Beam"):
            self.assertTrue(can_faint_target(resolve_move(name), ours, target),
                            f"{name} kills at 1 HP and must not be offered")

    def test_status_moves_stay_available(self):
        ours, target = ampharos(), hooh(hp=1, status=Status.PARALYSIS)
        for name in ("Light Screen", "Flash"):
            self.assertFalse(can_faint_target(resolve_move(name), ours, target))

    def test_false_swipe_is_the_exception_and_that_is_why_smeargle_solves(self):
        ours, target = smeargle(), hooh(hp=1, status=Status.PARALYSIS)
        self.assertFalse(can_faint_target(resolve_move("False Swipe"), ours, target),
                         "False Swipe cannot reduce the target below 1 HP, by its own effect")

    def test_the_solver_offers_ampharos_only_its_status_moves(self):
        state = state_with(ampharos(), hooh(hp=1, status=Status.PARALYSIS))
        offered = {a for a, _, _ in _legal_actions(state, SolverConfig(), HUNT)
                   if a.move_slot is not None}
        self.assertEqual(offered, {Action.MOVE_1, Action.MOVE_2},
                         "Light Screen and Flash only; Discharge and Signal Beam both kill")

    def test_an_unpriceable_move_counts_as_dangerous(self):
        """A false positive costs one filler action; a false negative costs the hunt."""
        ours = smeargle(moves=("Seismic Toss",), pp=(20,))
        self.assertTrue(can_faint_target(resolve_move("Seismic Toss"), ours,
                                         hooh(hp=1, status=Status.PARALYSIS)))


# --- clayton-957.10.5: the danger floor ---------------------------------------------------------

class TestTheDangerFloorFollowsTheStages(unittest.TestCase):
    def test_the_floor_follows_the_targets_actual_stage(self):
        """178-210 at +0 but 264-312 at +1, against 311 HP. Reading the live stage is what makes
        the +1 case visible without pre-paying for a +6 that has not happened."""
        ours = ampharos()
        self.assertEqual(worst_incoming_hit(ours, hooh()), 210)
        at_plus_one = worst_incoming_hit(ours, hooh(atk_stage=1))
        self.assertEqual(at_plus_one, 312)
        self.assertGreater(at_plus_one, ours.max_hp,
                           "one Ancient Power proc is the difference for a Lv93 Ampharos")

    def test_the_floor_does_not_pre_pay_for_a_boost_that_has_not_happened(self):
        """Enumerating to +6 returns 828 against Ampharos's 311, which makes `in_danger`
        permanently true -- clayton-957.10.1's collapse, deepened rather than fixed. The gate
        reads the current stage; the enumeration is advice."""
        ours = ampharos()
        gate = worst_incoming_hit(ours, hooh())
        advice = worst_incoming_hit(ours, hooh(), any_reachable_stage=True)
        self.assertLess(gate, ours.max_hp, "the gate must be able to open at full HP")
        self.assertGreater(advice, ours.max_hp)
        self.assertEqual(advice, 828)

    def test_a_target_that_cannot_boost_enumerates_only_its_current_stage(self):
        no_boost = hooh(moves=("Sacred Fire", "Punishment", "Safeguard"), pp=(5, 5, 25))
        self.assertEqual(reachable_attack_stages(no_boost), (0,))

    def test_a_target_with_ancient_power_enumerates_upward(self):
        self.assertEqual(reachable_attack_stages(hooh()), (0, 1, 2, 3, 4, 5, 6))

    def test_it_starts_from_the_current_stage_rather_than_zero(self):
        self.assertEqual(reachable_attack_stages(hooh(atk_stage=2)), (2, 3, 4, 5, 6))

    def test_the_floor_is_read_from_the_state_not_the_config(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS))
        self.assertEqual(danger_floor_for(state, SolverConfig(danger_floor=0)),
                         worst_incoming_hit(state.ours, state.target, field=state))

    def test_a_configured_floor_is_a_lower_bound_not_an_override(self):
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS))
        self.assertEqual(danger_floor_for(state, SolverConfig(danger_floor=10_000)), 10_000)


# --- clayton-957.10.6: Static -------------------------------------------------------------------

class TestStaticSpendsARollOnlyWhenItCan(unittest.TestCase):
    def test_punishment_is_the_only_contact_move_ho_oh_has(self):
        contact = {name: resolve_move(name).makes_contact for name in HOOH_MOVES}
        self.assertEqual(contact, {"Sacred Fire": False, "Punishment": True,
                                   "Ancient Power": False, "Safeguard": False})

    def test_a_contact_hit_on_ampharos_costs_an_extra_roll(self):
        ours, static = ampharos(ability="Quick Feet"), ampharos(ability="Static")
        plain = execute_move(0x1234, resolve_move("Punishment"), hooh(), ours,
                             actor="E", slot=1)[1]
        with_static = execute_move(0x1234, resolve_move("Punishment"), hooh(), static,
                                   actor="E", slot=1)[1]
        self.assertEqual(with_static.rolls, plain.rolls + 1)

    def test_a_non_contact_hit_costs_nothing(self):
        ours, static = ampharos(ability="Quick Feet"), ampharos(ability="Static")
        plain = execute_move(0x1234, resolve_move("Sacred Fire"), hooh(), ours,
                             actor="E", slot=0)[1]
        with_static = execute_move(0x1234, resolve_move("Sacred Fire"), hooh(), static,
                                   actor="E", slot=0)[1]
        self.assertEqual(with_static.rolls, plain.rolls)

    def test_an_already_statused_attacker_costs_nothing(self):
        """The RNG call is the LAST term in the && chain, so C short-circuits before it. This is
        why the turn-1 Thunder Wave makes Static permanently dormant rather than merely harmless."""
        static = ampharos(ability="Static")
        unstatused = execute_move(0x1234, resolve_move("Punishment"), hooh(), static,
                                  actor="E", slot=1)[1]
        paralyzed = execute_move(0x1234, resolve_move("Punishment"),
                                 hooh(status=Status.PARALYSIS), static, actor="E", slot=1)[1]
        self.assertEqual(paralyzed.rolls, unstatused.rolls - 1)
        self.assertIsNone(paralyzed.attacker_status)

    def test_when_it_procs_the_target_is_paralyzed(self):
        """Searched over seeds rather than asserted on one, because which seed procs is the
        model's business and the state change is what this test is about."""
        static = ampharos(ability="Static")
        procced = False
        for seed in range(0x1000, 0x1000 + 400):
            outcome = execute_move(seed, resolve_move("Punishment"), hooh(), static,
                                   actor="E", slot=1)[1]
            if outcome.attacker_status is Status.PARALYSIS:
                procced = True
                break
        self.assertTrue(procced, "Static never procced in 400 seeds; the 30% gate is wrong")

    def test_a_procced_static_reaches_the_target_through_a_turn(self):
        static = ampharos(ability="Static")
        for seed in range(0x1000, 0x1000 + 4000):
            state = state_with(static, hooh(), rng=seed, phase=1)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            if nxt.target.status is Status.PARALYSIS:
                return
        self.fail("no seed in 4000 paralyzed Ho-Oh through Static")


# --- clayton-957.10.7: screens ------------------------------------------------------------------

class TestScreens(unittest.TestCase):
    def test_reflect_halves_physical_and_light_screen_does_not(self):
        attacker = Attacker(level=70, attack=208, special_attack=180, types=("Fire", "Flying"),
                            ability="Pressure")
        defender = Defender(defence=66, special_defence=70, types=("Normal",))
        sacred_fire = resolve_move("Sacred Fire")
        self.assertEqual(damage_range(sacred_fire, attacker, defender)[1], 286)
        self.assertEqual(damage_range(sacred_fire, attacker, defender, reflect=True)[1], 144)
        self.assertEqual(
            damage_range(sacred_fire, attacker, defender, light_screen=True)[1], 286,
            "Sacred Fire is PHYSICAL -- this is the fact the whole party plan turned on")

    def test_light_screen_halves_ancient_power(self):
        attacker = Attacker(level=70, attack=208, special_attack=180, types=("Fire", "Flying"),
                            ability="Pressure")
        defender = Defender(defence=66, special_defence=70, types=("Normal",))
        move = resolve_move("Ancient Power")
        self.assertEqual(damage_range(move, attacker, defender)[1], 94)
        self.assertEqual(damage_range(move, attacker, defender, light_screen=True)[1], 48)

    def test_a_crit_bypasses_both(self):
        attacker = Attacker(level=70, attack=208, special_attack=180, types=("Fire", "Flying"),
                            ability="Pressure")
        defender = Defender(defence=66, special_defence=70, types=("Normal",))
        for move, kwargs in ((resolve_move("Sacred Fire"), {"reflect": True}),
                             (resolve_move("Ancient Power"), {"light_screen": True})):
            bare = damage_range(move, attacker, defender, critical=True)
            screened = damage_range(move, attacker, defender, critical=True, **kwargs)
            self.assertEqual(bare, screened, f"{move.name}: crit must ignore the screen")

    def test_light_clay_extends_it(self):
        self.assertEqual(screen_turns(""), SCREEN_TURNS)
        self.assertEqual(screen_turns("Light Clay"), SCREEN_TURNS_LIGHT_CLAY)
        self.assertEqual(screen_turns("  LIGHT CLAY "), SCREEN_TURNS_LIGHT_CLAY)

    def test_setting_one_puts_it_on_the_state_for_the_right_number_of_turns(self):
        state = state_with(ampharos(item="Light Clay"), hooh(status=Status.PARALYSIS), phase=1)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)       # slot 0 is Light Screen
        self.assertEqual(nxt.light_screen_turns, SCREEN_TURNS_LIGHT_CLAY - 1,
                         "set this turn, then ticked once at end of turn")

    def test_a_second_screen_fails(self):
        """The half that bites even with the halving unimplemented: a failed move costs the turn
        two fewer advances, which is the bug that desynchronised test1.jsonl at turn 3."""
        field = state_with(ampharos(), hooh(), light_screen_turns=3)
        self.assertTrue(will_fail(resolve_move("Light Screen"), hooh(), field,
                                  actor=ampharos()))
        self.assertFalse(will_fail(resolve_move("Reflect"), hooh(), field, actor=ampharos()))

    def test_a_second_screen_costs_fewer_advances_than_the_first(self):
        fresh = state_with(ampharos(), hooh(status=Status.PARALYSIS), phase=1)
        held = state_with(ampharos(), hooh(status=Status.PARALYSIS), phase=1,
                          light_screen_turns=3)
        first = simulate_turn(fresh, Action.MOVE_1, HUNT)
        second = simulate_turn(held, Action.MOVE_1, HUNT)
        self.assertLess(second.rng_offset, first.rng_offset)

    def test_a_screen_survives_our_switches(self):
        """A SIDE condition in the ROM, not a battler one -- Magneton sets it, Smeargle keeps it."""
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS),
                           bench=(smeargle(),), phase=1, reflect_turns=5)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(nxt.ours.name, "Smeargle")
        self.assertEqual(nxt.reflect_turns, 4, "ticked, not cleared")

    def test_our_screen_does_not_reduce_damage_we_deal(self):
        """It is our side's. A screen of ours must not blunt our own False Swipe."""
        shielded = state_with(smeargle(), hooh(status=Status.PARALYSIS), phase=1,
                              reflect_turns=5)
        plain = state_with(smeargle(), hooh(status=Status.PARALYSIS), phase=1)
        a = simulate_turn(shielded, Action.MOVE_1, HUNT)
        b = simulate_turn(plain, Action.MOVE_1, HUNT)
        self.assertEqual(a.target.hp, b.target.hp)


if __name__ == "__main__":
    unittest.main()


# --- the two support slots: Natu (the Synchronize lead) and Chatot ------------------------------

def natu(*, level=12, hp=38, moves=("Peck", "Leer"), pp=(35, 30), ability="Synchronize"):
    mon = Battler(name="Natu", level=level, types=("Psychic", "Flying"),
                  stats={"hp": 38, "atk": 23, "def": 21, "spa": 28, "spd": 21, "spe": 28},
                  moves=moves, pp=pp, ability=ability, party_slot=1)
    return mon.with_hp(hp)


def chatot(*, level=20, hp=62, moves=("Growl", "Sing"), pp=(40, 15), ability="Keen Eye"):
    mon = Battler(name="Chatot", level=level, types=("Normal", "Flying"),
                  stats={"hp": 62, "atk": 34, "def": 26, "spa": 44, "spd": 25, "spe": 44},
                  moves=moves, pp=pp, ability=ability, party_slot=6)
    return mon.with_hp(hp)


class TestTheSupportSlotsAreConfigurable(unittest.TestCase):
    """Both would have made a hunt RAISE, not merely lose a warning.

    `facade._battlers_for` resolves our own party's TYPES through
    `battle.stats.species(pokemon.species)["types"]` -- our stats are entered off the summary
    screen but our types are not -- and that call raises KeyError for a species absent from
    `base_stats.json`. Natu and Chatot were both absent, so configuring either into the party
    broke starting the run.
    """

    def test_the_whole_party_resolves(self):
        from claytonlib.battle.stats import species

        for name in ("natu", "chatot", "magneton", "ampharos", "granbull", "smeargle",
                     "gyarados"):
            info = species(name)
            self.assertTrue(1 <= len(info["types"]) <= 2, name)
            self.assertNotIn("Fairy", info["types"], f"{name}: Fairy does not exist in Gen 4")

    def test_granbull_is_normal_not_fairy(self):
        """The reason these came from the ROM rather than PokeAPI: Granbull became Fairy in Gen 6,
        so a fetched entry would be wrong in a way that silently changes every damage figure."""
        from claytonlib.battle.stats import species

        self.assertEqual(species("granbull")["types"], ["Normal"])
        self.assertEqual(species("natu")["types"], ["Psychic", "Flying"])
        self.assertEqual(species("chatot")["types"], ["Normal", "Flying"])

    def test_their_abilities_are_inert_against_this_target(self):
        """Neither support slot needs ability modelling, and that is worth asserting rather than
        assuming -- it is the only reason they can be dropped into the party for free.

        Natu is Synchronize, which bounces a status back to the attacker: `TrySyncronizeStatus`
        makes no RNG call, and the only status Ho-Oh can inflict is burn, to which a Fire-type is
        immune. Early Bird halves sleep, and nothing here sleeps us. Chatot is Keen Eye (blocks
        accuracy drops, which Ho-Oh has none of) or Tangled Feet (evasion while confused, and
        nothing in the moveset confuses).
        """
        from claytonlib.battle_compass.sim import ABILITY_INTIMIDATE, ABILITY_STATIC

        for mon in (natu(), chatot(), natu(ability="Early Bird"),
                    chatot(ability="Tangled Feet")):
            ability = mon.ability.strip().lower()
            self.assertNotIn(ability, {ABILITY_INTIMIDATE, ABILITY_STATIC})

    def test_a_moveless_bench_member_is_structural(self):
        """Chatot is there to reach the frame, to be revived from, and as a free-switch token --
        so it may carry no moves the solver can use at all."""
        empty = chatot(moves=(), pp=())
        self.assertEqual(empty.usable_slots(), ())
        self.assertIsNone(empty.move(0))

    def test_a_faint_replacement_enters_without_being_hit(self):
        """Why the Chatot/Natu shuffle gets Magneton in safely.

        `_send_out` runs at the very END of the turn, after both sides have acted, so the
        replacement skips that turn's attack entirely. Magneton dies to any Sacred Fire from full
        HP (240 against 171), so this is the difference between a guaranteed Thunder Wave and a
        coin flip on Ho-Oh's move choice.
        """
        from claytonlib.battle_compass.sim import _send_out

        magneton = Battler(
            name="Magneton", level=70, types=("Electric", "Steel"),
            stats={"hp": 171, "atk": 92, "def": 159, "spa": 194, "spd": 110, "spe": 124},
            moves=("Thunder Wave", "Screech"), pp=(20, 40), held_item="Choice Scarf",
            party_slot=2)
        state = state_with(chatot(hp=1), hooh(), bench=(magneton,), phase=1)
        state.ours = state.ours.with_hp(0)
        _send_out(state, replacement=2)
        self.assertEqual(state.ours.name, "Magneton")
        self.assertEqual(state.ours.hp, state.ours.max_hp, "it came in untouched")


class TestChatotsGrowlAndSing(unittest.TestCase):
    def test_growl_is_already_covered_and_lowers_attack(self):
        self.assertEqual(primary_stat_drop(resolve_move("Growl")), ("atk_stage", 1))
        state = state_with(chatot(), hooh(status=Status.PARALYSIS), phase=1)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        self.assertEqual(nxt.target.atk_stage, -1)

    def test_growl_stacks_with_intimidate_and_charm_toward_the_same_floor(self):
        mon = hooh()
        for drop in (("atk_stage", 1), ("atk_stage", 2), ("atk_stage", 2), ("atk_stage", 1)):
            mon = apply_stat_drop(mon, drop)
        self.assertEqual(mon.atk_stage, -6)

    def test_sing_applies_sleep_and_rolls_its_duration(self):
        from claytonlib.battle_compass.sim import status_applied_by

        self.assertIs(status_applied_by(resolve_move("Sing")), Status.SLEEP)
        for seed in range(0x2000, 0x2000 + 600):
            _, outcome = execute_move(seed, resolve_move("Sing"), chatot(), hooh(),
                                      actor="M", slot=1)
            if outcome.applied_status is Status.SLEEP:
                self.assertTrue(2 <= outcome.sleep_turns <= 5)
                return
        self.fail("Sing never connected in 600 seeds")

    def test_sing_against_a_paralyzed_ho_oh_fails_but_still_rolls_accuracy(self):
        """Which is exactly what makes it useful: a free information probe.

        A status move against an already-statused target always fails, and the ROM checks
        accuracy BEFORE reporting the failure. So Sing spends its accuracy roll either way, and
        at 55 accuracy that roll is the sharpest separator of RTC-second sibling seeds there is
        (notes/seed_separation.md: ~49.5% disagreement, against 0% for a 100-accuracy move).
        Ho-Oh's own moveset offers nothing comparable -- Sacred Fire is 95 but it picks that only
        one turn in four, whereas Sing is a probe we choose.
        """
        paralyzed = hooh(status=Status.PARALYSIS)
        self.assertTrue(will_fail(resolve_move("Sing"), paralyzed, None, actor=chatot()))
        _, outcome = execute_move(0x1234, resolve_move("Sing"), chatot(), paralyzed,
                                  actor="M", slot=1)
        self.assertFalse(outcome.successful)
        self.assertEqual(outcome.rolls, 1, "the accuracy roll is still spent")

    def test_safeguard_blocks_sing_outright(self):
        field = state_with(chatot(), hooh(), safeguard_turns=5)
        self.assertTrue(will_fail(resolve_move("Sing"), hooh(), field, actor=chatot()))

    def test_both_of_chatots_useful_moves_pass_the_coverage_check(self):
        self.assertEqual(unsupported_our_moves(["Growl", "Sing"]), ())

    def test_feather_dance_is_charm_by_another_name(self):
        """Chatot learns it at L41, and it is the same effect id -- so a levelled Chatot could do
        the Granbull job from a slot the party already spends."""
        self.assertEqual(primary_stat_drop(resolve_move("Feather Dance")),
                         primary_stat_drop(resolve_move("Charm")))


class TestMovesThatWouldEndTheRun(unittest.TestCase):
    """A KO costs the Pokemon; a flee costs the encounter. Both are level-up moves here."""

    def test_teleport_and_roar_are_refused(self):
        from claytonlib.battle_compass.solver import ends_the_run

        for name in ("Teleport", "Roar", "Whirlwind"):
            self.assertTrue(ends_the_run(resolve_move(name)), name)

    def test_ordinary_moves_are_not(self):
        from claytonlib.battle_compass.solver import ends_the_run

        for name in ("Growl", "Sing", "False Swipe", "Flash", "Screech", "Charm", "Thunder Wave"):
            self.assertFalse(ends_the_run(resolve_move(name)), name)

    def test_the_solver_never_offers_natus_teleport(self):
        state = state_with(natu(moves=("Teleport", "Leer"), pp=(20, 30)),
                           hooh(hp=1, status=Status.PARALYSIS))
        offered = {a for a, _, _ in _legal_actions(state, SolverConfig(), HUNT)
                   if a.move_slot is not None}
        self.assertEqual(offered, {Action.MOVE_2},
                         "Leer only -- Teleport would flee and lose the encounter")

    def test_they_are_reported_as_unmodelled_too(self):
        """Belt and braces: the refusal stops the solver, the report tells the player."""
        problems = dict(unsupported_our_moves(["Teleport", "Roar"]))
        self.assertEqual(set(problems), {"Teleport", "Roar"})


class TestSafeguardDoesNotStopStaticInGenFour(unittest.TestCase):
    """The asymmetry the Safeguard contingency rests on, pinned so it is not "fixed" later.

    A status MOVE is refused while Safeguard is up -- `will_fail` has checked that since
    clayton-957.7, and it is why a Safeguard raised before Thunder Wave lands is a five-turn
    block. An ability-induced status is **not** refused in Gen 4: Static, Poison Point, Flame Body
    and Effect Spore all bypass Safeguard until Gen 5 closes the hole.

    **This is not verifiable from the decompilation**, and that is worth stating rather than
    implying. `SIDE_CONDITION_SAFEGUARD` appears in exactly four places in the C -- the move
    setting it, the move failing against itself, and its expiry -- so the blocking lives entirely
    in the battle scripts inside `NARC_a_0_0_1`, where `BATTLE_SUBSCRIPT_PARALYZE` cannot be read.
    `CheckAbilityEffectOnHit` itself has no Safeguard term, which is consistent with the Gen 4
    behaviour but does not prove it, because the subscript it dispatches to might.

    So this test pins a believed mechanic, not a measured one. It is load-bearing for the plan:
    if Thunder Wave is walled off by a Safeguard, a Punishment into Ampharos is the only paralysis
    route left.
    """

    def test_a_status_move_is_refused_through_safeguard(self):
        field = state_with(chatot(), hooh(), safeguard_turns=5)
        self.assertTrue(will_fail(resolve_move("Thunder Wave"), hooh(), field, actor=chatot()))
        self.assertTrue(will_fail(resolve_move("Sing"), hooh(), field, actor=chatot()))

    def test_static_paralyzes_through_safeguard(self):
        static = ampharos(ability="Static")
        for seed in range(0x1000, 0x1000 + 4000):
            state = state_with(static, hooh(), rng=seed, phase=1, safeguard_turns=5)
            nxt = simulate_turn(state, Action.MOVE_1, HUNT)
            if nxt.target.status is Status.PARALYSIS:
                return
        self.fail("Safeguard blocked Static; in Gen 4 it should not")

    def test_the_two_routes_disagree_on_purpose(self):
        """Stated as one assertion so the asymmetry reads as a decision, not an oversight."""
        field = state_with(ampharos(), hooh(), safeguard_turns=5)
        move_blocked = will_fail(resolve_move("Thunder Wave"), hooh(), field, actor=ampharos())
        _, outcome = execute_move(0x1234, resolve_move("Punishment"), hooh(),
                                  ampharos(ability="Static"), actor="E", slot=1, field=field)
        self.assertTrue(move_blocked, "a status MOVE is walled off")
        self.assertEqual(outcome.rolls, 4,
                         "and the Static roll is still spent -- the ability does not consult it")


# --- clayton-957.10.12: Leftovers ---------------------------------------------------------------

class TestLeftovers(unittest.TestCase):
    """Magneton and Ampharos hold one, and nothing in the code knew the item existed.

    +19/turn on Ampharos against a ~900-damage budget is not a rounding error: an unmodelled
    recovery makes the predicted HP low by max HP / 16 *every turn*, and the predicted HP is
    compared exactly, so the true seed is eliminated on the second turn of the run.
    """

    def test_the_figure_is_a_sixteenth_of_maximum(self):
        from claytonlib.battle_compass.sim import leftovers_tick
        self.assertEqual(leftovers_tick(ampharos(hp=300)), 19)       # 311 // 16

    def test_it_is_skipped_at_full_hp(self):
        """`CheckItemGradualHPRestore` gates on `hp < maxHp`: at full HP the item does nothing at
        all, which is a different statement from healing zero."""
        from claytonlib.battle_compass.sim import leftovers_tick
        self.assertEqual(leftovers_tick(ampharos(hp=311)), 0)

    def test_a_non_holder_recovers_nothing(self):
        from claytonlib.battle_compass.sim import leftovers_tick
        self.assertEqual(leftovers_tick(ampharos(hp=300, item="")), 0)
        self.assertEqual(leftovers_tick(ampharos(hp=300, item="Light Clay")), 0)

    def test_it_never_rounds_down_to_zero(self):
        """`DamageDivide` floors but returns the sign rather than 0, so a 10 HP Pokemon still
        gets 1 -- the same rule as the burn tick, from the same ROM function."""
        from claytonlib.battle_compass.sim import leftovers_tick
        tiny = Battler(name="Tiny", level=5, types=("Normal",),
                       stats={"hp": 10, "atk": 10, "def": 10, "spa": 10, "spd": 10, "spe": 10},
                       moves=("Tackle",), pp=(35,), held_item="Leftovers").with_hp(5)
        self.assertEqual(leftovers_tick(tiny), 1)

    def _turn(self, mon, *, rng=0x2468, status=Status.PARALYSIS):
        state = state_with(mon, hooh(status=status), rng=rng, phase=1)
        return simulate_turn(state, Action.MOVE_2, HUNT)              # Flash

    def _quiet_turn(self, mon, *, rng=0x2468):
        """A turn where NOTHING but the residual moves our HP: Ho-Oh is out of attacking PP, so
        Safeguard is all it can pick. The absolute HP figures below are then the arithmetic
        itself rather than the arithmetic plus a damage roll."""
        quiet = hooh(status=Status.PARALYSIS, pp=(0, 0, 0, 25))
        return simulate_turn(state_with(mon, quiet, rng=rng, phase=1), Action.MOVE_2, HUNT)

    def test_a_turn_ends_nineteen_higher_than_without_the_item(self):
        with_item = self._turn(ampharos(hp=200))
        without = self._turn(ampharos(hp=200, item=""))
        self.assertEqual(with_item.ours.hp - without.ours.hp, 19)

    def test_it_costs_no_advances(self):
        """Deterministic, like the burn tick -- so it must not move the stream by a single roll."""
        with_item = self._turn(ampharos(hp=200))
        without = self._turn(ampharos(hp=200, item=""))
        self.assertEqual(with_item.rng_offset, without.rng_offset)
        self.assertEqual(with_item.rng, without.rng)

    def test_the_recovery_lands_before_the_burn_tick(self):
        """`UpdateMonConditionState` orders LEFTOVERS_RECOVERY ahead of BURN, so a burned holder
        nets max HP / 16 instead of max HP / 8: 200 + 19 - 38."""
        burned = ampharos(hp=200).with_status(Status.BURN)
        self.assertEqual(self._quiet_turn(burned).ours.hp, 181)

    def test_a_burned_holder_cannot_end_a_turn_on_full_hp(self):
        """The consequence of the ordering, and the one the player will see: at full HP the
        recovery is skipped (hp < maxHp fails) and the tick lands anyway."""
        burned = ampharos(hp=311).with_status(Status.BURN)
        self.assertEqual(self._quiet_turn(burned).ours.hp, 311 - 38)

    def test_but_it_roughly_doubles_how_long_a_burn_takes(self):
        """-19/turn against -38, which is the reason to keep the item on a burned Pokemon."""
        mon = ampharos(hp=200).with_status(Status.BURN)
        bare = ampharos(hp=200, item="").with_status(Status.BURN)
        self.assertEqual(200 - self._quiet_turn(mon).ours.hp, 19)
        self.assertEqual(200 - self._quiet_turn(bare).ours.hp, 38)

    def test_a_turn_moved_only_by_the_item_emits_no_hp_token(self):
        """An HP token reads back a damage ROLL. A deterministic residual carries no information,
        and demanding one for a turn the player saw nothing random on would be unreportable."""
        from claytonlib.battle_compass import tokens as tok
        # Ho-Oh out of attacking PP: it can only Safeguard, which touches nothing of ours.
        quiet = hooh(status=Status.PARALYSIS, pp=(0, 0, 0, 25))
        state = state_with(ampharos(hp=200), quiet, rng=0x2468, phase=1)
        nxt = simulate_turn(state, Action.MOVE_2, HUNT)
        self.assertEqual(nxt.ours.hp, 219, "the recovery still happened")
        self.assertNotIn("HP", tok.render_turn(tok.normalise(nxt.log[-1])))

    def test_the_cap_is_the_missing_hp_not_the_figure(self):
        """Over-healing would predict an impossible HP, and then demand a token for it."""
        from claytonlib.battle_compass import tokens as tok
        quiet = hooh(status=Status.PARALYSIS, pp=(0, 0, 0, 25))
        state = state_with(ampharos(hp=306), quiet, rng=0x2468, phase=1)
        nxt = simulate_turn(state, Action.MOVE_2, HUNT)
        self.assertEqual(nxt.ours.hp, 311, "capped at maximum, not 306 + 19")
        self.assertNotIn("HP", tok.render_turn(tok.normalise(nxt.log[-1])))


# --- clayton-957.10.10: a secondary that inflicts a status --------------------------------------

class TestDischargeActuallyParalyzes(unittest.TestCase):
    """`MODELLED_OUR_EFFECTS` listed effect 6 as modelled while nothing applied it.

    The roll was spent, so every advance count was right and the gap was invisible -- and what it
    dropped on the floor is the single most valuable thing that can happen in the run, since
    paralysis IS the Phase 2 precondition.
    """

    def test_the_effect_maps_to_a_status(self):
        from claytonlib.battle_compass.sim import secondary_status
        self.assertIs(secondary_status(resolve_move("Discharge")), Status.PARALYSIS)
        self.assertIs(secondary_status(resolve_move("Sacred Fire")), Status.BURN)
        self.assertIsNone(secondary_status(resolve_move("Ancient Power")))
        self.assertIsNone(secondary_status(resolve_move("Thunder Wave")),
                          "that is a PRIMARY effect -- see status_applied_by")

    def test_a_proc_paralyzes_the_target(self):
        state = state_with(ampharos(), hooh(), rng=0x100F, phase=1)
        nxt = simulate_turn(state, Action.MOVE_3, HUNT)               # Discharge
        self.assertIs(nxt.target.status, Status.PARALYSIS)

    def test_freeze_is_deliberately_not_in_the_table(self):
        """Freeze's turn-skipping is unmodelled, so inflicting one would predict a turn nothing
        could match. Guarded on both sides: no configured moveset has one either."""
        from claytonlib.battle_compass.sim import (
            MODELLED_OUR_EFFECTS, SECONDARY_STATUSES, unsupported_our_moves,
        )
        self.assertNotIn(Status.FREEZE, set(SECONDARY_STATUSES.values()))
        self.assertNotIn(5, MODELLED_OUR_EFFECTS)
        self.assertTrue(unsupported_our_moves(["Ice Beam"]))

    def test_safeguard_blocks_it(self):
        state = state_with(ampharos(), hooh(), rng=0x100F, phase=1, safeguard_turns=5)
        nxt = simulate_turn(state, Action.MOVE_3, HUNT)
        self.assertIs(nxt.target.status, Status.NONE)

    def test_sacred_fires_burn_still_lands_on_us(self):
        """The same code path from the other direction -- a regression guard on the refactor that
        replaced two hardcoded effect checks with one table."""
        state = state_with(ampharos(), hooh(status=Status.PARALYSIS), rng=0x1012, phase=1)
        nxt = simulate_turn(state, Action.MOVE_2, HUNT)
        self.assertIs(nxt.ours.status, Status.BURN)


class TestAnInvisibleProcIsNotTokenized(unittest.TestCase):
    """A secondary status that cannot land sets nothing AND says nothing.

    This one was live rather than theoretical. Sacred Fire procs at 50%, and the plan has it
    hitting an already-burned Ampharos for the rest of its 8 PP: the simulator claimed
    "Ampharos was burned!" on every one of those, so a player correctly reporting silence
    eliminated every candidate that procced -- the true seed included.
    """

    def _tokens(self, state, action):
        from claytonlib.battle_compass import tokens as tok
        nxt = simulate_turn(state, action, HUNT)
        return tok.render_turn(tok.normalise(nxt.log[-1])), nxt

    def test_a_burn_on_an_already_burned_pokemon_shows_nothing(self):
        burned = ampharos().with_status(Status.BURN)
        rendered, _ = self._tokens(
            state_with(burned, hooh(status=Status.PARALYSIS), rng=0x1012, phase=1), Action.MOVE_2)
        self.assertEqual(rendered, "M2E1hHP201")
        self.assertNotIn("~", rendered)

    def test_the_first_burn_still_does(self):
        """The contrast that makes it a suppression rather than a removal."""
        rendered, _ = self._tokens(
            state_with(ampharos(), hooh(status=Status.PARALYSIS), rng=0x1012, phase=1),
            Action.MOVE_2)
        self.assertIn("E1h~", rendered)

    def test_the_roll_is_still_spent(self):
        """Only the MARKER goes. Suppressing the advance would desynchronise the stream."""
        burned = ampharos().with_status(Status.BURN)
        hidden, after_hidden = self._tokens(
            state_with(burned, hooh(status=Status.PARALYSIS), rng=0x1012, phase=1), Action.MOVE_2)
        shown, after_shown = self._tokens(
            state_with(ampharos(), hooh(status=Status.PARALYSIS), rng=0x1012, phase=1),
            Action.MOVE_2)
        self.assertEqual(after_hidden.rng_offset, after_shown.rng_offset)
        self.assertEqual(after_hidden.rng, after_shown.rng)
        self.assertNotEqual(hidden, shown)

    def test_a_discharge_proc_on_an_already_paralyzed_target_shows_nothing(self):
        """The state the entire run is built on reaching, so this would have fired every turn."""
        rendered, _ = self._tokens(
            state_with(ampharos(), hooh(status=Status.PARALYSIS), rng=0x100F, phase=1),
            Action.MOVE_3)
        self.assertNotIn("~", rendered)

    def test_a_safeguard_blocked_proc_shows_nothing(self):
        """[believed, not verified] -- whether a Safeguard block prints a protection message is
        decided in NARC_a_0_0_1, which is not in the decompilation. Suppressed on the same
        reasoning as the rest: losing an observation costs information, inventing one costs the
        run."""
        rendered, nxt = self._tokens(
            state_with(ampharos(), hooh(), rng=0x1007, phase=1, safeguard_turns=5), Action.MOVE_3)
        self.assertIs(nxt.target.status, Status.NONE)
        self.assertNotIn("~", rendered)

    def test_ancient_powers_self_boost_is_untouched(self):
        """It raises the ATTACKER, so it is visible whatever the victim's state -- and it must
        keep its marker, since it is the proc that cancels an Intimidate."""
        from claytonlib.battle_compass import tokens as tok
        for seed in range(0x3000, 0x3000 + 4000):
            state = state_with(ampharos(), hooh(status=Status.PARALYSIS), rng=seed, phase=1)
            nxt = simulate_turn(state, Action.MOVE_2, HUNT)
            rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
            if "E3" in rendered and nxt.target.atk_stage > 0:
                self.assertIn("E3h~", rendered)
                return
        self.fail("no Ancient Power proc in 4,000 seeds")


# --- clayton-957.10.9: naming the secondary ----------------------------------------------------

class TestTheSecondaryIsDescribed(unittest.TestCase):
    """The interview has to say what it is asking about, and the page said "<ours>'s stat fell"
    for every secondary there is -- true of Suicune's Aurora Beam, wrong twice over on Ho-Oh."""

    def test_ancient_power_names_the_attacker(self):
        from claytonlib.battle_compass.sim import secondary_description
        side, clause = secondary_description(resolve_move("Ancient Power"))
        self.assertEqual(side, "attacker")
        self.assertIn("{who}", clause)
        self.assertIn("rose", clause)

    def test_sacred_fire_names_the_victim_and_says_burned(self):
        from claytonlib.battle_compass.sim import secondary_description
        side, clause = secondary_description(resolve_move("Sacred Fire"))
        self.assertEqual(side, "victim")
        self.assertIn("burned", clause)

    def test_the_suicune_wording_is_still_right_for_suicune(self):
        from claytonlib.battle_compass.sim import secondary_description
        self.assertEqual(secondary_description(resolve_move("Aurora Beam")),
                         ("victim", "{who}'s Attack fell"))
        self.assertEqual(secondary_description(resolve_move("Luster Purge")),
                         ("victim", "{who}'s Sp. Def fell"))

    def test_every_secondary_in_play_is_described(self):
        from claytonlib.battle_compass.sim import secondary_description
        for name in HOOH_MOVES + ("Discharge", "Signal Beam", "Air Slash", "Extrasensory",
                                  "Hydro Pump", "Aurora Beam", "Mist Ball", "Luster Purge"):
            move = resolve_move(name)
            if move.effect_chance:
                self.assertIsNotNone(secondary_description(move), name)

    def test_an_undescribed_effect_is_None_rather_than_a_guess(self):
        """None means "say something generic". The page falls back to a bare "Yes" -- vague beats
        a claim about something the game never said."""
        from claytonlib.battle_compass.sim import secondary_description
        self.assertIsNone(secondary_description(resolve_move("Thunder Wave")))


# --- clayton-957.10.14: a faint clears the status -----------------------------------------------

class TestFaintingClearsTheStatus(unittest.TestCase):
    """The only mismatch in 108 turns of emulator ground truth (notes/hooh_log_replay.md sec 3).

    Sacred Fire fainted Granbull and its 50% burn procced on the same roll. The token was right --
    `_visible_tokens` already knew a KO shows no secondary message -- but the STATE took the burn,
    the Revive brought it back still burned, and the simulator then ticked 20 HP a turn off a
    Pokemon the game was not burning. Three defects, each checked here.
    """

    def _state(self, ours, **kw):
        return state_with(ours, hooh(**kw), rng=0x1010, phase=1,
                          bench=(smeargle(),))

    def test_a_victim_the_move_fainted_takes_no_status(self):
        """Defect (a). The roll is spent and the status script never runs."""
        state = self._state(granbull(hp=20))
        nxt = simulate_turn(state, Action.MOVE_1, HUNT, replacement=4)
        self.assertTrue(nxt.faints, "the fixture seed must actually faint Granbull")
        down = [b for b in nxt.bench if b.name == "Granbull"][0]
        self.assertIs(down.status, Status.NONE)

    def test_fainting_clears_a_status_it_already_had(self):
        """Defect (b). Independent of (a): burned first, fainted later."""
        burned = granbull(hp=20).with_status(Status.BURN)
        nxt = simulate_turn(self._state(burned), Action.MOVE_1, HUNT, replacement=4)
        down = [b for b in nxt.bench if b.name == "Granbull"][0]
        self.assertEqual(down.hp, 0)
        self.assertIs(down.status, Status.NONE)

    def test_the_choke_point_is_with_hp(self):
        """So no path can hold a fainted-and-statused Battler, however it got there."""
        self.assertIs(granbull().with_status(Status.BURN).with_hp(0).status, Status.NONE)
        self.assertEqual(granbull().with_status(Status.SLEEP, sleep_turns=3)
                         .with_hp(0).sleep_turns, 0)

    def test_a_revive_brings_back_a_healthy_pokemon(self):
        """Defect (c), checked against a party member CONFIGURED as fainted and statused -- the
        one way to reach this state without going through `with_hp`."""
        down = replace(granbull(), hp=0, status=Status.BURN)
        state = state_with(chatot(), hooh(moves=("Safeguard",), pp=(25,)),
                           rng=0x1234, phase=1, bench=(down,))
        nxt = simulate_turn(state, Action.REVIVE, HUNT, bench_slot=0)
        self.assertEqual(nxt.bench[0].hp, 72)              # the fixture's 144 // 2
        self.assertIs(nxt.bench[0].status, Status.NONE)

    def test_a_survivable_sacred_fire_still_burns(self):
        """The regression that matters: suppressing the status on a KO must not suppress it on a
        hit the victim lives through. [verified: hooh2 turn 4 is exactly this turn]"""
        state = state_with(ampharos(), hooh(moves=("Sacred Fire",), pp=(5,)),
                           rng=0x1000, phase=1)
        nxt = simulate_turn(state, Action.MOVE_2, HUNT)
        self.assertIs(nxt.ours.status, Status.BURN)
        self.assertIn("~", "".join(nxt.log[-1]), "and it is still reported")

    def test_a_statused_target_is_unaffected_by_any_of_this(self):
        """Ho-Oh never faints -- the solver forbids it -- so its paralysis must survive
        everything above."""
        state = state_with(smeargle(), hooh(hp=1, status=Status.PARALYSIS), rng=0x1234)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        self.assertIs(nxt.target.status, Status.PARALYSIS)
        self.assertEqual(nxt.target.hp, 1)


# --- clayton-957.10.18: stat stages reset on send-out -------------------------------------------

class TestSendingOutResetsTheStages(unittest.TestCase):
    """A Pokemon arriving on the field gets a freshly built BattleMon, and the reset is in it:

        BattleSystem_GetBattleMon (src/battle/overlay_12_0224E4FC.c:75)
            if (!(ctx->battleStatus & BATTLE_STATUS_BATON_PASS))
                for (i = 0; i < 8; i++) statChanges[i] = 6;     // 6 is neutral

    Nothing reset them here, so a Pokemon that switched out at -1 Attack came back at -1. Not
    reachable against Ho-Oh -- nothing in its moveset touches our stats -- but Suicune's Aurora
    Beam drops our Attack, and a Smeargle that shuttles would then under-predict its own False
    Swipe damage for the rest of the run against an exactly-compared target HP.
    """

    def _carrying(self):
        return replace(smeargle(), atk_stage=-1, spdef_stage=-2, accuracy_stage=-3,
                       status=Status.BURN, party_slot=1)

    def test_the_helper_clears_all_seven(self):
        from claytonlib.battle_compass.sim import sent_out

        fresh = sent_out(replace(
            smeargle(), atk_stage=-1, def_stage=2, spatk_stage=-3, spdef_stage=4,
            speed_stage=-5, accuracy_stage=6, evasion_stage=-6))
        for field in ("atk_stage", "def_stage", "spatk_stage", "spdef_stage", "speed_stage",
                      "accuracy_stage", "evasion_stage"):
            self.assertEqual(getattr(fresh, field), 0, field)

    def test_a_voluntary_switch_in_arrives_neutral(self):
        state = state_with(chatot(), hooh(status=Status.PARALYSIS), rng=0x1234, phase=1,
                           bench=(self._carrying(),))
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(nxt.ours.name, "Smeargle")
        self.assertEqual((nxt.ours.atk_stage, nxt.ours.spdef_stage, nxt.ours.accuracy_stage),
                         (0, 0, 0))

    def test_a_post_faint_replacement_arrives_neutral_too(self):
        """The other send-out path, and the one the plan uses most."""
        state = state_with(chatot(hp=3), hooh(), rng=0x1010, phase=1,
                           bench=(replace(self._carrying(), party_slot=2),))
        nxt = simulate_turn(state, Action.MOVE_1, HUNT, replacement=2)
        self.assertTrue(nxt.faints, "the fixture seed must faint Chatot")
        self.assertEqual(nxt.ours.name, "Smeargle")
        self.assertEqual((nxt.ours.atk_stage, nxt.ours.accuracy_stage), (0, 0))

    def test_the_status_survives_the_switch(self):
        """The same ROM function reads status from the PARTY Pokemon's own byte, so this is the
        half that must NOT reset -- and it is why a revived Pokemon comes back clean."""
        state = state_with(chatot(), hooh(status=Status.PARALYSIS), rng=0x1234, phase=1,
                           bench=(self._carrying(),))
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertIs(nxt.ours.status, Status.BURN)

    def test_the_reset_is_on_the_way_IN_not_the_way_out(self):
        """Where the ROM puts it. A benched Pokemon's stages are simply never read, so this is
        about matching the game rather than about tidiness."""
        state = state_with(self._carrying(), hooh(status=Status.PARALYSIS), rng=0x1234, phase=1,
                           bench=(chatot(),))
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        benched = [b for b in nxt.bench if b.name == "Smeargle"][0]
        self.assertEqual(benched.atk_stage, -1, "still carried on the bench")
        back = simulate_turn(nxt, Action.SWITCH, HUNT,
                             bench_slot=[b.name for b in nxt.bench].index("Smeargle"))
        self.assertEqual(back.ours.atk_stage, 0, "and cleared when it returns")

    def test_the_target_is_untouched_by_any_of_it(self):
        """A wild Pokemon never switches, so six Flashes stay spent -- which is the whole reason
        the plan prefers stat drops to field conditions."""
        state = state_with(chatot(), hooh(status=Status.PARALYSIS, atk_stage=-5), rng=0x1234,
                           phase=1, bench=(smeargle(),))
        state.target = replace(state.target, accuracy_stage=-6, def_stage=-6)
        nxt = simulate_turn(state, Action.SWITCH, HUNT, bench_slot=0)
        self.assertEqual(nxt.target.accuracy_stage, -6)
        self.assertEqual(nxt.target.def_stage, -6)
