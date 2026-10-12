"""Three forced-seed emulator runs of the Ho-Oh hunt, replayed turn by turn.

`data/battle_logs/hooh{1,2,3}.jsonl` are gdb recordings of the real SoulSilver encounter: every
RNG call with its address, every message, every HP change. Between them they cover 108 turns and
1,780 rolls -- switches, all three faint variants, a Revive, Static, Leftovers, Safeguard,
Light Screen, Intimidate, a burn, 21 ball throws, and Ho-Oh running three of its four moves out
of PP.

The analysis that built this is notes/hooh_log_replay.md; the harness it shares is
`one-offs/hooh_log_replay.py`. Kept as a test because the *stream* is the thing that cannot be
allowed to drift: a one-roll error anywhere makes every later turn of a real run unmatchable, and
a synthetic fixture cannot catch that -- it would drift with the code.

Three figures had to be inferred rather than read from a file (sec 4 of the note), and they are
part of the fixture: Ampharos holds Leftovers, Smeargle a Silk Scarf, Magneton a Choice Scarf.
Each is load-bearing -- removing one produces 2, 11 and 56 mismatching turns respectively.

`data/` is gitignored, so these tests SKIP where the logs are absent -- same as
`test_battle_compass_ground_truth.py` does for the Suicune recording.
"""
import json
import pathlib
import re
import unittest

from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status
from claytonlib.battle_compass import tokens as tok
from claytonlib.moves import resolve_move
from claytonlib.safari import advance_rng

LOGS = pathlib.Path(__file__).resolve().parents[1] / "data" / "battle_logs"
#: Every turn opens with the wild Pokemon's move-choice roll here, which makes it the turn
#: delimiter -- the message stream is useless for it, since the number of "What will X do?"
#: prompts depends on how the player navigated the menu.
CHOICE_ADDR = "0x0225e46e"
HUNT = HuntConfig(target_catch_rate=3, target_has_pressure=True)

#: The party as configured for the run, levels and stats from the player's profile.
PARTY = {
    "natu": dict(name="Adamant", level=23, types=("Psychic", "Flying"),
                 stats={"hp": 58, "atk": 37, "def": 26, "spa": 34, "spd": 31, "spe": 37},
                 moves=("Peck",), ability="Synchronize", held_item=""),
    "chatot": dict(name="Chatot", level=21, types=("Normal", "Flying"),
                   stats={"hp": 66, "atk": 35, "def": 25, "spa": 47, "spd": 28, "spe": 44},
                   moves=("Sing",), ability="Keen Eye", held_item=""),
    "ampharos": dict(name="AMY FAIR", level=94, types=("Electric",),
                     stats={"hp": 314, "atk": 139, "def": 184, "spa": 339, "spd": 212,
                            "spe": 145},
                     moves=("Flash", "Light Screen"), ability="Static",
                     held_item="Leftovers"),
    "granbull": dict(name="SCARY  DOG!", level=44, types=("Normal",),
                     stats={"hp": 162, "atk": 109, "def": 122, "spa": 64, "spd": 66, "spe": 52},
                     moves=("Charm",), ability="Intimidate", held_item=""),
    "magneton": dict(name="Magneton", level=49, types=("Electric", "Steel"),
                     stats={"hp": 122, "atk": 97, "def": 103, "spa": 134, "spd": 92, "spe": 107},
                     moves=("Thunder Wave", "Screech"), ability="Sturdy",
                     held_item="Choice Scarf"),
    "smeargle": dict(name="Smeargle", level=58, types=("Normal",),
                     stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160},
                     moves=("Sweet Scent", "False Swipe", "Spore", "Mean Look"),
                     ability="Technician", held_item="Silk Scarf"),
}
#: Send-out order, which is what the S/X/R tokens number.
ORDER = ("natu", "chatot", "ampharos", "granbull", "magneton", "smeargle")
NICK = {"ADAMANT": "natu", "CHATOT": "chatot", "FLASHDRIVE": "ampharos",
        "SCARY DOG": "granbull", "MAGNETON": "magneton"}
TARGET_MOVES = ("Sacred Fire", "Punishment", "Ancient Power", "Safeguard")
SHAKES = ("Oh, no!", "Aww!", "Aargh!", "Gah!")
#: Turns whose action left NO message in the log, with what the state change says it was. Both
#: are Revives; the recorder does not log item use (see the note, sec 5).
BAG = {"hooh2": {24: "smeargle"}, "hooh3": {13: "granbull"}}

USED = re.compile(r"^(.+?) used\s+(.+?)!", re.S)
SWITCH = re.compile(r"^(.+?), switch out!", re.S)
GO = re.compile(r"^(?:Go! |Your foe's weak!\s*Get 'em, )(.+?)!*$", re.S)


def species_of(nick):
    """Nicknames, normalised. Smeargle's comes through as mojibake, so anything unknown is it."""
    return NICK.get(" ".join(nick.split()).upper().rstrip("!"), "smeargle")


def battler(species, slot):
    fields = dict(PARTY[species])
    moves = fields.pop("moves")
    return Battler(moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
                   party_slot=slot, **fields)


