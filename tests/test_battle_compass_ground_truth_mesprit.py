"""Ground truth: the three roaming-Mesprit recordings, 21 turns, and the first roamer on film.

`data/battle_logs/mesprit.jsonl` and `mesprit1.jsonl` (seed ``0x64018903``) and `mesprit2.jsonl`
(``0x78017333``) are gdb captures of Platinum's roaming Mesprit against a Wobbuffet (Shadow Tag,
Speed 21), a Smeargle (Speed 177) and a Honchkrow (Speed 94) — the roamer's Speed being 100, which
is what makes the trap work for one of them and fail for another.

**Every roll count, every HP figure and every rendered token matches across all 21 turns**, which
is what this file asserts. What it measures that nothing else could:

* **The roamer AI's cost, exactly.** 80 rolls at the four-damage-roll call site over 20 turns
  (``0x0221fc96``, four per turn without exception) and 14 at the tie-break (``0x0221fe12``) — so
  14 turns chose a move and 6 chose Escape, and the wild side's own selection call site
  (``0x02260e1a``, the one every other ground-truth log is segmented on) **never fires at all**.
* **Shadow Tag is a lead-only trap.** `mesprit1` is two turns long for one reason: a Wobbuffet
  switched in behind an already-chosen escape, which does not stop it.
* **A faster Mean Look rescues an already-chosen escape**, three times over.
* **Sleep does not hold a roamer.** `mesprit2` T9–T11 are asleep and T11 still leaves.
* **Lucky Chant's crit roll is still spent**, and `mesprit2` dates its expiry to the turn.

**And it found a bug that predates roamers.** `mesprit2` T8 sleeps the target with Spore and the
simulator refused to, because `safeguard_turns` was a single counter documented as the target's --
"nothing in any party can set one". Wobbuffet has Safeguard and Wobbuffet is the standard roamer
trapper, so our own Safeguard blocked our own Spore. Fixed by giving our side its own counter; the
log is the only reason anybody would have noticed, since the roll count on that turn happened to
agree anyway and only the two turns AFTER it diverged.

One fixture note. **The target's Defence and Sp. Def in these logs are 23933**, not the 125 the
recorder meant to write (`stats_verified: false` -- see clayton-957.35.22). That is what the game
actually had in memory, so it is what the replay uses and what makes the numbers line up: our
False Swipe does exactly 1 damage against it. Nothing here depends on a sane defensive stat, and
nothing here may be read as validating one.

(clayton-957.35.17, .15, .16, .2)
"""
import json
import unittest
from pathlib import Path

