"""Tests for the Metronome Compass facade (seed identification + run persistence)."""
import datetime as dt
import tempfile
import unittest

from app.facade import Facade
from app.metronome_session import SessionRegistry
from app.models import Run
from app.store import FileStore

_TARGET = {
    "target_time": "2025-07-24T14:45:56",
    "target_delay": 673,
    "prev_routes": {"r": 31, "e": 30, "l": 7},
}


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
            "target_time": _TARGET["target_time"], "target_delay": 673,
            "prev_routes": {"r": 31, "l": 7},  # e not roaming
            "seconds_window": 0, "delay_window": 1})
        self.assertEqual(res["roamers"], ["r", "l"])
        self.assertIsNone(res["candidates"][0]["e_route"])


class TestSeedB(unittest.TestCase):
    def setUp(self):
        self.api = Facade(FileStore(tempfile.mkdtemp()))

    def test_generates_paths(self):
        res = self.api.metronome_seed_b({
            "target_time": _TARGET["target_time"], "target_delay": 673,
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
            "target_time": "2025-07-24T14:45:56", "target_delay": 673,
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


if __name__ == "__main__":
    unittest.main()
