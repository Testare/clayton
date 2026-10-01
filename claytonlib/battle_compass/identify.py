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
from claytonlib.battle_compass.sim import HuntConfig, opening_rng, simulate_turn
from claytonlib.battle_compass.state import Action, Battler, BattleState, Status


#: Measured median turns for two seeds one RTC second apart to predict different tokens, playing
#: False Swipe every turn against the section 11 fixture (120 pairs: all separated, max 54).
SECOND_SIBLING_MEDIAN_TURNS = 19


class Phase(IntEnum):
    SETUP = 1          # Phase 1
    PINNING = 2        # Phase 1.5
    SOLVING = 3        # Phase 2

    @property
    def label(self) -> str:
        return {Phase.SETUP: "Phase 1 — setup",
                Phase.PINNING: "Phase 1.5 — pinning the seed",
                Phase.SOLVING: "Phase 2 — solving"}[self]

    #: Balls are legal in EVERY phase. The blanket Phase 1 ban this replaces was wrong on both
    #: halves. The capture ball is never a risk -- if it lands, the run is won -- so forbidding
    #: it only wasted information. And a standard ball IS a risk, but a measured one that gets
    #: *cheaper* the earlier it is thrown: 0.35% per throw at full HP against 1.25% at 1 HP and
    #: paralyzed, because the shake threshold rises as the target weakens
    #: (notes/seed_separation.md sec 2a). The ban's own reasoning had this backwards -- it
    #: assumed the target "ends Phase 1 at its most catchable" and so deferred throws to exactly
    #: the point where they cost the most.
    #:
    #: The information was worth having, too: the shake check is a magnitude comparison rather
    #: than a modulus, so it separates RTC-second siblings 44.5% of the time per roll -- a median
    #: of 2 turns, against 13 for the 100%-accuracy filler the ban forced instead.
    #:
    #: What replaces the gate is disclosure, not permission: `HuntSession.standard_ball_risk`
    #: reports the live fraction of candidates a plain ball would catch, and
    #: `HuntConfig.standard_ball_matches_capture_ball` says whether this matchup is the dangerous
    #: one at all.


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
        # `opening_rng`, not the raw seed: the battle seed is not the state turn 1 runs from.
        # The game burns `config.battle_start_advances` rolls first, and seeding the simulation
        # with the seed itself put every candidate six advances into the wrong stream -- which
        # eliminated the TRUE seed on turn 1 of data/battle_logs/test2.jsonl while leaving 29
        # unrelated ones alive. The dict stays keyed by the seed the player targeted, so nothing
        # downstream has to know about the offset.
        self.states: dict[int, BattleState] = {
            c.seed: BattleState(ours=ours, target=target, rng=opening_rng(c.seed, config),
                                phase=int(phase))
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
        """Why the surviving set has not collapsed, and how expensive collapsing it will be.

        **Corrected.** An earlier version of this claimed survivors differing only in the RTC
        second could never be separated by any move. That is wrong, and the correction matters
        because it changes the advice from "restart" to "keep playing".

        What is true is the invariant: ``calculate_seed`` puts the second in the seed's top 8
        bits, and an LCRNG difference of ``k * 2**24`` stays a multiple of ``2**24`` forever --
        ``(2**24 * c) * A mod 2**32`` is ``2**24 * (c * A mod 2**8)``. What does *not* follow is
        that the game cannot see it. A roll is ``state >> 16``, so it differs by ``256 * c``, and:

        * ``% 4`` (the wild move choice) and ``% 16`` (crit and damage rolls) are **identical**,
          because 256 is a multiple of both.
        * ``% 100`` (accuracy checks and secondary-effect procs) **differs**, because 100 does
          not divide 256.
        * A magnitude comparison -- the shake check ``roll < b`` -- differs too.

        So second-siblings are separable, just slowly, and slowly for a reason specific to this
        matchup: no move in the fixture can miss (every accuracy is 100 or 0), so the accuracy
        roll's verdict is invisible, and the only observable ``% 100`` left is Aurora Beam's 10%
        Attack-drop proc. That needs Aurora Beam chosen (one move of four) *and* the two rolls to
        straddle the 10 threshold (~20% of rolls), which is about 5% of turns.

        Measured over 120 second-apart pairs playing False Swipe every turn: **all 120 separated,
        median 19 turns, max 54.** So ``second_window`` still defaults to 0 -- five times the
        candidates and ~19 extra turns is a poor trade when the second is usually known from
        ``rtc_offset_seconds`` -- but a set stuck on seconds is waiting for turns, not doomed.
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
            # Second-siblings ARE separable -- see the docstring. Slowly, but separable, so this
            # is no longer False for them.
            "separable_by_moves": len(self.states) > 1,
            "expected_turns": SECOND_SIBLING_MEDIAN_TURNS if second_only else None,
            "advice": (
                "identified" if len(self.states) == 1 else
                f"The frame is pinned; what remains differs only in the RTC second. That is "
                f"slow to resolve, not impossible: the move choice and the crit and damage rolls "
                f"are genuinely identical, but accuracy and proc rolls take % 100, which does "
                f"see the difference. For this matchup nothing can miss, so it comes down to "
                f"Aurora Beam's 10% Attack drop -- about one turn in twenty. Measured median "
                f"{SECOND_SIBLING_MEDIAN_TURNS} turns to separate a pair. Keep playing, or "
                f"restart with a narrower second window if you would rather not spend them."
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

        Balls are ranked alongside moves rather than filtered out by phase, and they rank well:
        the shake check is a magnitude comparison, so it sees differences every modulus dividing
        256 is blind to. Ranking is about INFORMATION only -- a standard ball's risk of ending
        the run is priced nowhere in this number, which is why `standard_ball_risk` is reported
        next to it rather than folded into it.
        """
        allowed = [a for a in actions
                   if a is not Action.SWITCH
                   or any(st.bench for st in self.states.values())]
        scored = [(a, self.expected_survivors(a)) for a in allowed]
        scored.sort(key=lambda pair: (pair[1], pair[0].value))
        return scored
