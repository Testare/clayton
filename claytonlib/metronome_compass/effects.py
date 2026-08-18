"""Effect scripts and registry for metronome battle simulation.

Each effect number maps to a handler function that calls ctx.emit() helpers to
advance RNG (RngContext) or prompt the user (InteractiveContext). Unknown effects
fall back to _eff_unsupported.

Roll sequences per effects.md:
  Standard damage: crit (observable), damage (unobservable), hit (observable)
  Status moves:    hit (observable) only — no crit or damage roll
  Always-hit:      crit (observable), damage (unobservable) — no hit roll
"""
from __future__ import annotations
from typing import TYPE_CHECKING, Callable

from claytonlib.moves import Move
from .path import (
    NonVolatileStatus, Hit, Miss, Crit, EffectProc,
    Unsupported, PathEnd, PathToken, Magnitude, BindDmg, BindEnd, DrowsySlept,
    ConversionType, RampageEnd,
)

if TYPE_CHECKING:
    from .context import BattleContext


# ---------------------------------------------------------------------------
# Human-readable effect descriptions
# ---------------------------------------------------------------------------

def move_effect(effect: int, effect_chance: int = 0) -> str:
    """Return a human-readable description of an effect number."""
    descriptions: dict[int, str] = {
        0:   "standard",             1:   "sleep",
        2:   f"poison {effect_chance}%",   3:   "drain",
        4:   f"burn {effect_chance}%",     5:   f"freeze {effect_chance}%",
        6:   f"paralyze {effect_chance}%", 7:   "self-destruct",
        8:   "dream-eater",          10:  "atk+1",
        11:  "def+1",                13:  "spatk+1",
        16:  "eva+1",                17:  "always-hit",
        18:  "growl",                19:  "leer",
        20:  "string-shot",          23:  "acc-1",
        24:  "eva-1",                25:  "haze",
        26:  "bide",                 27:  "thrash",
        28:  "whirlwind",            29:  "multi-hit",
        30:  "conversion",           31:  f"flinch {effect_chance}%",
        32:  "recover",              33:  "toxic",
        34:  "pay-day",              35:  "light-screen",
        36:  "tri-attack",           37:  "rest",
        38:  "ohko",                 39:  "razor-wind",
        40:  "super-fang",           41:  "dragon-rage",
        42:  "bind",                 43:  "high-crit",
        44:  "double-hit",           45:  "jump-kick",
        46:  "mist",                 47:  "focus-energy",
        48:  "recoil",               49:  "confuse",
        50:  "atk+2",                51:  "def+2",
        52:  "spd+2",                53:  "spatk+2",
        54:  "spdef+2",              57:  "transform",
        58:  "opp-atk-2",            59:  "opp-def-2",
        60:  "opp-spd-2",            62:  "opp-spdef-2",
        65:  "reflect",              66:  "poison-powder",
        67:  "paralyze",             68:  f"opp-atk-1 {effect_chance}%",
        69:  f"opp-def-1 {effect_chance}%", 70: f"opp-spd-1 {effect_chance}%",
        71:  f"opp-spatk-1 {effect_chance}%", 72: f"opp-spdef-1 {effect_chance}%",
        73:  f"opp-acc-1 {effect_chance}%",  75: "sky-attack",
        76:  f"confuse {effect_chance}%",    77: "twineedle",
        78:  "vital-throw",          79:  "substitute",
        80:  "hyper-beam",           81:  "rage",
        84:  "leech-seed",           85:  "splash",
        86:  "disable",              87:  "seismic-toss",
        88:  "psywave",              90:  "encore",
        91:  "pain-split",           92:  "snore",
        93:  "conversion2",          94:  "lock-on",
        99:  "flail",                100: "spite",
        101: "false-swipe",          102: "heal-bell",
        103: "priority",             104: "triple-kick",
        106: "spider-web",           107: "nightmare",
        108: "minimize",             109: "curse",
        112: "spikes",               113: "foresight",
        114: "perish-song",          115: "sandstorm",
        117: "rollout",              118: "swagger",
        119: "fury-cutter",          120: "attract",
        121: "return",               122: "present",
        123: "frustration",          124: "safeguard",
        125: f"burn {effect_chance}%",      126: "magnitude",
        127: "baton-pass",           128: "pursuit",
        129: "rapid-spin",           130: "sonic-boom",
        132: "recover",              135: "hidden-power",
        136: "rain-dance",           137: "sunny-day",
        138: f"user-def+1 {effect_chance}%", 139: f"user-atk+1 {effect_chance}%",
        140: f"all-stats+1 {effect_chance}%", 142: "belly-drum",
        143: "psych-up",             145: "skull-bash",
        146: f"flinch {effect_chance}%",    147: "earthquake",
        148: "future-sight",         149: "gust",
        150: f"flinch {effect_chance}%",    151: "solar-beam",
        152: f"thunder-paralyze {effect_chance}%", 153: "teleport",
        154: "beat-up",              155: "fly",
        156: "defense-curl",         158: "fake-out",
        159: "uproar",               160: "stockpile",
        161: "spit-up",              162: "swallow",
        164: "hail",                 165: "torment",
        166: "flatter",              167: "will-o-wisp",
        168: "memento",              169: "facade",
        171: "smelling-salt",        173: "nature-power",
        174: "charge",               175: "taunt",
        178: "role-play",            179: "wish",
        181: "ingrain",              182: "superpower",
        183: "magic-coat",           184: "recycle",
        185: "revenge",              186: "brick-break",
        187: "yawn",                 188: "knock-off",
        189: "endeavor",             190: "eruption",
        191: "skill-swap",           192: "imprison",
        193: "refresh",              194: "grudge",
        196: "low-kick",             197: f"sec-atk-1 {effect_chance}%",
        198: "recoil",               199: "teeter-dance",
        200: f"burn {effect_chance}% high-crit", 201: "mud-sport",
        202: f"poison {effect_chance}%",    203: "weather-ball",
        204: f"spatk-2 {effect_chance}%",  205: "tickle",
        206: "cosmic-power",         207: "sky-uppercut",
        208: "bulk-up",              209: f"poison {effect_chance}% high-crit",
        210: "water-sport",          211: "calm-mind",
        212: "dragon-dance",         213: "camouflage",
        214: "roost",                215: "gravity",
        216: "miracle-eye",          217: "wake-up-slap",
        218: "hammer-arm",           219: "gyro-ball",
        220: "healing-wish",         221: "brine",
        222: "natural-gift",         224: "pluck",
        225: "tailwind",             226: "acupressure",
        227: "metal-burst",          228: "u-turn",
        229: "close-combat",         230: "payback",
        231: "assurance",            232: "embargo",
        233: "fling",                234: "psycho-shift",
        235: "trump-card",           236: "heal-block",
        237: "wring-out",            238: "power-trick",
        239: "gastro-acid",          240: "lucky-chant",
        243: "power-swap",           244: "guard-swap",
        245: "punishment",           246: "last-resort",
        247: "worry-seed",           248: "sucker-punch",
        249: "toxic-spikes",         250: "heart-swap",
        251: "aqua-ring",            252: "magnet-rise",
        253: f"burn {effect_chance}% recoil", 255: "dive",
        256: "dig",                  257: "surf",
        258: "defog",                259: "trick-room",
        260: f"freeze {effect_chance}%",    261: "whirlpool",
        262: f"paralyze {effect_chance}%",  263: "bounce",
        265: "captivate",            266: "stealth-rock",
        268: "judgment",             269: "head-smash",
        270: "lunar-dance",          271: f"opp-spdef-2 {effect_chance}%",
        272: "shadow-force",         273: "fire-fang",
        274: "ice-fang",             275: "thunder-fang",
        276: f"user-spatk+1 {effect_chance}%",
    }
    return descriptions.get(effect, f"unsupported({effect})")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _hit_check(ctx: 'BattleContext', move: Move) -> bool:
    """Single observable hit roll for status moves (no crit or damage roll)."""
    def rng_to_token(c: 'BattleContext') -> PathToken:
        roll = c.advance_observable()
        return Hit() if roll % 100 < c.effective_accuracy(move.accuracy) else Miss()
    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Hit? (h/-):",
        input_to_token=lambda s: Hit() if s.strip() == 'h' else Miss(),
    )
    return not isinstance(token, Miss)


def _emit_path_end(ctx: 'BattleContext') -> None:
    ctx.raw_emit(PathEnd())
    ctx.battle_state['unsupported'] = True


