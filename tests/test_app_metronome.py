"""Tests for the Metronome Compass facade (seed identification + run persistence)."""
import datetime as dt
import tempfile
import unittest

from app.facade import Facade
from app.metronome import _rel_predicate, _target_delay_for_key_seed
from app.metronome_session import SessionRegistry
from app.models import Run
from app.store import FileStore
from claytonlib.calibration_tools import seed_for

_TARGET_TIME = "2025-07-24T14:45:56"
_TARGET_DT = dt.datetime(2025, 7, 24, 14, 45, 56)
_TRUE_DELAY = 673
# The user never supplies a delay -- only a key seed. Build one exactly as a real
# target-selection step would (seed_for at some real delay), so the facade's
# algebraic derivation is exercised the same way it is in the app.
_KEY_SEED = seed_for(_TARGET_DT, _TRUE_DELAY)

_TARGET = {
    "target_time": _TARGET_TIME,
    "key_seed": _KEY_SEED,
    "prev_routes": {"r": 31, "e": 30, "l": 7},
}


class TestTargetDelayDerivation(unittest.TestCase):
    def test_round_trips_the_true_delay(self):
        self.assertEqual(_target_delay_for_key_seed(_KEY_SEED, _TARGET_DT), _TRUE_DELAY)

    def test_derivation_is_year_agnostic(self):
        # The exact regression this fixes: entering a DIFFERENT calendar year for
        # target_time (as the app previously mishandled) must still reconstruct a
        # delay whose seed_for() low-16 field matches the key seed's -- no drift.
        other_year_time = _TARGET_DT.replace(year=2030)
        derived = _target_delay_for_key_seed(_KEY_SEED, other_year_time)
        reconstructed = seed_for(other_year_time, derived)
        self.assertEqual(reconstructed & 0xFFFF, _KEY_SEED & 0xFFFF)

    def test_naive_low16_reuse_would_have_been_wrong(self):
        # Documents the original bug: directly reusing the key seed's low 16 bits as
        # a fresh delay double-counts the year term once seed_for() re-adds it.
        naive_delay = _KEY_SEED & 0xFFFF
        self.assertNotEqual(naive_delay, _TRUE_DELAY)
        self.assertEqual(naive_delay - _TRUE_DELAY, _TARGET_DT.year - 2000)


class TestRelPredicate(unittest.TestCase):
    KEYS = ["r", "e", "l"]

    def test_exact_two_digit_match(self):
        pred, ok = _rel_predicate("39 44 7", self.KEYS)
        self.assertTrue(ok)
        self.assertTrue(pred({"r_route": 39, "e_route": 44, "l_route": 7}))
        self.assertFalse(pred({"r_route": 39, "e_route": 45, "l_route": 7}))

    def test_single_digit_r_or_e_is_tens_place_prefix(self):
        pred, ok = _rel_predicate("39 4", self.KEYS)
        self.assertTrue(ok)
        # "4" for E should match any real E route starting with 4 (42-46), any L.
        for e in (42, 43, 44, 45, 46):
            self.assertTrue(pred({"r_route": 39, "e_route": e, "l_route": 99}))
        self.assertFalse(pred({"r_route": 39, "e_route": 30, "l_route": 1}))

    def test_l_is_never_prefix_matched(self):
        pred, ok = _rel_predicate(". . 2", self.KEYS)
        self.assertTrue(ok)
        self.assertTrue(pred({"r_route": 1, "e_route": 1, "l_route": 2}))
        self.assertFalse(pred({"r_route": 1, "e_route": 1, "l_route": 24}))  # not a prefix match

    def test_missing_trailing_tokens_are_wildcards(self):
        pred, ok = _rel_predicate("39", self.KEYS)
        self.assertTrue(ok)
        self.assertTrue(pred({"r_route": 39, "e_route": 999, "l_route": 999}))

    def test_empty_string_matches_everything(self):
        pred, ok = _rel_predicate("", self.KEYS)
        self.assertTrue(ok)
        self.assertTrue(pred({"r_route": 1, "e_route": 2, "l_route": 3}))

    def test_unparseable_token_is_flagged_not_raised(self):
        pred, ok = _rel_predicate("abc", self.KEYS)
        self.assertFalse(ok)
        self.assertIsNone(pred)

    def test_extra_tokens_ignored(self):
        pred, ok = _rel_predicate("39 44 7 99", self.KEYS)
        self.assertTrue(ok)  # still-typing tail beyond the known roamers is harmless


