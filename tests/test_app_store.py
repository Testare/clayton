"""Tests for app.store.FileStore."""
import tempfile
import unittest
from pathlib import Path

from app.store import FileStore, default_data_dir


class TestFileStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = FileStore(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_read_missing_returns_none(self):
        self.assertIsNone(self.store.read("profiles", "nope"))
        self.assertFalse(self.store.exists("profiles", "nope"))

    def test_write_then_read_round_trips(self):
        doc = {"name": "Silver", "tid": 12345, "nested": {"a": [1, 2, 3]}}
        self.store.write("profiles", "p1", doc)
        self.assertEqual(self.store.read("profiles", "p1"), doc)
        self.assertTrue(self.store.exists("profiles", "p1"))

    def test_write_replaces(self):
        self.store.write("profiles", "p1", {"v": 1})
        self.store.write("profiles", "p1", {"v": 2})
        self.assertEqual(self.store.read("profiles", "p1"), {"v": 2})

    def test_list_ids_sorted_and_scoped(self):
        self.store.write("profiles", "b", {})
        self.store.write("profiles", "a", {})
        self.store.write("expeditions", "x", {})
        self.assertEqual(self.store.list_ids("profiles"), ["a", "b"])
        self.assertEqual(self.store.list_ids("expeditions"), ["x"])

    def test_list_ids_empty_collection(self):
        self.assertEqual(self.store.list_ids("never_written"), [])

    def test_delete(self):
        self.store.write("profiles", "p1", {})
        self.assertTrue(self.store.delete("profiles", "p1"))
        self.assertFalse(self.store.delete("profiles", "p1"))
        self.assertIsNone(self.store.read("profiles", "p1"))

    def test_no_temp_files_leak_into_listing(self):
        # Atomic writes use a dotfile temp; it must never show up as a document id.
        self.store.write("profiles", "p1", {})
        ids = self.store.list_ids("profiles")
        self.assertEqual(ids, ["p1"])

    def test_rejects_unsafe_segments(self):
        for bad in ("../escape", "a/b", "", "."):
            with self.assertRaises(ValueError):
                self.store.write("profiles", bad, {})
        with self.assertRaises(ValueError):
            self.store.read("../secrets", "x")

    def test_default_data_dir_is_app_scoped(self):
        self.assertEqual(default_data_dir().name, "Clayton")


if __name__ == "__main__":
    unittest.main()
