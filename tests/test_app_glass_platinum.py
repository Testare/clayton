"""Glass on a Platinum profile: the same four steps, two of them on a different signal.

Per notes/platinum.md section 7, Configure and History are unchanged — the delay arithmetic and
the year-stamped time picker are formula-identical, and the time-of-day buckets are the same three
in both games. What changes is how Seed A is identified (coin flips, not roamer routes and Elm
calls) and how the advance frame is routed (Journal flips, with a chatot-pitch margin to confirm
by ear). There is no frame-*finding* step on Platinum at all: the frame is counted from the seed's
starting advance, so the pitch is output and never input (clayton-6xu.5).

These tests cover the facade surface the page calls, and the two properties the fork rests on:

* an HGSS Seed is **untouched** — the Platinum path is additive, not a rewrite;
* the gate is the game, and an **unset** game is permissive, because every profile that predates
  the field has one.
"""
import tempfile
import unittest

from app.facade import Facade
from app.store import FileStore
from claytonlib.coin_flips import flip_sequence

#: A real key seed: hour 21 (so the time-of-day bucket is night), mid-minute second.
KEY_SEED = 0x961502A4


class GlassPlatinumCase(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.api = Facade(FileStore(self._tmp.name))
        self.platinum = self.api.create_profile({"name": "Plat", "game": "platinum"})["id"]
        self.hgss = self.api.create_profile({"name": "SS", "game": "soulsilver"})["id"]

    def tearDown(self):
        self._tmp.cleanup()

    def _seed(self, profile_id, **fields):
        seed = self.api.create_seed({"profile_id": profile_id, **fields})
        return seed["id"]


class TestGating(GlassPlatinumCase):

    def test_a_platinum_profile_can_hold_seeds(self):
        self.assertTrue(self._seed(self.platinum, label="Darkrai run"))

    def test_a_diamond_profile_cannot(self):
        diamond = self.api.create_profile({"name": "D", "game": "diamond"})["id"]
        with self.assertRaises(ValueError) as caught:
            self.api.create_seed({"profile_id": diamond})
        self.assertIn("not supported yet", str(caught.exception))

    def test_a_profile_with_no_game_can_still_hold_seeds(self):
        """The migration rule: existing profiles were already using Glass."""
        legacy = self.api.create_profile({"name": "Legacy"})["id"]
        self.assertTrue(self._seed(legacy))


class TestConfigureIsUnchanged(GlassPlatinumCase):
    """The delay arithmetic is formula-identical in Platinum (verified), so this half of the
    page needed no work at all -- which is worth a test precisely because it needed no work."""

    def test_the_absolute_delay_is_the_same_arithmetic(self):
        readout = self.api.seed_readout(KEY_SEED, "2026-06-15T21:30:30")
        self.assertEqual(readout["delay"], (KEY_SEED & 0xFFFF) - 26)
        self.assertEqual(readout["year"], 2026)
        self.assertEqual(readout["problem"], "")

    def test_the_time_of_day_bucket_is_one_of_the_shared_three(self):
        readout = self.api.seed_readout(KEY_SEED, "2026-06-15T21:30:30")
        self.assertEqual(readout["hour"], 21)
        self.assertEqual(readout["time_of_day"], "night")

    def test_an_impossible_hour_is_still_reported_not_crashed_on(self):
        # Hour byte (bits 16-23) of 0xFF: no clock reaches 255, so the seed is unreachable.
        readout = self.api.seed_readout(0xAAFF1234, "2026-06-15T21:30:30")
        self.assertIn("no DS clock", readout["problem"])


class TestPlatinumSeedA(GlassPlatinumCase):

    def _params(self, **extra):
        return {"target_time": "2026-06-15T21:30:30", "key_seed": KEY_SEED,
                "seconds_window": 1, "delay_window": 20, **extra}

    def test_candidates_come_back_with_both_signals(self):
        res = self.api.platinum_seed_a(self._params())
        self.assertGreater(res["count"], 100)
        row = res["candidates"][0]
        self.assertEqual(set(row) - {"seed", "seed_hex", "time", "delay", "sec_delta",
                                     "delay_delta", "flips", "pitch_display"}, set())
        self.assertEqual(len(row["flips"]), 20)
        self.assertIn("(", row["pitch_display"])

    def test_the_key_seed_is_in_the_window_at_zero_delta(self):
        res = self.api.platinum_seed_a(self._params())
        centre = [c for c in res["candidates"]
                  if c["delay_delta"] == 0 and c["sec_delta"] == 0]
        self.assertEqual(len(centre), 1)
        self.assertEqual(centre[0]["seed"], KEY_SEED)

    def test_the_search_delay_is_derived_not_taken_from_the_caller(self):
        """Same contract as metronome_seed_a: passing a delay is not an option, so a page
        cannot search a window around a delay the readout would have refused."""
        res = self.api.platinum_seed_a(self._params(delay=999))
        self.assertEqual(max(c["delay"] for c in res["candidates"]),
                         (KEY_SEED & 0xFFFF) - 26 + 20)

    def test_observed_flips_narrow_to_one(self):
        truth = flip_sequence(KEY_SEED, 10)
        res = self.api.platinum_seed_a(self._params(observed_flips=truth))
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["candidates"][0]["seed"], KEY_SEED)

    def test_narrowing_forgives_spacing_and_case(self):
        truth = flip_sequence(KEY_SEED, 10)
        spaced = " ".join(truth.lower())
        self.assertEqual(self.api.platinum_seed_a(self._params(observed_flips=spaced))["count"], 1)

    def test_impossible_flips_narrow_to_nothing(self):
        res = self.api.platinum_seed_a(self._params(observed_flips="HHHHHHHHHHHHHHHHHHHH"))
        self.assertEqual(res["count"], 0)
        self.assertEqual(res["candidates"], [])

    def test_match_parity_is_honoured(self):
        res = self.api.platinum_seed_a(self._params(match_parity=True))
        target_parity = ((KEY_SEED & 0xFFFF) - 26) % 2
        self.assertTrue(all(c["delay"] % 2 == target_parity for c in res["candidates"]))

    def test_key_seed_info_needs_no_roamer_argument(self):
        info = self.api.platinum_key_seed_info(KEY_SEED)
        self.assertEqual(info["flips"], flip_sequence(KEY_SEED, 20))
        self.assertIn("(", info["pitch_display"])


