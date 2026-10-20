"""Glass: the Seed entity, the delay readout, and the year that decides it.

The UI side is covered by tests/test_app_web_ui.py (every api() call names a real facade
method, every nav button has a setView branch, every handler exists). What needs its own tests
is the arithmetic Glass is the only tool to show a player — the absolute delay — and the two
ways it can be impossible. See notes/glass.md.
"""
import datetime as dt
import tempfile
import unittest

from app import glass
from app.facade import Facade
from app.metronome import times_on_date
from app.models import SEED_HISTORY_LIMIT, Seed
from app.store import FileStore

# Hour byte 0x15 = 21 -> night; low 16 bits 0x04DC = 1244.
NIGHT_SEED = 0xEC1504DC
# Hour byte 0x0C = 12 -> day. Its mdms byte is 0x3A = 58 = 2*29, so Feb 29 00:00 is one of its
# valid times -- which is what makes it the seed to test leap-year stamping with.
DAY_SEED = 0x3A0C1234
# Hour byte 0xFF: no DS clock can show hour 255, so no time produces this seed at all.
IMPOSSIBLE_HOUR = 0x3AFF1234
# Low 16 bits 0x0005 = 5, so any year after 2005 would need a negative delay.
TINY_DELAY_SEED = 0x3A0C0005


