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
from app.models import (
    ENCOUNTER_ROAMER, ENCOUNTER_STATIC, CalibrationModelDoc, Chart, Expedition, Hunt,
    MetronomeUser, PartyPokemon, Profile, Run, Seed, Target, _default_preferences,
)
from app.store import FileStore, Store
from claytonlib.battle.catch import shake_messages
from claytonlib.games import (
    ALL_TOOLS, GAMES, LEGACY_DEFAULT_SIGNAL, TOOL_GLASS, TOOL_HUNTS, UNSET_HINT,
    canonical_game_key, game as game_info,
)

def _throw_context(hunt, species_info: dict):
    """The non-turn context the conditional balls need, assembled from the hunt.

    Three of the four pieces come from configuration or species data. The fourth, **time of day,
    is derived rather than asked for**: the in-game hour is bits 16-23 of the key seed, so a hunt
    that knows which seed it is aiming at already knows whether the Dusk Ball's night applies.
    Asking the player for it would be asking them to restate something the seed already says --
    and to get it wrong independently.
    """
    from claytonlib.battle.balls import ThrowContext
    from claytonlib.safari_encounters import time_of_day

    hour = None if hunt.key_seed is None else (int(hunt.key_seed) >> 16) & 0xFF
    # An hour byte above 23 means no clock can produce the seed at all (Glass refuses it for the
    # same reason); treat the bucket as unknown rather than inventing one.
    bucket = time_of_day(hour) if hour is not None and hour <= 23 else ""
    return ThrowContext(
        terrain=hunt.terrain,
        time_of_day=bucket,
        target_types=tuple(species_info.get("types") or ()),
        target_level=int(hunt.target.level or 1),
        target_base_speed=int((species_info.get("base_stats") or {}).get("spe", 0)),
        registered=bool(hunt.target_registered),
    )


def _seed_a_signal(profile) -> dict:
    """How this profile's game identifies Seed A, as data the page can render.

    Two shapes exist and the page has to render whichever one applies: HGSS narrows by roamer
    routes and Elm calls, Platinum by Poketch coin flips, with chatot pitch for the advance
    frame. Returning a descriptor rather than a boolean keeps the branch in one place -- the
    page asks what to draw instead of asking which game it is.
    """
    found = game_info(profile.game)
    if found is None:
        # No game set: every profile that predates the field is HGSS, and both HGSS versions
        # identify Seed A identically, so the signal is well-defined even when the version is
        # not. The page shows `unset_hint` alongside, so this is a default rather than a guess
        # the player cannot see.
        return {"kind": LEGACY_DEFAULT_SIGNAL, "label": "roamer routes and Elm calls",
                "bulk_action": "Chatot flip", "bulk_advances": 2, "margin_action": "Elm call",
                "hygiene_note": "", "unset_hint": UNSET_HINT}
    flips = found.uses_coin_flips
    return {
        "kind": found.seed_a_signal,
        "label": "Poketch coin flips" if flips else "roamer routes and Elm calls",
        "bulk_action": found.bulk_action,
        "bulk_advances": found.bulk_advances,
        "margin_action": found.margin_action,
        # The one thing a Platinum player must do that an HGSS player need not, and it is
        # invisible when forgotten: a randomly-moving NPC spends an advance of its own, and the
        # in-game menu freezes them. The Journal lives in that menu anyway.
        "hygiene_note": (
            "Press X to open the in-game menu the moment you enter the world -- it freezes the "
            "NPCs, which would otherwise spend advances of their own. The Journal is in there "
            "too. Your Chatot also needs a recorded cry, or playing it spends no advance at all."
        ) if flips else "",
        "unset_hint": "",
    }


_PROFILES = "profiles"
_EXPEDITIONS = "expeditions"
_RUNS = "runs"
_CHARTS = "charts"
_TARGETS = "targets"
_CALIBRATION_MODELS = "calibration_models"
_HUNTS = "hunts"
_SEEDS = "seeds"



def _configured_pp(pokemon, slot: int, move_name: str) -> int:
    """Max PP for the 0-based `slot`, which is also its PP at battle start.

    The configured value IS the maximum -- PP Ups are already in it -- so a battle begins with
    every move full. When it was never recorded, fall back to the move's own base PP rather than
    to zero: zero makes the move unusable, which silently removed every move from the run's
    action list and left only "use an item" and "switch". It is only a warning on the party
    Pokemon, so the hunt still reported itself ready.

    Through `pp_for_slot`, which owns the fact that `max_pp` is keyed by 1-based move NUMBER.
    This used to index it with the 0-based slot directly, so every move got the previous move's
    PP and move 1 fell through to the base-PP fallback above -- a fallback that then looked like
    it was working.
    """
    recorded = pokemon.pp_for_slot(slot)
    if recorded is not None:
        return recorded
    from claytonlib.moves import resolve_move
    move = resolve_move(move_name)
    return move.pp if move else 0


