# Complex Metronome Compass — Implementation Plan

## Context

The current `compass_metronome` (simple) takes one Metronome move observation, filters candidates, and exits. The **complex** version tracks RNG state across multiple battle turns — each turn the user observes what move Metronome selected, whether it hit/crit, what Magikarp did, etc., and the compass filters candidates by simulating the full RNG sequence. This is analogous to how `compass_safari` tracks RNG through multiple safari turns.

The key challenge is accurately modeling every RNG call in a battle turn so the simulated state stays in sync with the game's actual RNG state across turns.

## Verified turn RNG sequence

**Battle start**: 4 bellShimmer + 2 ability + 1 flee = **7 advances** (same as safari `start_encounter`)

**Each turn** (supersedes earlier GDB notes, which were fast-and-loose):
```
1 roll   Magikarp move selection       # only if Magikarp has useable moves; skipped for Struggle
4 rolls  BeforeTurn                    # quick claw checks
N rolls  BtlCmd_Metronome()            # 1+ rolls (reroll if gravity-blocked or known move)
N rolls  Metronome move execution      # variable; depends on move profile + observations
2 rolls  IF Metronome move successful  # skipped on miss / move failure
2 rolls  Magikarp turn start           # always (even if Magikarp is prevented)
N rolls  Magikarp's move               # Splash: 0; Tackle (not prevented): accuracy check,
                                       #   then IF hit: crit + damage (CheckMoveHit/TryCrit still apply)
                                       # Struggle (not prevented): crit + damage (always hits, no accuracy check)
2 rolls  IF Magikarp move successful   # skipped if Magikarp was prevented or move failed
4 rolls  End of turn
```

Note: "successful" means the move animation played — misses, status moves that fail, being
asleep/frozen/disabled/taunted/gravitated/paralyzed/infatuated do NOT count as successful.

## Architecture

### New package: `claytonlib/metronome_compass_full/`

The implementation is large enough to warrant a package rather than a single file. Submodules:

```
claytonlib/metronome_compass_full/
    __init__.py     — exports metronome_compass_full() function
    path.py         — PathToken hierarchy, Path type, rendering
    context.py      — BattleContext, RngContext, InteractiveContext, emit helpers
    effects.py      — effect scripts keyed by effect number
```

The function is named `metronome_compass_full`. The existing simple version should be renamed to `metronome_compass_simple`.

### Path representation

A **path** pre-computes all observable RNG events for a candidate seed into a structured sequence, analogous to machete paths but representing battle observations rather than capture actions.

#### PathToken

Tokens are frozen dataclasses sharing a base class. Each token knows its string representation. New tokens can be added without touching path-building or filtering logic.

```python
@dataclass(frozen=True)
class PathToken:
    def render(self) -> str: ...

# Parameterized tokens
@dataclass(frozen=True)
class MetronomeMove(PathToken):
    move_num: int
    def render(self): return f"M{self.move_num:03d}"

@dataclass(frozen=True)
class MagikarpMove(PathToken):
    move: str   # "sp" / "tk"
    def render(self): return f"K{self.move}"

@dataclass(frozen=True)
class MultiHit(PathToken):
    count: int
    def render(self): return f"x{self.count}"

# Player-move outcome tokens
Hit        → "h"
Miss       → "-"
Crit       → "!"    # implies hit; never combined with Hit
EffectProc → "~"

# Magikarp action tokens (appear where MagikarpMove would, when a selected move
# is not possible or is replaced by a forced action)
PAR        → "PAR"   # fully paralyzed, couldn't move
FRZ        → "FRZ"   # frozen, couldn't move
SLP        → "SLP"   # asleep, couldn't move
FLN        → "FLN"   # flinched from our move's secondary effect
LV         → "LV"    # immobilized by love (Attract)
CFZ        → "CFZ"   # hurt itself in confusion (action replaced by self-hit)
SCFZ       → "SCFZ"  # snapped out of confusion; must be followed by action token
Struggle   → "STR"   # forced action when no usable moves remain (not a selected move)

# Path-end token
PathEnd    → "_"     # battle ended (Magikarp fainted, PP exhausted, etc.)
                     # always last; dropped before prefix-matching against precomputed paths
```

**Only emit tokens for events that represent an actual RNG roll.** A move with no accuracy check doesn't produce a Hit/Miss token. A move with no effect chance doesn't produce an EffectProc token. This keeps paths minimal.

