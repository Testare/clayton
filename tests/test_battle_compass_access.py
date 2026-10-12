"""Reaching an encounter is a separate question from beating it, and nothing was asking it.

Lugia is at the bottom of the Whirl Islands, behind Surf and Whirlpool. The reason this earns a
check rather than a line in a note: **the party you arrive with is the party you fight with.**
There is no PC down there, so the HM carrier occupies one of the six slots, and discovering that
after a seed-targeting setup is the expensive way to find out.

Advisory in every case — the player may be carrying a mule the hunt's party list does not
mention, or may already be standing in front of the encounter with a save ready to reload.
"""
import unittest

from claytonlib.battle_compass.sim import MODELLED_OUR_EFFECTS, unsupported_our_moves
from claytonlib.battle_compass.targets import (
    ENCOUNTER_ACCESS, EncounterAccess, access_warnings, supported,
)
from claytonlib.moves import CATEGORY_STATUS, resolve_move

PARTY = {
    "Natu": ["Teleport", "Night Shade", "Confuse Ray", "Psychic"],
    "Magneton": ["Thunder Wave", "Screech", "Discharge", "Signal Beam"],
    "Ampharos": ["Flash", "Discharge", "Light Screen", "Signal Beam"],
    "Smeargle": ["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
    "Chatot": ["Sing", "Chatter", "Peck", "Mirror Move"],
}


class TestTheFieldMoveCheck(unittest.TestCase):
    def test_a_party_with_neither_is_warned_about_both(self):
        warnings = access_warnings("lugia", PARTY)
        field = [w for w in warnings if "Surf" in w]
        self.assertEqual(len(field), 1)
        self.assertIn("Surf or Whirlpool", field[0])
        self.assertIn("Whirl Islands", field[0])

    def test_a_party_with_one_is_warned_about_the_other_only(self):
        party = dict(PARTY, Chatot=["Surf", "Sing", "Peck", "Mirror Move"])
        field = [w for w in access_warnings("lugia", party) if "needs to reach" in w]
        self.assertEqual(len(field), 1)
        self.assertIn("Whirlpool", field[0])
        self.assertNotIn("Surf or", field[0])

    def test_a_party_with_both_gets_no_field_move_warning(self):
        party = dict(PARTY, Lapras=["Surf", "Whirlpool", "Ice Beam", "Strength"])
        self.assertEqual([w for w in access_warnings("lugia", party) if "needs to reach" in w],
                         [])

    def test_the_two_can_be_split_across_two_pokemon(self):
        """Nothing requires one carrier -- the check is over the party, not per Pokemon."""
        party = dict(PARTY,
                     Chatot=["Surf", "Sing", "Peck", "Mirror Move"],
                     Lapras=["Whirlpool", "Ice Beam", "Body Slam", "Rest"])
        self.assertEqual([w for w in access_warnings("lugia", party) if "needs to reach" in w],
                         [])

    def test_spelling_and_case_do_not_matter(self):
        party = dict(PARTY, Lapras=["  surf  ", "WHIRLPOOL", "", "Rest"])
        self.assertEqual([w for w in access_warnings("lugia", party) if "needs to reach" in w],
                         [])

    def test_an_empty_party_still_reports_the_requirement(self):
        """The most useful moment to be told is BEFORE the party is picked."""
        field = [w for w in access_warnings("lugia", {}) if "needs to reach" in w]
        self.assertEqual(len(field), 1)


class TestNonMovePrerequisites(unittest.TestCase):
    def test_the_silver_wing_is_reported_and_never_checked(self):
        """No moveset can express a key item, so it is said rather than tested -- and said even
        when the field moves are satisfied."""
        party = dict(PARTY, Lapras=["Surf", "Whirlpool", "Ice Beam", "Strength"])
        warnings = access_warnings("lugia", party)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Silver Wing", warnings[0])


class TestTargetsWithNothingToCheck(unittest.TestCase):
    def test_the_walk_in_encounters_produce_no_warnings(self):
        for species in ("suicune", "ho-oh", "latias", "latios"):
            with self.subTest(species):
                self.assertEqual(access_warnings(species, PARTY), [])

    def test_an_unknown_species_produces_no_warnings_rather_than_raising(self):
        """Absence of a requirement and absence of knowledge are deliberately not
        distinguished: every supported encounter is one or the other."""
        self.assertEqual(access_warnings("pikachu", PARTY), [])
        self.assertEqual(access_warnings("", PARTY), [])

    def test_the_name_is_normalised_like_the_other_tables(self):
        self.assertEqual(access_warnings("Lugia", PARTY), access_warnings("lugia", PARTY))

    def test_every_row_names_a_supported_target(self):
        """A row for a species that is not a target would never be reached."""
        for species in ENCOUNTER_ACCESS:
            with self.subTest(species):
                self.assertIn(species, supported())

    def test_every_field_move_is_a_real_move(self):
        for species, access in ENCOUNTER_ACCESS.items():
            for name in access.field_moves:
                with self.subTest(species=species, move=name):
                    self.assertIsNotNone(resolve_move(name))


class TestSurfIsModelledAndWhirlpoolIsNot(unittest.TestCase):
    """Both will be sitting in a real moveset, so both have to report honestly.

    Surf is inert here for the same reason Gust's effect 149 is: effect 257 is
    `MOVE_EFFECT_DOUBLE_DAMAGE_DIVE`, a conditional multiplier against a state no configured
    encounter can be in. Whirlpool is effect 261, which `metronome_compass` resolves as
    `_eff_bind` -- a hidden duration roll plus a per-turn residual, so it is genuinely unmodelled.
    """

    def test_surf_is_clean(self):
        surf = resolve_move("Surf")
        self.assertEqual(surf.effect, 257)
        self.assertIn(257, MODELLED_OUR_EFFECTS)
        self.assertEqual(unsupported_our_moves(["Surf"]), ())

    def test_surf_sits_beside_the_effect_it_mirrors(self):
        """149 is Gust's `DOUBLE_DAMAGE_FLY_OR_BOUNCE` and was already accepted on this
        reasoning; 257 is the Dive version of the same shape."""
        self.assertIn(149, MODELLED_OUR_EFFECTS)
        self.assertEqual(resolve_move("Gust").effect, 149)

    def test_whirlpool_is_still_refused(self):
        whirlpool = resolve_move("Whirlpool")
        self.assertEqual(whirlpool.effect, 261)
        self.assertNotIn(261, MODELLED_OUR_EFFECTS)
        problems = unsupported_our_moves(["Whirlpool"])
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], "Whirlpool")

    def test_metronome_resolves_whirlpool_as_a_trap_which_is_why(self):
        """The citation for refusing it, asserted so that "it binds" cannot quietly become
        "it is probably fine"."""
        from claytonlib.metronome_compass import effects

        self.assertIs(effects.EFFECT_HANDLERS[261], effects._eff_bind)
        self.assertIs(effects.EFFECT_HANDLERS[257], effects._eff_damage)


