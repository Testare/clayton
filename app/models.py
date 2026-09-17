"""models.py — app entity model (the pieces the entry flow needs).

Covers the entities behind the Profile/Expedition entry flow: :class:`Profile`,
:class:`MetronomeUser`, and :class:`Expedition`. Runs, models, targets and charts
get added as those areas land, so they aren't guessed at here.

Design points that come straight from ``notes/clayton_v1_draft2.md``:

* Runs, models and metronome users belong to the **profile** (a console/cartridge
  identity), shared across every expedition that references it.
* Each metronome user gets a **profile-unique id** from a monotonic per-profile
  counter that never reuses a value, and a name unique within the profile.
* Metronome users are **immutable** — there is deliberately no update method; to
  change one, add a new user and remove the old.
* "Vector ms" is the term for the value that aims a run at a good Seed B.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

# Metronome-user suitability (P0). See draft2 "Metronome Users".
_REQUIRED_SPECIES = "Chansey"
_REQUIRED_ABILITY = "Natural Cure"
_REQUIRED_MOVE = "Metronome"


def _new_id() -> str:
    """A short, collision-resistant id for a profile or expedition document."""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Metronome user
# ---------------------------------------------------------------------------

@dataclass
class MetronomeUser:
    """A party Pokémon used to calibrate via Metronome Compass. Immutable once made."""

    id: int
    name: str
    species: str = _REQUIRED_SPECIES
    gender: str | None = None
    level: int | None = None
    moveset: list[str] = field(default_factory=list)
    ability: str | None = None
    lagging_tail: bool = False

    def suitability_warnings(self) -> list[str]:
        """Human-readable reasons this user may be unsuitable (empty == suitable)."""
        warnings: list[str] = []
        if self.species != _REQUIRED_SPECIES:
            warnings.append(
                f"only {_REQUIRED_SPECIES} is supported right now (this is {self.species})"
            )
        if self.ability and self.ability != _REQUIRED_ABILITY:
            warnings.append(f"ability should be {_REQUIRED_ABILITY} (this is {self.ability})")
        if not any(m.lower() == _REQUIRED_MOVE.lower() for m in self.moveset):
            warnings.append("does not know Metronome")
        if not self.lagging_tail:
            warnings.append("is not holding a Lagging Tail")
        return warnings

    @property
    def is_suitable(self) -> bool:
        return not self.suitability_warnings()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MetronomeUser":
        return cls(
            id=d["id"],
            name=d["name"],
            species=d.get("species", _REQUIRED_SPECIES),
            gender=d.get("gender"),
            level=d.get("level"),
            moveset=list(d.get("moveset", [])),
            ability=d.get("ability"),
            lagging_tail=bool(d.get("lagging_tail", False)),
        )


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@dataclass
class Profile:
    """A console/cartridge identity that owns runs, models and metronome users."""

    name: str
    id: str = field(default_factory=_new_id)
    tid: int | None = None
    sid: int | None = None
    console: str = ""  # free-text note; see the different-console caveat in the doc.
    metronome_users: list[MetronomeUser] = field(default_factory=list)
    # Monotonic; assigns the next metronome-user id and never rewinds, so ids are
    # never reused even after a user is removed.
    next_metronome_user_id: int = 1

    def get_metronome_user(self, user_id: int) -> MetronomeUser | None:
        return next((u for u in self.metronome_users if u.id == user_id), None)

    def add_metronome_user(self, name: str, **fields) -> MetronomeUser:
        """Create a metronome user with the next id. Raises on a duplicate name."""
        name = name.strip()
        if not name:
            raise ValueError("metronome user needs a name")
        if any(u.name.lower() == name.lower() for u in self.metronome_users):
            raise ValueError(f"a metronome user named {name!r} already exists in this profile")
        user = MetronomeUser(id=self.next_metronome_user_id, name=name, **fields)
        self.next_metronome_user_id += 1
        self.metronome_users.append(user)
        return user

    def remove_metronome_user(self, user_id: int) -> MetronomeUser:
        """Remove and return the user. Raises if it isn't in this profile.

        Note the counter is *not* rewound, so a later user never reuses this id and
        runs that reference the removed id stay unambiguous (they just can't resolve
        the user any more — the app shows them as an unknown user).
        """
        user = self.get_metronome_user(user_id)
        if user is None:
            raise ValueError(f"no metronome user with id {user_id} in this profile")
        self.metronome_users.remove(user)
        return user

    @property
    def has_valid_metronome_user(self) -> bool:
        return any(u.is_suitable for u in self.metronome_users)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tid": self.tid,
            "sid": self.sid,
            "console": self.console,
            "metronome_users": [u.to_dict() for u in self.metronome_users],
            "next_metronome_user_id": self.next_metronome_user_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            name=d["name"],
            id=d.get("id") or _new_id(),
            tid=d.get("tid"),
            sid=d.get("sid"),
            console=d.get("console", ""),
            metronome_users=[MetronomeUser.from_dict(u) for u in d.get("metronome_users", [])],
            next_metronome_user_id=d.get("next_metronome_user_id", 1),
        )


# ---------------------------------------------------------------------------
# Expedition
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Run (a saved Compass run — profile-scoped)
# ---------------------------------------------------------------------------

@dataclass
class Run:
    """One saved Metronome/Safari Compass run. Owned by a profile, not an expedition.

    Shaped to stay compatible with the calibration record (``a_seed`` / ``b_seed``,
    ``vector_ms`` = the aimed timer value) so these can feed the fit later, and carries
    the app-side extras from draft2: the metronome user's id and an exclusion flag.
    """

    profile_id: str
    kind: str = "metronome"  # "metronome" | "safari"
    id: str = field(default_factory=_new_id)
    tag: str = ""
    vector_ms: int | None = None
    target_timer_calibration: int = 0
    notes: str = ""
    metronome_user_id: int | None = None  # metronome runs only
    a_seed: dict = field(default_factory=dict)
    b_seed: dict = field(default_factory=dict)
    saved_at: str = field(default_factory=_now_iso)
    excluded: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        return cls(
            profile_id=d["profile_id"],
            kind=d.get("kind", "metronome"),
            id=d.get("id") or _new_id(),
            tag=d.get("tag", ""),
            vector_ms=d.get("vector_ms"),
            target_timer_calibration=d.get("target_timer_calibration", 0),
            notes=d.get("notes", ""),
            metronome_user_id=d.get("metronome_user_id"),
            a_seed=dict(d.get("a_seed", {})),
            b_seed=dict(d.get("b_seed", {})),
            saved_at=d.get("saved_at") or _now_iso(),
            excluded=bool(d.get("excluded", False)),
        )


def _default_preferences() -> dict:
    return {"elm_calls_after_flips": 3}


@dataclass
class Expedition:
    """A quest for one Pokémon. References a profile; owns no runs or models itself."""

    name: str
    profile_id: str
    id: str = field(default_factory=_new_id)
    pokemon: str = ""
    safari_area: str = ""
    block_config: dict = field(default_factory=dict)
    chatots: int = 0
    key_seed: int | None = None
    key_seed_advances: int | None = None
    # Last-used target for the Compass pages: {"initial_time": ..., "vector_ms": ...}
    last_target: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=_default_preferences)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Expedition":
        return cls(
            name=d["name"],
            profile_id=d["profile_id"],
            id=d.get("id") or _new_id(),
            pokemon=d.get("pokemon", ""),
            safari_area=d.get("safari_area", ""),
            block_config=dict(d.get("block_config", {})),
            chatots=d.get("chatots", 0),
            key_seed=d.get("key_seed"),
            key_seed_advances=d.get("key_seed_advances"),
            last_target=dict(d.get("last_target", {})),
            preferences={**_default_preferences(), **d.get("preferences", {})},
        )
