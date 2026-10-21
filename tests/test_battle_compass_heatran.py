"""Heatran Lv50 (Platinum, Stark Mountain), and the first target that fights our stat stages.

`StartLegendaryBattle SPECIES_HEATRAN, 50` (res/field/scripts/scripts_stark_mountain_room_3.s:83).
Catch rate 3, Fire/Steel, Flash Fire, base 91/90/106/77/130/106.

Three things make this target different in kind from the first five, and each has a section here:

* **Its drops are two stages at a time.** Metal Sound is -2 Sp. Def and Scary Face -2 Speed, where
  every earlier target's drops were one. Scary Face can flip turn order outright — and the
  no-speed-tie guarantee is what keeps ties out of the solver's search.
* **The danger floor was computed at stage 0 whatever had been done to us.** That is a pre-existing
  soundness bug (Latios's Luster Purge has had the same shape for longer), and Heatran is what
  makes it acute: at -2 Sp. Def its Lava Plume one-shots a full-HP Smeargle where at 0 it does not.
* **Flash Fire is about OUR party, not about the fight.** A Fire move thrown at it is absorbed AND
  raises its own Fire power by half, so the Lava Plume afterwards hits harder than anything
  predicted. Refused rather than approximated. The mirror is worth knowing too: Metal Sound is one
  of the twelve SOUND moves, so a Soundproof party member blocks it outright.

(clayton-6xu.6)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.hunt_session import (
    reachable_defensive_drops, survivability_warnings, worst_incoming_hit,
)
from claytonlib.battle_compass.sim import (
    MODELLED_TARGET_EFFECTS, PRIMARY_STAT_DROPS, SECONDARY_STAT_DROPS, HuntConfig, absorbs,
    can_miss, effective_speed, execute_move, opening_rng, primary_stat_drop, simulate_turn,
    soundproofed, unselectable_reason, unsupported_our_moves, will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    encounter_level, moveset, supported, target_ability, unsupported_moves,
)
from claytonlib.moves import resolve_move


def _heatran(**kwargs) -> Battler:
    moves = moveset("heatran")
    return replace(Battler(
        name="heatran", level=50, types=tuple(species("heatran")["types"]),
        stats=derive_species_stats("heatran", 50, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(name).pp for name in moves),
        ability=target_ability("heatran")), **kwargs)


def _ours(**kwargs) -> Battler:
    return replace(Battler(
        name="Smeargle", level=73, types=("Normal",),
        stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
        moves=("False Swipe", "Flash"), pp=(40, 20)), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestTheRow(unittest.TestCase):

    def test_the_moveset_is_the_last_four_learnable_at_fifty(self):
        """Metal Sound(25), Crunch(33), Scary Face(41), Lava Plume(49), in learn order."""
        self.assertEqual(moveset("heatran"),
                         ("Metal Sound", "Crunch", "Scary Face", "Lava Plume"))

    def test_the_level_is_fifty(self):
        self.assertEqual(encounter_level("heatran"), 50)

    def test_it_is_platinum_only(self):
        self.assertIn("heatran", supported("platinum"))
        self.assertNotIn("heatran", supported("heartgold"))
        self.assertNotIn("heatran", supported("soulsilver"))

    def test_the_ability_is_flash_fire(self):
        self.assertEqual(target_ability("heatran"), "Flash Fire")

    def test_nothing_in_the_set_is_unmodelled(self):
        self.assertEqual(unsupported_moves("heatran"), ((), None))

    def test_the_two_moves_the_level_window_pushes_out_were_the_dangerous_ones(self):
        """Fire Fang(17) is effect 273 and unmodelled -- it would have refused this target
        outright -- and Ancient Power(1) is the all-stats boost that makes Ho-Oh's Speed a
        problem. Both are learned before the four it keeps, so both are pushed out.
        """
        self.assertNotIn("Fire Fang", moveset("heatran"))
        self.assertNotIn("Ancient Power", moveset("heatran"))
        self.assertNotIn(resolve_move("Fire Fang").effect, MODELLED_TARGET_EFFECTS)

    def test_it_is_the_first_configured_target_with_a_gender(self):
        """50/50, where every other configured target is genderless. Nothing reads it: the Love
        Ball is the only mechanic that would, and Platinum has no apricorn balls."""
        self.assertFalse(species("heatran")["genderless"])
        for genderless in ("suicune", "lugia", "darkrai", "giratina-altered"):
            with self.subTest(genderless):
                self.assertTrue(species(genderless)["genderless"])


class TestTheTwoStageDrops(unittest.TestCase):

    def test_both_are_listed_as_modelled_for_a_target(self):
        for name in ("Metal Sound", "Scary Face"):
            with self.subTest(name):
                self.assertIn(resolve_move(name).effect, MODELLED_TARGET_EFFECTS)

    def test_metal_sound_takes_two_sp_def_stages(self):
        self.assertEqual(primary_stat_drop(resolve_move("Metal Sound")), ("spdef_stage", 2))

    def test_scary_face_takes_two_speed_stages(self):
        self.assertEqual(primary_stat_drop(resolve_move("Scary Face")), ("speed_stage", 2))

    def test_both_can_miss_which_is_what_separates_rtc_second_siblings(self):
        """Accuracy 85 and 90. A sub-100 move on the target's side resolves the second axis from
        its own turns, the way Lugia's Hydro Pump does and Suicune's set cannot
        (notes/seed_separation.md)."""
        self.assertTrue(can_miss(resolve_move("Metal Sound"), 0))
        self.assertTrue(can_miss(resolve_move("Scary Face"), 0))

    def test_the_drop_lands_on_us_when_the_target_uses_it(self):
        config = _config()
        state = BattleState(ours=_ours(), target=_heatran(pp=(20, 0, 0, 0)),
                            rng=opening_rng(0x0C0E02CA, config))
        state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(state.ours.spdef_stage, -2)
        self.assertEqual(state.target.spdef_stage, 0)       # not on itself

    def test_scary_face_can_flip_turn_order(self):
        """The headline, and the reason this target needed a careful read. Our lead outspeeds it
        2:1 and two Scary Faces put it in front -- after which the whole turn is a different
        shape, since who moves first decides what our move can still reach.
        """
        ours, target = _ours(), _heatran()
        self.assertGreater(effective_speed(ours), effective_speed(target))
        self.assertLess(effective_speed(replace(ours, speed_stage=-4)),
                        effective_speed(target))

    def test_the_drops_are_permanent(self):
        """A wild target never switches out and neither do we on a one-Pokemon plan, so the ROM's
        stat reset never runs -- which is what makes a second Scary Face worth as much as the
        first."""
        config = _config()
        state = BattleState(ours=_ours(), target=_heatran(pp=(0, 0, 20, 0)),
                            rng=opening_rng(0x0C0E02CA, config))
        for _ in range(3):
            state = simulate_turn(state, Action.MOVE_1, config)
        self.assertLessEqual(state.ours.speed_stage, -4)


class TestCrunchAndTheSecondaryTable(unittest.TestCase):

    def test_crunch_drops_DEFENCE_in_gen_four(self):
        """It dropped Sp. Def in Gen 3, which is exactly the kind of thing a modern reference gets
        wrong for this project. `effect_script_0069.s` loads
        `MOVE_SUBSCRIPT_PTR_DEFENSE_DOWN_1_STAGE`.
        """
        self.assertEqual(SECONDARY_STAT_DROPS[resolve_move("Crunch").effect], ("def_stage", 1))

    def test_the_secondary_is_a_table_rather_than_a_branch_per_effect(self):
        """It was three hand-written branches, two of which only existed on the target's half of
        the turn. Crunch would have been a fourth."""
        for move, expected in (("Aurora Beam", ("atk_stage", 1)),
                               ("Crunch", ("def_stage", 1)),
                               ("Mist Ball", ("spatk_stage", 1)),
                               ("Luster Purge", ("spdef_stage", 1))):
            with self.subTest(move):
                self.assertEqual(SECONDARY_STAT_DROPS[resolve_move(move).effect], expected)

    def test_a_secondary_drop_is_not_also_a_primary_one(self):
        """The two tables must not overlap: a secondary rides on `outcome.secondary` and a primary
        lands whenever the move succeeds, so an effect in both would be applied twice."""
        self.assertEqual(set(SECONDARY_STAT_DROPS) & set(PRIMARY_STAT_DROPS), set())

    def test_it_lands_on_us_when_the_proc_fires(self):
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0240):
            state = BattleState(ours=_ours(), target=_heatran(pp=(0, 20, 0, 0)),
                                rng=opening_rng(seed, config))
            state = simulate_turn(state, Action.MOVE_1, config)
            if state.ours.def_stage < 0:
                self.assertEqual(state.ours.def_stage, -1)
                self.assertEqual(state.target.def_stage, 0)
                return
        self.fail("no Crunch proc in 64 seeds, which a 20% secondary should produce")

    def test_our_own_secondary_drop_now_lands_too(self):
        """The mirror did not exist: a secondary drop from one of OUR moves was applied nowhere.
        Nothing in a planned party has one, so it cost nothing -- but the two halves of a turn are
        meant to differ only in which side they read.
        """
        us = _ours(moves=("Crunch",), pp=(15,))
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0240):
            state = BattleState(ours=us, target=_heatran(pp=(0, 0, 0, 0)),
                                rng=opening_rng(seed, config))
            state = simulate_turn(state, Action.MOVE_1, config)
            if state.target.def_stage < 0:
                self.assertEqual(state.target.def_stage, -1)
                return
        self.fail("no Crunch proc of ours in 64 seeds")


class TestFlashFire(unittest.TestCase):

    def test_a_fire_move_of_ours_is_refused_rather_than_absorbed(self):
        """Absorbing it also raises Heatran's own Fire power by half, so the Lava Plume afterwards
        hits harder than anything predicted. Unsound, not imprecise."""
        flamethrower = resolve_move("Flamethrower")
        self.assertTrue(absorbs(_heatran(), flamethrower))
        reason = unselectable_reason(flamethrower, _heatran())
        self.assertIsNotNone(reason)
        self.assertIn("Flash Fire", reason)

    def test_a_non_fire_move_is_unaffected(self):
        self.assertIsNone(unselectable_reason(resolve_move("False Swipe"), _heatran()))
        self.assertFalse(absorbs(_heatran(), resolve_move("False Swipe")))

    def test_a_status_fire_move_is_not_absorbed_by_this_rule(self):
        """`absorbs` requires power, as the ROM's check does -- Will-O-Wisp is handled by a named
        exception there, and nothing in any party has one, so this stays the narrow rule."""
        self.assertFalse(absorbs(_heatran(), resolve_move("Sunny Day")))

    def test_the_configure_page_reports_it_before_the_run(self):
        problems = unsupported_our_moves(("Flamethrower", "False Swipe"), _heatran())
        self.assertEqual([name for name, _ in problems], ["Flamethrower"])

    def test_with_no_target_given_nothing_is_refused_for_absorption(self):
        """`unsupported_our_moves` is called on a half-configured hunt, where the target may not
        resolve to a row yet. No target means no pairing to judge."""
        self.assertEqual(unsupported_our_moves(("Flamethrower",)), ())

    def test_the_solver_will_not_plan_an_absorbed_move(self):
        from claytonlib.battle_compass.solver import _legal_actions, SolverConfig

        us = _ours(moves=("False Swipe", "Flamethrower"), pp=(40, 15))
        state = BattleState(ours=us, target=_heatran(hp=1, status=Status.PARALYSIS),
                            rng=0x0C0E02CA, phase=2)
        actions = [a for a, *_ in _legal_actions(state, SolverConfig(), _config())]
        self.assertIn(Action.MOVE_1, actions)
        self.assertNotIn(Action.MOVE_2, actions)


class TestSoundproof(unittest.TestCase):
    """The mirror: our ability blocking THEIR move."""

    def test_metal_sound_is_one_of_the_twelve_sound_moves(self):
        self.assertTrue(soundproofed(_ours(ability="Soundproof"), resolve_move("Metal Sound")))

    def test_it_blocks_the_move_outright(self):
        """Without this the simulator would apply two Sp. Def stages the game never applied, and
        mis-predict every special hit afterwards."""
        self.assertTrue(will_fail(resolve_move("Metal Sound"), _ours(ability="Soundproof")))
        self.assertFalse(will_fail(resolve_move("Metal Sound"), _ours()))

    def test_it_is_by_move_name_not_by_type(self):
        """`sSoundMoves` is a list of twelve moves, so "sound move" is not a type and cannot be
        derived. Lava Plume is not on it; Growl and Roar are."""
        soundproofed_mon = _ours(ability="Soundproof")
        self.assertFalse(soundproofed(soundproofed_mon, resolve_move("Lava Plume")))
        self.assertTrue(soundproofed(soundproofed_mon, resolve_move("Growl")))
        self.assertTrue(soundproofed(soundproofed_mon, resolve_move("Screech")))

    def test_another_ability_does_not_block_it(self):
        self.assertFalse(soundproofed(_ours(ability="Own Tempo"),
                                      resolve_move("Metal Sound")))


class TestTheDangerFloorReadsOurStages(unittest.TestCase):
    """A pre-existing soundness bug this target makes acute."""

    def test_the_floor_rises_with_our_own_sp_def_drop(self):
        """It was computed at stage 0 whatever had been done to us -- and this figure IS the
        solver's heal threshold, so under-predicting it is how a run faints at a number the plan
        called safe."""
        at_zero = worst_incoming_hit(_ours(), _heatran(), any_reachable_weather=True)
        dropped = worst_incoming_hit(_ours(spdef_stage=-2), _heatran(),
                                    any_reachable_weather=True)
        self.assertGreater(dropped, at_zero)

    def test_the_memo_is_keyed_on_those_stages(self):
        """Asked in this order on purpose: a key without our stages served the stage-0 answer for
        the rest of the run once the first call had cached it."""
        first = worst_incoming_hit(_ours(), _heatran(), any_reachable_weather=True)
        second = worst_incoming_hit(_ours(spdef_stage=-2), _heatran(),
                                    any_reachable_weather=True)
        self.assertNotEqual(first, second)

    def test_the_reachable_figure_enumerates_what_the_target_can_drop(self):
        """`any_reachable_stage` means "every stage this battle can reach", and it used to look
        only at the target's offensive ones -- half the question."""
        drops = reachable_defensive_drops(_ours(), _heatran())
        self.assertEqual(drops, (-6, -6))       # Crunch takes Defence, Metal Sound Sp. Def

    def test_a_target_with_no_defensive_drops_leaves_our_stages_alone(self):
        """Suicune cannot touch our defences, so the reachable figure is the current one and the
        advice stays selective."""
        suicune_moves = moveset("suicune")
        suicune = Battler(
            name="suicune", level=40, types=tuple(species("suicune")["types"]),
            stats=derive_species_stats("suicune", 40, "Bold", ivs=31),
            moves=suicune_moves,
            pp=tuple(resolve_move(name).pp for name in suicune_moves),
            ability=target_ability("suicune"))
        self.assertEqual(reachable_defensive_drops(_ours(), suicune), (0, 0))

    def test_the_advice_names_the_escalation(self):
        """A party member that survives the hit now and not once its defences are gone is exactly
        what the second tier exists to report."""
        bulky = _ours(name="Blissey",
                      stats={"hp": 400, "atk": 10, "def": 40, "spa": 40, "spd": 130, "spe": 100})
        warnings = " ".join(survivability_warnings([bulky], _heatran()))
        self.assertIn("survives", warnings)
        self.assertIn("once the target has worked on you", warnings)


class TestItRunsEndToEnd(unittest.TestCase):

    def test_a_sweep_fires_every_move_without_raising(self):
        config = _config()
        seen = set()
        for seed in range(0x0C0E0200, 0x0C0E0230):
            state = BattleState(ours=_ours(), target=_heatran(), rng=opening_rng(seed, config))
            for _ in range(8):
                state = simulate_turn(state, Action.MOVE_1, config)
                seen.update(p for p in state.log[-1] if p.startswith("E"))
                if state.over:
                    break
        for slot in ("E1", "E2", "E3", "E4"):
            self.assertTrue(any(p.startswith(slot) for p in seen), slot)

    def test_lava_plume_can_burn_us_like_any_other_burning_move(self):
        config = _config()
        for seed in range(0x0C0E0200, 0x0C0E0260):
            state = BattleState(ours=_ours(), target=_heatran(pp=(0, 0, 0, 15)),
                                rng=opening_rng(seed, config))
            for _ in range(3):
                state = simulate_turn(state, Action.MOVE_1, config)
                if state.ours.status is Status.BURN:
                    return
                if state.over:
                    break
        self.fail("no Lava Plume burn in 96 seeds, which a 30% secondary should produce")


if __name__ == "__main__":
    unittest.main()
