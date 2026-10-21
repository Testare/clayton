"""A Hunt on a Platinum profile: the same run, two of its steps on a different signal.

What this file does NOT cover is any specific legendary — Darkrai's four effects and Giratina's
formes are their own beads. What it covers is the game-generic Hunts work: the ball a Platinum
player can actually hold and what it is worth, the Seed A fork, the venue's starting frame, and
the gate.

The load-bearing claims:

* a conditional ball's multiplier reaches the **simulator and the solver**, per turn, rather than
  being computed once for display;
* **time of day is derived from the key seed**, not asked for;
* an HGSS hunt is untouched.
"""
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore
from claytonlib.battle.balls import ThrowContext
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.coin_flips import flip_sequence

#: Hour byte 21, so the time-of-day bucket derived from it is night (the Dusk Ball's condition).
NIGHT_SEED = 0x961502A4
#: Hour byte 12 — day, so the same ball is x1.
DAY_SEED = 0x960C02A4

STATS = ("hp", "atk", "def", "spa", "spd", "spe")


def _target(species="suicune", level=40):
    return {"species": species, "level": level, "nature": "Timid",
            "ivs": {k: 31 for k in STATS}}


#: Each game's own target. The fixture used to hunt Suicune on both, which was impossible on a
#: Platinum cartridge the whole time and became a reported error once encounter rows carried the
#: games they exist in (clayton-957.35.4). Darkrai is Platinum's one configured encounter.
_TARGETS = {"platinum": ("darkrai", 50), "soulsilver": ("suicune", 40)}


class HuntPlatinumCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))
        self.platinum = self.api.create_profile({"name": "Plat", "game": "platinum"})["id"]
        self.hgss = self.api.create_profile({"name": "SS", "game": "soulsilver"})["id"]

    def tearDown(self):
        self._tmp.cleanup()

    def _hunt(self, profile_id, name="Hunt", **fields):
        created = self.api.create_hunt({"profile_id": profile_id, "name": name})
        doc = dict(created)
        game = self.api.get_profile(profile_id).get("game", "")
        species, level = _TARGETS.get(game, ("suicune", 40))
        doc.update({"target": _target(species, level), "key_seed": NIGHT_SEED,
                    "initial_time": "2026-06-15T21:30:30", "vector_ms": 300000})
        doc.update(fields)
        return self.api.save_hunt(doc)


class TestGating(HuntPlatinumCase):

    def test_a_platinum_profile_can_create_a_hunt(self):
        self.assertTrue(self._hunt(self.platinum)["id"])

    def test_a_diamond_profile_cannot(self):
        diamond = self.api.create_profile({"name": "D", "game": "diamond"})["id"]
        with self.assertRaises(ValueError) as caught:
            self.api.create_hunt({"profile_id": diamond, "name": "Nope"})
        self.assertIn("not supported yet", str(caught.exception))

    def test_a_profile_with_no_game_can_still_create_one(self):
        legacy = self.api.create_profile({"name": "Legacy"})["id"]
        self.assertTrue(self.api.create_hunt({"profile_id": legacy, "name": "Old"})["id"])


class TestBallAvailability(HuntPlatinumCase):

    def test_the_picker_is_scoped_to_the_game(self):
        platinum = {b["name"] for b in self.api.list_balls(self.platinum)}
        hgss = {b["name"] for b in self.api.list_balls(self.hgss)}
        self.assertIn("Dusk Ball", platinum)
        self.assertNotIn("Fast Ball", platinum)
        self.assertIn("Fast Ball", hgss)

    def test_an_apricorn_ball_on_platinum_is_a_hard_error(self):
        hunt = self._hunt(self.platinum, capture_ball="Fast Ball")
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertTrue([e for e in errors if "Fast Ball does not exist in Platinum" in e])

    def test_the_same_ball_is_fine_on_hgss(self):
        hunt = self._hunt(self.hgss, name="SS hunt", capture_ball="Fast Ball")
        errors = self.api.hunt_readiness(hunt["id"])["hard_errors"]
        self.assertEqual([e for e in errors if "Fast Ball" in e], [])

    def test_the_picker_marks_which_balls_move_with_the_turn(self):
        rows = {b["name"]: b for b in self.api.list_balls(self.platinum)}
        self.assertTrue(rows["Timer Ball"]["turn_dependent"])
        self.assertTrue(rows["Quick Ball"]["turn_dependent"])
        self.assertFalse(rows["Dusk Ball"]["turn_dependent"])
        self.assertTrue(rows["Dusk Ball"]["conditional"])


