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
        return Hit() if roll % 100 < move.accuracy else Miss()
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
# Group 1: Standard damage — crit (observable), damage (unobservable), hit
# ---------------------------------------------------------------------------

def _eff_damage(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    return not isinstance(token, Miss)


def _eff_high_crit(ctx: 'BattleContext', move: Move) -> bool:
    """Increased crit stage; same RNG roll count as standard."""
    token = ctx.hit_crit_or_miss(move.accuracy)
    return not isinstance(token, Miss)


# ---------------------------------------------------------------------------
# Group 2: Damage + one observable secondary effect proc
# ---------------------------------------------------------------------------

def _eff_damage_secondary(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance)
    return True


def _eff_high_crit_secondary(ctx: 'BattleContext', move: Move) -> bool:
    """High-crit damage + observable secondary effect proc."""
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance)
    return True


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

def _eff_damage_status_flinch(ctx: 'BattleContext', move: Move) -> bool:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance)  # burn/freeze/paralyze (observable)
    ctx.advance_unobservable(1)          # flinch roll (not observable, we go second)
    return True


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
        _hit_check(ctx, move)  # hit check still performed even on failure
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
    def rng_to_token(c: 'BattleContext') -> PathToken:
        roll = c.advance_observable()
        # Threshold = (30 + user_level - target_level) / 100; approximate with roll % 100
        return Hit() if roll % 100 < 55 else Miss()  # approximate for Chansey vs Magikarp

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
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    count = ctx.multi_hit()
    # Each additional hit: crit + damage (no hit check)
    for _ in range(count - 1):
        ctx.advance_unobservable(2)
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
    ctx.effect_proc(move.effect_chance)  # first poison roll
    ctx.advance_unobservable(2)          # 2 contact rolls
    ctx.advance_unobservable(2)          # crit + damage for second hit
    ctx.effect_proc(move.effect_chance)  # second poison roll
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
    ctx.advance_unobservable(1)  # roll for which status type (burn/freeze/paralysis)
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return False
    ctx.effect_proc(move.effect_chance)
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
    ctx.effect_proc(move.effect_chance)
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
    ctx.effect_proc(move.effect_chance)
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
    _hit_check(ctx, move)  # hit check performed, then fails
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
# Acupressure (Effect 226) — single roll selects stat
# ---------------------------------------------------------------------------

def _eff_acupressure(ctx: 'BattleContext', move: Move) -> bool:
    ctx.advance_unobservable(1)  # stat-selection roll (not directly observable)
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
    ctx.advance_unobservable(1)  # crit roll (no damage roll for this move)
    if _hit_check(ctx, move):
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
    return True


def _eff_focus_energy(ctx: 'BattleContext', move: Move) -> bool:
    from .path import MetronomeBattleState
    state: MetronomeBattleState = ctx.battle_state['state']
    if state.user_focus_energy:
        return False
    state.user_focus_energy = True
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
    # Magikarp gains Insomnia; if drowsy, wake-up is cancelled
    state.mk_drowsy_turns = 0
    if state.mk_status.status == NonVolatileStatus.SLEEP:
        state.mk_status.status = NonVolatileStatus.NONE
        state.mk_status.sleep_turns = 0
    return True


# Moves with only a hit check and no observable secondary (stat changes, etc.)
def _eff_hit_only(ctx: 'BattleContext', move: Move) -> bool:
    return _hit_check(ctx, move)


# No rolls, always succeeds
def _eff_no_rolls_ok(ctx: 'BattleContext', move: Move) -> bool:
    return True


# No rolls, always fails
def _eff_no_rolls_fail(ctx: 'BattleContext', move: Move) -> bool:
    return False


# ---------------------------------------------------------------------------
# Unsupported (complex consecutive or two-turn moves)
# ---------------------------------------------------------------------------

