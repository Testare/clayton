"""games.py — which game a save is, and the three things that actually follow from it.

Until Platinum, "which game" was decoration: `Profile.version` was a free-text
``"HeartGold"``/``"SoulSilver"`` that nothing ever branched on, while
`battle_compass/targets.py` said outright "This profile is SoulSilver" and shipped SoulSilver's
rows. So this module is both the Platinum prerequisite and the fix for that latent HeartGold bug.

It lives in `claytonlib` rather than in `app/` because what differs between the games is ROM
fact, not presentation:

* **Which Seed A signal exists.** HGSS relocates its roamers at game load and has Elm calls;
  Platinum relocates roamers only on Fly/Teleport (`src/field_map_change_flags.c:106,112`) and has
  no phone calls at all. What it has instead is the Poketch coin toss on the **MT** stream and
  chatot cry pitch on the LCRNG. See :mod:`claytonlib.coin_flips`, :mod:`claytonlib.chatot_pitch`.
* **What the advance units are called.** Both games route the same way — a blind 2-advance bulk
  action, then a readable 1-advance margin — but the actions differ: chatot flips + Elm calls in
  HGSS, Journal flips + chatot cries in Platinum. Carrying the labels here keeps the route guide
  from having to know which game it is in.
* **Which tools can run.** Expeditions are built on the Safari Zone and the Blackthorn Metronome
  matchup, neither of which exists in Platinum, so they stay HGSS-only. Diamond and Pearl are
  selectable but supported nowhere yet.

Everything else about the RNG is shared, and verified so: the seed formula, the two-stream
LCRNG/battle split, the capture maths, the accuracy table, the move and species tables. That is
why this registry is small — it names the differences, and there are only a few.
"""
from __future__ import annotations

from dataclasses import dataclass

#: The two Seed A identification mechanisms.
SIGNAL_ROAMERS_ELM = "roamers_elm"
SIGNAL_FLIPS_PITCH = "flips_pitch"

#: The tools a game can be used with.
TOOL_GLASS = "glass"
TOOL_HUNTS = "hunts"
TOOL_EXPEDITIONS = "expeditions"
ALL_TOOLS = (TOOL_GLASS, TOOL_HUNTS, TOOL_EXPEDITIONS)


@dataclass(frozen=True)
class Game:
    """One supported (or not yet supported) game.

    `key` is what gets stored; `name` is what the player sees. Storing the key rather than the
    display name is the whole reason this type exists — the old free-text `version` field held a
    display name, which is why nothing could branch on it without string-matching.
    """
    key: str
    name: str
    #: Which Seed A identification mechanism this game offers.
    seed_a_signal: str
    #: Tools that can run against this game.
    tools: frozenset[str]
    #: The blind bulk-advance action, and how many advances one costs.
    bulk_action: str = "Chatot flip"
    bulk_advances: int = 2
    #: The readable margin action — one advance, one observable symbol.
    margin_action: str = "Elm call"
    #: Why this game is not supported, when it is not. Shown instead of a generic refusal.
    unsupported_reason: str = ""

    def supports(self, tool: str) -> bool:
        return tool in self.tools

    @property
    def is_supported(self) -> bool:
        return bool(self.tools)

    @property
    def uses_coin_flips(self) -> bool:
        return self.seed_a_signal == SIGNAL_FLIPS_PITCH


#: Diamond and Pearl share one reason, written once.
_DP_REASON = (
    "Diamond and Pearl are not supported yet. Their RNG is the same as Platinum's, so support is "
    "mostly a matter of the encounter data each one needs — but none of it has been checked, and "
    "a tool that is confidently wrong about a seed is worse than one that declines.")