from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.sim import (
    BATTLE_START_ADVANCES, HuntConfig, opening_rng, simulate_turn,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler

_LOGS = Path(__file__).resolve().parent.parent / "data" / "battle_logs"

#: The four BeforeTurn advances, which every turn spends and nothing else uses -- so the first of
#: them is where a turn starts. The same address `giratina3`'s fixture segments on.
BEFORE = "0x0224c6d4"
#: `TrainerAI_Init`'s four damage rolls and `TrainerAI_MainSingles`'s tie-break. Named by address
#: because the symbols gdb reports for them (``ov10_0221FC78`` / ``ov10_0221FE10``) are
#: nearest-symbol guesses; the addresses and the grouping are not.
AI_DAMAGE = "0x0221fc96"
AI_TIE_BREAK = "0x0221fe12"
#: The wild side's `% validMovesCount` pick, which a roamer never reaches.
WILD_SELECT = "0x02260e1a"

SEEDS = {"mesprit": 0x64018903, "mesprit1": 0x64018903, "mesprit2": 0x78017333}


def _records(name):
    return json.loads((_LOGS / f"{name}.jsonl").read_text())


def _turns(name):
    """One dict per turn: the rolls it spent, its messages and its HP reports.

    The AI block for a turn sits BEFORE that turn's first BeforeTurn roll -- selection happens
    first -- so it is collected from the preceding gap and excluded from the body, or it would be
    counted twice (once for its own turn and once as the tail of the one before).
    """
    events = []
    for record in _records(name)["records"]:
        kind = next(iter(record))
        if kind == "roll":
            events.append(("roll", record[kind]["addr"]))
        elif kind == "msg":
            events.append(("msg", " ".join(record[kind].split())))
        elif kind == "hp":
            events.append(("hp", tuple((h["battler"], h["hp"]) for h in record[kind])))
    starts = [i for i, e in enumerate(events)
              if e == ("roll", BEFORE) and (i == 0 or events[i - 1] != ("roll", BEFORE))]
    out = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(events)
        gap = starts[n - 1] if n else 0
        ai = [e for e in events[gap:i]
              if e[0] == "roll" and e[1] in (AI_DAMAGE, AI_TIE_BREAK)]
        body = [e for e in events[i:end]
                if e[0] == "roll" and e[1] not in (AI_DAMAGE, AI_TIE_BREAK)]
        out.append({
            "ai": len(ai),
            "tie_break": sum(1 for e in ai if e[1] == AI_TIE_BREAK),
            "rolls": len(ai) + len(body),
            "msgs": [e[1] for e in events[i:end]
                     if e[0] == "msg" and "What will" not in e[1]],
            "hp": [e[1] for e in events[i:end] if e[0] == "hp"],
        })
    return out


def _wobbuffet() -> Battler:
    """Shadow Tag (the log's ``"ability": 23``), Speed 21, and a Safeguard it really did use."""
    return Battler(name="Wobbuffet", level=25, types=("Psychic",),
                   stats={"hp": 130, "atk": 21, "def": 34, "spa": 21, "spd": 34, "spe": 21},
                   moves=("Counter", "Mirror Coat", "Safeguard", "Destiny Bond"),
                   pp=(20, 20, 25, 5), ability="Shadow Tag", party_slot=1)


def _smeargle() -> Battler:
    """The same Smeargle as `giratina3`: Technician (``"ability": 101``) and a Silk Scarf.

    **Neither is exercised here** and that is worth saying rather than leaving implied: the
    target's Defence is 23933, so False Swipe is floored at 1 damage whatever the attacker's
    multipliers are. They are in the fixture because it is the real Pokemon.
    """
    return Battler(name="CATCHMONKE", level=64, types=("Normal",),
                   stats={"hp": 168, "atk": 71, "def": 72, "spa": 50, "spd": 87, "spe": 177},
                   moves=("Spore", "Foresight", "Mean Look", "False Swipe"),
                   pp=(15, 40, 5, 40), ability="Technician", held_item="Silk Scarf",
                   party_slot=2)


def _honchkrow() -> Battler:
    """Speed 94 against the roamer's 100, which is the whole reason two of these runs end."""
    return Battler(name="BEEG QRO", level=52, types=("Dark", "Flying"),
                   stats={"hp": 214, "atk": 166, "def": 75, "spa": 110, "spd": 107, "spe": 94},
                   moves=("Taunt", "Haze", "Fly", "Mean Look"), pp=(20, 30, 15, 5),
                   ability="Insomnia", party_slot=3)


def _mesprit() -> Battler:
    """Lv50, Levitate, and the recorder's broken defences -- see the module docstring."""
    return Battler(name="Mesprit", level=50, types=("Psychic",),
                   stats={"hp": 155, "atk": 112, "def": 23933, "spa": 137, "spd": 23933,
                          "spe": 100},
                   moves=("Swift", "Lucky Chant", "Future Sight", "Charm"),
                   pp=(20, 30, 15, 20), ability="Levitate")


CONFIG = HuntConfig(target_catch_rate=3, target_has_pressure=False, target_is_roamer=True)

#: Our action per turn, read off each log's messages. Wobbuffet's Safeguard is slot 3 and
#: Smeargle's Mean Look slot 3; the bench index of a switch follows party order, so switching
#: Smeargle in leaves the bench as (Wobbuffet, Honchkrow).
#:
#: **`mesprit2` turn 9 is the one inference in this file.** Our action there spent no rolls, was
#: not a successful move (the turn is three rolls shorter than a move turn) and printed nothing the
#: recorder's message hook caught -- which narrows it to a bag action, all of which cost the same
#: nothing. A Revive is the one Testare described testing ("Choice Scarf Mean Look can still lock
#: the pokemon in while we use revives for other members"), and Wobbuffet had fainted two turns
#: earlier, so that is what it is modelled as. The assertion is about the roll COUNT, which every
#: bag action shares; nothing here distinguishes which one it was.
PLANS = {
    "mesprit1": [
        (Action.SWITCH, {"bench_slot": 0}),      # Wobbuffet out, Smeargle in
        (Action.SWITCH, {"bench_slot": 0}),      # Smeargle out, Wobbuffet back -- and it flees
    ],
    "mesprit": [
        (Action.MOVE_3, {}),                     # Wobbuffet's Safeguard
        (Action.SWITCH, {"bench_slot": 0}),      # Smeargle in
        (Action.MOVE_3, {}),                     # Mean Look, refusing the chosen escape
        (Action.MOVE_4, {}),                     # False Swipe, for its 1 damage
        (Action.MOVE_2, {}),                     # Foresight
        (Action.SWITCH, {"bench_slot": 1}),      # Honchkrow in, releasing the trap
        (Action.MOVE_4, {}),                     # ...and it flees before the Mean Look
    ],
    "mesprit2": [
        (Action.SWITCH, {"bench_slot": 0}),      # Smeargle in
        (Action.MOVE_3, {}),                     # Mean Look, refusing the chosen escape
        (Action.SWITCH, {"bench_slot": 0}),      # Wobbuffet back; Shadow Tag covers the release
        (Action.MOVE_3, {}),                     # Safeguard
        (Action.MOVE_3, {}),                     # Safeguard again -- fails
        (Action.MOVE_3, {"replacement": 2}),     # ...again, and Future Sight faints Wobbuffet
        (Action.MOVE_3, {}),                     # the replacement's Mean Look, in time
        (Action.MOVE_1, {}),                     # Spore
        (Action.REVIVE, {"bench_slot": 0}),      # see above
        (Action.SWITCH, {"bench_slot": 1}),      # Honchkrow in, releasing the trap
        (Action.MOVE_4, {}),                     # ...and it flees, asleep
    ],
}

BENCHES = {
    "mesprit1": (_smeargle(),),
    "mesprit": (_smeargle(), _honchkrow()),
    "mesprit2": (_smeargle(), _honchkrow()),
}


def _replay(name):
    """``[(rolls spent, rendered turn, state), ...]`` for one log."""
    state = BattleState(ours=_wobbuffet(), target=_mesprit(), bench=BENCHES[name],
                        rng=opening_rng(SEEDS[name], CONFIG))
    out, previous = [], state.rng_offset
    for action, extra in PLANS[name]:
        state = simulate_turn(state, action, CONFIG, **extra)
        out.append((state.rng_offset - previous, tok.render_turn(state.log[-1]), state.copy()))
        previous = state.rng_offset
        if state.over:
            break
    return out


class TestTheLogsAreWhatWeThinkTheyAre(unittest.TestCase):

    def test_the_seeds_were_forced_and_confirmed(self):
        for name, seed in SEEDS.items():
            records = _records(name)
            self.assertEqual(int(records["forced_seed"], 16), seed, name)
            confirmed = next(r["seed"] for r in records["records"] if "seed" in r)
            self.assertTrue(confirmed["confirmed"], name)

    def test_they_parse_to_two_seven_and_eleven_turns(self):
        self.assertEqual([len(_turns(n)) for n in ("mesprit1", "mesprit", "mesprit2")],
                         [2, 7, 11])

    def test_each_plan_is_as_long_as_its_log(self):
        for name in SEEDS:
            self.assertEqual(len(PLANS[name]), len(_turns(name)), name)

    def test_the_target_override_did_not_take_and_the_fixture_says_so(self):
        """The fixture must use what the GAME had, not what the recorder meant to write."""
        for name in SEEDS:
            override = next(r["override"] for r in _records(name)["records"] if "override" in r)
            self.assertFalse(override["stats_verified"], name)
            self.assertEqual(override["readback"]["stats"]["def"], 23933, name)
        self.assertEqual(_mesprit().stats["def"], 23933)

    def test_the_battle_start_advances_are_six_here_too(self):
        """Four in `BattleContext_InitCounters` plus two at the send-out, exactly as every
        Platinum static log shows -- so a ROAMER route encounter spends no more and no fewer, and
        `BATTLE_START_ADVANCES` needs no roamer variant (clayton-957.35.2)."""
        for name in SEEDS:
            events = _records(name)["records"]
            first_turn = next(i for i, r in enumerate(events)
                              if "roll" in r and r["roll"]["addr"] == AI_DAMAGE)
            intro = [r for r in events[:first_turn] if "roll" in r]
            self.assertEqual(len(intro), BATTLE_START_ADVANCES, name)


class TestTheRoamerAisCostIsMeasured(unittest.TestCase):

    def test_four_damage_rolls_every_turn_without_exception(self):
        for name in SEEDS:
            turns = _turns(name)
            for i, turn in enumerate(turns):
                self.assertEqual(turn["ai"] - turn["tie_break"], 4, f"{name} T{i + 1}")

    def test_the_tie_break_fires_on_fourteen_turns_of_twenty(self):
        """And its absence is the Escape decision, which is the whole point: the roll count says
        what the roamer decided before it acts."""
        ties = sum(t["tie_break"] for name in SEEDS for t in _turns(name))
        total = sum(len(_turns(name)) for name in SEEDS)
        self.assertEqual((ties, total), (14, 20))

    def test_the_wild_selection_call_site_never_fires(self):
        """A roamer takes the trainer-AI path, so the `% validMovesCount` pick every other
        ground-truth log is segmented on is simply absent from these."""
        for name in SEEDS:
            addrs = {r["roll"]["addr"] for r in _records(name)["records"] if "roll" in r}
            self.assertNotIn(WILD_SELECT, addrs, name)
            self.assertIn(AI_DAMAGE, addrs, name)


class TestTheReplayMatches(unittest.TestCase):
    """The load-bearing assertions: roll counts and HP, turn by turn, in all three logs."""

    def _assert_log(self, name):
        log, sim = _turns(name), _replay(name)
        self.assertEqual(len(sim), len(log), name)
        for i, ((spent, rendered, state), turn) in enumerate(zip(sim, log)):
            self.assertEqual(spent, turn["rolls"], f"{name} T{i + 1}: {rendered} vs {turn}")

    def test_mesprit1(self):
        self._assert_log("mesprit1")

    def test_mesprit(self):
        self._assert_log("mesprit")

    def test_mesprit2(self):
        self._assert_log("mesprit2")

    def test_every_hp_the_logs_report_is_reproduced(self):
        """Our HP, which is the only side with a believable defensive stat: Wobbuffet to 35 off a
        Swift, Smeargle to 128 off another, and the Future Sight that faints Wobbuffet."""
        expected = {
            ("mesprit", 5): 128,
            ("mesprit2", 3): 35,
        }
        for (name, turn), hp in expected.items():
            state = _replay(name)[turn - 1][2]
            self.assertEqual(state.ours.hp, hp, f"{name} T{turn}")

    def test_false_swipe_does_exactly_one_damage_through_that_defence(self):
        state = _replay("mesprit")[3][2]
        self.assertEqual(state.target.hp, 154)


class TestWhatTheLogsProveAboutTheTrap(unittest.TestCase):

    def test_a_shadow_tag_switched_in_behind_an_escape_does_not_stop_it(self):
        """`mesprit1` is two turns long because of this, and nothing else."""
        turns = _replay("mesprit1")
        self.assertEqual(turns[-1][1], "S1" + tok.escaped_token())
        self.assertTrue(turns[-1][2].target_fled)
        self.assertEqual(turns[-1][2].ours.name, "Wobbuffet")
        self.assertIn("fled", " ".join(_turns("mesprit1")[-1]["msgs"]))

    def test_a_faster_mean_look_refuses_an_already_chosen_escape(self):
        for name, turn in (("mesprit", 3), ("mesprit2", 2), ("mesprit2", 7)):
            rendered = _replay(name)[turn - 1][1]
            self.assertIn(tok.escape_failed_token(), rendered, f"{name} T{turn}")
            self.assertIn("can’t escape!", " ".join(_turns(name)[turn - 1]["msgs"]))

    def test_a_slower_mean_look_user_never_gets_the_chance(self):
        """Honchkrow at 94 against 100, twice -- and in both the run simply ends."""
        for name in ("mesprit", "mesprit2"):
            last = _replay(name)[-1]
            self.assertEqual(last[1], tok.escaped_token(), name)
            self.assertEqual(last[2].ours.name, "BEEG QRO", name)

    def test_switching_the_trapper_out_is_what_released_it_both_times(self):
        """`mesprit` T6 and `mesprit2` T10 are the switches, and the flee is the turn after."""
        for name, switch in (("mesprit", 6), ("mesprit2", 10)):
            after = _replay(name)[switch - 1][2]
            self.assertFalse(after.target_trapped, name)
            self.assertFalse(after.target_fled, name)

    def test_shadow_tag_covered_a_release_when_it_was_already_out(self):
        """`mesprit2` T3 switches Wobbuffet back IN, which clears the Mean Look -- and T4 is a
        move rather than an escape, because by then Shadow Tag is what the AI sees."""
        turns = _replay("mesprit2")
        self.assertFalse(turns[2][2].target_trapped)
        self.assertEqual(turns[2][2].ours.name, "Wobbuffet")
        self.assertNotIn(tok.escaped_token(), turns[3][1])
        self.assertEqual(_turns("mesprit2")[3]["tie_break"], 1)

    def test_sleep_does_not_hold_it(self):
        """`mesprit2` T8 sleeps it, T9 and T10 are slept turns, T11 it leaves anyway."""
        turns = _replay("mesprit2")
        for i in (7, 8, 9):
            self.assertIn(tok.prevented_token("E", "slp"), turns[i][1], f"T{i + 1}")
        self.assertTrue(turns[10][2].target_fled)


class TestWhatTheLogsProveAboutMesprit(unittest.TestCase):

    def test_the_moveset_is_the_one_the_log_reports(self):
        """``moves: [129, 381, 248, 204]`` -- Swift / Lucky Chant / Future Sight / Charm."""
        from claytonlib.battle_compass.targets import moveset
        from claytonlib.moves import resolve_move

        logged = next(r["mon"]["moves"] for r in _records("mesprit")["records"]
                      if "mon" in r and r["mon"]["battler"] == 1)
        self.assertEqual([resolve_move(m).number for m in moveset("mesprit", "platinum")],
                         logged)

    def test_charm_takes_two_stages_off_our_attack(self):
        """Three Charms land across these logs and each is "harshly fell"."""
        turns = _replay("mesprit")
        self.assertEqual(turns[0][2].ours.atk_stage, -2)
        self.assertIn("harshly fell", " ".join(_turns("mesprit")[0]["msgs"]))

    def test_lucky_chant_goes_up_and_expires_on_the_turn_the_log_says(self):
        """Used on `mesprit2` T6 and "wore off" at the end of T10: five turns, inclusive."""
        turns = _replay("mesprit2")
        self.assertEqual(turns[5][2].target_lucky_chant_turns, 4)
        self.assertEqual(turns[9][2].target_lucky_chant_turns, 0)
        self.assertIn("Lucky Chant wore off", " ".join(_turns("mesprit2")[9]["msgs"]))

    def test_a_future_sight_lands_two_turns_after_it_is_used(self):
        """Used on `mesprit2` T4, lands at the end of T6 and faints Wobbuffet."""
        turns = _replay("mesprit2")
        self.assertIn(tok.future_sight_token(True), turns[5][1])
        self.assertEqual(turns[5][2].faints, 1)
        self.assertIn("fainted", " ".join(_turns("mesprit2")[5]["msgs"]))


class TestTheBugTheseLogsFound(unittest.TestCase):
    """Our own Safeguard blocked our own Spore, and only a recording could have shown it."""

    def test_our_safeguard_is_a_separate_counter_from_the_targets(self):
        turns = _replay("mesprit2")
        after_safeguard = turns[3][2]
        self.assertEqual(after_safeguard.our_safeguard_turns, 4)
        self.assertEqual(after_safeguard.safeguard_turns, 0)

    def test_and_our_spore_still_lands_through_it(self):
        """The turn that caught it: T8, with our Safeguard up since T4."""
        from claytonlib.battle_compass.state import Status

        turns = _replay("mesprit2")
        self.assertIs(turns[7][2].target.status, Status.SLEEP)
        self.assertIn("fell asleep", " ".join(_turns("mesprit2")[7]["msgs"]))

    def test_a_second_safeguard_of_ours_does_fail(self):
        """T5, which is the half of the old behaviour that was right."""
        self.assertIn("But it failed!", _turns("mesprit2")[4]["msgs"])
        turns = _replay("mesprit2")
        self.assertEqual(turns[4][2].our_safeguard_turns, 3)
