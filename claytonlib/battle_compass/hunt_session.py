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

from dataclasses import dataclass, replace

from claytonlib.battle.damage import Attacker, Defender, damage_range, unsupported_reason
from claytonlib.battle_compass import tokens as tok
from claytonlib.battle_compass import items
from claytonlib.battle_compass.candidates import CandidateWindow
from claytonlib.battle_compass.identify import Phase, Session
from claytonlib.battle_compass.sim import HuntConfig, can_flinch, effective_speed
from claytonlib.battle_compass.solver import Solution, SolverConfig, Unreachable, solve
from claytonlib.battle_compass.state import Action, Battler, Status
from claytonlib.moves import CATEGORY_STATUS, resolve_move

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


#: Status -> the marker that prevents a move because of it.
_PREVENTED_BY_STATUS = {Status.PARALYSIS: "par", Status.SLEEP: "slp", Status.FREEZE: "frz"}


def prevention_options(actor: Battler, other: Battler, *, actor_moves_first: bool) -> list[dict]:
    """What could legitimately have stopped `actor` from moving THIS turn.

    Derived from state rather than offered as a fixed menu. An unparalyzed Magneton cannot be
    fully paralyzed, and nothing in Suicune's moveset can make it flinch, so offering either as a
    possible outcome invites a report that no candidate could ever have predicted -- which looks
    exactly like a wrong model constant.

    Flinching needs the *other* side to move first, since a flinch is inflicted by a hit that has
    already landed.
    """
    options: list[dict] = []
    marker = _PREVENTED_BY_STATUS.get(actor.status)
    if marker:
        options.append({"code": marker, "label": {
            "par": "was fully paralyzed", "slp": "is asleep",
            "frz": "is frozen solid"}[marker]})
    if actor.confused:
        options.append({"code": "cfz", "label": "hurt itself in confusion"})
    if not actor_moves_first and can_flinch(other):
        options.append({"code": "fln", "label": "flinched"})
    return options


def resolution_options(actor: Battler) -> list[dict]:
    """Status changes that let the move through and so must be reported explicitly.

    Only confusion: for sleep and freeze the move happening at all proves the status ended, but a
    confused Pokemon can attack perfectly normally (sec 13.4).
    """
    if actor.confused:
        return [{"code": "scfz", "label": "snapped out of confusion"}]
    return []


def move_info(battler: Battler) -> list[dict]:
    """Per slot: what the UI must know to ask the right questions about this move.

    A damaging move renders a hit marker (``h``/``!``); a status move that lands renders the bare
    slot, so asking "did it crit?" about Mean Look would be nonsense. A move with accuracy 0
    cannot miss, so offering "missed" would be wrong too. Deriving this here rather than in the
    page keeps one source of truth for it.
    """
    out: list[dict] = []
    for slot in range(len(battler.moves)):
        move = battler.move(slot)
        if move is None:
            out.append({"slot": slot, "name": "", "known": False, "damaging": False,
                        "can_miss": False, "has_secondary": False, "effect_chance": 0,
                        "priority": 0, "pp": 0})
            continue
        out.append({
            "slot": slot,
            "name": move.name,
            "known": True,
            "damaging": move.category != CATEGORY_STATUS,
            "can_miss": move.accuracy > 0,
            # A secondary effect is observable ("Smeargle's Attack fell!") and renders its own
            # `~` token, so the interview has to ask about it or such a turn is unreportable.
            "has_secondary": move.effect_chance > 0,
            "effect_chance": move.effect_chance,
            #: Priority decides turn order before Speed does, so the page needs it to know
            #: which side's tokens come first.
            "priority": move.priority,
            "pp": battler.pp_left(slot),
        })
    return out


@dataclass
class TurnLog:
    """One accepted turn, kept for display and for replay-based undo."""
    action: Action
    tokens: tuple[str, ...]
    survivors_before: int
    survivors_after: int
    #: Which item, or which bench slot -- part of the action, so replay needs them.
    item_code: str | None = None
    bench_slot: int | None = None

    @property
    def extra(self) -> dict:
        out = {}
        if self.item_code is not None:
            out["item_code"] = self.item_code
        if self.bench_slot is not None:
            out["bench_slot"] = self.bench_slot
        return out

    @property
    def rendered(self) -> str:
        return tok.render_turn(tok.normalise(self.tokens))