class TestTheBallReadout(HuntPlatinumCase):

    def test_time_of_day_comes_from_the_key_seed_not_from_configuration(self):
        """The in-game hour is bits 16-23 of the seed, so a hunt that knows which seed it is
        aiming at already knows whether the Dusk Ball's night applies. Asking would be asking
        the player to restate it -- and to get it wrong independently."""
        night = self._hunt(self.platinum, capture_ball="Dusk Ball", key_seed=NIGHT_SEED)
        readout = self.api.hunt_readiness(night["id"])["ball"]
        self.assertEqual(readout["time_of_day"], "night")
        self.assertEqual(readout["multiplier"], 35)

        day = self._hunt(self.platinum, name="Day", capture_ball="Dusk Ball", key_seed=DAY_SEED)
        readout = self.api.hunt_readiness(day["id"])["ball"]
        self.assertEqual(readout["time_of_day"], "day")
        self.assertEqual(readout["multiplier"], 10)

    def test_a_cave_makes_the_hour_irrelevant(self):
        hunt = self._hunt(self.platinum, capture_ball="Dusk Ball", key_seed=DAY_SEED,
                          terrain="cave")
        readout = self.api.hunt_readiness(hunt["id"])["ball"]
        self.assertEqual(readout["multiplier"], 35)
        self.assertIn("cave", readout["reason"])

    def test_the_readout_names_what_it_was_computed_from(self):
        hunt = self._hunt(self.platinum, capture_ball="Dusk Ball", terrain="water")
        readout = self.api.hunt_readiness(hunt["id"])["ball"]
        self.assertEqual(readout["terrain"], "water")
        self.assertEqual(readout["time_of_day"], "night")

    def test_an_unmodelled_apricorn_rule_is_surfaced(self):
        hunt = self._hunt(self.hgss, name="SS", capture_ball="Heavy Ball")
        self.assertTrue(self.api.hunt_readiness(hunt["id"])["ball"]["unmodelled"])

    def test_no_ball_or_no_species_means_no_readout(self):
        hunt = self._hunt(self.platinum, capture_ball="")
        self.assertIsNone(self.api.hunt_readiness(hunt["id"])["ball"])


