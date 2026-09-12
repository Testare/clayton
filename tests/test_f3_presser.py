"""Tests for utils/f3_presser.py key-sequence parsing + enqueue (ctd.14)."""
import os
import queue
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "utils"))
import f3_presser as p  # noqa: E402


class TestParseKeySequence(unittest.TestCase):
    def test_plus_separated(self):
        self.assertEqual(p.parse_key_sequence("s+a+space"), ["s", "a", "space"])

    def test_comma_and_whitespace(self):
        self.assertEqual(p.parse_key_sequence("s, d , space"), ["s", "d", "space"])
        self.assertEqual(p.parse_key_sequence("s d space"), ["s", "d", "space"])

    def test_lowercased(self):
        self.assertEqual(p.parse_key_sequence("S+SPACE"), ["s", "space"])

    def test_empty_is_empty_list(self):
        self.assertEqual(p.parse_key_sequence("   "), [])

    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            p.parse_key_sequence("s+9+space")
        with self.assertRaises(ValueError):
            p.parse_key_sequence("ctrl")


class TestEnqueueKeys(unittest.TestCase):
    def test_enqueue_preserves_order(self):
        # Drain any residue, enqueue, then read back FIFO order (worker not started here).
        while True:
            try:
                p._key_queue.get_nowait()
            except queue.Empty:
                break
        p.enqueue_keys(["s", "a", "space"])
        got = [p._key_queue.get_nowait() for _ in range(3)]
        self.assertEqual(got, ["s", "a", "space"])


if __name__ == "__main__":
    unittest.main()