class TestPlatinumRoute(GlassPlatinumCase):
    """There is no identification call, and the route needs no starting point.

    The frame is counted, not measured: a freshly loaded seed is on advance 0 and every action
    from there has a known cost, so `platinum_plan_frame` takes only a destination. The pitch
    margin it returns is the error check on that count (clayton-6xu.5).
    """

    def test_there_is_no_pitch_identification_call(self):
        self.assertFalse([n for n in dir(self.api) if "identify" in n and "platinum" in n])

    def test_the_route_needs_only_a_destination(self):
        plan = self.api.platinum_plan_frame({"seed": KEY_SEED, "target_frame": 30})
        self.assertEqual(plan["current_frame"], 0)
        self.assertEqual(plan["target_frame"], 30)
        self.assertEqual(plan["journal_advances"] + plan["cries_before_target"], 30)

    def test_route_is_journal_flips_then_cries(self):
        plan = self.api.platinum_plan_frame({"seed": KEY_SEED, "target_frame": 30})
        self.assertEqual(plan["journal_advances"], plan["journal_flips"] * 2)

    def test_a_current_frame_is_accepted_but_not_required(self):
        """Hunts will want it, for a venue whose starting frame is not zero."""
        plan = self.api.platinum_plan_frame(
            {"seed": KEY_SEED, "target_frame": 30, "current_frame": 4})
        self.assertEqual(plan["current_frame"], 4)
        self.assertEqual(plan["journal_advances"] + plan["cries_before_target"], 26)

    def test_an_empty_current_frame_falls_back_to_zero(self):
        """What the page sends when its box is blank."""
        plan = self.api.platinum_plan_frame(
            {"seed": KEY_SEED, "target_frame": 30, "current_frame": ""})
        self.assertEqual(plan["current_frame"], 0)

    def test_the_guide_carries_numbers_only_in_the_margin(self):
        guide = self.api.platinum_plan_frame(
            {"seed": KEY_SEED, "target_frame": 30})["guide"]
        self.assertNotIn("(", guide[:guide.index("[")])
        self.assertIn("(", guide[guide.index("["):guide.index("]")])

    def test_the_margin_is_what_the_player_confirms_against(self):
        """One rendered token per cry, so there is something to hear for each one."""
        plan = self.api.platinum_plan_frame({"seed": KEY_SEED, "target_frame": 30})
        bracket = plan["guide"][plan["guide"].index("[") + 1:plan["guide"].index("]")]
        self.assertEqual(bracket.count("("), plan["cries_before_target"])

    def test_the_description_carries_no_encounter_verb(self):
        text = self.api.platinum_plan_frame(
            {"seed": KEY_SEED, "target_frame": 30})["description"]
        for verb in ("Sweet Scent", "cast", "rod"):
            self.assertNotIn(verb, text)

    def test_a_backwards_route_raises(self):
        with self.assertRaises(ValueError):
            self.api.platinum_plan_frame(
                {"seed": KEY_SEED, "target_frame": 4, "current_frame": 30})