class TestSeedA(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))

    def _gen(self, **extra):
        return self.api.metronome_seed_a({**_TARGET, "seconds_window": 1, "delay_window": 2, **extra})

    def test_generates_annotated_candidates(self):
        res = self._gen()
        self.assertGreater(res["count"], 0)
        self.assertEqual(res["roamers"], ["r", "e", "l"])
        c = res["candidates"][0]
        for key in ("seed", "seed_hex", "time", "delay", "r_route", "e_route", "l_route", "elm"):
            self.assertIn(key, c)

    def test_rel_filter_narrows_and_keeps_the_match(self):
        res = self._gen()
        target = next(c for c in res["candidates"] if c["sec_delta"] == 0 and c["delay_delta"] == 0)
        rel = f"{target['r_route']} {target['e_route']} {target['l_route']}"
        narrowed = self._gen(rel_observed=rel)
        self.assertLessEqual(narrowed["count"], res["count"])
        self.assertIn(target["seed"], [c["seed"] for c in narrowed["candidates"]])

    def test_elm_filter_further_narrows(self):
        res = self._gen()
        target = next(c for c in res["candidates"] if c["sec_delta"] == 0 and c["delay_delta"] == 0)
        rel = f"{target['r_route']} {target['e_route']} {target['l_route']}"
        narrowed = self._gen(rel_observed=rel, elm_observed=target["elm"][2:6])
        self.assertIn(target["seed"], [c["seed"] for c in narrowed["candidates"]])

    def test_rel_wildcard(self):
        res = self._gen(rel_observed=". . .")  # all wildcards keep everything
        self.assertEqual(res["count"], self._gen()["count"])

    def test_key_seed_info_matches_generation(self):
        res = self._gen()
        target = next(c for c in res["candidates"] if c["sec_delta"] == 0 and c["delay_delta"] == 0)
        info = self.api.metronome_key_seed_info(target["seed"], _TARGET["prev_routes"])
        self.assertEqual(info["r_route"], target["r_route"])
        self.assertEqual(info["e_route"], target["e_route"])
        self.assertEqual(info["elm"], target["elm"])

    def test_not_roaming_roamer_omitted(self):
        res = self.api.metronome_seed_a({
            "target_time": _TARGET["target_time"], "key_seed": _KEY_SEED,
            "prev_routes": {"r": 31, "l": 7},  # e not roaming
            "seconds_window": 0, "delay_window": 1})
        self.assertEqual(res["roamers"], ["r", "l"])
        self.assertIsNone(res["candidates"][0]["e_route"])

    def test_exact_rel_found_within_a_tight_window_regardless_of_year(self):
        # Regression for the reported bug: entering the exact REL for the true
        # candidate must find it within a narrow +/-10 delay window, and this must
        # hold no matter what year the user happens to type into target_time.
        for year in (2000, 2025, 2030):
            t = _TARGET_DT.replace(year=year)
            key_seed = seed_for(t, _TRUE_DELAY)  # a key seed picked for THIS year's run
            res = self.api.metronome_seed_a({
                "target_time": t.isoformat(), "key_seed": key_seed,
                "prev_routes": _TARGET["prev_routes"],
                "seconds_window": 0, "delay_window": 10})
            target = next(c for c in res["candidates"] if c["delay_delta"] == 0)
            rel = f"{target['r_route']} {target['e_route']} {target['l_route']}"
            narrowed = self.api.metronome_seed_a({
                "target_time": t.isoformat(), "key_seed": key_seed,
                "prev_routes": _TARGET["prev_routes"],
                "seconds_window": 0, "delay_window": 10, "rel_observed": rel})
            self.assertIn(target["seed"], [c["seed"] for c in narrowed["candidates"]],
                f"year={year}: exact REL match not found within the window")

    def test_single_digit_rel_prefix_narrows_live(self):
        res = self._gen()
        target = next(c for c in res["candidates"] if c["sec_delta"] == 0 and c["delay_delta"] == 0)
        prefix = str(target["e_route"])[0]  # tens digit only, as if still typing
        narrowed = self._gen(rel_observed=f"{target['r_route']} {prefix}")
        self.assertTrue(narrowed["rel_valid"])
        self.assertIn(target["seed"], [c["seed"] for c in narrowed["candidates"]])

    def test_unparseable_rel_flags_instead_of_raising(self):
        res = self._gen(rel_observed="xyz")
        self.assertFalse(res["rel_valid"])
        self.assertEqual(res["count"], 0)

    def test_partial_rel_while_typing_is_not_an_error(self):
        # A single token (still typing the rest) must not raise -- this was the CX bug.
        res = self._gen(rel_observed="3")
        self.assertTrue(res["rel_valid"])


