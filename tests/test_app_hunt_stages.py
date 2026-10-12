"""Stat stages on the run page, for both sides.

Nothing published them before this -- not the snapshot, not the page. That was defensible while
our own stat-change moves did nothing (clayton-957.10.2): against Suicune the only stages in a
whole run were our Attack from Aurora Beam and our Sp. Def from Luster Purge, both inferable from
the damage we took.

It stopped being defensible the moment Flash, Screech, Charm and Intimidate started working. A
Ho-Oh run spends most of its turns moving three of the TARGET's stages at once -- accuracy down
six, Attack down five, Defence down six -- and the counts are what decide when to switch. Worse,
Ancient Power raises every stat by one, so a single proc silently cancels an Intimidate and puts
Sacred Fire back into one-shot range against Magneton (204-240 against 171 HP). A player cannot
hold that in their head across twenty turns, and the failure mode is losing a Pokemon to a number
they had no way to see.

Static checks on the page, as the rest of the run-page tests are -- there is no JS engine here --
plus live assertions on the facade payload they read from.
"""
import pathlib
import unittest

from claytonlib.battle_compass.hunt_session import STAGE_FIELDS, move_info, stat_stages
from claytonlib.battle_compass.state import Battler, Status
from claytonlib.moves import resolve_move

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"
HTML = INDEX.read_text()


def hooh(**kwargs):
    return Battler(name="Ho-Oh", level=70, types=("Fire", "Flying"),
                   stats={"hp": 250, "atk": 208, "def": 152, "spa": 180, "spd": 242, "spe": 152},
                   moves=("Sacred Fire", "Punishment", "Ancient Power", "Safeguard"),
                   pp=(5, 5, 5, 25), ability="Pressure", **kwargs)


def ampharos():
    return Battler(name="Ampharos", level=94, types=("Electric",),
                   stats={"hp": 314, "atk": 137, "def": 184, "spa": 336, "spd": 211, "spe": 143},
                   moves=("Light Screen", "Flash"), pp=(30, 20), ability="Static")


class TestTheFacadePublishesStages(unittest.TestCase):
    def test_a_neutral_battler_reports_nothing(self):
        """So an ordinary run looks exactly as it did -- no row of seven dashes."""
        self.assertEqual(stat_stages(hooh()), {})

    def test_every_stage_a_battler_has_is_reachable(self):
        """Guards the table against a renamed field, which would silently stop reporting one."""
        mon = hooh()
        for label, field in STAGE_FIELDS:
            self.assertTrue(hasattr(mon, field), f"{label} names no such field: {field}")

    def test_the_three_the_ho_oh_plan_moves(self):
        mon = hooh(accuracy_stage=-6, atk_stage=-5, def_stage=-6)
        self.assertEqual(stat_stages(mon),
                         {"atk": -5, "def": -6, "accuracy": -6})

    def test_a_raised_stage_reports_too(self):
        """Ancient Power raises every one of them, which is the case worth seeing."""
        self.assertEqual(stat_stages(hooh(atk_stage=1, speed_stage=1)),
                         {"atk": 1, "spe": 1})

    def test_an_ancient_power_proc_shows_as_cancelling_an_intimidate(self):
        """The specific thing a player would otherwise miss: -1 and +1 net to nothing, and the
        page then correctly shows no Attack stage at all -- which is the honest reading."""
        self.assertNotIn("atk", stat_stages(hooh(atk_stage=0)))


class TestMoveInfoCarriesTheConsequence(unittest.TestCase):
    """The stage is the cause; the accuracy is what a player acts on."""

    def test_six_flashes_are_visible_as_accuracy_numbers(self):
        info = move_info(hooh(accuracy_stage=-6), ampharos())
        by_name = {m["name"]: m for m in info}
        self.assertEqual(by_name["Sacred Fire"]["effective_accuracy"], 31)
        self.assertEqual(by_name["Punishment"]["effective_accuracy"], 33)
        self.assertEqual(by_name["Ancient Power"]["effective_accuracy"], 33)

    def test_unmodified_accuracy_is_reported_unchanged(self):
        by_name = {m["name"]: m for m in move_info(hooh(), ampharos())}
        self.assertEqual(by_name["Sacred Fire"]["effective_accuracy"], 95)
        self.assertEqual(by_name["Punishment"]["effective_accuracy"], 100)

    def test_a_move_that_bypasses_the_check_reports_zero(self):
        """Not the same as a 0% chance, which is why the page leaves it unannotated."""
        by_name = {m["name"]: m for m in move_info(hooh(accuracy_stage=-6), ampharos())}
        self.assertEqual(by_name["Safeguard"]["effective_accuracy"], 0)
        self.assertEqual(resolve_move("Safeguard").accuracy, 0)

    def test_an_empty_slot_still_answers(self):
        thin = Battler(name="Chatot", level=20, types=("Normal", "Flying"),
                       stats={"hp": 62, "atk": 34, "def": 26, "spa": 44, "spd": 25, "spe": 44},
                       moves=("Growl",), pp=(40,))
        info = move_info(thin, hooh())
        self.assertEqual(len(info), 1)
        self.assertTrue(info[0]["known"])


class TestThePageRendersThem(unittest.TestCase):
    def test_the_side_card_calls_the_stage_renderer(self):
        self.assertIn("${hrStages(m)}", HTML,
                      "the side card must render stages, or they are published and unseen")

    def test_both_sides_get_it_because_the_renderer_is_shared(self):
        """`hrSide` draws ours and the target from one function, so one call covers both."""
        self.assertEqual(HTML.count("function hrSide("), 1)
        self.assertEqual(HTML.count("${hrStages(m)}"), 1)

    def test_a_capped_stage_says_so(self):
        """Six Flashes and three Screeches are both counts toward the -6 floor, so the page has to
        say when the next one would do nothing rather than leaving it to be worked out."""
        self.assertIn("v <= -6 || v >= 6", HTML)
        self.assertIn("at the limit", HTML)

    def test_the_accuracy_suffix_sits_next_to_the_move(self):
        self.assertIn("hrAccSuffix(m, i)", HTML)
        self.assertIn("accuracy after stat stages", HTML)

    def test_bypassing_the_check_is_not_rendered_as_zero_percent(self):
        """`!acc` catches the 0 that means "no accuracy check", so Safeguard shows no number."""
        self.assertIn("if (!acc || acc >= 100) return \"\";", HTML)

    def test_the_spread_modal_shows_the_stage_beside_the_stat(self):
        self.assertIn("hrStageNote(m, k)", HTML)
        self.assertIn('hrStageRow(m, "accuracy", "Accuracy")', HTML)
        self.assertIn('hrStageRow(m, "evasion", "Evasion")', HTML)

    def test_drops_and_boosts_are_coloured_apart(self):
        """A drop on the TARGET is good news and a drop on OURS is bad, but the colour tracks the
        sign rather than the side -- the label already says whose card it is."""
        self.assertIn("#7fd4a0", HTML)
        self.assertIn("#e8a0a0", HTML)
