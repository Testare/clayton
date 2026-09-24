"""The abilities the simulation actually implements (clayton-2ae.2/.4/.9).

The overriding constraint is that NATURAL CURE MUST NOT MOVE. It is the verified,
recommended ability and every saved run and fitted model rests on it, so each test here
checks the new ability against a Natural Cure baseline rather than in isolation.
"""
import unittest

from claytonlib.calibration_tools import resolve_moveset
from claytonlib.metronome_compass import (
    MetronomeBattleState, apply_entry_ability, precompute_path, render_path,
)
from claytonlib.metronome_compass import effects as E

_MOVESET = resolve_moveset(metronome_only=False)


def _path(seed, ability, level=15, turns=10, moveset=_MOVESET):
    return render_path(precompute_path(seed, magikarp_level=level, opposite_gender=True,
                                       moveset=moveset, n_turns=turns, user_ability=ability))


def _seeds(n, stride=3, start=0x0D0E0000):
    return list(range(start, start + n * stride, stride))


class TestNaturalCureIsUnchanged(unittest.TestCase):
    """The regression that matters most: modelling other abilities must not touch this one."""

    def test_natural_cure_matches_no_ability_at_all(self):
        for moveset in (_MOVESET, ()):
            for s in _seeds(400):
                self.assertEqual(_path(s, "Natural Cure", moveset=moveset),
                                 _path(s, None, moveset=moveset),
                                 f"Natural Cure diverged from the no-ability baseline at 0x{s:08X}")

    def test_no_effect_abilities_still_change_nothing(self):
        for ability in ("Pickup", "Run Away", "Quick Feet", "Thick Fat",
                        "Immunity", "Synchronize"):
            for s in _seeds(200):
                self.assertEqual(_path(s, ability), _path(s, "Natural Cure"),
                                 f"{ability} changed a path but is classified no-effect")


class TestSereneGrace(unittest.TestCase):
    def test_doubles_the_threshold_without_changing_the_roll(self):
        from claytonlib.metronome_compass import RngContext
        ctx = RngContext(0)
        state = MetronomeBattleState()
        ctx.battle_state["state"] = state
        for chance, expected in ((0, 0), (10, 20), (30, 60), (50, 100), (60, 100), (100, 100)):
            state.user_ability = "Serene Grace"
            self.assertEqual(ctx.secondary_effect_chance(chance), expected)
            state.user_ability = "Natural Cure"
            self.assertEqual(ctx.secondary_effect_chance(chance), chance)

    def test_zero_stays_zero(self):
        # A move with no secondary effect must not acquire one.
        from claytonlib.metronome_compass import RngContext
        ctx = RngContext(0)
        state = MetronomeBattleState()
        state.user_ability = "Serene Grace"
        ctx.battle_state["state"] = state
        self.assertEqual(ctx.secondary_effect_chance(0), 0)

    def test_it_actually_moves_paths(self):
        seeds = _seeds(600)
        differing = sum(1 for s in seeds if _path(s, "Serene Grace") != _path(s, "Natural Cure"))
        # Roughly a fifth in practice; assert only that it is substantial and not everything,
        # so the test survives unrelated effect fixes without becoming meaningless.
        self.assertGreater(differing, len(seeds) // 20)
        self.assertLess(differing, len(seeds))

    def test_more_procs_not_fewer(self):
        # Doubling a chance can only make effects proc more often, so the '~' proc marker
        # should never become rarer overall.
        seeds = _seeds(400)
        nc = sum(_path(s, "Natural Cure").count("~") for s in seeds)
        sg = sum(_path(s, "Serene Grace").count("~") for s in seeds)
        self.assertGreater(sg, nc)


class TestMagicGuard(unittest.TestCase):
    def _state(self, ability):
        st = MetronomeBattleState()
        st.user_ability = ability
        return st

    def test_recoil_does_not_mark_the_user_damaged(self):
        class _Ctx:
            def __init__(self, st): self.battle_state = {"state": st}
        for ability, expected in (("Natural Cure", True), (None, True), ("Magic Guard", False)):
            st = self._state(ability)
            E._mark_user_recoil(_Ctx(st))
            self.assertEqual(st.user_took_damage, expected,
                             f"recoil under {ability} should mark damaged={expected}")

    def test_it_moves_paths_when_recoil_is_the_only_damage_source(self):
        # Below level 15 Magikarp can only Splash, so it never damages the user directly and
        # recoil is the only thing that can put her below full. This is where Magic Guard
        # decides anything.
        seeds = _seeds(800)
        differing = sum(1 for s in seeds
                        if _path(s, "Magic Guard", level=10) != _path(s, "Natural Cure", level=10))
        self.assertGreater(differing, 0)

    def test_a_landed_tackle_masks_it(self):
        # Magic Guard does not prevent DIRECT damage, so once Magikarp connects the user is
        # below full regardless and recovery succeeds either way. Documented because it is
        # why the ability looks inert at level 15.
        seeds = _seeds(600)
        differing = sum(1 for s in seeds
                        if _path(s, "Magic Guard", level=15) != _path(s, "Natural Cure", level=15))
        self.assertEqual(differing, 0,
                         "if this starts differing at L15, the Tackle-masks-it note is stale")


class TestIntimidate(unittest.TestCase):
    def test_it_drops_magikarps_attack_on_entry(self):
        st = MetronomeBattleState()
        st.user_ability = "Intimidate"
        apply_entry_ability(st)
        self.assertEqual(st.target_atk_stage, -1)

    def test_no_other_ability_touches_a_stat(self):
        for ability in (None, "Natural Cure", "Serene Grace", "Magic Guard", "Hustle"):
            st = MetronomeBattleState()
            st.user_ability = ability
            apply_entry_ability(st)
            self.assertEqual(st.target_atk_stage, 0, f"{ability} moved a stat stage")

    def test_it_stops_at_the_floor(self):
        st = MetronomeBattleState()
        st.user_ability = "Intimidate"
        st.target_atk_stage = -6
        apply_entry_ability(st)
        self.assertEqual(st.target_atk_stage, -6)

    def test_it_changes_no_observed_path_today(self):
        # Damage magnitude is invisible, and the only thing that reads a stage observably is
        # the floor check in _target_stat_applier, which takes six lowering effects to reach.
        # Pinned so that if a future change DOES make stages observable, this fails and the
        # ability's reach gets re-examined rather than shifting silently.
        seeds = _seeds(500)
        differing = sum(1 for s in seeds if _path(s, "Intimidate") != _path(s, "Natural Cure"))
        self.assertEqual(differing, 0)


class TestTheRegistryMatchesReality(unittest.TestCase):
    def test_modelled_abilities_are_no_longer_blocked(self):
        from app.models import HARD_ERROR_ABILITIES
        for ability in ("Serene Grace", "Magic Guard", "Intimidate"):
            self.assertNotIn(ability, HARD_ERROR_ABILITIES)

    def test_the_unimplemented_ones_still_are(self):
        from app.models import HARD_ERROR_ABILITIES
        self.assertEqual(sorted(HARD_ERROR_ABILITIES), ["Cute Charm", "Hustle"])


if __name__ == "__main__":
    unittest.main()
