"""Speed checks should not assume our paralysis against a target that cannot inflict it.

Reported twice from the app: "I even get warnings about *near* speed ties that only occur when
my party is paralyzed, against an opponent that has no way of paralyzing me."

`speed_checks(include_our_paralysis=...)` defaulted True and nothing ever derived it, so half
the table described a state the player could not reach. Against Lugia -- no paralysing move,
Pressure rather than Static -- every one of those rows was a hypothetical.

clayton-36b.
"""
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore
from claytonlib.battle.readiness import speed_checks
from claytonlib.battle_compass.sim import can_inflict
from claytonlib.battle_compass.state import Battler, Status

IVS = {"hp": 31, "atk": 31, "def": 31, "spa": 17, "spd": 31, "spe": 31}


def _mon(moves, ability=""):
    return Battler(name="x", level=50, types=("Normal",), stats={},
                   moves=moves, pp=(5,) * len(moves), ability=ability)


class TestCanInflict(unittest.TestCase):
    def test_no_configured_target_can_paralyze_us(self):
        """Which is why the rows were pure noise. Asserted per target rather than in the
        aggregate so a new one that CAN is a visible change here."""
        from claytonlib.battle.stats import abilities
        from claytonlib.battle_compass.targets import moveset, supported

        for species in supported():
            with self.subTest(species):
                probe = _mon(moveset(species), (abilities(species) or ("",))[0])
                self.assertFalse(can_inflict(probe, Status.PARALYSIS))

    def test_a_primary_paralysis_move_counts(self):
        for name in ("Thunder Wave", "Glare", "Stun Spore"):
            with self.subTest(name):
                self.assertTrue(can_inflict(_mon((name,)), Status.PARALYSIS))

    def test_a_secondary_paralysis_move_counts(self):
        """Dragon Breath is the one that matters: it is in both roamer Lati sets, so the roamer
        target really will need these rows."""
        for name in ("Dragon Breath", "Discharge", "Body Slam", "Spark"):
            with self.subTest(name):
                self.assertTrue(can_inflict(_mon((name,)), Status.PARALYSIS))

    def test_static_counts_even_with_no_paralysing_move(self):
        self.assertTrue(can_inflict(_mon(("Tackle",), "Static"), Status.PARALYSIS))

    def test_the_abilities_our_targets_actually_have_do_not(self):
        for ability in ("Pressure", "Levitate", "Sturdy", "Magnet Pull", ""):
            with self.subTest(ability):
                self.assertFalse(can_inflict(_mon(("Tackle",), ability), Status.PARALYSIS))

    def test_an_UNKNOWN_ability_is_assumed_capable(self):
        """Erring toward a spurious row: it costs a line of advice, where a missing row costs an
        unmodelled desync."""
        self.assertTrue(can_inflict(_mon(("Tackle",), "Mould Breaker"), Status.PARALYSIS))

    def test_it_distinguishes_the_status_asked_about(self):
        burner = _mon(("Sacred Fire",))
        self.assertTrue(can_inflict(burner, Status.BURN))
        self.assertFalse(can_inflict(burner, Status.PARALYSIS))
        self.assertTrue(can_inflict(_mon(("Tackle",), "Flame Body"), Status.BURN))
        self.assertFalse(can_inflict(_mon(("Tackle",), "Flame Body"), Status.PARALYSIS))

    def test_every_paralysis_effect_the_simulator_models_is_caught(self):
        """The completeness invariant. A paralysis-capable effect the simulator accepts but this
        predicate misses would put the rows back -- silently, and only for that target.

        Thunder (effect 152) is NOT caught, and does not need to be: it is in neither
        MODELLED_TARGET_EFFECTS nor MODELLED_OUR_EFFECTS, so `unsupported_moves` refuses any
        target carrying it. The predicate only has to be complete over what is configurable.
        """
        from claytonlib.battle_compass.sim import (
            MODELLED_OUR_EFFECTS, MODELLED_TARGET_EFFECTS, SECONDARY_STATUSES,
        )
        from claytonlib.moves import _load_moves

        caught = {e for e, s in SECONDARY_STATUSES.items() if s is Status.PARALYSIS} | {67}
        modelled = set(MODELLED_TARGET_EFFECTS) | set(MODELLED_OUR_EFFECTS)
        for move in _load_moves():
            if move.effect not in modelled or move.effect in caught:
                continue
            with self.subTest(move=move.name):
                self.assertFalse(
                    can_inflict(_mon((move.name,)), Status.PARALYSIS),
                    f"{move.name} (effect {move.effect}) is modelled and paralysis-capable "
                    f"but not in the predicate's tables")


class TestTheFacadeDerivesIt(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.profile = self.api.create_profile({"name": "Gold"})
        self.pid = self.api.add_party_pokemon(self.profile["id"], dict(
            name="Magneton", species="magneton", level=54, ability="Sturdy",
            stats={"hp": 134, "atk": 85, "def": 120, "spa": 170, "spd": 101, "spe": 118},
            moveset=["Thunder Wave", "Screech"], max_pp={"1": 20, "2": 40}))["pokemon_id"]

    def _hunt(self, species, level, **kw):
        fields = {
            "name": species, "profile_id": self.profile["id"], "capture_ball": "Love Ball",
            "target": {"species": species, "level": level, "nature": "Serious",
                       "ivs": dict(IVS)},
            "party": [{"pokemon_id": self.pid}],
            "key_seed": 0xEC1504DC, "initial_time": "2026-09-29T12:00:00",
            "vector_ms": 382791,
        }
        fields.update(kw)
        return self.api.create_hunt(fields)

    def test_a_lugia_hunt_has_no_rows_assuming_our_paralysis(self):
        checks = self.api.hunt_readiness(self._hunt("lugia", 45)["id"])["speed"]["checks"]
        self.assertTrue(checks, "there must still be rows for the healthy case")
        self.assertEqual([c for c in checks if "(paralyzed)" in c["ours"]], [])

    def test_nor_a_ho_oh_hunt_which_has_seven_speed_stages(self):
        """The one where it mattered most: seven stages x two target states x two of ours was
        28 rows, 14 of them unreachable."""
        checks = self.api.hunt_readiness(self._hunt("ho-oh", 70)["id"])["speed"]["checks"]
        self.assertEqual([c for c in checks if "(paralyzed)" in c["ours"]], [])
        self.assertEqual(len(checks), 14)

    def test_the_genuine_fragile_margin_survives(self):
        """Magneton at 118 against Lugia's 117 is one point apart, which is a real warning and
        must not be swept away with the hypotheticals."""
        warnings = self.api.hunt_readiness(self._hunt("lugia", 45)["id"])["speed"]["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Magneton", warnings[0])
        self.assertNotIn("paralyzed)", warnings[0])

    def test_an_unknown_species_keeps_the_rows(self):
        """No moveset to read, so the safe direction is to keep showing them."""
        self.assertTrue(self.api._target_can_paralyze_us(
            type("T", (), {"species": "pikachu"})()))


class TestTheParameterStillWorks(unittest.TestCase):
    def test_passing_it_on_adds_the_rows_back(self):
        off = speed_checks({"A": 100}, 80, include_our_paralysis=False)
        on = speed_checks({"A": 100}, 80, include_our_paralysis=True)
        self.assertEqual(len(on), 2 * len(off))
        self.assertEqual([c for c in off if "(paralyzed)" in c.ours], [])


if __name__ == "__main__":
    unittest.main()
