"""A "Reset run" must not throw away what belongs to the save file.

Reported: resetting a Safari Compass run cleared the roamer starting positions and appeared to
put the delay/second windows back to their defaults.

Those three describe the SAVE FILE and the player's timing, not the run that just ended. Both
compasses already persist them per expedition precisely so a repeat attempt needs no retyping --
and then blanked them in memory on reset, so the next attempt opened with an empty roamer field
anyway.
"""
import pathlib
import unittest

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"


def _body(html, name):
    body = html[html.index(f"function {name}("):]
    return body[:body.index("\n}") + 2]


class TestResetKeepsTheRoamerSearch(unittest.TestCase):
    def setUp(self):
        self.html = INDEX.read_text()

    def test_no_reset_blanks_the_roamer_positions_any_more(self):
        """The whole bug, in one line that used to appear twice."""
        self.assertNotIn('_startrel = ""', self.html)

    def test_both_compasses_harvest_the_fields_before_resetting(self):
        """Not just "stop blanking it". The fields are only read back into state when a Seed A
        search COMPLETES, so a window typed and not yet searched with was never in state -- and
        re-rendering showed the previous value, which looked like a reset to the default."""
        for name, state, prefix in (("nrReset", "nr", "nr"), ("sacReset", "sac", "sac")):
            body = _body(self.html, name)
            self.assertIn(f'captureRoamerSearch({state}, "{prefix}")', body, name)

    def test_the_harvest_covers_all_four_fields(self):
        body = _body(self.html, "captureRoamerSearch")
        for field in ("-startrel", "-secwin", "-delaywin", "-parity"):
            self.assertIn(field, body)

    def test_it_ignores_an_empty_window_rather_than_reading_it_as_zero(self):
        """A cleared number input reads as "", and Number("") is 0 -- which would silently
        narrow the search to a single delay."""
        body = _body(self.html, "captureRoamerSearch")
        self.assertIn('seconds.value !== ""', body)
        self.assertIn('delays.value !== ""', body)

    def test_it_tolerates_fields_that_are_not_on_screen(self):
        """Reset is reachable from a later step, where the Seed A inputs are not rendered."""
        body = _body(self.html, "captureRoamerSearch")
        self.assertIn("if (startrel)", body)
        self.assertIn("if (parity)", body)

    def test_the_run_specific_state_is_still_cleared(self):
        """The point is to keep the SEARCH, not to keep the run."""
        for name in ("nrReset", "sacReset"):
            body = _body(self.html, name)
            self.assertIn("seedA = null", body, name)
            self.assertIn("seedB = null", body, name)

    def test_the_battle_compass_restores_them_from_the_hunt_instead(self):
        """It has no in-page reset -- abandoning restarts from `hunt_run_setup` -- so its
        equivalent is that the search persists them per hunt and the rebuild reads them back."""
        self.assertIn("hunt_save_seed_a_defaults", self.html)
        self.assertIn("startrel: d.startrel", self.html)


class TestTheDefaultsStillPersistServerSide(unittest.TestCase):
    """The in-memory fix would be pointless if the stored copy were not there to come back to."""

    def test_a_hunt_remembers_its_roamer_search(self):
        import tempfile

        from app.facade import Facade
        from app.store import FileStore

        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        facade.save_hunt(hunt)
        facade.hunt_save_seed_a_defaults(
            hunt["id"], {"startrel": "31 30 7", "seconds_window": 3, "delay_window": 20})
        got = facade.hunt_run_setup(hunt["id"])["seed_a_defaults"]
        self.assertEqual(got["startrel"], "31 30 7")
        self.assertEqual(got["seconds_window"], 3)
        self.assertEqual(got["delay_window"], 20)


if __name__ == "__main__":
    unittest.main()
