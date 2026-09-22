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
                "trainer_name": p.trainer_name,
                "version": p.version,
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
            # Reasons this user can't be SELECTED in Metronome Compass specifically (e.g.
            # New Run's user picker) — distinct from `warnings`, which are advisory only.
            user_dict["hard_errors"] = user.hard_errors()
        doc["has_valid_metronome_user"] = p.has_valid_metronome_user
        return doc

    def create_profile(self, fields: dict) -> dict:
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a profile needs a name")
        p = Profile(
            name=name,
            trainer_name=fields.get("trainer_name", ""),
            version=fields.get("version", ""),
            console=fields.get("console", ""),
        )
        self._save_profile(p)
        self._ensure_standard_calibration_model_seeded(p.id)
        return self.get_profile(p.id)

    def _ensure_standard_calibration_model_seeded(self, profile_id: str) -> None:
        """Seeds the bundled 'Standard' calibration model into `profile_id` if it has no
        calibration models at all yet — a no-op otherwise. Called both from create_profile
        (new profiles) AND from _resolve_calibration_models (every profile that predates
        this feature, so it self-heals on next use rather than staying stuck on the old
        'no model' error forever)."""
        if self.list_calibration_models(profile_id):
            return
        self._seed_standard_calibration_model(profile_id)

    def _seed_standard_calibration_model(self, profile_id: str) -> None:
        """Every fresh profile starts with a bundled 'Standard' calibration model, active
        by default — a real fitted model shipped with the app, so Safari Chart works
        immediately instead of being blocked until the user re-runs their own Metronome
        Compass calibration. Harmless to overwrite later: it's just model #1, like any
        other saved fit, and can be replaced as the active one or deleted."""
        from app._resources import standard_calibration_modelset
        doc = CalibrationModelDoc(
            profile_id=profile_id, number=1, name="Standard",
            artifact=standard_calibration_modelset(), active=True)
        self._store.write(_CALIBRATION_MODELS, doc.id, doc.to_dict())

    def update_profile(self, profile_id: str, fields: dict) -> dict:
        """Update a profile's own settings (name, trainer name, version, console note) after
        creation (round 13 feedback) -- everything else (metronome users, etc.) is
        untouched."""
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a profile needs a name")
        p = self._load_profile(profile_id)
        p.name = name
        p.trainer_name = fields.get("trainer_name", "")
        p.version = fields.get("version", "")
        p.console = fields.get("console", "")
        self._save_profile(p)
        return self.get_profile(profile_id)

    def profile_delete_summary(self, profile_id: str) -> dict:
        """What delete_profile would remove (or, if expeditions exist, what's blocking it --
        see delete_profile), for a confirmation prompt.

        `expeditions`/`expedition_names` are what blocks it; `other_profiles` lists the
        profiles those expeditions could be MOVED to instead of deleted (round 15 feedback --
        reassigning is the other way out of the block, so the prompt has to offer it)."""
        expeditions = self.list_expeditions(profile_id)
        runs = len(self.list_runs(profile_id, "metronome")) + len(self.list_runs(profile_id, "safari"))
        others = [{"id": p["id"], "name": p["name"]} for p in self.list_profiles()
                  if p["id"] != profile_id]
        return {"expeditions": len(expeditions),
               "expedition_names": [e["name"] for e in expeditions],
               "expedition_list": [{"id": e["id"], "name": e["name"]} for e in expeditions],
               "other_profiles": others,
               "runs": runs, "calibration_models": len(self.list_calibration_models(profile_id)),
               "metronome_users": len((self._store.read(_PROFILES, profile_id) or {})
                                      .get("metronome_users", []))}

    def move_expedition(self, expedition_id: str, profile_id: str) -> dict:
        """Reassign an expedition to a different profile.

        The alternative to deleting an expedition when its profile is going away (round 15
        feedback). Only the expedition's own `profile_id` moves: its charts and targets follow
        it because they reference the EXPEDITION, not the profile. Runs and calibration models
        do NOT follow -- those are owned by the profile directly, never by an expedition, so
        the moved expedition is scored against its NEW profile's active calibration model.
        """
        exp = self._load_expedition(expedition_id)
        if self._store.read(_PROFILES, profile_id) is None:
            raise ValueError(f"no profile with id {profile_id!r}")
        if exp.profile_id == profile_id:
            return exp.to_dict()
        exp.profile_id = profile_id
        doc = exp.to_dict()
        self._store.write(_EXPEDITIONS, exp.id, doc)
        return doc

    def delete_profile(self, profile_id: str) -> bool:
        """Deletes the profile and its own directly-owned data (every run, every calibration
        model -- metronome users live inline on the profile document, so they're removed
        automatically with it). Does NOT delete this profile's expeditions (round 13
        feedback) -- refuses instead while any exist, so the user deletes/reviews them
        individually (each has its own Delete on the Configure page) rather than losing them
        as a side effect of deleting the profile."""
        expeditions = self.list_expeditions(profile_id)
        if expeditions:
            names = ", ".join(e["name"] for e in expeditions)
            raise ValueError(
                f"This profile still has {len(expeditions)} expedition(s) ({names}) -- "
                "delete those first, then delete the profile.")
        for kind in ("metronome", "safari"):
            for r in self.list_runs(profile_id, kind):
                self._store.delete(_RUNS, r["id"])
        for m in self.list_calibration_models(profile_id):
            self._store.delete(_CALIBRATION_MODELS, m["id"])
        return self._store.delete(_PROFILES, profile_id)

    # -- metronome users --------------------------------------------------

    def _probe_metronome_user(self, fields: dict) -> MetronomeUser:
        return MetronomeUser(
            id=0,
            name=fields.get("name", "?"),
            species=fields.get("species", "Chansey"),
            gender=fields.get("gender"),
            level=fields.get("level"),
            moveset=list(fields.get("moveset", [])),
            ability=fields.get("ability"),
            lagging_tail=bool(fields.get("lagging_tail", False)),
        )

    def metronome_user_warnings(self, fields: dict) -> list[str]:
        """Suitability warnings for prospective fields, so the UI can warn pre-save. These
        are advisory only — see metronome_user_hard_errors for what actually blocks saving."""
        return self._probe_metronome_user(fields).suitability_warnings()

    def metronome_user_hard_errors(self, fields: dict) -> list[str]:
        """Blocking issues for prospective fields (e.g. a calibration-breaking ability) —
        add_metronome_user raises if these are non-empty; exposed separately so the UI can
        disable the submit button pre-save instead of only surfacing the error after."""
        return self._probe_metronome_user(fields).hard_errors()

    def list_metronome_species(self) -> list[dict]:
        """Every species offerable in the Metronome-user Species dropdown — gender
        category, real abilities (flagging which are hard-blocked, see
        MetronomeUser.hard_errors), and the full HGSS-learnable movepool (level-up/TM-HM/
        tutor/egg/pre-evolution) for the 4 moveset dropdowns."""
        from app.models import HARD_ERROR_ABILITIES
        from claytonlib.metronome_species import list_metronome_species as _list
        return [{
            "name": s.name, "dex_no": s.dex_no, "gender": s.gender,
            "abilities": list(s.abilities), "moves": list(s.moves),
            "blocking_abilities": [a for a in s.abilities if a in HARD_ERROR_ABILITIES],
        } for s in _list()]

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
            "hard_errors": user.hard_errors(),
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
                "completed": e.completed,
            })
        # Completed expeditions sort below incomplete ones (round 12 feedback), name within
        # each group.
        out.sort(key=lambda d: (d["completed"], d["name"].lower()))
        return out

    def set_expedition_completed(self, expedition_id: str, completed: bool) -> dict:
        e = self._load_expedition(expedition_id)
        e.completed = bool(completed)
        self._store.write(_EXPEDITIONS, e.id, e.to_dict())
        return e.to_dict()

    def get_expedition(self, expedition_id: str) -> dict:
        return self._load_expedition(expedition_id).to_dict()

    def _assert_expedition_name_free(self, name: str, except_id: str | None = None) -> None:
        """Expedition names are unique GLOBALLY, not per profile (round 16 feedback).

        An expedition is *associated with* a profile rather than owned by one — it can be moved
        between them (move_expedition) — so scoping uniqueness per profile would let a rename or
        a move create two indistinguishable "Shiny Metang"s. Imports resolve a collision by
        auto-numbering; a person typing a name gets told instead, so they can pick a real one.
        `except_id` is the expedition being edited, which never collides with itself.
        """
        for eid in self._store.list_ids(_EXPEDITIONS):
            doc = self._store.read(_EXPEDITIONS, eid)
            if doc is None or doc.get("id") == except_id:
                continue
            if (doc.get("name") or "").strip().lower() == name.lower():
                owner = (self._store.read(_PROFILES, doc.get("profile_id")) or {}).get("name")
                where = f" (in profile \"{owner}\")" if owner else ""
                raise ValueError(
                    f"An expedition named \"{doc['name']}\"{where} already exists. "
                    "Expedition names have to be unique across every profile — pick another.")

    def create_expedition(self, fields: dict) -> dict:
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("an expedition needs a name")
        profile_id = fields.get("profile_id")
        if not profile_id:
            raise ValueError("an expedition must reference a profile")
        # Fail early if the referenced profile is missing.
        self._load_profile(profile_id)
        self._assert_expedition_name_free(name)
        e = Expedition.from_dict({**fields, "name": name})
        self._store.write(_EXPEDITIONS, e.id, e.to_dict())
        return e.to_dict()

    def save_expedition(self, expedition: dict) -> dict:
        """Upsert an existing expedition from its full document."""
        if not expedition.get("id"):
            raise ValueError("save_expedition needs an expedition id (use create_expedition for new)")
        e = Expedition.from_dict(expedition)
        self._load_profile(e.profile_id)  # validate the reference still resolves
        self._assert_expedition_name_free(e.name.strip(), except_id=e.id)
        self._store.write(_EXPEDITIONS, e.id, e.to_dict())
        return e.to_dict()

    def expedition_delete_summary(self, expedition_id: str) -> dict:
        """What delete_expedition would remove, for a confirmation prompt."""
        return {"charts": len(self.list_charts(expedition_id)),
               "targets": len(self.list_targets(expedition_id))}

    def delete_expedition(self, expedition_id: str) -> bool:
        """Deletes the expedition and everything scoped to it (its charts and targets).
        Runs, calibration models, and metronome users live on the PROFILE, not the
        expedition (see app/models.py's Run/MetronomeUser docs), so they're untouched."""
        for c in self.list_charts(expedition_id):
            self._store.delete(_CHARTS, c["id"])
        for t in self.list_targets(expedition_id):
            self._store.delete(_TARGETS, t["id"])
        return self._store.delete(_EXPEDITIONS, expedition_id)

    # -- reference data ---------------------------------------------------

    def list_safari_areas(self) -> list[str]:
        """The Safari Zone area names, for the expedition-config dropdown."""
        from claytonlib.safari_encounters import safari_areas
        return safari_areas()

    def list_safari_areas_for_pokemon(self, pokemon: str) -> list[str]:
        """Only the areas where `pokemon` can actually appear — narrows the Safari area
        dropdown once a Pokemon is chosen (clayton-b42.10.3)."""
        from claytonlib.safari_encounters import areas_for_species
        return areas_for_species(pokemon)

    def safari_block_requirement(self, area: str, pokemon: str) -> dict | None:
        """The block score `pokemon` needs to appear in `area`, or None if it's already
        reachable unconditionally there (or doesn't appear in that area at all) — drives
        the "(required: N)" label and invalid-styling on the block-score inputs."""
        from claytonlib.safari_encounters import block_requirement_for
        return block_requirement_for(area, pokemon)

    # -- Metronome Compass: seed identification ---------------------------

    def metronome_seed_a(self, params: dict) -> dict:
        """Candidate initial seeds, narrowed by observed roamer routes + Elm calls."""
        return metronome.seed_a(params)

    def metronome_key_seed_info(self, key_seed: int, prev_routes: dict) -> dict:
        """The key seed's own roamer routes + Elm (to spot a key-seed hit)."""
        return metronome.key_seed_info(key_seed, prev_routes)

    def times_on_date(self, key_seed: int, month: int | None = None, day: int | None = None,
                      second: int | None = None) -> list[str]:
        """Every valid initial time for `key_seed`, optionally filtered to a month (1-12),
        a day-of-month (1-31), and/or a second-of-minute value — powers the calendar/
        date-picker flow for Initial-time fields. All filters are optional and independent
        (a month alone, or month+day, etc.); with none, every valid time comes back."""
        return metronome.times_on_date(key_seed, month, day, second)

    def _metronome_model(self, params: dict):
        """The calibration model a metronome Seed B search should be centered on.

        The METRONOME-path model -- never with_safari_offset(): that offset describes the
        Safari Zone's extra loading screen, which has nothing to do with a Magikarp battle.
        Scoped by profile_id when the caller supplies one; falls back to claytonlib's global
        model file otherwise (a caller that predates profile-scoped models)."""
        profile_id = params.get("profile_id")
        models = (self._resolve_calibration_models(profile_id) if profile_id
                  else chart_lib.global_calibration_models())
        return models.get(params.get("fps_model", "linear")) or next(iter(models.values()), None)

    def metronome_seed_b(self, params: dict) -> dict:
        """Candidate battle seeds, each with its precomputed Metronome path.

        Centered on where the active calibration model says Seed B lands for this target's
        Vector ms -- NOT on the key seed, which is where Seed A lands."""
        return metronome.seed_b(params, self._metronome_model(params))

    def _json_session_state(self, state: dict) -> dict:
        result = state.get("result")
        if result:  # the identified candidate carries a datetime + path objects
            state = {**state, "result": metronome._row_b_json(result)}
        return state

    def metronome_seed_b_start(self, params: dict) -> dict:
        """Begin the interactive Seed B narrowing; returns the first question (or result)."""
        runner = metronome.seed_b_runner(params, self._metronome_model(params))
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
            # The advance count the run will actually use: the encounter frame the frame-route
            # guide planned (Safari Compass locks the Seed B panel until a route exists, so one
            # is always available), falling back to the expedition's configured key-seed
            # advances. It only matters at all when the model carries a per-advance offset.
            advances = params.get("advances")
            if advances is None:
                advances = exp.get("key_seed_advances") or 0
            model = model.with_safari_offset(int(advances))
        return safari_compass.seed_b(exp, model, params)

    def safari_compass_cheatsheet(self, pokemon_name: str) -> list[dict]:
        """The (key, action, in-game message) legend for a Safari Compass path — what each
        letter actually looks like on screen for this species (e.g. a mud-crit's message)."""
        from claytonlib.compass import cheatsheet_rows
        return [{"key": k, "action": a, "message": m} for k, a, m in cheatsheet_rows(pokemon_name)]

    def safari_compass_identify_frame(self, params: dict) -> dict:
        """Pin Seed A's current advance frame from the Elm calls heard since it loaded.

        params: seed (int or hex string), prev_routes ({r,e,l}), observed_elm — re-call with
        the full string heard so far as more calls come in, like metronome_seed_a."""
        from app import safari_compass
        seed = params["seed"]
        seed = int(seed, 16) if isinstance(seed, str) else int(seed)
        return safari_compass.identify_seed_a_frame(
            seed, params.get("prev_routes") or {}, params.get("observed_elm", ""))

    def safari_compass_plan_frame(self, params: dict) -> dict:
        """A chatot-flip + Elm-call route from the pinned current frame to a chosen target
        encounter frame. params: seed, prev_routes, current_frame, encounter_frame, margin."""
        from app import safari_compass
        seed = params["seed"]
        seed = int(seed, 16) if isinstance(seed, str) else int(seed)
        return safari_compass.plan_frame_route(
            seed, params.get("prev_routes") or {},
            int(params["current_frame"]), int(params["encounter_frame"]),
            margin=int(params.get("margin", 3)))

    def safari_compass_find_target_frame(self, params: dict) -> dict:
        """In-house target-encounter-frame search (vs. pasting one from Pokefinder).

        params: seed, prev_routes, current_frame, area, tod (morning/day/night), block_config,
        pokemon, margin, max_frame, aim_advance (optional)."""
        from app import safari_compass
        seed = params["seed"]
        seed = int(seed, 16) if isinstance(seed, str) else int(seed)
        aim = params.get("aim_advance")
        return safari_compass.find_target_frame(
            seed, params.get("prev_routes") or {}, int(params["current_frame"]),
            params["area"], params["tod"], params.get("block_config") or {}, params["pokemon"],
            margin=int(params.get("margin", 3)), max_frame=int(params.get("max_frame", 300)),
            aim_advance=int(aim) if aim not in (None, "") else None)

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
            frame_guide=data.get("frame_guide", ""),
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

    def run_delay_metrics(self, profile_id: str, kind: str | None = None) -> dict:
        """Per-run Vector delay / Delta delay for the Review Data runs tables (round 15).

        Keyed by run id, so the table can look each row up without changing list_runs' shape
        (these are derived from the profile's ACTIVE calibration model, which list_runs has no
        business resolving on every call). See app.calibration.run_delay_metrics."""
        models = self._resolve_calibration_models(profile_id)
        model = models.get("linear") or next(iter(models.values()), None)
        metrics = {}
        for run in self.list_runs(profile_id, kind):
            m = calibration_lib.run_delay_metrics(run, model)
            if m is not None:
                metrics[run["id"]] = m
        return {"metrics": metrics, "has_model": model is not None}

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
    #
    # Every import that can collide (expedition-into-profile by name, bundle-into-a-
    # same-named-profile) returns {"collision": True, "existing_id", "existing_name"}
    # instead of importing when `on_collision` isn't given — the UI shows that to the
    # user and re-calls with an explicit decision. See app/portability.py for the exact
    # semantics of each `on_collision` value.

    def export_runs_to_file(self, run_ids: list[str], default_name: str | None = None) -> dict:
        """Export the given runs as jsonl (one run per line — no envelope) via a native
        Save dialog. `run_ids` decides both which runs and the export scope entirely —
        the UI resolves "all" / "all except excluded" / a manual selection into this list
        before calling here. `default_name` lets the caller suggest a more specific
        filename (e.g. including the profile/expedition it was exported from); falls back
        to a kind-based name (clayton-runs-metronome.jsonl / clayton-runs-safari.jsonl,
        or the generic clayton-runs.jsonl for a mixed-kind selection) when not given."""
        from app import files, portability
        rows = portability.export_runs_jsonl(self._store, run_ids)
        if default_name is None:
            kinds = {r.get("kind") for r in rows}
            default_name = f"clayton-runs-{kinds.pop()}.jsonl" if len(kinds) == 1 else "clayton-runs.jsonl"
        path = files.save_jsonl_dialog(default_name, rows, store=self._store)
        return {"saved": bool(path), "path": path, "count": len(rows)}

    def import_runs_from_file(self, profile_id: str) -> dict:
        """Import runs from a jsonl file via a native Open dialog — always a copy (fresh
        ids), never a collision/overwrite. Each row's own "kind" field ("metronome"/
        "safari") decides which compass it belongs to; no scope selection needed here."""
        from app import files, portability
        rows = files.open_jsonl_dialog(store=self._store)
        if rows is None:
            return {"imported": False}
        docs = portability.import_runs_jsonl(self._store, profile_id, rows)
        return {"imported": True, "count": len(docs)}

    def export_expedition(self, expedition_id: str) -> dict:
        """A versioned export envelope for one expedition (+ its charts/targets)."""
        from app import portability
        return portability.export_expedition(self._store, expedition_id)

    def import_expedition(self, profile_id: str, envelope: dict, on_collision: str | None = None) -> dict:
        """Import one expedition (+ its charts/targets) into a profile."""
        from app import portability
        self._load_profile(profile_id)
        return portability.import_expedition(self._store, profile_id, envelope, on_collision)

    def export_profile_bundle(self, profile_id: str, include_excluded: bool = True) -> dict:
        """A versioned export bundle: a profile + its expeditions/charts/targets/runs/
        calibration models. `include_excluded=False` drops manually-excluded runs."""
        from app import portability
        return portability.export_profile_bundle(self._store, profile_id, include_excluded)

    def import_profile_bundle(self, envelope: dict, on_collision: str | None = None) -> dict:
        """Import a profile bundle. `on_collision`: "new" (separate profile, default-safe
        when there's no collision) or "merge" (fold into the existing same-named profile)."""
        from app import portability
        return portability.import_profile_bundle(self._store, envelope, on_collision)

    def export_calibration_model(self, model_id: str) -> dict:
        """A versioned export envelope for one saved calibration model."""
        from app import portability
        return portability.export_calibration_model(self._store, model_id)

    def import_calibration_model(self, profile_id: str, envelope: dict) -> dict:
        """Import one calibration model into a profile, as a new inactive entry."""
        from app import portability
        self._load_profile(profile_id)
        return portability.import_calibration_model(self._store, profile_id, envelope)

    def _export_filename(self, kind: str, name: str, ext: str = "json") -> str:
        """A suggested export filename that says what the file IS, not just that it's ours.

        "clayton-profile-Silver.json" rather than "clayton-Silver.json" (round 17 feedback) —
        with expeditions, profiles, models and runs all exporting as plain JSON, the prefix is
        the only thing distinguishing them in a folder.
        """
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "")) or kind
        return f"clayton-{kind}-{safe}.{ext}"

    def export_calibration_model_to_file(self, model_id: str) -> dict:
        """Export one calibration model via a native Save dialog."""
        from app import files
        env = self.export_calibration_model(model_id)
        m = env["data"]["model"]
        name = m.get("name") or f"{m.get('number', '')}"
        path = files.save_json_dialog(
            self._export_filename("model", name), env, store=self._store)
        return {"saved": bool(path), "path": path}

    def import_calibration_model_from_file(self, profile_id: str) -> dict:
        """Import a calibration model via a native Open dialog. No collision handling —
        models always land as a new, inactive, freshly-numbered entry (see portability)."""
        from app import files
        env = files.open_json_dialog(store=self._store)
        if env is None:
            return {"imported": False}
        return {"imported": True, **self.import_calibration_model(profile_id, env)}

    def export_expedition_to_file(self, expedition_id: str) -> dict:
        """Export one expedition via a native Save dialog."""
        from app import files
        env = self.export_expedition(expedition_id)
        name = (self._store.read(_EXPEDITIONS, expedition_id) or {}).get("name", "")
        path = files.save_json_dialog(
            self._export_filename("expedition", name), env, store=self._store)
        return {"saved": bool(path), "path": path}

    def import_expedition_from_file(self, profile_id: str) -> dict:
        """Open an expedition export via a native Open dialog. If it collides with an
        existing expedition (same name in this profile), returns the collision instead of
        importing — resolve it with import_expedition_resolve."""
        from app import files
        env = files.open_json_dialog(store=self._store)
        if env is None:
            return {"imported": False}
        result = self.import_expedition(profile_id, env)
        if result.get("collision"):
            return {"imported": False, **result, "envelope": env}
        return {"imported": True, **result}

    def import_expedition_resolve(self, profile_id: str, envelope: dict, on_collision: str) -> dict:
        """Finish an import_expedition_from_file that returned a collision, with the
        user's explicit "copy" or "replace" decision."""
        return {"imported": True, **self.import_expedition(profile_id, envelope, on_collision)}

    def export_profile_bundle_to_file(self, profile_id: str, include_excluded: bool = True) -> dict:
        """Export a profile bundle via a native Save dialog."""
        from app import files
        env = self.export_profile_bundle(profile_id, include_excluded)
        name = (self._store.read(_PROFILES, profile_id) or {}).get("name", "")
        path = files.save_json_dialog(
            self._export_filename("profile", name), env, store=self._store)
        return {"saved": bool(path), "path": path}

    def import_profile_bundle_from_file(self) -> dict:
        """Open a profile bundle via a native Open dialog. If it collides with an existing
        same-named profile, returns the collision instead of importing — resolve it with
        import_profile_bundle_resolve."""
        from app import files
        env = files.open_json_dialog(store=self._store)
        if env is None:
            return {"imported": False}
        result = self.import_profile_bundle(env)
        if result.get("collision"):
            return {"imported": False, **result, "envelope": env}
        return {"imported": True, **result}

    def import_profile_bundle_resolve(self, envelope: dict, on_collision: str) -> dict:
        """Finish an import_profile_bundle_from_file that returned a collision, with the
        user's explicit "new" or "merge" decision."""
        return {"imported": True, **self.import_profile_bundle(envelope, on_collision)}

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
        self._ensure_standard_calibration_model_seeded(profile_id)  # self-heal older profiles
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

    def update_chart_window(self, chart_id: str, setup_delay_seconds: int,
                            max_target_seconds: int) -> dict:
        """Change an existing chart's delay window. Safe to widen or narrow after the fact —
        the canon map's signature doesn't include setup/max (see claytonlib.chart.canon's
        _config_signature), so this never invalidates a computed chart; a wider window just
        means the next Compute chart extends into the newly-uncovered range."""
        doc = self.get_chart(chart_id)
        doc["setup_delay_seconds"] = int(setup_delay_seconds)
        doc["max_target_seconds"] = int(max_target_seconds)
        self._store.write(_CHARTS, chart_id, doc)
        return doc

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
        """Delete a chart, and its computed data too unless something else still maps to it.

        A canon map is keyed by pokemon + key seed + strategy + criteria, NOT by chart id, so
        several charts (across expeditions) can legitimately share one. Deleting the map while
        another chart still points at it would silently throw away that chart's precompute, so
        this only removes it once no other chart resolves to the same canon path (round 18
        feedback). The chart's own cached rank report always goes, since nothing else uses it.
        """
        doc = self._store.read(_CHARTS, chart_id)
        if doc is None:
            return False
        exp = self._store.read(_EXPEDITIONS, doc.get("expedition_id"))
        if exp is not None:
            import os
            canon_path = chart_lib.canon_path(exp, doc)
            try:
                os.remove(chart_lib.rank_report_path(exp, doc))
            except OSError:
                pass
            others = [cid for cid in self._store.list_ids(_CHARTS) if cid != chart_id]
            shared = False
            for cid in others:
                other = self._store.read(_CHARTS, cid)
                if other is None:
                    continue
                other_exp = self._store.read(_EXPEDITIONS, other.get("expedition_id"))
                if other_exp is not None and chart_lib.canon_path(other_exp, other) == canon_path:
                    shared = True
                    break
            if not shared:
                chart_lib.delete_canon(exp, doc)
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

    def chart_rank_start(self, expedition_id: str, chart_id: str, params: dict) -> dict:
        """Rank targets, reporting progress — a cold rank is ~35 s and deserves a real bar
        rather than a spinner (round 18 feedback).

        Returns a finished snapshot immediately when a valid cached report exists (the common
        case, and it would be silly to make that wait on a poll cycle); otherwise starts a
        background run and returns its first snapshot, polled via chart_rank_poll.
        """
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        models = self._resolve_calibration_models(exp["profile_id"])
        hit = chart_lib.rank_cached_only(exp, c, models, params)
        if hit is not None:
            return {"session_id": None, "done": True, "error": None,
                    "progress": {}, "result": hit}

        def runner(progress_cb):
            return chart_lib.rank_best_per_time(exp, c, models, params, progress=progress_cb)

        return self._chart_sessions.start(runner)

    def chart_rank_poll(self, session_id: str) -> dict:
        return self._chart_sessions.poll(session_id)

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

    def chart_examine_second(self, expedition_id: str, chart_id: str, initial_time: str,
                             vector_ms: int, second: int, params: dict) -> dict:
        """Individual (frame, seed) rows for one candidate second of a chart_examine() result —
        click a second in Examine target to drill into this."""
        exp, c = self._load_expedition(expedition_id).to_dict(), self.get_chart(chart_id)
        models = self._resolve_calibration_models(exp["profile_id"])
        return chart_lib.examine_second(exp, c, models, initial_time, vector_ms, second, params)

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

    def examine_target_second(self, target_id: str, second: int, params: dict) -> dict:
        """Examine a SAVED target's one candidate second, per-seed (convenience over
        chart_examine_second)."""
        t = self.get_target(target_id)
        return self.chart_examine_second(t["expedition_id"], t["chart_id"],
                                         t["initial_time"], t["vector_ms"], second, params)

    # -- Calibrate Model ----------------------------------------------------

    def preview_calibration(self, profile_id: str, params: dict | None = None) -> dict:
        """Fit a calibration model from the profile's metronome runs (after exclusions)
        without saving anything — Metronome Compass's Calibrate Model live preview. Never
        looks at safari runs or produces a safari_offset; see preview_safari_calibration for
        Safari Compass's own flow (app/calibration.py)."""
        p = self._load_profile(profile_id)
        metronome_runs = self.list_runs(profile_id, kind="metronome")
        return calibration_lib.preview_fit(metronome_runs, p.excluded_tags)

    def preview_safari_calibration(self, profile_id: str, base_model_id: str,
                                   params: dict | None = None) -> dict:
        """Safari Compass's own Calibrate Model live preview: fit `safari_offset` from the
        profile's safari runs (after exclusions) against `base_model_id`'s own trend, held
        fixed. `base_model_id` may be ANY saved model for this profile, including the
        bundled "Standard" one — not just the currently-active model. Touches no persisted
        state; save the result with save_calibration_model like any other preview.

        params: {"per_advance": bool, "safari_jitter": bool} — the two calibration-time
        options (fit a per-advance offset; fit the safari path's own landing spread). Both
        default off. They are fit-time only: what they produce is baked into the saved model,
        so prediction just uses whichever model is active."""
        p = self._load_profile(profile_id)
        base_doc = self._store.read(_CALIBRATION_MODELS, base_model_id)
        if base_doc is None or base_doc.get("profile_id") != profile_id:
            raise ValueError(f"no calibration model {base_model_id!r} for this profile")
        from claytonlib.calibration import CalibrationModel
        base_models = {k: CalibrationModel.from_dict(v)
                       for k, v in base_doc["artifact"]["models"].items()}
        safari_runs = self.list_runs(profile_id, kind="safari")
        params = params or {}
        report = calibration_lib.preview_safari_offset(
            base_models, safari_runs, p.excluded_tags,
            per_advance=bool(params.get("per_advance")),
            safari_jitter=bool(params.get("safari_jitter")))
        report["base_model_id"] = base_doc["id"]
        report["base_model_name"] = base_doc.get("name") or f"#{base_doc['number']}"
        return report

    def safari_run_exclude_reasons(self, profile_id: str) -> dict:
        """Manual/tag/incomplete exclude reasons for the profile's safari runs — Safari
        Compass Review Data's Runs-tab preview, independent of any calibration fit (seeing
        why a run wouldn't currently be included doesn't need a base model chosen)."""
        p = self._load_profile(profile_id)
        safari_runs = self.list_runs(profile_id, kind="safari")
        _records, pre_excluded = calibration_lib.effective_included(
            safari_runs, set(p.excluded_tags), record_fn=calibration_lib._record_for_safari_run)
        return {"reasons": dict(pre_excluded)}

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
