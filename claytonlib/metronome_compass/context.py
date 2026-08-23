"""BattleContext abstract base and its two concrete implementations."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable, TYPE_CHECKING

from claytonlib.safari import advance_rng
from .path import (
    PathToken, Turn, Path,
    Hit, Miss, Crit, EffectProc,
    MagikarpMove, MultiHit,
)

# Indexed by crit stage (0–4). RAND % modifier == 0 → crit.
_CRIT_MODIFIERS = [16, 8, 4, 3, 2]


class BattleContext(ABC):
    """Tracks RNG events during a battle and accumulates them into a Path.

    Mutable for the whole battle session. Call end_turn() at the end of each
    battle turn to snapshot that turn's tokens and begin the next.

    Two implementations exist:
    - RngContext: drives state from an RNG seed (pre-computes paths).
    - InteractiveContext: drives state from user input (interactive session).

    Effect scripts are mode-agnostic: they call emit() helpers on whichever
    context they receive.
    """

    def __init__(self) -> None:
        self.battle_state: dict = {}
        self._path: list[list[PathToken]] = []
        self._current_turn: list[PathToken] = []

    # ------------------------------------------------------------------
    # Low-level primitives
    # ------------------------------------------------------------------

    @abstractmethod
    def advance_unobservable(self, n: int = 1) -> None:
        """Consume n non-observable RNG rolls.

        RngContext: advances internal RNG n times.
        InteractiveContext: no-op.
        """

    @abstractmethod
    def advance_observable(self) -> int:
        """Consume one observable RNG roll and return the shifted (top 16 bits) value.

        RngContext: advances RNG and returns the shifted value.
        InteractiveContext: raises RuntimeError. Effect scripts must use
        emit() helpers rather than calling this directly.
        """

    @abstractmethod
    def consume_observable_roll(self) -> int | None:
        """Advance observable RNG and return value (RngContext) or None (Interactive).

        Use for rolls that happen early in a turn but whose results are only
        observed (and thus emitted as tokens) later.
        """

    @abstractmethod
    def _resolve_emit(
        self,
        rng_to_token: Callable[['BattleContext'], PathToken],
        question: str,
        input_to_token: Callable[[str], PathToken],
    ) -> PathToken:
        """Mode-specific resolution for emit(). Implemented by subclasses."""

    @abstractmethod
    def unobservable_roll(self) -> int:
        """Advance RNG by one roll that affects state but emits no token.

        RngContext: advances internal RNG and returns the shifted value.
        InteractiveContext: returns 0 (caller uses a conservative default).

        Use for rolls whose outcome is not directly observable to the player
        on the turn they occur (e.g. Yawn sleep-duration roll at end of turn).
        """

    @abstractmethod
    def _resolve_proc(self, chance: int) -> bool:
        """Roll/ask whether a secondary effect proc'd. Does NOT emit a token.

        RngContext: advances observable RNG, computes outcome.
        InteractiveContext: prompts the user.
        Returns True if proc'd.
        """

    # ------------------------------------------------------------------
    # Token emission
    # ------------------------------------------------------------------

    def emit(
        self,
        rng_to_token: Callable[['BattleContext'], any],
        question: str,
        input_to_token: Callable[[str], any],
    ) -> any:
        """Resolve one observable event into a token and append it to the current turn.

        rng_to_token receives the context so it can call advance_observable() /
        advance_unobservable() as needed and consult battle_state. It may call
        advance_observable() multiple times (e.g. metronome rerolls).

        RngContext calls rng_to_token(self).
        InteractiveContext prints question and calls input_to_token on the answer.
        """
        token = self._resolve_emit(rng_to_token, question, input_to_token)
        if token is not None and isinstance(token, PathToken):
            self._current_turn.append(token)
        return token


    def raw_emit(self, token: PathToken) -> PathToken:
        """Append a token directly — no RNG roll and no user prompt.

        Use when a token is determined by earlier emit() results, or when one
        user question resolves multiple tokens and raw_emit() handles the extras.
        """
        self._current_turn.append(token)
        return token

    def end_turn(self) -> Turn:
        """Snapshot the current turn's tokens, begin a new turn, return the snapshot."""
        turn: Turn = tuple(self._current_turn)
        self._path.append(list(turn))
        self._current_turn = []
        return turn

    @property
    def path(self) -> Path:
        """Completed turns accumulated so far (excludes the current in-progress turn)."""
        return tuple(tuple(t) for t in self._path)

    # ------------------------------------------------------------------
    # Emit helpers — common token patterns defined once on the base class
    # ------------------------------------------------------------------

    def lock_on_active(self) -> bool:
        """True if Mind Reader / Lock-On guarantees the user's move hits this turn.

        The hit roll is still consumed on hardware — only its result is forced to
        Hit — so callers must advance the accuracy roll *before* consulting this.
        """
        state = self.battle_state.get('state')
        return state is not None and state.user_lock_on_turns > 0

    def effective_accuracy(self, base: int) -> int:
        """Apply accuracy/evasion stat stages and gravity to a base accuracy.

        base=0 is the always-hit sentinel and is returned unchanged. Uses the
        Gen-IV accuracy stage table (net = user accuracy stage − target evasion
        stage, clamped to ±6) and the 5/3 gravity multiplier. Integer floor math
        matches the game's fixed-point behaviour.

        Lock-On/Mind Reader is NOT handled here: it doesn't change the accuracy
        value, it forces the *result* while still consuming the roll. See
        lock_on_active() and the hit resolvers.
        """
        if base == 0:
            return 0
        state = self.battle_state.get('state')
        if state is None:
            return base
        net = max(-6, min(6, state.user_accuracy_stage - state.target_evasion_stage))
        if net >= 0:
            acc = base * (3 + net) // 3
        else:
            acc = base * 3 // (3 - net)
        if state.gravity_turns > 0:
            acc = acc * 5 // 3
        return acc

    def hit_crit_or_miss(self, accuracy: int, crit_stage: int = 0) -> PathToken:
        """Resolve the crit/damage/hit 3-roll sequence to a single Miss, Hit, or Crit token.

        A single h/!/- question covers all three outcomes in interactive mode.
        accuracy=0 means the move always hits (no accuracy roll consumed).
        crit_stage=1 for high-crit moves (effect 43); default 0 for normal moves.
        The user's Focus Energy crit stage is added on top of crit_stage.
        The hit roll uses effective_accuracy() so evasion/accuracy stages and
        gravity are respected.
        """
        state = self.battle_state.get('state')
        total_crit_stage = crit_stage + (state.user_crit_stage if state is not None else 0)
        modifier = _CRIT_MODIFIERS[min(total_crit_stage, 4)]

        def rng_to_token(ctx: BattleContext) -> PathToken:
            crit_roll = ctx.advance_observable()
            ctx.advance_unobservable()  # damage roll is not observable
            is_crit = crit_roll % modifier == 0
            if accuracy == 0:
                return Crit() if is_crit else Hit()
            hit_roll = ctx.advance_observable()
            # Lock-On still rolls the hit check; only the result is forced to Hit.
            is_hit = ctx.lock_on_active() or hit_roll % 100 < ctx.effective_accuracy(accuracy)
            if not is_hit:
                return Miss()
            return Crit() if is_crit else Hit()

        token = self.emit(
            rng_to_token=rng_to_token,
            question="Hit, crit, or miss? (h/!/-):",
            input_to_token=lambda s: {'h': Hit, '!': Crit, '-': Miss}[s.strip()](),
        )
        # A landed damaging move (only damaging moves use hit_crit_or_miss) means
        # Magikarp took damage → provably not at full HP (clears any prior heal).
        if state is not None and not isinstance(token, Miss):
            state.mk_took_damage = True
            state.mk_recovered = False
        return token

    def effect_proc(self, chance: int, apply: Callable[[], bool] | None = None) -> bool:
        """Roll/ask whether a secondary effect proc'd. Emits EffectProc if observable.

        Returns True if the RNG proc'd (roll < chance). The roll always advances.
        `apply`, if given, is invoked on a proc to mutate battle state (e.g. apply
        a status) and returns whether the effect was *observable*. The EffectProc
        token is emitted only when the effect actually landed — a proc against a
        Magikarp that already has a non-volatile status (or freeze in sun) rolls
        the RNG but shows no message, so no token is emitted.

        Only call this after confirming the move hit.
        """
        proc = self._resolve_proc(chance)
        if proc:
            observable = True if apply is None else apply()
            if observable:
                self.raw_emit(EffectProc())
        return proc

    def multi_hit(self) -> int:
        """Roll/ask number of hits. Emits MultiHit token. Returns the count.

        Gen IV distribution: 35% x2, 35% x3, 15% x4, 15% x5.
        TODO: verify exact RNG formula with GDB.
        """
        def rng_to_token(ctx: BattleContext) -> PathToken:
            roll = ctx.advance_observable()
            r = roll % 20
            count = 2 if r < 7 else 3 if r < 14 else 4 if r < 17 else 5
            return MultiHit(count)

        token = self.emit(
            rng_to_token=rng_to_token,
            question="Number of hits? (2/3/4/5):",
            input_to_token=lambda s: MultiHit(int(s.strip())),
        )
        assert isinstance(token, MultiHit)
        return token.count

    def magikarp_move_select(self, magikarp_level: int, roll: int | None = None) -> MagikarpMove:
        """Roll/ask which move Magikarp chose. Emits MagikarpMove token.

        Level < 15: Splash only — no RNG roll consumed.
        Level 15+: Splash or Tackle — one RNG roll for move selection.
        If 'roll' is provided, it is used instead of advancing RNG (RngContext only).

        TODO: verify move index order (Splash=0, Tackle=1?) with GDB.
        """
        if magikarp_level < 15:
            return self.raw_emit(MagikarpMove("sp"))  # type: ignore[return-value]

        def rng_to_token(ctx: BattleContext) -> PathToken:
            r = roll if roll is not None else ctx.advance_observable()
            idx = r % 2  # TODO: verify Splash=0, Tackle=1
            return MagikarpMove("sp" if idx == 0 else "tk")

        token = self.emit(
            rng_to_token=rng_to_token,
            question="Magikarp used? (sp/tk):",
            input_to_token=lambda s: MagikarpMove(s.strip()),
        )
        assert isinstance(token, MagikarpMove)
        return token


