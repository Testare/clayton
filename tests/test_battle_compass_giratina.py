"""Giratina Lv47 (Platinum), met twice, and the two-turn move that comes with it.

**This is the target the encounter-keyed table exists for.** Both fights are Lv47 — the Distortion
World (`StartGiratinaOriginBattle`) and Turnback Cave (`StartLegendaryBattle`) — so the level
cross-check that distinguishes HeartGold's Ho-Oh from SoulSilver's cannot tell them apart at all.
And they differ in more than a moveset: Origin is 120/100/120/100 with **Levitate**, Altered is
100/120/100/120 with **Pressure**, and assuming Pressure where there is none halves every PP
budget the solver plans against.

Shadow Force is the first two-turn move on either side, and it costs three separate things that a
one-turn move does not:

* the **charge turn spends no rolls at all** — its script branches away from CalcCrit/CalcDamage
  and "charge-up moves don't consider accuracy on their first turn";
* the **fire turn spends no selection roll**, because a locked battler never picks a command;
* while it is away, **everything we throw at it misses** — after spending its rolls, because the
  accuracy roll comes first and the invulnerability is layered on afterwards.

A ball is the exception, and it is the fact that matters most: the catch path has no
invulnerability check, so Shadow Force costs us two turns of moves and nothing of the capture.

(clayton-6xu.3.4)
"""
import unittest
from dataclasses import replace
from pathlib import Path

from claytonlib.battle.stats import abilities, derive_species_stats, species
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.hunt_session import move_info
from claytonlib.battle_compass.sim import (
    EFFECT_SHADOW_FORCE, MODELLED_TARGET_EFFECTS, SEMI_INVULNERABLE_EFFECTS, HuntConfig,
    execute_move, is_semi_invulnerable, opening_rng, select_target_move, simulate_turn,
    starts_charge_turn,
)
from claytonlib.battle_compass.state import Action, BattleState, Battler, Status
from claytonlib.battle_compass.targets import (
    ENCOUNTERS, encounter_level, moveset, resolve, stats_key, supported, target_ability,
    unsupported_moves,
)
from claytonlib.moves import resolve_move

#: Shadow Force's slot in both rows, 0-based. E4 to the player.
FORCE = 3


def _giratina(key="giratina-origin", **kwargs) -> Battler:
    moves = moveset(key)
    row = species(stats_key(key))
    return replace(Battler(
        name=key, level=47, types=tuple(row["types"]),
        stats=derive_species_stats(stats_key(key), 47, "Timid", ivs=31),
        moves=moves, pp=tuple(resolve_move(name).pp for name in moves),
        ability=target_ability(key)), **kwargs)


def _forced(key="giratina-origin", **kwargs) -> Battler:
    """Giratina with only Shadow Force usable, so the selection roll cannot pick anything else."""
    base = _giratina(key, **kwargs)
    return replace(base, pp=(0, 0, 0, base.pp[FORCE]))


def _ours(**kwargs) -> Battler:
    """Smeargle, the planned lead. **Normal-typed, which matters here more than anywhere else.**"""
    return replace(Battler(
        name="Smeargle", level=73, types=("Normal",),
        stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
        moves=("False Swipe", "Flash"), pp=(40, 20)), **kwargs)


def _hittable(**kwargs) -> Battler:
    """A party member Ghost moves can actually touch, for the damage assertions."""
    return replace(_ours(name="Magneton", types=("Electric", "Steel")), **kwargs)


def _config() -> HuntConfig:
    return HuntConfig(target_catch_rate=3, target_has_pressure=False)


