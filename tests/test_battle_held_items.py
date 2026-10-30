"""Held items the simulator cannot model: warn before the encounter, never block.

A misconfigured held item SHOULD desynchronise a run -- the simulator is right once told, and the
only way to tell it is this field. What was missing is hearing about it *before* the encounter
rather than as a turn-2 contradiction whose message blames the candidate window.

The measured stakes, from the hooh1 replay (57 turns, one item removed at a time):

    no Silk Scarf (Smeargle)    -> 11 mismatching turns, every False Swipe low by ~1/6
    no Leftovers (Ampharos)     ->  2 mismatching turns, HP low by 19 while it is out
    no Choice Scarf (Magneton)  -> 56 of 57 turns wrong

That last one is the reason `HAZARDOUS_UNMODELLED_ITEMS` exists as a separate category: it fails
in KIND, not degree -- 107 * 1.5 = 160 beats Ho-Oh's 152, so turn order flips on turn 2 and
nothing after it matches.

clayton-957.10.15.
"""
import unittest

from claytonlib.battle.damage import item_key
from claytonlib.battle.readiness import (
    CHOICE_ITEMS, HAZARDOUS_UNMODELLED_ITEMS, MODELLED_HELD_ITEMS, MOVES_LAST_ITEMS,
    SPEED_HALVING_ITEMS, unmodelled_held_items,
)

ALLOWED = frozenset().union(*MODELLED_HELD_ITEMS.values())


class TestTheAllowlist(unittest.TestCase):
    def test_it_is_assembled_from_the_tables_that_actually_read_the_items(self):
        """Assembled rather than hand-listed, because a hand-list goes stale the first time a
        mechanism is added -- and stale here means FAILING TO WARN, the direction that costs a
        run."""
        from claytonlib.battle.damage import (
            ACCURACY_RAISING_ITEMS, ACCURACY_REDUCING_ITEMS, LIGHT_CLAY, TYPE_ENHANCING_ITEMS,
        )
        from claytonlib.battle.readiness import STATUS_RESTORE_ITEMS
        from claytonlib.battle_compass.sim import LEFTOVERS

        expected = (set(TYPE_ENHANCING_ITEMS) | set(CHOICE_ITEMS) | set(SPEED_HALVING_ITEMS)
                    | set(MOVES_LAST_ITEMS) | set(ACCURACY_REDUCING_ITEMS)
                    | set(ACCURACY_RAISING_ITEMS) | set(STATUS_RESTORE_ITEMS)
                    | {item_key(LEFTOVERS), item_key(LIGHT_CLAY)})
        self.assertEqual(ALLOWED, expected)

    def test_leftovers_is_spelled_in_exactly_one_place(self):
        """`sim` owns the divisor and the tick; `readiness` owns the NAME, so the allowlist can
        be built without the shared core importing from a module that depends on it."""
        from claytonlib.battle import readiness
        from claytonlib.battle_compass import sim

        self.assertIs(sim.LEFTOVERS, readiness.LEFTOVERS)

    def test_the_items_the_lugia_plan_actually_uses_are_all_modelled(self):
        for item in ("Silk Scarf", "Leftovers", "Choice Scarf", "Light Clay", "Brightpowder"):
            with self.subTest(item):
                self.assertIn(item_key(item), ALLOWED)

    def test_nothing_is_both_allowed_and_hazardous(self):
        self.assertEqual(ALLOWED & set(HAZARDOUS_UNMODELLED_ITEMS), frozenset())

    def test_brightpowder_moved_from_hazardous_to_allowed(self):
        """It was in the dangerous list until clayton-957.28 modelled it. Pinned so that the two
        tables cannot both claim it."""
        self.assertIn(item_key("BrightPowder"), ALLOWED)
        self.assertNotIn(item_key("BrightPowder"), HAZARDOUS_UNMODELLED_ITEMS)
        self.assertIn(item_key("Lax Incense"), ALLOWED)

    def test_every_group_is_non_empty_and_described(self):
        for why, names in MODELLED_HELD_ITEMS.items():
            with self.subTest(why):
                self.assertTrue(names)
                self.assertGreater(len(why), 10, "the key is the player-facing explanation")


class TestTheWarnings(unittest.TestCase):
    def test_a_fully_modelled_party_is_silent(self):
        self.assertEqual(unmodelled_held_items({
            "Smeargle": "Silk Scarf", "Ampharos": "Leftovers",
            "Magneton": "Choice Scarf"}), [])

    def test_a_hazardous_item_says_how_it_fails_and_to_remove_it(self):
        (warning,) = unmodelled_held_items({"Chatot": "Quick Claw"})
        self.assertIn("Chatot", warning)
        self.assertIn("Quick Claw", warning)
        self.assertIn("flips turn order", warning)
        self.assertTrue(warning.startswith("Take "), warning)

    def test_an_ordinary_unmodelled_item_is_reported_more_gently(self):
        (warning,) = unmodelled_held_items({"Natu": "Life Orb"})
        self.assertIn("Life Orb", warning)
        self.assertIn("not modelled", warning)
        self.assertFalse(warning.startswith("Take "))
        self.assertIn("harmless if inert", warning)

    def test_a_blank_item_is_SILENT(self):
        """Holding nothing is the common case, not a suspicious one.

        An earlier version warned here, reasoning that all three hooh1 items had to be inferred
        from the logs afterwards. But it then fired on most of the party on every readiness
        check, and noise that trains the reader to skip the panel costs more than the rare
        forgotten Leftovers it catches.
        """
        for blank in ("", "   ", None):
            with self.subTest(blank=blank):
                self.assertEqual(unmodelled_held_items({"Tentacruel": blank}), [])

    def test_a_whole_party_holding_nothing_produces_no_warnings_at_all(self):
        self.assertEqual(
            unmodelled_held_items({n: "" for n in ("Natu", "Magneton", "Ampharos")}), [])

    def test_case_and_whitespace_do_not_matter(self):
        self.assertEqual(unmodelled_held_items({"A": "  SILK SCARF "}), [])

    def test_the_name_of_the_holder_is_always_in_the_message(self):
        """Six party members and one warning is useless without it."""
        for item in ("Quick Claw", "Life Orb"):
            with self.subTest(item=item):
                (warning,) = unmodelled_held_items({"Tentacruel": item})
                self.assertIn("Tentacruel", warning)

    def test_every_hazardous_item_produces_the_harsher_message(self):
        for item in HAZARDOUS_UNMODELLED_ITEMS:
            with self.subTest(item):
                (warning,) = unmodelled_held_items({"X": item})
                self.assertTrue(warning.startswith("Take X's "), warning)

    def test_an_empty_party_is_silent_rather_than_an_error(self):
        self.assertEqual(unmodelled_held_items({}), [])


