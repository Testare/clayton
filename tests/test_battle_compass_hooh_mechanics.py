"""Ho-Oh Lv70's four mechanics: burn, Safeguard, Ancient Power, Punishment.

Every figure here is transcribed from the decompiled ROM rather than reasoned, and the ones that
came out differently from the planning note are called out at the point of use -- the note had
Punishment capped at 120 (it is 200) and claimed burn forces an HP token every turn (it does not).
"""
import unittest

from claytonlib.battle.damage import apply_stage, stage_multiplier
from claytonlib.battle.readiness import (
    PARALYSIS_SPEED_DIVISOR, speed_after_item, speed_checks, speed_warnings,
    target_speed_states,
)
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.sim import (
    BURN_ATTACK_DIVISOR, BURN_EFFECTS, BURN_TICK_DIVISOR, EFFECT_SAFEGUARD, HuntConfig,
    PUNISHMENT_MAX_POWER, SAFEGUARD_TURNS, burn_tick, effective_speed, punishment_power,
    simulate_turn, variable_base_power, will_fail,
)
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass.targets import moveset
from claytonlib.moves import resolve_move

HUNT = HuntConfig(target_catch_rate=3, target_has_pressure=True)


def _ours(hp=None, **kw):
    fields = dict(name="Smeargle", level=58, types=("Normal",),
                  stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                  moves=("False Swipe", "Thunder Wave", "Spore"), pp=(40, 20, 15),
                  party_slot=1, hp=hp)
    fields.update(kw)
    return Battler(**fields)


def _hooh(moves=None, **kw):
    mv = moves if moves is not None else moveset("ho-oh")
    fields = dict(name="Ho-Oh", level=70, types=tuple(species("ho-oh")["types"]),
                  stats=derive_species_stats("ho-oh", 70, "Hardy"), moves=mv,
                  pp=tuple(resolve_move(m).pp for m in mv), hp=1, ability="Pressure")
    fields.update(kw)
    return Battler(**fields)


def _rendered(state):
    return tok.render_turn(tok.normalise(state.log[-1]))


