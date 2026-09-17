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

from app import metronome
from app.models import Expedition, MetronomeUser, Profile, Run
from app.store import FileStore, Store

_PROFILES = "profiles"
_EXPEDITIONS = "expeditions"
_RUNS = "runs"


class Facade:
    def __init__(self, store: Store | None = None):
        self._store = store or FileStore()
        from app.metronome_session import SessionRegistry
        self._sessions = SessionRegistry()

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
