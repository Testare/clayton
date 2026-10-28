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

Battle Compass adds :class:`PartyPokemon` and :class:`Hunt` (see
``notes/battle_compass.md`` sec 15.4).  The split there mirrors Expedition/Safari Compass: a
**Hunt is configuration** — the party you plan to bring, their held items, the target and the
ball — while the live encounter runs in Battle Compass and its mid-battle state is not
persisted.  Party Pokemon live on the **profile** (they are reused across hunts, like metronome
users); only the per-hunt held item belongs to the hunt.

Glass adds :class:`Seed` — a key seed worth keeping, with an initial time, a frame to route to,
notes, and a short history of identifications. It owns nothing and belongs to a profile
(``notes/glass.md``).
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

from claytonlib.battle.balls import TERRAIN_OTHER, TERRAINS as TERRANS_OK

#: What kind of encounter a Hunt is against. A static encounter is timed and its target is
#: generated when the battle starts; a roamer is found by walking and everything about it was
#: decided when the roam began (notes/roamers.md).
ENCOUNTER_STATIC = "static"
ENCOUNTER_ROAMER = "roamer"
ENCOUNTER_KINDS = (ENCOUNTER_STATIC, ENCOUNTER_ROAMER)
from claytonlib.games import canonical_game_key, game_name, tool_refusal
from claytonlib.metronome_abilities import ability_info, unsupported_abilities

# Metronome-user suitability (P0). See draft2 "Metronome Users".
_REQUIRED_SPECIES = "Chansey"
_REQUIRED_ABILITY = "Natural Cure"
_REQUIRED_MOVE = "Metronome"
# Abilities the simulation does not implement, and which WOULD change this battle -- so a
# user carrying one can't be selected in Metronome Compass (creation is never blocked; see
# hard_errors). Derived from claytonlib.metronome_abilities rather than listed here, so the
# block follows what is actually implemented instead of a parallel hand-maintained set: an
# ability that gains support stops blocking by virtue of its registry entry changing
# (clayton-2ae.5). Abilities that provably cannot affect this fight are classified NO_EFFECT
# there and never blocked, and one the registry has never heard of is UNKNOWN -- it warns,
# since "not yet judged" is a weaker claim than "judged, and it breaks the simulation".
HARD_ERROR_ABILITIES = unsupported_abilities()


def _new_id() -> str:
    """A short, collision-resistant id for a profile or expedition document."""
    return uuid.uuid4().hex[:12]


# The six stats, in the order the in-game summary screen shows them.
STAT_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")


# ---------------------------------------------------------------------------
# Party Pokemon (Battle Compass)
# ---------------------------------------------------------------------------


