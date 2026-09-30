"""Analysis of recorded battle logs.

The recorder (utils/gdb-battle-reader.py) needs a live emulator and cannot be tested, so the
judgement lives here instead and is tested against synthetic logs.
"""
import json
import tempfile
import unittest
from pathlib import Path

from claytonlib.battle.damage import Attacker, Defender
from claytonlib.battle.logcheck import (
    PLAYER_BATTLER, TARGET_BATTLER, BattleLog, check_damage_event, load, report,
)
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.moves import resolve_move


def _roll(val, func="BattleSystem_Random", addr="0x0"):
    return {"roll": {"addr": addr, "func": func, "val": val}}


def _hp(battler, hp, max_hp):
    return {"hp": [{"battler": battler, "hp": hp, "max": max_hp}]}


def _log(records, **kwargs):
    doc = {"label": "t", "forced_seed": "0xec1504dc", "recorded_at": "now",
           "records": records, **kwargs}
    return BattleLog(doc)


def _suicune_attacker() -> Attacker:
    stats = derive_species_stats("suicune", 40, "Bold")
    return Attacker(level=40, attack=stats["atk"], special_attack=stats["spa"],
                    types=tuple(species("suicune")["types"]))


def _smeargle_defender() -> Defender:
    stats = derive_species_stats("smeargle", 60, "Hardy")
    return Defender(defence=stats["def"], special_defence=stats["spd"],
                    types=tuple(species("smeargle")["types"]))


class TestViews(unittest.TestCase):
    def test_records_split_into_kinds(self):
        log = _log([_roll(1), {"msg": "hi"}, {"mark": "turn1"},
                    _hp(0, 154, 154), {"mon": {"battler": 0}}])
        self.assertEqual(len(log.rolls), 1)
        self.assertEqual(log.messages, ["hi"])
        self.assertEqual(log.marks, ["turn1"])
        self.assertEqual(len(log.mons), 1)
        self.assertEqual(len(log.hp_changes()), 1)

    def test_hp_changes_filter_by_battler(self):
        log = _log([_hp(0, 154, 154), _hp(1, 142, 142)])
        self.assertEqual(len(log.hp_changes(PLAYER_BATTLER)), 1)
        self.assertEqual(log.hp_changes(TARGET_BATTLER)[0].hp, 142)

    def test_rolls_by_caller_counts_per_function(self):
        log = _log([_roll(1, "A"), _roll(2, "A"), _roll(3, "B")])
        self.assertEqual(dict(log.rolls_by_caller()), {"A": 2, "B": 1})

    def test_metadata_survives(self):
        log = _log([], label="suicune")
        self.assertEqual(log.label, "suicune")
        self.assertEqual(log.forced_seed, "0xec1504dc")


class TestBattleStartAdvances(unittest.TestCase):
    """R2: the rolls spent before the first turn, read off a marker rather than guessed."""

    def test_counts_rolls_before_the_marker(self):
        log = _log([_roll(1), _roll(2), _roll(3), {"mark": "turn1"}, _roll(4)])
        self.assertEqual(log.rolls_before_mark("turn1"), 3)

    def test_non_roll_records_do_not_count(self):
        log = _log([_roll(1), {"msg": "x"}, _hp(0, 1, 1), {"mark": "turn1"}])
        self.assertEqual(log.rolls_before_mark("turn1"), 1)

    def test_a_missing_marker_is_none_not_zero(self):
        """Distinguishing "no marker" from "zero rolls" matters: one is a measurement."""
        self.assertIsNone(_log([_roll(1)]).rolls_before_mark("turn1"))

    def test_segments_give_per_turn_counts(self):
        log = _log([_roll(1), {"mark": "t1"}, _roll(2), _roll(3), {"mark": "t2"}, _roll(4)])
        self.assertEqual(log.segments(), [("t1", 1), ("t2", 2), ("<end>", 1)])

    def test_trailing_rolls_are_reported_under_end(self):
        log = _log([{"mark": "t1"}, _roll(1), _roll(2)])
        self.assertEqual(log.segments(), [("t1", 0), ("<end>", 2)])

    def test_no_trailing_segment_when_the_log_ends_on_a_marker(self):
        log = _log([_roll(1), {"mark": "t1"}])
        self.assertEqual(log.segments(), [("t1", 1)])


