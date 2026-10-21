"""balls.py — which ball exists in which game, and what it actually multiplies.

Until Platinum this table did not need to exist. Every HGSS target/ball pairing the project had
reached was ×1 — Suicune out of a Fast Ball it does not match, the tower birds out of a Luxury or
Love Ball that have no case in the ROM's switch (notes/battle_compass_next_targets.md §3) — so
`app/facade.py` set only `fast_ball_matched` and `HuntConfig.capture_ball_multiplier` was never
assigned at all. Nothing was wrong, because nothing was multiplied.

Platinum ends that. It has **no apricorn balls**, and gives the conditional balls their multiplier
directly in `BattleScript_CalcCatchShakes` (`src/battle/battle_script.c:10922-10974`) — so the
obvious choices against a legendary are no longer ×1, and two of them are not even *constant*:

* **Quick Ball is ×4 on turn 1 only**, so a throw's `b` depends on when it happens;
* **Timer Ball climbs** `10 + totalTurns` to a ×4 ceiling, so `b` *improves* as a run goes on;
* **Dusk Ball is ×3.5 at night or in a cave**, so it depends on the key seed's own hour (the hour
  is bits 16-23 of the seed) and on the venue.

That is why this module returns a :class:`BallEffect` from a :class:`ThrowContext` rather than
exposing a constant. The solver already asks for `b` "at one moment" (`solver.target_threshold`),
so a multiplier that moves with the turn fits where a constant used to sit.

**Two mechanisms, not one** — as `catch.py` says: a standard or conditional ball sets the
*multiplier*, while an apricorn ball scales the *catch rate* and is then clamped to 1..255. Both
come back in one `BallEffect` so no caller has to know which kind it was holding.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from claytonlib.battle.catch import (
    BALL_DIVE_MATCHED, BALL_DUSK_MATCHED, BALL_GREAT, BALL_NEST_MATCHED, BALL_NET_MATCHED,
    BALL_POKE, BALL_QUICK_MATCHED, BALL_REPEAT_MATCHED, BALL_SAFARI, BALL_TIMER_MATCHED,
    BALL_ULTRA, apricorn_catch_rate,
)
from claytonlib.games import game_keys

#: Terrain values the ball rules care about. `CalcTerrain` derives terrain from the TILE the player
#: stands on (`src/field_battle_data_transfer.c:467-494`), testing cave floor and surfable water
#: before falling back to the map's battle background — so "in a cave" is a property of where you
#: are standing, not of the map's name.
TERRAIN_CAVE = "cave"
TERRAIN_WATER = "water"
TERRAIN_OTHER = "other"
TERRAINS = (TERRAIN_OTHER, TERRAIN_CAVE, TERRAIN_WATER)

#: The Dusk Ball's night, in the three buckets `safari_encounters.time_of_day` already produces.
#:
#: The ROM tests `TIMEOFDAY_NIGHT || TIMEOFDAY_LATE_NIGHT` and **not** twilight
#: (`src/battle/battle_script.c:10961-10967`). Platinum's five buckets are late night 0-3, morning
#: 4-9, day 10-16, twilight 17-19, night 20-23, so the ROM's "night or late night" is hours 20-3 —
#: which is *exactly* the three-bucket reading's `night` (notes/platinum.md §4.3). The collapse is
#: lossless for this purpose, which is why there is one time-of-day function and not two.
DUSK_BALL_BUCKET = "night"

_ALL_GAMES = frozenset(game_keys())
_HGSS = frozenset(("heartgold", "soulsilver"))
_SINNOH = frozenset(("platinum", "diamond", "pearl"))


@dataclass(frozen=True)
class ThrowContext:
    """Everything outside the ball itself that can change what it is worth.

    All defaulted, and the defaults are the pessimistic ones (no condition met), so a caller that
    does not know a field cannot accidentally claim a bonus.
    """
    #: Completed turns, i.e. the ROM's `totalTurns`. Quick Ball wants `< 1`; Timer Ball adds it.
    turn: int = 0
    terrain: str = TERRAIN_OTHER
    #: "morning" / "day" / "night" — `safari_encounters.time_of_day`'s buckets.
    time_of_day: str = ""
    #: The target's types, as `base_stats.json` spells them ("Water", "Bug", ...).
    target_types: tuple[str, ...] = ()
    target_level: int = 1
    target_base_speed: int = 0
    #: Whether this species is already registered as *caught* in the Pokedex (Repeat Ball).
    registered: bool = False


@dataclass(frozen=True)
class BallEffect:
    """What a ball does to a throw.

    `catch_rate` is the species rate after any apricorn scaling; `multiplier` is the ROM's
    `ballMod`, in tenths. Feed both to `catch.catch_value`.
    """
    catch_rate: int
    multiplier: int = BALL_POKE
    #: True for the Master Ball, which skips the shake rolls outright.
    guaranteed: bool = False
    #: Why this ball is worth what it is worth, for the UI to show beside the choice.
    reason: str = ""
    #: Set when the ball's rule is NOT modelled and ×1 is a fallback rather than the truth.
    unmodelled: str = ""


@dataclass(frozen=True)
class Ball:
    """One ball: where it exists, and how it changes a throw."""
    name: str
    games: frozenset[str] = field(default_factory=lambda: _ALL_GAMES)
    #: Unconditional multiplier in tenths, for the plain balls.
    multiplier: int = BALL_POKE
    #: Name of the conditional rule in `_CONDITIONAL`, when it has one.
    rule: str = ""
    #: An apricorn ball scales the catch rate instead; the name of its rule in `_APRICORN`.
    apricorn: str = ""
    guaranteed: bool = False
    note: str = ""

    @property
    def key(self) -> str:
        return ball_key(self.name)


def ball_key(name: str) -> str:
    """A ball name reduced to a lookup key: lowercase ASCII letters and digits only.

    Like `damage.item_key`, and for the same reason — a table keyed on `strip().lower()` matches
    the UI's spelling and silently misses the player's. But **one step further than `item_key`**,
    because of the Poké Ball: `"é".isalnum()` is True in Python, so dropping non-alphanumerics
    leaves the accent in place and `"poke ball"` — what anyone actually types — fails to match
    `"Poké Ball"`. Decomposing first turns `é` into `e` plus a combining mark, and the mark is not
    alphanumeric, so it goes.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    return "".join(ch for ch in decomposed.lower() if ch.isalnum() and ch.isascii())