@dataclass
class PartyPokemon:
    """A Pokemon on the profile, available to any hunt.

    Stats are **entered directly off the in-game summary screen** rather than derived from
    IVs/EVs/nature: the game already shows the exact numbers, so asking for them is both
    simpler and less error-prone than asking for a spread (notes/battle_compass.md sec 15.4.1).
    Only *targets* have their stats derived, since their IVs come from RNG manipulation.

    `max_pp` is per move slot and accounts for PP Ups/Maxes, so it can exceed the move's base
    PP.  Held items are deliberately absent — they change per hunt and live on the Hunt.
    """

    id: int
    name: str
    species: str = ""
    level: int | None = None
    ability: str | None = None
    gender: str | None = None
    # Entered stats, keyed by STAT_KEYS.
    stats: dict = field(default_factory=dict)
    # Up to four move names, in slot order — the order the M1..M4 tokens refer to.
    moveset: list[str] = field(default_factory=list)
    #: Move NUMBER (1-4, as a string key so it survives JSON) -> max PP for that move.
    #:
    #: **One-based, unlike every slot index elsewhere in this project.** Move slots are 0-based
    #: in `moveset`, in `Action.move_slot`, in `move_info` and in the M1-M4 tokens; this one
    #: field is not, because that is how the party form has always written it and how every
    #: saved profile holds it. Read it through :meth:`pp_for_slot`, never directly.
    #:
    #: Reading it directly is what broke: `_configured_pp` looked up `str(slot)` with a 0-based
    #: slot, so move 2 got move 1's PP, move 3 got move 2's, move 4's recorded PP was never read
    #: at all, and move 1 fell through to the move's base PP. Everything the player SAW was
    #: 1-based and self-consistent -- the form, the read-back, the per-slot warning -- so only
    #: the simulator was wrong, and it was wrong by one slot in silence.
    max_pp: dict = field(default_factory=dict)

    def hard_errors(self) -> list[str]:
        """Reasons this Pokemon can't be taken into a Hunt.

        Battle Compass simulates the whole battle, so unlike a metronome user it cannot work
        around missing numbers: turn order needs an exact Speed, and the damage model needs
        the defences.  A Pokemon with no usable moves is *allowed* — Mamoswine's role in the
        reference fixture is exactly that — because a move slot the Pokemon lacks simply isn't
        an action the solver can choose (sec 12.5).
        """
        errors: list[str] = []
        if not self.species:
            errors.append("needs a species")
        if self.level is None or not 1 <= self.level <= 100:
            errors.append("needs a level between 1 and 100")
        missing = [k for k in STAT_KEYS if not isinstance(self.stats.get(k), int)]
        if missing:
            errors.append(
                "needs every stat entered from the summary screen (missing "
                + ", ".join(missing) + ")")
        if len(self.moveset) > 4:
            errors.append(f"has {len(self.moveset)} moves; a Pokemon can hold at most 4")
        return errors

    def warnings(self) -> list[str]:
        """Advisory notes — none of these block taking the Pokemon into a hunt."""
        notes: list[str] = []
        if not self.moveset:
            notes.append(
                "has no moves registered, so it can only use items, balls and switches. That "
                "is a legitimate role (a wall to revive behind), but it cannot attack — and a "
                "Pokemon with no usable moves is forced to Struggle if you ever pick Fight, "
                "which would KO a target at 1 HP.")
        for slot, move in enumerate(self.moveset):
            if self.pp_for_slot(slot) is None:
                notes.append(f"move {slot + 1} ({move}) has no max PP recorded; "
                             f"PP cannot be budgeted for it")
        if not self.ability:
            notes.append("has no ability recorded; entry abilities and damage modifiers "
                         "that depend on it will not be simulated")
        return notes

    def pp_for_slot(self, slot: int) -> int | None:
        """Recorded max PP for a **0-based** move slot, or None if it was never entered.

        The one place the 1-based storage of `max_pp` is converted. Every caller uses the
        project's 0-based slots and none of them has to remember that this field does not.

        Both `"1"` and `1` are accepted: the keys are strings once they have been through JSON,
        but a dict built in Python need not have been.
        """
        key = slot + 1
        recorded = self.max_pp.get(str(key), self.max_pp.get(key))
        return recorded if isinstance(recorded, int) and recorded > 0 else None

    @property
    def speed(self) -> int | None:
        value = self.stats.get("spe")
        return value if isinstance(value, int) else None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PartyPokemon":
        return cls(
            id=int(d["id"]),
            name=d["name"],
            species=d.get("species", ""),
            level=d.get("level"),
            ability=d.get("ability"),
            gender=d.get("gender"),
            stats={k: v for k, v in dict(d.get("stats", {})).items()},
            moveset=list(d.get("moveset", [])),
            max_pp=dict(d.get("max_pp", {})),
        )


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
        """Human-readable reasons this user may be unreliable for calibration (empty ==
        no concerns). Advisory only — the user is still fully creatable and selectable in
        Metronome Compass; the UI frames these as "you might experience more errors in
        metronome compass", not a block. See hard_errors for the set of issues that DO
        block selection in Metronome Compass specifically."""
        warnings: list[str] = []
        if self.species != _REQUIRED_SPECIES:
            warnings.append(
                f"Metronome Compass is built and verified specifically for Natural Cure "
                f"{_REQUIRED_SPECIES} — using {self.species} may produce errors"
            )
        if self.ability and self.ability != _REQUIRED_ABILITY:
            info = ability_info(self.ability)
            if info.is_supported:
                warnings.append(
                    f"ability should be {_REQUIRED_ABILITY} (this is {self.ability})")
            elif not info.blocks_selection:
                # UNKNOWN: an ability the registry has never judged. That is a weaker claim
                # than a named unsupported one, so it warns rather than blocking (the run is
                # the player's call), but it is never silent -- see metronome_abilities.
                warnings.append(
                    f"{info.reason} Metronome Compass may identify the wrong seed with "
                    f"this user."
                )
        return warnings

    def hard_errors(self) -> list[str]:
        """Reasons this user can't be SELECTED in Metronome Compass (e.g. New Run's user
        picker) — but a user can still always be created, viewed, and removed on the
        Profile page with these present; nothing here blocks add_metronome_user. The UI
        frames these as "cannot be used in Metronome Compass" (round 10 feedback: no "...
        yet" — that phrasing is only accurate for the hard-error abilities, which might
        genuinely gain support later; not knowing Metronome never will, since Metronome
        Compass has no way to calibrate off a user that can't use the move at all). Not
        knowing Metronome and not holding a Lagging Tail moved here from
        suitability_warnings (round 9 feedback) — Metronome Compass can't calibrate off a
        user that can't use the move or won't hold still for the timing check, so these
        are hard blocks, not advisory.

        Only a REGISTERED unsupported ability (Cute Charm) blocks. An ability the registry
        has never judged warns from suitability_warnings instead."""
        errors: list[str] = []
        info = ability_info(self.ability)
        if info.blocks_selection:
            # The registry's own reason, so the message says what this specific ability does
            # to the battle rather than one generic sentence for every blocked ability. Only
            # a NAMED unsupported ability lands here -- an unrecognised one warns instead.
            errors.append(
                f"{self.ability} is not simulated yet — {info.reason} "
                f"A metronome user with this ability can't be used for calibration."
            )
        if not any(m.lower() == _REQUIRED_MOVE.lower() for m in self.moveset):
            errors.append("does not know Metronome")
        if not self.lagging_tail:
            errors.append("is not holding a Lagging Tail")
        return errors

    @property
    def is_suitable(self) -> bool:
        return not (self.suitability_warnings() or self.hard_errors())

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
    # TID/SID aren't tracked -- this app does no shiny-checking logic that would need them.
    trainer_name: str = ""
    #: Which game this cartridge is, as a `claytonlib.games` KEY ("platinum"), not a display
    #: name. Stored as a key because the thing it replaced -- a free-text `version` holding
    #: "HeartGold" -- could not be branched on without string-matching, so nothing ever did:
    #: `targets.py` simply hardcoded SoulSilver's rows and a HeartGold player was silently
    #: simulated against the wrong four moves (clayton-6xu.1.1).
    #:
    #: Reads back through `games.canonical_game_key`, so profiles written with the old field
    #: migrate on load rather than needing a data migration. May be "" on a profile whose game
    #: was never set; `game_errors` is what refuses work in that case.
    game: str = ""
    console: str = ""  # free-text note; see the different-console caveat in the doc.
    metronome_users: list[MetronomeUser] = field(default_factory=list)
    # Monotonic; assigns the next metronome-user id and never rewinds, so ids are
    # never reused even after a user is removed.
    next_metronome_user_id: int = 1
    # Battle Compass party. Lives here rather than on the Hunt because the same Pokemon is
    # reused across hunts; only its held item is per-hunt (notes/battle_compass.md sec 15.4.1).
    party: list[PartyPokemon] = field(default_factory=list)
    next_party_pokemon_id: int = 1
    # Tags excluded wholesale from calibration (Review Data → Tags). Distinct from a run's own
    # `excluded` flag: excluding a tag here does NOT toggle individual runs' flags — a run's
    # effective-excluded state is the OR of both, and the UI shows "tag:<name>" for this case.
    excluded_tags: list[str] = field(default_factory=list)

    @property
    def game_name(self) -> str:
        """The game's display name, or ``""`` when unset. What the UI shows.

        A property rather than a stored field so there is exactly one spelling of the truth: the
        old setup stored the display name *as* the identity, which is how it ended up unusable for
        branching.
        """
        return game_name(self.game)

    def tool_refusal(self, tool: str) -> str:
        """Why `tool` cannot run against this profile's game, or ``""`` when it can.

        `tool` is one of `games.ALL_TOOLS`. Returns a sentence rather than a boolean because every
        caller needs to tell the player why — Diamond/Pearl and "Expeditions are HGSS-only" are
        different refusals and deserve different words.
        """
        return tool_refusal(self.game, tool)

    def get_party_pokemon(self, pokemon_id: int) -> PartyPokemon | None:
        return next((p for p in self.party if p.id == pokemon_id), None)

    def add_party_pokemon(self, name: str, **fields) -> PartyPokemon:
        """Add a party Pokemon with the next id.

        Unlike a metronome user, a party Pokemon IS editable — its stats change as it levels
        and its max PP changes with PP Ups — so `update_party_pokemon` exists too.  Creation
        only requires a name; anything `hard_errors()` reports instead blocks taking it into a
        Hunt, so a half-entered Pokemon can be saved and finished later.
        """
        name = name.strip()
        if not name:
            raise ValueError("party pokemon needs a name")
        pokemon = PartyPokemon(id=self.next_party_pokemon_id, name=name, **fields)
        self.next_party_pokemon_id += 1
        self.party.append(pokemon)
        return pokemon

    def update_party_pokemon(self, pokemon_id: int, **fields) -> PartyPokemon:
        pokemon = self.get_party_pokemon(pokemon_id)
        if pokemon is None:
            raise ValueError(f"no party pokemon with id {pokemon_id} in this profile")
        for key, value in fields.items():
            if not hasattr(pokemon, key) or key == "id":
                raise ValueError(f"cannot set {key!r} on a party pokemon")
            setattr(pokemon, key, value)
        return pokemon

    def remove_party_pokemon(self, pokemon_id: int) -> PartyPokemon:
        """Remove and return it. The id counter is not rewound, so hunts referencing a
        removed Pokemon stay unambiguous — they just cannot resolve it any more."""
        pokemon = self.get_party_pokemon(pokemon_id)
        if pokemon is None:
            raise ValueError(f"no party pokemon with id {pokemon_id} in this profile")
        self.party.remove(pokemon)
        return pokemon

    def get_metronome_user(self, user_id: int) -> MetronomeUser | None:
        return next((u for u in self.metronome_users if u.id == user_id), None)

    def add_metronome_user(self, name: str, **fields) -> MetronomeUser:
        """Create a metronome user with the next id. The user can create whatever
        metronome user they want here — even one with a hard_errors() issue (e.g. a
        calibration-breaking ability) — creation only ever requires a non-blank name; a
        hard_errors() issue instead blocks SELECTING that user in Metronome Compass (see
        MetronomeUser.hard_errors).

        Names need NOT be unique within a profile — the UI disambiguates same-named users
        for display by appending "#<id>" only when a collision actually exists (the id
        itself is always the real unique key runs reference).
        """
        name = name.strip()
        if not name:
            raise ValueError("metronome user needs a name")
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

    def set_tag_excluded(self, tag: str, excluded: bool) -> None:
        have = tag in self.excluded_tags
        if excluded and not have:
            self.excluded_tags.append(tag)
        elif not excluded and have:
            self.excluded_tags.remove(tag)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "trainer_name": self.trainer_name,
            "game": self.game,
            # Written alongside `game` so an export read by an older build still names the game.
            # Read back only as a fallback -- see from_dict.
            "version": self.game_name,
            "console": self.console,
            "metronome_users": [u.to_dict() for u in self.metronome_users],
            "next_metronome_user_id": self.next_metronome_user_id,
            "excluded_tags": self.excluded_tags,
            "party": [p.to_dict() for p in self.party],
            "next_party_pokemon_id": self.next_party_pokemon_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        return cls(
            name=d["name"],
            id=d.get("id") or _new_id(),
            trainer_name=d.get("trainer_name", ""),
            # `version` is the pre-Platinum spelling and held a display name; both resolve
            # through canonical_game_key, so no stored profile needs rewriting.
            game=canonical_game_key(d.get("game") or d.get("version") or ""),
            console=d.get("console", ""),
            metronome_users=[MetronomeUser.from_dict(u) for u in d.get("metronome_users", [])],
            excluded_tags=list(d.get("excluded_tags", [])),
            next_metronome_user_id=d.get("next_metronome_user_id", 1),
            # Absent on profiles written before Battle Compass existed.
            party=[PartyPokemon.from_dict(p) for p in d.get("party", [])],
            next_party_pokemon_id=d.get("next_party_pokemon_id", 1),
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
    kind: str = "metronome"  # "metronome" | "safari" | "battle"
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
    # Seed A's advance recipe, optionally recorded to test whether it correlates with a
    # safari run's frame_delta (the user is still verifying this hypothesis — see
    # notes/flagged_for_review.md; no fit consumes these yet, they're just captured so
    # historical runs aren't missing the data once it's confirmed). Matches the notebook's
    # save_safari_run(elm_calls=, chatot_flips=, advance_frame=) fields.
    elm_calls: int | None = None
    chatot_flips: float | None = None
    advance_frame: int | None = None
    # The human-readable "how to get there" text from Safari Compass's frame-route planner
    # (app.safari_compass.plan_frame_route / claytonlib.safari_advance), saved alongside the
    # run so it's still visible after the fact — not just during the live session.
    frame_guide: str = ""
    # -- Battle Compass runs (kind="battle") -------------------------------
    # The hunt this attempt came from. Runs are profile-owned like the others, so this is a
    # back-reference rather than ownership -- a hunt can be attempted many times, and deleting
    # one should not take its history with it.
    hunt_id: str = ""
    #: "caught" | "wrong_ball" | "wiped" | "abandoned". The thing a diagnostic record is for:
    #: a run that ended is only interesting alongside HOW it ended.
    outcome: str = ""
    turns: int | None = None
    #: The whole reported path, in token form -- the one field that makes a run replayable.
    path: str = ""
    #: The nature and IVs the run was actually simulated against, which on a non-key-seed Seed A
    #: are not the hunt's configured ones. Without it a saved run cannot be reproduced.
    target_spread: dict = field(default_factory=dict)
    #: Items spent, code -> count.
    items: dict = field(default_factory=dict)

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
            elm_calls=d.get("elm_calls"),
            chatot_flips=d.get("chatot_flips"),
            advance_frame=d.get("advance_frame"),
            frame_guide=d.get("frame_guide", ""),
            hunt_id=d.get("hunt_id", ""),
            outcome=d.get("outcome", ""),
            turns=d.get("turns"),
            path=d.get("path", ""),
            target_spread=dict(d.get("target_spread", {})),
            items=dict(d.get("items", {})),
        )


