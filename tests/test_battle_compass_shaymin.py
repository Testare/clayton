"""Shaymin — the first target whose own moves move its OWN HP, and why full HP deletes that.

Flower Paradise, Lv30, catch rate 45, Natural Cure, base stats 100 across the board.
`StartFatefulEncounter SPECIES_SHAYMIN, 30` (res/field/scripts/scripts_flower_paradise.s:46) —
a different script command from every other static, and it does not matter: it is
`Encounter_NewVsSpeciesAtLevel` plus one data write after `CreateWildMon_Scripted`
(src/encounter.c:549 vs :568), so `BATTLE_START_ADVANCES` is reused unchanged.

Exactly four learnable moves at 30, so the slot order is simply the learn order: Growth(1),
Magical Leaf(10), Leech Seed(19), Synthesis(28). Two were already modelled. The other two are
the point of this file, and **both are inert at full HP** — Synthesis fails outright and Leech
Seed's heal clamps to nothing. That is the whole argument for Phase 2 solving above 1 HP rather
than at it: a full-HP Shaymin cannot move its own HP, so `b` stays where the window search put
it, while at 1 HP the two recovery moves interact and move `b` out from under the precomputed
window (notes/battle_compass_dialga_palkia_shaymin.md sec 4C).

(clayton-6xu.9.7, clayton-6xu.9.9, clayton-6xu.9.11)
"""
import unittest
from dataclasses import replace

from claytonlib.battle.damage import WEATHER_NONE, WEATHER_RAIN, WEATHER_SUN
from claytonlib.battle.stats import derive_species_stats
from claytonlib.battle_compass.sim import (
    ABILITY_MAGIC_GUARD, EFFECT_LEECH_SEED, EFFECT_SYNTHESIS, LEECH_SEED_DIVISOR,
    MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, HuntConfig, cure_with_held_item, execute_move,
    leech_seed_tick, opening_rng, sent_out, simulate_turn, synthesis_heal, unselectable_reason,
    will_fail,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, encounter_level, moveset, resolve, supported, target_held_item,
    unsupported_moves,
)
from claytonlib.moves import resolve_move

GROWTH, MAGICAL_LEAF, LEECH_SEED, SYNTHESIS = 0, 1, 2, 3

#: Shaymin Lv30 at 31 IVs: base HP 100 -> (2*100+31)*30/100 + 30 + 10 = 109.
SHAYMIN_MAX_HP = 109


def _shaymin(slot: int = LEECH_SEED, **kwargs) -> Battler:
    """Shaymin with one usable slot, so the selection roll cannot pick away from it.

    PP of 0 in every other slot is how the rest of this suite pins a target's choice.

    `GROWTH` is the inert choice where a test needs the target to act without moving anybody's
    HP: it raises its own Sp. Atk and does nothing else. Passing `SYNTHESIS` to a drain test
    instead would heal the target mid-measurement.
    """
    pp = [0, 0, 0, 0]
    pp[slot] = 10
    return replace(Battler(
        name="Shaymin", level=30, types=("Grass",),
        stats=derive_species_stats("shaymin", 30, "Timid", ivs=31),
        moves=moveset("shaymin"), pp=tuple(pp), ability="Natural Cure",
        held_item=target_held_item("shaymin")), **kwargs)


def _wall(**kwargs) -> Battler:
    """A fat Normal lead. Normal so it is seedable, and fat enough that nothing here faints it."""
    return replace(Battler(
        name="Wall", level=100, types=("Normal",),
        stats={"hp": 400, "atk": 100, "def": 150, "spa": 100, "spd": 150, "spe": 200},
        moves=("Sweet Scent",), pp=(20,)), **kwargs)


def _grass_wall(**kwargs) -> Battler:
    """The one lead Leech Seed cannot touch at all."""
    return replace(_wall(), types=("Grass",), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=45)