class TestItIsAdvisoryThroughTheFacade(unittest.TestCase):
    def test_a_hazardous_item_does_not_become_a_hard_error(self):
        import tempfile

        from app.facade import Facade
        from app.store import FileStore

        api = Facade(FileStore(tempfile.mkdtemp()))
        profile = api.create_profile({"name": "Gold"})
        pid = api.add_party_pokemon(profile["id"], dict(
            name="Smeargle", species="smeargle", level=60, ability="Technician",
            stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
            moveset=["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
            max_pp={"1": 40, "2": 5, "3": 20, "4": 15}))["pokemon_id"]
        hunt = api.create_hunt({
            "name": "H", "profile_id": profile["id"], "capture_ball": "Fast Ball",
            "target": {"species": "suicune", "level": 40, "nature": "Bold",
                       "ivs": {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}},
            "party": [{"pokemon_id": pid, "held_item": "Quick Claw"}],
            "key_seed": 0xEC1504DC, "initial_time": "2026-09-29T12:00:00",
            "vector_ms": 382791})
        readiness = api.hunt_readiness(hunt["id"])
        self.assertEqual(readiness["hard_errors"], [], "must not block")
        self.assertEqual(len(readiness["held_items"]), 1)
        self.assertIn("Quick Claw", readiness["held_items"][0])


if __name__ == "__main__":
    unittest.main()


class TestSpellingTolerance(unittest.TestCase):
    """Item names are typed from memory, and the in-game spellings are inconsistent.

    "BrightPowder" is one word on the item screen and "Bright Powder" is what most people write;
    "King's Rock" has an apostrophe that is easy to drop. Every item table is keyed on
    `damage.item_key` -- lowercase, alphanumerics only -- so all of those match.

    Checked for collisions before adopting: across all eight tables plus the hazardous list, the
    only two raw names that reduced to the same key were "never-melt ice" and "nevermeltice",
    which were already there as deliberate aliases for the same item. So the normaliser REPLACED
    the need for aliases rather than risking a wrong match.

    This matters more than cosmetics: a held item that silently fails to match desynchronises the
    whole run, which is the failure `unmodelled_held_items` exists to pre-empt.
    """

    def test_brightpowder_both_ways_round(self):
        for spelling in ("BrightPowder", "Bright Powder", "bright powder", "brightpowder",
                         "BRIGHT POWDER", "  Bright  Powder  "):
            with self.subTest(spelling):
                self.assertEqual(unmodelled_held_items({"X": spelling}), [],
                                 f"{spelling!r} should be recognised as modelled")

    def test_an_apostrophe_is_optional(self):
        for spelling in ("King's Rock", "Kings Rock", "kings rock", "KINGSROCK"):
            with self.subTest(spelling):
                (warning,) = unmodelled_held_items({"X": spelling})
                self.assertIn("flinch roll", warning,
                              f"{spelling!r} should be recognised as hazardous")

    def test_the_type_enhancing_items_too(self):
        for spelling in ("Silk Scarf", "silkscarf", "SILK SCARF"):
            with self.subTest(spelling):
                self.assertEqual(unmodelled_held_items({"X": spelling}), [])

    def test_the_message_echoes_what_the_PLAYER_typed(self):
        """Normalised for matching, not for display -- the warning has to name the thing they
        can see in their own field."""
        (warning,) = unmodelled_held_items({"X": "Life  Orb"})
        self.assertIn("Life  Orb", warning)

    def test_every_table_key_is_already_normalised(self):
        """Or a lookup through `item_key` would never reach it. Asserted over the tables rather
        than spot-checked, so a hand-added entry with a space fails here instead of silently
        never matching."""
        for why, names in MODELLED_HELD_ITEMS.items():
            for name in names:
                with self.subTest(why=why, name=name):
                    self.assertEqual(item_key(name), name)
        for name in HAZARDOUS_UNMODELLED_ITEMS:
            with self.subTest(name=name):
                self.assertEqual(item_key(name), name)

    def test_the_normaliser_does_not_merge_two_different_items(self):
        """The check that made this safe to adopt at all."""
        from claytonlib.battle.damage import TYPE_ENHANCING_ITEMS

        raw = (set(TYPE_ENHANCING_ITEMS) | set(HAZARDOUS_UNMODELLED_ITEMS)
               | frozenset().union(*MODELLED_HELD_ITEMS.values()))
        self.assertEqual(len({item_key(n) for n in raw}), len(raw))
