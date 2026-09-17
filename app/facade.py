"""facade.py — the flat API the UI calls.

Every method takes and returns plain JSON-friendly values (dicts, lists, scalars),
so the same surface works whether it's reached from the pywebview ``js_api`` bridge
or a Python caller in a test. The UI never touches :mod:`app.models` or the Store
directly — it goes through here, which is what lets a future shell reuse the exact
same front end.

Complex inputs arrive as a single dict (JS passes an object), not keyword
arguments, to keep the bridge simple: ``api.create_profile({name, tid, ...})``.
"""
from __future__ import annotations

from app import calibration as calibration_lib
from app import chart as chart_lib
from app import metronome
from app.models import CalibrationModelDoc, Chart, Expedition, MetronomeUser, Profile, Run, Target
from app.store import FileStore, Store

_PROFILES = "profiles"
_EXPEDITIONS = "expeditions"
_RUNS = "runs"
_CHARTS = "charts"
_TARGETS = "targets"
_CALIBRATION_MODELS = "calibration_models"


class Facade:
    def __init__(self, store: Store | None = None):
        self._store = store or FileStore()
        from app.metronome_session import SessionRegistry
        self._sessions = SessionRegistry()
        from app.progress_session import ProgressRegistry
        self._chart_sessions = ProgressRegistry()

    # -- internal loaders -------------------------------------------------

    def _load_profile(self, profile_id: str) -> Profile:
        doc = self._store.read(_PROFILES, profile_id)
        if doc is None:
            raise ValueError(f"no profile with id {profile_id!r}")
        return Profile.from_dict(doc)

    def _save_profile(self, profile: Profile) -> None:
        self._store.write(_PROFILES, profile.id, profile.to_dict())

    def _load_expedition(self, expedition_id: str) -> Expedition:
        doc = self._store.read(_EXPEDITIONS, expedition_id)
        if doc is None:
            raise ValueError(f"no expedition with id {expedition_id!r}")
        return Expedition.from_dict(doc)

    # -- profiles ---------------------------------------------------------

    def list_profiles(self) -> list[dict]:
        """Summaries of every profile, for a selector/list."""
        out = []
        for pid in self._store.list_ids(_PROFILES):
            doc = self._store.read(_PROFILES, pid)
            if doc is None:
                continue
            p = Profile.from_dict(doc)
            out.append({
                "id": p.id,
                "name": p.name,
                "tid": p.tid,
                "sid": p.sid,
                "console": p.console,
                "metronome_user_count": len(p.metronome_users),
                "has_valid_metronome_user": p.has_valid_metronome_user,
            })
        out.sort(key=lambda d: d["name"].lower())
        return out

    def get_profile(self, profile_id: str) -> dict:
        """The full profile document, with derived suitability per metronome user."""
        p = self._load_profile(profile_id)
        doc = p.to_dict()
        for user_dict, user in zip(doc["metronome_users"], p.metronome_users):
            user_dict["is_suitable"] = user.is_suitable
            user_dict["warnings"] = user.suitability_warnings()
        doc["has_valid_metronome_user"] = p.has_valid_metronome_user
        return doc

    def create_profile(self, fields: dict) -> dict:
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a profile needs a name")
        p = Profile(
            name=name,
            tid=fields.get("tid"),
            sid=fields.get("sid"),
            console=fields.get("console", ""),
        )
        self._save_profile(p)
        return self.get_profile(p.id)

    def delete_profile(self, profile_id: str) -> bool:
        return self._store.delete(_PROFILES, profile_id)

    # -- metronome users --------------------------------------------------

    def metronome_user_warnings(self, fields: dict) -> list[str]:
        """Suitability warnings for prospective fields, so the UI can warn pre-save."""
        probe = MetronomeUser(
            id=0,
            name=fields.get("name", "?"),
            species=fields.get("species", "Chansey"),
            gender=fields.get("gender"),
            level=fields.get("level"),
            moveset=list(fields.get("moveset", [])),
            ability=fields.get("ability"),
            lagging_tail=bool(fields.get("lagging_tail", False)),
        )
        return probe.suitability_warnings()

    def add_metronome_user(self, profile_id: str, fields: dict) -> dict:
        """Add a user to the profile; returns the profile plus any warnings."""
        p = self._load_profile(profile_id)
        user = p.add_metronome_user(
            name=fields.get("name", ""),
            species=fields.get("species", "Chansey"),
            gender=fields.get("gender"),
            level=fields.get("level"),
            moveset=list(fields.get("moveset", [])),
            ability=fields.get("ability"),
            lagging_tail=bool(fields.get("lagging_tail", False)),
        )
        self._save_profile(p)
        return {
            "profile": self.get_profile(p.id),
            "user_id": user.id,
            "warnings": user.suitability_warnings(),
        }

    def remove_metronome_user(self, profile_id: str, user_id: int) -> dict:
        """Remove a user. Runs referencing its id can no longer resolve it."""
        p = self._load_profile(profile_id)
        removed = p.remove_metronome_user(int(user_id))
        self._save_profile(p)
        return {"profile": self.get_profile(p.id), "removed": removed.to_dict()}

    # -- expeditions ------------------------------------------------------

    def list_expeditions(self, profile_id: str | None = None) -> list[dict]:
        out = []
        for eid in self._store.list_ids(_EXPEDITIONS):
            doc = self._store.read(_EXPEDITIONS, eid)
            if doc is None:
                continue
            e = Expedition.from_dict(doc)
            if profile_id is not None and e.profile_id != profile_id:
                continue
            out.append({
                "id": e.id,
                "name": e.name,
                "profile_id": e.profile_id,
                "pokemon": e.pokemon,
            })
        out.sort(key=lambda d: d["name"].lower())
        return out

    def get_expedition(self, expedition_id: str) -> dict:
        return self._load_expedition(expedition_id).to_dict()

    def create_expedition(self, fields: dict) -> dict:
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("an expedition needs a name")
        profile_id = fields.get("profile_id")
        if not profile_id:
            raise ValueError("an expedition must reference a profile")
        # Fail early if the referenced profile is missing.
        self._load_profile(profile_id)
        e = Expedition.from_dict({**fields, "name": name})
        self._store.write(_EXPEDITIONS, e.id, e.to_dict())
        return e.to_dict()

    def save_expedition(self, expedition: dict) -> dict:
        """Upsert an existing expedition from its full document."""
        if not expedition.get("id"):
            raise ValueError("save_expedition needs an expedition id (use create_expedition for new)")
        e = Expedition.from_dict(expedition)
        self._load_profile(e.profile_id)  # validate the reference still resolves
        self._store.write(_EXPEDITIONS, e.id, e.to_dict())
        return e.to_dict()

    def delete_expedition(self, expedition_id: str) -> bool:
        return self._store.delete(_EXPEDITIONS, expedition_id)

    # -- reference data ---------------------------------------------------

    def list_safari_areas(self) -> list[str]:
        """The Safari Zone area names, for the expedition-config dropdown."""
        from claytonlib.safari_encounters import safari_areas
        return safari_areas()

    # -- Metronome Compass: seed identification ---------------------------

    def metronome_seed_a(self, params: dict) -> dict:
        """Candidate initial seeds, narrowed by observed roamer routes + Elm calls."""
        return metronome.seed_a(params)

    def metronome_key_seed_info(self, key_seed: int, prev_routes: dict) -> dict:
        """The key seed's own roamer routes + Elm (to spot a key-seed hit)."""
        return metronome.key_seed_info(key_seed, prev_routes)

    def metronome_seed_b(self, params: dict) -> dict:
        """Candidate battle seeds, each with its precomputed Metronome path."""
        return metronome.seed_b(params)

    def _json_session_state(self, state: dict) -> dict:
        result = state.get("result")
        if result:  # the identified candidate carries a datetime + path objects
            state = {**state, "result": metronome._row_b_json(result)}
        return state

    def metronome_seed_b_start(self, params: dict) -> dict:
        """Begin the interactive Seed B narrowing; returns the first question (or result)."""
        runner = metronome.seed_b_runner(params)
        _sid, state = self._sessions.start(runner)
        return self._json_session_state(state)

    def metronome_seed_b_answer(self, session_id: str, text: str) -> dict:
        """Answer the current question; returns the next question (or the identified seed)."""
        return self._json_session_state(self._sessions.answer(session_id, text))

    def metronome_seed_b_abort(self, session_id: str) -> dict:
        """Stop the narrowing without identifying a seed."""
        return self._sessions.abort(session_id)

    # -- Safari Compass: seed identification -------------------------------

    def safari_compass_seed_b(self, expedition_id: str, params: dict) -> dict:
        """Candidate battle seeds for Safari Compass, narrowed by the observed path so far
        (stateless — re-call with the full path on every keystroke, like metronome_seed_a)."""
        from app import safari_compass
        exp = self._load_expedition(expedition_id).to_dict()
        models = self._resolve_calibration_models(exp["profile_id"])
        model = models.get(params.get("fps_model", "linear")) or next(iter(models.values()), None)
        if model is None:
            raise ValueError(
                "no calibration model available — build one from Metronome Compass → Review "
                "Data → Calibrate Model first")
        if params.get("use_safari_offset", True):
            model = model.with_safari_offset()
        return safari_compass.seed_b(exp, model, params)

    # -- Runs (profile-scoped) --------------------------------------------

    def save_metronome_run(self, profile_id: str, data: dict) -> dict:
        """Persist a Metronome Compass run under the profile."""
        self._load_profile(profile_id)  # validate the reference
        run = Run(
            profile_id=profile_id,
            kind="metronome",
            tag=data.get("tag", ""),
            vector_ms=data.get("vector_ms"),
            target_timer_calibration=data.get("target_timer_calibration", 0),
            notes=data.get("notes", ""),
            metronome_user_id=data.get("metronome_user_id"),
            a_seed=dict(data.get("a_seed", {})),
            b_seed=dict(data.get("b_seed", {})),
            elm_calls=data.get("elm_calls"),
            chatot_flips=data.get("chatot_flips"),
            advance_frame=data.get("advance_frame"),
        )
        self._store.write(_RUNS, run.id, run.to_dict())
        return run.to_dict()

    def save_safari_run(self, profile_id: str, data: dict) -> dict:
        """Persist a Safari Compass run under the profile (kind="safari" — feeds the safari
        load-path offset fit, see app/calibration.py; NOT the metronome F_b-vs-M trend)."""
        self._load_profile(profile_id)
        run = Run(
            profile_id=profile_id,
            kind="safari",
            tag=data.get("tag", ""),
            vector_ms=data.get("vector_ms"),
            target_timer_calibration=data.get("target_timer_calibration", 0),
            notes=data.get("notes", ""),
            a_seed=dict(data.get("a_seed", {})),
            b_seed=dict(data.get("b_seed", {})),
            elm_calls=data.get("elm_calls"),
            chatot_flips=data.get("chatot_flips"),
            advance_frame=data.get("advance_frame"),
        )
        self._store.write(_RUNS, run.id, run.to_dict())
        return run.to_dict()

    def list_runs(self, profile_id: str, kind: str | None = None) -> list[dict]:
        """Runs for a profile (optionally filtered to a kind), newest first."""
        out = []
        for rid in self._store.list_ids(_RUNS):
            doc = self._store.read(_RUNS, rid)
            if doc is None or doc.get("profile_id") != profile_id:
                continue
            if kind is not None and doc.get("kind") != kind:
                continue
            out.append(doc)
        out.sort(key=lambda d: d.get("saved_at", ""), reverse=True)
        return out

    def get_run(self, run_id: str) -> dict:
        doc = self._store.read(_RUNS, run_id)
        if doc is None:
            raise ValueError(f"no run with id {run_id!r}")
        return doc

    def set_run_excluded(self, run_id: str, excluded: bool) -> dict:
        """Manually include/exclude a run from calibration (distinct from outliers)."""
        run = Run.from_dict(self.get_run(run_id))
        run.excluded = bool(excluded)
        self._store.write(_RUNS, run.id, run.to_dict())
        return run.to_dict()

    def delete_run(self, run_id: str) -> bool:
        return self._store.delete(_RUNS, run_id)

    def set_tag_excluded(self, profile_id: str, tag: str, excluded: bool) -> dict:
        """Exclude/include a whole tag from calibration. Does NOT touch individual runs'
        own exclude flags — a run's effective reason shows "tag:<name>" separately."""
        p = self._load_profile(profile_id)
        p.set_tag_excluded(tag, bool(excluded))
        self._save_profile(p)
        return self.get_profile(p.id)

    # -- export / import --------------------------------------------------

    def export_expedition(self, expedition_id: str) -> dict:
        """A versioned export envelope for one expedition."""
        from app import portability
        return portability.export_expedition(self._store, expedition_id)

    def export_profile_bundle(self, profile_id: str) -> dict:
        """A versioned export bundle: a profile + its expeditions + runs."""
        from app import portability
        return portability.export_profile_bundle(self._store, profile_id)

    def import_profile_bundle(self, envelope: dict) -> dict:
        """Import a profile bundle as a fresh copy; returns the new id + counts."""
        from app import portability
        return portability.import_profile_bundle(self._store, envelope)

    def export_profile_bundle_to_file(self, profile_id: str) -> dict:
        """Export a profile bundle via a native Save dialog."""
        from app import files
        env = self.export_profile_bundle(profile_id)
        name = (self._store.read(_PROFILES, profile_id) or {}).get("name", "profile")
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name) or "profile"
        path = files.save_json_dialog(f"clayton-{safe}.json", env)
        return {"saved": bool(path), "path": path}

    def import_profile_bundle_from_file(self) -> dict:
        """Import a profile bundle via a native Open dialog."""
        from app import files
        env = files.open_json_dialog()
        if env is None:
            return {"imported": False}
        return {"imported": True, **self.import_profile_bundle(env)}

    # -- Safari Chart: reference data --------------------------------------

    def list_chart_strategies(self) -> list[dict]:
        return chart_lib.list_strategies()

    def list_chart_criteria(self) -> list[dict]:
        return chart_lib.list_criteria()

    def list_safari_pokemon(self) -> list[str]:
        return chart_lib.list_safari_pokemon()

    def _resolve_calibration_models(self, profile_id: str) -> dict:
        """The profile's active saved calibration models, or claytonlib's global model file
        as a fallback (for a profile that hasn't used Calibrate Model yet)."""
        from claytonlib.calibration import CalibrationModel
        active = self.get_active_calibration_model(profile_id)
        if active is not None:
            return {k: CalibrationModel.from_dict(v) for k, v in active["artifact"]["models"].items()}
        return chart_lib.global_calibration_models()

    def calibration_model_summary(self, profile_id: str) -> dict | None:
        """Info about the profile's active calibration model (or the global fallback), if any."""
        return chart_lib.summarize_models(self._resolve_calibration_models(profile_id))

    # -- Safari Chart: Chart CRUD ------------------------------------------

    def create_chart(self, expedition_id: str, fields: dict) -> dict:
        self._load_expedition(expedition_id)  # validate the reference
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a chart needs a name")
        c = Chart(
            expedition_id=expedition_id, name=name,
            strategy_name=fields["strategy_name"], criteria_name=fields["criteria_name"],
            setup_delay_seconds=int(fields.get("setup_delay_seconds", 0)),
            max_target_seconds=int(fields.get("max_target_seconds", 300)),
        )
        self._store.write(_CHARTS, c.id, c.to_dict())
        return c.to_dict()

    def list_charts(self, expedition_id: str) -> list[dict]:
        out = []
        for cid in self._store.list_ids(_CHARTS):
            doc = self._store.read(_CHARTS, cid)
            if doc is not None and doc.get("expedition_id") == expedition_id:
                out.append(doc)
        out.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return out

    def get_chart(self, chart_id: str) -> dict:
        doc = self._store.read(_CHARTS, chart_id)
        if doc is None:
            raise ValueError(f"no chart with id {chart_id!r}")
        return doc

    def delete_chart(self, chart_id: str) -> bool:
        return self._store.delete(_CHARTS, chart_id)

    # -- Safari Chart: compute ----------------------------------------------

    def chart_canon_status(self, expedition_id: str, chart_id: str) -> dict:
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        return chart_lib.canon_status(exp, c)

    def chart_delete_canon(self, expedition_id: str, chart_id: str) -> bool:
        """Delete a chart's canon map, freeing disk and forcing a full rebuild next time."""
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        return chart_lib.delete_canon(exp, c)

    def chart_precompute_start(self, expedition_id: str, chart_id: str) -> dict:
        """Begin building the canon map in the background; returns the first progress snapshot."""
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        models = self._resolve_calibration_models(exp["profile_id"])
        runner = chart_lib.precompute_runner(exp, c, models)
        return self._chart_sessions.start(runner)

    def chart_precompute_poll(self, session_id: str) -> dict:
        return self._chart_sessions.poll(session_id)

    def chart_rank_best_per_time(self, expedition_id: str, chart_id: str, params: dict) -> dict:
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        models = self._resolve_calibration_models(exp["profile_id"])
        return chart_lib.rank_best_per_time(exp, c, models, params)

    def chart_rank_at_time(self, expedition_id: str, chart_id: str,
                           initial_time: str, params: dict) -> list[dict]:
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        models = self._resolve_calibration_models(exp["profile_id"])
        return chart_lib.rank_at_time(exp, c, models, initial_time, params)

    def chart_examine(self, expedition_id: str, chart_id: str,
                      initial_time: str, vector_ms: int, params: dict) -> dict:
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        models = self._resolve_calibration_models(exp["profile_id"])
        return chart_lib.examine(exp, c, models, initial_time, vector_ms, params)

    # -- Safari Chart: Target CRUD -------------------------------------------

    def save_target(self, expedition_id: str, chart_id: str, fields: dict) -> dict:
        self._load_expedition(expedition_id)
        self.get_chart(chart_id)  # validate the reference
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a target needs a name")
        t = Target(
            expedition_id=expedition_id, chart_id=chart_id, name=name,
            initial_time=fields["initial_time"], vector_ms=int(fields["vector_ms"]),
            target_delay=int(fields["target_delay"]), p=float(fields["p"]),
            sigma=float(fields["sigma"]), second=fields.get("second"),
            mdmsh=list(fields.get("mdmsh", [])),
        )
        self._store.write(_TARGETS, t.id, t.to_dict())
        return t.to_dict()

    def list_targets(self, expedition_id: str, chart_id: str | None = None) -> list[dict]:
        out = []
        for tid in self._store.list_ids(_TARGETS):
            doc = self._store.read(_TARGETS, tid)
            if doc is None or doc.get("expedition_id") != expedition_id:
                continue
            if chart_id is not None and doc.get("chart_id") != chart_id:
                continue
            out.append(doc)
        out.sort(key=lambda d: d.get("created_at", ""), reverse=True)
        return out

    def get_target(self, target_id: str) -> dict:
        doc = self._store.read(_TARGETS, target_id)
        if doc is None:
            raise ValueError(f"no target with id {target_id!r}")
        return doc

    def delete_target(self, target_id: str) -> bool:
        return self._store.delete(_TARGETS, target_id)

    def examine_target(self, target_id: str, params: dict) -> dict:
        """Examine a SAVED target by id (convenience over chart_examine)."""
        t = self.get_target(target_id)
        return self.chart_examine(t["expedition_id"], t["chart_id"],
                                  t["initial_time"], t["vector_ms"], params)

    # -- Calibrate Model ----------------------------------------------------

    def preview_calibration(self, profile_id: str, params: dict | None = None) -> dict:
        """Fit a calibration model from the profile's runs (after exclusions) without saving
        anything — the Calibrate Model view's live preview. Metronome runs fit the F_b-vs-M
        trend; safari runs fit the safari load-path offset against it (see app/calibration.py)."""
        p = self._load_profile(profile_id)
        metronome_runs = self.list_runs(profile_id, kind="metronome")
        safari_runs = self.list_runs(profile_id, kind="safari")
        return calibration_lib.preview_fit(metronome_runs, safari_runs, p.excluded_tags)

    def save_calibration_model(self, profile_id: str, fields: dict) -> dict:
        """Persist a previewed fit as a new, numbered model; makes it the active one
        unless told not to (a user may want to compare before switching)."""
        self._load_profile(profile_id)
        preview = fields.get("preview")
        if not preview:
            raise ValueError("save_calibration_model needs the preview it's saving")
        existing = self.list_calibration_models(profile_id)
        number = (max((m["number"] for m in existing), default=0)) + 1
        make_active = bool(fields.get("make_active", True))
        doc = CalibrationModelDoc(
            profile_id=profile_id, number=number, name=(fields.get("name") or "").strip(),
            artifact=preview["artifact"], stats=preview.get("stats", {}), active=make_active)
        if make_active:
            for m in existing:
                if m.get("active"):
                    m["active"] = False
                    self._store.write(_CALIBRATION_MODELS, m["id"], m)
        self._store.write(_CALIBRATION_MODELS, doc.id, doc.to_dict())
        return doc.to_dict()

    def list_calibration_models(self, profile_id: str) -> list[dict]:
        out = []
        for mid in self._store.list_ids(_CALIBRATION_MODELS):
            doc = self._store.read(_CALIBRATION_MODELS, mid)
            if doc is not None and doc.get("profile_id") == profile_id:
                out.append(doc)
        out.sort(key=lambda d: d.get("number", 0), reverse=True)
        return out

    def get_active_calibration_model(self, profile_id: str) -> dict | None:
        return next((m for m in self.list_calibration_models(profile_id) if m.get("active")), None)

    def set_active_calibration_model(self, profile_id: str, model_id: str) -> dict:
        """Make a previously-saved model the active one Safari Chart uses."""
        target = self._store.read(_CALIBRATION_MODELS, model_id)
        if target is None or target.get("profile_id") != profile_id:
            raise ValueError(f"no calibration model {model_id!r} for this profile")
        for m in self.list_calibration_models(profile_id):
            active = m["id"] == model_id
            if m.get("active") != active:
                m["active"] = active
                self._store.write(_CALIBRATION_MODELS, m["id"], m)
        return self._store.read(_CALIBRATION_MODELS, model_id)

    def delete_calibration_model(self, model_id: str) -> bool:
        return self._store.delete(_CALIBRATION_MODELS, model_id)