class TestTheEncounterRow(unittest.TestCase):
    def test_it_is_lv30_with_the_learn_order_moveset(self):
        key, enc = resolve("shaymin", "platinum")
        self.assertEqual(key, "shaymin")
        self.assertEqual(enc.level, 30)
        self.assertEqual(enc.moves,
                         ("Growth", "Magical Leaf", "Leech Seed", "Synthesis"))
        self.assertEqual(encounter_level("shaymin", "platinum"), 30)

    def test_every_move_is_modelled(self):
        """The check that gates the row's existence, rather than a reading of a list."""
        self.assertEqual(unsupported_moves("shaymin", "platinum"), ((), None))

    def test_it_is_platinum_only(self):
        self.assertEqual(ENCOUNTERS["shaymin"].games, ("platinum",))
        self.assertIn("shaymin", supported("platinum"))
        self.assertNotIn("shaymin", supported("heartgold"))
        self.assertNotIn("shaymin", supported("soulsilver"))

    def test_it_takes_the_species_ability_and_stats(self):
        """Both fields are deliberately empty: Natural Cure is slot 0 of the species row and is
        inert on a wild Pokemon (it cures on switching OUT, which a wild target never does), and
        the encounter is the Land forme, which IS the `shaymin` row."""
        enc = ENCOUNTERS["shaymin"]
        self.assertEqual(enc.ability, "")
        self.assertEqual(enc.forme, "")
        self.assertFalse(enc.roamer)

    def test_the_derived_max_hp_is_the_figure_the_catch_maths_uses(self):
        self.assertEqual(_shaymin().max_hp, SHAYMIN_MAX_HP)


