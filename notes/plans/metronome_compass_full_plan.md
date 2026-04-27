# Complex Metronome Compass — Implementation Plan

## Context

The current `compass_metronome` (simple) takes one Metronome move observation, filters candidates, and exits. The **complex** version tracks RNG state across multiple battle turns — each turn the user observes what move Metronome selected, whether it hit/crit, what Magikarp did, etc., and the compass filters candidates by simulating the full RNG sequence. This is analogous to how `compass_safari` tracks RNG through multiple safari turns.

The key challenge is accurately modeling every RNG call in a battle turn so the simulated state stays in sync with the game's actual RNG state across turns.

## GDB-verified turn RNG sequence (from `notes/gdb/metronome`)

**Battle start**: 4 bellShimmer + 2 ability + 1 flee = **7 advances** (same as safari `start_encounter`)

**Each turn** (observed with a standard damaging move + Magikarp Tackle):
```
BEFORE TURN x4                          # quick claw checks
BtlCmd_Metronome()                      # 1+ rolls (reroll if disallowed/known)
CalcDamage / CheckMoveHit / TryCrit / ApplyDamage   # move execution (variable)
CheckMoveHit                            # opponent's move accuracy
Battle script rand                      # 1
ov12_022585B8 x4 (x3 if Splash)        # post-turn ability processing
ov12_022585B8 x6                        # more ability processing
0x0225e46e                              # flee check
```

**Important uncertainty**: The "x3 if they splash I think" comment in GDB notes needs verification. Getting end-of-turn count wrong means state diverges after turn 1.

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

# Singleton tokens (zero-field frozen dataclasses, module-level instances)
Hit        → "h"
Miss       → "-"
Crit       → "!"   # implies hit; never combined with h
EffectProc → "~"
Fainted    → "F"
PAR        → "PAR"   # Magikarp couldn't move: paralyzed
FRZ        → "FRZ"   # frozen
CFZ        → "CFZ"   # confused (hurt itself)
```

**Only emit tokens for events that represent an actual RNG roll.** A move with no accuracy check doesn't produce a Hit/Miss token. A move with no effect chance doesn't produce an EffectProc token. This keeps paths minimal.

**Crit vs hit**: `!` (crit) implies the move hit. `h` is hit without crit. `-` is miss; crit is not observable on a miss and is never emitted.

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

    def emit(self,
             rng_to_token: Callable[[int], PathToken],
             question: str,
             input_to_token: Callable[[str], PathToken]) -> PathToken:
        """Advance one observable RNG event. Appends resulting token to current turn."""
        ...

    def raw_emit(self, token: PathToken) -> PathToken:
        """Append a token directly, for cases where one question per token isn't appropriate."""
        ...

    def advance(self, n: int = 1) -> None:
        """Consume n non-observable RNG rolls (no token emitted)."""
        ...

    def end_turn(self) -> tuple[PathToken, ...]:
        """Snapshot the current turn's tokens and start a new turn."""
        ...

    # --- Emit helpers (common token patterns, defined once) ---
    def hit_crit_or_miss(self, accuracy: int) -> PathToken:
        """Single question: h/!/- covering both accuracy and crit rolls."""
        ...

    def effect_proc(self, chance: int) -> PathToken | None:
        """Roll/ask whether a secondary effect proc'd. Returns EffectProc or None."""
        ...

    def multi_hit(self) -> PathToken:
        """Roll/ask number of hits for a multi-hit move."""
        ...
```

**`RngContext`**: implements `emit()` by advancing the internal RNG state and applying `rng_to_token`. `advance()` increments RNG without emitting. Exposes `.rng` for reading current state. The `battle_state` dict and token accumulation are inherited.

**`InteractiveContext`**: implements `emit()` by printing `question`, reading user input, and applying `input_to_token`. `advance()` is a no-op. No RNG state. Filtering against pre-computed paths happens outside the context, at turn boundaries after `end_turn()` is called.

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

### Magikarp simulation

```python
def _simulate_magikarp(rng, obs_tokens, magikarp_level):
    if magikarp_level >= 15:
        rng = advance_rng(rng)
        selected_idx = (rng >> 16) % 2
        # Validate: does selected_idx map to the observed move?
        # Move order (Splash=0, Tackle=1?) needs GDB verification

    if magikarp_move == "tackle":
        rng = advance_rng(rng)  # accuracy check
        if hit:
            rng = advance_rng(rng)  # crit
            rng = advance_rng(rng)  # damage
    # Splash: 0 additional RNG
    return rng
```

### End-of-turn processing

```python
def _simulate_end_of_turn(rng, magikarp_splashed, target_fainted):
    rng = advance_rng(rng)           # battle script rand
    ability_block_1 = 3 if magikarp_splashed else 4
    rng = advance_n(rng, ability_block_1)
    rng = advance_n(rng, 6)          # ov12_022585B8 x6
    rng = advance_rng(rng)           # flee check
    return rng
```

**Open question**: Does end-of-turn processing change when Magikarp faints?

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

**Phase 2**: Full dual-mode turn simulation — move execution RNG, Magikarp RNG, end-of-turn RNG. Requires GDB verification of exact RNG call counts and ordering.

**Phase 3**: Gravity tracking (move pool + accuracy modifier), weather effects, stat stage tracking, status condition effects on Magikarp. Uses `MetronomeBattleState`.

**Phase 4**: Expedition integration, history saving, calibration suggestions, polish.

## Verification

- Unit test: given a known seed, verify pre-computed path matches simple compass metronome roll
- Integration test: construct multi-turn scenario with known seed, verify filtering narrows correctly
- Manual test: run against emulator output and compare

## Resolved questions

1. **Magikarp's level**: Session parameter. Blackthorn City = levels 2-20. Level <15 = Splash only, 15-20 = Splash+Tackle. Flail (30+) not supported → `BLACKTHORN_MAGIKARP`.
2. **Known moves**: Part of input + expedition config. Metronome always implicit. Max 3 additional.
3. **Magikarp fainting**: Halts compass. Hit/crit from killing move still observable. No further turns tracked.
4. **End-of-turn uncertainty**: All GDB numbers need re-verification.
5. **Tackle accuracy**: 95% in Gen IV. Needs GDB verification whether accuracy roll is consumed.
6. **Two paths per seed**: Not needed. Level is a session parameter declared upfront.
7. **Effect modeling**: Use effect numbers from decompiled source, not hand-crafted profile dataclass. `move_effect(effect, effect_chance) -> str` for display; effect handlers for simulation.

## Things to confirm (before Phase 2)

- Do calc/crit/accuracy rolls still happen for moves like Night Shade (set damage)?
- Do accuracy rolls happen for 100% accurate moves (not to be confused with always-hit moves)?
- What order do crit/accuracy/damage rolls happen? Does miss skip crit and damage rolls?
- Exact formula for miss/crit checks (including stage modifiers and gravity with C integer arithmetic).
- How confusion/paralysis/infatuation/sleep/freeze prevent or modify moves.
- For moves with multiple effects (Ice Fang, Tri Attack), what order are effect rolls done in?
- What is the exact RNG call count when Magikarp faints (end-of-turn processing)?
- Tackle move order in Magikarp's moveset (Splash=0, Tackle=1?).