def _apply_confusion(ctx: 'BattleContext') -> None:
    """Roll/record confusion duration and store in Magikarp status."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']

    def rng_to_duration(c: 'BattleContext') -> int:
        return 2 + (c.advance_observable() % 4)

    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Confusion duration? (2-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.mk_status.confusion_turns = int(duration)


# ---------------------------------------------------------------------------
# Secondary-effect appliers — passed to ctx.effect_proc(chance, apply)
# ---------------------------------------------------------------------------

def _status_applier(ctx: 'BattleContext', status: NonVolatileStatus,
                    *, block_weather: str | None = None) -> Callable[[], bool]:
    """Return an apply() callback that sets a non-volatile status on Magikarp.

    Returns True (observable) only if the status actually landed. A proc against
    a Magikarp that already has a non-volatile status — or a freeze while
    block_weather is active — rolls the RNG but is not observable.
    """
    state = ctx.battle_state['state']

    def apply() -> bool:
        if block_weather is not None and state.weather == block_weather:
            return False
        if state.mk_status.status != NonVolatileStatus.NONE:
            return False
        state.mk_status.status = status
        return True

    return apply


def _target_accuracy_applier(ctx: 'BattleContext', amount: int = 1) -> Callable[[], bool]:
    """Return an apply() callback that lowers Magikarp's accuracy stage.

    Returns False (not observable) when already at the -6 floor: the proc rolls
    but no message is shown.
    """
    state = ctx.battle_state['state']

    def apply() -> bool:
        if state.target_accuracy_stage <= -6:
            return False
        state.target_accuracy_stage = max(-6, state.target_accuracy_stage - amount)
        return True

    return apply


def _target_stat_applier(ctx: 'BattleContext', attr: str, amount: int = -1) -> Callable[[], bool]:
    """Return an apply() callback that changes Magikarp's stat stage by amount.

    Returns False (not observable) when the stage is already at its floor/ceil.
    """
    state = ctx.battle_state['state']

    def apply() -> bool:
        current = getattr(state, attr)
        if amount < 0 and current <= -6:
            return False
        if amount > 0 and current >= 6:
            return False
        setattr(state, attr, max(-6, min(6, current + amount)))
        return True

    return apply


def _user_stat_applier(ctx: 'BattleContext', attr: str, amount: int = 1) -> Callable[[], bool]:
    """Return an apply() callback that changes Chansey's stat stage by amount.

    Returns False (not observable) when the stage is already at its floor/ceil.
    """
    state = ctx.battle_state['state']

    def apply() -> bool:
        current = getattr(state, attr)
        if amount > 0 and current >= 6:
            return False
        if amount < 0 and current <= -6:
            return False
        setattr(state, attr, max(-6, min(6, current + amount)))
        return True

    return apply


def _all_user_stats_applier(ctx: 'BattleContext') -> Callable[[], bool]:
    """Return apply() for Ancient Power / Silver Wind / Ominous Wind (all user stats +1).

    Observable only if at least one stat was not already at +6.
    """
    state = ctx.battle_state['state']
    _ALL_ATTRS = [
        'user_atk_stage', 'user_def_stage', 'user_spd_stage',
        'user_spatk_stage', 'user_spdef_stage',
        'user_accuracy_stage', 'user_evasion_stage',
    ]

    def apply() -> bool:
        any_changed = False
        for attr in _ALL_ATTRS:
            if getattr(state, attr) < 6:
                setattr(state, attr, getattr(state, attr) + 1)
                any_changed = True
        return any_changed

    return apply


# ---------------------------------------------------------------------------
# Group 1: Standard damage — crit (observable), damage (unobservable), hit
# ---------------------------------------------------------------------------

def _eff_damage(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    return not isinstance(token, Miss)


def _eff_high_crit(ctx: 'BattleContext', move: Move) -> bool:
    """Increased crit stage; same RNG roll count as standard."""
    token = ctx.hit_crit_or_miss(move.accuracy, crit_stage=1)
    return not isinstance(token, Miss)


# ---------------------------------------------------------------------------
# Group 2: Damage + one observable secondary effect proc
# ---------------------------------------------------------------------------

def _eff_damage_secondary(ctx: 'BattleContext', move: Move,
                          apply: Callable[[], bool] | None = None) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance, apply)
    return True


def _eff_high_crit_secondary(ctx: 'BattleContext', move: Move,
                             apply: Callable[[], bool] | None = None) -> bool:
    """High-crit damage + observable secondary effect proc."""
    token = ctx.hit_crit_or_miss(move.accuracy, crit_stage=1)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance, apply)
    return True


# Typed secondary-effect handlers (bind the applier at call time so it can read ctx).
def _eff_burn_secondary(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _status_applier(ctx, NonVolatileStatus.BURN))


def _eff_freeze_secondary(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _status_applier(ctx, NonVolatileStatus.FROZEN))


def _eff_paralyze_secondary(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _status_applier(ctx, NonVolatileStatus.PARALYZED))


def _eff_poison_secondary(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _status_applier(ctx, NonVolatileStatus.POISON))


def _eff_accuracy_drop_secondary(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_accuracy_applier(ctx))


def _eff_burn_highcrit(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_high_crit_secondary(ctx, move, _status_applier(ctx, NonVolatileStatus.BURN))


def _eff_poison_highcrit(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_high_crit_secondary(ctx, move, _status_applier(ctx, NonVolatileStatus.POISON))


# Stat-lowering secondaries (target Magikarp)
def _eff_target_atk_minus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_stat_applier(ctx, 'target_atk_stage'))


def _eff_target_def_minus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_stat_applier(ctx, 'target_def_stage'))


def _eff_target_spd_minus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_stat_applier(ctx, 'target_spd_stage'))


def _eff_target_spatk_minus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_stat_applier(ctx, 'target_spatk_stage'))


def _eff_target_spdef_minus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_stat_applier(ctx, 'target_spdef_stage'))


def _eff_target_spdef_minus2(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _target_stat_applier(ctx, 'target_spdef_stage', -2))


# Stat-raising secondaries (user Chansey)
def _eff_user_def_plus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _user_stat_applier(ctx, 'user_def_stage'))


def _eff_user_atk_plus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _user_stat_applier(ctx, 'user_atk_stage'))


def _eff_user_all_stats_plus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _all_user_stats_applier(ctx))


def _eff_user_spatk_plus1(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _user_stat_applier(ctx, 'user_spatk_stage'))


def _eff_user_spatk_minus2(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_secondary(ctx, move, _user_stat_applier(ctx, 'user_spatk_stage', -2))


# ---------------------------------------------------------------------------
# Group 3: Damage + unobservable flinch roll (we always go second)
# ---------------------------------------------------------------------------

def _eff_damage_flinch(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.advance_unobservable(1)  # flinch roll — not observable since Magikarp already moved
    return True


# ---------------------------------------------------------------------------
# Group 4: Damage + observable status proc + unobservable flinch
# (Fire/Ice/Thunder Fang)
# ---------------------------------------------------------------------------

def _eff_damage_status_flinch(ctx: 'BattleContext', move: Move,
                              apply: Callable[[], bool] | None = None) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance, apply)  # burn/freeze/paralyze (observable)
    ctx.advance_unobservable(1)                 # flinch roll (not observable, we go second)
    return True


def _eff_fire_fang(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_status_flinch(ctx, move, _status_applier(ctx, NonVolatileStatus.BURN))


def _eff_ice_fang(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_status_flinch(ctx, move, _status_applier(ctx, NonVolatileStatus.FROZEN))


def _eff_thunder_fang(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_damage_status_flinch(ctx, move, _status_applier(ctx, NonVolatileStatus.PARALYZED))


# ---------------------------------------------------------------------------
# Sleep (Effect 1)
# ---------------------------------------------------------------------------

def _eff_sleep(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.status != NonVolatileStatus.NONE:
        return False
    if state.mk_insomnia:
        return False
    # Duration: roll observable, user needs to observe sleep duration from game
    def rng_to_duration(c: 'BattleContext') -> int:
        return 2 + (c.advance_observable() % 4)
    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Sleep duration? (2-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.mk_status.status = NonVolatileStatus.SLEEP
    state.mk_status.sleep_turns = int(duration)
    return True


# ---------------------------------------------------------------------------
# Confusion on hit (Effect 49)
# ---------------------------------------------------------------------------

def _eff_confuse_hit(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.confusion_turns > 0:
        return False
    _apply_confusion(ctx)
    return True


# ---------------------------------------------------------------------------
# Confusion chance on damaging hit (Effect 76: Psybeam, etc.)
# ---------------------------------------------------------------------------

def _eff_damage_confuse(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False

    def rng_to_proc(c: 'BattleContext') -> PathToken | None:
        roll = c.advance_observable()
        return EffectProc() if roll % 100 < move.effect_chance else None

    proc_token = ctx.emit(
        rng_to_token=rng_to_proc,
        question="Confusion proc? (~/-): ",
        input_to_token=lambda s: EffectProc() if s.strip() == '~' else None,
    )
    if isinstance(proc_token, EffectProc) and state.mk_status.confusion_turns == 0:
        _apply_confusion(ctx)
    return True


# ---------------------------------------------------------------------------
# Paralyze (Effect 67)
# ---------------------------------------------------------------------------

def _eff_paralyze(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.status != NonVolatileStatus.NONE:
        return False
    state.mk_status.status = NonVolatileStatus.PARALYZED
    return True


# ---------------------------------------------------------------------------
# Poison on hit — Toxic (33) and Poison Powder (66)
# ---------------------------------------------------------------------------

def _eff_poison_hit(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.status != NonVolatileStatus.NONE:
        return False
    state.mk_status.status = NonVolatileStatus.POISON
    return True


# ---------------------------------------------------------------------------
# Will-O-Wisp (Effect 167)
# ---------------------------------------------------------------------------

def _eff_will_o_wisp(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.status != NonVolatileStatus.NONE:
        return False
    state.mk_status.status = NonVolatileStatus.BURN
    return True


# ---------------------------------------------------------------------------
# Disable (Effect 86)
# ---------------------------------------------------------------------------

def _eff_disable(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if (state.mk_status.disabled_move is not None
            or state.mk_last_move is None
            or state.mk_last_move_prevented):
        return False

    def rng_to_duration(c: 'BattleContext') -> int:
        return 4 + (c.advance_observable() % 4)

    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Disable duration? (4-7):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.mk_status.disabled_move = state.mk_last_move
    state.mk_status.disable_turns = int(duration)
    return True


# ---------------------------------------------------------------------------
# Taunt (Effect 175)
# ---------------------------------------------------------------------------

def _eff_taunt(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.taunt_turns > 0:
        return False

    def rng_to_duration(c: 'BattleContext') -> int:
        return 3 + (c.advance_observable() % 3)

    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Taunt duration? (3-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.mk_status.taunt_turns = int(duration)
    return True


# ---------------------------------------------------------------------------
# Swagger (Effect 118)
# ---------------------------------------------------------------------------

def _eff_swagger(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    # Always raises target attack by 2; confusion only if not already confused
    if state.mk_status.confusion_turns == 0:
        _apply_confusion(ctx)
    return True


# ---------------------------------------------------------------------------
# Flatter (Effect 166) — hit + confusion if not confused (like Swagger)
# ---------------------------------------------------------------------------

def _eff_flatter(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.confusion_turns == 0:
        _apply_confusion(ctx)
    return True


# ---------------------------------------------------------------------------
# Teeter Dance (Effect 199) — fail if already confused
# ---------------------------------------------------------------------------

def _eff_teeter_dance(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.confusion_turns > 0:
        return False
    _apply_confusion(ctx)
    return True


# ---------------------------------------------------------------------------
# Attract (Effect 120)
# ---------------------------------------------------------------------------

def _eff_attract(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if not ctx.battle_state.get('opposite_gender', False):
        return False
    if state.mk_status.infatuated:
        return False
    state.mk_status.infatuated = True
    return True


# ---------------------------------------------------------------------------
# Encore (Effect 90)
# ---------------------------------------------------------------------------

def _eff_encore(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_last_move is None or state.mk_last_move_prevented:
        return False

    def rng_to_duration(c: 'BattleContext') -> int:
        return 3 + (c.advance_observable() % 4)

    ctx.emit(
        rng_to_token=rng_to_duration,
        question="Encore duration? (3-6):",
        input_to_token=lambda s: int(s.strip()),
    )
    return True


# ---------------------------------------------------------------------------
# Gravity (Effect 215)
# ---------------------------------------------------------------------------

def _eff_gravity(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.gravity_turns > 0:
        return False
    state.gravity_turns = 5
    return True


# ---------------------------------------------------------------------------
# Dream Eater (Effect 8)
# ---------------------------------------------------------------------------

def _eff_dream_eater(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.mk_status.status != NonVolatileStatus.SLEEP:
        ctx.advance_unobservable(1)  # hit check roll consumed but has no visible effect
        return False
    token = ctx.hit_crit_or_miss(move.accuracy)
    return not isinstance(token, Miss)


# ---------------------------------------------------------------------------
# Seismic Toss / Night Shade (Effect 87) — hit check only, no crit/damage
# ---------------------------------------------------------------------------

def _eff_seismic_toss(ctx: 'BattleContext', move: Move) -> bool:
    return _hit_check(ctx, move)


# ---------------------------------------------------------------------------
# Psywave (Effect 88) — special damage roll + hit check
# ---------------------------------------------------------------------------

def _eff_psywave(ctx: 'BattleContext', move: Move) -> bool:
    ctx.advance_unobservable(1)  # special damage roll
    return _hit_check(ctx, move)


# ---------------------------------------------------------------------------
# OHKO (Effect 38)
# ---------------------------------------------------------------------------

def _eff_ohko(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    user_lvl = state.user_level
    target_lvl = state.target_level

    def rng_to_token(c: 'BattleContext') -> PathToken:
        roll = c.advance_observable()
        if user_lvl < target_lvl:
            return Miss()  # always fails (but roll consumed)
        # Lock-On is already handled in effective_accuracy; OHKO bypasses accuracy
        # stages (it's not an accuracy check), so we check lock_on directly here.
        if state.user_lock_on_turns > 0:
            return Hit()  # guaranteed by Lock-On when user_lvl >= target_lvl
        threshold = 30 + user_lvl - target_lvl
        return Hit() if roll % 100 < threshold else Miss()

    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="OHKO hit? (h/-):",
        input_to_token=lambda s: Hit() if s.strip() == 'h' else Miss(),
    )
    return not isinstance(token, Miss)


# ---------------------------------------------------------------------------
# Multi-hit (Effect 29)
# ---------------------------------------------------------------------------

def _eff_multi_hit(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']

    # Roll hit count FIRST (before hit check), using unobservable rolls.
    # R1 % 4: 0→count=2, 1→count=3, 2 or 3→roll R2: count=2+(R2%4).
    # In interactive mode unobservable_roll() returns 0, giving count=2,
    # but the loop below stops when user signals 'd' so count is not used.
    r1 = ctx.unobservable_roll()
    if r1 % 4 >= 2:
        r2 = ctx.unobservable_roll()
        hit_count = 2 + (r2 % 4)
    else:
        hit_count = 2 if r1 % 4 == 0 else 3

    # First hit: full C/D/H sequence
    first_token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(first_token, Miss):
        return False

    # Subsequent hits: crit + damage only (no miss check).
    # Each hit is its own observable token (Crit or Hit) because Magikarp may
    # faint mid-sequence, making the total count unobservable.
    # In RNG mode: loop exactly hit_count-1 times.
    # In interactive mode: loop until user enters 'd' (done/fainted).
    _crit_mods = [16, 8, 4, 3, 2]
    hits_done = [0]  # mutable so rng closure can increment

    def rng_to_subsequent(c: 'BattleContext') -> 'PathToken | None':
        if hits_done[0] >= hit_count - 1:
            return None  # stop after correct number of hits
        crit_roll = c.advance_observable()
        c.advance_unobservable(1)  # damage roll
        total_crit_stage = state.user_crit_stage
        modifier = _crit_mods[min(total_crit_stage, 4)]
        hits_done[0] += 1
        return Crit() if crit_roll % modifier == 0 else Hit()

    def input_to_subsequent(s: str) -> 'PathToken | None':
        s = s.strip().lower()
        if s in ('d', 'done', 'e', 'end'):
            return None
        if s == '!':
            return Crit()
        if s == 'h':
            return Hit()
        raise ValueError(f"unknown multi-hit token: {s!r}. Use h, !, or d (done)")

    while True:
        token = ctx.emit(
            rng_to_token=rng_to_subsequent,
            question="Next hit? (h/!/d for done):",
            input_to_token=input_to_subsequent,
        )
        if token is None:
            break

    return True


# ---------------------------------------------------------------------------
# Double-hit (Effect 44)
# ---------------------------------------------------------------------------

def _eff_double_hit(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.advance_unobservable(2)  # 2 contact rolls
    ctx.advance_unobservable(2)  # crit + damage for second hit
    return True


# ---------------------------------------------------------------------------
# Triple Kick (Effect 104)
# ---------------------------------------------------------------------------

def _eff_triple_kick(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.advance_unobservable(2)  # 2 contact rolls
    token2 = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token2, Miss):
        return True
    ctx.advance_unobservable(2)  # 2 contact rolls
    ctx.hit_crit_or_miss(move.accuracy)
    return True


# ---------------------------------------------------------------------------
# Twineedle (Effect 77)
# ---------------------------------------------------------------------------

def _eff_twineedle(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    poison = _status_applier(ctx, NonVolatileStatus.POISON)
    ctx.effect_proc(move.effect_chance, poison)  # first poison roll
    ctx.advance_unobservable(2)                  # 2 contact rolls
    ctx.advance_unobservable(2)                  # crit + damage for second hit
    # Same applier: if the first proc poisoned, the second sees an existing status
    # and is not observable, matching the game (a target can't be poisoned twice).
    ctx.effect_proc(move.effect_chance, poison)  # second poison roll
    return True


# ---------------------------------------------------------------------------
# Bind / Wrap / Whirlpool (Effects 42, 261)
# ---------------------------------------------------------------------------

def _eff_bind(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    if state.mk_binding_turns > 0:
        return True  # Already bound; no new duration roll

    def rng_to_duration(c: 'BattleContext') -> int:
        return 3 + (c.advance_observable() % 3)

    duration = ctx.emit(
        rng_to_token=rng_to_duration,
        question="Binding duration? (3-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.mk_binding_turns = int(duration)
    return True


# ---------------------------------------------------------------------------
# Leech Seed (Effect 84)
# ---------------------------------------------------------------------------

def _eff_leech_seed(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_seeded:
        return False
    state.mk_seeded = True
    return True


# ---------------------------------------------------------------------------
# Torment (Effect 165)
# ---------------------------------------------------------------------------

def _eff_torment(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_tormented:
        return False
    state.mk_tormented = True
    return True


# ---------------------------------------------------------------------------
# Nightmare (Effect 107)
# ---------------------------------------------------------------------------

def _eff_nightmare(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_status.status != NonVolatileStatus.SLEEP:
        return False
    if state.mk_nightmare:
        return False
    state.mk_nightmare = True
    return True


# ---------------------------------------------------------------------------
# Hyper Beam / recharge (Effect 80)
# ---------------------------------------------------------------------------

def _eff_hyper_beam(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    state.user_recharging = True
    return True


# ---------------------------------------------------------------------------
# Magnitude (Effect 126)
# ---------------------------------------------------------------------------

def _eff_magnitude(ctx: 'BattleContext', move: Move) -> bool:
    def rng_to_token(c: 'BattleContext') -> PathToken:
        roll = c.advance_observable() % 100
        if roll < 5:    mag = 4
        elif roll < 15: mag = 5
        elif roll < 35: mag = 6
        elif roll < 65: mag = 7
        elif roll < 85: mag = 8
        elif roll < 95: mag = 9
        else:           mag = 10
        return Magnitude(mag)

    ctx.emit(
        rng_to_token=rng_to_token,
        question="Magnitude level? (4-10):",
        input_to_token=lambda s: Magnitude(int(s.strip())),
    )
    token = ctx.hit_crit_or_miss(move.accuracy)
    return not isinstance(token, Miss)


# ---------------------------------------------------------------------------
# Tri Attack (Effect 36)
# ---------------------------------------------------------------------------

def _eff_tri_attack(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']

    _STATUS = [NonVolatileStatus.BURN, NonVolatileStatus.FROZEN, NonVolatileStatus.PARALYZED]
    _LABEL = ['BRN', 'FRZ', 'PAR']

    # Type roll is unobservable to the player but determines which status applies on proc.
    # In RNG mode unobservable_roll() returns the actual value; in interactive returns 0.
    type_val = ctx.unobservable_roll()
    status_type = _STATUS[type_val % 3]
    status_label = _LABEL[type_val % 3]

    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False

    # Proc roll: observable. EffectProc carries the applied status label.
    applier = _status_applier(ctx, status_type)

    def rng_to_proc(c: 'BattleContext') -> 'PathToken | None':
        roll = c.advance_observable()
        if roll % 100 < move.effect_chance:
            observable = applier()
            if observable:
                return EffectProc(status=status_label)
        return None

    def input_to_proc(s: str) -> 'PathToken | None':
        s = s.strip().upper().lstrip('~').strip('<>')
        if s == '-' or s == '':
            return None
        if s in ('BRN', 'FRZ', 'PAR'):
            # Apply the observed status in interactive mode
            st = _STATUS[_LABEL.index(s)]
            if state.mk_status.status == NonVolatileStatus.NONE:
                state.mk_status.status = st
            return EffectProc(status=s)
        raise ValueError(f"unknown Tri Attack proc: {s!r}. Use ~<BRN>, ~<FRZ>, ~<PAR>, or -")

    ctx.emit(
        rng_to_token=rng_to_proc,
        question="Tri Attack proc? (~<BRN>/~<FRZ>/~<PAR>/-):",
        input_to_token=input_to_proc,
    )
    return True


# ---------------------------------------------------------------------------
# Present (Effect 122)
# ---------------------------------------------------------------------------

def _eff_present(ctx: 'BattleContext', move: Move) -> bool:
    def rng_to_token(c: 'BattleContext') -> PathToken:
        roll = c.advance_observable()
        return Hit() if (roll & 0xFF) < 204 else Miss()

    mode_token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Present: damage or heal? (h=damage, -=heal):",
        input_to_token=lambda s: Hit() if s.strip() == 'h' else Miss(),
    )
    if not isinstance(mode_token, Miss):
        hit_token = ctx.hit_crit_or_miss(move.accuracy)
        return not isinstance(hit_token, Miss)
    else:
        return _hit_check(ctx, move)


# ---------------------------------------------------------------------------
# Thunder (Effect 152) — weather-dependent accuracy
# ---------------------------------------------------------------------------

def _eff_thunder(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'rain':
        token = ctx.hit_crit_or_miss(0)       # always hits
    elif state.weather == 'sunny':
        token = ctx.hit_crit_or_miss(50)      # accuracy 50 in sun
    else:
        token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance, _status_applier(ctx, NonVolatileStatus.PARALYZED))
    return True


# ---------------------------------------------------------------------------
# Blizzard (Effect 260) — weather-dependent
# ---------------------------------------------------------------------------

def _eff_blizzard(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'hail':
        token = ctx.hit_crit_or_miss(0)       # always hits in hail
    else:
        token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance,
                    _status_applier(ctx, NonVolatileStatus.FROZEN, block_weather='sunny'))
    return True


# ---------------------------------------------------------------------------
# Fake Out (Effect 158) — only works on first turn
# ---------------------------------------------------------------------------

def _eff_fake_out(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.turn_number == 1:
        token = ctx.hit_crit_or_miss(move.accuracy)
        if isinstance(token, Miss):
            return False
        ctx.advance_unobservable(1)  # flinch chance roll (100%, still rolled)
        return True
    ctx.advance_unobservable(1)  # hit check roll consumed but not observable; move then fails
    return False


# ---------------------------------------------------------------------------
# Spider Web / Mean Look / Block (Effect 106) — no rolls
# ---------------------------------------------------------------------------

def _eff_spider_web(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.mk_blocked:
        return False
    state.mk_blocked = True
    return True


# ---------------------------------------------------------------------------
# Yawn (Effect 187) — no rolls; sleep applied end of next turn
# ---------------------------------------------------------------------------

def _eff_yawn(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.mk_drowsy_turns > 0 or state.mk_status.status != NonVolatileStatus.NONE:
        return False
    if state.mk_insomnia:
        return False
    state.mk_drowsy_turns = 2  # ticks each turn; at 0 sleep is applied
    return True


# ---------------------------------------------------------------------------
# Beat Up (Effect 154) — simplified: assume 6-member party
# ---------------------------------------------------------------------------

def _eff_beat_up(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.advance_unobservable(2)  # successful-move rolls for main pokemon
    # 5 additional party members: crit + damage each (no hit check) + success rolls
    for _ in range(5):
        ctx.advance_unobservable(2)  # crit + damage
        ctx.advance_unobservable(2)  # successful-move rolls
    return True


# ---------------------------------------------------------------------------
# Acupressure (Effect 226) — observable stat selection, raise by 2
# ---------------------------------------------------------------------------

_ACUPRESSURE_ATTRS = [
    ('user_atk_stage', 'Attack'),
    ('user_def_stage', 'Defense'),
    ('user_spd_stage', 'Speed'),
    ('user_spatk_stage', 'Sp. Atk'),
    ('user_spdef_stage', 'Sp. Def'),
    ('user_accuracy_stage', 'Accuracy'),
    ('user_evasion_stage', 'Evasion'),
]


def _eff_acupressure(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState, PathToken
    from .path import EffectProc
    state: MetronomeBattleState = ctx.battle_state['state']

    eligible = [(attr, name) for attr, name in _ACUPRESSURE_ATTRS
                if getattr(state, attr) < 6]
    if not eligible:
        # All stats maxed; roll still consumed but move effectively does nothing
        ctx.advance_unobservable(1)
        return True

    def rng_to_token(c: 'BattleContext') -> EffectProc:
        roll = c.advance_observable()
        idx = roll % len(eligible)
        attr, name = eligible[idx]
        setattr(state, attr, min(6, getattr(state, attr) + 2))
        return EffectProc(status=name[:3].upper())  # encode chosen stat in token

    def input_to_token(s: str) -> EffectProc:
        s = s.strip().upper()
        # Accept full name prefix or abbreviated
        for attr, name in eligible:
            if name.upper().startswith(s) or s == name.upper()[:3]:
                setattr(state, attr, min(6, getattr(state, attr) + 2))
                return EffectProc(status=name[:3].upper())
        raise ValueError(f"unknown Acupressure stat: {s!r}. Options: {[n[:3] for _, n in eligible]}")

    ctx.emit(
        rng_to_token=rng_to_token,
        question=f"Acupressure raised which stat? ({'/'.join(n[:3] for _, n in eligible)}):",
        input_to_token=input_to_token,
    )
    return True


# ---------------------------------------------------------------------------
# Trick Room (Effect 259) — 4 extra unobservable rolls
# ---------------------------------------------------------------------------

def _eff_trick_room(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_trick_room_turns > 0:
        state.user_trick_room_turns = 0
    else:
        state.user_trick_room_turns = 5
    ctx.advance_unobservable(4)
    return True


# ---------------------------------------------------------------------------
# Spit Up (Effect 161)
# ---------------------------------------------------------------------------

def _eff_spit_up(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_stockpile == 0:
        _hit_check(ctx, move)
        return False
    # Spit Up: crit (observable) + hit (observable), NO damage roll.
    _crit_mods = [16, 8, 4, 3, 2]
    total_crit = state.user_crit_stage
    modifier = _crit_mods[min(total_crit, 4)]

    def rng_to_token(c: 'BattleContext') -> PathToken:
        crit_roll = c.advance_observable()
        is_crit = crit_roll % modifier == 0
        if move.accuracy == 0:
            return Crit() if is_crit else Hit()
        hit_roll = c.advance_observable()
        is_hit = hit_roll % 100 < c.effective_accuracy(move.accuracy)
        if not is_hit:
            return Miss()
        return Crit() if is_crit else Hit()

    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Spit Up hit, crit, or miss? (h/!/-):",
        input_to_token=lambda s: {'h': Hit(), '!': Crit(), '-': Miss()}[s.strip()],
    )
    if not isinstance(token, Miss):
        state.user_stockpile = 0
        return True
    return False


# ---------------------------------------------------------------------------
# Captivate (Effect 265) — fails before hit check if same gender
# ---------------------------------------------------------------------------

def _eff_captivate(ctx: 'BattleContext', move: Move) -> bool:
    if not ctx.battle_state.get('opposite_gender', False):
        return False  # fails without a hit check
    return _hit_check(ctx, move)


# ---------------------------------------------------------------------------
# Path-ending effects
# ---------------------------------------------------------------------------

def _eff_selfdestruct(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    _emit_path_end(ctx)
    return not isinstance(token, Miss)


def _eff_teleport(ctx: 'BattleContext', move: Move) -> bool:
    _emit_path_end(ctx)
    return False


def _eff_healing_wish(ctx: 'BattleContext', move: Move) -> bool:
    _emit_path_end(ctx)
    return True


def _eff_lunar_dance(ctx: 'BattleContext', move: Move) -> bool:
    _emit_path_end(ctx)
    return True


def _eff_memento(ctx: 'BattleContext', move: Move) -> bool:
    if not _hit_check(ctx, move):
        return False
    _emit_path_end(ctx)
    return True


def _eff_whirlwind(ctx: 'BattleContext', move: Move) -> bool:
    _hit_check(ctx, move)         # hit roll still performed
    ctx.advance_unobservable(1)  # CelebiCutscene_InitSwirlData roll
    _emit_path_end(ctx)
    return True


def _eff_u_turn(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    _emit_path_end(ctx)
    return True


def _eff_fling(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    _emit_path_end(ctx)
    return True


def _eff_baton_pass(ctx: 'BattleContext', move: Move) -> bool:
    _emit_path_end(ctx)
    return True


# ---------------------------------------------------------------------------
# No-roll effects (state bookkeeping only)
# ---------------------------------------------------------------------------

def _eff_splash(ctx: 'BattleContext', move: Move) -> bool:
    return False  # animation doesn't play; not "successful"


def _eff_recovery(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_is_full_hp:
        return False
    state.user_is_full_hp = True
    return True


def _eff_rest(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_is_full_hp:
        return False
    state.user_is_full_hp = True
    state.user_sleep_turns = 2  # Chansey can't act for the next 2 turns
    return True


def _eff_hidden_power(ctx: 'BattleContext', move: Move) -> bool:
    """Hidden Power (135): standard C/D/H, but Unsupported if Magikarp is frozen.

    A Fire-type Hidden Power would thaw Magikarp, which we can't model without
    knowing the HP type. End path preemptively on a frozen target.
    """
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.mk_status.status == NonVolatileStatus.FROZEN:
        ctx.raw_emit(Unsupported())
        ctx.raw_emit(PathEnd())
        ctx.battle_state['unsupported'] = True
        return False
    token = ctx.hit_crit_or_miss(move.accuracy)
    return not isinstance(token, Miss)


def _eff_lock_on(ctx: 'BattleContext', move: Move) -> bool:
    """Mind Reader / Lock-On (effect 94): sets guaranteed-hit for next turn.

    Does not fail if already active; just resets the counter.
    user_lock_on_turns is decremented at end of turn in simulate_turn.
    """
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_lock_on_turns = 1  # active through end of the following turn
    return True


def _eff_focus_energy(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_focus_energy:
        return False
    state.user_focus_energy = True
    state.user_crit_stage = 2  # Focus Energy raises the user's crit stage by 2 (Gen IV)
    return True


def _eff_light_screen(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_light_screen_turns > 0:
        return False
    state.user_light_screen_turns = 5
    return True


def _eff_reflect(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_reflect_turns > 0:
        return False
    state.user_reflect_turns = 5
    return True


def _eff_mist(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_mist_turns > 0:
        return False
    state.user_mist_turns = 5
    return True


def _eff_safeguard(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_safeguard_turns > 0:
        return False
    state.user_safeguard_turns = 5
    return True


def _eff_tailwind(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_tailwind_turns > 0:
        return False
    state.user_tailwind_turns = 3
    return True


def _eff_lucky_chant(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_lucky_chant_turns > 0:
        return False
    state.user_lucky_chant_turns = 5
    return True


def _eff_perish_song(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_perish_song_turns > 0 and state.mk_perish_song_turns > 0:
        return False
    state.user_perish_song_turns = 4
    state.mk_perish_song_turns = 4
    return True


def _eff_rain_dance(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'rain':
        return False
    state.weather = 'rain'
    state.weather_until = state.turn_number + 5
    return True


def _eff_sunny_day(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'sunny':
        return False
    state.weather = 'sunny'
    state.weather_until = state.turn_number + 5
    return True


def _eff_sandstorm(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'sand':
        return False
    state.weather = 'sand'
    state.weather_until = state.turn_number + 5
    return True


def _eff_hail(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'hail':
        return False
    state.weather = 'hail'
    state.weather_until = state.turn_number + 5
    return True


def _eff_spikes(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.opp_spikes >= 3:
        return False
    state.opp_spikes += 1
    return True


def _eff_toxic_spikes(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.opp_toxic_spikes >= 2:
        return False
    state.opp_toxic_spikes += 1
    return True


def _eff_stealth_rock(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.opp_stealth_rock:
        return False
    state.opp_stealth_rock = True
    return True


def _eff_mud_sport(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_mud_sport:
        return False
    state.user_mud_sport = True
    return True


def _eff_camouflage(ctx: 'BattleContext', move: Move) -> bool:
    """Camouflage (213): become Water type in the Safari Zone environment. Fails if already Water."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if 'Water' in state.user_types:
        return False
    state.user_types = ['Water']
    return True