class TestTheMultiplierReachesTheSimulation(HuntPlatinumCase):
    """A readout the solver does not share would be decoration. These assert the real path."""

    def test_hunt_config_resolves_the_ball_by_name(self):
        config = HuntConfig(target_catch_rate=3, capture_ball="Dusk Ball",
                            throw=ThrowContext(time_of_day="night"))
        self.assertEqual(config.ball_multiplier_at(0), 35)
        self.assertEqual(config.effective_catch_rate(0), 3)

    def test_a_quick_ball_is_worth_less_after_the_first_turn(self):
        config = HuntConfig(target_catch_rate=3, capture_ball="Quick Ball")
        self.assertEqual(config.ball_multiplier_at(0), 40)
        self.assertEqual(config.ball_multiplier_at(1), 10)

    def test_a_timer_ball_is_worth_more_later(self):
        config = HuntConfig(target_catch_rate=3, capture_ball="Timer Ball")
        self.assertLess(config.ball_multiplier_at(0), config.ball_multiplier_at(20))

    def test_the_solver_threshold_follows_the_turn(self):
        """`target_threshold` was already "b at one moment"; this is the moment mattering."""
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.battle_compass.solver import target_threshold
        from claytonlib.battle_compass.state import BattleState, Battler, Status

        config = HuntConfig(target_catch_rate=3, capture_ball="Quick Ball")
        target = Battler(name="Suicune", level=40, types=tuple(species("suicune")["types"]),
                         stats=derive_species_stats("suicune", 40, "Bold"),
                         hp=1, status=Status.NONE)
        ours = Battler(name="Smeargle", level=58, types=("Normal",),
                       stats={"hp": 153, "atk": 65, "def": 66, "spa": 45, "spd": 79, "spe": 160})
        first = BattleState(ours=ours, target=target, rng=0, turn=0)
        later = BattleState(ours=ours, target=target, rng=0, turn=5)
        self.assertGreater(target_threshold(first, config), target_threshold(later, config))

    def test_a_config_with_no_ball_name_behaves_exactly_as_before(self):
        """Every existing fixture builds one this way, so the legacy pair still has to win."""
        legacy = HuntConfig(target_catch_rate=3, capture_ball_multiplier=20)
        self.assertEqual(legacy.ball_multiplier_at(0), 20)
        self.assertEqual(legacy.ball_multiplier_at(99), 20)
        fast = HuntConfig(target_catch_rate=3, fast_ball_matched=True)
        self.assertEqual(fast.effective_catch_rate(), 12)

    def test_turn_dependence_is_reported_rather_than_inferred(self):
        self.assertTrue(HuntConfig(target_catch_rate=3,
                                   capture_ball="Timer Ball").ball_is_turn_dependent)
        self.assertFalse(HuntConfig(target_catch_rate=3,
                                    capture_ball="Ultra Ball").ball_is_turn_dependent)
        self.assertFalse(HuntConfig(target_catch_rate=3).ball_is_turn_dependent)

    def test_a_guaranteed_ball_is_never_called_equivalent_to_a_poke_ball(self):
        """The Master Ball has the default x1 multiplier, so a check that looked only at the
        multiplier would have called it the same as a Poke Ball."""
        master = HuntConfig(target_catch_rate=3, capture_ball="Master Ball")
        self.assertFalse(master.standard_ball_matches_capture_ball())


class TestSeedAOnThePlatinumSignal(HuntPlatinumCase):

    def test_the_setup_says_which_signal_and_where_counting_starts(self):
        hunt = self._hunt(self.platinum, start_frame=22)
        setup = self.api.hunt_run_setup(hunt["id"])
        self.assertEqual(setup["seed_a_signal"]["kind"], "flips_pitch")
        self.assertEqual(setup["seed_a_signal"]["bulk_action"], "Journal flip")
        self.assertEqual(setup["start_frame"], 22)
        self.assertEqual(setup["refusal"], "")

    def test_an_hgss_hunt_reports_the_elm_signal(self):
        hunt = self._hunt(self.hgss, name="SS")
        setup = self.api.hunt_run_setup(hunt["id"])
        self.assertEqual(setup["seed_a_signal"]["kind"], "roamers_elm")
        self.assertEqual(setup["seed_a_signal"]["hygiene_note"], "")

    def test_coin_flips_narrow_the_hunts_candidate_window(self):
        """Same facade call Glass uses; the Hunts page differs only in which page draws it."""
        res = self.api.platinum_seed_a({
            "target_time": "2026-06-15T21:30:30", "key_seed": NIGHT_SEED,
            "seconds_window": 1, "delay_window": 20,
            "observed_flips": flip_sequence(NIGHT_SEED, 10)})
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["candidates"][0]["seed"], NIGHT_SEED)

    def test_the_route_starts_from_the_venues_frame(self):
        plan = self.api.platinum_plan_frame({
            "seed": NIGHT_SEED, "target_frame": 60, "current_frame": 22})
        self.assertEqual(plan["current_frame"], 22)
        self.assertEqual(plan["journal_advances"] + plan["cries_before_target"], 38)

    def test_the_start_frame_round_trips_on_the_hunt(self):
        hunt = self._hunt(self.platinum, start_frame=22)
        self.assertEqual(self.api.get_hunt(hunt["id"])["start_frame"], 22)

    def test_terrain_and_registration_round_trip(self):
        hunt = self._hunt(self.platinum, terrain="cave", target_registered=True)
        stored = self.api.get_hunt(hunt["id"])
        self.assertEqual(stored["terrain"], "cave")
        self.assertTrue(stored["target_registered"])

    def test_a_hunt_written_before_these_fields_reads_with_defaults(self):
        hunt = self._hunt(self.platinum)
        raw = self.api.get_hunt(hunt["id"])
        for key in ("terrain", "target_registered", "start_frame"):
            self.assertIn(key, raw)
        self.assertEqual(raw["terrain"], "other")
        self.assertEqual(raw["start_frame"], 0)


