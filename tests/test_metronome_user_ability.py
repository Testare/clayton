"""The metronome user's ability reaches the simulation (clayton-2ae.1).

path.py has always carried `user_ability` on the battle state, but nothing initialised it
from the configured MetronomeUser and nothing read it — so the simulation ran as though the
user had no ability, including for the abilities the app permits with only a warning.

These tests pin the two halves of that:

* the ability ARRIVES — a value that is plumbed but unread is exactly the state being fixed,
  so "it got there" is the thing worth asserting;
* passing an ability that nothing reads CHANGES NOTHING. The abilities that ARE modelled
  (Serene Grace, Magic Guard, Intimidate) have their own tests in
  test_metronome_ability_effects.py; what is guarded here is that everything else -- the
  recommended Natural Cure above all -- stays byte-identical.
"""
import tempfile
import unittest
from unittest.mock import patch

from claytonlib.calibration_tools import (
    generate_candidates_near, narrow_candidates, resolve_moveset,
)
from claytonlib.metronome_compass import MetronomeBattleState, precompute_path, render_path

import datetime as dt

_TARGET_TIME = dt.datetime(2025, 7, 24, 14, 45, 56)
_SEEDS = list(range(0x0D0E0000, 0x0D0E0000 + 300, 11))


class TestAbilityReachesTheBattleState(unittest.TestCase):
    def _captured_state(self, **kwargs):
        """The MetronomeBattleState precompute_path actually hands to the turn simulator."""
        seen = {}

        def spy(ctx, state, *a, **kw):
            seen.setdefault("state", state)
            ctx.battle_state["unsupported"] = True      # stop after one turn

        with patch("claytonlib.metronome_compass.simulate_turn", side_effect=spy):
            precompute_path(0x0D0E02BA, magikarp_level=15, opposite_gender=True, **kwargs)
        return seen["state"]

    def test_precompute_path_seeds_the_configured_ability(self):
        self.assertEqual(self._captured_state(user_ability="Serene Grace").user_ability,
                         "Serene Grace")

    def test_default_is_still_no_ability(self):
        # The historical state, kept so an un-plumbed caller behaves exactly as before.
        self.assertIsNone(self._captured_state().user_ability)
        self.assertIsNone(MetronomeBattleState().user_ability)

    def test_generate_candidates_near_passes_it_down(self):
        seen = []

        def spy(seed, **kw):
            seen.append(kw.get("user_ability"))
            return ()

        with patch("claytonlib.metronome_compass.precompute_path", side_effect=spy):
            generate_candidates_near(_TARGET_TIME, 700, 0, 1, magikarp_level=15,
                                     opposite_gender=True, user_ability="Hustle")
        self.assertTrue(seen)
        self.assertEqual(set(seen), {"Hustle"})

    def test_narrow_candidates_configures_the_same_battle(self):
        # Narrowing compares observed turns against the candidates' PRECOMPUTED paths, so a
        # mismatch here would compare predictions against a battle nobody ran. Captured at
        # state construction rather than at simulate_turn, because the interactive loop exits
        # before simulating anything when there are no candidates left to narrow.
        made = []
        real = MetronomeBattleState

        def factory(*a, **kw):
            st = real(*a, **kw)
            made.append(st)
            return st

        with patch("claytonlib.calibration_tools.install_input_fixup"), \
             patch("claytonlib.metronome_compass.MetronomeBattleState", side_effect=factory):
            narrow_candidates([], magikarp_level=15, opposite_gender=True,
                              input_fn=lambda _p: "", output_fn=lambda *a: None,
                              user_ability="Magic Guard")
        self.assertTrue(made, "narrow_candidates built no battle state")
        self.assertEqual(made[0].user_ability, "Magic Guard")
        self.assertEqual(made[0].target_level, 15)   # the sibling input, as a control


class TestPlumbingChangesNoPrediction(unittest.TestCase):
    """Until an ability is actually modelled, passing one must not move a single path."""

    def _paths(self, moveset, ability):
        return [render_path(precompute_path(s, magikarp_level=15, opposite_gender=True,
                                            moveset=moveset, n_turns=10, user_ability=ability))
                for s in _SEEDS]

    def test_identical_for_every_ability_that_should_not_move_a_path(self):
        # This asserted ALL abilities when none were modelled. Serene Grace, Magic Guard and
        # Intimidate are implemented now and have their own tests; what remains here is the
        # set that must still be inert -- the recommended ability, the ones classified as
        # provably-no-effect, and the ones not yet implemented.
        moveset = resolve_moveset(metronome_only=False)
        baseline = self._paths(moveset, None)
        for ability in ("Natural Cure", "Cute Charm",
                        "Pickup", "Run Away", "Quick Feet", "Thick Fat",
                        "Immunity", "Synchronize"):
            self.assertEqual(self._paths(moveset, ability), baseline,
                             f"{ability} changed a path but nothing should read it")

    def test_identical_metronome_only(self):
        baseline = self._paths((), None)
        self.assertEqual(self._paths((), "Natural Cure"), baseline)

    def test_candidate_generation_is_unchanged_too(self):
        common = dict(magikarp_level=15, opposite_gender=True, metronome_only=True)
        base = generate_candidates_near(_TARGET_TIME, 700, 0, 2, **common)
        with_ab = generate_candidates_near(_TARGET_TIME, 700, 0, 2,
                                           user_ability="Natural Cure", **common)
        self.assertEqual([c["path_str"] for c in base], [c["path_str"] for c in with_ab])


class TestFacadeResolvesTheAbility(unittest.TestCase):
    """The ability is read from the stored profile, not taken from the caller."""

    def setUp(self):
        from app.facade import Facade
        from app.store import FileStore
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "P1"})["id"]
        self.uid = self.api.add_metronome_user(self.pid, {
            "name": "Togekiss", "species": "Togekiss", "ability": "Hustle",
            "moveset": ["Metronome"], "lagging_tail": True, "gender": "female",
            "level": 30})["user_id"]

    def test_resolves_from_the_profile(self):
        got = self.api._with_metronome_user_ability(
            {"profile_id": self.pid, "metronome_user_id": self.uid})
        self.assertEqual(got["user_ability"], "Hustle")

    def test_absent_without_enough_to_resolve_it(self):
        for params in ({}, {"profile_id": self.pid}, {"metronome_user_id": self.uid},
                       {"profile_id": "ghost", "metronome_user_id": self.uid},
                       {"profile_id": self.pid, "metronome_user_id": 999}):
            self.assertNotIn("user_ability", self.api._with_metronome_user_ability(params),
                             f"unexpectedly resolved from {params}")

    def test_an_explicit_value_is_not_overwritten(self):
        got = self.api._with_metronome_user_ability(
            {"profile_id": self.pid, "metronome_user_id": self.uid,
             "user_ability": "Serene Grace"})
        self.assertEqual(got["user_ability"], "Serene Grace")

    def test_it_reaches_seed_b(self):
        from tests.test_app_chart import _isolated_cwd
        seen = {}

        def spy(params, model=None):
            seen["ability"] = params.get("user_ability")
            return {}

        with _isolated_cwd(), patch("app.metronome.seed_b", side_effect=spy):
            self.api.metronome_seed_b({
                "target_time": "2025-07-24T14:45:56", "key_seed": 0x0D0E02BA,
                "vector_ms": 300000, "profile_id": self.pid, "metronome_user_id": self.uid,
                "seconds_window": 0, "delay_window": 1,
                "magikarp_level": 15, "opposite_gender": True, "metronome_only": True})
        self.assertEqual(seen["ability"], "Hustle")


if __name__ == "__main__":
    unittest.main()
