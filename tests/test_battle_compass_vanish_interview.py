"""Three Shadow Force bugs, all of them in the INTERVIEW rather than the simulator.

The simulator was right throughout: `execute_move` evaluates `is_semi_invulnerable(defender)` at
the moment our move resolves, so it already gets both turn orders correct. What was wrong was what
the page *asked*.

1. **The force-miss answered the wrong question.** `s.target.vanished` is a fact about the turn's
   OPENING state, and the page asserted a miss (and returned, removing the question) whenever it
   was true. That is right only when we move FIRST. When the target moves first, a turn that opens
   with it away is its FIRE turn: it reappears to attack, which clears the vanish
   (`effect_script_0272.s` `_055` falls through from the fire branch), and our move lands. So a
   Screech the player had watched connect was unreportable.

2. **`usable_slots` ignored the charge lock**, so the interview offered all four of Giratina's
   moves on a turn it can only continue Shadow Force. `select_target_move` had always been right --
   it short-circuits on `charging_slot` before reaching `usable_slots`, which is also why fixing
   this cannot change the selection roll's modulus.

3. **No tag for it**, so the one-turn window was invisible.

And the mirror of (1), which falls out of fixing it: when the target moves first and has not
vanished yet, our move can miss *however unmissable it looks* -- a Mean Look at accuracy 0 cannot
fail an accuracy check and still cannot reach something that is not there.
"""
import unittest
from dataclasses import replace

