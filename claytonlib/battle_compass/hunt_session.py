"""One Battle Compass run, from the first turn to the capture.

The layer the app drives.  ``identify.Session`` narrows candidates and ``solver.solve`` steers
the RNG; this joins them into something with a single surface: take a snapshot, show it, accept
one reported turn, repeat.  Nothing here is interactive and nothing blocks -- the caller owns the
prompting, which is what lets the same object back a desktop UI, a test, and a replay of a
recorded battle.

Two design choices worth stating, because both differ from how the older tools work.

**Undo is replay, not rollback.**  The session keeps the candidate window and the list of
observations, and rewinding means rebuilding from the window and replaying one fewer turn.  No
``BattleState`` is ever snapshotted or mutated backwards.  Exact by construction, and cheap: a
few hundred candidates over a handful of turns.

**Phase 2 re-solves every turn rather than following a precomputed path.**  Sec 15.4.2 asked for
two undo operations -- rewind a misreport, but accept a *misplay* and re-solve, because the game
has already advanced and cannot be rewound.  Re-solving unconditionally collapses those into one
path: a misplay is simply the next turn's starting state.  It costs nothing worth counting, since
a solve is ~0.2s, and it removes the failure mode where a stale path is followed past a
divergence (sec 2.5).
"""
from __future__ import annotations

from dataclasses import dataclass

from claytonlib.battle.damage import Attacker, Defender, damage_range, unsupported_reason
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass.candidates import CandidateWindow
from claytonlib.battle_compass.identify import Phase, Session
from claytonlib.battle_compass.sim import HuntConfig
from claytonlib.battle_compass.solver import Solution, SolverConfig, Unreachable, solve
from claytonlib.battle_compass.state import Action, Battler

#: How many candidate rows a snapshot carries. The full set can be 1,200 wide; the UI shows the
#: nearest few and a count, and the window is sorted centre-first so these are the likeliest.
CANDIDATE_PREVIEW = 12


def worst_incoming_hit(ours: Battler, target: Battler) -> int:
    """The largest single hit the target can land: max roll, critical, over all its moves.

    The solver's `danger_floor` -- heal at or below this and no single hit can faint us, without
    needing to know which move is coming (sec 11.2). Critical, because a crit ignores any stat
    change that would reduce the damage, so a Sp. Def boost cannot be relied on.
    """
    worst = 0
    for slot in range(len(target.moves)):
        move = target.move(slot)
        if move is None or unsupported_reason(move) is not None:
            continue
        _, high = damage_range(
            move,
            Attacker(level=target.level, attack=target.stats["atk"],
                     special_attack=target.stats["spa"], types=target.types),
            Defender(defence=ours.stats["def"], special_defence=ours.stats["spd"],
                     types=ours.types),
            critical=True)
        worst = max(worst, high)
    return worst


#: Move slot -> Action, so slot order and token numbering cannot drift apart.
_MOVE_ACTIONS = (Action.MOVE_1, Action.MOVE_2, Action.MOVE_3, Action.MOVE_4)


@dataclass
class TurnLog:
    """One accepted turn, kept for display and for replay-based undo."""
    action: Action
    tokens: tuple[str, ...]
    survivors_before: int
    survivors_after: int

    @property
    def rendered(self) -> str:
        return tok.render_turn(tok.normalise(self.tokens))