# ---------------------------------------------------------------------------
# RngContext
# ---------------------------------------------------------------------------

class RngContext(BattleContext):
    """BattleContext that advances an RNG state to pre-compute paths."""

    def __init__(self, rng: int) -> None:
        super().__init__()
        self.rng = rng

    def advance_unobservable(self, n: int = 1) -> None:
        for _ in range(n):
            self.rng = advance_rng(self.rng)

    def advance_observable(self) -> int:
        self.rng = advance_rng(self.rng)
        return self.rng >> 16

    def unobservable_roll(self) -> int:
        self.rng = advance_rng(self.rng)
        return self.rng >> 16

    def consume_observable_roll(self) -> int | None:
        return self.advance_observable()

    def _resolve_emit(self, rng_to_token, question, input_to_token) -> PathToken:
        return rng_to_token(self)

    def _resolve_proc(self, chance: int) -> bool:
        roll = self.advance_observable()
        return roll % 100 < chance

    def roll_hidden_duration(self, min_dur: int, max_dur: int) -> int:
        """Roll a hidden status duration (Disable/Taunt/Encore).

        Consumes one observable RNG roll (its value is never tokenised — the
        duration is unobservable at apply time) and returns the actual duration
        in [min_dur, max_dur]. The wear-off is what the player observes; see
        hidden_status_ends().
        """
        span = max_dur - min_dur + 1
        return min_dur + (self.advance_observable() % span)

    def hidden_status_ends(self, label: str, remaining: int,
                           min_dur: int, max_dur: int) -> bool:
        """Whether a hidden-duration status wears off at the end of this turn.

        `remaining` counts down from the rolled duration, so it ends on the turn
        its remaining count reaches its final tick. min_dur/max_dur are unused in
        RNG mode (the actual duration is known).
        """
        return remaining <= 1

    def confusion_outcome(self, label: str, remaining: int,
                          min_dur: int, max_dur: int) -> str:
        """Resolve a confused Pokémon's turn: 'snap', 'hit_self', or 'act'.

        Confusion lasts `remaining` turns counting this one. On its final turn
        (remaining == 1) the Pokémon snaps out immediately with NO self-hit roll
        (ground truth: "snapped out of confusion!" with no preceding check).
        Otherwise a self-hit check consumes one observable roll: even → hurt
        itself, odd → attack through. The caller emits SCFZ on 'snap' and CFZ on
        'hit_self'; 'act' emits nothing.
        """
        if remaining <= 1:
            return 'snap'
        roll = self.advance_observable()
        return 'hit_self' if (roll & 1) == 0 else 'act'

    def confirm_lock_end(self, label: str) -> bool:
        """Whether a hidden-length lock (rampage/uproar) ended THIS turn.

        RNG mode never forces an early end — the rolled lock length (its counter)
        is authoritative. Interactive mode overrides this to observe the end.
        """
        return False