class TestTheReasonDistinguishesDamageFromStatus(unittest.TestCase):
    """`execute_move` fails two different ways, and the message used to describe only one.

    An unknown STATUS move is treated as having worked and done nothing, which is inert. An
    unknown DAMAGING move is treated as plain damage -- so any extra roll it really spends
    desynchronises the stream, and any residual keeps the predicted HP wrong. Calling that
    "changed nothing" understated it in the dangerous direction.
    """

    def test_a_damaging_move_says_the_stream_desynchronises(self):
        (_, why), = unsupported_our_moves(["Whirlpool"])
        self.assertIn("plain damage", why)
        self.assertIn("desynchronise", why)
        self.assertNotIn("changed nothing", why)

    def test_a_status_move_still_says_it_changed_nothing(self):
        defog = resolve_move("Defog")
        self.assertEqual(defog.category, CATEGORY_STATUS)
        (_, why), = unsupported_our_moves(["Defog"])
        self.assertIn("changed nothing", why)

    def test_a_move_that_is_not_in_the_table_is_reported_separately(self):
        (name, why), = unsupported_our_moves(["Hyperspace Fury"])
        self.assertEqual(name, "Hyperspace Fury")
        self.assertIn("not in the move table", why)


class TestTheOtherFieldMovesWeMightCarry(unittest.TestCase):
    """Which HMs are safe to leave on a hunt party member, so the answer is written down once.

    Not a requirement -- a mule's other two slots are free -- but the warning is only useful if
    it fires on the right moves.
    """

    def test_these_are_already_modelled(self):
        for name in ("Surf", "Strength", "Cut", "Waterfall", "Rock Climb"):
            with self.subTest(name):
                self.assertEqual(unsupported_our_moves([name]), (), name)

    def test_and_these_are_not(self):
        for name in ("Whirlpool", "Fly", "Dive", "Defog", "Rock Smash"):
            with self.subTest(name):
                self.assertEqual(len(unsupported_our_moves([name])), 1, name)


