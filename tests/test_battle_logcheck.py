"""Analysis of recorded battle logs.

The recorder (utils/gdb-battle-reader.py) needs a live emulator and cannot be tested, so the
judgement lives here instead and is tested against synthetic logs.
"""
import json
import tempfile
from collections import Counter
import unittest
from pathlib import Path

from claytonlib.battle.damage import Attacker, Defender
from claytonlib.battle.logcheck import (
    END_OF_TURN_COMMANDS, PLAYER_BATTLER, TARGET_BATTLER, BattleLog, check_damage_event, load,
    phase_label, report,
)
from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.moves import resolve_move


def _roll(val, func="BattleSystem_Random", addr="0x0"):
    return {"roll": {"addr": addr, "func": func, "val": val}}


def _hp(battler, hp, max_hp):
    return {"hp": [{"battler": battler, "hp": hp, "max": max_hp}]}


def _phase(command, *, next_command=None, mon=26, side=3, field=13, temp=0,
           narc=1, script_file=18, cursor=0, script="sub_seq:subscript_fall_asleep"):
    """A phase record shaped like the Platinum reader's, with readable defaults: every
    condition-check state parked at its END value and nothing being walked."""
    fields = {"command": command, "commandNext": next_command or command,
              "fieldConditionCheckState": field, "fieldConditionCheckTemp": temp,
              "monConditionCheckState": mon, "monConditionCheckTemp": temp,
              "sideConditionCheckState": side, "sideConditionCheckTemp": temp,
              "attacker": 0, "defender": 1,
              "scriptNarc": narc, "scriptFile": script_file, "scriptCursor": cursor}
    names = {"command": command, "commandNext": next_command or command,
             "fieldConditionCheckState": {7: "RAINING", 13: "END"}.get(field, str(field)),
             "monConditionCheckState": {14: "THRASH", 23: "YAWN", 24: "ITEM_CONDITION",
                                        26: "END"}.get(mon, str(mon)),
             "sideConditionCheckState": {0: "FUTURE_SIGHT", 3: "END"}.get(side, str(side)),
             "script": script}
    return {"phase": {"fields": fields, "names": names}}


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


