"""Speed ties that one of OUR OWN moves can create.

`readiness.speed_checks` has always asked "could these two Pokemon tie as they stand", and
enumerates every Speed stage the TARGET can reach because Ancient Power is in two configured
movesets. What it treats as constant is our own Speed — and that stopped being true the moment
the pure stat-stage family went in: Agility and Rock Polish raise our Speed two stages at a time,
Dragon Dance one, and String Shot, Cotton Spore and Scary Face lower the target's.

Either direction can land the two sides on exactly equal effective Speed, and a tie is not a
small error: it spends rolls this simulator does not model (notes/ss_rng/speed.md, sec 11.4), so
every turn after it is unmatchable. Worse than a standing tie, in one way — this one appears
mid-run, on a turn the player chose, long after the configuration screen said the party was fine.

Hence a warning rather than a refusal, and hence a validation of its own rather than more rows in
the existing table: only some stage combinations tie, the move may be exactly the right play, and
what the player needs is to be told which stages to avoid.

Two rules worth stating because they are easy to get wrong:

* **A target Speed drop is attributed to the whole party, not to its holder.** A wild target
  never switches out, so the drop is permanent — the Pokemon that used Cotton Spore may be back
  on the bench by the time the tie matters.
* **Ties nobody's move caused are not reported here.** A combination at our stage 0 and a target
  stage the target reaches on its own belongs to `speed_checks`, which enumerates exactly those.

(clayton-4wr.1.8)
"""
import unittest

from claytonlib.battle.readiness import (
    PARALYSIS_SPEED_DIVISOR, SPEED_STAGE_EFFECTS, SpeedMoveTie, speed_move_ties,
    speed_move_warnings, speed_moves,
)
from claytonlib.moves import resolve_move

#: Azelf Lv50, Timid, 31 Speed IVs — the number the facade would hand in.
TARGET = 132


def M(*names):
    return [resolve_move(name) for name in names]


class TestTheTableAgreesWithTheSimulator(unittest.TestCase):
    """`SPEED_STAGE_EFFECTS` is declared in `battle/readiness.py` and the simulator reads its own
    copy out of `battle_compass/sim.py`.

    Two copies because the dependency only runs one way -- `battle/` is the shared core that
    `battle_compass` builds on -- and two copies is exactly how a Speed move gets added to one
    and forgotten in the other. This is the test that stops that.
    """

    def test_every_speed_mover_in_the_sim_is_here(self):
        from claytonlib.battle_compass.sim import PRIMARY_SELF_RAISES, PRIMARY_STAT_DROPS

        expected = {}
        for effect, pairs in PRIMARY_SELF_RAISES.items():
            for field, stages in pairs:
                if field == "speed_stage":
                    expected[effect] = ("self", stages)
        for effect, pairs in PRIMARY_STAT_DROPS.items():
            for field, stages in pairs:
                if field == "speed_stage":
                    expected[effect] = ("target", -stages)
        self.assertEqual(SPEED_STAGE_EFFECTS, expected)

    def test_nothing_here_is_absent_from_the_sim(self):
        """The other direction: a row here with no simulator support would warn about a move the
        simulation silently ignores."""
        from claytonlib.battle_compass.sim import MODELLED_OUR_EFFECTS

        for effect in SPEED_STAGE_EFFECTS:
            with self.subTest(effect=effect):
                self.assertIn(effect, MODELLED_OUR_EFFECTS)

    def test_it_classifies_the_six_moves_and_nothing_else(self):
        classified = {m.name: (whose, stages) for m, whose, stages in speed_moves(
            M("Agility", "Rock Polish", "Dragon Dance", "String Shot", "Cotton Spore",
              "Scary Face", "Swords Dance", "Taunt", "Thunder Wave"))}
        self.assertEqual(classified, {
            "Agility": ("self", 2), "Rock Polish": ("self", 2),
            "Dragon Dance": ("self", 1),
            "String Shot": ("target", -1),
            "Cotton Spore": ("target", -2), "Scary Face": ("target", -2),
        })


