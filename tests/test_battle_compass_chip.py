"""Can the party actually DAMAGE the target — asked before the run rather than during it.

The sibling of `test_battle_compass_access`, and for the same reason: reaching an encounter and
beating it are separate questions, and so is *chipping* it. Phase 1 needs the target on 1 HP and
False Swipe is the only move that can safely put it there (effect 101's floor is what makes it
safe). **False Swipe is Normal.** So against Giratina, which is Ghost/Dragon, the one move the
whole chip phase rests on does nothing at all.

That is worth a pre-run check rather than a note, because of when the alternative tells you: the
interview renders a hit marker and an unmoved HP bar, which is indistinguishable from a bug, and
by then a seed-targeting setup has already been spent. The fix costs a party slot — a Foresight, an
Odor Sleuth, or a Scrappy attacker — and a party slot is a decision made at configuration time.

Advisory in every case, like every other warning in `targets`: the hunt's party list is not
necessarily the game party, and a player may intend to chip with something the simulator cannot
price.

(clayton-957.26.4)
"""
import unittest

from claytonlib.battle_compass.targets import (
    ENCOUNTERS, chip_warnings, supported, target_ability, target_types,
)
from claytonlib.moves import resolve_move


def _moves(*names):
    return [resolve_move(name) for name in names]


#: The planned Phase 2 Pokemon for every target, with nothing to lift an immunity.
BARE_SMEARGLE = {"Smeargle": _moves("False Swipe", "Flash", "Spore", "Mean Look")}
#: The same party with one slot swapped for the answer. Sketch is why this is realistic.
ARMED_SMEARGLE = {"Smeargle": _moves("False Swipe", "Odor Sleuth", "Spore", "Mean Look")}

GHOST = "giratina-origin"
#: A target with no immunity to anything a party carries, as the control.
PLAIN = "suicune"


class TestTheTargetsOwnRow(unittest.TestCase):
    """`target_types` is new, and it is what the check and the readiness probe both read."""

    def test_it_comes_off_the_stats_row(self):
        self.assertEqual(target_types(GHOST), ("Ghost", "Dragon"))
        self.assertEqual(target_types(PLAIN), ("Water",))

    def test_it_is_keyed_by_forme_like_the_stats_are(self):
        """Both Giratina formes share a typing, so this is about the lookup rather than the
        answer: nothing should depend on that coincidence holding."""
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                self.assertEqual(target_types(key), ("Ghost", "Dragon"))

    def test_every_configured_target_has_types(self):
        """A target whose types could not be read would make the chip check silently vacuous,
        which is the direction that costs a run."""
        for key in supported():
            with self.subTest(key):
                types = target_types(key)
                self.assertTrue(types)
                self.assertTrue(all(isinstance(t, str) and t for t in types))

    def test_an_unknown_species_raises_rather_than_guessing(self):
        with self.assertRaises(KeyError):
            target_types("pikachu")