class TestSeedB(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))

    def test_generates_paths(self):
        res = self.api.metronome_seed_b({
            "target_time": _TARGET["target_time"], "key_seed": _KEY_SEED,
            "seconds_window": 0, "delay_window": 1,
            "magikarp_level": 15, "opposite_gender": True, "metronome_only": True})
        self.assertGreater(res["count"], 0)
        self.assertTrue(all("path_str" in c for c in res["candidates"]))


class TestSeedBSession(unittest.TestCase):
    def test_fake_runner_question_flow(self):
        reg = SessionRegistry()

        def runner(inp, out):
            out("battle context")
            a = inp("Magikarp used? (sp/tk) ")
            b = inp("Hit or crit? ")
            if (a, b) == ("sp", "hit"):
                return {"seed": 42, "time": dt.datetime(2025, 1, 1), "delay": 5,
                        "sec_delta": 0, "delay_delta": 0, "path_str": "KspM303"}
            return None

        sid, st = reg.start(runner)
        self.assertFalse(st["done"])
        self.assertEqual(st["prompt"], "Magikarp used? (sp/tk) ")
        self.assertIn("battle context", st["output"])
        st = reg.answer(sid, "sp")
        self.assertEqual(st["prompt"], "Hit or crit? ")
        st = reg.answer(sid, "hit")
        self.assertTrue(st["done"])
        self.assertEqual(st["result"]["seed"], 42)
        # session is forgotten once done
        with self.assertRaises(ValueError):
            reg.answer(sid, "x")

    def test_single_candidate_completes_without_questions(self):
        reg = SessionRegistry()
        sid, st = reg.start(lambda inp, out: {"seed": 7})
        self.assertTrue(st["done"])
        self.assertEqual(st["result"], {"seed": 7})

    def test_abort(self):
        reg = SessionRegistry()

        def runner(inp, out):
            inp("q? ")
            return {"seed": 1}

        sid, st = reg.start(runner)
        self.assertFalse(st["done"])
        st = reg.abort(sid)
        self.assertTrue(st["done"])
        self.assertTrue(st.get("aborted"))

    def test_real_narrowing_session_starts_then_aborts(self):
        api = Facade(FileStore(tempfile.mkdtemp()))
        st = api.metronome_seed_b_start({
            "target_time": _TARGET_TIME, "key_seed": _KEY_SEED,
            "seconds_window": 0, "delay_window": 1,
            "magikarp_level": 15, "opposite_gender": True, "metronome_only": True})
        self.assertIn("session_id", st)
        if not st["done"]:
            self.assertIn("prompt", st)
            done = api.metronome_seed_b_abort(st["session_id"])
            self.assertTrue(done["done"])


