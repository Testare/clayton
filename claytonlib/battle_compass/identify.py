"""Narrowing candidate battle seeds against what the player reports.

The whole mechanism is one comparison.  Every surviving candidate is simulated forward through
the action the player took; each produces the tokens *it* would have emitted; any candidate whose
tokens disagree with what was observed is eliminated.  Because the simulation only runs forwards,
there is no second implementation to keep in step (sec 13.1).

Phases, per sec 15.3, because they optimise different things:

* **Phase 1** — setup, player-driven, working the target to 1 HP and paralyzed. No balls
  (sec 2.3): a plain Poke Ball is also x1 on Suicune, so a practice throw that lands catches it
  in the wrong ball and the run is lost.
* **Phase 1.5** — already at 1 HP and paralyzed, pinning the seed. The tool advises; the
  objective is **information gain**.
* **Phase 2** — seed pinned, solver-driven; the objective is **minimum distance**.

An observation that matches *nothing* is the outcome that matters, and is reported rather than
swallowed: it means the window was too narrow, or a modelled constant is wrong. Emptying the set
silently would turn either into a mystery (sec 2.5, sec 15.5).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.candidates import Candidate
from claytonlib.battle_compass.sim import HuntConfig, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status


class Phase(IntEnum):
    SETUP = 1          # Phase 1
    PINNING = 2        # Phase 1.5
    SOLVING = 3        # Phase 2

    @property
    def label(self) -> str:
        return {Phase.SETUP: "Phase 1 — setup",
                Phase.PINNING: "Phase 1.5 — pinning the seed",
                Phase.SOLVING: "Phase 2 — solving"}[self]

    @property
    def balls_allowed(self) -> bool:
        """No throws during setup: the target ends Phase 1 at its most catchable, so a practice
        ball is rising risk for information that moves mostly get for free (sec 2.3)."""
        return self is not Phase.SETUP


@dataclass
class Observation:
    """What the player reported for one turn, as tokens.

    `item_code` and `bench_slot` are part of the action, not of the outcome: the same ITEM action
    heals different amounts and the same SWITCH brings in different Pokemon, so replaying without
    them would reproduce a different turn.
    """
    action: Action
    tokens: tuple[str, ...]
    item_code: str | None = None
    bench_slot: int | None = None

    @property
    def rendered(self) -> str:
        return tok.render_turn(tok.normalise(self.tokens))


@dataclass
class Narrowing:
    """The result of applying one observation."""
    survivors: tuple[int, ...]
    eliminated: int
    #: True when nothing matched — the window or a constant is wrong, not the player.
    contradiction: bool = False
    #: What each surviving candidate predicted, keyed by seed. Kept for display and for
    #: choosing the next action by information gain (sec 15.3).
    predictions: dict[int, str] = field(default_factory=dict)
    #: Predictions from the candidates that were just eliminated, so a contradiction can be
    #: explained rather than merely announced.
    rejected: dict[int, str] = field(default_factory=dict)

    @property
    def identified(self) -> int | None:
        return self.survivors[0] if len(self.survivors) == 1 else None


class Session:
    """One Battle Compass run: candidates in, narrowing out.

    Holds a simulated ``BattleState`` per surviving candidate. They share the player's action
    each turn and differ only in their RNG, which is exactly what makes them separable.
    """

    def __init__(self, candidates: list[Candidate] | tuple[Candidate, ...],
                 ours: Battler, target: Battler, config: HuntConfig,
                 phase: Phase = Phase.SETUP):
        self.config = config
        self.phase = phase
        self.candidate_info = {c.seed: c for c in candidates}
        self.states: dict[int, BattleState] = {
            c.seed: BattleState(ours=ours, target=target, rng=c.seed, phase=int(phase))
            for c in candidates
        }
        self.history: list[Observation] = []
        #: Turn-by-turn record of how the set shrank, for display and for undo.
        self.narrowings: list[Narrowing] = []

    # -- state ----------------------------------------------------------

    @property
    def survivors(self) -> tuple[int, ...]:
        return tuple(self.states)

    @property
    def identified(self) -> int | None:
        return self.survivors[0] if len(self.states) == 1 else None

    def state_of(self, seed: int) -> BattleState:
        return self.states[seed]

    # -- the loop -------------------------------------------------------

    def predict(self, action: Action, **extra) -> dict[int, str]:
        """What each survivor would emit if the player took `action` — without committing.

        This is the display for Phase 1.5: it shows what a given action would distinguish, so
        the player can pick the one that separates the set best (sec 15.3).
        """
        out: dict[int, str] = {}
        for seed, state in self.states.items():
            advanced = simulate_turn(state, action, self.config, **extra)
            out[seed] = tok.render_turn(tok.normalise(advanced.log[-1]))
        return out

    def observe(self, action: Action, tokens: tuple[str, ...] | list[str],
                **extra) -> Narrowing:
        """Apply one reported turn, keeping only the candidates that predicted it.

        A contradiction leaves the surviving set **unchanged** rather than empty: an impossible
        observation is far more likely to mean a too-narrow window or a wrong constant than that
        every candidate is genuinely excluded, and discarding the set would destroy the evidence
        needed to tell which (sec 15.5).
        """
        if not self.phase.balls_allowed and action in (Action.CAPTURE_BALL,
                                                       Action.STANDARD_BALL):
            raise ValueError(
                f"balls are not thrown during {self.phase.label}: a standard Poke Ball shares "
                f"the capture ball's multiplier here, so a throw that lands catches the target "
                f"in the wrong ball")

        observed = tok.render_turn(tok.normalise(tokens))
        advanced: dict[int, BattleState] = {}
        predictions: dict[int, str] = {}
        for seed, state in self.states.items():
            nxt = simulate_turn(state, action, self.config, **extra)
            predictions[seed] = tok.render_turn(tok.normalise(nxt.log[-1]))
            advanced[seed] = nxt

        matched = {s for s, pred in predictions.items() if pred == observed}
        if not matched:
            return Narrowing(survivors=self.survivors, eliminated=0, contradiction=True,
                             predictions={}, rejected=predictions)

        before = len(self.states)
        self.states = {s: advanced[s] for s in matched}
        self.history.append(Observation(action=action, tokens=tuple(tokens),
                                        item_code=extra.get("item_code"),
                                        bench_slot=extra.get("bench_slot")))
        result = Narrowing(survivors=self.survivors, eliminated=before - len(matched),
                           predictions={s: predictions[s] for s in matched},
                           rejected={s: p for s, p in predictions.items() if s not in matched})
        self.narrowings.append(result)
        return result

    # -- phases ---------------------------------------------------------

    def enter_pinning(self) -> None:
        """Move to Phase 1.5. Player-declared, never inferred from a hit count.

        A fixed False Swipe count is unreliable anyway: Aurora Beam's Attack drop lands on us and
        reduces the damage, so some runs need more swipes than others (sec 11.6).
        """
        if self.phase is not Phase.SETUP:
            raise ValueError(f"already past setup ({self.phase.label})")
        self.phase = Phase.PINNING

    def solver_blockers(self) -> list[str]:
        """Why Phase 2 cannot start yet. Empty means it can.

        The solver asserts its preconditions rather than coping with their absence: the target at
        exactly 1 HP and paralyzed is what makes ``b`` a single constant and the battle state
        nearly frozen (sec 2.2).
        """
        problems: list[str] = []
        if self.phase is Phase.SETUP:
            problems.append("still in setup — declare the target at 1 HP to move on")
        if self.identified is None:
            problems.append(f"the seed is not pinned yet ({len(self.states)} candidates remain)")
        for state in self.states.values():
            if state.target.hp != 1:
                problems.append(f"the target is at {state.target.hp} HP, not 1")
            if state.target.status is not Status.PARALYSIS:
                problems.append("the target is not paralyzed")
            break
        return problems

    def enter_solving(self) -> None:
        blockers = self.solver_blockers()
        if blockers:
            raise ValueError("cannot start solving: " + "; ".join(blockers))
        self.phase = Phase.SOLVING

    # -- ambiguity --------------------------------------------------------

    def ambiguity(self) -> dict:
        """Why the surviving set has not collapsed, and whether play can collapse it.

        The distinction that matters: survivors differing only in the **RTC second** cannot be
        separated by any move, ever.  ``calculate_seed`` puts the second in the seed's top 8
        bits, an LCRNG difference of ``k * 2**24`` stays in the top 8 bits forever, and every
        modulus the game takes (``% 4`` move choice, ``% 16`` crit and damage, ``% 100`` accuracy
        and procs) reads only the low bits — which are identical.  Only a magnitude comparison
        tells them apart, and the shake check ``roll < b`` is the game's only one.

        And throwing balls is not a practical substitute.  Measured on a real four-second
        ambiguity: a single throw separates only two of the four, ten throws are needed to
        separate all of them, and **two of those ten throws capture** — losing the run to the
        wrong ball.  So the only viable answer is a narrow second window, which is why
        ``candidates.generate`` defaults ``second_window`` to 0.

        A set stuck on several seconds is therefore **not** waiting for more turns. Restart with
        a tighter second window.
        """
        frames = {self.candidate_info[s].frame for s in self.states
                  if s in self.candidate_info}
        seconds = {self.candidate_info[s].second for s in self.states
                   if s in self.candidate_info}
        second_only = len(frames) <= 1 and len(seconds) > 1
        return {
            "survivors": len(self.states),
            "frames": sorted(frames),
            "seconds": sorted(seconds),
            "frame_pinned": len(frames) <= 1,
            "second_only": second_only,
            "separable_by_moves": not second_only and len(self.states) > 1,
            "advice": (
                "identified" if len(self.states) == 1 else
                "The frame is pinned but several RTC seconds remain, and no move can ever "
                "separate them — the second lives in the seed's top 8 bits, which every in-game "
                "modulo discards. Playing on will not help. Balls are the only observable that "
                "could, and they are not worth it: separating four seconds took ten throws in "
                "testing, two of which captured. Restart with a narrower second window."
                if second_only else
                "Keep playing: the survivors still differ in ways moves can reveal."),
        }

    # -- information gain (Phase 1.5) -----------------------------------

    def ranking_extra(self, action: Action) -> dict:
        """Parameters an action needs before it can be simulated at all, for ranking purposes.

        A switch needs to know who came in and an item needs to know which item. Neither choice
        can affect information gain: both cost zero RNG advances, so every candidate consumes the
        same stream whichever is picked, and the partition is identical. So ranking may default
        them, where actually *observing* the turn must not.
        """
        if action is Action.SWITCH:
            state = next(iter(self.states.values()), None)
            if state is not None and state.bench:
                return {"bench_slot": 0}
        return {}

    def partition(self, action: Action) -> dict[str, tuple[int, ...]]:
        """Survivors grouped by what `action` would make them predict."""
        groups: dict[str, list[int]] = {}
        for seed, pred in self.predict(action, **self.ranking_extra(action)).items():
            groups.setdefault(pred, []).append(seed)
        return {pred: tuple(seeds) for pred, seeds in groups.items()}

    def expected_survivors(self, action: Action) -> float:
        """Expected size of the surviving set after taking `action`.

        Under a uniform prior — which is the right prior here, since the candidate set is
        deliberately unweighted (sec 17.1) — this is ``sum(|g|^2) / N``. Lower is better, and it
        is the objective Phase 1.5 optimises where Phase 2 optimises distance.
        """
        total = len(self.states)
        if total == 0:
            return 0.0
        return sum(len(g) ** 2 for g in self.partition(action).values()) / total

    def rank_actions(self, actions: list[Action] | tuple[Action, ...]) -> list[tuple[Action, float]]:
        """`actions` ordered by how well each separates the set, best first.

        Only actions legal in the current phase are considered, so a ball never appears during
        setup.
        """
        allowed = [a for a in actions
                   if (self.phase.balls_allowed
                       or a not in (Action.CAPTURE_BALL, Action.STANDARD_BALL))
                   and (a is not Action.SWITCH
                        or any(st.bench for st in self.states.values()))]
        scored = [(a, self.expected_survivors(a)) for a in allowed]
        scored.sort(key=lambda pair: (pair[1], pair[0].value))
        return scored