class HuntSession:
    """A run in progress: candidates, phase, history, and the current solver advice."""

    def __init__(self, window: CandidateWindow, ours: Battler, target: Battler,
                 config: HuntConfig, *, solver_config: SolverConfig | None = None,
                 capture_ball: str = "", bench: tuple[Battler, ...] = ()):
        if not window.candidates:
            raise ValueError("no candidate seeds: widen the window or check the seed targeting")
        self.window = window
        self.ours = ours
        self.bench = tuple(bench)
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
        session = Session(list(self.window.candidates), self.ours, self.target, self.config,
                          phase=Phase.SETUP)
        if self.bench:
            session.states = {seed: replace(state, bench=self.bench)
                              for seed, state in session.states.items()}
        return session

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
            result = self._session.observe(turn.action, turn.tokens, **turn.extra)
            if result.contradiction:
                # Only reachable if the model changed under us; a turn that was accepted once
                # must be accepted again. Stop rather than silently dropping it.
                raise ValueError(
                    f"replaying turn {index + 1} ({turn.rendered}) no longer matches any "
                    f"candidate; the simulation has changed since it was recorded")
            replayed.append(TurnLog(action=turn.action, tokens=turn.tokens,
                                    survivors_before=before,
                                    survivors_after=len(self._session.survivors),
                                    item_code=turn.item_code, bench_slot=turn.bench_slot))
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
        if self.phase is Phase.SETUP and state.bench:
            actions.append(Action.SWITCH)
        return actions

    def predict(self, action: Action, **extra) -> dict[int, str]:
        return self._session.predict(action, **extra)

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

    def observe(self, action: Action, tokens: tuple[str, ...] | list[str],
                item_code: str | None = None, bench_slot: int | None = None) -> dict:
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

        extra = {}
        if item_code is not None:
            extra["item_code"] = item_code
        if bench_slot is not None:
            extra["bench_slot"] = bench_slot
        before = len(self._session.survivors)
        result = self._session.observe(action, tokens, **extra)
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
                                  survivors_after=len(self._session.survivors),
                                  item_code=item_code, bench_slot=bench_slot))
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

    def snapshot(self, *, include_advice: bool = False) -> dict:
        """Everything the UI needs, as plain JSON-safe data.

        One method rather than several so a caller cannot render a half-updated view, and so a
        recorded snapshot is a complete regression fixture.

        `include_advice` is off by default because ranking actions simulates every candidate
        against every action -- 8s at 6,000 candidates, and the *only* slow part of a snapshot.
        The page renders without it and fetches it separately, so a turn is never waiting on
        advice the player may not read.
        """
        state = next(iter(self._session.states.values()))
        we_first = effective_speed(state.ours) > effective_speed(state.target)
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
            # Who acts first when we use a MOVE. A bag action or switch always resolves before
            # any move, so the page ignores this for those (sec 12.1).
            "we_move_first": we_first,
            "prevention": {
                "ours": prevention_options(state.ours, state.target,
                                           actor_moves_first=we_first),
                "target": prevention_options(state.target, state.ours,
                                             actor_moves_first=not we_first),
            },
            "resolution": {
                "ours": resolution_options(state.ours),
                "target": resolution_options(state.target),
            },
            "ours": {"name": state.ours.name, "hp": state.ours.hp,
                     "max_hp": state.ours.max_hp,
                     "status": state.ours.status.value,
                     "confused": state.ours.confused,
                     "effective_speed": effective_speed(state.ours),
                     "pp": [state.ours.pp_left(i) for i in range(len(state.ours.moves))],
                     "moves": list(state.ours.moves),
                     "move_info": move_info(state.ours)},
            "target": {"name": state.target.name, "hp": state.target.hp,
                       "max_hp": state.target.max_hp,
                       "status": state.target.status.value,
                       "confused": state.target.confused,
                       "effective_speed": effective_speed(state.target),
                       "pp": [state.target.pp_left(i) for i in range(len(state.target.moves))],
                       "moves": list(state.target.moves),
                       "move_info": move_info(state.target)},
            "bench": [{"slot": i, "name": b.name,
                       "hp": b.hp, "max_hp": b.max_hp,
                       "status": b.status.value,
                       "moves": list(b.moves)}
                      for i, b in enumerate(state.bench)],
            "items": [{"code": i.code, "name": i.name, "price": i.price,
                       "heals": i.heals, "cures_status": i.cures_status,
                       "heal": i.heal}
                      for i in items.ITEMS],
            "capture_ball": self.capture_ball,
            "danger_floor": self.danger_floor,
            "in_danger": state.ours.hp is not None and state.ours.hp <= self.danger_floor,
            "turns": [{"n": i + 1, "action": t.action.value, "rendered": t.rendered,
                       "survivors_before": t.survivors_before,
                       "survivors_after": t.survivors_after}
                      for i, t in enumerate(self.turns)],
            "path": tok.render_path([list(t.tokens) for t in self.turns]),
            "legal_actions": [a.value for a in self.legal_actions()],
            "advice": self.advice() if include_advice else None,
            # True when advice exists to be fetched but was not computed here.
            "advice_pending": not include_advice and self.identified is None,
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