class HuntSession:
    """A run in progress: candidates, phase, history, and the current solver advice."""

    def __init__(self, window: CandidateWindow, ours: Battler, target: Battler,
                 config: HuntConfig, *, solver_config: SolverConfig | None = None,
                 capture_ball: str = ""):
        if not window.candidates:
            raise ValueError("no candidate seeds: widen the window or check the seed targeting")
        self.window = window
        self.ours = ours
        self.target = target
        self.config = config
        self.capture_ball = capture_ball
        self.danger_floor = worst_incoming_hit(ours, target)
        self.solver_config = solver_config or SolverConfig(danger_floor=self.danger_floor)
        self.turns: list[TurnLog] = []
        #: Phase transitions as (turns taken before it, phase), in order. A list rather than a
        #: dict keyed by turn index because two transitions can share an index -- declaring 1 HP
        #: and starting the solver on the same turn boundary is normal -- and a dict would silently
        #: keep only the last.
        self.transitions: list[tuple[int, Phase]] = []
        self.contradiction: dict | None = None
        self.solution: Solution | Unreachable | None = None
        self._session = self._fresh()

    # -- construction / replay ------------------------------------------

    def _fresh(self) -> Session:
        return Session(list(self.window.candidates), self.ours, self.target, self.config,
                       phase=Phase.SETUP)

    def _apply_transitions_at(self, boundary: int) -> None:
        """Re-enter any phase recorded at this turn boundary, in the order it happened."""
        for at, phase in self.transitions:
            if at != boundary:
                continue
            if phase is Phase.PINNING and self._session.phase is Phase.SETUP:
                self._session.enter_pinning()
            elif phase is Phase.SOLVING and self._session.phase is not Phase.SOLVING:
                self._session.enter_solving()

    def _replay(self, turns: list[TurnLog]) -> None:
        """Rebuild from the window and re-apply `turns`. The only way state moves backwards."""
        self._session = self._fresh()
        self.contradiction = None
        replayed: list[TurnLog] = []
        for index, turn in enumerate(turns):
            self._apply_transitions_at(index)
            before = len(self._session.survivors)
            result = self._session.observe(turn.action, turn.tokens)
            if result.contradiction:
                # Only reachable if the model changed under us; a turn that was accepted once
                # must be accepted again. Stop rather than silently dropping it.
                raise ValueError(
                    f"replaying turn {index + 1} ({turn.rendered}) no longer matches any "
                    f"candidate; the simulation has changed since it was recorded")
            replayed.append(TurnLog(action=turn.action, tokens=turn.tokens,
                                    survivors_before=before,
                                    survivors_after=len(self._session.survivors)))
        self.turns = replayed
        # A transition recorded after the last surviving turn has not happened yet.
        self.transitions = [(at, p) for at, p in self.transitions if at <= len(replayed)]
        self._apply_transitions_at(len(replayed))

    # -- read-only state ------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._session.phase

    @property
    def survivors(self) -> tuple[int, ...]:
        return self._session.survivors

    @property
    def identified(self) -> int | None:
        return self._session.identified

    def legal_actions(self) -> list[Action]:
        """Actions the player could report this turn, in slot order.

        Move slots are filtered to those with PP left in *every* surviving candidate, since PP is
        not a thing candidates can disagree about. Balls are excluded during setup (sec 2.3).
        """
        state = next(iter(self._session.states.values()))
        actions = [_MOVE_ACTIONS[slot] for slot in state.ours.usable_slots()]
        actions.extend([Action.ITEM, Action.ITEM_CURE])
        if self.phase.balls_allowed:
            actions.extend([Action.CAPTURE_BALL, Action.STANDARD_BALL])
        if self.phase is Phase.SETUP:
            actions.append(Action.SWITCH)
        return actions

    def predict(self, action: Action) -> dict[int, str]:
        return self._session.predict(action)

    def advice(self) -> list[dict]:
        """Actions ranked by how much they would narrow the set, best first (Phase 1.5).

        Empty once the seed is pinned -- there is nothing left to learn, and Phase 2 optimises
        distance instead.
        """
        if self.identified is not None:
            return []
        ranked = self._session.rank_actions(self.legal_actions())
        return [{"action": a.value, "expected_survivors": round(score, 2),
                 "groups": len(self._session.partition(a))} for a, score in ranked]

    # -- the loop -------------------------------------------------------

    def observe(self, action: Action, tokens: tuple[str, ...] | list[str]) -> dict:
        """Accept one reported turn. Returns the new snapshot.

        A contradiction does **not** advance the turn or shrink the set: it is surfaced on the
        snapshot so the player can fix a typo or widen the window, because an impossible
        observation almost always means one of those rather than a genuinely excluded set
        (sec 15.5).
        """
        problems = tok.validate_turn(list(tokens))
        if problems:
            self.contradiction = {"kind": "grammar", "problems": problems,
                                  "observed": tok.render_turn(tok.normalise(list(tokens)))}
            return self.snapshot()

        before = len(self._session.survivors)
        result = self._session.observe(action, tokens)
        if result.contradiction:
            self.contradiction = {
                "kind": "no_match",
                "observed": tok.render_turn(tok.normalise(list(tokens))),
                "predicted": _preview(result.rejected),
                "problems": [
                    "No candidate seed predicted that turn, so the set was left untouched.",
                    "Most likely: a mistyped token, or the true seed is outside the window.",
                ],
            }
            return self.snapshot()

        self.contradiction = None
        self.turns.append(TurnLog(action=action, tokens=tuple(tokens),
                                  survivors_before=before,
                                  survivors_after=len(self._session.survivors)))
        if self.phase is Phase.SOLVING:
            self.solve()
        return self.snapshot()

    def undo(self) -> dict:
        """Rewind one reported turn and re-widen the set (sec 15.4.2, the misreport case).

        A *misplay* is not undone -- the game has advanced, so there is nothing to rewind. Report
        what actually happened with :meth:`observe` and Phase 2 re-solves from there.
        """
        self.contradiction = None
        if not self.turns:
            return self.snapshot()
        self._replay(self.turns[:-1])
        if self.phase is Phase.SOLVING:
            self.solve()
        return self.snapshot()

    # -- phases ---------------------------------------------------------

    def enter_pinning(self) -> dict:
        self._session.enter_pinning()
        self.transitions.append((len(self.turns), Phase.PINNING))
        return self.snapshot()

    def solver_blockers(self) -> list[str]:
        return self._session.solver_blockers()

    def enter_solving(self) -> dict:
        self._session.enter_solving()
        self.transitions.append((len(self.turns), Phase.SOLVING))
        self.solve()
        return self.snapshot()

    def solve(self) -> Solution | Unreachable:
        """Re-solve from the current state. Called automatically every Phase 2 turn."""
        seed = self.identified
        if seed is None:
            raise ValueError("cannot solve until the seed is pinned")
        self.solution = solve(self._session.state_of(seed), self.config, self.solver_config)
        return self.solution

    # -- output ---------------------------------------------------------

    def snapshot(self) -> dict:
        """Everything the UI needs, as plain JSON-safe data.

        One method rather than several so a caller cannot render a half-updated view, and so a
        recorded snapshot is a complete regression fixture.
        """
        state = next(iter(self._session.states.values()))
        seed = self.identified
        out = {
            "phase": int(self.phase),
            "phase_label": self.phase.label,
            "balls_allowed": self.phase.balls_allowed,
            "survivors": len(self.survivors),
            "identified": None if seed is None else f"{seed:#010x}",
            "candidates": [
                {"seed": f"{s:#010x}",
                 "frame": self._session.candidate_info[s].frame,
                 "second": self._session.candidate_info[s].second}
                for s in self.survivors[:CANDIDATE_PREVIEW]
            ],
            "candidates_truncated": max(0, len(self.survivors) - CANDIDATE_PREVIEW),
            "window": {
                "frame_centre": self.window.frame_centre,
                "second_centre": self.window.second_centre,
                "frame_window": self.window.frame_window,
                "second_window": self.window.second_window,
                "size": len(self.window.candidates),
            },
            "ours": {"name": state.ours.name, "hp": state.ours.hp,
                     "max_hp": state.ours.max_hp,
                     "status": state.ours.status.value,
                     "pp": [state.ours.pp_left(i) for i in range(len(state.ours.moves))],
                     "moves": list(state.ours.moves)},
            "target": {"name": state.target.name, "hp": state.target.hp,
                       "max_hp": state.target.max_hp,
                       "status": state.target.status.value,
                       "pp": [state.target.pp_left(i) for i in range(len(state.target.moves))],
                       "moves": list(state.target.moves)},
            "capture_ball": self.capture_ball,
            "danger_floor": self.danger_floor,
            "in_danger": state.ours.hp is not None and state.ours.hp <= self.danger_floor,
            "turns": [{"n": i + 1, "action": t.action.value, "rendered": t.rendered,
                       "survivors_before": t.survivors_before,
                       "survivors_after": t.survivors_after}
                      for i, t in enumerate(self.turns)],
            "path": tok.render_path([list(t.tokens) for t in self.turns]),
            "legal_actions": [a.value for a in self.legal_actions()],
            "advice": self.advice(),
            "ambiguity": self._session.ambiguity(),
            "solver_blockers": self.solver_blockers(),
            "contradiction": self.contradiction,
            "solution": None,
        }
        if isinstance(self.solution, Solution):
            out["solution"] = {
                "found": True,
                "turns": self.solution.turns,
                "distance": self.solution.total_distance,
                "rendered": self.solution.rendered(),
                "items": self.solution.item_bill(),
                "next": {"action": self.solution.steps[0].action.value,
                         "item": self.solution.steps[0].item,
                         "expect": self.solution.steps[0].rendered},
                "steps": [{"n": i + 1, "action": s.action.value, "item": s.item,
                           "expect": s.rendered, "distance": s.distance}
                          for i, s in enumerate(self.solution.steps)],
            }
        elif isinstance(self.solution, Unreachable):
            out["solution"] = {
                "found": False,
                "reason": self.solution.reason,
                "proven": self.solution.proven,
                # Targets, not reachable ones -- see Unreachable's docstring.
                "capture_windows": self.solution.capture_windows,
                "searched_turns": self.solution.searched_turns,
            }
        return out


def _preview(predictions: dict[int, str], limit: int = 6) -> list[dict]:
    """A few of what candidates predicted, for explaining a contradiction."""
    return [{"seed": f"{s:#010x}", "predicted": p}
            for s, p in list(predictions.items())[:limit]]