def _default_preferences() -> dict:
    return {
        "elm_calls_after_flips": 3,
        # "pokefinder" (paste a frame you found yourself) or "in_house" (search block_config
        # via claytonlib.safari_encounters) -- how the advance-frame guide picks a target
        # encounter frame.
        "target_frame_source": "in_house",
        # Machete search depth (turns) for Safari Compass Seed B's single-seed capture-path
        # prediction -- higher finds more paths but costs exponentially more compute. Matches
        # claytonlib.machete.MacheteOptions.max_turns_one's own default.
        "machete_max_turns": 50,
    }


@dataclass
class Expedition:
    """A quest for one Pokémon. References a profile; owns no runs or models itself."""

    name: str
    profile_id: str
    id: str = field(default_factory=_new_id)
    pokemon: str = ""
    safari_area: str = ""
    # How the encounter is triggered: "grass"/"surf" (Sweet Scent) or "old_rod"/"good_rod"/
    # "super_rod" (clayton-858). Defaults to grass, which is what every expedition saved
    # before water methods existed was implicitly hunting.
    safari_method: str = "grass"
    # Only meaningful for the rods: the lead's happiness bonus to the hook rate (one of
    # claytonlib.safari_encounters.HAPPINESS_BONUSES) and whether the lead has Suction Cups.
    # They don't change which slot a frame draws, but they decide which frames hook at all.
    fishing_happiness_bonus: int = 0
    fishing_suction_cups: bool = False
    block_config: dict = field(default_factory=dict)
    key_seed: int | None = None
    key_seed_advances: int | None = None
    # Last-used target for the Compass pages: {"initial_time": ..., "vector_ms": ...}
    last_target: dict = field(default_factory=dict)
    # Last-used Metronome Compass New Run defaults, so repeat hunts on the same expedition
    # don't need retyping: {"startrel", "seconds_window", "delay_window", "match_parity", "tag",
    # "sb_seconds_window", "sb_delay_window"} -- the sb_* pair is Seed B's OWN search window
    # (independent of Seed A's — the battle-delay guess may need a different range).
    last_metronome_defaults: dict = field(default_factory=dict)
    # Same idea, Safari Compass's own New Run:
    # {"startrel", "seconds_window", "delay_window", "match_parity", "tag"}
    last_safari_compass_defaults: dict = field(default_factory=dict)
    preferences: dict = field(default_factory=_default_preferences)
    # Set via "Mark as complete" on the Configure page, or offered after a successful Safari
    # Compass capture on the key seed (round 12 feedback). Purely a display/sort flag -- doesn't
    # gate any tool.
    completed: bool = False

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
            safari_method=d.get("safari_method") or "grass",
            fishing_happiness_bonus=int(d.get("fishing_happiness_bonus", 0) or 0),
            fishing_suction_cups=bool(d.get("fishing_suction_cups", False)),
            block_config=dict(d.get("block_config", {})),
            key_seed=d.get("key_seed"),
            key_seed_advances=d.get("key_seed_advances"),
            last_target=dict(d.get("last_target", {})),
            last_metronome_defaults=dict(d.get("last_metronome_defaults", {})),
            last_safari_compass_defaults=dict(d.get("last_safari_compass_defaults", {})),
            preferences={**_default_preferences(), **d.get("preferences", {})},
            completed=bool(d.get("completed", False)),
        )