GAMES: tuple[Game, ...] = (
    Game("heartgold", "HeartGold", SIGNAL_ROAMERS_ELM,
         frozenset(ALL_TOOLS)),
    Game("soulsilver", "SoulSilver", SIGNAL_ROAMERS_ELM,
         frozenset(ALL_TOOLS)),
    # Glass and Hunts only: an Expedition is a Safari Zone quest, and the Metronome compass is
    # the Blackthorn Magikarp matchup. Neither has a Platinum counterpart.
    Game("platinum", "Platinum", SIGNAL_FLIPS_PITCH,
         frozenset((TOOL_GLASS, TOOL_HUNTS)),
         bulk_action="Journal flip", bulk_advances=2, margin_action="Chatot cry"),
    Game("diamond", "Diamond", SIGNAL_FLIPS_PITCH, frozenset(), unsupported_reason=_DP_REASON),
    Game("pearl", "Pearl", SIGNAL_FLIPS_PITCH, frozenset(), unsupported_reason=_DP_REASON),
)

#: What to tell a player whose profile has no game yet. Not a refusal — see `tool_refusal`.
UNSET_HINT = ("This profile has no game set, so it is treated as HeartGold/SoulSilver. Set it in "
              "the profile's settings if it is Platinum.")

#: The game an unset profile is treated as, for choosing a Seed A signal. Every profile written
#: before the field existed is HGSS, and both of those identify Seed A the same way, so the signal
#: is well-defined even though the exact version is not.
LEGACY_DEFAULT_SIGNAL = SIGNAL_ROAMERS_ELM

_BY_KEY: dict[str, Game] = {g.key: g for g in GAMES}
#: Display name (lowercased) -> game, so the old free-text `version` values still resolve.
_BY_NAME: dict[str, Game] = {g.name.lower(): g for g in GAMES}


def game_keys() -> tuple[str, ...]:
    return tuple(g.key for g in GAMES)


def canonical_game_key(value: str | None) -> str:
    """Normalise anything a stored profile might hold into a game key, or ``""`` if unset.

    Accepts the key (``"platinum"``), the display name (``"Platinum"``, ``"HEARTGOLD"``) and the
    spellings the old `version` field actually held — which is what makes the migration a read-time
    concern rather than a data migration. An unrecognised non-empty value raises, because silently
    treating it as "unset" would hand a HeartGold profile SoulSilver's target rows, which is the
    bug this module exists to close.
    """
    if value is None:
        return ""
    text = value.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in _BY_KEY:
        return lowered
    if lowered in _BY_NAME:
        return _BY_NAME[lowered].key
    # "Heart Gold" / "Soul Silver" / "heart-gold" all mean the obvious thing.
    squashed = "".join(ch for ch in lowered if ch.isalnum())
    if squashed in _BY_KEY:
        return squashed
    raise ValueError(
        f"{value!r} is not a game this build knows; expected one of "
        f"{', '.join(g.name for g in GAMES)}")


def game(key: str | None) -> Game | None:
    """The :class:`Game` for a key or display name, or None when unset."""
    resolved = canonical_game_key(key)
    return _BY_KEY.get(resolved) if resolved else None


def game_name(key: str | None) -> str:
    """Display name for a key, or ``""`` when unset."""
    found = game(key)
    return found.name if found else ""


def tool_refusal(key: str | None, tool: str) -> str:
    """Why `tool` cannot run for this game, or ``""`` when it can.

    A sentence rather than a boolean, because every caller that needs the boolean also needs to
    tell the player why — and "unsupported" on its own invites the same question twice.

    **An unset game refuses nothing.** Every profile that predates this field has one, and they
    are all HeartGold or SoulSilver — so refusing them would lock existing players out of the
    tools they were already using, to enforce a field they never filled in. Setting the game is
    worth prompting for (see `UNSET_HINT`); it is not worth blocking on.
    """
    if tool not in ALL_TOOLS:
        raise ValueError(f"unknown tool {tool!r}; known: {', '.join(ALL_TOOLS)}")
    found = game(key)
    if found is None:
        return ""
    if found.supports(tool):
        return ""
    if found.unsupported_reason:
        return found.unsupported_reason
    if tool == TOOL_EXPEDITIONS:
        return (f"Expeditions are HeartGold/SoulSilver only: a quest is a Safari Zone hunt and the "
                f"Metronome compass is the Blackthorn matchup, and {found.name} has neither. "
                f"Glass and Hunts both work.")
    return f"{found.name} does not support {tool} yet"