def load(label):
    return json.loads((LOGS / f"{label}.jsonl").read_text())


def require(case, *labels):
    """Skip rather than fail where the recording is not on this machine."""
    for label in labels:
        if not (LOGS / f"{label}.jsonl").exists():
            case.skipTest(f"{LOGS / (label + '.jsonl')} not present")


def turns_of(records):
    """(records before the first turn, [one turn's records, ...])."""
    marks = [i for i, r in enumerate(records)
             if "roll" in r and r["roll"]["addr"] == CHOICE_ADDR]
    return records[:marks[0]], [records[a:b] for a, b in zip(marks, marks[1:] + [len(records)])]


def target_of(log):
    """Ho-Oh as the recorder's override actually wrote it: Lv70, Adamant, 31/31/31/17/31/31."""
    after = [r for r in log["records"] if "override" in r][0]["override"]["after"]
    return Battler(name="Ho-Oh", level=70, types=("Fire", "Flying"),
                   stats={k: after["stats"][k] for k in
                          ("hp", "atk", "def", "spa", "spd", "spe")},
                   moves=TARGET_MOVES, pp=(5, 5, 5, 25), ability="Pressure")


def read_action(msgs, ours, party, label, turn):
    """(Action, extra kwargs) for one turn, from the emulator's own messages."""
    if turn in BAG.get(label, {}):
        return Action.REVIVE, {"who": BAG[label][turn]}
    for m in msgs:
        if SWITCH.match(m):
            for g in msgs:
                if (gm := GO.match(g.strip())):
                    return Action.SWITCH, {"who": species_of(gm.group(1))}
    for m in msgs:
        if "used" in m and "Ball" in m:
            return Action.STANDARD_BALL, {}
        mm = USED.match(m.strip())
        if mm and species_of(mm.group(1)) == ours:
            want = " ".join(mm.group(2).split()).lower().replace(" ", "")
            for i, mv in enumerate(party[ours].moves):
                if mv.lower().replace(" ", "") == want:
                    return (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4)[i], {}
            raise AssertionError(f"{label} turn {turn}: {want!r} is not one of {ours}'s moves")
    if any("Got away safely" in m for m in msgs):
        return None, {}
    if any("fainted" in m for m in msgs):
        return Action.FAINTED, {}
    raise AssertionError(f"{label} turn {turn}: no action in {msgs}")


class TestTheLogsAreOurStream(unittest.TestCase):
    """Before any turn is compared: is the recording even the same LCRNG?"""

    def test_every_logged_roll_is_advance_rng_from_the_forced_seed(self):
        require(self, "hooh1", "hooh2", "hooh3")
        for label in ("hooh1", "hooh2", "hooh3"):
            log = load(label)
            state = int(log["forced_seed"], 16)
            rolls = [r["roll"] for r in log["records"] if "roll" in r]
            self.assertGreater(len(rolls), 400, label)
            for i, roll in enumerate(rolls):
                state = advance_rng(state)
                self.assertEqual(state >> 16, roll["val"],
                                 f"{label} diverges at roll {i} ({roll['func']})")

    def test_the_battle_start_advances_are_six(self):
        """Verified for a DIFFERENT encounter from the one the figure was measured on, and three
        times over: 4 at bellShimmerReplaceGraphics plus 2 more, before the first move choice."""
        require(self, "hooh1", "hooh2", "hooh3")
        for label in ("hooh1", "hooh2", "hooh3"):
            intro, _ = turns_of(load(label)["records"])
            self.assertEqual(len([r for r in intro if "roll" in r]),
                             HUNT.battle_start_advances, label)