# ---------------------------------------------------------------------------
# Hunt (Battle Compass)
# ---------------------------------------------------------------------------


@dataclass
class HuntSlot:
    """One party Pokemon brought on a hunt, plus the item it is holding for it."""

    pokemon_id: int
    held_item: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HuntSlot":
        return cls(pokemon_id=int(d["pokemon_id"]), held_item=d.get("held_item", ""))


@dataclass
class HuntTarget:
    """The Pokemon being caught, as configured.

    IVs and nature come from RNG manipulation and are entered by hand (Pokefinder), which is
    what lets the incoming-damage filter run at all — an unknown Sp. Atk would make that filter
    unsound rather than merely vague (notes/battle_compass.md sec 14.1).
    """

    species: str = ""
    level: int | None = None
    nature: str = ""
    # Keyed by STAT_KEYS; 0-31 each.
    ivs: dict = field(default_factory=dict)

    def hard_errors(self, game: str = "") -> list[str]:
        """Everything wrong with this target: its spread, and the encounter itself.

        `game` is the profile's game key, and it decides which encounter rows exist at all --
        Darkrai is Platinum's and Lugia's row on file is SoulSilver's. Empty means "unset", which
        filters nothing; see `targets.resolve`.
        """
        return self.spread_errors() + self.encounter_errors(game)

    @property
    def spread_is_blank(self) -> bool:
        """Nothing entered at all, as opposed to half-entered.

        The distinction is the one `Facade._target_spread_from_params` already draws and for the
        same reason: a nature without IVs is a half-filled form rather than a deliberate "I do
        not know this", and treating it as the latter would mix a nature from one Pokemon with
        assumed IVs -- stats that belong to no Pokemon at all, and no error anywhere.
        """
        return not self.nature and not any(
            isinstance(self.ivs.get(k), int) for k in STAT_KEYS)

    def spread_errors(self) -> list[str]:
        """Only what makes the SPREAD unusable -- a missing species, level, nature or IV.

        Split out from `hard_errors` because the two have different consumers. Deriving stats
        needs the spread and nothing else, so `hunt_readiness` gates the derived stats on this:
        an unconfigured species still has base stats worth showing, and suppressing them because
        the *encounter* is unsupported hides information that was perfectly good.
        """
        errors: list[str] = []
        if not self.species:
            errors.append("target needs a species")
        if self.level is None or not 1 <= self.level <= 100:
            errors.append("target needs a level between 1 and 100")
        if not self.nature:
            errors.append("target needs a nature (from Pokefinder)")
        missing = [k for k in STAT_KEYS if not isinstance(self.ivs.get(k), int)]
        if missing:
            errors.append("target needs every IV (missing " + ", ".join(missing) + ")")
        out_of_range = [k for k in STAT_KEYS
                        if isinstance(self.ivs.get(k), int) and not 0 <= self.ivs[k] <= 31]
        if out_of_range:
            errors.append("target IVs out of range: " + ", ".join(out_of_range))
        return errors

    def encounter_errors(self, game: str = "") -> list[str]:
        """Whether this species can be simulated at all, and at the level entered.

        Both are hard rather than advisory, and for the same reason: `execute_move` treats an
        effect it does not recognise as inert instead of refusing it, so a target with an
        unmodelled move is not approximately simulated -- it is confidently wrong on every turn
        that move fires, which eliminates the true seed. Better to refuse the run than to spend
        an hour of real play on predictions that cannot match.

        The level check exists because two of these encounters are version-split: Ho-Oh is Lv45
        in HeartGold and Lv70 in SoulSilver, with a different moveset each, and only one of the
        two is on file. A player on the other version would otherwise be simulated against four
        moves their Pokemon does not have.
        """
        from claytonlib.battle_compass.targets import (
            VERSION_SPLIT_LEVELS, encounter_key, resolve, supported, unsupported_moves,
        )

        if not self.species:
            return []
        key = encounter_key(self.species)
        try:
            key, row = resolve(key, game)
        except KeyError as problem:
            # `resolve` says which of the three mistakes it was -- a typo, a species met twice, or
            # the wrong cartridge -- and the last of those is the one a bare "not a configured
            # target" was actively misleading about. Its own message is carried through, with the
            # list of what IS available appended.
            available = supported(game)
            return [f"{problem.args[0]} Configured: {', '.join(available) or 'nothing'}."]
        errors: list[str] = []
        if self.level is not None and self.level != row.level:
            note = VERSION_SPLIT_LEVELS.get(key)
            errors.append(
                f"the {self.species} on file is the Lv{row.level} encounter, not Lv{self.level}"
                + (f" -- Lv{note[0]} is {note[1]}, and it is not configured" if note else ""))
        _, problem_text = unsupported_moves(key, game)
        if problem_text:
            errors.append(problem_text)
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HuntTarget":
        return cls(species=d.get("species", ""), level=d.get("level"),
                   nature=d.get("nature", ""), ivs=dict(d.get("ivs", {})))