class TestTheGhostCase(unittest.TestCase):
    """The case the check exists for."""

    def test_a_bare_false_swipe_against_a_ghost_is_warned_about(self):
        warnings = chip_warnings(GHOST, BARE_SMEARGLE)
        self.assertEqual(len(warnings), 1)
        self.assertIn("False Swipe", warnings[0])
        self.assertIn("Smeargle", warnings[0])

    def test_the_warning_names_the_typing_that_blocks_it(self):
        """So the player can tell this from a Levitate or a bad matchup without guessing."""
        warning = chip_warnings(GHOST, BARE_SMEARGLE)[0]
        self.assertIn("Ghost/Dragon", warning)

    def test_with_no_fix_in_the_party_it_says_what_to_bring(self):
        warning = chip_warnings(GHOST, BARE_SMEARGLE)[0]
        self.assertIn("Foresight or Odor Sleuth", warning)
        self.assertIn("Scrappy", warning)

    def test_with_a_fix_in_the_party_it_names_the_move_and_the_holder(self):
        """"Use Odor Sleuth" is a move; "use Odor Sleuth (Smeargle)" is a turn."""
        warning = chip_warnings(GHOST, ARMED_SMEARGLE)[0]
        self.assertIn("Odor Sleuth (Smeargle)", warning)
        self.assertNotIn("Scrappy", warning)

    def test_the_fix_may_be_carried_by_somebody_else(self):
        """**The Foresight does not have to be on the False Swipe user** [verified in game, by
        Testare]. The flag is a volatile on the TARGET, so one Pokemon can identify it and another
        can come in and chip -- which is why the suggestion names any carrier in the party rather
        than only the one holding the False Swipe.

        Cited as verified rather than derived because the opposite is the natural assumption,
        acting on it costs a party slot, and it was briefly believed to work the other way round
        (clayton-957.26.5). The simulator side of the same fact is pinned in
        `test_battle_compass_foresight`.
        """
        party = {"Smeargle": _moves("False Swipe", "Flash"),
                 "Stantler": _moves("Odor Sleuth", "Take Down")}
        warning = next(w for w in chip_warnings(GHOST, party) if "False Swipe" in w)
        self.assertIn("Odor Sleuth (Stantler)", warning)

    def test_foresight_counts_as_the_same_fix(self):
        party = {"Smeargle": _moves("False Swipe", "Foresight")}
        self.assertIn("Foresight (Smeargle)", chip_warnings(GHOST, party)[0])

    def test_a_scrappy_attacker_needs_no_warning_at_all(self):
        """The attacker-side route to the same removal. Reported as fine rather than as fixable,
        because there is nothing left to do about it."""
        party = {"Kangaskhan": _moves("False Swipe", "Fake Out")}
        self.assertEqual(chip_warnings(GHOST, party, {"Kangaskhan": "Scrappy"}), [])

    def test_scrappy_on_the_WRONG_pokemon_does_not_help(self):
        """It is the attacker's ability, so it has to be on whoever holds the False Swipe."""
        party = {"Smeargle": _moves("False Swipe"), "Kangaskhan": _moves("Fake Out")}
        warnings = chip_warnings(GHOST, party, {"Kangaskhan": "Scrappy"})
        self.assertTrue(any("False Swipe" in w for w in warnings))

    def test_abilities_are_optional(self):
        """The check has to work on a half-configured hunt, where nothing has an ability yet."""
        self.assertEqual(len(chip_warnings(GHOST, BARE_SMEARGLE, None)), 1)


class TestWhatItStaysQuietAbout(unittest.TestCase):
    """A warning has to earn its line — the module's own rule, and the reason the panel gets
    read at all."""

    def test_a_target_with_no_immunity_is_completely_silent(self):
        self.assertEqual(chip_warnings(PLAIN, BARE_SMEARGLE), [])

    def test_a_ghost_target_with_the_fix_aboard_still_warns_but_only_once(self):
        """It is a reminder rather than a blocker, and one line is the whole of it."""
        self.assertEqual(len(chip_warnings(GHOST, ARMED_SMEARGLE)), 1)

    def test_a_pure_status_pokemon_is_not_a_coverage_gap(self):
        """A dedicated paralyzer or a Flash mule carries no attacks on purpose. Reporting it
        would fire on a legitimate party member every single time."""
        party = {"Magneton": _moves("Thunder Wave", "Light Screen", "Screech")}
        self.assertEqual(chip_warnings(GHOST, party), [])

    def test_an_empty_party_says_nothing(self):
        """Unlike `access_warnings`, which can answer before a party exists: "nothing can damage
        it" is trivially true of no party and tells the player only that they have not finished
        configuring."""
        self.assertEqual(chip_warnings(GHOST, {}), [])

    def test_an_unknown_target_says_nothing(self):
        self.assertEqual(chip_warnings("pikachu", BARE_SMEARGLE), [])

    def test_a_pokemon_with_one_working_attack_is_not_reported(self):
        """Dragon Claw gets through, so Giratina is not a wall to this Pokemon — and a warning
        about its other move belongs to the interview, not to a pre-run blocker."""
        party = {"Dragonite": _moves("Dragon Claw", "Body Slam")}
        self.assertEqual(chip_warnings(GHOST, party), [])


