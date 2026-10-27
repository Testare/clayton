"""Ground truth: ``data/battle_logs/giratina.jsonl``, a six-turn forced-seed Giratina battle.

A gdb capture at seed ``0x4e0238ab``: a Lv54 Magneton ("THE RADIO") against the Lv47 Distortion
World Giratina, paralysing it on turn 1 and then Screeching. Six turns, and it settles three
things that were previously derived rather than measured.

**It found a real bug.** The simulator spent **12** advances on turn 2 where the game spends
**14**, and everything after that turn was therefore reading the wrong part of the stream. Turns 2
and 5 are a controlled pair that isolates it: both end "The wild GIRATINA is paralyzed! It can't
move!" with no move rolls at all, and the only difference is that turn 2's paralysis **broke a
Shadow Force charge**. Turn 2 spends 6 trailing advances against turn 5's 4. So a prevented turn
that breaks a charge owes two more — the cleanup — and `broken_charge` now says so
(clayton-6xu.3.10).

**It confirms two figures that were flagged as derived.**

* *The charge turn gets its two post-successful-move advances.* `execute_move`'s charge branch
  returns ``successful=True`` on the reasoning that the move went off and printed a message, with
  the caveat that "nothing has watched a charge turn in the emulator" (notes/platinum.md sec 13).
  Turn 1 watches one: 17 advances, which is only consistent with the charge turn being credited.
* *No move-selection roll on the fire turn.* Turn 2 has none, where every other turn has one --
  `Battler_CanPickCommand` is FALSE for a locked battler, and this is the measurement.

**And it confirms the hardware report** that a paralysis-broken charge ends the vanish: turn 3 has
a selection roll again and our Screech lands, rather than a delayed Shadow Force firing.

Expectations are PARSED FROM THE LOG rather than copied out of it, so the two cannot drift. The
only hand-written figures are the battlers, and those come from the log's own `mon` records.
"""
import json
import unittest
from pathlib import Path

from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, BattleState, Battler
from claytonlib.battle_compass import tokens as tok

_LOG = Path(__file__).resolve().parent.parent / "data" / "battle_logs" / "giratina.jsonl"

#: The gdb symboliser resolves these by nearest preceding symbol, so the NAMES in the log are
#: unrelated to what the sites do ("ChooseTraceTarget" against a Magneton, for instance). The
#: addresses are what identify them, and these four are pinned by what the log itself shows:
#: `0x0224c6d4` always arrives in runs of four at the top of a turn, `0x02260e1a` once per turn
#: except the fire turn, `0x0224ec8e` immediately precedes every "paralyzed" message, and
#: `0x0224f230` is the accuracy PC already identified in uxie1.jsonl (`sim.execute_move`).
SELECT = "0x02260e1a"
BEFORE = "0x0224c6d4"


def _records():
    return json.loads(_LOG.read_text())


def _turns():
    """``[(selection rolls, total advances, [messages]), ...]`` for each turn in the log.

    A turn begins at the first of a run of four `BEFORE` rolls; the selection roll belonging to it
    sits in the gap before that run, which is why it is counted backwards from there rather than
    forwards.
    """
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
        rolls = sum(1 for e in events[i:end]
                    if e[0] == "roll" and e[1] != SELECT)
        msgs = [e[1] for e in events[i:end] if e[0] == "msg" and "What will" not in e[1]]
        out.append((selects, rolls + selects, msgs))
    return out


def _ours() -> Battler:
    """The log's `mon` record for battler 0: Magneton, Lv54, moves 86/103/48/49."""
    return Battler(name="THE RADIO", level=54, types=("Electric", "Steel"),
                   stats={"hp": 134, "atk": 106, "def": 113,
                          "spa": 148, "spd": 101, "spe": 118},
                   moves=("Thunder Wave", "Screech", "Supersonic", "Sonic Boom"),
                   pp=(20, 40, 20, 20), ability="Magnet Pull")


def _giratina() -> Battler:
    """Battler 1, after the override: Lv47, Bold, the stats the log records."""
    return Battler(name="Giratina", level=47, types=("Ghost", "Dragon"),
                   stats={"hp": 204, "atk": 96, "def": 145,
                          "spa": 111, "spd": 119, "spe": 90},
                   moves=("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force"),
                   pp=(5, 5, 15, 5), ability="Levitate")


#: Thunder Wave, then Screech for the rest. Read off the log's messages.
ACTIONS = [Action.MOVE_1] + [Action.MOVE_2] * 5


def _replay():
    config = HuntConfig(target_catch_rate=3, target_has_pressure=False)
    state = BattleState(ours=_ours(), target=_giratina(),
                        rng=opening_rng(int(_records()["forced_seed"], 16), config))
    out, previous = [], state.rng_offset
    for action in ACTIONS:
        state = simulate_turn(state, action, config)
        out.append((state.rng_offset - previous, tok.render_turn(state.log[-1]), state))
        previous = state.rng_offset
    return out