class TestTheTwoRows(unittest.TestCase):

    def test_both_venues_are_configured_and_both_are_level_47(self):
        self.assertEqual(encounter_level("giratina-origin"), 47)
        self.assertEqual(encounter_level("giratina-altered"), 47)

    def test_the_level_cross_check_cannot_separate_them(self):
        """Which is the whole argument for keying on the encounter. With the roamers a level
        check could at least have caught the mistake; here it cannot."""
        self.assertEqual(ENCOUNTERS["giratina-origin"].level,
                         ENCOUNTERS["giratina-altered"].level)

    def test_the_moveset_is_the_same_in_both(self):
        """The form's own `learnset.by_level` is identical to the species' through 47 -- they
        diverge at Heal Block (50). So the moveset is NOT what distinguishes them."""
        expected = ("Ominous Wind", "Ancient Power", "Dragon Claw", "Shadow Force")
        self.assertEqual(moveset("giratina-origin"), expected)
        self.assertEqual(moveset("giratina-altered"), expected)

    def test_the_ability_differs_and_comes_off_the_row(self):
        self.assertEqual(target_ability("giratina-origin"), "Levitate")
        self.assertEqual(target_ability("giratina-altered"), "Pressure")

    def test_the_species_row_would_have_answered_pressure_for_both(self):
        """The failure the row's `ability` field prevents: `giratina-altered` IS the Giratina row,
        so a species-keyed lookup says Pressure for the Distortion World fight too -- and
        over-budgets every PP figure the solver plans against."""
        self.assertEqual(abilities("giratina-altered"), ("Pressure",))

    def test_the_stats_come_from_the_forme_row(self):
        origin = species(stats_key("giratina-origin"))
        altered = species(stats_key("giratina-altered"))
        self.assertEqual((origin["base_stats"]["atk"], origin["base_stats"]["def"]), (120, 100))
        self.assertEqual((altered["base_stats"]["atk"], altered["base_stats"]["def"]), (100, 120))

    def test_a_bare_giratina_is_refused_and_names_both_venues(self):
        with self.assertRaises(KeyError) as caught:
            resolve("giratina", "platinum")
        message = str(caught.exception)
        self.assertIn("Distortion World", message)
        self.assertIn("Turnback Cave", message)

    def test_both_are_platinum_only(self):
        """Asserted per row rather than by pinning the whole Platinum set, so adding a target
        does not fail a file about Giratina."""
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                self.assertIn(key, supported("platinum"))
                self.assertNotIn(key, supported("heartgold"))
                self.assertNotIn(key, supported("soulsilver"))

    def test_nothing_in_the_set_is_unmodelled(self):
        self.assertEqual(unsupported_moves("giratina-origin"), ((), None))
        self.assertEqual(unsupported_moves("giratina-altered"), ((), None))

    def test_a_forme_encounter_is_keyed_by_its_forme(self):
        """The invariant that lets the player type one name. The species field on a hunt is what
        they typed, and `stats_key` has to land on a real base-stats row -- which it does because
        the encounter key and the forme slug are the same string.
        """
        for key, row in ENCOUNTERS.items():
            if row.forme:
                with self.subTest(key):
                    self.assertEqual(key, row.forme)
                    self.assertEqual(species(row.forme)["name"], row.forme)