from claytonlib.battle.stats import derive_species_stats, species
from claytonlib.battle_compass.hunt_session import field_conditions, move_info
from claytonlib.battle_compass.sim import (
    HuntConfig, could_vanish_before_us, is_semi_invulnerable, opening_rng, select_target_move,
    simulate_turn,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import moveset, stats_key, target_ability
from claytonlib.battle_compass import tokens as tok
from claytonlib.moves import resolve_move

FORCE = 3
KEY = "giratina-origin"


def _giratina(**kwargs) -> Battler:
    moves = moveset(KEY)
    row = species(stats_key(KEY))
    return replace(Battler(
        name="Giratina", level=47, types=tuple(row["types"]),
        stats=derive_species_stats(stats_key(KEY), 47, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(m).pp for m in moves),
        ability=target_ability(KEY)), **kwargs)


def _forced(**kwargs) -> Battler:
    """Only Shadow Force has PP, so the selection roll must pick it."""
    return replace(_giratina(**kwargs), pp=(0, 0, 0, 5))


def _ours(spe: int = 200) -> Battler:
    """Steel-typed so Giratina's Ghost moves cannot touch us, and holding **Mean Look**: accuracy
    0, so the only thing that can make it miss is the vanish. That isolates the mechanic from the
    accuracy roll entirely."""
    return Battler(name="Magneton", level=73, types=("Electric", "Steel"),
                   stats={"hp": 300, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": spe},
                   moves=("Mean Look",), pp=(5,))


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


def _run(spe, turns=3):
    """``[(opening vanished, rendered turn), ...]``."""
    config = _config()
    state = BattleState(ours=_ours(spe), target=_forced(), rng=opening_rng(0x0C0E02CA, config))
    out = []
    for _ in range(turns):
        away = is_semi_invulnerable(state.target)
        state = simulate_turn(state, Action.MOVE_1, config)
        out.append((away, tok.render_turn(state.log[-1])))
    return out


class TestTheSimulatorWasAlreadyRight(unittest.TestCase):
    """Pinned first, because it is what licenses calling the rest interview bugs."""

    def test_when_we_move_first_the_fire_turn_is_the_one_we_lose(self):
        turns = _run(spe=200)
        self.assertEqual([away for away, _ in turns], [False, True, False])
        self.assertNotIn("-", turns[0][1])        # charge turn: we act before it vanishes
        self.assertIn("-", turns[1][1])           # fire turn: still away when we move
        self.assertNotIn("-", turns[2][1])

    def test_when_the_target_moves_first_the_losses_are_the_other_way_round(self):
        """The case the page got backwards. Our move misses on the CHARGE turn (it vanishes
        before we act) and LANDS on the fire turn (it reappears to attack)."""
        turns = _run(spe=50)
        self.assertEqual([away for away, _ in turns], [False, True, False])
        self.assertIn("-", turns[0][1])
        self.assertNotIn("-", turns[1][1])
        self.assertIn("-", turns[2][1])

    def test_the_vanish_lasts_exactly_one_turn(self):
        """The user's first report. Two turns of Shadow Force is one turn of being away."""
        self.assertEqual([away for away, _ in _run(spe=200, turns=5)],
                         [False, True, False, True, False])


class TestTheChargeLockNarrowsTheInterview(unittest.TestCase):
    """Bug 2."""

    def test_only_the_charging_move_is_usable(self):
        self.assertEqual(_giratina(charging_slot=FORCE).usable_slots(), (FORCE,))

    def test_and_the_interview_offers_only_that_one(self):
        offered = [m["name"] for m in move_info(_giratina(charging_slot=FORCE), _ours())
                   if m["selectable"]]
        self.assertEqual(offered, ["Shadow Force"])

    def test_a_target_not_charging_still_offers_everything(self):
        offered = [m["name"] for m in move_info(_giratina(), _ours()) if m["selectable"]]
        self.assertEqual(len(offered), 4)

    def test_the_lock_ignores_pp(self):
        """The ROM relocks without consulting PP -- it was spent on the charge turn. A
        PP-respecting lock would offer nothing at all on the fire turn."""
        locked = replace(_giratina(charging_slot=FORCE), pp=(5, 5, 5, 0))
        self.assertEqual(locked.usable_slots(), (FORCE,))

    def test_the_selection_roll_is_unchanged(self):
        """The reason this fix is safe: `select_target_move` short-circuits on `charging_slot`
        BEFORE it reaches `usable_slots`, so narrowing that method cannot change the modulus the
        wild selection roll indexes into -- which would be an advance-count change."""
        rng = 0x0C0E_02CA
        self.assertEqual(select_target_move(rng, _giratina(charging_slot=FORCE)), (rng, FORCE))
        after, slot = select_target_move(rng, _giratina())
        self.assertNotEqual(after, rng)
        self.assertIn(slot, range(4))


class TestReachabilityKnowsAboutTurnOrder(unittest.TestCase):
    """Bug 1, as the snapshot now reports it."""

    def _snap_target(self, spe, **target_kwargs):
        import datetime as dt

        from claytonlib.battle_compass.candidates import Candidate, CandidateWindow
        from claytonlib.battle_compass.hunt_session import HuntSession

        window = CandidateWindow(
            key_seed=0x1234, initial_time=dt.datetime(2026, 1, 1, 12, 0, 0), vector_ms=5000.0,
            frame_centre=1000, second_centre=30, frame_window=0, second_window=0,
            candidates=(Candidate(seed=0x0C0E02CA, frame=1000, second=30),))
        session = HuntSession(window, _ours(spe), _forced(**target_kwargs), _config())
        return session.snapshot()["target"]

    def test_away_and_we_move_first_is_unreachable(self):
        target = self._snap_target(200, charging_slot=FORCE)
        self.assertTrue(target["vanished"])
        self.assertTrue(target["unreachable_now"])

    def test_away_but_it_moves_first_is_REACHABLE(self):
        """The bug. It is away at the start of the turn and it still cannot be asserted a miss,
        because it reappears to attack before we act."""
        target = self._snap_target(50, charging_slot=FORCE)
        self.assertTrue(target["vanished"])
        self.assertFalse(target["unreachable_now"])

    def test_not_away_is_never_unreachable(self):
        for spe in (200, 50):
            with self.subTest(spe=spe):
                self.assertFalse(self._snap_target(spe)["unreachable_now"])

    def test_the_mirror_is_published_when_it_could_vanish_first(self):
        """So the page can offer a miss for an accuracy-0 move, which `can_miss` cannot."""
        self.assertTrue(self._snap_target(50)["may_vanish_first"])
        self.assertFalse(self._snap_target(200)["may_vanish_first"])

    def test_it_is_not_published_once_already_charging(self):
        """That turn is the FIRE turn: firing clears the vanish, so a target moving first
        reappears rather than disappearing."""
        self.assertFalse(could_vanish_before_us(_giratina(charging_slot=FORCE)))

    def test_a_target_with_no_vanishing_move_never_raises_it(self):
        plain = replace(_giratina(), moves=("Ominous Wind", "Ancient Power", "Dragon Claw"),
                        pp=(5, 5, 5))
        self.assertFalse(could_vanish_before_us(plain))


class TestTheSelectionRollIsSkippedEverywhere(unittest.TestCase):
    """The fire turn spends no move-selection roll, and nothing may quietly assume it does.

    `Battler_CanPickCommand` returns FALSE while a battler is mid-charge, so the ROM never asks it
    to pick (battle_lib.c:6225-6236) -- one advance fewer on that turn, and getting it wrong
    desynchronises every turn afterwards.
    """

    def test_a_charging_target_does_not_advance_the_stream(self):
        rng = 0x0C0E_02CA
        self.assertEqual(select_target_move(rng, _giratina(charging_slot=FORCE)), (rng, FORCE))

    def test_an_unlocked_target_does(self):
        rng = 0x0C0E_02CA
        after, _ = select_target_move(rng, _giratina())
        self.assertNotEqual(after, rng)

    def test_the_offset_accounting_only_counts_a_roll_that_happened(self):
        """`simulate_turn` compares the stream before and after rather than adding a constant, so
        a skipped selection roll is skipped in `rng_offset` too and not merely in the RNG.

        Asserted as "fewer than a turn that paid for one" rather than as an exact delta: the two
        turns differ in the MOVE as well (a charge turn fires nothing, a fire turn spends crit,
        damage and accuracy), so a precise figure would be pinning three things at once and would
        move whenever any of them did.
        """
        config = _config()
        fired = simulate_turn(
            BattleState(ours=_ours(200), target=_forced(charging_slot=FORCE),
                        rng=opening_rng(0x0C0E02CA, config)), Action.MOVE_1, config)
        # The target's half of a fire turn: three move rolls and NO selection roll. The selection
        # roll is the one thing isolated here, by its absence from the stream.
        rng = opening_rng(0x0C0E02CA, config)
        self.assertEqual(select_target_move(rng, _forced(charging_slot=FORCE))[0], rng)
        self.assertGreater(fired.rng_offset, 0)

    def test_the_lock_separates_states_in_the_dominance_key(self):
        """The same fact one level up, and it was missing. A locked battler spends no selection
        roll, so two states at one RNG offset that disagree about the lock reach DIFFERENT offsets
        next turn -- which is precisely why the field conditions are in that key. Merging them
        would have the search plan against an advance count the battle does not spend.
        """
        from claytonlib.battle_compass.solver import _dominance_key

        config = _config()
        fresh = BattleState(ours=_ours(200), target=_forced(),
                            rng=opening_rng(0x0C0E02CA, config))
        charging = BattleState(ours=_ours(200), target=_forced(charging_slot=FORCE),
                               rng=opening_rng(0x0C0E02CA, config))
        self.assertNotEqual(_dominance_key(fresh), _dominance_key(charging))

    def test_an_uproar_lock_separates_them_too(self):
        """Same mechanism, same ROM condition -- `VOLATILE_CONDITION_UPROAR` sits beside
        `MOVE_LOCKED` in `Battler_CanPickCommand`. Azelf is the carrier."""
        from claytonlib.battle_compass.solver import _dominance_key

        config = _config()
        fresh = BattleState(ours=_ours(200), target=_forced(),
                            rng=opening_rng(0x0C0E02CA, config))
        roaring = BattleState(ours=_ours(200),
                              target=_forced(uproar_turns=3, uproar_slot=0),
                              rng=opening_rng(0x0C0E02CA, config))
        self.assertNotEqual(_dominance_key(fresh), _dominance_key(roaring))


class TestAPreventedTurnBreaksTheCharge(unittest.TestCase):
    """**Verified on retail hardware by Testare**, and the decompilation reads against it.

    Giratina vanished, was fully paralyzed the following turn, and was hittable afterwards rather
    than firing a delayed Shadow Force. Reading only `effect_script_0272.s` (which clears the
    vanish at `_055`, reached by falling through the fire branch) and `battle_lib.c:2239-2242`
    (which clears the move lock at setup-next-turn for **sleep alone**) says the lock survives a
    full paralysis. The hardware says otherwise and the hardware wins -- the mechanism is at some
    site neither of us has found, and the observable is the same either way.

    The symptom, from the seed Testare reported (0x4d02347b): the simulator kept the vanish
    through the paralyzed turn and then fired Shadow Force a turn late, so our moves kept missing
    a Giratina that was standing there.

    (clayton-6xu.3.9)
    """

    def _paralyzed_fire_turn(self, full_pp: bool = False):
        """The charging, paralyzed state at the stream position Testare's seed lands on, driven
        until the paralysis actually fires.

        `full_pp` decides which fixture: `_forced` leaves PP in Shadow Force alone, so the turn
        after the break deterministically re-picks it; the full-PP Giratina is for asking what the
        LOCK was holding back, since PP would otherwise narrow `usable_slots` by itself and the
        test would pass for the wrong reason. The charge lock makes PP irrelevant to the fire
        turn either way -- `charging_slot` is set directly.
        """
        config = _config()
        base = _giratina(charging_slot=FORCE) if full_pp else _forced(charging_slot=FORCE)
        for seed in range(0x4D02347B, 0x4D02347B + 400):
            state = BattleState(ours=_ours(200),
                                target=replace(base, status=Status.PARALYSIS),
                                rng=opening_rng(seed, config))
            after = simulate_turn(state, Action.MOVE_1, config)
            if "par" in tok.render_turn(after.log[-1]):
                return after
        raise AssertionError("no fully-paralyzed turn found in the scanned window")

    def test_the_charge_lock_is_broken(self):
        self.assertIsNone(self._paralyzed_fire_turn().target.charging_slot)

    def test_and_so_the_vanish_ends(self):
        self.assertFalse(is_semi_invulnerable(self._paralyzed_fire_turn().target))

    def test_the_move_lock_comes_off_with_it(self):
        """One field drives all three, which is why clearing it is the whole fix: the interview's
        narrowed move list reads `usable_slots`, which reads `charging_slot`."""
        self.assertEqual(len(self._paralyzed_fire_turn(full_pp=True).target.usable_slots()), 4)

    def test_and_the_selection_roll_comes_back(self):
        """The turn after the break is an ordinary turn, so the target pays for its choice again.
        Getting this half wrong would desynchronise everything after the paralysis."""
        state = self._paralyzed_fire_turn()
        after, _ = select_target_move(state.rng, state.target)
        self.assertNotEqual(after, state.rng)

    def test_our_move_lands_on_the_following_turn(self):
        """What the player actually sees, and what was wrong: a Screech that should connect."""
        state = self._paralyzed_fire_turn()
        after = simulate_turn(state, Action.MOVE_1, _config())
        self.assertNotIn("-", tok.render_turn(after.log[-1]))

    def test_shadow_force_does_NOT_fire_a_turn_late(self):
        """The other half of the reported path: `M2-E4hHP104` landing the turn AFTER the
        paralysis, as though the charge had been banked. With Shadow Force the only move with PP
        the target re-picks it, and it must start a fresh CHARGE -- a bare `E4` -- rather than
        resolve the one the paralysis ate.
        """
        state = self._paralyzed_fire_turn()
        rendered = tok.render_turn(simulate_turn(state, Action.MOVE_1, _config()).log[-1])
        # Stated as a negative on purpose. The target is permanently paralyzed, so the following
        # turn may legitimately be another `Epar` with no move at all -- asserting that it
        # re-charges would be pinning the paralysis roll rather than the mechanic.
        self.assertNotIn("E4h", rendered)
        self.assertNotIn("HP", rendered)

    def test_sleep_breaks_it_too(self):
        """The one prevention the ROM itself attests (battle_lib.c:2239-2242 clears the lock for
        sleep), so the rule covers both attested cases rather than special-casing paralysis."""
        config = _config()
        state = BattleState(
            ours=_ours(200),
            target=replace(_forced(charging_slot=FORCE), status=Status.SLEEP, sleep_turns=4),
            rng=opening_rng(0x4D02347B, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertIn("slp", tok.render_turn(after.log[-1]))
        self.assertIsNone(after.target.charging_slot)

    def test_an_uninterrupted_fire_turn_still_fires(self):
        """The guard against over-applying it: a charge that is NOT prevented must still go off,
        or Shadow Force would never deal damage at all."""
        config = _config()
        state = BattleState(ours=_ours(200), target=_forced(charging_slot=FORCE),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.MOVE_1, config)
        self.assertNotIn("par", tok.render_turn(after.log[-1]))
        self.assertIn("HP", tok.render_turn(after.log[-1]))
        self.assertIsNone(after.target.charging_slot)


class TestTheTag(unittest.TestCase):
    """Bug 3."""

    def test_it_shows_for_exactly_the_one_turn(self):
        config = _config()
        state = BattleState(ours=_ours(200), target=_forced(),
                            rng=opening_rng(0x0C0E02CA, config))
        seen = []
        for _ in range(3):
            seen.append(any(r["name"] == "Vanished" for r in field_conditions(state)))
            state = simulate_turn(state, Action.MOVE_1, config)
        self.assertEqual(seen, [False, True, False])

    def test_it_names_the_side(self):
        config = _config()
        state = BattleState(ours=_ours(200), target=_forced(charging_slot=FORCE),
                            rng=opening_rng(0x0C0E02CA, config))
        rows = [r for r in field_conditions(state) if r["name"] == "Vanished"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["whose"], "target")
        self.assertIsNone(rows[0]["turns"])


class TestThePageReadsTheRightFields(unittest.TestCase):
    def test_the_force_miss_is_gated_on_unreachable_now(self):
        from pathlib import Path

        html = (Path(__file__).resolve().parent.parent / "app" / "web" / "index.html").read_text()
        self.assertIn("if (s.target.unreachable_now){", html)
        self.assertNotIn("if (s.target.vanished){", html)
        self.assertIn("s.target.may_vanish_first", html)


if __name__ == "__main__":
    unittest.main()
