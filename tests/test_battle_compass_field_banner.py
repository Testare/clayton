"""What is up on the field, and for how long.

Requested from the app: "Might be good to have a banner for field effects and their duration,
like rain, safeguard, screens, etc." Everything here was already tracked on `BattleState` and
none of it was shown, so the player was keeping turn counters in their head.

It is worth more than convenience: several of these change the ADVANCE COUNT of a turn. A Rain
Dance into standing rain fails, which costs the turn its two post-successful-move advances --
the bug that desynchronised test1.jsonl at turn 3. Seeing that rain is up is seeing why the next
turn will cost what it costs.

clayton-gni.
"""
import unittest

from claytonlib.battle_compass.hunt_session import (
    FIELD_CONDITIONS, FIELD_FLAGS, field_conditions,
)
from claytonlib.battle_compass.state import BattleState, Battler, Status


def _state(**kw):
    ours = Battler(name="Smeargle", level=58, types=("Normal",),
                   stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160})
    target = Battler(name="Lugia", level=45, types=("Psychic", "Flying"),
                     stats={"hp": 164, "atk": 99, "def": 135,
                            "spa": 93, "spd": 157, "spe": 117})
    state = BattleState(rng=0x12345678, ours=ours, target=target)
    for key, value in kw.items():
        setattr(state, key, value)
    return state


class TestWhatItReports(unittest.TestCase):
    def test_an_untouched_field_reports_nothing(self):
        """Hidden entirely rather than listing six inactive rows -- a banner nobody reads is
        worse than no banner, because it also costs the space."""
        self.assertEqual(field_conditions(_state()), [])

    def test_a_counter_carries_its_remaining_turns(self):
        (rain,) = field_conditions(_state(rain_turns=3))
        self.assertEqual(rain, {"name": "Rain", "turns": 3, "whose": "field"})

    def test_a_flag_carries_None_rather_than_a_made_up_number(self):
        """Trapped and Water Sport do not count down, so the page renders them without a number
        instead of showing a misleading 0 or 1."""
        (trapped,) = field_conditions(_state(target_trapped=True))
        self.assertEqual(trapped, {"name": "Trapped", "turns": None, "whose": "target"})

    def test_several_at_once_keep_the_table_order(self):
        """Ordered by how much each changes play, not alphabetically: weather first because it
        scales damage, then what blocks an action, then the merely defensive."""
        state = _state(rain_turns=2, safeguard_turns=5, mist_turns=1,
                       reflect_turns=4, light_screen_turns=3)
        self.assertEqual([c["name"] for c in field_conditions(state)],
                         ["Rain", "Safeguard", "Mist", "Reflect", "Light Screen"])

    def test_zero_turns_is_absent_rather_than_present_at_zero(self):
        self.assertEqual(field_conditions(_state(rain_turns=0, mist_turns=0)), [])

    def test_each_condition_says_whose_side_it_is_on(self):
        """Which matters for reading it: Mist and Safeguard are the TARGET's and work against us,
        Reflect and Light Screen are ours, rain belongs to neither."""
        state = _state(rain_turns=1, safeguard_turns=1, mist_turns=1,
                       reflect_turns=1, light_screen_turns=1, target_water_sport=True)
        whose = {c["name"]: c["whose"] for c in field_conditions(state)}
        self.assertEqual(whose["Rain"], "field")
        self.assertEqual(whose["Safeguard"], "target")
        self.assertEqual(whose["Mist"], "target")
        self.assertEqual(whose["Water Sport"], "target")
        self.assertEqual(whose["Reflect"], "ours")
        self.assertEqual(whose["Light Screen"], "ours")


class TestItCoversWhatTheSimulatorTracks(unittest.TestCase):
    def test_every_listed_attribute_exists_on_the_state(self):
        """A typo'd attribute would silently never report, which is the failure mode a banner
        cannot afford -- it would look like the condition was never up."""
        state = _state()
        for attr, _, _ in FIELD_CONDITIONS + FIELD_FLAGS:
            with self.subTest(attr):
                self.assertTrue(hasattr(state, attr), attr)

    def test_no_turn_counter_the_simulator_keeps_is_left_out(self):
        """The list has to be complete, not merely correct. Every `*_turns` field on the state
        is either reported or deliberately excluded here, so adding one to the simulator fails
        this test rather than quietly going unshown.
        """
        reported = {attr for attr, _, _ in FIELD_CONDITIONS}
        # Not field conditions: sleep belongs to a Pokemon and both sides already render a status
        # chip for it, so a field banner would report it twice and in the wrong place.
        excluded = {"sleep_turns"}
        state = _state()
        on_state = {name for name in vars(state) if name.endswith("_turns")}
        self.assertEqual(on_state - reported - excluded, set())

    def test_sleep_is_deliberately_not_in_the_banner(self):
        state = _state()
        state.ours = state.ours.with_status(Status.SLEEP, sleep_turns=3)
        self.assertEqual(field_conditions(state), [])


class TestTheSnapshotAndThePage(unittest.TestCase):
    def test_the_snapshot_carries_a_field_key(self):
        from claytonlib.battle_compass import hunt_session

        self.assertIn('"field": field_conditions(state)',
                      __import__("inspect").getsource(hunt_session))

    def test_the_page_renders_it(self):
        import pathlib

        html = (pathlib.Path(__file__).resolve().parent.parent
                / "app" / "web" / "index.html").read_text()
        self.assertIn("function hrFieldBanner(field){", html)
        self.assertIn("${hrFieldBanner(s.field)}", html)
        # Renders nothing at all when empty, matching `field_conditions`.
        self.assertIn('if(!field || !field.length) return "";', html)


if __name__ == "__main__":
    unittest.main()