class TestRuns(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))
        self.pid = self.api.create_profile({"name": "P1"})["id"]

    def _save(self, **extra):
        data = {"tag": "300s test", "vector_ms": 300000, "metronome_user_id": 1,
                "a_seed": {"seed": 1, "seed_hex": "0x1"},
                "b_seed": {"seed": 2, "path_str": "KspM303"}, **extra}
        return self.api.save_metronome_run(self.pid, data)

    def test_run_model_round_trip(self):
        r = Run(profile_id="p", tag="t", vector_ms=300000, a_seed={"seed": 1})
        self.assertEqual(Run.from_dict(r.to_dict()).to_dict(), r.to_dict())
        self.assertTrue(r.saved_at)  # auto-stamped

    def test_save_and_list(self):
        self._save(tag="run A")
        self._save(tag="run B")
        runs = self.api.list_runs(self.pid)
        self.assertEqual(len(runs), 2)
        self.assertEqual({r["tag"] for r in runs}, {"run A", "run B"})
        self.assertTrue(all(r["kind"] == "metronome" for r in runs))

    def test_runs_scoped_by_profile_and_kind(self):
        other = self.api.create_profile({"name": "P2"})["id"]
        self._save()
        self.assertEqual(len(self.api.list_runs(other)), 0)
        self.assertEqual(len(self.api.list_runs(self.pid, kind="safari")), 0)

    def test_save_requires_existing_profile(self):
        with self.assertRaises(ValueError):
            self.api.save_metronome_run("ghost", {"tag": "x"})

    def test_exclude_and_delete(self):
        r = self._save()
        updated = self.api.set_run_excluded(r["id"], True)
        self.assertTrue(updated["excluded"])
        self.assertTrue(self.api.get_run(r["id"])["excluded"])
        self.assertTrue(self.api.delete_run(r["id"]))
        self.assertEqual(len(self.api.list_runs(self.pid)), 0)


class TestTimesOnDate(unittest.TestCase):
    """Powers the calendar/valid-times picker (clayton-b42.6.1)."""

    def test_finds_times_on_the_exact_date_used_to_build_the_key_seed(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            times = api.times_on_date(_KEY_SEED, "2025-07-24")
            self.assertIn(_TARGET_TIME, times)

    def test_year_is_reinterpreted_not_matched_literally(self):
        # generate_times() stamps a nominal placeholder year -- month/day/hour/minute/second
        # are what the RNG actually cares about -- so a DIFFERENT real year with the same
        # month/day must still find (and re-stamp) the same time.
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            times_2030 = api.times_on_date(_KEY_SEED, "2030-07-24")
            self.assertIn("2030-07-24T14:45:56", times_2030)

    def test_empty_for_a_date_with_no_matches(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            # January 14 falls outside this key seed's mdms window (verified directly against
            # get_times() -- the window is wide enough that "just pick any other month" isn't
            # reliably a non-match, so this specific date is deliberate, not arbitrary).
            far_off = api.times_on_date(_KEY_SEED, "2025-01-14")
            self.assertEqual(far_off, [])

    def test_both_filters_optional_returns_everything(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            everything = api.times_on_date(_KEY_SEED)
            on_date = api.times_on_date(_KEY_SEED, "2025-07-24")
            self.assertGreater(len(everything), len(on_date))
            # Unfiltered results keep generate_times()'s own nominal year (2000).
            self.assertTrue(all(t.startswith("2000-") for t in everything))

    def test_second_filter_alone(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            times = api.times_on_date(_KEY_SEED, second=56)
            self.assertTrue(times)
            self.assertTrue(all(t.endswith(":56") for t in times))

    def test_date_and_second_combine(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            times = api.times_on_date(_KEY_SEED, "2025-07-24", 56)
            self.assertEqual(times, [_TARGET_TIME])

    def test_year_out_of_range_normalizes_to_2000(self):
        from tests.test_app_chart import _isolated_cwd
        with _isolated_cwd():
            api = Facade(FileStore(tempfile.mkdtemp()))
            too_early = api.times_on_date(_KEY_SEED, "1999-07-24")
            too_late = api.times_on_date(_KEY_SEED, "2150-07-24")
            self.assertIn("2000-07-24T14:45:56", too_early)
            self.assertIn("2000-07-24T14:45:56", too_late)


if __name__ == "__main__":
    unittest.main()
