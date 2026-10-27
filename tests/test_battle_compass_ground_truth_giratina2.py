"""Ground truth: ``data/battle_logs/giratina2.jsonl``, a seven-turn Giratina battle with a switch.

A gdb capture at seed ``0x4a0231dd``: a Lv54 Magneton paralyses Giratina and Screeches it to -6
Defence, then switches to a Lv64 Smeargle carrying Spore / Foresight / Mean Look / False Swipe --
the actual planned Giratina party -- which uses Foresight. Seven turns.

**It found two bugs, both on the same turn and both about an INEFFECTIVE hit.** Turn 6 is a switch
turn: Giratina's Ominous Wind lands on the incoming Normal-typed Smeargle and the game prints "It
doesn't affect CATCHMONKE...". The simulator spent **18** advances there against the game's **15**.
Turn 1 is the control -- the same Ominous Wind against the Electric/Steel lead, which merely
resists it:

===========================  ========================  ==========================
turn                         target's move rolls       trailing advances
===========================  ========================  ==========================
1, vs Electric/Steel         CRIT DMG ACC **SEC**      **6**
6, vs Normal (immune)        CRIT DMG ACC              **4**
===========================  ========================  ==========================

So an ineffective hit spends **no secondary proc roll** and is **not a successful move**, losing
the two post-move advances as well: -1 and -2, which is the +3 exactly.

Both corrections are reversals of things this project had previously concluded, which is why the
log matters more than the reasoning did:

* The proc roll. `BtlCmd_CheckMoveHit` jumps past the side-effect subscript on
  `MOVE_STATUS_DID_NOT_HIT`, which was the first reading and the right one; it was replaced by
  `BattleSystem_TriggerSecondaryEffect`'s unconditional `Random`, on the assumption that the
  function is reached at all on such a turn. It is not.
* `successful`. An immune hit was left as successful because it "connected and just did nothing" --
  true of the animation, false of the stream.

**And it confirms four things**, none of which needed changing: Foresight spends zero rolls and
identifies the target (turn 7); a switch costs no rolls of its own (turn 6); the charge turn and
the no-selection-roll fire turn behave as ``giratina.jsonl`` already showed (turns 3 and 4); and an
ordinary full paralysis spends four trailing advances where a charge-breaking one spends six
(turn 5 against ``giratina.jsonl``'s turn 2).

(clayton-6xu.3.12)
"""
import json
import unittest
from pathlib import Path

from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass import tokens as tok

_LOG = Path(__file__).resolve().parent.parent / "data" / "battle_logs" / "giratina2.jsonl"

#: See the sibling module for why the log's function NAMES are meaningless and the addresses are
#: what identify these sites.
SELECT = "0x02260e1a"
BEFORE = "0x0224c6d4"
SECONDARY = "0x022538b2"


def _records():
    return json.loads(_LOG.read_text())


def _turns():
    """``[(selection rolls, total advances, [roll kinds], [messages]), ...]``, per turn."""
    events = []
    for record in _records()["records"]:
        kind = next(iter(record))
        if kind == "roll":
            events.append(("roll", record[kind]["addr"]))
        elif kind == "msg":
            events.append(("msg", " ".join(record[kind].split())))
    starts = [i for i, e in enumerate(events)
              if e == ("roll", BEFORE) and (i == 0 or events[i - 1] != ("roll", BEFORE))]
    out = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(events)
        gap = starts[n - 1] if n else 0
        selects = sum(1 for e in events[gap:i] if e == ("roll", SELECT))
        kinds = [e[1] for e in events[i:end] if e[0] == "roll" and e[1] != SELECT]
        msgs = [e[1] for e in events[i:end] if e[0] == "msg" and "What will" not in e[1]]
        out.append((selects, len(kinds) + selects, kinds, msgs))
    return out


def _magneton() -> Battler:
    return Battler(name="THE RADIO", level=54, types=("Electric", "Steel"),
                   stats={"hp": 134, "atk": 106, "def": 113,
                          "spa": 148, "spd": 101, "spe": 118},
                   moves=("Thunder Wave", "Screech", "Supersonic", "Sonic Boom"),
                   pp=(20, 40, 20, 20), ability="Magnet Pull", party_slot=1)