# --- the conditional rules, transcribed from BattleScript_CalcCatchShakes -------------------
#
# `src/battle/battle_script.c:10922-10974` (Platinum) and the equivalent in pokeheartgold. Each
# returns (multiplier, reason) and is responsible for saying WHY, since the UI shows that.

def _net(ctx: ThrowContext) -> tuple[int, str]:
    types = {t.lower() for t in ctx.target_types}
    if types & {"water", "bug"}:
        return BALL_NET_MATCHED, "x3: the target is Water or Bug"
    return BALL_POKE, "x1: the target is neither Water nor Bug"


def _dive(ctx: ThrowContext) -> tuple[int, str]:
    if ctx.terrain == TERRAIN_WATER:
        return BALL_DIVE_MATCHED, "x3.5: surfing or fishing"
    return BALL_POKE, "x1: not on water"


def _nest(ctx: ThrowContext) -> tuple[int, str]:
    # `ballMod = 40 - level`, floored at 10, and only below level 40. Note the ceiling is 39 at
    # level 1, never 40 -- an earlier comment in catch.py called 40 its ceiling, which it is not.
    if ctx.target_level < 40:
        value = max(40 - ctx.target_level, BALL_POKE)
        return value, f"x{value / 10:g}: the target is level {ctx.target_level}"
    return BALL_POKE, f"x1: level {ctx.target_level} is at or above 40"


def _repeat(ctx: ThrowContext) -> tuple[int, str]:
    if ctx.registered:
        return BALL_REPEAT_MATCHED, "x3: already caught this species"
    return BALL_POKE, "x1: this species is not registered as caught yet"