class TestTheDataclass(unittest.TestCase):
    def test_a_row_with_no_requirements_is_legal_and_silent(self):
        access = EncounterAccess(where="nowhere in particular")
        self.assertEqual(access.field_moves, ())
        self.assertEqual(access.also_needed, ())


if __name__ == "__main__":
    unittest.main()


class TestWhirlpoolIsCarriableButNotSelectable(unittest.TestCase):
    """The resolution: allow the move on the Pokemon, refuse it at the point of use.

    Implementing bind properly would mean a counter on `Battler`, the duration roll, residual
    accounting, the counter in `_dominance_key`, and `can_faint_target` taught to see residual
    damage -- real work for a move nobody intends to use. Refusing it instead costs nothing,
    because a party slot is what is actually scarce: Lugia is behind Surf and Whirlpool, so a
    mule has to come along, and refusing to let it HOLD Whirlpool would refuse the only route to
    the encounter.
    """

    def test_a_pokemon_may_carry_it(self):
        """Nothing in the party or hunt model rejects it -- only the interview and the solver do.
        Asserted through the model that would be the one to object."""
        from app.models import PartyPokemon

        mon = PartyPokemon(
            id=1, name="Lapras", species="lapras", level=40,
            stats={"hp": 150, "atk": 85, "def": 80, "spa": 85, "spd": 95, "spe": 60},
            moveset=["Surf", "Whirlpool", "Strength", "Waterfall"],
            max_pp={"1": 15, "2": 15, "3": 15, "4": 15})
        # `hard_errors` is what the facade turns into `is_hunt_ready` (facade.py:120), so an
        # empty list here IS "can be taken on a hunt".
        self.assertEqual(mon.hard_errors(), [])
        # And it is not even warned about at the party level: carrying it is not the problem.
        self.assertEqual([w for w in mon.warnings() if "Whirlpool" in w], [])

    def test_the_interview_refuses_it_with_a_reason(self):
        from claytonlib.battle_compass.sim import unselectable_reason

        reason = unselectable_reason(resolve_move("Whirlpool"))
        self.assertIsNotNone(reason)
        self.assertIn("Whirlpool", reason)
        self.assertIn("261", reason)

    def test_the_moves_a_mule_should_carry_instead_are_all_selectable(self):
        from claytonlib.battle_compass.sim import unselectable_reason

        for name in ("Surf", "Strength", "Cut", "Waterfall", "Rock Climb"):
            with self.subTest(name):
                self.assertIsNone(unselectable_reason(resolve_move(name)))

    def test_a_run_ending_move_is_refused_for_its_own_reason(self):
        """Teleport and Roar are refused too, and must not be explained as a modelling gap --
        there is no turn to report, which is a different thing from a mis-predicted one."""
        from claytonlib.battle_compass.sim import unselectable_reason

        for name in ("Teleport", "Roar"):
            with self.subTest(name):
                reason = unselectable_reason(resolve_move(name))
                self.assertIn("end the battle", reason)
                self.assertNotIn("cannot model", reason)

    def test_a_guaranteed_FAILURE_is_still_selectable(self):
        """The distinction that makes this safe. A move certain to fail is a perfectly good turn
        to report -- and a Sing against an already-paralyzed target is one of the sharpest
        identification probes there is, so refusing it would cost information rather than save
        it (notes/seed_separation.md sec 2)."""
        from claytonlib.battle_compass.sim import unselectable_reason, will_fail
        from claytonlib.battle_compass.state import Battler, Status

        target = Battler(name="Lugia", level=45, types=("Psychic", "Flying"),
                         stats={"hp": 164, "atk": 99, "def": 135,
                                "spa": 93, "spd": 157, "spe": 117},
                         status=Status.PARALYSIS)
        sing = resolve_move("Sing")
        self.assertTrue(will_fail(sing, target), "the probe depends on it failing")
        self.assertIsNone(unselectable_reason(sing), "and on it staying selectable")

    def test_move_info_carries_the_reason_per_slot(self):
        from claytonlib.battle_compass.hunt_session import move_info
        from claytonlib.battle_compass.state import Battler

        mule = Battler(name="Lapras", level=40, types=("Water", "Ice"),
                       stats={"hp": 150, "atk": 85, "def": 80, "spa": 85, "spd": 95, "spe": 60},
                       moves=("Surf", "Whirlpool", "Strength", "Waterfall"),
                       pp=(15, 15, 15, 15))
        info = move_info(mule)
        by_name = {m["name"]: m for m in info}
        self.assertIsNone(by_name["Surf"]["unselectable_reason"])
        self.assertIsNotNone(by_name["Whirlpool"]["unselectable_reason"])
        # Every slot carries the key, including empty ones, so the page never reads undefined.
        self.assertTrue(all("unselectable_reason" in m for m in info))

    def test_an_empty_slot_carries_the_key_too(self):
        from claytonlib.battle_compass.hunt_session import move_info
        from claytonlib.battle_compass.state import Battler

        mon = Battler(name="Wall", level=40, types=("Normal",), stats={"hp": 100},
                      moves=(), pp=())
        for entry in move_info(Battler(name="Wall", level=40, types=("Normal",),
                                       stats={"hp": 100}, moves=("", ""), pp=(0, 0))):
            self.assertIsNone(entry["unselectable_reason"])