**Crit vs hit**: `!` (crit) implies the move hit. `h` is hit without crit. `-` is miss; crit is not observable on a miss and is never emitted.

**Confusion has three observable outcomes**: `CFZ` (hurt itself, no action follows), `SCFZ` + action token (snapped out then acted), or just an action token (stayed confused but acted — implied by absence of `SCFZ`, tracked via `battle_state`).

**Struggle vs MagikarpMove**: `Struggle` is a forced action, not a move Magikarp selected, so it is a standalone token rather than a `MagikarpMove` variant.

**PathEnd vs old Fainted (`F`)**: `_` marks the end of the *observed* path for any reason. Precomputed paths (up to 10 turns, capped by Metronome PP) contain no `PathEnd`. When comparing, strip `_` and prefix-match the last partial turn against the precomputed path. Metronome PP is tracked as a field on `BattleContext`; when it reaches 0 the precomputed path ends naturally.

#### Path structure and rendering

A `Path` is a `tuple` of turns, each turn a `tuple[PathToken, ...]`. Tokens within a turn are concatenated; turns are space-separated:

```python
Path = tuple[tuple[PathToken, ...], ...]

def render_path(path: Path) -> str:
    return " ".join("".join(t.render() for t in turn) for turn in path)
```

Example: `"M053h~ Ksp M007x3 F"`

The annotation column alongside the path shows move names for all `MetronomeMove` tokens, e.g. `"Flamethrower, Splash, Low Kick"`.

Whether `Path` is a type alias or a class with methods (`render`, `matches_prefix`, `annotate`) is TBD — a class is cleaner if paths accumulate behavior.

### BattleContext (`context.py`)

`BattleContext` is the abstract base class shared by both modes. It is **mutable for the whole battle** — a single instance lives for the entire session, accumulating tokens turn by turn. Unlike machete, the user makes no branching decisions, so there's no need to fork or rewind context mid-battle.

```python
class BattleContext(ABC):
    battle_state: dict        # free-form game state: weather, gravity_turns, stat stages, etc.
    _path: list[list[PathToken]]   # accumulated turns
    _current_turn: list[PathToken] # tokens for the turn in progress

    def advance_unobservable(self, n: int = 1) -> None:
        """Consume n non-observable RNG rolls. RngContext advances RNG; InteractiveContext no-ops."""
        ...

    def advance_observable(self) -> int:
        """Consume one observable RNG roll and return the shifted (top 16 bits) value.
        RngContext advances RNG and returns (val >> 16).
        InteractiveContext raises — effect scripts must not call this directly."""
        ...

    def emit(self,
             rng_to_token: Callable[['BattleContext'], PathToken],
             question: str,
             input_to_token: Callable[[str], PathToken]) -> PathToken:
        """Resolve one observable event into a token and append it to the current turn.
        rng_to_token receives the context (not a raw number) so it can call
        advance_observable()/advance_unobservable() as needed and access battle_state.
        RngContext calls rng_to_token(self); InteractiveContext asks the question."""
        ...

    def raw_emit(self, token: PathToken) -> PathToken:
        """Append a token directly, for cases where one question per token isn't appropriate."""
        ...

    def end_turn(self) -> tuple[PathToken, ...]:
        """Snapshot the current turn's tokens and start a new turn."""
        ...

    # --- Emit helpers (common token patterns defined once on the base class) ---
    def hit_crit_or_miss(self, move: 'Move') -> PathToken:
        """Covers the 3-roll sequence (crit, damage, hit check) with a single h/!/- question.
        rng_to_token calls advance_observable() x2 + advance_unobservable() x1 internally."""
        ...

    def effect_proc(self, chance: int) -> PathToken | None:
        """Roll/ask whether a secondary effect proc'd. Returns EffectProc or None."""
        ...

    def multi_hit(self) -> PathToken:
        """Roll/ask number of hits for a multi-hit move."""
        ...
```

**`RngContext`**: implements `advance_observable()` by advancing internal RNG and returning the value; `advance_unobservable()` advances without returning. `emit()` calls `rng_to_token(self)`. Exposes `.rng` for reading final state.

**`InteractiveContext`**: `advance_unobservable()` is a no-op; `advance_observable()` raises `RuntimeError` (effect scripts must use helpers, not raw advances). `emit()` prints `question`, reads input, calls `input_to_token`. Filtering against pre-computed paths happens outside the context, at turn boundaries after `end_turn()`.