def _timer(ctx: ThrowContext) -> tuple[int, str]:
    value = min(BALL_POKE + ctx.turn, BALL_TIMER_MATCHED)
    capped = " (capped)" if value == BALL_TIMER_MATCHED else ""
    return value, f"x{value / 10:g} on turn {ctx.turn + 1}{capped}: grows each turn to x4"


def _dusk(ctx: ThrowContext) -> tuple[int, str]:
    if ctx.terrain == TERRAIN_CAVE:
        return BALL_DUSK_MATCHED, "x3.5: in a cave, so the hour does not matter"
    if ctx.time_of_day == DUSK_BALL_BUCKET:
        return BALL_DUSK_MATCHED, "x3.5: night"
    return BALL_POKE, "x1: not night and not in a cave"


def _quick(ctx: ThrowContext) -> tuple[int, str]:
    if ctx.turn < 1:
        return BALL_QUICK_MATCHED, "x4: first turn"
    return BALL_POKE, "x1: only the first turn gets the bonus"


_CONDITIONAL = {
    "net": _net, "dive": _dive, "nest": _nest, "repeat": _repeat,
    "timer": _timer, "dusk": _dusk, "quick": _quick,
}


# --- apricorn rules (HGSS only) -------------------------------------------------------------
#
# These scale the CATCH RATE and are clamped to 1..255, so a high-rate species gains far less from
# one than a multiplier would suggest. Only the rules this project can state with confidence are
# implemented; the rest declare themselves unmodelled rather than quietly return x1, because a
# silently wrong `b` eliminates the true seed.

def _fast(rate: int, ctx: ThrowContext) -> tuple[int, str, str]:
    if ctx.target_base_speed >= 100:
        return (apricorn_catch_rate(rate, multiplier=4),
                "x4 on the catch rate: base Speed is at least 100", "")
    return rate, f"x1: base Speed {ctx.target_base_speed} is under 100", ""


def _love(rate: int, ctx: ThrowContext) -> tuple[int, str, str]:
    # x8 only when our Pokemon is the SAME species and the OPPOSITE gender. Against a genderless
    # target it can never apply -- even Lugia against Lugia fails the gender test -- which is the
    # case notes/lugia_love_ball.md works through.
    return rate, "x1 unless your Pokemon is the same species and the opposite gender", (
        "the Love Ball's x8 needs your own Pokemon's species and gender, which a hunt does not "
        "model; it is treated as x1, which is correct for every genderless target")


def _unmodelled(reason: str):
    def rule(rate: int, ctx: ThrowContext) -> tuple[int, str, str]:
        return rate, "x1 (not modelled)", reason
    return rule


_APRICORN = {
    "fast": _fast,
    "love": _love,
    "level": _unmodelled("the Level Ball compares your Pokemon's level with the target's, which a "
                         "hunt does not model"),
    "lure": _unmodelled("the Lure Ball's bonus applies only to a fishing encounter"),
    "heavy": _unmodelled("the Heavy Ball offsets by weight -- and the ROM tests the CATCH RATE "
                         "where it meant to test the weight, so the sign is not obvious"),
    "moon": _unmodelled("the Moon Ball's x4 needs the Moon Stone evolution family, which is not "
                        "in base_stats.json"),
    "friend": _unmodelled(""),      # friendship only; genuinely x1 for catching
}


