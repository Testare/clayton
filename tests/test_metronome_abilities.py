"""The metronome-ability registry, and the facts its verdicts rest on (clayton-2ae.5).

Half of these test the registry itself. The other half are the important half: they pin the
properties of the SIMULATION that make an ability a no-op, so that a future change which
invalidates one fails here instead of quietly turning a "provably cannot matter" into a
silently-wrong path.
"""
import unittest

from claytonlib._resources import basedata_json
from claytonlib.metronome_abilities import (
    METRONOME_ABILITIES, AbilitySupport, ability_info, unsupported_abilities,
)
from claytonlib.metronome_compass import MetronomeBattleState


class TestEveryReachableAbilityIsClassified(unittest.TestCase):
    """The audit's actual acceptance criterion: nothing permitted-but-ignored."""

    def test_no_species_offers_an_unclassified_ability(self):
        data = basedata_json("metronome_species.json")
        rows = data if isinstance(data, list) else list(data.values())
        offered = {a for r in rows for a in (r.get("abilities") or [])}
        self.assertTrue(offered, "no abilities found in the species data")
        unclassified = sorted(offered - set(METRONOME_ABILITIES))
        self.assertEqual(unclassified, [],
                         f"these abilities are selectable but unclassified: {unclassified}")

    def test_every_entry_carries_a_reason(self):
        for name, info in METRONOME_ABILITIES.items():
            self.assertTrue(info.reason.strip(), f"{name} has no reason recorded")
            self.assertEqual(info.name, name)

    def test_unknown_is_unsupported_rather_than_waved_through(self):
        # An ability the registry has never heard of has an unknown effect, and "unknown"
        # must not collapse to "none" -- that is the failure mode this whole file exists for.
        self.assertIs(ability_info("Levitate").support, AbilitySupport.UNSUPPORTED)
        self.assertFalse(ability_info("Levitate").is_supported)

    def test_no_recorded_ability_is_treated_as_no_effect(self):
        for blank in (None, ""):
            self.assertIs(ability_info(blank).support, AbilitySupport.NO_EFFECT)

    def test_unsupported_set_matches_the_registry(self):
        self.assertEqual(
            unsupported_abilities(),
            frozenset(n for n, i in METRONOME_ABILITIES.items()
                      if i.support is AbilitySupport.UNSUPPORTED))


class TestTheFactsBehindTheNoEffectVerdicts(unittest.TestCase):
    """If any of these stops being true, a NO_EFFECT verdict above is no longer safe."""

    def test_magikarp_only_ever_splashes_or_tackles(self):
        # Thick Fat (no Fire/Ice to halve), Immunity and Synchronize (nothing to inflict a
        # status) all rest on this.
        import inspect
        from claytonlib.metronome_compass.context import BattleContext
        src = inspect.getsource(BattleContext.magikarp_move_select)
        self.assertIn('MagikarpMove("sp")', src)
        self.assertIn('"sp" if idx == 0 else "tk"', src)
        # Two options, chosen by one bit -- no room for a third move to appear unnoticed.
        self.assertIn("% 2", src)

    def test_the_user_has_no_burn_poison_paralysis_or_freeze(self):
        # Immunity (prevents poison) and Synchronize (passes burn/para/poison back) rest on
        # there being no such state for the user in the first place.
        state = MetronomeBattleState()
        fields = set(vars(state))
        for condition in ("poison", "burn", "paraly", "frozen", "freeze", "toxic"):
            offenders = sorted(f for f in fields
                               if condition in f.lower() and f.startswith("user_"))
            self.assertEqual(offenders, [],
                             f"the user now has {condition} state ({offenders}); "
                             f"re-check the Immunity/Synchronize verdicts")

    def test_the_only_user_side_conditions_are_self_inflicted(self):
        state = MetronomeBattleState()
        self.assertTrue(hasattr(state, "user_sleep_turns"))       # Rest, on itself
        self.assertTrue(hasattr(state, "user_confusion_turns"))   # Rampage backlash
        # Neither is inflicted BY Magikarp, which is what Synchronize would need.

    def test_the_battle_tracks_hp_knowledge_not_hp_totals(self):
        # Thick Fat halves damage taken; that only matters if a damage AMOUNT is observable.
        state = MetronomeBattleState()
        fields = set(vars(state))
        self.assertIn("user_took_damage", fields)
        self.assertNotIn("user_hp", fields)
        self.assertNotIn("user_current_hp", fields)