class TestPhaseLabels(unittest.TestCase):
    def test_a_command_outside_the_end_of_turn_has_no_label(self):
        self.assertIsNone(phase_label(_phase("USE_MOVE")["phase"]))

    def test_the_mon_condition_walk_names_the_condition_and_the_battler(self):
        phase = _phase("CHECK_MON_CONDITIONS", mon=23, temp=1)["phase"]
        self.assertEqual(phase_label(phase), "mon:YAWN[b1]")

    def test_the_side_condition_walk_names_its_own_state(self):
        phase = _phase("CHECK_SIDE_CONDITIONS", side=0)["phase"]
        self.assertEqual(phase_label(phase), "side:FUTURE_SIGHT[b0]")

    def test_turn_end_walks_nothing(self):
        self.assertEqual(phase_label(_phase("TURN_END")["phase"]), "turn_end")

    def test_a_subscripts_roll_is_attributed_to_the_command_it_returns_to(self):
        """A roll inside subscript_fall_asleep reports command EXEC_SCRIPT; commandNext is what
        says it is still the end of turn. Without this the two rolls 6xu.7.1 is about -- both of
        which happen inside subscripts -- would be invisible."""
        phase = _phase("EXEC_SCRIPT", next_command="CHECK_MON_CONDITIONS", mon=24)["phase"]
        self.assertEqual(phase_label(phase), "mon:YAWN[b0]")

    def test_the_mon_walks_increment_is_undone_inside_a_subscript(self):
        """Every case in CheckMonConditions increments the state before breaking out to its
        subscript, so a roll in subscript_fall_asleep reads ITEM_CONDITION (24) when Yawn (23)
        is what loaded it. Measured in data/battle_logs/uxie1.jsonl."""
        inside = _phase("EXEC_SCRIPT", next_command="CHECK_MON_CONDITIONS", mon=24)["phase"]
        self.assertEqual(phase_label(inside), "mon:YAWN[b0]")
        # ...and NOT undone when the walk itself is the current command.
        walking = _phase("CHECK_MON_CONDITIONS", mon=24)["phase"]
        self.assertEqual(phase_label(walking), "mon:ITEM_CONDITION[b0]")

    def test_the_side_walks_state_is_not_adjusted(self):
        """CheckSideConditions loops the battler inside each state and only advances the state
        when that loop ends, so the state still names the condition."""
        phase = _phase("EXEC_SCRIPT", next_command="CHECK_SIDE_CONDITIONS", side=0,
                       temp=1)["phase"]
        self.assertEqual(phase_label(phase), "side:FUTURE_SIGHT[b1]")

    def test_a_field_walk_subscript_is_marked_uncertain(self):
        """The field walk is mixed -- seven cases do not increment on break-out and six do -- so
        there is no adjustment to apply and the label says so instead of guessing."""
        phase = _phase("EXEC_SCRIPT", next_command="CHECK_FIELD_CONDITIONS", field=7)["phase"]
        self.assertEqual(phase_label(phase), "field:RAINING[b0]?")

    def test_the_condition_tables_match_the_recorders(self):
        """logcheck keeps its own copy of the three enums so it can re-name an adjusted state.
        The recorder's copies are the ones a log's `names` were built from, so they must agree."""
        import importlib.util
        import pathlib as _pathlib
        import sys as _sys
        from claytonlib.battle.logcheck import _CONDITION_NAMES
        path = (_pathlib.Path(__file__).resolve().parent.parent / "utils"
                / "gdb-platinum-battle-reader.py")
        sentinel = object()
        previous = _sys.modules.get("gdb", sentinel)
        _sys.modules["gdb"] = None
        try:
            spec = importlib.util.spec_from_file_location("_plr_for_logcheck", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            if previous is sentinel:
                del _sys.modules["gdb"]
            else:
                _sys.modules["gdb"] = previous
        self.assertEqual(_CONDITION_NAMES["mon"], module.MON_COND_CHECK_NAMES)
        self.assertEqual(_CONDITION_NAMES["side"], module.SIDE_COND_CHECK_NAMES)
        self.assertEqual(_CONDITION_NAMES["field"], module.FIELD_COND_CHECK_NAMES)

    def test_a_subscript_outside_the_end_of_turn_is_still_unlabelled(self):
        phase = _phase("EXEC_SCRIPT", next_command="USE_MOVE")["phase"]
        self.assertIsNone(phase_label(phase))

    def test_every_end_of_turn_command_gets_a_label(self):
        for command in END_OF_TURN_COMMANDS:
            self.assertIsNotNone(phase_label(_phase(command)["phase"]), command)


class TestEndOfTurnSequences(unittest.TestCase):
    def test_a_log_without_phases_reports_nothing_rather_than_guessing(self):
        """An HG/SS log has no phase records, and inventing an attribution for it would be worse
        than saying it cannot answer the question."""
        log = _log([_roll(1), _roll(2)])
        self.assertEqual(log.end_of_turn_sequences(), [])
        self.assertEqual(log.phases, [])

    def test_rolls_are_numbered_within_the_sequence(self):
        log = _log([
            _phase("USE_MOVE"), _roll(10),
            _phase("CHECK_MON_CONDITIONS", mon=14), _roll(20),
            _phase("CHECK_MON_CONDITIONS", mon=23), _roll(30),
            _phase("CHECK_SIDE_CONDITIONS", side=0), _roll(40),
            _phase("TURN_END"), _roll(50),
        ])
        sequences = log.end_of_turn_sequences()
        self.assertEqual(len(sequences), 1)
        self.assertEqual([(r.ordinal, r.label, r.value) for r in sequences[0]],
                         [(1, "mon:THRASH[b0]", 20),
                          (2, "mon:YAWN[b0]", 30),
                          (3, "side:FUTURE_SIGHT[b0]", 40),
                          (4, "turn_end", 50)])

    def test_the_move_phase_roll_is_not_counted(self):
        log = _log([_phase("USE_MOVE"), _roll(10)])
        self.assertEqual(log.end_of_turn_sequences(), [])

    def test_leaving_the_end_of_turn_closes_the_sequence(self):
        log = _log([
            _phase("CHECK_MON_CONDITIONS", mon=23), _roll(1),
            _phase("INIT_COMMAND_SELECTION"), _roll(2),
            _phase("CHECK_MON_CONDITIONS", mon=23), _roll(3),
        ])
        sequences = log.end_of_turn_sequences()
        self.assertEqual([len(s) for s in sequences], [1, 1])
        self.assertEqual([s[0].ordinal for s in sequences], [1, 1])

    def test_a_phase_with_no_rolls_in_it_does_not_split_a_sequence(self):
        """The ROM walks every condition state whether or not it does anything, so most phases
        spend no roll; splitting on those would turn one sequence into four empty ones."""
        log = _log([
            _phase("CHECK_MON_CONDITIONS", mon=4), _phase("CHECK_MON_CONDITIONS", mon=8),
            _phase("CHECK_MON_CONDITIONS", mon=23), _roll(1),
            _phase("CHECK_SIDE_CONDITIONS", side=0), _roll(2),
        ])
        self.assertEqual([len(s) for s in log.end_of_turn_sequences()], [2])

    def test_rolls_before_the_first_phase_are_not_attributed(self):
        log = _log([_roll(1), _phase("TURN_END"), _roll(2)])
        self.assertEqual([r.value for r in log.end_of_turn_sequences()[0]], [2])

    def test_the_script_travels_with_the_roll(self):
        log = _log([
            _phase("EXEC_SCRIPT", next_command="CHECK_MON_CONDITIONS", mon=23, cursor=7,
                   script="sub_seq:subscript_fall_asleep"),
            _roll(1),
        ])
        self.assertEqual(log.end_of_turn_sequences()[0][0].script,
                         "sub_seq:subscript_fall_asleep@7")

    def test_rolls_by_phase_aggregates_the_whole_battle(self):
        log = _log([
            _phase("CHECK_MON_CONDITIONS", mon=23), _roll(1),
            _phase("INIT_COMMAND_SELECTION"), _roll(2),
            _phase("CHECK_MON_CONDITIONS", mon=23), _roll(3),
        ])
        self.assertEqual(log.rolls_by_phase(), Counter({"mon:YAWN[b0]": 2}))


class TestSeedAndGameMetadata(unittest.TestCase):
    def test_the_game_is_read_when_present_and_none_otherwise(self):
        self.assertEqual(_log([], game="platinum").game, "platinum")
        self.assertIsNone(_log([]).game)

    def test_the_seed_entries_are_exposed(self):
        log = _log([{"seed": {"seedRandNext": "0xec1504dc", "seedLCRNG": "0x1",
                              "forced": "0xec1504dc", "confirmed": True}}])
        self.assertEqual(log.seeds[0]["seedRandNext"], "0xec1504dc")

    def test_a_confirmed_forced_seed_is_reported_as_such(self):
        log = _log([{"seed": {"seedRandNext": "0xec1504dc", "seedLCRNG": "0x1",
                              "confirmed": True}}], game="platinum")
        self.assertIn("CONFIRMED", report(log))

    def test_a_forced_seed_that_did_not_take_is_loud(self):
        log = _log([{"seed": {"seedRandNext": "0x1", "seedLCRNG": "0x2",
                              "confirmed": False}}], game="platinum")
        self.assertIn("DID NOT TAKE", report(log))


class TestReportIncludesPhases(unittest.TestCase):
    def test_the_report_lists_each_end_of_turn_roll_in_order(self):
        log = _log([
            _phase("CHECK_MON_CONDITIONS", mon=14), _roll(1),
            _phase("EXEC_SCRIPT", next_command="CHECK_MON_CONDITIONS", mon=24, cursor=3),
            _roll(2),
            _phase("CHECK_SIDE_CONDITIONS", side=0), _roll(3),
            _phase("TURN_END"), _roll(4),
        ], game="platinum")
        text = report(log)
        self.assertIn("end-of-turn rolls", text)
        self.assertIn("mon:YAWN[b0]", text)
        self.assertIn("side:FUTURE_SIGHT[b0]", text)
        self.assertIn("sub_seq:subscript_fall_asleep@3", text)
        self.assertIn("phases: 4", text)

    def test_a_phase_bearing_log_with_no_end_of_turn_rolls_says_so(self):
        log = _log([_phase("USE_MOVE"), _roll(1)], game="platinum")
        self.assertIn("no end-of-turn rolls", report(log))

    def test_an_hgss_log_gets_no_phase_section_at_all(self):
        text = report(_log([_roll(1), _hp(0, 100, 100)]))
        self.assertNotIn("end-of-turn rolls", text)