#: Every Gen 4 ball, with the games it exists in.
#:
#: Apricorn balls and the Sport Ball are HGSS-only; the Park Ball is Pal Park's, and the Heal and
#: Cherish balls exist in both but have no case in the catch switch, so they are x1.
BALLS: tuple[Ball, ...] = (
    Ball("Poké Ball", multiplier=BALL_POKE),
    Ball("Great Ball", multiplier=BALL_GREAT),
    Ball("Ultra Ball", multiplier=BALL_ULTRA),
    Ball("Master Ball", guaranteed=True, note="always catches: the ROM skips the shake rolls"),
    Ball("Safari Ball", multiplier=BALL_SAFARI,
         note="x1.5, and only inside the Safari Zone / Great Marsh"),
    Ball("Net Ball", rule="net"),
    Ball("Dive Ball", rule="dive"),
    Ball("Nest Ball", rule="nest"),
    Ball("Repeat Ball", rule="repeat"),
    Ball("Timer Ball", rule="timer"),
    Ball("Quick Ball", rule="quick"),
    Ball("Dusk Ball", rule="dusk"),
    Ball("Luxury Ball", note="x1: it only affects friendship"),
    Ball("Premier Ball", note="x1: cosmetic"),
    Ball("Heal Ball", note="x1: it only heals on capture"),
    Ball("Cherish Ball", note="x1"),
    Ball("Park Ball", games=_SINNOH | _HGSS,
         note="x1 in the catch maths; Pal Park captures never fail for a different reason"),
    # HGSS only, and all of them scale the catch rate rather than setting a multiplier.
    Ball("Fast Ball", games=_HGSS, apricorn="fast"),
    Ball("Level Ball", games=_HGSS, apricorn="level"),
    Ball("Lure Ball", games=_HGSS, apricorn="lure"),
    Ball("Heavy Ball", games=_HGSS, apricorn="heavy"),
    Ball("Love Ball", games=_HGSS, apricorn="love"),
    Ball("Friend Ball", games=_HGSS, apricorn="friend"),
    Ball("Moon Ball", games=_HGSS, apricorn="moon"),
    Ball("Sport Ball", games=_HGSS, multiplier=BALL_SAFARI,
         note="x1.5, and only during the Bug-Catching Contest"),
)

_BY_KEY: dict[str, Ball] = {b.key: b for b in BALLS}


def ball(name: str) -> Ball:
    """The :class:`Ball` for a name, however it was spelled."""
    try:
        return _BY_KEY[ball_key(name)]
    except KeyError:
        raise ValueError(
            f"unknown ball {name!r}; known: {', '.join(b.name for b in BALLS)}") from None


def balls_for_game(game_key: str | None) -> tuple[Ball, ...]:
    """The balls a given game has. An unset game returns every ball.

    Unset is permissive for the same reason `games.tool_refusal` is: a profile that predates the
    field is HGSS, and offering too many is a smaller harm than hiding the one they are holding.
    """
    from claytonlib.games import canonical_game_key
    key = canonical_game_key(game_key)
    if not key:
        return BALLS
    return tuple(b for b in BALLS if key in b.games)


def ball_effect(name: str, base_catch_rate: int,
                ctx: ThrowContext | None = None) -> BallEffect:
    """What `name` is worth against a target of `base_catch_rate`, in this context.

    One call for both mechanisms: a conditional or plain ball comes back with its `multiplier` and
    the species rate untouched; an apricorn ball comes back with a scaled `catch_rate` and a ×1
    multiplier.
    """
    entry = ball(name)
    ctx = ctx or ThrowContext()
    if entry.apricorn:
        rate, reason, unmodelled = _APRICORN[entry.apricorn](base_catch_rate, ctx)
        return BallEffect(catch_rate=rate, multiplier=BALL_POKE, reason=reason,
                          unmodelled=unmodelled)
    if entry.rule:
        multiplier, reason = _CONDITIONAL[entry.rule](ctx)
        return BallEffect(catch_rate=base_catch_rate, multiplier=multiplier, reason=reason)
    reason = entry.note or f"x{entry.multiplier / 10:g}"
    return BallEffect(catch_rate=base_catch_rate, multiplier=entry.multiplier,
                      guaranteed=entry.guaranteed, reason=reason)


def is_turn_dependent(name: str) -> bool:
    """Whether this ball's multiplier changes as a battle goes on.

    True for the Quick Ball (×4 on turn 1 only) and the Timer Ball (climbing to ×4). Worth asking
    separately because the solver's dominance key assumes a threshold that does not improve with
    time, and a Timer Ball's does.
    """
    return ball(name).rule in ("timer", "quick")