class TestItFindsTheTies(unittest.TestCase):

    def test_a_self_raise_that_lands_on_the_targets_speed(self):
        """66 at +2 is 132, which is the target exactly."""
        ties = speed_move_ties({"Krow": 66}, {"Krow": M("Agility", "Taunt")}, TARGET)
        self.assertEqual(len(ties), 1)
        self.assertEqual((ties[0].our_stage, ties[0].our_speed), (2, 132))
        self.assertFalse(ties[0].target_paralyzed)
        self.assertEqual(ties[0].via, "Agility")

    def test_one_stage_at_a_time_is_enumerated_too(self):
        """Dragon Dance is +1, so a tie can sit at a stage Agility cannot reach."""
        ties = speed_move_ties({"Nite": 88}, {"Nite": M("Dragon Dance")}, TARGET)
        self.assertEqual([t.our_stage for t in ties], [1])

    def test_repeated_use_is_enumerated(self):
        """Two Agilities is +4 and three is +6; a tie at +4 is as real as one at +2."""
        ties = speed_move_ties({"Slow": 44}, {"Slow": M("Agility")}, TARGET)
        self.assertIn(4, [t.our_stage for t in ties])

    def test_a_target_drop_that_lands_on_our_speed(self):
        ties = speed_move_ties({"Chipper": 88}, {"Chipper": M("String Shot")}, TARGET)
        self.assertEqual(len(ties), 1)
        self.assertEqual((ties[0].target_stage, ties[0].target_speed), (-1, 88))

    def test_a_drop_is_attributed_to_the_whole_party(self):
        """A wild target never switches out, so a Cotton Spore from the chipper can tie a
        Pokemon that was not even out when it landed."""
        ties = speed_move_ties(
            {"Smeargle": 177, "Krow": 66},
            {"Smeargle": M("Cotton Spore"), "Krow": M("Taunt")}, TARGET)
        self.assertEqual([t.ours for t in ties], ["Krow"])
        self.assertEqual(ties[0].via, "Cotton Spore")
        self.assertEqual(ties[0].via_owner, "Smeargle")

    def test_the_paralyzed_target_rows_need_a_paralyzer(self):
        """A paralyzed target is a second full set of stage combinations to tie at, and it is
        only reachable if somebody in the party can inflict it."""
        speeds, sets_ = {"Tiny": 16}, {"Tiny": M("Cotton Spore")}
        self.assertEqual(speed_move_ties(speeds, sets_, TARGET), [])
        ties = speed_move_ties(speeds, sets_, TARGET, target_can_be_paralyzed=True)
        self.assertEqual(len(ties), 1)
        self.assertTrue(ties[0].target_paralyzed)
        self.assertEqual(ties[0].target_speed, 66 // PARALYSIS_SPEED_DIVISOR)

    def test_a_drop_stacks_on_top_of_the_targets_own_boost(self):
        """The reason the two stage sets are composed rather than unioned. Cotton Spore moves
        two stages, so from 0 it can only reach -2, -4 and -6 -- the ODD negative stages exist
        only if the target boosted itself first, and -1 is where this tie hides.
        """
        self.assertEqual(speed_move_ties({"K": 88}, {"K": M("Cotton Spore")}, TARGET), [])
        ties = speed_move_ties({"K": 88}, {"K": M("Cotton Spore")}, TARGET,
                               target_own_speed_stages=tuple(range(7)))
        self.assertEqual([t.target_stage for t in ties], [-1])


class TestItStaysQuietWhenItShould(unittest.TestCase):

    def test_a_party_with_no_speed_move_is_silent(self):
        self.assertEqual(
            speed_move_ties({"Krow": 66}, {"Krow": M("Taunt", "Haze")}, TARGET,
                            target_can_be_paralyzed=True), [])

    def test_a_speed_move_that_cannot_reach_a_tie_is_silent(self):
        """Having the move is not the warning; being able to tie with it is."""
        self.assertEqual(
            speed_move_ties({"Fast": 199}, {"Fast": M("Agility")}, TARGET), [])

    def test_a_standing_tie_is_left_to_the_other_check(self):
        """At stage 0 on both sides the party already ties, which `speed_checks` reports. Saying
        it twice buries the new information under the old."""
        ties = speed_move_ties({"Krow": TARGET}, {"Krow": M("Agility")}, TARGET)
        self.assertNotIn(0, [t.our_stage for t in ties])

    def test_a_tie_the_target_reaches_on_its_own_is_not_blamed_on_our_move(self):
        """Our stage 0 plus a target stage from Ancient Power is `speed_checks`'s row, and
        crediting it to a String Shot that had nothing to do with it would be worse than silence.
        """
        ties = speed_move_ties({"Krow": 198}, {"Krow": M("String Shot")}, TARGET,
                               target_own_speed_stages=tuple(range(7)))
        self.assertEqual([t for t in ties if t.our_stage == 0 and t.target_stage > 0], [])


class TestTheWarnings(unittest.TestCase):

    def test_one_line_per_move_rather_than_per_combination(self):
        """A Dragon Dance against a target that both boosts and can be paralyzed ties at three
        separate combinations, and three lines saying the same thing is how a real warning gets
        scrolled past."""
        ties = speed_move_ties({"Nite": 88}, {"Nite": M("Dragon Dance")}, TARGET,
                               target_can_be_paralyzed=True,
                               target_own_speed_stages=tuple(range(7)))
        self.assertEqual(len(ties), 3)
        self.assertEqual(len(speed_move_warnings(ties)), 1)

    def test_it_names_the_move_the_stage_and_the_number(self):
        ties = speed_move_ties({"Krow": 66}, {"Krow": M("Agility")}, TARGET)
        (line,) = speed_move_warnings(ties)
        self.assertIn("Agility", line)
        self.assertIn("Krow at +2", line)
        self.assertIn("132", line)

    def test_it_says_what_a_tie_costs_and_what_to_do(self):
        """The reason matters as much as the fact: a player who does not know a tie is a DESYNC
        reads this as a tie-break coin flip and ignores it."""
        ties = speed_move_ties({"Krow": 66}, {"Krow": M("Agility")}, TARGET)
        (line,) = speed_move_warnings(ties)
        self.assertIn("does not model", line)
        self.assertIn("stops matching", line)

    def test_a_borrowed_move_says_whose_it_is(self):
        ties = speed_move_ties(
            {"Smeargle": 177, "Krow": 66},
            {"Smeargle": M("Cotton Spore"), "Krow": M("Taunt")}, TARGET)
        (line,) = speed_move_warnings(ties)
        self.assertIn("Cotton Spore (Smeargle's)", line)
        self.assertIn("Krow", line)

    def test_the_paralyzed_row_says_so(self):
        ties = speed_move_ties({"Tiny": 16}, {"Tiny": M("Cotton Spore")}, TARGET,
                               target_can_be_paralyzed=True)
        (line,) = speed_move_warnings(ties)
        self.assertIn("paralyzed", line)

    def test_no_ties_means_no_lines(self):
        self.assertEqual(speed_move_warnings([]), [])


class TestTheFacadeAsksTheQuestion(unittest.TestCase):
    """End to end through `hunt_readiness`, because the two dicts it joins are keyed
    differently -- `our_speeds` carries the held item in its label and the movesets do not."""

    def setUp(self):
        import tempfile

        from app.facade import Facade
        from app.store import FileStore
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))
        self.profile = self.api.create_profile({"name": "P", "game": "platinum"})["id"]

    def tearDown(self):
        self._tmp.cleanup()

    #: Azelf Lv50 Timid with 31 Speed IVs, as `derive_species_stats` gives it -- which is what
    #: the facade hands in, and a different number from the forced Lax spread the log fixtures
    #: use. Paralyzed it is 37.
    DERIVED_SPEED = 148

    def _readiness(self, *party, held_item="", name="H"):
        ids = []
        for name, speed, moves, ability in party:
            added = self.api.add_party_pokemon(self.profile, {
                "name": name, "species": "honchkrow", "level": 50, "ability": ability,
                "stats": {"hp": 200, "atk": 120, "def": 100, "spa": 90, "spd": 95,
                          "spe": speed},
                "moveset": list(moves)})
            ids.append(added["pokemon_id"])
        hunt = self.api.create_hunt({"profile_id": self.profile, "name": name})
        doc = dict(hunt)
        doc.update({
            "target": {"species": "azelf", "level": 50, "nature": "Timid",
                       "ivs": {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}},
            "key_seed": 0x961502A4, "initial_time": "2026-06-15T21:30:30",
            "vector_ms": 300000,
            "party": [{"pokemon_id": i, "held_item": held_item} for i in ids]})
        self.api.save_hunt(doc)
        return self.api.hunt_readiness(doc["id"])

    def test_the_derived_target_speed_is_what_it_asks_against(self):
        """Stated so the fixtures below are checkable rather than magic."""
        result = self._readiness(("Krow", 74, ("Taunt",), "Insomnia"), name="H0")
        self.assertEqual(result["speed"]["target_speed"], self.DERIVED_SPEED)

    def test_it_reports_a_tie_an_agility_would_create(self):
        """74 at +2 Speed is 148, which is the target exactly."""
        result = self._readiness(("Krow", 74, ("Agility", "Taunt"), "Insomnia"), name="H1")
        self.assertTrue(result["speed"]["move_tie_warnings"])
        self.assertIn("Agility", result["speed"]["move_tie_warnings"][0])
        self.assertEqual([t["our_stage"] for t in result["speed"]["move_ties"]], [2])

    def test_a_party_with_no_speed_move_gets_no_line(self):
        result = self._readiness(("Krow", 74, ("Taunt", "Haze"), "Insomnia"), name="H2")
        self.assertEqual(result["speed"]["move_tie_warnings"], [])

    def test_a_speed_move_that_cannot_reach_a_tie_gets_no_line(self):
        """Carrying the move is not the warning."""
        result = self._readiness(("Krow", 71, ("Agility", "Taunt"), "Insomnia"), name="H3")
        self.assertEqual(result["speed"]["move_tie_warnings"], [])

    def test_the_paralyzed_rows_appear_only_with_a_paralyzer_in_the_party(self):
        """The target at -2 Speed is 74 and paralyzed is 18, so an 18-Speed Pokemon with a Cotton
        Spore ties only when somebody can also paralyze."""
        without = self._readiness(("Tiny", 18, ("Cotton Spore",), "Insomnia"), name="H4")
        self.assertEqual(without["speed"]["move_ties"], [])
        with_tw = self._readiness(("Tiny", 18, ("Cotton Spore",), "Insomnia"),
                                  ("Zap", 300, ("Thunder Wave",), "Insomnia"), name="H5")
        rows = [t for t in with_tw["speed"]["move_ties"] if t["target_paralyzed"]]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["target_stage"], -2)

    def test_a_held_item_label_still_joins_to_the_moveset(self):
        """`our_speeds` is keyed "Krow (Choice Scarf)" and the movesets by "Krow"; a join on the
        label alone finds no moves and warns about nothing.

        25 scarfed is 37, and 37 at +6 Speed is 148 -- so the tie exists only once the item is
        applied, which also makes this the test that the item reaches the check at all.
        """
        result = self._readiness(("Krow", 25, ("Agility", "Taunt"), "Insomnia"),
                                 held_item="Choice Scarf", name="H6")
        self.assertTrue(result["speed"]["move_tie_warnings"],
                        "the scarfed label lost its moveset")
        self.assertIn("Choice Scarf", result["speed"]["move_tie_warnings"][0])
        self.assertEqual([t["our_stage"] for t in result["speed"]["move_ties"]], [6])


