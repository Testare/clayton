"""Marking a hunt complete, and being offered it at the moment you have earned it.

The field, the facade call, the hunt-home toggle and the tick in the list were all already
there -- what was missing is any prompt from the one moment the player is certain they are
done. Safari Compass has offered exactly that on an expedition since round 12
(`sacShowMarkCompletePrompt`); Battle Compass caught the Pokemon and said nothing.
"""
import pathlib
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"


def _body(html, name):
    body = html[html.index(f"function {name}("):]
    return body[:body.index("\n}") + 2]


class TestTheBackendAlreadySupportedIt(unittest.TestCase):
    """Asserted rather than assumed, because the UI work leans on all of it."""

    def setUp(self):
        self.facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = self.facade.create_profile({"name": "T"})["id"]
        self.hunt = self.facade.create_hunt({"name": "H", "profile_id": profile_id})
        self.facade.save_hunt(self.hunt)

    def test_a_hunt_starts_incomplete(self):
        self.assertFalse(self.facade.get_hunt(self.hunt["id"])["completed"])

    def test_it_can_be_marked_and_unmarked(self):
        self.assertTrue(
            self.facade.set_hunt_completed(self.hunt["id"], True)["completed"])
        self.assertFalse(
            self.facade.set_hunt_completed(self.hunt["id"], False)["completed"])

    def test_it_survives_a_reload(self):
        self.facade.set_hunt_completed(self.hunt["id"], True)
        self.assertTrue(self.facade.get_hunt(self.hunt["id"])["completed"])

    def test_the_list_reports_it_and_sorts_the_unfinished_first(self):
        """So a finished hunt stops competing for attention with the live one."""
        other = self.facade.create_hunt({"name": "AAA later", "profile_id": self.hunt["profile_id"]})
        self.facade.save_hunt(other)
        self.facade.set_hunt_completed(self.hunt["id"], True)
        names = [h["name"] for h in self.facade.list_hunts()]
        done = [h["completed"] for h in self.facade.list_hunts()]
        self.assertEqual(done, [False, True])
        self.assertEqual(names[0], "AAA later")


class TestTheRunOffersIt(unittest.TestCase):
    def setUp(self):
        self.html = INDEX.read_text()

    def test_the_offer_is_gated_on_actually_having_finished_the_hunt(self):
        body = _body(self.html, "huntJustFinishedIt")
        # Caught, in the capture ball, on the KEY SEED -- a capture on another Seed A is a
        # different Pokemon from the one the hunt was planned around.
        self.assertIn("_huntSnap.captured", body)
        self.assertIn("huntSeedAIsKeySeed()", body)
        self.assertIn("!_hunt.completed", body)

    def test_it_uses_the_agreed_capture_flag_not_the_path_text(self):
        """`captured` is `all()` over the surviving candidates, so it is only true once the set
        agrees the ball landed."""
        body = _body(self.html, "huntJustFinishedIt")
        self.assertNotIn("endsWith", body)

    def test_saving_a_winning_run_prompts(self):
        body = _body(self.html, "huntSaveRun")
        self.assertIn("if (huntJustFinishedIt()) huntShowMarkCompletePrompt();", body)

    def test_the_prompt_can_be_declined(self):
        self.assertIn("Not yet", _body(self.html, "huntShowMarkCompletePrompt"))

    def test_the_won_panel_offers_it_too_without_saving_first(self):
        """Saving is optional, and "Start another" is right next to it -- a prompt that only
        fires on save is a prompt the player can walk straight past."""
        self.assertIn("Mark hunt complete", self.html)
        self.assertIn("that is the hunt itself finished", self.html)

    def test_marking_it_goes_through_the_facade_and_refreshes_the_hunt(self):
        body = _body(self.html, "huntMarkCompleteFromRun")
        self.assertIn('api("set_hunt_completed", _huntRunHunt, true)', body)
        self.assertIn("_hunt = await", body)

    def test_it_mirrors_the_safari_offer_rather_than_inventing_a_second_shape(self):
        for name in ("sacShowMarkCompletePrompt", "huntShowMarkCompletePrompt"):
            body = _body(self.html, name)
            self.assertIn("Nice catch!", body, name)
            self.assertIn("Mark as complete", body, name)


if __name__ == "__main__":
    unittest.main()