class TestBurnNeedsNoTokenOfItsOwn(unittest.TestCase):
    """The planning note claimed the residual forces an HP token on every subsequent turn, so
    that `turn_requires_hp` had to learn about it "or every turn becomes ungrammatical". Wrong:
    burn damage is not random.

    An HP token earns its place by reading back a damage roll or by catching a Phase 2 desync. A
    deterministic tick does neither -- its result is computable from the HP before it -- so
    demanding one would be making the player retype their HP every turn for nothing.
    """

    def test_the_tick_is_max_hp_over_eight_rounded_down(self):
        self.assertEqual(BURN_TICK_DIVISOR, 8)
        self.assertEqual(burn_tick(_ours()), 153 // 8)
        self.assertEqual(burn_tick(_ours()), 19)

    def test_it_never_rounds_down_to_nothing(self):
        tiny = _ours(stats={"hp": 4, "atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1})
        self.assertEqual(burn_tick(tiny), 1)

    def test_a_tick_only_turn_emits_no_hp_token(self):
        state = BattleState(ours=_ours(status=Status.BURN),
                            target=_hooh(moves=("Safeguard",)), rng=0x1234, phase=2)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        self.assertNotIn("HP", _rendered(nxt))
        self.assertEqual(nxt.ours.hp, 153 - 19)

    def test_it_costs_the_turn_no_advances(self):
        """Corroborated from the other direction by the fainting measurements: dying to an
        end-of-turn effect leaves the advance counts unchanged."""
        clean = BattleState(ours=_ours(), target=_hooh(moves=("Safeguard",)),
                            rng=0x1234, phase=2)
        burned = BattleState(ours=_ours(status=Status.BURN),
                             target=_hooh(moves=("Safeguard",)), rng=0x1234, phase=2)
        self.assertEqual(simulate_turn(clean, Action.MOVE_1, HUNT).rng_offset,
                         simulate_turn(burned, Action.MOVE_1, HUNT).rng_offset)

    def test_a_turn_that_also_took_a_hit_reports_the_total_including_the_tick(self):
        """Which is why nothing is lost: the one token still verifies the tick wherever there is
        anything else to verify."""
        state = BattleState(ours=_ours(status=Status.BURN),
                            target=_hooh(moves=("Ancient Power",)), rng=0x4A1B2C3D, phase=2)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        rendered = _rendered(nxt)
        if "E1h" in rendered or "E1!" in rendered:
            self.assertIn("HP", rendered)
            self.assertEqual(int(rendered[rendered.index("HP") + 2:][:3]), nxt.ours.hp)

    def test_a_tick_that_faints_us_still_reports_the_switch(self):
        """The `E3h~X2` shape: the move burned us, we survived it, and the tick finished the job.
        The tick emits no token, so without the X there would be nothing to show at all."""
        bench = (_ours(name="Magneton", party_slot=2),)
        state = BattleState(ours=_ours(hp=10, status=Status.BURN),
                            target=_hooh(moves=("Safeguard",)), rng=0x1234,
                            bench=bench, phase=2)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT, replacement=2)
        rendered = _rendered(nxt)
        self.assertIn("X2", rendered)
        self.assertEqual(tok.validate_turn(tok.tokenise(rendered)), [])
        self.assertEqual(nxt.ours.name, "Magneton")

    def test_the_interview_knows_a_tick_can_faint_us(self):
        """It emits no HP token, so the faint would otherwise have no question attached."""
        import pathlib

        html = (pathlib.Path(__file__).resolve().parent.parent
                / "app" / "web" / "index.html").read_text()
        body = html[html.index("function hrCanFaint(){"):]
        body = body[:body.index("\n}") + 2]
        self.assertIn("s.burn_tick > 0", body)

    def test_sacred_fire_is_what_applies_it(self):
        self.assertIn(resolve_move("Sacred Fire").effect, BURN_EFFECTS)
        self.assertIn(resolve_move("Fire Blast").effect, BURN_EFFECTS)
        self.assertEqual(resolve_move("Sacred Fire").effect_chance, 50)


class TestBurnHalvesOurPhysicalAttack(unittest.TestCase):
    """Which matters because we DO model the damage we deal -- it is how the run knows whether
    enough False Swipes have landed for the solver to start. The file claimed otherwise for a
    long time."""

    def test_the_divisor_is_two(self):
        self.assertEqual(BURN_ATTACK_DIVISOR, 2)

    def test_a_burned_false_swipe_takes_longer_to_reach_one_hp(self):
        healthy = BattleState(ours=_ours(), target=_hooh(moves=("Safeguard",), hp=250),
                              rng=0x1234, phase=1)
        burned = BattleState(ours=_ours(status=Status.BURN),
                             target=_hooh(moves=("Safeguard",), hp=250), rng=0x1234, phase=1)
        dealt_healthy = 250 - simulate_turn(healthy, Action.MOVE_1, HUNT).target.hp
        dealt_burned = 250 - simulate_turn(burned, Action.MOVE_1, HUNT).target.hp
        self.assertGreater(dealt_healthy, dealt_burned,
                           "burn did not reduce the damage we deal")


class TestSafeguard(unittest.TestCase):
    def test_it_blocks_our_status_moves(self):
        state = BattleState(ours=_ours(), target=_hooh(), rng=0x1234, phase=1)
        self.assertFalse(will_fail(resolve_move("Thunder Wave"), state.target, state))
        state.safeguard_turns = SAFEGUARD_TURNS
        self.assertTrue(will_fail(resolve_move("Thunder Wave"), state.target, state))
        self.assertTrue(will_fail(resolve_move("Spore"), state.target, state))

    def test_it_does_not_block_a_ball(self):
        """A ball is not a move, which is what keeps the target catchable through it."""
        state = BattleState(ours=_ours(), target=_hooh(moves=("Safeguard",)),
                            rng=0x1234, phase=2)
        state.safeguard_turns = SAFEGUARD_TURNS
        nxt = simulate_turn(state, Action.CAPTURE_BALL, HUNT)
        self.assertIn("C", _rendered(nxt))

    def test_using_it_sets_the_counter_and_a_second_one_fails(self):
        state = BattleState(ours=_ours(), target=_hooh(moves=("Safeguard",)),
                            rng=0x1234, phase=2)
        nxt = simulate_turn(state, Action.MOVE_1, HUNT)
        # One fewer than SAFEGUARD_TURNS, because durations are counted INCLUSIVE of the turn
        # they are set and then tick at end of turn -- the same convention rain and mist use
        # (verified for those against test1.jsonl). So it is up for five turns, this one
        # included.
        self.assertEqual(nxt.safeguard_turns, SAFEGUARD_TURNS - 1)
        self.assertGreater(nxt.safeguard_turns, 0)
        self.assertTrue(will_fail(resolve_move("Safeguard"), nxt.ours, nxt))

    def test_it_expires(self):
        state = BattleState(ours=_ours(), target=_hooh(moves=("Safeguard",)),
                            rng=0x1234, phase=2)
        state.safeguard_turns = 1
        nxt = simulate_turn(state, Action.CAPTURE_BALL, HUNT)
        self.assertEqual(nxt.safeguard_turns, 0)

    def test_the_dominance_key_separates_on_it(self):
        """Same argument rain and mist won: while it is up our status moves FAIL, and a failing
        move costs the turn two fewer advances."""
        from claytonlib.battle_compass.solver import _dominance_key

        a = BattleState(ours=_ours(), target=_hooh(), rng=1, phase=2)
        b = a.copy()
        b.safeguard_turns = 5
        self.assertNotEqual(_dominance_key(a), _dominance_key(b))

    def test_it_is_the_effect_id_the_sim_names(self):
        self.assertEqual(resolve_move("Safeguard").effect, EFFECT_SAFEGUARD)


class TestAncientPowerAndTheSpeedTie(unittest.TestCase):
    """The 10% raises EVERY stat of the attacker. Mostly harmless against a target held still --
    except Speed, because stages are applied before paralysis quarters it."""

    def test_six_stages_cancel_the_quartering_exactly(self):
        """And with no rounding loss: 40/10 is x4 and x4/4 is exact. That is the whole danger --
        a paralyzed target at +6 is back to full Speed and the sec 4.2 guarantee is gone."""
        base = 153
        states = target_speed_states(base, speed_stages=(0, 6))
        self.assertEqual(states["paralyzed"], base // PARALYSIS_SPEED_DIVISOR)
        self.assertEqual(states["paralyzed at +6 Spe"], base)

    def test_two_stages_do_not_restore_it(self):
        """The player asked directly: at +2 a paralyzed 153 is 76, not 153. Stages multiply by 2
        and paralysis divides by 4."""
        self.assertEqual(target_speed_states(153, speed_stages=(2,))["paralyzed at +2 Spe"], 76)

    def test_the_stage_is_applied_before_paralysis(self):
        """Order from the ROM's speed comparison. Each step truncates, so the two orders differ:
        14 at +1 is 21 then 5, where quartering first gives 3 then 4."""
        mon = _ours(stats={"hp": 1, "atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 14},
                    status=Status.PARALYSIS, speed_stage=1)
        self.assertEqual(effective_speed(mon), 14 * 15 // 10 // 4)
        self.assertNotEqual(14 * 15 // 10 // 4, 14 // 4 * 15 // 10)

    def test_a_proc_raises_every_stat(self):
        target = _hooh(moves=("Ancient Power",))
        state = BattleState(ours=_ours(), target=target, rng=0x1234, phase=2)
        for seed in range(0x1234, 0x1234 + 4000):
            nxt = simulate_turn(
                BattleState(ours=_ours(), target=target, rng=seed, phase=2),
                Action.MOVE_1, HUNT)
            if "~" in _rendered(nxt):
                self.assertEqual(nxt.target.speed_stage, 1)
                self.assertEqual(nxt.target.atk_stage, 1)
                self.assertEqual(nxt.target.spdef_stage, 1)
                return
        self.fail("no seed in the sweep procced Ancient Power")

    def test_the_readiness_check_enumerates_every_reachable_stage(self):
        """Not just the extremes: a tie can land at +2 and nowhere else."""
        stages = {c.target_speed_stage
                  for c in speed_checks({"X": 100}, 153, target_speed_stages=tuple(range(7)))}
        self.assertEqual(stages, set(range(7)))

    def test_a_tie_only_reachable_through_a_boost_is_still_warned_about(self):
        """Paralyzed 153 at +2 is 76, so a 76-Speed Pokemon of ours ties there and nowhere
        else -- and the warning says where the boost came from."""
        checks = speed_checks({"Slow": 76}, 153, include_our_paralysis=False,
                              target_speed_stages=tuple(range(7)))
        warnings = speed_warnings(checks)
        self.assertTrue(any("ties" in w for w in warnings), warnings)
        self.assertTrue(any("Ancient Power" in w for w in warnings), warnings)

    def test_an_unboosting_target_keeps_the_table_short(self):
        stages = {c.target_speed_stage for c in speed_checks({"X": 100}, 85)}
        self.assertEqual(stages, {0})


class TestPunishment(unittest.TestCase):
    """Power 1 in the table marks "work it out from state", not "unknown forever" -- and treating
    it as unmodellable kept it out of the danger floor, which is worse than imprecise: a floor
    that ignores one of the target's attacks is not a floor."""

    def test_the_formula_and_the_cap_are_the_roms(self):
        """60 + 20 per positive stage of its TARGET, capped at 200
        [BtlCmd_CalcPunishmentPower]. The planning note said 120."""
        self.assertEqual(PUNISHMENT_MAX_POWER, 200)
        self.assertEqual(punishment_power(_ours()), 60)
        self.assertEqual(punishment_power(_ours(spdef_stage=1)), 80)
        self.assertEqual(punishment_power(_ours(spdef_stage=6)), 180)

    def test_accuracy_and_evasion_count_too(self):
        """The ROM sums all eight stat-change entries, not just the five battle stats."""
        self.assertEqual(punishment_power(_ours(evasion_stage=2)), 100)

    def test_it_is_capped(self):
        maxed = _ours(atk_stage=6, def_stage=6, spatk_stage=6, spdef_stage=6,
                      speed_stage=6, accuracy_stage=6, evasion_stage=6)
        self.assertEqual(punishment_power(maxed), PUNISHMENT_MAX_POWER)

    def test_our_x_sp_def_feeds_the_move_hitting_us(self):
        """The interaction the planning note flagged: `choose_item` reaches for X Sp. Def as
        cheap filler, and every stage of it is +20 power on Punishment."""
        self.assertGreater(punishment_power(_ours(spdef_stage=2)),
                           punishment_power(_ours()))

    def test_only_punishment_gets_a_computed_power(self):
        self.assertIsNone(variable_base_power(resolve_move("Sacred Fire"), _ours()))
        self.assertEqual(variable_base_power(resolve_move("Punishment"), _ours()), 60)

    def test_it_reaches_the_danger_floor_now(self):
        from claytonlib.battle_compass.hunt_session import worst_incoming_hit

        ours = _ours()
        with_punishment = worst_incoming_hit(ours, _hooh(moves=("Punishment",), pp=(5,)))
        self.assertGreater(with_punishment, 0,
                           "Punishment was skipped, so the floor ignored one of its attacks")


class TestTheStageArithmeticMatchesTheRom(unittest.TestCase):
    """`sStatChangeTable` is written in tenths and the ROM multiplies then divides in integers.
    Ours holds the reduced ratios, which floors identically -- the float detour was the only
    thing in question, and it agreed everywhere reachable. Now it is exact by construction."""

    ROM = [(10, 40), (10, 35), (10, 30), (10, 25), (10, 20), (10, 15), (10, 10),
           (15, 10), (20, 10), (25, 10), (30, 10), (35, 10), (40, 10)]

    def test_it_agrees_with_the_roms_integer_form_everywhere_reachable(self):
        for index, (num, den) in enumerate(self.ROM):
            stage = index - 6
            for stat in range(1, 800):
                self.assertEqual(apply_stage(stat, stage), stat * num // den,
                                 f"stage {stage}, stat {stat}")

    def test_the_float_helper_is_still_there_for_margins(self):
        self.assertAlmostEqual(stage_multiplier(0), 1.0)
        self.assertAlmostEqual(stage_multiplier(6), 4.0)

    def test_a_stage_out_of_range_is_refused(self):
        with self.assertRaises(ValueError):
            apply_stage(100, 7)


class TestTheHeldItemReachesTheReadinessCheck(unittest.TestCase):
    """The summary screen does not include a Choice Scarf's boost, so the check that tells the
    player whether a tie is possible was reading the wrong number."""

    def test_the_item_is_applied(self):
        self.assertEqual(speed_after_item(124, "Choice Scarf"), 186)
        self.assertEqual(speed_after_item(124, "Macho Brace"), 62)
        self.assertEqual(speed_after_item(124, ""), 124)

    def test_the_simulator_and_the_check_share_one_implementation(self):
        mon = _ours(stats={"hp": 1, "atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 124},
                    held_item="Choice Scarf")
        self.assertEqual(effective_speed(mon), speed_after_item(124, "Choice Scarf"))

    def test_readiness_uses_the_boosted_figure(self):
        import tempfile

        from app.facade import Facade
        from app.store import FileStore

        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        mag = facade.add_party_pokemon(profile_id, {
            "name": "Magneton", "species": "magneton", "level": 70, "ability": "Sturdy",
            "stats": {"hp": 171, "atk": 80, "def": 159, "spa": 80, "spd": 80, "spe": 124},
            "moveset": ["Thunder Wave"], "max_pp": {"1": 20}})["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({
            "target": {"species": "ho-oh", "level": 70, "nature": "Hardy",
                       "ivs": {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}},
            "party": [{"pokemon_id": mag, "held_item": "Choice Scarf"}],
            "capture_ball": "Luxury Ball", "key_seed": 0x2D005C61,
            "initial_time": "2026-01-01T12:00:00", "vector_ms": 5000})
        facade.save_hunt(hunt)
        speeds = {c["our_speed"] for c in facade.hunt_readiness(hunt["id"])["speed"]["checks"]}
        self.assertIn(186, speeds, "the scarf's boost never reached the check")
        self.assertNotIn(124, speeds, "the unboosted figure is not what decides turn order")


if __name__ == "__main__":
    unittest.main()