class TestTheChargeTurn(unittest.TestCase):

    def test_shadow_force_is_effect_272_and_in_the_modelled_set(self):
        move = resolve_move("Shadow Force")
        self.assertEqual(move.effect, EFFECT_SHADOW_FORCE)
        self.assertIn(move.effect, MODELLED_TARGET_EFFECTS)
        self.assertIn(move.effect, SEMI_INVULNERABLE_EFFECTS)

    def test_it_spends_nothing_and_deals_nothing(self):
        """No CalcCrit, no CalcDamage, and `CheckMoveHitAccuracy` returns before its roll. Zero
        rolls, cross-validated against metronome_compass's `_eff_charge_fire`."""
        rng = 0x1234_5678
        after, outcome = execute_move(rng, resolve_move("Shadow Force"), _giratina(), _ours(),
                                     actor="E", slot=FORCE)
        self.assertEqual(outcome.rolls, 0)
        self.assertEqual(after, rng)
        self.assertEqual(outcome.damage, 0)
        self.assertEqual(outcome.starts_charge, FORCE)
        self.assertTrue(outcome.successful)

    def test_the_fire_turn_is_an_ordinary_damaging_move(self):
        """Crit, damage and accuracy: three rolls, because accuracy is only skipped on the FIRST
        turn of a multi-turn move."""
        charging = _giratina(charging_slot=FORCE)
        _, outcome = execute_move(0x1234_5678, resolve_move("Shadow Force"), charging, _hittable(),
                                 actor="E", slot=FORCE)
        self.assertEqual(outcome.rolls, 3)
        self.assertGreater(outcome.damage, 0)
        self.assertTrue(outcome.ends_charge)
        self.assertIsNone(outcome.starts_charge)

    def test_half_its_moveset_cannot_touch_a_normal_party_member(self):
        """Measured while writing this file, and worth stating: Ominous Wind and Shadow Force are
        both **Ghost**, which does nothing at all to a Normal type. So against a Smeargle lead
        Giratina has two live moves, not four -- Ancient Power and Dragon Claw -- and two of its
        four turns are free. The immunity is the type chart's, not an unmodelled ability.
        """
        charging = _giratina(charging_slot=FORCE)
        _, forced = execute_move(0x1234_5678, resolve_move("Shadow Force"), charging, _ours(),
                                actor="E", slot=FORCE)
        self.assertEqual(forced.damage, 0)
        # "It connected; it just did nothing" is how this read, and it was true of the animation
        # and false of the stream: an ineffective hit is NOT successful and gets none of the two
        # post-move advances [data/battle_logs/giratina2.jsonl turn 6]. The ROM groups
        # MOVE_STATUS_INEFFECTIVE under MOVE_STATUS_DID_NOT_HIT, which is the same answer
        # soundproof already gave.
        self.assertFalse(forced.successful)
        _, wind = execute_move(0x1234_5678, resolve_move("Ominous Wind"), _giratina(), _ours(),
                              actor="E", slot=0)
        self.assertEqual(wind.damage, 0)

    def test_levitate_is_modelled_rather_than_refused(self):
        """It used to be in `UNMODELLED_DAMAGE_ABILITIES`, which was harmless only because the
        target's Battler carried no ability. Once it did, every Levitate holder -- both Lati twins
        and this one -- was reported as an unmodelled ATTACKER and dealt zero damage: not a
        conservative error but a wrong prediction. In Gen 4 Levitate is a Ground immunity and
        nothing else.
        """
        from claytonlib.battle.damage import (
            UNMODELLED_ATTACKER_ABILITIES, UNMODELLED_DEFENDER_ABILITIES,
            unsupported_attacker_reason, Attacker,
        )
        self.assertNotIn("levitate", UNMODELLED_ATTACKER_ABILITIES)
        self.assertNotIn("levitate", UNMODELLED_DEFENDER_ABILITIES)
        self.assertIsNone(unsupported_attacker_reason(Attacker(
            level=47, attack=100, special_attack=100, types=("Ghost",), ability="Levitate")))

    def test_a_ground_move_against_levitate_is_immune(self):
        from claytonlib.battle.damage import Attacker, Defender, damage

        attacker = Attacker(level=50, attack=200, special_attack=200, types=("Ground",))
        earthquake = resolve_move("Earthquake")
        grounded = Defender(defence=100, special_defence=100, types=("Ghost", "Dragon"))
        floating = Defender(defence=100, special_defence=100, types=("Ghost", "Dragon"),
                            ability="Levitate")
        self.assertGreater(damage(earthquake, attacker, grounded, roll=100), 0)
        self.assertEqual(damage(earthquake, attacker, floating, roll=100), 0)

    def test_a_charging_target_is_semi_invulnerable(self):
        self.assertTrue(is_semi_invulnerable(_giratina(charging_slot=FORCE)))
        self.assertFalse(is_semi_invulnerable(_giratina()))

    def test_a_charge_lock_on_an_ordinary_move_is_not_invulnerability(self):
        """Read off the charging MOVE rather than off a second flag, so the two cannot disagree.
        Dragon Claw is not a vanishing move."""
        self.assertFalse(is_semi_invulnerable(_giratina(charging_slot=2)))


class TestTheSelectionRoll(unittest.TestCase):

    def test_a_locked_target_spends_no_selection_roll(self):
        """`Battler_CanPickCommand` is FALSE for a locked battler and command selection is skipped
        entirely -- one advance fewer on the fire turn. Getting this wrong would desynchronise
        every turn after a Shadow Force."""
        rng = 0x0C0E_02CA
        after, slot = select_target_move(rng, _giratina(charging_slot=FORCE))
        self.assertEqual(after, rng)
        self.assertEqual(slot, FORCE)

    def test_an_unlocked_target_still_spends_one(self):
        rng = 0x0C0E_02CA
        after, slot = select_target_move(rng, _giratina())
        self.assertNotEqual(after, rng)
        self.assertIn(slot, range(4))

    def test_the_locked_slot_wins_even_with_no_pp_left_in_it(self):
        """The ROM relocks into `moveLockedInto` without consulting PP, and PP was already spent
        on the charge turn. A `usable_slots` answer here would both pick the wrong move and spend
        a roll that does not exist."""
        locked = _giratina(charging_slot=FORCE)
        locked = replace(locked, pp=(5, 5, 5, 0))
        rng = 0x0C0E_02CA
        after, slot = select_target_move(rng, locked)
        self.assertEqual((after, slot), (rng, FORCE))