class TestADarkraiHuntConfigures(HuntPlatinumCase):
    """The first Platinum target, end to end through the facade (clayton-6xu.3.3)."""

    SMEARGLE = dict(
        name="Smeargle", species="smeargle", level=73, ability="Own Tempo",
        stats={"hp": 154, "atk": 65, "def": 70, "spa": 40, "spd": 77, "spe": 160},
        moveset=["False Swipe", "Mean Look", "Sweet Scent", "Spore"],
        max_pp={"1": 40, "2": 5, "3": 20, "4": 15},
    )

    def setUp(self):
        super().setUp()
        self.smeargle = self.api.add_party_pokemon(self.platinum, self.SMEARGLE)["pokemon_id"]

    def _darkrai_hunt(self, **fields):
        return self._hunt(self.platinum, capture_ball="Dusk Ball",
                          party=[{"pokemon_id": self.smeargle}], **fields)

    def test_it_passes_readiness_with_nothing_refused(self):
        hunt = self._darkrai_hunt()
        readiness = self.api.hunt_readiness(hunt["id"])
        self.assertEqual(readiness["hard_errors"], [], readiness["hard_errors"])

    def test_it_is_refused_on_an_hgss_profile(self):
        """Not "no such target" -- it exists, for a cartridge this profile is not."""
        hgss = self._hunt(self.hgss, target=_target("darkrai", 50))
        errors = " ".join(self.api.hunt_readiness(hgss["id"])["hard_errors"])
        self.assertIn("darkrai", errors)
        self.assertIn("Platinum", errors)

    def test_the_session_carries_bad_dreams_and_no_pressure(self):
        """Both derived from the encounter row rather than defaulted, and they are opposite: the
        default for Pressure is True and for Bad Dreams False."""
        hunt = self._darkrai_hunt()
        started = self.api.hunt_session_start(hunt["id"])
        config = self.api._hunt_sessions.get(started["session_id"]).config
        self.assertTrue(config.target_has_bad_dreams)
        self.assertFalse(config.target_has_pressure)

    def test_the_target_battler_carries_its_ability(self):
        """It carried none at all before, which was invisible until an ability mattered to a
        residual rather than to damage."""
        hunt = self._darkrai_hunt()
        started = self.api.hunt_session_start(hunt["id"])
        session = self.api._hunt_sessions.get(started["session_id"])
        self.assertEqual(session.target.ability, "Bad Dreams")

    def test_an_hgss_target_still_gets_pressure_from_its_row(self):
        party = [{"pokemon_id":
                  self.api.add_party_pokemon(self.hgss, self.SMEARGLE)["pokemon_id"]}]
        hunt = self._hunt(self.hgss, capture_ball="Fast Ball", party=party)
        started = self.api.hunt_session_start(hunt["id"])
        config = self.api._hunt_sessions.get(started["session_id"]).config
        self.assertTrue(config.target_has_pressure)
        self.assertFalse(config.target_has_bad_dreams)

    def test_readiness_warns_that_falling_asleep_is_lethal(self):
        """The advice a hit-shaped warning table could not give: Smeargle survives two ticks of a
        sleep that can last four."""
        hunt = self._darkrai_hunt()
        readiness = self.api.hunt_readiness(hunt["id"])
        asleep = [w for w in readiness.get("survivability", []) if "asleep" in w]
        self.assertTrue(asleep, readiness.get("survivability"))
        self.assertIn("Nightmare and Bad Dreams", asleep[0])

    def test_the_wrong_level_is_still_cross_checked(self):
        hunt = self._hunt(self.platinum, target=_target("darkrai", 40))
        errors = " ".join(self.api.hunt_readiness(hunt["id"])["hard_errors"])
        self.assertIn("Lv50 encounter, not Lv40", errors)


