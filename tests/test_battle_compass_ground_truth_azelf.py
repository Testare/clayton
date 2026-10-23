"""The forced-seed Platinum Azelf run, replayed turn by turn.

`data/battle_logs/azelf_failure.jsonl` is a gdb recording of the Valor Cavern encounter with the
battle seed forced to 0x49023160 (the reader read it back and confirmed it). 15 turns, 273 rolls,
and it was recorded because the simulator got a turn WRONG: on the turn BEEG QRO used Mean Look,
Azelf used Swift and Clayton predicted Uproar.

The two bugs behind that are `sim._tick_uproar`'s missing `BattleContext_MoveFailed` branch
(clayton-6xu.7.8) and the move-selection roll `simulate_turn` charged to `rng_offset` on a turn
the target could not pick a command (clayton-6xu.7.9). Both are measured here rather than argued:
the fixture is the recording, and a one-roll error anywhere makes every later turn unmatchable.

What the run exercises that nothing else does:

* **Three separate Uproars**, with rolled durations 3, 3 and 6, including one cut short by a full
  paralysis and one still running when the recording ends.
* **A Future Sight landing twice**, once on the Pokemon that banked it and once on a different
  one that was switched in afterwards.
* Taunt landing on the target, Haze wiping three turns of Screech, two switches, a Hyper Potion,
  Leftovers, and Honchkrow's Insomnia.

`data/` is gitignored, so this SKIPS where the recording is absent -- same as the Suicune and
Ho-Oh ground-truth modules.
"""
import json
import pathlib
import re
import unittest

from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState
from claytonlib.battle_compass import tokens as tok
from claytonlib.safari import advance_rng

LOG = pathlib.Path(__file__).resolve().parents[1] / "data" / "battle_logs" / "azelf_failure.jsonl"
#: The four CHECK_PRE_MOVE_ACTIONS rolls, which every turn spends. The turn delimiter CANNOT be
#: the move-selection roll the way the Ho-Oh harness's is: that roll is exactly the one an
#: Uproar-locked turn skips, which is the whole subject here.
BEFORE_TURN_ADDR = "0x0224c6d4"
#: The wild move-selection roll, when the turn spends one. Folded into the turn it opens.
CHOICE_ADDR = "0x02260e1a"
#: Azelf is Levitate, not Pressure -- so our PP is spent single, and `target_has_pressure`
#: defaults the other way.
HUNT = HuntConfig(target_catch_rate=3, target_has_pressure=False)