class TestATurnPair(unittest.TestCase):
    """The two turns together, through `simulate_turn`."""

    def _pair(self, action=Action.MOVE_1):
        config = _config()
        state = BattleState(ours=_ours(), target=_forced(),
                            rng=opening_rng(0x0C0E02CA, config))
        charge = simulate_turn(state, action, config)
        fire = simulate_turn(charge, action, config)
        return charge, fire

    def test_the_charge_turn_locks_it_and_the_fire_turn_releases(self):
        charge, fire = self._pair()
        self.assertEqual(charge.target.charging_slot, FORCE)
        self.assertIsNone(fire.target.charging_slot)

    def test_pp_is_spent_once_across_the_two_turns(self):
        """`ppDecremented` is set TRUE for a battler that cannot pick a command, so the fire turn
        is free. Spending it twice would empty a 5-PP move in two uses, shrink `usable_slots`
        early and change the selection modulus."""
        charge, fire = self._pair()
        self.assertEqual(charge.target.pp_left(FORCE), 4)
        self.assertEqual(fire.target.pp_left(FORCE), 4)

    def test_our_move_misses_on_the_turn_it_fires(self):
        """**Not on the charge turn**, and the difference is turn order. Smeargle outspeeds
        Giratina, so on the charge turn our move resolves before it vanishes and lands normally.
        It is the FIRE turn we lose: the vanish is still up when we move, and the flag only comes
        off once the move goes off (`_055`).
        """
        charge, fire = self._pair()
        self.assertNotIn("-", charge.log[-1])
        self.assertIn("-", fire.log[-1])

    def test_our_move_still_spends_its_rolls_against_a_vanished_target(self):
        """`CheckMoveHitAccuracy` spends the accuracy roll and `CheckMoveHitOverrides` layers the
        invulnerability on afterwards [battle_controller_player.c:219-220]. So a move at something
        that is not there costs exactly what an ordinary miss costs -- it is not a free turn, and
        a model that skipped the rolls would desynchronise from the turn it happened on.
        """
        false_swipe = resolve_move("False Swipe")
        rng = 0x0C0E_02CA
        _, landed = execute_move(rng, false_swipe, _ours(), _giratina(),
                                actor="M", slot=0)
        _, missed = execute_move(rng, false_swipe, _ours(), _giratina(charging_slot=FORCE),
                                actor="M", slot=0)
        self.assertEqual(landed.rolls, missed.rolls)
        # Neither is "successful": the reachable one is a Normal move against a Ghost, so it is
        # INEFFECTIVE, and the other could not reach a vanished target. The roll COUNT is what
        # this test is about, and it is the same either way -- see
        # `TestASecondaryDoesNotProcOnAnImmuneHit` for why an immune hit is not successful.
        self.assertFalse(landed.successful)
        self.assertFalse(missed.successful)
        self.assertNotIn("-", landed.tokens)
        self.assertIn("-", missed.tokens)

    def test_an_accuracy_zero_move_of_ours_cannot_reach_it_either(self):
        """Nothing rolls accuracy for an accuracy-0 move, and it still cannot hit something that
        is not there -- the invulnerability is not an accuracy check."""
        _, outcome = execute_move(0x0C0E_02CA, resolve_move("Faint Attack"), _ours(),
                                 _giratina(charging_slot=FORCE), actor="M", slot=0)
        self.assertFalse(outcome.successful)
        self.assertIn("-", outcome.tokens)

    def test_a_ball_still_works_while_it_is_away(self):
        """The fact that matters most. The catch path has no invulnerability check at all, so
        Shadow Force costs us two turns of MOVES and nothing of the capture."""
        config = _config()
        state = BattleState(ours=_ours(),
                            target=_forced(charging_slot=FORCE, hp=1, status=Status.SLEEP,
                                           sleep_turns=4),
                            rng=opening_rng(0x0C0E02CA, config))
        after = simulate_turn(state, Action.CAPTURE_BALL, config)
        self.assertEqual(after.balls_thrown, 1)
        self.assertTrue(any(part.startswith("C") or part.startswith("P")
                            for part in after.log[-1]), after.log[-1])

    def test_fainting_clears_the_lock(self):
        """`statusVolatile` goes when a Pokemon leaves the field, and the charge lock with it."""
        self.assertIsNone(_giratina(charging_slot=FORCE).with_hp(0).charging_slot)