@dataclass
class Hunt:
    """Configuration for one Battle Compass capture attempt.

    A Hunt is **configuration and planning only** — the party you intend to bring, their held
    items, the target, the ball, and the seed targeting.  The live encounter runs in Battle
    Compass and its mid-battle state is not persisted; finished attempts are saved as run
    records instead.  That split mirrors Expedition/Safari Compass exactly
    (notes/battle_compass.md sec 15.4).

    There is no chart equivalent: nothing here needs to *hit* a seed, only to contain the true
    one in its candidate window, so the seed targeting exists to centre that window rather than
    to be optimised.
    """

    name: str
    profile_id: str
    id: str = field(default_factory=_new_id)
    target: HuntTarget = field(default_factory=HuntTarget)
    # The party for this hunt, in send-out order; references Profile.party ids.
    party: list[HuntSlot] = field(default_factory=list)
    # The single ball we intend to catch it in. No fallback -- the solver's goal set is one
    # threshold throughout.
    capture_ball: str = ""
    # Seed targeting, as for an Expedition: these centre the candidate window (sec 17.1).
    key_seed: int | None = None
    key_seed_advances: int | None = None
    initial_time: str = ""      # ISO-8601; chosen from the seed's possible times, not optimised
    vector_ms: int | None = None
    # Last-used target and Metronome Compass defaults, exactly as an Expedition keeps them, so
    # the shared calibration tools can run against a Hunt without retyping.
    last_target: dict = field(default_factory=dict)
    last_metronome_defaults: dict = field(default_factory=dict)
    # Roamer/Elm search defaults for the run page's Seed A step -- starting positions, the two
    # window sizes and the parity checkbox. Kept per hunt for the same reason Safari Compass
    # keeps them per expedition: the roamers' starting positions are a property of the save
    # file, so retyping them every run is pure friction.
    seed_a_defaults: dict = field(default_factory=dict)
    # NB: no calibration_model_id. Calibration models live on the PROFILE with one marked
    # active, and every profile is seeded with a bundled "Standard" model active by default --
    # so there is never a model to pick, and an Expedition does not carry one either. The Hunt
    # simply uses whatever its profile has active; Review Data is where that gets changed.
    # Candidate search window around the centre seed.
    seconds_window: int = 2
    delay_window: int = 60
    # Where the encounter happens, for the conditional balls: "other", "cave" or "water".
    # Terrain is a property of the TILE you stand on, not of the map (CalcTerrain,
    # pokeplatinum src/field_battle_data_transfer.c:467-494), which is why it is configured here
    # rather than derived -- a Dusk Ball is x3.5 in any cave at any hour, and a Dive Ball is
    # x3.5 only on water. Time of day is NOT configured alongside it: it is derivable from the
    # key seed's own hour byte (notes/platinum.md section 5.3).
    terrain: str = TERRAIN_OTHER
    # Whether this species is already registered as CAUGHT in the Pokedex (Repeat Ball x3).
    target_registered: bool = False
    # The advance frame a freshly loaded save sits on at this venue, which in Platinum replaces
    # HGSS's REL cost as the anchor for counting. Zero unless a venue is known to differ -- and
    # note the published guides are 1-based where this project is 0-based
    # (claytonlib.platinum_advance.PLATINUM_START_FRAME).
    start_frame: int = 0
    #: Whether the target is a ROAMER, which changes how the seed is acquired rather than how
    #: hard the battle is (notes/roamers.md sec 8). Not configured by the player: it is read off
    #: the encounter row, because a player cannot make Cresselia static. Stored so a saved hunt
    #: and its run records agree about which kind of run they describe even if the table changes.
    #:
    #: What it switches, all of it in the facade and the run page: there is no Seed A to identify
    #: and no frame to route to, the vector is a measured stopwatch reading rather than a
    #: commanded countdown, and the target's spread cannot come from the key seed.
    encounter_kind: str = ENCOUNTER_STATIC
    #: The HP the target will be at when the battle OPENS, for a roamer -- or None for "full".
    #:
    #: A roamer brings its damage with it: `RoamerAfterBattle_UpdateRoamers` writes HP and status
    #: back to the save after any battle that is neither a win-with-KO nor a capture, and
    #: `AddRoamerToEnemyParty` reads them out again next encounter (notes/roamers.md sec 3). So the
    #: usual plan is to chip it to 1 and sleep it in a throwaway encounter and then hunt the seed
    #: with the chip phase already done -- which the simulation has to be told, because every
    #: prediction from turn 1 depends on it.
    #:
    #: Meaningless for a static encounter, which is always generated at full HP, and refused there
    #: rather than ignored.
    opening_hp: int | None = None
    #: The status the target will be in when the battle opens: "" for none, else a
    #: `battle_compass.state.Status` value ("sleep", "paralysis", ...).
    opening_status: str = ""
    #: Remaining sleep turns, when the opening status is sleep. **Uncertain by nature**: the
    #: duration was rolled in the prep encounter and the counter did not tick while the roamer was
    #: out of battle, so the player did not see it and cannot know it (clayton-957.35.21). Stored
    #: so a player who has deduced it can say so; left at 0 it means "we do not know", which the
    #: facade turns into the ROM's own maximum rather than into zero -- a zero counter would wake
    #: it on its very first turn, which is the one value we can be sure is wrong.
    opening_sleep_turns: int = 0
    #: Stopwatch reading in ms, load press to encounter, for a roamer hunt. Kept SEPARATE from
    #: `vector_ms` on purpose: the two are different quantities measured different ways, and a
    #: single field would let a static hunt's calibrated countdown be read as a stopwatch
    #: reading or the reverse -- a silent, confident error of hundreds of frames. The facade
    #: chooses which one to centre on from `encounter_kind` and never from which is populated.
    stopwatch_ms: int | None = None
    completed: bool = False

    @property
    def is_roamer(self) -> bool:
        return self.encounter_kind == ENCOUNTER_ROAMER

    @property
    def centring_ms(self) -> "int | float | None":
        """The number this hunt's candidate window is centred on, whichever kind it is."""
        return self.stopwatch_ms if self.is_roamer else self.vector_ms

    def hard_errors(self, profile: "Profile | None" = None) -> list[str]:
        """Reasons Battle Compass cannot start from this hunt."""
        errors: list[str] = []
        game = profile.game if profile is not None else ""
        # **A roamer's spread cannot be looked up, so a blank one is allowed.** It was fixed when
        # the roam started and no seed names it (notes/roamers.md sec 7), so demanding it would
        # refuse a run over information the player cannot obtain -- while the encounter errors,
        # which are about whether the battle can be SIMULATED at all, still apply. A half-entered
        # spread stays an error either way: see `HuntTarget.spread_is_blank`.
        if self.is_roamer and self.target.spread_is_blank:
            errors.extend(self.target.encounter_errors(game))
        else:
            errors.extend(self.target.hard_errors(game))
        if not self.capture_ball:
            errors.append("needs a capture ball")
        elif profile is not None:
            errors.extend(self._ball_errors(profile))
        if self.terrain not in TERRANS_OK:
            errors.append(f"terrain must be one of {', '.join(TERRANS_OK)}")
        if not self.party:
            errors.append("needs at least one party pokemon")
        if self.key_seed is None:
            errors.append("needs a key seed")
        if not self.initial_time:
            errors.append("needs an initial time")
        if self.encounter_kind not in ENCOUNTER_KINDS:
            errors.append(f"encounter kind must be one of {', '.join(ENCOUNTER_KINDS)}")
        if self.is_roamer:
            # A roamer has no commanded countdown to report, so Vector ms is not merely absent
            # here -- it is the wrong question. What it has is a stopwatch reading.
            if self.stopwatch_ms is None:
                errors.append("needs a stopwatch reading (load press to encounter, in ms)")
            elif self.stopwatch_ms <= 0:
                errors.append("the stopwatch reading must be greater than zero")
            errors.extend(self._opening_errors())
        elif self.vector_ms is None:
            errors.append("needs a Vector ms")
        if profile is not None:
            for slot in self.party:
                pokemon = profile.get_party_pokemon(slot.pokemon_id)
                if pokemon is None:
                    errors.append(f"party pokemon #{slot.pokemon_id} is no longer on the profile")
                else:
                    errors.extend(f"{pokemon.name}: {e}" for e in pokemon.hard_errors())
        return errors

    def _opening_errors(self) -> list[str]:
        """Whether the declared opening state is one the game could actually produce.

        Hard rather than advisory, and for the reason `HuntTarget.encounter_errors` gives: the
        simulation consumes these numbers from turn 1, so a wrong one is not a vague run but a
        confidently wrong one. A declared 0 HP is the sharp case -- a fainted roamer is a roamer
        whose slot the save already zeroed, so there is nothing to hunt.
        """
        from claytonlib.battle_compass.state import Status

        errors: list[str] = []
        if self.opening_hp is not None and self.opening_hp < 1:
            errors.append("the target's opening HP must be at least 1 (a roamer that reached 0 "
                          "is gone from the save)")
        known = {s.value for s in Status}
        if self.opening_status and self.opening_status not in known:
            errors.append(f"opening status must be one of {', '.join(sorted(known))}")
        return errors

    def _ball_errors(self, profile: "Profile") -> list[str]:
        """Whether the chosen ball exists in this profile's game.

        A hard error rather than a warning: a Fast Ball on a Platinum cartridge is not a ball the
        player can throw, so a plan built around one is a plan they cannot execute. Mirrors the
        unsupported-move refusal — better to refuse the configuration than to simulate an hour of
        a run that could not happen.
        """
        from claytonlib.battle.balls import ball, balls_for_game
        try:
            chosen = ball(self.capture_ball)
        except ValueError as problem:
            return [str(problem)]
        available = balls_for_game(profile.game)
        if chosen not in available:
            return [f"{chosen.name} does not exist in {profile.game_name or 'this game'}"]
        return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "profile_id": self.profile_id,
            "target": self.target.to_dict(),
            "party": [s.to_dict() for s in self.party],
            "capture_ball": self.capture_ball,
            "key_seed": self.key_seed,
            "key_seed_advances": self.key_seed_advances,
            "initial_time": self.initial_time,
            "vector_ms": self.vector_ms,
            "last_target": self.last_target,
            "last_metronome_defaults": self.last_metronome_defaults,
            "seed_a_defaults": self.seed_a_defaults,
            "seconds_window": self.seconds_window,
            "delay_window": self.delay_window,
            "terrain": self.terrain,
            "target_registered": self.target_registered,
            "start_frame": self.start_frame,
            "encounter_kind": self.encounter_kind,
            "stopwatch_ms": self.stopwatch_ms,
            "opening_hp": self.opening_hp,
            "opening_status": self.opening_status,
            "opening_sleep_turns": self.opening_sleep_turns,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Hunt":
        return cls(
            name=d["name"],
            profile_id=d["profile_id"],
            id=d.get("id") or _new_id(),
            target=HuntTarget.from_dict(d.get("target", {})),
            party=[HuntSlot.from_dict(s) for s in d.get("party", [])],
            capture_ball=d.get("capture_ball", ""),
            key_seed=d.get("key_seed"),
            key_seed_advances=d.get("key_seed_advances"),
            initial_time=d.get("initial_time", ""),
            vector_ms=d.get("vector_ms"),
            last_target=dict(d.get("last_target", {})),
            last_metronome_defaults=dict(d.get("last_metronome_defaults", {})),
            seed_a_defaults=dict(d.get("seed_a_defaults", {})),
            seconds_window=d.get("seconds_window", 2),
            delay_window=d.get("delay_window", 60),
            # Absent on hunts written before the conditional balls needed them.
            terrain=d.get("terrain") or TERRAIN_OTHER,
            target_registered=bool(d.get("target_registered", False)),
            start_frame=int(d.get("start_frame") or 0),
            # Every hunt written before roamers existed is a static one, which is also what an
            # unrecognised value degrades to -- a hunt is not worth refusing to load over.
            encounter_kind=(d.get("encounter_kind") if d.get("encounter_kind") in ENCOUNTER_KINDS
                            else ENCOUNTER_STATIC),
            stopwatch_ms=d.get("stopwatch_ms"),
            opening_hp=d.get("opening_hp"),
            opening_status=d.get("opening_status", "") or "",
            opening_sleep_turns=int(d.get("opening_sleep_turns") or 0),
            completed=bool(d.get("completed", False)),
        )