def _eff_unsupported(ctx: 'BattleContext', move: Move) -> bool:
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
    135: _eff_damage,        # Hidden Power
    147: _eff_damage,        # Earthquake
    149: _eff_damage,        # Gust
    169: _eff_damage,        # Facade
    171: _eff_damage,        # Smelling Salt
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
    217: _eff_damage,        # Wake Up Slap
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
    2:   _eff_damage_secondary,  # Poison Sting, Sludge, etc.
    4:   _eff_damage_secondary,  # Fire Punch / Flamethrower (burn)
    5:   _eff_damage_secondary,  # Ice Punch / Ice Beam (freeze)
    6:   _eff_damage_secondary,  # Thunder Punch / Thunderbolt (paralyze)
    36:  _eff_tri_attack,
    68:  _eff_damage_secondary,  # Aurora Beam (opp atk -1)
    69:  _eff_damage_secondary,  # Iron Tail / Crunch (opp def -1)
    70:  _eff_damage_secondary,  # Bubble Beam / Icy Wind (opp spd -1)
    71:  _eff_damage_secondary,  # Mist Ball (opp spatk -1)
    72:  _eff_damage_secondary,  # Acid / Psychic (opp spdef -1)
    73:  _eff_damage_secondary,  # Mud Slap / Muddy Water (opp acc -1)
    77:  _eff_twineedle,
    125: _eff_damage_secondary,  # Flame Wheel / Sacred Fire (burn, same as 4)
    126: _eff_magnitude,
    138: _eff_damage_secondary,  # Steel Wing (user def +1)
    139: _eff_damage_secondary,  # Metal Claw / Meteor Mash (user atk +1)
    140: _eff_damage_secondary,  # Ancient Power / Silver Wind / Ominous Wind
    152: _eff_thunder,
    154: _eff_beat_up,
    197: _eff_damage_secondary,  # Secret Power (opp atk -1 in sea-water env)
    200: _eff_high_crit_secondary,  # Blaze Kick (high crit + burn)
    202: _eff_damage_secondary,  # Poison Fang (bad poison)
    204: _eff_damage_secondary,  # Overheat / Psycho Boost (spatk -2, 100%)
    209: _eff_high_crit_secondary,  # Poison Tail / Cross Poison (high crit + poison)
    253: _eff_damage_secondary,  # Flare Blitz (burn)
    260: _eff_blizzard,
    262: _eff_damage_secondary,  # Volt Tackle (paralyze)
    271: _eff_damage_secondary,  # Seed Flare (opp spdef -2)
    276: _eff_damage_secondary,  # Charge Beam (user spatk +1)

    # --- Damage + flinch (unobservable when going second) ---
    31:  _eff_damage_flinch,  # Rolling Kick, Headbutt, Bite, etc.
    146: _eff_damage_flinch,  # Twister
    150: _eff_damage_flinch,  # Stomp

    # --- Damage + status + flinch (Fire/Ice/Thunder Fang) ---
    273: _eff_damage_status_flinch,  # Fire Fang
    274: _eff_damage_status_flinch,  # Ice Fang
    275: _eff_damage_status_flinch,  # Thunder Fang

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
    18:  _eff_hit_only,  # Growl (opp atk -1)
    19:  _eff_hit_only,  # Tail Whip / Leer (opp def -1)
    20:  _eff_hit_only,  # String Shot (opp spd -1)
    23:  _eff_hit_only,  # Sand Attack / Flash (opp acc -1)
    24:  _eff_hit_only,  # Sweet Scent (opp eva -1)
    40:  _eff_hit_only,  # Super Fang (half HP)
    41:  _eff_hit_only,  # Dragon Rage (40 dmg)
    58:  _eff_hit_only,  # Charm / Feather Dance (opp atk -2)
    59:  _eff_hit_only,  # Screech (opp def -2)
    60:  _eff_hit_only,  # Cotton Spore / Scary Face (opp spd -2)
    62:  _eff_hit_only,  # Fake Tears / Metal Sound (opp spdef -2)
    92:  _eff_hit_only,  # Snore (hit check but always fails — user can't be asleep)
    100: _eff_hit_only,  # Spite
    106: _eff_spider_web,
    130: _eff_hit_only,  # Sonic Boom (20 dmg)
    168: _eff_memento,
    205: _eff_hit_only,  # Tickle (opp atk -1, opp def -1)
    222: _eff_hit_only,  # Natural Gift (fails with lagging tail — hit check still done)
    227: _eff_hit_only,  # Metal Burst (hit check; fails if no dmg taken — simplified)
    232: _eff_embargo,
    234: _eff_hit_only,  # Psycho Shift (no status to transfer)
    236: _eff_heal_block,
    239: _eff_gastro_acid,
    246: _eff_hit_only,  # Last Resort (fails from Metronome)
    247: _eff_worry_seed,
    248: _eff_hit_only,  # Sucker Punch (Magikarp not selecting damage move)
    265: _eff_captivate,

    # --- No-roll success ---
    10:  _eff_no_rolls_ok,   # Meditate / Sharpen / Howl (atk +1)
    11:  _eff_no_rolls_ok,   # Harden / Withdraw (def +1)
    13:  _eff_no_rolls_ok,   # Growth (spatk +1)
    16:  _eff_no_rolls_ok,   # Double Team (eva +1)
    25:  _eff_no_rolls_ok,   # Haze
    50:  _eff_no_rolls_ok,   # Swords Dance (atk +2)
    51:  _eff_no_rolls_ok,   # Barrier / Acid Armor / Iron Defense (def +2)
    52:  _eff_no_rolls_ok,   # Agility / Rock Polish (spd +2)
    53:  _eff_no_rolls_ok,   # Tail Glow / Nasty Plot (spatk +2)
    54:  _eff_no_rolls_ok,   # Amnesia (spdef +2)
    91:  _eff_pain_split,
    94:  _eff_no_rolls_ok,   # Mind Reader / Lock On
    102: _eff_no_rolls_ok,   # Heal Bell / Aromatherapy
    108: _eff_no_rolls_ok,   # Minimize (eva +1)
    109: _eff_no_rolls_ok,   # Curse (non-ghost: atk/def +1, spd -1)
    113: _eff_no_rolls_ok,   # Foresight / Odor Sleuth
    143: _eff_no_rolls_ok,   # Psych Up
    156: _eff_no_rolls_ok,   # Defense Curl (def +1)
    174: _eff_no_rolls_ok,   # Charge (spdef +1)
    178: _eff_no_rolls_ok,   # Role Play
    179: _eff_no_rolls_ok,   # Wish
    191: _eff_no_rolls_ok,   # Skill Swap
    194: _eff_no_rolls_ok,   # Grudge
    206: _eff_no_rolls_ok,   # Cosmic Power / Defend Order (def +1, spdef +1)
    208: _eff_no_rolls_ok,   # Bulk Up (atk +1, def +1)
    211: _eff_no_rolls_ok,   # Calm Mind (spatk +1, spdef +1)
    212: _eff_no_rolls_ok,   # Dragon Dance (atk +1, spd +1)
    216: _eff_no_rolls_ok,   # Miracle Eye
    238: _eff_no_rolls_ok,   # Power Trick
    240: _eff_lucky_chant,
    243: _eff_no_rolls_ok,   # Power Swap
    244: _eff_no_rolls_ok,   # Guard Swap
    250: _eff_no_rolls_ok,   # Heart Swap

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
    213: _eff_no_rolls_ok,   # Camouflage (always Water type in this env; simplified)
    214: _eff_recovery,      # Roost
    225: _eff_tailwind,
    249: _eff_toxic_spikes,
    251: _eff_aqua_ring,
    252: _eff_magnet_rise,
    258: _eff_defog,
    259: _eff_trick_room,
    266: _eff_stealth_rock,

    # --- Field effect moves ---
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

    # --- Unsupported (consecutive/two-turn) ---
    26:  _eff_unsupported,  # Bide
    27:  _eff_unsupported,  # Thrash / Petal Dance / Outrage
    30:  _eff_unsupported,  # Conversion
    39:  _eff_unsupported,  # Razor Wind
    57:  _eff_unsupported,  # Transform
    75:  _eff_unsupported,  # Sky Attack
    93:  _eff_unsupported,  # Conversion 2
    117: _eff_unsupported,  # Rollout / Ice Ball
    145: _eff_unsupported,  # Skull Bash
    148: _eff_unsupported,  # Future Sight / Doom Desire
    151: _eff_unsupported,  # Solar Beam
    155: _eff_unsupported,  # Fly
    159: _eff_unsupported,  # Uproar
    189: _eff_unsupported,  # Endeavor (requires HP tracking)
    255: _eff_unsupported,  # Dive
    256: _eff_unsupported,  # Dig
    263: _eff_unsupported,  # Bounce
    272: _eff_unsupported,  # Shadow Force
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