class TestItRunsEndToEnd(unittest.TestCase):

    def test_a_sweep_against_both_formes_simulates_without_raising(self):
        config = _config()
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                seen = set()
                for seed in range(0x0C0E0200, 0x0C0E0220):
                    state = BattleState(ours=_ours(), target=_giratina(key),
                                        rng=opening_rng(seed, config))
                    for _ in range(8):
                        state = simulate_turn(state, Action.MOVE_1, config)
                        seen.update(p for p in state.log[-1] if p.startswith("E"))
                        if state.over:
                            break
                for slot in ("E1", "E2", "E3", "E4"):
                    self.assertTrue(any(p.startswith(slot) for p in seen), f"{key}: {slot}")

class TestTheInterviewQuestionsOnTheChargeTurn(unittest.TestCase):
    """What the PLAYER is asked, which is a different thing from what the simulator does.

    The simulator and the token grammar were both already right about the charge turn: it renders
    the bare slot (`execute_move` returns before CalcCrit, CalcDamage and the accuracy check) and
    `tokens.turn_requires_hp` therefore asks for no HP. But Shadow Force is **physical and
    100-accuracy by category**, and `move_info` read those off the move rather than off the turn
    -- so the interview offered "Hit us" and "Critical hit" as the only answers to a turn that can
    render neither, and then asked for an HP figure that had not moved.
    """

    def _info(self, target, move_name="Shadow Force"):
        rows = {row["name"]: row for row in move_info(target, _ours())}
        return rows[move_name]

    def test_the_predicate_tells_the_two_turns_apart(self):
        self.assertTrue(starts_charge_turn(_giratina(), FORCE))
        self.assertFalse(starts_charge_turn(_giratina(charging_slot=FORCE), FORCE))

    def test_an_ordinary_move_never_charges(self):
        """Read off the move's EFFECT, so a charge lock on something else is not a charge turn --
        the same distinction `is_semi_invulnerable` makes."""
        for slot in (0, 1, 2):
            with self.subTest(slot=slot):
                self.assertFalse(starts_charge_turn(_giratina(), slot))

    def test_an_empty_slot_does_not_charge(self):
        self.assertFalse(starts_charge_turn(_ours(), 3))

    def test_the_charge_turn_is_not_offered_as_damaging(self):
        """The bug as reported: the first turn asked whether it hit."""
        self.assertFalse(self._info(_giratina())["damaging"])

    def test_the_fire_turn_IS_damaging(self):
        """The other half, and the reason this could not be fixed on the move alone: the same
        move really does hit on its second turn."""
        self.assertTrue(self._info(_giratina(charging_slot=FORCE))["damaging"])

    def test_the_charge_turn_cannot_miss_and_has_no_accuracy(self):
        """"Charge-up moves don't consider accuracy on their first turn" -- the accuracy check
        returns before its roll, so 0 means "bypassed" rather than "0%"."""
        info = self._info(_giratina())
        self.assertFalse(info["can_miss"])
        self.assertEqual(info["effective_accuracy"], 0)

    def test_the_fire_turn_has_its_real_accuracy_back(self):
        self.assertEqual(self._info(_giratina(charging_slot=FORCE))["effective_accuracy"], 100)

    def test_the_charge_turn_is_flagged_so_the_page_can_say_why(self):
        """The three flags above carry the consequences; this one carries the reason, so a turn
        with nothing asked about it does not read as a question that failed to render."""
        self.assertTrue(self._info(_giratina())["charges"])
        self.assertFalse(self._info(_giratina(charging_slot=FORCE))["charges"])

    def test_a_charge_turn_cannot_miss_even_with_our_evasion_raised(self):
        """The case that makes `can_miss` state-dependent rather than a property of the move: a
        Double Team of ours makes a 100-accuracy move missable, and must still not make a charge
        turn missable."""
        rows = {row["name"]: row
                for row in move_info(_giratina(), _ours(evasion_stage=3))}
        self.assertFalse(rows["Shadow Force"]["can_miss"])
        # ...while the move that really can miss this turn still says so.
        self.assertTrue(rows["Dragon Claw"]["can_miss"])

    def test_nothing_else_in_the_moveset_is_affected(self):
        for name in ("Ominous Wind", "Ancient Power", "Dragon Claw"):
            with self.subTest(name):
                info = self._info(_giratina(), name)
                self.assertFalse(info["charges"])
                self.assertTrue(info["damaging"])

    def test_the_charge_turn_needs_no_hp_and_validates(self):
        """The end of the chain the bug ran down: `hrNeedsHp` keys off the hit answer, so a charge
        turn that is not damaging asks for no HP -- and the turn the simulator predicts is one the
        grammar accepts."""
        config = _config()
        state = BattleState(ours=_ours(), target=_forced(),
                            rng=opening_rng(0x0C0E02CA, config))
        turn = simulate_turn(state, Action.MOVE_2, config).log[-1]
        self.assertIn("E4", turn)
        self.assertNotIn("h", turn)
        self.assertFalse(tok.turn_requires_hp(turn))
        self.assertEqual(tok.validate_turn(list(turn)), [])

    def test_the_page_asks_the_charge_turn_question_differently(self):
        html = (Path(__file__).resolve().parent.parent / "app" / "web" / "index.html").read_text()
        self.assertIn("} else if (info.charges){", html)
        self.assertIn("It vanished", html)
        self.assertIn("vanished instantly", html)