# ---------------------------------------------------------------------------
# Seed (Glass)
# ---------------------------------------------------------------------------

#: How many identifications a Seed's recent history keeps. Deliberately small and hard --
#: Glass's history is a scratchpad for "which seed did I land on just now", not a record, and
#: nothing fits it either (both calibration fits need a vector ms and a Seed B, which Glass has
#: neither of -- see notes/glass.md).
SEED_HISTORY_LIMIT = 10


@dataclass
class Seed:
    """A key seed worth keeping, and the whole of the Glass page's configuration.

    Smaller than an Expedition or a Hunt on purpose: a Seed is not a quest, it is a seed you
    want to be able to come back to.  There is no name and no uniqueness rule -- `label` is
    optional and the hex seed is always displayed beside it, so two Seeds may legitimately share
    a key seed (the same seed loaded at different times, or kept for different reasons) and the
    document id stays the only real key, as for a metronome user.

    `seed_a_defaults` exists for the same reason a Hunt has one: the roamers' starting positions
    are a property of the save file, so retyping them every visit is pure friction.  The live
    identification is NOT stored -- reopening the page starts clean, like every other compass;
    `history` is written only by an explicit "Save to history".
    """

    profile_id: str
    id: str = field(default_factory=_new_id)
    label: str = ""
    key_seed: int | None = None
    # ISO-8601, and unlike every other tool's initial time this one's YEAR matters: Glass shows
    # an absolute delay, and seed_for folds (delay + year - 2000) into the seed's low 16 bits.
    initial_time: str = ""
    # The advance frame the route planner aims at unless the page is told otherwise.
    default_frame: int | None = None
    notes: str = ""
    seed_a_defaults: dict = field(default_factory=dict)
    # Newest first, at most SEED_HISTORY_LIMIT entries, repeats included.
    history: list = field(default_factory=list)

    def add_history(self, entry: dict) -> list:
        """Record one identification, evicting the oldest past the limit.

        Repeats are kept: identifying the same seed twice is two entries, because "I landed here
        again" is exactly the thing the history is for.
        """
        self.history.insert(0, dict(entry))
        del self.history[SEED_HISTORY_LIMIT:]
        return self.history

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Seed":
        return cls(
            profile_id=d["profile_id"],
            id=d.get("id") or _new_id(),
            label=d.get("label", ""),
            key_seed=d.get("key_seed"),
            initial_time=d.get("initial_time", ""),
            default_frame=d.get("default_frame"),
            notes=d.get("notes", ""),
            seed_a_defaults=dict(d.get("seed_a_defaults", {})),
            history=[dict(h) for h in d.get("history", [])][:SEED_HISTORY_LIMIT],
        )