### Effect-based move modeling

Instead of a hand-crafted `MoveProfile` dataclass, moves are modeled using the **effect numbers** from the decompiled source. Each move has an `effect` field (integer) that maps to a battle script, which determines its RNG call pattern.

```python
def move_effect(effect: int, effect_chance: int, **kwargs) -> str:
    """Human-readable description of a move's effect. Returns 'unsupported(N)' for unknown effects."""
    match effect:
        case 0:   return "standard"
        case 43:  return "high crit"
        case 29:  return "multi-hit"
        case 4:   return f"burn {effect_chance}%"
        case 5:   return f"freeze {effect_chance}%"
        case 6:   return f"paralyze {effect_chance}%"
        case _:   return f"unsupported({effect})"
```

For **simulation**, each effect number maps to a handler that knows how to advance RNG and validate observations. Unknown effect numbers → treat as unsupported (still usable for metronome roll filtering, halt further state tracking).

The combined move data lives in `notes/combined_moves.json` (generated by `notes/combine_moves.py`) and will inform which effect numbers need handlers. The `effect` and `effect_chance` fields in `combined_moves.json` come from the GDB dump; `metronome_usable` and `name` come from the existing `moves.json`.

### Magikarp level

Declared as a **session parameter** at the start of the compass session (not per-seed). One path is computed per seed, not two:

- Level < 15: Splash only (no move selection roll)
- Level 15–20 (Blackthorn cap): Splash + Tackle (one move selection roll per Magikarp turn)

Level 30+ (Flail) is not supported → use `BLACKTHORN_MAGIKARP` target which caps at level 20.

### Battle state

```python
@dataclass
class MetronomeBattleState:
    rng_state: int
    gravity_turns: int = 0            # 0 = inactive, >0 = turns remaining
    weather: str | None = None        # "sunny" / "rain" / "sand" / "hail" / None
    weather_until: int = 0            # turn number weather expires
    user_evasion_stage: int = 0       # -6 to +6
    target_evasion_stage: int = 0
    user_accuracy_stage: int = 0
    target_accuracy_stage: int = 0
    user_crit_stage: int = 0
    target_status: str | None = None  # "paralysis" / "sleep" / "freeze" / "burn" / "poison" / None
    target_infatuated: bool = False
    target_confused: bool = False
```

Magikarp's per-turn status is tracked separately in `MagikarpStatus` (see Turn simulation section).

### Turn simulation (`effects.py`)

Effect scripts are plain functions that take a `BattleContext` and call `ctx.emit()`, `ctx.advance()`, and helpers. They are mode-agnostic — the context implementation handles whether to roll RNG or ask the user.

```python
def effect_standard_damage(ctx: BattleContext, move: Move) -> None:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return
    ctx.advance()  # damage roll

def effect_burn_chance(ctx: BattleContext, move: Move) -> None:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return
    ctx.advance()  # damage roll
    ctx.effect_proc(move.effect_chance)

def effect_multi_hit(ctx: BattleContext, move: Move) -> None:
    token = ctx.hit_crit_or_miss(move.accuracy)
    if isinstance(token, Miss):
        return
    ctx.multi_hit()
```

Effect scripts are registered in a dict keyed by effect number:
```python
EFFECT_HANDLERS: dict[int, Callable[[BattleContext, Move], None]] = {
    0:  effect_standard_damage,
    4:  effect_burn_chance,
    29: effect_multi_hit,
    43: effect_high_crit,
    ...
}
```

Unknown effect numbers → call a fallback that emits no tokens and sets a flag in `battle_state` that further state tracking is halted (move name still used for seed filtering).

Pre-computing a path for a seed: create an `RngContext`, run through all turns with effect scripts, collect `ctx._path`.

Interactive session: create an `InteractiveContext`, run through turns in real time, compare each completed turn (via `end_turn()`) against pre-computed candidate paths to filter seeds.

### Move execution

**Key insight**: We don't need to compute exact damage values — we just need to advance RNG the right number of times and validate observable outcomes (hit/miss, crit/no-crit, effect proc/no-proc).

Observable outcomes determine which code paths the game took, which determines how many RNG calls happened:
- Miss (`-`): skip crit and damage rolls
- Hit without crit (`h`): advance for crit roll + damage roll
- Hit with crit (`!`): advance for crit roll (validated) + damage roll

### Full turn simulation skeleton