class TestTheRunsReplayExactly(unittest.TestCase):
    """The whole point. Per turn: rolls spent, both sides' HP, which move Ho-Oh chose, and how
    each move resolved."""

    def _replay(self, label):
        log = load(label)
        party = {s: battler(s, i + 1) for i, s in enumerate(ORDER)}
        state = BattleState(ours=party["natu"], target=target_of(log), phase=1,
                            bench=tuple(party[s] for s in ORDER if s != "natu"),
                            rng=opening_rng(int(log["forced_seed"], 16), HUNT))
        _, chunks = turns_of(log["records"])
        by_name = {v.name: k for k, v in party.items()}
        problems, compared = [], 0
        for turn, block in enumerate(chunks, start=1):
            msgs = [" ".join(r["msg"].split()) for r in block if "msg" in r]
            rolls = len([r for r in block if "roll" in r])
            hp = [(x["battler"], x["hp"], x["max"])
                  for r in block if "hp" in r for x in r["hp"]]
            if not msgs:
                break        # hooh1 ends mid-turn: one move-choice roll and no messages at all
            action, extra = read_action(msgs, by_name[state.ours.name], party, label, turn)
            if action is None:
                break                                   # "Got away safely!" -- the run ends
            kwargs = {}
            who = extra.get("who")
            if who is not None:
                names = [b.name for b in state.bench]
                kwargs["bench_slot"] = names.index(party[who].name)
            # Who the player sent out after a faint, read off the log rather than defaulted.
            for j, m in enumerate(msgs):
                if "Use next" in m or "weak!" in m:
                    for g in msgs[j:]:
                        if (gm := GO.match(g.strip())):
                            kwargs["replacement"] = party[species_of(gm.group(1))].party_slot
                            break
                    break
            nxt = simulate_turn(state, action, HUNT, **kwargs)
            rendered = tok.render_turn(tok.normalise(nxt.log[-1]))
            where = f"{label} turn {turn} ({rendered})"
            spent = nxt.rng_offset - state.rng_offset
            if spent != rolls:
                problems.append(f"{where}: rolls sim={spent} log={rolls}")
            theirs = [h for h in hp if h[0] == 1]
            if theirs and nxt.target.hp != theirs[-1][1]:
                problems.append(f"{where}: target HP sim={nxt.target.hp} log={theirs[-1][1]}")
            ours = [h for h in hp if h[0] == 0]
            if ours and ours[-1][2] == nxt.ours.max_hp and nxt.ours.hp != ours[-1][1]:
                problems.append(f"{where}: our HP sim={nxt.ours.hp} log={ours[-1][1]}")
            problems += [f"{where}: {p}" for p in self._semantics(msgs, rendered)]
            compared += 1
            state = nxt
        return compared, problems

    @staticmethod
    def _semantics(msgs, rendered):
        """The MEANING of the turn, not just its cost."""
        out, joined = [], " | ".join(msgs)
        named = None
        for m in msgs:
            if m.startswith("The wild HO-OH used"):
                want = " ".join(m.split("used")[1].split()).rstrip("!").lower().replace(" ", "")
                for i, mv in enumerate(TARGET_MOVES):
                    if mv.lower().replace(" ", "") == want:
                        named = i + 1
        slot = re.search(r"E(\d)", rendered)
        if named != (int(slot.group(1)) if slot else None):
            out.append(f"target move sim={slot and slot.group(0)} log=E{named}")
        for label, in_log, in_tokens in (
            ("fully paralyzed", "is paralyzed! It can't move!" in joined, "Epar" in rendered),
            ("target missed", "attack missed" in joined, bool(re.search(r"E\d-", rendered))),
            ("Static", "Static paralyzed" in joined, "*" in rendered),
            ("crit", "A critical hit!" in joined, "!" in rendered),
        ):
            if in_log != in_tokens:
                out.append(f"{label} sim={in_tokens} log={in_log}")
        if ("'s Attack rose!" in joined or "was burned!" in joined) and "~" not in rendered:
            out.append("the secondary is missing from the tokens")
        if "Ball!" in joined:
            shakes = next((i for i, s in enumerate(SHAKES) if s in joined), None)
            sim = re.search(r"[CP](\d)", rendered)
            if shakes != (int(sim.group(1)) if sim else None):
                out.append(f"shakes sim={sim and sim.group(0)} log={shakes}")
        return out

    def test_hooh1(self):
        """57 turns, 18 ball throws, and the Sweet Scent PP that Pressure doubles."""
        require(self, "hooh1")
        compared, problems = self._replay("hooh1")
        self.assertEqual(problems, [])
        self.assertEqual(compared, 57)

    def test_hooh2(self):
        """28 turns: a burn, both faint variants, a Revive, and Light Screen."""
        require(self, "hooh2")
        compared, problems = self._replay("hooh2")
        self.assertEqual(problems, [])
        self.assertEqual(compared, 28)

    def test_hooh3(self):
        """23 turns, and the one that found clayton-957.10.14: Static fires on turn 3, Granbull
        is fainted by a Sacred Fire that procs its burn on turn 9, and the Revive on turn 13 has
        to bring back a Pokemon that is NOT burned."""
        require(self, "hooh3")
        compared, problems = self._replay("hooh3")
        self.assertEqual(problems, [])
        self.assertEqual(compared, 23)


class TestWhatTheFixtureDependsOn(unittest.TestCase):
    """The three held items are inferred, not read from a file, so each one is pinned."""

    def test_each_held_item_is_load_bearing(self):
        for species, expected in (("ampharos", "Leftovers"), ("smeargle", "Silk Scarf"),
                                  ("magneton", "Choice Scarf")):
            self.assertEqual(PARTY[species]["held_item"], expected)

    def test_removing_the_choice_scarf_desyncs_the_stream(self):
        """Not a degradation -- a desync. 107 x 1.5 = 160 beats Ho-Oh's 152, so without it the
        Speed order flips on turn 2 of hooh1 and nothing after it matches. This is the failure
        mode a mis-set held item produces in a real run (clayton-957.10.15)."""
        require(self, "hooh1")
        saved = PARTY["magneton"]["held_item"]
        PARTY["magneton"]["held_item"] = ""
        try:
            _, problems = TestTheRunsReplayExactly()._replay("hooh1")
        finally:
            PARTY["magneton"]["held_item"] = saved
        self.assertGreater(len(problems), 40,
                           "the test would not notice a wrong held item at all")