class TestATypeImmuneHitRendersNoMarker(unittest.TestCase):
    """Found by fixing the charge turn, and the same family of bug: a move that connects and does
    nothing was reporting a hit.

    The ROM groups a type immunity with a miss. `MOVE_STATUS_INEFFECTIVE` is a member of
    `MOVE_STATUS_DID_NOT_HIT` (include/constants/battle/moves.h:80-82), next to
    `MOVE_STATUS_MISSED` and `MOVE_STATUS_SEMI_INVULNERABLE` -- the player sees "It doesn't affect
    Smeargle!" and no hit, no crit and no HP change.

    **Why it was a run-ending bug rather than a cosmetic one.** `simulate_turn` emits an HP token
    only on a CHANGE, while `tokens.turn_requires_hp` demands one for any ``E`` token carrying a
    hit marker. So against the planned Normal-typed lead the prediction was ``E4h`` and the
    interview built ``E4hHP154``, which matches no candidate at all -- the true seed eliminated
    with no contradiction raised. Live on half of Giratina's turns, since Ominous Wind and Shadow
    Force are both Ghost.

    What this does NOT change is what the turn SPENDS: see clayton-957.26.6, which owns the
    question of whether an ineffective hit's secondary proc roll happens at all.
    """

    def test_a_ghost_move_against_a_normal_type_renders_the_bare_slot(self):
        _, wind = execute_move(0x1234_5678, resolve_move("Ominous Wind"), _giratina(), _ours(),
                               actor="E", slot=0)
        self.assertEqual(wind.damage, 0)
        self.assertNotIn("h", wind.tokens)
        self.assertNotIn("!", wind.tokens)

    def test_the_fire_turn_against_a_normal_type_renders_it_too(self):
        """Shadow Force's second turn is an ordinary damaging move, and ordinary includes this."""
        _, fired = execute_move(0x1234_5678, resolve_move("Shadow Force"),
                                _giratina(charging_slot=FORCE), _ours(), actor="E", slot=FORCE)
        self.assertEqual(fired.damage, 0)
        self.assertNotIn("h", fired.tokens)

    def test_a_defender_it_CAN_touch_still_gets_its_marker(self):
        """Magneton is Electric/Steel, and Steel merely resists Ghost. So this is a real hit and
        has to keep reading as one -- the suppression is about zero, not about "not very"."""
        _, fired = execute_move(0x1234_5678, resolve_move("Shadow Force"),
                                _giratina(charging_slot=FORCE), _hittable(),
                                actor="E", slot=FORCE)
        self.assertGreater(fired.damage, 0)
        self.assertTrue("h" in fired.tokens or "!" in fired.tokens)

    def test_it_spends_exactly_the_same_rolls_either_way(self):
        """**Tokens only.** The marker is suppressed and nothing about the stream moves, which is
        what keeps this clear of the advance-count question in clayton-957.26.6."""
        move = resolve_move("Shadow Force")
        immune_rng, immune = execute_move(0x1234_5678, move, _giratina(charging_slot=FORCE),
                                          _ours(), actor="E", slot=FORCE)
        hit_rng, landed = execute_move(0x1234_5678, move, _giratina(charging_slot=FORCE),
                                       _hittable(), actor="E", slot=FORCE)
        self.assertEqual(immune.rolls, landed.rolls)
        self.assertEqual(immune_rng, hit_rng)

    def test_our_own_false_swipe_is_subject_to_the_same_rule(self):
        """It reads the pairing rather than the side, so a Normal move of OURS against a Ghost
        renders the bare slot as well -- and gets its marker back once a Foresight lands."""
        false_swipe = resolve_move("False Swipe")
        _, blocked = execute_move(0x0C0E_02CA, false_swipe, _ours(), _giratina(),
                                  actor="M", slot=0)
        _, connected = execute_move(0x0C0E_02CA, false_swipe, _ours(),
                                    _giratina(identified=True), actor="M", slot=0)
        self.assertNotIn("h", blocked.tokens)
        self.assertIn("h", connected.tokens)

    def test_a_whole_immune_turn_validates_and_needs_no_hp(self):
        """The regression, stated as the contradiction it caused: what the simulator predicts and
        what the grammar requires now agree."""
        config = _config()
        state = BattleState(ours=_ours(), target=_forced(charging_slot=FORCE),
                            rng=opening_rng(0x0C0E02CA, config))
        turn = simulate_turn(state, Action.MOVE_1, config).log[-1]
        self.assertFalse(tok.turn_requires_hp(turn))
        self.assertEqual(tok.validate_turn(list(turn)), [])

    def test_levitate_is_covered_by_the_same_rule(self):
        """An Earthquake at Giratina Origin is zero for an ABILITY rather than for the chart, and
        the player sees the same "doesn't affect" message -- so the same bare slot."""
        _, outcome = execute_move(0x1234_5678, resolve_move("Earthquake"),
                                  _hittable(), _giratina(), actor="M", slot=0)
        self.assertEqual(outcome.damage, 0)
        self.assertNotIn("h", outcome.tokens)