# ---------------------------------------------------------------------------
# Chart (a strategy+criteria pairing; the canon map is built against this)
# ---------------------------------------------------------------------------

@dataclass
class Chart:
    """A named strategy/criteria selection, scoped to an expedition (pokemon + key seed come
    from there). Model-independent by design (claytonlib.chart.canon) — the canon map this
    charts builds is reused across calibration-model refits, only the ranking changes.
    """

    expedition_id: str
    name: str
    strategy_name: str
    criteria_name: str
    id: str = field(default_factory=_new_id)
    # The delay-window (seconds after button press) the canon map is built to cover.
    setup_delay_seconds: int = 0
    max_target_seconds: int = 300
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chart":
        return cls(
            expedition_id=d["expedition_id"],
            name=d["name"],
            strategy_name=d["strategy_name"],
            criteria_name=d["criteria_name"],
            id=d.get("id") or _new_id(),
            setup_delay_seconds=d.get("setup_delay_seconds", 0),
            max_target_seconds=d.get("max_target_seconds", 300),
            created_at=d.get("created_at") or _now_iso(),
        )


# ---------------------------------------------------------------------------
# Target (a saved candidate initial time + Vector ms, with its landing stats)
# ---------------------------------------------------------------------------

@dataclass
class Target:
    """An initial time that hits the key seed plus a Vector ms aimed at a good Seed B —
    saved from a chart's ranking, carrying the landing stats it was picked with."""

    expedition_id: str
    chart_id: str
    name: str
    initial_time: str  # ISO
    vector_ms: int      # = M, the commanded countdown (chart's "M"; identical quantity)
    target_delay: int   # = F_b, the expected battle frame (for compass identification)
    p: float             # capture probability at the time this was saved
    sigma: float
    second: int | None = None
    mdmsh: list = field(default_factory=list)  # [mdms, hour] — informational
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Target":
        return cls(
            expedition_id=d["expedition_id"],
            chart_id=d["chart_id"],
            name=d["name"],
            initial_time=d["initial_time"],
            vector_ms=d["vector_ms"],
            target_delay=d["target_delay"],
            p=d["p"],
            sigma=d["sigma"],
            second=d.get("second"),
            mdmsh=list(d.get("mdmsh", [])),
            id=d.get("id") or _new_id(),
            created_at=d.get("created_at") or _now_iso(),
        )