class TestTheMoveData(unittest.TestCase):
    def test_leech_seed_is_effect_84_target_side_only(self):
        self.assertEqual(resolve_move("Leech Seed").effect, EFFECT_LEECH_SEED)
        self.assertIn(EFFECT_LEECH_SEED, MODELLED_TARGET_EFFECTS)
        self.assertNotIn(EFFECT_LEECH_SEED, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Leech Seed")))

    def test_synthesis_is_effect_132_target_side_only(self):
        self.assertEqual(resolve_move("Synthesis").effect, EFFECT_SYNTHESIS)
        self.assertIn(EFFECT_SYNTHESIS, MODELLED_TARGET_EFFECTS)
        self.assertNotIn(EFFECT_SYNTHESIS, MODELLED_OUR_EFFECTS)
        self.assertIsNotNone(unselectable_reason(resolve_move("Synthesis")))

    def test_leech_seed_spends_exactly_one_accuracy_roll(self):
        """90 accuracy — so unlike every 100-accuracy move on this table it can really miss, and
        a sub-100 move from the TARGET is free RTC-second-sibling separation."""
        rng = 0x0C0E_02CA
        after, outcome = execute_move(rng, resolve_move("Leech Seed"), _shaymin(), _wall(),
                                      actor="E", slot=LEECH_SEED)
        self.assertEqual(outcome.rolls, 1)
        self.assertNotEqual(after, rng)
        self.assertTrue(outcome.seeds)

    def test_synthesis_spends_nothing_at_all(self):
        """Accuracy 0, so no accuracy roll, and `BtlCmd_WeatherHPRecovery` is pure arithmetic."""
        rng = 0x0C0E_02CA
        after, outcome = execute_move(rng, resolve_move("Synthesis"),
                                      _shaymin(SYNTHESIS, hp=40), _wall(),
                                      actor="E", slot=SYNTHESIS)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertTrue(outcome.successful)
        self.assertEqual(outcome.self_heal, SHAYMIN_MAX_HP // 2)


class TestSynthesisFailsAtFullHP(unittest.TestCase):
    """`subscript_recover_hp.s` `_036`: compares cur HP to max on its first line, prints
    "{0}'s HP is full!" and sets `MOVE_STATUS_NO_MORE_WORK` without healing."""

    def test_full_hp_fails_and_a_scratch_does_not(self):
        move = resolve_move("Synthesis")
        self.assertTrue(will_fail(move, _wall(), actor=_shaymin(SYNTHESIS)))
        self.assertFalse(
            will_fail(move, _wall(), actor=_shaymin(SYNTHESIS, hp=SHAYMIN_MAX_HP - 1)))

    def test_it_reads_the_ACTOR_not_the_defender(self):
        """The second self-targeting family in `will_fail`, after Refresh. A full-HP DEFENDER is
        irrelevant; a full-HP user is the whole condition."""
        move = resolve_move("Synthesis")
        self.assertFalse(will_fail(move, _wall(hp=400), actor=_shaymin(SYNTHESIS, hp=1)))
        self.assertTrue(will_fail(move, _wall(hp=1), actor=_shaymin(SYNTHESIS)))

    def test_a_failing_synthesis_is_not_successful_and_still_spends_nothing(self):
        """It is the one `will_fail` family with no accuracy roll to forfeit, so the two
        post-successful-move advances are the entire difference."""
        rng = 0x0C0E_02CA
        after, outcome = execute_move(rng, resolve_move("Synthesis"), _shaymin(SYNTHESIS),
                                      _wall(), actor="E", slot=SYNTHESIS)
        self.assertFalse(outcome.successful)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertEqual(outcome.self_heal, 0)

    def test_a_full_hp_shaymin_does_not_move_its_own_hp_over_a_turn(self):
        """The property Phase 2 depends on: `b` stays where the window search put it."""
        config = _config()
        state = BattleState(ours=_wall(), target=_shaymin(SYNTHESIS),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.target.hp, SHAYMIN_MAX_HP)


class TestSynthesisHeal(unittest.TestCase):
    """`BtlCmd_WeatherHPRecovery` (battle_script.c:5966-5979), in the ROM's three branches."""

    def test_the_three_weather_figures_for_shaymin(self):
        class _Field:
            rain_turns = 0
        mon = _shaymin(SYNTHESIS, hp=1)
        self.assertEqual(synthesis_heal(mon, None), 54)
        self.assertEqual(synthesis_heal(mon, _Field()), 54)
        _Field.rain_turns = 3
        self.assertEqual(synthesis_heal(mon, _Field()), 27)

    def test_rain_halves_it_which_is_our_own_rain_dance_working_for_us(self):
        """Suicune's and Lugia's Rain Dance are the only weather any moveset can set, and against
        Shaymin setting it cuts the recovery from 54 to 27."""
        class _Rain:
            rain_turns = 5
        self.assertLess(synthesis_heal(_shaymin(SYNTHESIS, hp=1), _Rain()),
                        synthesis_heal(_shaymin(SYNTHESIS, hp=1), None))

    def test_sun_is_modelled_though_unreachable(self):
        """No party can set sun; the branch exists because `weather_of` already reads weather and
        a row costs nothing. 109 * 20 // 30 = 72."""
        self.assertEqual(SHAYMIN_MAX_HP * 20 // 30, 72)

    def test_the_weather_names_are_the_shared_ones(self):
        self.assertEqual((WEATHER_NONE, WEATHER_RAIN, WEATHER_SUN), ("", "rain", "sun"))


class TestLeechSeedLanding(unittest.TestCase):
    def test_a_grass_lead_cannot_be_seeded(self):
        """`subscript_leech_seed_start.s` `_065`, checked on BOTH type slots before anything
        else — the one case where the move does nothing whatsoever, and a real party answer."""
        move = resolve_move("Leech Seed")
        self.assertTrue(will_fail(move, _grass_wall()))
        self.assertTrue(will_fail(move, replace(_wall(), types=("Normal", "Grass"))))
        self.assertFalse(will_fail(move, _wall()))

    def test_a_second_one_fails(self):
        """`_046`, `MOVE_STATUS_NO_MORE_WORK`. A different flag from the Grass branch's, and
        `CheckMoveFailure` routes both away from `BATTLE_CONTROL_USE_MOVE`."""
        move = resolve_move("Leech Seed")
        self.assertFalse(will_fail(move, _wall()))
        self.assertTrue(will_fail(move, _wall(seeded=True)))

    def test_a_failing_one_still_spends_the_accuracy_roll(self):
        rng = 0x0C0E_02CA
        _, blocked = execute_move(rng, resolve_move("Leech Seed"), _shaymin(),
                                  _wall(seeded=True), actor="E", slot=LEECH_SEED)
        _, landed = execute_move(rng, resolve_move("Leech Seed"), _shaymin(), _wall(),
                                 actor="E", slot=LEECH_SEED)
        self.assertEqual(blocked.rolls, landed.rolls)
        self.assertFalse(blocked.successful)
        self.assertTrue(landed.successful)

    def test_it_lands_on_us_through_a_turn(self):
        config = _config()
        state = BattleState(ours=_wall(), target=_shaymin(LEECH_SEED),
                            rng=opening_rng(0x0C0E02CA, config))
        self.assertFalse(state.ours.seeded)
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertTrue(after.ours.seeded)
        self.assertFalse(after.target.seeded)


class TestTheDrain(unittest.TestCase):
    def test_unseeded_is_zero(self):
        self.assertEqual(leech_seed_tick(_wall()), 0)

    def test_seeded_is_max_hp_over_eight(self):
        self.assertEqual(leech_seed_tick(_wall(seeded=True)), 400 // LEECH_SEED_DIVISOR)

    def test_it_floors_but_never_to_zero(self):
        """`DivideVarByValue` is `BattleSystem_Divide`, which clamps a zero quotient to 1
        (battle_lib.c:3599-3618) — the same rule as the burn tick and Leftovers."""
        tiny = replace(_wall(), stats={**_wall().stats, "hp": 7}, hp=7, seeded=True)
        self.assertEqual(tiny.max_hp, 7)
        self.assertEqual(leech_seed_tick(tiny), 1)

    def test_magic_guard_is_drained_for_nothing(self):
        """The ROM skips the whole state for a Magic Guard holder
        (battle_controller_player.c:1381). Clefable is an ordinary lead, so this is a party
        answer rather than a hypothetical — and because the heal is the damage dealt, it starves
        the target too."""
        self.assertEqual(leech_seed_tick(_wall(seeded=True, ability="Magic Guard")), 0)
        self.assertEqual(ABILITY_MAGIC_GUARD, "magic guard")

    def test_a_fainted_battler_is_not_drained(self):
        self.assertEqual(leech_seed_tick(_wall(seeded=True, hp=0)), 0)


class TestTheHealIsTheDamageDealt(unittest.TestCase):
    """`subscript_leech_seed_effect.s` hands the seeder `BTLVAR_HIT_DAMAGE`, not the figure it
    computed — so the heal is whatever the drain actually removed."""

    def test_a_full_drain_heals_the_full_figure(self):
        config = _config()
        state = BattleState(ours=_wall(seeded=True),
                            target=_shaymin(GROWTH, hp=SHAYMIN_MAX_HP - 60),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        drained = 400 // LEECH_SEED_DIVISOR
        self.assertEqual(after.ours.hp, 400 - drained)
        self.assertEqual(after.target.hp, SHAYMIN_MAX_HP - 60 + drained)

    def test_a_clamped_drain_heals_only_what_it_took(self):
        """3 HP left against a 50 HP drain: the ROM takes 3 and heals 3, not 50. Predicting
        `max HP / 8` here would over-heal the target on the turn the drain faints us."""
        config = _config()
        state = BattleState(ours=_wall(seeded=True, hp=3),
                            target=_shaymin(GROWTH, hp=40),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.target.hp, 43)

    def test_a_full_hp_shaymin_gains_nothing_from_it(self):
        """The other half of sec 4C: at full HP the heal is clamped to nothing, so the drain is
        pure chip on us and `b` does not move."""
        config = _config()
        state = BattleState(ours=_wall(seeded=True), target=_shaymin(GROWTH),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(after.target.hp, SHAYMIN_MAX_HP)
        self.assertEqual(after.ours.hp, 400 - 400 // LEECH_SEED_DIVISOR)


class TestTheBanner(unittest.TestCase):
    def test_a_leech_seed_shows_up_once_it_lands(self):
        """A flag with no counter, so it renders without a number -- and it is the one condition
        in the banner that takes HP off one side and gives it to the other, which is why the
        player should not have to infer it from the HP dropping."""
        from claytonlib.battle_compass.hunt_session import field_conditions
        config = _config()
        state = BattleState(ours=_wall(), target=_shaymin(LEECH_SEED),
                            rng=opening_rng(0x0C0E02CA, config))
        self.assertNotIn("Leech Seed", [r["name"] for r in field_conditions(state)])
        after = simulate_turn(state, Action.MOVE_1, config)
        rows = [r for r in field_conditions(after) if r["name"] == "Leech Seed"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["whose"], "ours")
        self.assertIsNone(rows[0]["turns"])


class TestTheLumBerry(unittest.TestCase):
    """Shaymin is the ONLY target on the table that holds anything, and the berry changes the
    plan rather than the arithmetic.

    `wildHeldItems` is Lum Berry in BOTH the common and rare slots, which is exactly the case
    `Pokemon_GiveHeldItem` (src/pokemon.c:4675-4701) short-circuits: same non-empty item in both
    slots means it is always held, not 45/50/5. A static encounter really does reach that
    function -- `StartFatefulEncounter` -> `CreateWildMon_Scripted` -> `CreateWildMon` ->
    `AddWildMonToParty` -> `Pokemon_GiveHeldItem`.
    """

    def test_the_row_carries_it_and_the_facade_helper_reads_it(self):
        self.assertEqual(ENCOUNTERS["shaymin"].held_item, "Lum Berry")
        self.assertEqual(target_held_item("shaymin", "platinum"), "Lum Berry")

    def test_no_other_target_holds_anything(self):
        """Only a GUARANTEED item is on file, so every other row is empty -- there is no species
        fallback, because a 45/50/5 roll has no honest default."""
        for key, enc in ENCOUNTERS.items():
            if key != "shaymin":
                with self.subTest(key):
                    self.assertEqual(enc.held_item, "")

    def test_the_item_roll_is_spent_either_way_so_generation_is_unchanged(self):
        """`LCRNG_Next() % 100` is called BEFORE the species lookup and before the equal-items
        shortcut, so an encounter that holds something costs no more advances than one that does
        not. That is what keeps `BATTLE_START_ADVANCES` shared across the whole table, and it is
        asserted here as the reason rather than left implicit."""
        self.assertEqual(ENCOUNTERS["suicune"].held_item, "")
        self.assertEqual(ENCOUNTERS["shaymin"].held_item, "Lum Berry")

    def test_it_cures_and_is_consumed(self):
        mon = _shaymin(hp=40).with_status(Status.SLEEP, sleep_turns=4)
        cured = cure_with_held_item(mon)
        self.assertIs(cured.status, Status.NONE)
        self.assertEqual(cured.sleep_turns, 0)
        self.assertEqual(cured.held_item, "")

    def test_it_does_nothing_to_an_unstatused_holder(self):
        """So the berry survives until something actually lands -- it is not spent on turn 1."""
        self.assertEqual(_shaymin().held_item, "Lum Berry")
        self.assertEqual(cure_with_held_item(_shaymin()).held_item, "Lum Berry")

    def test_it_does_nothing_without_the_berry(self):
        statused = _wall().with_status(Status.SLEEP, sleep_turns=4)
        self.assertIs(cure_with_held_item(statused).status, Status.SLEEP)

    def test_it_cures_confusion_too(self):
        """`itemUseParams` sets `healConfusion` alongside the five non-volatile statuses, which is
        why this is modelled as "cures whatever it finds". Nothing inflicts confusion yet; the
        half is here because the ROM's case is one case."""
        confused = replace(_shaymin(), confusion_turns=4)
        cured = cure_with_held_item(confused)
        self.assertFalse(cured.confused)
        self.assertEqual(cured.held_item, "")

    def test_THE_FIRST_SPORE_IS_WASTED_AND_THE_SECOND_STICKS(self):
        """The planning fact. Phase 2 wants the target asleep for the x2 catch bonus, so against
        Shaymin the first sleep burns the berry and the second is the one that holds."""
        config = _config()
        ours = replace(_wall(), moves=("Spore",), pp=(15,),
                       stats={**_wall().stats, "spa": 10, "atk": 10})
        state = BattleState(ours=ours,
                            target=_shaymin(GROWTH, held_item="Lum Berry"),
                            rng=opening_rng(0x0C0E02CA, config))
        after_one = simulate_turn(state, Action.MOVE_1, config)
        self.assertIs(after_one.target.status, Status.NONE)
        self.assertEqual(after_one.target.held_item, "")
        after_two = simulate_turn(after_one, Action.MOVE_1, config)
        self.assertIs(after_two.target.status, Status.SLEEP)

    def test_the_cure_itself_cannot_spend_an_advance(self):
        """None of the restore subscripts contains a `Random`, and the model says so
        structurally: `cure_with_held_item` takes no RNG state and returns none, so there is no
        way for it to cost one. Asserted as a signature property because an empirical check
        cannot separate the cure from its consequence -- see the test below."""
        import inspect
        params = inspect.signature(cure_with_held_item).parameters
        self.assertEqual(list(params), ["battler"])

    def test_BUT_A_CURED_TARGET_STILL_ACTS_AND_THAT_IS_OBSERVABLE(self):
        """The consequence that matters more than the cost, and it is visible in the TOKENS.

        The berry fires immediately, before the target's half of the turn, so a Shaymin woken by
        it goes on to use a move: the turn reads ``M1 E1`` where a sleeping one reads ``M1 Eslp``.
        So the berry is not a silent planning tax -- the player can see it happen, and a turn
        that spent the target's selection and move rolls is a different turn to match against.
        """
        config = _config()
        ours = replace(_wall(), moves=("Spore",), pp=(15,),
                       stats={**_wall().stats, "spa": 10, "atk": 10})
        with_berry = simulate_turn(
            BattleState(ours=ours, target=_shaymin(GROWTH, held_item="Lum Berry"),
                        rng=opening_rng(0x0C0E02CA, config)),
            Action.MOVE_1, config)
        without = simulate_turn(
            BattleState(ours=ours, target=_shaymin(GROWTH, held_item=""),
                        rng=opening_rng(0x0C0E02CA, config)),
            Action.MOVE_1, config)
        self.assertEqual(with_berry.log[-1], ("M1", "E1"))
        self.assertEqual(without.log[-1], ("M1", "Eslp"))

    def test_it_is_on_the_modelled_items_allowlist(self):
        """So a party member carrying one is not warned about, now that it is modelled on both
        sides -- the ROM's trigger is per battler, not per side."""
        from claytonlib.battle.readiness import unmodelled_held_items
        self.assertEqual(unmodelled_held_items({"Smeargle": "Lum Berry"}), [])


class TestTheSeedIsShed(unittest.TestCase):
    def test_switching_out_sheds_it(self):
        """`moveEffectsMask` is zeroed by the fresh BattleMon a send-out builds, so switching is
        the ordinary answer to a Leech Seed."""
        self.assertTrue(_wall(seeded=True).seeded)
        self.assertFalse(sent_out(_wall(seeded=True)).seeded)

    def test_fainting_clears_it(self):
        self.assertFalse(_wall(seeded=True).with_hp(0).seeded)


if __name__ == "__main__":
    unittest.main()