class TestASecondaryDoesNotProcOnAnImmuneHit(unittest.TestCase):
    """The other half of an ineffective hit, and the half that moves STATE rather than tokens.

    One ROM function settles both halves, and it settles them differently --
    `BattleSystem_TriggerSecondaryEffect` (battle_lib.c:1519). It runs from the controller loop
    rather than from the effect script, which is why it is reached after a move that did not
    connect, and its generic branch (battle_lib.c:1569-1586) is:

    ```c
    if (BattleSystem_RandNext(battleSys) % 100 < effectChance) {
        SetupSideEffect(...);
        if (curHP && !substituteWasHit
            && (moveStatusFlags & MOVE_STATUS_NO_EFFECTS) == FALSE) { result = TRUE; }
    }
    ```

    The `Random` sits outside every guard, so **the advance is unconditional**; `result` is what
    runs the subscript. `MOVE_STATUS_NO_EFFECTS` contains `MOVE_STATUS_DID_NOT_HIT`, which
    contains `MOVE_STATUS_INEFFECTIVE`. So the roll is spent and the effect is suppressed -- an
    outcome-only correction with no advance-count change, which is why it needed no capture.

    Why it matters here rather than being a curiosity: Ominous Wind raises **all five** of its own
    user's stats, Speed among them, and the no-speed-tie guarantee that keeps ties out of the
    search is built on Giratina being slower than us. Boosting it on a turn the game did not was
    the expensive half of this bug.
    """

    #: An RNG state whose Ominous Wind procs its 10% against a defender it can touch, so the
    #: immune and non-immune cases can be compared on the SAME roll rather than on two different
    #: ones. Fed straight to `execute_move`, so this is a raw stream position.
    PROCCING_RNG = 0x1043
    #: The same thing one layer up: a HUNT seed, which `opening_rng` advances before the first
    #: turn. A different number for the same reason `opening_rng` exists -- the two are not
    #: interchangeable, and using the hunt seed as a raw state is how this test first failed.
    PROCCING_SEED = 0x0C0E0205

    def _wind_only(self):
        """Giratina with PP in Ominous Wind alone, so the selection roll cannot pick anything
        else."""
        base = _giratina()
        return replace(base, pp=(base.pp[0], 0, 0, 0))

    def _bulky(self):
        """A Magneton that survives the hit, so the turn is about the secondary rather than about
        a faint."""
        return replace(_hittable(),
                       stats={"hp": 300, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 100})

    def test_the_roll_is_NOT_spent(self):
        """**Reversed by ground truth**, and the reversal is the point.

        This asserted the opposite -- that the proc roll is spent and only the effect suppressed --
        on the strength of `BattleSystem_TriggerSecondaryEffect` putting its `Random` outside the
        `MOVE_STATUS_NO_EFFECTS` guard. That reading assumed the function is REACHED on an
        ineffective hit, and it is not: `BtlCmd_CheckMoveHit` jumps past the side-effect subscript
        when `MOVE_STATUS_DID_NOT_HIT` is set, which was the FIRST reading and the right one.

        data/battle_logs/giratina2.jsonl settles it. Ominous Wind against the Electric/Steel lead
        on turn 1 spends CRIT, DMG, ACC and SEC; the same move against the Normal-typed Smeargle on
        turn 6 spends CRIT, DMG, ACC and stops. One roll fewer, same move, same 10%
        (clayton-6xu.3.12).
        """
        wind = resolve_move("Ominous Wind")
        _, immune = execute_move(self.PROCCING_RNG, wind, self._wind_only(),
                                 _ours(), actor="E", slot=0)
        _, landed = execute_move(self.PROCCING_RNG, wind, self._wind_only(),
                                 self._bulky(), actor="E", slot=0)
        self.assertEqual(immune.rolls, landed.rolls - 1)

    def test_and_it_is_not_a_successful_move_either(self):
        """So it gets none of the two post-move advances. Same log, same pair of turns: turn 6
        spends 4 trailing advances where turn 1's connecting Ominous Wind spends 6."""
        wind = resolve_move("Ominous Wind")
        _, immune = execute_move(self.PROCCING_RNG, wind, self._wind_only(),
                                 _ours(), actor="E", slot=0)
        _, landed = execute_move(self.PROCCING_RNG, wind, self._wind_only(),
                                 self._bulky(), actor="E", slot=0)
        self.assertFalse(immune.successful)
        self.assertTrue(landed.successful)

    def test_the_proc_that_would_have_landed_does_not(self):
        """Same seed, same roll, opposite verdict -- so this is the immunity doing it and not a
        different random number."""
        wind = resolve_move("Ominous Wind")
        _, immune = execute_move(self.PROCCING_RNG, wind, self._wind_only(), _ours(),
                                 actor="E", slot=0)
        _, landed = execute_move(self.PROCCING_RNG, wind, self._wind_only(), self._bulky(),
                                 actor="E", slot=0)
        self.assertTrue(landed.secondary)
        self.assertFalse(immune.secondary)

    def test_no_secondary_token_is_emitted(self):
        """Nothing was shown, so nothing is reportable -- and a `~` the player never saw would
        filter the candidate set on a message the game did not print."""
        _, immune = execute_move(self.PROCCING_RNG, resolve_move("Ominous Wind"),
                                 self._wind_only(), _ours(), actor="E", slot=0)
        self.assertNotIn("~", immune.tokens)

    def test_giratinas_speed_stage_does_not_move(self):
        """The consequence that costs the run, through `simulate_turn` so the state change is
        what is being checked rather than the flag."""
        config = _config()
        immune = simulate_turn(
            BattleState(ours=_ours(), target=self._wind_only(),
                        rng=opening_rng(self.PROCCING_SEED, config)), Action.MOVE_1, config)
        self.assertEqual(immune.target.speed_stage, 0)

    def test_but_it_does_move_when_the_hit_connects(self):
        """The control, and what keeps the test above from passing for the wrong reason: the same
        seed against a defender Ghost can touch really does boost."""
        config = _config()
        landed = simulate_turn(
            BattleState(ours=self._bulky(), target=self._wind_only(),
                        rng=opening_rng(self.PROCCING_SEED, config)), Action.MOVE_1, config)
        self.assertEqual(landed.target.speed_stage, 1)
        self.assertIn("~", landed.log[-1])

    def test_every_stat_it_would_have_raised_stays_put(self):
        """Ominous Wind raises five at once; Speed is merely the dangerous one."""
        config = _config()
        immune = simulate_turn(
            BattleState(ours=_ours(), target=self._wind_only(),
                        rng=opening_rng(self.PROCCING_SEED, config)), Action.MOVE_1, config)
        for field in ("atk_stage", "def_stage", "spatk_stage", "spdef_stage", "speed_stage"):
            with self.subTest(field):
                self.assertEqual(getattr(immune.target, field), 0)

    def test_no_configured_move_takes_the_branch_that_skips_the_gate(self):
        """The invariant the suppression rests on. Two of the six branches in
        `BattleSystem_TriggerSecondaryEffect` do not consult `MOVE_STATUS_NO_EFFECTS`:
        `MOVE_SIDE_EFFECT_PROBABILISTIC`, which only effects **253 and 262** use (Flare Blitz and
        Volt Tackle), and `MOVE_SIDE_EFFECT_CHECK_HP`, which reads no `effectChance` at all and so
        cannot carry a chance-based secondary. Pinned over every configured target rather than
        asserted in prose, so a target added later that brings one of them fails here instead of
        being silently mis-simulated.
        """
        unguarded = {253, 262}
        for key in supported():
            for name in moveset(key):
                move = resolve_move(name)
                with self.subTest(f"{key}: {name}"):
                    self.assertNotIn(move.effect, unguarded)


if __name__ == "__main__":
    unittest.main()