class SeedModelCase(unittest.TestCase):
    def test_a_seed_round_trips_through_the_store(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        profile = api.create_profile({"name": "Gold"})
        created = api.create_seed({"profile_id": profile["id"], "label": "Metang approach",
                                   "key_seed": "0xEC1504DC",
                                   "initial_time": "2026-03-01T21:00:00",
                                   "default_frame": 73, "notes": "line one\nline two"})
        api.seed_save_seed_a_defaults(created["id"], {"startrel": "31 30 7",
                                                      "seconds_window": 3})
        api.seed_add_history(created["id"], {"seed_hex": "0xEC1504DC", "delay": 1218})

        reloaded = api.get_seed(created["id"])
        self.assertEqual(reloaded["label"], "Metang approach")
        self.assertEqual(reloaded["key_seed"], NIGHT_SEED)
        self.assertEqual(reloaded["default_frame"], 73)
        self.assertEqual(reloaded["notes"], "line one\nline two")
        self.assertEqual(reloaded["seed_a_defaults"]["startrel"], "31 30 7")
        self.assertEqual(reloaded["seed_a_defaults"]["seconds_window"], 3)
        self.assertEqual(len(reloaded["history"]), 1)

    def test_from_dict_tolerates_a_document_with_nothing_but_a_profile(self):
        """Creation only ever requires a profile, so every other field has to survive absence."""
        s = Seed.from_dict({"profile_id": "p1"})
        self.assertEqual((s.label, s.key_seed, s.initial_time, s.default_frame, s.notes),
                         ("", None, "", None, ""))
        self.assertEqual((s.seed_a_defaults, s.history), ({}, []))
        self.assertTrue(s.id)

    def test_several_seeds_may_share_a_key_seed(self):
        """No uniqueness rule, deliberately: the same seed kept for two reasons is two Seeds."""
        api = Facade(FileStore(tempfile.mkdtemp()))
        profile = api.create_profile({"name": "Gold"})
        for label in ("morning run", "evening run"):
            api.create_seed({"profile_id": profile["id"], "label": label,
                             "key_seed": NIGHT_SEED})
        rows = api.list_seeds()
        self.assertEqual([r["key_seed"] for r in rows], [NIGHT_SEED, NIGHT_SEED])

    def test_create_seed_needs_a_profile_that_exists(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        with self.assertRaises(ValueError):
            api.create_seed({"label": "orphan"})
        with self.assertRaises(ValueError):
            api.create_seed({"profile_id": "nope"})

    def test_delete_seed_removes_only_the_seed(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        profile = api.create_profile({"name": "Gold"})
        kept = api.create_seed({"profile_id": profile["id"], "label": "kept"})
        gone = api.create_seed({"profile_id": profile["id"], "label": "gone"})

        self.assertTrue(api.delete_seed(gone["id"]))
        self.assertFalse(api.delete_seed(gone["id"]))
        self.assertEqual([r["id"] for r in api.list_seeds()], [kept["id"]])
        self.assertEqual(api.get_profile(profile["id"])["name"], "Gold")


class SaveSeedCase(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.profile = self.api.create_profile({"name": "Gold"})
        self.seed = self.api.create_seed({"profile_id": self.profile["id"]})

    def test_a_bare_hex_key_seed_is_read_as_hex_not_decimal(self):
        """int(x, 0) would read "12345" as decimal; every key-seed field in this app means hex."""
        self.assertEqual(self.api.save_seed(self.seed["id"], {"key_seed": "12345"})["key_seed"],
                         0x12345)
        self.assertEqual(self.api.save_seed(self.seed["id"], {"key_seed": "0x12345"})["key_seed"],
                         0x12345)
        self.assertEqual(self.api.save_seed(self.seed["id"], {"key_seed": NIGHT_SEED})["key_seed"],
                         NIGHT_SEED)

    def test_omitted_fields_are_left_alone_and_blanks_clear(self):
        self.api.save_seed(self.seed["id"], {"label": " kept ", "default_frame": 73,
                                             "notes": "why"})
        after = self.api.save_seed(self.seed["id"], {"default_frame": ""})
        self.assertEqual(after["label"], "kept")       # untouched, and stripped on the way in
        self.assertEqual(after["notes"], "why")
        self.assertIsNone(after["default_frame"])

    def test_saving_configuration_never_touches_the_history(self):
        """The page saves as you type; a whole-document upsert would have eaten the history."""
        self.api.seed_add_history(self.seed["id"], {"seed_hex": "0xEC1504DC"})
        after = self.api.save_seed(self.seed["id"], {"label": "renamed"})
        self.assertEqual(len(after["history"]), 1)

    def test_seed_a_defaults_merge_rather_than_replace(self):
        self.api.seed_save_seed_a_defaults(self.seed["id"], {"startrel": "31 30 7",
                                                             "delay_window": 10})
        merged = self.api.seed_save_seed_a_defaults(self.seed["id"], {"delay_window": 25})
        self.assertEqual(merged, {"startrel": "31 30 7", "delay_window": 25})


class DelayReadoutCase(unittest.TestCase):
    """delay = (key_seed & 0xFFFF) - (year - 2000), and the two ways it can be impossible."""

    def test_the_delay_is_the_low_16_bits_less_the_year_offset(self):
        read = glass.readout(NIGHT_SEED, "2026-03-01T21:00:00")
        self.assertEqual(read["delay"], (NIGHT_SEED & 0xFFFF) - 26)
        self.assertEqual(read["year"], 2026)
        self.assertEqual(read["key_seed_hex"], "0xEC1504DC")
        self.assertEqual(read["problem"], "")

    def test_the_delay_moves_with_the_year(self):
        """The whole reason Glass pins the year down -- a placeholder year 2000 would be 26 out."""
        low16 = NIGHT_SEED & 0xFFFF
        self.assertEqual(glass.readout(NIGHT_SEED, "2000-03-01T21:00:00")["delay"], low16)
        self.assertEqual(glass.readout(NIGHT_SEED, "2026-03-01T21:00:00")["delay"], low16 - 26)
        self.assertEqual(glass.readout(NIGHT_SEED, "2027-03-01T21:00:00")["delay"], low16 - 27)

    def test_the_derived_delay_reconstructs_the_key_seed(self):
        """The claim the readout rests on: aim at this delay in this year and you get this seed."""
        from claytonlib.calibration_tools import seed_for
        # The time has to be one the seed itself allows (its mdms byte fixes month*day +
        # minute + second), which is exactly what the picker offers.
        for valid in times_on_date(NIGHT_SEED, year=2026)[:5]:
            delay = glass.readout(NIGHT_SEED, valid)["delay"]
            self.assertEqual(seed_for(dt.datetime.fromisoformat(valid), delay), NIGHT_SEED)

    def test_a_year_the_seed_cannot_reach_is_explained_not_printed(self):
        """generate_roamer_candidates_near skips negative delays, so the search would just
        come back empty -- the readout has to be the thing that says why."""
        read = glass.readout(TINY_DELAY_SEED, "2026-03-01T12:00:00")
        self.assertIsNone(read["delay"])
        self.assertIn("2005", read["problem"])
        # The year 2005 still works, so this is about the year rather than the seed.
        self.assertEqual(glass.readout(TINY_DELAY_SEED, "2005-03-01T12:00:00")["delay"], 0)

    def test_an_hour_byte_above_23_means_no_clock_can_produce_the_seed(self):
        read = glass.readout(IMPOSSIBLE_HOUR, "2026-03-01T12:00:00")
        self.assertIsNone(read["hour"])
        self.assertIsNone(read["time_of_day"])
        self.assertIsNone(read["delay"])
        self.assertIn("255", read["problem"])

    def test_without_a_time_there_is_a_bucket_but_no_delay(self):
        """The hour is in the seed, so the time-of-day is known before any time is picked."""
        read = glass.readout(DAY_SEED)
        self.assertEqual((read["hour"], read["time_of_day"]), (12, "day"))
        self.assertIsNone(read["delay"])
        self.assertTrue(read["problem"])

    def test_the_bucket_comes_from_the_seeds_own_hour(self):
        self.assertEqual(glass.readout(NIGHT_SEED)["time_of_day"], "night")
        self.assertEqual(glass.readout(DAY_SEED)["time_of_day"], "day")
        self.assertEqual(glass.readout(0x3A041234)["time_of_day"], "morning")

    def test_no_key_seed_yields_nothing_rather_than_raising(self):
        read = glass.readout(None)
        self.assertEqual(read["key_seed_hex"], "")
        self.assertIsNone(read["delay"])

    def test_the_facade_accepts_the_fields_text_unsaved(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        read = api.seed_readout("0x3A0C1234", "2026-02-28T12:00:00")
        self.assertEqual(read["delay"], (DAY_SEED & 0xFFFF) - 26)
        self.assertEqual(api.seed_readout("", "")["delay"], None)


class TimesOnDateYearCase(unittest.TestCase):
    """The picker's new year, which is what keeps a stored initial time self-sufficient."""

    def test_every_returned_time_carries_the_year(self):
        years = {t[:4] for t in times_on_date(DAY_SEED, year=2031)}
        self.assertEqual(years, {"2031"})

    def test_the_year_applies_without_a_month_or_day_filter(self):
        """The trap it fixes: unfiltered picks used to come back on the placeholder year 2000."""
        self.assertEqual({t[:4] for t in times_on_date(DAY_SEED)}, {"2000"})
        self.assertEqual({t[:4] for t in times_on_date(DAY_SEED, year=2026)}, {"2026"})

    def test_feb_29_survives_a_leap_year_and_is_dropped_otherwise(self):
        self.assertEqual(times_on_date(DAY_SEED, month=2, day=29, year=2024),
                         ["2024-02-29T12:00:00"])
        self.assertEqual(times_on_date(DAY_SEED, month=2, day=29, year=2026), [])

    def test_omitting_the_year_leaves_the_old_behaviour(self):
        """Every other caller passes no year, so their result has to be byte-identical."""
        this_year = dt.date.today().year
        filtered = times_on_date(DAY_SEED, month=3)
        self.assertTrue(filtered)
        self.assertEqual({t[:4] for t in filtered}, {str(this_year)})
        self.assertEqual(times_on_date(DAY_SEED, month=3),
                         times_on_date(DAY_SEED, month=3, year=this_year))


class HistoryCase(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        profile = self.api.create_profile({"name": "Gold"})
        self.seed = self.api.create_seed({"profile_id": profile["id"]})

    def _save(self, n):
        for i in range(n):
            self.api.seed_add_history(self.seed["id"], {"seed_hex": f"0x{i:08X}", "frame": i})

    def test_the_eleventh_save_evicts_the_oldest(self):
        self._save(SEED_HISTORY_LIMIT + 3)
        history = self.api.get_seed(self.seed["id"])["history"]
        self.assertEqual(len(history), SEED_HISTORY_LIMIT)
        # Newest first, and the three oldest are gone.
        self.assertEqual([e["frame"] for e in history],
                         list(range(SEED_HISTORY_LIMIT + 2, 2, -1)))

    def test_repeats_are_kept_as_separate_entries(self):
        for _ in range(3):
            self.api.seed_add_history(self.seed["id"], {"seed_hex": "0xEC1504DC"})
        self.assertEqual(len(self.api.get_seed(self.seed["id"])["history"]), 3)

    def test_an_entry_is_stamped_and_trimmed_to_known_fields(self):
        entry = glass.history_entry({"seed_hex": "0xEC1504DC", "delay": 1218, "frame": 73,
                                     "routed_to": None, "elm_heard": "",
                                     "something_invented": "dropped"})
        self.assertIn("saved_at", entry)
        self.assertEqual(entry["seed_hex"], "0xEC1504DC")
        self.assertEqual(entry["delay"], 1218)
        self.assertNotIn("something_invented", entry)
        # Empty and absent values are left out rather than stored as blanks.
        self.assertNotIn("routed_to", entry)
        self.assertNotIn("elm_heard", entry)

    def test_history_is_never_a_run_and_never_reaches_calibration(self):
        """Both fits need a vector ms and a Seed B; Glass has neither, so nothing may leak in."""
        self._save(2)
        profile_id = self.api.get_seed(self.seed["id"])["profile_id"]
        self.assertEqual(self.api.list_runs(profile_id), [])

    def test_clearing_leaves_the_configuration(self):
        self._save(4)
        self.api.save_seed(self.seed["id"], {"label": "kept", "default_frame": 73})
        self.assertEqual(self.api.seed_clear_history(self.seed["id"]), [])
        after = self.api.get_seed(self.seed["id"])
        self.assertEqual(after["history"], [])
        self.assertEqual(after["label"], "kept")
        self.assertEqual(after["default_frame"], 73)


class ListRowCase(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.profile = self.api.create_profile({"name": "Gold"})

    def test_a_row_carries_what_the_list_draws(self):
        self.api.create_seed({"profile_id": self.profile["id"], "key_seed": DAY_SEED,
                              "initial_time": "2026-02-28T12:00:00", "default_frame": 73,
                              "notes": "first line\nsecond line"})
        row, = self.api.list_seeds()
        self.assertEqual(row["key_seed_hex"], "0x3A0C1234")
        self.assertEqual(row["delay"], (DAY_SEED & 0xFFFF) - 26)
        self.assertEqual(row["time_of_day"], "day")
        self.assertEqual(row["notes_line"], "first line")
        self.assertEqual(row["history_count"], 0)

    def test_a_row_has_its_bucket_before_a_time_is_picked(self):
        self.api.create_seed({"profile_id": self.profile["id"], "key_seed": NIGHT_SEED})
        row, = self.api.list_seeds()
        self.assertEqual(row["time_of_day"], "night")
        self.assertIsNone(row["delay"])

    def test_an_unreachable_key_seed_reports_its_problem_instead_of_crashing(self):
        """times_on_date would raise for this seed (hour 255 is not a parseable time), so the
        row has to carry the explanation rather than the list dying on one bad record."""
        self.api.create_seed({"profile_id": self.profile["id"], "key_seed": IMPOSSIBLE_HOUR})
        row, = self.api.list_seeds()
        self.assertIsNone(row["time_of_day"])
        self.assertIn("255", row["problem"])

    def test_labelled_seeds_sort_first(self):
        self.api.create_seed({"profile_id": self.profile["id"], "key_seed": 0x3A0C0100})
        self.api.create_seed({"profile_id": self.profile["id"], "label": "zebra"})
        self.api.create_seed({"profile_id": self.profile["id"], "label": "apple"})
        self.assertEqual([r["label"] for r in self.api.list_seeds()], ["apple", "zebra", ""])

    def test_listing_can_be_scoped_to_one_profile(self):
        other = self.api.create_profile({"name": "Silver"})
        self.api.create_seed({"profile_id": self.profile["id"], "label": "mine"})
        self.api.create_seed({"profile_id": other["id"], "label": "theirs"})
        self.assertEqual([r["label"] for r in self.api.list_seeds(self.profile["id"])], ["mine"])
        self.assertEqual([r["label"] for r in self.api.list_seeds(other["id"])], ["theirs"])


if __name__ == "__main__":
    unittest.main()