```python
def _simulate_turn(ctx: BattleContext, magikarp_status: MagikarpStatus,
                   known_moves: tuple, magikarp_level: int) -> MagikarpStatus:
    # 1. Magikarp move selection (only if useable moves exist; skipped if Struggle)
    # The roll happens here, but the observation (move name) is only known later.
    mk_move_roll = None
    if magikarp_has_useable_moves(magikarp_status, magikarp_level):
        mk_move_roll = ctx.advance_observable()

    # 2. [Player chooses move]

    # 3. BeforeTurn x4
    ctx.advance_unobservable(4)

    # 4. Metronome roll (1+ advances with reroll on gravity-blocked / known moves)
    move = ctx.emit_metronome_roll(known_moves, ctx.battle_state.get("gravity_turns", 0) > 0)

    # 5. Metronome move effect (variable; handled by EFFECT_HANDLERS[move.effect])
    handler = EFFECT_HANDLERS.get(move.effect, effect_unsupported)
    move_succeeded = handler(ctx, move)

    # 6. IF Metronome move successful: 2 more rolls
    if move_succeeded:
        ctx.advance_unobservable(2)

    # 7. Magikarp turn start: 2 rolls always
    ctx.advance_unobservable(2)

    # 8. Magikarp's action (status checks in order, then move or replacement)
    magikarp_status, magikarp_succeeded = _simulate_magikarp_turn(
        ctx, magikarp_status, magikarp_level, mk_move_roll
    )

    # 9. IF Magikarp move successful: 2 more rolls
    if magikarp_succeeded:
        ctx.advance_unobservable(2)

    # 10. End of turn: 4 rolls
    ctx.advance_unobservable(4)

    # 11. End of turn maintenance (ticks regardless of other prevention)
    if ctx.battle_state.get("gravity_turns", 0) > 0:
        ctx.battle_state["gravity_turns"] -= 1

    _tick_disable_taunt(magikarp_status)

    return magikarp_status
```

### Magikarp turn simulation

```python
def _simulate_magikarp_turn(ctx, status: MagikarpStatus, magikarp_level: int,
                             mk_move_roll: int | None) -> tuple[MagikarpStatus, bool]:
    """Simulate Magikarp's action including all status checks.
    Returns (updated_status, move_succeeded).
    Status effects checked in order per effect_status.md."""

    status = status.copy()

    # Sleep
    if status.status == NonVolatileStatus.SLEEP:
        if status.sleep_turns == 1:
            status.sleep_turns = 0
            status.status = NonVolatileStatus.NONE  # wakes up; fall through to move
        else:
            status.sleep_turns -= 1
            ctx.raw_emit(SLP)
            return status, False

    # Freeze
    if status.status == NonVolatileStatus.FROZEN:
        thaw = ctx.emit(
            rng_to_token=lambda c: FRZ if c.advance_observable() % 5 != 0 else SCFZ,
            question="Magikarp thawed? (y/n): ",
            input_to_token=lambda s: SCFZ if s.startswith('y') else FRZ,
        )
        if isinstance(thaw, FRZ):
            return status, False
        status.status = NonVolatileStatus.NONE  # thawed; fall through to move

    # Flinch (current-turn only)
    if status.flinched:
        status.flinched = False
        ctx.raw_emit(FLN)
        return status, False

    # Disable / Taunt / Gravity — prevent specific moves (emit P)
    prevented = _check_prevented(ctx, status, magikarp_level)
    if prevented:
        return status, False

    # Confusion
    if status.confusion_turns > 0:
        confused_roll = ctx.emit(
            rng_to_token=lambda c: CFZ if (c.advance_observable() & 1) == 0 else None,
            question="Magikarp snapped out / acted / hit itself? (snap/act/cfz): ",
            input_to_token=...,
        )
        status.confusion_turns -= 1
        if status.confusion_turns == 0:
            ctx.raw_emit(SCFZ)  # snapped out before acting
        if isinstance(confused_roll, CFZ):
            ctx.advance_unobservable()  # damage roll (no hit/crit check for confusion self-hit)
            return status, False  # hit itself; not "successful" in the game's terms

    # Paralysis
    if status.status == NonVolatileStatus.PARALYZED:
        para_roll = ctx.emit(
            rng_to_token=lambda c: PAR if c.advance_observable() % 4 == 0 else None,
            question="Fully paralyzed? (y/n): ",
            input_to_token=lambda s: PAR if s.startswith('y') else None,
        )
        if isinstance(para_roll, PAR):
            return status, False

    # Attract
    if status.infatuated:
        attract_roll = ctx.emit(
            rng_to_token=lambda c: LV if (c.advance_observable() & 1) == 0 else None,
            question="Immobilized by love? (y/n): ",
            input_to_token=lambda s: LV if s.startswith('y') else None,
        )
        if isinstance(attract_roll, LV):
            return status, False

    # Magikarp's move executes
    return _simulate_magikarp_move(ctx, status, magikarp_level, mk_move_roll)


def _tick_disable_taunt(status: MagikarpStatus) -> None:
    """Disable and taunt tick down every turn regardless of other prevention."""
    if status.disable_turns > 0:
        status.disable_turns -= 1
        if status.disable_turns == 0:
            status.disabled_move = None
            # path token DIS_END emitted by caller
    if status.taunt_turns > 0:
        status.taunt_turns -= 1
        # path token TNT_END emitted by caller when it reaches 0
```