class TestAHeatranHuntConfigures(HuntPlatinumCase):
    """Stark Mountain, Lv50, and the Fire move a party must not bring (clayton-6xu.6)."""

    SMEARGLE = TestADarkraiHuntConfigures.SMEARGLE
    #: A party member carrying exactly the move Flash Fire eats.
    TORCHER = dict(
        name="Rapidash", species="rapidash", level=70, ability="Flash Fire",
        stats={"hp": 200, "atk": 160, "def": 120, "spa": 150, "spd": 130, "spe": 210},
        moveset=["Flamethrower", "False Swipe"], max_pp={"1": 15, "2": 40},
    )

    def setUp(self):
        super().setUp()
        self.smeargle = self.api.add_party_pokemon(self.platinum, self.SMEARGLE)["pokemon_id"]

    def _heatran_hunt(self, **fields):
        doc = {"capture_ball": "Dusk Ball",
               "party": [{"pokemon_id": self.smeargle}],
               "target": _target("heatran", 50)}
        doc.update(fields)
        return self._hunt(self.platinum, name="Hunt heatran", **doc)

    def test_it_passes_readiness(self):
        readiness = self.api.hunt_readiness(self._heatran_hunt()["id"])
        self.assertEqual(readiness["hard_errors"], [], readiness["hard_errors"])

    def test_the_session_carries_flash_fire_rather_than_pressure(self):
        started = self.api.hunt_session_start(self._heatran_hunt()["id"])
        session = self.api._hunt_sessions.get(started["session_id"])
        self.assertEqual(session.target.ability, "Flash Fire")
        self.assertFalse(session.config.target_has_pressure)
        self.assertFalse(session.config.target_has_bad_dreams)

    def test_a_fire_move_in_the_party_is_reported_before_the_run(self):
        """Not refused -- the Pokemon is a legitimate party member and `move_coverage` is advice,
        the same split the Whirlpool mule gets. What must not happen is the solver planning it or
        the interview offering it."""
        torcher = self.api.add_party_pokemon(self.platinum, self.TORCHER)["pokemon_id"]
        hunt = self._heatran_hunt(party=[{"pokemon_id": self.smeargle},
                                         {"pokemon_id": torcher}])
        readiness = self.api.hunt_readiness(hunt["id"])
        self.assertEqual(readiness["hard_errors"], [], readiness["hard_errors"])
        absorbed = [row for row in readiness["move_coverage"]
                    if row["move"] == "Flamethrower"]
        self.assertTrue(absorbed, readiness["move_coverage"])
        self.assertIn("Flash Fire", absorbed[0]["reason"])

    def test_the_same_party_against_a_different_target_is_fine(self):
        """The refusal is about the PAIRING. Darkrai has no Flash Fire, so the same Flamethrower
        is a perfectly good move there."""
        torcher = self.api.add_party_pokemon(self.platinum, self.TORCHER)["pokemon_id"]
        hunt = self._hunt(self.platinum, name="Hunt darkrai too", capture_ball="Dusk Ball",
                          party=[{"pokemon_id": torcher}], target=_target("darkrai", 50))
        coverage = self.api.hunt_readiness(hunt["id"])["move_coverage"]
        self.assertEqual([row for row in coverage if row["move"] == "Flamethrower"], [])

    def test_the_advice_warns_about_what_it_does_to_our_defences(self):
        readiness = self.api.hunt_readiness(self._heatran_hunt()["id"])
        self.assertTrue(readiness["survivability"], "nothing said about a one-shot Lava Plume")


