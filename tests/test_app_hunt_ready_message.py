"""The readiness panel must state the HP it actually has, and the click must not invent one.

Two faults, both fallout from Phase 2 accepting any HP (clayton-6xu.9.1).

1. The panel said "<name> is at 1 HP — ready to solve" unconditionally. True while Phase 2
   required 1 HP; a plain falsehood the moment it did not, and it announced "Giratina is at 1 HP"
   over a Giratina on 198.
2. Worse, the button BEHIND that message called `enter_pinning` with its 1 HP default, so pressing
   it told the solver the target was on 1 when the simulation had it on 198 -- pricing every throw
   against a `b` the battle does not have and planning a capture that cannot land. That is the
   failure `declared_hp` was added to prevent, reached by the one path that had not been updated.

**1 HP is still recommended**, which is why the fix is not to genericise the message away: at a x1
ball it is worth about 3x on every throw (8.09% against 23.42% for a catch-rate-30 target), the
difference between a capture window every twelve stream positions and every four. So the panel
reports the state and says what chipping would buy.

(clayton-6xu.3.14)
"""
import unittest
from pathlib import Path

_HTML = (Path(__file__).resolve().parent.parent / "app" / "web" / "index.html").read_text()


class TestTheMessageReadsTheState(unittest.TestCase):

    def test_it_no_longer_claims_one_hp_unconditionally(self):
        """The literal that was wrong. Written as the markup it appeared in, so a reflow cannot
        hide a reintroduction."""
        self.assertNotIn("is at\n             1 HP", _HTML)

    def test_it_interpolates_the_real_hp(self):
        self.assertIn("${s.target.hp} HP", _HTML)

    def test_it_shows_the_maximum_when_the_target_is_above_one(self):
        """"198 HP" alone is not actionable; "198 of 198" says how much chipping is left."""
        self.assertIn('s.target.hp === 1 ? "" : ` of ${s.target.max_hp}`', _HTML)

    def test_it_still_recommends_chipping_when_above_one(self):
        """The half the user asked for: supported is not the same as recommended."""
        self.assertIn("s.target.hp > 1", _HTML)
        self.assertIn("Chipping further still helps", _HTML)

    def test_and_says_solving_from_here_is_supported(self):
        """So the recommendation does not read as a refusal -- the whole point of the HP
        relaxation is that a higher HP is slower, not impossible."""
        self.assertIn("Solving", _HTML)
        self.assertIn("just slower to find a window", _HTML)


class TestTheClickDoesNotInventAnHp(unittest.TestCase):

    def test_the_normal_path_trusts_the_simulation(self):
        """`null`, not 1. This is the fault that could actually lose a run, as opposed to merely
        reading wrong."""
        self.assertIn('huntRunDo("hunt_session_enter_pinning", force ? 1 : null)', _HTML)

    def test_the_force_path_still_declares_one(self):
        """It exists for a model that lags the game, and its own confirm text already states the
        precondition -- so it is the one caller that should still assert 1."""
        self.assertIn("force ? 1 : null", _HTML)
        self.assertIn("shows the target at 1 HP", _HTML)

    def test_nothing_calls_enter_pinning_without_saying_which(self):
        """A bare call would take the 1 HP default, which is the bug. Every call site has to be
        explicit now that the default is only right for some of them."""
        self.assertNotIn('huntRunDo("hunt_session_enter_pinning")', _HTML)


class TestTheFacadeCarriesIt(unittest.TestCase):

    def test_the_method_takes_a_declared_hp(self):
        import inspect

        from app.facade import Facade

        signature = inspect.signature(Facade.hunt_session_enter_pinning)
        self.assertIn("declared_hp", signature.parameters)
        self.assertIsNone(signature.parameters["declared_hp"].default,
                          "the facade default must be 'trust the simulation'")

    def test_none_leaves_the_hp_alone_and_a_number_adopts_it(self):
        from claytonlib.battle_compass.candidates import Candidate
        from claytonlib.battle_compass.identify import Session
        from claytonlib.battle_compass.sim import HuntConfig
        from claytonlib.battle_compass.state import Battler

        def session():
            target = Battler(name="Giratina", level=47, types=("Ghost", "Dragon"),
                             stats={"hp": 198, "atk": 111, "def": 129,
                                    "spa": 99, "spd": 106, "spe": 104},
                             moves=("Ominous Wind",), pp=(5,))
            ours = Battler(name="Smeargle", level=64, types=("Normal",),
                           stats={"hp": 168, "atk": 71, "def": 72,
                                  "spa": 50, "spd": 87, "spe": 177},
                           moves=("False Swipe",), pp=(40,))
            return Session([Candidate(seed=0x490231DD, frame=1, second=0)], ours, target,
                           HuntConfig(target_catch_rate=3))

        trusted = session()
        trusted.enter_pinning(declared_hp=None)
        self.assertEqual(next(iter(trusted.states.values())).target.hp, 198)

        declared = session()
        declared.enter_pinning(declared_hp=1)
        self.assertEqual(next(iter(declared.states.values())).target.hp, 1)


if __name__ == "__main__":
    unittest.main()