if __name__ == "__main__":
    unittest.main()


class TestInsomniaStoppedClaimingItCanParalyze(unittest.TestCase):
    """A side effect of building the gate, and a real omission it exposed.

    `can_inflict` treats an ability it does not recognise as capable, deliberately: a spurious
    row costs a line of advice and a missing one costs an unmodelled desync. But `_INERT_ABILITIES`
    is what keeps that from swallowing everything, and **Insomnia was not in it** -- the headline
    ability of the wall the whole support kit is built around (clayton-4wr.1). So every party
    containing a Honchkrow answered "yes, we can paralyze" on the strength of its ability alone,
    and the paralyzed-target half of this validation would have been ungated in practice.

    No configured TARGET has any of the added abilities, which is why nothing else moved.
    """

    def test_an_insomnia_holder_cannot_paralyze_by_ability_alone(self):
        from claytonlib.battle_compass.sim import can_inflict
        from claytonlib.battle_compass.state import Battler, Status

        wall = Battler(name="Krow", level=50, types=("Dark", "Flying"), stats={"hp": 1},
                       moves=("Taunt",), pp=(20,), ability="Insomnia")
        self.assertFalse(can_inflict(wall, Status.PARALYSIS))

    def test_a_move_still_counts_whatever_the_ability_is(self):
        from claytonlib.battle_compass.sim import can_inflict
        from claytonlib.battle_compass.state import Battler, Status

        zapper = Battler(name="Z", level=50, types=("Electric",), stats={"hp": 1},
                         moves=("Thunder Wave",), pp=(20,), ability="Insomnia")
        self.assertTrue(can_inflict(zapper, Status.PARALYSIS))

    def test_static_is_untouched(self):
        """The ability route is the whole reason `can_inflict` reads abilities at all."""
        from claytonlib.battle_compass.sim import can_inflict
        from claytonlib.battle_compass.state import Battler, Status

        shocker = Battler(name="S", level=50, types=("Electric",), stats={"hp": 1},
                          moves=("Tackle",), pp=(20,), ability="Static")
        self.assertTrue(can_inflict(shocker, Status.PARALYSIS))

    def test_an_unknown_ability_is_still_assumed_capable(self):
        """The default is not being narrowed, only the known-inert list extended."""
        from claytonlib.battle_compass.sim import can_inflict
        from claytonlib.battle_compass.state import Battler, Status

        mystery = Battler(name="M", level=50, types=("Normal",), stats={"hp": 1},
                          moves=("Tackle",), pp=(20,), ability="Some New Ability")
        self.assertTrue(can_inflict(mystery, Status.PARALYSIS))