#: Levels, stats, moves and PP read off the recording's own `mon` records; nicknames and held
#: items are the player's, which the recording does not carry.
PARTY = {
    "magneton": dict(name="THE RADIO", level=54, types=("Electric", "Steel"),
                     stats={"hp": 134, "atk": 106, "def": 113, "spa": 148, "spd": 101,
                            "spe": 118},
                     moves=("Thunder Wave", "Screech", "Supersonic", "Sonic Boom"),
                     pp=(19, 40, 19, 20), ability="Sturdy", held_item=""),
    "smeargle": dict(name="CATCHMONKE", level=64, types=("Normal",),
                     stats={"hp": 168, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
                     moves=("Spore", "Sweet Scent", "Mean Look", "False Swipe"),
                     pp=(15, 20, 5, 40), ability="Technician", held_item=""),
    "honchkrow": dict(name="BEEG QRO", level=52, types=("Dark", "Flying"),
                      stats={"hp": 214, "atk": 166, "def": 75, "spa": 110, "spd": 107,
                             "spe": 94},
                      moves=("Taunt", "Haze", "Fly", "Mean Look"),
                      pp=(20, 30, 15, 5), ability="Insomnia", held_item="Leftovers"),
}
#: Send-out order, which is what the S tokens number.
ORDER = ("magneton", "smeargle", "honchkrow")
NICK = {"THE RADIO": "magneton", "CATCHMONKE": "smeargle", "BEEG QRO": "honchkrow"}
TARGET_MOVES = ("Swift", "Uproar", "Future Sight", "Nasty Plot")
#: Azelf's PP at Lv50, from the recording's `mon` record for battler 1.
TARGET_PP = (20, 10, 15, 20)

USED = re.compile(r"^(.+?) used\s+(.+?)!", re.S)
GO = re.compile(r"^(?:Go! |Your foe.s weak!\s*Get .em, )(.+?)!*$", re.S)


def clean(text):
    """One message, whitespace collapsed and the ROM's curly apostrophe flattened to ASCII.

    Platinum prints U+2019 in "It can’t move!" and "The wild AZELF’s Defense", so every
    string compared against a message would otherwise have to carry the same character.
    """
    return " ".join(text.split()).replace("’", "'")


def require(case):
    if not LOG.exists():
        case.skipTest(f"{LOG} not present")


def load():
    return json.loads(LOG.read_text())


def turns_of(records):
    """(records before turn 1, [one turn's records, ...]).

    Each turn spends exactly four rolls at `BEFORE_TURN_ADDR` in a row, so every fourth one is a
    turn head; the move-selection roll that precedes it is pulled in when the turn spent one.
    """
    heads = [i for i, r in enumerate(records)
             if "roll" in r and r["roll"]["addr"] == BEFORE_TURN_ADDR][::4]
    marks = []
    for head in heads:
        start = head
        for j in range(head - 1, -1, -1):
            if "roll" in records[j]:
                if records[j]["roll"]["addr"] == CHOICE_ADDR:
                    start = j
                break
        marks.append(start)
    return records[:marks[0]], [records[a:b] for a, b in zip(marks, marks[1:] + [len(records)])]


def battler(species, slot):
    fields = dict(PARTY[species])
    moves, pp = fields.pop("moves"), fields.pop("pp")
    return Battler(moves=moves, pp=pp, party_slot=slot, **fields)


def target_of(log):
    """Azelf as the recorder's override actually wrote it: Lv50, Lax, 7/13/13/11/8/24."""
    after = [r for r in log["records"] if "override" in r][0]["override"]["after"]
    return Battler(name="Azelf", level=50, types=("Psychic",),
                   stats={k: after["stats"][k] for k in ("hp", "atk", "def", "spa", "spd", "spe")},
                   moves=TARGET_MOVES, pp=TARGET_PP, ability="Levitate")


def read_action(msgs, ours, turn):
    """(Action, kwargs) for one turn, from the emulator's own messages."""
    if any("Used the Hyper Potion" in m for m in msgs):
        return Action.ITEM, {"item_code": "hp"}
    if any("switch out!" in m or "enough!" in m for m in msgs):
        for m in msgs:
            if (gm := GO.match(m.strip())):
                return Action.SWITCH, {"who": NICK[" ".join(gm.group(1).split()).upper()]}
    for m in msgs:
        mm = USED.match(m.strip())
        if mm and NICK.get(" ".join(mm.group(1).split()).upper()) == ours:
            want = " ".join(mm.group(2).split()).lower().replace(" ", "")
            for i, mv in enumerate(PARTY[ours]["moves"]):
                if mv.lower().replace(" ", "") == want:
                    return (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4)[i], {}
            raise AssertionError(f"turn {turn}: {want!r} is not one of {ours}'s moves")
    raise AssertionError(f"turn {turn}: no action in {msgs}")


class TestTheLogIsOurStream(unittest.TestCase):
    """Before any turn is compared: is the recording even the same LCRNG?"""

    def test_every_logged_roll_is_advance_rng_from_the_forced_seed(self):
        require(self)
        log = load()
        state = int(log["forced_seed"], 16)
        rolls = [r["roll"] for r in log["records"] if "roll" in r]
        self.assertEqual(len(rolls), 273)
        for i, roll in enumerate(rolls):
            state = advance_rng(state)
            self.assertEqual(state >> 16, roll["val"], f"diverges at roll {i} ({roll['func']})")

    def test_the_battle_start_advances_are_six(self):
        """Platinum's Valor Cavern spends the same six as the Bell Tower, and they are a
        different six: four in `BattleContext_InitCounters` and two at the send-out."""
        require(self)
        intro, turns = turns_of(load()["records"])
        self.assertEqual(len([r for r in intro if "roll" in r]), HUNT.battle_start_advances)
        self.assertEqual(len(turns), 15)

    def test_the_target_spent_a_selection_roll_on_nine_turns_of_fifteen(self):
        """The six it skipped are the Uproar-locked ones, and that count is the measurement both
        fixed bugs turn on: six locked turns, six withheld rolls."""
        require(self)
        rolls = [r["roll"] for r in load()["records"] if "roll" in r]
        self.assertEqual(len([r for r in rolls if r["addr"] == CHOICE_ADDR]), 9)


class TestTheRunReplaysExactly(unittest.TestCase):
    """The whole point. Per turn: rolls spent, both sides' HP, and which move Azelf chose."""

    def _replay(self):
        log = load()
        party = {s: battler(s, i + 1) for i, s in enumerate(ORDER)}
        state = BattleState(ours=party["magneton"], target=target_of(log), phase=1,
                            bench=tuple(party[s] for s in ORDER if s != "magneton"),
                            rng=opening_rng(int(log["forced_seed"], 16), HUNT))
        _, chunks = turns_of(log["records"])
        by_name = {v.name: k for k, v in party.items()}
        problems, rendered_turns = [], []
        for turn, block in enumerate(chunks, start=1):
            msgs = [clean(r["msg"]) for r in block if "msg" in r]
            rolls = len([r for r in block if "roll" in r])
            hp = [(x["battler"], x["hp"], x["max"])
                  for r in block if "hp" in r for x in r["hp"]]
            action, extra = read_action(msgs, by_name[state.ours.name], turn)
            kwargs = {}
            if "item_code" in extra:
                kwargs["item_code"] = extra["item_code"]
            if "who" in extra:
                names = [b.name for b in state.bench]
                kwargs["bench_slot"] = names.index(party[extra["who"]].name)
            nxt = simulate_turn(state, action, HUNT, **kwargs)
            rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
            rendered_turns.append(rendered)
            where = f"turn {turn} ({rendered})"
            spent = nxt.rng_offset - state.rng_offset
            if spent != rolls:
                problems.append(f"{where}: rolls sim={spent} log={rolls}")
            ours = [h for h in hp if h[0] == 0]
            if ours and ours[-1][2] == nxt.ours.max_hp and nxt.ours.hp != ours[-1][1]:
                problems.append(f"{where}: our HP sim={nxt.ours.hp} log={ours[-1][1]}")
            theirs = [h for h in hp if h[0] == 1]
            if theirs and nxt.target.hp != theirs[-1][1]:
                problems.append(f"{where}: target HP sim={nxt.target.hp} log={theirs[-1][1]}")
            problems += [f"{where}: {p}" for p in self._semantics(msgs, rendered)]
            state = nxt
        return rendered_turns, problems

    @staticmethod
    def _semantics(msgs, rendered):
        """The MEANING of the turn, not just its cost."""
        out, joined = [], " | ".join(msgs)
        named = None
        for m in msgs:
            if m.startswith("The wild AZELF used"):
                want = " ".join(m.split("used")[1].split()).rstrip("!").lower().replace(" ", "")
                for i, mv in enumerate(TARGET_MOVES):
                    if mv.lower().replace(" ", "") == want:
                        named = i + 1
        slot = re.search(r"E(\d)", rendered)
        if named is not None and named != (int(slot.group(1)) if slot else None):
            out.append(f"target move sim={slot and slot.group(0)} log=E{named}")
        for label, in_log, in_tokens in (
            ("fully paralyzed", "It can't move!" in joined, "Epar" in rendered),
            ("our move missed", "attack missed" in joined, bool(re.search(r"M\d-", rendered))),
            ("crit", "A critical hit!" in joined, "!" in rendered),
            ("Future Sight landed", "took the Future Sight attack" in joined, "F" in rendered),
        ):
            if in_log != in_tokens:
                out.append(f"{label} sim={in_tokens} log={in_log}")
        return out

    def test_the_run_replays(self):
        require(self)
        rendered, problems = self._replay()
        self.assertEqual(problems, [])
        self.assertEqual(len(rendered), 15)

    def test_the_turn_the_recording_was_made_for(self):
        """Turn 11: Mean Look, and Azelf picks Swift because its Uproar ended a turn early.

        This is the reported failure. With `_tick_uproar` counting down instead of reading
        `BattleContext_MoveFailed`, the lock was still on and the simulator predicted E2 (Uproar)
        while spending no selection roll -- so the prediction AND every roll after it were wrong.
        """
        require(self)
        rendered, _ = self._replay()
        self.assertEqual(rendered[10], "M4E1hHP149")

    def test_the_uproar_that_a_full_paralysis_cut_short(self):
        """Turn 10. Azelf rolled a 3-turn Uproar on turn 9, was fully paralyzed on turn 10, and
        'The wild AZELF calmed down.' printed with a turn still on the counter."""
        require(self)
        log = load()
        _, chunks = turns_of(log["records"])
        tenth = [clean(r["msg"]) for r in chunks[9] if "msg" in r]
        self.assertIn("The wild AZELF is paralyzed! It can't move!", tenth)
        self.assertIn("The wild AZELF calmed down.", tenth)
        eleventh = [clean(r["msg"]) for r in chunks[10] if "msg" in r]
        self.assertIn("The wild AZELF used Swift!", eleventh)
        rendered, _ = self._replay()
        self.assertEqual(rendered[9], "S3EparFhHP166")


if __name__ == "__main__":
    unittest.main()