# ---------------------------------------------------------------------------
# InteractiveContext
# ---------------------------------------------------------------------------

class InteractiveContext(BattleContext):
    """BattleContext that builds a path from user observations."""

    def advance_unobservable(self, n: int = 1) -> None:
        pass

    def advance_observable(self) -> int:
        raise RuntimeError(
            "advance_observable() must not be called on InteractiveContext. "
            "Effect scripts must use emit() helpers, not advance_observable() directly."
        )

    def unobservable_roll(self) -> int:
        return 0  # Duration unknown in interactive mode; caller uses conservative default

    def consume_observable_roll(self) -> int | None:
        return None

    def _resolve_emit(self, rng_to_token, question, input_to_token) -> PathToken:
        while True:
            raw = input(f"  {question} ").strip()
            try:
                return input_to_token(raw)
            except (KeyError, ValueError):
                print(f"    Invalid input: {raw!r}. Try again.")

    def _resolve_proc(self, chance: int) -> bool:
        while True:
            raw = input("  Effect proc'd? (~/-): ").strip()
            if raw == '~':
                return True
            if raw == '-':
                return False
            print(f"    Invalid input: {raw!r}. Enter ~ (proc'd) or - (no proc).")

    def roll_hidden_duration(self, min_dur: int, max_dur: int) -> int:
        """Hidden duration is unobservable at apply time: track the maximum and
        confirm the actual wear-off later via hidden_status_ends(). No prompt and
        no token here — the player cannot know the duration when it is applied.
        """
        return max_dur

    def hidden_status_ends(self, label: str, remaining: int,
                           min_dur: int, max_dur: int) -> bool:
        """Ask whether the status wore off at the end of this turn.

        `remaining` counts down from max_dur (set by roll_hidden_duration), so the
        1-based turn number since application is `max_dur - remaining + 1`. Before
        the minimum possible duration it cannot have ended; at the maximum it must
        have; in between we prompt the player, who observes the wear-off message.
        """
        turn = max_dur - remaining + 1
        if turn < min_dur:
            return False
        if turn >= max_dur:
            return True
        while True:
            raw = input(f"  Did {label} wear off at end of turn? (y/n): ").strip().lower()
            if raw == 'y':
                return True
            if raw == 'n':
                return False
            print("    Invalid input. Enter y (wore off) or n (still active).")

    def confusion_outcome(self, label: str, remaining: int,
                          min_dur: int, max_dur: int) -> str:
        """Prompt the player for a confused Pokémon's turn outcome.

        Duration is hidden. Before the minimum a snap is impossible; on the final
        possible turn (>= max) it must snap out (no self-hit roll). In between the
        player picks from three observed outcomes. Only 'snap' (SCFZ) and
        'hit_self' (CFZ) produce tokens; 'act' looks like a normal attack.
        """
        turn = max_dur - remaining + 1
        if turn >= max_dur:
            return 'snap'
        can_snap = turn >= min_dur
        opts = ("s=snapped out, h=hit itself, a=attacked through it"
                if can_snap else "h=hit itself, a=attacked through it")
        keymap = {'h': 'hit_self', 'a': 'act', 's': 'snap'}
        while True:
            raw = input(f"  {label} confusion — {opts}: ").strip().lower()
            if raw in keymap and (raw != 's' or can_snap):
                return keymap[raw]
            print("    Invalid input.")

    def confirm_lock_end(self, label: str) -> bool:
        """Ask whether a hidden-length lock (rampage/uproar) ended this turn.

        Called only within the possible-end window (the caller gates on the
        minimum length), so the player simply reports what they observed: the
        rampage/uproar stopping (Metronome resumes / confusion sets in).
        """
        while True:
            raw = input(f"  Did {label} end this turn? (y/n): ").strip().lower()
            if raw == 'y':
                return True
            if raw == 'n':
                return False
            print("    Invalid input. Enter y (ended) or n (continues).")