### Magikarp move execution (Tackle / Splash / Struggle)

```python
def _simulate_magikarp_move(ctx, status: MagikarpStatus, magikarp_level: int,
                              mk_move_roll: int | None) -> tuple[MagikarpStatus, bool]:
    # Move selection roll was consumed at turn start (mk_move_roll).
    # If no usable moves remain, it's a forced Struggle (no roll).

    if not magikarp_has_useable_moves(status, magikarp_level):
        ctx.raw_emit(Struggle())
        ctx.emit_crit()             # struggle always hits; only crit is observable
        ctx.advance_unobservable()  # damage roll
        return status, True

    # Has useable moves: resolve the selected one
    def rng_to_token(ctx: BattleContext) -> PathToken:
        # Use roll from step 1 (RngContext) or advance if missing (fallback)
        r = mk_move_roll if mk_move_roll is not None else ctx.advance_observable()
        return MagikarpMove("sp" if r % 2 == 0 else "tk")

    token = ctx.emit(
        rng_to_token=rng_to_token,
        question="Magikarp used? (sp/tk):",
        input_to_token=lambda s: MagikarpMove(s.strip()),
    )

    if isinstance(token, MagikarpMove) and token.move == "tk":
        # Tackle: accuracy check + (crit + damage if hit)
        outcome = ctx.hit_crit_or_miss(TACKLE_ACCURACY)
        return status, not isinstance(outcome, Miss)

    # Splash (MagikarpMove("sp")) always fails
    return status, False
```

### MagikarpStatus dataclass

```python
class NonVolatileStatus(Enum):
    NONE = 0
    SLEEP = 1
    FROZEN = 2
    BURN = 3
    POISON = 4
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
```

### End-of-turn processing

End of turn is a fixed **4 rolls** (unconditional). Previous GDB notes showing a variable count
(`ov12_022585B8 x4/x3 + x6 + flee check`) were inaccurate — superseded by verified observation.

```python
ctx.advance_unobservable(4)  # end of turn, always
```

Whether this changes when Magikarp faints is still an open question.

### User input

Users input path tokens as they observe them. The input parser maps user strings to `PathToken` instances. The compass matches the entered prefix against pre-computed candidate paths, eliminating non-matching seeds each turn.

Tokens are entered compactly: `M053 h ~ sp` or equivalently as a sequence of prompts. Undo (`u`) and quit (`q`) behave as in `compass_safari`.

Magikarp level is prompted once at session start. "Go again" prompt after completion, creating visible calibration history in the notebook.

### Undo & caching

Same stack-based approach as `compass_safari`:
```python
cache: list[tuple[str, list[MetronomeCandidate]]] = [("", initial_candidates)]
```

`u` pops the stack. Each turn pushes a new entry.

### Integration

1. **`compass_metronome.py`**: Add `known_moves: tuple[int, ...] = ()` and `magikarp_level: int` to `CompassMetronomeInput`. Metronome always implicit. Max 3 additional known moves.

2. **`compass.py`**: Add re-export `metronome_compass_full`. Rename existing to `metronome_compass_simple`.

3. **`expedition.py`**: Add `metronome_compass_full()` method. Add `magikarp_level` and `known_moves` config fields. Save results to `compass_m_history` up to `compass_metronome_histsize`.

## Files to create/modify

