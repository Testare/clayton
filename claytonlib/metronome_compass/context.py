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

    def hit_crit_or_miss(self, accuracy: int) -> PathToken:
        """Resolve the crit/damage/hit 3-roll sequence to a single Miss, Hit, or Crit token.

        A single h/!/- question covers all three outcomes in interactive mode.
        accuracy=0 means the move always hits (no accuracy roll consumed).

        TODO: verify roll order and exact C integer thresholds with GDB.
        """
        def rng_to_token(ctx: BattleContext) -> PathToken:
            crit_roll = ctx.advance_observable()
            ctx.advance_unobservable()  # damage roll is not observable
            # TODO: BELOW LOGIC IS WRONG - check critical_hit.md for correct logic
            is_crit = crit_roll % 256 < 17
            if accuracy == 0:
                return Crit() if is_crit else Hit()
            hit_roll = ctx.advance_observable()
            is_hit = hit_roll % 100 < accuracy
            if not is_hit:
                return Miss()
            return Crit() if is_crit else Hit()

        return self.emit(
            rng_to_token=rng_to_token,
            question="Hit, crit, or miss? (h/!/-):",
            input_to_token=lambda s: {'h': Hit, '!': Crit, '-': Miss}[s.strip()](),
        )

    def effect_proc(self, chance: int) -> bool:
        """Roll/ask whether a secondary effect proc'd. Emits EffectProc if so.

        Returns True if proc'd. Only call this after confirming the move hit.
        """
        proc = self._resolve_proc(chance)
        if proc:
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