class TestHistory(GlassPlatinumCase):

    def test_a_platinum_entry_records_the_route_not_what_was_heard(self):
        """Nothing was heard *and reported*: the pitches were a check the player made in the
        moment. What is worth keeping is where they started and where they went."""
        seed_id = self._seed(self.platinum)
        history = self.api.seed_add_history(seed_id, {
            "seed": KEY_SEED, "seed_hex": f"0x{KEY_SEED:08X}", "frame": 0, "routed_to": 30})
        self.assertEqual(history[0]["routed_to"], 30)
        self.assertNotIn("elm_heard", history[0])
        self.assertNotIn("pitches_heard", history[0])

    def test_an_hgss_history_entry_still_stores_elm_heard(self):
        seed_id = self._seed(self.hgss)
        history = self.api.seed_add_history(seed_id, {
            "seed": KEY_SEED, "elm_heard": "PEKE", "frame": 6})
        self.assertEqual(history[0]["elm_heard"], "PEKE")


class TestTheHgssPathIsUntouched(GlassPlatinumCase):
    """The Platinum work is additive. An HGSS Seed must behave exactly as it did."""

    def test_the_roamer_seed_a_call_still_works(self):
        res = self.api.metronome_seed_a({
            "target_time": "2026-06-15T21:30:30", "key_seed": KEY_SEED,
            "prev_routes": {"r": 31, "e": 30, "l": 7},
            "seconds_window": 1, "delay_window": 5})
        self.assertGreater(res["count"], 0)
        row = res["candidates"][0]
        for key in ("r_route", "e_route", "l_route", "elm", "rng_calls"):
            self.assertIn(key, row)

    def test_the_elm_frame_calls_still_work(self):
        prev = {"r": 31, "e": 30, "l": 7}
        identified = self.api.safari_compass_identify_frame(
            {"seed": KEY_SEED, "prev_routes": prev, "observed_elm": ""})
        self.assertIn("frames", identified)
        plan = self.api.safari_compass_plan_frame({
            "seed": KEY_SEED, "prev_routes": prev,
            "current_frame": identified["rng_calls"],
            "encounter_frame": identified["rng_calls"] + 30})
        self.assertIn("chatot_flips", plan)
        self.assertIn("elm_before_scent", plan)

    def test_an_hgss_profile_reports_the_elm_signal(self):
        signal = self.api.get_profile(self.hgss)["seed_a_signal"]
        self.assertEqual(signal["kind"], "roamers_elm")
        self.assertEqual(signal["margin_action"], "Elm call")

    def test_a_platinum_profile_reports_the_flips_signal_and_the_hygiene_note(self):
        signal = self.api.get_profile(self.platinum)["seed_a_signal"]
        self.assertEqual(signal["kind"], "flips_pitch")
        self.assertEqual(signal["bulk_action"], "Journal flip")
        self.assertIn("menu", signal["hygiene_note"])


if __name__ == "__main__":
    unittest.main()