class TestTheGeneralCoverageCase(unittest.TestCase):
    """Beyond False Swipe: a Pokemon whose whole attacking half is blocked."""

    def test_an_all_normal_attacker_is_reported(self):
        party = {"Snorlax": _moves("Body Slam", "Hyper Fang")}
        warnings = chip_warnings(GHOST, party)
        self.assertEqual(len(warnings), 1)
        self.assertIn("Snorlax", warnings[0])
        self.assertIn("until it is identified", warnings[0])

    def test_an_unfixable_block_is_said_to_be_unfixable(self):
        """Levitate, which a Foresight does not touch — the ROM tests it before the table walk.
        Offering a fix here would send the player to find a move that cannot help."""
        party = {"Donphan": _moves("Earthquake", "Magnitude")}
        warning = chip_warnings(GHOST, party)[0]
        self.assertIn("Levitate", warning)
        self.assertNotIn("Odor Sleuth", warning)
        self.assertNotIn("identified", warning)

    def test_one_problem_is_not_reported_twice(self):
        """A Smeargle whose only attack is a blocked False Swipe is covered by the specific
        warning; the general one must not also fire on it."""
        party = {"Smeargle": _moves("False Swipe", "Spore", "Flash")}
        warnings = chip_warnings(GHOST, party)
        self.assertEqual(len(warnings), 1)
        self.assertIn("False Swipe", warnings[0])


class TestThePanelRendersIt(unittest.TestCase):
    """The check is only worth having if it reaches the screen. The facade half is tested with a
    real `hunt_readiness` call in `test_app_hunt_facade`; this is the markup contract."""

    def test_the_panel_renders_it(self):
        from pathlib import Path

        html = (Path(__file__).resolve().parent.parent / "app" / "web" / "index.html").read_text()
        self.assertIn("const chip = r.chip || [], trap = r.trap || [];", html)
        self.assertIn("Chipping it down", html)
        # The trap panel moved in directly underneath -- same kind of question, and on a roamer
        # the trap comes first in time (notes/roamers.md sec 10.1).
        self.assertIn("${reach}${chipping}${trapping}", html)


class TestEveryConfiguredTarget(unittest.TestCase):
    """A sweep, so a target added later cannot quietly break the check."""

    def test_the_check_runs_against_every_target_without_raising(self):
        for key in supported():
            with self.subTest(key):
                chip_warnings(key, ARMED_SMEARGLE, {"Smeargle": "Own Tempo"})

    def test_only_the_ghosts_warn_about_false_swipe(self):
        """Which is both a check on the message and a statement about the target list: Giratina
        is the only Ghost in it, and the only target False Swipe cannot touch."""
        warned = {key for key in supported()
                  if any("False Swipe" in w for w in chip_warnings(key, BARE_SMEARGLE))}
        ghosts = {key for key in supported() if "Ghost" in target_types(key)}
        self.assertEqual(warned, ghosts)
        self.assertTrue(ghosts, "no Ghost target configured — this test has stopped testing")

    def test_a_foresight_is_always_the_whole_answer_for_a_false_swipe(self):
        """No target's ability blocks Normal -- Levitate is Ground-only and nothing else in the
        column is an immunity -- so against every Ghost target the warning's promise holds. Worth
        pinning, because the message says "until it is identified" and that would be a false
        promise if some ability could outlive the fix.
        """
        ghosts = [key for key in supported() if "Ghost" in target_types(key)]
        self.assertTrue(ghosts, "no Ghost target configured -- this test has stopped testing")
        for key in ghosts:
            with self.subTest(key, ability=target_ability(key)):
                warning = next(w for w in chip_warnings(key, ARMED_SMEARGLE)
                               if "False Swipe" in w)
                self.assertIn("until it is identified", warning)
                # ...and the fix really does silence it, rather than only being offered.
                armed = dict(ARMED_SMEARGLE)
                self.assertEqual(
                    [w for w in chip_warnings(key, armed, {"Smeargle": "Scrappy"})
                     if "False Swipe" in w], [])


if __name__ == "__main__":
    unittest.main()