def _eff_water_sport(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_water_sport:
        return False
    state.user_water_sport = True
    return True


def _eff_aqua_ring(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_aqua_ring:
        return False
    state.user_aqua_ring = True
    return True


def _eff_magnet_rise(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_magnet_rise_turns > 0 or state.user_ingrained:
        return False
    state.user_magnet_rise_turns = 5
    return True


def _eff_ingrain(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_ingrained = True
    return True


def _eff_substitute(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not state.user_is_full_hp or state.user_substitute:
        return False
    state.user_substitute = True
    state.user_is_full_hp = False
    return True


def _eff_belly_drum(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not state.user_is_full_hp:
        return False
    state.user_is_full_hp = False
    state.user_atk_stage = 6  # Belly Drum maxes out Attack
    return True


def _eff_stockpile(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_stockpile >= 3:
        return False
    state.user_stockpile += 1
    return True


def _eff_swallow(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_stockpile == 0:
        return False
    state.user_stockpile = 0
    state.user_is_full_hp = True
    return True


def _eff_defog(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.opp_spikes = 0
    state.opp_toxic_spikes = 0
    state.opp_stealth_rock = False
    if state.target_evasion_stage > -6:
        state.target_evasion_stage -= 1  # Defog also lowers the target's evasion
    return True


def _eff_pain_split(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_is_full_hp = False  # user HP equalizes, no longer full
    return True


def _eff_embargo(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_embargo:
        return False
    state.mk_embargo = True
    return True


def _eff_heal_block(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_heal_block:
        return False
    state.mk_heal_block = True
    return True


def _eff_gastro_acid(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.mk_gastro_acid:
        return False
    state.mk_gastro_acid = True
    return True


def _eff_worry_seed(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    # Magikarp gains Insomnia; cancels drowsy, cures sleep, blocks future sleep moves
    state.mk_insomnia = True
    state.mk_drowsy_turns = 0
    if state.mk_status.status == NonVolatileStatus.SLEEP:
        state.mk_status.status = NonVolatileStatus.NONE
        state.mk_status.sleep_turns = 0
    return True


# Moves with only a hit check and no observable secondary (stat changes, etc.)
def _eff_hit_only(ctx: 'BattleContext', move: Move) -> bool:
    return _hit_check(ctx, move)


def _eff_hit_then_fail(ctx: 'BattleContext', move: Move) -> bool:
    """Moves that roll a hit check but always fail when called by Metronome.

    (Snore, Last Resort, Sucker Punch, Psycho Shift, Natural Gift.) The accuracy
    roll is consumed but shows no observable result — the game reports the
    failure, not a hit/miss — so no Hit/Miss token is emitted.
    """
    ctx.advance_unobservable(1)
    return False


def _eff_stat_hit(ctx: 'BattleContext', move: Move,
                  attr: str, amount: int) -> bool:
    """Hit-check then apply stat stage change; always observable (move shows "not affected" only at cap in some games, but here we still emit Hit)."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    current = getattr(state, attr)
    setattr(state, attr, max(-6, min(6, current + amount)))
    return True


def _eff_growl(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_atk_stage', -1)


def _eff_leer(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_def_stage', -1)


def _eff_string_shot(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_spd_stage', -1)


def _eff_charm(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_atk_stage', -2)


def _eff_screech(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_def_stage', -2)


def _eff_scary_face(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_spd_stage', -2)


def _eff_fake_tears(ctx: 'BattleContext', move: Move) -> bool:
    return _eff_stat_hit(ctx, move, 'target_spdef_stage', -2)


def _eff_tickle(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    state.target_atk_stage = max(-6, state.target_atk_stage - 1)
    state.target_def_stage = max(-6, state.target_def_stage - 1)
    return True


def _eff_lower_target_evasion(ctx: 'BattleContext', move: Move) -> bool:
    """Sweet Scent (24): hit check, then lower Magikarp's evasion by 1 stage.

    Evasion feeds the hit formula, so this is NOT a no-op: it raises the hit
    rate of our subsequent moves and shifts their hit/crit/miss rolls.
    """
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.target_evasion_stage > -6:
        state.target_evasion_stage -= 1
    return True


def _eff_lower_target_accuracy(ctx: 'BattleContext', move: Move) -> bool:
    """Sand Attack / Smoke Screen / Kinesis / Flash (23): lower Magikarp accuracy."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if not _hit_check(ctx, move):
        return False
    if state.target_accuracy_stage > -6:
        state.target_accuracy_stage -= 1
    return True


def _eff_haze(ctx: 'BattleContext', move: Move) -> bool:
    """Haze (25): reset all stat stages of both sides. No rolls.

    Focus Energy is a volatile status, not a stat stage, so it is not cleared.
    """
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    for attr in (
        'user_atk_stage', 'user_def_stage', 'user_spd_stage',
        'user_spatk_stage', 'user_spdef_stage',
        'user_evasion_stage', 'user_accuracy_stage',
        'target_atk_stage', 'target_def_stage', 'target_spd_stage',
        'target_spatk_stage', 'target_spdef_stage',
        'target_evasion_stage', 'target_accuracy_stage',
    ):
        setattr(state, attr, 0)
    return True


def _eff_wake_up_slap(ctx: 'BattleContext', move: Move) -> bool:
    """Wake-Up Slap (217): C/D/H; on hit, cures Magikarp's sleep."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    if state.mk_status.status == NonVolatileStatus.SLEEP:
        state.mk_status.status = NonVolatileStatus.NONE
        state.mk_status.sleep_turns = 0
    return True


def _eff_smelling_salt(ctx: 'BattleContext', move: Move) -> bool:
    """Smelling Salt (171): C/D/H; on hit, cures Magikarp's paralysis."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    if state.mk_status.status == NonVolatileStatus.PARALYZED:
        state.mk_status.status = NonVolatileStatus.NONE
    return True


def _eff_stat_boost(ctx: 'BattleContext', attrs_amounts: list[tuple[str, int]]) -> bool:
    """Apply no-roll stat stage changes. Always returns True."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    for attr, amount in attrs_amounts:
        current = getattr(state, attr)
        setattr(state, attr, max(-6, min(6, current + amount)))
    return True


def _eff_meditate(ctx: 'BattleContext', move: Move) -> bool:  # effect 10: atk+1
    return _eff_stat_boost(ctx, [('user_atk_stage', 1)])

def _eff_harden(ctx: 'BattleContext', move: Move) -> bool:  # effect 11: def+1
    return _eff_stat_boost(ctx, [('user_def_stage', 1)])

def _eff_growth(ctx: 'BattleContext', move: Move) -> bool:  # effect 13: spatk+1
    return _eff_stat_boost(ctx, [('user_spatk_stage', 1)])

def _eff_double_team(ctx: 'BattleContext', move: Move) -> bool:  # effect 16: eva+1
    return _eff_stat_boost(ctx, [('user_evasion_stage', 1)])

def _eff_swords_dance(ctx: 'BattleContext', move: Move) -> bool:  # effect 50: atk+2
    return _eff_stat_boost(ctx, [('user_atk_stage', 2)])

def _eff_barrier(ctx: 'BattleContext', move: Move) -> bool:  # effect 51: def+2
    return _eff_stat_boost(ctx, [('user_def_stage', 2)])

def _eff_agility(ctx: 'BattleContext', move: Move) -> bool:  # effect 52: spd+2
    return _eff_stat_boost(ctx, [('user_spd_stage', 2)])

def _eff_nasty_plot(ctx: 'BattleContext', move: Move) -> bool:  # effect 53: spatk+2
    return _eff_stat_boost(ctx, [('user_spatk_stage', 2)])

def _eff_amnesia(ctx: 'BattleContext', move: Move) -> bool:  # effect 54: spdef+2
    return _eff_stat_boost(ctx, [('user_spdef_stage', 2)])

def _eff_minimize(ctx: 'BattleContext', move: Move) -> bool:  # effect 108: eva+1
    return _eff_stat_boost(ctx, [('user_evasion_stage', 1)])

def _eff_curse_stat(ctx: 'BattleContext', move: Move) -> bool:  # effect 109: atk+1, def+1, spd-1
    return _eff_stat_boost(ctx, [('user_atk_stage', 1), ('user_def_stage', 1), ('user_spd_stage', -1)])

def _eff_defense_curl(ctx: 'BattleContext', move: Move) -> bool:  # effect 156: def+1
    return _eff_stat_boost(ctx, [('user_def_stage', 1)])

def _eff_charge(ctx: 'BattleContext', move: Move) -> bool:  # effect 174: spdef+1
    return _eff_stat_boost(ctx, [('user_spdef_stage', 1)])

def _eff_cosmic_power(ctx: 'BattleContext', move: Move) -> bool:  # effect 206: def+1, spdef+1
    return _eff_stat_boost(ctx, [('user_def_stage', 1), ('user_spdef_stage', 1)])

def _eff_bulk_up(ctx: 'BattleContext', move: Move) -> bool:  # effect 208: atk+1, def+1
    return _eff_stat_boost(ctx, [('user_atk_stage', 1), ('user_def_stage', 1)])

def _eff_calm_mind(ctx: 'BattleContext', move: Move) -> bool:  # effect 211: spatk+1, spdef+1
    return _eff_stat_boost(ctx, [('user_spatk_stage', 1), ('user_spdef_stage', 1)])

def _eff_dragon_dance(ctx: 'BattleContext', move: Move) -> bool:  # effect 212: atk+1, spd+1
    return _eff_stat_boost(ctx, [('user_atk_stage', 1), ('user_spd_stage', 1)])

def _eff_power_trick(ctx: 'BattleContext', move: Move) -> bool:  # effect 238: swap user atk/def
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_atk_stage, state.user_def_stage = state.user_def_stage, state.user_atk_stage
    return True

def _eff_psych_up(ctx: 'BattleContext', move: Move) -> bool:  # effect 143: copy target stat stages
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_atk_stage = state.target_atk_stage
    state.user_def_stage = state.target_def_stage
    state.user_spd_stage = state.target_spd_stage
    state.user_spatk_stage = state.target_spatk_stage
    state.user_spdef_stage = state.target_spdef_stage
    state.user_accuracy_stage = state.target_accuracy_stage
    state.user_evasion_stage = state.target_evasion_stage
    return True

def _eff_power_swap(ctx: 'BattleContext', move: Move) -> bool:  # effect 243: swap atk+spatk
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_atk_stage, state.target_atk_stage = state.target_atk_stage, state.user_atk_stage
    state.user_spatk_stage, state.target_spatk_stage = state.target_spatk_stage, state.user_spatk_stage
    return True

def _eff_guard_swap(ctx: 'BattleContext', move: Move) -> bool:  # effect 244: swap def+spdef
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_def_stage, state.target_def_stage = state.target_def_stage, state.user_def_stage
    state.user_spdef_stage, state.target_spdef_stage = state.target_spdef_stage, state.user_spdef_stage
    return True

def _eff_heart_swap(ctx: 'BattleContext', move: Move) -> bool:  # effect 250: swap all stat stages
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    # Check if Magikarp would gain any evasion (from Minimize etc.)
    if state.user_evasion_stage > state.target_evasion_stage:
        # Magikarp gains user's evasion advantage → end path (Unsupported)
        _emit_path_end(ctx)
        return True
    # Swap all stat stages
    for u, t in [
        ('user_atk_stage', 'target_atk_stage'),
        ('user_def_stage', 'target_def_stage'),
        ('user_spd_stage', 'target_spd_stage'),
        ('user_spatk_stage', 'target_spatk_stage'),
        ('user_spdef_stage', 'target_spdef_stage'),
        ('user_accuracy_stage', 'target_accuracy_stage'),
        ('user_evasion_stage', 'target_evasion_stage'),
    ]:
        uv, tv = getattr(state, u), getattr(state, t)
        setattr(state, u, tv)
        setattr(state, t, uv)
    return True


# No rolls, always succeeds
def _eff_no_rolls_ok(ctx: 'BattleContext', move: Move) -> bool:
    return True


# No rolls, always fails
def _eff_no_rolls_fail(ctx: 'BattleContext', move: Move) -> bool:
    return False


# ---------------------------------------------------------------------------
# Conversion (Effect 30)
# ---------------------------------------------------------------------------

def _eff_conversion(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    user_move_types: list[str] = ctx.battle_state.get('user_move_types', ['Normal'])

    n_moves = len(user_move_types)
    if all(t in state.user_types for t in user_move_types):
        return False  # Every move matches the user's current type(s); nothing to change

    def rng_to_token(c: 'BattleContext') -> ConversionType:
        while True:
            roll = c.advance_observable()
            chosen = user_move_types[roll % n_moves]
            if chosen not in state.user_types:
                return ConversionType(chosen)

    eligible = [t for t in user_move_types if t not in state.user_types]
    token = ctx.emit(
        rng_to_token=rng_to_token,
        question=f"Conversion type? ({'/'.join(dict.fromkeys(eligible))}):",
        input_to_token=lambda s: ConversionType(s.strip().capitalize()),
    )
    state.user_types = [token.type_name]
    return True


# ---------------------------------------------------------------------------
# Unsupported (complex consecutive or two-turn moves)
# ---------------------------------------------------------------------------

def _eff_unsupported(ctx: 'BattleContext', move: Move) -> bool:
    ctx.raw_emit(Unsupported())
    ctx.raw_emit(PathEnd())
    ctx.battle_state['unsupported'] = True
    return False


# ---------------------------------------------------------------------------
# Bide (26)
# Turn 1: no rolls, sets lock for 2 continuation turns.
# Turn 2: counts as successful (no rolls).
# Turn 3: if triggered (Magikarp hit with Tackle/Struggle while biding) → deal damage,
#          no rolls. If not triggered → fails. Substitute active → Unsupported.
# ---------------------------------------------------------------------------

def _eff_bide(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_substitute:
        ctx.raw_emit(Unsupported())
        ctx.raw_emit(PathEnd())
        ctx.battle_state['unsupported'] = True
        return False
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 2
    state.user_bide_triggered = False
    return True


# ---------------------------------------------------------------------------
# Conversion 2 (93)
# Prereq: Magikarp hit with Tackle or Struggle since switch-in / last C2 use.
# Rolls %112 against the effectiveness table; since Magikarp is Normal-type only,
# valid results are indices 0 (Rock), 1 (Steel), 109 (Ghost).
# Emits a ConversionType token for the chosen type.
# ---------------------------------------------------------------------------

def _eff_conversion2(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']

    if not state.user_was_hit:
        return False  # Not hit by Normal-type attack since switch-in or last use

    # Valid target types: resist/immune to Normal, excluding user's current types
    _NORMAL_RESISTS = {0: 'Rock', 1: 'Steel', 109: 'Ghost'}
    valid = {k: v for k, v in _NORMAL_RESISTS.items() if v not in state.user_types}
    if not valid:
        return False  # All possible types already user's type

    state.user_was_hit = False  # Consumed; reset for next Conversion 2 use

    def rng_to_token(c: 'BattleContext') -> ConversionType:
        for _ in range(1000):
            roll = c.advance_observable()
            idx = roll % 112
            if idx in valid:
                return ConversionType(valid[idx])
        # Fallback: linear scan (essentially unreachable)
        return ConversionType(valid[min(valid)])

    eligible = list(valid.values())
    token = ctx.emit(
        rng_to_token=rng_to_token,
        question=f"Conversion 2 type? ({'/'.join(eligible)}):",
        input_to_token=lambda s: ConversionType(s.strip().capitalize()),
    )
    state.user_types = [token.type_name]
    return True


# ---------------------------------------------------------------------------
# Group A: Charge-and-fire (Fly/Dive/Dig/Razor Wind/Shadow Force)
# Effects 39, 155, 255, 256, 272 — turn 1 sets lock, no rolls
# ---------------------------------------------------------------------------

def _eff_charge_fire(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 1
    return True


# ---------------------------------------------------------------------------
# Group B: Charge-and-fire with secondary
# Sky Attack (75): turn 1 sets lock; turn 2 C/D/H + unobservable flinch
# ---------------------------------------------------------------------------

def _eff_sky_attack(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 1
    return True


def _eff_bounce(ctx: 'BattleContext', move: Move) -> bool:
    """Bounce (263): turn 1 sets lock; turn 2 C/D/H + observable paralyze proc."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 1
    return True


def _eff_skull_bash(ctx: 'BattleContext', move: Move) -> bool:
    """Skull Bash (145): 1 unobservable roll turn 1, then lock; turn 2 C/D/H."""
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    ctx.advance_unobservable(1)  # purpose unknown (#FUTUREWORK)
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 1
    return True


# ---------------------------------------------------------------------------
# Group C: Solar Beam (151) — weather-conditional charge
# In harsh sunlight: fires immediately. Otherwise: charge turn 1, fire turn 2.
# ---------------------------------------------------------------------------

def _eff_solar_beam(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.weather == 'sunny':
        token = ctx.hit_crit_or_miss(move.accuracy)
        return not isinstance(token, Miss)
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 1
    return True


# ---------------------------------------------------------------------------
# Group D: Rampage moves
# Thrash (27): turn 1 C/D/H + duration roll; continuation C/D/H; confusion at end
# Uproar (159): turn 1 C/D/H + duration roll; continuation C/D/H; no early exit on miss
# ---------------------------------------------------------------------------

def _eff_thrash(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    def rng_to_total(c: 'BattleContext') -> int:
        return 2 + (c.advance_observable() % 2)
    total_turns = ctx.emit(
        rng_to_token=rng_to_total,
        question="Thrash duration? (2-3 total turns):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = int(total_turns) - 1
    return True


def _eff_uproar(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    def rng_to_extra(c: 'BattleContext') -> int:
        return 2 + (c.advance_observable() % 4)
    extra_turns = ctx.emit(
        rng_to_token=rng_to_extra,
        question="Uproar extra turns after turn 1? (2-5):",
        input_to_token=lambda s: int(s.strip()),
    )
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = int(extra_turns)
    return True


# ---------------------------------------------------------------------------
# Group E: Rollout / Ice Ball (117)
# Turn 1: C/D/H; if hit lock for 4 continuation turns. Miss on any turn ends lock.
# ---------------------------------------------------------------------------

def _eff_rollout(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    state.user_locked_move_num = move.number
    state.user_locked_effect = move.effect
    state.user_locked_turns = 4
    return True


# ---------------------------------------------------------------------------
# Group F: Future Sight / Doom Desire (148)
# Turn 1: unobservable damage roll, set 3-turn counter. NOT a locked move.
# If already active: extra roll consumed, move fails.
# End-of-turn when counter hits 0: observable hit check fired in simulate_turn.
# ---------------------------------------------------------------------------

def _eff_future_sight(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    ctx.advance_unobservable(1)  # damage roll
    if state.future_sight_turns > 0:
        ctx.advance_unobservable(1)  # extra hit check roll when re-used while active
        return False
    state.future_sight_turns = 3
    state.future_sight_move_num = move.number
    return True


# ---------------------------------------------------------------------------
# Locked-move continuation dispatcher (called by simulate_turn)
# ---------------------------------------------------------------------------

def simulate_locked_continuation(ctx: 'BattleContext', state: object, locked_move: Move) -> bool:
    """Execute the continuation turn for a locked move. user_locked_turns already decremented."""
    effect = state.user_locked_effect  # type: ignore[attr-defined]

    if effect == 26:  # Bide
        if state.user_locked_turns > 0:  # type: ignore[attr-defined]
            # Turn 2: Bide continues, counts as successful, no rolls
            return True
        # Turn 3 (last): final outcome
        if state.user_substitute:  # type: ignore[attr-defined]
            ctx.raw_emit(Unsupported())
            ctx.raw_emit(PathEnd())
            ctx.battle_state['unsupported'] = True
            return False
        triggered = state.user_bide_triggered  # type: ignore[attr-defined]
        state.user_bide_triggered = False      # type: ignore[attr-defined]
        state.user_locked_move_num = None      # type: ignore[attr-defined]
        state.user_locked_effect = None        # type: ignore[attr-defined]
        return triggered  # True = damage dealt (no rolls); False = move fails

    elif effect in {39, 155, 255, 256, 272}:  # Group A: charge-fire
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        state.user_locked_move_num = None  # type: ignore[attr-defined]
        state.user_locked_effect = None    # type: ignore[attr-defined]
        return not isinstance(token, Miss)

    elif effect == 151:  # Solar Beam charge continuation
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        state.user_locked_move_num = None  # type: ignore[attr-defined]
        state.user_locked_effect = None    # type: ignore[attr-defined]
        return not isinstance(token, Miss)

    elif effect == 75:  # Sky Attack: C/D/H + unobservable flinch on hit
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        state.user_locked_move_num = None  # type: ignore[attr-defined]
        state.user_locked_effect = None    # type: ignore[attr-defined]
        if not isinstance(token, Miss):
            ctx.advance_unobservable(1)  # flinch roll (unobservable; we go second)
            return True
        return False

    elif effect == 263:  # Bounce: C/D/H + observable paralyze proc on hit
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        state.user_locked_move_num = None  # type: ignore[attr-defined]
        state.user_locked_effect = None    # type: ignore[attr-defined]
        if not isinstance(token, Miss):
            ctx.effect_proc(locked_move.effect_chance)
            return True
        return False

    elif effect == 145:  # Skull Bash: C/D/H only (unobservable roll was on turn 1)
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        state.user_locked_move_num = None  # type: ignore[attr-defined]
        state.user_locked_effect = None    # type: ignore[attr-defined]
        return not isinstance(token, Miss)

    elif effect == 27:  # Thrash/Outrage/Petal Dance: C/D/H; rampage-end confusion in simulate_turn
        return not isinstance(ctx.hit_crit_or_miss(locked_move.accuracy), Miss)

    elif effect == 159:  # Uproar: C/D/H each turn; lock does not end early on miss
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        if state.user_locked_turns == 0:  # type: ignore[attr-defined]
            state.user_locked_move_num = None  # type: ignore[attr-defined]
            state.user_locked_effect = None    # type: ignore[attr-defined]
        return not isinstance(token, Miss)

    elif effect == 117:  # Rollout/Ice Ball: C/D/H; miss ends lock early
        token = ctx.hit_crit_or_miss(locked_move.accuracy)
        if isinstance(token, Miss):
            state.user_locked_turns = 0        # type: ignore[attr-defined]
            state.user_locked_move_num = None  # type: ignore[attr-defined]
            state.user_locked_effect = None    # type: ignore[attr-defined]
            return False
        if state.user_locked_turns == 0:       # type: ignore[attr-defined]
            state.user_locked_move_num = None  # type: ignore[attr-defined]
            state.user_locked_effect = None    # type: ignore[attr-defined]
        return True

    else:
        ctx.raw_emit(Unsupported())
        ctx.raw_emit(PathEnd())
        ctx.battle_state['unsupported'] = True
        return False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EffectHandler = Callable[['BattleContext', Move], bool]

EFFECT_HANDLERS: dict[int, EffectHandler] = {
    # --- Standard C/D/H damage ---
    0:   _eff_damage,        # Pound, Tackle, etc.
    3:   _eff_damage,        # Absorb (drain)
    7:   _eff_selfdestruct,  # Selfdestruct/Explosion — C/D/H + path ends
    8:   _eff_dream_eater,
    17:  _eff_damage,        # Swift (accuracy=0 → always hits via hit_crit_or_miss)
    34:  _eff_damage,        # Pay Day
    43:  _eff_high_crit,     # Karate Chop, Slash, etc.
    44:  _eff_double_hit,    # Double Kick, Bonemerang
    45:  _eff_damage,        # Jump Kick (user takes recoil on miss, no extra rolls)
    48:  _eff_damage,        # Take Down / Submission (recoil)
    78:  _eff_damage,        # Vital Throw (always hits)
    80:  _eff_hyper_beam,    # Hyper Beam / Blast Burn etc.
    81:  _eff_damage,        # Rage
    87:  _eff_seismic_toss,  # Seismic Toss / Night Shade (hit check only)
    88:  _eff_psywave,       # Psywave (damage roll + hit check)
    99:  _eff_damage,        # Flail / Reversal
    101: _eff_damage,        # False Swipe
    103: _eff_damage,        # Quick Attack, Mach Punch, etc.
    104: _eff_triple_kick,
    119: _eff_damage,        # Fury Cutter
    121: _eff_damage,        # Return
    123: _eff_damage,        # Frustration
    128: _eff_damage,        # Pursuit
    129: _eff_damage,        # Rapid Spin
    135: _eff_hidden_power,  # Hidden Power (Unsupported if frozen target — Fire HP thaws)
    147: _eff_damage,        # Earthquake
    149: _eff_damage,        # Gust
    169: _eff_damage,        # Facade
    171: _eff_smelling_salt, # Smelling Salt (cures paralysis on hit)
    173: _eff_damage,        # Nature Power (Hydro Pump)
    182: _eff_damage,        # Superpower
    185: _eff_damage,        # Revenge / Avalanche
    186: _eff_damage,        # Brick Break
    188: _eff_damage,        # Knock Off
    190: _eff_damage,        # Eruption / Water Spout
    196: _eff_damage,        # Low Kick / Grass Knot
    198: _eff_damage,        # Double Edge / Brave Bird / Wood Hammer (recoil)
    203: _eff_damage,        # Weather Ball
    207: _eff_damage,        # Sky Uppercut
    217: _eff_wake_up_slap,  # Wake Up Slap (cures sleep on hit)
    218: _eff_damage,        # Hammer Arm
    219: _eff_damage,        # Gyro Ball
    221: _eff_damage,        # Brine
    224: _eff_damage,        # Pluck / Bug Bite
    229: _eff_damage,        # Close Combat
    230: _eff_damage,        # Payback
    231: _eff_damage,        # Assurance
    235: _eff_damage,        # Trump Card (always hits)
    237: _eff_damage,        # Wring Out / Crush Grip
    245: _eff_damage,        # Punishment
    257: _eff_damage,        # Surf
    268: _eff_damage,        # Judgment
    269: _eff_damage,        # Head Smash (recoil)

    # --- Damage + observable secondary proc ---
    2:   _eff_poison_secondary,        # Poison Sting, Sludge, etc.
    4:   _eff_burn_secondary,          # Fire Punch / Flamethrower (burn)
    5:   _eff_freeze_secondary,        # Ice Punch / Ice Beam (freeze)
    6:   _eff_paralyze_secondary,      # Thunder Punch / Thunderbolt (paralyze)
    36:  _eff_tri_attack,
    68:  _eff_target_atk_minus1,       # Aurora Beam (opp atk -1, cap-checked)
    69:  _eff_target_def_minus1,       # Iron Tail / Crunch (opp def -1, cap-checked)
    70:  _eff_target_spd_minus1,       # Bubble Beam / Icy Wind (opp spd -1, cap-checked)
    71:  _eff_target_spatk_minus1,     # Mist Ball (opp spatk -1, cap-checked)
    72:  _eff_target_spdef_minus1,     # Acid / Psychic (opp spdef -1, cap-checked)
    73:  _eff_accuracy_drop_secondary, # Mud Slap / Muddy Water (opp acc -1, tracked)
    77:  _eff_twineedle,
    125: _eff_burn_secondary,          # Flame Wheel / Sacred Fire (burn, same as 4)
    126: _eff_magnitude,
    138: _eff_user_def_plus1,          # Steel Wing (user def +1, cap-checked)
    139: _eff_user_atk_plus1,          # Metal Claw / Meteor Mash (user atk +1, cap-checked)
    140: _eff_user_all_stats_plus1,    # Ancient Power / Silver Wind / Ominous Wind
    152: _eff_thunder,
    154: _eff_beat_up,
    197: _eff_target_atk_minus1,       # Secret Power (opp atk -1 in sea-water env)
    200: _eff_burn_highcrit,           # Blaze Kick (high crit + burn)
    202: _eff_poison_secondary,        # Poison Fang (bad poison)
    204: _eff_user_spatk_minus2,       # Overheat / Psycho Boost (user spatk -2, 100%)
    209: _eff_poison_highcrit,         # Poison Tail / Cross Poison (high crit + poison)
    253: _eff_burn_secondary,          # Flare Blitz (burn)
    260: _eff_blizzard,
    262: _eff_paralyze_secondary,      # Volt Tackle (paralyze)
    271: _eff_target_spdef_minus2,     # Seed Flare (opp spdef -2, cap-checked)
    276: _eff_user_spatk_plus1,        # Charge Beam (user spatk +1, cap-checked)

    # --- Damage + flinch (unobservable when going second) ---
    31:  _eff_damage_flinch,  # Rolling Kick, Headbutt, Bite, etc.
    146: _eff_damage_flinch,  # Twister
    150: _eff_damage_flinch,  # Stomp

    # --- Damage + status + flinch (Fire/Ice/Thunder Fang) ---
    273: _eff_fire_fang,     # Fire Fang (burn + flinch)
    274: _eff_ice_fang,      # Ice Fang (freeze + flinch)
    275: _eff_thunder_fang,  # Thunder Fang (paralyze + flinch)

    # --- Multi-hit ---
    29:  _eff_multi_hit,

    # --- Binding ---
    42:  _eff_bind,   # Bind / Wrap / Fire Spin / Clamp / Sand Tomb / Magma Storm
    261: _eff_bind,   # Whirlpool

    # --- Sleep ---
    1:   _eff_sleep,

    # --- Confusion ---
    49:  _eff_confuse_hit,  # Confuse Ray / Supersonic / Sweet Kiss
    76:  _eff_damage_confuse,  # Psybeam / Confusion / Water Pulse, etc.

    # --- Paralyze ---
    67:  _eff_paralyze,

    # --- Poison ---
    33:  _eff_poison_hit,  # Toxic
    66:  _eff_poison_hit,  # Poison Powder / Poison Gas

    # --- Burn ---
    167: _eff_will_o_wisp,

    # --- Disable / Taunt / Gravity ---
    86:  _eff_disable,
    175: _eff_taunt,
    215: _eff_gravity,

    # --- Swagger / Flatter / Teeter Dance ---
    118: _eff_swagger,
    166: _eff_flatter,
    199: _eff_teeter_dance,

    # --- Attract ---
    120: _eff_attract,

    # --- Encore ---
    90:  _eff_encore,

    # --- Disable-related: Nightmare / Torment / Leech Seed ---
    84:  _eff_leech_seed,
    107: _eff_nightmare,
    165: _eff_torment,

    # --- OHKO ---
    38:  _eff_ohko,

    # --- Hit-check-only status moves ---
    18:  _eff_growl,       # Growl (opp atk -1, tracked)
    19:  _eff_leer,        # Tail Whip / Leer (opp def -1, tracked)
    20:  _eff_string_shot, # String Shot (opp spd -1, tracked)
    23:  _eff_lower_target_accuracy,  # Sand Attack / Flash (opp acc -1, tracked)
    24:  _eff_lower_target_evasion,   # Sweet Scent (opp eva -1, tracked)
    40:  _eff_hit_only,  # Super Fang (half HP)
    41:  _eff_hit_only,  # Dragon Rage (40 dmg)
    58:  _eff_charm,      # Charm / Feather Dance (opp atk -2, tracked)
    59:  _eff_screech,    # Screech (opp def -2, tracked)
    60:  _eff_scary_face, # Cotton Spore / Scary Face (opp spd -2, tracked)
    62:  _eff_fake_tears, # Fake Tears / Metal Sound (opp spdef -2, tracked)
    92:  _eff_hit_then_fail,  # Snore (hit check but always fails — user can't be asleep)
    100: _eff_hit_only,  # Spite
    106: _eff_spider_web,
    130: _eff_hit_only,  # Sonic Boom (20 dmg)
    168: _eff_memento,
    205: _eff_tickle,    # Tickle (opp atk -1, opp def -1, tracked)
    222: _eff_hit_then_fail,  # Natural Gift (fails with lagging tail — hit check still done)
    227: _eff_hit_only,  # Metal Burst (hit check; fails if no dmg taken — simplified)
    232: _eff_embargo,
    234: _eff_hit_then_fail,  # Psycho Shift (no status to transfer)
    236: _eff_heal_block,
    239: _eff_gastro_acid,
    246: _eff_hit_then_fail,  # Last Resort (fails from Metronome)
    247: _eff_worry_seed,
    248: _eff_hit_then_fail,  # Sucker Punch (Magikarp not selecting damage move)
    265: _eff_captivate,

    # --- No-roll success (stat tracking) ---
    10:  _eff_meditate,      # Meditate / Sharpen / Howl (user atk +1)
    11:  _eff_harden,        # Harden / Withdraw (user def +1)
    13:  _eff_growth,        # Growth (user spatk +1)
    16:  _eff_double_team,   # Double Team (user eva +1)
    25:  _eff_haze,          # Haze (resets all stat stages)
    50:  _eff_swords_dance,  # Swords Dance (user atk +2)
    51:  _eff_barrier,       # Barrier / Acid Armor / Iron Defense (user def +2)
    52:  _eff_agility,       # Agility / Rock Polish (user spd +2)
    53:  _eff_nasty_plot,    # Tail Glow / Nasty Plot (user spatk +2)
    54:  _eff_amnesia,       # Amnesia (user spdef +2)
    91:  _eff_pain_split,
    94:  _eff_lock_on,       # Mind Reader / Lock On
    102: _eff_no_rolls_ok,   # Heal Bell / Aromatherapy
    108: _eff_minimize,      # Minimize (user eva +1)
    109: _eff_curse_stat,    # Curse non-ghost (user atk+1, def+1, spd-1)
    113: _eff_no_rolls_ok,   # Foresight / Odor Sleuth
    143: _eff_psych_up,      # Psych Up (copy target stat stages)
    156: _eff_defense_curl,  # Defense Curl (user def +1)
    174: _eff_charge,        # Charge (user spdef +1)
    178: _eff_no_rolls_ok,   # Role Play
    179: _eff_no_rolls_ok,   # Wish
    191: _eff_no_rolls_ok,   # Skill Swap
    194: _eff_no_rolls_ok,   # Grudge
    206: _eff_cosmic_power,  # Cosmic Power / Defend Order (user def+1, spdef+1)
    208: _eff_bulk_up,       # Bulk Up (user atk+1, def+1)
    211: _eff_calm_mind,     # Calm Mind (user spatk+1, spdef+1)
    212: _eff_dragon_dance,  # Dragon Dance (user atk+1, spd+1)
    216: _eff_no_rolls_ok,   # Miracle Eye
    238: _eff_power_trick,   # Power Trick (swap user atk/def)
    240: _eff_lucky_chant,
    243: _eff_power_swap,    # Power Swap (swap user+target atk/spatk)
    244: _eff_guard_swap,    # Guard Swap (swap user+target def/spdef)
    250: _eff_heart_swap,    # Heart Swap (swap all stat stages; end path if Magikarp gains evasion)

    # --- No-roll, may fail ---
    32:  _eff_recovery,      # Recover / Softboiled etc.
    35:  _eff_light_screen,
    37:  _eff_rest,
    46:  _eff_mist,
    47:  _eff_focus_energy,
    65:  _eff_reflect,
    79:  _eff_substitute,
    85:  _eff_splash,
    112: _eff_spikes,
    114: _eff_perish_song,
    115: _eff_sandstorm,
    124: _eff_safeguard,
    132: _eff_recovery,      # Morning Sun / Synthesis / Moonlight
    136: _eff_rain_dance,
    137: _eff_sunny_day,
    142: _eff_belly_drum,
    160: _eff_stockpile,
    162: _eff_swallow,
    164: _eff_hail,
    181: _eff_ingrain,
    183: _eff_no_rolls_fail, # Magic Coat (user goes second; always fails)
    184: _eff_no_rolls_fail, # Recycle (holding lagging tail, not lost)
    187: _eff_yawn,
    192: _eff_no_rolls_fail, # Imprison (no shared moves P0)
    193: _eff_no_rolls_fail, # Refresh (no status from Magikarp)
    201: _eff_mud_sport,
    210: _eff_water_sport,
    213: _eff_camouflage,
    214: _eff_recovery,      # Roost
    225: _eff_tailwind,
    249: _eff_toxic_spikes,
    251: _eff_aqua_ring,
    252: _eff_magnet_rise,
    258: _eff_defog,
    259: _eff_trick_room,
    266: _eff_stealth_rock,

    # --- Acupressure: observable stat selection ---
    226: _eff_acupressure,

    # --- Path-ending ---
    28:  _eff_whirlwind,    # Whirlwind / Roar
    127: _eff_baton_pass,
    153: _eff_teleport,
    220: _eff_healing_wish,
    228: _eff_u_turn,
    233: _eff_fling,
    270: _eff_lunar_dance,

    # --- Context-dependent ---
    122: _eff_present,
    158: _eff_fake_out,
    161: _eff_spit_up,

    # --- Conversion ---
    30:  _eff_conversion,

    # --- Multi-turn / locked moves ---
    27:  _eff_thrash,       # Thrash / Petal Dance / Outrage (Group D)
    39:  _eff_charge_fire,  # Razor Wind (Group A)
    75:  _eff_sky_attack,   # Sky Attack (Group B)
    117: _eff_rollout,      # Rollout / Ice Ball (Group E)
    145: _eff_skull_bash,   # Skull Bash (Group B)
    148: _eff_future_sight, # Future Sight / Doom Desire (Group F)
    151: _eff_solar_beam,   # Solar Beam (Group C)
    155: _eff_charge_fire,  # Fly (Group A)
    159: _eff_uproar,       # Uproar (Group D)
    255: _eff_charge_fire,  # Dive (Group A)
    256: _eff_charge_fire,  # Dig (Group A)
    263: _eff_bounce,       # Bounce (Group B)
    272: _eff_charge_fire,  # Shadow Force (Group A)

    # --- Bide and Conversion 2 ---
    26:  _eff_bide,
    93:  _eff_conversion2,

    # --- Unsupported (SUPPORT_NOT_PLANNED) ---
    57:  _eff_unsupported,  # Transform — Chansey loses Metronome; no future path possible
    189: _eff_unsupported,  # Endeavor — always fails in P0 (Magikarp HP << Chansey HP); hit check always Miss, no seed-differentiating info
}


def simulate_move_execution(ctx: 'BattleContext', move: Move) -> bool:
    """Dispatch to the appropriate effect handler for the given move."""
    handler = EFFECT_HANDLERS.get(move.effect, _eff_unsupported)
    return handler(ctx, move)


# ---------------------------------------------------------------------------
# Metronome roll simulation
# ---------------------------------------------------------------------------

_METRONOME_POOL = 0x1D3  # 467 — total moves in the roll range
_METRONOME_MOVE_NUM = 118  # Metronome itself is always excluded


def simulate_metronome_roll(
    ctx: 'BattleContext',
    moves_by_number: dict[int, Move],
    known_moves: frozenset[int],
) -> Move:
    """Roll/ask for the Metronome move selection. Emits MetronomeMove token."""
    from .path import MetronomeMove, MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    gravity = state.gravity_turns > 0
    excluded = known_moves | {_METRONOME_MOVE_NUM}

    def rng_to_token(c: 'BattleContext') -> MetronomeMove:
        while True:
            roll = c.advance_observable()
            move_num = roll % _METRONOME_POOL + 1
            move = moves_by_number.get(move_num)
            if move is None:
                continue
            if not move.metronome_usable:
                continue
            if move_num in excluded:
                continue
            if gravity and move.is_gravity_blocked():
                continue
            return MetronomeMove(move_num)

    def input_to_token(s: str) -> MetronomeMove:
        s = s.strip()
        if s.upper().startswith('M') and s[1:].isdigit():
            num = int(s[1:])
            if num not in moves_by_number:
                raise ValueError(f"Unknown move number: {num}")
            return MetronomeMove(num)
        key = s.lower().replace('-', ' ').replace('_', ' ')
        for mv in moves_by_number.values():
            if mv.name.lower() == key:
                return MetronomeMove(mv.number)
        raise ValueError(f"Unknown move: {s!r}")

    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Metronome selected? (move name or M###):",
        input_to_token=input_to_token,
    )
    assert isinstance(token, MetronomeMove)
    return moves_by_number[token.move_num]