class TestTheLogIsWhatWeThinkItIs(unittest.TestCase):
    """Guards against the parse silently going vacuous, which would make every assertion below
    pass for the wrong reason."""

    def test_the_seed_was_forced_and_confirmed(self):
        records = _records()
        self.assertEqual(records["forced_seed"], "0x4e0238ab")
        seed = next(r["seed"] for r in records["records"] if "seed" in r)
        self.assertTrue(seed["confirmed"])
        self.assertEqual(seed["seedRandNext"], records["forced_seed"])

    def test_it_parses_to_six_turns(self):
        self.assertEqual(len(_turns()), 6)

    def test_the_messages_describe_the_battle_we_replay(self):
        joined = " ".join(" ".join(t[2]) for t in _turns())
        for expected in ("used Thunder Wave", "vanished instantly", "used Screech",
                         "paralyzed! It can't move", "used AncientPower", "used Ominous Wind"):
            with self.subTest(expected):
                self.assertIn(expected, joined.replace("’", "'"))


class TestEveryTurnMatches(unittest.TestCase):
    """The whole point: advance counts turn by turn, against the figures parsed from the log."""

    def test_the_advance_counts_agree(self):
        log = _turns()
        for n, ((_, expected, msgs), (got, rendered, _state)) in enumerate(zip(log, _replay()), 1):
            with self.subTest(turn=n, log_says=" / ".join(msgs)[:60]):
                self.assertEqual(got, expected)

    def test_the_total_agrees(self):
        """Stated separately because a compensating pair of errors would pass the per-turn check
        only if they fell in the same turn, and this is the cheaper thing to read in a failure."""
        self.assertEqual(sum(t[0] for t in _replay()), sum(t[1] for t in _turns()))

    def test_the_targets_move_choices_agree(self):
        """Not just the counts -- the stream has to be in the right PLACE, and the selection roll
        is what reads it. Ancient Power on turn 3 and Ominous Wind on turns 4 and 6."""
        expected = {3: "E2", 4: "E1", 6: "E1"}
        replay = _replay()
        for turn, token in expected.items():
            with self.subTest(turn=turn):
                self.assertIn(token, replay[turn - 1][1])

    def test_our_hp_agrees_at_every_point_the_log_records_one(self):
        """The strongest single check in the file: an HP figure is a damage roll read back, so
        matching all three means the stream is aligned to the roll, not merely to the count."""
        recorded = [h["hp"] for r in _records()["records"] if "hp" in r
                    for h in r["hp"] if h["battler"] == 0 and h["hp"] not in (0, 134)]
        replayed = [s.ours.hp for _, rendered, s in _replay() if "HP" in rendered]
        self.assertEqual(replayed, recorded)


class TestTheBugItFound(unittest.TestCase):
    """Turn 2 against turn 5: the controlled pair that isolates the charge-break cost."""

    def _pair(self):
        log = _turns()
        return log[1], log[4]

    def test_both_turns_are_the_same_prevention(self):
        broke, plain = self._pair()
        for turn in (broke, plain):
            self.assertIn("can't move", " ".join(turn[2]).replace("’", "'"))

    def test_but_the_one_that_broke_a_charge_costs_two_more(self):
        """The two totals are 14 and 15, which hides it -- turn 2 spends no selection roll and
        turn 5 does, and our own move landed on one and missed on the other. Peeling off
        everything the two turns do NOT share leaves the target's half plus end-of-turn, and that
        is **6 against 4**.

        Built from `battle.turn`'s constants rather than from hand-written numbers, so the
        subtraction cannot quietly stop meaning what it says.
        """
        from claytonlib.battle import turn as costs

        broke, plain = self._pair()
        shared = costs.BEFORE_TURN_ADVANCES + 1 + costs.BETWEEN_TURN_ADVANCES + 1  # +acc +paralysis
        # Our Screech missed on the breaking turn and landed on the plain one, so only the latter
        # is credited post-move advances for OUR half.
        broke_tail = broke[1] - broke[0] - shared - 0
        plain_tail = plain[1] - plain[0] - shared - costs.POST_SUCCESSFUL_MOVE_ADVANCES
        self.assertEqual((broke_tail, plain_tail), (6, 4))
        self.assertEqual(broke_tail - plain_tail, costs.POST_SUCCESSFUL_MOVE_ADVANCES,
                         "the break costs exactly one post-move block")

    def test_the_simulator_now_spends_the_extra_two(self):
        replay = _replay()
        self.assertEqual(replay[1][0], 14)
        self.assertEqual(replay[4][0], 15)


class TestTheFiguresItConfirms(unittest.TestCase):
    """Two things `notes/platinum.md` sec 13 flagged as derived, now measured."""

    def test_the_fire_turn_spends_no_selection_roll(self):
        log = _turns()
        self.assertEqual(log[1][0], 0, "turn 2 is the fire turn and must spend no selection roll")
        for n in (0, 2, 3, 4, 5):
            with self.subTest(turn=n + 1):
                self.assertEqual(log[n][0], 1)

    def test_the_charge_turn_is_credited_its_post_move_advances(self):
        """Turn 1's 17 advances are only consistent with the charge turn counting as successful:
        1 selection + 4 before + 1 accuracy + 4 (our post + between) + 1 paralysis + 0 move rolls
        + 2 post + 4 end. Drop the 2 and it is 15.
        """
        self.assertEqual(_turns()[0][1], 17)
        self.assertEqual(_replay()[0][0], 17)

    def test_the_broken_charge_releases_it_for_the_next_turn(self):
        """The hardware report, measured: turn 3 has a selection roll and our Screech lands, which
        it could not if Giratina were still away."""
        log, replay = _turns(), _replay()
        self.assertEqual(log[2][0], 1)
        self.assertNotIn("M2-", replay[2][1])
        self.assertIsNone(replay[1][2].target.charging_slot)


if __name__ == "__main__":
    unittest.main()