| File | Action |
|------|--------|
| `claytonlib/metronome_compass_full/__init__.py` | **Create** — exports `metronome_compass_full()` |
| `claytonlib/metronome_compass_full/path.py` | **Create** — `PathToken` hierarchy, `Path` type, rendering |
| `claytonlib/metronome_compass_full/context.py` | **Create** — `BattleContext`, `RngContext`, `InteractiveContext`, emit helpers |
| `claytonlib/metronome_compass_full/effects.py` | **Create** — effect scripts and `EFFECT_HANDLERS` registry |
| `claytonlib/compass_metronome.py` | Modify — add `known_moves`, `magikarp_level` to input |
| `claytonlib/compass.py` | Modify — add re-export, rename simple |
| `claytonlib/expedition.py` | Modify — add `metronome_compass_full()` method |
| `one-offs/populate_moves.py` | **Create** — CLI tool for populating move data |
| `notes/combined_moves.json` | **Created** — merged move data for reference |

## Ability restrictions (deferred)

Cute Charm (Cleffa/Clefairy/Clefable) and Serene Grace (Happiny/Chansey/Togepi/Togetic/Togekiss) can interfere with RNG calculations. Require the user to use a Metronome Pokemon without these abilities. All listed Pokemon have alternate abilities. Push to TODO.

## Implementation phases

**Phase 1**: PathToken hierarchy + path rendering + move effect registry + pre-compute paths per seed from the metronome roll only (no post-move RNG). Basic interactive loop that filters on the `MetronomeMove` token. "Go again" loop. This already provides multi-turn filtering equivalent to running the simple compass multiple times.

**Phase 2**: Full dual-mode turn simulation — move execution RNG (hit/crit/damage), Magikarp RNG (move select + Tackle execution), fixed pre/post rolls (BeforeTurn x4, post-metronome x2, Magikarp-start x2, post-Magikarp x2, end-of-turn x4). Does not require status tracking.

**Phase 3**: Magikarp status condition effects (sleep/freeze/flinch/disable/taunt/gravity/confusion/paralysis/attract). Uses `MagikarpStatus`. Gravity move-pool filtering and accuracy modifier. Weather effects, stat stage tracking. Uses `MetronomeBattleState`.

**Phase 4**: Expedition integration, history saving, calibration suggestions, polish.

## Verification

- Unit test: given a known seed, verify pre-computed path matches simple compass metronome roll
- Integration test: construct multi-turn scenario with known seed, verify filtering narrows correctly
- Manual test: run against emulator output and compare

## Resolved questions

1. **Magikarp's level**: Session parameter. Blackthorn City = levels 2-20. Level <15 = Splash only, 15-20 = Splash+Tackle. Flail (30+) not supported → `BLACKTHORN_MAGIKARP`.
2. **Known moves**: Part of input + expedition config. Metronome always implicit. Max 3 additional.
3. **Magikarp fainting**: Halts compass. Hit/crit from killing move still observable. No further turns tracked.
4. **End-of-turn roll count**: Fixed 4 rolls. Supersedes earlier GDB notes.
5. **Tackle accuracy**: 95% in Gen IV. CheckMoveHit still rolled (verified).
6. **Two paths per seed**: Not needed. Level is a session parameter declared upfront.
7. **Effect modeling**: Use effect numbers from decompiled source, not hand-crafted profile dataclass. `move_effect(effect, effect_chance) -> str` for display; effect handlers for simulation.
8. **Turn structure**: Verified sequence — 1 Magikarp-select, 4 BeforeTurn, Metronome roll, move effect, 2 if-successful, 2 Magikarp-start, Magikarp move, 2 if-successful, 4 end-of-turn.
9. **Magikarp status effects**: Detailed mechanics documented in `notes/refined/effect_status.md`. Checked in order: sleep → freeze → flinch → disable → taunt → gravity → confusion → paralysis → attract.

## Things to confirm (before Phase 2)

- Do calc/crit/accuracy rolls still happen for moves like Night Shade (set damage)?
- Do accuracy rolls happen for 100% accurate moves (not to be confused with always-hit moves)?
- What order do crit/accuracy/damage rolls happen? Does miss skip crit and damage rolls?
- Exact formula for miss/crit checks (including stage modifiers and gravity with C integer arithmetic).
- For moves with multiple effects (Ice Fang, Tri Attack), what order are effect rolls done in?
- What is the exact RNG call count when Magikarp faints (end-of-turn processing)?
- Tackle move order in Magikarp's moveset (Splash=0, Tackle=1?).
