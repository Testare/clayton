"""`max_pp`'s key base, pinned from both sides.

`PartyPokemon.max_pp` is keyed by **1-based move number**, unlike every other slot index in this
project (`moveset`, `Action.move_slot`, `move_info`, the M1-M4 tokens are all 0-based). That is
not a design preference -- it is what the party form has always written and what every saved
profile holds.

`_configured_pp` indexed it with the 0-based slot instead. So move 2 got move 1's PP, move 3 got
move 2's, move 4's recorded PP was never read at all, and move 1 fell through to the base-PP
fallback -- which then looked like it was working. Everything the player SAW was 1-based and
self-consistent (the form, its read-back, the per-slot warning), so only the simulator was wrong,
and it was wrong by one slot in silence.

**It survived because no test crossed the boundary.** `test_app_hunt_models` and
`test_app_hunt_facade` wrote 1-based fixtures and exercised the model; `test_app_hunt_run` and
`test_app_hunt_seed_a` wrote 0-based fixtures and exercised the facade. Each agreed with the code
it tested. This file exists to be the test that spans both, using the key the PAGE writes.
"""
import pathlib
import re
import tempfile
import unittest

from app.facade import Facade
from app.models import PartyPokemon
from app.store import FileStore

INDEX = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "index.html"

MOVES = ["False Swipe", "Mean Look", "Sweet Scent", "Spore"]
#: Deliberately all different, and none equal to its move's base PP (40/5/20/15), so any shift
#: or any silent fall-through to the base value shows up as a different number.
RECORDED = {"1": 11, "2": 22, "3": 33, "4": 44}
STATS = {"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160}


def _pokemon(**kw):
    fields = dict(id=1, name="Smeargle", species="smeargle", level=58, ability="Technician",
                  stats=dict(STATS), moveset=list(MOVES), max_pp=dict(RECORDED))
    fields.update(kw)
    return PartyPokemon(**fields)


class TestPpForSlot(unittest.TestCase):
    """The single place the base is converted."""

    def test_each_zero_based_slot_gets_its_own_move_number(self):
        pokemon = _pokemon()
        self.assertEqual([pokemon.pp_for_slot(i) for i in range(4)], [11, 22, 33, 44])

    def test_slot_zero_is_move_one(self):
        """The off-by-one, stated at its smallest."""
        self.assertEqual(_pokemon(max_pp={"1": 11}).pp_for_slot(0), 11)
        self.assertIsNone(_pokemon(max_pp={"1": 11}).pp_for_slot(1))

    def test_the_last_slot_is_read_at_all(self):
        """Move 4's PP was never reached under the old indexing, which a 2- or 3-move fixture
        cannot catch."""
        self.assertEqual(_pokemon().pp_for_slot(3), 44)

    def test_integer_keys_work_as_well_as_strings(self):
        """Strings after a JSON round-trip, but a dict built in Python need not have been."""
        self.assertEqual(_pokemon(max_pp={1: 11, 2: 22}).pp_for_slot(0), 11)

    def test_unrecorded_is_none_rather_than_zero(self):
        """So the caller can tell "nobody filled this in" from "this move has no PP left"."""
        self.assertIsNone(_pokemon(max_pp={}).pp_for_slot(0))

    def test_a_recorded_zero_counts_as_unrecorded(self):
        self.assertIsNone(_pokemon(max_pp={"1": 0}).pp_for_slot(0))

    def test_an_out_of_range_slot_is_none_rather_than_raising(self):
        self.assertIsNone(_pokemon().pp_for_slot(9))


class TestTheWarningAgrees(unittest.TestCase):
    def test_a_fully_recorded_set_warns_about_no_move(self):
        self.assertEqual([n for n in _pokemon().warnings() if "max PP" in n], [])

    def test_a_missing_entry_names_the_move_the_player_sees(self):
        """1-based in the message, because that is the move number on the summary screen."""
        notes = [n for n in _pokemon(max_pp={"1": 11, "2": 22, "4": 44}).warnings()
                 if "max PP" in n]
        self.assertEqual(len(notes), 1)
        self.assertIn("move 3 (Sweet Scent)", notes[0])

    def test_it_reads_through_the_same_accessor_as_the_simulator(self):
        """The warning and the simulator disagreeing about which slots are recorded is how a
        hunt reports itself ready and then runs on the wrong numbers."""
        pokemon = _pokemon(max_pp={"2": 22})
        warned = {int(re.search(r"move (\d)", n).group(1)) - 1
                  for n in pokemon.warnings() if "max PP" in n}
        unrecorded = {i for i in range(len(MOVES)) if pokemon.pp_for_slot(i) is None}
        self.assertEqual(warned, unrecorded)


class TestTheKeyThePageWritesIsTheKeyTheSimulatorReads(unittest.TestCase):
    """The boundary no previous test crossed."""

    def _pp_in_a_run(self, max_pp):
        facade = Facade(FileStore(tempfile.mkdtemp()))
        profile_id = facade.create_profile({"name": "T"})["id"]
        lead = facade.add_party_pokemon(profile_id, {
            "name": "Smeargle", "species": "smeargle", "level": 58, "ability": "Technician",
            "stats": dict(STATS), "moveset": list(MOVES), "max_pp": max_pp})["pokemon_id"]
        hunt = facade.create_hunt({"name": "H", "profile_id": profile_id})
        hunt.update({
            "target": {"species": "suicune", "level": 40, "nature": "Bold",
                       "ivs": {k: 31 for k in ("hp", "atk", "def", "spa", "spd", "spe")}},
            "party": [{"pokemon_id": lead}], "capture_ball": "Fast Ball",
            "key_seed": 0x2D005C61, "initial_time": "2026-01-01T12:00:00",
            "vector_ms": 5000, "seconds_window": 0, "delay_window": 10})
        facade.save_hunt(hunt)
        return facade.hunt_session_start(hunt["id"])["snapshot"]["ours"]["pp"]

    def test_the_run_sees_exactly_what_was_recorded(self):
        self.assertEqual(self._pp_in_a_run(dict(RECORDED)), [11, 22, 33, 44])

    def test_the_page_writes_one_based_keys(self):
        """Read off the page's own source: it pushes the move first, so `moveset.length` is the
        1-based move number by the time it is used as the key."""
        save = INDEX.read_text()
        save = save[save.index("const moveset = [], max_pp = {};"):]
        save = save[:save.index("const fields = {")]
        self.assertIn("moveset.push(name);", save)
        self.assertIn("max_pp[String(moveset.length)] = +ppv;", save)
        self.assertLess(save.index("moveset.push(name);"),
                        save.index("max_pp[String(moveset.length)]"),
                        "the push must come first or the key is a 0-based slot")

    def test_the_page_reads_back_the_same_keys_it_wrote(self):
        """Form row `i` is 0-based, so the display lookup is `i + 1` -- the one the save writes.
        If these two ever disagree, the PP a player types is not the PP they see next time."""
        html = INDEX.read_text()
        self.assertIn('(m.max_pp || {})[String(i + 1)]', html)

    def test_a_profile_saved_through_the_pages_convention_round_trips(self):
        """End to end on the shape the page actually produces: keys "1".."4", integer values."""
        page_shaped = {str(n): pp for n, pp in zip(range(1, 5), (11, 22, 33, 44))}
        self.assertEqual(page_shaped, RECORDED)
        self.assertEqual(self._pp_in_a_run(page_shaped), [11, 22, 33, 44])

    def test_nothing_reads_max_pp_without_going_through_the_accessor(self):
        """The accessor is only a fix while it is the only reader."""
        for path in ("app/facade.py",):
            source = (pathlib.Path(__file__).resolve().parent.parent / path).read_text()
            for line in source.splitlines():
                if "max_pp" not in line or line.strip().startswith("#"):
                    continue
                # Copying the dict wholesale is fine; indexing it is not.
                self.assertNotIn("max_pp.get(", line, f"{path}: {line.strip()}")
                self.assertNotIn("max_pp[", line, f"{path}: {line.strip()}")