class TestAGiratinaHuntConfigures(HuntPlatinumCase):
    """Both venues, through the facade. The forme is what the player names (clayton-6xu.3.4)."""

    SMEARGLE = TestADarkraiHuntConfigures.SMEARGLE

    def setUp(self):
        super().setUp()
        self.smeargle = self.api.add_party_pokemon(self.platinum, self.SMEARGLE)["pokemon_id"]

    def _giratina_hunt(self, key="giratina-origin", level=47, **fields):
        # Named after the forme, because hunt names are unique across profiles and these tests
        # configure both venues in one case.
        return self._hunt(self.platinum, name=f"Hunt {key}", capture_ball="Dusk Ball",
                          party=[{"pokemon_id": self.smeargle}],
                          target=_target(key, level), **fields)

    def test_both_formes_pass_readiness(self):
        for key in ("giratina-origin", "giratina-altered"):
            with self.subTest(key):
                hunt = self._giratina_hunt(key)
                readiness = self.api.hunt_readiness(hunt["id"])
                self.assertEqual(readiness["hard_errors"], [], readiness["hard_errors"])

    def test_a_bare_giratina_is_refused_and_says_which_two(self):
        """The level cross-check cannot help here -- both fights are Lv47 -- so the refusal has to
        come from the name being ambiguous."""
        hunt = self._giratina_hunt("giratina")
        errors = " ".join(self.api.hunt_readiness(hunt["id"])["hard_errors"])
        self.assertIn("Distortion World", errors)
        self.assertIn("Turnback Cave", errors)

    def test_pressure_follows_the_forme_rather_than_the_species(self):
        """The bug the row's `ability` field exists to prevent: `giratina-altered` IS the Giratina
        base-stats row, so a species-keyed lookup answers Pressure for the Distortion World fight
        too -- and halves every PP budget the solver plans against."""
        origin = self.api.hunt_session_start(self._giratina_hunt("giratina-origin")["id"])
        altered = self.api.hunt_session_start(self._giratina_hunt("giratina-altered")["id"])
        self.assertFalse(
            self.api._hunt_sessions.get(origin["session_id"]).config.target_has_pressure)
        self.assertTrue(
            self.api._hunt_sessions.get(altered["session_id"]).config.target_has_pressure)

    def test_the_stats_come_from_the_forme_row(self):
        """Origin is the physical-offence spread, Altered the physical-defence one. Same level,
        same IVs, same nature -- so any difference here is the forme row doing its job."""
        origin = self.api.hunt_session_start(self._giratina_hunt("giratina-origin")["id"])
        altered = self.api.hunt_session_start(self._giratina_hunt("giratina-altered")["id"])
        o = self.api._hunt_sessions.get(origin["session_id"]).target
        a = self.api._hunt_sessions.get(altered["session_id"]).target
        self.assertGreater(o.stats["atk"], a.stats["atk"])
        self.assertGreater(a.stats["def"], o.stats["def"])
        self.assertEqual(o.ability, "Levitate")
        self.assertEqual(a.ability, "Pressure")

    def test_the_run_page_reports_whether_it_is_away(self):
        """Shadow Force's charge turn, so the page can say why everything missed."""
        started = self.api.hunt_session_start(self._giratina_hunt()["id"])
        snapshot = started["snapshot"]
        self.assertIn("vanished", snapshot["target"])
        self.assertFalse(snapshot["target"]["vanished"])


class TestTheHgssHuntPathIsUntouched(HuntPlatinumCase):

    def test_the_roamer_and_elm_calls_still_serve_a_hunt(self):
        prev = {"r": 31, "e": 30, "l": 7}
        candidates = self.api.metronome_seed_a({
            "target_time": "2026-06-15T21:30:30", "key_seed": NIGHT_SEED,
            "prev_routes": prev, "seconds_window": 1, "delay_window": 5})
        self.assertGreater(candidates["count"], 0)
        plan = self.api.safari_compass_plan_frame({
            "seed": NIGHT_SEED, "prev_routes": prev,
            "current_frame": 0, "encounter_frame": 40})
        self.assertIn("chatot_flips", plan)

    def test_an_hgss_hunt_with_a_fast_ball_still_gets_its_x4(self):
        """The one HGSS pairing that was never x1, and the regression that would hurt most."""
        hunt = self._hunt(self.hgss, name="Lugia", capture_ball="Fast Ball",
                          target={"species": "lugia", "level": 45, "nature": "Timid",
                                  "ivs": {k: 31 for k in STATS}})
        readout = self.api.hunt_readiness(hunt["id"])["ball"]
        self.assertEqual(readout["catch_rate"], 12)       # 3 x 4, base Speed 110
        self.assertEqual(readout["multiplier"], 10)

    def test_suicune_still_misses_the_fast_balls_threshold(self):
        """Base Speed 85, which is the whole reason that target is the hard case."""
        hunt = self._hunt(self.hgss, name="Suicune", capture_ball="Fast Ball")
        self.assertEqual(self.api.hunt_readiness(hunt["id"])["ball"]["catch_rate"], 3)


if __name__ == "__main__":
    unittest.main()