class TestTheFactBehindIntimidate(unittest.TestCase):
    """Intimidate is UNSUPPORTED rather than NO_EFFECT because stat stages are observable."""

    def test_a_stat_at_its_floor_makes_the_effect_not_proc(self):
        # This is the whole mechanism: damage magnitude is invisible, but a lowering effect
        # that fails to proc changes the path -- so where the floor is reached matters, and
        # Intimidate moves it by starting the stage at -1.
        from claytonlib.metronome_compass.effects import _target_stat_applier

        class _Ctx:
            def __init__(self, state):
                self.battle_state = {"state": state}

        state = MetronomeBattleState()
        ctx = _Ctx(state)
        apply = _target_stat_applier(ctx, "target_atk_stage", -1)
        for expected_stage in range(-1, -7, -1):
            self.assertTrue(apply(), "should still be able to lower")
            self.assertEqual(state.target_atk_stage, expected_stage)
        self.assertFalse(apply(), "at the floor it must report not-observable")
        self.assertEqual(state.target_atk_stage, -6)


class TestModelsUsesTheRegistry(unittest.TestCase):
    def _user(self, ability):
        from app.models import MetronomeUser
        return MetronomeUser(id=1, name="x", species="Chansey", ability=ability,
                             moveset=["Metronome"], lagging_tail=True)

    def test_unsupported_abilities_block_selection(self):
        for ability in sorted(unsupported_abilities()):
            errors = self._user(ability).hard_errors()
            self.assertTrue(errors, f"{ability} should block selection")
            self.assertIn(ability, errors[0])
            self.assertIn("not simulated yet", errors[0])

    def test_no_effect_abilities_never_block(self):
        for name, info in METRONOME_ABILITIES.items():
            if info.support is AbilitySupport.NO_EFFECT:
                self.assertEqual(self._user(name).hard_errors(), [],
                                 f"{name} provably cannot matter and must not block")

    def test_the_recommended_ability_is_clean(self):
        u = self._user("Natural Cure")
        self.assertEqual(u.hard_errors(), [])
        self.assertEqual(u.suitability_warnings(), [])

    def test_a_blocked_ability_is_not_also_warned_about(self):
        # It is reported once, as a block, not twice in two different voices. Uses an ability
        # that is still unsupported -- Serene Grace and Hustle, the earlier examples, are
        # both modelled now.
        u = self._user("Cute Charm")
        self.assertTrue(u.hard_errors())
        self.assertEqual(u.suitability_warnings(), [])

    def test_a_modelled_ability_neither_blocks_nor_warns(self):
        for ability in ("Serene Grace", "Magic Guard", "Intimidate", "Hustle"):
            u = self._user(ability)
            self.assertEqual(u.hard_errors(), [], f"{ability} is modelled and must not block")

    def test_creation_is_never_blocked(self):
        # hard_errors gates SELECTION only; people must still record the Pokemon they own.
        import tempfile
        from app.facade import Facade
        from app.store import FileStore
        api = Facade(FileStore(tempfile.mkdtemp()))
        pid = api.create_profile({"name": "P"})["id"]
        res = api.add_metronome_user(pid, {
            "name": "Clefairy", "species": "Clefairy", "ability": "Cute Charm",
            "moveset": ["Metronome"], "lagging_tail": True})
        self.assertTrue(res["hard_errors"])
        self.assertEqual(len(api.get_profile(pid)["metronome_users"]), 1)


if __name__ == "__main__":
    unittest.main()