class TestTheSolverCannotPlanOne(unittest.TestCase):
    """`allowed_moves` defaults to all four slots and nothing ever narrowed it.

    `MODELLED_OUR_EFFECTS` has said since it was written that callers should "keep the slots out
    of `SolverConfig.allowed_moves`", and no caller did -- so the solver really could plan a
    Whirlpool as filler. Enforced in `_legal_actions` alongside `ends_the_run` rather than left
    to the caller, so forgetting gets the safe behaviour.
    """

    def test_the_default_allowed_moves_really_is_every_slot(self):
        from claytonlib.battle_compass.solver import SolverConfig

        self.assertEqual(SolverConfig().allowed_moves, (0, 1, 2, 3))

    def test_an_unmodellable_slot_is_not_offered(self):
        from claytonlib.battle_compass.sim import HuntConfig
        from claytonlib.battle_compass.solver import SolverConfig, _legal_actions
        from claytonlib.battle_compass.state import Action, BattleState, Battler, Status

        ours = Battler(
            name="Lapras", level=40, types=("Water", "Ice"),
            stats={"hp": 150, "atk": 85, "def": 80, "spa": 85, "spd": 95, "spe": 60},
            moves=("Whirlpool", "Sweet Scent", "", ""), pp=(15, 20, 0, 0))
        target = Battler(
            name="Lugia", level=45, types=("Psychic", "Flying"),
            stats={"hp": 164, "atk": 99, "def": 135, "spa": 93, "spd": 157, "spe": 117},
            moves=("Extrasensory", "Rain Dance", "Hydro Pump", "Aeroblast"),
            pp=(30, 5, 5, 5), hp=1, status=Status.PARALYSIS)
        state = BattleState(rng=0x12345678, ours=ours, target=target)
        actions = {a for a, _, _ in _legal_actions(state, SolverConfig(),
                                                   HuntConfig(target_catch_rate=3))}
        self.assertNotIn(Action.MOVE_1, actions, "Whirlpool must not be planned")
        self.assertIn(Action.MOVE_2, actions, "Sweet Scent is fine and must stay available")