def _smeargle() -> Battler:
    """The planned chipper, as the log records it: Lv64, 31s across the board."""
    return Battler(name="CATCHMONKE", level=64, types=("Normal",),
                   stats={"hp": 168, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
                   moves=("Spore", "Foresight", "Mean Look", "False Swipe"),
                   pp=(15, 40, 5, 40), ability="Own Tempo", party_slot=2)


def _giratina() -> Battler:
    return Battler(name="Giratina", level=47, types=("Ghost", "Dragon"),
                   stats={"hp": 198, "atk": 111, "def": 129,
                          "spa": 99, "spd": 106, "spe": 104},
                   moves=("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force"),
                   pp=(5, 5, 15, 5), ability="Levitate")


#: Thunder Wave, four Screeches, the switch, then Foresight. Read off the log's messages.
PLAN = [(Action.MOVE_1, {}), (Action.MOVE_2, {}), (Action.MOVE_2, {}), (Action.MOVE_2, {}),
        (Action.MOVE_2, {}), (Action.SWITCH, {"bench_slot": 0}), (Action.MOVE_2, {})]


def _replay():
    config = HuntConfig(target_catch_rate=3, target_has_pressure=False)
    state = BattleState(ours=_magneton(), target=_giratina(), bench=(_smeargle(),),
                        rng=opening_rng(int(_records()["forced_seed"], 16), config))
    out, previous = [], state.rng_offset
    for action, extra in PLAN:
        state = simulate_turn(state, action, config, **extra)
        out.append((state.rng_offset - previous, tok.render_turn(state.log[-1]), state))
        previous = state.rng_offset
    return out


class TestTheLogIsWhatWeThinkItIs(unittest.TestCase):
    def test_the_seed_was_forced_and_confirmed(self):
        records = _records()
        self.assertEqual(records["forced_seed"], "0x4a0231dd")
        seed = next(r["seed"] for r in records["records"] if "seed" in r)
        self.assertTrue(seed["confirmed"])

    def test_it_parses_to_seven_turns(self):
        self.assertEqual(len(_turns()), 7)

    def test_it_contains_the_switch_and_the_foresight(self):
        joined = " ".join(" ".join(t[3]) for t in _turns()).replace("\u2019", "'")
        self.assertIn("switch out", joined)
        self.assertIn("used Foresight", joined)
        self.assertIn("identified the wild GIRATINA", joined)
        self.assertIn("doesn", joined)      # "It doesn't affect CATCHMONKE..."


class TestEveryTurnMatches(unittest.TestCase):
    def test_the_advance_counts_agree(self):
        for n, ((_, expected, _k, msgs), (got, _r, _s)) in enumerate(
                zip(_turns(), _replay()), 1):
            with self.subTest(turn=n, log_says=" / ".join(msgs)[:60]):
                self.assertEqual(got, expected)

    def test_the_total_agrees(self):
        self.assertEqual(sum(t[0] for t in _replay()), sum(t[1] for t in _turns()))

    def test_our_hp_agrees_wherever_the_log_records_one(self):
        """The strong check: an HP figure is a damage roll read back, so matching them means the
        stream is aligned to the roll rather than merely to the count."""
        recorded = [h["hp"] for r in _records()["records"] if "hp" in r
                    for h in r["hp"] if h["battler"] == 0 and h["hp"] not in (0, 134)]
        replayed, seen = [], None
        for _cost, _rendered, state in _replay():
            if state.ours.hp != seen:
                replayed.append(state.ours.hp)
                seen = state.ours.hp
        self.assertEqual(replayed, recorded)


class TestTheTwoBugsItFound(unittest.TestCase):
    """Turn 1 against turn 6: the same Ominous Wind, resisted and then immune."""

    def _pair(self):
        turns = _turns()
        return turns[0], turns[5]

    def test_both_turns_are_the_same_move(self):
        resisted, immune = self._pair()
        self.assertIn("used Ominous Wind", " ".join(resisted[3]))
        self.assertIn("used Ominous Wind", " ".join(immune[3]))

    def test_the_immune_one_spends_no_secondary_roll(self):
        resisted, immune = self._pair()
        self.assertIn(SECONDARY, resisted[2])
        self.assertNotIn(SECONDARY, immune[2])

    def test_and_it_forfeits_the_post_move_advances(self):
        """Trailing advances: six when it connects, four when it does not. The ROM groups
        MOVE_STATUS_INEFFECTIVE under MOVE_STATUS_DID_NOT_HIT, so the move never "went off"."""
        resisted, immune = self._pair()
        self.assertEqual(resisted[2][-6:].count("0x0225b88e"), 6)
        self.assertEqual(immune[2][-4:].count("0x0225b88e"), 4)
        self.assertNotIn("0x0225b88e", immune[2][-5:-4])

    def test_the_simulator_now_agrees_on_that_turn(self):
        self.assertEqual(_replay()[5][0], 15)


class TestWhatItConfirms(unittest.TestCase):
    def test_foresight_spends_no_rolls_and_identifies(self):
        """Turn 7: accuracy 0 and no `Random` in either script, so the only rolls on the turn are
        the skeleton's. 1 selection + 4 before + 0 + 2 post + 2 between + 1 paralysis + 4 end."""
        turn = _turns()[6]
        self.assertEqual(turn[1], 14)
        self.assertIn("identified the wild GIRATINA", " ".join(turn[3]))
        self.assertEqual(_replay()[6][0], 14)

    def test_a_switch_costs_no_rolls_of_its_own(self):
        turn = _turns()[5]
        self.assertIn("switch out", " ".join(turn[3]))
        self.assertEqual(_replay()[5][0], turn[1])

    def test_the_fire_turn_still_spends_no_selection_roll(self):
        """Turn 3 charges and turn 4 fires -- the same pair `giratina.jsonl` showed, confirmed on
        a second seed."""
        turns = _turns()
        self.assertEqual(turns[2][0], 1)
        self.assertEqual(turns[3][0], 0)

    def test_an_ordinary_full_paralysis_spends_four_trailing_advances(self):
        """Turn 5, against `giratina.jsonl`'s turn 2 where the paralysis broke a charge and spent
        six. The charge-break cost is confirmed from the other side."""
        turn = _turns()[4]
        self.assertIn("can", " ".join(turn[3]))
        self.assertEqual(turn[1], 15)
        self.assertEqual(_replay()[4][0], 15)


if __name__ == "__main__":
    unittest.main()
