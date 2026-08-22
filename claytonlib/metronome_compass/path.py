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
    status: str | None = None  # set for Tri Attack: 'BRN', 'FRZ', 'PAR'
    def render(self) -> str:
        return f"~<{self.status}>" if self.status else "~"


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
# End-of-turn observable tokens
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BindDmg(PathToken):
    """Magikarp took binding damage at end of turn."""
    def render(self) -> str: return "BD"

@dataclass(frozen=True)
class BindEnd(PathToken):
    """Magikarp broke free from binding at end of turn."""
    def render(self) -> str: return "BF"

@dataclass(frozen=True)
class Magnitude(PathToken):
    """Magnitude move level (observable in battle)."""
    level: int
    def render(self) -> str: return f"Mag{self.level}"

@dataclass(frozen=True)
class DrowsySlept(PathToken):
    """Magikarp fell asleep from Yawn at end of turn."""
    def render(self) -> str: return "ZZ"

@dataclass(frozen=True)
class ConversionType(PathToken):
    """User's type changed via Conversion. type_name is the new type (e.g. 'Electric')."""
    type_name: str
    def render(self) -> str: return f"CV{self.type_name}"


@dataclass(frozen=True)
class RampageEnd(PathToken):
    """Rampage (Thrash/Outrage/Petal Dance) ended; confusion applied afterward."""
    def render(self) -> str: return "REND"


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
    # Field effects (turns remaining; 0 = inactive)
    gravity_turns: int = 0
    user_light_screen_turns: int = 0
    user_reflect_turns: int = 0
    user_mist_turns: int = 0
    user_safeguard_turns: int = 0
    user_tailwind_turns: int = 0
    user_lucky_chant_turns: int = 0
    user_trick_room_turns: int = 0
    user_magnet_rise_turns: int = 0

    # Weather
    weather: str | None = None        # "sunny" / "rain" / "sand" / "hail" / None
    weather_until: int = 0            # turn number weather expires

    # Stat stages (all -6 to +6)
    user_atk_stage: int = 0
    user_def_stage: int = 0
    user_spd_stage: int = 0
    user_spatk_stage: int = 0
    user_spdef_stage: int = 0
    target_atk_stage: int = 0
    target_def_stage: int = 0
    target_spd_stage: int = 0
    target_spatk_stage: int = 0
    target_spdef_stage: int = 0
    user_evasion_stage: int = 0
    target_evasion_stage: int = 0
    user_accuracy_stage: int = 0
    target_accuracy_stage: int = 0
    user_crit_stage: int = 0

    # User (Chansey) HP knowledge — we cannot track exact HP, only what we can
    # prove. `user_took_damage` becomes True the moment Chansey is hit; taking
    # damage also clears `user_recovered` (we KNOW she is below max right then).
    # `user_recovered` is set by non-guaranteeing heals (Recover/Swallow) which
    # may or may not have topped her off. The three provable states are:
    #   FULL      : not took_damage                  (never hurt → at max)
    #   NOT_FULL  : took_damage and not recovered     (hurt, no heal since)
    #   UNKNOWN   : took_damage and recovered         (hurt then healed by ??)
    # Moves whose success depends on HP must throw Unsupported in UNKNOWN.
    user_took_damage: bool = False
    user_recovered: bool = False
    user_focus_energy: bool = False
    user_sleep_turns: int = 0         # Rest: turns remaining where Chansey can't act
    user_confusion_turns: int = 0     # Rampage end: turns remaining where Chansey may hurt itself
    user_lock_on_turns: int = 0       # Mind Reader/Lock-On: guaranteed-hit turns remaining
    user_aqua_ring: bool = False
    user_ingrained: bool = False
    user_mud_sport: bool = False
    user_water_sport: bool = False
    user_substitute: bool = False
    user_stockpile: int = 0           # 0-3

    # User consecutive-move / locked-move state
    user_recharging: bool = False     # Hyper Beam recharge turn
    user_locked_move_num: int | None = None   # move number being continued
    user_locked_effect: int | None = None     # effect of that move
    user_locked_turns: int = 0               # continuation turns remaining

    # Bide state
    user_bide_triggered: bool = False  # True if Magikarp hit with Tackle/Struggle while biding

    # Conversion 2's "last damaging move that landed on me" record (game's
    # conversion2Move != 0). Set when Magikarp lands a Tackle; cleared when a move
    # resolving against Chansey misses/fails (Tackle miss, Magikarp prevented) or
    # on C2 use. A self-targeting Magikarp Splash leaves it unchanged.
    user_conv2_hit: bool = False
    # Metal Burst prerequisite: Chansey took damage THIS turn (reset each turn)
    user_hit_this_turn: bool = False
    # Magikarp HP knowledge (mirror of the Chansey flags), for Present's heal
    # branch which fails at full HP. Only Present heals Magikarp, so UNKNOWN is
    # only reachable via two consecutive Presents.
    mk_took_damage: bool = False
    mk_recovered: bool = False

    # Future Sight / Doom Desire counter
    future_sight_turns: int = 0             # turns until Future Sight fires (0 = inactive)
    future_sight_move_num: int | None = None # move number for accuracy lookup on fire

    # Hazards on opponent's side
    opp_spikes: int = 0               # 0-3
    opp_toxic_spikes: int = 0         # 0-2
    opp_stealth_rock: bool = False

    # Perish Song countdowns (0 = inactive)
    user_perish_song_turns: int = 0
    mk_perish_song_turns: int = 0

    # Magikarp volatile status
    mk_status: MagikarpStatus = field(default_factory=MagikarpStatus)
    mk_binding_turns: int = 0         # 0 = not bound
    mk_seeded: bool = False           # Leech Seed
    mk_blocked: bool = False          # Spider Web / Mean Look
    mk_tormented: bool = False        # Torment
    mk_encore_turns: int = 0         # Encore: turns remaining where Magikarp must repeat last move
    mk_drowsy_turns: int = 0          # Yawn: 2→1 then applies sleep
    mk_nightmare: bool = False
    mk_embargo: bool = False
    mk_heal_block: bool = False
    mk_gastro_acid: bool = False      # ability suppressed

    mk_ability: str | None = None      # Magikarp's current ability (None = default Swift Swim)
    user_ability: str | None = None    # Chansey's current ability (None = default)

    mk_last_move: int | None = None   # move number used last turn
    mk_last_move_prevented: bool = False

    # Level info for OHKO (effect 38): fails outright when user_level < target_level
    # (roll still consumed); otherwise threshold = 30 + user_level - target_level.
    user_level: int = 7               # metronome user's level (default; no input source yet)
    target_level: int = 10            # Magikarp level; set from magikarp_level in precompute_path

    # Turn counter (for Fake Out and weather expiry)
    turn_number: int = 0

    # User's current types (changes via Conversion / Camouflage / etc.)
    user_types: list = field(default_factory=lambda: ['Normal'])

    def copy(self) -> MetronomeBattleState:
        from dataclasses import replace
        c = replace(self)
        c.mk_status = self.mk_status.copy()
        c.user_types = list(self.user_types)
        return c