class TestDamageEvents(unittest.TestCase):
    """R10: pair each HP drop with the rolls before it."""

    def test_a_drop_becomes_an_event_with_its_preceding_rolls(self):
        log = _log([_hp(0, 154, 154), _roll(90), _roll(91),
                    {"msg": "Suicune used Aurora Beam!"}, _hp(0, 128, 154)])
        events = log.damage_events()
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0].before, events[0].after, events[0].damage), (154, 128, 26))
        self.assertEqual(events[0].preceding_rolls, [90, 91])
        self.assertIn("Aurora Beam", events[0].preceding_messages[0])

    def test_the_first_reading_is_a_baseline_not_a_drop(self):
        self.assertEqual(_log([_hp(0, 154, 154)]).damage_events(), [])

    def test_healing_is_not_a_damage_event(self):
        log = _log([_hp(0, 100, 154), _hp(0, 154, 154)])
        self.assertEqual(log.damage_events(), [])

    def test_rolls_reset_between_events(self):
        log = _log([_hp(0, 154, 154), _roll(1), _hp(0, 140, 154),
                    _roll(2), _roll(3), _hp(0, 120, 154)])
        self.assertEqual([len(e.preceding_rolls) for e in log.damage_events()], [1, 2])

    def test_the_target_can_be_tracked_too(self):
        log = _log([_hp(1, 142, 142), _hp(1, 120, 142)])
        self.assertEqual(log.damage_events(TARGET_BATTLER)[0].damage, 22)
        self.assertEqual(log.damage_events(PLAYER_BATTLER), [])

    def test_other_battlers_hp_does_not_interleave(self):
        log = _log([_hp(0, 154, 154), _hp(1, 142, 142), _hp(1, 100, 142), _hp(0, 130, 154)])
        self.assertEqual([e.damage for e in log.damage_events(PLAYER_BATTLER)], [24])


class TestCheckDamageEvent(unittest.TestCase):
    def setUp(self):
        self.attacker = _suicune_attacker()
        self.defender = _smeargle_defender()
        self.move = resolve_move("Aurora Beam")

    def _event(self, damage):
        log = _log([_hp(0, 154, 154), _hp(0, 154 - damage, 154)])
        return log.damage_events()[0]

    def test_an_explainable_hit_names_the_rolls(self):
        verdict = check_damage_event(self._event(26), self.move, self.attacker, self.defender)
        self.assertTrue(verdict["explained"])
        self.assertEqual(verdict["rolls"], (90, 91, 92, 93))
        self.assertEqual(verdict["expected_range"], (24, 29))

    def test_a_maximum_roll_is_pinned_exactly(self):
        verdict = check_damage_event(self._event(29), self.move, self.attacker, self.defender)
        self.assertEqual(verdict["rolls"], (100,))

    def test_an_unexplainable_hit_is_reported_not_swallowed(self):
        """The signal that matters: the seed, the stats, or the model is wrong (sec 3.1)."""
        verdict = check_damage_event(self._event(99), self.move, self.attacker, self.defender)
        self.assertFalse(verdict["explained"])
        self.assertEqual(verdict["rolls"], ())
        self.assertEqual(verdict["observed"], 99)

    def test_a_crit_is_checked_against_the_crit_range(self):
        plain = check_damage_event(self._event(52), self.move, self.attacker, self.defender)
        crit = check_damage_event(self._event(52), self.move, self.attacker, self.defender,
                                  critical=True)
        self.assertFalse(plain["explained"])
        self.assertTrue(crit["explained"])
        self.assertTrue(crit["critical_assumed"])


class TestLoadAndReport(unittest.TestCase):
    def test_load_reads_every_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            path.write_text("\n".join(json.dumps({"label": f"b{i}", "records": []})
                                      for i in range(3)) + "\n")
            self.assertEqual([log.label for log in load(path)], ["b0", "b1", "b2"])

    def test_load_tolerates_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            path.write_text('\n{"label":"a","records":[]}\n\n')
            self.assertEqual(len(load(path)), 1)

    def test_report_covers_the_three_measurements(self):
        log = _log([
            {"mon": {"battler": 1, "species": 245, "level": 40, "hp": 142, "maxHp": 142,
                     "stats": {"spa": 89}, "ivs": {"spa": 31}, "ability": 46,
                     "moves": [240], "pp": [5]}},
            _roll(1, "BattleSetup_New"), {"mark": "turn1"},
            _hp(0, 154, 154), _roll(90, "ServerCommand_CalcDamage"),
            {"msg": "Suicune used Aurora Beam!"}, _hp(0, 128, 154),
        ])
        text = report(log)
        self.assertIn("rolls by calling function", text)
        self.assertIn("rolls between markers", text)
        self.assertIn("damage taken", text)
        self.assertIn("ServerCommand_CalcDamage", text)
        self.assertIn("154 ->", text)

    def test_report_says_so_when_hp_was_never_captured(self):
        """A log with no HP cannot answer R10, and should say that rather than look complete."""
        text = report(_log([_roll(1), {"msg": "x"}]))
        self.assertIn("no HP readings", text)

    def test_report_handles_an_empty_log(self):
        self.assertIn("records: 0", report(_log([])))


if __name__ == "__main__":
    unittest.main()