class Facade:
    def __init__(self, store: Store | None = None):
        self._store = store or FileStore()
        from app.metronome_session import SessionRegistry
        self._sessions = SessionRegistry()
        from app.progress_session import ProgressRegistry
        from app.hunt_session import HuntSessionRegistry
        self._chart_sessions = ProgressRegistry()
        self._hunt_sessions = HuntSessionRegistry()

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
                "game": p.game,
                "game_name": p.game_name,
                "version": p.game_name,
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
        for pokemon_dict, pokemon in zip(doc.get("party", []), p.party):
            errors = pokemon.hard_errors()
            # Mirrors the metronome-user split: `warnings` is advisory, `hard_errors` is what
            # stops the Pokemon being taken into a Hunt (a half-entered one is still saveable).
            pokemon_dict["warnings"] = pokemon.warnings()
            pokemon_dict["hard_errors"] = errors
            pokemon_dict["is_hunt_ready"] = not errors
        doc["has_valid_metronome_user"] = p.has_valid_metronome_user
        doc["game_name"] = p.game_name
        # Why each tool can't run, per tool, so a page can refuse with a sentence instead of
        # re-deriving the rule. Empty string == this tool works.
        doc["tool_refusals"] = {tool: p.tool_refusal(tool) for tool in ALL_TOOLS}
        doc["seed_a_signal"] = _seed_a_signal(p)
        return doc

    def list_games(self) -> list[dict]:
        """Every game the build knows, for the profile form's picker.

        Unsupported games are listed rather than hidden, with their reason attached: a player who
        owns Diamond should see it and be told why it is not ready, not wonder whether the app has
        heard of it.
        """
        return [{
            "key": g.key,
            "name": g.name,
            "is_supported": g.is_supported,
            "unsupported_reason": g.unsupported_reason,
            "tools": sorted(g.tools),
            "seed_a_signal": g.seed_a_signal,
            "bulk_action": g.bulk_action,
            "bulk_advances": g.bulk_advances,
            "margin_action": g.margin_action,
        } for g in GAMES]

    def create_profile(self, fields: dict) -> dict:
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a profile needs a name")
        p = Profile(
            name=name,
            trainer_name=fields.get("trainer_name", ""),
            # Accepts the key or a display name (and the old "version" spelling), so the UI can
            # send either and an import written by an older build still resolves.
            game=canonical_game_key(fields.get("game") or fields.get("version") or ""),
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
        p.game = canonical_game_key(fields.get("game") or fields.get("version") or "")
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

    # -- party pokemon (Battle Compass) ------------------------------------

    def add_party_pokemon(self, profile_id: str, fields: dict) -> dict:
        """Add a party Pokemon to the profile; returns the profile plus its validation."""
        p = self._load_profile(profile_id)
        pokemon = p.add_party_pokemon(**self._party_fields(fields))
        self._save_profile(p)
        return {
            "profile": self.get_profile(p.id),
            "pokemon_id": pokemon.id,
            "warnings": pokemon.warnings(),
            "hard_errors": pokemon.hard_errors(),
        }

    def update_party_pokemon(self, profile_id: str, pokemon_id: int, fields: dict) -> dict:
        """Party Pokemon are mutable, unlike metronome users — stats change as they level."""
        p = self._load_profile(profile_id)
        updates = self._party_fields(fields)
        if not fields.get("name"):
            # An edit form that doesn't send a name shouldn't blank the existing one.
            updates.pop("name")
        pokemon = p.update_party_pokemon(int(pokemon_id), **updates)
        self._save_profile(p)
        return {
            "profile": self.get_profile(p.id),
            "pokemon_id": pokemon.id,
            "warnings": pokemon.warnings(),
            "hard_errors": pokemon.hard_errors(),
        }

    def remove_party_pokemon(self, profile_id: str, pokemon_id: int) -> dict:
        """Remove it. Hunts referencing its id report it as no longer on the profile."""
        p = self._load_profile(profile_id)
        removed = p.remove_party_pokemon(int(pokemon_id))
        self._save_profile(p)
        return {"profile": self.get_profile(p.id), "removed": removed.to_dict(),
                "affected_hunts": [h["name"] for h in self.list_hunts(profile_id)
                                   if removed.id in h["party_pokemon_ids"]]}

    @staticmethod
    def _party_fields(fields: dict) -> dict:
        """Only the fields a party Pokemon actually has, so a stray key fails loudly."""
        out = {
            "name": (fields.get("name") or "").strip(),
            "species": fields.get("species", ""),
            "level": fields.get("level"),
            "ability": fields.get("ability"),
            "gender": fields.get("gender"),
            "stats": dict(fields.get("stats", {})),
            "moveset": list(fields.get("moveset", [])),
            "max_pp": dict(fields.get("max_pp", {})),
        }
        return out

    # -- hunts (Battle Compass) --------------------------------------------

    def list_hunts(self, profile_id: str | None = None) -> list[dict]:
        out = []
        for hid in self._store.list_ids(_HUNTS):
            doc = self._store.read(_HUNTS, hid)
            if doc is None:
                continue
            h = Hunt.from_dict(doc)
            if profile_id is not None and h.profile_id != profile_id:
                continue
            out.append({
                "id": h.id,
                "name": h.name,
                "profile_id": h.profile_id,
                "target": h.target.species,
                "capture_ball": h.capture_ball,
                "completed": h.completed,
                "party_pokemon_ids": [s.pokemon_id for s in h.party],
            })
        out.sort(key=lambda d: (d["completed"], d["name"].lower()))
        return out

    def get_hunt(self, hunt_id: str) -> dict:
        return self._load_hunt(hunt_id).to_dict()

    def _load_hunt(self, hunt_id: str) -> Hunt:
        doc = self._store.read(_HUNTS, hunt_id)
        if doc is None:
            raise ValueError(f"no hunt with id {hunt_id}")
        return Hunt.from_dict(doc)

    def _assert_hunt_name_free(self, name: str, except_id: str | None = None) -> None:
        """Hunt names are unique globally, for the same reason expedition names are."""
        for hid in self._store.list_ids(_HUNTS):
            doc = self._store.read(_HUNTS, hid)
            if doc is None or doc.get("id") == except_id:
                continue
            if (doc.get("name") or "").strip().lower() == name.lower():
                owner = (self._store.read(_PROFILES, doc.get("profile_id")) or {}).get("name")
                where = f" (in profile \"{owner}\")" if owner else ""
                raise ValueError(
                    f"A hunt named \"{doc['name']}\"{where} already exists. "
                    "Hunt names have to be unique across every profile — pick another.")

    @staticmethod
    def _sync_encounter_kind(hunt, profile) -> None:
        """Set `hunt.encounter_kind` from the encounter row, every time the hunt is written.

        DERIVED and not configured: a player cannot make Cresselia static or Suicune roam, so
        offering the choice would only let them get it wrong. It is still stored rather than looked
        up on read, so a saved hunt and the run records under it keep agreeing about which kind of
        run they describe.

        An unknown species leaves the kind alone instead of defaulting it: a half-configured hunt
        on its way to a species is not a static hunt, it is a hunt with no target yet, and
        stamping one in would have to be undone by the next save.
        """
        from claytonlib.battle_compass.targets import is_roamer

        if not hunt.target.species:
            return
        try:
            roamer = is_roamer(hunt.target.species, profile.game if profile else "")
        except (KeyError, ValueError):
            return
        hunt.encounter_kind = ENCOUNTER_ROAMER if roamer else ENCOUNTER_STATIC

    def create_hunt(self, fields: dict) -> dict:
        name = (fields.get("name") or "").strip()
        if not name:
            raise ValueError("a hunt needs a name")
        profile_id = fields.get("profile_id")
        if not profile_id:
            raise ValueError("a hunt must reference a profile")
        profile = self._load_profile(profile_id)
        # The same gate Glass applies, in the same place and for the same reason: refused at the
        # facade so it holds however a hunt is created, and with the game's own sentence.
        refusal = profile.tool_refusal(TOOL_HUNTS)
        if refusal:
            raise ValueError(refusal)
        self._assert_hunt_name_free(name)
        h = Hunt.from_dict({**fields, "name": name})
        self._sync_encounter_kind(h, profile)
        self._store.write(_HUNTS, h.id, h.to_dict())
        return h.to_dict()

    def save_hunt(self, hunt: dict) -> dict:
        """Upsert an existing hunt from its full document."""
        if not hunt.get("id"):
            raise ValueError("save_hunt needs a hunt id (use create_hunt for new)")
        h = Hunt.from_dict(hunt)
        profile = self._load_profile(h.profile_id)
        self._assert_hunt_name_free(h.name.strip(), except_id=h.id)
        # Re-derived on every save, so changing the target species changes the kind with it --
        # which is what keeps the two from ever disagreeing after an edit.
        self._sync_encounter_kind(h, profile)
        self._store.write(_HUNTS, h.id, h.to_dict())
        return h.to_dict()

    def set_hunt_completed(self, hunt_id: str, completed: bool) -> dict:
        h = self._load_hunt(hunt_id)
        h.completed = bool(completed)
        self._store.write(_HUNTS, h.id, h.to_dict())
        return h.to_dict()

    def delete_hunt(self, hunt_id: str) -> bool:
        """Deletes the hunt only. Party Pokemon live on the PROFILE and are untouched."""
        return self._store.delete(_HUNTS, hunt_id)

    # -- Battle Compass: the live run --------------------------------------

    def _hunt_battlers(self, hunt, profile, spread: dict | None = None):
        """(ours, target, bench) as ``battle_compass`` Battlers, from stored configuration.

        Our side's stats are entered off the summary screen; the target's are derived from the
        IVs and nature the RNG manipulation fixed (sec 15.4.1). The first party slot is the
        active Pokemon and the rest are the bench it can switch to -- a Phase 1 action, which is
        why the solver never weighs it.

        `spread` overrides the target's nature and IVs for ONE run, as ``{"nature", "ivs"}``.
        It exists because the configured spread is the one the KEY SEED would have produced, and
        a run that identifies a different Seed A is facing a different Suicune. The override is
        deliberately not written back to ``hunt.target``: that record is the plan, and
        overwriting it would lose the spread every future run is aimed at.
        """
        from claytonlib.battle.stats import derive_species_stats, species as species_data
        from claytonlib.battle_compass.state import Battler

        if not hunt.party:
            raise ValueError("this hunt has no party configured")

        def battler_for(pokemon, held_item="", party_slot=0):
            moves = tuple(pokemon.moveset)
            return Battler(
                # The STABLE slot in the hunt's party, which is what the S/X/R tokens name and
                # what the player reads off the game's party screen. Taken from the position in
                # `hunt.party` rather than from the bench, so a party member the profile has
                # since lost leaves a gap instead of shifting everyone after it.
                party_slot=party_slot,
                name=pokemon.name, level=pokemon.level or 1,
                types=(tuple(species_data(pokemon.species)["types"])
                       if pokemon.species else ("Normal",)),
                stats=dict(pokemon.stats), moves=moves,
                pp=tuple(_configured_pp(pokemon, i, name)
                         for i, name in enumerate(moves)),
                # Both feed the damage model: Technician raises base power, and a type-enhancing
                # held item raises it again. Held items are per HUNT, so they come off the slot.
                ability=pokemon.ability or "", held_item=held_item)

        members = [(profile.get_party_pokemon(slot.pokemon_id), slot.held_item)
                   for slot in hunt.party]
        if members[0][0] is None:
            raise ValueError("the hunt's lead Pokemon is no longer on the profile")
        ours = battler_for(*members[0], party_slot=1)
        bench = tuple(battler_for(m, item, party_slot=i + 2)
                      for i, (m, item) in enumerate(members[1:]) if m is not None)

        from claytonlib.battle_compass.targets import moveset, stats_key, target_ability
        from claytonlib.moves import resolve_move
        target_moves = moveset(hunt.target.species, profile.game)
        # Which base-stats row the target's numbers come from. The same as the species for every
        # target met once; for a forme-split one it is the forme's row, which is the whole reason
        # Giratina needed two encounters -- Origin is 120/100/120/100 against Altered's
        # 100/120/100/120 (clayton-6xu.3.4).
        stats_row = stats_key(hunt.target.species, profile.game)
        nature = (spread or {}).get("nature") or hunt.target.nature
        ivs = (spread or {}).get("ivs") or dict(hunt.target.ivs)
        target = Battler(
            name=hunt.target.species.title(), level=hunt.target.level,
            types=tuple(species_data(stats_row)["types"]),
            stats=derive_species_stats(stats_row, hunt.target.level, nature, ivs=dict(ivs)),
            moves=target_moves,
            pp=tuple(resolve_move(name).pp for name in target_moves),
            # Off the encounter row, like the HuntConfig flags. The target's Battler used to
            # carry no ability at all, which was invisible while the only abilities in play were
            # read from HuntConfig -- and would have gone on being invisible right up to a forme
            # whose ability differs from its species' (clayton-957.35.4).
            ability=target_ability(hunt.target.species, profile.game))
        target = self._apply_opening_state(hunt, target)
        return ours, target, bench

    @staticmethod
    def _apply_opening_state(hunt, target):
        """The HP and status a ROAMER walks in with, off the hunt's configuration.

        A static encounter is generated when the battle starts, so it always opens at full HP and
        unstatused and this is a no-op for it. A roamer's HP and status come out of the save
        (notes/roamers.md sec 3), which is the feature's single biggest advantage -- the chip phase
        can be done in throwaway encounters and the seed-hunting one can open at 1 HP asleep -- and
        the simulation has to be told, because every prediction from turn 1 reads them.

        **An unknown sleep counter becomes the ROM's maximum, not zero.** The duration was rolled
        in a prep encounter the player could not observe (clayton-957.35.21), and of the two
        guesses available, zero is the one we can be certain is wrong: it wakes the target on its
        very first turn. The maximum is at least reachable, and a run whose target wakes earlier
        than predicted diverges loudly on the turn it happens rather than quietly from turn 1.
        """
        from claytonlib.battle_compass.sim import SLEEP_DURATION_MIN, SLEEP_DURATION_SPAN
        from claytonlib.battle_compass.state import Status

        if not hunt.is_roamer:
            return target
        if hunt.opening_hp is not None:
            target = target.with_hp(min(hunt.opening_hp, target.max_hp))
        if hunt.opening_status:
            status = Status(hunt.opening_status)
            turns = hunt.opening_sleep_turns or (SLEEP_DURATION_MIN + SLEEP_DURATION_SPAN - 1)
            target = target.with_status(status, sleep_turns=turns)
        return target

    @staticmethod
    def _target_derived_speed(hunt) -> int | None:
        """The target's Speed from its configured spread, or None if it cannot be derived yet.

        None rather than zero or a guess: the trap check needs to tell "this party cannot hold
        it" from "we cannot tell yet", and a roamer hunt sits in the second state far more often
        than a static one -- its spread was rolled when the roam began and no seed names it
        (notes/roamers.md sec 7).
        """
        from claytonlib.battle.stats import derive_species_stats

        if hunt.target.spread_errors():
            return None
        try:
            return int(derive_species_stats(hunt.target.species, hunt.target.level,
                                            hunt.target.nature, ivs=dict(hunt.target.ivs))["spe"])
        except (KeyError, ValueError):
            return None

    @staticmethod
    def _target_speed_stages(target) -> tuple[int, ...]:
        """Speed stages this target can reach, for the speed-tie checks.

        Read off its moveset: only a move that raises its own Speed puts anything but 0 in
        reach, and among the configured encounters that is Ancient Power. `(0,)` for everything
        else, which keeps the check table short for targets that cannot boost.
        """
        from claytonlib.battle_compass.sim import EFFECT_ALL_STATS_UP
        from claytonlib.battle_compass.targets import moveset, supported
        from claytonlib.moves import resolve_move

        key = (target.species or "").strip().lower().replace(" ", "-")
        if key not in supported():
            return (0,)
        for name in moveset(key):
            move = resolve_move(name)
            if move is not None and move.effect == EFFECT_ALL_STATS_UP:
                return tuple(range(7))
        return (0,)

    @staticmethod
    def _target_ability_probe(hunt, profile):
        """A `Battler` carrying the target's name, ability and TYPES, or None if it has no row yet.

        Deliberately minimal. Everything that asks "what would this target's ability do to our
        move" reads those fields and nothing else, and building the real Battler needs a level, a
        nature and a full IV spread -- none of which a half-configured hunt has. So the advice is
        available from the moment a species is typed.

        **The types used to be hardcoded to Normal.** That is harmless today -- the one caller
        (`sim.unsupported_our_moves` -> `unselectable_reason`) reads the ability alone, for Flash
        Fire -- so this is a correction rather than a bug fix, and it is worth making anyway: a
        probe that ASSERTS a typing it does not have is a trap for the next question asked of it,
        and "is this move type-immune" is now a question the codebase asks elsewhere
        (`sim.deals_nothing`). The real types are one lookup away, off the same `stats_key` row
        the stats come from, so a forme-split target answers for the forme it is met as.

        Note that `chip_warnings` does NOT read them from here -- it resolves the species itself,
        because it needs the Pokedex name for its messages too.
        """
        from claytonlib.battle_compass.state import Battler
        from claytonlib.battle_compass.targets import target_ability, target_types

        species_name = (hunt.target.species or "").strip()
        if not species_name:
            return None
        game = profile.game if profile else ""
        try:
            ability = target_ability(species_name, game)
            types = target_types(species_name, game)
        except KeyError:
            return None
        return Battler(name=species_name, level=1, types=types, stats={"hp": 1},
                       ability=ability)

    @staticmethod
    def _target_can_paralyze_us(target) -> bool:
        """Whether this target has any way to paralyze our Pokemon.

        Gates the half of the speed-check table that assumes OUR paralysis. It quarters our
        Speed and really can flip an order that looked safe -- but only if the target can
        actually inflict it, and `include_our_paralysis` defaulted on with nothing deriving it.
        Against Lugia (no paralysing move, Pressure rather than Static) every one of those rows
        was a state the player could not reach (clayton-36b).

        Unknown species -> True, the same direction `can_inflict` errs in: a spurious row costs a
        line of advice and a missing one costs an unmodelled desync.
        """
        from claytonlib.battle.stats import abilities
        from claytonlib.battle_compass.sim import can_inflict
        from claytonlib.battle_compass.state import Battler, Status
        from claytonlib.battle_compass.targets import moveset, supported

        key = (target.species or "").strip().lower().replace(" ", "-")
        if key not in supported():
            return True
        try:
            ability = (abilities(key) or ("",))[0]
        except KeyError:
            ability = ""
        moves = moveset(key)
        probe = Battler(name=key, level=1, types=("Normal",), stats={},
                        moves=moves, pp=(1,) * len(moves), ability=ability)
        return can_inflict(probe, Status.PARALYSIS)

    @staticmethod
    def _party_can_paralyze(hunt, profile) -> bool:
        """Whether ANY configured party member can paralyze the target.

        Gates the paralyzed-target half of `speed_move_ties`. The mirror of
        `_target_can_paralyze_us`, and it errs the same way for the same reason: an unknown move
        or ability is treated as capable, because a spurious warning costs a line and a missing
        one costs an unmodelled desync.

        **"Any", not "another".** The ask was phrased as another party member, and in practice
        the distinction does not exist: a Pokemon holding both Agility and Thunder Wave can use
        them on successive turns and reach exactly the same tie. Reading it strictly would hide a
        reachable one.
        """
        from claytonlib.battle_compass.sim import can_inflict
        from claytonlib.battle_compass.state import Battler, Status
        from claytonlib.moves import resolve_move

        for slot in hunt.party:
            pokemon = profile.get_party_pokemon(slot.pokemon_id)
            if pokemon is None:
                continue
            moves = tuple(m.name for m in
                          (resolve_move(name) for name in pokemon.moveset) if m)
            probe = Battler(name=pokemon.name or "?", level=1, types=("Normal",), stats={},
                            moves=moves, pp=(1,) * len(moves),
                            ability=(pokemon.ability or ""))
            if can_inflict(probe, Status.PARALYSIS):
                return True
        return False

    def hunt_run_setup(self, hunt_id: str) -> dict:
        """What the run page needs to open, before any seed has been looked for.

        Opening the page must not depend on the targeting being right. Every other compass works
        this way -- you get the page, then search for candidates on it, then adjust and search
        again -- and Battle Compass needs it more, not less: the seed is found *during* the run.
        """
        from claytonlib.battle.stats import STAT_KEYS, format_iv_spread, nature_names

        h = self._load_hunt(hunt_id)
        profile = self._load_profile(h.profile_id)
        return {
            "hunt_id": h.id,
            "name": h.name,
            "hard_errors": h.hard_errors(profile),
            "targeting": {
                "key_seed": None if h.key_seed is None else f"{h.key_seed:#010x}",
                "initial_time": h.initial_time,
                "vector_ms": h.vector_ms,
                "stopwatch_ms": h.stopwatch_ms,
                "delay_window": h.delay_window,
                "seconds_window": h.seconds_window,
            },
            # Which kind of run this is, so the page can draw the right one rather than
            # branching on the species. A roamer run SKIPS the Seed A step entirely -- there is
            # nothing to identify and no frame to route to, because the target's spread, HP and
            # status all come out of the save (notes/roamers.md sec 1) -- and asks for a
            # stopwatch reading where a static run asks for a Vector ms.
            "encounter_kind": h.encounter_kind,
            "skips_seed_a": h.is_roamer,
            # What the target walks in with, for a roamer: the prep encounter's chip and status
            # come out of the save, so the page shows them and the run is simulated from them
            # (notes/roamers.md sec 3). All three are None/""/0 on a static hunt, which is the
            # honest answer there -- a static target is generated when the battle starts.
            "opening": {
                "hp": h.opening_hp,
                "status": h.opening_status,
                "sleep_turns": h.opening_sleep_turns,
            },
            "capture_ball": h.capture_ball,
            "calibration_model": self.calibration_model_summary(h.profile_id),
            # The advance frame the hunt is planned to encounter on. Only meaningful when the
            # run actually lands on the key seed -- on any other Seed A it was computed for a
            # different stream -- so the page uses it only there, to plan the chatot-flip route.
            "key_seed_advances": h.key_seed_advances,
            # Elm calls to leave after the chatot flips. A Hunt has no preferences of its own
            # (only an Expedition does), so this is the shared default rather than an invented
            # per-hunt setting.
            "elm_margin": _default_preferences()["elm_calls_after_flips"],
            # Seed A comes first in a real run, and it needs the key seed and initial time that
            # are already above. What it adds is the roamer/Elm search defaults, remembered per
            # hunt so a repeat run does not retype them.
            "seed_a_defaults": dict(h.seed_a_defaults or {}),
            # Which Seed A signal this hunt's game offers -- roamers + Elm, or coin flips with a
            # chatot-pitch margin. The page asks the descriptor what to draw rather than asking
            # which game it is in.
            "seed_a_signal": _seed_a_signal(profile),
            # The four lines the game prints after a throw, in THIS game's wording -- Platinum's
            # three-shake line opens "Shoot!" where HGSS's opens "Gah!". Sent as data for the
            # same reason `seed_a_signal` is: the page renders what it is given instead of
            # branching on which game it is in. The interview asks the player to pick the line
            # they saw, and the shake count that comes back constrains the seed -- so a ladder
            # that does not match the screen is not cosmetic.
            "shake_messages": list(shake_messages(profile.game)),
            # The advance frame a freshly loaded save sits on at this venue. In Platinum this is
            # the anchor for counting advances, since there is nothing to identify the frame FROM
            # (notes/platinum.md section 3.4).
            "start_frame": h.start_frame,
            # Whether this profile's game can run a hunt at all. Diamond and Pearl cannot.
            "refusal": profile.tool_refusal(TOOL_HUNTS),
            # The spread the hunt is PLANNED around -- the one the key seed produces. Shown as
            # the prefill for the spread step, and the thing a different Seed A replaces.
            "configured_spread": {
                "nature": h.target.nature,
                "ivs": dict(h.target.ivs),
                "text": (format_iv_spread(h.target.ivs)
                         if all(isinstance(h.target.ivs.get(k), int) for k in STAT_KEYS)
                         else ""),
            },
            "natures": list(nature_names()),
            # Who the hunt is actually for. The page used to say "Suicune" in every sentence
            # about the target, which was true of the v1 fixture and a lie on every hunt since.
            # Name rather than species so the page needs no title-casing of its own, and both so
            # it can still match against configuration.
            "target": {
                "species": h.target.species,
                "name": h.target.species.title() if h.target.species else "",
                "level": h.target.level,
            },
        }

    @staticmethod
    def _target_spread_from_params(params: dict | None) -> dict | None:
        """``{"nature", "ivs"}`` for this run, or None to use the hunt's configured spread.

        Both fields must arrive together. A nature without IVs (or the reverse) is a half-entered
        form rather than a partial override, and silently filling the other half from the
        configured spread would mix a nature from one Suicune with IVs from another -- stats that
        belong to no Pokemon at all, and no error anywhere.
        """
        from claytonlib.battle.stats import parse_iv_spread

        params = params or {}
        nature = (params.get("target_nature") or "").strip()
        raw_ivs = params.get("target_ivs")
        text = raw_ivs if isinstance(raw_ivs, str) else ""
        if not nature and not text.strip() and not isinstance(raw_ivs, dict):
            return None
        if isinstance(raw_ivs, dict):
            ivs = dict(raw_ivs)
        else:
            if not text.strip():
                raise ValueError("a target nature was given without IVs; enter both or neither")
            ivs = parse_iv_spread(text)
        if not nature:
            raise ValueError("target IVs were given without a nature; enter both or neither")
        return {"nature": nature, "ivs": ivs}

    def hunt_save_seed_a_defaults(self, hunt_id: str, defaults: dict) -> dict:
        """Remember the roamer/Elm search inputs for this hunt's next run.

        The roamers' starting positions are a property of the save file, not of the run, so
        retyping them every attempt is pure friction -- the same reason Safari Compass keeps
        them per expedition. Stored on the hunt rather than returned, because the point is for
        them to survive the app closing.
        """
        h = self._load_hunt(hunt_id)
        h.seed_a_defaults = {**(h.seed_a_defaults or {}), **(defaults or {})}
        self._store.write(_HUNTS, h.id, h.to_dict())
        return dict(h.seed_a_defaults)

    def hunt_parse_target_spread(self, hunt_id: str, nature: str, ivs_text: str) -> dict:
        """Validate a typed spread and show what it derives, without starting anything.

        The derived stats come back deliberately: they are the only part the player can check
        against something they can see. A transposed pair of IVs is invisible in the spread
        itself and obvious the moment the HP it implies disagrees with the HP bar.
        """
        from claytonlib.battle.stats import derive_species_stats, nature_names

        h = self._load_hunt(hunt_id)
        try:
            spread = self._target_spread_from_params(
                {"target_nature": nature, "target_ivs": ivs_text})
        except ValueError as exc:
            return {"ok": False, "problem": str(exc), "natures": list(nature_names())}
        if spread is None:
            return {"ok": False, "problem": "enter a nature and six IVs",
                    "natures": list(nature_names())}
        if spread["nature"] not in nature_names():
            return {"ok": False, "problem": f"unknown nature {spread['nature']!r}",
                    "natures": list(nature_names())}
        if not h.target.species or h.target.level is None:
            return {"ok": False, "problem": "configure the target's species and level first",
                    "natures": list(nature_names())}
        stats = derive_species_stats(h.target.species, h.target.level,
                                     spread["nature"], ivs=spread["ivs"])
        return {"ok": True, "problem": None, "natures": list(nature_names()),
                "nature": spread["nature"], "ivs": spread["ivs"], "stats": stats}

    def _centring_model(self, hunt, *, elapsed_ms: float | None = None):
        """What centres this hunt's candidate window, and the sizes it suggests.

        Returns ``(model, suggested_frame_window, suggested_second_window)``, where the two
        suggestions are None for a static hunt -- its windows are the player's own settings, and
        a calibrated countdown has no business proposing them.

        **A roamer gets a `StopwatchVector`, never the calibration model.** The model maps a
        COMMANDED countdown through a fitted load path whose intercept belongs to that workflow;
        a roamer encounter is observed, so the reading is a measurement and pushing it through
        that intercept would add a constant to a number that already contains everything
        (notes/roamers.md sec 6). The two objects share exactly the two methods
        `candidates.generate` calls, which is why nothing downstream branches.

        Returns ``(None, ...)`` when the profile has no calibration model at all, which both
        callers already report -- a roamer still needs one, for the load press's landing spread.
        """
        from claytonlib.stopwatch import StopwatchVector

        models = self._resolve_calibration_models(hunt.profile_id)
        model = models.get("linear") or next(iter(models.values()), None)
        if model is None or not hunt.is_roamer:
            return model, None, None
        vector = StopwatchVector.from_calibration(model)
        if elapsed_ms is None:
            return vector, None, None
        return (vector, vector.suggest_frame_window(elapsed_ms),
                vector.suggest_second_window(elapsed_ms))

    def hunt_candidates(self, hunt_id: str, params: dict | None = None) -> dict:
        """Build the candidate window, without starting a run.

        Never raises for an empty result: an empty window is a normal thing to see on the way to
        a good one, and it is the page's job to explain it and let the player try again.
        """
        import datetime as dt

        from claytonlib.battle_compass.candidates import generate

        h = self._load_hunt(hunt_id)
        params = params or {}
        # A field PRESENT in params is used as given, blank included -- the page sends every
        # field, so a blank one means the player cleared it and should be reported as missing,
        # not silently replaced by the stored value it was meant to override. A field absent
        # from params falls back to the hunt.
        key_seed = params["key_seed"] if "key_seed" in params else h.key_seed
        if isinstance(key_seed, str):
            key_seed = int(key_seed, 0) if key_seed.strip() else None
        initial_time = (params["initial_time"] if "initial_time" in params
                        else h.initial_time) or ""
        # A roamer is centred on a STOPWATCH READING and a static hunt on a commanded Vector ms.
        # Read from the field that matches the kind, never from whichever happens to be filled
        # in: the two are different measurements, and confusing them is a silent error of
        # hundreds of frames rather than a visible one.
        vector_key = "stopwatch_ms" if h.is_roamer else "vector_ms"
        vector_ms = params[vector_key] if vector_key in params else h.centring_ms
        if isinstance(vector_ms, str):
            vector_ms = float(vector_ms) if vector_ms.strip() else None
        label = "stopwatch reading" if h.is_roamer else "vector ms"

        missing = [name for name, value in (("key seed", key_seed),
                                            ("initial time", initial_time),
                                            (label, vector_ms)) if value in (None, "")]
        if missing:
            return {"ok": False, "candidates": 0,
                    "problem": f"Seed targeting is incomplete: no {', no '.join(missing)}."}

        model, suggested_frames, suggested_seconds = self._centring_model(
            h, elapsed_ms=float(vector_ms))
        if model is None:
            return {"ok": False, "candidates": 0,
                    "problem": "This profile has no calibration model."}

        # The suggestions are the DEFAULT for a roamer, not an override: a player who has set a
        # window keeps it. A static hunt has no suggestions at all, so this reduces to the
        # stored settings exactly as before.
        frame_window = int(params.get("delay_window")
                           or h.delay_window or suggested_frames or 0)
        second_window = int(params.get("seconds_window")
                            or h.seconds_window or suggested_seconds or 0)

        window = generate(
            model, key_seed=int(key_seed),
            initial_time=dt.datetime.fromisoformat(initial_time),
            vector_ms=float(vector_ms),
            frame_window=frame_window, second_window=second_window)
        return {
            "ok": bool(len(window)),
            "candidates": len(window),
            "problem": window.why_empty(),
            "frame_centre": window.frame_centre,
            "second_centre": window.second_centre,
            "base_delay": window.base_delay,
            "skipped_below_base_delay": window.skipped_below_base_delay,
            "frame_window": window.frame_window,
            "second_window": window.second_window,
            "encounter_kind": h.encounter_kind,
            # What the stopwatch's own spread would have asked for, so the page can offer it
            # rather than leaving the player to guess at a window ten times a static hunt's.
            # None on a static hunt, where the windows are the player's settings and nothing
            # else.
            "suggested_frame_window": suggested_frames,
            "suggested_second_window": suggested_seconds,
            "preview": [{"seed": f"{c.seed:#010x}", "frame": c.frame, "second": c.second}
                        for c in window.candidates[:12]],
        }

    def hunt_session_start(self, hunt_id: str, params: dict | None = None) -> dict:
        """Open a run against the window `params` describes. Returns (session_id, snapshot).

        `params` overrides the hunt's stored targeting and is saved back to it, so the window the
        player actually searched is the one the hunt remembers next time.

        Still refuses on ``hard_errors``: those are things the *simulation* needs exactly, and
        starting without them would desynchronise rather than degrade. An empty window is not one
        of them -- it comes back as a problem to fix on the page.
        """
        import datetime as dt

        from claytonlib.battle_compass.candidates import generate
        from claytonlib.battle_compass.hunt_session import HuntSession
        from claytonlib.battle.stats import species as species_data
        from claytonlib.battle_compass.sim import ABILITY_BAD_DREAMS, HuntConfig
        from claytonlib.battle_compass.targets import stats_key, target_ability

        h = self._load_hunt(hunt_id)
        profile = self._load_profile(h.profile_id)
        errors = h.hard_errors(profile)
        if errors:
            raise ValueError("this hunt is not ready: " + "; ".join(errors))

        params = params or {}
        if params:
            self._apply_hunt_targeting(h, params)
            self._store.write(_HUNTS, h.id, h.to_dict())

        probe = self.hunt_candidates(hunt_id)
        if not probe["ok"]:
            return {"session_id": None, "hunt_id": hunt_id, "window": probe,
                    "problem": probe["problem"]}

        # Validated BEFORE the window is built, so a mistyped spread is reported as a spread
        # problem rather than surfacing later as a battle that does not match.
        spread = self._target_spread_from_params(params)
        ours, target, bench = self._hunt_battlers(h, profile, spread)
        # Rebuilt rather than taken from `probe`, which returns counts and not the window itself
        # -- and through the same `_centring_model` it used, so the session can never run against
        # a window centred differently from the one the page just priced.
        centring_ms = float(h.centring_ms)
        model, suggested_frames, suggested_seconds = self._centring_model(
            h, elapsed_ms=centring_ms)
        window = generate(
            model, key_seed=int(h.key_seed),
            initial_time=dt.datetime.fromisoformat(h.initial_time),
            vector_ms=centring_ms,
            frame_window=h.delay_window or suggested_frames or 0,
            second_window=h.seconds_window or suggested_seconds or 0)

        # The forme's row where the encounter names one: the catch rate agrees between Giratina's
        # two formes but the types and the base Speed a conditional ball reads do not have to.
        info = species_data(stats_key(h.target.species, profile.game))
        # The ability comes off the ENCOUNTER, not the species. For every target met once the two
        # agree, and for a forme-split one they do not: Giratina is Pressure in Turnback Cave and
        # Levitate in the Distortion World, so asking the species would be confidently wrong for
        # one of the two fights (clayton-957.35.4).
        ability = target_ability(h.target.species, profile.game).strip().lower()
        config = HuntConfig(
            target_catch_rate=int(info["catch_rate"]),
            # The ball by NAME, so `claytonlib.battle.balls` decides what it is worth rather than
            # the facade guessing. This used to set only `fast_ball_matched`, which left
            # `capture_ball_multiplier` unassigned and simulated every ball as x1 -- harmless
            # while every HGSS target/ball pairing really was x1, and wrong the moment a
            # conditional ball is in play (notes/platinum.md section 5.3).
            capture_ball=h.capture_ball,
            throw=_throw_context(h, info),
            # Derived, not defaulted. `HuntConfig.target_has_pressure` defaults True and this
            # never set it, so every target was assumed to have Pressure -- right for all three
            # tower birds and wrong for both Lati twins, which have Levitate. Assuming it where
            # there is none DOUBLE-COUNTS our PP, halving every budget the solver plans against,
            # and the run quietly runs out of moves earlier than the plan said it would.
            target_has_pressure=ability == "pressure",
            # Darkrai's, and the reason a hunt against it is a clock rather than a budget: an
            # eighth of our max HP every turn we spend asleep, on top of Nightmare's quarter.
            target_has_bad_dreams=ability == ABILITY_BAD_DREAMS,
            # The trainer-AI selection path and the flee. Off the stored kind rather than asking
            # `targets.is_roamer` again here, so one run and the hunt it came from can never
            # disagree -- `_sync_encounter_kind` is the single place that decides it.
            target_is_roamer=h.is_roamer)
        # The spread the stats were DERIVED from, for the popup that lets the player check them
        # against the summary screen -- a run override if there was one, else the hunt's own
        # (clayton-1jd).
        shown = spread or {"nature": h.target.nature, "ivs": dict(h.target.ivs or {})}
        session = HuntSession(window, ours, target, config, capture_ball=h.capture_ball,
                              bench=bench, target_nature=shown.get("nature", ""),
                              target_ivs=shown.get("ivs") or {}, game=profile.game)
        session_id = self._hunt_sessions.add(hunt_id, session)
        return {"session_id": session_id, "hunt_id": hunt_id, "window": probe,
                "snapshot": session.snapshot(),
                "target_spread": None if spread is None else {
                    "nature": spread["nature"], "ivs": spread["ivs"],
                    "stats": dict(target.stats)}}

    @staticmethod
    def _apply_hunt_targeting(hunt, params: dict) -> None:
        """Copy the page's targeting fields onto the hunt, ignoring blanks."""
        key_seed = params.get("key_seed")
        if isinstance(key_seed, str) and key_seed.strip():
            hunt.key_seed = int(key_seed, 0)
        elif isinstance(key_seed, int):
            hunt.key_seed = key_seed
        if params.get("initial_time"):
            hunt.initial_time = params["initial_time"]
        if params.get("vector_ms") not in (None, ""):
            hunt.vector_ms = int(params["vector_ms"])
        if params.get("stopwatch_ms") not in (None, ""):
            hunt.stopwatch_ms = int(params["stopwatch_ms"])
        # The opening state is per ATTEMPT in practice -- the roamer's HP and status are whatever
        # the last encounter left in the save -- so the run page can set it alongside the vector
        # rather than making the player edit the hunt between attempts.
        if "opening_hp" in params:
            raw = params["opening_hp"]
            hunt.opening_hp = int(raw) if str(raw).strip() not in ("", "None") else None
        if "opening_status" in params:
            hunt.opening_status = (params["opening_status"] or "").strip()
        if params.get("opening_sleep_turns") not in (None, ""):
            hunt.opening_sleep_turns = int(params["opening_sleep_turns"])
        if params.get("delay_window") not in (None, ""):
            hunt.delay_window = int(params["delay_window"])
        if params.get("seconds_window") not in (None, ""):
            hunt.seconds_window = int(params["seconds_window"])

    def hunt_session_state(self, session_id: str) -> dict:
        return self._hunt_sessions.get(session_id).snapshot()

    def hunt_session_advice(self, session_id: str) -> dict:
        """Actions ranked by how much each would narrow the candidate set.

        Split out of the snapshot because it is the only slow part of one: it simulates every
        surviving candidate against every legal action, which is ~8s at 6,000 candidates. The
        page renders first and asks for this afterwards, so reporting a turn never waits on
        advice the player may not read.

        And if a turn IS reported while it runs, the sweep aborts rather than finishing: it was
        ranking a position that has been played, and until it stops it competes for the
        interpreter with the report the player is waiting on.
        """
        from claytonlib.battle_compass.identify import AdviceAborted
        session = self._hunt_sessions.get(session_id)
        try:
            advice = session.advice()
            # Computed here rather than on the snapshot because it costs the same sweep over
            # every candidate that the ranking does.
            risk = session.standard_ball_risk()
        except AdviceAborted:
            # A turn was reported while this was computing, so it was ranking a position that no
            # longer exists. Reported as an outcome rather than raised: the page has nothing to
            # fix, it just asks again for the new position.
            return {"session_id": session_id, "turns": len(session.turns),
                    "survivors": len(session.survivors), "aborted": True,
                    "advice": [], "standard_ball_risk": None}
        return {"session_id": session_id, "turns": len(session.turns),
                "survivors": len(session.survivors), "aborted": False,
                "advice": advice, "standard_ball_risk": risk}

    def hunt_session_observe(self, session_id: str, action: str, tokens: list,
                             item_code: str | None = None,
                             bench_slot: int | None = None,
                             replacement: int | None = None) -> dict:
        """Report one played turn. `tokens` may be a list or one already-rendered string.

        `item_code` and `bench_slot` complete the action rather than describing its outcome: the
        same ITEM heals different amounts, the same SWITCH brings in a different Pokemon, and a
        REVIVE names who it was used on. `replacement` is the other kind -- part of the OUTCOME,
        namely which party member came in after our Pokemon fainted.
        """
        from claytonlib.battle_compass.state import Action
        session = self._hunt_sessions.get(session_id)
        if isinstance(tokens, str):
            tokens = [tokens]
        return session.observe(
            Action(action), [str(t) for t in tokens],
            item_code=item_code or None,
            bench_slot=None if bench_slot in (None, "") else int(bench_slot),
            replacement=None if replacement in (None, "") else int(replacement))

    def hunt_session_undo(self, session_id: str) -> dict:
        """Rewind one reported turn (a misreport). A misplay is reported, not undone."""
        return self._hunt_sessions.get(session_id).undo()

    def hunt_session_enter_pinning(self, session_id: str,
                                   declared_hp: int | None = None) -> dict:
        """Move the run to Phase 1.5. `declared_hp` is what the PLAYER says the target is on.

        **`None` means "trust the simulation", and that is now the default.** It used to force 1
        unconditionally, which was right while Phase 2 required 1 HP and is wrong now that it does
        not: a run deliberately solving higher up would have had every throw priced against a `b`
        the battle does not have, and a plan built on it cannot land (clayton-6xu.3.14).

        Passing 1 is still the right thing on the force path, which exists precisely for a model
        that lags the game -- an unmodelled damage modifier leaves the simulation above 1 HP when
        the HP bar says otherwise, and the bar is an observation while our figure is an output.
        """
        return self._hunt_sessions.get(session_id).enter_pinning(declared_hp=declared_hp)

    def hunt_session_enter_solving(self, session_id: str, force: bool = False) -> dict:
        """Start Phase 2. `force` proceeds despite the blockers the simulation reports.

        Those blockers are what the model believes, and the player can see things it cannot -- so
        this stays available rather than locking the run out when the model is the thing at fault.
        """
        return self._hunt_sessions.get(session_id).enter_solving(force=bool(force))

    def hunt_session_predict(self, session_id: str, action: str,
                             item_code: str | None = None,
                             bench_slot: int | None = None,
                             replacement: int | None = None) -> dict:
        """What each surviving candidate would emit for `action`, without committing to it."""
        from claytonlib.battle_compass.state import Action
        session = self._hunt_sessions.get(session_id)
        extra = {}
        if item_code:
            extra["item_code"] = item_code
        if bench_slot not in (None, ""):
            extra["bench_slot"] = int(bench_slot)
        if replacement not in (None, ""):
            extra["replacement"] = int(replacement)
        return {f"{seed:#010x}": pred
                for seed, pred in session.predict(Action(action), **extra).items()}

    def hunt_session_replay_path(self, session_id: str, path: str) -> dict:
        """Report every turn of a pasted path in order. Returns the snapshot.

        The recovery route for a run that has to be re-entered: a code error or a missed frame on
        a not-shiny run is sometimes only discovered later, when the damage numbers stop matching,
        and retyping thirty turns by hand is the friction that makes the tool not worth using
        (clayton-fag).

        Paths round-trip because the tool renders them and `tokens.tokenise` reads them back, so
        the input this accepts is exactly the string the run page offers to copy. It stops at the
        first turn that does not fit and reports which -- see `HuntSession.replay_path`.
        """
        return self._hunt_sessions.get(session_id).replay_path(str(path or ""))

    def hunt_session_widen(self, session_id: str, frame_window: int | None = None,
                           second_window: int | None = None) -> dict:
        """Widen the candidate window mid-run and replay the turns so far against it.

        The recovery path for "no candidate predicted that turn" when the cause was the window
        rather than a mistyped answer. Only widening is allowed: the current candidates must stay
        in the set, since a turn already accepted has to remain explicable.

        Defaults double the frame range and leave the second range alone -- deliberately, because
        widening the SECOND axis admits candidates no move can ever separate (sec 17.1), so it
        buys ambiguity rather than coverage.
        """
        import datetime as dt

        from claytonlib.battle_compass.candidates import estimate_size, generate

        session = self._hunt_sessions.get(session_id)
        hunt_id = self._hunt_sessions.hunt_of(session_id)
        h = self._load_hunt(hunt_id)

        frames = int(frame_window if frame_window is not None
                     else session.window.frame_window * 2)
        seconds = int(second_window if second_window is not None
                      else session.window.second_window)
        if frames < session.window.frame_window or seconds < session.window.second_window:
            raise ValueError(
                f"this would narrow the window, not widen it "
                f"(frame {session.window.frame_window}->{frames}, "
                f"second {session.window.second_window}->{seconds})")

        # Through `_centring_model` like the other two sites: widening must not RE-CENTRE. A
        # roamer window centred on the calibration model instead of the stopwatch would move by
        # the whole difference between the two, so a widen could lose the true seed it was
        # widened to catch -- a silent failure, since a wider window that misses looks exactly
        # like a window that was never wide enough.
        model, _, _ = self._centring_model(h)
        if model is None:
            raise ValueError("no calibration model available for this profile")

        window = generate(
            model, key_seed=int(h.key_seed),
            initial_time=dt.datetime.fromisoformat(h.initial_time),
            vector_ms=float(h.centring_ms),
            frame_window=frames, second_window=seconds)

        snapshot = session.rebase(window)
        # Remember it, so a restart does not begin from the window that already failed.
        h.delay_window, h.seconds_window = frames, seconds
        self._store.write(_HUNTS, h.id, h.to_dict())
        snapshot["widened"] = {
            "frame_window": frames, "second_window": seconds,
            "candidates": len(window.candidates),
            "estimated": estimate_size(frames, seconds),
        }
        return snapshot

    def hunt_session_abandon(self, session_id: str) -> dict:
        return {"session_id": session_id, "closed": self._hunt_sessions.drop(session_id)}

    def list_balls(self, profile_id: str | None = None) -> list[dict]:
        """The balls available, for the hunt form's picker.

        Scoped to the profile's game when one is given: the apricorn balls do not exist in
        Platinum and the Sport Ball does not exist outside HGSS, and offering one a player cannot
        hold is how a plan gets built around a throw they cannot make.
        """
        from claytonlib.battle.balls import balls_for_game
        game_key = ""
        if profile_id:
            try:
                game_key = self._load_profile(profile_id).game
            except ValueError:
                # Fall back to the unscoped list rather than raising. This is the ONE call the
                # picker cannot do without: an exception reaches the page as a null list, and a
                # Capture ball select with nothing in it looks exactly like "this game has no
                # balls" -- which is how the reported symptom presented. Offering too many is the
                # smaller harm, and the same reasoning `balls_for_game` applies to an unset game;
                # `Hunt._ball_errors` is what actually refuses a ball the game does not have, and
                # it reads the profile itself.
                game_key = ""
        return [{"name": b.name, "note": b.note,
                 "turn_dependent": bool(b.rule in ("timer", "quick")),
                 "conditional": bool(b.rule), "apricorn": bool(b.apricorn)}
                for b in balls_for_game(game_key)]

    def _ball_readout(self, hunt) -> dict | None:
        """What `hunt`'s ball is worth against its target, as data for the configure screen."""
        from claytonlib.battle.balls import ball_effect, is_turn_dependent
        from claytonlib.battle.stats import species as species_data
        if not hunt.capture_ball or not hunt.target.species:
            return None
        try:
            info = species_data(hunt.target.species)
            effect = ball_effect(hunt.capture_ball, int(info["catch_rate"]),
                                 _throw_context(hunt, info))
            turn_dependent = is_turn_dependent(hunt.capture_ball)
        except (ValueError, KeyError):
            return None
        return {
            "name": hunt.capture_ball,
            "multiplier": effect.multiplier,
            "catch_rate": effect.catch_rate,
            "reason": effect.reason,
            "guaranteed": effect.guaranteed,
            "unmodelled": effect.unmodelled,
            "turn_dependent": turn_dependent,
            # The two conditions the player can get wrong without noticing, echoed back so the
            # screen can show what the multiplier was computed FROM.
            "terrain": hunt.terrain,
            "time_of_day": _throw_context(hunt, info).time_of_day,
        }

    def hunt_readiness(self, hunt_id: str) -> dict:
        """Everything the configure screen needs to say whether this hunt can be run.

        Three layers, deliberately distinct:

        * ``hard_errors`` — Battle Compass cannot start at all.
        * ``alphabet`` — it *can* start, but with how good a chance? A party with one distinct
          per-turn RNG cost makes a capture reachable for ~36% of seeds against ~99% for three,
          so this is advice worth giving before the encounter rather than after.
        * ``speed`` — ties desynchronise the simulation rather than merely costing turns.
        * ``survivability`` — which party members cannot live through the target's worst hit, and
          whether that is true now or only once it has boosted. This is what stops the danger
          floor failing opaquely: a floor above a Pokemon's max HP makes every turn "in danger",
          so the solver never throws a ball and reports Unreachable for a reason that has nothing
          to do with capture windows (clayton-957.10.1).
        * ``move_coverage`` — moves of OURS the simulator cannot model. The mirror of the check
          `targets.unsupported_moves` has always done for the target. Advisory rather than
          blocking, because unlike the target's moves we can simply not select ours.
        * ``access`` — whether the party can **reach** the encounter, which is a different
          question from whether it can beat it and was not being asked at all. Lugia is behind
          Surf and Whirlpool, and because there is no PC in the Whirl Islands the carrier has to
          be one of the six you fight with. Asked of the target even with no party configured,
          since "you will need Surf and Whirlpool" is most useful before the party is picked.

        Only the first blocks; the rest are warnings the player may knowingly accept.
        """
        from claytonlib.battle.readiness import (
            alphabet_report, speed_after_item, speed_checks, speed_move_ties,
            speed_move_warnings, speed_warnings, unmodelled_held_items,
        )
        from claytonlib.battle.stats import derive_species_stats, species
        from claytonlib.battle_compass.sim import unsupported_our_moves
        from claytonlib.battle_compass.targets import (
            TrapCandidate, access_warnings, chip_warnings, repel_warnings, trap_warnings,
        )
        from claytonlib.moves import resolve_move

        h = self._load_hunt(hunt_id)
        profile = self._load_profile(h.profile_id)
        result: dict = {
            "hunt_id": h.id,
            "hard_errors": h.hard_errors(profile),
            "alphabet": None,
            "speed": None,
            "survivability": [],
            "move_coverage": [],
            # Whether the party can REACH the encounter, which is a different question from
            # whether it can beat it and was not being asked at all. Lugia is behind Surf and
            # Whirlpool, and the party you arrive with is the party you fight with.
            "access": [],
            # ...and whether it can DAMAGE the encounter, which is the other half of that
            # question. Phase 1 needs the target on 1 HP and False Swipe is the only move that
            # can safely get it there -- but False Swipe is Normal, so against Giratina it does
            # nothing at all until a Foresight or Odor Sleuth lands. That is a one-slot decision
            # made before the run, and it was only discoverable after hitting the seed
            # (clayton-957.26.4).
            "chip": [],
            # And whether it can HOLD it, which only a roamer asks: the trap is released when our
            # side leaves the field, so every member that could end up active needs Shadow Tag,
            # Arena Trap against a grounded target, or a trapping move plus the Speed to land it
            # first (notes/roamers.md sec 2). Empty for a static encounter, which cannot leave.
            "trap": [],
            # Held items the simulator cannot model, plus the ones left blank. A misconfigured
            # item SHOULD desync the run -- what was missing is being told before the encounter
            # instead of as a turn-2 contradiction blaming the window (clayton-957.10.15).
            "held_items": [],
            "target_stats": None,
            # Which calibration model the centre-seed maths will use. Never a blocker: models
            # are profile-scoped and every profile is seeded with an active "Standard" one, so
            # this is information plus a route to Review Data, not a thing to configure.
            "calibration_model": self.calibration_model_summary(h.profile_id),
            # What the chosen ball is actually worth against this target -- its multiplier, the
            # sentence explaining why, whether it moves with the turn, and whether its rule is
            # modelled at all. Information rather than a blocker: a x1 ball is a legitimate
            # choice, and the warning worth giving is the one about a rule we do NOT model.
            "ball": self._ball_readout(h),
        }

        # A probe standing in for the target, carrying only its NAME and ABILITY -- which is all
        # `unselectable_reason` reads to answer "would this target absorb that move of ours".
        # Heatran is the case: Flash Fire eats a Fire move AND raises its own Fire power, so a
        # Flamethrower in the party has to be reported before the run rather than refused in the
        # middle of one. A probe rather than the real Battler because this runs on a
        # half-configured hunt, where the stats a Battler needs may not exist yet.
        target_probe = self._target_ability_probe(h, profile)

        movesets: dict[str, list] = {}
        #: The same party, as move NAMES, for the field-move check. Taken from the resolved Move
        #: where resolution worked, so that whatever spelling the player typed is normalised to
        #: the table's -- and from the raw string where it did not, since an unrecognised name is
        #: already reported by `move_coverage` and should not also vanish from this check.
        move_names: dict[str, list[str]] = {}
        held_items: dict[str, str] = {}
        party_species: dict[str, str] = {}
        #: Abilities, read for Scrappy alone by `chip_warnings` -- the attacker-side route to
        #: removing a Ghost immunity. Without it a Scrappy Kangaskhan gets warned about when it
        #: is the answer rather than the problem.
        our_abilities: dict[str, str] = {}
        our_speeds: dict[str, int] = {}
        #: Speed-check label -> the Pokemon's own name, for joining the two dicts above.
        speed_labels: dict[str, str] = {}
        #: The party in SEND-OUT ORDER for the trap check, which is the one check here that cares
        #: which member is the lead -- its failure ends the run on turn 1 where a bench member's
        #: only matters after a faint. The other collections above are dicts keyed by name
        #: precisely because order is irrelevant to them.
        trap_party: list[TrapCandidate] = []
        for slot in h.party:
            pokemon = profile.get_party_pokemon(slot.pokemon_id)
            if pokemon is None:
                continue
            moves = [m for m in (resolve_move(name) for name in pokemon.moveset) if m]
            if moves:
                movesets[pokemon.name] = moves
            move_names[pokemon.name] = [
                (resolved.name if (resolved := resolve_move(name)) else name)
                for name in pokemon.moveset if name]
            # Keyed on the Pokemon so the warning can name the holder. Held items are per HUNT,
            # so they come off the slot rather than the profile entry.
            held_items[pokemon.name] = slot.held_item
            # Species as well as moves, so the field-move warning can name who COULD carry a
            # missing HM -- and say plainly when nobody can, which is the Lugia party's answer.
            party_species[pokemon.name] = pokemon.species or ""
            our_abilities[pokemon.name] = pokemon.ability or ""
            trap_party.append(TrapCandidate(
                name=pokemon.name, ability=pokemon.ability or "",
                moves=tuple(move_names[pokemon.name]),
                # Item-adjusted, like `our_speeds` -- a Choice Scarf is exactly what turns a
                # Mean Look user that cannot trap into one that can, so reading the bare stat
                # would reject the party for a problem the player had already solved. Zero when
                # the Speed is not configured, which `trap_checks` reports as unknown rather
                # than as a failure.
                speed=(speed_after_item(pokemon.speed, slot.held_item)
                       if pokemon.speed is not None else 0),
                held_item=slot.held_item))
            for name, why in unsupported_our_moves(pokemon.moveset, target_probe):
                result["move_coverage"].append(
                    {"pokemon": pokemon.name, "move": name, "reason": why})
            if pokemon.speed is not None:
                # The HELD ITEM applied, because the summary screen does not include it: a
                # scarfed Magneton reads 124 and moves at 186, and this check is what tells the
                # player whether a tie is possible. Labelled with the item, so the number not
                # matching their screen is explained rather than mysterious.
                effective = speed_after_item(pokemon.speed, slot.held_item)
                label = (f"{pokemon.name} ({slot.held_item})"
                         if effective != pokemon.speed else pokemon.name)
                our_speeds[label] = effective
                # `our_speeds` is keyed by a LABEL that may carry the held item; the movesets are
                # keyed by the bare name. `speed_move_ties` needs the two keyed alike, so the
                # mapping is kept rather than the label being parsed back apart.
                speed_labels[label] = pokemon.name

        # Asked of the target regardless of whether a party is configured yet: "you will need
        # Surf and Whirlpool" is most useful BEFORE the party is picked, not after.
        result["access"] = access_warnings(h.target.species, move_names, party_species)
        # Asked only once a party exists, unlike `access`: "nothing can damage it" is not a
        # statement worth making about an empty party list, where it is trivially true and tells
        # the player only that they have not finished configuring yet.
        result["chip"] = chip_warnings(h.target.species, movesets, our_abilities,
                                       profile.game if profile else "")
        # Asked once a party exists, like `chip`. The target's Speed comes from the derived
        # spread when there is one and is None otherwise -- a roamer's spread is not lookupable
        # from the key seed, so "we cannot tell yet" is a normal state here rather than a
        # misconfiguration, and `trap_checks` says which of the two it is.
        if trap_party:
            result["trap"] = trap_warnings(
                h.target.species, trap_party,
                target_speed=self._target_derived_speed(h),
                game=profile.game if profile else "")
            # The Repel ceiling, which is the same Pokemon's problem: the lead is both the trapper
            # and what `RepelPreventsEncounter` reads. Appended to the same field rather than
            # given one of its own, because the player's answer to either is "change the lead".
            lead = profile.get_party_pokemon(h.party[0].pokemon_id) if h.party else None
            result["trap"] += repel_warnings(
                h.target.species, getattr(lead, "level", None),
                profile.game if profile else "")
        result["held_items"] = unmodelled_held_items(held_items)

        if movesets or our_speeds:
            report = alphabet_report(movesets)
            result["alphabet"] = {
                "distinct_costs": sorted(report.distinct_costs),
                "reachability_percent": report.reachability_percent,
                "costs_by_action": report.costs_by_action,
                "warnings": report.warnings,
            }

        # The target's stats are derived, not entered — its IVs come from RNG manipulation.
        # Gated on the SPREAD rather than on every target error: an unsupported encounter still
        # has base stats worth showing, and a species that is not a configured target is
        # reported as its own hard error rather than by withholding this.
        if not h.target.spread_errors():
            try:
                stats = derive_species_stats(
                    h.target.species, h.target.level, h.target.nature, ivs=dict(h.target.ivs))
            except KeyError as exc:
                result["target_stats"] = {"error": str(exc)}
            else:
                result["target_stats"] = stats
                if our_speeds:
                    # Every Speed stage the target can reach. Ancient Power's 10% raises all of
                    # its stats, and stages are applied BEFORE paralysis quarters Speed -- so a
                    # boosted paralyzed target can claw back the Speed gap the precondition
                    # depends on, and at +6 it recovers it exactly.
                    checks = speed_checks(
                        our_speeds, stats["spe"],
                        target_speed_stages=self._target_speed_stages(h.target),
                        # Half the table assumed our paralysis against a target with no way to
                        # inflict it (clayton-36b).
                        include_our_paralysis=self._target_can_paralyze_us(h.target))
                    # Ties a move in OUR OWN party could create, which is a different question
                    # from the one above: `speed_checks` holds our Speed constant and the
                    # target's at whatever the target can do to itself. An Agility, a Dragon
                    # Dance or a Cotton Spore moves one of those mid-run, on a turn the player
                    # chose, long after this screen said the party was fine.
                    move_ties = speed_move_ties(
                        our_speeds,
                        {label: movesets.get(name, [])
                         for label, name in speed_labels.items()},
                        stats["spe"],
                        # The paralyzed-target rows are a second full set of stage combinations
                        # to tie at, and they are only reachable if somebody in the party can
                        # actually inflict it -- the same reasoning `_target_can_paralyze_us`
                        # applies in the other direction.
                        target_can_be_paralyzed=self._party_can_paralyze(h, profile),
                        target_own_speed_stages=self._target_speed_stages(h.target))
                    result["speed"] = {
                        "target_speed": stats["spe"],
                        "move_tie_warnings": speed_move_warnings(move_ties),
                        "move_ties": [
                            {"ours": t.ours, "our_speed": t.our_speed,
                             "our_stage": t.our_stage, "target_speed": t.target_speed,
                             "target_stage": t.target_stage,
                             "target_paralyzed": t.target_paralyzed,
                             "via": t.via, "via_owner": t.via_owner}
                            for t in move_ties
                        ],
                        "checks": [
                            {"ours": c.ours, "our_speed": c.our_speed,
                             "target_state": c.target_state, "target_speed": c.target_speed,
                             "margin": c.margin, "is_tie": c.is_tie,
                             "is_fragile": c.is_fragile,
                             # So the page can show the unboosted rows and hide the rest unless
                             # they are actually dangerous: seven stages x two statuses is a
                             # table nobody reads.
                             "target_speed_stage": c.target_speed_stage,
                             "notable": c.notable}
                            for c in checks
                        ],
                        "warnings": speed_warnings(checks),
                    }
                result["survivability"] = self._survivability_warnings(h, profile, stats)
        return result

    def _survivability_warnings(self, hunt, profile, target_stats: dict) -> list[str]:
        """`survivability_warnings` over the configured party, or [] if it cannot be built.

        Separate from `hunt_readiness` because building `Battler`s is the one part of this that
        can fail on an incomplete configuration, and a half-entered party should cost the screen
        its warnings rather than its whole payload.
        """
        from claytonlib.battle.stats import species
        from claytonlib.battle_compass.hunt_session import survivability_warnings
        from claytonlib.battle_compass.state import Battler
        from claytonlib.battle_compass.targets import moveset, target_ability
        from claytonlib.moves import resolve_move

        game = profile.game if profile is not None else ""
        try:
            target_moves = moveset(hunt.target.species, game)
            ability = target_ability(hunt.target.species, game)
        except KeyError:
            return []
        try:
            info = species(hunt.target.species)
        except KeyError:
            return []
        target = Battler(
            name=hunt.target.species, level=hunt.target.level,
            types=tuple(info["types"]), stats=dict(target_stats),
            moves=target_moves,
            pp=tuple((resolve_move(n).pp if resolve_move(n) else 0) for n in target_moves),
            ability=ability)
        party = []
        for slot in hunt.party:
            pokemon = profile.get_party_pokemon(slot.pokemon_id)
            if pokemon is None or not pokemon.stats:
                continue
            try:
                party.append(Battler(
                    name=pokemon.name, level=pokemon.level,
                    types=tuple(species(pokemon.species)["types"]),
                    stats=dict(pokemon.stats), moves=tuple(pokemon.moveset),
                    # **The ability, which this dropped.** The RUN path has always passed it
                    # (`hunt_run_setup`'s `battler_for`), so the simulation was right and only
                    # the pre-hunt advice was wrong -- and wrong in the direction that matters:
                    # every party member was judged ability-less, so an Insomnia holder was told
                    # a target could sleep it, an Early Bird holder got the unhalved sleep clock,
                    # and `_sleep_answer` could never find the carrier it exists to name. Found by
                    # pointing the Honchkrow kit at it (clayton-4wr.1.3).
                    ability=pokemon.ability or "",
                    held_item=slot.held_item))
            except (KeyError, TypeError, ValueError):
                continue
        if not party:
            return []
        return survivability_warnings(party, target)

    # -- seeds (Glass) ----------------------------------------------------
    #
    # A Seed is the smallest entity in the app: a key seed worth keeping, an initial time to
    # load it at, a frame to route to, and notes. It owns nothing, has no name and no
    # uniqueness rule, and gates no tool -- so this is the hunt CRUD above with every
    # validation that does not apply removed, rather than a new pattern. See notes/glass.md.

    def _load_seed(self, seed_id: str) -> Seed:
        doc = self._store.read(_SEEDS, seed_id)
        if doc is None:
            raise ValueError(f"no seed with id {seed_id}")
        return Seed.from_dict(doc)

    @staticmethod
    def _parse_key_seed(value) -> int | None:
        """A key seed as the UI sends it: an int, or hex text with or without "0x".

        int(x, 0) would read a bare "12345" as decimal where every key-seed field in this app
        means hex, so bare text is parsed base 16 explicitly (the UI normalises to an explicit
        0x as well, but the facade is the one that must not be fooled).
        """
        if value in (None, ""):
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if text.lower().startswith("0x"):
            return int(text[2:], 16)
        return int(text, 16)

    def _seed_row(self, s: Seed) -> dict:
        """One row of the Glass list: what it shows, already derived.

        The readout is server-side so the list does not have to make a call per row -- and the
        time-of-day bucket comes from the KEY SEED rather than the time, because the seed's hour
        byte (bits 16-23) fixes the hour of every initial time that can produce it, so the
        bucket is known before any time is picked.
        """
        from app import glass
        read = glass.readout(s.key_seed, s.initial_time)
        notes = (s.notes or "").strip().splitlines()
        return {
            "id": s.id,
            "profile_id": s.profile_id,
            "label": s.label,
            "key_seed": s.key_seed,
            "key_seed_hex": read["key_seed_hex"],
            "initial_time": s.initial_time,
            "default_frame": s.default_frame,
            "delay": read["delay"],
            "time_of_day": read["time_of_day"],
            "problem": read["problem"],
            "notes_line": notes[0] if notes else "",
            "history_count": len(s.history),
        }

    def list_seeds(self, profile_id: str | None = None) -> list[dict]:
        out = []
        for sid in self._store.list_ids(_SEEDS):
            doc = self._store.read(_SEEDS, sid)
            if doc is None:
                continue
            s = Seed.from_dict(doc)
            if profile_id is not None and s.profile_id != profile_id:
                continue
            out.append(self._seed_row(s))
        # Labelled seeds first, alphabetically, then the unlabelled ones by seed -- so a seed
        # someone bothered to name never sorts below one they didn't.
        out.sort(key=lambda d: (not d["label"], (d["label"] or "").lower(), d["key_seed"] or 0))
        return out

    def get_seed(self, seed_id: str) -> dict:
        """The full seed document, plus the derived readout the page prints beside the time."""
        from app import glass
        s = self._load_seed(seed_id)
        doc = s.to_dict()
        doc["readout"] = glass.readout(s.key_seed, s.initial_time)
        return doc

    def create_seed(self, fields: dict) -> dict:
        """A new seed. Only a profile is required -- everything else is filled in on the page."""
        profile_id = fields.get("profile_id")
        if not profile_id:
            raise ValueError("a seed must reference a profile")
        profile = self._load_profile(profile_id)  # validate the reference
        # The gate the game field exists for. Refused here rather than in the page so it holds
        # however a seed is created, and with the game's own sentence rather than a generic no.
        refusal = profile.tool_refusal(TOOL_GLASS)
        if refusal:
            raise ValueError(refusal)
        s = Seed.from_dict({
            **fields,
            "profile_id": profile_id,
            "key_seed": self._parse_key_seed(fields.get("key_seed")),
            "label": (fields.get("label") or "").strip(),
        })
        self._store.write(_SEEDS, s.id, s.to_dict())
        return s.to_dict()

    def save_seed(self, seed_id: str, fields: dict) -> dict:
        """Update the editable configuration, leaving the history alone.

        Field-wise rather than whole-document on purpose: the page saves as you type, and a
        whole-document upsert from a page that has never loaded the history would quietly
        delete it. Passing a field as "" clears it; omitting it leaves it untouched.
        """
        from app import glass
        s = self._load_seed(seed_id)
        if "label" in fields:
            s.label = (fields.get("label") or "").strip()
        if "key_seed" in fields:
            s.key_seed = self._parse_key_seed(fields.get("key_seed"))
        if "initial_time" in fields:
            s.initial_time = (fields.get("initial_time") or "").strip()
        if "default_frame" in fields:
            frame = fields.get("default_frame")
            s.default_frame = None if frame in (None, "") else int(frame)
        if "notes" in fields:
            s.notes = fields.get("notes") or ""
        self._store.write(_SEEDS, s.id, s.to_dict())
        doc = s.to_dict()
        doc["readout"] = glass.readout(s.key_seed, s.initial_time)
        return doc

    def delete_seed(self, seed_id: str) -> bool:
        return self._store.delete(_SEEDS, seed_id)

    def seed_save_seed_a_defaults(self, seed_id: str, defaults: dict) -> dict:
        """Remember the roamer starting positions and window sizes, as a Hunt does."""
        s = self._load_seed(seed_id)
        s.seed_a_defaults = {**(s.seed_a_defaults or {}), **(defaults or {})}
        self._store.write(_SEEDS, s.id, s.to_dict())
        return dict(s.seed_a_defaults)

    # -- Platinum Seed A: coin flips, then chatot pitch ----------------------
    #
    # The Platinum counterparts of `metronome_seed_a`, `safari_compass_identify_frame` and
    # `safari_compass_plan_frame`. Named by MECHANISM rather than after a tool, unlike the three
    # above -- those carry the name of the compass they were written for and are now called from
    # three pages each, which is exactly the confusion worth not repeating.
    #
    # PokeFinder draws this same fork in one line (`Core/Gen4/SeedTime4.cpp:77`), so a player
    # moving between the two tools sees the same two columns.

    def platinum_seed_a(self, params: dict) -> dict:
        """Candidate initial seeds around a target, narrowed by the coin flips observed.

        params: target_time (ISO), key_seed, seconds_window, delay_window, match_parity, and
        optionally observed_flips. The search delay is derived from key_seed + target_time, never
        a caller input -- same contract as `metronome_seed_a`.

        No `prev_routes`: Platinum does not relocate its roamers at game load, so there is
        nothing to enter and nothing to walk past.
        """
        import datetime as dt

        from claytonlib.platinum_advance import filter_flips, generate_flip_candidates_near
        target_time = dt.datetime.fromisoformat(str(params["target_time"]).strip())
        key_seed = int(params["key_seed"])
        target_delay = metronome.target_delay_for_key_seed(key_seed, target_time)
        rows = generate_flip_candidates_near(
            target_time, target_delay,
            int(params.get("seconds_window", 2)),
            int(params.get("delay_window", 10)),
            match_parity=bool(params.get("match_parity", False)))
        observed = (params.get("observed_flips") or "").strip()
        if observed:
            rows = filter_flips(rows, observed)
        return {"candidates": [self._flip_row_json(r) for r in rows], "count": len(rows)}

    @staticmethod
    def _flip_row_json(row: dict) -> dict:
        return {
            "seed": row["seed"], "seed_hex": f"0x{row['seed']:08X}",
            "time": row["time"].strftime("%Y-%m-%dT%H:%M:%S"),
            "delay": row["delay"], "sec_delta": row["sec_delta"],
            "delay_delta": row["delay_delta"],
            "flips": row["flips"], "pitch_display": row["pitch_display"],
        }

    def platinum_key_seed_info(self, key_seed: int) -> dict:
        """The key seed's own flips and opening pitches — the Seed-to-Time readout.

        The counterpart of `metronome_key_seed_info`, and it needs no second argument for the
        same reason `platinum_seed_a` needs no `prev_routes`.
        """
        from claytonlib.chatot_pitch import format_sequence, pitch_values
        from claytonlib.coin_flips import flip_sequence
        key_seed = int(key_seed)
        return {
            "flips": flip_sequence(key_seed, 20),
            "pitch_display": format_sequence(pitch_values(key_seed, 12)),
        }

    def platinum_plan_frame(self, params: dict) -> dict:
        """A Journal-flip + chatot-cry route to `target_frame`, with its pitch margin.

        params: seed, target_frame, optionally current_frame (default 0), margin and start_frame.

        **There is no Platinum counterpart of `safari_compass_identify_frame`, deliberately.** The
        advance frame is not identified in Platinum, it is counted: you load the seed on frame 0
        and every action you take has a known cost. The pitch margin this returns is how that
        count gets *checked* — the player hears it and knows whether they landed where the plan
        said. Asking them to type pitches in would be asking them to measure a number they
        already have (clayton-6xu.5).
        """
        from claytonlib.platinum_advance import PLATINUM_START_FRAME, plan_route
        seed = params["seed"]
        seed = int(seed, 16) if isinstance(seed, str) else int(seed)
        current = params.get("current_frame")
        return plan_route(
            seed, int(params["target_frame"]),
            current_frame=PLATINUM_START_FRAME if current in (None, "") else int(current),
            margin=int(params.get("margin", 3)),
            start_frame=int(params.get("start_frame", 0) or 0))

    def seed_readout(self, key_seed, initial_time: str = "") -> dict:
        """The hour, time-of-day bucket and ABSOLUTE delay for a key seed + initial time.

        Unsaved values, straight from the page's fields -- so the delay updates as the year in
        the time is edited, before anything is stored.
        """
        from app import glass
        return glass.readout(self._parse_key_seed(key_seed), initial_time)

    def seed_add_history(self, seed_id: str, entry: dict) -> list:
        """Append one identification to the seed's recent history (newest first, capped).

        Explicitly NOT a run: both calibration fits need a vector ms and a Seed B, and Glass has
        neither, so nothing here can reach the model (see app/calibration.py and notes/glass.md).
        """
        from app import glass
        s = self._load_seed(seed_id)
        s.add_history(glass.history_entry(entry))
        self._store.write(_SEEDS, s.id, s.to_dict())
        return list(s.history)

    def seed_clear_history(self, seed_id: str) -> list:
        s = self._load_seed(seed_id)
        s.history = []
        self._store.write(_SEEDS, s.id, s.to_dict())
        return []

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

    def app_version(self) -> str:
        """Clayton's version string, for the window header. See app/_version.py."""
        from app._version import version
        return version()

    def list_safari_areas(self) -> list[str]:
        """The Safari Zone area names, for the expedition-config dropdown."""
        from claytonlib.safari_encounters import safari_areas
        return safari_areas()

    def list_safari_areas_for_pokemon(self, pokemon: str, method: str | None = None) -> list[str]:
        """Only the areas where `pokemon` can actually appear — narrows the Safari area
        dropdown once a Pokemon is chosen (clayton-b42.10.3). `method=None` means by any
        method; pass one to narrow to just that one (clayton-858).

        With no `pokemon` yet (the dropdown's own starting state) this falls back to every
        area that offers `method` at all — so picking Super Rod before picking a Pokemon still
        leaves only the five areas with water."""
        from claytonlib.safari_encounters import areas_for_species, safari_areas, safari_methods
        if not pokemon:
            if not method:
                return safari_areas()
            from claytonlib.safari_encounters import normalize_method
            m = normalize_method(method)
            return [a for a in safari_areas() if m in safari_methods(a)]
        return areas_for_species(pokemon, method=method or None)

    def list_safari_methods(self, area: str = "") -> list[dict]:
        """The encounter methods, as ``{"method", "label", "action", "is_rod"}`` rows for the
        Configure dropdown. Narrowed to what `area` actually offers when one is given — the
        four water methods exist only in the five areas with water (clayton-858)."""
        from claytonlib.safari_encounters import (
            METHODS, METHOD_ACTIONS, METHOD_LABELS, ROD_METHODS, safari_methods,
        )
        names = safari_methods(area) if area else list(METHODS)
        return [{"method": m, "label": METHOD_LABELS[m], "action": METHOD_ACTIONS[m],
                 "is_rod": m in ROD_METHODS} for m in names]

    def list_safari_locations_for_pokemon(self, pokemon: str) -> list[dict]:
        """Every ``{"area", "method", "label"}`` where `pokemon` can appear — the "where do I
        even hunt this" answer now that a species may be reachable several ways (clayton-858).
        Poliwhirl, for instance, surfaces in Wetland surf AND on all three rods."""
        from claytonlib.safari_encounters import METHOD_LABELS, locations_for_species
        return [{**loc, "label": METHOD_LABELS[loc["method"]]}
                for loc in locations_for_species(pokemon)]

    def safari_fishing_happiness_bonuses(self) -> list[int]:
        """The lead-happiness bonuses a rod's hook rate can take (0/20/30/40/50)."""
        from claytonlib.safari_encounters import HAPPINESS_BONUSES
        return list(HAPPINESS_BONUSES)

    def safari_hook_rate(self, method: str, happiness_bonus: int = 0,
                         suction_cups: bool = False) -> int | None:
        """A rod's chance out of 100 that something bites, for the Configure page's own
        feedback. None for grass/surf, which have no such check."""
        from claytonlib.safari_encounters import ROD_METHODS, hook_rate, normalize_method
        if normalize_method(method) not in ROD_METHODS:
            return None
        return hook_rate(method, int(happiness_bonus or 0), bool(suction_cups))

    def safari_pokemon_rates(self, pokemon_name: str) -> dict | None:
        """Base catch and flee rates for a species, raw and as percentages.

        The raw numbers are the game's own; the percentages are what they actually work out
        to per ball / per flee check, which is the part that isn't guessable from the raw
        value (catch rate 255 is a 50% ball, not a certainty). `catch_percent`/`flee_percent`
        are fractions in 0..1 -- the UI does the rounding, since it also decides how to show a
        chance that rounds to zero without being zero."""
        from claytonlib.safari import safari_pokemon_by_name
        if not pokemon_name:
            return None
        try:
            p = safari_pokemon_by_name(pokemon_name)
        except Exception:
            return None
        return {"name": p.name,
                "catch_rate": p.base_catch_rate, "catch_percent": p.capture_chance(),
                "flee_rate": p.base_flee_rate, "flee_percent": p.flee_chance()}

    def safari_block_requirement(self, area: str, pokemon: str,
                                 method: str = "grass") -> dict | None:
        """The block score `pokemon` needs to appear in `area` by `method`, or None if it's
        already reachable unconditionally there (or doesn't appear that way at all) — drives
        the "(required: N)" label and invalid-styling on the block-score inputs."""
        from claytonlib.safari_encounters import (
            block_requirement_for, normalize_method, safari_methods,
        )
        if not area or not pokemon:
            return None
        # A water method in a waterless area can't be reached through the UI's own dropdowns,
        # but this is a label helper: say "no requirement" rather than raising mid-keystroke.
        # The real search (safari_compass_find_target_frame) explains that case properly.
        if normalize_method(method or "grass") not in safari_methods(area):
            return None
        return block_requirement_for(area, pokemon, method=method or "grass")

    # -- Metronome Compass: seed identification ---------------------------

    def metronome_seed_a(self, params: dict) -> dict:
        """Candidate initial seeds, narrowed by observed roamer routes + Elm calls."""
        return metronome.seed_a(params)

    def metronome_key_seed_info(self, key_seed: int, prev_routes: dict) -> dict:
        """The key seed's own roamer routes + Elm (to spot a key-seed hit)."""
        return metronome.key_seed_info(key_seed, prev_routes)

    def times_on_date(self, key_seed: int, month: int | None = None, day: int | None = None,
                      second: int | None = None, year: int | None = None) -> list[str]:
        """Every valid initial time for `key_seed`, optionally filtered to a month (1-12),
        a day-of-month (1-31), and/or a second-of-minute value — powers the calendar/
        date-picker flow for Initial-time fields. All filters are optional and independent
        (a month alone, or month+day, etc.); with none, every valid time comes back.

        `year` stamps every returned time with that year. Only Glass passes it, because only
        Glass shows an absolute delay and therefore has to store a time carrying the year the
        player will set (see app/glass.py); omitting it leaves the placeholder-year behaviour
        every other caller already relies on."""
        return metronome.times_on_date(key_seed, month, day, second,
                                       None if year in (None, "") else int(year))

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

    def _with_metronome_user_ability(self, params: dict) -> dict:
        """`params` plus the selected metronome user's ability, read from the stored profile.

        Resolved here rather than sent by the UI so the simulation is configured from the
        record the user actually saved, not from whatever the page happened to have in hand.
        Needs `profile_id` and `metronome_user_id`; without both, or if the id no longer
        resolves, the ability stays unset and the battle runs as it always has.
        """
        if params.get("user_ability") is not None:
            return params                       # an explicit override wins (tests, callers)
        profile_id, user_id = params.get("profile_id"), params.get("metronome_user_id")
        if not profile_id or user_id is None:
            return params
        doc = self._store.read(_PROFILES, profile_id)
        if doc is None:
            return params
        for u in doc.get("metronome_users", []):
            if u.get("id") == user_id:
                return {**params, "user_ability": u.get("ability")}
        return params

    def metronome_seed_b(self, params: dict) -> dict:
        """Candidate battle seeds, each with its precomputed Metronome path.

        Centered on where the active calibration model says Seed B lands for this target's
        Vector ms -- NOT on the key seed, which is where Seed A lands."""
        params = self._with_metronome_user_ability(params)
        return metronome.seed_b(params, self._metronome_model(params))

    def _json_session_state(self, state: dict) -> dict:
        result = state.get("result")
        if result:  # the identified candidate carries a datetime + path objects
            state = {**state, "result": metronome._row_b_json(result)}
        return state

    def metronome_seed_b_start(self, params: dict) -> dict:
        """Begin the interactive Seed B narrowing; returns the first question (or result)."""
        params = self._with_metronome_user_ability(params)
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
        encounter frame. params: seed, prev_routes, current_frame, encounter_frame, margin,
        method (grass/surf/old_rod/good_rod/super_rod — decides the guide's verb)."""
        from app import safari_compass
        seed = params["seed"]
        seed = int(seed, 16) if isinstance(seed, str) else int(seed)
        return safari_compass.plan_frame_route(
            seed, params.get("prev_routes") or {},
            int(params["current_frame"]), int(params["encounter_frame"]),
            margin=int(params.get("margin", 3)),
            method=params.get("method") or "grass")

    def safari_compass_find_target_frame(self, params: dict) -> dict:
        """In-house target-encounter-frame search (vs. pasting one from Pokefinder).

        params: seed, prev_routes, current_frame, area, tod (morning/day/night), block_config,
        pokemon, margin, max_frame, aim_advance (optional), method (default grass), and for a
        rod happiness_bonus / suction_cups (which decide WHICH frames hook at all)."""
        from app import safari_compass
        seed = params["seed"]
        seed = int(seed, 16) if isinstance(seed, str) else int(seed)
        aim = params.get("aim_advance")
        return safari_compass.find_target_frame(
            seed, params.get("prev_routes") or {}, int(params["current_frame"]),
            params["area"], params["tod"], params.get("block_config") or {}, params["pokemon"],
            margin=int(params.get("margin", 3)), max_frame=int(params.get("max_frame", 300)),
            aim_advance=int(aim) if aim not in (None, "") else None,
            method=params.get("method") or "grass",
            happiness_bonus=int(params.get("happiness_bonus", 0) or 0),
            suction_cups=bool(params.get("suction_cups", False)))

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

    def hunt_session_run_record(self, session_id: str) -> dict:
        """What `save_hunt_run` would store, for the page to show before committing."""
        session = self._hunt_sessions.get(session_id)
        hunt_id = self._hunt_sessions.hunt_of(session_id)
        record = session.run_record()
        record["hunt_id"] = hunt_id
        hunt = self._load_hunt(hunt_id) if hunt_id else None
        if hunt is not None:
            record["vector_ms"] = hunt.vector_ms
            record["hunt_name"] = hunt.name
        return record

    def save_hunt_run(self, session_id: str, data: dict | None = None) -> dict:
        """Persist this Battle Compass attempt (kind="battle").

        **No longer diagnostic-only.** `preview_battle_calibration` fits these, which is the only
        calibration path a Platinum profile has (notes/platinum.md section 6) and a free gain on
        HGSS, where a Suicune or Lugia run used to be thrown away. Nothing here is validated
        against a calibration model even so: a run that cannot be fit is screened out by
        `_record_for_battle_run` returning None, the same way an incomplete metronome run is.

        Taken from the SESSION rather than from the page: the session is
        what knows the path, the items actually spent and how it ended, and a record assembled
        from whatever the page had in hand is the kind that turns out to be missing the one field
        you needed.

        Saveable at any point, not only on a capture. A run that ended in the wrong ball or a
        faint is the more informative record, and a half-finished one is still a real
        observation of where the seed landed.
        """
        data = data or {}
        session = self._hunt_sessions.get(session_id)
        hunt_id = self._hunt_sessions.hunt_of(session_id)
        if not hunt_id:
            raise ValueError("this session is not attached to a hunt any more")
        hunt = self._load_hunt(hunt_id)
        self._load_profile(hunt.profile_id)
        record = session.run_record()
        run = Run(
            profile_id=hunt.profile_id,
            kind="battle",
            hunt_id=hunt_id,
            tag=data.get("tag", ""),
            notes=data.get("notes", ""),
            vector_ms=hunt.vector_ms,
            # Seed A and its advance frame come from the PAGE: they are identified before the
            # session exists, so the session has never seen them.
            a_seed=dict(data.get("a_seed", {})),
            advance_frame=data.get("advance_frame"),
            elm_calls=data.get("elm_calls"),
            chatot_flips=data.get("chatot_flips"),
            frame_guide=data.get("frame_guide", ""),
            b_seed=record["b_seed"],
            outcome=data.get("outcome") or record["outcome"] or "abandoned",
            turns=record["turns"],
            path=record["path"],
            target_spread=dict(data.get("target_spread", {})),
            items=record["items"],
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

    def preview_battle_calibration(self, profile_id: str) -> dict:
        """Fit a calibration model from this profile's Battle Compass runs.

        The only calibration path a Platinum profile has: the metronome fit needs the Blackthorn
        Magikarp matchup and the safari offset needs the Safari Zone, and neither exists outside
        HGSS -- so without this a Platinum profile stays on the bundled "Standard" model forever
        (notes/platinum.md section 6). Useful on HGSS too, where a Suicune or Lugia run was
        previously thrown away as diagnostic-only.

        Kept separate from `preview_calibration` rather than pooled, because whether a static
        A-press encounter shares the metronome run's load-path offset is unmeasured -- see
        `calibration.preview_battle_fit`.
        """
        p = self._load_profile(profile_id)
        battle_runs = self.list_runs(profile_id, kind="battle")
        return calibration_lib.preview_battle_fit(battle_runs, p.excluded_tags)

    def battle_run_exclude_reasons(self, profile_id: str) -> dict:
        """Why each battle run does or does not reach the battle fit. Mirrors
        `safari_run_exclude_reasons`, which does the same for the safari offset fit."""
        p = self._load_profile(profile_id)
        battle_runs = self.list_runs(profile_id, kind="battle")
        _records, pre_excluded = calibration_lib.effective_included(
            battle_runs, set(p.excluded_tags),
            record_fn=calibration_lib._record_for_battle_run)
        return pre_excluded

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
