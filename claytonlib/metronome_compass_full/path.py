"""PathToken hierarchy and Path type for battle observation paths."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class PathToken:
    def render(self) -> str:
        raise NotImplementedError(f"{type(self).__name__}.render()")


# ---------------------------------------------------------------------------
# Parameterized tokens
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetronomeMove(PathToken):
    move_num: int
    def render(self) -> str:
        return f"M{self.move_num:03d}"


@dataclass(frozen=True)
class MagikarpMove(PathToken):
    """A move Magikarp actively selected: Splash (sp) or Tackle (tk)."""
    move: str
    def render(self) -> str:
        return f"K{self.move}"


@dataclass(frozen=True)
class MultiHit(PathToken):
    count: int
    def render(self) -> str:
        return f"x{self.count}"


# ---------------------------------------------------------------------------
# Player-move outcome tokens
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Hit(PathToken):
    def render(self) -> str: return "h"

@dataclass(frozen=True)
class Miss(PathToken):
    def render(self) -> str: return "-"

@dataclass(frozen=True)
class Crit(PathToken):
    """Crit implies hit; never combined with Hit."""
    def render(self) -> str: return "!"

@dataclass(frozen=True)
class EffectProc(PathToken):
    def render(self) -> str: return "~"


# ---------------------------------------------------------------------------
# Magikarp action tokens
# (appear in the position where MagikarpMove would be when a selected move
#  is not possible or is replaced by a forced action)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PAR(PathToken):
    """Magikarp was fully paralyzed and couldn't move."""
    def render(self) -> str: return "PAR"

@dataclass(frozen=True)
class FRZ(PathToken):
    """Magikarp was frozen and couldn't move."""
    def render(self) -> str: return "FRZ"

@dataclass(frozen=True)
class CFZ(PathToken):
    """Magikarp hurt itself in confusion (action replaced by self-hit)."""
    def render(self) -> str: return "CFZ"

@dataclass(frozen=True)
class SCFZ(PathToken):
    """Magikarp snapped out of confusion. Must be followed by its action token."""
    def render(self) -> str: return "SCFZ"

@dataclass(frozen=True)
class SLP(PathToken):
    """Magikarp was asleep and couldn't move."""
    def render(self) -> str: return "SLP"

@dataclass(frozen=True)
class FLN(PathToken):
    """Magikarp flinched from our move's secondary effect and couldn't move."""
    def render(self) -> str: return "FLN"

@dataclass(frozen=True)
class LV(PathToken):
    """Magikarp was immobilized by love (Attract) and couldn't move."""
    def render(self) -> str: return "LV"

@dataclass(frozen=True)
class Struggle(PathToken):
    """Magikarp used Struggle (forced action when no usable moves remain)."""
    def render(self) -> str: return "STR"


@dataclass(frozen=True)
class Prevented(PathToken):
    """Magikarp's selected move was prevented by Disable/Taunt/Gravity."""
    def render(self) -> str: return "P"


@dataclass(frozen=True)
class StatusEnd(PathToken):
    """A status (Disable/Taunt/etc) ended at the end of turn."""
    label: str
    def render(self) -> str: return f"({self.label})"


# ---------------------------------------------------------------------------
# Unsupported-effect token
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Unsupported(PathToken):
    """The Metronome move selected has an unmodelled effect.

    Path generation halts here; no further turns are appended.
    """
    def render(self) -> str: return "?"


# ---------------------------------------------------------------------------
# Path-end token
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PathEnd(PathToken):
    """Marks the end of an observed path (Magikarp fainted or battle ended).

    Always the last token. Dropped before comparing against precomputed paths;
    the preceding tokens are matched as a prefix of the precomputed path.
    """
    def render(self) -> str: return "_"


# ---------------------------------------------------------------------------
# Path type
# ---------------------------------------------------------------------------

Turn = tuple[PathToken, ...]
Path = tuple[Turn, ...]


def render_path(path: Path) -> str:
    """Tokens concatenated within a turn; turns space-separated."""
    return " ".join("".join(t.render() for t in turn) for turn in path)


# ---------------------------------------------------------------------------
# Battle State & Status
# ---------------------------------------------------------------------------

class NonVolatileStatus(Enum):
    NONE      = 0
    SLEEP     = 1
    FROZEN    = 2
    BURN      = 3
    POISON    = 4
    PARALYZED = 5


@dataclass
class MagikarpStatus:
    status: NonVolatileStatus = NonVolatileStatus.NONE
    sleep_turns: int = 0          # 1 = wakes up next turn; 2+ = still sleeping
    flinched: bool = False        # cleared each turn
    disable_turns: int = 0        # ticks every turn; disabled_move cleared when 0
    disabled_move: int | None = None
    taunt_turns: int = 0          # ticks every turn
    confusion_turns: int = 0      # ticks only when Magikarp attempts to act
    infatuated: bool = False

    def copy(self) -> MagikarpStatus:
        from dataclasses import replace
        return replace(self)


@dataclass
class MetronomeBattleState:
    gravity_turns: int = 0            # 0 = inactive, >0 = turns remaining
    weather: str | None = None        # "sunny" / "rain" / "sand" / "hail" / None
    weather_until: int = 0            # turn number weather expires
    user_evasion_stage: int = 0       # -6 to +6
    target_evasion_stage: int = 0
    user_accuracy_stage: int = 0
    target_accuracy_stage: int = 0
    user_crit_stage: int = 0

    mk_status: MagikarpStatus = field(default_factory=MagikarpStatus)
    mk_last_move: int | None = None   # move number used last turn
    mk_last_move_prevented: bool = False

    def copy(self) -> MetronomeBattleState:
        from dataclasses import replace
        c = replace(self)
        c.mk_status = self.mk_status.copy()
        return c