# ---------------------------------------------------------------------------
# CalibrationModelDoc (a saved, profile-scoped timer-calibration fit)
# ---------------------------------------------------------------------------

@dataclass
class CalibrationModelDoc:
    """One saved calibration fit for a profile.

    `artifact` is the modelset shape claytonlib.calibration.CalibrationModel.save_set/
    load_set/_from_artifact already read and write ({"format": "modelset", "default": ...,
    "models": {"linear": {...}, "quad": {...}}}) — app.chart hands the resolved
    CalibrationModel objects straight to claytonlib's scorer, no reshaping needed.
    `number` is a strict per-profile increment (never reused); `active` marks the one
    Safari Chart currently uses (exactly one per profile, enforced by the facade).
    """

    profile_id: str
    number: int
    artifact: dict
    stats: dict = field(default_factory=dict)
    id: str = field(default_factory=_new_id)
    name: str = ""
    active: bool = False
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CalibrationModelDoc":
        return cls(
            profile_id=d["profile_id"],
            number=d["number"],
            artifact=dict(d.get("artifact", {})),
            stats=dict(d.get("stats", {})),
            id=d.get("id") or _new_id(),
            name=d.get("name", ""),
            active=bool(d.get("active", False)),
            created_at=d.get("created_at") or _now_iso(),
        )