class TestBattleRunsFeedCalibration(HuntPlatinumCase):
    """The only calibration path a Platinum profile has.

    Both existing fits take HGSS-only run kinds -- the metronome one needs the Blackthorn
    matchup, the safari one needs the Safari Zone -- so without this a Platinum profile is stuck
    on the bundled "Standard" model forever, and the Hunts window has to be wide enough to
    contain the truth on every run (notes/platinum.md section 6).
    """

    def _battle_run(self, **overrides):
        """A saved battle run, in the shape save_hunt_run writes."""
        from app.models import Run
        run = Run(
            profile_id=self.platinum, kind="battle", vector_ms=300000,
            a_seed={"seed": NIGHT_SEED, "time": "2026-06-15T21:30:30", "delay": 650},
            b_seed={"seed": "0x961508dc", "frame": 18600, "second": 300,
                    "delay": 18600, "time": "2026-06-15T21:35:30"},
            outcome="captured",
        )
        for key, value in overrides.items():
            setattr(run, key, value)
        self.api._store.write("runs", run.id, run.to_dict())
        return run.to_dict()

    def test_a_battle_run_becomes_a_fittable_record(self):
        from app.calibration import _record_for_battle_run
        record = _record_for_battle_run(self._battle_run())
        self.assertIsNotNone(record)
        self.assertEqual(record["target_timer_delay"], 300000)
        self.assertEqual(record["a_seed"]["delay"], 650)
        self.assertEqual(record["b_seed"]["delay"], 18600)

    def test_a_run_of_another_kind_is_not_one(self):
        from app.calibration import _record_for_battle_run
        self.assertIsNone(_record_for_battle_run(dict(self._battle_run(), kind="metronome")))

    def test_a_run_missing_vector_ms_is_screened_out(self):
        from app.calibration import _record_for_battle_run
        self.assertIsNone(_record_for_battle_run(self._battle_run(vector_ms=None)))

    def test_a_run_whose_seed_b_was_never_pinned_is_screened_out(self):
        from app.calibration import _record_for_battle_run
        self.assertIsNone(_record_for_battle_run(self._battle_run(b_seed={})))

    def test_the_session_writes_the_delay_and_time_the_fit_reads(self):
        """`_candidate_row` carries `delay`/`time` beside its own `frame`/`second` spelling
        precisely so the fit does not have to reconstruct them from the hunt's configuration,
        which may have been edited since the run."""
        from app.calibration import _record_for_battle_run
        row = self._battle_run()["b_seed"]
        self.assertEqual(row["delay"], row["frame"])
        self.assertIsNotNone(_record_for_battle_run(self._battle_run()))

    def test_a_fit_needs_more_than_one_run_but_reports_rather_than_crashes(self):
        self._battle_run()
        try:
            report = self.api.preview_battle_calibration(self.platinum)
        except ValueError as problem:
            # A single run cannot support a trend; the message has to say so rather than
            # surfacing an arithmetic error from inside the fit.
            self.assertTrue(str(problem))
            return
        self.assertGreaterEqual(report["n_input"], 1)

    def test_no_runs_is_a_sentence_not_a_crash(self):
        with self.assertRaises(ValueError) as caught:
            self.api.preview_battle_calibration(self.platinum)
        self.assertIn("no fittable battle runs", str(caught.exception))

    def test_exclude_reasons_are_reported_per_run(self):
        run = self._battle_run(vector_ms=None)
        reasons = self.api.battle_run_exclude_reasons(self.platinum)
        self.assertEqual(reasons.get(run["id"]), "incomplete")

    def test_a_manually_excluded_run_says_so(self):
        run = self._battle_run(excluded=True)
        self.assertEqual(self.api.battle_run_exclude_reasons(self.platinum).get(run["id"]),
                         "manual")

    def test_the_battle_fit_is_separate_from_the_metronome_one(self):
        """Not pooled, because whether a static A-press shares the metronome run's load-path
        offset is unmeasured -- the same reason `fit_safari_offset` exists separately."""
        self._battle_run()
        with self.assertRaises(ValueError) as caught:
            self.api.preview_calibration(self.platinum)
        self.assertIn("metronome", str(caught.exception))
